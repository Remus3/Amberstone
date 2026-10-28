"""RM-1099: the planner digest's Opener line applies the MIN_GAMES floor.

milestones.aggregate() builds `opener` as the units on board at the last
stage-2 round in at least OPENER_SHARE of the games that had one, but it never
said how many games that was. recommend._digest() printed "Opener: ..." from
it unconditionally, so one top-4 game made every unit a 1.0 share and the
synthetic planner fixture printed an opener read from 2 games.

  (a) aggregate() now exposes `opener_games` (appended; the existing keys are
      unchanged), the count of games with unit observations whose last
      stage-2 board holds at least one real unit id.
  (b) _digest() drops the Opener line when `opener_games` is under MIN_GAMES.
      A text line carries no flag, so dropping is the honest choice (the same
      rule RM-1098 applied to _milestone_line). A missing or junk count is
      no evidence and reads as 0.

All rows are hand-written synthetic aggregates.
"""
from __future__ import annotations

import json

import pytest

from tests.test_tft_engine_recommend import _history
from tests.test_tft_engine_synthetic import SYNTH_DOC
from tft.engine import comps, milestones, recommend
from tft.engine.comps import MIN_GAMES

JUNK_N = [None, True, "3", -2, 2.5, 3.0, [3]]


@pytest.fixture(scope="module")
def sd():
    return comps.SetData.from_cdragon(SYNTH_DOC)


@pytest.fixture(scope="module")
def built(sd):
    recs = _history()
    cat = comps.build_catalogue(recs, sd)
    ms = milestones.milestones_by_comp(recs, cat, sd)
    return cat, ms, cat["comps"][0]


def _mined(opener):
    return {"rounds": 3, "has_unit_obs": True, "opener": opener}


# ------------------------------------------------------- (a) the aggregate count

@pytest.mark.parametrize("games", [1, 2, MIN_GAMES, 7])
def test_aggregate_exposes_the_opener_game_count(games):
    agg = milestones.aggregate([_mined(["U_Bolt", "U_Cora"])] * games)
    assert agg["opener_games"] == games
    assert [o["share"] for o in agg["opener"]] == [1.0, 1.0]


def test_opener_games_counts_only_games_with_an_observed_stage2_board():
    rows = [_mined(["U_Bolt"]), _mined([]), _mined(None), {"rounds": 3, "opener": ["U_Bolt"]},
            _mined([5, None]), _mined(["U_Bolt", "U_Cora"])]
    agg = milestones.aggregate(rows)
    # Only the first and the last row carry a stage-2 board of real unit ids:
    # no unit obs, an empty board and a junk board are not opener games.
    assert agg["opener_games"] == 2
    assert agg["opener"] == [{"api": "U_Bolt", "share": 1.0}, {"api": "U_Cora", "share": 0.5}]


def test_an_empty_aggregate_has_zero_opener_games():
    agg = milestones.aggregate([])
    assert agg["opener_games"] == 0 and agg["opener"] == []
    json.dumps(agg)


def test_the_fixture_comp_opener_rests_on_two_games(built):
    _cat, ms, comp_a = built
    agg = ms["comps"][comp_a["comp_id"]]
    assert agg["opener_games"] == 2
    assert {o["api"] for o in agg["opener"]} == {"U_Bolt", "U_Cora"}
    json.dumps(ms)


# ------------------------------------------------------- (b) the digest line

def _agg(games, opener=({"api": "U_Bolt", "share": 1.0},)):
    agg = {"opener": list(opener)}
    if games is not None:
        agg["opener_games"] = games
    return agg


def _digest(agg, sd):
    return recommend._digest([{"name": "Gale"}], [], None, agg, None, sd)


def _opener_lines(lines):
    return [line for line in lines if line.startswith("Opener: ")]


@pytest.mark.parametrize("games", [MIN_GAMES, MIN_GAMES + 1, 40])
def test_digest_prints_the_opener_at_or_above_the_floor(sd, games):
    assert _opener_lines(_digest(_agg(games), sd)) == ["Opener: " + sd.unit_name("U_Bolt")]


@pytest.mark.parametrize("games", [0, 1, MIN_GAMES - 1])
def test_digest_drops_the_opener_under_the_floor(sd, games):
    lines = _digest(_agg(games), sd)
    assert _opener_lines(lines) == []
    assert lines[0] == "Core: Gale"


@pytest.mark.parametrize("games", JUNK_N)
def test_digest_reads_a_junk_opener_count_as_no_evidence(sd, games):
    assert _opener_lines(_digest(_agg(games), sd)) == []


def test_digest_without_an_opener_count_drops_the_line(sd):
    # An aggregate from before RM-1099 (no opener_games) is no evidence.
    assert _opener_lines(_digest(_agg(None), sd)) == []


def test_planner_digest_drops_the_two_game_opener(sd, built):
    cat, ms, comp_a = built
    out = recommend.planner_choices(cat, ms, sd)
    row = next(c for c in out["choices"] if c["comp_id"] == comp_a["comp_id"])
    assert row["digest"][0].startswith("Core: ")
    assert _opener_lines(row["digest"]) == []


def test_planner_digest_keeps_an_opener_on_enough_games(sd, built):
    cat, ms, comp_a = built
    agg = dict(ms["comps"][comp_a["comp_id"]], opener_games=MIN_GAMES)
    payload = dict(ms, comps={comp_a["comp_id"]: agg})
    out = recommend.planner_choices(cat, payload, sd)
    row = next(c for c in out["choices"] if c["comp_id"] == comp_a["comp_id"])
    names = sorted(sd.unit_name(a) for a in ("U_Bolt", "U_Cora"))
    assert len(_opener_lines(row["digest"])) == 1
    # The overlay fit rule the TFT-14 picker test pinned while the line was unfloored.
    assert all(line.isascii() and len(line) <= 64 for line in row["digest"])
    assert sorted(_opener_lines(row["digest"])[0][len("Opener: "):].split(", ")) == names
