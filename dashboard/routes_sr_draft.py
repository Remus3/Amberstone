"""SR Draft Theatre routes.

Phase 8 step 5 (2026-05-04): POST /api/sr-draft/apply pushes a chosen
profile to the LCU via the same vision-server `/lcu-cmd` proxy as
`/api/loadout/apply`. Each variant gets a unique rune-page name
(`RC: <Champ> <key> (SR)`) so concurrent variants don't clobber each
other through `lcu_rune_writer._write_page`'s delete-all-RC-pages step.

Note: the sibling POST profile endpoint was retired in item 186
(0 live callers). The engine entry point `build_profile()` in
`coaches.sr_draft_profile` is still imported directly by phase8 tests +
any future consumer.

  POST /api/sr-draft/apply
  {
    "champion":  "Tristana",
    "key":       "primary",                 # profile key - used in page name
    "label":     "Primary",                 # optional, surfaces in response
    "kind":      "engine"|"user",           # optional, response only
    "runes": {                              # optional - skipped if missing
      "keystone":  "Press the Attack",
      "primary":   "Precision",
      "secondary": "Domination"
    },
    "summoner_spells": [4, 12],             # optional - [d, f] LCU IDs
    "item_ids":  ["6675", "3094", ...],     # optional - pre-resolved
    "push_runes": true,                     # default true
    "push_items": true,                     # default true
    "push_summoners": true                  # default true
  }

  -> 200 {
       "ok": true,
       "champion": "Tristana", "key": "primary", "label": "Primary",
       "queued": ["apply_runes", "apply_item_set", "set_summoners"],
       "page_name": "RC: Tristana primary (SR)",
       "item_ids": ["6675", "3094", ...]
     }

  "ok" is true only when every command the body asked for was queued; a
  relay that refused or timed out gives a 200 with "ok": false, the failed
  command named in `notes` ("<cmd>: enqueue failed - see logs") and the
  cause in the log (a partial push is still a 200: the queued commands did
  reach the client, so the reply says exactly which did).

Errors:
  400 - the WHOLE body is validated before anything is queued, so a refused
        body never leaves a partial write on the League client:
        {"ok": false, "error": <code>, "field": <name>} for champion / key
        (required printable strings, at most 64 chars), label (at most 128)
        / kind (at most 64) (optional printable strings), runes (an object
        whose rune names are printable strings), item_ids (a list of at
        most 64 positive ids, each an int or an ASCII-digit string of at
        most 7 digits) and summoner_spells (exactly two distinct ints in
        1..9999; null or [] = not supplied). A push_* flag the server
        cannot read keeps the shared RM-414 envelope
        {"error": "bad_push_flag", "field": <flag>}.
  500 - anything unexpected: {"ok": false, "error": "internal error - see
        logs"}, the traceback in the log only.

Lane 8 (true-audit) s144: every field above used to be read without a type
check - a string item_ids was pushed one character per item, [true, false]
pushed Cleanse, a list keystone was a 500 - and the reply said "ok": true
after a failed enqueue. Pinned by tests/test_routes_sr_draft_lane8_s144.py.
"""
import http.client
import json
import logging
import urllib.request

from core.log_scrub import scrub_log
from dashboard._dispatch import equals
from dashboard._json_flags import (
    bad_flag_body,
    coerce_json_flag,
    first_ambiguous_flag,
)

log = logging.getLogger("rc.web_dashboard")

# Body limits. Champion names top out well under 20 chars ("Nunu & Willump");
# the cap only has to stop an unbounded value reaching the client and the
# echo. Item ids are 4-6 digits today; 7 leaves headroom.
_TEXT_MAX = 64
_LABEL_MAX = 128
_ITEM_IDS_MAX = 64
_ITEM_ID_DIGITS_MAX = 7
_SUMMONER_ID_MAX = 9999   # same bound as routes_loadout._SUMMONER_ID_MAX
_RUNE_NAME_KEYS = ("keystone", "primary", "secondary",
                   "primary_tree", "secondary_tree")

