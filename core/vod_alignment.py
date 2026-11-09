# arch: pure VOD alignment (game time -> recording time) | section=core | frozen=no
"""core/vod_alignment.py - map Live Client gameTime onto recording time.

RM-637 (directive X-37, ADR-016). Behaviour observed in external references
C/E/G/H and re-implemented clean-room; no code or constants were copied.

Convention: ``video_time = game_time + offset``, where video_time is seconds
since the recording started (``record_start_wall``).

Rules (ADR-016 "Alignment"):
  * PROOF only on a poll where gameTime ADVANCED over the previous poll. A
    frozen 0 on the loading screen and a frozen value during a pause are not
    proof, because the video keeps rolling while game time stands still.
  * Each proving poll measures ``(wall - record_start_wall) - game_time``. A
    new ANCHOR is stored only when that measurement moves by more than
    ``tolerance_s`` from the current one (a pause shifts it by the pause
    length; poll jitter does not). A game time maps through the last anchor at
    or before it, so markers before a pause keep their pre-pause offset.
  * Markers seen before proof are PROVISIONAL (best guess from their wall
    stamp) and are rewritten by ``resolve()``.
  * video_time is clamped to >= 0 everywhere.
  * A game that ends before any proof falls back to 1:1 (offset 0.0).
  * Junk input never raises and never reaches the output as NaN / inf
    (s144 true-audit, S144-T-677):
      - an unusable ``record_start_wall`` (None, bool, NaN, inf, non-numeric)
        leaves the tracker unprovable: everything maps 1:1, method
        ``fallback_1to1``. Such a start used to add an anchor on every poll
        (NaN offsets never compare within tolerance) or raise TypeError;
      - an unusable ``tolerance_s`` (as above, or negative) uses
        DEFAULT_TOLERANCE_S;
      - at most MAX_ANCHORS anchors are kept. A stream whose game clock does
        not run 1:1 with the wall (a replay at 2x) moved the offset every
        poll and grew the list without bound; past the cap the mapping stays
        on the last anchor and ``resolve()`` reports ``anchors_capped``;
      - a marker whose game_time is unusable is stored with game_time None
        and keeps its wall-stamp video_time through ``resolve()`` (it stays
        provisional: no mapping can prove it). It used to be stored as game
        time 0.0 and rewritten at resolve to ``0 + offset``, a wrong seek.

Pure: no I/O, no clock reads, no logging. The caller supplies wall stamps.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Optional

# Our own choice: Live Client polls land 0.5 s apart and the relay stamp
# jitters by tens of milliseconds, so a 0.5 s move is the smallest shift we
# treat as a real discontinuity (a pause, a reconnect) rather than noise.
DEFAULT_TOLERANCE_S = 0.5

# Our own choice: a real game re-anchors only on a pause or a reconnect, a
# handful of times at most; 64 leaves ample headroom and bounds both the
# sidecar's anchor list and the per-lookup scan.
MAX_ANCHORS = 64

_EPS = 1e-6


@dataclass(frozen=True)
class Poll:
    wall: float
    game_time: float


def _num(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def _coerce_poll(poll: Any) -> Optional[Poll]:
    if poll is None:
        return None
    if isinstance(poll, dict):
        wall, gt = poll.get("wall"), poll.get("game_time")
    else:
        wall, gt = getattr(poll, "wall", None), getattr(poll, "game_time", None)
    wall_f, gt_f = _num(wall), _num(gt)
    if wall_f is None or gt_f is None or gt_f < 0:
        return None
    return Poll(wall=wall_f, game_time=gt_f)


class AlignmentTracker:
    """Observe Live Client polls, prove an offset, resolve markers."""

    def __init__(self, record_start_wall: float,
                 tolerance_s: float = DEFAULT_TOLERANCE_S) -> None:
        # None = no usable start: the tracker can never prove an offset.
        self._start: Optional[float] = _num(record_start_wall)
        tol = _num(tolerance_s)
        self._tol = tol if tol is not None and tol >= 0 else DEFAULT_TOLERANCE_S
        self._prev: Optional[Poll] = None
        # (game_time, offset), ascending game_time, at most MAX_ANCHORS
        self._anchors: list[tuple[float, float]] = []
        self._capped = False
        self._markers: list[dict] = []

    @property
    def proven(self) -> bool:
        return bool(self._anchors)

    def observe(self, poll: Any) -> bool:
        """Feed one poll. Returns True when this poll created an anchor."""
        p = _coerce_poll(poll)
        if p is None or self._start is None:
            return False
        prev, self._prev = self._prev, p
        if prev is None or p.game_time <= prev.game_time + _EPS:
            return False  # first poll, frozen (loading / pause) or a drop
        offset = (p.wall - self._start) - p.game_time
        if self._anchors:
            _gt0, off0 = self._anchor_for(p.game_time)
            if abs(offset - off0) <= self._tol:
                return False
            # An anchor never goes BEFORE an existing one: keep the list
            # ascending so the lookup stays a simple scan.
            if p.game_time <= self._anchors[-1][0] + _EPS:
                return False
            if len(self._anchors) >= MAX_ANCHORS:
                self._capped = True
                return False
        self._anchors.append((p.game_time, offset))
        return True

    def _anchor_for(self, game_time: float) -> tuple[float, float]:
        chosen = self._anchors[0]
        for a in self._anchors:
            if a[0] <= game_time + _EPS:
                chosen = a
            else:
                break
        return chosen

    def video_time_for(self, game_time: float) -> float:
        """Recording time for ``game_time`` (1:1 before proof), clamped >= 0."""
        gt = _num(game_time) or 0.0
        if not self._anchors:
            return max(0.0, gt)
        return max(0.0, gt + self._anchor_for(gt)[1])

    def mark(self, game_time: float, wall: Optional[float] = None,
             key: Any = None, label: Any = None) -> dict:
        """Record a marker. Before proof its video_time is a provisional guess
        from its wall stamp; ``resolve()`` rewrites it."""
        gt = _num(game_time)
        w = _num(wall)
        if gt is None:
            # Unmappable: the wall stamp is the only evidence (video time is
            # wall since the recording started), kept as-is by resolve().
            vt = self._wall_video_time(w)
            prov = True
        elif self._anchors:
            vt, prov = self.video_time_for(gt), False
        else:
            wv = self._wall_video_time(w)
            vt = max(0.0, gt) if wv is None else wv
            prov = True
        if vt is None:
            vt = 0.0
        m = {"key": key, "label": label, "game_time": gt,
             "video_time": vt, "provisional": prov}
        self._markers.append(m)
        return dict(m)

    def _wall_video_time(self, wall: Optional[float]) -> Optional[float]:
        if wall is None or self._start is None:
            return None
        return max(0.0, wall - self._start)

    def resolve(self) -> dict:
        """Finalize: rewrite every marker against the proven mapping, or the
        1:1 fallback when the game ended before proof. A marker with no
        usable game_time keeps its wall-stamp video_time and stays
        provisional."""
        proven = bool(self._anchors)
        markers = []
        for m in self._markers:
            r = dict(m)
            if m["game_time"] is not None:
                r["video_time"] = self.video_time_for(m["game_time"])
                r["provisional"] = False
            markers.append(r)
        return {
            "proven": proven,
            "method": "proven" if proven else "fallback_1to1",
            "game_time_offset_s": self._anchors[0][1] if proven else 0.0,
            "anchors": [{"game_time": g, "offset_s": o} for g, o in self._anchors],
            "anchors_capped": self._capped,
            "markers": markers,
        }
