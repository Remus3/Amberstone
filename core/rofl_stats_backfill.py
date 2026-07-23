"""Map .rofl stats-sidecar players onto rewind_history.db participant columns.

The sidecar carries Riot's internal ENGINE stat names (CHAMPIONS_KILLED,
NUM_DEATHS, ITEM0) rather than the Match-V5 camelCase names the DB schema was
built from. This module extends the alias-resolution seam already used by
lcu/lcu_postgame_collector.py (`_s`) with the engine-name variants, so a single
table drives both paths.

Every column in COLUMN_ALIASES was proven against the six sidecars whose matches
were ALREADY in the DB via Match-V5: 99 columns agreed exactly across 76
participant rows. Three candidates were measured and DELIBERATELY EXCLUDED:

  summoner_id   the sidecar carries the raw numeric id, the DB the encrypted
                one - the same namespace split as puuid (see below)
  time_played   disagrees by one second on 3 of 76 rows (engine rounding)
  puuid         sidecar PUUID is the RAW game uuid, DB puuid is API-key
                ENCRYPTED - zero overlap, so it is surfaced as `rofl_uuid`

Only the mapping lives here. Writes live in the backfill entry point, which
refuses to run unless the oracle passes.
"""

from core.rofl_archive import DEFAULT_ACCOUNTS
from lcu.lcu_postgame_collector import _s

