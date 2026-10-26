"""s134 true-audit (lane 8, cycle 15): tft/engine/comps.py.

comps.py is the engine's input boundary: it reads the CommunityDragon set
extract (SetData.from_cdragon), every measured unit-row shape (normalize_unit)
and the match records dashboard/routes_tft.py build_engine_model assembles from
the round store and the RM-616 placement files. Its own header and its helpers
promise junk tolerance ("never raises"); these tests pin the sites that broke
that promise, each measured at HEAD before the fix:

  F1 as_int raised ValueError on a digit string past Python's int-string
     limit (RM-937), which reaches placement_of, parse_label and mine_match.
  F2 _conf_ok raised OverflowError on an int confidence too large for a float,
     so envelope_value / row_is_evidence raised.
  F3 from_cdragon raised TypeError when a list field (units, traits, items,
     augments, a unit's traits, a trait's breakpoints, an item's composition)
     was a scalar, and iterated a STRING list field per character: traits
     "Mage" became four one-letter traits, composition "ab" a recipe.
  F4 a set id tft_set.parse_set_id cannot convert ("\\u00b2", 5000 digits)
     raised out of from_cdragon and out of build_catalogue for one record.
  F5 canonical / record_id raised on an int too long to print in decimal, so
     one such value anywhere in one record took the whole catalogue down; a
     set inside a record printed in hash-seed order; match_id True became the
     id "True".
  F6 a deeply nested items_json raised RecursionError out of normalize_unit,
     and items_json had no size bound.
  F7 build_catalogue / ordered_records raised on a non-iterable records value.
  F8 assign_comp raised on a non-list "comps" or "signature" and iterated a
     string signature per character.
  F9 placement_of truncated a non-integral placement (4.9 -> 4, a top-4).
  F10 a negative raw cost overrode the set data's cost.
  F11 an augment with an empty name displayed as "" (every other name field
     falls back to the apiName).
"""
from __future__ import annotations

import pytest

from tests.test_tft_engine_synthetic import SYNTH_DOC, SYNTH_SET_ID, board_a, synth_history, u
from tft.engine import comps

HUGE_DIGITS = "9" * 5000


@pytest.fixture(scope="module")
def sd():
    return comps.SetData.from_cdragon(SYNTH_DOC)


def _good(mid="good"):
    return {"match_id": mid, "set_id": SYNTH_SET_ID, "placement": 2, "final_board": board_a(0)}


# ------------------------------------------------------------------ F1

@pytest.mark.parametrize("value", [HUGE_DIGITS, "-" + HUGE_DIGITS, " " + HUGE_DIGITS + " "],
                         ids=["huge", "neg-huge", "padded-huge"])
def test_f1_as_int_huge_digit_string_is_none(value):
    assert comps.as_int(value) is None


def test_f1_as_int_still_parses_ordinary_strings():
    assert comps.as_int("12") == 12 and comps.as_int("-3") == -3 and comps.as_int(" 7 ") == 7


def test_f1_placement_of_huge_digit_string_is_none():
    assert comps.placement_of({"placement": HUGE_DIGITS}) is None


# ------------------------------------------------------------------ F2

def test_f2_envelope_value_huge_int_confidence_is_not_evidence():
    assert comps.envelope_value({"gold": 5, "gold_conf": 10 ** 400}, "gold") is None


def test_f2_row_is_evidence_huge_int_confidence_is_false():
    assert comps.row_is_evidence({"conf": 10 ** 400}) is False


def test_f2_ordinary_confidence_still_counts():
    assert comps.envelope_value({"gold": 5, "gold_conf": 1}, "gold") == 5
    assert comps.row_is_evidence({"conf": 0.9}) is True


# ------------------------------------------------------------------ F3

@pytest.mark.parametrize("key", ["units", "traits", "items", "augments"])
@pytest.mark.parametrize("junk", [5, True, 1.5])
def test_f3_from_cdragon_scalar_top_level_field_reads_as_empty(key, junk):
    data = comps.SetData.from_cdragon(dict(SYNTH_DOC, **{key: junk}))
    assert data.set_id == SYNTH_SET_ID
    assert {"units": data.units, "traits": data.trait_breakpoints,
            "items": data.item_names, "augments": data.augment_names}[key] == {}


