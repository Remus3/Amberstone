"""Loadout + LCU command POST routes.

Slice 2C-7d (2026-05-01): final POST sub-slice. Handlers carved out
of `web_dashboard._Handler.do_POST`. All three reach the in-process
vision server at 127.0.0.1:8889 (which proxies to the Legion LCU agent),
so they share the `_VISION_TOKEN` auth header.

`_VISION_TOKEN` is deferred-imported from `web_dashboard` inside each
handler - same pattern as `routes_diag` - to avoid a circular import
at module load time (web_dashboard imports the dashboard package
during start-up).

TRUST BOUNDARY (lane 8 cycle 38, 2026-08-31)
    This module's prose used to say "the vision server also revalidates".
    That is MEASURED FALSE and the wrong component was named:
    `vision_server/_http.py:213` routes /lcu-cmd straight into
    `vision_server/_relay.lcu_queue_command`, which appends the decoded
    dict to the pending queue VERBATIM - there is no allowlist anywhere in
    `vision_server/`. The vision server is a PIPE, not a gate.

    The second gate is one hop further on, in `tools/lcu_agent.py`: it
    name-dispatches at `:422`, answers an unrecognised verb with
    "unknown cmd" at `:1102`, coerces every field it reads (`int()` /
    `str()`, e.g. `:657`), and catches per command at `:1693-1696`. So
    this edge is NOT the only defence - but it is the only one before the
    command is queued, and the agent's coercion is incidental to its
    implementation rather than a declared contract.

    What this edge checks today is the `cmd` VERB only; every sibling key
    is forwarded unexamined. Per-command payload schemas are filed as
    RM-296 rather than guessed at here - each of the 28 verbs has its own
    shape and a wrong guess breaks champ-select silently.
"""
import json
import logging
import urllib.error
import urllib.request
from urllib.parse import parse_qs, quote, urlparse

from dashboard._dispatch import equals, prefix

log = logging.getLogger("rc.web_dashboard")

# Raw exception text can leak file paths - log it, never render it
# (same policy as dashboard/_handler.do_POST; audit cycle 8 slice E).
_GENERIC_ERR = "internal error - see logs"

# Summoner-spell ids are small positive ints (Riot's live set tops out in
# the low hundreds; Arena's pair sits near 2200). The bound exists to reject
# obvious junk - a negative id, a 10-digit id - not to enumerate Riot's set,
# which changes per patch and is not this module's to pin.
_SUMMONER_ID_MAX = 9999


# Allowlist for /api/lcu-cmd. Hoisted out of the legacy handler body
# so it's allocated once at import, not per-request. See TRUST BOUNDARY
# in the module docstring: nothing downstream re-checks this, so a verb
# that reaches the queue reaches the League client.
_LCU_ALLOWED_CMDS = {
    "accept_ready", "set_config", "bench_swap",
    "set_summoners", "lock_pick", "reroll",
    "apply_runes", "apply_item_set",
    # 2026-05-23 (item 164): plural-form batch push so all 4 build
    # variants + the build-order set go to LCU in one PUT. Each entry
    # replaces by-uid (does NOT wipe other RC- sets). Used by the
    # champ-select Apply flow + the active-match phase=InProgress
    # trigger so the in-game item-shop dropdown always carries RC's
    # current curated builds.
    "apply_item_sets_batch",
    # 2026-05-25 (item 188 Slice B): wipe stale RC- item-sets that
    # don't match the current {champion, mode}. Operator-reported the
    # in-game item-shop dropdown was showing 20+ stale RC- sets after
    # a session of switching champions + modes (4 paths * 3 modes per
    # champion * 2-3 champions). Wired as PRE-PUSH step in
    # _csvMaybePushBuildsToLCU so the dropdown only carries the
    # current scope's sets. Preserves operator's own custom (non-RC-)
    # sets + the current-champion-current-mode-* RC- sets.
    "delete_stale_rc_item_sets",
    # 2026-05-23 (item 164): summoner-spell strip click pushes via the
    # existing set_summoners agent route - allowlist surfaces it for
    # the new click handler in champ_select.js.
    "set_summoner_spell",
    "trade_request", "accept_trade", "decline_trade",
    # Lobby actions (2026-04-26): start/cancel matchmaking from the
    # dashboard's Find Match button + change queue type from the
    # lobby dropdown. LCU restricts these to the lobby leader; the UI
    # gates the controls on lobby.is_leader before sending.
    "start_matchmaking", "cancel_matchmaking",
    "change_queue_type",
    # Phase B champ-select commands (s166): hover intents + lane / pick
    # order swaps + Arena augment selection. Wired in
    # ``tools/lcu_agent.py`` (set_*_intent at L908, *_swap at
    # L932/L961, set_augment_intent at L988) but historically missing
    # here, so every click on a P&B recommendation card or swap chip in
    # the new champ-select view was rejected with 400 at the dashboard
    # edge and never reached the LCU.
    "set_pick_intent", "set_ban_intent",
    "request_position_swap", "request_pick_order_swap",
    "set_augment_intent",
    # s171: pre-game lobby controls - lane prefs, party visibility,
    # invitations, Practice Tool. Mirrors the Phase A "visual-only"
    # toggles in the lobby view that previously never propagated to
    # the League client.
    "lobby.set_position_prefs", "lobby.set_party_type",
    "lobby.invite_player", "lobby.create_practice_tool",
    "lobby.promote_leader", "lobby.kick_member",
}


