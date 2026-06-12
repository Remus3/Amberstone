"""GET /api/damage-mix - per-enemy damage-type donut data (UX-2, 2026-05-20).

Inputs (query string):

  - ``champ_id``  : Riot numeric champion key (e.g. 86 for Garen) OR
                    the snapshot string id (e.g. "Garen"). Required.
  - ``items``     : comma-separated item ids (e.g. "3074,3071,3047").
                    1..6 items. Required for a meaningful mix; empty
                    returns 400 ``items_required`` (kit-only baseline
                    is not exposed - the whole point of the surface is
                    "items have flipped damage").
  - ``level``     : optional, default 11. Clamped to [1, 18].
  - ``mode``      : optional, default "SR". Affects ARAM
                    ``aramDamageDealt`` if "ARAM".

Output (JSON 200):

  {
    "ok": true,
    "champ_id": "Garen",
    "champ_key": 86,
    "items": ["3074", "3071", "3047"],
    "level": 11,
    "mode": "SR",
    "physical_dps": 18.5,
    "magical_dps": 0.3,
    "true_dps": 0.9,
    "on_hit_dps": 0.0,
    "total_dps": 19.7,
    "mix": {"physical": 0.939, "magical": 0.015, "true": 0.046, "on_hit": 0.0},
    "cache_key": "Garen:3074,3071,3047",
    "cached": false
  }

Errors (JSON 400):

  - missing or empty ``champ_id``
  - unknown champ key / id
  - missing or empty ``items``
  - unknown item id in the list
  - more than 6 items
  - level out of range
"""
from __future__ import annotations

import json
import logging
import threading
from urllib.parse import parse_qs, urlparse

from dashboard._dispatch import equals

log = logging.getLogger("rc.web_dashboard")

# DataSnapshot is immutable per patch - load once + reuse across requests
# (mirrors routes_ds_knobs._get_snapshot). Pre-fix the route re-parsed the
# full multi-file snapshot from disk on EVERY request.
_SNAPSHOT = None
_SNAPSHOT_LOCK = threading.Lock()


def _get_snapshot():
    """Lazy-load + memoize the DS DataSnapshot (current.txt patch)."""
    global _SNAPSHOT
    with _SNAPSHOT_LOCK:
        if _SNAPSHOT is None:
            from agents.daemon_slayer.data_loader import DataSnapshot
            _SNAPSHOT = DataSnapshot.load()
        return _SNAPSHOT


def _reset_caches() -> None:
    """Test-only: clear the memoized snapshot."""
    global _SNAPSHOT
    with _SNAPSHOT_LOCK:
        _SNAPSHOT = None


def _bad(h, msg: str) -> None:
    body = json.dumps({"ok": False, "error": msg}).encode("utf-8")
    h._send(400, body, "application/json")


def _serve_damage_mix(h) -> None:
    """GET /api/damage-mix?champ_id=X&items=A,B,C[&level=N&mode=M]."""
    try:
        qs = parse_qs(urlparse(h.path).query, keep_blank_values=True)

        champ_raw = (qs.get("champ_id") or [""])[0].strip()
        if not champ_raw:
            _bad(h, "champ_id_required")
            return

        items_raw = (qs.get("items") or [""])[0].strip()
        if not items_raw:
            _bad(h, "items_required")
            return
        items = [t for t in items_raw.split(",") if t.strip()]
        if not items:
            _bad(h, "items_required")
            return

        # Level parsing - default 11 (mid-game). Out-of-range -> 400.
        level_raw = (qs.get("level") or ["11"])[0].strip()
        try:
            level = int(level_raw)
        except ValueError:
            _bad(h, f"level_invalid:{level_raw}")
            return
        if level < 1 or level > 18:
            _bad(h, f"level_out_of_range:{level}")
            return

        mode = (qs.get("mode") or ["SR"])[0].strip() or "SR"

        # Lazy import keeps a malformed snapshot from crashing the
        # whole dashboard at boot - same pattern as routes_lessons.
        from core.damage_mix import compute_damage_mix

        snapshot = _get_snapshot()
        try:
            mix, was_cached = compute_damage_mix(
                snapshot, champ_raw, items, level=level, mode=mode,
            )
        except ValueError as exc:
            # Translate domain errors into 400 with the error tag.
            _bad(h, str(exc))
            return

        payload = mix.to_dict()
        payload.update({
            "ok": True,
            "cache_key": f"{mix.champ_id}:{','.join(mix.items)}",
            "cached": was_cached,
        })
        body = json.dumps(payload).encode("utf-8")
        h._send(200, body, "application/json")
    except Exception as exc:
        log.warning("damage-mix failed: %s", exc, exc_info=True)
        try:
            body = json.dumps({"ok": False, "error": str(exc)[:200]}).encode("utf-8")
            h._send(500, body, "application/json")
        except Exception:
            pass


GET_ROUTES = [
    (equals("/api/damage-mix"), _serve_damage_mix),
]

POST_ROUTES: list = []
