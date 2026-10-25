"""TFT engine (slice TFT-13): live recommendations and the prior-top-4
planner-picker payload (tft/engine/recommend.py).

Odds come from tft/tft_roll_odds.py; these tests pass explicit SetConstants so
the parallel Set 18 odds fix in tft/tft_data.py can never move them, and they
prove the engine reports its own odds as stale when the constants are for
another set or unverified in client.
"""
from __future__ import annotations

import json

import pytest

from tests.test_tft_engine_synthetic import (
    SYNTH_DOC,
    SYNTH_SET_ID,
    obs,
    rerolls,
    seq_for,
    synth_history,
    timeline_record,
    u,
)
from tft import tft_roll_odds
from tft.engine import ENGINE_NAME, ENGINE_SCHEMA, comps, milestones, recommend


def _consts(set_number=SYNTH_SET_ID, verified=True):
    return tft_roll_odds.SetConstants(
        source="test", set_number=set_number, verified_in_client=verified,
        tier_odds={5: {1: 0.45, 2: 0.33, 3: 0.20, 4: 0.02, 5: 0.0},
                   8: {1: 0.15, 2: 0.20, 3: 0.32, 4: 0.30, 5: 0.03}},
        pool_sizes={1: 30, 2: 25, 3: 18, 4: 10, 5: 9},
        units_per_cost={1: 2, 2: 3, 3: 3, 4: 2, 5: 2})


@pytest.fixture(scope="module")
def sd():
    return comps.SetData.from_cdragon(SYNTH_DOC)


def _history():
    """synth_history plus three A-comp games that carry per-round rows."""
    extra = [
        timeline_record("t1", 1, {"2-1": 4, "2-5": 5, "3-1": 6, "3-6": 7, "4-2": 8},
                        gold={"3-2": 30}, shop=rerolls(seq_for("4-1"), 44, 12),
                        units=[obs("2-3", "U_Cora"), obs("2-4", "U_Cora", 1, ["I_Rage"]),
                               obs("2-7", "U_Bolt"), obs("2-7", "U_Cora", 2, ["I_Rage"])]),
        timeline_record("t2", 2, {"2-1": 4, "2-5": 5, "3-1": 6, "3-5": 7, "4-1": 8},
                        gold={"3-2": 36}, shop=rerolls(seq_for("4-1"), 48, 14),
                        units=[obs("2-3", "U_Bolt"), obs("2-5", "U_Bolt", 1, ["I_Staff"]),
                               obs("2-7", "U_Bolt"), obs("2-7", "U_Cora")]),
        timeline_record("t3", 3, {"2-1": 4, "2-6": 5, "3-2": 6, "3-6": 7, "4-2": 8},
                        gold={"3-2": 20, "4-1": 40}),
    ]
    return synth_history() + extra


@pytest.fixture(scope="module")
def built(sd):
    recs = _history()
    cat = comps.build_catalogue(recs, sd)
    ms = milestones.milestones_by_comp(recs, cat, sd)
    comp_a = cat["comps"][0]
    assert comp_a["label"] == "Mage / Blade - Gale"
    return cat, ms, comp_a


# ------------------------------------------------------------ nearest comps

def test_nearest_comps_ranks_by_core_coverage(sd, built):
    cat, _ms, comp_a = built
    state = {"board": [u("U_Gale"), u("U_Cora"), u("U_Bolt")], "bench": [u("U_Kite")], "items": []}
    ranked = recommend.nearest_comps(state, cat, sd)
    assert ranked[0]["comp_id"] == comp_a["comp_id"]
    assert ranked[0]["core_owned"] == ["U_Bolt", "U_Cora", "U_Gale", "U_Kite"]
    assert ranked[0]["core_missing"] == ["U_Jinx"]
    assert ranked[0]["score"] > ranked[1]["score"]
    beast = {"board": [u("U_Hex"), u("U_Fang"), u("U_Dune")], "bench": [], "items": []}
    assert recommend.nearest_comps(beast, cat, sd)[0]["label"] == "Beast / Ward - Hex"


def test_nearest_comps_reads_held_items(sd, built):
    cat, _ms, comp_a = built
    # Bolt sits in both cores; two Vests build Plate, which only the B comp uses.
    no_items = recommend.nearest_comps({"board": [u("U_Bolt")], "items": []}, cat, sd)
    assert no_items[0]["comp_id"] == comp_a["comp_id"]          # tie broken by top-4 rate
    vests = recommend.nearest_comps({"board": [u("U_Bolt")], "items": ["C_Vest", "C_Vest"]}, cat, sd)
    assert vests[0]["label"] == "Beast / Ward - Hex" and vests[0]["item_fit"] == 1.0
    assert {r["comp_id"]: r["item_fit"] for r in vests}[comp_a["comp_id"]] == 0.0


