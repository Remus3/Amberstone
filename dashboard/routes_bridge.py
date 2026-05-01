"""Bridge / preview-build / champions routes.

Slice 2C-6 (2026-05-01): handlers carved out of web_dashboard._Handler.
Group 6 — three GET endpoints:

  /api/bridge          cross-Claude message log read
  /api/preview-build   champ-select build + runes + ally-notes brief
  /api/champions       DDragon championId -> {name, slug} map (cached)

`/api/bridge` and `/api/preview-build` reach helpers that still live in
web_dashboard.py (`_bridge_since`, `_lcu_summary`,
`_champ_select_brief_via_coach`) — those are deferred-imported inside
each handler to avoid the same circular-import that web_dashboard
imports the dashboard package at start-up. Same pattern as routes_diag.

`/api/champions` keeps its module-level cache (`_CACHE`) here; nothing
outside this handler reads it.
"""
import json
import logging
from urllib.parse import parse_qs, urlparse

from dashboard._context import APP_DIR
from dashboard._dispatch import equals

log = logging.getLogger("rc.web_dashboard")


def _serve_bridge(h) -> None:
    # Cross-Claude message log read.
    # GET ?since=<ts>&limit=N&kind=<>&target=<>
    try:
        import time
        from web_dashboard import _bridge_since
        qs = parse_qs(urlparse(h.path).query)
        since  = float((qs.get("since") or ["0"])[0])
        limit  = int((qs.get("limit") or ["20"])[0])
        kind   = (qs.get("kind")   or [None])[0]
        target = (qs.get("target") or [None])[0]
        items = _bridge_since(since, limit, kind=kind, target=target)
        payload = {"now": time.time(), "messages": items}
        h._send(200, json.dumps(payload).encode(), "application/json")
    except Exception as exc:
        h._send(500, json.dumps({"error": str(exc)}).encode(), "application/json")


def _serve_preview_build(h) -> None:
    # Unified champ-select brief: build + runes + ally notes. The
    # CHAMPION_BUILDS curated path is preferred for build *only* when
    # the champion is curated and the mode isn't ARAM; runes + ally
    # notes always come from Haiku (cheap).
    try:
        from web_dashboard import _champ_select_brief_via_coach, _lcu_summary
        qs = parse_qs(urlparse(h.path).query)
        champ = (qs.get("champion") or [""])[0].strip()
        enemies = [s.strip() for s in
                   (qs.get("enemies") or [""])[0].split(",") if s.strip()]
        allies  = [s.strip() for s in
                   (qs.get("allies")  or [""])[0].split(",") if s.strip()]
        role = (qs.get("role") or [""])[0].strip()
        mode = (qs.get("mode") or ["SR"])[0].strip().upper()
        # Auto-detect ARAM from live LCU state if caller didn't pass.
        if mode == "SR":
            lcu = _lcu_summary() or {}
            if ((lcu.get("champ_select") or {}).get("is_aram")):
                mode = "ARAM"
        if not champ:
            h._send(400, b'{"error":"champion required"}', "application/json")
            return
        import sys as _sys
        _sys.path.insert(0, str(APP_DIR))
        from item_advisor import resolve_build, CHAMPION_BUILDS
        brief = _champ_select_brief_via_coach(champ, enemies, allies, role, mode)
        source = "coach"
        # Curated build wins outside ARAM. Runes/ally_notes still from coach.
        if champ in CHAMPION_BUILDS and mode != "ARAM":
            brief["build"] = resolve_build(champ, enemies, [])
            source = "curated+coach"
        payload = {
            "champion": champ, "mode": mode, "source": source,
            "build":      brief["build"],
            "runes":      brief["runes"],
            "ally_notes": brief["ally_notes"],
        }
        h._send(200, json.dumps(payload).encode(), "application/json")
    except Exception as exc:
        log.warning("api/preview-build: %s", exc)
        h._send(500, json.dumps({"error": str(exc)}).encode(), "application/json")


# Module-level cache for /api/champions. None on first hit, dict
# thereafter. Migrated from web_dashboard._CHAMP_MAP_CACHE — nothing
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


# ── route table ──────────────────────────────────────────────────────

# /api/bridge accepts query strings (`?since=…&limit=…`) — equals()
# already handles the `?…` suffix. /api/preview-build is the same.
# /api/champions is exact.
GET_ROUTES = [
    (equals("/api/bridge"),         _serve_bridge),
    (equals("/api/preview-build"),  _serve_preview_build),
    (equals("/api/champions"),      _serve_champions),
]

POST_ROUTES: list = []
