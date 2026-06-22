"""Pure Zone-of-Influence shading from per-team minimap dots (item 567 slice 3).

Given the slice-2 minimap dots (per-team colored-blob centroids in box-fraction
[0,1] space) this computes the ZONE OF INFLUENCE overlay payload: one shaded
"bubble" per dot, a team DEMARCATION line (the contested frontier), and a
MAP-CONTROL summary (ally control %, the live action quadrant, a coach line).
It is the data layer behind the /api/state.zoi shading the overlay renders.

Design notes:
  - 100% PURE + stateless plain python: NO numpy, NO I/O, fail-soft, NEVER
    raises. A malformed dot is skipped; an all-malformed / empty input -> None.
  - Coords are BOX-FRACTION [0,1], origin top-left, x right, y down - the same
    basis as minimap_dots.x_frac / y_frac (see core/minimap_blob_detect.py).

HONEST SCOPE (mirror core/minimap_blob_detect.py:16-19): the Live Client API
exposes ONLY my own data - my level / gold / game_time. It does NOT expose
enemy levels, enemy/ally alive-dead, or enemy gold (the team lists are champion
NAMES only). So per-team STRENGTH here is grounded ONLY in (a) per-team on-map
PRESENCE (px * confidence from the blob detector), (b) MY level spikes (6/11/16
scale ALLY bubbles), and (c) game_time (a generic mid/late-game scale on ENEMY
bubbles, since we cannot see their real power). The control % is a presence
ratio, not a true gold/strength lead. This is a map-control heuristic, not a
win-probability model.

ASCII only (repo hard rule). No em-dashes.
"""
from __future__ import annotations

# --- tunables (box-fraction radii derived from the 312px design minimap) ---
_BOX_PX = 312.0
_R_MIN_FRAC = 15.0 / 312.0   # floor bubble radius (fraction of box width)
_R_MAX_FRAC = 60.0 / 312.0   # ceiling bubble radius
_ALLY_SPIKE_STEP = 0.15      # +15% ally power per crossed spike level
_ENEMY_TIME_GAIN = 0.20      # generic enemy power gain across the game
_SPIKE_LEVELS = (6, 11, 16)
_TIME_FULL_S = 1200.0        # game_time at which the time-scalar saturates to 1


def _num(v):
    """Coerce to a finite float, or None if not a real number."""
    if isinstance(v, bool):
        return None
    if not isinstance(v, (int, float)):
        return None
    f = float(v)
    if f != f or f in (float("inf"), float("-inf")):  # NaN / inf
        return None
    return f


def _clamp(v, lo, hi):
    if v < lo:
        return lo
    if v > hi:
        return hi
    return v


def _time_scalar(game_time_s) -> float:
    """game_time normalized to [0,1] (saturates at 20 min). 0.0 on bad input."""
    t = _num(game_time_s)
    if t is None:
        return 0.0
    return _clamp(t / _TIME_FULL_S, 0.0, 1.0)


def _ally_power(my_level, T) -> float:
    """Ally power multiplier (>=1.0). +15% per crossed spike level (6/11/16).
    `T` accepted for signature symmetry with _enemy_power; ally scales on spikes
    only. my_level None -> 1.0."""
    lv = _num(my_level)
    if lv is None:
        return 1.0
    crossed = sum(1 for s in _SPIKE_LEVELS if lv >= s)
    return 1.0 + _ALLY_SPIKE_STEP * crossed


def _enemy_power(T) -> float:
    """Enemy power multiplier (>=1.0): a generic mid/late-game gain (we cannot
    see real enemy power, so it grows with game_time only)."""
    return 1.0 + T * _ENEMY_TIME_GAIN


def _bubble_radius_frac(px, confidence, power, T) -> float:
    """Radius (box-fraction) for one dot. W=px*confidence drives the base size;
    `power` (spike/time) and the time term inflate it; clamped to [15,60] px."""
    p = _num(px)
    c = _num(confidence)
    if p is None or c is None:
        return _R_MIN_FRAC
    W = p * c
    pw = power if (isinstance(power, (int, float)) and power == power) else 1.0
    r_px = 15.0 + (W * 0.1) * pw * (1.0 + T)
    r_px = _clamp(r_px, 15.0, 60.0)
    return r_px / _BOX_PX


def _weighted_centroid(dots):
    """(cx, cy, Wtot) weighted by W=px*confidence over already-validated dots.
    (0.0, 0.0, 0.0) on empty / zero total weight."""
    wx = wy = wt = 0.0
    for d in dots:
        W = d["_w"]
        wx += W * d["x_frac"]
        wy += W * d["y_frac"]
        wt += W
    if wt <= 0.0:
        return (0.0, 0.0, 0.0)
    return (wx / wt, wy / wt, wt)


