"""
tft/tft_pbe_data.py
Set 17 constants the TFT lane still reads: roll-odds tables (unverified,
see CONSTANTS_SET_VERIFIED), the Realm of the Gods round schedule and the
per-round tempo notes.

RM-845 removed eleven tables nothing read - GODS, ORIGINS, CLASSES,
CHAMPIONS, META_COMPS, ENCOUNTERS, GOD_BLESSINGS, DOUBLE_UP_GOD_STRATEGY,
DOUBLE_UP_UNIT_SEND_PRIORITY, ITEM_TIERS, COMPONENTS (measured: no import,
getattr or star import anywhere in the tree). They carried guide-style
claims - comp and item tier calls, god "strategy" advice, patch commentary -
that no ingested game data backs. Set game data lives in data/meta
(tft/tft_set.py; CommunityDragon extracts), and the coach system prompt is
built from it (tft/tft_prompt.py).

Readers: tft/tft_roll_odds.py load_constants (constants), and the round
schedule in tft/tft_state_reader.py. The PBE engine and PBE coach that also
read the schedule (only when the resolved set's meta records Realm of the
Gods, tft/tft_prompt.py set_has_gods) were deleted by RM-292 (b),
2026-10-25.
"""

# -- Set declaration ----------------------------------------------------------
# See tft/tft_data.py for what these two mean and which guard reads them.
CONSTANTS_SET = 17
# NOT in-client verified: the tables below are byte-identical to the Set 14
# tables in tft/tft_data.py, which is evidence they were copied rather than
# re-derived for Set 17. Operator verifies in client; live-gated.
CONSTANTS_SET_VERIFIED = False

# -- Tier probability tables (standard Set 17) -------------------------------
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

POOL_SIZES = {1: 29, 2: 22, 3: 18, 4: 12, 5: 10}

# -- Stage / round structure - Set 17 "Realm of the Gods" --------------------
# Carousel rounds (X-1 for stages 2+) are GONE.
# Replaced by God selection at mid-stage: 2-4, 3-4, 4-4
# Stage 4-7: God Boon (alignment reward)
# PvE rounds remain at end of each stage.
ROUND_EVENTS = {
    (1, 1): "opening_carousel",     # Still exists as opening round shared draft
    (1, 3): "krugs",                # PvE
    (2, 4): "realm_of_gods",        # God selection replaces carousel
    (2, 5): "wolves",               # PvE
    (3, 4): "realm_of_gods",        # God selection
    (3, 5): "raptors",              # PvE
    (4, 4): "realm_of_gods",        # God selection
    (4, 5): "herald",               # PvE
    (4, 7): "god_boon",             # Aligned god grants Boon armory
    (5, 5): "baron",                # PvE
    (6, 5): "baron",                # PvE
}
PVE_ROUNDS = {(1, 3), (2, 5), (3, 5), (4, 5), (5, 5), (6, 5)}
GOD_ROUNDS = {(2, 4), (3, 4), (4, 4)}
BOON_ROUND = (4, 7)

# -- Key tempo milestones (Set 17) --------------------------------------------
TEMPO_MILESTONES = {
    "2-1":  "First PvP round. Establish early board, look for 2-star 1-costs.",
    "2-4":  "REALM OF THE GODS: Choose god offering. Pick based on comp direction.",
    "2-5":  "Wolves PvE. Evaluate econ and plan level timing.",
    "3-2":  "Mid-game pivot point. Evaluate contested units, decide vertical vs flex.",
    "3-4":  "REALM OF THE GODS: Second god choice. Align with same god if boon is strong.",
    "4-1":  "Stage 4 opener. Level 7 spike for 3-cost carries.",
    "4-2":  "Consider level 8 push for 4-cost carries if HP allows.",
    "4-4":  "REALM OF THE GODS: Third god choice. Lock alignment for 4-7 Boon.",
    "4-7":  "GOD BOON: Your aligned god offers a powerful armory reward.",
    "5-1":  "Level 9 decision. Fast-9 vs hyperroll for capped board.",
    "6-1":  "Late game. Stabilize, push for top 2.",
}
