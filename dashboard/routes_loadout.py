"""Loadout + LCU command POST routes.

Slice 2C-7d (2026-05-01): final POST sub-slice. Handlers carved out
of `web_dashboard._Handler.do_POST`. All three reach the in-process
vision server at 127.0.0.1:8889 (which proxies to Game-PC's LCU agent),
so they share the `_VISION_TOKEN` auth header.

`_VISION_TOKEN` is deferred-imported from `web_dashboard` inside each
handler - same pattern as `routes_diag` - to avoid a circular import
at module load time (web_dashboard imports the dashboard package
during start-up).
"""
import json
import logging
import urllib.error
from urllib.parse import parse_qs, urlparse

from dashboard._dispatch import equals, prefix

log = logging.getLogger("rc.web_dashboard")


# Allowlist for /api/lcu-cmd. Hoisted out of the legacy handler body
# so it's allocated once at import, not per-request. The vision server
# also revalidates, but the dashboard edge rejects malformed bodies
# before they cross the LAN.
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
    # ``tools/gamepc_lcu_agent.py`` (set_*_intent at L908, *_swap at
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


def _serve_loadout_list_post(h, payload) -> None:
    # GET-style query in POST body for symmetry: {champion, mode}.
    # Returns [{key, label, is_default}, ...] for variants visible
    # in this mode for this champion.
    try:
        from coaches.loadout_resolver import list_variants, default_variant
        champ = (payload.get("champion") or "").strip()
        mode  = (payload.get("mode")     or "sr").strip()
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
        # below, experimental last.
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
        except Exception as exc:
            log.warning("loadout/list user-build merge: %s", exc)
        h._send(200, json.dumps({
            "champion": champ, "mode": mode,
            "variants": vs, "default": df,
        }).encode(), "application/json")
    except Exception as exc:
        log.warning("api/loadout/list: %s", exc)
        h._send(500, json.dumps({"error": str(exc)}).encode(), "application/json")


# s210 v2: build LCU command payloads for the synthetic "experimental"
# variant row in the build chooser. The frontend supplies a complete
# override package (keystone+primary+secondary + item-id list +
# adaptive summoners) - we skip the variant resolver entirely and
# build rune_cmd / item_cmd / summ_cmd inline.
def _build_experimental_resolved(champion: str, mode: str,
                                  override_runes: dict,
                                  override_items: list,
                                  override_summ: list | None) -> dict:
    from lcu.lcu_rune_writer import _TREES, build_perk_ids
    keystone   = str(override_runes.get("keystone") or "")
    primary    = str(override_runes.get("primary") or "")
    secondary  = str(override_runes.get("secondary") or "")
    is_aram    = (mode == "aram")
    perk_ids   = build_perk_ids(keystone, primary, secondary, is_aram)
    primary_id = _TREES.get(primary, 0)
    sub_id     = _TREES.get(secondary, 0)
    rune_cmd = None
    if perk_ids and primary_id and sub_id:
        rune_cmd = {
            "cmd":        "apply_runes",
            "page_name":  f"RC Experimental - {champion}",
            "primary_id": primary_id,
            "sub_id":     sub_id,
            "perk_ids":   perk_ids,
        }
    items_str = [str(x) for x in (override_items or []) if x]
    item_cmd = None
    if items_str:
        item_cmd = {
            "cmd":      "apply_item_set",
            "set_name": f"RC Experimental - {champion}",
            "blocks":   [{
                "type":  "DS engine · top picks",
                "items": [{"id": iid, "count": 1} for iid in items_str],
            }],
        }
    summ_cmd = None
    if override_summ and len(override_summ) == 2:
        summ_cmd = {"cmd": "set_summoners",
                    "d": int(override_summ[0]),
                    "f": int(override_summ[1])}
    return {
        "ok":         True,
        "mode":       mode,
        "label":      f"Experimental ({champion})",
        "rune_cmd":   rune_cmd,
        "item_cmd":   item_cmd,
        "summ_cmd":   summ_cmd,
        "raw_items":  items_str,
        "synthetic":  True,
    }


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
    from lcu.lcu_rune_writer import _TREES, build_perk_ids
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
        perk_ids   = build_perk_ids(keystone, primary, secondary,
                                    mode_key == "aram")
        primary_id = _TREES.get(primary, 0)
        sub_id     = _TREES.get(secondary, 0)
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


