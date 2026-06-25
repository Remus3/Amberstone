# arch: GET /api/champions | section=dashboard | frozen=no
"""GET /api/champions - DDragon championId -> {name, slug} map (cached).

Carved out of routes_bridge.py when the cross-Claude bridge was
decommissioned (2026-06-24). The champions map is the lobby's champ-icon
lookup; it has no bridge dependency.
"""
import json
import logging
from dashboard._context import APP_DIR
from dashboard._dispatch import equals

log = logging.getLogger("rc.routes_champions")

# Module-level cache for /api/champions. None on first hit, dict thereafter;
# nothing outside this handler reads it.
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
                except Exception:  # noqa: BLE001
                    pass
            _CACHE = out
        except Exception as exc:  # noqa: BLE001
            log.warning("api/champions: %s", exc)
            _CACHE = {}
    h._send(200, json.dumps(_CACHE).encode(), "application/json")


GET_ROUTES = [
    (equals("/api/champions"), _serve_champions),
]

POST_ROUTES: list = []
