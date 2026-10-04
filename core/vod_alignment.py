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
        self._start = float(record_start_wall)
        self._tol = float(tolerance_s)
        self._prev: Optional[Poll] = None
        # (game_time, offset), ascending game_time
        self._anchors: list[tuple[float, float]] = []
        self._markers: list[dict] = []

    @property
    def proven(self) -> bool:
        return bool(self._anchors)

    def observe(self, poll: Any) -> bool:
        """Feed one poll. Returns True when this poll created an anchor."""
        p = _coerce_poll(poll)
        if p is None:
            return False
        prev, self._prev = self._prev, p
        if prev is None or p.game_time <= prev.game_time + _EPS:
            return False  # first poll, frozen (loading / pause) or a drop
        offset = (p.wall - self._start) - p.game_time
        if self._anchors:
            gt0, off0 = self._anchor_for(p.game_time)
            if abs(offset - off0) <= self._tol:
                return False
            # An anchor never goes BEFORE an existing one: keep the list
            # ascending so the lookup stays a simple scan.
            if p.game_time <= self._anchors[-1][0] + _EPS:
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
        gt = _num(game_time) or 0.0
        if self._anchors:
            vt, prov = self.video_time_for(gt), False
        else:
            w = _num(wall)
            vt = max(0.0, (w - self._start) if w is not None else gt)
            prov = True
        m = {"key": key, "label": label, "game_time": gt,
             "video_time": vt, "provisional": prov}
        self._markers.append(m)
        return dict(m)

    def resolve(self) -> dict:
        """Finalize: rewrite every marker against the proven mapping, or the
        1:1 fallback when the game ended before proof."""
        proven = bool(self._anchors)
        markers = []
        for m in self._markers:
            r = dict(m)
            r["video_time"] = self.video_time_for(m["game_time"])
            r["provisional"] = False
            markers.append(r)
        return {
            "proven": proven,
            "method": "proven" if proven else "fallback_1to1",
            "game_time_offset_s": self._anchors[0][1] if proven else 0.0,
            "anchors": [{"game_time": g, "offset_s": o} for g, o in self._anchors],
            "markers": markers,
        }
