"""
tft/tft_data.py
TFT Set data - units, traits, items, tier probabilities, carousel logic.
Set-agnostic structure: update UNITS / TRAITS / ITEMS dicts each set patch.
Currently seeded for TFT Set 14 (patch 15.x baseline).
"""

# -- Set declaration ----------------------------------------------------------
# CONSTANTS_SET is the TFT set the tables below were transcribed for. The set
# the rest of the TFT lane is actually running is read off disk from
# data/meta/tft_set17_meta.json ("_set"). When these two disagree, everything
# below is STALE. tests/test_tft_constants_staleness.py is the guard; it fails
# the moment this declaration, the lane's set, or the known discrepancies move
# without someone updating the expectation.
CONSTANTS_SET = 14
# True only once the tables below were read off the IN-CLIENT display for
# CONSTANTS_SET. Third-party aggregator tables are NOT sufficient - two
# reviewed sources disagreed on the L7-L9 rows - so this stays False until an
# operator verifies in client. Live-gated; no headless run can flip it.
CONSTANTS_SET_VERIFIED = False

# -- Tier probability tables (standard) --------------------------------------
# {player_level: {cost: probability}}
TIER_ODDS = {
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

# Pool sizes per cost
POOL_SIZES = {1: 29, 2: 22, 3: 18, 4: 12, 5: 10}

# Units in pool per cost tier
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
