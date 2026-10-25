"""RM-615 (X-15): the pure monotonic stage-round plausibility gate.

`core/tft_stage_gate.py` judges one TFT stage read at a time and names the
round to act on: reads outside the structure or not reachable at the game
clock are screened out; while the recent window agrees with the accepted
round a forward read within the measured pace is taken at once; otherwise
the accepted round moves only to a round holding a windowed majority with a
hysteresis margin; a restarted game clock (or, with no clock, the legacy
"stage > 2 -> stage <= 2" rule) is a new game and bypasses the gate.

HISTORY. Two earlier cuts of this slice were REFUTED by independent
verifiers: an anchor + consecutive-confirmation design could be held on a
misread for a whole round by interleaved reads, and flipped on every poll
under a mixed flicker. The cases named LOCK1 / LOCK2 / (a1)-(a3) / (c) below
are those verifiers' reproducers, kept as regression tests.

FIXTURE PROVENANCE. No live stage sample exists this session (the s134
recorder saw no TFT state: TFT ran as a standalone client and nothing was
served on :2999), so the measured data is the tree's own: the reader's
calibrated round table `_TIME_TO_ROUND` (tft/tft_state_reader.py:21, fitted
to the confirmed live points its comment records) read through
`_estimate_round` (:33) - the stage stream production publishes whenever OCR
is unavailable. Nothing here copies that table: tests read it from the
reader, so a re-measured table (the Set 18 timings) is exercised as-is.

Names used, cited at the fix tree:
  core/tft_stage_gate.py  STAGE_MAX, STAGE1_ROUNDS, STAGE_ROUNDS,
      ACCEPT / SAME / NEW_GAME / REJECT / REVERT, FORWARD_SLACK_ROUNDS,
      UNRATED_SLACK_ROUNDS, WINDOW_READS, SWITCH_MIN_READS, SWITCH_MARGIN,
      PACE_SAFETY, CLOCK_RESET_SLACK_S, CLOCK_RESET_READS, MAX_GAME_S,
      QueueTiming, QUEUE_TIMINGS, QUEUE_VARIANT, UNMEASURED, timing_for,
      ordinal, stage_round_of, parse_stage_round, pace_floor_from_table,
      Verdict, StageGate (observe / reset / set_queue / set_pace / rate /
      accepted / timing).
  lcu/snapshot_shape.py:74-78  the TFT queue names (1090 Normal, 1100
      Ranked, 1130 Hyper Roll, 1160 Double Up).
  tft/tft_state_reader.py  `_TIME_TO_ROUND` :21, `_estimate_round` :33,
      the state's "variant" (detect_variant :127, set in `_parse`).
  core/tft_worker.py:44  POLL_INTERVAL_S = 1.5; tft/tft_state_reader.py:84
      the OCR loop's 2 s refresh.
"""
from __future__ import annotations

import ast
import random
from pathlib import Path

import pytest

from core import tft_stage_gate as g
from tft import tft_state_reader as reader

REPO = Path(__file__).resolve().parent.parent
PACE = 20.0          # an explicit pace for rule tests; the reader's own is tested separately
POLL = 1.5           # core/tft_worker.py:44
OCR_PERIOD = 2.0     # tft/tft_state_reader.py:84


def _gate(queue="standard", pace=PACE):
    return g.StageGate(queue, min_round_s=pace)


def _fill(gate, sr, t0, n=g.WINDOW_READS):
    """n reads of one round from t0, one poll apart; returns the next poll time."""
    t = t0
    for _ in range(n):
        gate.observe(*sr, t)
        t += POLL
    return t


# -- structure ---------------------------------------------------------------

def test_ordinal_follows_the_round_structure_and_inverts():
    assert g.ordinal(1, 1) == 1
    assert g.ordinal(1, 4) == 4
    assert g.ordinal(2, 1) == 5          # 2-1 follows 1-4 directly
    assert g.ordinal(3, 1) == 12
    assert g.ordinal(7, 4) == 4 + 5 * 7 + 4
    legal = [(s, r) for s in range(1, g.STAGE_MAX + 1)
             for r in range(1, (g.STAGE1_ROUNDS if s == 1 else g.STAGE_ROUNDS) + 1)]
    seq = [g.ordinal(*sr) for sr in legal]
    assert seq == list(range(1, len(legal) + 1))
    for sr in legal:
        assert g.stage_round_of(g.ordinal(*sr)) == sr


