# arch: ward-coverage rolling-window backend | section=core | frozen=no
"""core/ward_events.py - in-memory rolling window of ward placements.

UX research recommended a "Ward-Coverage Heat Strip" panel (UX-3 in the
pitch deck) that visualises the last 90s of ward placements across the
four lane zones (top / mid / bot / jg) for both teams. This module is
the backend half - data substrate only; no rendering.

EVENT SOURCE STATUS (2026-05-20):
  The Live Client API event stream is FIXED to the canonical Riot set:
  ChampionKill, BaronKill, DragonKill, TurretKilled, InhibKilled,
  FirstBloodKill, GameEnd. WARD_PLACED is NOT in that set - never has
  been. So this module exposes a record_ward() injection API and a
  rolling-window query API; the producer side (who calls record_ward)
  is intentionally not wired here. A future task will either:
    (a) detect inventory delta on the Live Client allPlayers items
        feed when a yellow / control / blue trinket count drops, or
    (b) bolt onto an OCR pass over the minimap to detect new ward
        sprites,
  and feed those into ``record_ward``. Until that producer ships, the
  /api/ward-heat route returns an empty rolling window - the UX is
  still designable against the contract.

Public API:
  - record_ward(side, lane, ward_type, ts=None) -> None
      Register a ward placement. ``ts`` defaults to time.time().
      Lane is one of {top, mid, bot, jg, unknown}. ``side`` is
      ally / enemy. ``ward_type`` is yellow / control / blue_trinket /
      farsight.
  - record_from_position(side, x, z, ward_type, ts=None) -> str
      Convenience: derive the lane label from (x, z) game-units on
      Summoner's Rift, then record_ward(). Returns the resolved lane.
  - recent_wards(now_s=None, window_s=90) -> list[dict]
      The rolling window: entries with now_s - window_s <= ts <= now_s,
      in insertion order. Returns a list of dicts:
        {ts, side, lane, ward_type}
      Entries older than the RETENTION horizon (not the caller's window)
      are dropped lazily on read, so one narrow read never erases what a
      wider reader still needs.
  - counts_by_lane(now_s=None, window_s=90) -> dict
      Aggregate per-side per-lane count over the window:
        {"ally": {"top": 3, "mid": 2, "bot": 0, "jg": 1, "unknown": 0},
         "enemy": {...}}
  - lanes_uncovered(side, now_s=None, window_s=60) -> list[str]
      Lanes (top/mid/bot/jg) with ZERO friendly wards in the most
      recent ``window_s`` seconds. Default 60 - matches the UX-3 spec
      ("a lane is uncovered if no friendly ward placed there in the
      last 60s").
  - reset() -> None
      Clear the buffer. Test helper; also useful between games.

Internals:
  - Single module-level deque keyed off a threading.Lock. The expected
    write rate is < 1/s (operator + 9 other players, mostly idle); the
    expected read rate is ~0.5/s (dashboard tick). A lock-protected
    deque is the simplest correct shape - well under any contention
    threshold that would warrant a lock-free design.
  - Maximum buffer size: 256 entries. A defensive cap so a producer bug
    can't unbounded-grow the buffer. A real game places on the order of
    100-150 wards across all ten players in 30 minutes, so the 600 s
    retention horizon holds well under 256; only a producer bug firing
    every tick reaches the cap, and then the oldest entries fall off.
  - Retention: ``_RETENTION_S`` (600 s, the widest window
    /api/ward-heat accepts). Eviction on read uses
    ``now_s - max(window_s, _RETENTION_S)``. It used to use the caller's
    own window, so a ``?window_s=5`` request deleted every ward older
    than 5 s from the default 90 s view (s144 true-audit).
  - Every timestamp (``ts``, ``now_s``) must be a finite real number; a
    bool, NaN or inf is refused. A NaN ``ts`` at the head of the deque
    used to block the lazy GC forever while reporting itself in every
    window.

Lane zones (SR, game units, 0..16000 accepted; the map is ~14800):
  The Live Client emits position in raw game-unit coordinates with
  origin at the blue base corner. SR lane regions (broad zones):
    top  : low x  + high z  (top-left quadrant)
    bot  : high x + low z   (bottom-right quadrant)
    mid  : near the (x = z) diagonal
    jg   : everything else (both jungle quadrants)
  The 'unknown' label is reserved for callers who explicitly bypass
  position-based inference (e.g. an OCR producer that only knows the
  minimap region a ward was placed in).
"""
from __future__ import annotations

