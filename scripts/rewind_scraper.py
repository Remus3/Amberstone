"""
scripts/rewind_scraper.py
─────────────────────────
Scrapes match history from rewind.lol for SamplePlayer#Trist (NA).

Data sources (no auth required):
  History list:  GET /get_data/NA/{username}/history  → 15MB JSON, 2846 matches
  Match stats:   GET /getmatch/NA/{match_id}/stats    → 145 fields/player
  Timeline:      GET /getmatch/NA/{match_id}/timeline → frame-by-frame events

Output: C:\\Riot Commander\\data\\rewind_history.db  (SEPARATE from postgame_stats.db)

Resumable - skips matches already stored. Safe to Ctrl+C and re-run.

Usage:
  python scripts\\rewind_scraper.py
  python scripts\\rewind_scraper.py --no-timeline    (skip timeline, faster)
  python scripts\\rewind_scraper.py --limit 100      (test with 100 matches)
  python scripts\\rewind_scraper.py --from-match 500 (start from match index 500)
"""

import argparse
import json
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# ── Config ─────────────────────────────────────────────────────────────────────
ROOT     = Path(__file__).parent.parent
DB_PATH  = ROOT / "data" / "rewind_history.db"
CACHE_DIR = ROOT / "data" / "rewind_cache"

REGION   = "NA"
USERNAME = "SamplePlayer#Trist"
BASE     = "https://rewind.lol"

# Polite rate limiting - seconds between requests
REQUEST_DELAY   = 1.2   # baseline delay
RETRY_DELAY     = 8.0   # wait after 429/503
MAX_RETRIES     = 3

HDR = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/147.0",
    "Accept":     "application/json,*/*",
}

# ── HTTP ───────────────────────────────────────────────────────────────────────

def fetch_json(url: str, retries: int = MAX_RETRIES) -> dict | list | None:
    """Fetch JSON from URL with retry/backoff. Returns None on persistent failure."""
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HDR)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None                      # not found - not an error
            if e.code in (429, 503):
                wait = RETRY_DELAY * (2 ** attempt)
                print(f"    Rate-limited ({e.code}), waiting {wait:.0f}s...")
                time.sleep(wait)
            else:
                print(f"    HTTP {e.code} for {url}")
                if attempt == retries - 1:
                    return None
                time.sleep(REQUEST_DELAY * 2)
        except Exception as e:
            print(f"    Fetch error ({url}): {e}")
            if attempt == retries - 1:
                return None
            time.sleep(REQUEST_DELAY * 2)
    return None


# ── Database schema ────────────────────────────────────────────────────────────

