"""Per-mode SQLite schema creation for Phase 3.

Creates (idempotent) five physical SQLite files under ``data/db/``:
  sr_draft.db, sr_ranked.db, aram.db, arena.db, brawl.db

Schema identical across all five (see §9 of the spec). Physical separation
makes mode bleed impossible by design.

Idempotency: ``CREATE TABLE IF NOT EXISTS`` + ``CREATE INDEX IF NOT EXISTS``.
Safe to call at every supervisor startup.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger("agent2.db_schema")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_DIR = _PROJECT_ROOT / "data" / "db"

MODE_DB_FILES = {
    "sr_draft": "sr_draft.db",
    "sr_ranked": "sr_ranked.db",
    "aram": "aram.db",
    "arena": "arena.db",
    "brawl": "brawl.db",
}

SCHEMA_STATEMENTS = [
    # --- matches -------------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS matches (
      match_id INTEGER PRIMARY KEY AUTOINCREMENT,
      started_at TEXT NOT NULL,
      ended_at TEXT,
      champion TEXT NOT NULL,
      ally_champions TEXT NOT NULL,
      enemy_champions TEXT NOT NULL,
      duration_sec INTEGER,
      win INTEGER,
      final_rating_json TEXT,
      source TEXT NOT NULL,
      kills INTEGER,
      deaths INTEGER,
      assists INTEGER
    )
    """,
    # --- match_events --------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS match_events (
      event_id INTEGER PRIMARY KEY AUTOINCREMENT,
      match_id INTEGER NOT NULL REFERENCES matches(match_id),
      ts_game_sec REAL NOT NULL,
      event_type TEXT NOT NULL,
      state_json TEXT NOT NULL,
      coach_output_json TEXT,
      outcome_30s_json TEXT
    )
    """,
    # --- adaptation_buckets -------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS adaptation_buckets (
      champion TEXT NOT NULL,
      games_played INTEGER DEFAULT 0,
      wins INTEGER DEFAULT 0,
      losses INTEGER DEFAULT 0,
      avg_rating REAL,
      last_updated TEXT,
      aggregates_json TEXT,
      PRIMARY KEY (champion)
    )
    """,
    # --- matchup_modifiers --------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS matchup_modifiers (
      champion TEXT NOT NULL,
      opponent_signature TEXT NOT NULL,
      sample_count INTEGER DEFAULT 0,
      activated INTEGER DEFAULT 0,
      modifier_json TEXT,
      last_updated TEXT,
      PRIMARY KEY (champion, opponent_signature)
    )
    """,
    # --- _migration_state (operational, not part of S9 schema) --------
    # Tracks which rewind_history.db rows we've ingested so migration
    # can be re-run without duplicating data. source_ref = rewind's
    # original match id / rowid.
    """
    CREATE TABLE IF NOT EXISTS _migration_state (
      source TEXT NOT NULL,
      source_ref TEXT NOT NULL,
      local_match_id INTEGER NOT NULL,
      migrated_at TEXT NOT NULL,
      PRIMARY KEY (source, source_ref)
    )
    """,
    # --- helpful indexes ----------------------------------------------
    "CREATE INDEX IF NOT EXISTS idx_matches_champion ON matches(champion)",
    "CREATE INDEX IF NOT EXISTS idx_matches_started_at ON matches(started_at)",
    "CREATE INDEX IF NOT EXISTS idx_matches_source ON matches(source)",
    "CREATE INDEX IF NOT EXISTS idx_events_match_id ON match_events(match_id)",
    "CREATE INDEX IF NOT EXISTS idx_events_type ON match_events(event_type)",
]


def db_path(mode: str) -> Path:
    fname = MODE_DB_FILES.get(mode)
    if fname is None:
        raise ValueError(f"unknown mode: {mode}; valid: {list(MODE_DB_FILES)}")
    return DB_DIR / fname


def open_db(mode: str) -> sqlite3.Connection:
    p = db_path(mode)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_mode(mode: str) -> Path:
    p = db_path(mode)
    p.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(p) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        for stmt in SCHEMA_STATEMENTS:
            conn.execute(stmt)
        conn.commit()
    logger.info("mode-db ready: %s (%s)", mode, p)
    return p


def init_all() -> dict[str, str]:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    out: dict[str, str] = {}
    for mode in MODE_DB_FILES:
        p = init_mode(mode)
        out[mode] = str(p)
    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    result = init_all()
    for mode, path in result.items():
        print(f"[db_schema] {mode}: {path}")
