"""
core/match_db.py - SQLite match history database for Amberstone.

Stores per-match results across all modes (SR, ARAM, Arena, Brawl, TFT).
TFT matches include comp/trait/unit data for ranked LP analysis.

Usage:
    from core.match_db import MatchDB
    db = MatchDB(app_dir / "data" / "match_history.db")
    db.save_match({...})
    recent = db.get_recent("TFT", limit=20)
    best = db.get_best_comps(min_games=2, limit=10)

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

# Lane 8 cycle 16. Columns declared INTEGER / REAL in _SCHEMA below. Every
# value bound to one of these MUST be coerced to a number before the INSERT.
#
# Why this is not cosmetic: SQLite type affinity converts a numeric-looking
# TEXT value but leaves a non-numeric one stored AS TEXT. The previous
# `{c: data.get(c, "") for c in cols}` defaulted every absent column to the
# empty string, so a TFT save (which carries no kills/cs/gold) wrote `''`
# into thirteen numeric columns. Two measured consequences:
#   1. get_mode_stats("TFT") raised TypeError unconditionally - `sum()` over
#      `int + str`. ZERO of the 8041 live TFT rows had a numeric `kills`.
#   2. SQLite orders TEXT above INTEGER, so `'' > 0` is TRUE and the
#      `tft_placement > 0` guard admitted exactly the rows it exists to
#      exclude.
# tests/test_match_db_column_types.py pins both, and
# tests/test_match_db_backfill.py covers the repair of rows already written.
_INT_COLS = frozenset({
    "kills", "deaths", "assists", "cs", "gold",
    "tft_placement", "tft_stage", "tft_level",
    "arena_rounds_won", "arena_placement", "game_id",
})
_REAL_COLS = frozenset({
    "game_time_s", "cs_per_min", "gold_per_min", "kp_pct",
})
NUMERIC_COLS = _INT_COLS | _REAL_COLS


def _as_int(value) -> int:
    """Best-effort integer. Anything unparseable becomes the schema DEFAULT 0."""
    try:
        return int(value)
    except (TypeError, ValueError):
        pass
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _as_float(value) -> float:
    """Best-effort float. Anything unparseable becomes the schema DEFAULT 0."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def coerce_numeric(column: str, value):
    """Bind-time coercion for one column. Non-numeric columns pass through."""
    if column in _INT_COLS:
        return _as_int(value)
    if column in _REAL_COLS:
        return _as_float(value)
    return value

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
    raw_data    TEXT DEFAULT '',        -- full JSON dump for future reference
    -- Item 211: Match-V5 / LCU gameId so /api/last-match/ingest can
    -- row-match by id instead of "latest non-TFT row" (which raced the
    -- local performance_tracker writer and attached items to the wrong
    -- card on Home Recent-5). 0 = unknown (legacy or pre-stamp).
    game_id     INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_matches_mode ON matches(mode);
