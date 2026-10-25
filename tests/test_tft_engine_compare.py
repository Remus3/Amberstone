"""TFT engine (slice TFT-13): board compare, category 17 of
docs/TFT_PROGRAM.md section 1.4 (tft/engine/compare.py).

Power = unit count, star-weighted cost (gold value: cost x 3^(star-1)),
completed items (anything that is not a loose component), active traits and
the sum of their tiers; plus the units both boards hold (contested).
"""
from __future__ import annotations

import json

import pytest

from tests.test_tft_engine_synthetic import SYNTH_DOC, WORKED_FINAL_BOARD, u
from tft.engine import ENGINE_NAME, comps, compare


@pytest.fixture(scope="module")
def sd():
    return comps.SetData.from_cdragon(SYNTH_DOC)


def test_board_power_counts_gold_value_items_and_traits(sd):
    board = [u("U_Gale", 2, ["I_Rage", "C_Bow"]), u("U_Cora", 1, ["I_BladeEmblem"]), u("U_Kite", 3)]
    p = compare.board_power(board, sd)
    assert p["units"] == 3
    assert p["star_cost"] == 4 * 3 + 2 * 1 + 2 * 9
    assert p["completed_items"] == 2          # Rage + the emblem; the loose Bow is not completed
    assert p["components"] == 1
    # Mage: Gale, Cora, Kite = 3 (tier 1); Blade: Gale, Cora = 2 (tier 1)
    assert p["active_traits"] == 2 and p["trait_tiers"] == 2
    assert p["top_traits"] == [{"trait": "Mage", "count": 3, "tier": 1}, {"trait": "Blade", "count": 2, "tier": 1}]


def test_compare_boards_reports_deltas_leads_and_contested(sd):
    own = [u("U_Gale", 2, ["I_Rage"]), u("U_Cora", 2), u("U_Bolt")]
    other = [u("U_Hex", 1), u("U_Cora", 1), u("U_Fang", 2, ["I_Plate", "I_Edge"])]
    c = compare.compare_boards(own, other, sd)
    assert c["engine"] == ENGINE_NAME
    assert c["contested"] == ["U_Cora"]
    assert c["delta"]["units"] == 0
    assert c["delta"]["star_cost"] == (12 + 6 + 1) - (4 + 2 + 9)
    assert c["delta"]["completed_items"] == -1
    # own: Mage 3 + Blade 2 active (2 tiers); other: Beast 2 only (1 tier)
    assert c["delta"]["trait_tiers"] == 1
    assert c["leads"] == {"own": ["star_cost", "trait_tiers"], "other": ["completed_items"], "even": ["units"]}


def test_compare_lobby_orders_opponents_by_strength(sd):
    own = [u("U_Gale")]
    others = {"P3": [u("U_Ace")], "P2": [u("U_Jinx", 2)], "P4": [u("U_Ace")]}
    rows = compare.compare_lobby(own, others, sd)
    assert [r["player_key"] for r in rows] == ["P2", "P3", "P4"]
    assert rows[0]["other"]["star_cost"] == 15
    json.dumps(rows)


def test_empty_boards_compare_cleanly(sd):
    c = compare.compare_boards([], [], sd)
    assert c["own"]["units"] == 0 and c["contested"] == []
    assert c["leads"]["even"] == ["units", "star_cost", "completed_items", "trait_tiers"]


def test_worked_final_board_power_on_real_set18():
    s18 = comps.load_set_data(18)
    if not s18.units:
        pytest.skip("Set 18 CommunityDragon extract not ingested")
    p = compare.board_power(WORKED_FINAL_BOARD, s18)
    assert p["units"] == 9
    assert p["star_cost"] == 3 * (5 + 5 + 4 + 3 + 3 + 2 + 2 + 1 + 1)
    assert p["completed_items"] == 16 and p["components"] == 0
    assert p["active_traits"] == 8
