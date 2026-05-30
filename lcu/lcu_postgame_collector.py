"""
lcu/lcu_postgame_collector.py
─────────────────────────────
Captures end-of-game statistics for ALL players (both teams) and stores them
in a mode-separated SQLite database for later analysis.

KEY DESIGN RULES:
  - ISOLATED: not used by coaching, rune choices, or any live system
  - MODE-SEPARATED: each game mode has its own tables (no bleed)
  - IDEMPOTENT: duplicate game IDs are silently skipped
  - BEST-EFFORT: partial data is still saved; failures never crash the app
  - ASYNC: runs in background thread, never blocks the overlay

Database:  C:\\Riot Commander\\data\\postgame_stats.db
Tables:    {mode}_matches, {mode}_player_stats, {mode}_item_events
Modes:     ARAM | SR | ARENA | BRAWL | TFT
"""

import asyncio
import json
import logging
import sqlite3
import ssl
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Optional

_log = logging.getLogger("rc.postgame")

# ── Paths ─────────────────────────────────────────────────────────────────────
_ROOT    = Path(__file__).parent.parent
_DB_PATH = _ROOT / "data" / "postgame_stats.db"
_DDRAGON_ITEMS = _ROOT / "data" / "meta" / "ddragon_items.json"
_DDRAGON_RUNES = _ROOT / "data" / "meta" / "ddragon_runes.json"

# ── Game mode normalisation ────────────────────────────────────────────────────
_MODE_MAP = {
    "CLASSIC":    "SR",
    "ARAM":       "ARAM",
    "KIWI":       "ARAM",     # ARAM Mayhem
    "ARAM_5V5":   "ARAM",
    "ARAM_MAYHEM":"ARAM",
    "CHERRY":     "ARENA",
    "NEXUSBLITZ": "BRAWL",
    "URF":        "BRAWL",
    "ONEFORALL":  "BRAWL",
    "ULTBOOK":    "BRAWL",
    "TFT":        "TFT",
}
_VALID_MODES = {"SR", "ARAM", "ARENA", "BRAWL", "TFT"}

def _norm_mode(raw: str) -> str:
    return _MODE_MAP.get(raw.upper(), "SR")

# ── Summoner spell ID → name (DDragon internal names) ─────────────────────────
_SPELL_ID_MAP = {
    1: "Cleanse", 3: "Exhaust", 4: "Flash", 6: "Ghost",
    7: "Heal", 11: "Smite", 12: "Teleport", 13: "Clarity",
    14: "Ignite", 21: "Barrier", 32: "Snowball",
    39: "Mark (Snowball)", 54: "Placeholder",
}

