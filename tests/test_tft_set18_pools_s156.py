"""Session 156 (S6): Set 18 champion pools from the game's own shop data, and
the coach saying "unverified" for every roll-odds / XP figure the client was
not read for.

EVIDENCE
--------
CommunityDragon `<patch>/game/data/maps/shipping/map22/map22.bin.json` (the
game's own data file, the mirror RM-840 already credits in NOTICE), fetched
for 16.21 and 16.22 on 2026-11-08 and compared: the Set 18 `ShopContentData`
TierBags (the champion pool: one bag per cost, each entry a shop unit and its
`Count` of copies), the "Shop" DropRateTable and the StageRoundData are
byte-equal across the two patches. TierBags 1..5: 14 / 13 / 14 / 14 / 10 units
with 30 / 25 / 18 / 10 / 9 copies each. Every one of the 65 bag units is in
the committed extract (data/meta/tft_set18_cdragon.json) at the SAME cost (the
nine extract units not in a bag are the Lux variants), and the per-cost counts
equal the LT-03 live team-planner roster candidate in
tools/gated_tft_lt02r.py. No third-party table is used.

A game-data file is NOT the in-client display: at L7 the 16.21 / 16.22 drop
table says 19/30/40/10/1 while the live HUD shows 16/30/43/10/1 (LT-02). So
pools sourced here are "game data, not read in client" and the whole-module
CONSTANTS_SET_VERIFIED stays False.

Names used, cited at the fix tree: tft/tft_data.py `POOL_SIZES`,
`POOL_SIZES_SET14`, `POOL_SIZES_FROM_SET`, `POOL_SIZES_SOURCE`,
`UNITS_PER_COST`, `UNITS_PER_COST_SET14`, `CONSTANTS_SET`,
`CONSTANTS_SET_VERIFIED`, `TIER_ODDS_VERIFIED_LEVELS`, `odds_level_verified`,
`xp_table_verified`; tft/tft_roll_odds.py `default_constants`,
`remaining_pool`; tft/tft_coach_engine.py `_build_prompt`; tft/tft_set.py
`ENV_PIN`, `clear_live_set`, `comp_state`.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tft import tft_data
from tft import tft_roll_odds as ro
from tft import tft_set

REPO_ROOT = Path(__file__).resolve().parent.parent

# Set 18 TierBags at map22 16.21 == 16.22 (apiName of each ShopData entry).
BAGS = {
    1: ["DA_18_Akali_AD", "DA_18_Camille", "DA_18_Kobuko", "DA_18_Leona", "DA_18_Ornn",
        "DA_18_Rakan", "DA_18_RekSai", "DA_18_Sentry", "DA_18_Varus", "DA_18_Veigar",
        "DA_18_Xayah", "DA_18_Yorick", "DA_Cinderling18", "DA_Karma18"],
    2: ["DA_18_Alistar", "DA_18_Caitlyn", "DA_18_Elise", "DA_18_Kayle", "DA_18_LeBlanc",
        "DA_18_Sejuani", "DA_18_Shen", "DA_18_Teemo", "DA_18_Warwick", "DA_18_Yunara",
        "DA_Gromp18_AP", "DA_Murkwolf18", "DA_Scuttlecrab18"],
    3: ["DA_18_Azir", "DA_18_Cassiopeia", "DA_18_Diana", "DA_18_Hecarim", "DA_18_KhaZix",
        "DA_18_MasterYi_AD", "DA_18_Rammus", "DA_18_Rengar", "DA_18_Tristana",
        "DA_CrimsonRaptor18", "DA_Fiddlesticks18", "DA_KogMaw18_AD", "DA_Krug18", "DA_Vi18"],
    4: ["DA_18_Ahri", "DA_18_Aphelios", "DA_18_Ezreal", "DA_18_Lillia", "DA_18_Malphite",
        "DA_18_Morgana", "DA_18_Sett", "DA_18_Sivir", "DA_18_Soraka", "DA_18_Zyra",
        "DA_Amumu18", "DA_Brambleback18", "DA_Nidalee18_AP", "DA_Sentinel18"],
    5: ["DA_18_Alune", "DA_18_Ashe", "DA_18_ElderDragon", "DA_18_GnarSmall", "DA_18_Ivern",
        "DA_18_Kennen", "DA_18_Maokai", "DA_Draven18", "DA_Lux18_Base", "DA_Taric18"],
}
COPIES = {1: 30, 2: 25, 3: 18, 4: 10, 5: 9}


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    monkeypatch.delenv(tft_set.ENV_PIN, raising=False)
    monkeypatch.setattr(tft_set, "comp_state", lambda root=None: {})
    tft_set.clear_live_set()
    yield
    tft_set.clear_live_set()


# -- the pool constants --------------------------------------------------------

def test_set18_pool_sizes_and_units_are_the_game_data_values():
    assert tft_data.POOL_SIZES == COPIES
    assert tft_data.UNITS_PER_COST == {c: len(v) for c, v in BAGS.items()}
    assert tft_data.UNITS_PER_COST == {1: 14, 2: 13, 3: 14, 4: 14, 5: 10}


def test_pool_constants_declare_set18_and_cite_the_source():
    assert tft_data.POOL_SIZES_FROM_SET == tft_data.CONSTANTS_SET == 18
    src = tft_data.POOL_SIZES_SOURCE
    assert "ShopContentData" in src and "16.22" in src and "not read in client" in src


def test_the_set14_pool_tables_are_kept_intact_not_borrowed():
    assert tft_data.POOL_SIZES_SET14 == {1: 29, 2: 22, 3: 18, 4: 12, 5: 10}
    assert tft_data.UNITS_PER_COST_SET14 == {1: 13, 2: 13, 3: 13, 4: 12, 5: 8}
    assert tft_data.POOL_SIZES != tft_data.POOL_SIZES_SET14


def test_whole_module_pin_stays_false_because_game_data_is_not_the_client():
    assert tft_data.CONSTANTS_SET_VERIFIED is False


def test_every_bag_unit_is_in_the_extract_at_the_same_cost():
    ex = json.loads((REPO_ROOT / "data" / "meta" / "tft_set18_cdragon.json").read_text("utf-8"))
    cost = {u["apiName"]: u["cost"] for u in ex["units"]}
    for c, apis in BAGS.items():
        for api in apis:
            assert cost.get(api) == c, api
    assert sum(len(v) for v in BAGS.values()) == 65


def test_total_copies_per_cost_flow_through_the_roll_odds_math():
    d = ro.default_constants()
    assert d.set_number == 18 and d.complete
    for cost, per_unit in COPIES.items():
        total = per_unit * len(BAGS[cost])
        assert ro.remaining_pool(cost, consts=d) == (per_unit, total), cost


# -- the verified-level helpers --------------------------------------------------

def test_odds_levels_are_verified_only_for_the_hud_levels_of_set18():
    for level in range(1, 12):
        assert tft_data.odds_level_verified(level, 18) is (level in range(4, 10)), level
    assert tft_data.odds_level_verified(7, 17) is False
    assert tft_data.odds_level_verified(7, 14) is False
    assert tft_data.odds_level_verified(7, 19) is False
    assert tft_data.odds_level_verified(True, 18) is False


def test_only_set18_xp_is_client_measured():
    assert tft_data.xp_table_verified(18) is True
    for n in (14, 17, 19, None):
        assert tft_data.xp_table_verified(n) is False


# -- the coach says "unverified" ---------------------------------------------------

def _prompt(level: int, monkeypatch, *, pin=None) -> str:
    from tft import tft_coach_engine as eng
    if pin is not None:
        monkeypatch.setenv(tft_set.ENV_PIN, str(pin))
    monkeypatch.setattr(eng, "_META_SECTION_CACHE", {})
    return eng._build_prompt({"stage": 4, "round": 2, "level": level})


def _odds_lines(msg: str) -> list:
    return [ln for ln in msg.splitlines() if ln.startswith("Roll odds at Lv")]


def test_client_read_levels_carry_no_unverified_tag(monkeypatch):
    lines = _odds_lines(_prompt(6, monkeypatch, pin=18))
    assert len(lines) == 2 and all("unverified" not in ln for ln in lines)


def test_unread_levels_are_tagged_game_data_only(monkeypatch):
    lines = _odds_lines(_prompt(9, monkeypatch, pin=18))  # Lv9 read, Lv10 not
    assert "unverified" not in lines[0]
    assert lines[1].startswith("Roll odds at Lv10:")
    assert "unverified" in lines[1] and "not read in client" in lines[1]


def test_a_set_with_no_client_read_tags_every_odds_and_xp_line(monkeypatch):
    msg = _prompt(7, monkeypatch, pin=17)
    odds = _odds_lines(msg)
    assert odds and all("unverified" in ln for ln in odds)
    xp = [ln for ln in msg.splitlines() if ln.startswith("XP to Lv")]
    assert xp and all("unverified" in ln for ln in xp)


def test_set18_xp_line_is_not_tagged(monkeypatch):
    xp = [ln for ln in _prompt(7, monkeypatch, pin=18).splitlines() if ln.startswith("XP to Lv")]
    assert xp and "unverified" not in xp[0]
