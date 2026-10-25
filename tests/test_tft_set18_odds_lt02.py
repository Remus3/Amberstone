"""LT-02 (session 134): Set 18 shop odds, pinned from the LIVE client HUD.

EVIDENCE
--------
The shop odds bar (1/2/3/4/5-cost) of a live Set 18 normal game, read off the
frames of ops/runtime/tft_qa/20261025-070350 (QA_REPORT.md section 3; the L6,
L7, L8 and L9 crops were re-read for this slice). Each row was identical in
every frame at that level where the bar was visible.

Cross-checks (facts only, nothing vendored):
- CommunityDragon game data, map22 TFTSet18 DropRateTables "Shop" (content
  16.21, file dated 2026-10-21): equal to the HUD at L4, L5, L6, L8 and L9;
  at L7 it says 19/30/40/10/1 while the HUD shows 16/30/43/10/1. The live
  client wins (the source of truth is the in-client display); the game-data
  row is recorded here. The same game-data table serves Set 17.
- One third-party aggregator table: equal to the HUD at L4-L9, L7 included.

Not read in client: L1-L3 and L10-L11 (before capture / never reached) and
the pool sizes (the HUD does not show them). Those rows come from the game
data and stay unpinned, so the whole-module CONSTANTS_SET_VERIFIED stays
False; TIER_ODDS_VERIFIED_LEVELS is the per-level pin.

Names used, cited at the fix tree: tft/tft_data.py `CONSTANTS_SET`,
`CONSTANTS_SET_VERIFIED`, `TIER_ODDS`, `TIER_ODDS_SET14`, `TIER_ODDS_BY_SET`,
`TIER_ODDS_VERIFIED_LEVELS`, `tier_odds_for_set`, `POOL_SIZES`,
`POOL_SIZES_FROM_SET`, `UNITS_PER_COST`; tft/tft_pbe_data.py `TIER_ODDS`,
`CONSTANTS_SET`; tft/tft_roll_odds.py `default_constants`; tft/tft_set.py
`resolve_set`.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tft import tft_data
from tft import tft_pbe_data as pbe
from tft import tft_roll_odds as ro
from tft import tft_set

REPO_ROOT = Path(__file__).resolve().parent.parent

# level -> (1, 2, 3, 4, 5-cost percent), frame it was read from.
HUD = {
    4: ((55, 30, 15, 0, 0), "game_0001_el0269"),
    5: ((45, 33, 20, 2, 0), "game_0007_el0409"),
    6: ((30, 40, 25, 5, 0), "game_0015_el0599"),
    7: ((16, 30, 43, 10, 1), "game_0031_el0944"),
    8: ((15, 20, 32, 30, 3), "game_0041_el1164"),
    9: ((10, 17, 25, 33, 15), "game_0065_el1709"),
}
# Game-data rows for the levels the HUD did not show (CommunityDragon).
GAME_DATA_ONLY = {
    1: (100, 0, 0, 0, 0), 2: (100, 0, 0, 0, 0), 3: (75, 25, 0, 0, 0),
    10: (5, 10, 20, 40, 25), 11: (1, 2, 12, 50, 35),
}
GAME_DATA_L7 = (19, 30, 40, 10, 1)


@pytest.fixture(autouse=True)
def _isolated_resolver(monkeypatch):
    monkeypatch.delenv(tft_set.ENV_PIN, raising=False)
    tft_set.clear_live_set()
    yield
    tft_set.clear_live_set()


def _pct(row) -> tuple:
    return tuple(round(row[c] * 100) for c in (1, 2, 3, 4, 5))


@pytest.mark.parametrize("level", sorted(HUD))
def test_set18_tier_odds_equal_the_live_hud(level):
    want, frame = HUD[level]
    assert _pct(tft_data.TIER_ODDS[level]) == want, frame


def test_the_live_l7_row_wins_over_the_game_data_row():
    assert _pct(tft_data.TIER_ODDS[7]) == HUD[7][0] != GAME_DATA_L7


@pytest.mark.parametrize("level", sorted(GAME_DATA_ONLY))
def test_rows_not_seen_in_client_come_from_the_game_data(level):
    assert _pct(tft_data.TIER_ODDS[level]) == GAME_DATA_ONLY[level]


def test_table_covers_levels_1_to_11_and_every_row_sums_to_one():
    assert sorted(tft_data.TIER_ODDS) == list(range(1, 12))
    for lv, row in tft_data.TIER_ODDS.items():
        assert sorted(row) == [1, 2, 3, 4, 5], lv
        assert abs(sum(row.values()) - 1.0) < 1e-9, lv


def test_per_level_pin_is_exactly_the_hud_levels():
    assert tft_data.TIER_ODDS_VERIFIED_LEVELS == frozenset(HUD)
    assert tft_data.TIER_ODDS_VERIFIED_LEVELS < frozenset(tft_data.TIER_ODDS)


def test_whole_module_pin_stays_false_until_pools_and_all_levels_are_read():
    assert tft_data.CONSTANTS_SET_VERIFIED is False
    assert pbe.CONSTANTS_SET_VERIFIED is False


def test_module_declares_set18_the_lane_set():
    assert tft_data.CONSTANTS_SET == 18
    assert tft_set.resolve_set() == 18  # committed tree: newest ingested


def test_pool_sizes_are_a_set14_carryover_not_set18():
    assert tft_data.POOL_SIZES_FROM_SET == 14 != tft_data.CONSTANTS_SET
    assert tft_data.POOL_SIZES == {1: 29, 2: 22, 3: 18, 4: 12, 5: 10}
    assert tft_data.UNITS_PER_COST == {1: 13, 2: 13, 3: 13, 4: 12, 5: 8}


def test_set14_table_is_kept_intact():
    old = tft_data.TIER_ODDS_SET14
    assert sorted(old) == list(range(1, 11))
    assert _pct(old[7]) == (22, 30, 33, 15, 0)
    assert _pct(old[10]) == (5, 10, 20, 35, 30)
    assert old == pbe.TIER_ODDS  # the Set 17 module still carries the copy


def test_odds_are_routed_by_set_key():
    assert tft_data.TIER_ODDS_BY_SET[18] is tft_data.TIER_ODDS
    assert tft_data.TIER_ODDS_BY_SET[14] is tft_data.TIER_ODDS_SET14
    assert tft_data.tier_odds_for_set(18) is tft_data.TIER_ODDS
    assert tft_data.tier_odds_for_set(14) is tft_data.TIER_ODDS_SET14
    assert tft_data.tier_odds_for_set(pbe.CONSTANTS_SET) is pbe.TIER_ODDS
    assert tft_data.tier_odds_for_set(19) is None
    assert tft_data.tier_odds_for_set() is tft_data.TIER_ODDS  # resolver: 18


def test_roll_odds_default_bundle_reads_the_set18_rows():
    d = ro.default_constants()
    assert d.set_number == 18
    assert _pct(d.tier_odds[7]) == HUD[7][0]
    assert d.verified_in_client is False
