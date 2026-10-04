"""rebuild_sim_fixtures.py - emit the canonical 26-fixture set for dev preview.

Categories (per user spec 2026-04-25):
  SR              * 3 (early / mid / late)
  ARAM            * 3 (early / mid / late)
  ARAM Mayhem     * 3 (early / mid / late)
  Arena           * 3 (early / mid / late)
  Brawl           * 3 (early / mid / late)
  TFT             * 3 (early / mid / late)
  Aftergame       * 2 (victory / defeat)
  Session digest  * 2 (cold streak / hot streak)
  Client idle     * 1 (no game, no champ select)
  Client champ-select Ranked SR        * 1
  Client champ-select ARAM Mayhem      * 1
  Client loading-screen (transition)   * 1

Existing fixture files are LEFT IN PLACE - this script only writes the 26
canonical files + manifest.json. Old files (sr_clash_brawl, sr_jungle_gank,
stress_*, etc.) remain on disk but drop out of the dev-preview dropdown
since they're no longer in the manifest.
"""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SIM_DIR = ROOT / "data" / "sim"
SIM_DIR.mkdir(parents=True, exist_ok=True)


# -- Position presets (normalized 0..1, top-left origin) --------------------
# SR - full Summoner's Rift coords; allies on blue side (bottom-left).
_SR_ALLY_POSITIONS = {
    "early": {  # laning phase - everyone roughly on lane
        "Ahri":   [0.50, 0.50], "LeeSin": [0.40, 0.62], "Sion":   [0.18, 0.30],
        "Jinx":   [0.66, 0.82], "Nami":   [0.62, 0.82],
    },
    "mid": {    # grouping for objective
        "Ahri":   [0.55, 0.55], "LeeSin": [0.62, 0.60], "Sion":   [0.58, 0.50],
        "Jinx":   [0.60, 0.62], "Nami":   [0.58, 0.62],
    },
    "late": {   # baron sweep / soul fight cooldown
        "Ahri":   [0.40, 0.32], "LeeSin": [0.38, 0.30], "Sion":   [0.42, 0.30],
        "Jinx":   [0.38, 0.36], "Nami":   [0.40, 0.34],
    },
}
_SR_ENEMY_POSITIONS = {
    "early": {
        "Zed":    [0.55, 0.45], "Graves": [0.58, 0.42], "Darius": [0.78, 0.20],
        "Kaisa":  [0.32, 0.18], "Thresh": [0.30, 0.22],
    },
    "mid": {
        "Zed":    [0.50, 0.42], "Graves": [0.40, 0.42], "Darius": [0.42, 0.40],
        "Kaisa":  [0.45, 0.45], "Thresh": [0.46, 0.44],
    },
    "late": {
        "Zed":    [0.55, 0.40], "Graves": [0.58, 0.42], "Darius": [0.50, 0.40],
        "Kaisa":  [0.55, 0.42], "Thresh": [0.52, 0.40],
    },
}
# ARAM - Howling Abyss is a single bridge; positions cluster along it.
_ARAM_ALLY_POSITIONS = {
    "early": {
        "Zeri": [0.36, 0.55], "Sion": [0.34, 0.50], "Yone": [0.38, 0.48],
        "Karma": [0.32, 0.55], "Nami": [0.30, 0.58],
    },
    "mid": {
        "Zeri": [0.55, 0.46], "Sion": [0.58, 0.42], "Yone": [0.56, 0.40],
        "Karma": [0.52, 0.46], "Nami": [0.50, 0.48],
    },
    "late": {
        "Zeri": [0.74, 0.30], "Sion": [0.78, 0.26], "Yone": [0.76, 0.28],
        "Karma": [0.72, 0.32], "Nami": [0.70, 0.34],
    },
}
_ARAM_ENEMY_POSITIONS = {
    "early": {
        "Karthus": [0.62, 0.42], "Pyke": [0.65, 0.38], "Vladimir": [0.60, 0.45],
        "Lucian": [0.66, 0.40], "Heimerdinger": [0.68, 0.36],
    },
    "mid": {
        "Karthus": [0.62, 0.40], "Pyke": [0.65, 0.36], "Vladimir": [0.60, 0.42],
        "Lucian": [0.66, 0.38], "Heimerdinger": [0.68, 0.34],
    },
    "late": {
        "Karthus": [0.85, 0.18], "Pyke": [0.86, 0.16], "Vladimir": [0.84, 0.20],
        "Lucian": [0.87, 0.16], "Heimerdinger": [0.85, 0.20],
    },
}
_MAYHEM_ALLY_POSITIONS = {
    "early": {
        "Tristana": [0.36, 0.55], "Sion": [0.34, 0.50], "Yasuo": [0.38, 0.48],
        "Lulu": [0.32, 0.55], "Soraka": [0.30, 0.58],
    },
    "mid": {
        "Tristana": [0.55, 0.46], "Sion": [0.58, 0.42], "Yasuo": [0.56, 0.40],
        "Lulu": [0.52, 0.46], "Soraka": [0.50, 0.48],
    },
    "late": {
        "Tristana": [0.74, 0.30], "Sion": [0.78, 0.26], "Yasuo": [0.76, 0.28],
        "Lulu": [0.72, 0.32], "Soraka": [0.70, 0.34],
    },
}
_MAYHEM_ENEMY_POSITIONS = {
    "early": {
        "Yone": [0.62, 0.42], "Heimerdinger": [0.65, 0.38], "Senna": [0.60, 0.45],
        "Akali": [0.66, 0.40], "Olaf": [0.68, 0.36],
    },
    "mid": {
        "Yone": [0.62, 0.40], "Heimerdinger": [0.65, 0.36], "Senna": [0.60, 0.42],
        "Akali": [0.66, 0.38], "Olaf": [0.68, 0.34],
    },
    "late": {
        "Yone": [0.85, 0.18], "Heimerdinger": [0.86, 0.16], "Senna": [0.84, 0.20],
        "Akali": [0.87, 0.16], "Olaf": [0.85, 0.20],
    },
}


# -- Helpers ----------------------------------------------------------------
def _health(mode: str, *, has_game: bool = True,
            aram=False, arena=False, brawl=False, tft=False) -> dict:
    p = {"pid": 99999, "alive": True, "has_game": has_game,
         "mode": mode, "last_reload_ok": True}
    if aram:  p["aram_mode"]  = True
    if arena: p["arena_mode"] = True
    if brawl: p["brawl_mode"] = True
    if tft:   p["tft_mode"]   = True
    return {"type": "health", "source": "sim", "payload": p}


def _state(mode: str, source: str, payload: dict) -> dict:
    return {"type": "state", "mode": mode, "source": source, "payload": payload}


def _write(name: str, fixture: dict) -> None:
    out = SIM_DIR / f"{name}.json"
    # AUDIT 2026-04-28 (deferred-low-value): atomic so an interrupted
    # rebuild leaves the previous fixture intact instead of a partial.
    from core.polled_json import atomic_write_json
    atomic_write_json(out, fixture)


# -- SR (3) -----------------------------------------------------------------
FIXTURES = {}

FIXTURES["sr_early"] = {
    "meta": {"name": "sr_early", "label": "SR \xb7 early laning \xb7 4:30",
             "mode": "sr",
             "summary": "Early laning \xb7 Ahri mid \xb7 wave-crash + ward river before Drake 1"},
    "health": _health("sr"),
    "state": _state("sr", "aram_coaching_data.json", {
        "game_time": "04:30", "game_time_s": 270, "kda": "0/0/1",
        "cs": 32, "gold": 880, "level": 4, "vision_score": 3,
        "hp_pct": 88, "mp_pct": 91, "champion": "Ahri",
        "lane": "MID",
        "action": "Shove wave, ward river",
        "immediate": "Next wave is yours - crash then place river ward bush-side",
        "risk": "Jungle pathing toward mid after Drake scuttle",
        "fight_rule": "No all-in without flash up on Zed",
        "reset_item": "Dark Seal + Refillable (400g)",
        "next": "Push 5 \u2192 recall \u2192 950 gold for Lost Chapter spike",
        "objective": "First Drake spawns 5:00 - vision contest",
        "positioning": "Mid lane, near river bush for safe ward",
        "wave_pct": 45,
        "wave_top": 28, "wave_mid": 55, "wave_bot": 50,
        "items_display": "Doran's Ring, Refillable Potion, Stealth Ward",
        "item_build": "Lost Chapter \u2192 Luden's Echo \u2192 Sorcerer's Shoes",
        "ally_spells": {"Ahri": [{"spell": "Flash", "cd_s": 0},
                                  {"spell": "Teleport", "cd_s": 0}]},
        "ally_comp":  ["Ahri", "LeeSin", "Sion", "Jinx", "Nami"],
        "enemy_comp": ["Zed", "Graves", "Darius", "Kaisa", "Thresh"],
        "dragon_state": "First spawns 5:00 - contest vision",
        "baron_state": "-", "herald_state": "spawns 14:00",
        "atakhan_state": "-",
        "towers_us": 11, "towers_them": 11, "score": "0-0",
        "team_gold_diff": 180, "win_pct": 50,
    }),
}