CREATE INDEX IF NOT EXISTS idx_matches_timestamp ON matches(timestamp);
CREATE INDEX IF NOT EXISTS idx_matches_tft_comp ON matches(tft_comp);
CREATE INDEX IF NOT EXISTS idx_matches_tft_placement ON matches(tft_placement);
CREATE INDEX IF NOT EXISTS idx_matches_grade ON matches(grade);
CREATE INDEX IF NOT EXISTS idx_matches_game_id ON matches(game_id);
"""


class MatchDB:
    def __init__(self, db_path: Path | str) -> None:
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
            #
            # RM-233: this pragma is a QUERY, not a command. SQLite answers
            # with the journal mode it actually settled on, and it can
            # legitimately answer something else (a filesystem with no
            # shared-memory support, another connection holding the old
            # mode, a locked db). Discarding that row made the module's own
            # concurrency claim - and the "opened (WAL)" log line - unfalsifiable
            # from outside. Record it and warn on a fallback instead.
            jm_row = setup.execute("PRAGMA journal_mode = WAL").fetchone()
            self.journal_mode = (
                str(jm_row[0]).lower() if jm_row else "unknown")
            if self.journal_mode != "wal":
                _log.warning(
                    "MatchDB journal_mode fell back to %r (wanted wal): %s - "
                    "concurrent readers WILL block writers on this database",
                    self.journal_mode, self._path)
            setup.execute("PRAGMA synchronous = NORMAL")
            setup.execute("PRAGMA busy_timeout = 5000")
            # Item 211: handle fresh vs legacy DB separately. executescript()
            # is safe on a fresh fleet, but a pre-fix DB may carry a
            # narrower legacy matches table (no tft_comp/grade columns) and
            # the CREATE INDEX statements in _SCHEMA explode against
            # missing columns. Branch on table existence to keep both paths
            # idempotent without losing data on legacy machines.
            tbl_exists = setup.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='matches'"
            ).fetchone() is not None
            if not tbl_exists:
                setup.executescript(_SCHEMA)
            existing_cols = {r[1] for r in setup.execute(
                "PRAGMA table_info(matches)")}
            if "game_id" not in existing_cols:
                setup.execute(
                    "ALTER TABLE matches ADD COLUMN game_id INTEGER DEFAULT 0")
            # Index creation is conditional on the underlying column existing
            # (so legacy short tables don't error out here either).
            setup.execute(
                "CREATE INDEX IF NOT EXISTS idx_matches_game_id "
                "ON matches(game_id)")
            setup.commit()
        finally:
            setup.close()
        _log.info("MatchDB opened (journal_mode=%s): %s",
                  self.journal_mode, self._path)

    def _conn(self) -> sqlite3.Connection:
        c = getattr(self._tlocal, "conn", None)
        if c is None:
            c = sqlite3.connect(str(self._path))
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA busy_timeout = 5000")
            self._tlocal.conn = c
        return c

    def save_match(self, data: dict) -> bool:
        """Save a match record. Accepts rating data dict from performance_tracker.

        Returns True when the row was inserted and committed, False when the
        write was lost. RM-233: this was annotated `-> None` and the
        `except Exception` arm logged and fell off the end, so a lost match
        and a saved one were indistinguishable to every caller. The method
        still never raises - both production callers already wrap it in a
        try/except and would keep working either way - but the outcome is
        now readable. Widening the return is additive: no caller in the tree
        reads it (performance_tracker.py:415 and :477 discard it).
        """
        cols = [
            "timestamp", "mode", "champion", "grade", "game_time_s",
            "kills", "deaths", "assists", "cs", "cs_per_min",
            "gold", "gold_per_min", "kda_str", "kp_pct",
            "tft_placement", "tft_stage", "tft_level", "tft_comp",
            "tft_traits", "tft_units", "tft_augments", "tft_items",
            "arena_rounds_won", "arena_placement",
            "notes", "label", "raw_data",
            "game_id",
        ]
        # Numeric columns default to 0 (their declared schema DEFAULT), text
        # columns to ''. Defaulting a numeric column to '' is what wrote TEXT
        # into thirteen INTEGER/REAL columns - see NUMERIC_COLS above.
        #
        # CAREFUL: this default is REDUNDANT today and no test covers it. The
        # coercion loop below runs unconditionally over every numeric column,
        # so reverting this to a bare "" is an EQUIVALENT MUTANT - measured,
        # all 20 tests in tests/test_match_db_column_types.py stay green.
        # It is kept as defence in depth, which means: if you ever make that
        # loop conditional, this line silently becomes the ONLY protection
        # and the suite will NOT catch its removal. Change one, re-check the
        # other.
        vals = {
            c: data.get(c, 0 if c in NUMERIC_COLS else "")
            for c in cols
        }
        # Serialize lists to JSON
        for k in ("tft_traits", "tft_units", "tft_augments", "tft_items", "notes"):
            v = vals.get(k)
            if isinstance(v, (list, dict)):
                vals[k] = json.dumps(v)
        # A caller may still pass '' or None explicitly for a numeric column
        # (several do), so coerce at bind time rather than trusting the
        # default above. Item 211's game_id special case is subsumed here.
        for c in cols:
            if c in NUMERIC_COLS:
                vals[c] = coerce_numeric(c, vals[c])
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
            # Per-match Anthropic spend boundary: a saved match closes the
            # current cost segment so the Settings spend-gate panel can show
            # cost averaged over the last N full matches. Best-effort - never
            # let a telemetry hiccup break the match-save path.
            try:
                from core.cost_tracker import get_tracker as _gt
                _gt().note_match_boundary()
            except Exception as _exc:  # noqa: BLE001
                _log.debug("cost note_match_boundary: %s", _exc)
            return True
        except Exception as exc:  # noqa: BLE001
            _log.error("Match save failed: %s", exc)
            return False

    def get_recent(self, mode: str = "", limit: int = 20) -> list:
        """Get recent matches, optionally filtered by mode.

        RM-233: SQLite reads a NEGATIVE `LIMIT` as UNLIMITED, so the whole
        table came back for `get_recent(mode, -1)`. Clamped here rather than
        only at the caller - `tools/ds_matchdb_mcp_server.py:342` does clamp
        (`max(1, min(int(limit), 200))`), but this is a public method with a
        default argument and "LIMIT n returns at most n rows" belongs to it.
        `_as_int` keeps a numeric string working and never raises; 0 stays 0,
        which is what SQLite already did.
        """
        limit = max(0, _as_int(limit))
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

    def close(self) -> None:
        """Close the calling thread's connection only.

        Another thread's connection is NOT closed here and cannot be - the
        handle lives in that thread's `threading.local` storage. It is
        released when that thread exits and CPython finalizes the orphaned
        Connection, not by the OS (the previous wording said "by the OS",
        which is wrong about the mechanism even though the outcome holds on
        CPython). A non-refcounting runtime would defer the close until GC.
        """
        c = getattr(self._tlocal, "conn", None)
        if c is None:
            return
        try:
            c.close()
        except Exception as exc:  # noqa: BLE001
            _log.debug("MatchDB close: %s", exc)
        self._tlocal.conn = None
