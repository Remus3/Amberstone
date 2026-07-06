# arch: fluid oil-and-water DMZ frontier from signed influence bubbles | section=core | frozen=no
"""Fluid DMZ frontier extraction for the ZOI influence layer (spec F, wave 3b).

``field_dmz(bubbles)`` turns a set of signed influence sources (ally bubbles
push POSITIVE, enemy bubbles push NEGATIVE) into the fluid "oil-and-water"
demarcation the overlay paints instead of the legacy straight bisector: a coarse
grid is sampled for the summed signed influence, the ZERO-CROSSING frontier
(where ally and enemy influence exactly cancel) is traced as an ordered polyline
path, and a band width is derived from the local field gradient (a shallow
gradient = a wide contested no-mans-land, a steep gradient = a sharp frontier).

CONTRACT (zoi.dmz):
    {"path": [[x, y], ...] (>= 2 points, box-fraction [0,1]),
     "band_w_frac": float} or None.
DEGENERATE (one team absent, < 2 crossings, all-zero field) -> None, so the
render falls back to the byte-identical legacy straight "demarcation" line.

INPUT bubble shape (grep-confirmed core/zoi_influence.py:290-296):
    {"team": "blue"|"red", "cx": float, "cy": float, "r_frac": float,
     "weight": float}
This module SIGNS it: blue (ally) -> +weight source, red (enemy) -> -weight.

DESIGN:
  - 100% PURE + stateless plain python: NO numpy, NO I/O, fail-soft, NEVER
    raises. Malformed bubbles are skipped; if either team is absent after
    filtering, or the field never crosses zero, returns None.
  - Coords are BOX-FRACTION [0,1], origin top-left - the same basis as the
    bubbles / minimap dots.
  - Influence model: each source contributes weight / (1 + (d / sigma)^2) at a
    sample point distance d away (a smooth, bounded, radius-scaled kernel). The
    signed sum over all sources is the field; its zero contour is the DMZ.

ASCII only (repo hard rule). No em-dashes.
"""
from __future__ import annotations

# --- tunables -------------------------------------------------------------
_GRID = 24              # sample resolution per axis (coarse, pure-python cost)
_SIGMA_FLOOR = 0.08     # min kernel spread (box-fraction) so a tiny r stays smooth
_SIGMA_FROM_R = 1.5     # kernel spread = _SIGMA_FROM_R * bubble r_frac (>= floor)
_EPS = 1e-9


def _num(v):
    """Coerce to a finite float, or None if not a real number (bools rejected)."""
    if isinstance(v, bool):
        return None
    if not isinstance(v, (int, float)):
        return None
    f = float(v)
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f


def _clamp(v, lo, hi):
    if v < lo:
        return lo
    if v > hi:
        return hi
    return v


def _valid_source(b):
    """Normalize a raw bubble to a signed source {sx, sy, sigma, sw} or None.

    sw is SIGNED: ally (blue) positive, enemy (red) negative. Zero-weight or
    malformed bubbles are dropped (return None)."""
    if not isinstance(b, dict):
        return None
    team = b.get("team")
    if team not in ("blue", "red"):
        return None
    cx = _num(b.get("cx"))
    cy = _num(b.get("cy"))
    w = _num(b.get("weight"))
    if cx is None or cy is None or w is None:
        return None
    if w <= 0.0:
        return None
    r = _num(b.get("r_frac"))
    if r is None or r <= 0.0:
        r = _SIGMA_FLOOR / _SIGMA_FROM_R
    sigma = max(_SIGMA_FROM_R * r, _SIGMA_FLOOR)
    sign = 1.0 if team == "blue" else -1.0
    return {
        "sx": _clamp(cx, 0.0, 1.0),
        "sy": _clamp(cy, 0.0, 1.0),
        "sigma": sigma,
        "sw": sign * w,
    }


def _field_at(x, y, sources) -> float:
    """Summed SIGNED influence at (x,y): sum sw / (1 + (d/sigma)^2)."""
    total = 0.0
    for s in sources:
        dx = x - s["sx"]
        dy = y - s["sy"]
        d2 = dx * dx + dy * dy
        sig = s["sigma"]
        total += s["sw"] / (1.0 + d2 / (sig * sig))
    return total


def field_dmz(bubbles):
    """Extract the fluid DMZ frontier from signed influence bubbles.

    Returns {"path": [[x,y],...], "band_w_frac": float} or None (degenerate).
    Pure + fail-soft: never raises on any input.
    """
    try:
        return _field_dmz_impl(bubbles)
    except Exception:  # noqa: BLE001 - pure fail-soft, never raise
        return None