SCHEMA = """
-- Core game metadata (one row per match)
CREATE TABLE IF NOT EXISTS matches (
    match_id         TEXT PRIMARY KEY,
    platform         TEXT,
    queue_id         INTEGER,
    game_mode        TEXT,
    game_type        TEXT,
    map_id           INTEGER,
    game_version     TEXT,
    patch            TEXT,
    game_duration_s  INTEGER,
    game_creation_ts INTEGER,
    game_end_ts      INTEGER,
    end_of_game_result TEXT,
    tournament_code  TEXT,
    tracked_champion_id   INTEGER,
    tracked_champion_name TEXT,
    tracked_team_id       INTEGER,
    tracked_win           INTEGER,
    tracked_kills         INTEGER,
    tracked_deaths        INTEGER,
    tracked_assists        INTEGER,
    tracked_kp            INTEGER,
    tracked_lane          INTEGER,
    tracked_side          TEXT,
    tracked_ff            TEXT,
    tracked_ttmga_t       TEXT,
    has_stats             INTEGER DEFAULT 0,
    has_timeline          INTEGER DEFAULT 0,
    fetched_at            TEXT
);
CREATE INDEX IF NOT EXISTS idx_matches_queue ON matches(queue_id);
CREATE INDEX IF NOT EXISTS idx_matches_patch ON matches(patch);
CREATE INDEX IF NOT EXISTS idx_matches_champion ON matches(tracked_champion_name);

-- All 10 participants per match (145+ fields)
CREATE TABLE IF NOT EXISTS participants (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id          TEXT NOT NULL,
    participant_id    INTEGER,
    team_id           INTEGER,
    -- Identity
    puuid             TEXT,
    summoner_id       TEXT,
    riot_id_game_name TEXT,
    riot_id_tagline   TEXT,
    summoner_name     TEXT,
    summoner_level    INTEGER,
    profile_icon      INTEGER,
    champion_id       INTEGER,
    champion_name     TEXT,
    champion_transform INTEGER,
    champ_level       INTEGER,
    champ_experience  INTEGER,
    win               INTEGER,
    team_early_surrendered INTEGER,
    game_ended_in_surrender INTEGER,
    game_ended_in_early_surrender INTEGER,
    time_played       INTEGER,
    team_position     TEXT,
    individual_position TEXT,
    role              TEXT,
    lane              TEXT,
    kills             INTEGER,
    deaths            INTEGER,
    assists           INTEGER,
    largest_multi_kill INTEGER,
    killing_sprees    INTEGER,
    largest_killing_spree INTEGER,
    double_kills      INTEGER,
    triple_kills      INTEGER,
    quadra_kills      INTEGER,
    penta_kills       INTEGER,
    unreal_kills      INTEGER,
    total_damage_dealt              INTEGER,
    total_damage_dealt_to_champs    INTEGER,
    physical_damage_dealt           INTEGER,
    physical_damage_dealt_to_champs INTEGER,
    magic_damage_dealt              INTEGER,
    magic_damage_dealt_to_champs    INTEGER,
    true_damage_dealt               INTEGER,
    true_damage_dealt_to_champs     INTEGER,
    largest_crit_strike             INTEGER,
    total_damage_taken              INTEGER,
    physical_damage_taken           INTEGER,
    magic_damage_taken              INTEGER,
    true_damage_taken               INTEGER,
    damage_self_mitigated           INTEGER,
    total_heal                      INTEGER,
    total_heals_on_teammates        INTEGER,
    total_damage_shielded_on_teammates INTEGER,
    total_units_healed              INTEGER,
    damage_dealt_to_buildings       INTEGER,
    damage_dealt_to_objectives      INTEGER,
    damage_dealt_to_turrets         INTEGER,
    damage_dealt_to_epic_monsters   INTEGER,
    first_blood_kill                INTEGER,
    first_blood_assist              INTEGER,
    first_tower_kill                INTEGER,
    first_tower_assist              INTEGER,
    turret_kills                    INTEGER,
    turret_takedowns                INTEGER,
    turrets_lost                    INTEGER,
    inhibitor_kills                 INTEGER,
    inhibitor_takedowns             INTEGER,
    inhibitors_lost                 INTEGER,
    nexus_kills                     INTEGER,
    nexus_takedowns                 INTEGER,
    nexus_lost                      INTEGER,
    objectives_stolen               INTEGER,
    objectives_stolen_assists       INTEGER,
    dragon_kills                    INTEGER,
    baron_kills                     INTEGER,
    total_minions_killed            INTEGER,
    neutral_minions_killed          INTEGER,
    total_ally_jungle_minions_killed INTEGER,
    total_enemy_jungle_minions_killed INTEGER,
    gold_earned                     INTEGER,
    gold_spent                      INTEGER,
    items_purchased                 INTEGER,
    consumables_purchased           INTEGER,
    item0 INTEGER, item1 INTEGER, item2 INTEGER, item3 INTEGER,
    item4 INTEGER, item5 INTEGER, item6 INTEGER,
    summoner1_id      INTEGER,
    summoner2_id      INTEGER,
    summoner1_casts   INTEGER,
    summoner2_casts   INTEGER,
    spell1_casts      INTEGER,
    spell2_casts      INTEGER,
    spell3_casts      INTEGER,
    spell4_casts      INTEGER,
    vision_score                    INTEGER,
    sight_wards_bought              INTEGER,
    vision_wards_bought             INTEGER,
    detector_wards_placed           INTEGER,
    wards_placed                    INTEGER,
    wards_killed                    INTEGER,
    time_ccing_others               INTEGER,
    total_time_cc_dealt             INTEGER,
    time_spent_dead                 INTEGER,
    longest_time_alive              INTEGER,
    all_in_pings      INTEGER,
    assist_me_pings   INTEGER,
    basic_pings       INTEGER,
    command_pings     INTEGER,
    danger_pings      INTEGER,
    enemy_missing_pings INTEGER,
    enemy_vision_pings INTEGER,
    get_back_pings    INTEGER,
    hold_pings        INTEGER,
    need_vision_pings INTEGER,
    on_my_way_pings   INTEGER,
    push_pings        INTEGER,
    retreat_pings     INTEGER,
    vision_cleared_pings INTEGER,
    player_augment1 INTEGER, player_augment2 INTEGER,
    player_augment3 INTEGER, player_augment4 INTEGER,
    player_augment5 INTEGER, player_augment6 INTEGER,
    player_subteam_id INTEGER,
    subteam_placement INTEGER,
    placement         INTEGER,
    challenges_json   TEXT,
    missions_json     TEXT,
    perks_json        TEXT,
    -- Extracted rune shortcuts (for easy querying)
    rune_keystone_id  INTEGER,
    rune_primary_style INTEGER,
    rune_sub_style    INTEGER,
    rune_p0 INTEGER, rune_p1 INTEGER, rune_p2 INTEGER, rune_p3 INTEGER,
    rune_s0 INTEGER, rune_s1 INTEGER,
    stat_perk_offense INTEGER, stat_perk_flex INTEGER, stat_perk_defense INTEGER,
    eligible_for_progression INTEGER,
    FOREIGN KEY (match_id) REFERENCES matches(match_id)
);
CREATE INDEX IF NOT EXISTS idx_participants_match ON participants(match_id);
CREATE INDEX IF NOT EXISTS idx_participants_champion ON participants(champion_name);
CREATE INDEX IF NOT EXISTS idx_participants_puuid ON participants(puuid);

-- Team-level data (objectives, bans) - one row per team per match
CREATE TABLE IF NOT EXISTS teams (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id        TEXT NOT NULL,
    team_id         INTEGER,
    win             INTEGER,
    baron_first    INTEGER, baron_kills    INTEGER,
    champion_first INTEGER, champion_kills INTEGER,
    dragon_first   INTEGER, dragon_kills   INTEGER,
    horde_first    INTEGER, horde_kills    INTEGER,
    inhibitor_first INTEGER, inhibitor_kills INTEGER,
    rift_herald_first INTEGER, rift_herald_kills INTEGER,
    tower_first    INTEGER, tower_kills    INTEGER,
    atakhan_first  INTEGER, atakhan_kills  INTEGER,
    ban1 INTEGER, ban2 INTEGER, ban3 INTEGER, ban4 INTEGER, ban5 INTEGER,
    FOREIGN KEY (match_id) REFERENCES matches(match_id)
);
CREATE INDEX IF NOT EXISTS idx_teams_match ON teams(match_id);

-- Timeline: per-minute state snapshots for each participant
CREATE TABLE IF NOT EXISTS timeline_frames (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id        TEXT NOT NULL,
    timestamp_ms    INTEGER,
    participant_id  INTEGER,
    current_gold    INTEGER,
    total_gold      INTEGER,
    gold_per_second INTEGER,
    xp              INTEGER,
    level           INTEGER,
    minions_killed  INTEGER,
    jungle_minions  INTEGER,
    pos_x           INTEGER,
    pos_y           INTEGER,
    time_enemy_cc   INTEGER,
    magic_dmg_done     INTEGER,
    physical_dmg_done  INTEGER,
    true_dmg_done      INTEGER,
    total_dmg_done     INTEGER,
    magic_dmg_taken    INTEGER,
    physical_dmg_taken INTEGER,
    true_dmg_taken     INTEGER,
    total_dmg_taken    INTEGER,
    total_healed       INTEGER,
    self_mitigated     INTEGER,
    FOREIGN KEY (match_id) REFERENCES matches(match_id)
);
CREATE INDEX IF NOT EXISTS idx_frames_match ON timeline_frames(match_id);
CREATE INDEX IF NOT EXISTS idx_frames_participant ON timeline_frames(match_id, participant_id);

-- Timeline: all discrete events
CREATE TABLE IF NOT EXISTS timeline_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id        TEXT NOT NULL,
    timestamp_ms    INTEGER,
    event_type      TEXT,
    participant_id  INTEGER,
    item_id         INTEGER,
    killer_id       INTEGER,
    victim_id       INTEGER,
    assisting_ids_json TEXT,
    bounty          INTEGER,
    shutdown_bounty INTEGER,
    kill_streak_len INTEGER,
    kill_pos_x      INTEGER,
    kill_pos_y      INTEGER,
    victim_damage_json TEXT,
    -- BUILDING_KILL
    building_type   TEXT,
    lane_type       TEXT,
    tower_type      TEXT,
    team_id         INTEGER,
    monster_type    TEXT,
    monster_subtype TEXT,
    ward_type       TEXT,
    skill_slot      INTEGER,
    level_up_type   TEXT,
    level           INTEGER,
    -- (uses building fields)
    -- Raw JSON for any extra fields
    raw_json        TEXT,
    FOREIGN KEY (match_id) REFERENCES matches(match_id)
);
CREATE INDEX IF NOT EXISTS idx_events_match ON timeline_events(match_id);
CREATE INDEX IF NOT EXISTS idx_events_type ON timeline_events(match_id, event_type);
CREATE INDEX IF NOT EXISTS idx_events_participant ON timeline_events(participant_id);
"""