# ── Schema - one set of 3 tables per mode ─────────────────────────────────────
_MODES_SQL = {}
for _m in _VALID_MODES:
    _tbl = _m.lower()
    _MODES_SQL[_m] = f"""
    -- ── {_m} ──────────────────────────────────────────────────────────────────
    CREATE TABLE IF NOT EXISTS {_tbl}_matches (
        match_id        TEXT PRIMARY KEY,
        game_mode       TEXT NOT NULL CHECK(game_mode = '{_m}'),
        map_id          INTEGER,
        game_duration_s INTEGER,
        patch           TEXT,
        captured_at     TEXT NOT NULL,
        raw_mode_string TEXT          -- original Riot gameMode string
    );

    CREATE TABLE IF NOT EXISTS {_tbl}_player_stats (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        match_id        TEXT NOT NULL,
        game_mode       TEXT NOT NULL CHECK(game_mode = '{_m}'),

        -- Identity
        summoner_name   TEXT,
        game_name       TEXT,
        tag_line        TEXT,
        puuid           TEXT,
        champion_id     INTEGER,
        champion_name   TEXT,
        team_id         INTEGER,      -- 100=ORDER/BLUE, 200=CHAOS/RED
        team_result     TEXT,         -- WIN | LOSS
        is_local_player INTEGER,      -- 1 if this is the RC user
        position        TEXT,         -- BOTTOM, SUPPORT, etc. (may be empty in ARAM)

        -- Core KDA
        kills           INTEGER,
        deaths          INTEGER,
        assists         INTEGER,
        level           INTEGER,
        cs              INTEGER,      -- creep/minion score
        gold_earned     INTEGER,

        -- Damage output
        dmg_total       INTEGER,      -- total damage dealt to champions
        dmg_physical    INTEGER,
        dmg_magic       INTEGER,
        dmg_true        INTEGER,
        dmg_total_all   INTEGER,      -- includes minions/structures
        dmg_to_obj      INTEGER,      -- objectives
        dmg_to_turrets  INTEGER,

        -- Damage received / sustain
        dmg_taken       INTEGER,
        dmg_healed      INTEGER,      -- total healing done

        -- Vision
        vision_score    INTEGER,
        wards_placed    INTEGER,
        wards_killed    INTEGER,
        ctrl_wards_bought INTEGER,

        -- Objectives
        turrets_killed  INTEGER,
        inhibs_killed   INTEGER,

        -- Multikills / streaks
        double_kills    INTEGER,
        triple_kills    INTEGER,
        quadra_kills    INTEGER,
        penta_kills     INTEGER,
        largest_kill_spree INTEGER,
        longest_alive_s INTEGER,      -- longest time without dying

        -- CC
        time_cc_others_s INTEGER,

        -- Items (final loadout, item6 = trinket/ward slot)
        item0_id INTEGER, item0_name TEXT,
        item1_id INTEGER, item1_name TEXT,
        item2_id INTEGER, item2_name TEXT,
        item3_id INTEGER, item3_name TEXT,
        item4_id INTEGER, item4_name TEXT,
        item5_id INTEGER, item5_name TEXT,
        item6_id INTEGER, item6_name TEXT,

        -- Summoner spells
        spell1_id INTEGER, spell1_name TEXT,
        spell2_id INTEGER, spell2_name TEXT,

        -- Runes
        rune_keystone_id   INTEGER,
        rune_keystone_name TEXT,
        rune_primary_id    INTEGER,
        rune_primary_name  TEXT,
        rune_secondary_id  INTEGER,
        rune_secondary_name TEXT,
        rune_page_name     TEXT,
        rune_ids_json      TEXT,      -- JSON array of all rune IDs [perk0..perk8]
        rune_names_json    TEXT,      -- JSON array of all rune display names

        -- Stat shards
        stat_shard1 INTEGER,
        stat_shard2 INTEGER,
        stat_shard3 INTEGER,

        -- Team context (for later analysis)
        team_comp_json  TEXT,         -- JSON list of ALL champion names on player's team
        enemy_comp_json TEXT,         -- JSON list of ALL champion names on enemy team

        -- Raw stats blob (everything from Riot API, for future fields)
        raw_stats_json  TEXT,

        FOREIGN KEY (match_id) REFERENCES {_tbl}_matches(match_id)
    );

    CREATE INDEX IF NOT EXISTS idx_{_tbl}_ps_match
        ON {_tbl}_player_stats(match_id);
    CREATE INDEX IF NOT EXISTS idx_{_tbl}_ps_champion
        ON {_tbl}_player_stats(champion_name);
    CREATE INDEX IF NOT EXISTS idx_{_tbl}_ps_summoner
        ON {_tbl}_player_stats(summoner_name);

    CREATE TABLE IF NOT EXISTS {_tbl}_item_events (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        match_id        TEXT NOT NULL,
        game_mode       TEXT NOT NULL CHECK(game_mode = '{_m}'),
        summoner_name   TEXT,
        champion_name   TEXT,
        event_type      TEXT,         -- ITEM_PURCHASED | ITEM_SOLD | ITEM_UNDO | ITEM_DESTROYED
        item_id         INTEGER,
        item_name       TEXT,
        timestamp_s     INTEGER,      -- seconds into the game
        FOREIGN KEY (match_id) REFERENCES {_tbl}_matches(match_id)
    );
    """

# ── Lookup helpers ────────────────────────────────────────────────────────────

def _load_item_map() -> dict:
    """Returns {item_id(int): item_name(str)} from DDragon items JSON."""
    try:
        raw = json.loads(_DDRAGON_ITEMS.read_text(encoding="utf-8"))
        data = raw.get("data", raw) if isinstance(raw, dict) else {}
        return {int(k): v.get("name", str(k)) for k, v in data.items() if k.isdigit()}
    except Exception as exc:
        _log.debug("item map load failed: %s", exc)
        return {}

def _load_rune_map() -> dict:
    """Returns {rune_id(int): rune_name(str)} from DDragon runes JSON."""
    out = {}
    try:
        trees = json.loads(_DDRAGON_RUNES.read_text(encoding="utf-8"))
        for tree in trees:
            out[int(tree.get("id", 0))] = tree.get("name", "")
            for slot in tree.get("slots", []):
                for rune in slot.get("runes", []):
                    out[int(rune.get("id", 0))] = rune.get("name", "")
    except Exception as exc:
        _log.debug("rune map load failed: %s", exc)
    return out

