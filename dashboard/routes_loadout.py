"""Loadout + LCU command POST routes.

Slice 2C-7d (2026-05-01): final POST sub-slice. Handlers carved out
of `web_dashboard._Handler.do_POST`. All three reach the in-process
vision server at 127.0.0.1:8889 (which proxies to Game-PC's LCU agent),
so they share the `_VISION_TOKEN` auth header.

`_VISION_TOKEN` is deferred-imported from `web_dashboard` inside each
handler — same pattern as `routes_diag` — to avoid a circular import
at module load time (web_dashboard imports the dashboard package
during start-up).
"""
import json
import logging

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
    "trade_request", "accept_trade", "decline_trade",
    # Lobby actions (2026-04-26): start/cancel matchmaking from the
    # dashboard's Find Match button + change queue type from the
    # lobby dropdown. LCU restricts these to the lobby leader; the UI
    # gates the controls on lobby.is_leader before sending.
    "start_matchmaking", "cancel_matchmaking",
    "change_queue_type",
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
        h._send(200, json.dumps({
            "champion": champ, "mode": mode,
            "variants": vs, "default": df,
        }).encode(), "application/json")
    except Exception as exc:
        log.warning("api/loadout/list: %s", exc)
        h._send(500, json.dumps({"error": str(exc)}).encode(), "application/json")


def _serve_loadout_apply_post(h, payload) -> None:
    # Body: {champion, variant, mode, push_runes?, push_items?, push_summoners?}.
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
        if not champ or not variant:
            h._send(400, b'{"error":"champion+variant required"}', "application/json"); return
        resolved = resolve(champ, variant, mode)
        if not resolved.get("ok"):
            h._send(404, json.dumps(resolved).encode(), "application/json"); return
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


# ── route table ──────────────────────────────────────────────────────

# /api/loadout/list uses prefix() because the legacy do_POST used
# `startswith("/api/loadout/list")`. /api/loadout/apply must come
# first so its exact-match fires before the /list prefix would
# (`/list` does not prefix-match `/apply`, but ordering is explicit
# for safety as future loadout/* endpoints land here).
GET_ROUTES: list = []

POST_ROUTES = [
    (equals("/api/loadout/apply"),  _serve_loadout_apply_post),
    (prefix("/api/loadout/list"),   _serve_loadout_list_post),
    (equals("/api/lcu-cmd"),        _serve_lcu_cmd_post),
]
