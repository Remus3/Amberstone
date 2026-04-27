"""
Validate and correct all comp positioning in tft_set17_meta.json.

Issues found:
- Meeple lv9: positioning uses Veigar/Teemo/Lissandra/Sona instead of Fizz/Gnar/Meepsie/Milio
- AP Vanguards lv9: only 8 units (needs Shen), positioning uses wrong units
- Conduit Reroll lv9: positioning uses Leona/Nasus/Pantheon/Karma instead of Rhaast/Gragas/Zoe/Aatrox
- Mecha lv9: only 7 units (needs Shen+Rammus), positioning wrong
- N.O.V.A. lv9: Fiora placed D6 (backline for melee carry - wrong)
- Rogue Reroll lv9: Fizz D7 (melee carry in backline wrong), Gwen A6 (carry in frontline wrong), only 8 units
- 12 comps have NO positioning sections at all
"""
import json
from pathlib import Path

META = Path(r"C:\Riot Commander\data\meta\tft_set17_meta.json")
meta = json.loads(META.read_text(encoding="utf-8-sig"))
comps = meta["comps"]

# ===========================================================================
# POSITIONING CORRECTIONS
# Grid: Row A=frontline(enemy), B=2nd, C=3rd, D=backline(player)
#       Columns 1-7 left to right
# Rules:
#   Tanks       → A row, spread wide (A1 A3 A5 A7)
#   Melee carry → B row (B3 or B5)
#   AP utility  → C or D row
#   Ranged carry→ D row, far corner D7 (or D1 vs assassins)
#   Support     → C3/C5 adjacent to carry
# ===========================================================================

