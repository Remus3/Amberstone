"""core/tft_stage_gate.py - RM-615 (X-15): monotonic stage-round plausibility
gate for TFT stage reads.

A TFT stage read ("3-2") reaches the live analysis from OCR or from the
reader's time table (tft/tft_state_reader.py `_parse`). OCR misreads a digit
now and then, and the reader's own guard lets a read go up to one stage
BACKWARD (`going_backward`, tft/tft_state_reader.py:181). Downstream that one
bad read used to cost real work: tft/tft_live_analysis.py `notify_round`
treated any stage > 2 -> stage <= 2 read as a NEW GAME (augments cleared,
placement dropped), reset the round timer (one extra planning vision scan,
a paid call) on every flicker, and handed the misread label to the coach
prompt.

This module judges one read at a time against the last ACCEPTED read and
the game clock:

  out of range   outside the round structure below: held, never confirmed.
  backward       behind the accepted round while the game clock runs
                 forward: held (an OCR glitch, not a new game).
  at clock       not reachable from 1-1 by this game time at the queue's
                 MEASURED round pace (a stale previous-game OCR value at a
                 fresh clock, a stage-6 misread at minute 8): held.
  forward jump   further ahead of the accepted round than the time since it
                 was accepted allows at the measured pace: held. A queue
                 with no measured pace takes UNRATED_SLACK_ROUNDS at once
                 and a bigger jump only after confirmation.
  new game       the game clock restarted (:2999 gameTime starts at 0 each
                 game): the gate resets and the read is judged as a first
                 read. This is the bypass: a genuine new game never waits on
                 the gate. With no clock, the pre-RM-615 rule (stage > 2 ->
                 stage <= 2) still stands, so nothing regresses.
  confirmation   CONFIRM_READS consecutive identical held reads re-anchor
                 the gate when the ANCHOR may be the error (a backward or
                 forward-jump read after an anchor taken a round early or
                 confirmed onto a repeated misread, or an unrated jump), so
                 a wrong anchor cannot lock the gate in. An "at clock" or
                 out-of-range read is never confirmed by repetition: a stale
                 OCR cache repeats the same impossible value.

PURE: no I/O, no clock of its own, no RC imports. The caller passes the game
clock (seconds), so the gate is deterministic under test and in replay.

PER-QUEUE CONSTANTS are our own measurements only. The tree holds one set:
the four confirmed live points of tft/tft_state_reader.py:22-24, copied into
MEASURED_POINTS below. Their per-round pace between consecutive points is
45.1 / 43.6 / 46.2 s (ordinal steps of the structure below), so the floor
MIN_ROUND_S_MEASURED = 20.0 sits under HALF the fastest one: a legitimate
catch-up after missed reads is admitted at twice the fastest measured pace,
which also covers stage-1 rounds being shorter than the average and the
gate's anchor time trailing the true round start by a poll or an OCR cycle.
Those points were recorded as "Set 17 Space Gods Double Up", a label set by
`detect_variant` (tft/tft_state_reader.py:127), which calls every
mapNumber-22 game Double Up; the LCU reported mapId 22 for a queue-1090
Normal game on 2026-10-25 (the s134 recorder). So the measured queue is
Double Up OR Standard and the floor is applied to both; it is a floor well
under either pace, not a schedule. Hyper Roll has never been measured here
and carries NO rate (it never borrows the standard one, the RM-855
doctrine); an unknown queue is UNMEASURED the same way.
"""
from __future__ import annotations

import math
from typing import NamedTuple, Optional, Tuple

# -- round structure ---------------------------------------------------------
# The reader's OCR sanity bounds (tft/tft_state_reader.py:172-174): stage 1-7,
# round <= 4 in stage 1 and <= 7 after. A superset of every set's schedule,
# not a schedule: a stage may end before its cap.
STAGE_MIN = 1
STAGE_MAX = 7
STAGE1_ROUNDS = 4
STAGE_ROUNDS = 7

# -- verdict kinds -----------------------------------------------------------
ACCEPT = "accept"      # first read, a plausible advance, or a confirmed re-anchor
SAME = "same"          # the accepted round again
NEW_GAME = "new_game"  # a genuine new game: the gate reset
REJECT = "reject"      # implausible: the accepted round holds

