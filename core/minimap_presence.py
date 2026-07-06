"""Per-district team presence counters over minimap blob dots (ZOI Wave 2, spec B).

Consumes the ``core.minimap_blob_detect.current_minimap_dots`` shape
(``[{team: "blue"|"red", x_frac, y_frac, px, confidence}]``, box-fraction
``[0, 1]`` within the minimap crop - minimap_blob_detect.py:109-115) and
buckets each dot into the mode's district grid via
``core.minimap_districts.district_of``. Blue = ally, red = enemy (League
default minimap colors, same convention as core/zoi_influence.py:263).

``MinimapPresenceTracker.update`` emits ONE row per district in the mode's
grid EVERY tick - the FULL label set, zero-presence included, so the
overlay never reflows on data absence (no-reflow doctrine). Row shape is
flat-JSON-serializable and stable (same keys every tick):

    {
        "district": str,                      # district id from the grid
        "ally": int,                          # dots counted this tick
        "enemy": int,
        "ally_missing_since_s": float|None,   # 0.0 while present; game-time
        "enemy_missing_since_s": float|None,  # seconds since last seen when
                                              # absent; None if never seen
        "last_seen_t": {"ally": float|None, "enemy": float|None},
    }

``missing_since_s`` derives purely from ``game_time_s`` DELTAS: a team
count going 0 -> >0 stamps ``last_seen_t`` (and pins missing at 0.0);
0-presence accumulates from the last-seen game time.

State is wiped whenever counters could otherwise leak across matches:
mode change, ``game_time_s`` regressing by more than
``NEW_GAME_REGRESS_S`` (a new game starts near 0), or a stale gap of more
than ``STALE_GAP_S`` of game time with no update.

Fail-soft contract (matches core/zoi_influence.py + core/minimap_districts.py):
never raises on any input - garbage dots are skipped, grid-less/unknown
modes emit ``[]``, non-finite times emit a snapshot without mutating state.
"""
from __future__ import annotations

import math

from core.minimap_districts import district_of, load_grid

#: game_time_s going backwards by more than this = a NEW game (wipe).
#: Small regressions below this are treated as clock jitter and tolerated.
NEW_GAME_REGRESS_S = 5.0

#: no update for more than this much game time = stale (wipe) - never
#: resume counters across a relay/vision outage or a missed match boundary.
STALE_GAP_S = 30.0

#: blob team color -> presence side (core/zoi_influence.py:263 convention).
_TEAM_SIDE = {"blue": "ally", "red": "enemy"}

_SIDES = ("ally", "enemy")


class MinimapPresenceTracker:
    """Stateful per-process presence tracker. One instance per process is
    enough (see the module-level ``current_presence`` singleton); state is
    keyed by district id and wiped on any match-boundary signal."""

    def __init__(self):
        self._mode = None       # normalized mode of the current match
        self._last_t = None     # last VALID game_time_s processed
        self._last_seen = {}    # district_id -> {"ally": t|None, "enemy": t|None}

    def reset(self):
        """Drop all per-match state (test seam + match-boundary wipe)."""
        self._mode = None
        self._last_t = None
        self._last_seen = {}

    def update(self, dots, mode, game_time_s, flip=False):
        """Ingest one tick of blob dots; return the per-district presence
        vector (full label set, stable row shape). Never raises."""
        try:
            return self._update(dots, mode, game_time_s, flip)
        except Exception:  # noqa: BLE001 - fail-soft contract: never raises
            return []

    # --- internals -------------------------------------------------------

    def _update(self, dots, mode, game_time_s, flip):
        mode_key = _norm_mode(mode)
        grid = load_grid(mode_key) if mode_key else None
        if grid is None or not grid.districts:
            # grid-less mode (tft) or unknown mode: no district vector.
            # Also drop prior state so nothing carries into the next match.
            self.reset()
            return []

        counts = _bucket(dots, mode_key, flip, grid)
        t = _norm_time(game_time_s)
        if t is None:
            # NaN/garbage time: emit a live snapshot (counts still useful)
            # but do NOT advance or wipe state - deltas need a real clock.
            return self._rows(grid, counts, None)

        if self._should_wipe(mode_key, t):
            self.reset()
        self._mode = mode_key
        self._last_t = t

        for did, c in counts.items():
            slot = self._last_seen.get(did)
            if slot is None:
                slot = {"ally": None, "enemy": None}
                self._last_seen[did] = slot
            for side in _SIDES:
                if c[side] > 0:
                    slot[side] = t
        return self._rows(grid, counts, t)

    def _should_wipe(self, mode_key, t):
        if self._mode is not None and mode_key != self._mode:
            return True  # mode change = different match
        if self._last_t is None:
            return False
        if t < self._last_t - NEW_GAME_REGRESS_S:
            return True  # game clock regressed = new game
        if t - self._last_t > STALE_GAP_S:
            return True  # stale gap = do not resume old counters
        return False

    def _rows(self, grid, counts, t):
        rows = []
        for d in grid.districts:
            c = counts.get(d.id) or {"ally": 0, "enemy": 0}
            seen = self._last_seen.get(d.id) or {"ally": None, "enemy": None}
            rows.append(
                {
                    "district": d.id,
                    "ally": int(c["ally"]),
                    "enemy": int(c["enemy"]),
                    "ally_missing_since_s": _missing(c["ally"], seen["ally"], t),
                    "enemy_missing_since_s": _missing(c["enemy"], seen["enemy"], t),
                    "last_seen_t": {"ally": seen["ally"], "enemy": seen["enemy"]},
                }
            )
        return rows


