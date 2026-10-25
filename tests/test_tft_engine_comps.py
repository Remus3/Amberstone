"""TFT engine (slice TFT-13): set data view, board normalisation, traits,
carry choice and the deterministic comp catalogue (tft/engine/comps.py).

Logic tests run on the synthetic set of tests/test_tft_engine_synthetic.py.
The worked-example tests run on the tracked Set 18 CommunityDragon extract
read through tft/tft_set.py (load_cdragon), so they also prove the EoG
apiNames join the set data directly (docs/TFT_PROGRAM.md section 0 item 2).
"""
from __future__ import annotations

import hashlib
import json
import random

import pytest

from tests.test_tft_engine_synthetic import (
    SYNTH_DOC,
    SYNTH_SET_ID,
    WORKED_FINAL_BOARD,
    board_a,
    board_b,
    synth_history,
    u,
    worked_example_record,
)
from tft.engine import ENGINE_NAME, ENGINE_SCHEMA, comps


@pytest.fixture(scope="module")
def sd():
    return comps.SetData.from_cdragon(SYNTH_DOC)


@pytest.fixture(scope="module")
def s18():
    data = comps.load_set_data(18)
    if not data.units:
        pytest.skip("Set 18 CommunityDragon extract not ingested")
    return data


# ---------------------------------------------------------------- set data

def test_set_data_reads_units_traits_and_recipes(sd):
    assert sd.set_id == SYNTH_SET_ID
    assert sd.units["U_Gale"].cost == 4
    assert sd.units["U_Gale"].traits == ("Mage", "Blade")
    assert sd.trait_breakpoints["Mage"] == (3, 5)
    assert sd.recipes["I_Rage"] == ("C_Bow", "C_Rod")
    assert sd.components == frozenset({"C_Sword", "C_Bow", "C_Rod", "C_Vest", "C_Spat"})
    assert sd.emblem_traits == {"I_BladeEmblem": "Blade"}
    assert sd.item_kind("C_Bow") == "component"
    assert sd.item_kind("I_Rage") == "crafted"
    assert sd.item_kind("I_BladeEmblem") == "emblem"
    assert sd.item_kind("I_Relic") == "other"
    assert sd.is_unique_trait("Solo") and not sd.is_unique_trait("Crown")


def test_load_set_data_goes_through_the_set_resolver(monkeypatch):
    seen = {}

    def fake_resolve(live_set=None, *, root=None):
        seen["resolve"] = live_set
        return 77

    def fake_cdragon(set_number=None, *, root=None):
        seen["cdragon"] = set_number
        return dict(SYNTH_DOC, _set=77)

    monkeypatch.setattr(comps.tft_set, "resolve_set", fake_resolve)
    monkeypatch.setattr(comps.tft_set, "load_cdragon", fake_cdragon)
    data = comps.load_set_data(18)
    assert seen == {"resolve": 18, "cdragon": 77}
    assert data.set_id == 77 and "U_Ace" in data.units


def test_unit_lookup_accepts_api_and_display_names(sd):
    assert sd.resolve_unit_api("U_Gale") == "U_Gale"
    assert sd.resolve_unit_api("u_gale") == "U_Gale"
    assert sd.resolve_unit_api("Gale") == "U_Gale"
    assert sd.resolve_unit_api("Nobody") is None


# ---------------------------------------------------------- normalisation

def test_normalize_accepts_lcu_eog_eog_file_and_store_shapes(sd):
    lcu_eog = {"championId": "U_Gale", "level": 2, "price": 4,
               "items": [{"nameId": "I_Rage", "id": 0, "name": "Rage"}, {"nameId": "C_Bow"}]}
    eog_file = {"championName": "U_Gale", "starLevel": 2, "itemNames": ["I_Rage", "C_Bow"], "price": 4}
    store = {"champion_api": "U_Gale", "star": 2, "items_json": json.dumps(["I_Rage", "C_Bow"]), "cost": 4}
    got = {comps.normalize_unit(raw, sd) for raw in (lcu_eog, eog_file, store)}
    assert len(got) == 1
    unit = got.pop()
    assert (unit.api, unit.star, unit.items, unit.cost) == ("U_Gale", 2, ("C_Bow", "I_Rage"), 4)