FIXTURES["sr_mid"] = {
    "meta": {"name": "sr_mid", "label": "SR \xb7 mid-game \xb7 18:30 Drake 2",
             "mode": "sr",
             "summary": "Mid-game \xb7 Ahri 5/2/4 \xb7 Drake 2 setup, vs Zed, vision sweep before contest"},
    "health": _health("sr"),
    "state": _state("sr", "aram_coaching_data.json", {
        "game_time": "18:30", "game_time_s": 1110, "kda": "5/2/4",
        "cs": 168, "gold": 1820, "level": 12, "vision_score": 11,
        "hp_pct": 64, "mp_pct": 73, "champion": "Ahri",
        "lane": "MID",
        "wave_top": 67, "wave_mid": 25, "wave_bot": 45,
        "action": "Sweep deep, prep Drake 2",
        "immediate": "Charm + R into bot brush - clear vision then collapse with jungle",
        "risk": "Zed has level-13 R + Goredrinker timing - group, no solo",
        "fight_rule": "Engage on Zed shadow; never face-check unwarded",
        "reset_item": "Sorc shoes done; Shadowflame next (1280g away)",
        "next": "Drake 2 fight at 19:00 - sweep then Sion engage",
        "objective": "Drake 2 spawns 19:00 - soul point matters at this rate",
        "positioning": "Mid-side river, behind Sion frontline",
        "wave_pct": 60,
        "items_display": "Lost Chapter, Sorc Shoes, Blasting Wand, Stealth Ward",
        "item_build": "Luden's Echo \u2192 Shadowflame \u2192 Rabadon's",
        "item_build_reasons": {
            "Shadowflame": "Zed builds Eclipse - Shadowflame burst > Zhonya at this gold",
            "Rabadon's": "Snowball with team gold lead",
        },
        "ally_spells": {"Ahri": [{"spell": "Flash", "cd_s": 142},
                                  {"spell": "Teleport", "cd_s": 0}]},
        "ally_comp":  ["Ahri", "LeeSin", "Sion", "Jinx", "Nami"],
        "enemy_comp": ["Zed", "Graves", "Darius", "Kaisa", "Thresh"],
        "dragon_state": "1-1 \xb7 cloud + ocean \xb7 soul next",
        "baron_state": "spawns 20:00", "herald_state": "-",
        "atakhan_state": "-",
        "towers_us": 9, "towers_them": 8, "score": "12-9",
        "team_gold_diff": 2400, "win_pct": 62,
    }),
}

FIXTURES["sr_late"] = {
    "meta": {"name": "sr_late", "label": "SR \xb7 late \xb7 32:15 Soul fight cooldown",
             "mode": "sr",
             "summary": "Late \xb7 11/4/7 \xb7 Soul fight on cooldown, Baron up at 33:00, 18% HP disengage"},
    "health": _health("sr"),
    "state": _state("sr", "aram_coaching_data.json", {
        "game_time": "32:15", "game_time_s": 1935, "kda": "11/4/7",
        "cs": 268, "gold": 2940, "level": 17, "vision_score": 28,
        "hp_pct": 18, "mp_pct": 41, "champion": "Ahri",
        "lane": "MID",
        "wave_top": 88, "wave_mid": 50, "wave_bot": 72,
        "action": "DISENGAGE - back, then Baron",
        "immediate": "Zed R up. Don't face-check. Chrono back, regroup at mid inhib then sweep Baron pit at 32:50.",
        "risk": "Zed flank \u2192 100\u21920 in one combo from 18% HP. Stay deep behind Sion.",
        "fight_rule": "No fights without 3+ allies + Sion ult",
        "reset_item": "Already full-build (Luden's, Shadowflame, Rabadon's, Zhonya's, Sorcs, Void)",
        "next": "Baron 33:00 - sweep, smite priority Lee",
        "objective": "Baron up 33:00 \xb7 Soul on CD until 35:00",
        "positioning": "Behind Sion, at mid inhib \xb7 NOT in pit yet",
        "wave_pct": 80,
        "items_display": "Luden's Echo, Shadowflame, Rabadon's, Zhonya's Hourglass, Sorc Shoes, Void Staff",
        "item_build": "FULL BUILD - sell Sorc Shoes for Hexdrinker if vs Kaisa burst becomes the threat",
        "ally_spells": {"Ahri": [{"spell": "Flash", "cd_s": 38},
                                  {"spell": "Teleport", "cd_s": 0}]},
        "ally_comp":  ["Ahri", "LeeSin", "Sion", "Jinx", "Nami"],
        "enemy_comp": ["Zed", "Graves", "Darius", "Kaisa", "Thresh"],
        "dragon_state": "3-2 \xb7 soul taken (cloud) \xb7 CD until 35:00",
        "baron_state": "spawns 33:00 - sweep then engage",
        "herald_state": "-", "atakhan_state": "-",
        "towers_us": 6, "towers_them": 4, "score": "32-22",
        "team_gold_diff": 7800, "win_pct": 73,
    }),
}


# -- ARAM regular (3) -------------------------------------------------------
def _aram_state(payload):
    return _state("aram", "aram_coaching_data.json", payload)


FIXTURES["aram_early"] = {
    "meta": {"name": "aram_early", "label": "ARAM \xb7 early \xb7 3:15 first poke",
             "mode": "aram",
             "summary": "Early ARAM \xb7 Zeri \xb7 first item building, low HP from poke skirmish"},
    "health": _health("aram", aram=True),
    "state": _aram_state({
        "game_time": "03:15", "game_time_s": 195, "kda": "1/0/2",
        "cs": 22, "gold": 1180, "level": 5, "vision_score": 0,
        "hp_pct": 42, "mp_pct": 58, "champion": "Zeri",
        "game_mode": "ARAM",
        "action": "Hold mid \xb7 poke from max range",
        "immediate": "Don't side-step into Karthus E range. Auto-W from behind minions.",
        "risk": "Karthus has Q stacks \xb7 1300g away from Liandry - burst window opens at first item",
        "fight_rule": "Stay 700+ from Karthus \xb7 never near Pyke hook range",
        "reset_item": "Statikk Shiv (2900g) - first-back priority",
        "next": "Push wave, recall at 100% HP for shop",
        "positioning": "Mid lane, behind Sion, range advantage",
        "wave_pct": 50,
        "hp_packs": "both up \xb7 last 0:25 ago",
        "items_display": "Doran's Blade, Refillable Potion, Long Sword",
        "item_build": "Statikk Shiv \u2192 Berserker's Greaves \u2192 Navori Quickblades",
        "augments": "",
        "ally_spells": {"Zeri": [{"spell": "Flash", "cd_s": 0},
                                  {"spell": "Mark", "cd_s": 0}]},
        "ally_comp":  ["Zeri", "Sion", "Yone", "Karma", "Nami"],
        "enemy_comp": ["Karthus", "Pyke", "Vladimir", "Lucian", "Heimerdinger"],
        "my_team": "ORDER", "my_tower_hp": 100, "enemy_tower_hp": 100,
    }),
}

