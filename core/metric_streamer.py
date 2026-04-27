"""
MetricStreamer — cadence wrapper around `core.match_metrics.recorder`.

The recorder writes metric rows whenever asked. The streamer decides
*when* to ask: on game-time milestones, on 60s periodic boundaries, and
on discrete events. This keeps the coach's hot path free of DB-write
bookkeeping.

Design:
  - single-match lifetime: constructed when a match starts, destroyed
    when it ends
  - `on_state(payload, events=[])` is called by the coach on every tick
    (post-write of coaching_data.json). The streamer inspects the payload
    to decide whether to record + flush
  - stateless between snapshots — no internal payload diffing; that's
    the coach's job

Cadence rules:
  - `0:00 game_start`             → one-shot snapshot on first tick
  - every 60s of in-game time      → snapshot with milestone_tag=None
                                     (time-series base)
  - each of 10/15/20/25/30 min_mark → snapshot with the mark tag
  - l6_spike / l11_spike / l16_spike → snapshot on level transitions
  - event-driven (first_blood, first_tower, drake_take, baron_take,
    death, kill) → snapshot with tag
  - `game_end` → final snapshot then close()

WIRE-IN (coach side, not activated automatically):

    # At coach init:
    from core.metric_streamer import MetricStreamer
    streamer = MetricStreamer(match_id=..., champion=..., mode=...)

    # On every tick after writing coaching_data.json:
    streamer.on_state(coaching_data, events=live_events)

    # At game end:
    streamer.on_state(coaching_data, events=[...], game_end=True)
    streamer.close()

The wire-in above is INTENTIONALLY left unapplied in the coach modules —
enable it manually when you're ready to verify against a live match
without risking the coach crashing on a regression.
"""
from __future__ import annotations
import threading
from typing import Optional
from core.match_metrics import recorder

# Game-time thresholds → milestone tag.
_LEVEL_MILESTONES = {
    6:  "l6_spike",
    11: "l11_spike",
    16: "l16_spike",
}
_TIME_MILESTONES = [
    (600,  "10min_mark"),
    (900,  "15min_mark"),
    (1200, "20min_mark"),
    (1500, "25min_mark"),
    (1800, "30min_mark"),
]
# Periodic sampling every N seconds of game time.
_PERIODIC_INTERVAL_S = 60
# Canonical event names the coach passes via `events` list.
_EVENT_TAGS = {
    "first_blood":  "first_blood",
    "first_tower":  "first_tower",
    "drake_take":   "drake_take",
    "drake_lost":   "drake_contested_loss",
    "herald_take":  "herald_take",
    "baron_take":   "baron_take",
    "baron_lost":   "baron_contested_loss",
    "recall_start": "recall_start",
    "recall_end":   "recall_end",
    "death":        "death",
    "kill":         "kill",
    "assist":       "assist",
    "item_complete":"item_complete",
    "laning_end":   "laning_end",
}


class MetricStreamer:
    """One instance per live match. Thread-safe."""

    def __init__(self, *, match_id: str,
                 session_id: Optional[str] = None,
                 champion: Optional[str] = None,
                 mode: Optional[str] = None) -> None:
        self.match_id = match_id
        self.session_id = session_id
        self.champion = champion
        self.mode = mode
        self._lock = threading.Lock()
        self._started = False
        self._last_periodic_s: int = -1  # last game_time_s we snapshotted
        self._milestones_fired: set[str] = set()  # one-shot per match
        self._last_level: int = 0

    # ─────────── public API ───────────────────────────────────────────

    def on_state(self, payload: dict, *,
                 events: Optional[list[str]] = None,
                 game_end: bool = False) -> int:
        """Called by the coach on every tick. Returns number of metric
        rows buffered this call (0 if no cadence rule fired)."""
        if not isinstance(payload, dict):
            return 0
        gt = payload.get("game_time_s")
        if not isinstance(gt, (int, float)):
            gt = 0
        gt = int(gt)

        rows = 0
        events = events or []

        with self._lock:
            # 1. game_start one-shot
            if not self._started:
                self._started = True
                rows += self._snapshot(payload, gt, "game_start")

            # 2. level-based milestones (l6/l11/l16)
            level = payload.get("level")
            if isinstance(level, (int, float)):
                level = int(level)
                if level > self._last_level:
                    for lvl, tag in _LEVEL_MILESTONES.items():
                        if (self._last_level < lvl <= level
                                and tag not in self._milestones_fired):
                            self._milestones_fired.add(tag)
                            rows += self._snapshot(payload, gt, tag)
                self._last_level = level

            # 3. time-based milestones (10/15/20/25/30 min_mark)
            for threshold, tag in _TIME_MILESTONES:
                if gt >= threshold and tag not in self._milestones_fired:
                    self._milestones_fired.add(tag)
                    rows += self._snapshot(payload, gt, tag)

            # 4. event-driven (single-fire per event name per match for
            #    first_blood / first_tower; multi-fire for kill/death/assist/
            #    recall/item_complete).
            single_fire = {"first_blood", "first_tower", "laning_end"}
            for ev in events:
                tag = _EVENT_TAGS.get(ev)
                if not tag:
                    continue
                if tag in single_fire and tag in self._milestones_fired:
                    continue
                if tag in single_fire:
                    self._milestones_fired.add(tag)
                rows += self._snapshot(payload, gt, tag)

            # 5. periodic 60s sample (only if no other milestone fired
            #    this tick — avoids double-writes)
            if rows == 0 and gt >= 0:
                bucket = (gt // _PERIODIC_INTERVAL_S) * _PERIODIC_INTERVAL_S
                if bucket > self._last_periodic_s and bucket >= _PERIODIC_INTERVAL_S:
                    self._last_periodic_s = bucket
                    rows += self._snapshot(payload, gt, None)

            # 6. game_end final snapshot
            if game_end and "game_end" not in self._milestones_fired:
                self._milestones_fired.add("game_end")
                rows += self._snapshot(payload, gt, "game_end")

        # Flush outside the lock so the DB write doesn't serialize ticks.
        if rows > 0:
            recorder.flush()
        return rows

    def close(self) -> int:
        """Flush any remaining buffered rows."""
        with self._lock:
            return recorder.flush()

    # ─────────── internals ────────────────────────────────────────────

    def _snapshot(self, payload: dict, game_time_s: int, tag: Optional[str]) -> int:
        """Buffer one snapshot. Caller holds the lock. Returns rows buffered."""
        return recorder.record_state_snapshot(
            payload,
            match_id=self.match_id,
            session_id=self.session_id,
            champion=self.champion or payload.get("champion"),
            mode=self.mode or payload.get("game_mode") or payload.get("mode"),
            game_time_s=game_time_s,
            milestone_tag=tag,
            provenance="source_truth",
        )