def _serve_loadout_apply_post(h, payload) -> None:
    # Body: {champion, variant, mode, push_runes?, push_items?, push_summoners?,
    #        override_runes?:{keystone,primary,secondary},
    #        override_items?:[id1,...],
    #        override_summoners?:[d,f]}.
    # Defaults: push everything that the variant declares.
    # Resolves the variant to LCU command payloads and queues them
    # one-by-one through the vision server's LCU endpoint. Returns
    # immediately; results come back via the LCU command queue
    # (best-effort).
    try:
        from coaches.loadout_resolver import resolve
        import urllib.request as _ur
        from web_dashboard import _VISION_TOKEN
        champ   = (payload.get("champion") or "").strip()
        variant = (payload.get("variant")  or "").strip()
        mode    = (payload.get("mode")     or "sr").strip()
        push_runes = payload.get("push_runes",   True)
        push_items = payload.get("push_items",   True)
        push_summ  = payload.get("push_summoners", True)
        # s209: optional override of the variant's stored summoners.
        # Used by the champ-select build chooser's adaptive-summoners
        # pipeline - when enemy comp pressures a different second spell
        # (Cleanse vs CC / Barrier vs burst) the JS sends the swapped
        # pair as [d_id, f_id]. Falls through to the variant's stored
        # summoners when omitted or malformed.
        override_summ = payload.get("override_summoners")
        if not (isinstance(override_summ, list) and len(override_summ) == 2
                and all(isinstance(x, int) for x in override_summ)):
            override_summ = None
        # s210 v2: optional override of runes + items for the experimental
        # build chooser row. When both are provided, the resolver path is
        # bypassed entirely - we build the LCU command payloads inline
        # from the operator-supplied keystone+primary+secondary +
        # item-id list. Champion arg is still required (used in page
        # naming + as a sanity check); variant arg can be the synthetic
        # "experimental" key that doesn't exist in champion_loadouts.json.
        override_runes = payload.get("override_runes") or None
        if not (isinstance(override_runes, dict)
                and override_runes.get("keystone")
                and override_runes.get("primary")
                and override_runes.get("secondary")):
            override_runes = None
        override_items = payload.get("override_items")
        if not (isinstance(override_items, list) and override_items
                and all(isinstance(x, (int, str)) for x in override_items)):
            override_items = None
        if not champ or not variant:
            h._send(400, b'{"error":"champion+variant required"}', "application/json"); return
        # 2026-05-28: operator user-curated build. Namespaced
        # "userbuild_<id>" by /api/loadout/list; routed here BEFORE the
        # experimental + resolver paths so the colon-free key never
        # reaches resolve()'s "<variant>:<path>" partition logic.
        if variant.startswith("userbuild_"):
            resolved = _resolve_user_build(champ, variant, mode, override_summ)
            if not resolved.get("ok"):
                h._send(404, json.dumps(resolved).encode(), "application/json"); return
        # s210 v2: experimental path - build cmds inline, skip resolver.
        elif override_runes and override_items:
            resolved = _build_experimental_resolved(
                champ, mode, override_runes, override_items, override_summ,
            )
        else:
            resolved = resolve(champ, variant, mode)
            if not resolved.get("ok"):
                h._send(404, json.dumps(resolved).encode(), "application/json"); return
            # Apply summoner override AFTER resolve so the rune + item cmds
            # come from the variant; only the summ_cmd is rewritten.
            if override_summ and resolved.get("summ_cmd"):
                sc = dict(resolved["summ_cmd"])
                sc["d"] = override_summ[0]
                sc["f"] = override_summ[1]
                resolved["summ_cmd"] = sc
        queued = []
        def _enqueue(cmd_obj):
            if not cmd_obj: return
            try:
                req = _ur.Request(
                    "http://127.0.0.1:8889/lcu-cmd",
                    data=json.dumps(cmd_obj).encode(),
                    method="POST",
                    headers={"X-RC-Token": _VISION_TOKEN,
                             "Content-Type": "application/json"},
                )
                with _ur.urlopen(req, timeout=2) as r:
                    r.read()
                queued.append(cmd_obj.get("cmd"))
            except Exception as exc:
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
        h._send(200, json.dumps({
            "ok": True,
            "champion": champ, "variant": variant, "mode": resolved.get("mode"),
            "label":    resolved.get("label"),
            "queued":   queued,
            "raw_items": resolved.get("raw_items", []),
            "item_ids":  item_ids,
        }).encode(), "application/json")
    except Exception as exc:
        log.warning("api/loadout/apply: %s", exc)
        h._send(500, json.dumps({"error": str(exc)}).encode(), "application/json")