@pytest.mark.parametrize("stage,rnd", [
    (0, 1), (g.STAGE_MAX + 1, 1), (1, 0), (1, g.STAGE1_ROUNDS + 1),
    (2, g.STAGE_ROUNDS + 1), (None, 1), (3, None), (True, 1), ("x", 2), (2.5, 1),
    (chr(0xB2), 1), ("9" * 5000, 1), (10 ** 400, 1),
])
def test_ordinal_rejects_reads_outside_the_structure(stage, rnd):
    assert g.ordinal(stage, rnd) is None


def test_parse_stage_round_labels():
    assert g.parse_stage_round("3-2") == (3, 2)
    assert g.parse_stage_round(" 4 - 6 ") == (4, 6)
    for bad in ("", "3", "3-", "9-1", "1-5", "a-b", None, 32, "3-2-1", chr(0xB2) + "-1"):
        assert g.parse_stage_round(bad) is None, bad


def test_every_round_of_the_reader_table_is_legal():
    """The gate's structure (stage 1-7, <= 4 rounds in stage 1, <= 7 after:
    the reader's OCR sanity bounds) holds every round the reader's own table
    can publish, whatever that table currently says."""
    table = reader._TIME_TO_ROUND
    assert len(table) >= 2
    for _t, s, r in table:
        assert g.ordinal(s, r) is not None, (s, r)
    assert (g.STAGE_MAX, g.STAGE1_ROUNDS, g.STAGE_ROUNDS) == (7, 4, 7)


# -- per-queue constants and the measured pace ---------------------------------

def test_queue_ids_map_to_reader_variants():
    # lcu/snapshot_shape.py:74-78 names these four TFT queues.
    assert g.QUEUE_VARIANT == {1090: "standard", 1100: "standard",
                               1130: "hyper_roll", 1160: "double_up"}
    for qid, variant in g.QUEUE_VARIANT.items():
        assert g.timing_for(qid) is g.QUEUE_TIMINGS[variant]
        assert g.timing_for(variant) is g.QUEUE_TIMINGS[variant]
    src = (REPO / "tft" / "tft_state_reader.py").read_text(encoding="utf-8")
    for variant in ("standard", "hyper_roll", "double_up"):
        assert f'"{variant}"' in src        # detect_variant can return it
        assert variant in g.QUEUE_TIMINGS


@pytest.mark.parametrize("queue", [None, "", "arena", 1110, 0, True, 3.5, object()])
def test_unknown_queue_is_unmeasured_never_borrowed(queue):
    assert g.timing_for(queue) is g.UNMEASURED
    assert g.StageGate(queue, min_round_s=PACE).rate is None


def test_only_measured_queues_take_the_pace():
    """Hyper Roll's pace has never been measured here, so it never borrows
    the standard one (the RM-855 doctrine)."""
    assert g.StageGate("standard", min_round_s=PACE).rate == PACE
    assert g.StageGate("double_up", min_round_s=PACE).rate == PACE
    assert g.StageGate("hyper_roll", min_round_s=PACE).rate is None
    assert "unmeasured" in g.QUEUE_TIMINGS["hyper_roll"].source
    assert g.StageGate("standard").rate is None          # no pace given = no rate
    for bad in (0, -5.0, float("nan"), "20", True, None):
        assert g.StageGate("standard", min_round_s=bad).rate is None


def test_pace_floor_from_a_synthetic_table():
    # 63 s per round over full 7-round stages (the shape a re-measured set
    # table may take): floor = PACE_SAFETY x 63
    table = [(0, 1, 1), (63, 1, 2), (126, 1, 3), (189, 1, 4), (252, 2, 1), (315, 2, 2)]
    assert g.pace_floor_from_table(table) == pytest.approx(g.PACE_SAFETY * 63.0)
    # a stage boundary that skips a structure slot counts as two steps
    assert g.pace_floor_from_table([(0, 2, 6), (50, 3, 1)]) == pytest.approx(g.PACE_SAFETY * 25.0)