import math
import threading
import time
from collections import deque
from typing import Optional

# Buffer cap. Defensive; never reached in real play.
_MAX_BUFFER = 256

# Eviction horizon, independent of any caller's window. Must stay >= the
# widest window /api/ward-heat accepts (routes_ward_heat._WINDOW_MAX_S);
# tests/test_routes_ward_heat.py pins that.
_RETENTION_S = 600.0

# Default windows.
_DEFAULT_WINDOW_S = 90.0
_UNCOVERED_WINDOW_S = 60.0

# Canonical sets the public API normalises into.
SIDES = frozenset({"ally", "enemy"})
LANES = frozenset({"top", "mid", "bot", "jg", "unknown"})
WARD_TYPES = frozenset({"yellow", "control", "blue_trinket", "farsight"})

# Just the 4 named lanes used in 'uncovered' detection (unknown is not
# a coverage gap - it's "we don't know where the ward went").
NAMED_LANES = ("top", "mid", "bot", "jg")

# -- Module state -----------------------------------------------------------

_buffer: deque[dict] = deque(maxlen=_MAX_BUFFER)
_lock = threading.Lock()


# -- Input coercion ---------------------------------------------------------

def _finite(value) -> Optional[float]:
    """``value`` as a finite float, else None. A bool is not a number here
    (``True`` would otherwise read as 1.0 s / 1 game unit)."""
    if isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return out if math.isfinite(out) else None


def _label(value) -> str:
    """A str label lower-cased and stripped; anything that is not a str is
    the empty label (never str()'d - a hostile __str__ must not escape)."""
    return value.lower().strip() if isinstance(value, str) else ""


# -- Lane inference ---------------------------------------------------------

def lane_from_position(x: float, z: float) -> str:
    """Map an SR (x, z) game-unit pair onto a coarse lane zone.

    Bounds chosen to match the vision_tracker._sr_zone semantics:
      * top  : low x  (< 4500) + high z (> 10000)
      * bot  : high x (> 10000) + low z (< 4500)
      * mid  : within 2200 units of the (x == z) diagonal
      * jg   : everything else

    Returns one of {top, mid, bot, jg, unknown}. Out-of-bounds inputs
    (negative, or beyond 16000 - the SR map is ~14800) and anything that
    is not a finite number (NaN, inf, a bool, junk) -> 'unknown'.
    """
    x = _finite(x)
    z = _finite(z)
    if x is None or z is None:
        return "unknown"
    if x < 0 or z < 0 or x > 16000 or z > 16000:
        return "unknown"
    # Top: top-left quadrant
    if x < 4500 and z > 10000:
        return "top"
    # Bot: bottom-right quadrant
    if x > 10000 and z < 4500:
        return "bot"
    # Mid: near the x==z diagonal (broad band)
    if abs(x - z) < 2200:
        return "mid"
    # Everything else is jungle
    return "jg"


# -- Public API -------------------------------------------------------------

def record_ward(side: str, lane: str, ward_type: str,
                ts: Optional[float] = None) -> None:
    """Register a ward placement event.

    Inputs are sanity-checked and normalised:
      * unknown or non-str side / ward_type -> the event is dropped
        (no exception)
      * a ``ts`` that is not a finite number (NaN, inf, bool) -> dropped
      * unknown or non-str lane -> stored as 'unknown'
    The drop-on-bad-input shape matches vision_tracker.ingest: a
    malformed producer can't poison the buffer, but it also can't
    crash the dashboard route.
    """
    ts = _finite(time.time() if ts is None else ts)
    if ts is None:
        return
    side = _label(side)
    if side not in SIDES:
        return
    ward_type = _label(ward_type)
    if ward_type not in WARD_TYPES:
        return
    lane = _label(lane)
    if lane not in LANES:
        lane = "unknown"
    entry = {
        "ts":        ts,
        "side":      side,
        "lane":      lane,
        "ward_type": ward_type,
    }
    with _lock:
        _buffer.append(entry)