FIXTURES["aram_mid"] = {
    "meta": {"name": "aram_mid", "label": "ARAM \xb7 mid \xb7 11:40 first inhib",
             "mode": "aram",
             "summary": "Mid ARAM \xb7 Zeri \xb7 2-item spike, sieging first tower, full HP"},
    "health": _health("aram", aram=True),
    "state": _aram_state({
        "game_time": "11:40", "game_time_s": 700, "kda": "8/3/12",
        "cs": 76, "gold": 2410, "level": 13, "vision_score": 0,
        "hp_pct": 92, "mp_pct": 76, "champion": "Zeri",
        "game_mode": "ARAM",
        "action": "Siege turret \xb7 Q-W-Q from range",
        "immediate": "Sion ulted in - burst Karthus first while he's CC'd then back off Pyke",
        "risk": "Pyke E reset is 35s - keep 1 dash for it",
        "fight_rule": "Burst Karthus first \xb7 stay 600+ from Pyke",
        "reset_item": "200g from Navori - finish before next push",
        "next": "Crash inhibitor at 13:00 if outer tower falls",
        "positioning": "Behind Sion \xb7 max range from Karthus",
        "wave_pct": 70,
        "hp_packs": "ours 0:32 \xb7 theirs 1:14",
        "items_display": "Statikk Shiv, Berserker's Greaves, Long Sword, Long Sword",
        "item_build": "Navori Quickblades \u2192 Bloodthirster \u2192 Infinity Edge",
        "augments": "",
        "ally_spells": {"Zeri": [{"spell": "Flash", "cd_s": 88},
                                  {"spell": "Mark", "cd_s": 0}]},
        "ally_comp":  ["Zeri", "Sion", "Yone", "Karma", "Nami"],
        "enemy_comp": ["Karthus", "Pyke", "Vladimir", "Lucian", "Heimerdinger"],
        "my_team": "ORDER", "my_tower_hp": 100, "enemy_tower_hp": 22,
    }),
}

FIXTURES["aram_late"] = {
    "meta": {"name": "aram_late", "label": "ARAM \xb7 late \xb7 22:18 nexus turret",
             "mode": "aram",
             "summary": "Late ARAM \xb7 Zeri full-build \xb7 sieging nexus turrets, 2 enemies dead"},
    "health": _health("aram", aram=True),
    "state": _aram_state({
        "game_time": "22:18", "game_time_s": 1338, "kda": "16/5/22",
        "cs": 184, "gold": 1410, "level": 18, "vision_score": 0,
        "hp_pct": 78, "mp_pct": 65, "champion": "Zeri",
        "game_mode": "ARAM",
        "action": "Push for nexus - burst then back",
        "immediate": "Karthus + Pyke dead. Push nexus turret while they respawn (14s window).",
        "risk": "Vladimir R about to come up - back behind Sion if you see it",
        "fight_rule": "Force trade only with Sion ult up \xb7 respect Pyke flank",
        "reset_item": "FULL BUILD - sell Boots \u2192 Mortal Reminder if Vlad becomes 100% HP",
        "next": "Nexus break \xb7 1-2 turret swings then back",
        "positioning": "Pit edge \xb7 Sion frontlining",
        "wave_pct": 95,
        "hp_packs": "ours up \xb7 theirs 1:48",
        "items_display": "Navori Quickblades, Bloodthirster, Infinity Edge, Phantom Dancer, Berserker's Greaves, Mortal Reminder",
        "item_build": "(full build \xb7 sell Greaves for Lord Dominik's vs Mundo)",
        "augments": "",
        "ally_spells": {"Zeri": [{"spell": "Flash", "cd_s": 12},
                                  {"spell": "Mark", "cd_s": 0}]},
        "ally_comp":  ["Zeri", "Sion", "Yone", "Karma", "Nami"],
        "enemy_comp": ["Karthus", "Pyke", "Vladimir", "Lucian", "Heimerdinger"],
        "my_team": "ORDER", "my_tower_hp": 70, "enemy_tower_hp": 0,
    }),
}


# -- ARAM Mayhem (3) --------------------------------------------------------
FIXTURES["aram_mayhem_early"] = {
    "meta": {"name": "aram_mayhem_early", "label": "ARAM Mayhem \xb7 early \xb7 3:20 augment 1",
             "mode": "aram",
             "summary": "Mayhem early \xb7 Tristana \xb7 first augment + Limited Shopping rule"},
    "health": _health("aram", aram=True),
    "state": _aram_state({
        "game_time": "03:20", "game_time_s": 200, "kda": "2/0/1",
        "cs": 18, "gold": 1320, "level": 5, "vision_score": 0,
        "hp_pct": 88, "mp_pct": 92, "champion": "Tristana",
        "game_mode": "Mayhem",
        "action": "Auto-poke \xb7 stack Q",
        "immediate": "Limited Shopping is on - only buy when explicitly recalled. Plan a single-item back at 1700g.",
        "risk": "Yone E \u2192 R combo at level 6 - keep W up to disengage",
        "fight_rule": "Hold range \xb7 stack Q before fights",
        "reset_item": "Bork (3000g) - single-item Limited-Shopping back",
        "next": "Push minion 4 \u2192 recall, plan one-shot Bork",
        "positioning": "Mid \xb7 Sion in front, Tristana max range",
        "wave_pct": 50,
        "hp_packs": "both up",
        "items_display": "Doran's Blade, Refillable Potion, Long Sword",
        "item_build": "Bork \u2192 Berserker's \u2192 Phantom Dancer",
        "augments": "Limited Shopping, Platform Regen Disabled",
        "ally_spells": {"Tristana": [{"spell": "Flash", "cd_s": 0},
                                       {"spell": "Heal", "cd_s": 0}]},
        "ally_comp":  ["Tristana", "Sion", "Yasuo", "Lulu", "Soraka"],
        "enemy_comp": ["Yone", "Heimerdinger", "Senna", "Akali", "Olaf"],
        "my_team": "ORDER", "my_tower_hp": 100, "enemy_tower_hp": 100,
    }),
}

FIXTURES["aram_mayhem_mid"] = {
    "meta": {"name": "aram_mayhem_mid", "label": "ARAM Mayhem \xb7 mid \xb7 10:30 augment pick",
             "mode": "aram",
             "summary": "Mayhem mid \xb7 Tristana \xb7 5k-gold augment select active (3 cards offered)"},
    "health": _health("aram", aram=True),
    "state": _aram_state({
        "game_time": "10:30", "game_time_s": 630, "kda": "7/2/9",
        "cs": 64, "gold": 5240, "level": 12, "vision_score": 0,
        "hp_pct": 65, "mp_pct": 70, "champion": "Tristana",
        "game_mode": "Mayhem",
        "action": "PICK AUGMENT - Goldrend",
        "immediate": "5k gold milestone hit. Goldrend > Fan The Hammer for your build path. Burst > sustained.",
        "risk": "Yone has Crit augment - Bork must come before this fight at 11:00",
        "fight_rule": "Don't fight until augment picked + Bork bought",
        "reset_item": "Bork (1400g remaining)",
        "next": "Buy Bork \u2192 siege first tower at 11:30",
        "positioning": "Behind Sion \xb7 disengage with W if Yasuo windwalls",
        "wave_pct": 60,
        "hp_packs": "ours up \xb7 theirs 0:40",
        "items_display": "Long Sword, Long Sword, Berserker's Greaves, Refillable",
        "item_build": "Bork \u2192 Phantom Dancer \u2192 Infinity Edge",
        "augments": "Limited Shopping, Platform Regen Disabled",
        "augment_select": True,
        "augment_choices": [
            "Goldrend - Damage attacks deal +50-150 magic damage, grants gold + MS for 1.5s",
            "Fan The Hammer - Attacks fire 5 extra Firecrackers, each direction has its own CD",
            "Draw Your Sword - Become melee, gain AD/HP/AS/Lifesteal/MS scaling with range given up",
        ],
        "ally_spells": {"Tristana": [{"spell": "Flash", "cd_s": 0},
                                       {"spell": "Heal", "cd_s": 0}]},
        "ally_comp":  ["Tristana", "Sion", "Yasuo", "Lulu", "Soraka"],
        "enemy_comp": ["Yone", "Heimerdinger", "Senna", "Akali", "Olaf"],
        "my_team": "ORDER", "my_tower_hp": 100, "enemy_tower_hp": 8,
    }),
}