def test_normalize_board_drops_junk_and_sorts(sd):
    board = comps.normalize_board([u("U_Kite"), None, {"star": 2}, u("U_Ace", 3), "x"], sd)
    assert [x.api for x in board] == ["U_Ace", "U_Kite"]
    assert board[0].cost == 1  # cost filled from set data when the row has none


# ------------------------------------------------------------------ traits

def test_duplicate_units_count_once_and_emblems_add_their_trait(sd):
    board = comps.normalize_board([
        u("U_Ace"), u("U_Ace"),                 # Blade, Ward - one unique unit
        u("U_Dune", 1, ["I_BladeEmblem"]),      # Ward, Beast + Blade from the emblem
        u("U_Cora", 1, ["I_BladeEmblem"]),      # already Blade: the emblem adds nothing
    ], sd)
    traits = {t.trait: t for t in comps.board_traits(board, sd)}
    assert traits["Blade"].count == 3 and traits["Blade"].tier == 1
    assert traits["Ward"].count == 2 and traits["Ward"].active
    assert traits["Beast"].count == 1 and not traits["Beast"].active
    assert comps.trait_signature(board, sd) == frozenset({"Blade", "Ward"})


def test_unique_traits_stay_out_of_the_signature(sd):
    board = comps.normalize_board([u("U_Ira"), u("U_Jinx")], sd)
    active = {t.trait for t in comps.board_traits(board, sd) if t.active}
    assert active == {"Solo", "Crown"}
    assert comps.trait_signature(board, sd) == frozenset({"Crown"})


def test_worked_board_traits_match_the_hud(s18):
    # QA_REPORT section 5: Flora Fatalis 2/2, Bounty Seeker 1/1, Emerald Aspect
    # 1/1, Spellweaver 3, Blossom 3, Lunar 2, Juggernaut 2, Vanguard 2;
    # Defender 1 inactive.
    board = comps.normalize_board(WORKED_FINAL_BOARD, s18)
    traits = {t.trait: t for t in comps.board_traits(board, s18)}
    active = {t.trait: t.count for t in traits.values() if t.active}
    assert active == {"Flora Fatalis": 2, "Bounty Seeker": 1, "Emerald Aspect": 1, "Spellweaver": 3,
                      "Blossom": 3, "Lunar": 2, "Juggernaut": 2, "Vanguard": 2}
    assert traits["Defender"].count == 1 and not traits["Defender"].active
    assert traits["Flora Fatalis"].tier == 2


# ------------------------------------------------------------------- carry

def test_carry_is_the_most_itemised_unit_with_a_deterministic_tiebreak(s18):
    board = comps.normalize_board(WORKED_FINAL_BOARD, s18)
    carry = comps.board_carry(board, s18)
    # Draven and Aphelios both hold 3 carry items; the higher cost wins. Emblems
    # never count (Sejuani / Yunara / Yorick hold 2 carry items each).
    assert carry.api == "DA_Draven18"
    assert comps.carry_items(carry, s18) == ("DA_KrakensFury", "DA_SteraksGage", "DA_ThiefsGloves")


def test_components_do_not_make_a_carry(sd):
    board = comps.normalize_board([u("U_Ace", 1, ["C_Bow", "C_Rod"]), u("U_Kite")], sd)
    assert comps.board_carry(board, sd) is None


# --------------------------------------------------------------- catalogue