# ── Parsers ─────────────────────────────────────────────────────────────────────

def parse_participant(p: dict, match_id: str) -> dict:
    perks = p.get("perks", {})
    styles = perks.get("styles", []) if isinstance(perks, dict) else []
    stat_perks = perks.get("statPerks", {}) if isinstance(perks, dict) else {}

    primary_sel = secondary_sel = []
    primary_style = sub_style = 0
    for s in styles:
        if s.get("description") == "primaryStyle":
            primary_style = s.get("style", 0)
            primary_sel = [sel.get("perk", 0) for sel in s.get("selections", [])]
        elif s.get("description") == "subStyle":
            sub_style = s.get("style", 0)
            secondary_sel = [sel.get("perk", 0) for sel in s.get("selections", [])]

    def g(key, default=0):
        return p.get(key, default)

    return {
        "match_id": match_id,
        "participant_id": g("participantId"),
        "team_id": g("teamId"),
        "puuid": g("puuid", ""),
        "summoner_id": g("summonerId", ""),
        "riot_id_game_name": g("riotIdGameName", ""),
        "riot_id_tagline": g("riotIdTagline", ""),
        "summoner_name": g("summonerName", ""),
        "summoner_level": g("summonerLevel"),
        "profile_icon": g("profileIcon"),
        "champion_id": g("championId"),
        "champion_name": g("championName", ""),
        "champion_transform": g("championTransform"),
        "champ_level": g("champLevel"),
        "champ_experience": g("champExperience"),
        "win": int(bool(g("win", False))),
        "team_early_surrendered": int(bool(g("teamEarlySurrendered", False))),
        "game_ended_in_surrender": int(bool(g("gameEndedInSurrender", False))),
        "game_ended_in_early_surrender": int(bool(g("gameEndedInEarlySurrender", False))),
        "time_played": g("timePlayed"),
        "team_position": g("teamPosition", ""),
        "individual_position": g("individualPosition", ""),
        "role": g("role", ""),
        "lane": g("lane", ""),
        "kills": g("kills"), "deaths": g("deaths"), "assists": g("assists"),
        "largest_multi_kill": g("largestMultiKill"),
        "killing_sprees": g("killingSprees"),
        "largest_killing_spree": g("largestKillingSpree"),
        "double_kills": g("doubleKills"), "triple_kills": g("tripleKills"),
        "quadra_kills": g("quadraKills"), "penta_kills": g("pentaKills"),
        "unreal_kills": g("unrealKills"),
        "total_damage_dealt": g("totalDamageDealt"),
        "total_damage_dealt_to_champs": g("totalDamageDealtToChampions"),
        "physical_damage_dealt": g("physicalDamageDealt"),
        "physical_damage_dealt_to_champs": g("physicalDamageDealtToChampions"),
        "magic_damage_dealt": g("magicDamageDealt"),
        "magic_damage_dealt_to_champs": g("magicDamageDealtToChampions"),
        "true_damage_dealt": g("trueDamageDealt"),
        "true_damage_dealt_to_champs": g("trueDamageDealtToChampions"),
        "largest_crit_strike": g("largestCriticalStrike"),
        "total_damage_taken": g("totalDamageTaken"),
        "physical_damage_taken": g("physicalDamageTaken"),
        "magic_damage_taken": g("magicDamageTaken"),
        "true_damage_taken": g("trueDamageTaken"),
        "damage_self_mitigated": g("damageSelfMitigated"),
        "total_heal": g("totalHeal"),
        "total_heals_on_teammates": g("totalHealsOnTeammates"),
        "total_damage_shielded_on_teammates": g("totalDamageShieldedOnTeammates"),
        "total_units_healed": g("totalUnitsHealed"),
        "damage_dealt_to_buildings": g("damageDealtToBuildings"),
        "damage_dealt_to_objectives": g("damageDealtToObjectives"),
        "damage_dealt_to_turrets": g("damageDealtToTurrets"),
        "damage_dealt_to_epic_monsters": g("damageDealtToEpicMonsters"),
        "first_blood_kill": int(bool(g("firstBloodKill", False))),
        "first_blood_assist": int(bool(g("firstBloodAssist", False))),
        "first_tower_kill": int(bool(g("firstTowerKill", False))),
        "first_tower_assist": int(bool(g("firstTowerAssist", False))),
        "turret_kills": g("turretKills"), "turret_takedowns": g("turretTakedowns"),
        "turrets_lost": g("turretsLost"),
        "inhibitor_kills": g("inhibitorKills"), "inhibitor_takedowns": g("inhibitorTakedowns"),
        "inhibitors_lost": g("inhibitorsLost"),
        "nexus_kills": g("nexusKills"), "nexus_takedowns": g("nexusTakedowns"),
        "nexus_lost": g("nexusLost"),
        "objectives_stolen": g("objectivesStolen"),
        "objectives_stolen_assists": g("objectivesStolenAssists"),
        "dragon_kills": g("dragonKills"), "baron_kills": g("baronKills"),
        "total_minions_killed": g("totalMinionsKilled"),
        "neutral_minions_killed": g("neutralMinionsKilled"),
        "total_ally_jungle_minions_killed": g("totalAllyJungleMinionsKilled"),
        "total_enemy_jungle_minions_killed": g("totalEnemyJungleMinionsKilled"),
        "gold_earned": g("goldEarned"), "gold_spent": g("goldSpent"),
        "items_purchased": g("itemsPurchased"),
        "consumables_purchased": g("consumablesPurchased"),
        "item0": g("item0"), "item1": g("item1"), "item2": g("item2"),
        "item3": g("item3"), "item4": g("item4"), "item5": g("item5"), "item6": g("item6"),
        "summoner1_id": g("summoner1Id"), "summoner2_id": g("summoner2Id"),
        "summoner1_casts": g("summoner1Casts"), "summoner2_casts": g("summoner2Casts"),
        "spell1_casts": g("spell1Casts"), "spell2_casts": g("spell2Casts"),
        "spell3_casts": g("spell3Casts"), "spell4_casts": g("spell4Casts"),
        "vision_score": g("visionScore"),
        "sight_wards_bought": g("sightWardsBoughtInGame"),
        "vision_wards_bought": g("visionWardsBoughtInGame"),
        "detector_wards_placed": g("detectorWardsPlaced"),
        "wards_placed": g("wardsPlaced"), "wards_killed": g("wardsKilled"),
        "time_ccing_others": g("timeCCingOthers"),
        "total_time_cc_dealt": g("totalTimeCCDealt"),
        "time_spent_dead": g("totalTimeSpentDead"),
        "longest_time_alive": g("longestTimeSpentLiving"),
        "all_in_pings": g("allInPings"), "assist_me_pings": g("assistMePings"),
        "basic_pings": g("basicPings"), "command_pings": g("commandPings"),
        "danger_pings": g("dangerPings"), "enemy_missing_pings": g("enemyMissingPings"),
        "enemy_vision_pings": g("enemyVisionPings"), "get_back_pings": g("getBackPings"),
        "hold_pings": g("holdPings"), "need_vision_pings": g("needVisionPings"),
        "on_my_way_pings": g("onMyWayPings"), "push_pings": g("pushPings"),
        "retreat_pings": g("retreatPings"), "vision_cleared_pings": g("visionClearedPings"),
        "player_augment1": g("playerAugment1"), "player_augment2": g("playerAugment2"),
        "player_augment3": g("playerAugment3"), "player_augment4": g("playerAugment4"),
        "player_augment5": g("playerAugment5"), "player_augment6": g("playerAugment6"),
        "player_subteam_id": g("playerSubteamId"), "subteam_placement": g("subteamPlacement"),
        "placement": g("placement"),
        "challenges_json": json.dumps(p.get("challenges", {})),
        "missions_json":   json.dumps(p.get("missions",   {})),
        "perks_json":      json.dumps(perks),
        "rune_keystone_id":    primary_sel[0] if primary_sel else 0,
        "rune_primary_style":  primary_style,
        "rune_sub_style":      sub_style,
        "rune_p0": primary_sel[0] if len(primary_sel) > 0 else 0,
        "rune_p1": primary_sel[1] if len(primary_sel) > 1 else 0,
        "rune_p2": primary_sel[2] if len(primary_sel) > 2 else 0,
        "rune_p3": primary_sel[3] if len(primary_sel) > 3 else 0,
        "rune_s0": secondary_sel[0] if len(secondary_sel) > 0 else 0,
        "rune_s1": secondary_sel[1] if len(secondary_sel) > 1 else 0,
        "stat_perk_offense":  stat_perks.get("offense",  0),
        "stat_perk_flex":     stat_perks.get("flex",     0),
        "stat_perk_defense":  stat_perks.get("defense",  0),
        "eligible_for_progression": int(bool(g("eligibleForProgression", True))),
    }