@pytest.mark.parametrize("bad", [
    None, [], [(0, 1, 1)], "table", [(0, 1, 1), (30, 1, 1)], [(30, 1, 2), (0, 1, 3)],
    [(0, 1, 1), (30, 9, 9)], [(0, 1, 1), (30, 1)], [(0, 1, 1), ("x", 1, 2)],
    [(0, 1, 2), (30, 1, 1)], [(0, 1, 1), (float("nan"), 1, 2)],
])
def test_pace_floor_from_an_unreadable_table_is_none(bad):
    assert g.pace_floor_from_table(bad) is None


def test_pace_floor_from_the_reader_table():
    """Recomputed here independently from the reader's live table."""
    table = reader._TIME_TO_ROUND
    paces = [(t1 - t0) / (g.ordinal(s1, r1) - g.ordinal(s0, r0))
             for (t0, s0, r0), (t1, s1, r1) in zip(table, table[1:])]
    floor = g.pace_floor_from_table(table)
    assert floor == pytest.approx(g.PACE_SAFETY * min(paces))
    assert 0 < floor < min(paces)


# -- screening and the monotonic hold ----------------------------------------

def test_first_read_and_one_step_advances_are_accepted():
    gate = _gate()
    v = gate.observe(3, 2, 600.0)
    assert (v.kind, v.reason, v.stage, v.rnd) == (g.ACCEPT, "first", 3, 2)
    assert gate.observe(3, 2, 610.0).kind == g.SAME
    v = gate.observe(3, 3, 640.0)
    assert (v.kind, v.reason, v.stage, v.rnd) == (g.ACCEPT, "advance", 3, 3)
    assert gate.accepted == (3, 3) and v.stage_round == "3-3"


def test_backward_glitch_with_a_running_clock_is_held():
    gate = _gate()
    t = _fill(gate, (4, 2), 820.0)
    for s, r in ((2, 1), (1, 2), (4, 1)):
        v = gate.observe(s, r, t)
        assert (v.kind, v.reason, v.stage, v.rnd) == (g.REJECT, "backward", 4, 2), (s, r)
        assert v.stage_round == "4-2"
        t += POLL
    assert gate.accepted == (4, 2)


def test_out_of_range_reads_never_count():
    gate = _gate()
    t = _fill(gate, (3, 1), 450.0)
    for _ in range(g.WINDOW_READS + 3):
        assert gate.observe(9, 9, t).reason == "out_of_range"
        t += POLL
    assert gate.accepted == (3, 1)
    assert gate.observe(3, 2, t + 40.0).reason == "advance"   # the window stayed clean


def test_read_unreachable_at_the_clock_is_screened_and_never_counts():
    gate = _gate()
    t = _fill(gate, (3, 2), 500.0)
    for _ in range(g.WINDOW_READS + 3):              # stage 6 at minute 8, repeated
        v = gate.observe(6, 1, t)
        assert (v.kind, v.reason) == (g.REJECT, "implausible_at_clock")
        t += POLL
    assert gate.accepted == (3, 2)


def test_implausible_first_read_is_held():
    """A stale previous-game value at a fresh game clock (the reader's OCR
    cache outlives the game, tft/tft_state_reader.py:56 / :81) is held."""
    gate = _gate()
    for i in range(g.WINDOW_READS):
        v = gate.observe(5, 3, 3.0 + i * POLL)
        assert v.kind == g.REJECT and v.reason == "implausible_at_clock"
    assert gate.accepted is None and v.stage is None and v.stage_round == ""
    assert gate.observe(5, 3, 1300.0).reason == "first"     # joined late, matching clock


# -- fast path, majority, revert -------------------------------------------------

def test_one_off_forward_misread_reverts_at_the_next_true_read():
    gate = _gate()
    t = _fill(gate, (3, 3), 600.0)
    assert gate.observe(3, 4, t).reason == "advance"          # clean window: taken at once
    v = gate.observe(3, 3, t + POLL)
    assert (v.kind, v.stage, v.rnd) == (g.REVERT, 3, 3)