def test_catalogue_clusters_the_two_archetypes(sd):
    cat = comps.build_catalogue(synth_history(), sd)
    assert cat["engine"] == ENGINE_NAME and cat["schema"] == ENGINE_SCHEMA
    assert cat["set_id"] == SYNTH_SET_ID
    assert cat["games"] == 9
    assert cat["skipped"] == {"other_set": 1, "queue_kind": 1, "no_board": 0}
    assert len(cat["comps"]) == 2
    a, b = cat["comps"]

    assert a["games"] == 5 and a["top4_games"] == 4
    assert a["avg_placement"] == 3.2 and a["top4_rate"] == 0.8
    assert {c["api"] for c in a["core"]} == {"U_Gale", "U_Jinx", "U_Cora", "U_Bolt", "U_Kite"}
    assert {f["api"] for f in a["flex"]} == {"U_Echo", "U_Lumen"}
    assert a["carry"]["api"] == "U_Gale"
    assert a["carry"]["item_sets"][0] == {"items": ["I_Edge", "I_Rage", "I_Staff"],
                                         "names": ["Edge", "Rage", "Staff"], "games": 5}
    assert a["label"] == "Mage / Blade - Gale"
    assert a["augments"] == [{"api": "A_Rich", "name": "Rich Get Richer", "games": 3},
                             {"api": "A_Tank", "name": "Tank Up", "games": 2}]
    assert a["three_star"] == []  # Bolt is 3-star in one of five games only
    assert a["match_ids"] == ["m-a0", "m-a1", "m-a2", "m-a3", "m-a4"]

    assert b["games"] == 4 and b["top4_games"] == 1
    assert b["avg_placement"] == 5.5 and b["top4_rate"] == 0.25
    assert {c["api"] for c in b["core"]} == {"U_Hex", "U_Fang", "U_Dune", "U_Bolt", "U_Ace"}
    assert b["label"] == "Beast / Ward - Hex"
    assert cat["assignments"]["m-b2"] == b["comp_id"]
    assert "m-du" not in cat["assignments"] and "m-old" not in cat["assignments"]


def test_catalogue_is_independent_of_input_order(sd):
    rows = synth_history()
    want = json.dumps(comps.build_catalogue(rows, sd), sort_keys=True)
    rng = random.Random(1806)
    for _ in range(6):
        shuffled = list(rows)
        rng.shuffle(shuffled)
        assert json.dumps(comps.build_catalogue(shuffled, sd), sort_keys=True) == want


def test_comp_id_is_a_hash_of_the_core_units_only(sd):
    cat = comps.build_catalogue(synth_history(), sd)
    a = cat["comps"][0]
    core = sorted(c["api"] for c in a["core"])
    assert a["comp_id"] == "c-" + hashlib.sha1("|".join(core).encode("ascii")).hexdigest()[:10]
    # Another A game with a new flex unit leaves the id where it was.
    more = synth_history() + [{"match_id": "m-a9", "set_id": SYNTH_SET_ID, "queue_kind": "ranked",
                               "placement": 2, "final_board": board_a(0) + [u("U_Ace", 1)]}]
    again = comps.build_catalogue(more, sd)
    assert again["comps"][0]["comp_id"] == a["comp_id"]
    assert again["comps"][0]["games"] == 6


def test_missing_placement_counts_a_game_but_not_the_average(sd):
    rows = [{"match_id": "x1", "set_id": SYNTH_SET_ID, "placement": 2, "final_board": board_b(0)},
            {"match_id": "x2", "set_id": SYNTH_SET_ID, "placement": None, "final_board": board_b(0)},
            {"match_id": "x3", "set_id": SYNTH_SET_ID, "placement": 4, "final_board": []}]
    cat = comps.build_catalogue(rows, sd)
    assert cat["skipped"]["no_board"] == 1
    (comp,) = cat["comps"]
    assert comp["games"] == 2 and comp["placed_games"] == 1
    assert comp["avg_placement"] == 2.0 and comp["top4_rate"] == 1.0


def test_set_filter_follows_the_set_data(sd):
    rows = synth_history()
    other = comps.SetData.from_cdragon(dict(SYNTH_DOC, _set=98))
    cat = comps.build_catalogue(rows, other)
    assert cat["games"] == 1 and cat["comps"][0]["match_ids"] == ["m-old"]


def test_assign_comp_matches_a_new_board_or_refuses(sd):
    cat = comps.build_catalogue(synth_history(), sd)
    got = comps.assign_comp(board_a(4), cat, sd)
    assert got["comp_id"] == cat["comps"][0]["comp_id"]
    assert got["label"] == "Mage / Blade - Gale"
    assert 0.5 <= got["similarity"] <= 1.0
    assert comps.assign_comp([u("U_Ira"), u("U_Echo")], cat, sd) is None