FIXTURES["aram_mayhem_late"] = {
    "meta": {"name": "aram_mayhem_late", "label": "ARAM Mayhem \xb7 late \xb7 18:50 nexus push",
             "mode": "aram",
             "summary": "Mayhem late \xb7 Tristana 13/4/14 \xb7 all 3 augments stacked, sieging nexus"},
    "health": _health("aram", aram=True),
    "state": _aram_state({
        "game_time": "18:50", "game_time_s": 1130, "kda": "13/4/14",
        "cs": 142, "gold": 800, "level": 18, "vision_score": 0,
        "hp_pct": 81, "mp_pct": 64, "champion": "Tristana",
        "game_mode": "Mayhem",
        "action": "Push nexus turret 2",
        "immediate": "Yone + Heimer dead. 2v5 advantage for 12s - break nexus turret 2 then back",
        "risk": "Olaf might Flash-engage when respawn; W is up so safe",
        "fight_rule": "Burst Senna first if she walks \xb7 don't chase past nexus turrets",
        "reset_item": "Mortal Reminder vs Olaf %max-HP burn (sell Refillable)",
        "next": "Open nexus \xb7 win condition met",
        "positioning": "Backline \xb7 behind Sion, max range on turret",
        "wave_pct": 95,
        "hp_packs": "-",
        "items_display": "Bork, Phantom Dancer, Infinity Edge, Berserker's Greaves, Bloodthirster, Long Sword",
        "item_build": "(near full \xb7 Long Sword \u2192 Mortal Reminder)",
        "augments": "Limited Shopping, Platform Regen Disabled, Goldrend, Fan The Hammer",
        "ally_spells": {"Tristana": [{"spell": "Flash", "cd_s": 88},
                                       {"spell": "Heal", "cd_s": 0}]},
        "ally_comp":  ["Tristana", "Sion", "Yasuo", "Lulu", "Soraka"],
        "enemy_comp": ["Yone", "Heimerdinger", "Senna", "Akali", "Olaf"],
        "my_team": "ORDER", "my_tower_hp": 60, "enemy_tower_hp": 0,
    }),
}


# -- Arena (3) --------------------------------------------------------------
def _arena_state(payload):
    return _state("arena", "arena_coaching_data.json", payload)


FIXTURES["arena_early"] = {
    "meta": {"name": "arena_early", "label": "Arena \xb7 early \xb7 Round 2 Samira",
             "mode": "arena",
             "summary": "Arena early \xb7 Samira+Taric \xb7 first augment picked, second incoming"},
    "health": _health("arena", arena=True),
    "state": _arena_state({
        "game_time": "-", "game_time_s": 0, "kda": "-",
        "champion": "Samira", "round": 2, "rank": 3, "alive_teams": 4,
        "wins": 1, "losses": 0,
        "action": "2v2 vs Yasuo+Soraka - engage on cooldowns",
        "immediate": "Taric R into Samira W \u2192 R combo. Yasuo windwall the W. Soraka silenced first.",
        "risk": "Yasuo has Conqueror augment - full-stack threat by mid-game",
        "fight_rule": "Engage when Yasuo Q is down \xb7 never face-check windwall",
        "reset_item": "-",
        "next": "Win this round \u2192 augment 2 selection at end",
        "objective": "Pick prismatic augment after this round (likely AD-scaling)",
        "positioning": "Stick to Taric \xb7 Samira W radius around him",
        "augments": ["Cosmic Insight"],
        "anvil_advice": "Save 500g for prismatic anvil at round 4",
        "items_display": "Long Sword, Vampiric Scepter, Refillable",
        "item_build": "Bloodthirster \u2192 Phantom Dancer",
        "partner": "Taric",
        "ally_comp": ["Samira", "Taric"],
        "enemy_comp": ["Yasuo", "Soraka"],
        "ally_spells": {"Samira": [{"spell": "Flash", "cd_s": 0},
                                     {"spell": "Heal", "cd_s": 0}]},
    }),
}

FIXTURES["arena_mid"] = {
    "meta": {"name": "arena_mid", "label": "Arena \xb7 mid \xb7 Round 5 augment pick",
             "mode": "arena",
             "summary": "Arena mid \xb7 Samira+Taric \xb7 2nd augment selection, 4 alive teams"},
    "health": _health("arena", arena=True),
    "state": _arena_state({
        "game_time": "-", "game_time_s": 0, "kda": "-",
        "champion": "Samira", "round": 5, "rank": 2, "alive_teams": 3,
        "wins": 3, "losses": 1,
        "action": "PICK AUGMENT - Apex Inventor",
        "immediate": "Apex Inventor > Castle Forged here - your build wants AS, not tank stats",
        "risk": "Vs Tryndamere+Karthus next - Tryndamere R + Karthus R is a 1-shot timer",
        "fight_rule": "Burst Karthus first \xb7 don't fight Trynd at 0 HP",
        "reset_item": "Anvil time - buy prismatic next round",
        "next": "Round 6: Trynd+Karth - focus Karth, kite Trynd",
        "objective": "Augment pick: Apex Inventor (attack-speed prismatic)",
        "positioning": "Stay 700+ from Karthus \xb7 use Taric R offensively",
        "augments": ["Cosmic Insight", "Restless Restoration"],
        "augment_select": True,
        "augment_choices": [
            "Apex Inventor - gain attack speed each takedown, stacks indefinitely",
            "Castle Forged - gain bonus armor + magic resist, scales with rounds played",
            "Holy Fire - basic attacks burn 4% max HP over 3s",
        ],
        "anvil_advice": "After this augment buy Bloodthirster on next anvil",
        "items_display": "Long Sword, Vampiric Scepter, Berserker's Greaves",
        "item_build": "Bloodthirster \u2192 Phantom Dancer \u2192 Infinity Edge",
        "partner": "Taric",
        "ally_comp": ["Samira", "Taric"],
        "enemy_comp": ["Tryndamere", "Karthus"],
        "ally_spells": {"Samira": [{"spell": "Flash", "cd_s": 22},
                                     {"spell": "Heal", "cd_s": 0}]},
    }),
}

FIXTURES["arena_late"] = {
    "meta": {"name": "arena_late", "label": "Arena \xb7 late \xb7 Round 8 finale",
             "mode": "arena",
             "summary": "Arena late \xb7 Samira+Taric vs Briar+Lux finals \xb7 all 3 augments stacked"},
    "health": _health("arena", arena=True),
    "state": _arena_state({
        "game_time": "-", "game_time_s": 0, "kda": "-",
        "champion": "Samira", "round": 8, "rank": 1, "alive_teams": 2,
        "wins": 5, "losses": 1,
        "action": "FINAL \xb7 Burst Lux first",
        "immediate": "Briar will tunnel - Taric stuns her, Samira full-combos Lux. Heal Briar's bite at low HP.",
        "risk": "Lux R + ignite is a 1-shot if you eat the snare",
        "fight_rule": "Side-step Lux Q \xb7 never line up with Taric for double-hit",
        "reset_item": "-",
        "next": "Win this round = 1st place, +200 LP",
        "objective": "Finals \xb7 close out Lux first",
        "positioning": "Sidestep Lux Q \xb7 weave around Briar charge",
        "augments": ["Cosmic Insight", "Restless Restoration", "Apex Inventor"],
        "anvil_advice": "Final anvil - Quicksilver Sash for Briar fear",
        "items_display": "Bloodthirster, Phantom Dancer, Infinity Edge, Berserker's Greaves, Mortal Reminder, Long Sword",
        "item_build": "(near full \xb7 Quicksilver Sash next anvil)",
        "partner": "Taric",
        "ally_comp": ["Samira", "Taric"],
        "enemy_comp": ["Briar", "Lux"],
        "ally_spells": {"Samira": [{"spell": "Flash", "cd_s": 8},
                                     {"spell": "Heal", "cd_s": 0}]},
    }),
}


# -- Brawl (3) --------------------------------------------------------------
def _brawl_state(payload):
    return _state("brawl", "brawl_coaching_data.json", payload)