def parse_team(team: dict, match_id: str) -> dict:
    obj = team.get("objectives", {}) or {}
    def ob(name, field):
        t = obj.get(name, {})
        return t.get(field, 0) if isinstance(t, dict) else 0

    bans = team.get("bans", []) or []
    ban_ids = [b.get("championId", 0) for b in bans] + [0]*5
    return {
        "match_id":  match_id,
        "team_id":   team.get("teamId", 0),
        "win":       int(bool(team.get("win", False))),
        "baron_first":       ob("baron",     "first"),
        "baron_kills":       ob("baron",     "kills"),
        "champion_first":    ob("champion",  "first"),
        "champion_kills":    ob("champion",  "kills"),
        "dragon_first":      ob("dragon",    "first"),
        "dragon_kills":      ob("dragon",    "kills"),
        "horde_first":       ob("horde",     "first"),
        "horde_kills":       ob("horde",     "kills"),
        "inhibitor_first":   ob("inhibitor", "first"),
        "inhibitor_kills":   ob("inhibitor", "kills"),
        "rift_herald_first": ob("riftHerald","first"),
        "rift_herald_kills": ob("riftHerald","kills"),
        "tower_first":       ob("tower",     "first"),
        "tower_kills":       ob("tower",     "kills"),
        "atakhan_first":     ob("atakhan",   "first"),
        "atakhan_kills":     ob("atakhan",   "kills"),
        "ban1": ban_ids[0], "ban2": ban_ids[1], "ban3": ban_ids[2],
        "ban4": ban_ids[3], "ban5": ban_ids[4],
    }