def _text(payload, key: str, default: str = "") -> str:
    """Read a string field WITHOUT assuming the client sent a string.

    Lane 8 cycle 38: every handler here did `(payload.get(k) or "").strip()`.
    `payload` is guaranteed a dict by `_handler.do_POST` (LEDGER 1181), but
    its VALUES are not guaranteed anything, and `.strip()` on a truthy
    non-str raises AttributeError. A non-str is a client error, so it
    collapses to the same empty string the missing-key case produces and
    the handler's own "required" branch answers it with a 400.
    """
    val = payload.get(key)
    if not isinstance(val, str):
        return default
    return val.strip() or default


def _coerce_override_summoners(value) -> tuple | None:
    """Validate `override_summoners` into a real (d, f) int pair, or None.

    The old guard was `isinstance(x, int) for x in pair`, and in Python
    `isinstance(True, int)` is True - so `[true, false]` passed. It then
    took two different routes: the user-build path ran `int(pair[0])`
    (turning it into 1/0), while the resolver path assigned the value
    straight into the outbound LCU command, so a JSON boolean was forwarded
    to the League client. Two paths, same input, different wire bytes.

    Bools are rejected outright rather than coerced: a client that sends
    `true` for a spell id is malfunctioning, and silently reading it as
    spell id 1 (Cleanse) would push a wrong summoner rather than report.
    """
    if isinstance(value, bool) or not isinstance(value, (list, tuple)):
        return None
    if len(value) != 2:
        return None
    out = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int):
            return None
        if not (0 < item <= _SUMMONER_ID_MAX):
            return None
        out.append(item)
    return (out[0], out[1])


# RM-296d: `/api/loadout/apply` read its three push_* flags with
# `payload.get(k, True)` and consumed them as BARE TRUTHINESS. A JSON body
# {"push_runes": "false"} yields the non-empty string "false", which is
# truthy, so the route pushed the runes anyway - overwriting the operator's
# live rune page with the one thing the body had just asked it not to touch.
# "0", "no" and "off" all failed the same way.
_PUSH_FLAG_FALSE = frozenset({"false", "0", "no", "off", "n", ""})
_PUSH_FLAG_TRUE = frozenset({"true", "1", "yes", "on", "y"})