FIXTURES["brawl_early"] = {
    "meta": {"name": "brawl_early", "label": "Brawl \xb7 early \xb7 2:10 first skirmish",
             "mode": "brawl",
             "summary": "Brawl early \xb7 Yasuo \xb7 first 4v4 contact, low HP from poke"},
    "health": _health("brawl", brawl=True),
    "state": _brawl_state({
        "game_time": "02:10", "game_time_s": 130, "kda": "1/0/2",
        "cs": 14, "gold": 980, "level": 4, "vision_score": 0,
        "hp_pct": 55, "mp_pct": 100, "champion": "Yasuo",
        "game_mode": "Brawl",
        "action": "Hold mid \xb7 stack passive",
        "immediate": "Wait for Karthus W to whiff - windwall is your engage cue",
        "risk": "Karthus stacking \xb7 2-min dive timer once he hits 6",
        "fight_rule": "Engage when Q3 ready + windwall \xb7 never chase past minions",
        "reset_item": "Berserker's (1100g away)",
        "next": "Push 5 \u2192 recall for Statikk Shiv",
        "objective": "Hold mid lane \xb7 don't lose tower under 9:00",
        "positioning": "Mid \xb7 stay behind Sett",
        "wave_pct": 50,
        "items_display": "Doran's Blade, Refillable, Long Sword",
        "item_build": "Statikk Shiv \u2192 Berserker's \u2192 Infinity Edge",
        "ally_spells": {"Yasuo": [{"spell": "Flash", "cd_s": 0},
                                    {"spell": "Heal", "cd_s": 0}]},
        "ally_comp":  ["Yasuo", "Sett", "Karma", "Nami"],
        "enemy_comp": ["Karthus", "Pyke", "Vladimir", "Heimerdinger"],
    }),
}

FIXTURES["brawl_mid"] = {
    "meta": {"name": "brawl_mid", "label": "Brawl \xb7 mid \xb7 8:30 contested objective",
             "mode": "brawl",
             "summary": "Brawl mid \xb7 Yasuo 5/2/3 \xb7 contested objective fight, full HP"},
    "health": _health("brawl", brawl=True),
    "state": _brawl_state({
        "game_time": "08:30", "game_time_s": 510, "kda": "5/2/3",
        "cs": 56, "gold": 2120, "level": 9, "vision_score": 0,
        "hp_pct": 88, "mp_pct": 100, "champion": "Yasuo",
        "game_mode": "Brawl",
        "action": "Engage on Karthus - he's out of position",
        "immediate": "Q3 \u2192 R the entire enemy team if Sett ult lands first. Don't go solo.",
        "risk": "Vlad pool dodge \xb7 don't waste R on him alone",
        "fight_rule": "Wait for Sett Q \xb7 then R 2+ enemies",
        "reset_item": "120g from IE - finish before regrouping",
        "next": "Take outer tower mid \xb7 group for 9:00 fight",
        "objective": "Contested objective fight at 9:00",
        "positioning": "Side \xb7 ready to flank with R",
        "wave_pct": 70,
        "items_display": "Statikk Shiv, Berserker's Greaves, Long Sword, B.F. Sword",
        "item_build": "Infinity Edge \u2192 Phantom Dancer \u2192 Bloodthirster",
        "ally_spells": {"Yasuo": [{"spell": "Flash", "cd_s": 56},
                                    {"spell": "Heal", "cd_s": 0}]},
        "ally_comp":  ["Yasuo", "Sett", "Karma", "Nami"],
        "enemy_comp": ["Karthus", "Pyke", "Vladimir", "Heimerdinger"],
    }),
}

FIXTURES["brawl_late"] = {
    "meta": {"name": "brawl_late", "label": "Brawl \xb7 late \xb7 14:25 endgame teamfight",
             "mode": "brawl",
             "summary": "Brawl late \xb7 Yasuo 11/3/8 \xb7 final teamfight, full build, nexus open"},
    "health": _health("brawl", brawl=True),
    "state": _brawl_state({
        "game_time": "14:25", "game_time_s": 865, "kda": "11/3/8",
        "cs": 132, "gold": 580, "level": 16, "vision_score": 0,
        "hp_pct": 70, "mp_pct": 100, "champion": "Yasuo",
        "game_mode": "Brawl",
        "action": "R into 4-man \xb7 Sett follows",
        "immediate": "Last fight before nexus. Q3 + R = teamwipe if Sett lands grab. Karthus passive will tick - finish nexus before he respawns.",
        "risk": "Karthus passive damage + Pyke ult reset chain",
        "fight_rule": "R 3+ enemies \xb7 never solo Pyke",
        "reset_item": "Mortal Reminder vs Vlad lifesteal (Long Sword + 700g)",
        "next": "End game \xb7 break nexus",
        "objective": "Endgame teamfight + nexus break",
        "positioning": "Flank from side bush",
        "wave_pct": 95,
        "items_display": "Infinity Edge, Phantom Dancer, Bloodthirster, Berserker's Greaves, Mortal Reminder, Long Sword",
        "item_build": "(full build)",
        "ally_spells": {"Yasuo": [{"spell": "Flash", "cd_s": 18},
                                    {"spell": "Heal", "cd_s": 0}]},
        "ally_comp":  ["Yasuo", "Sett", "Karma", "Nami"],
        "enemy_comp": ["Karthus", "Pyke", "Vladimir", "Heimerdinger"],
    }),
}


# -- TFT (3) ----------------------------------------------------------------
def _tft_state(payload):
    return _state("tft", "tft_coaching_data.json", payload)


FIXTURES["tft_early"] = {
    "meta": {"name": "tft_early", "label": "TFT \xb7 early \xb7 stage 2-2 econ",
             "mode": "tft",
             "summary": "TFT early \xb7 stage 2-2 \xb7 econ-roll path, 3 traits active"},
    "health": _health("tft", tft=True),
    "state": _tft_state({
        "game_time": "Stage 2-2", "game_time_s": 0,
        "level": 4, "gold": 22, "hp": 85,
        "round": "2-2", "stage": 2, "round_num": 2,
        "action": "Save \xb7 push to 30g interest cap",
        "immediate": "Don't roll. Open at 50g for 3-stars. Slam Spear of Shojin if you have components.",
        "risk": "Health 85 - comfortable; can econ to stage 4",
        "fight_rule": "Don't itemize duplicate components yet",
        "reset_item": "Spear of Shojin if components allow",
        "next": "Stage 3-1: roll only if uncontested \xb7 else push level",
        "objective": "Reach 50g + level 6 before rolling",
        "shop": "Caitlyn, Vex, Lulu, Wukong, Riven (refresh: 2g)",
        "augments": ["Cybernetic Implants", "Heart of the Lotus", "Pumping Up I"],
        "comp_synergy": "Sniper 2/3 \xb7 Inkshadow 2/4 \xb7 Heavenly 1/2",
        "board": "3\xd7 Caitlyn, 2\xd7 Wukong, 1\xd7 Lulu (4 units, level 4)",
        "items_display": "Sparring Gloves, Tear, Recurve Bow",
        "item_build": "Spear of Shojin \u2192 Last Whisper \u2192 Infinity Edge",
    }),
}

FIXTURES["tft_mid"] = {
    "meta": {"name": "tft_mid", "label": "TFT \xb7 mid \xb7 stage 4-2 combat",
             "mode": "tft",
             "summary": "TFT mid \xb7 stage 4-2 \xb7 comp 6/8 stable, top-4 positioning"},
    "health": _health("tft", tft=True),
    "state": _tft_state({
        "game_time": "Stage 4-2", "game_time_s": 0,
        "level": 7, "gold": 44, "hp": 52,
        "round": "4-2", "stage": 4, "round_num": 2,
        "action": "Slam Last Whisper \xb7 push level 8",
        "immediate": "Roll 30g for Aphelios 3-star \xb7 level 8 next round if 50+",
        "risk": "Health 52 - pushing level safely beats slow-rolling here",
        "fight_rule": "Position carry corner \xb7 tank 1 hex out",
        "reset_item": "Last Whisper on Aphelios",
        "next": "Stage 4-3 econ \xb7 4-4 fight key for top 4",
        "objective": "Stabilize top-4 with current 6 Sniper",
        "shop": "Aphelios\u2605\u2605, Caitlyn, Lillia, Setho, refresh 2g",
        "augments": ["Cybernetic Implants", "Heart of the Lotus", "Pumping Up I", "Trade Sector"],
        "comp_synergy": "Sniper 6/6 \xb7 Inkshadow 2/4 \xb7 Heavenly 3/4",
        "board": "Aphelios\u2605\u2605, Caitlyn\u2605\u2605\u2605, Vex\u2605\u2605, Wukong\u2605\u2605, Lulu\u2605, Setho\u2605, Lillia (7 units, level 7)",
        "items_display": "Spear of Shojin (Aphelios), Last Whisper (Aphelios), Recurve Bow",
        "item_build": "Last Whisper (Aphelios) \u2192 Infinity Edge \u2192 Bramble Vest tank",
    }),
}