def parse_frame(frame: dict, match_id: str) -> list:
    rows = []
    ts = frame.get("timestamp", 0)
    pframes = frame.get("participantFrames", {}) or {}
    for pid_str, pf in pframes.items():
        if not isinstance(pf, dict):
            continue
        pos = pf.get("position", {}) or {}
        ds  = pf.get("damageStats", {}) or {}
        cs  = pf.get("championStats", {}) or {}
        rows.append({
            "match_id":       match_id,
            "timestamp_ms":   ts,
            "participant_id": pf.get("participantId", int(pid_str)),
            "current_gold":   pf.get("currentGold", 0),
            "total_gold":     pf.get("totalGold", 0),
            "gold_per_second":pf.get("goldPerSecond", 0),
            "xp":             pf.get("xp", 0),
            "level":          pf.get("level", 0),
            "minions_killed": pf.get("minionsKilled", 0),
            "jungle_minions": pf.get("jungleMinionsKilled", 0),
            "pos_x":          pos.get("x", 0),
            "pos_y":          pos.get("y", 0),
            "time_enemy_cc":  pf.get("timeEnemySpentControlled", 0),
            "magic_dmg_done":     ds.get("magicDamageDone", 0),
            "physical_dmg_done":  ds.get("physicalDamageDone", 0),
            "true_dmg_done":      ds.get("trueDamageDone", 0),
            "total_dmg_done":     ds.get("totalDamageDone", 0),
            "magic_dmg_taken":    ds.get("magicDamageTaken", 0),
            "physical_dmg_taken": ds.get("physicalDamageTaken", 0),
            "true_dmg_taken":     ds.get("trueDamageTaken", 0),
            "total_dmg_taken":    ds.get("totalDamageTaken", 0),
            "total_healed":       ds.get("totalDamageSelfMitigated", 0),
            "self_mitigated":     ds.get("totalDamageSelfMitigated", 0),
        })
    return rows