# Cached at module load
_ITEM_MAP = {}
_RUNE_MAP = {}

def _item_name(item_id: int) -> str:
    global _ITEM_MAP
    if not _ITEM_MAP:
        _ITEM_MAP = _load_item_map()
    return _ITEM_MAP.get(item_id, str(item_id)) if item_id else ""

def _rune_name(rune_id: int) -> str:
    global _RUNE_MAP
    if not _RUNE_MAP:
        _RUNE_MAP = _load_rune_map()
    return _RUNE_MAP.get(rune_id, str(rune_id)) if rune_id else ""


# ── Database ──────────────────────────────────────────────────────────────────

_db_lock = threading.Lock()

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def _ensure_schema() -> None:
    """Create all mode tables if they don't exist."""
    with _db_lock:
        conn = _get_conn()
        try:
            for mode, sql in _MODES_SQL.items():
                for stmt in sql.split(";"):
                    stmt = stmt.strip()
                    if stmt:
                        conn.execute(stmt)
            conn.commit()
            _log.debug("postgame_stats DB schema OK (%s)", _DB_PATH)
        except Exception as exc:
            _log.error("postgame_stats schema error: %s", exc)
        finally:
            conn.close()


# ── Stat extraction helpers ───────────────────────────────────────────────────

def _s(stats: dict, *keys, default=0):
    """Try multiple field name variants (CAPS + camelCase) and return first found."""
    for k in keys:
        v = stats.get(k)
        if v is None:
            v = stats.get(k.upper())
        if v is None:
            v = stats.get(k.lower())
        if v is not None:
            try:
                return int(v)
            except (ValueError, TypeError):
                return v
    return default