def _coerce_push_flag(payload, key: str):
    """Read one push_* flag. Returns True, False, or None for AMBIGUOUS.

    Contract (RM-296d):
      key ABSENT      -> True. Push-everything is the live default and this
                         route's own body comment declares it, so only an
                         EXPLICITLY supplied falsey value may turn a push off.
      real JSON bool  -> used as-is.
      string          -> stripped + lowercased, looked up in the two tables
                         above.
      int / float     -> 0 is off, 1 is on.
      anything else   -> None, i.e. AMBIGUOUS.

    `None` is the caller's cue to answer 400. It is NOT "fall back to the
    default": a value the server cannot read is not consent to overwrite a
    rune page, and a silent default is wrong in whichever direction it goes.
    Defaulting ambiguity to True is the original defect. Defaulting it to
    False is a quiet failure of the operator's intent behind a green
    "check <label>" - `web/js/panels/item_build.js:445` already reads `ok`,
    so there is a live UI channel for an honest error but none for a silent
    skip. Rejecting is the resolution the sibling `dismiss` flag took at
    `routes_diag.py:347-350` for the same wrong-type class, on the same
    reasoning that the downstream act is irreversible.

    A JSON `null` is deliberately ambiguous rather than absent: a client that
    computed `null` had an opinion and failed to express it, which is a
    different statement from never mentioning the key. Hence the test is
    `key not in payload`, not the value's own truthiness.
    """
    if key not in payload:
        return True
    raw = payload[key]
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        token = raw.strip().lower()
        if token in _PUSH_FLAG_FALSE:
            return False
        if token in _PUSH_FLAG_TRUE:
            return True
        return None
    if isinstance(raw, (int, float)):
        if raw == 0:
            return False
        if raw == 1:
            return True
    return None


def _post_lcu_cmd(cmd_obj: dict) -> bytes:
    """POST one command to the vision server's LCU queue; return its body.

    Extracted as a seam so the enqueue path can be exercised without a
    live :8889. Raises on any transport failure - callers decide whether
    that is fatal, which is the point: the previous inline version
    swallowed the exception where the caller could not see it.
    """
    from web_dashboard import _VISION_TOKEN
    req = urllib.request.Request(
        "http://127.0.0.1:8889/lcu-cmd",
        data=json.dumps(cmd_obj).encode(),
        method="POST",
        headers={"X-RC-Token": _VISION_TOKEN,
                 "Content-Type": "application/json"},
    )
    with _urlopen(req, timeout=2) as r:
        return r.read()


def _urlopen(req, timeout=None):
    """Indirection seam over urllib.request.urlopen so tests can inject
    transport failures without monkeypatching the stdlib globally."""
    return urllib.request.urlopen(req, timeout=timeout)


def _serve_loadout_list_post(h, payload) -> None:
    # GET-style query in POST body for symmetry: {champion, mode}.
    # Returns [{key, label, is_default}, ...] for variants visible
    # in this mode for this champion.
    try:
        from coaches.loadout_resolver import list_variants, default_variant
        champ = _text(payload, "champion")
        mode  = _text(payload, "mode", "sr")
        if not champ:
            h._send(400, b'{"error":"champion required"}', "application/json"); return
        vs = list_variants(champ, mode)
        df = default_variant(champ, mode)
        # 2026-05-28: merge operator user-curated builds (sr_user_builds)
        # into the chooser for EVERY champ-select mode (operator
        # directive). The store is SR-authored today but a saved build is
        # selectable whether the live game is SR / ARAM / Arena. Keys are
        # namespaced "userbuild_<id>" (colon-free so the item-178
        # "<variant>:<path>" savedChoice split does not mis-parse them) so
        # /api/loadout/apply routes them to _resolve_user_build instead of
        # champion_loadouts.json. Appended AFTER the curated rows so the
        # engine defaults stay the operator's eye-line; user builds sit
        # below. (item 213: the synthetic experimental row was removed.)
        try:
            from coaches.sr_user_builds import (
                format_for_display as _ub_fmt,
                list_for as _ub_list,
            )
            for rec in _ub_list(champ):
                shaped = _ub_fmt(rec)
                if not shaped:
                    continue
                ub_runes = shaped.get("runes") or {}
                vs.append({
                    "key":         "userbuild_" + (shaped.get("key") or ""),
                    "label":       shaped.get("label") or "user build",
                    "is_default":  False,
                    "is_user":     True,
                    "keystone":    shaped.get("keystone") or "",
                    "primary":     ub_runes.get("primary") or "",
                    "secondary":   ub_runes.get("secondary") or "",
                    "summoners":   shaped.get("summoner_spells") or [],
                    "item_names":  shaped.get("build_path") or [],
                    "item_ids":    shaped.get("item_ids") or [],
                    "build_paths": [],
                    "_collapsed":  False,
                })
        except Exception as exc:  # noqa: BLE001
            log.warning("loadout/list user-build merge: %s", exc)
        h._send(200, json.dumps({
            "champion": champ, "mode": mode,
            "variants": vs, "default": df,
        }).encode(), "application/json")
    except Exception as exc:  # noqa: BLE001
        log.warning("api/loadout/list: %s", exc)
        h._send(500, json.dumps({"error": _GENERIC_ERR}).encode(), "application/json")