def parse_event(ev: dict, match_id: str) -> dict:
    etype = ev.get("type", "")
    return {
        "match_id":      match_id,
        "timestamp_ms":  ev.get("timestamp", 0),
        "event_type":    etype,
        "participant_id": ev.get("participantId"),
        "item_id":        ev.get("itemId"),
        "killer_id":      ev.get("killerId"),
        "victim_id":      ev.get("victimId"),
        "assisting_ids_json": json.dumps(ev.get("assistingParticipantIds", [])),
        "bounty":         ev.get("bounty"),
        "shutdown_bounty":ev.get("shutdownBounty"),
        "kill_streak_len":ev.get("killStreakLength"),
        "kill_pos_x":     (ev.get("position") or {}).get("x"),
        "kill_pos_y":     (ev.get("position") or {}).get("y"),
        "victim_damage_json": json.dumps(ev.get("victimDamageReceived", [])) if etype == "CHAMPION_KILL" else None,
        "building_type":  ev.get("buildingType"),
        "lane_type":      ev.get("laneType"),
        "tower_type":     ev.get("towerType"),
        "team_id":        ev.get("teamId"),
        "monster_type":   ev.get("monsterType"),
        "monster_subtype":ev.get("monsterSubType"),
        "ward_type":      ev.get("wardType"),
        "skill_slot":     ev.get("skillSlot"),
        "level_up_type":  ev.get("levelUpType"),
        "level":          ev.get("level"),
        "raw_json":       json.dumps({k: v for k, v in ev.items()
                                      if k not in ("timestamp","type","participantId",
                                                    "itemId","killerId","victimId",
                                                    "assistingParticipantIds","bounty",
                                                    "shutdownBounty","killStreakLength",
                                                    "position","victimDamageReceived",
                                                    "buildingType","laneType","towerType",
                                                    "teamId","monsterType","monsterSubType",
                                                    "wardType","skillSlot","levelUpType","level")}),
    }