# What a failed POST to the local relay can raise: URLError / HTTPError /
# TimeoutError / ConnectionError are all OSError; ValueError covers a bad URL
# or header; HTTPException a malformed reply. Anything else is a bug and is
# left to the handler's 500 path rather than reported as a routine note.
_ENQUEUE_ERRORS = (OSError, ValueError, http.client.HTTPException)


# Each field parser below returns (value, None) or (None, error_code). They
# return rather than raise on purpose: the 400 body is built from server-
# authored codes only, and no except-bound name ever flows toward a reply
# (the RM-835 source guard in tests/test_rm835_dashboard_reply_scrub.py).


def _text_ok(val: str, cap: int) -> bool:
    return len(val) <= cap and val.isprintable()


def _required_text(payload: dict, field: str, cap: int = _TEXT_MAX):
    """A required printable string; absent, null or blank is `required`."""
    val = payload.get(field)
    if val is None:
        return None, "required"
    if not isinstance(val, str):
        return None, "bad_type"
    val = val.strip()
    if not val:
        return None, "required"
    return (val, None) if _text_ok(val, cap) else (None, "bad_value")


def _optional_text(payload: dict, field: str, cap: int, default: str):
    """An optional printable string; absent, null or blank is `default`."""
    val = payload.get(field)
    if val is None:
        return default, None
    if not isinstance(val, str):
        return None, "bad_type"
    val = val.strip()
    if not val:
        return default, None
    return (val, None) if _text_ok(val, cap) else (None, "bad_value")


def _parse_runes(payload: dict):
    """The runes object; absent / null / {} = no rune push requested."""
    runes = payload.get("runes")
    if runes is None:
        return {}, None
    if not isinstance(runes, dict):
        return None, "bad_type"
    for name in _RUNE_NAME_KEYS:
        val = runes.get(name)
        if val is None:
            continue
        if not isinstance(val, str):
            return None, "bad_type"
        if not _text_ok(val, _TEXT_MAX):
            return None, "bad_value"
    return runes, None


def _item_id(val) -> "str | None":
    """One item id normalised to its decimal string, or None if unusable."""
    if isinstance(val, bool):
        return None
    if isinstance(val, int):
        num = val
    elif isinstance(val, str):
        s = val.strip()
        if not (s.isascii() and s.isdigit()) or len(s) > _ITEM_ID_DIGITS_MAX:
            return None
        num = int(s)
    else:
        return None
    if not 0 < num < 10 ** _ITEM_ID_DIGITS_MAX:
        return None
    return str(num)


def _parse_item_ids(payload: dict):
    """Normalised item ids (strings, in order); absent / null / [] = []."""
    raw = payload.get("item_ids")
    if raw is None:
        return [], None
    if not isinstance(raw, list):
        return None, "bad_type"
    if len(raw) > _ITEM_IDS_MAX:
        return None, "too_many"
    out = [_item_id(v) for v in raw]
    if None in out:
        return None, "bad_value"
    return out, None


def _parse_summoners(payload: dict):
    """(d, f), or None when not supplied (absent / null / [])."""
    raw = payload.get("summoner_spells")
    if raw is None or raw == []:
        return None, None
    if not isinstance(raw, list) or len(raw) != 2:
        return None, "bad_value"
    for val in raw:
        # bool first: isinstance(True, int) is True, and true would push
        # spell id 1 (Cleanse).
        if isinstance(val, bool) or not isinstance(val, int):
            return None, "bad_value"
        if not 0 < val <= _SUMMONER_ID_MAX:
            return None, "bad_value"
    if raw[0] == raw[1]:
        return None, "bad_value"
    return (raw[0], raw[1]), None