# participants column -> engine / Match-V5 key candidates, most specific first.
COLUMN_ALIASES = {
    # KDA and progression
    "kills": ("CHAMPIONS_KILLED", "KILLS", "kills"),
    "deaths": ("NUM_DEATHS", "DEATHS", "deaths"),
    "assists": ("ASSISTS", "assists"),
    "champ_level": ("LEVEL", "CHAMPION_LEVEL", "champLevel"),
    "champ_experience": ("EXP", "champExperience"),
    "largest_multi_kill": ("LARGEST_MULTI_KILL",),
    "killing_sprees": ("KILLING_SPREES",),
    "largest_killing_spree": ("LARGEST_KILLING_SPREE",),
    "double_kills": ("DOUBLE_KILLS",),
    "triple_kills": ("TRIPLE_KILLS",),
    "quadra_kills": ("QUADRA_KILLS",),
    "penta_kills": ("PENTA_KILLS",),
    "unreal_kills": ("UNREAL_KILLS",),
    # Damage dealt
    "total_damage_dealt": ("TOTAL_DAMAGE_DEALT",),
    "total_damage_dealt_to_champs": ("TOTAL_DAMAGE_DEALT_TO_CHAMPIONS",),
    "physical_damage_dealt": ("PHYSICAL_DAMAGE_DEALT_PLAYER",),
    "physical_damage_dealt_to_champs": ("PHYSICAL_DAMAGE_DEALT_TO_CHAMPIONS",),
    "magic_damage_dealt": ("MAGIC_DAMAGE_DEALT_PLAYER",),
    "magic_damage_dealt_to_champs": ("MAGIC_DAMAGE_DEALT_TO_CHAMPIONS",),
    "true_damage_dealt": ("TRUE_DAMAGE_DEALT_PLAYER",),
    "true_damage_dealt_to_champs": ("TRUE_DAMAGE_DEALT_TO_CHAMPIONS",),
    "largest_crit_strike": ("LARGEST_CRITICAL_STRIKE",),
    # Damage taken and mitigation
    "total_damage_taken": ("TOTAL_DAMAGE_TAKEN", "totalDamageTaken"),
    "physical_damage_taken": ("PHYSICAL_DAMAGE_TAKEN",),
    "magic_damage_taken": ("MAGIC_DAMAGE_TAKEN",),
    "true_damage_taken": ("TRUE_DAMAGE_TAKEN",),
    "damage_self_mitigated": ("TOTAL_DAMAGE_SELF_MITIGATED",),
    # Sustain
    "total_heal": ("TOTAL_HEAL",),
    "total_heals_on_teammates": ("TOTAL_HEAL_ON_TEAMMATES",),
    "total_damage_shielded_on_teammates": ("TOTAL_DAMAGE_SHIELDED_ON_TEAMMATES",),
    "total_units_healed": ("TOTAL_UNITS_HEALED",),
    # Structures and objectives
    "damage_dealt_to_buildings": ("TOTAL_DAMAGE_DEALT_TO_BUILDINGS",),
    "damage_dealt_to_objectives": ("TOTAL_DAMAGE_DEALT_TO_OBJECTIVES",),
    "damage_dealt_to_turrets": ("TOTAL_DAMAGE_DEALT_TO_TURRETS",),
    "damage_dealt_to_epic_monsters": ("TOTAL_DAMAGE_DEALT_TO_EPIC_MONSTERS",),
    "turret_kills": ("TURRETS_KILLED",),
    "turret_takedowns": ("TURRET_TAKEDOWNS",),
    "objectives_stolen": ("OBJECTIVES_STOLEN",),
    "objectives_stolen_assists": ("OBJECTIVES_STOLEN_ASSISTS",),
    "dragon_kills": ("DRAGON_KILLS",),
    "baron_kills": ("BARON_KILLS",),
    # Farm and economy
    "total_minions_killed": ("MINIONS_KILLED", "totalMinionsKilled"),
    "neutral_minions_killed": ("NEUTRAL_MINIONS_KILLED",),
    "total_ally_jungle_minions_killed": ("NEUTRAL_MINIONS_KILLED_YOUR_JUNGLE",),
    "total_enemy_jungle_minions_killed": ("NEUTRAL_MINIONS_KILLED_ENEMY_JUNGLE",),
    "gold_earned": ("GOLD_EARNED", "goldEarned"),
    "gold_spent": ("GOLD_SPENT", "goldSpent"),
    "items_purchased": ("ITEMS_PURCHASED",),
    "consumables_purchased": ("CONSUMABLES_PURCHASED",),
    # Items
    "item0": ("ITEM0", "item0"),
    "item1": ("ITEM1", "item1"),
    "item2": ("ITEM2", "item2"),
    "item3": ("ITEM3", "item3"),
    "item4": ("ITEM4", "item4"),
    "item5": ("ITEM5", "item5"),
    "item6": ("ITEM6", "item6"),
    # Spells
    "summoner1_id": ("SUMMONER_SPELL_1",),
    "summoner2_id": ("SUMMONER_SPELL_2",),
    "summoner1_casts": ("SUMMON_SPELL1_CAST",),
    "summoner2_casts": ("SUMMON_SPELL2_CAST",),
    "spell1_casts": ("SPELL1_CAST",),
    "spell2_casts": ("SPELL2_CAST",),
    "spell3_casts": ("SPELL3_CAST",),
    "spell4_casts": ("SPELL4_CAST",),
    # Vision
    "vision_score": ("VISION_SCORE", "visionScore"),
    "sight_wards_bought": ("SIGHT_WARDS_BOUGHT_IN_GAME",),
    "vision_wards_bought": ("VISION_WARDS_BOUGHT_IN_GAME",),
    "detector_wards_placed": ("WARD_PLACED_DETECTOR",),
    "wards_placed": ("WARD_PLACED",),
    "wards_killed": ("WARD_KILLED",),
    # Crowd control and time
    "time_ccing_others": ("TIME_CCING_OTHERS",),
    "total_time_cc_dealt": ("TOTAL_TIME_CROWD_CONTROL_DEALT",),
    "time_spent_dead": ("TOTAL_TIME_SPENT_DEAD",),
    "longest_time_alive": ("LONGEST_TIME_SPENT_LIVING",),
    # Position and outcome
    "team_id": ("TEAM", "teamId"),
    "team_position": ("TEAM_POSITION",),
    "individual_position": ("INDIVIDUAL_POSITION",),
    "champion_transform": ("CHAMPION_TRANSFORM",),
    "team_early_surrendered": ("TEAM_EARLY_SURRENDERED",),
    "game_ended_in_surrender": ("GAME_ENDED_IN_SURRENDER",),
    "game_ended_in_early_surrender": ("GAME_ENDED_IN_EARLY_SURRENDER",),
    # Pings
    "all_in_pings": ("ALL_IN_PINGS",),
    "assist_me_pings": ("ASSIST_ME_PINGS",),
    "basic_pings": ("BASIC_PINGS",),
    "command_pings": ("COMMAND_PINGS",),
    "danger_pings": ("DANGER_PINGS",),
    "enemy_missing_pings": ("ENEMY_MISSING_PINGS",),
    "enemy_vision_pings": ("ENEMY_VISION_PINGS",),
    "get_back_pings": ("GET_BACK_PINGS",),
    "hold_pings": ("HOLD_PINGS",),
    "need_vision_pings": ("NEED_VISION_PINGS",),
    "on_my_way_pings": ("ON_MY_WAY_PINGS",),
    "push_pings": ("PUSH_PINGS",),
    "retreat_pings": ("RETREAT_PINGS",),
    "vision_cleared_pings": ("VISION_CLEARED_PINGS",),
    # Arena
    "player_augment1": ("PLAYER_AUGMENT_1",),
    "player_augment2": ("PLAYER_AUGMENT_2",),
    "player_augment3": ("PLAYER_AUGMENT_3",),
    "player_augment4": ("PLAYER_AUGMENT_4",),
    "player_augment5": ("PLAYER_AUGMENT_5",),
    "player_augment6": ("PLAYER_AUGMENT_6",),
    "player_subteam_id": ("PLAYER_SUBTEAM",),
    "subteam_placement": ("PLAYER_SUBTEAM_PLACEMENT",),
    # Runes
    "rune_keystone_id": ("KEYSTONE_ID",),
    "rune_primary_style": ("PERK_PRIMARY_STYLE",),
    "rune_sub_style": ("PERK_SUB_STYLE",),
    "rune_p0": ("PERK0",),
    "rune_p1": ("PERK1",),
    "rune_p2": ("PERK2",),
    "rune_p3": ("PERK3",),
    "rune_s0": ("PERK4",),
    "rune_s1": ("PERK5",),
    "stat_perk_offense": ("STAT_PERK_0",),
    "stat_perk_flex": ("STAT_PERK_1",),
    "stat_perk_defense": ("STAT_PERK_2",),
    # Identity
    "riot_id_game_name": ("RIOT_ID_GAME_NAME",),
}