def record_from_position(side: str, x: float, z: float, ward_type: str,
                         ts: Optional[float] = None) -> str:
    """Convenience: infer lane from position then record_ward().

    Returns the resolved lane label so the caller can log or test the
    inference outcome without a second call.
    """
    lane = lane_from_position(x, z)
    record_ward(side, lane, ward_type, ts=ts)
    return lane


def recent_wards(now_s: Optional[float] = None,
                 window_s: float = _DEFAULT_WINDOW_S) -> list[dict]:
    """Return entries with ``now_s - window_s <= ts <= now_s``.

    Each entry is tested on its own ``ts``: the buffer is in insertion
    order, which is NOT time order once a producer passes an older
    ``ts`` or the wall clock steps, so a left-only prune that returned
    the rest unfiltered reported stale and future entries as current.

    Entries older than ``now_s - max(window_s, _RETENTION_S)`` are
    evicted from the buffer on read (lazy GC). The horizon is the
    retention, not the caller's window, so a narrow read never erases an
    entry a wider reader still needs. A ``now_s`` that is not a finite
    number, or a NaN / non-positive ``window_s``, returns [] and evicts
    nothing; ``window_s=inf`` means every retained entry up to ``now_s``.

    Entries are returned in INSERTION order (oldest-first). The UX-3
    canvas renders dots fading left over time, so insertion order is
    what the frontend wants - dot[0] is the oldest still in window.
    """
    now_s = _finite(time.time() if now_s is None else now_s)
    if now_s is None or isinstance(window_s, bool):
        return []
    try:
        window_s = float(window_s)
    except (TypeError, ValueError, OverflowError):
        return []
    if math.isnan(window_s) or window_s <= 0:
        return []
    cutoff = now_s - window_s
    horizon = now_s - max(window_s, _RETENTION_S)
    with _lock:
        # Lazy GC over the whole buffer, not just the left run: an
        # out-of-order old entry behind a newer head must go too. At
        # most 256 entries, so the rebuild stays cheap.
        if any(e["ts"] < horizon for e in _buffer):
            kept = [e for e in _buffer if e["ts"] >= horizon]
            _buffer.clear()
            _buffer.extend(kept)
        # Snapshot for the caller. dict copies so caller can mutate
        # safely (e.g. add a 'lane_label' frontend field).
        return [dict(e) for e in _buffer if cutoff <= e["ts"] <= now_s]


def counts_by_lane(now_s: Optional[float] = None,
                   window_s: float = _DEFAULT_WINDOW_S) -> dict:
    """Aggregate ward counts by (side, lane) over the window.

    Returns a nested dict with EVERY lane label seeded to 0 so the
    frontend can render the grid without null-guards.
    """
    out: dict[str, dict[str, int]] = {
        "ally":  {lane: 0 for lane in LANES},
        "enemy": {lane: 0 for lane in LANES},
    }
    for ev in recent_wards(now_s=now_s, window_s=window_s):
        side = ev.get("side")
        lane = ev.get("lane", "unknown")
        if side in out and lane in out[side]:
            out[side][lane] += 1
    return out


def lanes_uncovered(side: str,
                    now_s: Optional[float] = None,
                    window_s: float = _UNCOVERED_WINDOW_S) -> list[str]:
    """Return the named lanes (top/mid/bot/jg) with ZERO ``side`` wards
    in the last ``window_s`` seconds. Default 60s per UX-3 spec.

    Order: top, mid, bot, jg (canonical lane order). An empty return
    means full coverage; the list never includes 'unknown'. An unknown
    or non-str side reads as fully uncovered rather than raising.
    """
    side = _label(side)
    if side not in SIDES:
        return list(NAMED_LANES)
    seen: set[str] = set()
    for ev in recent_wards(now_s=now_s, window_s=window_s):
        if ev.get("side") != side:
            continue
        lane = ev.get("lane")
        if lane in NAMED_LANES:
            seen.add(lane)
    return [lane for lane in NAMED_LANES if lane not in seen]


def reset() -> None:
    """Clear the rolling-window buffer. Test helper + between-game hook."""
    with _lock:
        _buffer.clear()


def buffer_size() -> int:
    """Current buffer occupancy. Debug / test helper."""
    with _lock:
        return len(_buffer)