# -- tuning ------------------------------------------------------------------
# One round at once on a measured queue; the clock admits more.
FORWARD_SLACK_ROUNDS = 1
# One round plus one for a stage that ends a round before the structure cap
# (the reader's calibrated table runs stage 1 to 1-3 and stages 2-6 to x-6,
# tft/tft_state_reader.py:25-31), so the reader's own table stream never
# waits on confirmation on a queue with no measured pace.
UNRATED_SLACK_ROUNDS = 2
# Consecutive identical held reads that re-anchor the gate. At the worker's
# 1.5 s poll (core/tft_worker.py:44) this is about 4.5 s; the reader's OCR
# loop refreshes every 2 s (tft/tft_state_reader.py:84), so a one-off misread
# rarely survives three polls.
CONFIRM_READS = 3
# The game clock must fall by more than this to count as a restart.
CLOCK_RESET_SLACK_S = 5.0

# The four confirmed live points, verbatim from tft/tft_state_reader.py:23:
# (game time s, stage, round).
MEASURED_POINTS = ((32.0, 1, 2), (348.0, 2, 5), (1002.0, 4, 6), (1879.0, 7, 4))
MIN_ROUND_S_MEASURED = 20.0


class QueueTiming(NamedTuple):
    variant: str
    min_round_s: Optional[float]   # None = unmeasured: no clock-rate check
    source: str


_MEASURED_SOURCE = ("measured: tft/tft_state_reader.py:22-24 confirmed live points, "
                    "fastest pace 43.6 s/round; floor under half of it")
QUEUE_TIMINGS = {
    "standard": QueueTiming("standard", MIN_ROUND_S_MEASURED, _MEASURED_SOURCE),
    "double_up": QueueTiming("double_up", MIN_ROUND_S_MEASURED, _MEASURED_SOURCE),
    "hyper_roll": QueueTiming("hyper_roll", None, "unmeasured: no Hyper Roll pace recorded"),
}
UNMEASURED = QueueTiming("unknown", None, "unmeasured: unknown queue")

# LCU queue ids (names: lcu/snapshot_shape.py:74-78) -> the state's "variant"
# (tft/tft_state_reader.py detect_variant).
QUEUE_VARIANT = {1090: "standard", 1100: "standard", 1130: "hyper_roll", 1160: "double_up"}


def timing_for(queue: object) -> QueueTiming:
    """The timing for a queue id (int) or a reader variant (str).

    Anything else, or an unlisted queue, is UNMEASURED. Never raises.
    """
    if isinstance(queue, bool):
        return UNMEASURED
    if isinstance(queue, int):
        queue = QUEUE_VARIANT.get(queue)
    if isinstance(queue, str):
        return QUEUE_TIMINGS.get(queue.strip().lower(), UNMEASURED)
    return UNMEASURED


def _as_int(v: object) -> Optional[int]:
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and math.isfinite(v) and v.is_integer():
        return int(v)
    if isinstance(v, str) and v.strip().isdigit():
        return int(v.strip())
    return None


def ordinal(stage: object, rnd: object) -> Optional[int]:
    """Position of stage-round in the structure (1-1 = 1, 2-1 = 5), or None
    when the read is outside it."""
    s, r = _as_int(stage), _as_int(rnd)
    if s is None or r is None or not STAGE_MIN <= s <= STAGE_MAX:
        return None
    if not 1 <= r <= (STAGE1_ROUNDS if s == 1 else STAGE_ROUNDS):
        return None
    return r if s == 1 else STAGE1_ROUNDS + (s - 2) * STAGE_ROUNDS + r


def parse_stage_round(label: object) -> Optional[Tuple[int, int]]:
    """'3-2' -> (3, 2); None for anything outside the structure."""
    if not isinstance(label, str):
        return None
    parts = label.split("-")
    if len(parts) != 2:
        return None
    s, r = _as_int(parts[0]), _as_int(parts[1])
    if ordinal(s, r) is None:
        return None
    return s, r


def _clock(t: object) -> Optional[float]:
    """A usable game clock, else None. The reader defaults a missing gameTime
    to 0 (tft/tft_state_reader.py:145), so 0 means "no clock", never "the
    game restarted"."""
    if isinstance(t, bool) or not isinstance(t, (int, float)):
        return None
    t = float(t)
    if not math.isfinite(t) or t <= 0:
        return None
    return t


class Verdict(NamedTuple):
    kind: str
    reason: str
    stage: Optional[int]   # the round the caller should act on (None = none yet)
    rnd: Optional[int]

    @property
    def stage_round(self) -> str:
        return f"{self.stage}-{self.rnd}" if self.stage is not None else ""


class _Anchor(NamedTuple):
    stage: int
    rnd: int
    ordinal: int
    t: Optional[float]   # game clock when this round was first accepted