def _serve_rune_pages_post(h, payload) -> None:
    # {champion, mode} -> the deduped rune-page model for rune-follows-build
    # (item 1 Phase 1). Mirrors _serve_loadout_list_post: mode defaults to
    # "sr", champion is required, and enumerate_pages(champ, mode) is spliced
    # back with the echoed champion + mode. coaches.rune_pages only IMPORTS
    # build_perk_ids - it writes nothing. (Neither module is frozen; the
    # "frozen build_perk_ids" claim here was wrong, corrected lane 8 cycle 39.)
    try:
        from coaches.rune_pages import enumerate_pages
        champ = _text(payload, "champion")
        mode  = _text(payload, "mode", "sr")
        if not champ:
            h._send(400, b'{"error":"champion required"}', "application/json"); return
        h._send(200, json.dumps({
            "champion": champ, "mode": mode,
            **enumerate_pages(champ, mode),
        }).encode(), "application/json")
    except Exception as exc:  # noqa: BLE001
        log.warning("api/loadout/rune-pages: %s", exc)
        h._send(500, json.dumps({"error": _GENERIC_ERR}).encode(), "application/json")


# item 213 (2026-05-28): the synthetic auto-build chooser row was
# removed from the champ-select frontend (all champs + all modes). Its
# inline override-package builder + the dedicated "RC ..." page-name
# path are gone with it. The apply route now routes only userbuild_* +
# the variant resolver. The DS-vs-enemy-comp save+push uses the standard
# apply_item_sets_batch contract from the frontend (no bespoke backend
# resolver needed).