FIXTURES["tft_late"] = {
    "meta": {"name": "tft_late", "label": "TFT \xb7 late \xb7 stage 6 finale",
             "mode": "tft",
             "summary": "TFT late \xb7 stage 6 \xb7 8-unit cap board, 1st-place fight"},
    "health": _health("tft", tft=True),
    "state": _tft_state({
        "game_time": "Stage 6-1", "game_time_s": 0,
        "level": 9, "gold": 72, "hp": 30,
        "round": "6-1", "stage": 6, "round_num": 1,
        "action": "1st-place fight - full board",
        "immediate": "Board uncontested. Don't change positions. Slam Bramble on Setho.",
        "risk": "Top 2 has identical comp \xb7 who positions better wins",
        "fight_rule": "Setho front-left \xb7 Aphelios back-right \xb7 tank line at hex 1",
        "reset_item": "-",
        "next": "Stage 6-2 finals",
        "objective": "1st place fight",
        "shop": "Aphelios (already 3\u2605), Setho, Lulu, Vex, refresh 2g",
        "augments": ["Cybernetic Implants", "Heart of the Lotus", "Pumping Up I", "Trade Sector"],
        "comp_synergy": "Sniper 6/6 \xb7 Inkshadow 4/4 \xb7 Heavenly 4/4 \xb7 Bruiser 2/4",
        "board": "Aphelios\u2605\u2605\u2605, Caitlyn\u2605\u2605\u2605, Vex\u2605\u2605\u2605, Wukong\u2605\u2605, Lulu\u2605\u2605, Setho\u2605\u2605\u2605, Lillia\u2605\u2605, Riven\u2605\u2605 (8 units, level 9)",
        "items_display": "Spear of Shojin, Last Whisper, Infinity Edge (all Aphelios), Bramble Vest, Warmog's, Quicksilver",
        "item_build": "(full \xb7 final slam Crownguard on Setho)",
    }),
}


# -- Aftergame (2) - preserve existing structure ---------------------------
# Both already exist on disk with rich content; copy them to the new
# canonical names and update their `meta.name` so the manifest entry
# matches the file name.
import shutil
for old in ("aftergame_victory", "aftergame_defeat"):
    src = SIM_DIR / f"{old}.json"
    if src.exists():
        d = json.loads(src.read_text(encoding="utf-8"))
        d.setdefault("meta", {})["name"] = old
        FIXTURES[old] = d


# -- Session digest (2) - cold streak + hot streak -------------------------
def _digest_state(streak_kind: str, **overrides) -> dict:
    base = {
        "game_time": "", "kda": "", "champion": "Ahri",
        "action": "",
        "immediate": "",
        "risk": "", "fight_rule": "-", "reset_item": "-",
        "next": "", "objective": "",
        "advice_headline": "", "advice_objective": "",
        "key_points_review": "", "clips_review": "",
    }
    if streak_kind == "cold":
        base.update({
            "action": "\u2744 COLD STREAK - pause recommended",
            "immediate": "Last 5 games: 0W-5L on Ahri vs Zed. Recent KDA 1.4 (baseline 2.9). Win-prob model says next-game expected outcome is sub-30%.",
            "risk": "Tilt window active \xb7 queue dodge / take 30 min break before requeue",
            "next": "Pause queue \xb7 review the loss patterns clips below",
            "objective": "Rank goal: stop the bleed \xb7 prevent \u2212LP cascade",
            "advice_headline": "Stop. Take a break. Re-queue when reset.",
            "advice_objective": "Cold streak: 5 losses, all on Ahri vs Zed lane",
            "key_points_review": "1. Don't take Ahri vs Zed (32% wr, 5 game sample) \xb7 2. Vision when behind: 8 wards avg vs 14 in winning games \xb7 3. Don't ult-engage at sub-50% HP",
            "clips_review": "5 deaths to Zed R-W-Q combo at full HP - re-watch positioning at 0:00-0:30 of each death",
            "digest_state": "alert", "digest_label": "\u2744 ALERT", "digest_state_long": "Cold streak - 5 game losing run",
            "digest_streak": "5L on Ahri", "digest_recent": "0W-5L last 5 \xb7 12% wr",
            "digest_kda_trend": "\u2193 KDA 1.4 (baseline 2.9, \u221252%)",
            "digest_time_of_day": "Late night plays (11pm-2am) trending \u221218% wr",
            "digest_fatigue": "5 games in 90 min - fatigue threshold crossed",
            "digest_advice": "Stop queue \xb7 break \u226530min \xb7 don't queue Ahri vs Zed",
            "what_went_good": ["Held own first 8 min in last game \xb7 6 CS lead by 6:00"],
            "what_went_bad": [
                "5 deaths to Zed R-W-Q at full HP - pattern over 5 games",
                "Vision: 8 wards avg vs 14 in winning games",
                "Mid lane prio lost in 4/5 games (lost first tower)",
                "Tilt indicator: response time +180ms vs baseline",
                "Late-night plays: 4 of 5 losses after 11pm",
            ],
        })
    else:  # hot
        base.update({
            "action": "\U0001f525 HOT STREAK - extend the run",
            "immediate": "5W-1L last 6. Recent KDA 4.4 (baseline 2.9). Climb pace: +14 LP/hr.",
            "risk": "Don't tilt-queue past 8 games \xb7 streaks reverse on fatigue",
            "next": "1-2 more games max \xb7 log out at +24 LP",
            "objective": "Rank goal: extend +14 LP/hr pace \xb7 cap at +24 today",
            "advice_headline": "Hot streak active - preserve, don't burn",
            "advice_objective": "Climb pace: +14 LP/hr \xb7 target +24 by EOD",
            "key_points_review": "1. Don't go for 4th game past 9pm \xb7 2. Stick to 70%+ wr matchups \xb7 3. Reset if you tilt-queue 1 loss",
            "clips_review": "Winning fights at 18:00-25:00 - outplays vs Zed in 3 games",
            "digest_state": "good", "digest_label": "\U0001f525 HOT", "digest_state_long": "Hot streak - 5W-1L",
            "digest_streak": "5W on Ahri", "digest_recent": "5W-1L last 6 \xb7 83% wr",
            "digest_kda_trend": "\u2191 KDA 4.4 (baseline 2.9, +52%)",
            "digest_time_of_day": "Peak window 7-9pm \xb7 play here for streak preservation",
            "digest_fatigue": "Comfortable \xb7 6 games in 2.5 hours",
            "digest_advice": "1-2 more games \xb7 log out at +24 LP today",
            "what_went_good": [
                "Burst Zed at 18:30 - read his all-in pattern",
                "5/6 games: lane lead at 8:00 (CS +12 avg)",
                "Vision score Challenger-tier: 14 wards/game",
                "Drake control: secured 4/5 games",
                "Skillshot accuracy Q 88% \xb7 charm 71% \xb7 R 4/5 hit",
            ],
            "what_went_bad": ["1 loss in 6 - vs Vladimir (avoid until matchup study)"],
        })
    base.update(overrides)
    return base


FIXTURES["session_cold_streak"] = {
    "meta": {"name": "session_cold_streak", "label": "Session \xb7 cold streak (5L)",
             "mode": "client",
             "summary": "Cold-streak digest \xb7 5 losses on Ahri vs Zed \xb7 break advisory active"},
    "health": _health("client", has_game=False),
    "state": _state("client", "coaching_data.json", _digest_state("cold")),
}

FIXTURES["session_hot_streak"] = {
    "meta": {"name": "session_hot_streak", "label": "Session \xb7 hot streak (5W)",
             "mode": "client",
             "summary": "Hot-streak digest \xb7 5W-1L on Ahri \xb7 climb pace +14 LP/hr"},
    "health": _health("client", has_game=False),
    "state": _state("client", "coaching_data.json", _digest_state("hot")),
}


