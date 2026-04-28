"""
core/match_db.py — SQLite match history database for Riot Commander.

Stores per-match results across all modes (SR, ARAM, Arena, Brawl, TFT).
TFT matches include comp/trait/unit data for ranked LP analysis.

Usage:
    from core.match_db import MatchDB
    db = MatchDB(app_dir / "data" / "match_history.db")
    db.save_match({...})
    recent = db.get_recent("TFT", limit=20)
    best = db.get_best_comps(min_placement=4, limit=10)

AUDIT 2026-04-28 (proposal 1.2): WAL journal mode + per-thread connections.
Replaces the previous single-connection-under-Lock model. WAL allows
concurrent readers without blocking writes; per-thread connections drop
the lock from the hot path entirely. SQLite still serializes write
commits internally via its WAL writer slot, so multi-writer remains safe.
"""

import json
import sqlite3
import threading
import logging
from datetime import datetime
from pathlib import Path

_log = logging.getLogger("rc.match_db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS matches (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT NOT NULL,
    mode        TEXT NOT NULL,          -- SR, ARAM, ARENA, BRAWL, TFT
    champion    TEXT DEFAULT '',
    grade       TEXT DEFAULT '',        -- S, A, B, C, D, F
    game_time_s REAL DEFAULT 0,
    -- SR / ARAM / Brawl fields
    kills       INTEGER DEFAULT 0,
    deaths      INTEGER DEFAULT 0,
    assists     INTEGER DEFAULT 0,
    cs          INTEGER DEFAULT 0,
    cs_per_min  REAL DEFAULT 0,
    gold        INTEGER DEFAULT 0,
    gold_per_min REAL DEFAULT 0,
    kda_str     TEXT DEFAULT '',
    kp_pct      REAL DEFAULT 0,
    -- TFT fields
    tft_placement INTEGER DEFAULT 0,   -- 1-8
    tft_stage     INTEGER DEFAULT 0,
    tft_level     INTEGER DEFAULT 0,
    tft_comp      TEXT DEFAULT '',      -- comp archetype name
    tft_traits    TEXT DEFAULT '',      -- JSON list of active traits
    tft_units     TEXT DEFAULT '',      -- JSON list of board units
    tft_augments  TEXT DEFAULT '',      -- JSON list of augments
    tft_items     TEXT DEFAULT '',      -- JSON list of key items
    -- Arena fields
    arena_rounds_won  INTEGER DEFAULT 0,
    arena_placement   INTEGER DEFAULT 0,
    -- Notes
    notes       TEXT DEFAULT '',        -- JSON list of improvement notes
    label       TEXT DEFAULT '',        -- grade label text
    raw_data    TEXT DEFAULT ''         -- full JSON dump for future reference
);