def test_catalogue_is_json_and_ascii(sd):
    blob = json.dumps(comps.build_catalogue(synth_history(), sd))
    assert blob.isascii()


def test_as_int_never_raises():
    cases = ["--5", chr(0xB2), float("inf"), float("-inf"), float("nan"), "12", "-3", " 7 ", True, None, 3.9, [1]]
    assert [comps.as_int(v) for v in cases] == [None, None, None, None, None, 12, -3, 7, None, None, 3, None]


def test_envelope_rejects_nan_confidence():
    assert comps.envelope_value({"gold": 5, "gold_conf": float("nan")}, "gold") is None
    assert comps.envelope_value({"gold": 5, "gold_conf": "high"}, "gold") is None
    assert comps.envelope_value({"gold": 5, "gold_conf": 0.9, "gold_src": "ocr"}, "gold") == 5
    assert comps.row_is_evidence({"conf": float("nan")}) is False


def test_malformed_records_never_stop_the_catalogue(sd):
    junk = [
        {"match_id": "j1", "set_id": SYNTH_SET_ID, "placement": "--3", "final_board": board_a(0)},
        {"match_id": "j2", "set_id": SYNTH_SET_ID, "queue_kind": ["double_up"], "final_board": board_a(1)},
        {"match_id": "j3", "set_id": SYNTH_SET_ID, 1: "mixed keys", "augments": "A_Rich", "final_board": board_a(2)},
        {"match_id": "j4", "set_id": SYNTH_SET_ID, "final_board": "junk"},
        {"match_id": "j5", "set_id": SYNTH_SET_ID, "placement": float("inf"),
         "final_board": [None, 7, {"champion_api": "U_Gale", "star": "x", "items_json": "{bad"}] + board_a(0)[1:]},
        None, "not a record", 42,
    ]
    cat = comps.build_catalogue(junk, sd)
    assert cat["games"] == 4 and cat["skipped"]["no_board"] == 1
    (comp,) = cat["comps"]
    assert comp["placed_games"] == 0 and comp["augments"] == []
    again = comps.build_catalogue(list(reversed(junk)), sd)
    assert json.dumps(again, sort_keys=True) == json.dumps(cat, sort_keys=True)


def test_duplicate_match_ids_resolve_by_content_not_list_order(sd):
    first = {"match_id": "dup", "set_id": SYNTH_SET_ID, "placement": 1, "final_board": board_a(0)}
    second = {"match_id": "dup", "set_id": SYNTH_SET_ID, "placement": 7, "final_board": board_a(0)}
    flipped = dict(second, final_board=list(reversed(board_a(0))))
    a = comps.build_catalogue([first, second], sd)
    b = comps.build_catalogue([flipped, first], sd)
    assert a["games"] == 1
    assert a["comps"][0]["avg_placement"] == b["comps"][0]["avg_placement"]
    assert comps.canonical({"x": [1, 2], "y": {"b": 1, 2: "a"}}) == comps.canonical({"y": {"b": 1, "2": "a"}, "x": [2, 1]})


def test_assign_comp_skips_malformed_catalogue_rows(sd):
    cat = comps.build_catalogue(synth_history(), sd)
    broken = dict(cat, comps=[{"label": "no id"}, "junk", {"comp_id": 5}] + cat["comps"])
    assert comps.assign_comp(board_a(4), broken, sd)["comp_id"] == cat["comps"][0]["comp_id"]
    assert comps.assign_comp(board_a(4), {"comps": [{"label": "no id"}]}, sd) is None


def test_worked_example_catalogue_on_real_set18_data(s18):
    cat = comps.build_catalogue([worked_example_record()], s18)
    (comp,) = cat["comps"]
    assert comp["games"] == 1 and comp["top4_rate"] == 1.0 and comp["avg_placement"] == 1.0
    assert comp["carry"]["api"] == "DA_Draven18"
    assert comp["label"] == "Blossom / Spellweaver - Draven"
    assert len(comp["core"]) == 9
    names = {c["name"] for c in comp["core"]}
    assert {"Draven", "Taric", "Aphelios", "Yunara"} <= names
