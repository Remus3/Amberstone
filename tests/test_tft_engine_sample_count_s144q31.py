"""RM-1100: one sample-count reader for the TFT engine's MIN_GAMES floor.

recommend._sample (RM-1096), milestones._games (RM-1098) and the inline
first_rolldown check in recommend.level_advice were three functionally identical
copies of the rule "an aggregate row's top-4 game count `n` is
evidence only as a plain positive int". Two copies of a floor rule drift: a fix
to one (say, accepting 3.0) would leave the other site flagging the same row
the opposite way. The rule now lives once, as comps.sample_count, beside
MIN_GAMES, and every site calls it.

Float n is pinned explicitly: milestones.aggregate writes `n` as an int
(len(...)), so a float `n` did not come from the engine's own writer and reads
as no evidence (0), the same stance pair_stats takes on a float min_count.
"""
from __future__ import annotations

import ast
import inspect

import pytest

from tft.engine import comps, milestones, recommend

N = comps.MIN_GAMES


@pytest.mark.parametrize("row, want", [
    ({"n": N}, N),
    ({"n": 1}, 1),
    ({"n": 10 ** 6}, 10 ** 6),
    ({"n": 0}, 0),
    ({"n": -N}, 0),
    ({"n": float(N)}, 0),
    ({"n": N + 0.5}, 0),
    ({"n": float("nan")}, 0),
    ({"n": float("inf")}, 0),
    ({"n": str(N)}, 0),
    ({"n": True}, 0),
    ({"n": False}, 0),
    ({"n": None}, 0),
    ({"n": [N]}, 0),
    ({}, 0),
    (None, 0),
    ([("n", N)], 0),
    ("n", 0),
    (N, 0),
])
def test_sample_count_reads_only_a_plain_positive_int(row, want):
    got = comps.sample_count(row)
    assert got == want
    assert type(got) is int


def test_float_n_at_the_floor_is_explicitly_no_evidence():
    # The one case the two old copies agreed on silently and no test named.
    assert comps.sample_count({"n": float(N)}) == 0
    assert comps.sample_count({"n": float(N)}) < N


def test_the_two_copies_are_gone():
    assert not hasattr(recommend, "_sample")
    assert not hasattr(milestones, "_games")
    assert recommend.sample_count is comps.sample_count
    assert milestones.sample_count is comps.sample_count


@pytest.mark.parametrize("module", [recommend, milestones])
def test_no_module_re_derives_the_n_rule_by_hand(module):
    """No function in either module reads row.get("n") itself: the floor's input
    goes through comps.sample_count, so the rule cannot fork again."""
    tree = ast.parse(inspect.getsource(module))
    offenders = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get"
                and node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == "n"):
            offenders.append(node.lineno)
    assert offenders == []


# ------------------------------------------------------------------ the consumers agree on float n

def test_level_advice_reads_a_float_n_curve_row_as_too_few():
    out = recommend.level_advice({"label": "3-2", "level": 6},
                                 {"level_curve": {"3-2": {"median": 7, "n": float(N)}}})
    assert out["status"] == "insufficient"
    assert f"(0 of {N})" in out["message"]


def test_level_advice_reads_an_int_n_curve_row_as_a_verdict():
    out = recommend.level_advice({"label": "3-2", "level": 6},
                                 {"level_curve": {"3-2": {"median": 7, "n": N}}})
    assert out["status"] == "behind"


def test_next_milestone_flags_a_float_n_row():
    agg = {"level_reached": {"8": {"median": "4-2", "n": float(N)}}}
    out = recommend.level_advice({"label": "3-2", "level": 6}, agg)
    assert out["next"]["games"] == 0 and out["next"]["insufficient"] is True


def test_milestone_line_drops_a_float_n_row_and_keeps_an_int_one():
    assert recommend._milestone_line({"first_slam": {"median": "2-5", "n": float(N)}}) is None
    assert recommend._milestone_line({"first_slam": {"median": "2-5", "n": N}}) == "first slam 2-5"


def test_compare_to_average_flags_a_float_n_median_and_passes_an_int_one():
    mined = {"first_slam": {"label": "2-5"}}
    thin = milestones.compare_to_average(mined, {"first_slam": {"median": "2-5", "n": float(N)}})
    ok = milestones.compare_to_average(mined, {"first_slam": {"median": "2-5", "n": N}})
    assert [(r["games"], r["insufficient"]) for r in thin] == [(0, True)]
    assert [(r["games"], r["insufficient"]) for r in ok] == [(N, False)]
