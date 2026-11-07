"""
MetricStreamer - cadence wrapper around `core.match_metrics.recorder`.

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
  - stateless between snapshots - no internal payload diffing; that's
    the coach's job

Cadence rules:
  - `game_start`                   -> one-shot snapshot on the first tick
                                     (whatever the clock reads then)
  - every 60s of in-game time      -> snapshot with milestone_tag=None
                                     (time-series base), at most one per
                                     60s bucket; a tick that writes any
                                     tagged snapshot consumes its bucket,
                                     so the next tick does not write a
                                     near-duplicate periodic row
  - each of 10/15/20/25/30 min_mark -> snapshot with the mark tag, only
                                     while the mark is under 60s old; a
                                     mark first seen later (a streamer
                                     started mid-game after an RC restart,
                                     or a stalled coach) is consumed with
                                     no snapshot rather than mislabelling
                                     later data as that mark
  - l6_spike / l11_spike / l16_spike -> snapshot on level transitions;
                                     several crossed in one tick (Arena
                                     levels move by rounds) snapshot only
                                     the highest, and levels already
                                     passed at the FIRST level reading are
                                     consumed (a mid-game join has no
                                     snapshot from when they were hit)
  - event-driven (first_blood, first_tower, drake_take, baron_take,
    death, kill, ...) -> snapshot with tag; first_blood / first_tower /
    laning_end fire once per match
  - `game_end` -> final snapshot (once), then close()

Input contract (the payload is coach-built from feeds RC does not
control): a game clock or level that is not a non-negative finite number
(None, bool, str, NaN, infinity, negative) is UNKNOWN - never raised on,
never recorded as 0:00; an unknown clock fires no time mark and no
periodic sample and the row's clock is stored NULL. `events` is a list /
tuple / set of event names or one bare name; anything else, and any
non-str item, is ignored.

WIRE-IN (coach side):

    # At coach init:
    from core.metric_streamer import MetricStreamer
    streamer = MetricStreamer(match_id=..., champion=..., mode=...)

    # On every tick after writing coaching_data.json:
    streamer.on_state(coaching_data, events=live_events)

    # At game end:
    streamer.on_state(coaching_data, events=[...], game_end=True)
    streamer.close()

In production the wire-in is owned by `core.live_metrics.stream()` - the
sr/aram/arena/brawl coaches call it after each coaching write (so a
"tick" here is a coaching write, not a game-loop tick), as
`on_state(cur)` only: no `events`, no `game_end` and no close(), so the
event-driven and game_end rules are unreached in production today. It is gated
OFF by default (RC_LIVE_METRICS env or coach_settings.json
`live_metrics_enabled`) and error-wrapped so a streaming fault can never
crash the coach.
"""
from __future__ import annotations

import math
import threading
from typing import Any, Optional

from core.match_metrics import recorder

# Game-time thresholds -> milestone tag.
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
# Event tags that fire at most once per match.
_SINGLE_FIRE_TAGS = frozenset({"first_blood", "first_tower", "laning_end"})


