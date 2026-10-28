"""RM-1098: the rest of the top-4 median readers apply the MIN_GAMES floor.

RM-1096 floored level_advice()'s verdict and flagged its roll hint, but three
readers still spoke from a median of one or two top-4 games:

  (a) level_advice()'s `next` milestone, read from the level_reached median,
      never read that median's n. It now carries `games` and `insufficient`,
      the same pair the roll hint carries.
  (b) _milestone_line(), the planner hover digest, printed "roll at 4-1 to
      ~20g" from 2 top-4 games. A text line has no flag, so a part whose
      median rests on fewer than MIN_GAMES games is dropped; a roll whose gold
      median alone is thin keeps the round and drops the gold.
  (c) milestones.compare_to_average(), the post-match digest rows, compared
      this match against a median of any n. Every row now carries `games` and
      `insufficient`; the verdict stays, so a consumer can show it greyed.

All rows are hand-written synthetic aggregates.
"""
from __future__ import annotations

import json

import pytest

from tests.test_tft_engine_recommend import _history
from tests.test_tft_engine_synthetic import SYNTH_DOC
from tft.engine import comps, milestones, recommend
from tft.engine.comps import MIN_GAMES

JUNK_N = [None, True, "3", -2, 2.5]


@pytest.fixture(scope="module")
def sd():
    return comps.SetData.from_cdragon(SYNTH_DOC)


@pytest.fixture(scope="module")
def built(sd):
    recs = _history()
    cat = comps.build_catalogue(recs, sd)
    ms = milestones.milestones_by_comp(recs, cat, sd)
    return cat, ms, cat["comps"][0]


def _stat(median, n):
    row = {"median": median}
    if n is not None:
        row["n"] = n
    return row


# ------------------------------------------------------- (a) the next milestone

def _reached(n):
    return {"level_curve": {"3-2": {"median": 6, "n": 9}}, "level_reached": {"7": _stat("4-1", n)}}


@pytest.mark.parametrize("n,flag", [(1, True), (MIN_GAMES - 1, True), (MIN_GAMES, False), (9, False)])
def test_next_milestone_carries_the_floor_flag(n, flag):
    out = recommend.level_advice({"label": "3-2", "level": 6}, _reached(n))
    assert out["next"] == {"level": 7, "label": "4-1", "games": n, "insufficient": flag}


@pytest.mark.parametrize("n", JUNK_N)
def test_next_milestone_with_junk_n_is_flagged_as_no_evidence(n):
    out = recommend.level_advice({"label": "3-2", "level": 6}, _reached(n))
    assert out["next"] == {"level": 7, "label": "4-1", "games": 0, "insufficient": True}


# ---------------------------------------------------- (b) the planner digest line

def _digest_agg(n6=9, n8=9, nroll=9, ngold=9, nslam=9):
    return {"level_reached": {"6": _stat("3-1", n6), "8": _stat("4-5", n8)},
            "first_rolldown": _stat("4-1", nroll), "rolldown_gold_end": _stat(20.0, ngold),
            "first_slam": _stat("2-5", nslam)}


def test_digest_line_at_the_floor_keeps_every_part():
    line = recommend._milestone_line(_digest_agg(MIN_GAMES, MIN_GAMES, MIN_GAMES, MIN_GAMES, MIN_GAMES))
    assert line == "Lv6 by 3-1, Lv8 by 4-5, roll at 4-1 to ~20g, first slam 2-5"


@pytest.mark.parametrize("field,gone", [("n6", "Lv6 by 3-1"), ("n8", "Lv8 by 4-5"),
                                        ("nroll", "roll at 4-1"), ("nslam", "first slam 2-5")])
@pytest.mark.parametrize("n", [1, MIN_GAMES - 1, None])
def test_digest_line_drops_a_part_under_the_floor(field, gone, n):
    line = recommend._milestone_line(_digest_agg(**{field: n}))
    assert gone not in line
    assert line.count(", ") == 2  # the other three parts stay


@pytest.mark.parametrize("n", [1, MIN_GAMES - 1, None, "9"])
def test_digest_line_drops_only_the_gold_when_the_gold_median_is_thin(n):
    line = recommend._milestone_line(_digest_agg(ngold=n))
    assert "roll at 4-1, " in line and "~20g" not in line


def test_digest_line_all_thin_is_none():
    assert recommend._milestone_line(_digest_agg(1, 1, 1, 1, 1)) is None


def test_planner_digest_drops_the_two_game_roll(sd, built):
    cat, ms, comp_a = built
    agg = ms["comps"][comp_a["comp_id"]]
    assert agg["first_rolldown"]["n"] == 2
    out = recommend.planner_choices(cat, ms, sd)
    row = next(c for c in out["choices"] if c["comp_id"] == comp_a["comp_id"])
    assert not any("roll at" in line for line in row["digest"])


# ----------------------------------------------- (c) the post-match compare rows

def _compare_agg(n):
    return {"level_reached": {"6": _stat("3-1", n)}, "first_rolldown": _stat("4-1", n),
            "first_slam": _stat("2-5", n), "gold_at": {"3-2": _stat(40.0, n)}, "hp_at": {"4-1": _stat(60.0, n)}}


_MINED = {"level_reached": {"6": "3-2"}, "first_rolldown": "4-1", "first_slam": {"label": "2-3"},
          "gold_at": {"3-2": 12}, "hp_at": {"4-1": 80}}


@pytest.mark.parametrize("n,flag", [(1, True), (MIN_GAMES - 1, True), (MIN_GAMES, False), (9, False)])
def test_compare_rows_carry_the_floor_flag(n, flag):
    rows = {r["milestone"]: r for r in milestones.compare_to_average(_MINED, _compare_agg(n))}
    assert set(rows) == {"level_6", "first_rolldown", "first_slam", "gold_at_3-2", "hp_at_4-1"}
    for row in rows.values():
        assert row["games"] == n and row["insufficient"] is flag
    assert rows["level_6"] == {"milestone": "level_6", "this_match": "3-2", "median": "3-1", "verdict": "later",
                               "games": n, "insufficient": flag}
    assert rows["gold_at_3-2"]["verdict"] == "lower"
    json.dumps(rows)


@pytest.mark.parametrize("n", JUNK_N)
def test_compare_rows_with_junk_n_are_flagged_as_no_evidence(n):
    rows = milestones.compare_to_average(_MINED, _compare_agg(n))
    assert len(rows) == 5
    assert all(r["games"] == 0 and r["insufficient"] is True for r in rows)