# 2026-05-28: operator user-curated builds (coaches/sr_user_builds) are
# merged into /api/loadout/list across ALL champ-select modes and applied
# here. The variant key is "userbuild_<8hex>"; we look the record up,
# shape it via format_for_display (resolves item display names -> ddragon
# ids), and build the same rune_cmd / item_cmd / summ_cmd trio resolve()
# produces so the existing enqueue loop is unchanged. override_summ (from
# the champ-select adaptive-summoners pipeline) wins over the build's
# stored pair when present.
def _resolve_user_build(champion: str, variant: str, mode: str,
                        override_summ: list | None) -> dict:
    from coaches.loadout_resolver import (
        _load_champ_id_by_name, _norm, _normalize_mode,
    )
    from coaches.sr_user_builds import format_for_display, list_for
    from lcu.lcu_rune_writer import build_perk_ids, resolve_tree_ids
    uid = variant[len("userbuild_"):]
    rec = next((b for b in list_for(champion)
                if isinstance(b, dict) and b.get("id") == uid), None)
    if not rec:
        return {"ok": False, "err": f"no user build {uid!r} for {champion!r}"}
    shaped = format_for_display(rec)
    if not shaped:
        return {"ok": False, "err": f"user build {uid!r} malformed"}
    mode_key  = _normalize_mode(mode)
    label     = shaped.get("label") or "user build"
    runes     = shaped.get("runes") or {}
    keystone  = str(runes.get("keystone") or "")
    primary   = str(runes.get("primary") or "")
    secondary = str(runes.get("secondary") or "")
    rune_cmd = None
    if keystone and primary and secondary:
        perk_ids   = build_perk_ids(
            keystone, primary, secondary, mode_key == "aram",
            minor_primary=[str(x) for x in (runes.get("minor_primary") or []) if x],
            minor_secondary=[str(x) for x in (runes.get("minor_secondary") or []) if x],
        )
        # Lane 8 cycle 39: user-curated builds can name the same tree twice.
        primary_id, sub_id = resolve_tree_ids(primary, secondary)
        if perk_ids and primary_id and sub_id:
            rune_cmd = {
                "cmd":        "apply_runes",
                "page_name":  f"RC: {champion} {label} ({mode_key.upper()})"[:75],
                "primary_id": primary_id,
                "sub_id":     sub_id,
                "perk_ids":   perk_ids,
            }
    item_ids = [str(x) for x in (shaped.get("item_ids") or []) if x]
    item_cmd = None
    if item_ids:
        champ_id = _load_champ_id_by_name().get(champion, 0)
        item_cmd = {
            "cmd":         "apply_item_set",
            "set_uid":     f"RC-{_norm(champion)}-{mode_key}-ub-{uid}",
            "title":       f"RC: {champion} {label} ({mode_key.upper()})"[:50],
            "champion_id": champ_id,
            "blocks": [{
                "type":  "User Build (RC)",
                "items": [{"id": i, "count": 1} for i in item_ids],
            }],
        }
    spells = shaped.get("summoner_spells") or []
    pair = (override_summ if (isinstance(override_summ, list)
                              and len(override_summ) == 2) else spells)
    summ_cmd = None
    if isinstance(pair, list) and len(pair) >= 2:
        try:
            summ_cmd = {"cmd": "set_summoners",
                        "d": int(pair[0]), "f": int(pair[1])}
        except (ValueError, TypeError):
            pass
    return {
        "ok":        True,
        "champion":  champion,
        "variant":   variant,
        "mode":      mode_key,
        "label":     label,
        "rune_cmd":  rune_cmd,
        "item_cmd":  item_cmd,
        "summ_cmd":  summ_cmd,
        "raw_items": list(shaped.get("build_path") or []),
    }


def _resolve_variant(champ: str, variant: str, mode: str,
                     override_summ) -> dict:
    """Route a variant key to its resolver and apply the summoner override.

    Extracted from `_serve_loadout_apply_post` so the enqueue/report logic
    can be tested without `coaches.loadout_resolver` on the path. Behaviour
    is unchanged: "userbuild_" keys go to `_resolve_user_build` (which
    applies the override itself), everything else to `resolve()` with the
    override rewritten onto summ_cmd afterwards so the rune + item commands
    still come from the variant.
    """
    if variant.startswith("userbuild_"):
        return _resolve_user_build(champ, variant, mode,
                                   list(override_summ) if override_summ else None)
    from coaches.loadout_resolver import resolve
    resolved = resolve(champ, variant, mode)
    if not resolved.get("ok"):
        return resolved
    if override_summ and resolved.get("summ_cmd"):
        sc = dict(resolved["summ_cmd"])
        sc["d"] = override_summ[0]
        sc["f"] = override_summ[1]
        resolved["summ_cmd"] = sc
    return resolved