def _field_dmz_impl(bubbles):
    if not bubbles or not isinstance(bubbles, (list, tuple)):
        return None
    sources = []
    have_ally = False
    have_enemy = False
    for b in bubbles:
        s = _valid_source(b)
        if s is None:
            continue
        sources.append(s)
        if s["sw"] > 0.0:
            have_ally = True
        else:
            have_enemy = True
    # DEGENERATE: need BOTH teams present (a frontier needs two sides).
    if not sources or not have_ally or not have_enemy:
        return None

    n = _GRID
    step = 1.0 / (n - 1)
    # Sample the field on the grid once.
    grid = [[0.0] * n for _ in range(n)]
    for j in range(n):
        y = j * step
        row = grid[j]
        for i in range(n):
            x = i * step
            row[i] = _field_at(x, y, sources)

    # Extract the zero-crossing frontier. For each grid ROW, find where the
    # field changes sign horizontally and interpolate the crossing x. This
    # yields one ordered-by-y polyline sweeping top->bottom (a fluid frontier
    # that bends around bubbles), which is the natural oil-and-water boundary
    # for a blue-bottom/red-top style split. Also do the COLUMN sweep and keep
    # whichever axis produced more crossings (handles left-right splits too).
    row_path = _row_crossings(grid, n, step)
    col_path = _col_crossings(grid, n, step)

    if len(row_path) >= len(col_path):
        path = row_path
    else:
        path = col_path

    if len(path) < 2:
        return None

    band = _band_width(path, sources)
    # Round for a stable, compact payload (mirrors zoi_influence rounding).
    rpath = [[round(_clamp(x, 0.0, 1.0), 4), round(_clamp(y, 0.0, 1.0), 4)]
             for (x, y) in path]
    return {"path": rpath, "band_w_frac": round(band, 4)}


def _interp_zero(a, b):
    """Fraction t in [0,1] where a linear a->b crosses zero. a,b opposite sign."""
    denom = a - b
    if abs(denom) < _EPS:
        return 0.5
    return _clamp(a / denom, 0.0, 1.0)


def _row_crossings(grid, n, step):
    """One crossing per row (scan x left->right), ordered by y (top->bottom)."""
    path = []
    for j in range(n):
        y = j * step
        row = grid[j]
        found = None
        for i in range(n - 1):
            a = row[i]
            b = row[i + 1]
            if (a > 0.0) != (b > 0.0) and (a != 0.0 or b != 0.0):
                t = _interp_zero(a, b)
                found = (i + t) * step
                break
        if found is not None:
            path.append((found, y))
    return path


def _col_crossings(grid, n, step):
    """One crossing per column (scan y top->bottom), ordered by x (left->right)."""
    path = []
    for i in range(n):
        x = i * step
        found = None
        for j in range(n - 1):
            a = grid[j][i]
            b = grid[j + 1][i]
            if (a > 0.0) != (b > 0.0) and (a != 0.0 or b != 0.0):
                t = _interp_zero(a, b)
                found = (j + t) * step
                break
        if found is not None:
            path.append((x, found))
    return path


def _band_width(path, sources):
    """Band width (box-fraction) from the local field gradient along the path.

    A shallow gradient near the frontier = a wide contested band; a steep one =
    a sharp line. We probe the field a small delta on each side of the mean
    frontier point, normal-ish to the sweep, and map the reciprocal gradient
    magnitude to a bounded band width."""
    if not path:
        return 0.1
    mx = sum(p[0] for p in path) / len(path)
    my = sum(p[1] for p in path) / len(path)
    delta = 0.03
    # numeric gradient magnitude at the frontier centroid
    fx1 = _field_at(_clamp(mx + delta, 0.0, 1.0), my, sources)
    fx0 = _field_at(_clamp(mx - delta, 0.0, 1.0), my, sources)
    fy1 = _field_at(mx, _clamp(my + delta, 0.0, 1.0), sources)
    fy0 = _field_at(mx, _clamp(my - delta, 0.0, 1.0), sources)
    gx = (fx1 - fx0) / (2.0 * delta)
    gy = (fy1 - fy0) / (2.0 * delta)
    grad = (gx * gx + gy * gy) ** 0.5
    if grad < _EPS:
        return 0.5  # essentially flat -> a wide, ambiguous band
    # total signed magnitude scales the field, so normalize band by it: a
    # field-relative band. reciprocal gradient, bounded to a sane [0.02, 0.5].
    mag = sum(abs(s["sw"]) for s in sources) or 1.0
    band = (mag / grad) * 0.02
    return _clamp(band, 0.02, 0.5)
