"""
tft/tft_data.py
TFT Set data - units, traits, items, tier probabilities, carousel logic.
Set-agnostic structure: update UNITS / TRAITS / ITEMS dicts each set patch.
Roll odds: Set 18 (LT-02, in-client measured at L4-L9), the Set 14 table kept
beside it and routed by set key (tier_odds_for_set). XP to the next level:
Set 18 (S134, in-client measured at L4-L9) beside the Set 14 table, routed by
xp_to_next_level. Pool sizes and units per cost: Set 18 from the game's own
shop data (S156, POOL_SIZES_SOURCE), the Set 14 transcription kept beside
them. The Set 14 guide tables (rounds, tempo, items) were removed in S156
(see the note at the end of the file).
"""

# -- Set declaration ----------------------------------------------------------
# CONSTANTS_SET is the TFT set the roll-odds table TIER_ODDS was transcribed
# for. The set the rest of the TFT lane is actually running comes from
# tft/tft_set.py resolve_set() (RM-840; newest ingested set by default, Set 18
# at 2026-10-24). When these two disagree, TIER_ODDS is STALE.
# tests/test_tft_constants_staleness.py is the guard; it fails the moment this
# declaration, the lane's set, or the known discrepancies move without someone
# updating the expectation.
CONSTANTS_SET = 18
# True only once EVERY roll table below (all TIER_ODDS rows, POOL_SIZES,
# UNITS_PER_COST) was read off the IN-CLIENT display for CONSTANTS_SET.
# Third-party aggregator tables are NOT sufficient. Stays False: L1-L3,
# L10-L11 and the pool sizes were not read in client (LT-02, session 134).
CONSTANTS_SET_VERIFIED = False
# Per-level pin (LT-02): the TIER_ODDS rows read off the live Set 18 HUD odds
# bar (ops/runtime/tft_qa/20261025-070350 frames, QA_REPORT.md section 3) AND
# cross-checked against published data. Guard:
# tests/test_tft_set18_odds_lt02.py.
TIER_ODDS_VERIFIED_LEVELS = frozenset({4, 5, 6, 7, 8, 9})

# -- Tier probability tables (standard) --------------------------------------
# {player_level: {cost: probability}}
# Set 18. L4-L9: the live client HUD (each row identical in every frame at
# that level). Cross-checks: CommunityDragon game data (map22 TFTSet18
# DropRateTables "Shop", content 16.21) equals the HUD at L4-L6 and L8-L9 but
# says 19/30/40/10/1 at L7 - the live client wins and that row is recorded
# here only; one third-party aggregator table equals the HUD at L4-L9.
# L1-L3, L10, L11: that game-data table only (never seen in client).
TIER_ODDS = {
    1:  {1: 1.00, 2: 0.00, 3: 0.00, 4: 0.00, 5: 0.00},
    2:  {1: 1.00, 2: 0.00, 3: 0.00, 4: 0.00, 5: 0.00},
    3:  {1: 0.75, 2: 0.25, 3: 0.00, 4: 0.00, 5: 0.00},
    4:  {1: 0.55, 2: 0.30, 3: 0.15, 4: 0.00, 5: 0.00},
    5:  {1: 0.45, 2: 0.33, 3: 0.20, 4: 0.02, 5: 0.00},
    6:  {1: 0.30, 2: 0.40, 3: 0.25, 4: 0.05, 5: 0.00},
    7:  {1: 0.16, 2: 0.30, 3: 0.43, 4: 0.10, 5: 0.01},
    8:  {1: 0.15, 2: 0.20, 3: 0.32, 4: 0.30, 5: 0.03},
    9:  {1: 0.10, 2: 0.17, 3: 0.25, 4: 0.33, 5: 0.15},
    10: {1: 0.05, 2: 0.10, 3: 0.20, 4: 0.40, 5: 0.25},
    11: {1: 0.01, 2: 0.02, 3: 0.12, 4: 0.50, 5: 0.35},
}

