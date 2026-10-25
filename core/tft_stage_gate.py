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

The gate judges one read at a time and names the round to act on:

  screened out   a read outside the round structure below, or one not
                 reachable from 1-1 by this game time at the queue's
                 MEASURED round pace (a stale previous-game OCR value at a
                 fresh clock, a stage-6 misread at minute 8), is rejected
                 and never counts toward anything.
  new game       the game clock restarting (:2999 gameTime starts at 0 each
                 game) on CLOCK_RESET_READS consecutive reads resets the
                 gate: the bypass, a genuine new game never waits on the
                 gate. One glitched clock value is not a new game. With no
                 clock the pre-RM-615 rule (stage > 2 -> stage <= 2) still
                 decides, so nothing regresses.
  fast path      while the last WINDOW_READS reads all agreed with the
                 accepted round, a forward read within the pace allowance
                 (FORWARD_SLACK_ROUNDS plus the measured pace since the
                 round was accepted; UNRATED_SLACK_ROUNDS for a queue with
                 no measured pace) is taken at once - a real round change,
                 or a one-off misread the next reads overturn.
  majority       otherwise the accepted round moves only to a round that
                 holds at least SWITCH_MIN_READS of the last WINDOW_READS
                 reads AND leads the accepted round there by SWITCH_MARGIN.
                 The hysteresis margin is what stops a flicker: a value that
                 keeps returning (the true round, or a stubborn misread)
                 holds its ground, so the gate neither sticks to a misread
                 the true round outvotes nor flips with every frame. A
                 backward read is held unless the majority carries it (the
                 gate may have taken a one-off misread on the fast path).
  revert         a majority move back to the round before the last change
                 is reported as REVERT, so the live analysis restores that
                 round's timer instead of re-arming its planning scan.

PURE: no I/O, no clock of its own, no RC imports. The caller passes the game
clock (seconds), so the gate is deterministic under test and in replay.

PER-QUEUE PACE is our own measurement only, and it is NOT copied here: the
caller computes it at runtime from the reader's calibrated round table
(tft/tft_state_reader.py `_TIME_TO_ROUND`, fitted to confirmed live points)
with pace_floor_from_table(): PACE_SAFETY (half) of the fastest per-round
pace between consecutive table entries, so a re-measured or per-set table
(the Set 18 timings) flows in without an edit here. Half admits a
legitimate catch-up after missed reads at twice the fastest measured pace,
and covers the gate's anchor time trailing the true round start by a poll
or an OCR cycle. The table is measured on standard-structure games, so it
rates "standard" and "double_up" (detect_variant, tft/tft_state_reader.py
:127, calls every mapNumber-22 game Double Up, and the LCU reported mapId 22
for a queue-1090 Normal game on 2026-10-25, so the table's games are one or
the other). Hyper Roll has never been measured here and carries NO rate (it
never borrows the standard one, the RM-855 doctrine); an unknown queue is
UNMEASURED the same way. No pace (unreadable table) means no rate, never a
guessed one.

