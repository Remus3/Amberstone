"""s144 true-audit of core/tft_stage_gate.py (S144-T-734).

Three contract defects, each pinned here:

1. pace_floor_from_table took ANY finite clock column. A table whose clock is
   negative or past MAX_GAME_S is not a TFT round table, yet it yielded a
   "measured" pace (25.0 from a negative column, 5e8 from a 1e9 s step) and a
   step spanning the float range yielded inf - the docstring promises None
   ("never a guessed one"). The live caller logs "no measured pace" only on
   None, so a huge or inf result also skipped that line while set_pace
   silently dropped it.
2. stage_round_of fabricated a round for an ordinal outside the structure:
   0 -> (1, 0), -3 -> (1, -3), True -> (1, True), 4.5 -> (1.0, 7.5), 999 ->
   (143, ...). It now raises ValueError for anything ordinal() cannot return.
3. QUEUE_TIMINGS / QUEUE_VARIANT were plain module dicts, so any importer
   could rebind Hyper Roll to a rated timing process-wide (the RM-855
   doctrine: an unmeasured queue never borrows a rate). They are read-only
   mappings now; lookups and equality are unchanged.
"""
from __future__ import annotations

import math

import pytest

from core import tft_stage_gate as g

MAX_ORDINAL = g.STAGE1_ROUNDS + (g.STAGE_MAX - 1) * g.STAGE_ROUNDS


# -- 1. pace_floor_from_table: clock column must be a TFT game clock ----------
@pytest.mark.parametrize(
    "table",
    [
        [(-100, 1, 1), (-50, 1, 2)],                 # negative clock column
        [(-10, 1, 1), (40, 1, 2)],                   # one negative row
        [(0, 1, 1), (1e9, 1, 2)],                    # past MAX_GAME_S
        [(0, 1, 1), (g.MAX_GAME_S + 1, 1, 2)],        # just past MAX_GAME_S
        [(-1.7e308, 1, 1), (1.7e308, 1, 2)],         # step overflows to inf
    ],
)
def test_pace_floor_refuses_a_clock_column_outside_a_game(table):
    assert g.pace_floor_from_table(table) is None


def test_pace_floor_keeps_a_table_on_the_clock_bounds():
    # 0 and MAX_GAME_S are both legal clock values: the bound is inclusive
    floor = g.pace_floor_from_table([(0, 1, 1), (g.MAX_GAME_S, 1, 2)])
    assert floor == pytest.approx(g.PACE_SAFETY * g.MAX_GAME_S)


def test_pace_floor_result_is_always_a_pace_set_pace_keeps():
    # whatever the table function returns, StageGate must keep it as the rate
    for table in ([(0, 1, 1), (63, 1, 2)], [(0, 1, 1), (g.MAX_GAME_S, 1, 2)]):
        floor = g.pace_floor_from_table(table)
        assert floor is not None and math.isfinite(floor)
        assert g.StageGate("standard", min_round_s=floor).rate == floor


def test_pace_floor_real_reader_tables_unchanged():
    from tft import tft_state_reader as reader
    for name in ("_TIME_TO_ROUND", "_TIME_TO_ROUND_SET18"):
        table = getattr(reader, name)
        floor = g.pace_floor_from_table(table)
        assert floor is not None
        steps = [(b[0] - a[0]) / (g.ordinal(b[1], b[2]) - g.ordinal(a[1], a[2]))
                 for a, b in zip(table, table[1:])]
        assert floor == pytest.approx(g.PACE_SAFETY * min(steps))


# -- 2. stage_round_of refuses an ordinal outside the structure ---------------
@pytest.mark.parametrize("bad", [0, -3, MAX_ORDINAL + 1, 999, True, False, 4.5, 5.0, "5", None])
def test_stage_round_of_refuses_an_illegal_ordinal(bad):
    with pytest.raises(ValueError):
        g.stage_round_of(bad)


def test_stage_round_of_round_trips_every_legal_ordinal():
    seen = set()
    for o in range(1, MAX_ORDINAL + 1):
        s, r = g.stage_round_of(o)
        assert type(s) is int and type(r) is int
        assert g.ordinal(s, r) == o
        seen.add((s, r))
    assert len(seen) == MAX_ORDINAL
    assert g.stage_round_of(MAX_ORDINAL) == (g.STAGE_MAX, g.STAGE_ROUNDS)


# -- 3. queue tables are read-only --------------------------------------------
def test_queue_timings_cannot_be_rebound():
    with pytest.raises(TypeError):
        g.QUEUE_TIMINGS["hyper_roll"] = g.QUEUE_TIMINGS["standard"]
    with pytest.raises(TypeError):
        g.QUEUE_TIMINGS["new"] = g.UNMEASURED
    assert g.timing_for("hyper_roll").rated is False


def test_queue_variant_cannot_be_rebound():
    with pytest.raises(TypeError):
        g.QUEUE_VARIANT[1130] = "standard"
    with pytest.raises(TypeError):
        g.QUEUE_VARIANT[9999] = "standard"
    assert g.timing_for(1130).rated is False


def test_queue_tables_still_read_like_dicts():
    assert g.QUEUE_VARIANT == {1090: "standard", 1100: "standard",
                               1130: "hyper_roll", 1160: "double_up"}
    assert set(g.QUEUE_TIMINGS) == {"standard", "double_up", "hyper_roll"}
    assert g.QUEUE_TIMINGS.get("nope") is None