def _clip_line_to_box(px, py, dx, dy):
    """Clip the infinite line through (px,py) with direction (dx,dy) to the unit
    box [0,1]^2 via Liang-Barsky on the parametric form. Returns ((x1,y1),(x2,y2))
    two edge points, or None if the line misses / is degenerate."""
    if dx == 0.0 and dy == 0.0:
        return None
    # parametric: P + t*D, t in (-inf, inf). Liang-Barsky against 4 edges.
    t_min = -1e18
    t_max = 1e18
    p = (-dx, dx, -dy, dy)
    q = (px - 0.0, 1.0 - px, py - 0.0, 1.0 - py)
    for pi, qi in zip(p, q):
        if pi == 0.0:
            if qi < 0.0:
                return None  # parallel and outside
            continue
        t = qi / pi
        if pi < 0.0:
            if t > t_min:
                t_min = t
        else:
            if t < t_max:
                t_max = t
    if t_min > t_max:
        return None
    x1 = _clamp(px + t_min * dx, 0.0, 1.0)
    y1 = _clamp(py + t_min * dy, 0.0, 1.0)
    x2 = _clamp(px + t_max * dx, 0.0, 1.0)
    y2 = _clamp(py + t_max * dy, 0.0, 1.0)
    return ((x1, y1), (x2, y2))


def _demarcation(ca, ce, wa, we):
    """Weighted perpendicular bisector between ally centroid `ca` and enemy
    centroid `ce`, clipped to the unit box. None on a zero-presence team or a
    degenerate (coincident) centroid pair."""
    if wa <= 0.0 or we <= 0.0:
        return None
    vx = ce[0] - ca[0]
    vy = ce[1] - ca[1]
    if abs(vx) < 1e-9 and abs(vy) < 1e-9:
        return None  # centroids coincide -> no meaningful frontier
    # split point along Ca->Ce proportional to ally share
    frac = wa / (wa + we)
    px = ca[0] + vx * frac
    py = ca[1] + vy * frac
    # line direction perpendicular to (vx,vy)
    perp = (-vy, vx)
    clipped = _clip_line_to_box(px, py, perp[0], perp[1])
    if clipped is None:
        return None
    (x1, y1), (x2, y2) = clipped
    # ally_side: which side of the Ca->Ce axis the ally centroid sits, mapped to
    # an edge label by the DOMINANT axis of the Ca->Ce vector.
    if abs(vx) >= abs(vy):
        ally_side = "left" if ca[0] <= ce[0] else "right"
    else:
        ally_side = "top" if ca[1] <= ce[1] else "bottom"
    return {
        "x1": round(x1, 4), "y1": round(y1, 4),
        "x2": round(x2, 4), "y2": round(y2, 4),
        "ally_side": ally_side,
    }


def _action_quadrant(cx, cy) -> str:
    """Map the global weighted centroid to one of the 9 enum labels. A diagonal
    RIVER band (the SR river runs corner-to-corner) takes priority near the
    map center; otherwise a 3x3 threshold grid. Always returns a 9-set value."""
    # base-corner pull (bottom-left = ally fountain, top-right = enemy fountain
    # on the default blue-side orientation)
    if cx <= 0.18 and cy >= 0.82:
        return "ally_base"
    if cx >= 0.82 and cy <= 0.18:
        return "enemy_base"
    # river corridor: the anti-diagonal x + y ~ 1 (top-right .. bottom-left).
    # split into top_river (upper half) vs bot_river (lower half).
    if abs((cx) - (1.0 - cy)) <= 0.16 and 0.18 < cx < 0.82:
        return "top_river" if cy < 0.5 else "bot_river"
    # 3x3 grid by thirds
    col = 0 if cx < 1.0 / 3.0 else (1 if cx < 2.0 / 3.0 else 2)
    row = 0 if cy < 1.0 / 3.0 else (1 if cy < 2.0 / 3.0 else 2)
    if col == 1 and row == 1:
        return "mid"
    if row == 0:  # top band
        return "top_left" if col == 0 else "top_right"
    if row == 2:  # bottom band
        return "bot_left" if col == 0 else "bot_right"
    # middle row, side columns -> fold into nearest horizontal quadrant
    if col == 0:
        return "bot_left" if cy >= 0.5 else "top_left"
    return "bot_right" if cy >= 0.5 else "top_right"


_QUADRANT_READABLE = {
    "top_left": "top lane / topside",
    "top_right": "enemy topside",
    "bot_left": "ally botside",
    "bot_right": "bot lane / botside",
    "mid": "mid lane",
    "top_river": "top river",
    "bot_river": "bot river / dragon",
    "ally_base": "ally base",
    "enemy_base": "enemy base",
}