# Held reasons a repetition may overturn, because the ANCHOR may be the error
# (taken a round early, or confirmed onto a repeated misread): a backward
# read, and a forward read the clock allows from 1-1 but the anchor's pace
# does not. A read the clock rules out from 1-1 ("implausible_at_clock") and
# an out-of-range read are never overturned: a stale OCR cache repeats them.
_CONFIRMABLE = frozenset({"backward", "forward_jump", "forward_unrated"})


class StageGate:
    """Stateful wrapper over the rules above: one instance per reader."""

    def __init__(self, queue: object = None) -> None:
        self._timing = timing_for(queue)
        self.reset()

    def reset(self) -> None:
        self._anchor: Optional[_Anchor] = None
        self._last_t: Optional[float] = None
        self._pending: Optional[Tuple[int, int]] = None
        self._pending_n = 0

    @property
    def timing(self) -> QueueTiming:
        return self._timing

    def set_queue(self, queue: object) -> None:
        self._timing = timing_for(queue)

    @property
    def accepted(self) -> Optional[Tuple[int, int]]:
        a = self._anchor
        return (a.stage, a.rnd) if a is not None else None

    # -- internals -----------------------------------------------------------
    def _verdict(self, kind: str, reason: str) -> Verdict:
        a = self._anchor
        return Verdict(kind, reason, a.stage if a else None, a.rnd if a else None)

    def _take(self, s: int, r: int, o: int, t: Optional[float], kind: str, reason: str) -> Verdict:
        self._anchor = _Anchor(s, r, o, t)
        self._pending, self._pending_n = None, 0
        return self._verdict(kind, reason)

    def _hold(self, s: int, r: int, o: int, t: Optional[float], reason: str) -> Verdict:
        if reason not in _CONFIRMABLE:
            self._pending, self._pending_n = None, 0
            return self._verdict(REJECT, reason)
        if self._pending == (s, r):
            self._pending_n += 1
        else:
            self._pending, self._pending_n = (s, r), 1
        if self._pending_n >= CONFIRM_READS:
            return self._take(s, r, o, t, ACCEPT, "confirmed_" + reason)
        return self._verdict(REJECT, reason)

    def _first_ok(self, o: int, t: Optional[float]) -> bool:
        rate = self._timing.min_round_s
        if rate is None or t is None:
            return True
        return o - 1 <= FORWARD_SLACK_ROUNDS + int(t // rate)

    # -- the rule ------------------------------------------------------------
    def observe(self, stage: object, rnd: object, game_time_s: object = None) -> Verdict:
        """Judge one read; the returned verdict names the round to act on."""
        t = _clock(game_time_s)
        o = ordinal(stage, rnd)
        s, r = _as_int(stage), _as_int(rnd)

        # A restarted game clock is a new game: the bypass.
        if t is not None and self._last_t is not None and t + CLOCK_RESET_SLACK_S < self._last_t:
            self.reset()
            self._last_t = t
            if o is not None and self._first_ok(o, t):
                return self._take(s, r, o, t, NEW_GAME, "clock_reset")
            return self._verdict(NEW_GAME, "clock_reset")
        if t is not None:
            self._last_t = t if self._last_t is None else max(self._last_t, t)

        if o is None:
            return self._hold(0, 0, 0, t, "out_of_range")
        a = self._anchor
        if a is None:
            if self._first_ok(o, t):
                return self._take(s, r, o, t, ACCEPT, "first")
            return self._hold(s, r, o, t, "implausible_at_clock")
        if o == a.ordinal:
            self._pending, self._pending_n = None, 0
            return self._verdict(SAME, "same")
        if o < a.ordinal:
            if t is None and a.stage > 2 and s <= 2:
                # No clock to tell a glitch from a new game: the pre-RM-615
                # tft_live_analysis rule decides, so nothing regresses.
                self.reset()
                return self._take(s, r, o, None, NEW_GAME, "stage_reset_no_clock")
            return self._hold(s, r, o, t, "backward")
        if not self._first_ok(o, t):
            # Not reachable from 1-1 at this game time at the measured pace,
            # whatever the anchor says: never confirmed by repetition.
            return self._hold(s, r, o, t, "implausible_at_clock")
        steps = o - a.ordinal
        rate = self._timing.min_round_s
        if rate is not None and t is not None and a.t is not None:
            if steps <= FORWARD_SLACK_ROUNDS + int(max(0.0, t - a.t) // rate):
                return self._take(s, r, o, t, ACCEPT, "advance")
            return self._hold(s, r, o, t, "forward_jump")
        if steps <= UNRATED_SLACK_ROUNDS:
            return self._take(s, r, o, t, ACCEPT, "advance")
        return self._hold(s, r, o, t, "forward_unrated")