CORRECT_POSITIONING = {

    # ── REDEEMER ──────────────────────────────────────────────────────────
    # Fix: Rhaast moved to B6 (right side, same side as MF D7 for kill synergy)
    # Fix: Nasus A7 instead of A6 to spread frontline better
    # All 9 units: MF, Rhaast, Maokai, Ornn, Leona, Nasus, Pantheon, Karma, Bard
    "Redeemer": {
        "lv4": {
            "Nasus":       "A1",
            "Maokai":      "A3",
            "Leona":       "A5",
            "Miss Fortune":"D7",
        },
        "lv7": {
            "Miss Fortune":"D7",
            "Rhaast":      "B5",
            "Maokai":      "A1",
            "Ornn":        "A3",
            "Leona":       "A5",
            "Nasus":       "A7",
            "Pantheon":    "B2",
        },
        "lv9": {
            "Miss Fortune":"D7",   # AD carry far corner
            "Karma":       "D4",   # AP support backline
            "Bard":        "D2",   # Utility backline left
            "Rhaast":      "B6",   # Redeemer kill-stacker right side, near MF
            "Pantheon":    "B2",   # Frontline flex 2nd row left
            "Maokai":      "A1",   # NOVA/Brawler tank left
            "Leona":       "A3",   # Arbiter/Vanguard tank
            "Ornn":        "A5",   # Space Groove/Bastion tank
            "Nasus":       "A7",   # Space Groove/Vanguard tank right
        },
    },

    # ── MEEPLE ────────────────────────────────────────────────────────────
    # Fix: Replace Veigar/Teemo/Lissandra/Sona with actual lv9 units: Fizz/Gnar/Meepsie/Milio
    # lv9: Bard, Corki, Rammus, Riven, Fizz, Gnar, Meepsie, Milio, Poppy
    "Meeple": {
        "lv4": {
            "Teemo":      "D6",
            "Poppy":      "A1",
            "Corki":      "D7",
            "Lissandra":  "A4",
        },
        "lv7": {
            "Corki":      "D7",
            "Rammus":     "A1",
            "Poppy":      "A4",
            "Fizz":       "B5",
            "Gnar":       "D5",
            "Milio":      "C4",
            "Meepsie":    "A7",
        },
        "lv9": {
            "Corki":      "D7",   # Meeple/Fateweaver AD carry
            "Bard":       "D4",   # Meeple/Conduit AP carry
            "Gnar":       "D5",   # Meeple/Sniper ranged DPS
            "Milio":      "C5",   # Timebreaker/Fateweaver support
            "Fizz":       "B5",   # Meeple/Rogue AP melee carry
            "Riven":      "B3",   # Timebreaker/Rogue skirmisher
            "Rammus":     "A1",   # Meeple/Bastion tank left
            "Poppy":      "A4",   # Meeple/Bastion tank center
            "Meepsie":    "A7",   # Meeple/Shepherd utility right
        },
    },

    # ── AP VANGUARDS ──────────────────────────────────────────────────────
    # Fix: Add Shen as 9th unit, correct positioning
    # lv9: Karma, LeBlanc, Nunu, Illaoi, Meepsie, Mordekaiser, Zoe, Leona, Shen
    "AP Vanguards": {
        "lv4": {
            "LeBlanc":     "D7",
            "Leona":       "A1",
            "Maokai":      "A4",
            "Nasus":       "A3",
        },
        "lv7": {
            "LeBlanc":     "D7",
            "Nunu":        "A3",
            "Karma":       "D4",
            "Shen":        "A5",
            "Leona":       "A1",
            "Maokai":      "A7",
            "Pantheon":    "B4",
        },
        "lv9": {
            "LeBlanc":     "D7",   # Main AP carry far corner
            "Karma":       "D4",   # AP support/secondary carry
            "Zoe":         "C5",   # Arbiter/Conduit AP utility
            "Meepsie":     "C3",   # Meeple/Shepherd support
            "Mordekaiser": "B4",   # Dark Star/Conduit/Vanguard brawler
            "Leona":       "A1",   # Arbiter/Vanguard tank left
            "Nunu":        "A3",   # Stargazer/Vanguard tank
            "Shen":        "A5",   # Bulwark/Bastion elite tank
            "Illaoi":      "A7",   # Anima/Vanguard/Shepherd tank right
        },
    },

    # ── CONDUIT REROLL ────────────────────────────────────────────────────
    # Fix: Replace Leona/Nasus/Pantheon/Karma with actual lv9 units: Rhaast/Gragas/Zoe/Aatrox
    # lv9: Miss Fortune, Ornn, Viktor, Bard, Maokai, Rhaast, Gragas, Zoe, Aatrox
    "Conduit Reroll": {
        "lv4": {
            "Nasus":       "A1",
            "Leona":       "A4",
            "Miss Fortune":"D7",
            "Maokai":      "A3",
        },
        "lv7": {
            "Miss Fortune":"D7",
            "Ornn":        "A1",
            "Viktor":      "D5",
            "Maokai":      "A3",
            "Gragas":      "A5",
            "Rhaast":      "B4",
            "Aatrox":      "A7",
        },
        "lv9": {
            "Miss Fortune":"D7",   # AD carry far corner
            "Viktor":      "D5",   # Psionic/Conduit AP carry
            "Bard":        "D3",   # Meeple/Conduit AP utility
            "Zoe":         "C5",   # Arbiter/Conduit AP utility
            "Rhaast":      "B4",   # Redeemer bruiser carry
            "Maokai":      "A1",   # NOVA/Brawler frontline healer
            "Aatrox":      "A3",   # NOVA/Bastion shredder
            "Ornn":        "A5",   # Space Groove/Bastion tank
            "Gragas":      "A7",   # Psionic/Brawler frontline
        },
    },

    # ── SPACE OPERA ── (already correct, keep as-is) ─────────────────────

    # ── MECHA ─────────────────────────────────────────────────────────────
    # Fix: lv9 unit list has only 7 (add Shen + Rammus). Fix positioning.
    # lv9: Bard, Graves, Aurelion Sol, The Mighty Mech, Maokai, Urgot, Akali, Shen, Rammus
    "Mecha": {
        "lv4": {
            "Poppy":          "A1",
            "Teemo":          "D6",
            "Corki":          "D7",
            "Graves":         "A4",
        },
        "lv7": {
            "Aurelion Sol":   "D4",
            "The Mighty Mech":"A3",
            "Graves":         "D7",
            "Shen":           "A5",
            "Urgot":          "A1",
            "Maokai":         "A7",
            "Akali":          "B5",
        },
        "lv9": {
            "Graves":         "D7",   # Factory New AD carry corner
            "Aurelion Sol":   "D5",   # Mecha/Conduit AP carry
            "Bard":           "D3",   # Meeple/Conduit AP utility
            "Akali":          "B5",   # NOVA/Marauder melee carry
            "The Mighty Mech":"A3",   # Mecha tank (absorbs stats)
            "Urgot":          "A1",   # Mecha/Brawler tank brawler
            "Shen":           "A5",   # Bulwark/Bastion elite tank
            "Maokai":         "A7",   # NOVA/Brawler frontline healer
            "Rammus":         "B2",   # Meeple/Bastion secondary frontline
        },
    },

    # ── N.O.V.A. ─────────────────────────────────────────────────────────
    # Fix: Fiora moved from D6 (backline wrong for melee carry) to B5
    # lv9: Aatrox, Caitlyn, Akali, Maokai, Kindred, Shen, Fiora, Bard, Nunu
    "N.O.V.A.": {
        "lv4": {
            "Aatrox":   "A1",
            "Caitlyn":  "D7",
            "Akali":    "B3",
            "Nasus":    "A4",
        },
        "lv7": {
            "Aatrox":   "A1",
            "Caitlyn":  "D6",
            "Akali":    "B3",
            "Maokai":   "A4",
            "Kindred":  "D7",
            "Shen":     "A6",
            "Nunu":     "A3",
        },
        "lv9": {
            "Kindred":  "D7",   # NOVA/Challenger AS carry far corner
            "Caitlyn":  "D5",   # NOVA/Fateweaver ranged carry
            "Bard":     "C4",   # Meeple/Conduit AP utility
            "Fiora":    "B5",   # Divine Duelist/Anima melee carry (NOT backline)
            "Akali":    "B3",   # NOVA/Marauder melee carry
            "Aatrox":   "A1",   # NOVA/Bastion shredder left
            "Nunu":     "A3",   # Stargazer/Vanguard tank
            "Maokai":   "A5",   # NOVA/Brawler healer
            "Shen":     "A7",   # Bulwark/Bastion elite tank right
        },
    },

    # ── NOVA YI ── (add complete positioning - was missing entirely) ─────
    # lv9: Fiora, Kindred, Master Yi, Maokai, Shen, Urgot, Akali, Aatrox, Caitlyn
    "NOVA YI": {
        "lv4": {
            "Aatrox":    "A1",
            "Caitlyn":   "D7",
            "Akali":     "B3",
            "Maokai":    "A4",
        },
        "lv7": {
            "Master Yi": "B5",
            "Kindred":   "D7",
            "Maokai":    "A3",
            "Shen":      "A5",
            "Urgot":     "A1",
            "Akali":     "B3",
            "Aatrox":    "A7",
        },
        "lv9": {
            "Kindred":   "D7",   # NOVA/Challenger AS carry corner
            "Caitlyn":   "D5",   # NOVA/Fateweaver ranged carry
            "Fiora":     "B6",   # Divine Duelist melee carry right side
            "Akali":     "B3",   # NOVA/Marauder melee carry
            "Master Yi": "B5",   # Psionic/Marauder bruiser carry
            "Aatrox":    "A1",   # NOVA/Bastion shredder left
            "Maokai":    "A3",   # NOVA/Brawler healer
            "Urgot":     "A5",   # Mecha/Brawler tank
            "Shen":      "A7",   # Bulwark/Bastion elite tank right
        },
    },

    # ── ROGUE REROLL ─────────────────────────────────────────────────────
    # Fix: Fizz moved from D7 to B5 (melee carry should NOT be in backline)
    #      Gwen moved from A6 to B3 (carry should not be in frontline row A)
    #      Talon added as 9th unit (Stargazer/Rogue gives Rogue 4)
    # lv9: Fizz, Kai'Sa, Ornn, Rhaast, Karma, Rammus, Gwen, Meepsie, Talon
    "Rogue Reroll": {
        "lv4": {
            "Talon":    "D6",
            "Fizz":     "D7",
            "Gwen":     "A4",
            "Meepsie":  "A1",
        },
        "lv7": {
            "Fizz":     "B5",
            "Kai'Sa":   "D7",
            "Ornn":     "A1",
            "Rhaast":   "B3",
            "Karma":    "C4",
            "Gwen":     "B6",
            "Meepsie":  "A5",
        },
        "lv9": {
            "Kai'Sa":   "D7",   # Dark Star/Rogue ranged carry corner
            "Karma":    "C5",   # Dark Star/Voyager AP support
            "Meepsie":  "C2",   # Meeple/Shepherd support
            "Talon":    "B6",   # Stargazer/Rogue melee rogue right
            "Fizz":     "B4",   # Meeple/Rogue AP melee carry center
            "Gwen":     "B2",   # Space Groove/Rogue skirmisher left
            "Rhaast":   "A6",   # Redeemer bruiser (walks to frontline)
            "Ornn":     "A1",   # Space Groove/Bastion tank left
            "Rammus":   "A4",   # Meeple/Bastion tank center
        },
    },

    # ── STARGAZER ── (add complete positioning - was missing) ────────────
    # lv9: Talon, Twisted Fate, Jax, Lulu, Nunu, Xayah, Riven, Shen, Pantheon
    "Stargazer": {
        "lv4": {
            "Talon":        "D6",
            "Twisted Fate": "D4",
            "Jax":          "B3",
            "Shen":         "A4",
        },
        "lv7": {
            "Talon":        "D6",
            "Twisted Fate": "D4",
            "Jax":          "A5",
            "Lulu":         "C4",
            "Nunu":         "A3",
            "Xayah":        "D7",
            "Shen":         "A1",
        },
        "lv9": {
            "Xayah":        "D7",   # Stargazer/Sniper AS carry corner
            "Twisted Fate": "D4",   # Stargazer/Fateweaver AP carry
            "Lulu":         "C4",   # Stargazer/Replicator support
            "Talon":        "B5",   # Stargazer/Rogue melee carry
            "Riven":        "B3",   # Timebreaker/Rogue melee carry
            "Nunu":         "A1",   # Stargazer/Vanguard tank left
            "Jax":          "A3",   # Stargazer/Bastion melee tank
            "Shen":         "A5",   # Bulwark/Bastion elite tank
            "Pantheon":     "A7",   # Timebreaker/Brawler tank right
        },
    },

    # ── TURBO DOOMER ── (add complete positioning - was missing) ─────────
    # lv9: Mordekaiser, Vex, Karma, Leona, Zoe, Maokai, Shen, Bard, Morgana
    "Turbo Doomer": {
        "lv4": {
            "Mordekaiser":  "B3",
            "Lissandra":    "A4",
            "Cho'Gath":     "A2",
            "Vex":          "D7",
        },
        "lv7": {
            "Mordekaiser":  "B3",
            "Vex":          "D7",
            "Karma":        "D4",
            "Leona":        "A1",
            "Zoe":          "C5",
            "Maokai":       "A4",
            "Shen":         "A6",
        },
        "lv9": {
            "Vex":          "D7",   # Doomer AP carry corner
            "Karma":        "D4",   # Dark Star/Voyager AP support
            "Bard":         "D2",   # Meeple/Conduit utility
            "Morgana":      "C5",   # Dark Lady AP utility
            "Zoe":          "C3",   # Arbiter/Conduit AP utility
            "Mordekaiser":  "B3",   # Dark Star/Conduit/Vanguard brawler
            "Maokai":       "A1",   # NOVA/Brawler tank left
            "Leona":        "A4",   # Arbiter/Vanguard tank center
            "Shen":         "A7",   # Bulwark/Bastion elite tank right
        },
    },

    # ── VOID ARCANE ── (add complete positioning - was missing) ──────────
    # lv9: Viktor, Shen, Morgana, Bard, Maokai, Leona, Zoe, Karma, Rhaast
    "Void Arcane": {
        "lv4": {
            "Viktor":   "D5",
            "Gragas":   "A3",
            "Zoe":      "C5",
            "Maokai":   "A1",
        },
        "lv7": {
            "Viktor":   "D7",
            "Shen":     "A5",
            "Morgana":  "C4",
            "Bard":     "D4",
            "Maokai":   "A1",
            "Leona":    "A3",
            "Zoe":      "C6",
        },
        "lv9": {
            "Viktor":   "D7",   # Psionic/Conduit AP carry corner
            "Bard":     "D3",   # Meeple/Conduit utility
            "Karma":    "D5",   # Dark Star/Voyager AP support
            "Zoe":      "C5",   # Arbiter/Conduit AP utility
            "Morgana":  "C3",   # Dark Lady AP utility
            "Rhaast":   "B5",   # Redeemer bruiser carry right side
            "Maokai":   "A1",   # NOVA/Brawler frontline healer
            "Leona":    "A3",   # Arbiter/Vanguard tank
            "Shen":     "A6",   # Bulwark/Bastion elite tank
        },
    },

    # ── ANIMA ── (add complete positioning - was missing) ────────────────
    # lv9: Illaoi, Miss Fortune, Aurora, Briar, Jinx, Fiora, Maokai, Shen, Bard
    "Anima": {
        "lv4": {
            "Illaoi":       "A3",
            "Briar":        "B3",
            "Jinx":         "D7",
            "Aurora":       "D5",
        },
        "lv7": {
            "Illaoi":       "A3",
            "Miss Fortune": "D7",
            "Aurora":       "D5",
            "Briar":        "B2",
            "Jinx":         "D6",
            "Fiora":        "B5",
            "Maokai":       "A1",
        },
        "lv9": {
            "Miss Fortune": "D7",   # Gun Goddess AD carry corner
            "Jinx":         "D5",   # Anima/Challenger AD carry
            "Aurora":       "D3",   # Anima/Voyager AP carry
            "Bard":         "C5",   # Meeple/Conduit utility
            "Fiora":        "B6",   # Divine Duelist melee carry right
            "Briar":        "B2",   # Anima/Primordian skirmisher left
            "Maokai":       "A1",   # NOVA/Brawler frontline healer
            "Illaoi":       "A4",   # Anima/Vanguard tank center
            "Shen":         "A7",   # Bulwark/Bastion elite tank right
        },
    },

    # ── PRIMORDIAN NOVA REROLL ── (add complete positioning) ─────────────
    # lv9: Rek'Sai, Caitlyn, Bel'Veth, Akali, Maokai, Briar, Aatrox, Kindred, Shen
    "Primordian NOVA Reroll": {
        "lv4": {
            "Rek'Sai":  "A3",
            "Caitlyn":  "D6",
            "Briar":    "B3",
            "Akali":    "B5",
        },
        "lv7": {
            "Rek'Sai":  "A3",
            "Caitlyn":  "D5",
            "Bel'Veth": "C5",
            "Akali":    "B3",
            "Maokai":   "A1",
            "Briar":    "B5",
            "Aatrox":   "A5",
        },
        "lv9": {
            "Kindred":  "D7",   # NOVA/Challenger AS carry corner
            "Caitlyn":  "D5",   # NOVA/Fateweaver ranged carry
            "Bel'Veth": "C5",   # Primordian/Challenger AS carry mid
            "Akali":    "B5",   # NOVA/Marauder melee carry
            "Briar":    "B3",   # Anima/Primordian skirmisher
            "Aatrox":   "A1",   # NOVA/Bastion shredder left
            "Maokai":   "A3",   # NOVA/Brawler healer
            "Shen":     "A5",   # Bulwark/Bastion elite tank
            "Rek'Sai":  "A7",   # Primordian/Brawler tank right
        },
    },

    # ── PSIONIC ── (add complete positioning - was missing) ──────────────
    # lv9: Fiora, Shen, Sona, Master Yi, Morgana, Tahm Kench, The Mighty Mech, Gragas, Pyke
    "Psionic": {
        "lv4": {
            "Gragas":         "A3",
            "Akali":          "B3",
            "Bel'Veth":       "D6",
            "Rek'Sai":        "A1",
        },
        "lv7": {
            "Gragas":         "A3",
            "Viktor":         "D4",
            "Akali":          "B3",
            "Maokai":         "A1",
            "Bel'Veth":       "D6",
            "Rek'Sai":        "A5",
            "Master Yi":      "B5",
        },
        "lv9": {
            "Sona":           "D4",   # Commander/Psionic/Shepherd support near carries
            "Morgana":        "D6",   # Dark Lady AP utility
            "Pyke":           "C4",   # Psionic/Voyager utility
            "Fiora":          "B5",   # Divine Duelist melee carry right
            "Master Yi":      "B3",   # Psionic/Marauder melee carry center
            "The Mighty Mech":"A2",   # Mecha frontline (absorbs stats)
            "Gragas":         "A4",   # Psionic/Brawler AP frontline
            "Shen":           "A6",   # Bulwark/Bastion elite tank
            "Tahm Kench":     "A1",   # Oracle/Brawler utility tank left
        },
    },

    # ── STELLAR COMBO ── (add complete positioning - was missing) ─────────
    # lv9: Aatrox, Caitlyn, Shen, Poppy, Twisted Fate, Jax, Milio, Talon, Corki
    "Stellar Combo": {
        "lv4": {
            "Aatrox":       "A1",
            "Caitlyn":      "D7",
            "Poppy":        "A4",
            "Twisted Fate": "D5",
        },
        "lv7": {
            "Aatrox":       "A1",
            "Caitlyn":      "D7",
            "Shen":         "A5",
            "Poppy":        "A3",
            "Twisted Fate": "D5",
            "Jax":          "B3",
            "Milio":        "C4",
        },
        "lv9": {
            "Caitlyn":      "D7",   # NOVA/Fateweaver ranged carry corner
            "Corki":        "D5",   # Meeple/Fateweaver ranged carry
            "Twisted Fate": "D3",   # Stargazer/Fateweaver AP carry
            "Milio":        "C5",   # Timebreaker/Fateweaver support
            "Talon":        "B4",   # Stargazer/Rogue melee carry
            "Aatrox":       "A1",   # NOVA/Bastion frontline left
            "Poppy":        "A3",   # Meeple/Bastion tank
            "Shen":         "A5",   # Bulwark/Bastion elite tank
            "Jax":          "A7",   # Stargazer/Bastion tank right
        },
    },

    # ── CONTRACT KILLER ── (add complete positioning - was missing) ───────
    # lv9: Gragas, Pyke, Meepsie, Rammus, Corki, Poppy, Fizz, Karma, Bard
    "Contract Killer": {
        "lv4": {
            "Gragas":   "A3",
            "Pyke":     "B3",
            "Poppy":    "A1",
            "Fizz":     "D7",
        },
        "lv7": {
            "Gragas":   "A3",
            "Pyke":     "B4",
            "Meepsie":  "A6",
            "Rammus":   "A1",
            "Corki":    "D7",
            "Poppy":    "A4",
            "Fizz":     "B5",
        },
        "lv9": {
            "Corki":    "D7",   # Meeple/Fateweaver ranged carry corner
            "Bard":     "D4",   # Meeple/Conduit AP utility
            "Karma":    "C5",   # Dark Star/Voyager AP support
            "Meepsie":  "C3",   # Meeple/Shepherd support
            "Fizz":     "B5",   # Meeple/Rogue AP melee carry
            "Pyke":     "B3",   # Psionic/Voyager utility rogue
            "Gragas":   "A1",   # Psionic/Brawler AP frontline
            "Rammus":   "A4",   # Meeple/Bastion tank center
            "Poppy":    "A7",   # Meeple/Bastion tank right
        },
    },

    # ── SPACE GROOVE ── (add complete positioning - was missing) ──────────
    # lv9: Nami, Shen, Blitzcrank, Ornn, Gwen, Morgana, Bard, Karma, Leona
    "Space Groove": {
        "lv4": {
            "Gwen":       "B3",
            "Ornn":       "A3",
            "Nami":       "D7",
            "Blitzcrank": "A1",
        },
        "lv7": {
            "Nami":       "D7",
            "Shen":       "A5",
            "Blitzcrank": "A1",
            "Ornn":       "A3",
            "Gwen":       "B4",
            "Morgana":    "C5",
            "Bard":       "D4",
        },
        "lv9": {
            "Nami":       "D7",   # Space Groove/Replicator AP carry corner
            "Karma":      "D4",   # Dark Star/Voyager AP support
            "Bard":       "D2",   # Meeple/Conduit utility
            "Morgana":    "C5",   # Dark Lady AP utility
            "Gwen":       "B4",   # Space Groove/Rogue skirmisher carry
            "Blitzcrank": "A1",   # Party Animal/Space Groove/Vanguard hook utility LEFT
            "Leona":      "A3",   # Arbiter/Vanguard tank
            "Ornn":       "A5",   # Space Groove/Bastion tank
            "Shen":       "A7",   # Bulwark/Bastion elite tank right
        },
    },

    # ── JHIN CAP ── (add complete positioning - was missing) ─────────────
    # lv9: Bard, Jhin, Rammus, Graves, Blitzcrank, Morgana, Shen, Gnar, Mordekaiser
    "Jhin Cap": {
        "lv4": {
            "Gnar":       "D5",
            "Poppy":      "A1",
            "Rammus":     "A4",
            "Jhin":       "D7",
        },
        "lv7": {
            "Jhin":       "D7",
            "Rammus":     "A1",
            "Graves":     "D6",
            "Gnar":       "C5",
            "Shen":       "A4",
            "Morgana":    "C3",
            "Bard":       "D3",
        },
        "lv9": {
            "Jhin":       "D7",   # Dark Star/Eradicator/Sniper AD carry corner
            "Graves":     "D6",   # Factory New AD carry
            "Bard":       "D3",   # Meeple/Conduit AP utility
            "Gnar":       "C5",   # Meeple/Sniper ranged DPS mid
            "Morgana":    "C3",   # Dark Lady AP utility
            "Mordekaiser":"B3",   # Dark Star/Conduit/Vanguard brawler
            "Blitzcrank": "A1",   # Party Animal/Space Groove/Vanguard hook LEFT
            "Shen":       "A4",   # Bulwark/Bastion elite tank
            "Rammus":     "A7",   # Meeple/Bastion tank right
        },
    },

    # ── CARDS & CARTRIDGES ── (add complete positioning - was missing) ────
    # lv9: Aatrox, Caitlyn, Twisted Fate, Corki, Rammus, Jax, Milio, Poppy, Talon
    "Cards & Cartridges": {
        "lv4": {
            "Twisted Fate": "D5",
            "Aatrox":       "A1",
            "Caitlyn":      "D7",
            "Poppy":        "A4",
        },
        "lv7": {
            "Aatrox":       "A1",
            "Caitlyn":      "D7",
            "Twisted Fate": "D4",
            "Corki":        "D6",
            "Rammus":       "A3",
            "Jax":          "A5",
            "Milio":        "C4",
        },
        "lv9": {
            "Caitlyn":      "D7",   # NOVA/Fateweaver ranged carry corner
            "Corki":        "D6",   # Meeple/Fateweaver ranged carry
            "Twisted Fate": "D4",   # Stargazer/Fateweaver AP carry
            "Milio":        "C4",   # Timebreaker/Fateweaver support
            "Talon":        "B5",   # Stargazer/Rogue melee carry
            "Aatrox":       "A1",   # NOVA/Bastion shredder left
            "Rammus":       "A3",   # Meeple/Bastion tank
            "Jax":          "A5",   # Stargazer/Bastion tank
            "Poppy":        "A7",   # Meeple/Bastion tank right
        },
    },
}