def _serve_lcu_cmd_post(h, payload) -> None:
    # Forward command to vision server's LCU queue.
    # Body: {cmd: "accept_ready"} or {cmd:"set_config", auto_accept:true}
    # Validate at the dashboard edge so a malformed body never reaches
    # the LCU agent on Game-PC.
    cmd_name = (payload.get("cmd") or "").strip()
    if cmd_name not in _LCU_ALLOWED_CMDS:
        h._send(400,
            json.dumps({"error": "unknown_lcu_cmd",
                        "cmd": cmd_name,
                        "allowed": sorted(_LCU_ALLOWED_CMDS)}).encode(),
            "application/json")
        return
    try:
        import urllib.request as _ur
        from web_dashboard import _VISION_TOKEN
        req = _ur.Request(
            "http://127.0.0.1:8889/lcu-cmd",
            data=json.dumps(payload).encode(),
            method="POST",
            headers={"X-RC-Token": _VISION_TOKEN,
                     "Content-Type": "application/json"},
        )
        with _ur.urlopen(req, timeout=2) as r:
            body = r.read()
        h._send(200, body, "application/json")
    except Exception as exc:
        log.warning("api/lcu-cmd: %s", exc)
        h._send(500, json.dumps({"error": str(exc)}).encode(), "application/json")


def _serve_lcu_cmd_result_get(h) -> None:
    # Pulls the stored result for a previously-queued LCU command so the
    # UI can surface errors (e.g. start_matchmaking returning 400 from a
    # non-leader). Vision server returns 404 while pending; client polls.
    try:
        import urllib.request as _ur
        from web_dashboard import _VISION_TOKEN
        qs = parse_qs(urlparse(h.path).query)
        rid = (qs.get("id") or [""])[0]
        if not rid:
            h._send(400, b'{"error":"id required"}', "application/json"); return
        req = _ur.Request(
            f"http://127.0.0.1:8889/lcu-cmd-result?id={rid}",
            headers={"X-RC-Token": _VISION_TOKEN},
        )
        try:
            with _ur.urlopen(req, timeout=2) as r:
                h._send(200, r.read(), "application/json")
        except urllib.error.HTTPError as e:
            h._send(e.code, e.read(), "application/json")
    except Exception as exc:
        log.warning("api/lcu-cmd-result: %s", exc)
        h._send(500, json.dumps({"error": str(exc)}).encode(), "application/json")


# ── route table ──────────────────────────────────────────────────────

# /api/loadout/list uses prefix() because the legacy do_POST used
# `startswith("/api/loadout/list")`. /api/loadout/apply must come
# first so its exact-match fires before the /list prefix would
# (`/list` does not prefix-match `/apply`, but ordering is explicit
# for safety as future loadout/* endpoints land here).
GET_ROUTES = [
    (prefix("/api/lcu-cmd-result"), _serve_lcu_cmd_result_get),
]

POST_ROUTES = [
    (equals("/api/loadout/apply"),  _serve_loadout_apply_post),
    (prefix("/api/loadout/list"),   _serve_loadout_list_post),
    (equals("/api/lcu-cmd"),        _serve_lcu_cmd_post),
]
