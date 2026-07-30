"""
tft/tft_pbe_data.py
TFT Set 17: Space Gods data - traits, tier probabilities, god offerings,
round structure (Realm of the Gods replaces carousel).
Last updated: patch 17.3 (2026-05-13) - Morgana cost drop, Anima/Stargazer reworks, Primordian nerfed.
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

# -- Gods and their offering strategies ---------------------------------------
GODS = {
    "Ahri":        {"type": "econ",    "boon": "2 gold, 2 XP, 2 rerolls per round",
                    "strategy": "Best for fast leveling and flexible econ. Strong for Double Up where one partner fast-9s."},
    "Aurelion Sol": {"type": "quest",  "boon": "Choose trial: gold/emblem/XP quests",
                     "strategy": "High skill cap. Great if you can hit 50g or field 6 traits. Risky in Double Up if behind."},
    "Ekko":        {"type": "scaling", "boon": "Anomaly item (role-based unique bonuses)",
                    "strategy": "Slow value. Best when you have a clear carry direction early. Good for item-hungry comps."},
    "Evelynn":     {"type": "risk",    "boon": "Team gains 10% Durability, lose extra HP on loss",
                    "strategy": "HP gamble. Powerful if win-streaking. AVOID in Double Up if partner is also low HP."},
    "Kayle":       {"type": "items",   "boon": "Upgrade random completed item to Radiant",
                    "strategy": "Pure item value. Best for item-dependent carries (Jhin, Jinx). Consistent in Double Up."},
    "Soraka":      {"type": "hp",      "boon": "Team +2HP per missing tactician HP, +1 HP/round",
                    "strategy": "Loss-streak insurance. Pairs with Anima trait. Good for Double Up comeback."},
    "Thresh":      {"type": "random",  "boon": "Roll a die after each combat for rewards",
                    "strategy": "High variance. Fun but unreliable. Avoid in competitive Double Up."},
    "Varus":       {"type": "units",   "boon": "Team +10HP per total star level, +4% 5-cost odds",
                    "strategy": "Best for fast-9 / 5-cost carries. Strong in Double Up for late-game Jhin/Bard hunting."},
    "Yasuo":       {"type": "hexes",   "boon": "Hex power +50%, or 12g if only 2 hexes",
                    "strategy": "Positioning-dependent. Strong with Stargazer. In Double Up, coordinate hex placement."},
}

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

# -- Set 17 traits -------------------------------------------------------------
ORIGINS = {
    "Anima":       {"breakpoints": [2, 4, 6], "type": "loss-streak", "note": "Gain Tech on loss, prototype Anima Weapons at 100 Tech. 17.3: (6) loot after EVERY combat (was: wins only)."},
    "Arbiter":     {"breakpoints": [2, 4], "type": "utility", "note": "Subscribe to divine law, choose effect for Arbiters"},
    "Dark Star":   {"breakpoints": [2, 4, 6, 9], "type": "execute", "note": "Black holes consume enemies below 10% HP. Vertical carry with Jhin."},
    "Meeple":      {"breakpoints": [3, 5, 7, 10], "type": "scaling", "note": "Meeps empower abilities. (7) Cloning Slot. 17.2: Clone gold nerfed (1c:3→2g, 5c:5→2g)."},
    "Mecha":       {"breakpoints": [2, 4, 6], "type": "transform", "note": "Transform to Ultimate Form: +60% HP, 2 slots, counts twice. (6) +1 team size"},
    "N.O.V.A.":    {"breakpoints": [2, 3, 5], "type": "burst", "note": "Power surges in combat. (5) Striker selector."},
    "Primordian":  {"breakpoints": [2, 4, 6], "type": "swarm", "note": "Spawn Swarmlings. (3+) free 1-2 cost champ each round."},
    "Stargazer":   {"breakpoints": [2, 4, 6], "type": "hex", "note": "REWORKED 17.3: HP regen + stacking stats (was mana/Fountain). Yasuo hex synergy. Fountain mechanic removed. Mountain HP buff retained."},
    "Space Groove": {"breakpoints": [2, 4, 6], "type": "sustain", "note": "Groove: AS + HP regen. (6) stacking AD/AP in Groove."},
    "Shepherd":    {"breakpoints": [2, 4, 6], "type": "summon", "note": "Summon Bia and Bayin. Star levels increase their power."},
    "Voyager":     {"breakpoints": [2, 4, 6], "type": "generic", "note": "Tanks/Fighters get Shield, others get Damage Amp."},
    "Replicator":  {"breakpoints": [2, 4], "type": "echo", "note": "Abilities fire a second time at reduced effectiveness."},
    "Conduit":     {"breakpoints": [2, 4], "type": "mana", "note": "Innate: +20% mana from all sources. Team mana regen."},
    "Fateweaver":  {"breakpoints": [2, 4], "type": "crit", "note": "Innate: Precision (abilities can crit). Lucky chance effects."},
    "Marauder":    {"breakpoints": [2, 4, 6], "type": "sustain", "note": "Omnivamp + AD. Overhealing converts to Shield. 17.3 NERF: omnivamp reduced all tiers (20→18%, 40→35%, 60→55%)."},
    "Rogue":       {"breakpoints": [2, 4], "type": "ad/ap", "note": "AD and AP scaling."},
    "Factory New":  {"breakpoints": [2, 4], "type": "items", "note": "Item-related bonuses."},
    "Timebreaker": {"breakpoints": [2, 3, 4], "type": "as/econ/reroll",
                    "note": "REWORKED 17.2: (2)+15% AS team; (3) free rerolls on loss; (4)+50% AS for Timebreakers."},
}

CLASSES = {
    "Challenger":  {"breakpoints": [2, 4, 6], "note": "Dash on kill + AS boost"},
    "Vanguard":    {"breakpoints": [2, 4, 6], "note": "Armor/MR, damage reduction"},
    "Slayer":      {"breakpoints": [2, 4], "note": "Lifesteal + execute damage"},
    "Juggernaut":  {"breakpoints": [2, 4, 6], "note": "HP + damage scaling"},
    "Longshot":    {"breakpoints": [2, 4], "note": "Increased damage per hex distance"},
    "Invoker":     {"breakpoints": [2, 4], "note": "Mana on cast + AP"},
    "Disruptor":   {"breakpoints": [2, 4], "note": "Crowd control + disruption"},
    "Quickstriker": {"breakpoints": [2, 4], "note": "Bonus attack speed, first strikes"},
    "Arcanist":    {"breakpoints": [2, 4, 6], "note": "AP scaling, AP sharing"},
    "Vanquisher":  {"breakpoints": [2, 4], "note": "Armor pen + crit"},
    "Bastion":     {"breakpoints": [2, 4, 6], "note": "Shields + durability"},
    "Brawler":     {"breakpoints": [2, 4, 6], "note": "Bonus HP"},
    "Commander":   {"breakpoints": [1], "note": "Unique passive per commander"},
    "Psionic":     {"breakpoints": [2, 4], "note": "Psychic damage + utility"},
    "Gunslinger":  {"breakpoints": [2, 4], "note": "Ranged multi-target attacks"},
    "Sniper":      {"breakpoints": [2, 4], "note": "Increased damage from range"},
}

# -- Champions by cost ---------------------------------------------------------
CHAMPIONS = {
    1: ["Nasus", "Poppy", "Briar", "Caitlyn", "Leona", "Veigar", "Aatrox"],
    2: ["Cho'Gath", "Rek'Sai", "Teemo", "Twisted Fate", "Gnar", "Meepsie", "Nami", "Zoe"],
    3: ["Diana", "Fizz", "Gwen", "Jinx", "Milio", "Urgot", "LeBlanc", "Corki", "Rammus"],
    4: ["Aurelion Sol", "The Mighty Mech", "Bel'Veth", "Lissandra", "Kai'Sa",
        "Karma", "Mordekaiser", "Akali", "Kindred", "Maokai", "Morgana"],  # Morgana moved 5->4 in 17.3
    5: ["Jhin", "Fiora", "Shen", "Graves", "Blitzcrank", "Bard", "Sona"],
}

# -- PBE meta comps (updated 2026-04-07) --------------------------------------
META_COMPS = {
    # 17.3 meta: AP late-game stronger (Sol/Karma/LeBlanc/Sona buffed). Primordian dead. Morgana now 4-cost.
    "S": [
        {"name": "Meeple",           "carry": "Bard/Veigar",  "core": "Meeple 7+, Cloning Slot for 5-cost"},
        {"name": "AP Vanguards",     "carry": "Lissandra",    "core": "Vanguard 4, Replicator 2, Dark Star splash - buffed 17.3"},
        {"name": "Redeemer",         "carry": "Sona/Morgana", "core": "Conduit 4, Space Groove; Morgana now 4g (easier to hit)"},
        {"name": "Dark Star Jhin",   "carry": "Jhin",         "core": "Dark Star 6-9, execute carry - stable S tier"},
        {"name": "Conduit Reroll",   "carry": "Nami",         "core": "Conduit 4, Replicator 2, 3-star Nami"},
        {"name": "N.O.V.A.",         "carry": "Caitlyn/Akali","core": "N.O.V.A. 5 for Striker selector; Akali buffed"},
        {"name": "Mecha",            "carry": "Corki/Rammus", "core": "Mecha 4-6, transformed units fill slots"},
    ],
    "A": [
        {"name": "Anima",            "carry": "LeBlanc",      "core": "Anima 4+, loss-streak; (6) loot every combat now (17.3 buff)"},
        {"name": "Stargazer",        "carry": "Karma/Yasuo",  "core": "Stargazer 4, HP regen rework 17.3; Karma buffed"},
        {"name": "Space Opera",      "carry": "Jinx",         "core": "Space Groove 4, Gunslinger 2"},
        {"name": "Rogue Reroll",     "carry": "Akali",        "core": "Rogue 4, 3-star Akali"},
        {"name": "Contract Killer",  "carry": "Fiora",        "core": "Fateweaver + Slayer, 1v1 duel win"},
        {"name": "Psionic",          "carry": "Master Yi",    "core": "Psionic 4, Fateweaver 2; Yi omnivamp nerfed 17.3"},
    ],
    "B": [
        # Primordian NOVA: Apex Primordian gutted 17.3 (AS 0.9->0.6, armor/MR 150->60). Avoid.
        {"name": "Primordian NOVA",  "carry": "Kindred",      "core": "AVOID 17.3: Apex Primordian nerfed to the ground"},
    ],
}

# -- Encounters (returned in patch 17.2) --------------------------------------
# Opening Encounters appear at early-game stages and modify conditions for all players.
ENCOUNTERS = {
    # Returning from Set 16 (16 total)
    "Golden Gala":         {"type": "econ",      "note": "Strong gold start; enables econ lead"},
    "Prismatic Party":     {"type": "loot",      "note": "Prismatic items early; flex carry direction"},
    "Prismatic Finale":    {"type": "loot",      "note": "Late loot boost"},
    "Prismatic Opener":    {"type": "loot",      "note": "Early Prismatic; adapt items to carry"},
    "3-cost Start":        {"type": "units",     "note": "Early 3-costs; skip slow-roll, push 3-cost carries"},
    "2-cost Start":        {"type": "units",     "note": "Early 2-costs; enables 2-cost reroll comps"},
    "Upgraded Start":      {"type": "units",     "note": "Units pre-upgraded; stronger early boards"},
    "Component Anvils":    {"type": "items",     "note": "Extra components; flex item paths"},
    "Loot Subscription":   {"type": "econ",      "note": "Periodic loot drops per stage"},
    "Gold Subscription":   {"type": "econ",      "note": "Periodic gold income"},
    "No Encounter":        {"type": "none",      "note": "Standard game, no modifier"},
    "Howling Abyss":       {"type": "combat",    "note": "Bonus HP on kills; aggressive boards rewarded"},
    "Silver Scrapes":      {"type": "items",     "note": "Silver items on loss"},
    "Scouting Party":      {"type": "scouting",  "note": "Reveal all boards early"},
    # New in 17.2 (5 total)
    "Double Duplicators":  {"type": "units",     "note": "17.3: Tiny duplicators (not Lesser); appears 3-5 not 3-3. Still speeds up 3-star pivots."},
    "Artifact Anvil":      {"type": "items",     "note": "All players get Artifact Anvil at 3-3; flex carries"},
    "Stage Three Augments":{"type": "augments",  "note": "Augments shift to 3-1/3-2/3-3; delay comp pivot"},
    "Reroll Start":        {"type": "rolls",     "note": "17.3 NERF: 5 free rerolls at 2-1 (was 8). Hyper-roll comps less explosive than before."},
    "Cheaper Levels":      {"type": "leveling",  "note": "-2 XP per level; enables fast-9 comps"},
}

# -- God Blessings (new mechanic in patch 17.2) --------------------------------
# When aligned with a god 2+ times, choose between 2-3 Blessing options instead
# of a fixed boon. Blessings provide powerful, character-specific bonuses.
GOD_BLESSINGS = {
    "Ahri": [
        {"name": "Gold Every Turn",     "effect": "+1 gold per turn for rest of game"},
        {"name": "Divine Investment",   "effect": "Max interest cap +1; 4/6 gold now"},
        {"name": "Chest of Greed",      "effect": "2/3/4 gold + shared wealth pool (12/16/25 split)"},
    ],
    "Kayle": [
        {"name": "Divine Refund",       "effect": "2 gold + component copy on next item crafted"},
        {"name": "Craftsmanship",       "effect": "2 Reforgers now + 1 each stage; 2g per Reforger use"},
        {"name": "Anvil Transformation","effect": "All component drops → Component Anvils; +2 gold"},
    ],
    "Evelynn": [
        {"name": "Finalist Gambit",     "effect": "3 gold now; +30 gold bonus for finishing top 4"},
    ],
    "Soraka": [
        {"name": "Soraka's Embrace",    "effect": "Each combat: grant 450-800 shield to first ally that died last fight"},
    ],
    "Thresh": [
        {"name": "Mini Recombobulate",  "effect": "Transform all 1-2 cost champs into random higher-cost units"},
        {"name": "Pandora's Seat",      "effect": "Each round: 2 rightmost bench slots transform to same-cost random"},
    ],
    "Varus": [
        {"name": "Ephemeral Rerolls",   "effect": "Free reroll each round if shop has no available units"},
        {"name": "Starcrossed Upgrade", "effect": "Next 2/3/4-cost shop unit appears 2-starred"},
        {"name": "Super Parting Gift",  "effect": "Next God Pengu selection: extra champion copy + 2 gold"},
    ],
}

# -- Double Up specific data --------------------------------------------------
DOUBLE_UP_GOD_STRATEGY = {
    "split_econ":    "One partner takes Ahri (econ), other takes Kayle (items). Both scale differently.",
    "both_units":    "Both take Varus for unit generation. Flood boards with stars.",
    "one_gambles":   "One takes Evelynn (risk) while partner takes Soraka (HP safety net).",
    "hex_coord":     "Both take Yasuo for hex stacking. Coordinate hex positions across boards.",
    "quest_safe":    "One takes Aurelion Sol (quests), other takes Thresh (random + gold).",
}

DOUBLE_UP_UNIT_SEND_PRIORITY = [
    "3rd copy of unit partner needs for 3-star",
    "Off-comp 2-star unit that fits partner's comp",
    "Overflow 4-cost or 5-cost not in your comp",
    "Component holder if partner needs specific item",
]

# -- Item tier list (Set 17) --------------------------------------------------
ITEM_TIERS = {
    "Rabadon's Deathcap":        "S",
    "Guinsoo's Rageblade":       "S",
    "Infinity Edge":             "S",
    "Bloodthirster":             "S",
    "Blue Buff":                 "S",
    "Spear of Shojin":          "S",
    "Jeweled Gauntlet":          "S",
    "Sunfire Cape":              "S",
    "Titan's Resolve":           "A",
    "Dragon's Claw":             "A",
    "Gargoyle Stoneplate":       "A",
    "Warmog's Armor":            "A",
    "Redemption":                "A",
    "Locket of the Iron Solari": "A",
    "Zephyr":                    "A",
    "Shroud of Stillness":       "A",
    "Archangel's Staff":         "A",
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
    "B.F. Sword", "Chain Vest", "Giant's Belt",
    "Needlessly Large Rod", "Negatron Cloak",
    "Recurve Bow", "Sparring Gloves", "Spatula", "Tear of the Goddess",
}