def test_nearest_comps_on_an_empty_board_is_empty(sd, built):
    cat, _ms, _a = built
    assert recommend.nearest_comps({"board": [], "bench": []}, cat, sd) == []


# --------------------------------------------------------------- shop picks

def test_shop_picks_rank_star_up_then_core_then_flex(sd, built):
    _cat, _ms, comp_a = built
    state = {
        "level": 8,
        "board": [u("U_Gale"), u("U_Cora"), u("U_Bolt", 2)],
        "bench": [u("U_Cora"), u("U_Kite")],
        "offers": [
            {"slot": 0, "champion_api": "U_Echo", "cost": 3},   # flex
            {"slot": 1, "champion_api": "U_Hex", "cost": 4},    # not in the comp
            {"slot": 2, "champion_api": "U_Cora", "cost": 2},   # third copy -> 2-star
            {"slot": 3, "champion_api": "U_Bolt", "cost": 1},   # owned core, not 3-star
            {"slot": 4, "kind": "empty"},
        ],
    }
    consts = _consts()
    out = recommend.shop_picks(state, comp_a, sd, consts=consts)
    assert [(p["slot"], p["reason"]) for p in out["picks"]] == [(2, "star_up"), (3, "core_copy"), (0, "flex")]
    assert out["odds_stale"] is False
    # Each pick carries its own next-shop odds: Cora has 2 copies out, cost-2 copies out = Cora 2 + Kite 1.
    cora = out["picks"][0]
    assert cora["p_shop"] == round(tft_roll_odds.shop_hit_probability(
        8, 2, target_copies_taken=2, cost_copies_taken=3, consts=consts), 4)
    assert cora["rolls_50"] == tft_roll_odds.rolls_for_confidence(
        8, 2, confidence=0.5, target_copies_taken=2, cost_copies_taken=3, consts=consts)


def test_shop_picks_and_recommend_survive_junk(sd, built):
    cat, ms, comp_a = built
    state = {"level": "x", "board": "junk", "bench": [None, 3],
             "offers": [{"kind": ["empty"]}, "junk", {"champion_api": None}, {"champion_api": "U_Jinx"}]}
    out = recommend.shop_picks(state, comp_a, sd, lobby_boards={"P2": [u("U_Jinx")], "P3": "junk"},
                               consts=_consts())
    assert [p["api"] for p in out["picks"]] == ["U_Jinx"] and out["picks"][0]["p_shop"] is None
    assert recommend.recommend("junk", cat, ms, sd, consts=_consts())["target"] is None
    assert recommend.level_advice({"label": "3-2", "level": 5}, "junk")["status"] == "unknown"


def test_wanted_units_carry_hit_odds_from_tft_roll_odds(sd, built):
    _cat, _ms, comp_a = built
    consts = _consts()
    lobby = [[u("U_Jinx", 2), u("U_Ira", 1)], [u("U_Ace", 1)]]
    state = {"level": 8, "board": [u("U_Gale"), u("U_Cora")], "bench": [], "offers": []}
    out = recommend.shop_picks(state, comp_a, sd, lobby_boards=lobby, consts=consts)
    wanted = {w["api"]: w for w in out["wanted"]}
    assert set(wanted) == {"U_Jinx", "U_Bolt", "U_Kite"}
    jinx = wanted["U_Jinx"]
    assert jinx["copies_taken"] == 3 and jinx["contested"] is True
    want_p = tft_roll_odds.shop_hit_probability(8, 5, target_copies_taken=3, cost_copies_taken=4, consts=consts)
    assert jinx["p_shop"] == round(want_p, 4)
    assert jinx["rolls_50"] == tft_roll_odds.rolls_for_confidence(
        8, 5, confidence=0.5, target_copies_taken=3, cost_copies_taken=4, consts=consts)
    assert wanted["U_Kite"]["contested"] is False


def test_odds_are_stale_for_another_set_and_absent_for_an_unknown_level(sd, built):
    _cat, _ms, comp_a = built
    state = {"level": 8, "board": [u("U_Gale")], "bench": [], "offers": []}
    assert recommend.shop_picks(state, comp_a, sd, consts=_consts(set_number=14))["odds_stale"] is True
    assert recommend.shop_picks(state, comp_a, sd, consts=_consts(verified=False))["odds_stale"] is True
    no_level = recommend.shop_picks({"level": 3, "board": [], "bench": []}, comp_a, sd, consts=_consts())
    assert all(w["p_shop"] is None and w["rolls_50"] is None for w in no_level["wanted"])


# --------------------------------------------------------------- item slams