def _parse_player(player: dict, team_result: str,
                  team_comp: list, enemy_comp: list,
                  item_map: dict, rune_map: dict,
                  game_mode: str) -> dict:
    """
    Parse one player entry from the EOG stats block into a flat dict
    ready for database insertion.
    """
    stats = player.get("stats", {})
    if not isinstance(stats, dict):
        stats = {}

    # Identity
    summoner_name = (player.get("summonerName") or
                     player.get("riotIdGameName") or
                     player.get("displayName") or "")
    game_name  = player.get("riotIdGameName") or player.get("gameName") or summoner_name
    tag_line   = player.get("tagLine") or player.get("riotIdTagline") or ""
    puuid      = player.get("puuid") or ""
    champ_id   = _s(player, "championId", "champion_id", default=0)
    champ_name = (player.get("championName") or
                  player.get("champion_name") or
                  player.get("champion", {}).get("name", "") if isinstance(player.get("champion"), dict) else "" or "")
    position   = player.get("selectedPosition") or player.get("teamPosition") or ""
    is_local   = int(bool(player.get("isLocalPlayer") or player.get("is_local_player")))

    # Items (stat keys: ITEM0..ITEM6  or  item0..item6)
    items = []
    for i in range(7):
        iid = _s(stats, f"ITEM{i}", f"item{i}", default=0)
        items.append((iid, item_map.get(iid, "") if iid else ""))

    # Summoner spells (player-level, not stats)
    sp1_id = _s(player, "spell1Id", "SPELL1", "summoner1Id", default=0)
    sp2_id = _s(player, "spell2Id", "SPELL2", "summoner2Id", default=0)
    if sp1_id == 0:
        sp1_id = _s(stats, "SPELL1", "spell1", default=0)
    if sp2_id == 0:
        sp2_id = _s(stats, "SPELL2", "spell2", default=0)

    # Runes - try player.perks first (cleaner), then stats.PERK*
    perks = player.get("perks") or {}
    if isinstance(perks, dict):
        perk_ids  = perks.get("perkIds") or perks.get("perk_ids") or []
        perk_pri  = int(perks.get("perkStyle") or perks.get("perkPrimaryStyle") or 0)
        perk_sub  = int(perks.get("perkSubStyle") or perks.get("perkSecondaryStyle") or 0)
    else:
        perk_ids = []
        perk_pri = perk_sub = 0

    # Fallback: read PERK0..PERK8 from stats
    if not perk_ids:
        for i in range(9):
            v = _s(stats, f"PERK{i}", f"perk{i}", default=None)
            if v:
                perk_ids.append(v)
    if not perk_pri:
        perk_pri = _s(stats, "PERK_PRIMARY_STYLE", "perkPrimaryStyle", default=0)
    if not perk_sub:
        perk_sub = _s(stats, "PERK_SUB_STYLE", "perkSubStyle", "PERK_SECONDARY_STYLE", default=0)

    keystone_id   = perk_ids[0] if perk_ids else 0
    stat_shards   = perk_ids[6:9] if len(perk_ids) >= 9 else [0, 0, 0]
    rune_names    = [rune_map.get(rid, "") for rid in perk_ids]

    return {
        "summoner_name":      summoner_name,
        "game_name":          game_name,
        "tag_line":           tag_line,
        "puuid":              puuid,
        "champion_id":        champ_id,
        "champion_name":      champ_name,
        "team_result":        team_result,
        "is_local_player":    is_local,
        "position":           position,
        # KDA
        "kills":              _s(stats, "KILLS", "kills"),
        "deaths":             _s(stats, "DEATHS", "deaths"),
        "assists":            _s(stats, "ASSISTS", "assists"),
        "level":              _s(stats, "CHAMPION_LEVEL", "champLevel", "level"),
        "cs":                 _s(stats, "MINIONS_KILLED", "minionsKilled", "cs"),
        "gold_earned":        _s(stats, "GOLD_EARNED", "goldEarned"),
        # Damage
        "dmg_total":          _s(stats, "TOTAL_DAMAGE_DEALT_TO_CHAMPIONS", "totalDamageDealtToChampions"),
        "dmg_physical":       _s(stats, "PHYSICAL_DAMAGE_DEALT_TO_CHAMPIONS", "physicalDamageDealtToChampions"),
        "dmg_magic":          _s(stats, "MAGIC_DAMAGE_DEALT_TO_CHAMPIONS", "magicDamageDealtToChampions"),
        "dmg_true":           _s(stats, "TRUE_DAMAGE_DEALT_TO_CHAMPIONS", "trueDamageDealtToChampions"),
        "dmg_total_all":      _s(stats, "TOTAL_DAMAGE_DEALT", "totalDamageDealt"),
        "dmg_to_obj":         _s(stats, "DAMAGE_DEALT_TO_OBJECTIVES", "damageDealtToObjectives"),
        "dmg_to_turrets":     _s(stats, "DAMAGE_DEALT_TO_TURRETS", "damageDealtToTurrets"),
        "dmg_taken":          _s(stats, "TOTAL_DAMAGE_TAKEN", "totalDamageTaken"),
        "dmg_healed":         _s(stats, "TOTAL_HEAL", "totalHeal", "totalHealsOnTeammates"),
        # Vision
        "vision_score":       _s(stats, "VISION_SCORE", "visionScore"),
        "wards_placed":       _s(stats, "WARDS_PLACED", "wardsPlaced"),
        "wards_killed":       _s(stats, "WARDS_KILLED", "wardsKilled"),
        "ctrl_wards_bought":  _s(stats, "SIGHT_WARDS_BOUGHT_IN_GAME", "controlWardsPlaced", "visionWardsBoughtInGame"),
        # Objectives
        "turrets_killed":     _s(stats, "TURRETS_KILLED", "turretKills"),
        "inhibs_killed":      _s(stats, "INHIBITOR_KILLS", "inhibitorKills"),
        # Multikills
        "double_kills":       _s(stats, "DOUBLE_KILLS", "doubleKills"),
        "triple_kills":       _s(stats, "TRIPLE_KILLS", "tripleKills"),
        "quadra_kills":       _s(stats, "QUADRA_KILLS", "quadraKills"),
        "penta_kills":        _s(stats, "PENTA_KILLS", "pentaKills"),
        "largest_kill_spree": _s(stats, "LARGEST_KILLING_SPREE", "largestKillingSpree"),
        "longest_alive_s":    _s(stats, "LONGEST_TIME_SPENT_LIVING", "longestTimeSpentLiving"),
        "time_cc_others_s":   _s(stats, "TOTAL_CC_TIME", "totalTimeCCingOthers"),
        # Items
        "item0_id": items[0][0], "item0_name": items[0][1],
        "item1_id": items[1][0], "item1_name": items[1][1],
        "item2_id": items[2][0], "item2_name": items[2][1],
        "item3_id": items[3][0], "item3_name": items[3][1],
        "item4_id": items[4][0], "item4_name": items[4][1],
        "item5_id": items[5][0], "item5_name": items[5][1],
        "item6_id": items[6][0], "item6_name": items[6][1],
        # Spells
        "spell1_id": sp1_id, "spell1_name": _SPELL_ID_MAP.get(sp1_id, ""),
        "spell2_id": sp2_id, "spell2_name": _SPELL_ID_MAP.get(sp2_id, ""),
        # Runes
        "rune_keystone_id":    keystone_id,
        "rune_keystone_name":  rune_map.get(keystone_id, ""),
        "rune_primary_id":     perk_pri,
        "rune_primary_name":   rune_map.get(perk_pri, ""),
        "rune_secondary_id":   perk_sub,
        "rune_secondary_name": rune_map.get(perk_sub, ""),
        "rune_page_name":      player.get("runes", {}).get("name", "") if isinstance(player.get("runes"), dict) else "",
        "rune_ids_json":       json.dumps(perk_ids),
        "rune_names_json":     json.dumps(rune_names),
        "stat_shard1":         stat_shards[0] if stat_shards else 0,
        "stat_shard2":         stat_shards[1] if len(stat_shards) > 1 else 0,
        "stat_shard3":         stat_shards[2] if len(stat_shards) > 2 else 0,
        # Context
        "team_comp_json":  json.dumps(team_comp),
        "enemy_comp_json": json.dumps(enemy_comp),
        "raw_stats_json":  json.dumps(stats),
    }