# -- Client (4) -------------------------------------------------------------
FIXTURES["client_idle"] = {
    "meta": {"name": "client_idle", "label": "Client \xb7 idle (no game / no champ select)",
             "mode": "client",
             "summary": "Client open, not in game, not in champ select \xb7 placeholder slots"},
    "health": _health("client", has_game=False),
    "state": _state("client", "coaching_data.json", {
        "game_time": "", "kda": "", "champion": None,
        "action": "", "immediate": "Awaiting champ-select or queue \xb7 idle",
        "risk": "-", "fight_rule": "-", "reset_item": "-",
        "next": "", "objective": "",
        "items_display": "", "item_build": "", "augments": "",
    }),
}

FIXTURES["client_champselect_sr"] = {
    "meta": {"name": "client_champselect_sr",
             "label": "Client \xb7 champ select \xb7 Ranked SR",
             "mode": "client",
             "summary": "Pregame SR ranked \xb7 Ahri locked \xb7 matchup brief + start items + risk profile"},
    "health": _health("client", has_game=False),
    "state": _state("client", "coaching_data.json", {
        "game_time": "", "kda": "", "champion": "Ahri",
        "queue": "Ranked Solo/Duo \xb7 SR",
        "action": "Lock-in confirmed - pre-game brief",
        "immediate": "Vs Zed mid \xb7 early all-in matchup until level 6. Buy Doran's Ring + 2 pots. Conqueror runes.",
        "risk": "Zed level 6 all-in window 6:00-7:30 \xb7 keep flash up",
        "fight_rule": "Don't push past river ward without flash \xb7 ult only after his W is committed",
        "reset_item": "First-back: Lost Chapter (1300g) \xb7 skip boots until 2nd back",
        "next": "Spawn \u2192 1st wave at 1:30 \xb7 ward at 2:35",
        "objective": "Lane survival to level 6 \xb7 scale into mid-game power spike",
        "positioning": "Mid lane \xb7 safe behind ranged minions vs Zed Q",
        "items_display": "Doran's Ring, Refillable Potion, Stealth Ward",
        "item_build": "Lost Chapter \u2192 Luden's Echo \u2192 Sorcerer's Shoes \u2192 Shadowflame \u2192 Rabadon's",
        "ally_comp":  ["Ahri", "LeeSin", "Sion", "Jinx", "Nami"],
        "enemy_comp": ["Zed", "Graves", "Darius", "Kaisa", "Thresh"],
        "ally_spells": {"Ahri": [{"spell": "Flash", "cd_s": 0},
                                  {"spell": "Teleport", "cd_s": 0}]},
        "matchup": "Zed vs Ahri \xb7 48% wr (n=12) \xb7 Ahri scales harder",
    }),
}

FIXTURES["client_champselect_aram_mayhem"] = {
    "meta": {"name": "client_champselect_aram_mayhem",
             "label": "Client \xb7 champ select \xb7 ARAM Mayhem",
             "mode": "client",
             "summary": "Pregame ARAM Mayhem \xb7 Tristana rolled \xb7 mayhem rules briefing"},
    "health": _health("client", has_game=False, aram=True),
    "state": _state("client", "coaching_data.json", {
        "game_time": "", "kda": "", "champion": "Tristana",
        "queue": "ARAM Mayhem (Kiwi)",
        "game_mode": "Mayhem",
        "action": "Tristana rolled - Mayhem rules briefing",
        "immediate": "Mayhem this game: Limited Shopping (only 1 buy per recall) \xb7 Platform Regen Disabled \xb7 Snowbomb Mortar enabled. Plan single-item back at 1700g for Bork.",
        "risk": "Yone enemy carry \xb7 windwall blocks Tristana W reposition \xb7 stack Q before fights",
        "fight_rule": "Stay 600+ from Yone \xb7 burst Karthus first when grouped",
        "reset_item": "First single-item back: Berserker's Greaves at 1100g (cheaper to slam early)",
        "next": "Loading screen \u2192 1:30 minion spawn",
        "objective": "Hold mid \xb7 stack Q before each fight \xb7 reach Bork before 9:00",
        "positioning": "Backline \xb7 max range, behind Sion",
        "items_display": "Doran's Blade, Refillable Potion, Long Sword",
        "item_build": "Berserker's Greaves \u2192 Bork \u2192 Phantom Dancer \u2192 Infinity Edge",
        "augments": "Limited Shopping, Platform Regen Disabled, Snowbomb Mortar",
        "ally_comp":  ["Tristana", "Sion", "Yasuo", "Lulu", "Soraka"],
        "enemy_comp": ["Yone", "Heimerdinger", "Senna", "Akali", "Olaf"],
        "ally_spells": {"Tristana": [{"spell": "Flash", "cd_s": 0},
                                       {"spell": "Heal", "cd_s": 0}]},
    }),
}

FIXTURES["client_loading_screen"] = {
    "meta": {"name": "client_loading_screen",
             "label": "Client \xb7 loading screen (champ-select \u2192 in-game)",
             "mode": "client",
             "summary": "Loading screen \xb7 all 10 players' meta data, transitions to in-game on completion"},
    "health": _health("client", has_game=False),
    "state": _state("client", "coaching_data.json", {
        "game_time": "", "kda": "", "champion": "Ahri",
        "queue": "Ranked Solo/Duo \xb7 SR",
        "action": "LOADING - 4/10 players in",
        "immediate": "All 10 players' rank + recent perf snapshot. Will flip to in-game at first minion spawn.",
        "risk": "Enemy Zed is Diamond II 67%wr last 10 \xb7 primary threat. Don't lane-trade until level 6.",
        "fight_rule": "-", "reset_item": "-",
        "next": "First wave at 1:30 \u2192 vision ping at 2:35",
        "objective": "Pre-game intel \xb7 queue: Ranked Solo \xb7 est duration 28-34min",
        "positioning": "Mid lane",
        "items_display": "Doran's Ring, Refillable Potion, Stealth Ward",
        "item_build": "Lost Chapter \u2192 Luden's Echo \u2192 Sorcerer's Shoes",
        "loading_progress": {"loaded": 4, "total": 10, "stuck_at": ["Zed", "Thresh"]},
        "ally_meta": [
            {"champion": "Ahri",   "summoner": "you",       "rank": "Plat I",     "recent_wr": 0.62, "kda_avg": 2.9, "main": True},
            {"champion": "LeeSin", "summoner": "ally-jng",  "rank": "Plat II",    "recent_wr": 0.55, "kda_avg": 3.1},
            {"champion": "Sion",   "summoner": "ally-top",  "rank": "Plat I",     "recent_wr": 0.58, "kda_avg": 2.4},
            {"champion": "Jinx",   "summoner": "ally-adc",  "rank": "Diamond IV", "recent_wr": 0.51, "kda_avg": 2.8},
            {"champion": "Nami",   "summoner": "ally-supp", "rank": "Plat II",    "recent_wr": 0.60, "kda_avg": 2.2},
        ],
        "enemy_meta": [
            {"champion": "Zed",    "summoner": "en-mid",  "rank": "Diamond II", "recent_wr": 0.67, "kda_avg": 3.4, "primary_threat": True},
            {"champion": "Graves", "summoner": "en-jng",  "rank": "Plat I",     "recent_wr": 0.52, "kda_avg": 2.8},
            {"champion": "Darius", "summoner": "en-top",  "rank": "Plat II",    "recent_wr": 0.49, "kda_avg": 2.1},
            {"champion": "Kaisa",  "summoner": "en-adc",  "rank": "Plat I",     "recent_wr": 0.55, "kda_avg": 2.6},
            {"champion": "Thresh", "summoner": "en-supp", "rank": "Plat II",    "recent_wr": 0.50, "kda_avg": 1.9},
        ],
        "ally_comp":  ["Ahri", "LeeSin", "Sion", "Jinx", "Nami"],
        "enemy_comp": ["Zed", "Graves", "Darius", "Kaisa", "Thresh"],
        "ally_spells": {"Ahri": [{"spell": "Flash", "cd_s": 0},
                                  {"spell": "Teleport", "cd_s": 0}]},
    }),
}