def _serve_loadout_apply_post(h, payload) -> None:
    # Body: {champion, variant, mode, push_runes?, push_items?, push_summoners?,
    #        override_runes?:{keystone,primary,secondary},
    #        override_items?:[id1,...],
    #        override_summoners?:[d,f]}.
    # Defaults: push everything that the variant declares. Only an
    # EXPLICITLY supplied falsey push_* value turns a push off; an omitted
    # key keeps the push-everything default, and a value that cannot be
    # read as a boolean is answered 400 rather than guessed at
    # (RM-296d, `_coerce_push_flag`).
    # Resolves the variant to LCU command payloads and queues them
    # one-by-one through the vision server's LCU endpoint. Returns
    # immediately; results come back via the LCU command queue
    # (best-effort).
    try:
        champ   = _text(payload, "champion")
        variant = _text(payload, "variant")
        mode    = _text(payload, "mode", "sr")
        # RM-296d: coerced, never bare-truthy. See `_coerce_push_flag` for
        # the contract. A None here means the value was AMBIGUOUS; it is
        # reported below, AFTER the champion+variant check, so that error's
        # existing precedence is unchanged.
        push_runes = _coerce_push_flag(payload, "push_runes")
        push_items = _coerce_push_flag(payload, "push_items")
        push_summ  = _coerce_push_flag(payload, "push_summoners")
        bad_flag = next(
            (name for name, val in (("push_runes", push_runes),
                                    ("push_items", push_items),
                                    ("push_summoners", push_summ))
             if val is None), None)
        # s209: optional override of the variant's stored summoners.
        # Used by the champ-select build chooser's adaptive-summoners
        # pipeline - when enemy comp pressures a different second spell
        # (Cleanse vs CC / Barrier vs burst) the JS sends the swapped
        # pair as [d_id, f_id]. Falls through to the variant's stored
        # summoners when omitted or malformed.
        override_summ = _coerce_override_summoners(
            payload.get("override_summoners"))
        # item 213 (2026-05-28): the experimental override_runes +
        # override_items inline-build path was removed with the
        # experimental chooser row. The apply route now routes only
        # userbuild_* + the variant resolver.
        if not champ or not variant:
            h._send(400, b'{"error":"champion+variant required"}', "application/json"); return
        if bad_flag:
            h._send(400, json.dumps({"error": "bad_push_flag",
                                     "field": bad_flag}).encode(),
                    "application/json"); return
        # 2026-05-28: operator user-curated build. Namespaced
        # "userbuild_<id>" by /api/loadout/list; routed here BEFORE the
        # experimental + resolver paths so the colon-free key never
        # reaches resolve()'s "<variant>:<path>" partition logic.
        resolved = _resolve_variant(champ, variant, mode, override_summ)
        if not resolved.get("ok"):
            h._send(404, json.dumps(resolved).encode(), "application/json"); return
        queued = []
        failed = []
        def _enqueue(cmd_obj):
            if not cmd_obj: return
            try:
                _post_lcu_cmd(cmd_obj)
                queued.append(cmd_obj.get("cmd"))
            except Exception as exc:  # noqa: BLE001
                # Still non-fatal per command - one dead push must not abort
                # the other two - but it is now REPORTED. See the `ok` note
                # below for why swallowing it silently was the real defect.
                failed.append(cmd_obj.get("cmd"))
                log.warning("loadout enqueue %s: %s",
                            cmd_obj.get("cmd"), exc)
        if push_runes: _enqueue(resolved.get("rune_cmd"))
        if push_items: _enqueue(resolved.get("item_cmd"))
        if push_summ:  _enqueue(resolved.get("summ_cmd"))
        # Pull item IDs back out of item_cmd.blocks for UI rendering
        # (frontend needs IDs to load /data/ddragon/<v>/img/item/<id>.png).
        item_ids = []
        if resolved.get("item_cmd"):
            for blk in resolved["item_cmd"].get("blocks", []):
                for it in blk.get("items", []):
                    iid = it.get("id")
                    if iid: item_ids.append(str(iid))
        # Lane 8 cycle 38: `ok` was hardcoded True, so a run in which every
        # enqueue raised still answered {"ok": true} with an empty `queued`.
        # That is not a cosmetic inaccuracy - `web/js/panels/item_build.js:445`
        # ALREADY reads this field (`if (!data || !data.ok) _ibSetStatus(
        # "push failed", "err")`), so the operator was shown a green
        # "check <label>" for a push that never reached the League client, and
        # the panel's own failure branch could never fire. Reporting honestly
        # activates UI that was written for it and has been dead since.
        # `failed` is additive; `champ_select.js:3366` ignores the body.
        h._send(200, json.dumps({
            "ok": not failed,
            "champion": champ, "variant": variant, "mode": resolved.get("mode"),
            "label":    resolved.get("label"),
            "queued":   queued,
            "failed":   failed,
            "raw_items": resolved.get("raw_items", []),
            "item_ids":  item_ids,
        }).encode(), "application/json")
    except Exception as exc:  # noqa: BLE001
        log.warning("api/loadout/apply: %s", exc)
        h._send(500, json.dumps({"error": _GENERIC_ERR}).encode(), "application/json")