def _save_eog(eog: dict, game_mode: str, item_map: dict, rune_map: dict) -> None:
    """Parse and save a full EOG stats block to the appropriate mode tables."""
    mode      = _norm_mode(game_mode)
    tbl       = mode.lower()
    match_id  = str(eog.get("gameId") or eog.get("game_id") or "")
    if not match_id:
        _log.warning("postgame: no gameId in EOG data - skip")
        return

    captured_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    game_len    = int(eog.get("gameLength") or eog.get("gameDuration") or 0)
    map_id      = int(eog.get("mapId") or 0)
    patch       = str(eog.get("gameVersion") or eog.get("patch") or "")

    # Normalise teams structure - LCU EOG uses {"teams": [...]} or flat player list
    teams = eog.get("teams") or []
    if not teams:
        # Some versions have players directly under the EOG block
        players_raw = eog.get("players") or eog.get("allPlayers") or []
        if players_raw:
            teams = [{"teamId": 100, "win": "Win", "players": players_raw}]

    if not teams:
        _log.warning("postgame: no teams data in EOG block for match %s", match_id)
        return

    # Build team comps
    team_champs = {}  # teamId -> [champion names]
    for team in teams:
        tid = int(team.get("teamId", 100))
        champs = [p.get("championName") or p.get("champion", {}).get("name", "?")
                  if isinstance(p.get("champion"), dict) else
                  p.get("championName") or "?"
                  for p in (team.get("players") or [])]
        team_champs[tid] = champs

    all_team_ids = list(team_champs.keys())

    with _db_lock:
        conn = _get_conn()
        try:
            # 2026-04-27 audit: collapse SELECT-then-INSERT into one
            # INSERT OR IGNORE so a same-process race on _db_lock release
            # (or a parallel external writer of the same DB) can't sneak
            # a second insert between the existence check and the write.
            cur = conn.execute(
                f"""INSERT OR IGNORE INTO {tbl}_matches
                    (match_id, game_mode, map_id, game_duration_s, patch, captured_at, raw_mode_string)
                    VALUES (?,?,?,?,?,?,?)""",
                (match_id, mode, map_id, game_len, patch, captured_at, game_mode)
            )
            if cur.rowcount == 0:
                _log.info("postgame: match %s already stored - skip", match_id)
                return

            # Insert player rows
            for team in teams:
                tid     = int(team.get("teamId", 100))
                win_str = str(team.get("win", "")).lower()
                result  = "WIN" if win_str in ("win", "1", "true") else "LOSS"
                players = team.get("players") or []

                enemy_ids = [t for t in all_team_ids if t != tid]
                enemy_comp = []
                for eid in enemy_ids:
                    enemy_comp.extend(team_champs.get(eid, []))
                team_comp = team_champs.get(tid, [])

                for player in players:
                    row = _parse_player(
                        player, result, team_comp, enemy_comp,
                        item_map, rune_map, mode
                    )
                    row["match_id"]  = match_id
                    row["game_mode"] = mode
                    row["team_id"]   = tid

                    cols   = ", ".join(row.keys())
                    ph     = ", ".join("?" * len(row))
                    vals   = list(row.values())
                    conn.execute(
                        f"INSERT INTO {tbl}_player_stats ({cols}) VALUES ({ph})", vals
                    )

            conn.commit()
            player_count = sum(len(t.get("players") or []) for t in teams)
            _log.info(
                "postgame: saved match %s  mode=%s  players=%d  duration=%ds",
                match_id, mode, player_count, game_len
            )
        except Exception as exc:
            conn.rollback()
            _log.error("postgame: save failed for match %s: %s", match_id, exc)
        finally:
            conn.close()


