"""Per-district team presence counters over minimap blob dots (ZOI Wave 2, spec B).

Consumes the ``core.minimap_blob_detect.current_minimap_dots`` shape
(``[{team: "blue"|"red", x_frac, y_frac, px, confidence}]``, box-fraction
``[0, 1]`` within the minimap crop - ``detect_team_dots`` in minimap_blob_detect.py) and
buckets each dot into the mode's district grid via
``core.minimap_districts.district_of``. Blue = ally, red = enemy (League
default minimap colors, same convention as ``compute_zoi`` in core/zoi_influence.py).

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
mode change (even on a tick whose clock is unusable - a mode change needs
no clock), ``game_time_s`` regressing by more than ``NEW_GAME_REGRESS_S``
(a new game starts near 0), or a stale gap of more than ``STALE_GAP_S`` of
game time with no update.

Input rules (S144-T-581, lane 8 true-audit):
- a dot counts only when it is a Mapping whose ``team`` is the str "blue"
  or "red" and whose ``x_frac`` / ``y_frac`` are finite non-bool numbers
  inside the ``[0, 1]`` box; ``district_of`` CLAMPS an off-map point into
  an edge district, so an off-map dot is refused here, not counted there;
- at most ``_MAX_DOTS`` entries of ``dots`` are read per tick (the live
  caller caps detection at five dots per team);
- a usable clock is a finite non-bool number; anything else (NaN, inf, an
  integer too large for a float, True) is "no clock": the tick still emits
  its live snapshot but advances no state;
- ``flip`` mirrors the map only for True, a non-zero int, or one of the
  strings "1" / "true" / "yes" / "on" (so ``flip="false"`` does not flip);
- update / reset hold one lock: the module singleton is fed from the
  ``ThreadingHTTPServer`` request threads that build /api/state.

Fail-soft contract (matches core/zoi_influence.py + core/minimap_districts.py):
never raises on any input - garbage dots are skipped, grid-less/unknown
modes emit ``[]``, unusable times emit a snapshot without advancing state.
"""
from __future__ import annotations

import math
import threading
from collections.abc import Mapping

from core.minimap_districts import district_of, load_grid

#: game_time_s going backwards by more than this = a NEW game (wipe).
#: Small regressions below this are treated as clock jitter and tolerated.
NEW_GAME_REGRESS_S = 5.0

#: no update for more than this much game time = stale (wipe) - never
#: resume counters across a relay/vision outage or a missed match boundary.
STALE_GAP_S = 30.0

#: most ``dots`` entries read per tick, and the most any one count may
#: report. The live caller keeps at most five dots per team, so 64 is far
#: above any real frame and only bounds a runaway or hostile feed.
_MAX_DOTS = 64

#: blob team color -> presence side (the ``compute_zoi`` blue = ally convention).
_TEAM_SIDE = {"blue": "ally", "red": "enemy"}

_SIDES = ("ally", "enemy")

_TRUE_STRINGS = frozenset({"1", "true", "yes", "on"})


class MinimapPresenceTracker:
    """Stateful per-process presence tracker. One instance per process is
    enough (see the module-level ``current_presence`` singleton); state is
    keyed by district id and wiped on any match-boundary signal."""

    def __init__(self):
        self._lock = threading.Lock()
        self._mode = None       # normalized mode of the current match
        self._last_t = None     # last VALID game_time_s processed
        self._last_seen = {}    # district_id -> {"ally": t|None, "enemy": t|None}

    def reset(self):
        """Drop all per-match state (test seam + match-boundary wipe)."""
        with self._lock:
            self._clear()

    def update(self, dots, mode, game_time_s, flip=False):
        """Ingest one tick of blob dots; return the per-district presence
        vector (full label set, stable row shape). Never raises."""
        try:
            with self._lock:
                return self._update(dots, mode, game_time_s, flip)
        except Exception:  # noqa: BLE001 - fail-soft contract: never raises
            return []

    # --- internals (callers hold self._lock) -------------------------------

    def _clear(self):
        self._mode = None
        self._last_t = None
        self._last_seen = {}

    def _update(self, dots, mode, game_time_s, flip):
        mode_key = _norm_mode(mode)
        grid = load_grid(mode_key) if mode_key else None
        if grid is None or not grid.districts:
            # grid-less mode (tft) or unknown mode: no district vector.
            # Also drop prior state so nothing carries into the next match.
            self._clear()
            return []

        if self._mode is not None and mode_key != self._mode:
            # mode change = different match, whatever the clock says
            self._clear()

        counts = _bucket(dots, mode_key, _as_flag(flip), grid)
        t = _norm_time(game_time_s)
        if t is None:
            # unusable time: emit a live snapshot (counts still useful)
            # but do NOT advance state - deltas need a real clock.
            return self._rows(grid, counts, None)

        if self._should_wipe(t):
            self._clear()
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

    def _should_wipe(self, t):
        if self._last_t is None:
            return False
        if t < self._last_t - NEW_GAME_REGRESS_S:
            return True  # game clock regressed = new game
        # stale gap = do not resume old counters
        return t - self._last_t > STALE_GAP_S

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