@pytest.mark.parametrize("junk", [7, "Mage", "M"])
def test_f3_unit_traits_must_be_a_list(junk):
    doc = {"units": [{"apiName": "U_X", "name": "X", "cost": 1, "traits": junk},
                     {"apiName": "U_Y", "name": "Y", "cost": 2, "traits": ["Mage"]}]}
    data = comps.SetData.from_cdragon(doc)
    assert data.units["U_X"].traits == ()
    assert data.units["U_Y"].traits == ("Mage",)


@pytest.mark.parametrize("junk", [3, "24"])
def test_f3_trait_breakpoints_must_be_a_list(junk):
    doc = {"traits": [{"name": "T", "breakpoints": junk}, {"name": "S", "breakpoints": (2, 4)}]}
    data = comps.SetData.from_cdragon(doc)
    assert data.trait_breakpoints["T"] == ()
    assert data.trait_breakpoints["S"] == (2, 4)


@pytest.mark.parametrize("junk", [1, "ab"])
def test_f3_item_composition_must_be_a_list(junk):
    doc = {"items": [{"apiName": "I_J", "name": "J", "composition": junk},
                     {"apiName": "I_K", "name": "K", "composition": ("C_A", "C_B")}]}
    data = comps.SetData.from_cdragon(doc)
    assert "I_J" not in data.recipes
    assert data.recipes["I_K"] == ("C_A", "C_B")
    assert data.components == frozenset({"C_A", "C_B"})


# ------------------------------------------------------------------ F4

@pytest.mark.parametrize("junk", [chr(0xB2), HUGE_DIGITS], ids=["superscript-two", "huge"])
def test_f4_from_cdragon_unparseable_set_id_is_none(junk):
    assert comps.SetData.from_cdragon(dict(SYNTH_DOC, _set=junk)).set_id is None


@pytest.mark.parametrize("junk", [chr(0xB2), HUGE_DIGITS], ids=["superscript-two", "huge"])
def test_f4_one_unparseable_record_set_id_never_stops_the_catalogue(sd, junk):
    bad = {"match_id": "bad", "set_id": junk, "final_board": board_a(1)}
    cat = comps.build_catalogue([bad, _good()], sd)
    assert cat["games"] == 1 and cat["skipped"]["other_set"] == 1
    assert cat["assignments"].keys() == {"good"}


# ------------------------------------------------------------------ F5

def test_f5_one_huge_int_inside_a_record_never_stops_the_catalogue(sd):
    bad = dict(_good("bad"), rounds=[{"gold": 10 ** 5000}])
    cat = comps.build_catalogue([bad, _good()], sd)
    assert cat["games"] == 2 and set(cat["assignments"]) == {"bad", "good"}


def test_f5_canonical_huge_int_is_text_and_distinct():
    a = comps.canonical({"x": 10 ** 5000})
    assert isinstance(a, str)
    assert a == comps.canonical({"x": 10 ** 5000})
    assert a != comps.canonical({"x": 10 ** 5000 + 1})


def test_f5_canonical_ordinary_ints_unchanged():
    assert comps.canonical({"x": [3, 1, 2]}) == '{"x": [1, 2, 3]}'
    assert comps.canonical({2: "a", True: "b"}) == '{"2": "a", "True": "b"}'


def test_f5_canonical_huge_int_key_never_raises():
    text = comps.canonical({10 ** 5000: "a"})
    assert isinstance(text, str) and "int:0x" in text


def test_f5_canonical_set_reads_like_the_sorted_list():
    assert comps.canonical({"a": {"x", "y", "z"}}) == comps.canonical({"a": ["z", "y", "x"]})
    assert comps.canonical({"a": frozenset({"q", "p"})}) == comps.canonical({"a": ["p", "q"]})


def test_f5_record_id_huge_int_match_id_never_raises():
    rid = comps.record_id({"match_id": 10 ** 5000})
    assert isinstance(rid, str) and rid.startswith("anon-")


def test_f5_record_id_bool_match_id_is_not_an_id():
    assert comps.record_id({"match_id": True}).startswith("anon-")
    assert comps.record_id({"match_id": 42}) == "42"
    assert comps.record_id({"match_id": "m-1"}) == "m-1"


# ------------------------------------------------------------------ F6

def test_f6_deeply_nested_items_json_never_raises(sd):
    unit = comps.normalize_unit({"champion_api": "U_Gale", "items_json": "[" * 200000}, sd)
    assert unit is not None and unit.items == () and unit.api == "U_Gale"