def _save_item_events(match_id: str, mode: str,
                      events: list, item_map: dict) -> None:
    """Save item purchase timeline events (best-effort)."""
    if not events:
        return
    tbl = _norm_mode(mode).lower()
    rows = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        ev_type = ev.get("type") or ev.get("eventType") or ""
        if ev_type not in ("ITEM_PURCHASED", "ITEM_SOLD", "ITEM_UNDO", "ITEM_DESTROYED"):
            continue
        rows.append((
            match_id,
            tbl.upper(),
            ev.get("participantId") or ev.get("summonerName") or "",
            ev.get("championName") or "",
            ev_type,
            int(ev.get("itemId") or 0),
            item_map.get(int(ev.get("itemId") or 0), ""),
            int((ev.get("timestamp") or 0) // 1000),
        ))
    if not rows:
        return
    with _db_lock:
        conn = _get_conn()
        try:
            conn.executemany(
                f"""INSERT INTO {tbl}_item_events
                    (match_id, game_mode, summoner_name, champion_name,
                     event_type, item_id, item_name, timestamp_s)
                    VALUES (?,?,?,?,?,?,?,?)""",
                rows
            )
            conn.commit()
            _log.info("postgame: saved %d item events for match %s", len(rows), match_id)
        except Exception as exc:
            conn.rollback()
            _log.debug("postgame: item events save failed: %s", exc)
        finally:
            conn.close()


# ── LCU HTTP helper ───────────────────────────────────────────────────────────

class PostgameCollector:
    """
    Background worker that monitors the LCU gameflow phase and captures
    end-of-game statistics when the client enters the post-game lobby.

    Usage:
        collector = PostgameCollector(lcu_client)
        collector.start()                   # starts monitoring thread
        collector.trigger(game_mode)        # called by game lifecycle on game end
        collector.stop()
    """

    # How long to poll for EOG phase after game_end signal (seconds)
    _EOG_TIMEOUT_S  = 120
    # Poll interval while waiting for EOG phase
    _POLL_INTERVAL  = 3.0
    # Short delay after EOG phase detected before fetching (client needs moment to populate)
    _FETCH_DELAY    = 4.0

    def __init__(self, lcu_client):
        self._lcu   = lcu_client
        self._ssl   = ssl.create_default_context()
        self._ssl.check_hostname = False
        self._ssl.verify_mode   = ssl.CERT_NONE
        self._stop  = threading.Event()
        self._trigger = threading.Event()
        self._game_mode_hint = "CLASSIC"
        self._thread: Optional[threading.Thread] = None
        self._task: Optional[Any] = None

        # Pre-load lookup maps (warm cache)
        global _ITEM_MAP, _RUNE_MAP
        if not _ITEM_MAP:
            _ITEM_MAP = _load_item_map()
        if not _RUNE_MAP:
            _RUNE_MAP = _load_rune_map()

        _ensure_schema()

    # ── Public API ──────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the background monitoring thread."""
        if self._thread and self._thread.is_alive():
            return
        if self._task is not None:
            return
        self._stop.clear()
        try:
            from app._loop import get_loop as _get_loop
            _sched = _get_loop()
        except Exception:
            _sched = None
        if _sched is not None:
            self._task = _sched.spawn_task(self._run_async())
            _log.info("PostgameCollector started (async)")
        else:
            self._thread = threading.Thread(
                target=self._run, daemon=True, name="rc.postgame"
            )
            self._thread.start()
            _log.info("PostgameCollector started (thread)")

    def stop(self) -> None:
        """Signal the monitoring thread to stop."""
        self._stop.set()
        self._trigger.set()
        if self._task is not None:
            try: self._task.cancel()
            except Exception: pass
            self._task = None

    def trigger(self, game_mode: str = "CLASSIC") -> None:
        """
        Called by game lifecycle when a game ends.
        Arms the EOG collection for the next post-game lobby detection.
        """
        self._game_mode_hint = game_mode
        self._trigger.set()
        _log.info("PostgameCollector: triggered for mode=%s", game_mode)

    # ── Internal ────────────────────────────────────────────────────────────

    def _run(self) -> None:
        """Background loop - waits for trigger, then captures EOG data."""
        while not self._stop.is_set():
            # Wait for a game-end trigger
            triggered = self._trigger.wait(timeout=30.0)
            if self._stop.is_set():
                break
            if not triggered:
                continue
            self._trigger.clear()
            self._capture_after_trigger(self._game_mode_hint)

    async def _run_async(self) -> None:
        """Async equivalent of _run - wraps the blocking trigger.wait + the
        EOG-poll/HTTP burst in asyncio.to_thread so the AppLoop never
        blocks on the embedded time.sleep + synchronous LCU calls."""
        while not self._stop.is_set():
            triggered = await asyncio.to_thread(self._trigger.wait, 30.0)
            if self._stop.is_set():
                break
            if not triggered:
                continue
            self._trigger.clear()
            try:
                await asyncio.to_thread(self._capture_after_trigger, self._game_mode_hint)
            except asyncio.CancelledError:
                return
            except Exception as exc:
                _log.debug("PostgameCollector async tick: %s", exc)

    def _capture_after_trigger(self, game_mode: str) -> None:
        """One trigger cycle: poll for EOG phase, capture when seen, fall
        back to match history if timeout. Shared by sync + async paths."""
        _log.info("PostgameCollector: waiting for EndOfGame phase (mode=%s)", game_mode)
        deadline = time.time() + self._EOG_TIMEOUT_S
        captured = False
        while time.time() < deadline and not self._stop.is_set():
            phase = self._get_gameflow_phase()
            if phase and "EndOfGame" in phase:
                _log.info("PostgameCollector: EndOfGame phase detected, waiting %ss then fetching", self._FETCH_DELAY)
                time.sleep(self._FETCH_DELAY)
                captured = self._capture(game_mode)
                break
            time.sleep(self._POLL_INTERVAL)
        if not captured:
            _log.info("PostgameCollector: EOG phase not detected, trying match history fallback")
            self._capture_via_history(game_mode)

    def _capture(self, game_mode: str) -> bool:
        """Try all EOG endpoints in order. Returns True if something was saved."""
        eog = self._fetch_eog_stats_block()
        if eog:
            _save_eog(eog, game_mode, _ITEM_MAP, _RUNE_MAP)
            # Best-effort: try to get item timeline from match history
            self._try_fetch_timeline(str(eog.get("gameId") or ""), game_mode)
            return True

        # Fallback: try match history
        return self._capture_via_history(game_mode)

    def _capture_via_history(self, game_mode: str) -> bool:
        """
        Fallback: get the most recent match from LCU match history and save it.
        The match history JSON has a different (but richer) structure.
        """
        try:
            summoner = self._lcu_get("/lol-summoner/v1/current-summoner")
            if not isinstance(summoner, dict):
                return False
            puuid = summoner.get("puuid") or summoner.get("accountId") or ""
            if not puuid:
                return False

            # Get last 1 match
            hist = self._lcu_get(f"/lol-match-history/v1/products/lol/{puuid}/matches?begin=0&end=1")
            if not isinstance(hist, dict):
                return False

            games = hist.get("games", {})
            if isinstance(games, dict):
                game_list = games.get("games", [])
            elif isinstance(games, list):
                game_list = games
            else:
                return False

            if not game_list:
                return False

            game = game_list[0]
            # Adapt match history format to EOG format
            adapted = self._adapt_match_history(game)
            if adapted:
                raw_mode = adapted.get("gameMode") or game.get("gameMode") or game_mode
                _save_eog(adapted, raw_mode, _ITEM_MAP, _RUNE_MAP)
                return True
        except Exception as exc:
            _log.debug("postgame history fallback failed: %s", exc)
        return False

    def _try_fetch_timeline(self, game_id: str, game_mode: str) -> None:
        """Best-effort: fetch item purchase timeline from match history."""
        if not game_id:
            return
        try:
            summoner = self._lcu_get("/lol-summoner/v1/current-summoner")
            if not isinstance(summoner, dict):
                return
            puuid = summoner.get("puuid") or ""
            if not puuid:
                return
            timeline = self._lcu_get(f"/lol-match-history/v1/products/lol/{puuid}/matches/{game_id}/timeline")
            if isinstance(timeline, dict):
                frames = timeline.get("frames") or []
                events = []
                for frame in frames:
                    if isinstance(frame, dict):
                        for ev in (frame.get("events") or []):
                            events.append(ev)
                _save_item_events(game_id, game_mode, events, _ITEM_MAP)
        except Exception as exc:
            _log.debug("postgame timeline fetch failed: %s", exc)

    def _adapt_match_history(self, game: dict) -> Optional[dict]:
        """
        Convert LCU match history entry format to the same structure
        as the EOG stats block so _save_eog can process either.
        """
        if not isinstance(game, dict):
            return None

        game_id   = game.get("gameId")
        game_mode = game.get("gameMode") or "CLASSIC"
        game_len  = game.get("gameDuration") or 0
        map_id    = game.get("mapId") or 0
        version   = game.get("gameVersion") or ""

        participants = game.get("participants") or []
        identities   = game.get("participantIdentities") or []
        teams_raw    = game.get("teams") or []

        # Build puuid/name map from identities
        id_map = {}
        for ident in identities:
            pid   = ident.get("participantId") or 0
            pinfo = ident.get("player") or {}
            id_map[pid] = {
                "summonerName": pinfo.get("summonerName") or pinfo.get("riotIdGameName") or "",
                "gameName":     pinfo.get("gameName") or "",
                "tagLine":      pinfo.get("tagLine") or "",
                "puuid":        pinfo.get("puuid") or "",
            }

        # Build team win map
        team_wins = {}
        for t in teams_raw:
            tid = int(t.get("teamId") or 100)
            team_wins[tid] = (str(t.get("win") or "").lower() == "win")

        # Group participants by team
        by_team = {}
        for p in participants:
            tid  = int(p.get("teamId") or 100)
            pid  = p.get("participantId") or 0
            ident = id_map.get(pid, {})

            stats = p.get("stats") or {}
            # LCU match history uses camelCase stats
            player_entry = {
                "summonerName": ident.get("summonerName") or "",
                "gameName":     ident.get("gameName") or "",
                "tagLine":      ident.get("tagLine") or "",
                "puuid":        ident.get("puuid") or "",
                "championId":   p.get("championId") or 0,
                "championName": p.get("championName") or "",
                "teamId":       tid,
                "spell1Id":     p.get("spell1Id") or 0,
                "spell2Id":     p.get("spell2Id") or 0,
                "stats":        stats,
                "perks": {
                    "perkStyle":    stats.get("perkPrimaryStyle") or 0,
                    "perkSubStyle": stats.get("perkSubStyle") or 0,
                    "perkIds": [
                        stats.get(f"perk{i}") or 0 for i in range(6)
                    ] + [
                        stats.get(f"statPerk{i}") or 0 for i in range(3)
                    ],
                },
            }
            by_team.setdefault(tid, []).append(player_entry)

        teams_out = []
        for tid, players in by_team.items():
            teams_out.append({
                "teamId":  tid,
                "win":     "Win" if team_wins.get(tid) else "Fail",
                "players": players,
            })

        return {
            "gameId":      game_id,
            "gameMode":    game_mode,
            "gameLength":  game_len,
            "mapId":       map_id,
            "gameVersion": version,
            "teams":       teams_out,
        }

    # ── LCU helpers ─────────────────────────────────────────────────────────

    def _lcu_get(self, path: str):
        port = getattr(self._lcu, "_port", None)
        auth = getattr(self._lcu, "_auth", None)
        if not port or not auth:
            return None
        from core.game_host import GAME_HOST
        url = f"https://{GAME_HOST}:{port}{path}"
        req = urllib.request.Request(url, headers={
            "Authorization": f"Basic {auth}",
            "Accept":        "application/json,*/*",
        })
        try:
            with urllib.request.urlopen(req, context=self._ssl, timeout=5) as r:
                return json.loads(r.read())
        except Exception:
            return None

    def _get_gameflow_phase(self) -> str:
        result = self._lcu_get("/lol-gameflow/v1/phase")
        if isinstance(result, str):
            return result
        return ""

    def _fetch_eog_stats_block(self) -> Optional[dict]:
        """Try the several EOG endpoint variants Riot has used across versions."""
        endpoints = [
            "/lol-end-of-game/v1/eog-stats-block",
            "/lol-end-of-game/v1/game-client-eog-stats-block",
            "/lol-end-of-game/v1/champion-mastery-updates",
        ]
        for ep in endpoints:
            data = self._lcu_get(ep)
            if isinstance(data, dict) and data.get("gameId"):
                _log.info("postgame: got EOG stats from %s", ep)
                return data
        return None


# ── Module-level singleton ─────────────────────────────────────────────────────

_collector: Optional[PostgameCollector] = None

def get_collector() -> Optional[PostgameCollector]:
    return _collector

def init_collector(lcu_client: object) -> PostgameCollector:
    """Create and start the singleton collector. Call once at app startup."""
    global _collector
    if _collector is None:
        _collector = PostgameCollector(lcu_client)
        _collector.start()
    return _collector