def _finite(v):
    """``v`` as a finite float, or None: bool, non-numbers, NaN, inf and
    integers too large for a float are all None."""
    if isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError, OverflowError):
        return None
    return f if math.isfinite(f) else None


def _norm_time(game_time_s):
    return _finite(game_time_s)


def _as_flag(flip):
    """Strict truthiness for ``flip``: a stray "false" must not mirror the map."""
    if isinstance(flip, bool):
        return flip
    if isinstance(flip, int):
        return flip != 0
    if isinstance(flip, str):
        return flip.strip().lower() in _TRUE_STRINGS
    return False


def _missing(count, last_seen_t, t):
    """Seconds of game time a side has been absent from a district.
    0.0 while present; None when never seen (or no usable clock)."""
    if count > 0:
        return 0.0
    if last_seen_t is None or t is None:
        return None
    return round(max(0.0, t - last_seen_t), 2)


def _box_frac(v):
    """A minimap box fraction in ``[0, 1]``, or None."""
    f = _finite(v)
    if f is None or f < 0.0 or f > 1.0:
        return None
    return f


def _bucket(dots, mode_key, flip, grid):
    """Count dots per (district, side). Malformed entries are skipped."""
    counts = {d.id: {"ally": 0, "enemy": 0} for d in grid.districts}
    if not isinstance(dots, (list, tuple)):
        return counts
    try:
        head = list(dots[:_MAX_DOTS])
    except Exception:  # noqa: BLE001 - a sequence subclass that cannot slice
        return counts
    for dot in head:
        try:
            if not isinstance(dot, Mapping):
                continue
            team = dot.get("team")
            if not isinstance(team, str):
                continue
            side = _TEAM_SIDE.get(str.__str__(team))
            if side is None:
                continue
            x = _box_frac(dot.get("x_frac"))
            y = _box_frac(dot.get("y_frac"))
            if x is None or y is None:
                continue
            did = district_of(x, y, mode_key, flip=flip)
            if did in counts:
                counts[did][side] += 1
        except Exception:  # noqa: BLE001 - fail-soft contract: never raises
            continue
    return counts


# --- serving helpers ---------------------------------------------------------

def presence_payload(rows):
    """Defensive JSON-safe copy of a tracker output for the /api/state
    splice (``zoi["districts"]``). Coerces every field to its declared
    type, drops non-dict rows and rows without a non-empty str district
    id, strips NaN/inf/bool and negative durations, caps counts at
    ``_MAX_DOTS``. A row that cannot be copied is dropped ALONE; the rest
    still serve. Garbage in -> []. Never raises."""
    out = []
    try:
        if not isinstance(rows, (list, tuple)):
            return []
        for r in rows:
            try:
                row = _payload_row(r)
            except Exception:  # noqa: BLE001 - one bad row drops alone
                continue
            if row is not None:
                out.append(row)
        return out
    except Exception:  # noqa: BLE001 - fail-soft contract: never raises
        return []


def _payload_row(r):
    if not isinstance(r, dict):
        return None
    district = r.get("district")
    if not isinstance(district, str):
        return None
    district = str.__str__(district)  # exact str: a subclass cannot override
    if not district:
        return None
    seen = r.get("last_seen_t")
    if not isinstance(seen, dict):
        seen = {}
    return {
        "district": district,
        "ally": _as_count(r.get("ally")),
        "enemy": _as_count(r.get("enemy")),
        "ally_missing_since_s": _as_duration(r.get("ally_missing_since_s")),
        "enemy_missing_since_s": _as_duration(r.get("enemy_missing_since_s")),
        "last_seen_t": {
            "ally": _as_opt_float(seen.get("ally")),
            "enemy": _as_opt_float(seen.get("enemy")),
        },
    }


def _as_count(v):
    if isinstance(v, int) and not isinstance(v, bool):
        # an exact int clamps directly, so 10**400 caps like 1e300 does
        return min(_MAX_DOTS, max(0, int.__index__(v)))
    f = _finite(v)
    if f is None:
        return 0
    return min(_MAX_DOTS, max(0, int(f)))


def _as_opt_float(v):
    f = _finite(v)
    return None if f is None else round(f, 2)


def _as_duration(v):
    f = _as_opt_float(v)
    return None if f is None or f < 0.0 else f


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