def test_f6_deeply_nested_items_json_under_the_size_cap_never_raises(sd):
    raw = {"champion_api": "U_Gale", "items_json": "[" * (comps.ITEMS_JSON_MAX_CHARS - 1)}
    assert comps.normalize_unit(raw, sd).items == ()


def test_f6_oversized_items_json_is_ignored(sd):
    raw = {"champion_api": "U_Gale", "items_json": '["I_Edge"]' + " " * (comps.ITEMS_JSON_MAX_CHARS + 1)}
    assert comps.normalize_unit(raw, sd).items == ()


def test_f6_ordinary_items_json_still_reads(sd):
    unit = comps.normalize_unit({"champion_api": "U_Gale", "items_json": '["I_Edge", "Rage"]'}, sd)
    assert unit.items == ("I_Edge", "I_Rage")


# ------------------------------------------------------------------ F7

@pytest.mark.parametrize("junk", [5, 1.5, True, "records", {"match_id": "m"}])
def test_f7_non_list_records_read_as_none(sd, junk):
    assert comps.ordered_records(junk) == []
    assert comps.build_catalogue(junk, sd)["games"] == 0


def test_f7_a_generator_of_records_still_reads(sd):
    cat = comps.build_catalogue((r for r in synth_history()), sd)
    assert cat["games"] == comps.build_catalogue(synth_history(), sd)["games"] > 0


# ------------------------------------------------------------------ F8

@pytest.mark.parametrize("junk", [5, True, "comps"])
def test_f8_assign_comp_non_list_comps_is_none(sd, junk):
    assert comps.assign_comp(board_a(0), {"comps": junk}, sd) is None


def test_f8_assign_comp_scalar_signature_never_raises(sd):
    cat = comps.build_catalogue(synth_history(), sd)
    broken = dict(cat, comps=[dict(c, signature=5) for c in cat["comps"]])
    got = comps.assign_comp(board_a(0), broken, sd)
    assert got is None or got["comp_id"] == cat["comps"][0]["comp_id"]


def test_f8_assign_comp_string_signature_is_not_per_character():
    doc = {"_set": 7, "units": [{"apiName": "U_P", "name": "P", "cost": 1, "traits": ["M"]},
                                {"apiName": "U_Q", "name": "Q", "cost": 1, "traits": ["M"]}],
           "traits": [{"name": "M", "breakpoints": [2, 4]}]}
    data = comps.SetData.from_cdragon(doc)
    board = [u("U_P"), u("U_Q")]
    assert comps.trait_signature(board, data) == frozenset({"M"})
    as_list = {"comps": [{"comp_id": "c-1", "core": [{"api": "U_P"}], "signature": ["M"]}]}
    as_text = {"comps": [{"comp_id": "c-1", "core": [{"api": "U_P"}], "signature": "M"}]}
    assert comps.assign_comp(board, as_list, data)["similarity"] == 0.75
    assert comps.assign_comp(board, as_text, data) is None


# ------------------------------------------------------------------ F9

@pytest.mark.parametrize("value", [4.9, 3.5, 0.5])
def test_f9_non_integral_placement_is_none(value):
    assert comps.placement_of({"placement": value}) is None


@pytest.mark.parametrize("value, want", [(4.0, 4), ("4", 4), (1, 1), (8, 8), (9, None), (0, None)])
def test_f9_integral_placement_still_reads(value, want):
    assert comps.placement_of({"placement": value}) == want


# ------------------------------------------------------------------ F10

@pytest.mark.parametrize("key", ["cost", "price"])
def test_f10_negative_raw_cost_falls_back_to_set_data(sd, key):
    unit = comps.normalize_unit({"champion_api": "U_Gale", key: -5}, sd)
    assert unit.cost == 4


def test_f10_zero_and_positive_raw_cost_still_win(sd):
    assert comps.normalize_unit({"champion_api": "U_Gale", "cost": 0}, sd).cost == 0
    assert comps.normalize_unit({"champion_api": "U_Gale", "price": 6}, sd).cost == 6


# ------------------------------------------------------------------ F11

def test_f11_empty_augment_name_falls_back_to_api():
    data = comps.SetData.from_cdragon({"augments": [{"apiName": "A_X", "name": ""},
                                                    {"apiName": "A_Y", "name": 5},
                                                    {"apiName": "A_Z", "name": "Zed"}]})
    assert data.augment_names == {"A_X": "A_X", "A_Y": "A_Y", "A_Z": "Zed"}