def test_revert_keeps_the_reverted_to_round_clock():
    """The round reverted to keeps the time it was first accepted at, so the
    pace allowance after a revert is not shortened."""
    gate = _gate()
    t0 = 500.0
    t = _fill(gate, (3, 2), t0)
    gate.observe(3, 3, t)
    t_revert = t + POLL
    assert gate.observe(3, 2, t_revert).kind == g.REVERT
    t = _fill(gate, (3, 2), t_revert + POLL)                # clean the window again
    # 3 steps at once are allowed from 3-2's own acceptance time t0, and
    # would not be from a clock re-stamped at the revert
    t_jump = t0 + 2 * PACE + 5.0
    assert t_jump > t
    assert g.FORWARD_SLACK_ROUNDS + int((t_jump - t0) // PACE) >= 3
    assert g.FORWARD_SLACK_ROUNDS + int((t_jump - t_revert) // PACE) < 3
    assert gate.observe(3, 5, t_jump).reason == "advance"


def test_catch_up_beyond_the_pace_is_held_then_taken_by_majority():
    gate = _gate()
    t = _fill(gate, (3, 2), 500.0)
    # from a full window of 3-2, the new value needs n reads with
    # n >= SWITCH_MIN_READS and n >= (WINDOW_READS - n) + SWITCH_MARGIN
    need = next(n for n in range(1, g.WINDOW_READS + 1)
                if n >= g.SWITCH_MIN_READS and n >= g.WINDOW_READS - n + g.SWITCH_MARGIN)
    v = gate.observe(3, 6, t)                     # 4 rounds in about 10 s
    assert (v.kind, v.reason) == (g.REJECT, "forward_jump")
    for _ in range(need - 2):
        t += POLL
        assert gate.observe(3, 6, t).kind == g.REJECT
    t += POLL
    v = gate.observe(3, 6, t)
    assert (v.kind, v.reason, v.stage, v.rnd) == (g.ACCEPT, "majority", 3, 6)


def test_catch_up_within_the_pace_is_taken_at_once():
    gate = _gate()
    gate.observe(3, 2, 500.0)
    t = 500.0 + PACE * 3                          # allows FORWARD_SLACK + 3 steps
    assert gate.observe(3, 6, t).reason == "advance"


def test_persistent_backward_reads_move_by_majority_not_as_a_new_game():
    gate = _gate()
    gate.observe(4, 2, 820.0)
    t = 821.5
    for _ in range(g.SWITCH_MIN_READS - 1):
        assert gate.observe(2, 1, t).kind == g.REJECT
        t += POLL
    v = gate.observe(2, 1, t)
    assert (v.kind, v.reason, v.stage, v.rnd) == (g.ACCEPT, "majority", 2, 1)


def test_unrated_queue_fast_path_is_the_slack_only():
    gate = _gate("hyper_roll")
    gate.observe(2, 6, 300.0)
    assert g.ordinal(3, 1) - g.ordinal(2, 6) == g.UNRATED_SLACK_ROUNDS
    assert gate.observe(3, 1, 301.5).reason == "advance"     # a stage ending at x-6
    gate2 = _gate("hyper_roll")
    gate2.observe(2, 1, 200.0)
    assert gate2.observe(2, 5, 230.0).reason == "forward_jump"
    # a forward read within the slack while the window is not clean waits
    gate3 = _gate("hyper_roll")
    t = _fill(gate3, (2, 1), 200.0)
    gate3.observe(1, 4, t)                        # one stray read
    gate3.observe(2, 2, t + POLL)                 # stray 2-2: fast path (one stray allowed)
    v = gate3.observe(2, 1, t + 2 * POLL)
    assert v.kind == g.REVERT
    v = gate3.observe(2, 2, t + 3 * POLL)         # 2-2 already came and went: not news
    assert (v.kind, v.reason) == (g.REJECT, "unconfirmed")


def _flicker(gate, t0, true_at, misread, misread_from, span):
    """Poll every POLL an OCR cache refreshed every OCR_PERIOD whose refreshes
    alternate between the true round and `misread` once `misread_from` s
    passed. Returns [(read, acted, truth)]."""
    out = []
    pt = t0 + POLL
    while pt < t0 + span:
        k = int((pt - t0) // OCR_PERIOD)
        true = true_at(pt - t0)
        cur = misread if (pt - t0 >= misread_from and k % 2 == 1) else true
        v = gate.observe(*cur, pt)
        out.append((cur, (v.stage, v.rnd), true))
        pt += POLL
    return out


def test_lock1_fifty_fifty_flicker_neither_holds_ahead_nor_flips():
    gate = _gate()
    _fill(gate, (3, 3), 590.0)
    out = _flicker(gate, 600.0, lambda dt: (3, 3), (3, 4), 0.0, 60.0)
    acted = [x[1] for x in out]
    assert acted.count((3, 4)) <= 1, acted
    assert sum(1 for a, b in zip(acted, acted[1:]) if a != b) <= 2, acted


def test_lock2_half_misread_stream_does_not_flip_and_recovers():
    """Verifier-1 reproducer LOCK2: every other OCR frame misread as 4-4
    while the true round moves 4-1 -> 4-2 -> 4-3. RECORDED LIMIT, not a
    pass: a stream that is wrong HALF the time has no majority, so neither
    this gate nor any filter can tell the misread from the truth; the gate
    holds the round it took (here the first 4-4, taken on a clean window,
    which a real round change looks identical to) instead of flipping with
    every frame as the pre-RM-615 code did - a flip re-armed a paid planning
    scan each time. An unrelated stray read cannot hand the round back to
    the stale reads in the window (test_glitches_spliced_... below needs
    exactly that). What is asserted: no flipping, and recovery as soon as
    the reads agree again."""
    def true_at(dt):
        return (4, 1) if dt < 45 else ((4, 2) if dt < 90 else (4, 3))
    gate = _gate()
    gate.observe(4, 1, 760.0)
    out = _flicker(gate, 760.0, true_at, (4, 4), 40.0, 130.0)
    acted = [x[1] for x in out]
    raw = [x[0] for x in out]
    assert sum(1 for a, b in zip(acted, acted[1:]) if a != b) <= 2, acted
    assert sum(1 for a, b in zip(raw, raw[1:]) if a != b) > 30     # the raw stream flips
    # and once the misreads stop, the true round is taken
    t = 760.0 + 130.0
    v = None
    for _ in range(g.WINDOW_READS):
        v = gate.observe(4, 3, t)
        t += POLL
    assert (v.stage, v.rnd) == (4, 3)


def _seq(gate, seq, t0, truth):
    wrong = flips = 0
    prev = None
    for i, sr in enumerate(seq):
        v = gate.observe(*sr, t0 + POLL * i)
        acted = (v.stage, v.rnd)
        wrong += acted != truth[i]
        flips += prev is not None and acted != prev
        prev = acted
    return wrong, flips


@pytest.mark.parametrize("queue", ["standard", "hyper_roll", None])
def test_verifier_reproducers_a1_to_c(queue):
    A, B = (3, 6), (3, 5)
    seq = [A] * 6 + [B] * 3 + [A, A, B] * 10                 # (a1) misread burst, truth 2/3
    assert _seq(_gate(queue), seq, 700.0, [A] * len(seq)) == (0, 0)
    seq = [(3, 2)] + [(3, 1), (3, 1), (3, 2)] * 10            # (a2) first read a misread
    wrong, flips = _seq(_gate(queue), seq, 455.0, [(3, 1)] * len(seq))
    assert wrong <= 5 and flips <= 1
    seq = [(3, 1)] * 8 + [(3, 2), (3, 1)] + [(3, 2), (3, 2), (3, 1)] * 10   # (a3)
    wrong, _ = _seq(_gate(queue), seq, 455.0, [(3, 1)] * 8 + [(3, 2)] * (len(seq) - 8))
    assert wrong <= 5                      # the first cut held the wrong round 31 polls
    R = (3, 3)                                                # (c) mixed flicker
    seq = [R] * 16 + [(3, 4), R, (3, 5), R] * 6
    wrong, flips = _seq(_gate(queue), seq, 552.0, [R] * len(seq))
    assert wrong <= 2 and flips <= 4


# -- the new-game bypass -----------------------------------------------------

def test_clock_reset_held_two_reads_is_a_new_game():
    gate = _gate()
    _fill(gate, (5, 3), 1300.0)
    v = gate.observe(1, 2, 40.0)
    assert (v.kind, v.reason, v.stage, v.rnd) == (g.REJECT, "clock_reset_pending", 5, 3)
    v = gate.observe(1, 2, 41.5)
    assert (v.kind, v.reason, v.stage, v.rnd) == (g.NEW_GAME, "clock_reset", 1, 2)
    assert g.CLOCK_RESET_READS == 2


def test_clock_reset_new_game_even_from_an_early_stage():
    """The pre-RM-615 detector needed the old stage > 2, so a game left at
    stage 2 leaked its augments into the next one. The clock does not care."""
    gate = _gate()
    _fill(gate, (2, 3), 400.0)
    gate.observe(1, 1, 5.0)
    v = gate.observe(1, 1, 6.5)
    assert v.kind == g.NEW_GAME and gate.accepted == (1, 1)


def test_clock_reset_with_a_stale_read_resets_and_holds_the_read():
    gate = _gate()
    _fill(gate, (6, 2), 1700.0)
    gate.observe(6, 2, 2.0)
    v = gate.observe(6, 2, 3.5)                # stale OCR value, fresh clock
    assert v.kind == g.NEW_GAME and v.stage is None and gate.accepted is None
    v = gate.observe(1, 1, 5.0)
    assert (v.kind, v.reason, v.stage, v.rnd) == (g.ACCEPT, "first", 1, 1)


@pytest.mark.parametrize("glitch", [0.5, 1e300, 10 ** 400, g.MAX_GAME_S + 1,
                                    1020.0, 3000.0, 7000.0])   # behind, absurd, AHEAD
def test_one_glitched_clock_value_mid_game_is_not_a_new_game(glitch):
    """Verifier-3 reproducer: one clock value 11-6000 s AHEAD raised the
    high-water mark, so the real clock then looked like a restart and the
    augments were cleared two polls later. A read's clock now counts only
    once the next read does not fall below it."""
    gate = _gate()
    t = _fill(gate, (4, 2), 1000.0)
    kinds = [gate.observe(4, 2, glitch).kind]
    kinds += [gate.observe(4, 2, t + POLL * i).kind for i in range(3)]
    assert g.NEW_GAME not in kinds and gate.accepted == (4, 2)


@pytest.mark.parametrize("queue", ["standard", "hyper_roll", None])
def test_stale_round_after_a_restart_is_ignored(queue):
    """Verifier-3 reproducer: with no rate (Hyper Roll, unknown) the
    previous game's round, still in the reader's OCR cache, was taken as
    the new game's first read and held about 10 polls. The round held before
    a clock restart is not news after it."""
    gate = _gate(queue)
    _fill(gate, (4, 2), 1000.0)
    assert gate.observe(4, 2, 2.0).reason == "clock_reset_pending"
    v = gate.observe(4, 2, 3.5)
    assert (v.kind, v.stage) == (g.NEW_GAME, None)
    for i in range(g.WINDOW_READS):
        assert gate.observe(4, 2, 5.0 + i * POLL).reason == "stale_after_reset"
    v = gate.observe(1, 1, 20.0)
    assert (v.kind, v.reason, v.stage, v.rnd) == (g.ACCEPT, "first", 1, 1)


@pytest.mark.parametrize("queue", ["hyper_roll", None, "standard"])
def test_stale_last_raw_read_after_a_restart_is_ignored(queue):
    """Verifier-4 reproducer: the guard remembered only the round the gate
    had accepted, so a last RAW read the gate was holding back (4-3 here)
    slipped through after the restart and was held 9 polls on unrated
    queues. The last read before the restart is stale too."""
    gate = _gate(queue)
    t = _fill(gate, (4, 2), 1000.0, 8)
    for sr in ((4, 1), (4, 1), (4, 3)):
        gate.observe(*sr, t)
        t += POLL
    assert gate.accepted == (4, 2)
    acted = []
    for i in range(6):
        v = gate.observe(4, 3, 2.0 + i * POLL)
        acted.append(v.stage_round)
    assert "4-3" not in acted, acted
    v = gate.observe(1, 1, 12.0)
    assert (v.stage, v.rnd) == (1, 1)


def test_stale_guard_spares_a_stage_1_round():
    """A game always starts in stage 1, so a stage-1 round held before the
    restart may be the new game's own: it is not ignored."""
    gate = _gate()
    _fill(gate, (1, 2), 40.0)
    gate.observe(1, 2, 2.0)
    v = gate.observe(1, 2, 3.5)
    assert (v.kind, v.stage, v.rnd) == (g.NEW_GAME, 1, 2)


def test_pathological_pace_gives_no_rate():
    """Verifier-3 reproducer: rows 1e-310 s apart overflowed the allowance
    arithmetic. A floor under MIN_PACE_S is no rate."""
    assert g.pace_floor_from_table([(0.0, 1, 1), (1e-310, 1, 2)]) is None
    assert g.pace_floor_from_table([(0, 1, 1), (10 ** 400, 1, 2)]) is None   # no OverflowError
    assert g.StageGate("standard", min_round_s=g.MIN_PACE_S / 2).rate is None
    gate = g.StageGate("standard", min_round_s=1e-310)
    gate.observe(3, 2, 500.0)
    assert gate.observe(3, 3, 502.0).kind == g.ACCEPT


def test_two_of_three_lag_after_a_flicker_is_bounded_recorded_trade_off():
    """Verifier-3 reproducer, kept as a RECORDED TRADE-OFF (module docstring):
    a real change to 3-4 read on a 2-of-3 majority, with the window still
    holding 3-3 after an earlier one-poll flicker, lags 7 polls. A 5-read
    window cuts it to 5 and still holds test_verifier_reproducers_a1_to_c's
    (a1) burst (verifier 4 measured it), but acts on the wrong round more
    often for +1 misreads on the seeded model, so 7 was kept. Pinned so the
    lag cannot silently grow."""
    A, B = (3, 3), (3, 4)
    seq = [A] * 7 + [B, A, A] + [A, B, B, A, B, B, A] + [B, B, A] * 5
    truth = [A] * 10 + [B] * (len(seq) - 10)
    gate = _gate()
    acted = []
    for i, sr in enumerate(seq):
        v = gate.observe(*sr, 600.0 + POLL * i)
        acted.append((v.stage, v.rnd))
    lag = 0
    for i in range(10, len(seq)):
        if acted[i] == truth[i]:
            break
        lag += 1
    assert lag <= 7, acted
    assert acted[-1] == B
    assert all(a == truth[i] for i, a in enumerate(acted) if i >= 10 + lag)


def test_small_clock_wobble_is_not_a_new_game():
    gate = _gate()
    t = _fill(gate, (3, 2), 500.0)
    for _ in range(3):
        v = gate.observe(2, 1, t - g.CLOCK_RESET_SLACK_S + 0.5)
        assert v.kind == g.REJECT


def test_no_clock_falls_back_to_the_legacy_stage_reset_rule():
    gate = _gate()
    gate.observe(4, 2, None)
    v = gate.observe(2, 1, None)
    assert (v.kind, v.reason) == (g.NEW_GAME, "stage_reset_no_clock")
    assert gate.accepted == (2, 1)
    gate2 = _gate()
    gate2.observe(2, 3, None)
    assert gate2.observe(1, 4, None).kind == g.REJECT       # stage 2 -> 1: not the legacy shape


@pytest.mark.parametrize("bad_clock", [0, 0.0, -3.0, float("nan"), float("inf"), "12", True])
def test_missing_or_bogus_clock_is_treated_as_no_clock(bad_clock):
    """The reader defaults gameTime to 0 (tft/tft_state_reader.py:145), so a
    zero clock means "no clock", never "the game restarted"."""
    gate = _gate()
    gate.observe(4, 2, 820.0)
    assert gate.observe(4, 3, bad_clock).reason == "advance"
    v = gate.observe(2, 1, bad_clock)
    assert (v.kind, v.reason) == (g.NEW_GAME, "stage_reset_no_clock")


def test_reset_forgets_the_anchor_the_window_and_the_clock():
    gate = _gate()
    _fill(gate, (4, 2), 820.0)
    gate.reset()
    assert gate.accepted is None
    assert gate.observe(1, 2, 30.0).reason == "first"


def test_set_queue_switches_the_rate():
    gate = g.StageGate(None, min_round_s=PACE)
    assert gate.timing is g.UNMEASURED and gate.rate is None
    gate.set_queue("standard")
    assert gate.timing is g.QUEUE_TIMINGS["standard"] and gate.rate == PACE
    gate.set_queue(1130)
    assert gate.timing is g.QUEUE_TIMINGS["hyper_roll"] and gate.rate is None
    gate.set_queue("standard")
    gate.set_pace(None)
    assert gate.rate is None


# -- measured-data replay ----------------------------------------------------

@pytest.mark.parametrize("queue", ["standard", "double_up", "hyper_roll", None])
def test_reader_time_table_stream_is_taken_on_the_same_poll(queue):
    """Polling the reader's own round table at the worker cadence - the
    stream production publishes whenever OCR is off - never trips the gate,
    with the pace computed from that same table, on any queue: every round
    change is acted on the poll it appears."""
    gate = g.StageGate(queue, min_round_s=g.pace_floor_from_table(reader._TIME_TO_ROUND))
    t = 0.7
    while t <= 1900.0:
        s, r = reader._estimate_round(t)
        v = gate.observe(s, r, t)
        assert v.kind in (g.ACCEPT, g.SAME), (queue, t, s, r, v)
        assert (v.stage, v.rnd) == (s, r)
        t += POLL


def test_glitches_spliced_into_the_measured_stream_are_held():
    gate = g.StageGate("standard", min_round_s=g.pace_floor_from_table(reader._TIME_TO_ROUND))
    glitches = {300.7: (1, 2), 600.7: (6, 1), 900.7: (2, 2), 1200.7: (9, 9), 1500.7: (4, 1)}
    held = 0
    t = 0.7
    while t <= 1900.0:
        key = round(t, 1)
        if key in glitches:
            v = gate.observe(*glitches[key], t)
            assert v.kind == g.REJECT, (t, glitches[key], v)
            held += 1
        else:
            s, r = reader._estimate_round(t)
            v = gate.observe(s, r, t)
            assert (v.stage, v.rnd) == (s, r), (t, s, r, v)
        t += POLL
    assert held == len(glitches)


def _misread_game(seed, p, offsets):
    """One seeded game on the reader's table: OCR frames every OCR_PERIOD,
    each misread with probability p by one of `offsets` rounds; polled every
    POLL. Returns (gate verdicts, raw reads, truths)."""
    rng = random.Random(seed)
    last = g.ordinal(*reader._TIME_TO_ROUND[-1][1:])
    gate = g.StageGate("standard", min_round_s=g.pace_floor_from_table(reader._TIME_TO_ROUND))
    frames = {}
    out = []
    t = 0.7
    while t <= 1880.0:
        fi = int(t // OCR_PERIOD)
        truth = reader._estimate_round(t)
        if fi not in frames:
            k = rng.choice(offsets) if rng.random() < p else 0
            frames[fi] = g.stage_round_of(min(last, max(1, g.ordinal(*reader._estimate_round(fi * OCR_PERIOD)) + k)))
        raw = frames[fi]
        out.append((gate.observe(*raw, t), raw, truth))
        t += POLL
    return out


@pytest.mark.parametrize("offsets", [[-1], [-1, 1], [-2, -1, 1, 2]])
def test_seeded_misreads_never_make_a_new_game_and_beat_the_raw_stream(offsets):
    """Under seeded misreads (5 percent of OCR frames) the gate reports no
    new game, and over the seeds acts on the wrong round less often than the
    raw stream the pre-RM-615 code acted on. (+1-only misreads are the one
    model where it does not: a misread of round N is round N+1, so the
    filter's latency at real round changes costs more than it saves; the
    module docstring records the measurement.)"""
    gated_wrong = raw_wrong = 0
    for seed in range(8):
        out = _misread_game(seed, 0.05, offsets)
        assert not [v for v, _, _ in out if v.kind == g.NEW_GAME], seed
        gated_wrong += sum((v.stage, v.rnd) != tr for v, _, tr in out)
        raw_wrong += sum(raw != tr for _, raw, tr in out)
    assert gated_wrong < raw_wrong, (gated_wrong, raw_wrong)


def test_odd_values_never_raise():
    gate = _gate()
    gate.observe(3, 2, 500.0)
    assert gate.observe(3, 2, 10 ** 400).kind == g.SAME
    for s, r in ((chr(0xB2), 1), (3, chr(0xB2)), (10 ** 400, 2), ("9" * 5000, 2), ([], {}), (None, None)):
        assert gate.observe(s, r, 501.0).kind == g.REJECT
    assert gate.accepted == (3, 2)


# -- purity ------------------------------------------------------------------

def test_module_is_pure():
    """No I/O, no clock of its own and no RC imports (the measured pace is
    passed in, never read here): deterministic under test and in replay."""
    tree = ast.parse((REPO / "core" / "tft_stage_gate.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert imported <= {"__future__", "collections", "math", "typing"}, imported
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert not names & {"open", "print", "time"}