def _norm_mode(mode):
    try:
        key = str(mode).strip().lower()
    except Exception:  # noqa: BLE001 - fail-soft contract: never raises
        return None
    return key or None


def _norm_time(game_time_s):
    try:
        t = float(game_time_s)
    except (TypeError, ValueError):
        return None
    return t if math.isfinite(t) else None


def _missing(count, last_seen_t, t):
    """Seconds of game time a side has been absent from a district.
    0.0 while present; None when never seen (or no usable clock)."""
    if count > 0:
        return 0.0
    if last_seen_t is None or t is None:
        return None
    return round(max(0.0, t - last_seen_t), 2)


def _bucket(dots, mode_key, flip, grid):
    """Count dots per (district, side). Malformed entries are skipped."""
    counts = {d.id: {"ally": 0, "enemy": 0} for d in grid.districts}
    if not isinstance(dots, (list, tuple)):
        return counts
    for dot in dots:
        try:
            if not isinstance(dot, dict):
                continue
            side = _TEAM_SIDE.get(dot.get("team"))
            if side is None:
                continue
            x = float(dot.get("x_frac"))
            y = float(dot.get("y_frac"))
            if not (math.isfinite(x) and math.isfinite(y)):
                continue
            did = district_of(x, y, mode_key, flip=bool(flip))
            if did in counts:
                counts[did][side] += 1
        except Exception:  # noqa: BLE001 - fail-soft contract: never raises
            continue
    return counts


# --- serving helpers ---------------------------------------------------------

def presence_payload(rows):
    """Defensive JSON-safe copy of a tracker output for the /api/state
    splice (``zoi["districts"]``). Coerces every field to its declared
    type, drops non-dict rows, strips NaN/inf. Garbage in -> []. Never
    raises."""
    out = []
    try:
        if not isinstance(rows, (list, tuple)):
            return []
        for r in rows:
            if not isinstance(r, dict):
                continue
            seen = r.get("last_seen_t")
            if not isinstance(seen, dict):
                seen = {}
            out.append(
                {
                    "district": str(r.get("district") or ""),
                    "ally": _as_count(r.get("ally")),
                    "enemy": _as_count(r.get("enemy")),
                    "ally_missing_since_s": _as_opt_float(
                        r.get("ally_missing_since_s")
                    ),
                    "enemy_missing_since_s": _as_opt_float(
                        r.get("enemy_missing_since_s")
                    ),
                    "last_seen_t": {
                        "ally": _as_opt_float(seen.get("ally")),
                        "enemy": _as_opt_float(seen.get("enemy")),
                    },
                }
            )
        return out
    except Exception:  # noqa: BLE001 - fail-soft contract: never raises
        return []


def _as_count(v):
    try:
        n = int(float(v))
    except (TypeError, ValueError, OverflowError):
        return 0
    return max(0, n)


def _as_opt_float(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return round(f, 2) if math.isfinite(f) else None


# --- module-level singleton (the /api/state splice entry point) ---------------

_TRACKER = MinimapPresenceTracker()


def current_presence(dots, mode, game_time_s, flip=False):
    """Update the process-wide tracker and return the presence vector.
    Never raises."""
    try:
        return _TRACKER.update(dots, mode, game_time_s, flip=flip)
    except Exception:  # noqa: BLE001 - fail-soft contract: never raises
        return []


def _reset_tracker():
    """Test seam: wipe the process-wide tracker."""
    _TRACKER.reset()
