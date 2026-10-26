"""s134 true-audit (lane 8, cycle 19): tft/engine/compare.py.

compare.py reads every board through comps.as_units, which hands a comps.Unit
instance back unchecked (only a raw row goes through normalize_unit's
clamping). Each site below was measured at HEAD before the fix:

  F1 a Unit with star None / NaN raised out of board_power (copies(int(star)));
     a star past MAX_STAR was not clamped, so star 200000 built a 95000-digit
     star_cost that json.dumps / str refuse.
  F2 a Unit cost that is not an int ("x", True) raised TypeError or counted as
     a price; a negative cost (a Unit's own, or the set data's) made a negative
     gold value: cost -3 at 2 stars gave star_cost -9.
  F3 a Unit items value that is not a list raised (None) or was read per
     character ("C_Bow" counted as five completed items).
  F4 a Unit with a junk api (None, an int) counted as a unit, and a mix of a
     str api and an int api raised TypeError out of the contested sort or
     out of as_units' board sort.
  F5 compare_lobby raised ValueError on an int player key too long to print
     in decimal, and returned non-text player keys that json.dumps refuses.
  F6 board_power truth-tested the board (`board or []`), which raises on a
     sequence whose truth value is undefined.
  F7 compare_lobby normalised the own board again for every opponent, and
     compare_boards normalised each board twice (power, then contested).
"""
from __future__ import annotations

import json

import pytest

from tests.test_tft_engine_synthetic import SYNTH_DOC, u
from tft.engine import comps, compare
from tft.engine.comps import MAX_STAR, Unit


@pytest.fixture(scope="module")
def sd():
    return comps.SetData.from_cdragon(SYNTH_DOC)


# ------------------------------------------------------------- F1 star


@pytest.mark.parametrize("star", [None, float("nan"), float("inf"), "x", True])
def test_junk_star_on_a_hand_built_unit_counts_as_one_star(sd, star):
    p = compare.board_power((Unit("U_Gale", star, (), 4),), sd)
    assert p["star_cost"] == 4


def test_star_past_max_star_is_clamped(sd):
    p = compare.board_power((Unit("U_Gale", 200000, (), 4),), sd)
    assert p["star_cost"] == 4 * 3 ** (MAX_STAR - 1)
    json.dumps(p)


def test_digit_string_star_is_read_like_a_raw_row(sd):
    assert compare.board_power((Unit("U_Gale", "2", (), 4),), sd)["star_cost"] == 12


# ------------------------------------------------------------- F2 cost


@pytest.mark.parametrize("cost", ["x", True, -3, None, float("nan")])
def test_junk_or_negative_unit_cost_falls_back_to_the_set_data(sd, cost):
    # U_Gale costs 4 in the set data; at 2 stars that is 12
    assert compare.board_power((Unit("U_Gale", 2, (), cost),), sd)["star_cost"] == 12


def test_negative_set_data_cost_is_no_gold_value():
    doc = dict(SYNTH_DOC)
    doc["units"] = [dict(r, cost=-5) if r.get("apiName") == "U_Gale" else r for r in SYNTH_DOC["units"]]
    sdn = comps.SetData.from_cdragon(doc)
    assert compare.board_power([u("U_Gale", 2)], sdn)["star_cost"] == 0
    assert compare.board_power((Unit("U_Gale", 2, (), None),), sdn)["star_cost"] == 0


# ------------------------------------------------------------- F3 items


def test_items_that_are_not_a_list_count_nothing(sd):
    p = compare.board_power((Unit("U_Gale", 1, None, 4),), sd)
    assert p["completed_items"] == 0 and p["components"] == 0
    p = compare.board_power((Unit("U_Gale", 1, "C_Bow", 4),), sd)
    assert p["completed_items"] == 0 and p["components"] == 0


def test_non_text_item_entries_are_skipped(sd):
    p = compare.board_power((Unit("U_Gale", 1, ("I_Rage", None, 7, "", "C_Bow"), 4),), sd)
    assert p["completed_items"] == 1 and p["components"] == 1


# ------------------------------------------------------------- F4 api


def test_junk_api_units_are_not_units(sd):
    p = compare.board_power((Unit(None, 1, (), 4), Unit("  ", 1, (), 4), Unit("U_Gale", 1, (), 4)), sd)
    assert p["units"] == 1 and p["star_cost"] == 4


def test_mixed_api_types_never_raise(sd):
    own = (Unit(5, 1, (), 4), Unit("U_Gale", 1, (), 4))
    other = [Unit(5, 1, (), 4), u("U_Gale"), Unit(None, None, None, None)]
    c = compare.compare_boards(own, other, sd)
    assert c["contested"] == ["U_Gale"]
    assert c["own"]["units"] == 1 and c["other"]["units"] == 1
    json.dumps(c)


# ------------------------------------------------------------- F5 lobby keys


def test_lobby_huge_int_key_never_raises_and_every_player_key_is_text(sd):
    rows = compare.compare_lobby([u("U_Gale")], {10 ** 5000: [u("U_Ace")], 3: [u("U_Jinx", 2)], "P1": []}, sd)
    assert [type(r["player_key"]) for r in rows] == [str, str, str]
    assert rows[0]["player_key"] == "3"
    assert rows[1]["player_key"].startswith("int:0x")
    json.dumps(rows)


def test_plain_list_keys_are_unchanged(sd):
    rows = compare.compare_lobby([u("U_Gale")], [[u("U_Ace")], [u("U_Jinx", 2)]], sd)
    assert [r["player_key"] for r in rows] == ["1", "0"]


# ------------------------------------------------------------- F6 truth test


class _NoTruth(list):
    def __bool__(self):
        raise ValueError("the truth value of this board is ambiguous")


def test_board_is_never_truth_tested(sd):
    assert compare.board_power(_NoTruth([u("U_Gale"), u("U_Cora")]), sd)["units"] == 2
    assert compare.compare_boards(_NoTruth([u("U_Gale")]), _NoTruth([u("U_Gale")]), sd)["contested"] == ["U_Gale"]


@pytest.mark.parametrize("board", [None, "U_Gale", 5, {"U_Gale": 1}])
def test_a_board_that_is_not_a_list_is_empty(sd, board):
    assert compare.board_power(board, sd)["units"] == 0


# ------------------------------------------------------------- F7 normalise once


def test_each_raw_row_is_normalised_once(sd, monkeypatch):
    seen = []
    real = comps.normalize_unit

    def counting(raw, setdata):
        if not isinstance(raw, Unit):
            seen.append(raw["champion_api"])
        return real(raw, setdata)

    monkeypatch.setattr(compare, "normalize_unit", counting)
    others = {f"P{i}": [u("U_Ace")] for i in range(7)}
    rows = compare.compare_lobby([u("U_Gale")], others, sd)
    assert len(rows) == 7
    assert seen.count("U_Gale") == 1
    assert seen.count("U_Ace") == 7
