"""
tests/test_match_db_backfill.py - lane 8 cycle 16.

Covers scripts/repair_match_db_column_types.py, the recovery half of the
match_db column-type fix. CLAUDE.md "Data Fixes": preventing new bad rows is
only half a fix - the 8395 rows already written stay wrong until the repair
runs, so the repair gets the same test bar as the writer.
"""

import sqlite3
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.match_db import NUMERIC_COLS, MatchDB  # noqa: E402
from scripts.repair_match_db_column_types import repair, scan  # noqa: E402

_GOOD = ("integer", "real")


def _write_prefix_row(db_path, **overrides):
    """Insert a row the way the PRE-FIX writer did: '' for every absent col.

    Deliberately bypasses MatchDB.save_match - that is the code under repair,
    and it no longer produces the corruption we need to test against.
    """
    cols = [
        "timestamp", "mode", "champion", "grade", "game_time_s",
        "kills", "deaths", "assists", "cs", "cs_per_min",
        "gold", "gold_per_min", "kda_str", "kp_pct",
        "tft_placement", "tft_stage", "tft_level", "tft_comp",
        "tft_traits", "tft_units", "tft_augments", "tft_items",
        "arena_rounds_won", "arena_placement",
        "notes", "label", "raw_data", "game_id",
    ]
    vals = {c: "" for c in cols}
    vals["timestamp"] = "2026-08-30 12:00:00"
    vals["mode"] = "TFT"
    vals.update(overrides)
    conn = sqlite3.connect(str(db_path))
    try:
        with conn:
            conn.execute(
                f"INSERT INTO matches ({', '.join(cols)}) "
                f"VALUES ({', '.join(f':{c}' for c in cols)})",
                vals)
    finally:
        conn.close()


class BackfillBase(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "match_history.db"
        db = MatchDB(self.path)      # creates the schema
        db.close()

    def typeofs(self, column):
        conn = sqlite3.connect(str(self.path))
        try:
            return [r[0] for r in conn.execute(
                f"SELECT typeof({column}) FROM matches")]
        finally:
            conn.close()

    def fetch(self, column):
        conn = sqlite3.connect(str(self.path))
        try:
            return [r[0] for r in conn.execute(
                f"SELECT {column} FROM matches ORDER BY id")]
        finally:
            conn.close()


class TestRepairFixesLegacyRows(BackfillBase):
    def test_dry_run_reports_but_does_not_write(self):
        _write_prefix_row(self.path)
        before = self.typeofs("kills")
        s = repair(self.path, apply=False)
        self.assertEqual(s["rows_to_fix"], 1)
        self.assertFalse(s["applied"])
        self.assertEqual(self.typeofs("kills"), before,
                         "dry run mutated the database")

    def test_apply_converts_every_numeric_column(self):
        _write_prefix_row(self.path)
        s = repair(self.path, apply=True)
        self.assertTrue(s["applied"])
        self.assertEqual(s["rows_remaining_bad"], 0)
        for col in sorted(NUMERIC_COLS):
            with self.subTest(column=col):
                self.assertTrue(
                    all(t in _GOOD for t in self.typeofs(col)),
                    f"{col} still TEXT after repair")

    def test_repair_preserves_real_values(self):
        _write_prefix_row(self.path, kills=9, tft_placement=2,
                          cs_per_min=6.5, champion="Vayne")
        repair(self.path, apply=True)
        self.assertEqual(self.fetch("kills"), [9])
        self.assertEqual(self.fetch("tft_placement"), [2])
        self.assertAlmostEqual(self.fetch("cs_per_min")[0], 6.5)
        self.assertEqual(self.fetch("champion"), ["Vayne"])

    def test_repair_parses_numeric_strings_rather_than_zeroing_them(self):
        """A legacy row may hold '7' as TEXT - that is data, not corruption."""
        _write_prefix_row(self.path, kills="7", cs_per_min="6.5")
        repair(self.path, apply=True)
        self.assertEqual(self.fetch("kills"), [7])
        self.assertAlmostEqual(self.fetch("cs_per_min")[0], 6.5)

    def test_repair_leaves_text_columns_alone(self):
        _write_prefix_row(self.path, champion="Ziggs", tft_comp="Rebels",
                          label="B tier", raw_data='{"a": 1}')
        repair(self.path, apply=True)
        self.assertEqual(self.fetch("champion"), ["Ziggs"])
        self.assertEqual(self.fetch("tft_comp"), ["Rebels"])
        self.assertEqual(self.fetch("label"), ["B tier"])
        self.assertEqual(self.fetch("raw_data"), ['{"a": 1}'])

    def test_repair_is_idempotent(self):
        _write_prefix_row(self.path)
        first = repair(self.path, apply=True)
        second = repair(self.path, apply=True)
        self.assertEqual(first["rows_to_fix"], 1)
        self.assertEqual(second["rows_to_fix"], 0,
                         "second run found work - repair is not idempotent")

    def test_clean_db_needs_no_repair(self):
        db = MatchDB(self.path)
        db.save_match({"mode": "TFT", "tft_placement": 4, "tft_comp": "X"})
        db.close()
        self.assertEqual(repair(self.path, apply=False)["rows_to_fix"], 0,
                         "the FIXED writer produced a row needing repair")


class TestRepairRestoresReaderBehaviour(BackfillBase):
    """The point of the repair: the broken readers must start working."""

    def test_get_mode_stats_tft_works_after_repair(self):
        for p in (1, 4, 8):
            _write_prefix_row(self.path, tft_placement=p, tft_comp="Rebels")
        db = MatchDB(self.path)
        self.addCleanup(db.close)
        with self.assertRaises(TypeError):
            db.get_mode_stats("TFT")          # the live failure, reproduced
        db.close()
        repair(self.path, apply=True)
        db2 = MatchDB(self.path)
        self.addCleanup(db2.close)
        self.assertEqual(db2.get_mode_stats("TFT")["games"], 3)

    def test_placement_guard_excludes_unplaced_rows_after_repair(self):
        _write_prefix_row(self.path, tft_comp="Ghost")
        conn = sqlite3.connect(str(self.path))
        admitted_before = conn.execute(
            "SELECT COUNT(*) FROM matches WHERE tft_placement > 0"
        ).fetchone()[0]
        conn.close()
        self.assertEqual(admitted_before, 1, "expected the pre-fix TEXT hole")
        repair(self.path, apply=True)
        conn = sqlite3.connect(str(self.path))
        try:
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM matches WHERE tft_placement > 0"
                ).fetchone()[0], 0)
        finally:
            conn.close()


class TestRepairHandlesLegacySchemas(BackfillBase):
    def test_scan_only_touches_columns_that_exist(self):
        conn = sqlite3.connect(str(self.path))
        try:
            conn.execute("DROP TABLE matches")
            conn.execute(
                "CREATE TABLE matches (id INTEGER PRIMARY KEY, "
                "timestamp TEXT, mode TEXT, kills INTEGER DEFAULT 0)")
            with conn:
                conn.execute(
                    "INSERT INTO matches (timestamp, mode, kills) "
                    "VALUES ('t', 'SR', '')")
            cols, rows, _ = scan(conn)
        finally:
            conn.close()
        self.assertEqual(cols, ["kills"])
        self.assertEqual(len(rows), 1)
        s = repair(self.path, apply=True)
        self.assertEqual(s["rows_remaining_bad"], 0)


if __name__ == "__main__":
    unittest.main()