# Set 14 (patch 15.x baseline), kept intact for a Set 14 lookup. Never
# in-client verified; tft/tft_pbe_data.py ships a byte-identical copy as its
# Set 17 table.
TIER_ODDS_SET14 = {
    1:  {1: 1.00, 2: 0.00, 3: 0.00, 4: 0.00, 5: 0.00},
    2:  {1: 1.00, 2: 0.00, 3: 0.00, 4: 0.00, 5: 0.00},
    3:  {1: 0.75, 2: 0.25, 3: 0.00, 4: 0.00, 5: 0.00},
    4:  {1: 0.55, 2: 0.30, 3: 0.15, 4: 0.00, 5: 0.00},
    5:  {1: 0.45, 2: 0.33, 3: 0.20, 4: 0.02, 5: 0.00},
    6:  {1: 0.35, 2: 0.35, 3: 0.25, 4: 0.05, 5: 0.00},
    7:  {1: 0.22, 2: 0.30, 3: 0.33, 4: 0.15, 5: 0.00},
    8:  {1: 0.15, 2: 0.20, 3: 0.35, 4: 0.25, 5: 0.05},
    9:  {1: 0.10, 2: 0.15, 3: 0.30, 4: 0.30, 5: 0.15},
    10: {1: 0.05, 2: 0.10, 3: 0.20, 4: 0.35, 5: 0.30},
}

# Roll odds by set key. Set 17's table lives in tft/tft_pbe_data.py.
TIER_ODDS_BY_SET = {14: TIER_ODDS_SET14, 18: TIER_ODDS}


def tier_odds_for_set(set_number=None):
    """TIER_ODDS for a TFT set, or None when RC has no table for it.

    set_number defaults to the lane's resolved set (tft/tft_set.py
    resolve_set: live set noted from the LCU or game data, RC_TFT_SET, then
    the newest ingested set). Set 17 comes from tft/tft_pbe_data.py. No other
    set's table is ever borrowed.
    """
    if set_number is None:
        from tft import tft_set
        set_number = tft_set.resolve_set()
    if set_number in TIER_ODDS_BY_SET:
        return TIER_ODDS_BY_SET[set_number]
    from tft import tft_pbe_data
    if set_number == tft_pbe_data.CONSTANTS_SET:
        return tft_pbe_data.TIER_ODDS
    return None


def odds_level_verified(level, set_number=None) -> bool:
    """True when the set's TIER_ODDS row for ``level`` was read off the live
    client HUD. Only Set 18 has such levels (TIER_ODDS_VERIFIED_LEVELS); every
    other set's table, and Set 18's L1-L3 / L10-L11, is unverified."""
    if isinstance(level, bool) or not isinstance(level, int):
        return False
    if set_number is None:
        from tft import tft_set
        set_number = tft_set.resolve_set()
    return set_number == CONSTANTS_SET and level in TIER_ODDS_VERIFIED_LEVELS


# Pool sizes per cost and units in the pool per cost, Set 18 (S156): the game's
# own shop data, CommunityDragon map22 `ShopContentData` TierBags (one bag per
# cost, each entry a shop unit with its `Count` of copies), identical at 16.21
# and 16.22. 14 / 13 / 14 / 14 / 10 units with 30 / 25 / 18 / 10 / 9 copies
# each; every bag unit is in data/meta/tft_set18_cdragon.json at the same cost.
# This is a game-data file, NOT the in-client display (at L7 the game data
# disagrees with the live HUD, LT-02), so these are "game data, not read in
# client": CONSTANTS_SET_VERIFIED stays False. Guard:
# tests/test_tft_set18_pools_s156.py. The Set 14 transcription is kept beside
# them and never borrowed for Set 18.
POOL_SIZES_FROM_SET = 18
POOL_SIZES_SOURCE = ("CommunityDragon map22 ShopContentData TierBags, patch 16.22 "
                     "(equal at 16.21); game data, not read in client")
POOL_SIZES = {1: 30, 2: 25, 3: 18, 4: 10, 5: 9}
UNITS_PER_COST = {1: 14, 2: 13, 3: 14, 4: 14, 5: 10}