def _parse_body(payload: dict):
    """Validate every field; (fields, None) or (None, (field, error_code))."""
    parsers = (
        ("champion", lambda p: _required_text(p, "champion")),
        ("key", lambda p: _required_text(p, "key")),
        ("kind", lambda p: _optional_text(p, "kind", _TEXT_MAX, "")),
        ("runes", _parse_runes),
        ("item_ids", _parse_item_ids),
        ("summoner_spells", _parse_summoners),
    )
    out: dict = {}
    for field, parse in parsers:
        val, err = parse(payload)
        if err:
            return None, (field, err)
        out[field] = val
    # label defaults to the (validated) key.
    label, err = _optional_text(payload, "label", _LABEL_MAX, out["key"])
    if err:
        return None, ("label", err)
    out["label"] = label
    return out, None


def _bad_field_body(field: str, error: str) -> bytes:
    return json.dumps({"ok": False, "error": error, "field": field}).encode()


def _build_page_name(champion: str, key: str) -> str:
    """Unique rune-page name per (champion, profile-key) pair.

    Truncated to 75 chars (LCU page-name cap). Per s51 plan: each variant
    gets its own page so concurrent saves don't clobber via the rune
    writer's delete-all-RC-pages step.
    """
    return f"RC: {champion} {key} (SR)"[:75]


def _build_item_set(champion: str, key: str, item_ids: list) -> dict:
    """Wrap pre-resolved item ids in the LCU `apply_item_set` shape.

    Mirrors `coaches.loadout_resolver.resolve`'s item_cmd shape so the
    Legion LCU agent receives an identical command structure. `set_uid`
    is variant-keyed so each profile gets its own slot in the client.
    """
    norm_champ = "".join(ch for ch in champion.lower() if ch.isalnum())
    norm_key   = "".join(ch for ch in key.lower()      if ch.isalnum())
    items = [{"id": str(i), "count": 1} for i in (item_ids or []) if i]
    return {
        "cmd":      "apply_item_set",
        "set_uid":  f"RC-{norm_champ}-sr-{norm_key}",
        "title":    f"RC: {champion} {key} (SR)"[:50],
        # champion_id is best-effort - the LCU agent tolerates 0 (item
        # set still applies; just isn't auto-equipped on champion lock).
        "champion_id": 0,
        "blocks": [{
            "type":  "Build (RC SR-draft)",
            "items": items,
        }],
    }


def _build_rune_cmd(champion: str, key: str, runes: dict) -> "dict | None":
    """Translate a profile's runes dict -> `apply_runes` LCU command.

    Returns None when the keystone or trees aren't recognised by the
    `lcu.lcu_rune_writer.build_perk_ids` resolver (NOT frozen - the claim
    that it was is corrected lane 8 cycle 39) - in that case
    the caller skips the rune push and surfaces a note. The shard3=5002
    SR bug in the rune writer is documented in
    `project_rune_writer_shard3_not_applied.md`; SR-draft variants ride
    this path knowingly (engine work, not Phase 8 scope).
    """
    if not isinstance(runes, dict):
        return None
    keystone  = runes.get("keystone")  or ""
    primary   = runes.get("primary")   or runes.get("primary_tree")   or ""
    secondary = runes.get("secondary") or runes.get("secondary_tree") or ""
    if not (keystone and primary and secondary):
        return None
    try:
        from lcu.lcu_rune_writer import build_perk_ids, resolve_tree_ids
    except Exception as exc:  # noqa: BLE001
        log.warning("api/sr-draft/apply rune import: %s", exc)
        return None
    perk_ids = build_perk_ids(keystone, primary, secondary, is_aram=False)
    # Lane 8 cycle 39: these names arrive in a POST body, so primary == secondary
    # is reachable. resolve_tree_ids mirrors build_perk_ids' substitution.
    primary_id, sub_id = resolve_tree_ids(primary, secondary)
    if not (perk_ids and primary_id and sub_id):
        return None
    return {
        "cmd":        "apply_runes",
        "page_name":  _build_page_name(champion, key),
        "primary_id": primary_id,
        "sub_id":     sub_id,
        "perk_ids":   perk_ids,
    }