WINDOW CONSTANTS are sized on the read cadence: the worker polls every
1.5 s (core/tft_worker.py:44) and the reader's OCR cache refreshes about
every 2 s (tft/tft_state_reader.py:84), so two polls can see one OCR
refresh; WINDOW_READS = 7 polls (about 10.5 s) span about five refreshes and
SWITCH_MIN_READS = 4 needs a majority of them. SWITCH_MARGIN = 2 is the
hysteresis that keeps a 50/50 flicker from flipping the gate (a margin of 1
flips it every few polls); FAST_PATH_MAX_DISSENT = 1 lets a genuine round
change through at once after one stray read. Measured on a seeded misread
model (2 s OCR frames, 1.5 s polls, the reader's table as truth, 25 games
per setting, 5 / 10 / 20 percent of frames misread; s134): versus
pre-RM-615, wrong-round polls fall 43-53 percent for -1 misreads and 16-31
percent for mixed ones, and change -3 to +14 percent for +1-only misreads
(the filter's latency when a misread of round N is round N+1); planning
scans fall 46-70 percent and false new games from 16-113 to 0. The cost: the
longest wrong run grows (7-24 polls against 4-9) because a burst of
misreads can win a window. A stream misread HALF the time has no majority:
the gate then holds the round it has instead of flipping per frame.
"""
from __future__ import annotations

import math
from collections import deque
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
ACCEPT = "accept"      # first read, a fast-path advance, or a majority move
SAME = "same"          # the accepted round again
NEW_GAME = "new_game"  # a genuine new game: the gate reset
REJECT = "reject"      # not taken: the accepted round holds
REVERT = "revert"      # a majority move back to the round before the last change

# -- tuning ------------------------------------------------------------------
# One round at once on a measured queue; the clock admits more.
FORWARD_SLACK_ROUNDS = 1
# One round plus one for a stage that ends a round before the structure cap
# (a set's stage 1 may end at 1-3, a stage at x-6), so a round table's stream
# takes the fast path on a queue with no measured pace.
UNRATED_SLACK_ROUNDS = 2
WINDOW_READS = 7
SWITCH_MIN_READS = 4
SWITCH_MARGIN = 2
FAST_PATH_MAX_DISSENT = 1
PACE_SAFETY = 0.5
# The game clock must fall by more than this, on this many consecutive
# reads, to count as a restart.
CLOCK_RESET_SLACK_S = 5.0
CLOCK_RESET_READS = 2
# A :2999 game clock past this is not a TFT game clock (TFT games end well
# inside an hour); it is treated as no clock.
MAX_GAME_S = 7200.0


class QueueTiming(NamedTuple):
    variant: str
    rated: bool    # takes the measured pace (the reader's round table)
    source: str


_MEASURED_SOURCE = ("measured: the reader's calibrated round table "
                    "(tft/tft_state_reader.py _TIME_TO_ROUND), via pace_floor_from_table")
QUEUE_TIMINGS = {
    "standard": QueueTiming("standard", True, _MEASURED_SOURCE),
    "double_up": QueueTiming("double_up", True, _MEASURED_SOURCE),
    "hyper_roll": QueueTiming("hyper_roll", False, "unmeasured: no Hyper Roll pace recorded"),
}
UNMEASURED = QueueTiming("unknown", False, "unmeasured: unknown queue")

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
    if isinstance(v, str):
        v = v.strip()
        # isascii: str.isdigit() accepts superscripts that int() rejects
        if v.isascii() and v.isdigit() and len(v) <= 4:
            return int(v)
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


def stage_round_of(o: int) -> Tuple[int, int]:
    """Inverse of ordinal() for a legal ordinal."""
    if o <= STAGE1_ROUNDS:
        return 1, o
    q, r = divmod(o - STAGE1_ROUNDS - 1, STAGE_ROUNDS)
    return q + 2, r + 1


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


def pace_floor_from_table(table: object) -> Optional[float]:
    """PACE_SAFETY x the fastest per-round pace (seconds per ordinal step)
    between consecutive entries of a round table shaped like the reader's
    `_TIME_TO_ROUND`: an ordered sequence of (game seconds, stage, round).

    None when the table is unreadable or yields no forward step, so a
    missing or reshaped table means "no rate", never a guessed one.
    """
    if not isinstance(table, (list, tuple)):
        return None
    prev = None
    best = None
    for row in table:
        if not isinstance(row, (list, tuple)) or len(row) != 3:
            return None
        t, s, r = row
        if isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t):
            return None
        o = ordinal(s, r)
        if o is None:
            return None
        if prev is not None:
            dt, steps = t - prev[0], o - prev[1]
            if dt <= 0 or steps <= 0:
                return None
            pace = dt / steps
            best = pace if best is None else min(best, pace)
        prev = (float(t), o)
    if best is None:
        return None
    return PACE_SAFETY * best


def _clock(t: object) -> Optional[float]:
    """A usable game clock, else None. The reader defaults a missing gameTime
    to 0 (tft/tft_state_reader.py:145), so 0 means "no clock", never "the
    game restarted"; past MAX_GAME_S is no clock either."""
    if isinstance(t, bool) or not isinstance(t, (int, float)):
        return None
    try:
        t = float(t)
    except OverflowError:   # an int past the float range
        return None
    if not math.isfinite(t) or t <= 0 or t > MAX_GAME_S:
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
    t: Optional[float]   # game clock when this round was accepted


class StageGate:
    """Stateful wrapper over the rules above: one instance per reader."""

    def __init__(self, queue: object = None, min_round_s: Optional[float] = None) -> None:
        self._timing = timing_for(queue)
        self._pace: Optional[float] = None
        self.set_pace(min_round_s)
        self.reset()

    def set_pace(self, min_round_s: object) -> None:
        """The measured pace floor (seconds per round) for rated queues, from
        pace_floor_from_table() over the reader's table; None = no rate."""
        self._pace = _clock(min_round_s)   # a positive finite number, else None

    @property
    def rate(self) -> Optional[float]:
        """The pace floor in force: the measured pace on a rated queue, else None."""
        return self._pace if self._timing.rated else None

    def reset(self) -> None:
        self._anchor: Optional[_Anchor] = None
        self._prev: Optional[_Anchor] = None   # the anchor before the last change
        self._window: deque = deque(maxlen=WINDOW_READS)   # ordinals of counted reads
        self._last_t: Optional[float] = None
        self._reset_n = 0

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

    def _move(self, o: int, t: Optional[float], kind: str, reason: str) -> Verdict:
        s, r = stage_round_of(o)
        p = self._prev
        self._prev = self._anchor
        if kind == REVERT and p is not None:
            self._anchor = p     # back to the round before: keep its clock
        else:
            self._anchor = _Anchor(s, r, o, t)
        return self._verdict(kind, reason)

    def _first_ok(self, o: int, t: Optional[float]) -> bool:
        rate = self.rate
        if rate is None or t is None:
            return True
        return o - 1 <= FORWARD_SLACK_ROUNDS + int(t // rate)

    def _within_pace(self, a: _Anchor, o: int, t: Optional[float]) -> bool:
        steps = o - a.ordinal
        rate = self.rate
        if rate is not None and t is not None and a.t is not None:
            return steps <= FORWARD_SLACK_ROUNDS + int(max(0.0, t - a.t) // rate)
        return steps <= UNRATED_SLACK_ROUNDS

    # -- the rule ------------------------------------------------------------
    def observe(self, stage: object, rnd: object, game_time_s: object = None) -> Verdict:
        """Judge one read; the returned verdict names the round to act on."""
        t = _clock(game_time_s)
        o = ordinal(stage, rnd)

        # A restarted game clock, held for CLOCK_RESET_READS reads: new game.
        if t is not None and self._last_t is not None and t + CLOCK_RESET_SLACK_S < self._last_t:
            self._reset_n += 1
            if self._reset_n < CLOCK_RESET_READS:
                return self._verdict(REJECT, "clock_reset_pending")
            self.reset()
            self._last_t = t
            if o is not None and self._first_ok(o, t):
                self._window.append(o)
                self._move(o, t, NEW_GAME, "clock_reset")
                self._prev = None
                return self._verdict(NEW_GAME, "clock_reset")
            return self._verdict(NEW_GAME, "clock_reset")
        self._reset_n = 0
        if t is not None:
            self._last_t = t if self._last_t is None else max(self._last_t, t)

        if o is None:
            return self._verdict(REJECT, "out_of_range")
        if not self._first_ok(o, t):
            return self._verdict(REJECT, "implausible_at_clock")
        a = self._anchor
        if a is None:
            self._window.append(o)
            return self._move(o, t, ACCEPT, "first")
        if t is None and o < a.ordinal and a.stage > 2 and stage_round_of(o)[0] <= 2:
            # No clock to tell a glitch from a new game: the pre-RM-615
            # tft_live_analysis rule decides, so nothing regresses.
            self.reset()
            self._window.append(o)
            return self._move(o, None, NEW_GAME, "stage_reset_no_clock")

        # Clean: at most FAST_PATH_MAX_DISSENT stray reads, none of them this
        # value (a value that already came and went is a flicker, not news).
        clean = (o not in self._window
                 and sum(1 for x in self._window if x != a.ordinal) <= FAST_PATH_MAX_DISSENT)
        self._window.append(o)
        if o == a.ordinal:
            return self._verdict(SAME, "same")
        if clean and o > a.ordinal and self._within_pace(a, o, t):
            return self._move(o, t, ACCEPT, "advance")

        # Majority: the round being READ now moves the gate only if it holds
        # SWITCH_MIN_READS of the window and leads EVERY other value (the
        # accepted round included) by SWITCH_MARGIN. Only the read itself is
        # a candidate: an unrelated stray read just after a real advance must
        # not hand the round back to the stale reads still in the window, and
        # a split vote (a 50/50 flicker) moves nothing.
        n_o = sum(1 for x in self._window if x == o)
        others: dict = {}
        for x in self._window:
            if x != o:
                others[x] = others.get(x, 0) + 1
        runner_up = max(others.values(), default=0)
        if n_o >= SWITCH_MIN_READS and n_o >= runner_up + SWITCH_MARGIN:
            if self._prev is not None and o == self._prev.ordinal:
                return self._move(o, t, REVERT, "revert")
            return self._move(o, t, ACCEPT, "majority")
        if o < a.ordinal:
            return self._verdict(REJECT, "backward")
        if not self._within_pace(a, o, t):
            return self._verdict(REJECT, "forward_jump")
        return self._verdict(REJECT, "unconfirmed")