def _serve_lcu_cmd_post(h, payload) -> None:
    # Forward command to vision server's LCU queue.
    # Body: {cmd: "accept_ready"} or {cmd:"set_config", auto_accept:true}
    # Validate at the dashboard edge so a malformed body never reaches
    # the Legion LCU agent.
    # Lane 8 cycle 38: this block used to read
    #     cmd_name = (payload.get("cmd") or "").strip()
    # and sat OUTSIDE the try below. `payload` is a guaranteed dict
    # (LEDGER 1181) but its VALUES are not, and .strip() on a truthy
    # non-str raises AttributeError - which nothing catches, because
    # `_handler.do_POST` wraps `_dispatch.dispatch_post` in no try at all.
    # MEASURED LIVE 2026-08-31 against pid 47076 on the LAN-reachable
    # :8888: {"cmd":123}, {"cmd":{"a":1}} and {"cmd":true} each returned
    # curl exit 56 - the connection closed with NO HTTP RESPONSE - while
    # {"cmd":"bogus_cmd"} correctly returned 400. The three failures left
    # NO log line either (the 400 is logged at _handler.py:157; they die
    # before that), and the traceback goes to stderr, which under
    # pythonw.exe is nowhere. Invisible on the wire and in the log at once.
    cmd_name = _text(payload, "cmd")
    if cmd_name not in _LCU_ALLOWED_CMDS:
        h._send(400,
            json.dumps({"error": "unknown_lcu_cmd",
                        "cmd": cmd_name,
                        "allowed": sorted(_LCU_ALLOWED_CMDS)}).encode(),
            "application/json")
        return
    try:
        from web_dashboard import _VISION_TOKEN
        # Lane 8 cycle 38: the edge validated the STRIPPED name and then
        # forwarded the payload UNSTRIPPED, so `{"cmd":" accept_ready "}`
        # passed here and reached `lcu_agent.py:422`, whose `name ==
        # "accept_ready"` is False - the agent answered "unknown cmd" while
        # this route had already reported acceptance. Forward the same
        # bytes that were validated.
        forwarded = dict(payload, cmd=cmd_name)
        req = urllib.request.Request(
            "http://127.0.0.1:8889/lcu-cmd",
            data=json.dumps(forwarded).encode(),
            method="POST",
            headers={"X-RC-Token": _VISION_TOKEN,
                     "Content-Type": "application/json"},
        )
        with _urlopen(req, timeout=2) as r:
            body = r.read()
        h._send(200, body, "application/json")
    except Exception as exc:  # noqa: BLE001
        log.warning("api/lcu-cmd: %s", exc)
        h._send(500, json.dumps({"error": _GENERIC_ERR}).encode(), "application/json")


def _scrub_result_err(body: bytes) -> bytes:
    """Replace a raw exception string in an LCU result with a friendly one.

    Lane 8 cycle 38. CLAUDE.md "Error Handling" is absolute: never surface a
    raw error string on a user-facing surface; log it and render a friendly
    degraded message. This route breached it on the 200 path, not the error
    path (the 404/500 bodies were already generic - that half of the finding
    was refuted). The chain is real and ends in champ select:

        tools/lcu_agent.py:1694   result = {"ok": False,
                                            "err": f"{type(exc).__name__}: {exc}"}
        vision_server/_http.py:148 self._j(200, rec)         # verbatim
        this route                 forwarded the body verbatim
        web/js/panels/champ_select.js:1330-1331
                                   "X Lock failed: " + err   # rendered

    So a `PermissionError: [WinError 5] ...` from inside the LCU agent was
    painted into the champ-select lock button. The raw text is logged here
    and the client is given an actionable degraded line instead. `ok` and
    every other field are passed through untouched, so the UI's existing
    success/failure branch is unchanged.

    Fail-soft by construction: a body that is not the expected JSON object
    is returned exactly as received, because this is a pass-through and
    inventing a shape would be worse than forwarding an unexpected one.
    """
    try:
        parsed = json.loads(body)
    except (ValueError, TypeError):
        return body
    if not isinstance(parsed, dict):
        return body
    result = parsed.get("result")
    target = result if isinstance(result, dict) else parsed
    err = target.get("err")
    if not isinstance(err, str) or not err:
        return body
    log.warning("lcu cmd result err (raw, not rendered): %s", err)
    target["err"] = "command failed - see logs"
    return json.dumps(parsed).encode()


