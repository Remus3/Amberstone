"""Map .rofl stats-sidecar players onto rewind_history.db participant columns.

The sidecar carries Riot's internal ENGINE stat names (CHAMPIONS_KILLED,
NUM_DEATHS, ITEM0) rather than the Match-V5 camelCase names the DB schema was
built from. This module extends the alias-resolution seam already used by
lcu/lcu_postgame_collector.py (`_s`) with the engine-name variants, so a single
table drives both paths.

Only the mapping lives here. Nothing in this module writes to the database.
"""

from lcu.lcu_postgame_collector import _s

# participants column -> engine / Match-V5 key candidates, most specific first.
COLUMN_ALIASES = {
    "kills": ("CHAMPIONS_KILLED", "KILLS", "kills"),
    "deaths": ("NUM_DEATHS", "DEATHS", "deaths"),
    "assists": ("ASSISTS", "assists"),
    "champ_level": ("LEVEL", "CHAMPION_LEVEL", "champLevel"),
    "gold_earned": ("GOLD_EARNED", "goldEarned"),
    "gold_spent": ("GOLD_SPENT", "goldSpent"),
    "total_minions_killed": ("MINIONS_KILLED", "totalMinionsKilled"),
    "total_damage_dealt_to_champs": (
        "TOTAL_DAMAGE_DEALT_TO_CHAMPIONS",
        "totalDamageDealtToChampions",
    ),
    "total_damage_taken": ("TOTAL_DAMAGE_TAKEN", "totalDamageTaken"),
    "vision_score": ("VISION_SCORE", "visionScore"),
    "item0": ("ITEM0", "item0"),
    "item1": ("ITEM1", "item1"),
    "item2": ("ITEM2", "item2"),
    "item3": ("ITEM3", "item3"),
    "item4": ("ITEM4", "item4"),
    "item5": ("ITEM5", "item5"),
    "item6": ("ITEM6", "item6"),
    "team_id": ("TEAM", "teamId"),
}


def map_rofl_player(player: dict, index: int) -> dict:
    """Return a participants-shaped dict for one sidecar player entry.

    `index` is the player's position in the sidecar `players` list, which is
    the engine's participant order and therefore participant_id - 1.

    The sidecar's PUUID field is the RAW game uuid, NOT the API-key-encrypted
    puuid the Match-V5 path stores. It is surfaced as `rofl_uuid` so it can
    never be mistaken for a joinable puuid.
    """
    row = {col: _s(player, *keys) for col, keys in COLUMN_ALIASES.items()}
    row["participant_id"] = index + 1
    row["champion_name"] = player.get("SKIN") or ""
    row["rofl_uuid"] = player.get("PUUID") or ""
    row["win"] = 1 if str(player.get("WIN", "")).strip().lower() == "win" else 0
    return row