def _whole_number(value: Any) -> Optional[int]:
    """A game clock or level as a non-negative whole number, else None.

    bool, str, NaN, infinity and negatives are not readings (int() raised
    on NaN / infinity, and a bool or a missing clock used to read as 0).
    Floats truncate."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value < 0:
        return None
    return int(value)


def _event_names(events: Any) -> list[str]:
    """The str event names in `events`: a list / tuple / set of names, or
    one bare name. Anything else (a dict, a number, an object) is no
    events; a non-str item (unhashable or not) is skipped."""
    if events is None:
        return []
    if isinstance(events, str):
        return [events]
    if not isinstance(events, (list, tuple, set, frozenset)):
        return []
    return [ev for ev in events if isinstance(ev, str)]


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
        self._last_periodic_s: int = -1  # last 60 s bucket start consumed
        self._milestones_fired: set[str] = set()  # one-shot per match
        self._last_level: int = 0
        self._level_seen = False  # first level reading only seeds

    # ----------- public API -------------------------------------------

    def on_state(self, payload: dict, *,
                 events: Optional[list[str]] = None,
                 game_end: bool = False) -> int:
        """Called by the coach on every tick. Returns the number of metric
        rows buffered this call (0 if no cadence rule fired or the payload
        is not a dict). Bad clock / level / event inputs never raise (see
        the module docstring); a recorder flush failure DOES propagate -
        the rows stay buffered in the recorder for the next flush and the
        cadence state is kept, so core.live_metrics.stream() contains it."""
        if not isinstance(payload, dict):
            return 0
        gt = _whole_number(payload.get("game_time_s"))
        level = _whole_number(payload.get("level"))
        names = _event_names(events)

        rows = 0
        with self._lock:
            fired = self._milestones_fired
            tags: list[Optional[str]] = []

            # 1. game_start one-shot
            first_tick = not self._started
            if first_tick:
                self._started = True
                tags.append("game_start")

            # 2. level-based milestones (l6/l11/l16): consume every one
            #    crossed, snapshot only the highest; the first level reading
            #    only seeds (levels passed before it get no snapshot).
            if level is not None and level > self._last_level:
                crossed = [tag for lvl, tag in sorted(_LEVEL_MILESTONES.items())
                           if self._last_level < lvl <= level
                           and tag not in fired]
                fired.update(crossed)
                if crossed and self._level_seen:
                    tags.append(crossed[-1])
                self._last_level = level
            if level is not None:
                self._level_seen = True

            # 3. time-based milestones (10/15/20/25/30 min_mark): consume
            #    every one passed, snapshot only a mark under one periodic
            #    interval old.
            if gt is not None:
                for threshold, tag in _TIME_MILESTONES:
                    if gt >= threshold and tag not in fired:
                        fired.add(tag)
                        if gt - threshold < _PERIODIC_INTERVAL_S:
                            tags.append(tag)

            # 4. event-driven (single-fire per match for first_blood /
            #    first_tower / laning_end; multi-fire for the rest).
            for ev in names:
                tag = _EVENT_TAGS.get(ev)
                if not tag:
                    continue
                if tag in _SINGLE_FIRE_TAGS:
                    if tag in fired:
                        continue
                    fired.add(tag)
                tags.append(tag)

            # 5. game_end final snapshot (once).
            end = bool(game_end) and "game_end" not in fired
            if end:
                fired.add("game_end")

            # 6. periodic 60s sample, only when nothing else is written
            #    this tick; any snapshot consumes the tick's bucket.
            if gt is not None:
                bucket = (gt // _PERIODIC_INTERVAL_S) * _PERIODIC_INTERVAL_S
                if (not tags and not end and bucket >= _PERIODIC_INTERVAL_S
                        and bucket > self._last_periodic_s):
                    tags.append(None)
                if tags or end:
                    self._last_periodic_s = max(self._last_periodic_s, bucket)

            if end:
                tags.append("game_end")

            for tag in tags:
                rows += self._snapshot(payload, gt, tag)

        # Flush outside the lock so the DB write doesn't serialize ticks.
        if rows > 0:
            recorder.flush()
        return rows

    def close(self) -> int:
        """Flush the recorder's buffered rows (the recorder is the
        process-wide singleton, so this flushes every buffered match).
        Runs outside the cadence lock, like the per-tick flush: a slow DB
        write here must not block a concurrent on_state(). The recorder
        serializes its own buffer."""
        return recorder.flush()

    # ----------- internals --------------------------------------------

    def _snapshot(self, payload: dict, game_time_s: Optional[int],
                  tag: Optional[str]) -> int:
        """Buffer one snapshot. Caller holds the lock. Returns rows
        buffered. An unknown clock (None) is stored NULL by the recorder."""
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
