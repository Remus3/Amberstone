"""Bridge / champions routes.

Slice 2C-6 (2026-05-01): handlers carved out of web_dashboard._Handler.

  /api/bridge          cross-Claude message log read
  /api/champions       DDragon championId -> {name, slug} map (cached)

`/api/bridge` reads from `dashboard._bridge_log` directly (the in-memory
deque + JSONL backup were extracted from web_dashboard.py in the Tier 2
helper-shake).

`/api/champions` keeps its module-level cache (`_CACHE`) here; nothing
outside this handler reads it.
"""
import json
import logging
import time
from urllib.parse import parse_qs, urlparse

from core import bridge as _bridge
from dashboard._bridge_log import bridge_post, bridge_since
from dashboard._context import APP_DIR
from dashboard._dispatch import equals

log = logging.getLogger("rc.web_dashboard")


def _serve_bridge(h) -> None:
    # Cross-Claude message log read.
    # GET ?since=<ts>&hours=N&limit=N&kind=<>&target=<>&source=<>
    # `hours` is a convenience alternative to `since`; since wins if both given.
    try:
        qs = parse_qs(urlparse(h.path).query)
        hours_raw = (qs.get("hours") or [None])[0]
        default_since = (time.time() - float(hours_raw) * 3600) if hours_raw else 0.0
        since  = float((qs.get("since") or [str(default_since)])[0])
        limit  = int((qs.get("limit") or ["100"])[0])
        kind   = (qs.get("kind")   or [None])[0]
        target = (qs.get("target") or [None])[0]
        source = (qs.get("source") or [None])[0]
        items = bridge_since(since, limit, kind=kind, target=target, source=source)
        payload = {"now": time.time(), "messages": items}
        h._send(200, json.dumps(payload).encode(), "application/json")
    except Exception as exc:
        h._send(500, json.dumps({"error": str(exc)}).encode(), "application/json")


# Module-level cache for /api/champions. None on first hit, dict
# thereafter. Migrated from web_dashboard._CHAMP_MAP_CACHE - nothing
# else reads it.
_CACHE: dict | None = None


def _serve_champions(h) -> None:
    # {championId: {name, slug}} map for the lobby's champ icon lookups.
    # Cached on first read.
    global _CACHE
    if _CACHE is None:
        try:
            p = APP_DIR / "data" / "meta" / "ddragon_champions.json"
            raw = json.loads(p.read_text(encoding="utf-8"))
            out = {}
            for slug, entry in raw.get("data", {}).items():
                try:
                    cid = int(entry.get("key"))
                    out[str(cid)] = {"name": entry.get("name", slug),
                                      "slug": slug}
                except Exception:
                    pass
            _CACHE = out
        except Exception as exc:
            log.warning("api/champions: %s", exc)
            _CACHE = {}
    h._send(200, json.dumps(_CACHE).encode(), "application/json")


# ── POST handlers (slice 2C-7b) ──────────────────────────────────────


def _serve_bridge_post(h, payload) -> None:
    # Post a message to the cross-Claude bridge. Body shape:
    #   {source, summary, kind?, id?, target?, body?, in_reply_to?}
    # Existing {source, summary} posts default to kind="note".
    try:
        src     = (payload.get("source") or "").strip()
        msg     = (payload.get("summary") or "").strip()
        kind    = (payload.get("kind") or "note").strip()
        eid     = payload.get("id")
        target  = payload.get("target")
        msg_body = payload.get("body")
        replyto = payload.get("in_reply_to")
        if not msg and kind == "note":
            h._send(400, b'{"error":"empty summary"}', "application/json"); return
        entry = bridge_post(src, msg, kind=kind, entry_id=eid,
                            target=target, body=msg_body, in_reply_to=replyto)
        h._send(200, json.dumps({"ok": True, "ts": entry["ts"],
                                  "id": entry.get("id"),
                                  "kind": entry.get("kind")}).encode(),
                "application/json")
    except Exception as exc:
        h._send(500, json.dumps({"error": str(exc)}).encode(), "application/json")


def _serve_bridge_inbox(h, payload) -> None:
    # POST /api/bridge/inbox - receive a message from the peer (Peer).
    # Mirrors Peer's /api/bridge/inbox per RC_BRIDGE_CONTRACT.md (v0).
    #   503 - no shared_secret configured
    #   401 - Authorization header missing or doesn't match
    #   400 - no `summary` field in payload
    #   200 - appended to bridge log; returns {ok, entry}
    try:
        if not _bridge.is_configured():
            h._send(503, b'{"error":"bridge_not_configured"}', "application/json")
            return

        # Bearer guard. Header may arrive as "Authorization" or "authorization"
        # depending on client; BaseHTTPRequestHandler.headers is case-insensitive
        # so a single .get() suffices.
        auth = (h.headers.get("Authorization") or "").strip()
        expected = "Bearer " + _bridge.shared_secret()
        if auth != expected:
            log.warning("bridge inbox auth reject from %s", h.client_address[0])
            h._send(401, b'{"error":"unauthorized"}', "application/json")
            return

        msg = (payload.get("summary") or "").strip()
        if not msg:
            h._send(400, b'{"error":"missing_summary"}', "application/json")
            return

        entry = bridge_post(
            (payload.get("source") or "peer").strip(),
            msg,
            kind=(payload.get("kind") or "note").strip(),
            entry_id=payload.get("id"),
            target=payload.get("target"),
            body=payload.get("body"),
            in_reply_to=payload.get("in_reply_to"),
        )
        h._send(200, json.dumps({"ok": True, "entry": entry}).encode("utf-8"),
                "application/json")
    except Exception as exc:
        log.warning("bridge inbox failed: %s", exc)
        h._send(500, json.dumps({"error": str(exc)[:200]}).encode(),
                "application/json")


def _serve_bridge_status(h) -> None:
    # GET /api/bridge/status - operator-facing config gate; never leaks the secret.
    try:
        h._send(200, json.dumps(_bridge.status_summary()).encode("utf-8"),
                "application/json")
    except Exception as exc:
        h._send(500, json.dumps({"error": str(exc)[:200]}).encode(),
                "application/json")


# ── route table ──────────────────────────────────────────────────────

# /api/bridge accepts query strings (`?since=...&limit=...`) - equals()
# already handles the `?...` suffix. /api/champions is exact.
GET_ROUTES = [
    (equals("/api/bridge"),          _serve_bridge),
    (equals("/api/bridge/messages"), _serve_bridge),
    (equals("/api/bridge/status"),   _serve_bridge_status),
    (equals("/api/champions"),       _serve_champions),
]

POST_ROUTES = [
    (equals("/api/bridge"),         _serve_bridge_post),
    (equals("/api/bridge/inbox"),   _serve_bridge_inbox),
]