# Set 14 transcription (never in-client verified), kept intact.
POOL_SIZES_SET14 = {1: 29, 2: 22, 3: 18, 4: 12, 5: 10}
UNITS_PER_COST_SET14 = {1: 13, 2: 13, 3: 13, 4: 12, 5: 8}

# XP to the next level. Every table here is {CURRENT level: XP needed at that
# level to reach the next}, the denominator of the HUD level box
# ("Lvl. 8  60/68" = 68 at L8). Read it through xp_to_next_level only: the
# coach once read XP_TO_LEVEL[level + 1] and was one level off (S134).
#
# Set 14 transcription (never in-client verified), kept intact. Its L4-L7
# rows equal the Set 18 HUD; L8 / L9 do not.
XP_TO_LEVEL = {
    2:  2,   3:  6,  4: 10,  5: 20,
    6: 36,  7: 56,  8: 80,  9: 100,
   10: 120,
}

# Set 18 (session 134), read off the HUD level box in every game frame of two
# live games: ops/runtime/tft_qa/20261025-070350 (L4-L9 read directly) and
# 20261025-081234 (L2-L9 under the 1-1 Ashe opener "each level costs 2 XP
# less": 2/4/8/18/34/54/66/66, so base L3 = 6 and L4-L9 agree with game 1;
# L10 showed no x/y, it is the cap). Cross-check, facts only: Riot's B-patch
# 18.2 notes (as reported by gamewave.fr, 2026-09-15) set L8 -> 9 and
# L9 -> 10 to 68 and keep the L7 -> 8 cut to 56. L1 was never seen and L2's
# base is ambiguous (2 under the opener: 4 if it applies at L2, 2 if not),
# so neither has a row; no other set's value is borrowed. An opener or
# augment that changes the cost is not modelled here.
# Guard: tests/test_tft_coach_set18_xp_odds_s134.py.
XP_TO_NEXT_SET18 = {3: 6, 4: 10, 5: 20, 6: 36, 7: 56, 8: 68, 9: 68}

# XP tables by set key. Set 17 has no table of its own; it keeps the table it
# was always served (as its roll odds keep the Set 14 copy).
XP_TO_NEXT_BY_SET = {14: XP_TO_LEVEL, 17: XP_TO_LEVEL, 18: XP_TO_NEXT_SET18}


def xp_table_verified(set_number) -> bool:
    """True only for a set whose XP table was read off the HUD level box
    (Set 18, S134). Set 14 / 17 keep the transcription, never client-read."""
    return set_number == CONSTANTS_SET


def xp_to_next_level(level, set_number=None):
    """XP needed at ``level`` to reach ``level + 1`` in a TFT set, or None.

    set_number defaults to the lane's resolved set (tft/tft_set.py
    resolve_set). None for a set with no table and for a level the set's
    table does not carry; never another set's row.
    """
    if isinstance(level, bool) or not isinstance(level, int):
        return None
    if set_number is None:
        from tft import tft_set
        set_number = tft_set.resolve_set()
    table = XP_TO_NEXT_BY_SET.get(set_number)
    if table is None:
        return None
    return table.get(level)


# Gold cost to buy XP
XP_BUY_COST = 4   # 4g = +4 XP

# -- Removed guide tables (S156) -----------------------------------------------
# ROUND_EVENTS, PVE_ROUNDS, TEMPO_MILESTONES, ITEM_TIERS, COMPONENTS,
# EMBLEM_TRAITS, AUGMENT_TIERS, INTEREST_BRACKETS and INTEREST_PER_10 were the
# Set 14 transcription. No module read them (tests/test_tft_engine_guards.py
# bans the engine from naming them), the round tables contradict the Set 18
# StageRoundData (carousel X-4, PvE X-7; the measured schedule is
# tft/tft_state_reader.py _SET18_EVENTS), and ITEM_TIERS was a third-party-
# shaped S/A/B tier list of Set 14 items. Item and round facts come from the
# ingested game data (tft/tft_set.py, data/meta/tft_set18_cdragon.json).
# Guard: tests/test_tft_strategy_review_s156.py.