# ── DB helpers ─────────────────────────────────────────────────────────────────

def insert_rows(conn: sqlite3.Connection, table: str, rows: list[dict]):
    if not rows:
        return
    cols = list(rows[0].keys())
    ph   = ", ".join("?" * len(cols))
    sql  = f"INSERT OR IGNORE INTO {table} ({', '.join(cols)}) VALUES ({ph})"
    conn.executemany(sql, [list(r.values()) for r in rows])


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ── Main scraper ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-timeline", action="store_true", help="Skip timeline data")
    parser.add_argument("--limit",      type=int, default=0,  help="Only scrape N matches")
    parser.add_argument("--from-match", type=int, default=0,  help="Start from index N")
    args = parser.parse_args()

    # Create schema
    conn = get_conn()
    # Execute schema using sqlite3 executescript (handles multi-statement correctly)
    try:
        conn.executescript(SCHEMA)
    except sqlite3.Error as e:
        print(f"Schema error: {e}")
    conn.commit()

    import urllib.parse
    enc_user = urllib.parse.quote(USERNAME)

    # ── 1. Fetch or load history list ──────────────────────────────────────────
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    hist_cache = CACHE_DIR / "history.json"
    if hist_cache.exists() and hist_cache.stat().st_size > 1_000_000:
        print(f"Loading history from cache ({hist_cache.stat().st_size//1024//1024}MB)...")
        history = json.loads(hist_cache.read_text(encoding="utf-8"))
    else:
        print(f"Fetching history list from {BASE}/get_data/{REGION}/{enc_user}/history ...")
        history = fetch_json(f"{BASE}/get_data/{REGION}/{enc_user}/history")
        if not history:
            print("ERROR: Could not fetch history. Exiting.")
            sys.exit(1)
        hist_cache.write_text(json.dumps(history), encoding="utf-8")
        print(f"Cached {len(history)} matches ({hist_cache.stat().st_size//1024//1024}MB)")

    total = len(history)
    print(f"Total matches in history: {total}")

    # Apply range limits
    start_idx = args.from_match
    end_idx   = start_idx + args.limit if args.limit else total
    batch     = history[start_idx:end_idx]
    print(f"Processing matches [{start_idx}:{end_idx}] = {len(batch)} matches")
    if args.no_timeline:
        print("Timeline: DISABLED (--no-timeline flag)")
    print()

    # ── 2. Determine already-scraped matches ──────────────────────────────────
    existing = set()
    for row in conn.execute("SELECT match_id FROM matches"):
        existing.add(row[0])
    print(f"Already in DB: {len(existing)} matches")

    # ── 3. Iterate and scrape ─────────────────────────────────────────────────
    done = skip = error = 0
    t0   = time.time()

    for i, hist_entry in enumerate(batch):
        mid        = hist_entry.get("mid")
        match_id   = f"{REGION}1_{mid}"
        patch      = hist_entry.get("patch", "")
        timestamp  = hist_entry.get("timestamp", 0)

        if match_id in existing:
            skip += 1
            continue

        abs_idx = start_idx + i
        if (done + skip) % 10 == 0 or done < 5:
            elapsed = time.time() - t0
            rate    = done / max(elapsed, 1)
            remain  = len(batch) - done - skip
            eta_s   = remain / max(rate, 0.001)
            eta_m   = int(eta_s // 60)
            print(f"[{abs_idx+1}/{total}] Scraping... done={done} skip={skip} err={error} "
                  f"rate={rate:.2f}/s ETA={eta_m}m")

        # Fetch stats
        stats_url = f"{BASE}/getmatch/{REGION}/{mid}/stats"
        stats = fetch_json(stats_url)
        time.sleep(REQUEST_DELAY)

        has_stats    = 0
        has_timeline = 0

        if stats and isinstance(stats, dict):
            has_stats = 1
            info = stats.get("info", {})
            meta = stats.get("metadata", {})

            # Determine the tracked player's team
            tracked = next((p for p in (info.get("participants") or [])
                           if any(alias in p.get("riotIdGameName", "").lower()
                                  for alias in ["sampleplayer", "moonbeam"])), None)

            # Teams from history
            teams_hist = hist_entry.get("teams", {})
            side       = hist_entry.get("side", "1")
            win_flag   = hist_entry.get("win", False)

            # Insert match
            conn.execute("""
                INSERT OR IGNORE INTO matches
                (match_id, platform, queue_id, game_mode, game_type, map_id,
                 game_version, patch, game_duration_s, game_creation_ts,
                 game_end_ts, end_of_game_result, tournament_code,
                 tracked_champion_id, tracked_champion_name, tracked_team_id,
                 tracked_win, tracked_kills, tracked_deaths, tracked_assists,
                 tracked_kp, tracked_lane, tracked_side, tracked_ff,
                 tracked_ttmga_t, has_stats, has_timeline, fetched_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                match_id,
                info.get("platformId", REGION+"1"),
                info.get("queueId", hist_entry.get("qid", 0)),
                info.get("gameMode", ""),
                info.get("gameType", ""),
                info.get("mapId", 0),
                info.get("gameVersion", ""),
                patch,
                info.get("gameDuration", hist_entry.get("duration", 0)),
                info.get("gameCreation", timestamp),
                info.get("gameEndTimestamp", 0),
                info.get("endOfGameResult", ""),
                info.get("tournamentCode", ""),
                hist_entry.get("cid", 0),
                tracked.get("championName", "") if tracked else "",
                tracked.get("teamId", 0) if tracked else 0,
                int(bool(win_flag)),
                hist_entry.get("K", 0),
                hist_entry.get("D", 0),
                hist_entry.get("A", 0),
                hist_entry.get("kp", 0),
                hist_entry.get("lane", 0),
                side,
                json.dumps(hist_entry.get("ff")),
                hist_entry.get("ttmga_t", ""),
                has_stats,
                has_timeline,
                time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            ))

            # Insert participants
            part_rows = [parse_participant(p, match_id)
                         for p in (info.get("participants") or [])]
            insert_rows(conn, "participants", part_rows)

            # Insert teams
            team_rows = [parse_team(t, match_id)
                         for t in (info.get("teams") or [])]
            insert_rows(conn, "teams", team_rows)

        else:
            # No stats available - insert minimal match row from history
            conn.execute("""
                INSERT OR IGNORE INTO matches
                (match_id, platform, queue_id, patch, game_duration_s,
                 game_creation_ts, tracked_champion_id, tracked_win,
                 tracked_kills, tracked_deaths, tracked_assists, tracked_kp,
                 tracked_side, has_stats, has_timeline, fetched_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                match_id, REGION+"1",
                hist_entry.get("qid", 0), patch,
                hist_entry.get("duration", 0), timestamp,
                hist_entry.get("cid", 0), int(bool(hist_entry.get("win", False))),
                hist_entry.get("K", 0), hist_entry.get("D", 0), hist_entry.get("A", 0),
                hist_entry.get("kp", 0), hist_entry.get("side", ""),
                0, 0,
                time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            ))
            error += 1

        # Fetch timeline
        if has_stats and not args.no_timeline:
            tl_url  = f"{BASE}/getmatch/{REGION}/{mid}/timeline"
            tl_data = fetch_json(tl_url)
            time.sleep(REQUEST_DELAY)

            if tl_data and isinstance(tl_data, dict):
                has_timeline = 1
                frames = (tl_data.get("info") or {}).get("frames") or []

                frame_rows = []
                event_rows = []
                for frame in frames:
                    frame_rows.extend(parse_frame(frame, match_id))
                    for ev in (frame.get("events") or []):
                        event_rows.append(parse_event(ev, match_id))

                insert_rows(conn, "timeline_frames", frame_rows)
                insert_rows(conn, "timeline_events", event_rows)

                # Update has_timeline flag
                conn.execute("UPDATE matches SET has_timeline=1 WHERE match_id=?",
                             (match_id,))

        conn.commit()
        done += 1

    # ── Summary ───────────────────────────────────────────────────────────────
    elapsed = time.time() - t0
    print()
    print(f"=== Done in {elapsed/60:.1f} min ===")
    print(f"  Scraped:  {done}")
    print(f"  Skipped:  {skip} (already in DB)")
    print(f"  Errors:   {error} (no stats available)")

    # Final counts
    for tbl in ("matches", "participants", "teams", "timeline_frames", "timeline_events"):
        cnt = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        print(f"  {tbl}: {cnt:,} rows")

    conn.close()
    print(f"\nDatabase: {DB_PATH}")


if __name__ == "__main__":
    main()
