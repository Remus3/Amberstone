"""
tests/fixtures/state_dicts.py
Minimal fixture state dicts for snapshot translation tests.
All values are deterministic; no live API required.
"""

# Minimal SR/ARAM state dict (output of GameReader._process_game())
SR_STATE = {
    "game_mode": "CLASSIC",
    "game_time": "05:30",
    "game_seconds": 330,
    "champion": "Jinx",
    "hp": 1200, "hp_max": 1200, "hp_pct": 100,
    "mana": 400, "mana_max": 400,
    "level": 8,
    "gold": 1800,
    "cs": 72,
    "cs_per_min": 7.1,
    "gold_per_min": 320,
    "kills": 2, "deaths": 0, "assists": 1,
    "kda": "2/0/1",
    "items": ["Yun Tal Wildarrows", "Long Sword"],
    "ally_comp": ["Lux", "Malphite", "Vi", "Sett"],
    "enemy_comp": ["Caitlyn", "Thresh", "Garen", "Jarvan IV", "Jinx"],
    "dead_enemies": [],
    "ally_kills_total": 3,
    "enemy_kills_total": 1,
    "objectives": "Dragon up in 1:20",
    "summoner1": "Flash",
    "summoner2": "Heal",
    "raw_state": None,
}
SR_STATE["raw_state"] = SR_STATE.copy()

ARAM_STATE = {
    "game_mode": "ARAM",
    "game_time": "08:12",
    "game_seconds": 492,
    "champion": "Vayne",
    "hp": 900, "hp_max": 1100, "hp_pct": 82,
    "mana": 200, "mana_max": 300,
    "level": 10,
    "gold": 2200,
    "cs": 40,
    "cs_per_min": 4.9,
    "gold_per_min": 280,
    "kills": 4, "deaths": 1, "assists": 5,
    "kda": "4/1/5",
    "kill_participation": 75,
    "items": ["BotRK", "Phantom Drive"],
    "ally_comp": ["Lux", "Sejuani", "Orianna", "Zyra"],
    "enemy_comp": ["Garen", "Malphite", "Morgana", "Sona", "Blitzcrank"],
    "dead_enemies": ["Garen"],
    "ally_kills_total": 12,
    "enemy_kills_total": 4,
    "raw_state": None,
}
ARAM_STATE["raw_state"] = ARAM_STATE.copy()

ARENA_STATE = {
    "game_mode": "CHERRY",
    "game_time": "12:45",
    "game_seconds": 765,
    "champion": "Garen",
    "hp": 1800, "hp_max": 2200, "hp_pct": 82,
    "mana": 0, "mana_max": 0,
    "level": 12,
    "gold": 3100,
    "cs": 0,
    "cs_per_min": 0,
    "gold_per_min": 240,
    "kills": 5, "deaths": 2, "assists": 3,
    "kda": "5/2/3",
    "items": ["Sunfire Aegis", "Thornmail"],
    "ally_comp": ["Lux"],
    "enemy_comp": ["Jinx", "Thresh"],
    "dead_enemies": [],
    "ally_kills_total": 8,
    "enemy_kills_total": 5,
    "raw_state": None,
}
ARENA_STATE["raw_state"] = ARENA_STATE.copy()

BRAWL_STATE = {
    "game_mode": "NEXUSBLITZ",
    "game_time": "06:00",
    "game_seconds": 360,
    "champion": "Ahri",
    "hp": 1000, "hp_max": 1400, "hp_pct": 71,
    "mana": 350, "mana_max": 500,
    "level": 9,
    "gold": 2500,
    "cs": 55,
    "cs_per_min": 9.2,
    "gold_per_min": 410,
    "kills": 3, "deaths": 1, "assists": 4,
    "kda": "3/1/4",
    "items": ["Luden's Tempest", "Shadowflame"],
    "ally_comp": ["Nasus", "Leona", "Jhin"],
    "enemy_comp": ["Yasuo", "Zed", "Blitzcrank", "Caitlyn", "Lux"],
    "dead_enemies": [],
    "ally_kills_total": 7,
    "enemy_kills_total": 3,
    "raw_state": None,
}
BRAWL_STATE["raw_state"] = BRAWL_STATE.copy()

# Minimal TFT state dict (output of TftStateReader.read())
# traits must be a dict {name: count} for TftSnapshot.from_state_dict()
TFT_STATE = {
    "game_mode": "TFT",
    "stage": 2,
    "round": 3,
    "hp": 78,
    "gold": 6,
    "level": 5,
    "xp": 14,
    "xp_max": 18,
    "board_units": ["Jinx", "Caitlyn", "Lulu"],
    "bench_units": ["Gnar"],
    "shop_units": ["Vayne", "Jinx", "Lux", "Caitlyn", "Riven"],
    "items_bench": ["B.F. Sword", "Recurve Bow"],
    "items_equipped": ["Guinsoo's Rageblade"],
    "traits": {"Sniper": 2},
    "augments": [],
    "loss_streak": 0,
    "win_streak": 2,
}