def _serve_lcu_cmd_result_get(h) -> None:
    # Pulls the stored result for a previously-queued LCU command so the
    # UI can surface errors (e.g. start_matchmaking returning 400 from a
    # non-leader). Vision server returns 404 while pending; client polls.
    try:
        from web_dashboard import _VISION_TOKEN
        qs = parse_qs(urlparse(h.path).query)
        rid = (qs.get("id") or [""])[0]
        if not rid:
            h._send(400, b'{"error":"id required"}', "application/json"); return
        # parse_qs already DECODED rid - re-encode it so a value with
        # spaces / & / = cannot smuggle params into (or break) the
        # outbound vision-server URL (audit cycle 8 slice E).
        req = urllib.request.Request(
            f"http://127.0.0.1:8889/lcu-cmd-result?id={quote(rid, safe='')}",
            headers={"X-RC-Token": _VISION_TOKEN},
        )
        try:
            with _urlopen(req, timeout=2) as r:
                h._send(200, _scrub_result_err(r.read()), "application/json")
        except urllib.error.HTTPError as e:
            # Lane 8 cycle 38: `e` was read and dropped, which this audit
            # first filed as a socket leak on the hot polled path. THAT WAS
            # REFUTED by the adversarial pass and the claim is corrected
            # here rather than quietly dropped: CPython `urllib.request` (request.py lines 1333-1335)
            # closes the socket right after `getresponse()`, and an
            # amt-less CPython `http.client` (client.py line 505) `read()` calls `_close_conn()`,
            # so `e.fp.fp is None` by this point. 300 iterations against a
            # local 404 server moved the process handle count by ZERO.
            # The only real residue is a ResourceWarning from
            # `urllib.response.addbase`, so this close() is hygiene that
            # keeps the warning out of the test log - NOT a leak fix. The
            # `finally` is still right: it must run if _send raises.
            try:
                h._send(e.code, e.read(), "application/json")
            finally:
                e.close()
    except Exception as exc:  # noqa: BLE001
        log.warning("api/lcu-cmd-result: %s", exc)
        h._send(500, json.dumps({"error": _GENERIC_ERR}).encode(), "application/json")


# -- route table ------------------------------------------------------

# /api/loadout/list uses prefix() because the legacy do_POST used
# `startswith("/api/loadout/list")`. /api/loadout/apply must come
# first so its exact-match fires before the /list prefix would
# (`/list` does not prefix-match `/apply`, but ordering is explicit
# for safety as future loadout/* endpoints land here).
def path_or_query(p: str):
    """Match exactly `p`, or `p` followed by a query string.

    Lane 8 cycle 38: both routes below used `prefix()`, which is a bare
    `startswith` (`dashboard/_matchers.py:25-27`). MEASURED live:
    `GET /api/lcu-cmd-resultXYZ?id=1` was HANDLED (404 `{"error":"pending"}`
    from the vision server, not the dispatcher's 404), and
    `POST /api/loadout/listEVIL` answered 400 `champion required`. Both
    used `prefix` only to tolerate the `?id=...` query string, so this
    narrower matcher keeps that and drops the accidental suffix match.
    Fixed locally rather than by changing `prefix`, whose other callers
    are outside this file and outside this lane's one-file scope.
    """
    return lambda x: x == p or x.startswith(p + "?")


GET_ROUTES = [
    (path_or_query("/api/lcu-cmd-result"), _serve_lcu_cmd_result_get),
]

POST_ROUTES = [
    (equals("/api/loadout/apply"),           _serve_loadout_apply_post),
    (equals("/api/loadout/rune-pages"),      _serve_rune_pages_post),
    (path_or_query("/api/loadout/list"),     _serve_loadout_list_post),
    (equals("/api/lcu-cmd"),                 _serve_lcu_cmd_post),
]
