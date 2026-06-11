# arch: live power-spike markers backend | section=dashboard | frozen=no
"""GET /api/spike-markers - discrete level + item-completion spike markers.

Competitor lift #4 (Aggregator C power-spike timeline; DEPTH spec
``docs/COMPETITOR_LIFT_2026-05-30.md`` "Lift 4"). Thin dashboard wire over
``agents.daemon_slayer.spike_markers.compute_spike_markers`` - the marker
MATH (which level / item-completion spike is crossed, which is next) keyed
on the operator's LIVE champion + level + owned items. NO new ENGINE math,
NO schema lift, NO new dependency; the engine module is a read-only
classifier over RC's own DS curves.

Sibling of ``routes_cooldown_watch.py`` (cache + fail-soft discipline) and
``routes_spike_curve.py`` (the team-vs-team sparkline this complements).
Where spike-curve renders a synthetic minute->level->item team power
curve, this route surfaces the OPERATOR's discrete spike thresholds keyed
on their actual live state - the in-game "now you can fight" markers.

Request shape:
  GET /api/spike-markers?champion=<id>&level=<1..18>[&items=<id,id,...>]
                         [&mode=SR][&item_count=<n>][&minor=1]

  champion   : canonical DDragon id ("Aatrox", "Jinx"). REQUIRED.
  level      : operator's live champion level. Defaults 1; clamped 1..18.
  items      : comma-separated owned item ids (threaded to the DS curve
               for the optional dps_at annotation). Blank entries skipped.
  mode       : SR | ARAM | ARENA | BRAWL. Defaults SR. Threaded to the DS
               curve; does NOT move the spike thresholds.
  item_count : explicit count of FINISHED legendary items. When absent,
               the engine defaults to min(len(items), 3).
  minor      : "1" to include the 9/13/18 minor level breakpoints.

Response shape:
  {
    "ok":         true,
    "champion":   "Aatrox",
    "level":      8,
    "markers": [
      {"kind":"level","threshold":6,"label":"R unlock","crossed":true,
       "next":false,"dps_at":210.4},
      {"kind":"level","threshold":11,"label":"R rank 2","crossed":false,
       "next":true,"dps_at":318.9},
      ...
      {"kind":"item","threshold":1,"label":"first item","crossed":true,
       "next":false},
      ...
    ],
    "next":       {"kind":"level","threshold":11,...} | null,
    "count":      <int>,
    "elapsed_ms": <int>,
    "cached":     <bool>
  }

Failure modes:
  - 400  champion param literally missing / blank.
  - 200  ok=false reason=no_markers when the engine returns no markers
         (blank champion that slipped the 400 guard - defensive).
  - 503  spike_markers import / compute fails (DS engine unreachable).

5-min TTL in-process cache keyed on (champion, level, sorted items, mode,
item_count, minor). Mirrors routes_cooldown_watch cache discipline.

Don't-redo:
  * The LIVE-clock cursor (a "now" line at game_time on the strip) is the
    live-game-only visual half of this lift and is OWED - NOT this route.
    This route returns the discrete marker MATH, which is mock-testable
    headless; the frontend renders the markers; the cursor is wired when a
    live game proves the visual.
  * item_count is the FINISHED-legendary count when the caller has it;
    otherwise the engine proxies min(len(items), 3). RC does not re-derive
    item completion from raw ids here.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from urllib.parse import parse_qs, urlparse

from dashboard._dispatch import equals

log = logging.getLogger("rc.web_dashboard")

# 5-min response TTL mirrors routes_cooldown_watch exactly.
_CACHE_TTL_S = 300.0
_CACHE: dict[tuple, tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()


def _parse_item_list(raw: str) -> list[str]:
    """Split a comma-separated item-id list, strip blanks."""
    if not raw:
        return []
    out: list[str] = []
    for part in raw.split(","):
        s = part.strip()
        if s:
            out.append(s)
    return out


def _parse_int(raw: str, default: int) -> int:
    """Parse an int param; fall to ``default`` on blank / garbage."""
    if not raw:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _parse_item_count(raw: str):
    """Parse the optional explicit finished-legendary count.

    Returns None (engine proxies from len(items)) on blank / garbage so
    the absence of the param is distinct from an explicit 0.
    """
    if not raw:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _cache_key(champion: str, level: int, items: list[str], mode: str,
               item_count, minor: bool) -> tuple:
    return (champion, level, tuple(sorted(items)), mode, item_count, minor)


def _compute(champion: str, level: int, items: list[str], mode: str,
             item_count, minor: bool) -> dict:
    """Build the response payload from scratch (no cache)."""
    from agents.daemon_slayer.spike_markers import compute_spike_markers

    result = compute_spike_markers(
        champion,
        level,
        item_ids=items,
        mode=mode,
        item_count_done=item_count,
        include_minor=minor,
    )
    d = result.to_dict()
    return {
        "ok":      True,
        "champion": d["champion"],
        "level":   d["level"],
        "item_count_done": d["item_count_done"],
        "markers": d["markers"],
        "next":    d["next"],
        "count":   len(d["markers"]),
    }


def _serve_spike_markers(h) -> None:
    """GET /api/spike-markers handler."""
    t0 = time.time()
    try:
        qs = parse_qs(urlparse(h.path).query or "", keep_blank_values=True)
        if "champion" not in qs:
            h._send(400, json.dumps({
                "ok":    False,
                "error": "champion param required",
            }).encode("utf-8"), "application/json")
            return

        champion = (qs.get("champion") or [""])[0].strip()
        if not champion:
            h._send(400, json.dumps({
                "ok":    False,
                "error": "champion param required",
            }).encode("utf-8"), "application/json")
            return

        # 2026-06-10: the active-match panel sends the coach payload's
        # champion verbatim - a Live Client DISPLAY name ("Tahm Kench").
        # The DS curve keys canonical DDragon ids, so the dps_at
        # annotation silently dropped for multi-word champs. Canonical
        # ids pass through unchanged; the bridge itself fail-softs.
        try:
            from core.archetype_picks import canonical_champion_id
            champion = canonical_champion_id(champion) or champion
        except Exception:
            pass

        level = _parse_int((qs.get("level") or [""])[0].strip(), 1)
        mode = ((qs.get("mode") or ["SR"])[0].strip() or "SR").upper()
        items = _parse_item_list((qs.get("items") or [""])[0].strip())
        item_count = _parse_item_count((qs.get("item_count") or [""])[0].strip())
        minor = (qs.get("minor") or [""])[0].strip() in ("1", "true", "yes")

        key = _cache_key(champion, level, items, mode, item_count, minor)
        now = time.time()
        with _CACHE_LOCK:
            cached = _CACHE.get(key)
            if cached and (now - cached[0]) < _CACHE_TTL_S:
                payload = dict(cached[1])
                payload["cached"] = True
                payload["elapsed_ms"] = int((time.time() - t0) * 1000)
                h._send(200, json.dumps(payload).encode("utf-8"),
                        "application/json")
                return

        try:
            payload = _compute(champion, level, items, mode, item_count, minor)
        except ImportError as exc:
            log.warning("api/spike-markers import: %s", exc)
            h._send(503, json.dumps({
                "ok":    False,
                "error": "DS engine unavailable",
            }).encode("utf-8"), "application/json")
            return
        except Exception as exc:
            log.warning("api/spike-markers compute: %s", exc)
            h._send(503, json.dumps({
                "ok":    False,
                "error": "DS engine compute failed",
            }).encode("utf-8"), "application/json")
            return

        # Defensive no-markers guard (blank champion that slipped the 400).
        if not payload.get("markers"):
            payload = {
                "ok":         False,
                "reason":     "no_markers",
                "champion":   champion,
                "level":      level,
                "markers":    [],
                "next":       None,
                "count":      0,
            }
            h._send(200, json.dumps({
                **payload,
                "cached": False,
                "elapsed_ms": int((time.time() - t0) * 1000),
            }).encode("utf-8"), "application/json")
            return

        with _CACHE_LOCK:
            _CACHE[key] = (now, dict(payload))

        payload["cached"] = False
        payload["elapsed_ms"] = int((time.time() - t0) * 1000)
        h._send(200, json.dumps(payload).encode("utf-8"),
                "application/json")

    except Exception as exc:
        log.warning("api/spike-markers: %s", exc)
        try:
            h._send(500, json.dumps({
                "ok": False, "error": str(exc)[:200],
            }).encode("utf-8"), "application/json")
        except Exception:
            pass


def _reset_caches() -> None:
    """Test-only: clear response cache."""
    with _CACHE_LOCK:
        _CACHE.clear()


GET_ROUTES = [
    (equals("/api/spike-markers"), _serve_spike_markers),
]

POST_ROUTES: list = []
