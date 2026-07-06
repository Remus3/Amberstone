"""Per-mode minimap district substrate (ZOI plan Wave 1, spec A).

Pure module: no numpy, no I/O at call time beyond one lazy, cached config
load per (mode, config_dir). Turns the single outer minimap square into a
labelled district partition so presence counters, API fusion and the macro
decision tree (Wave 2 consumers) can reason about WHERE dots are.

Coordinate frame: box-fraction ``[0, 1]`` within the minimap crop, y-down
image convention, UNFLIPPED (blue base bottom-left) - the same frame as
``core.minimap_blob_detect.detect_team_dots`` dots and the legacy
``core.zoi_influence._action_quadrant`` prototype. A flipped HUD anchors
the minimap left (core/minimap_geometry.py:104-108); ``district_of``
de-flips by mirroring x -> 1 - x BEFORE any lookup.

Configs live in ``config/minimap_grids/<mode>.json`` (mode lowercased).
Missing / corrupt files degrade to an EMBEDDED minimal config; only modes
that genuinely have no grid (tft) load as ``None``. Every public function
follows the fail-soft contract of ``core.zoi_influence``: never raises on
any input - degrade to a fallback id / ``[]`` / ``set()`` / ``None``.

SR grid note: the operator-approved 13-district SR grid keeps the LEGACY
convention of ``_action_quadrant`` (core/zoi_influence.py:177-203) where
the base-to-base anti-diagonal corridor is labelled "river" (top_river
y < 0.5, bot_river y >= 0.5). The 9 legacy readable labels are each
covered by at least one district's ``legacy_label`` (parity oracle in
tests/test_minimap_districts.py).
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config" / "minimap_grids"

#: Universal stub fallback id - returned for modes with no grid (tft),
#: unknown modes, and as the last-resort escape hatch of ``district_of``.
FALLBACK_DISTRICT_ID = "map"

_MAX_GRID_CELLS = 24  # sanity cap for grid_hint cols/rows


@dataclass(frozen=True)
class District:
    """One labelled minimap region.

    ``poly`` verts are ``(x, y)`` box-fractions in the UNFLIPPED frame.
    ``adjacent`` are walkable neighbours; ``shortcuts`` are river-gank
    routes (both count as adjacency for ``reachable``). ``legacy_label``
    is the ``_QUADRANT_READABLE`` label this district corresponds to
    (SR only; None elsewhere). Multiple districts may share one.
    """

    id: str
    label: str
    role: str  # lane/river/jungle/base/mid/bridge/brush/cell/map
    poly: tuple = field(default_factory=tuple)
    adjacent: tuple = field(default_factory=tuple)
    shortcuts: tuple = field(default_factory=tuple)
    legacy_label: Optional[str] = None


@dataclass(frozen=True)
class GridConfig:
    """A mode's full district grid. ``grid_hint`` (e.g. ``{"cols": 3,
    "rows": 3}``) marks cell-derived grids (Arena); its cells are also
    materialized into ``districts`` at load time."""

    mode: str
    districts: tuple = field(default_factory=tuple)
    grid_hint: Optional[dict] = None


# --- embedded minimal fallbacks (used when a config file is missing/corrupt) --

def _whole_map_config(district_id, label):
    return {
        "districts": [
            {
                "id": district_id,
                "label": label,
                "role": "map",
                "poly": [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]],
                "adjacent": [],
                "shortcuts": [],
                "legacy_label": None,
            }
        ]
    }


_EMBEDDED = {
    "sr": _whole_map_config("sr_map", "Summoner's Rift"),
    "aram": _whole_map_config("aram_map", "Howling Abyss"),
    "brawl": _whole_map_config("brawl_map", "Brawl map"),
    "arena": {"grid_hint": {"cols": 3, "rows": 3}, "districts": []},
    "tft": None,  # no spatial grid by design
}

_CACHE: dict = {}


def _reset_cache():
    """Test seam: drop every cached grid."""
    _CACHE.clear()


# --- parsing -------------------------------------------------------------------

def _clamp01(v):
    return 0.0 if v < 0.0 else (1.0 if v > 1.0 else v)


def _district_from_dict(entry):
    """Parse one district entry; None (skip) on any malformed shape."""
    try:
        if not isinstance(entry, dict):
            return None
        did = entry.get("id")
        if not isinstance(did, str) or not did:
            return None
        verts = []
        for pair in entry.get("poly") or ():
            x = float(pair[0])
            y = float(pair[1])
            if not (math.isfinite(x) and math.isfinite(y)):
                return None
            verts.append((_clamp01(x), _clamp01(y)))
        if len(verts) < 3:
            return None
        adjacent = tuple(
            s for s in (entry.get("adjacent") or ()) if isinstance(s, str)
        )
        shortcuts = tuple(
            s for s in (entry.get("shortcuts") or ()) if isinstance(s, str)
        )
        label = entry.get("label")
        role = entry.get("role")
        legacy = entry.get("legacy_label")
        return District(
            id=did,
            label=label if isinstance(label, str) else did,
            role=role if isinstance(role, str) else "map",
            poly=tuple(verts),
            adjacent=adjacent,
            shortcuts=shortcuts,
            legacy_label=legacy if isinstance(legacy, str) else None,
        )
    except Exception:  # noqa: BLE001 - fail-soft contract: never raises
        return None


def _cells_from_hint(hint):
    """Materialize grid_hint cells as District rows (ring+center labels)."""
    try:
        cols = int(hint.get("cols", 0))
        rows = int(hint.get("rows", 0))
    except Exception:  # noqa: BLE001 - fail-soft contract: never raises
        return []
    if not (0 < cols <= _MAX_GRID_CELLS and 0 < rows <= _MAX_GRID_CELLS):
        return []
    cells = []
    for row in range(rows):
        for col in range(cols):
            cid = f"cell_{col}_{row}"
            x0, x1 = col / cols, (col + 1) / cols
            y0, y1 = row / rows, (row + 1) / rows
            adj = []
            if col > 0:
                adj.append(f"cell_{col - 1}_{row}")
            if col < cols - 1:
                adj.append(f"cell_{col + 1}_{row}")
            if row > 0:
                adj.append(f"cell_{col}_{row - 1}")
            if row < rows - 1:
                adj.append(f"cell_{col}_{row + 1}")
            is_center = (
                cols % 2 == 1 and rows % 2 == 1
                and col == cols // 2 and row == rows // 2
            )
            cells.append(
                District(
                    id=cid,
                    label="center" if is_center else f"ring c{col} r{row}",
                    role="cell",
                    poly=((x0, y0), (x1, y0), (x1, y1), (x0, y1)),
                    adjacent=tuple(adj),
                    shortcuts=(),
                    legacy_label=None,
                )
            )
    return cells


def _grid_from_dict(mode, raw):
    """Build a GridConfig from a raw config dict; None if it yields no grid."""
    if not isinstance(raw, dict):
        return None
    hint = raw.get("grid_hint")
    if not isinstance(hint, dict):
        hint = None
    districts = []
    districts_raw = raw.get("districts")
    if isinstance(districts_raw, list):
        for entry in districts_raw:
            d = _district_from_dict(entry)
            if d is not None:
                districts.append(d)
    if hint is not None:
        districts.extend(_cells_from_hint(hint))
    if not districts:
        return None
    return GridConfig(mode=mode, districts=tuple(districts), grid_hint=hint)


def _declares_no_grid(raw):
    """True when a parsed config EXPLICITLY declares no grid (tft-style)."""
    if not isinstance(raw, dict):
        return False
    return raw.get("districts") in (None, []) and not raw.get("grid_hint")


def load_grid(mode, config_dir=None):
    """Load (cached) the district grid for ``mode``.

    Falls back to the embedded minimal config when the file is missing or
    corrupt. Returns None only for modes with no grid at all (tft,
    unknown modes). Never raises.
    """
    try:
        key_mode = str(mode).strip().lower()
        base = Path(config_dir) if config_dir is not None else _CONFIG_DIR
        cache_key = (key_mode, str(base))
        if cache_key in _CACHE:
            return _CACHE[cache_key]
        grid = _load_uncached(key_mode, base)
        _CACHE[cache_key] = grid
        return grid
    except Exception:  # noqa: BLE001 - fail-soft contract: never raises
        return None


def _load_uncached(mode, base):
    raw = None
    try:
        path = base / (mode + ".json")
        if path.is_file():
            raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - fail-soft contract: never raises
        raw = None
    if isinstance(raw, dict):
        grid = _grid_from_dict(mode, raw)
        if grid is not None:
            return grid
        if _declares_no_grid(raw):
            return None  # legit no-grid declaration, not corruption
    return _grid_from_dict(mode, _EMBEDDED.get(mode))


# --- geometry -------------------------------------------------------------------

def _point_in_poly(x, y, poly):
    """Ray-casting point-in-polygon (boundary handling is best-effort; the
    nearest-centroid fallback in ``district_of`` absorbs edge cases)."""
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y):
            x_cross = (xj - xi) * (y - yi) / (yj - yi) + xi
            if x < x_cross:
                inside = not inside
        j = i
    return inside


def _poly_centroid(poly):
    if not poly:
        return None
    sx = sy = 0.0
    for (px, py) in poly:
        sx += px
        sy += py
    return (sx / len(poly), sy / len(poly))


def _cell_id_at(x, y, hint):
    try:
        cols = int(hint.get("cols", 0))
        rows = int(hint.get("rows", 0))
    except Exception:  # noqa: BLE001 - fail-soft contract: never raises
        return None
    if not (0 < cols <= _MAX_GRID_CELLS and 0 < rows <= _MAX_GRID_CELLS):
        return None
    col = min(cols - 1, int(x * cols))
    row = min(rows - 1, int(y * rows))
    return f"cell_{col}_{row}"


def _fallback_id(grid):
    if grid is not None and grid.districts:
        return grid.districts[0].id
    return FALLBACK_DISTRICT_ID


# --- public lookups ---------------------------------------------------------------

def district_of(x_frac, y_frac, mode, flip=False):
    """TOTAL district lookup - always returns a district id string.

    De-flips on X first (flip=True mirrors x -> 1 - x), clamps to [0, 1],
    then first-match point-in-polygon in config order (priority), then a
    nearest-centroid fallback. Non-finite/garbage input -> the mode's
    fallback district id. Never raises.
    """
    try:
        grid = load_grid(mode)
        try:
            x = float(x_frac)
            y = float(y_frac)
        except (TypeError, ValueError):
            return _fallback_id(grid)
        if not (math.isfinite(x) and math.isfinite(y)):
            return _fallback_id(grid)
        if flip:
            x = 1.0 - x
        x = _clamp01(x)
        y = _clamp01(y)
        if grid is None or not grid.districts:
            return FALLBACK_DISTRICT_ID
        if grid.grid_hint:
            cid = _cell_id_at(x, y, grid.grid_hint)
            if cid is not None:
                return cid
        for d in grid.districts:
            if len(d.poly) >= 3 and _point_in_poly(x, y, d.poly):
                return d.id
        best = None
        best_d2 = None
        for d in grid.districts:
            c = _poly_centroid(d.poly)
            if c is None:
                continue
            d2 = (x - c[0]) ** 2 + (y - c[1]) ** 2
            if best_d2 is None or d2 < best_d2:
                best, best_d2 = d.id, d2
        return best if best is not None else _fallback_id(grid)
    except Exception:  # noqa: BLE001 - fail-soft contract: never raises
        return FALLBACK_DISTRICT_ID


def _find(district_id, mode):
    grid = load_grid(mode)
    if grid is None:
        return None
    for d in grid.districts:
        if d.id == district_id:
            return d
    return None


def neighbors(district_id, mode):
    """Adjacent district ids plus river-gank shortcuts (deduped). [] on
    unknown district/mode. Never raises."""
    try:
        d = _find(district_id, mode)
        if d is None:
            return []
        out = list(d.adjacent)
        for s in d.shortcuts:
            if s not in out:
                out.append(s)
        return out
    except Exception:  # noqa: BLE001 - fail-soft contract: never raises
        return []


def reachable(district_id, mode, hops=1):
    """Set of district ids within ``hops`` adjacency hops of
    ``district_id`` (inclusive of the start; shortcuts count as
    adjacency). Empty set on unknown district/mode. Never raises."""
    try:
        grid = load_grid(mode)
        if grid is None or not grid.districts:
            return set()
        by_id = {d.id: d for d in grid.districts}
        if district_id not in by_id:
            return set()
        try:
            n = max(0, int(hops))
        except (TypeError, ValueError):
            n = 1
        seen = {district_id}
        frontier = {district_id}
        for _ in range(n):
            nxt = set()
            for did in frontier:
                d = by_id[did]
                for nb in list(d.adjacent) + list(d.shortcuts):
                    if nb in by_id and nb not in seen:
                        seen.add(nb)
                        nxt.add(nb)
            if not nxt:
                break
            frontier = nxt
        return seen
    except Exception:  # noqa: BLE001 - fail-soft contract: never raises
        return set()


def district_bbox_frac(district_id, mode):
    """Axis-aligned (x0, y0, x1, y1) bounding box of the district polygon
    in box-fractions, or None on unknown district/mode. Never raises."""
    try:
        d = _find(district_id, mode)
        if d is None or not d.poly:
            return None
        xs = [p[0] for p in d.poly]
        ys = [p[1] for p in d.poly]
        return (min(xs), min(ys), max(xs), max(ys))
    except Exception:  # noqa: BLE001 - fail-soft contract: never raises
        return None