CREATE INDEX IF NOT EXISTS idx_matches_mode ON matches(mode);
CREATE INDEX IF NOT EXISTS idx_matches_timestamp ON matches(timestamp);
CREATE INDEX IF NOT EXISTS idx_matches_tft_comp ON matches(tft_comp);
CREATE INDEX IF NOT EXISTS idx_matches_tft_placement ON matches(tft_placement);
CREATE INDEX IF NOT EXISTS idx_matches_grade ON matches(grade);
"""


class MatchDB:
    def __init__(self, db_path):
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # Per-thread connections held in thread-local storage. SQLite
        # rejects sharing a connection across threads by default, and WAL
        # mode is happiest when each thread has its own handle anyway.
        self._tlocal = threading.local()
        # One-shot setup: enable WAL + populate schema. The connection is
        # discarded on exit; later threads re-open via _conn().
        setup = sqlite3.connect(str(self._path))
        try:
            # journal_mode=WAL is a persistent file property; once set the
            # DB stays in WAL across reopens. synchronous=NORMAL is the
            # WAL-safe fast pairing.
            setup.execute("PRAGMA journal_mode = WAL")
            setup.execute("PRAGMA synchronous = NORMAL")
            setup.execute("PRAGMA busy_timeout = 5000")
            setup.executescript(_SCHEMA)
            setup.commit()
        finally:
            setup.close()
        _log.info("MatchDB opened (WAL): %s", self._path)

    def _conn(self) -> sqlite3.Connection:
        c = getattr(self._tlocal, "conn", None)
        if c is None:
            c = sqlite3.connect(str(self._path))
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA busy_timeout = 5000")
            self._tlocal.conn = c
        return c

    def save_match(self, data: dict):
        """Save a match record. Accepts rating data dict from performance_tracker."""
        cols = [
            "timestamp", "mode", "champion", "grade", "game_time_s",
            "kills", "deaths", "assists", "cs", "cs_per_min",
            "gold", "gold_per_min", "kda_str", "kp_pct",
            "tft_placement", "tft_stage", "tft_level", "tft_comp",
            "tft_traits", "tft_units", "tft_augments", "tft_items",
            "arena_rounds_won", "arena_placement",
            "notes", "label", "raw_data",
        ]
        vals = {c: data.get(c, "") for c in cols}
        # Serialize lists to JSON
        for k in ("tft_traits", "tft_units", "tft_augments", "tft_items", "notes"):
            v = vals.get(k)
            if isinstance(v, (list, dict)):
                vals[k] = json.dumps(v)
        if not vals.get("timestamp"):
            vals["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if not vals.get("raw_data"):
            vals["raw_data"] = json.dumps(data, default=str)

        placeholders = ", ".join(f":{c}" for c in cols)
        col_names = ", ".join(cols)
        try:
            c = self._conn()
            c.execute(
                f"INSERT INTO matches ({col_names}) VALUES ({placeholders})", vals)
            c.commit()
            _log.info("Match saved: mode=%s grade=%s", vals["mode"], vals["grade"])
        except Exception as exc:
            _log.error("Match save failed: %s", exc)

    def get_recent(self, mode: str = "", limit: int = 20) -> list:
        """Get recent matches, optionally filtered by mode."""
        c = self._conn()
        if mode:
            rows = c.execute(
                "SELECT * FROM matches WHERE mode = ? ORDER BY timestamp DESC LIMIT ?",
                (mode, limit)).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM matches ORDER BY timestamp DESC LIMIT ?",
                (limit,)).fetchall()
        return [dict(r) for r in rows]

    def get_best_comps(self, min_games: int = 2, limit: int = 10) -> list:
        """Get TFT comps ranked by average placement (best first).
        Only includes comps played at least min_games times."""
        c = self._conn()
        rows = c.execute("""
            SELECT tft_comp,
                   COUNT(*) as games,
                   ROUND(AVG(tft_placement), 1) as avg_place,
                   MIN(tft_placement) as best,
                   MAX(tft_placement) as worst,
                   ROUND(AVG(CASE WHEN tft_placement <= 4 THEN 1.0 ELSE 0.0 END) * 100) as top4_pct,
                   GROUP_CONCAT(DISTINCT tft_traits) as all_traits
            FROM matches
            WHERE mode = 'TFT' AND tft_comp != '' AND tft_placement > 0
            GROUP BY tft_comp
            HAVING games >= ?
            ORDER BY avg_place ASC
            LIMIT ?
        """, (min_games, limit)).fetchall()
        return [dict(r) for r in rows]

    def get_worst_comps(self, min_games: int = 2, limit: int = 5) -> list:
        """Get TFT comps ranked by worst average placement."""
        c = self._conn()
        rows = c.execute("""
            SELECT tft_comp, COUNT(*) as games,
                   ROUND(AVG(tft_placement), 1) as avg_place,
                   ROUND(AVG(CASE WHEN tft_placement <= 4 THEN 1.0 ELSE 0.0 END) * 100) as top4_pct
            FROM matches
            WHERE mode = 'TFT' AND tft_comp != '' AND tft_placement > 0
            GROUP BY tft_comp
            HAVING games >= ?
            ORDER BY avg_place DESC
            LIMIT ?
        """, (min_games, limit)).fetchall()
        return [dict(r) for r in rows]

    def get_tft_streak(self, limit: int = 10) -> dict:
        """Get recent TFT performance summary."""
        c = self._conn()
        rows = c.execute("""
            SELECT tft_placement FROM matches
            WHERE mode = 'TFT' AND tft_placement > 0
            ORDER BY timestamp DESC LIMIT ?
        """, (limit,)).fetchall()
        if not rows:
            return {}
        placements = [r["tft_placement"] for r in rows]
        return {
            "last_n": len(placements),
            "avg_place": round(sum(placements) / len(placements), 1),
            "top4_count": sum(1 for p in placements if p <= 4),
            "top4_pct": round(sum(1 for p in placements if p <= 4) / len(placements) * 100),
            "wins": sum(1 for p in placements if p == 1),
            "placements": placements,
        }

    def get_mode_stats(self, mode: str, limit: int = 20) -> dict:
        """Get aggregate stats for a mode over recent games."""
        c = self._conn()
        rows = c.execute("""
            SELECT grade, kills, deaths, assists, cs_per_min, gold_per_min, kp_pct
            FROM matches WHERE mode = ? ORDER BY timestamp DESC LIMIT ?
        """, (mode, limit)).fetchall()
        if not rows:
            return {}
        grades = [r["grade"] for r in rows]
        return {
            "games": len(rows),
            "avg_kills": round(sum(r["kills"] for r in rows) / len(rows), 1),
            "avg_deaths": round(sum(r["deaths"] for r in rows) / len(rows), 1),
            "avg_cs_pm": round(sum(r["cs_per_min"] for r in rows) / len(rows), 1),
            "avg_gpm": round(sum(r["gold_per_min"] for r in rows) / len(rows)),
            "grade_dist": {g: grades.count(g) for g in set(grades)},
        }

    def close(self):
        """Close the calling thread's connection. Other threads' connections
        are released by the OS when those threads exit."""
        c = getattr(self._tlocal, "conn", None)
        if c is None:
            return
        try:
            c.close()
        except Exception as exc:
            _log.debug("MatchDB close: %s", exc)
        self._tlocal.conn = None