# ===========================================================================
# UNIT LIST CORRECTIONS (lv9 unit lists that are wrong or incomplete)
# ===========================================================================
UNIT_LIST_CORRECTIONS = {
    # AP Vanguards: add Shen as 9th unit
    "AP Vanguards": {
        "lv9": ["Karma", "LeBlanc", "Nunu", "Illaoi", "Meepsie", "Mordekaiser", "Zoe", "Leona", "Shen"]
    },
    # Mecha: add Shen + Rammus as 8th and 9th units
    "Mecha": {
        "lv9": ["Bard", "Graves", "Aurelion Sol", "The Mighty Mech", "Maokai", "Urgot", "Akali", "Shen", "Rammus"]
    },
    # Rogue Reroll: add Talon as 9th unit for Rogue 4
    "Rogue Reroll": {
        "lv9": ["Fizz", "Kai'Sa", "Ornn", "Rhaast", "Karma", "Rammus", "Gwen", "Meepsie", "Talon"]
    },
}

# ===========================================================================
# APPLY ALL CORRECTIONS
# ===========================================================================
changes = []

for comp_name, pos_data in CORRECT_POSITIONING.items():
    if comp_name not in comps:
        print(f"WARNING: {comp_name} not in comps")
        continue
    existing = comps[comp_name].get("positioning", {})
    comps[comp_name]["positioning"] = {**existing, **pos_data}
    changes.append(f"Updated positioning for {comp_name}")

for comp_name, corrections in UNIT_LIST_CORRECTIONS.items():
    if comp_name not in comps:
        continue
    for field, value in corrections.items():
        old = comps[comp_name].get(field)
        comps[comp_name][field] = value
        changes.append(f"Fixed {comp_name}.{field}: {len(old) if old else 0} → {len(value)} units")

# Write back
META.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"Done. {len(changes)} changes applied:")
for c in changes:
    print(f"  - {c}")