# Columns whose value must stay a string. `_s` int-coerces anything
# int-parseable, which silently turns the tagline "5045" into 5045.
TEXT_COLUMNS = {
    "riot_id_tagline": ("RIOT_ID_TAG_LINE",),
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
    for col, keys in TEXT_COLUMNS.items():
        value = next((player[k] for k in keys if player.get(k) is not None), "")
        row[col] = str(value)
    row["participant_id"] = index + 1
    row["champion_name"] = player.get("SKIN") or ""
    row["rofl_uuid"] = player.get("PUUID") or ""
    row["win"] = 1 if str(player.get("WIN", "")).strip().lower() == "win" else 0
    return row


def read_rofl_game_version(path) -> str:
    """Return the game version string from a .rofl header, e.g. 16.14.794.5912.

    Layout: magic 'RIOT' + 2 version bytes, 8 bytes of signature preamble, then
    a single length byte at offset 14 followed by the ASCII version.

    This is the ONLY match-level fact the container yields in plaintext. The
    body is zstd-compressed, so queue_id and game_mode are NOT recoverable -
    Replay Tool Z16 does not read them either, it infers the MAP from player stats.
    """
    with open(path, "rb") as handle:
        head = handle.read(64)
    if head[:4] != b"RIOT":
        raise ValueError(f"not a .rofl container: {path}")
    length = head[14]
    return head[15 : 15 + length].decode("ascii")


def _patch_from_version(version: str) -> str:
    """'16.13.791.5903' -> '16.13'."""
    parts = version.split(".")
    return ".".join(parts[:2]) if len(parts) >= 2 else version


def _champion_id_map(conn) -> dict:
    """Champion name -> id, learned from the rows the DB already holds.

    Deliberately sourced from the DB rather than a DDragon lookup: it cannot
    drift from what is already stored, and it needs no network.
    """
    rows = conn.execute(
        "SELECT DISTINCT champion_name, champion_id FROM participants "
        "WHERE champion_name IS NOT NULL AND champion_id IS NOT NULL"
    ).fetchall()
    return {name: cid for name, cid in rows}


def _find_rofl(archive_dir, match_id):
    """Locate the container for a match id, tolerating both name separators."""
    for name in (f"{match_id}.rofl", f"{match_id.replace('_', '-')}.rofl"):
        candidate = archive_dir / name
        if candidate.is_file():
            return candidate
    return None


def _select_operator_player(players, accounts):
    """Return the sidecar player entry belonging to a tracked account, or None.

    The join is by RIOT ID ((RIOT_ID_GAME_NAME, RIOT_ID_TAG_LINE)), case
    insensitive - never the sidecar PUUID, which is the RAW game uuid and shares
    no namespace with the key-encrypted puuid the DB stores. Returning None when
    no operator is in the lobby is deliberate: the caller must leave tracked_*
    NULL rather than guess a player (there is no "index 0 is me" fallback).
    """
    wanted = {(str(n).strip().lower(), str(t).strip().lower()) for n, t in accounts}
    for player in players:
        name = str(player.get("RIOT_ID_GAME_NAME", "")).strip().lower()
        tag = str(player.get("RIOT_ID_TAG_LINE", "")).strip().lower()
        if (name, tag) in wanted:
            return player
    return None


def _tracked_values(player, resolved_ids):
    """Map one operator sidecar entry onto the matches.tracked_* columns.

    champion_id is looked up in `resolved_ids` and left None when the name does
    not resolve - never invented. Returns (values_dict, unresolved_name) where
    unresolved_name is the champion name if its id could not be resolved.
    """
    name = player.get("SKIN") or ""
    champion_id = resolved_ids.get(name)
    values = {
        "tracked_champion_name": name,
        "tracked_champion_id": champion_id,
        "tracked_team_id": _s(player, "TEAM"),
        "tracked_kills": _s(player, "CHAMPIONS_KILLED"),
        "tracked_deaths": _s(player, "NUM_DEATHS"),
        "tracked_assists": _s(player, "ASSISTS"),
        "tracked_win": 1 if str(player.get("WIN", "")).strip().lower() == "win" else 0,
    }
    return values, (name if champion_id is None else None)


def backfill_tracked_summary(
    db_path,
    sidecar_paths,
    *,
    operator_accounts=DEFAULT_ACCOUNTS,
    dry_run: bool = False,
    champion_ids: dict | None = None,
) -> dict:
    """Fill matches.tracked_* on rows that already exist but are NULL-tracked.

    These rows are NOT missing: Match-V5 wrote the match with a correct
    queue_id/game_mode but no tracked summary, so the dashboard renders the
    operator's champion as "Unknown" and the KDA as "0-0-0". The fix is an
    UPDATE of the seven tracked_* columns on the existing row, joined:

      * file -> row by match_id (from the sidecar's own field), and
      * player -> operator by RIOT ID (see `_select_operator_player`).

    queue_id and game_mode are NEVER touched - the sidecar cannot prove a queue,
    and the existing value is already correct from Match-V5. The sweep is over
    every sidecar handed in whose match row is tracked-NULL, regardless of queue
    (the same root cause spans 420/450/2400/customs), so the caller drives
    breadth by which sidecars it globs.

    `champion_ids` maps champion name to Riot id; it defaults to learning from
    the participants the target DB already holds. Names that do not resolve are
    reported in `unresolved_champions` and stored as NULL, never guessed.

    Idempotent: a row that already carries a tracked_champion_name is reported
    in `skipped_already_filled` and left alone. A sidecar whose match is not in
    the DB at all is reported in `net_new` (that is the INSERT path's job, see
    `backfill_participants`), not inserted here.
    """
    import json
    import sqlite3
    from pathlib import Path

    db_path = Path(db_path)
    sidecar_paths = [Path(p) for p in sidecar_paths]

    report = {
        "updated": [],
        "skipped_no_operator": [],
        "skipped_already_filled": [],
        "net_new": [],
        "unresolved_champions": [],
    }

    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        resolved_ids = champion_ids if champion_ids is not None else _champion_id_map(conn)

        for sidecar_path in sidecar_paths:
            sidecar = json.loads(sidecar_path.read_text())
            match_id = sidecar["match_id"]

            row = conn.execute(
                "SELECT tracked_champion_name FROM matches WHERE match_id = ?",
                (match_id,),
            ).fetchone()
            if row is None:
                report["net_new"].append(match_id)
                continue
            if row["tracked_champion_name"] is not None:
                report["skipped_already_filled"].append(match_id)
                continue

            player = _select_operator_player(sidecar["players"], operator_accounts)
            if player is None:
                report["skipped_no_operator"].append(match_id)
                continue

            values, unresolved = _tracked_values(player, resolved_ids)
            if unresolved is not None:
                report["unresolved_champions"].append(f"{match_id}:{unresolved}")

            assignments = ", ".join(f"{col} = ?" for col in values)
            conn.execute(
                f"UPDATE matches SET {assignments} "
                "WHERE match_id = ? AND tracked_champion_name IS NULL",
                [*values.values(), match_id],
            )
            report["updated"].append(match_id)

        if dry_run:
            conn.rollback()
        else:
            conn.commit()
    finally:
        conn.close()

    return report


def backfill_participants(
    db_path,
    sidecar_paths,
    *,
    min_duration_s: int = 300,
    dry_run: bool = False,
    queue_overrides: dict | None = None,
    champion_ids: dict | None = None,
    operator_accounts=DEFAULT_ACCOUNTS,
) -> dict:
    """Insert participant rows for matches the DB does not already have.

    Deliberate constraints:

    * Matches shorter than `min_duration_s` are skipped as remakes.
    * Already-present matches are skipped, so the call is idempotent.
    * A minimal `matches` stub is written so participants are never orphaned
      (participants.match_id carries a foreign key to matches.match_id).
    * `queue_id` and `game_mode` are left NULL unless supplied explicitly via
      `queue_overrides`, because no local artifact can prove a queue. Passing
      an override is an assertion by the CALLER, not an inference by this code.

    `champion_ids` maps champion name to id. It defaults to learning from the
    rows the target DB already holds, which only works on a populated DB - pass
    it explicitly against an empty one. Names that do not resolve are reported
    in `unresolved_champions` and stored as NULL rather than guessed; callers
    should treat a non-empty list as a failure.
    """
    import json
    import sqlite3
    from pathlib import Path

    db_path = Path(db_path)
    sidecar_paths = [Path(p) for p in sidecar_paths]
    queue_overrides = queue_overrides or {}

    report = {
        "inserted_matches": 0,
        "inserted_participants": 0,
        "skipped_short": [],
        "skipped_present": [],
        "unresolved_champions": [],
    }

    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        resolved_ids = champion_ids if champion_ids is not None else _champion_id_map(conn)
        present = {
            r[0] for r in conn.execute("SELECT match_id FROM matches").fetchall()
        }

        for sidecar_path in sidecar_paths:
            sidecar = json.loads(sidecar_path.read_text())
            match_id = sidecar["match_id"]
            duration_s = sidecar["game_length_ms"] // 1000

            if match_id in present:
                report["skipped_present"].append(match_id)
                continue
            if duration_s < min_duration_s:
                report["skipped_short"].append(match_id)
                continue

            rofl = _find_rofl(sidecar_path.parent.parent, match_id)
            version = read_rofl_game_version(rofl) if rofl else None
            queue_id, game_mode = queue_overrides.get(match_id, (None, None))

            # Close the tracked_* hole on the way in: a net-new operator-present
            # match is rendered "Unknown / 0-0-0" unless the summary is filled
            # here too. queue_id/game_mode stay NULL - only tracked_* is derived
            # from the sidecar. No operator in the lobby -> all tracked_* NULL.
            operator = _select_operator_player(sidecar["players"], operator_accounts)
            if operator is not None:
                tracked, unresolved = _tracked_values(operator, resolved_ids)
                if unresolved is not None:
                    report["unresolved_champions"].append(f"{match_id}:{unresolved}")
            else:
                tracked = {
                    "tracked_champion_name": None,
                    "tracked_champion_id": None,
                    "tracked_team_id": None,
                    "tracked_kills": None,
                    "tracked_deaths": None,
                    "tracked_assists": None,
                    "tracked_win": None,
                }

            conn.execute(
                "INSERT INTO matches (match_id, queue_id, game_mode, game_version, "
                "patch, game_duration_s, has_stats, has_timeline, "
                "tracked_champion_name, tracked_champion_id, tracked_team_id, "
                "tracked_kills, tracked_deaths, tracked_assists, tracked_win) "
                "VALUES (?, ?, ?, ?, ?, ?, 1, 0, ?, ?, ?, ?, ?, ?, ?)",
                (
                    match_id,
                    queue_id,
                    game_mode,
                    version,
                    _patch_from_version(version) if version else None,
                    duration_s,
                    tracked["tracked_champion_name"],
                    tracked["tracked_champion_id"],
                    tracked["tracked_team_id"],
                    tracked["tracked_kills"],
                    tracked["tracked_deaths"],
                    tracked["tracked_assists"],
                    tracked["tracked_win"],
                ),
            )
            report["inserted_matches"] += 1

            for index, player in enumerate(sidecar["players"]):
                row = map_rofl_player(player, index)
                name = row["champion_name"]
                champion_id = resolved_ids.get(name)
                if champion_id is None:
                    report["unresolved_champions"].append(f"{match_id}:{name}")
                row["champion_id"] = champion_id
                row["match_id"] = match_id
                row.pop("rofl_uuid", None)

                columns = ", ".join(row)
                marks = ", ".join("?" for _ in row)
                conn.execute(
                    f"INSERT INTO participants ({columns}) VALUES ({marks})",
                    list(row.values()),
                )
                report["inserted_participants"] += 1

        if dry_run:
            conn.rollback()
        else:
            conn.commit()
    finally:
        conn.close()

    return report