def _enqueue(cmd_obj: dict, token: str) -> bool:
    """POST one command to the vision relay's `/lcu-cmd` queue.

    True when the relay accepted it. A relay that is down, slow or refusing
    (`_ENQUEUE_ERRORS`) is a routine False with the cause logged; anything
    else is a bug and propagates to the handler's 500.
    """
    req = urllib.request.Request(
        "http://127.0.0.1:8889/lcu-cmd",
        data=json.dumps(cmd_obj).encode(),
        method="POST",
        headers={"X-RC-Token": token, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=2) as r:
            r.read()
    except _ENQUEUE_ERRORS as exc:
        log.warning("sr-draft enqueue %s: %s: %s", cmd_obj["cmd"],
                    type(exc).__name__, scrub_log(str(exc)))
        return False
    return True


def _serve_sr_draft_apply_post(h, payload) -> None:
    try:
        if not isinstance(payload, dict):
            # _handler.do_POST already guarantees a dict (LEDGER 1181).
            h._send(400, _bad_field_body("body", "bad_type"),
                    "application/json")
            return
        # RM-414: parsed, never bare-truthy - {"push_runes": "false"} used to
        # push the runes. Same rule and same 400 envelope as the twin route
        # /api/loadout/apply (RM-296d); see dashboard/_json_flags.py.
        push_runes = coerce_json_flag(payload, "push_runes",     True)
        push_items = coerce_json_flag(payload, "push_items",     True)
        push_summ  = coerce_json_flag(payload, "push_summoners", True)
        bad_flag = first_ambiguous_flag(
            payload, ("push_runes", "push_items", "push_summoners"))
        if bad_flag:
            h._send(400, bad_flag_body(bad_flag, "bad_push_flag"),
                    "application/json")
            return
        # Every field is validated BEFORE anything is queued: a refused body
        # must never leave half a loadout on the League client. A malformed
        # field is refused even when its push_* flag is off.
        fields, bad = _parse_body(payload)
        if bad:
            h._send(400, _bad_field_body(*bad), "application/json")
            return
        champ, key = fields["champion"], fields["key"]
        label, kind = fields["label"], fields["kind"]
        runes, item_ids = fields["runes"], fields["item_ids"]
        spells = fields["summoner_spells"]

        from web_dashboard import _VISION_TOKEN

        rune_cmd = _build_rune_cmd(champ, key, runes) if push_runes else None
        item_cmd = (_build_item_set(champ, key, item_ids)
                    if (push_items and item_ids) else None)
        summ_cmd = ({"cmd": "set_summoners", "d": spells[0], "f": spells[1]}
                    if (push_summ and spells) else None)

        queued: list[str] = []
        notes:  list[str] = []
        if push_runes and rune_cmd is None and runes:
            notes.append("runes: keystone/tree unrecognised - skipped")
        failed = False
        for cmd_obj in (rune_cmd, item_cmd, summ_cmd):
            if cmd_obj is None:
                continue
            if _enqueue(cmd_obj, _VISION_TOKEN):
                queued.append(cmd_obj["cmd"])
            else:
                # RM-835: a fixed line, never the exception's text.
                failed = True
                notes.append(f"{cmd_obj['cmd']}: enqueue failed - see logs")

        h._send(200, json.dumps({
            "ok":         not failed,
            "champion":   champ,
            "key":        key,
            "kind":       kind,
            "label":      label,
            "queued":     queued,
            "page_name":  _build_page_name(champ, key),
            "item_ids":   item_ids,
            "notes":      notes,
        }).encode(), "application/json")
    except Exception as exc:  # the route's last-resort 500
        # Raw exception text stays in the log only, with its traceback.
        log.warning("api/sr-draft/apply: %s: %s", type(exc).__name__,
                    scrub_log(str(exc)), exc_info=True)
        h._send(500, json.dumps({"ok": False,
                                 "error": "internal error - see logs"}).encode(),
                "application/json")


# -- route table ------------------------------------------------------

GET_ROUTES: list = []

POST_ROUTES = [
    (equals("/api/sr-draft/apply"),   _serve_sr_draft_apply_post),
]