# -- Manifest ---------------------------------------------------------------
MANIFEST_ORDER = [
    # SR
    ("sr_early",  "SR \xb7 early \xb7 4:30 laning",                       "sr",
     "Early laning \xb7 Ahri mid \xb7 wave-crash + ward river before Drake 1"),
    ("sr_mid",    "SR \xb7 mid \xb7 18:30 Drake 2 setup",                 "sr",
     "Mid \xb7 Ahri 5/2/4 \xb7 Drake 2 setup, vs Zed, vision sweep"),
    ("sr_late",   "SR \xb7 late \xb7 32:15 Soul fight on cooldown",       "sr",
     "Late \xb7 11/4/7 \xb7 Baron 33:00, 18% HP disengage state"),
    # ARAM
    ("aram_early", "ARAM \xb7 early \xb7 3:15 first poke",                "aram",
     "Zeri early \xb7 first item building, low HP from poke"),
    ("aram_mid",   "ARAM \xb7 mid \xb7 11:40 first inhib",                "aram",
     "Zeri mid \xb7 2-item spike, sieging first tower"),
    ("aram_late",  "ARAM \xb7 late \xb7 22:18 nexus turret",              "aram",
     "Zeri full-build \xb7 sieging nexus, 2 enemies dead"),
    # ARAM Mayhem
    ("aram_mayhem_early", "ARAM Mayhem \xb7 early \xb7 3:20 augment 1",   "aram",
     "Tristana \xb7 first augment + Limited Shopping rule"),
    ("aram_mayhem_mid",   "ARAM Mayhem \xb7 mid \xb7 10:30 augment pick", "aram",
     "Tristana \xb7 5k-gold augment select active"),
    ("aram_mayhem_late",  "ARAM Mayhem \xb7 late \xb7 18:50 nexus push",  "aram",
     "Tristana 13/4/14 \xb7 all 3 augments stacked, sieging"),
    # Arena
    ("arena_early", "Arena \xb7 early \xb7 Round 2 Samira",               "arena",
     "Samira+Taric \xb7 first augment picked, second incoming"),
    ("arena_mid",   "Arena \xb7 mid \xb7 Round 5 augment pick",           "arena",
     "Samira+Taric \xb7 2nd augment selection, 4 alive teams"),
    ("arena_late",  "Arena \xb7 late \xb7 Round 8 finale",                "arena",
     "Samira+Taric finals \xb7 all 3 augments stacked"),
    # Brawl
    ("brawl_early", "Brawl \xb7 early \xb7 2:10 first skirmish",          "brawl",
     "Yasuo \xb7 first 4v4 contact, low HP"),
    ("brawl_mid",   "Brawl \xb7 mid \xb7 8:30 contested objective",       "brawl",
     "Yasuo 5/2/3 \xb7 contested objective fight, full HP"),
    ("brawl_late",  "Brawl \xb7 late \xb7 14:25 endgame teamfight",       "brawl",
     "Yasuo 11/3/8 \xb7 final teamfight, full build"),
    # TFT
    ("tft_early", "TFT \xb7 early \xb7 stage 2-2 econ",                   "tft",
     "Stage 2-2 \xb7 econ-roll path, 3 traits active"),
    ("tft_mid",   "TFT \xb7 mid \xb7 stage 4-2 combat",                   "tft",
     "Stage 4-2 \xb7 comp 6/8 stable, top-4 positioning"),
    ("tft_late",  "TFT \xb7 late \xb7 stage 6 finale",                    "tft",
     "Stage 6 \xb7 8-unit cap board, 1st-place fight"),
    # Aftergame (2)
    ("aftergame_victory", "Aftergame \xb7 VICTORY (hot streak)", "client",
     "Post-match positive \xb7 70% recent wr, +LP progress"),
    ("aftergame_defeat",  "Aftergame \xb7 DEFEAT (tilt guard)",  "client",
     "Post-match loss streak \xb7 tilt-guard break recommendation"),
    # Session digest (2)
    ("session_cold_streak", "Session \xb7 cold streak (5L)",            "client",
     "Cold-streak digest \xb7 5 losses \xb7 break advisory active"),
    ("session_hot_streak",  "Session \xb7 hot streak (5W)",             "client",
     "Hot-streak digest \xb7 5W-1L \xb7 climb pace +14 LP/hr"),
    # Client states (4)
    ("client_idle",                     "Client \xb7 idle (no game / no champ select)", "client",
     "Client open, not in game/champ select \xb7 placeholders"),
    ("client_champselect_sr",           "Client \xb7 champ select \xb7 Ranked SR",         "client",
     "Pregame SR ranked \xb7 Ahri locked \xb7 matchup brief"),
    ("client_champselect_aram_mayhem",  "Client \xb7 champ select \xb7 ARAM Mayhem",       "client",
     "Pregame ARAM Mayhem \xb7 Tristana rolled \xb7 mayhem rules"),
    ("client_loading_screen",           "Client \xb7 loading screen (champ\u2192in-game)",   "client",
     "Loading \xb7 all 10 players' meta data snapshot"),
]

manifest = {
    "version": 2,
    "fixtures": [
        {"name": name, "label": label, "mode": mode, "summary": summary}
        for (name, label, mode, summary) in MANIFEST_ORDER
    ],
}


# -- Position attachment (2026-04-25): inject `positions` + `my_team`
# into the in-game fixtures so the minimap canvas renders dots without
# "waiting on positions". Single source of truth for the per-stage
# preset -> fixture mapping. -----------------------------------------
_POSITION_INJECTIONS = {
    # SR - Ahri's team (ORDER / blue side)
    "sr_early": ("ORDER", _SR_ALLY_POSITIONS["early"], _SR_ENEMY_POSITIONS["early"]),
    "sr_mid":   ("ORDER", _SR_ALLY_POSITIONS["mid"],   _SR_ENEMY_POSITIONS["mid"]),
    "sr_late":  ("ORDER", _SR_ALLY_POSITIONS["late"],  _SR_ENEMY_POSITIONS["late"]),
    # ARAM - Howling Abyss
    "aram_early": ("ORDER", _ARAM_ALLY_POSITIONS["early"], _ARAM_ENEMY_POSITIONS["early"]),
    "aram_mid":   ("ORDER", _ARAM_ALLY_POSITIONS["mid"],   _ARAM_ENEMY_POSITIONS["mid"]),
    "aram_late":  ("ORDER", _ARAM_ALLY_POSITIONS["late"],  _ARAM_ENEMY_POSITIONS["late"]),
    # ARAM Mayhem
    "aram_mayhem_early": ("ORDER", _MAYHEM_ALLY_POSITIONS["early"], _MAYHEM_ENEMY_POSITIONS["early"]),
    "aram_mayhem_mid":   ("ORDER", _MAYHEM_ALLY_POSITIONS["mid"],   _MAYHEM_ENEMY_POSITIONS["mid"]),
    "aram_mayhem_late":  ("ORDER", _MAYHEM_ALLY_POSITIONS["late"],  _MAYHEM_ENEMY_POSITIONS["late"]),
}


# -- Emit -------------------------------------------------------------------
def main() -> int:
    written = 0
    for name, fixture in FIXTURES.items():
        # Make sure the meta.name matches the filename
        fixture.setdefault("meta", {})["name"] = name
        # Inject positions for in-game fixtures so the minimap canvas
        # renders dots immediately rather than "waiting on positions".
        inj = _POSITION_INJECTIONS.get(name)
        if inj:
            my_team, allies, enemies = inj
            payload = fixture.get("state", {}).get("payload", {})
            payload["my_team"] = my_team
            payload["positions"] = {"allies": allies, "enemies": enemies}
        _write(name, fixture)
        written += 1
    # AUDIT 2026-04-28 (deferred-low-value): atomic manifest write.
    from core.polled_json import atomic_write_json as _atomic_write_json
    _atomic_write_json(SIM_DIR / "manifest.json", manifest)
    print(f"wrote {written} fixtures + manifest ({len(MANIFEST_ORDER)} entries)")
    # Sanity: every manifest entry must have a corresponding file
    missing = [m["name"] for m in manifest["fixtures"]
               if not (SIM_DIR / f"{m['name']}.json").exists()]
    if missing:
        print("MISSING FILES:", missing)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