def test_item_slams_rank_by_the_carry_then_the_comp(sd, built):
    _cat, _ms, comp_a = built
    held = ["C_Rod", "C_Rod", "C_Bow", "C_Sword", "I_Edge"]
    slams = recommend.item_slams(held, comp_a, sd)
    assert [s["item"] for s in slams] == ["I_Staff", "I_Rage", "I_Cleave"]
    # Gale carries Staff in all 8 A games; Jinx holds one too: 16 on the comp.
    assert slams[0] == {"item": "I_Staff", "name": "Staff", "components": ["C_Rod", "C_Rod"],
                        "on": "U_Gale", "carry_games": 8, "comp_games": 16}
    assert recommend.item_slams(["C_Rod"], comp_a, sd) == []


# ------------------------------------------------------------- level advice

def test_level_advice_against_the_top4_median(sd, built):
    _cat, ms, comp_a = built
    agg = ms["comps"][comp_a["comp_id"]]
    behind = recommend.level_advice({"label": "3-2", "level": 5, "gold": 30}, agg)
    assert behind["status"] == "behind"
    assert behind["message"] == "Lv5 at 3-2; your top-4 median is Lv6 at 3-2"
    assert behind["next"] == {"level": 7, "label": "3-6"}
    on_curve = recommend.level_advice({"label": "3-2", "level": 6}, agg)
    assert on_curve["status"] == "on_curve"
    ahead = recommend.level_advice({"label": "3-2", "level": 7}, agg)
    assert ahead["status"] == "ahead"
    roll = recommend.level_advice({"label": "4-1", "level": 8, "gold": 50}, agg)
    assert roll["roll"] == {"label": "4-1", "to_gold": 20.0, "games": 2}
    unknown = recommend.level_advice({"label": "6-6", "level": 9}, agg)
    assert unknown["status"] == "unknown" and unknown["message"].isascii()


# ------------------------------------------------------ one-call live payload

def test_recommend_bundles_the_live_answer(sd, built):
    cat, ms, comp_a = built
    state = {"label": "3-2", "level": 5, "gold": 30,
             "board": [u("U_Gale"), u("U_Cora")], "bench": [u("U_Bolt")],
             "items": ["C_Rod", "C_Rod"], "offers": [{"slot": 0, "champion_api": "U_Jinx", "cost": 5}]}
    out = recommend.recommend(state, cat, ms, sd, consts=_consts())
    assert out["engine"] == ENGINE_NAME and out["schema"] == ENGINE_SCHEMA
    assert out["target"]["comp_id"] == comp_a["comp_id"]
    assert out["shop"]["picks"][0]["api"] == "U_Jinx"
    assert out["items"][0]["item"] == "I_Staff"
    assert out["level"]["status"] == "behind"
    json.dumps(out)


def test_recommend_without_a_catalogue_degrades_honestly(sd):
    empty = comps.build_catalogue([], sd)
    out = recommend.recommend({"board": [u("U_Gale")]}, empty, None, sd, consts=_consts())
    assert out["target"] is None and out["shop"] is None and out["items"] == []
    assert out["level"]["status"] == "unknown"


# ------------------------------------------------------- planner picker (TFT-14)

def test_planner_choices_payload_for_the_overlay_picker(sd, built):
    cat, ms, comp_a = built
    lobby = [[u("U_Jinx", 2), u("U_Cora", 1)], [u("U_Hex", 2)]]
    out = recommend.planner_choices(cat, ms, sd, lobby_boards=lobby)
    assert out["engine"] == ENGINE_NAME and out["schema"] == ENGINE_SCHEMA
    assert out["set_id"] == SYNTH_SET_ID and out["top4_only"] is True
    first = out["choices"][0]
    assert first["comp_id"] == comp_a["comp_id"]
    # A-comp placements 1, 2, 3, 6, 4 (synthetic) + 1, 2, 3 (with rounds): 22 / 8.
    assert first["summary"] == "8 games, avg 2.8, top-4 88%"
    assert {c["api"] for c in first["core"]} == {"U_Gale", "U_Jinx", "U_Cora", "U_Bolt", "U_Kite"}
    assert first["carry"]["api"] == "U_Gale"
    assert [i["name"] for i in first["carry"]["items"]] == ["Edge", "Rage", "Staff"]
    assert first["contest"] == 2
    digest = first["digest"]
    assert 1 <= len(digest) <= 6 and all(line.isascii() and len(line) <= 64 for line in digest)
    assert digest[0].startswith("Core: ")
    assert "Lv6 by 3-1" in " | ".join(digest)
    assert "roll at 4-1 to ~20g" in " | ".join(digest)
    assert "Opener: " in " | ".join(digest)
    # Every listed comp has at least one top-4 game; at most 8 rows.
    assert all(c["top4_games"] >= 1 for c in out["choices"]) and len(out["choices"]) <= 8
    json.dumps(out)


def test_planner_choices_cap_and_no_lobby(sd, built):
    cat, ms, _a = built
    out = recommend.planner_choices(cat, ms, sd, limit=1)
    assert len(out["choices"]) == 1 and out["choices"][0]["contest"] is None
    assert recommend.planner_choices(cat, None, sd)["choices"][0]["milestones"] is None