def _spike_hint(my_level) -> str:
    lv = _num(my_level)
    if lv is None:
        return "play to your wave"
    if lv >= 16:
        return "all spikes online"
    if lv >= 11:
        return "ult rank 2 - force a fight"
    if lv >= 6:
        return "ult online - look for picks"
    return "pre-6 - play safe"


def _valid_dot(d):
    """Normalize a raw dot to {team, x_frac, y_frac, _w} or None if malformed."""
    if not isinstance(d, dict):
        return None
    team = d.get("team")
    if team not in ("blue", "red"):
        return None
    x = _num(d.get("x_frac"))
    y = _num(d.get("y_frac"))
    px = _num(d.get("px"))
    conf = _num(d.get("confidence"))
    if x is None or y is None or px is None or conf is None:
        return None
    W = px * conf
    if W < 0.0:
        W = 0.0
    return {
        "team": team,
        "x_frac": _clamp(x, 0.0, 1.0),
        "y_frac": _clamp(y, 0.0, 1.0),
        "px": px,
        "confidence": conf,
        "_w": W,
    }


def compute_zoi(dots, *, my_level, game_time_s, base_fallback=(0.5, 0.5)):
    """Compute the /api/state.zoi payload from per-team minimap dots.

    Pure + fail-soft. Returns None when `dots` is empty/None or every dot is
    malformed. Otherwise a dict with EXACTLY {bubbles, demarcation, map_control}.
    Blue = ally, red = enemy (League default minimap colors; the operator uses
    the default). A zero-presence team falls back to `base_fallback` centroid +
    a forced 50/50 split so there is never a divide-by-zero.
    """
    if not dots:
        return None
    valid = []
    for d in dots:
        nd = _valid_dot(d)
        if nd is not None:
            valid.append(nd)
    if not valid:
        return None

    T = _time_scalar(game_time_s)
    ally_pw = _ally_power(my_level, T)
    enemy_pw = _enemy_power(T)

    ally = [d for d in valid if d["team"] == "blue"]
    enemy = [d for d in valid if d["team"] == "red"]

    # one bubble per valid dot
    bubbles = []
    for d in valid:
        is_ally = d["team"] == "blue"
        power = ally_pw if is_ally else enemy_pw
        r_frac = _bubble_radius_frac(d["px"], d["confidence"], power, T)
        bubbles.append({
            "team": d["team"],
            "cx": round(d["x_frac"], 4),
            "cy": round(d["y_frac"], 4),
            "r_frac": round(r_frac, 5),
            "weight": round(d["_w"], 3),
        })

    ca_x, ca_y, wa = _weighted_centroid(ally)
    ce_x, ce_y, we = _weighted_centroid(enemy)

    # zero-presence team -> fallback centroid + forced even split (no div-by-0)
    if wa <= 0.0:
        ca_x, ca_y = base_fallback
    if we <= 0.0:
        ce_x, ce_y = base_fallback

    if wa <= 0.0 or we <= 0.0:
        # only one team present (or neither has weight) -> no frontier, the
        # present team owns the map (or 0 if it is the enemy that is present).
        demarcation = None
        if wa > 0.0 and we <= 0.0:
            ally_pct = 100
        elif we > 0.0 and wa <= 0.0:
            ally_pct = 0
        else:
            ally_pct = 50  # both zero-weight (all dots had W==0) - even
    else:
        demarcation = _demarcation((ca_x, ca_y), (ce_x, ce_y), wa, we)
        total = wa + we
        ally_pct = int(round(wa / total * 100.0)) if total > 0.0 else 50

    ally_pct = int(_clamp(ally_pct, 0, 100))

    # action quadrant from the GLOBAL weighted centroid (all valid dots)
    gx, gy, gw = _weighted_centroid(valid)
    if gw <= 0.0:
        gx, gy = base_fallback
    quadrant = _action_quadrant(gx, gy)

    readable = _QUADRANT_READABLE.get(quadrant, quadrant)
    hint = _spike_hint(my_level)
    line = f"Map control {ally_pct}%. Action {readable}. {hint}"
    if len(line) > 120:
        line = line[:120]

    return {
        "bubbles": bubbles,
        "demarcation": demarcation,
        "map_control": {
            "ally_control_pct": ally_pct,
            "action_quadrant": quadrant,
            "line": line,
        },
    }


def zoi_callout(zoi):
    """Adapt a computed zoi payload to the canonical callout dict shape
    {tag, line, eta_s, kind}. None passthrough. eta_s None = standing advisory
    (no ETA chip)."""
    if not zoi:
        return None
    try:
        line = zoi["map_control"]["line"]
    except (KeyError, TypeError):
        return None
    return {
        "tag": "map_control",
        "line": line,
        "eta_s": None,
        "kind": "map_control",
    }
