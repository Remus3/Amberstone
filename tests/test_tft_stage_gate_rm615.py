"""RM-615 (X-15): the pure monotonic stage-round plausibility gate.

`core/tft_stage_gate.py` judges one TFT stage read at a time against the
last accepted read and the game clock:

  * a read outside the round structure is rejected (and never confirmed);
  * a read BEHIND the accepted round, with the game clock still running
    forward, is an OCR glitch and is held;
  * a read too far AHEAD for the game time elapsed is held, using the
    queue's own measured round pace;
  * a genuine new game BYPASSES the gate: the game clock restarting (or,
    with no clock, the legacy "stage > 2 -> stage <= 2" rule) resets it.

FIXTURE PROVENANCE. No live stage sample exists this session (the s134
recorder saw no TFT state: TFT ran as a standalone client and nothing was
served on :2999), so the measured data is the tree's own: the four
confirmed live points recorded at tft/tft_state_reader.py:22-24
(t=32 s -> 1-2, t=348 s -> 2-5, t~1002 s -> 4-6, t=1879 s -> 7-4) and the
reader's calibrated round table `_TIME_TO_ROUND` (tft/tft_state_reader.py:21)
read through `_estimate_round` (:33), which is the stage stream production
publishes whenever OCR is unavailable.

Names used, cited at the fix tree:
  core/tft_stage_gate.py  STAGE_MAX, STAGE1_ROUNDS, STAGE_ROUNDS,
      ACCEPT / SAME / NEW_GAME / REJECT, FORWARD_SLACK_ROUNDS,
      UNRATED_SLACK_ROUNDS, CONFIRM_READS, CLOCK_RESET_SLACK_S,
      QueueTiming, QUEUE_TIMINGS, QUEUE_VARIANT,
      UNMEASURED, MEASURED_POINTS, timing_for, ordinal, parse_stage_round,
      Verdict, StageGate (observe / reset / set_queue / accepted / timing).
  lcu/snapshot_shape.py:74-78  the TFT queue names (1090 Normal, 1100
      Ranked, 1130 Hyper Roll, 1160 Double Up).
  tft/tft_state_reader.py:165 / :221  the state's "variant" key, set by
      `detect_variant` (:127): "standard" / "hyper_roll" / "double_up".
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from core import tft_stage_gate as g
from tft import tft_state_reader as reader

REPO = Path(__file__).resolve().parent.parent

# The four confirmed live points, verbatim from tft/tft_state_reader.py:23.
CONFIRMED = [(32.0, 1, 2), (348.0, 2, 5), (1002.0, 4, 6), (1879.0, 7, 4)]


def _gate(queue="standard"):
    return g.StageGate(queue)


# -- structure ---------------------------------------------------------------

def test_ordinal_follows_the_round_structure():
    assert g.ordinal(1, 1) == 1
    assert g.ordinal(1, 4) == 4
    assert g.ordinal(2, 1) == 5          # 2-1 follows 1-4 directly
    assert g.ordinal(2, 7) == 11
    assert g.ordinal(3, 1) == 12
    assert g.ordinal(7, 4) == 4 + 5 * 7 + 4
    # strictly increasing across the whole legal range
    seq = [g.ordinal(s, r) for s in range(1, g.STAGE_MAX + 1)
           for r in range(1, (g.STAGE1_ROUNDS if s == 1 else g.STAGE_ROUNDS) + 1)]
    assert seq == sorted(seq) and len(set(seq)) == len(seq)


@pytest.mark.parametrize("stage,rnd", [
    (0, 1), (g.STAGE_MAX + 1, 1), (1, 0), (1, g.STAGE1_ROUNDS + 1),
    (2, g.STAGE_ROUNDS + 1), (None, 1), (3, None), (True, 1), ("x", 2), (2.5, 1),
])
def test_ordinal_rejects_reads_outside_the_structure(stage, rnd):
    assert g.ordinal(stage, rnd) is None


def test_parse_stage_round_labels():
    assert g.parse_stage_round("3-2") == (3, 2)
    assert g.parse_stage_round(" 4 - 6 ") == (4, 6)
    for bad in ("", "3", "3-", "9-1", "1-5", "a-b", None, 32, "3-2-1"):
        assert g.parse_stage_round(bad) is None, bad


def test_structure_bounds_match_the_reader_ocr_bounds():
    """The gate's legal range is the reader's OCR sanity range
    (tft/tft_state_reader.py:172-174: stage 1-7, round <= 4 in stage 1,
    <= 7 after), so a read the reader accepts is never out of range here."""
    src = (REPO / "tft" / "tft_state_reader.py").read_text(encoding="utf-8")
    assert "max_rnd = 4 if os == 1 else 7" in src
    assert "1 <= os <= 7" in src
    assert (g.STAGE_MAX, g.STAGE1_ROUNDS, g.STAGE_ROUNDS) == (7, 4, 7)


# -- per-queue constants -----------------------------------------------------

def test_queue_ids_map_to_reader_variants():
    # lcu/snapshot_shape.py:74-78 names these four TFT queues.
    assert g.QUEUE_VARIANT == {1090: "standard", 1100: "standard",
                               1130: "hyper_roll", 1160: "double_up"}
    for qid, variant in g.QUEUE_VARIANT.items():
        assert g.timing_for(qid) is g.QUEUE_TIMINGS[variant]
        assert g.timing_for(variant) is g.QUEUE_TIMINGS[variant]
    # every variant detect_variant can return has an entry
    src = (REPO / "tft" / "tft_state_reader.py").read_text(encoding="utf-8")
    for variant in ("standard", "hyper_roll", "double_up"):
        assert f'"{variant}"' in src
        assert variant in g.QUEUE_TIMINGS


@pytest.mark.parametrize("queue", [None, "", "arena", 1110, 0, True, 3.5, object()])
def test_unknown_queue_is_unmeasured_never_borrowed(queue):
    assert g.timing_for(queue) is g.UNMEASURED
    assert g.UNMEASURED.min_round_s is None


def test_hyper_roll_is_unmeasured_not_borrowed():
    """Hyper Roll's round pace has never been measured here, so it carries
    no rate of its own and never borrows the standard one (RM-855 doctrine:
    another schedule's timings are never borrowed)."""
    assert g.QUEUE_TIMINGS["hyper_roll"].min_round_s is None
    assert "unmeasured" in g.QUEUE_TIMINGS["hyper_roll"].source


def test_measured_rate_is_derived_from_the_confirmed_points():
    """The measured queues' floor sits at or below HALF the fastest pace
    between consecutive confirmed points, and the module carries those
    points verbatim (so the derivation can be re-run, not just believed)."""
    assert list(g.MEASURED_POINTS) == CONFIRMED
    src = (REPO / "tft" / "tft_state_reader.py").read_text(encoding="utf-8")
    assert "t=32s->1-2, t=348s->2-5, t~1002s->4-6, t=1879s->7-4" in src
    paces = []
    for (t0, s0, r0), (t1, s1, r1) in zip(CONFIRMED, CONFIRMED[1:]):
        paces.append((t1 - t0) / (g.ordinal(s1, r1) - g.ordinal(s0, r0)))
    fastest = min(paces)
    assert 40.0 < fastest < 47.0, paces
    for variant in ("standard", "double_up"):
        t = g.QUEUE_TIMINGS[variant]
        assert t.min_round_s is not None and 0 < t.min_round_s <= fastest / 2
        assert "measured" in t.source


# -- acceptance and the monotonic hold ----------------------------------------

def test_first_read_and_one_step_advances_are_accepted():
    gate = _gate()
    v = gate.observe(3, 2, 600.0)
    assert (v.kind, v.stage, v.rnd) == (g.ACCEPT, 3, 2)
    assert gate.observe(3, 2, 610.0).kind == g.SAME
    v = gate.observe(3, 3, 640.0)
    assert (v.kind, v.stage, v.rnd) == (g.ACCEPT, 3, 3)
    assert gate.accepted == (3, 3)
    assert v.stage_round == "3-3"


def test_backward_read_with_a_running_clock_is_held():
    gate = _gate()
    gate.observe(4, 2, 820.0)
    for t, (s, r) in ((822.0, (2, 1)), (823.5, (1, 2)), (825.0, (4, 1))):
        v = gate.observe(s, r, t)
        assert v.kind == g.REJECT and v.reason == "backward", (s, r, v)
        assert (v.stage, v.rnd) == (4, 2)          # the anchor holds
        assert v.stage_round == "4-2"
    assert gate.accepted == (4, 2)


def test_out_of_range_read_is_held_and_never_confirmed():
    gate = _gate()
    gate.observe(3, 1, 450.0)
    for i in range(g.CONFIRM_READS + 3):
        v = gate.observe(9, 9, 451.0 + i)
        assert v.kind == g.REJECT and v.reason == "out_of_range"
    assert gate.accepted == (3, 1)


def test_read_unreachable_at_the_game_clock_is_held_and_never_confirmed():
    gate = _gate()
    gate.observe(3, 2, 500.0)
    v = gate.observe(6, 1, 502.0)          # stage 6 at minute 8
    assert v.kind == g.REJECT and v.reason == "implausible_at_clock"
    assert gate.accepted == (3, 2)
    # a stale or misread value repeated is still impossible at that game time
    for i in range(g.CONFIRM_READS + 2):
        assert gate.observe(6, 1, 503.0 + i * 1.5).kind == g.REJECT
    assert gate.accepted == (3, 2)


def test_forward_jump_too_fast_for_the_anchor_is_held_then_confirmable():
    gate = _gate()
    gate.observe(3, 2, 500.0)
    v = gate.observe(3, 6, 502.0)          # reachable by minute 8, not in 2 s
    assert v.kind == g.REJECT and v.reason == "forward_jump"
    assert gate.accepted == (3, 2)
    t = 503.5
    for _ in range(g.CONFIRM_READS - 2):
        assert gate.observe(3, 6, t).kind == g.REJECT
        t += 1.5
    v = gate.observe(3, 6, t)
    assert (v.kind, v.reason, v.stage, v.rnd) == (g.ACCEPT, "confirmed_forward_jump", 3, 6)


def test_a_wrong_low_anchor_does_not_lock_the_gate():
    """A deterministic OCR misread (4 read as 1) confirmed onto the anchor is
    overturned by the true reads once they repeat: no lock-in."""
    gate = _gate()
    gate.observe(4, 1, 760.0)
    t = 761.5
    for _ in range(g.CONFIRM_READS):
        v = gate.observe(1, 1, t)
        t += 1.5
    assert v.kind == g.ACCEPT and gate.accepted == (1, 1)
    for _ in range(g.CONFIRM_READS):
        v = gate.observe(4, 2, t)
        t += 1.5
    assert (v.kind, v.stage, v.rnd) == (g.ACCEPT, 4, 2)


def test_multi_round_catch_up_is_accepted_once_the_clock_allows_it():
    gate = _gate()
    t0 = 500.0
    gate.observe(3, 2, t0)
    rate = g.QUEUE_TIMINGS["standard"].min_round_s
    steps = 4                               # 3-2 -> 3-6
    t_ok = t0 + rate * (steps - g.FORWARD_SLACK_ROUNDS)
    assert gate.observe(3, 6, t_ok - 1.0).kind == g.REJECT
    v = gate.observe(3, 6, t_ok)
    assert (v.kind, v.stage, v.rnd) == (g.ACCEPT, 3, 6)


def test_implausible_first_read_is_held():
    """A stale previous-game value at a fresh game clock (the reader's OCR
    cache outlives the game, tft/tft_state_reader.py:56 / :81) is held."""
    gate = _gate()
    v = gate.observe(5, 3, 3.0)
    assert v.kind == g.REJECT and v.reason == "implausible_at_clock"
    for i in range(g.CONFIRM_READS + 1):     # never confirmed
        assert gate.observe(5, 3, 4.5 + i * 1.5).kind == g.REJECT
    assert gate.accepted is None and v.stage is None and v.stage_round == ""
    # a joined-late read at a matching clock is fine
    assert gate.observe(5, 3, 1300.0).kind == g.ACCEPT


# -- confirmation (no lock-in on a wrong anchor) -----------------------------

def test_repeated_backward_read_re_anchors_after_confirm_reads():
    """An anchor accepted one round early (a misread inside the forward
    slack) cannot lock the gate: CONFIRM_READS consecutive identical
    backward reads re-anchor it, and the re-anchor is NOT a new game."""
    gate = _gate()
    gate.observe(3, 2, 500.0)
    gate.observe(3, 3, 501.5)               # early misread, within the slack
    t = 503.0
    for _ in range(g.CONFIRM_READS - 1):
        assert gate.observe(3, 2, t).kind == g.REJECT
        t += 1.5
    v = gate.observe(3, 2, t)
    assert (v.kind, v.reason, v.stage, v.rnd) == (g.ACCEPT, "confirmed_backward", 3, 2)


def test_confirmation_needs_consecutive_identical_reads():
    gate = _gate()
    gate.observe(4, 2, 820.0)
    t = 821.0
    for _ in range(g.CONFIRM_READS - 1):
        gate.observe(2, 1, t)
        t += 1.5
    assert gate.observe(4, 2, t).kind == g.SAME      # breaks the run
    t += 1.5
    for _ in range(g.CONFIRM_READS - 1):
        assert gate.observe(2, 1, t).kind == g.REJECT
        t += 1.5
    assert gate.accepted == (4, 2)


def test_unrated_forward_jump_needs_confirmation():
    """With no measured rate (Hyper Roll) only an UNRATED_SLACK_ROUNDS step
    is taken at once; a bigger jump is taken after CONFIRM_READS identical
    reads."""
    gate = _gate("hyper_roll")
    gate.observe(2, 1, 200.0)
    assert gate.observe(2, 2, 201.0).kind == g.ACCEPT
    # a stage that ends a round early (2-6 -> 3-1 skips the 2-7 slot of the
    # structure bound) is still one step at once
    gate2 = _gate("hyper_roll")
    gate2.observe(2, 6, 300.0)
    assert g.ordinal(3, 1) - g.ordinal(2, 6) == g.UNRATED_SLACK_ROUNDS
    assert gate2.observe(3, 1, 301.0).kind == g.ACCEPT
    for i in range(g.CONFIRM_READS - 1):
        v = gate.observe(4, 1, 202.0 + i)
        assert v.kind == g.REJECT and v.reason == "forward_unrated"
    v = gate.observe(4, 1, 210.0)
    assert (v.kind, v.stage, v.rnd) == (g.ACCEPT, 4, 1)


# -- the new-game bypass -----------------------------------------------------

def test_clock_reset_is_a_new_game_and_bypasses_the_hold():
    gate = _gate()
    gate.observe(5, 3, 1300.0)
    v = gate.observe(1, 2, 40.0)
    assert (v.kind, v.reason, v.stage, v.rnd) == (g.NEW_GAME, "clock_reset", 1, 2)
    assert gate.accepted == (1, 2)


def test_clock_reset_new_game_even_from_an_early_stage():
    """The pre-RM-615 detector needed the old stage > 2, so a game left at
    stage 2 leaked its augments into the next one. The clock does not care."""
    gate = _gate()
    gate.observe(2, 3, 400.0)
    v = gate.observe(1, 1, 5.0)
    assert v.kind == g.NEW_GAME and gate.accepted == (1, 1)


def test_clock_reset_with_a_stale_read_resets_and_holds_the_read():
    gate = _gate()
    gate.observe(6, 2, 1700.0)
    v = gate.observe(6, 2, 2.0)             # stale OCR value, fresh clock
    assert v.kind == g.NEW_GAME and v.stage is None
    assert gate.accepted is None
    v = gate.observe(1, 1, 3.5)
    assert (v.kind, v.stage, v.rnd) == (g.ACCEPT, 1, 1)


def test_small_clock_wobble_is_not_a_new_game():
    gate = _gate()
    gate.observe(3, 2, 500.0)
    v = gate.observe(2, 1, 500.0 - g.CLOCK_RESET_SLACK_S + 0.5)
    assert v.kind == g.REJECT


def test_no_clock_falls_back_to_the_legacy_stage_reset_rule():
    gate = _gate()
    gate.observe(4, 2, None)
    v = gate.observe(2, 1, None)
    assert (v.kind, v.reason) == (g.NEW_GAME, "stage_reset_no_clock")
    assert gate.accepted == (2, 1)
    # stage 2 -> stage 1 without a clock is not the legacy shape: held
    gate2 = _gate()
    gate2.observe(2, 3, None)
    assert gate2.observe(1, 4, None).kind == g.REJECT


@pytest.mark.parametrize("bad_clock", [0, 0.0, -3.0, float("nan"), float("inf"), "12", True])
def test_missing_or_bogus_clock_is_treated_as_no_clock(bad_clock):
    """The reader defaults gameTime to 0 (tft/tft_state_reader.py:145), so a
    zero clock means "no clock", never "the game restarted"."""
    gate = _gate()
    gate.observe(4, 2, 820.0)
    v = gate.observe(4, 3, bad_clock)
    assert v.kind == g.ACCEPT
    v = gate.observe(2, 1, bad_clock)       # legacy rule applies, no reset
    assert (v.kind, v.reason) == (g.NEW_GAME, "stage_reset_no_clock")


def test_reset_forgets_the_anchor_and_the_clock():
    gate = _gate()
    gate.observe(4, 2, 820.0)
    gate.reset()
    assert gate.accepted is None
    assert gate.observe(1, 2, 30.0).kind == g.ACCEPT


def test_set_queue_switches_the_rate():
    gate = _gate(None)
    assert gate.timing is g.UNMEASURED
    gate.set_queue("standard")
    assert gate.timing is g.QUEUE_TIMINGS["standard"]
    gate.set_queue(1130)
    assert gate.timing is g.QUEUE_TIMINGS["hyper_roll"]


# -- measured-data replay ----------------------------------------------------

def test_confirmed_live_points_replay_with_no_reject():
    """The four confirmed points, read sparsely (gaps of 300-900 s, the
    shape of a reader that missed most rounds), are all accepted."""
    for variant in ("standard", "double_up"):
        gate = _gate(variant)
        for t, s, r in CONFIRMED:
            v = gate.observe(s, r, t)
            assert v.kind == g.ACCEPT, (variant, t, s, r, v)


def test_reader_time_table_stream_replays_with_no_reject():
    """Polling the reader's own round table at the worker cadence (1.5 s,
    core/tft_worker.py:44) - the stream production publishes whenever OCR is
    off - never trips the gate, on any queue."""
    for variant in ("standard", "double_up", "hyper_roll", None):
        gate = _gate(variant)
        t = 1.5
        while t <= 1900.0:
            s, r = reader._estimate_round(t)
            v = gate.observe(s, r, t)
            assert v.kind in (g.ACCEPT, g.SAME), (variant, t, s, r, v)
            t += 1.5


def test_glitches_injected_into_the_measured_stream_are_held():
    """The same stream with OCR-shaped glitches spliced in: every glitch is
    held, the anchor never moves backward, and the stream resumes."""
    gate = _gate("standard")
    glitches = {300.0: (1, 2), 600.0: (6, 1), 900.0: (2, 2), 1200.0: (9, 9),
                1500.0: (4, 1)}
    held = 0
    best = 0
    t = 1.5
    while t <= 1900.0:
        if t in glitches:
            v = gate.observe(*glitches[t], t)
            assert v.kind == g.REJECT, (t, glitches[t], v)
            held += 1
        else:
            s, r = reader._estimate_round(t)
            v = gate.observe(s, r, t)
            assert v.kind in (g.ACCEPT, g.SAME), (t, s, r, v)
        o = g.ordinal(*gate.accepted)
        assert o >= best
        best = o
        t += 1.5
    assert held == len(glitches)


# -- purity ------------------------------------------------------------------

def test_module_is_pure():
    """No I/O, no clock of its own and no RC imports: the caller passes the
    game clock, so the gate is deterministic under test and in replay."""
    tree = ast.parse((REPO / "core" / "tft_stage_gate.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert imported <= {"__future__", "math", "typing"}, imported
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert not names & {"open", "print", "time"}
