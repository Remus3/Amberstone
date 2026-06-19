# arch: DS stat-sweep graph backend | section=dashboard | frozen=no
"""GET /api/ds-sweep - 1-variable DPS stat-sweep curve for one champion.

Competitor lift #3 (calc.gg stat-sweep graphs; DEPTH spec
``docs/COMPETITOR_LIFT_2026-05-30.md`` "Lift 3"). Thin dashboard wire over
``agents.daemon_slayer.dps_sweep.compute_dps_sweep`` - a read-only loop over
the EXISTING DS auto-attack DPS engine with ONE input swept and everything
else held fixed. NO new compute, NO ENGINE math change, NO schema lift, NO
new dependency; the sweep seam already exists in the engine module (and
``compute_dps_curve`` already sweeps the level axis).

Sibling of ``routes_spike_curve.py`` (snapshot-load + id->slug + 5-min
response cache) and ``routes_cooldown_watch.py`` (cache discipline + error
codes). Where spike-curve plots per-minute TEAM power, ds-sweep plots ONE
champion's DPS against a swept enemy-stat axis (target armor / MR / level) -
the "how does my damage scale vs their armor 0->300" calc.gg read.

Request shape:
  GET /api/ds-sweep?champion=<slug>&axis=armor[&item_ids=ID,ID][&mode=SR]
                    [&level=11][&max=300][&step=25]

  champion : canonical DDragon id ("Caitlyn") OR numeric LCU key (51).
             Numeric keys are resolved to the slug via the DDragon map.
  axis     : armor | mr | level (also accepts target_armor / target_mr).
             Defaults armor. Unknown axis -> 400.
  item_ids : optional comma-separated item ids. When omitted/blank the route
             resolves the champion's canonical archetype build (mirrors
             routes_spike_curve._ARCHETYPE_BUILDS) so the curve is not zeroed
             by an itemless body.
  mode     : SR | ARAM | ARENA | BRAWL. Defaults SR.
  level    : fixed champion level for the resist axes (default 11). Ignored by
             the level axis (it sweeps level). Clamped [1, 18].
  max      : resist-axis sweep ceiling (default 300). Clamped [step, 1000].
             Ignored by the level axis.
  step     : resist-axis sweep step (default 25). Clamped [1, 100]. Ignored by
             the level axis.

Response shape:
  {
    "ok":         true,
    "champion":   "Caitlyn",
    "axis":       "target_armor",
    "mode":       "SR",
    "level":      11,
    "item_ids":   ["3094", "3031", ...],
    "points": [
      {"x": 0.0,   "dps": 240.97, "phase": "mid"},
      {"x": 25.0,  "dps": 205.10, "phase": "mid"},
      ...
    ],
    "count":      <int>,
    "elapsed_ms": <int>,
    "cached":     <bool>
  }

Failure modes:
  - 400  champion param missing/blank, or axis not in {armor, mr, level}.
  - 200  ok=false reason=no_points when the sweep resolves zero points
         (unknown champion / degenerate build - compute_dps_sweep fail-softs).
  - 503  dps_sweep import fails or the DS snapshot is unloadable.

5-min TTL in-process cache keyed on
(champion, axis, sorted_item_ids, mode, level, max, step). Mirrors
routes_cooldown_watch cache discipline exactly. The level axis ignores
max/step in the sweep but they still participate in the key (a no-op vary).

Don't-redo:
  * Y is exactly compute_dps().weighted_dps - the same number RC surfaces
    elsewhere. No re-derivation, no smoothing.
  * The resist axes hold level FIXED at ``level`` (default 11). The level
    axis delegates to compute_dps_curve so the two surfaces agree.
  * When item_ids is blank the route resolves the canonical archetype build
    (NOT an itemless body) so a marksman's armor curve actually scales.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from dashboard._dispatch import equals

log = logging.getLogger("rc.web_dashboard")

# 5-min response TTL mirrors routes_cooldown_watch / routes_spike_curve.
_CACHE_TTL_S = 300.0
_CACHE: dict[tuple, tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()

# Axis shorthand -> canonical compute_dps_sweep axis name.
_AXIS_ALIASES: dict[str, str] = {
    "armor": "target_armor",
    "target_armor": "target_armor",
    "mr": "target_mr",
    "target_mr": "target_mr",
    "level": "level",
}

# Resist-axis sweep defaults + clamp bounds.
_DEFAULT_MAX = 300
_DEFAULT_STEP = 25
_MAX_CEILING = 1000
_MAX_STEP = 100
_DEFAULT_LEVEL = 11

# Canonical per-archetype 6-item builds used when the caller omits item_ids.
# Kept in lockstep with routes_spike_curve._ARCHETYPE_BUILDS (stat-rich cores
# so the curve is not artificially zeroed by a niche pick). All ids present in
# the 16.x DS snapshot.
_ARCHETYPE_BUILDS: dict[str, tuple[str, ...]] = {
    "carry":     ("3094", "3031", "3072", "3036", "3046", "3026"),
    "mage":      ("6655", "3157", "3020", "3089", "3135", "3116"),
    "assassin":  ("6691", "3142", "3814", "3036", "3179", "3026"),
    "tank":      ("3068", "3742", "3110", "3193", "3083", "3001"),
    "bruiser":   ("6630", "3742", "3071", "3053", "3026", "3193"),
    "enchanter": ("3504", "3011", "3107", "3222", "3050", "3001"),
}
_FALLBACK_ARCHETYPE = "carry"

# Lazy snapshot + id->slug map. Re-resolved on first call after a process
# restart so a fresh data_pipeline pull picks up. Same single-process pattern
# as routes_spike_curve.
_SNAPSHOT = None
_SNAPSHOT_LOAD_LOCK = threading.Lock()
_ID_TO_SLUG: dict[int, str] | None = None
_ID_MAP_LOCK = threading.Lock()


def _load_snapshot():
    global _SNAPSHOT
    if _SNAPSHOT is not None:
        return _SNAPSHOT
    with _SNAPSHOT_LOAD_LOCK:
        if _SNAPSHOT is not None:
            return _SNAPSHOT
        from agents.daemon_slayer.data_loader import DataSnapshot
        _SNAPSHOT = DataSnapshot.load()
        return _SNAPSHOT


def _load_id_to_slug() -> dict[int, str]:
    """DDragon ``key`` (int) -> ``id`` (slug, e.g. 'Garen'). Mirrors
    routes_spike_curve._load_id_to_slug; fail-soft to {} on any error."""
    global _ID_TO_SLUG
    if _ID_TO_SLUG is not None:
        return _ID_TO_SLUG
    with _ID_MAP_LOCK:
        if _ID_TO_SLUG is not None:
            return _ID_TO_SLUG
        mapping: dict[int, str] = {}
        try:
            path = (
                Path(__file__).resolve().parent.parent
                / "data" / "meta" / "ddragon_champions.json"
            )
            raw = json.loads(path.read_text(encoding="utf-8"))
            data = raw.get("data", raw)
            for entry in data.values():
                if not isinstance(entry, dict):
                    continue
                key = entry.get("key")
                slug = entry.get("id")
                if not (key and slug):
                    continue
                try:
                    mapping[int(key)] = str(slug)
                except (TypeError, ValueError):
                    continue
        except Exception as exc:  # noqa: BLE001
            log.warning("ds-sweep: id_to_slug load failed: %s", exc)
        _ID_TO_SLUG = mapping
        return mapping


def _resolve_champion(raw: str) -> str:
    """Accept either a slug or a numeric LCU key; return the slug.

    A purely-numeric token is resolved via the DDragon id->slug map (so the
    frontend may pass cs.my_champion directly). A non-numeric token is taken
    as a slug verbatim. Unresolvable numerics fall through as the original
    string (compute_dps_sweep then fail-softs to no_points)."""
    s = (raw or "").strip()
    if not s:
        return ""
    if s.isdigit():
        slug = _load_id_to_slug().get(int(s))
        return slug or s
    return s


def _resolve_archetype(slug: str) -> str:
    """Canonical archetype primary for ``slug`` via the project resolver.
    Falls back to ``carry`` when unmapped. Mirrors
    routes_spike_curve._resolve_archetype."""
    try:
        from core.archetype_picks import get_archetype_for
        entry = get_archetype_for(slug) or {}
        primary = str(entry.get("primary") or "").lower().strip()
        if primary in _ARCHETYPE_BUILDS:
            return primary
    except Exception as exc:  # noqa: BLE001
        log.debug("ds-sweep: archetype resolve failed for %s: %s", slug, exc)
    return _FALLBACK_ARCHETYPE


def _parse_item_ids(raw: str) -> list[str]:
    """Split a comma-separated item-id list, strip blanks."""
    if not raw:
        return []
    out: list[str] = []
    for part in raw.split(","):
        s = part.strip()
        if s:
            out.append(s)
    return out


def _parse_int(raw: str, default: int, lo: int, hi: int) -> int:
    """Parse an int query arg; clamp to [lo, hi]; fall to default."""
    if not raw:
        return default
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return default
    return max(lo, min(n, hi))


def _axis_values(axis: str, max_v: int, step: int) -> list[float] | None:
    """Build the explicit sweep value list for the resist axes; None for the
    level axis (compute_dps_sweep then uses the default level curve)."""
    if axis == "level":
        return None
    if step <= 0:
        step = _DEFAULT_STEP
    return [float(v) for v in range(0, max_v + 1, step)]


def _cache_key(
    champion: str, axis: str, item_ids: list[str], mode: str,
    level: int, max_v: int, step: int,
) -> tuple:
    return (champion, axis, tuple(sorted(item_ids)), mode, level, max_v, step)


def _compute(
    champion: str, axis: str, item_ids: list[str], mode: str,
    level: int, max_v: int, step: int,
) -> dict:
    """Build the response payload from scratch (no cache)."""
    from agents.daemon_slayer.dps_sweep import compute_dps_sweep

    snapshot = _load_snapshot()
    # Resolve a canonical build when the caller omitted item_ids so a
    # marksman's armor curve actually scales (an itemless body is near-flat).
    used_items: list[str] = list(item_ids)
    if not used_items:
        arch = _resolve_archetype(champion)
        used_items = list(_ARCHETYPE_BUILDS.get(arch, _ARCHETYPE_BUILDS[_FALLBACK_ARCHETYPE]))

    result = compute_dps_sweep(
        snapshot,
        champion,
        item_ids=used_items,
        mode=mode,
        axis=axis,
        axis_values=_axis_values(axis, max_v, step),
        level=level,
    )
    points = [
        {"x": p.x, "dps": round(float(p.weighted_dps), 2), "phase": p.phase}
        for p in result.points
    ]
    if not points:
        return {
            "ok":       False,
            "reason":   "no_points",
            "champion": champion,
            "axis":     axis,
            "mode":     mode,
            "level":    level,
            "item_ids": used_items,
            "points":   [],
            "count":    0,
        }
    return {
        "ok":       True,
        "champion": champion,
        "axis":     axis,
        "mode":     mode,
        "level":    result.level,
        "item_ids": used_items,
        "points":   points,
        "count":    len(points),
    }


def _serve_ds_sweep(h) -> None:
    """GET /api/ds-sweep handler."""
    t0 = time.time()
    try:
        qs = parse_qs(urlparse(h.path).query or "", keep_blank_values=True)
        if "champion" not in qs:
            h._send(400, json.dumps({
                "ok":    False,
                "error": "champion param required",
            }).encode("utf-8"), "application/json")
            return

        champ_raw = (qs.get("champion") or [""])[0].strip()
        champion = _resolve_champion(champ_raw)
        if not champion:
            h._send(400, json.dumps({
                "ok":    False,
                "error": "champion param required",
            }).encode("utf-8"), "application/json")
            return

        axis_raw = (qs.get("axis") or ["armor"])[0].strip().lower() or "armor"
        axis = _AXIS_ALIASES.get(axis_raw)
        if axis is None:
            h._send(400, json.dumps({
                "ok":        False,
                "error":     f"unsupported axis {axis_raw!r}",
                "supported": ["armor", "mr", "level"],
            }).encode("utf-8"), "application/json")
            return

        mode = (qs.get("mode") or ["SR"])[0].upper().strip() or "SR"
        item_ids = _parse_item_ids((qs.get("item_ids") or [""])[0].strip())
        level = _parse_int((qs.get("level") or [""])[0].strip(),
                           _DEFAULT_LEVEL, 1, 18)
        max_v = _parse_int((qs.get("max") or [""])[0].strip(),
                           _DEFAULT_MAX, _MAX_STEP, _MAX_CEILING)
        step = _parse_int((qs.get("step") or [""])[0].strip(),
                          _DEFAULT_STEP, 1, _MAX_STEP)

        key = _cache_key(champion, axis, item_ids, mode, level, max_v, step)
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
            payload = _compute(champion, axis, item_ids, mode,
                               level, max_v, step)
        except ImportError as exc:
            log.warning("api/ds-sweep import: %s", exc)
            h._send(503, json.dumps({
                "ok":    False,
                "error": "DS engine unavailable",
            }).encode("utf-8"), "application/json")
            return
        except Exception as exc:  # noqa: BLE001
            log.warning("api/ds-sweep compute: %s", exc)
            h._send(503, json.dumps({
                "ok":    False,
                "error": "DS engine compute failed",
            }).encode("utf-8"), "application/json")
            return

        with _CACHE_LOCK:
            _CACHE[key] = (now, dict(payload))

        payload["cached"] = False
        payload["elapsed_ms"] = int((time.time() - t0) * 1000)
        h._send(200, json.dumps(payload).encode("utf-8"),
                "application/json")

    except Exception as exc:  # noqa: BLE001
        log.warning("api/ds-sweep: %s", exc)
        try:
            h._send(500, json.dumps({
                "ok": False, "error": str(exc)[:200],
            }).encode("utf-8"), "application/json")
        except Exception:  # noqa: BLE001
            pass


def _reset_caches() -> None:
    """Test-only: clear response cache."""
    with _CACHE_LOCK:
        _CACHE.clear()


GET_ROUTES = [
    (equals("/api/ds-sweep"), _serve_ds_sweep),
]

POST_ROUTES: list = []
