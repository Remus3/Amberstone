"""
tft/tft_data.py
TFT Set data - units, traits, items, tier probabilities, carousel logic.
Set-agnostic structure: update UNITS / TRAITS / ITEMS dicts each set patch.
Roll odds: Set 18 (LT-02, in-client measured at L4-L9), the Set 14 table kept
beside it and routed by set key (tier_odds_for_set). The other tables below
(pool sizes, XP, rounds, items) are still the Set 14 transcription.
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


# Pool sizes per cost. NOT Set 18 values: carried over from the Set 14
# transcription (POOL_SIZES_FROM_SET). The HUD does not show pool sizes and no
# measured Set 18 source exists yet, so they stay unpinned (LT-02).
POOL_SIZES_FROM_SET = 14
POOL_SIZES = {1: 29, 2: 22, 3: 18, 4: 12, 5: 10}

# Units in pool per cost tier (Set 14 carry-over, as POOL_SIZES)
UNITS_PER_COST = {1: 13, 2: 13, 3: 13, 4: 12, 5: 8}

# -- Econ thresholds ----------------------------------------------------------
INTEREST_BRACKETS = [10, 20, 30, 40, 50]   # gold thresholds for interest
INTEREST_PER_10   = 1                        # +1g per 10g held

# XP cost per level
XP_TO_LEVEL = {
    2:  2,   3:  6,  4: 10,  5: 20,
    6: 36,  7: 56,  8: 80,  9: 100,
   10: 120,
}

# Gold cost to buy XP
XP_BUY_COST = 4   # 4g = +4 XP

# -- Stage / round structure --------------------------------------------------
# (stage, round): event
ROUND_EVENTS = {
    (1, 1): "carousel",
    (1, 3): "krugs",  # PvE
    (2, 1): "carousel",
    (2, 5): "wolves",
    (3, 1): "carousel",
    (3, 5): "raptors",
    (4, 1): "carousel",
    (4, 5): "herald",
    (5, 1): "carousel",
    (5, 5): "baron",
    (6, 1): "carousel",
    (6, 5): "baron",
    (7, 1): "carousel",
}
PVE_ROUNDS = {(1,3), (2,5), (3,5), (4,5), (5,5), (6,5)}

# -- Key tempo milestones -----------------------------------------------------
TEMPO_MILESTONES = {
    "2-1":  "First PvP - roll to 50g if needed for strong 2-star opener",
    "2-5":  "Wolves PvE - save roll-down gold, plan econ after",
    "3-1":  "Carousel - pick item component or 2-cost for comp",
    "3-2":  "Mid-game pivot point - evaluate contested units, decide comp direction",
    "4-1":  "Carousel - target BiS item component or 4-cost carry",
    "4-2":  "Consider level 8 push for 4-costs if health permits",
    "5-1":  "Level 9 decision - fast 9 or hyper-roll for 5-cost?",
    "6-1":  "Late game - stabilise board, push level 9-10",
}

# -- Item tier list -----------------------------------------------------------
ITEM_TIERS = {
    "Sunfire Cape":              "S",
    "Rabadon's Deathcap":        "S",
    "Guinsoo's Rageblade":       "S",
    "Infinity Edge":             "S",
    "Bloodthirster":             "S",
    "Jeweled Gauntlet":          "S",
    "Blue Buff":                 "S",
    "Shojin":                    "S",
    "Titan's Resolve":           "A",
    "Dragon's Claw":             "A",
    "Gargoyle Stoneplate":       "A",
    "Warmog's Armor":            "A",
    "Redemption":                "A",
    "Locket of the Iron Solari": "A",
    "Zephyr":                    "A",
    "Shroud of Stillness":       "A",
    "Bramble Vest":              "B",
    "Ionic Spark":               "B",
    "Runaan's Hurricane":        "B",
    "Last Whisper":              "B",
    "Giant Slayer":              "B",
    "Hand of Justice":           "B",
    "Statikk Shiv":              "C",
    "Rapid Firecannon":          "C",
}

COMPONENTS = {
    "BF Sword", "Chain Vest", "Giant's Belt",
    "Needlessly Large Rod", "Negatron Cloak",
    "Recurve Bow", "Sparring Gloves", "Spatula", "Tear of the Goddess",
}

EMBLEM_TRAITS = {}

AUGMENT_TIERS = {"prismatic": 3, "gold": 2, "silver": 1}
