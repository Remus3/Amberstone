"""RM-1096: the live recommendation's small-sample flags (tft/engine/recommend.py).

RM-893 floored the catalogue (MIN_GAMES placed games) and flagged nearest-comp
rows `insufficient`, but two live paths still spoke from a sample of one:

  (a) recommend() built the explicit-target row (a target_comp_id the player
      picked that is not among the nearest comps) without the `insufficient`
      flag, so the payload could not say "few games" for the comp it coaches.
  (b) level_advice() called the player behind / ahead / on_curve against the
      comp's top-4 median at this round whatever that median's n was, so one
      top-4 game made a verdict. Below MIN_GAMES top-4 games at the round it
      now says "too few top-4 games" (status "insufficient"), and the roll hint,
      which already discloses its game count, carries the same flag.

All rows are hand-written synthetic aggregates and catalogue rows.
"""
from __future__ import annotations

import json

import pytest

from tests.test_tft_engine_synthetic import SYNTH_DOC, u
from tests.test_tft_engine_recommend import _consts, _history
from tft.engine import comps, milestones, recommend
from tft.engine.comps import MIN_GAMES


@pytest.fixture(scope="module")
def sd():
    return comps.SetData.from_cdragon(SYNTH_DOC)


@pytest.fixture(scope="module")
def built(sd):
    recs = _history()
    cat = comps.build_catalogue(recs, sd)
    ms = milestones.milestones_by_comp(recs, cat, sd)
    return cat, ms, cat["comps"][0]


def _curve(n, median=6):
    row = {"median": median}
    if n is not None:
        row["n"] = n
    return {"level_curve": {"3-2": row}}


# ------------------------------------------------------------------ (a) target

def test_explicit_target_outside_nearest_carries_the_flag(sd, built):
    cat, ms, comp_a = built
    assert comp_a["insufficient"] is False
    # No board and no bench: nearest is empty, so the target is the fallback row.
    out = recommend.recommend({"target_comp_id": comp_a["comp_id"]}, cat, ms, sd, consts=_consts())
    assert out["alternatives"] == []
    assert out["target"]["comp_id"] == comp_a["comp_id"]
    assert out["target"]["insufficient"] is False
    json.dumps(out)


@pytest.mark.parametrize("patch", [{"insufficient": True}, {"placed_games": MIN_GAMES - 1},
                                   {"placed_games": None}])
def test_explicit_under_floor_target_is_flagged(sd, built, patch):
    cat, ms, comp_a = built
    thin = dict(comp_a, **patch)
    cat2 = dict(cat, comps=[thin] + [c for c in cat["comps"] if c["comp_id"] != comp_a["comp_id"]])
    out = recommend.recommend({"target_comp_id": comp_a["comp_id"]}, cat2, ms, sd, consts=_consts())
    assert out["target"]["comp_id"] == comp_a["comp_id"]
    assert out["target"]["insufficient"] is True


def test_nearest_fallback_target_keeps_its_flag(sd, built):
    cat, ms, comp_a = built
    state = {"board": [u("U_Gale"), u("U_Cora")], "bench": [u("U_Bolt")], "items": []}
    out = recommend.recommend(state, cat, ms, sd, consts=_consts())
    near = recommend.nearest_comps(state, cat, sd)
    assert out["target"] == near[0]
    assert isinstance(out["target"]["insufficient"], bool)


# ------------------------------------------------------------ (b) level advice

@pytest.mark.parametrize("n", [1, MIN_GAMES - 1, None, True, "3", -2])
def test_level_verdict_below_the_floor_says_too_few(n):
    out = recommend.level_advice({"label": "3-2", "level": 5}, _curve(n))
    assert out["status"] == "insufficient"
    assert "too few top-4 games" in out["message"].lower()
    assert "behind" not in out["message"] and out["message"].isascii()


def test_level_verdict_at_the_floor_is_a_verdict():
    out = recommend.level_advice({"label": "3-2", "level": 5}, _curve(MIN_GAMES))
    assert out["status"] == "behind"
    assert out["message"] == "Lv5 at 3-2; your top-4 median is Lv6 at 3-2"


def test_too_few_message_names_the_count_and_the_floor():
    out = recommend.level_advice({"label": "3-2", "level": 7}, _curve(1))
    assert out["message"] == f"Too few top-4 games at 3-2 (1 of {MIN_GAMES}) to judge Lv7"


def test_no_median_is_still_no_data_not_too_few():
    out = recommend.level_advice({"label": "3-2", "level": 5}, {"level_curve": {"3-2": {"n": 1}}})
    assert out["status"] == "unknown"
    assert out["message"] == "No top-4 level data at 3-2 yet"


def _roll(n):
    return {"first_rolldown": {"n": n, "q1": "3-5", "q3": "4-2", "median": "4-1"},
            "rolldown_gold_end": {"median": 18}}


@pytest.mark.parametrize("n,flag", [(1, True), (MIN_GAMES - 1, True), (MIN_GAMES, False), (9, False)])
def test_roll_hint_carries_the_floor_flag(n, flag):
    out = recommend.level_advice({"label": "4-1", "level": 8}, _roll(n))
    assert out["roll"] == {"label": "4-1", "to_gold": 18.0, "games": n, "insufficient": flag}


def test_live_payload_flags_a_two_game_roll(sd, built):
    cat, ms, comp_a = built
    agg = ms["comps"][comp_a["comp_id"]]
    assert agg["first_rolldown"]["n"] == 2
    out = recommend.recommend({"label": "4-1", "level": 8, "target_comp_id": comp_a["comp_id"]},
                              cat, ms, sd, consts=_consts())
    assert out["level"]["roll"]["insufficient"] is True
