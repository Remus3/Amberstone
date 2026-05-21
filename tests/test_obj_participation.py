"""Tests for core/obj_participation.py.

Closes the item-132 carry-forward (c). Validates:
  - Function signature + module-level constants
  - Hand-derived expected values from a fixture sqlite DB
  - Clamp range [0.0, 1.0]
  - Fail-soft on blank inputs / unknown match / unknown puuid /
    zero-denominator / malformed schema / sqlite errors
  - No exceptions raised on any of the above
"""
from __future__ import annotations

import os
import pathlib
import sqlite3
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.obj_participation import (  # noqa: E402
    _OBJ_COLUMNS,
    _ROW_SUM_SQL,
    _coerce_float,
    compute_obj_participation,
)


def _seed_db(path: pathlib.Path, rows: list[dict]) -> None:
    """Build a minimal participants-shaped DB with the 6 objective columns.

    Each row dict supplies match_id, team_id, puuid + any subset of the
    six objective columns; missing keys default to 0.
    """
    conn = sqlite3.connect(str(path))
    cur = conn.cursor()
    cur.executescript(
        """
        CREATE TABLE participants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id TEXT,
            team_id INTEGER,
            puuid TEXT,
            dragon_kills INTEGER,
            baron_kills INTEGER,
            objectives_stolen INTEGER,
            objectives_stolen_assists INTEGER,
            first_tower_kill INTEGER,
            first_tower_assist INTEGER
        );
        """
    )
    for r in rows:
        cur.execute(
            """INSERT INTO participants
               (match_id, team_id, puuid,
                dragon_kills, baron_kills, objectives_stolen,
                objectives_stolen_assists, first_tower_kill, first_tower_assist)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                r["match_id"],
                r["team_id"],
                r["puuid"],
                r.get("dragon_kills", 0),
                r.get("baron_kills", 0),
                r.get("objectives_stolen", 0),
                r.get("objectives_stolen_assists", 0),
                r.get("first_tower_kill", 0),
                r.get("first_tower_assist", 0),
            ),
        )
    conn.commit()
    conn.close()


def _build_full_team_match(
    path: pathlib.Path,
    match_id: str = "NA1_TEST",
    operator_puuid: str = "PUUID_SELF",
) -> None:
    """Seed a 10-participant match (5v5).

    Operator on team 100 owns:
      dragon_kills=2, baron_kills=1, objectives_stolen=1,
      objectives_stolen_assists=0, first_tower_kill=1,
      first_tower_assist=0  -> sum 5

    Allies (4 rows on team 100) own a combined:
      dragon_kills=3, baron_kills=0, objectives_stolen=0,
      objectives_stolen_assists=1, first_tower_kill=0,
      first_tower_assist=1  -> sum 5

    Team-total = 10, ratio = 5/10 = 0.5.
    """
    rows = [
        # Operator
        {
            "match_id": match_id, "team_id": 100, "puuid": operator_puuid,
            "dragon_kills": 2, "baron_kills": 1,
            "objectives_stolen": 1, "objectives_stolen_assists": 0,
            "first_tower_kill": 1, "first_tower_assist": 0,
        },
        # 4 allies; total sum across them is 5
        {
            "match_id": match_id, "team_id": 100, "puuid": "ALLY_A",
            "dragon_kills": 2, "baron_kills": 0,
            "objectives_stolen": 0, "objectives_stolen_assists": 0,
            "first_tower_kill": 0, "first_tower_assist": 1,
        },
        {
            "match_id": match_id, "team_id": 100, "puuid": "ALLY_B",
            "dragon_kills": 1, "baron_kills": 0,
            "objectives_stolen": 0, "objectives_stolen_assists": 1,
            "first_tower_kill": 0, "first_tower_assist": 0,
        },
        {
            "match_id": match_id, "team_id": 100, "puuid": "ALLY_C",
            "dragon_kills": 0, "baron_kills": 0,
            "objectives_stolen": 0, "objectives_stolen_assists": 0,
            "first_tower_kill": 0, "first_tower_assist": 0,
        },
        {
            "match_id": match_id, "team_id": 100, "puuid": "ALLY_D",
            "dragon_kills": 0, "baron_kills": 0,
            "objectives_stolen": 0, "objectives_stolen_assists": 0,
            "first_tower_kill": 0, "first_tower_assist": 0,
        },
        # 5 enemies on team 200 (should NOT affect operator's denominator)
        {
            "match_id": match_id, "team_id": 200, "puuid": "ENEMY_A",
            "dragon_kills": 4, "baron_kills": 2,
            "objectives_stolen": 2, "objectives_stolen_assists": 1,
            "first_tower_kill": 1, "first_tower_assist": 1,
        },
        {
            "match_id": match_id, "team_id": 200, "puuid": "ENEMY_B",
            "dragon_kills": 0, "baron_kills": 0,
            "objectives_stolen": 0, "objectives_stolen_assists": 0,
            "first_tower_kill": 0, "first_tower_assist": 0,
        },
        {
            "match_id": match_id, "team_id": 200, "puuid": "ENEMY_C",
            "dragon_kills": 0, "baron_kills": 0,
            "objectives_stolen": 0, "objectives_stolen_assists": 0,
            "first_tower_kill": 0, "first_tower_assist": 0,
        },
        {
            "match_id": match_id, "team_id": 200, "puuid": "ENEMY_D",
            "dragon_kills": 0, "baron_kills": 0,
            "objectives_stolen": 0, "objectives_stolen_assists": 0,
            "first_tower_kill": 0, "first_tower_assist": 0,
        },
        {
            "match_id": match_id, "team_id": 200, "puuid": "ENEMY_E",
            "dragon_kills": 0, "baron_kills": 0,
            "objectives_stolen": 0, "objectives_stolen_assists": 0,
            "first_tower_kill": 0, "first_tower_assist": 0,
        },
    ]
    _seed_db(path, rows)


class ModuleSchemaTests(unittest.TestCase):
    """Pin the public surface of the module."""

    def test_obj_columns_tuple_holds_six_entries(self):
        self.assertEqual(len(_OBJ_COLUMNS), 6)

    def test_obj_columns_includes_dragons_and_barons(self):
        self.assertIn("dragon_kills", _OBJ_COLUMNS)
        self.assertIn("baron_kills", _OBJ_COLUMNS)

    def test_obj_columns_includes_objectives_stolen_pair(self):
        self.assertIn("objectives_stolen", _OBJ_COLUMNS)
        self.assertIn("objectives_stolen_assists", _OBJ_COLUMNS)

    def test_obj_columns_includes_first_tower_pair(self):
        self.assertIn("first_tower_kill", _OBJ_COLUMNS)
        self.assertIn("first_tower_assist", _OBJ_COLUMNS)

    def test_row_sum_sql_coalesces_nulls(self):
        for col in _OBJ_COLUMNS:
            self.assertIn(f"COALESCE({col}, 0)", _ROW_SUM_SQL)

    def test_compute_obj_participation_is_callable(self):
        self.assertTrue(callable(compute_obj_participation))


class CoerceFloatTests(unittest.TestCase):
    """The internal float coercion is fail-soft."""

    def test_none_returns_zero(self):
        self.assertEqual(_coerce_float(None), 0.0)

    def test_int_returns_float(self):
        self.assertEqual(_coerce_float(5), 5.0)

    def test_float_passes_through(self):
        self.assertEqual(_coerce_float(3.14), 3.14)

    def test_invalid_string_returns_zero(self):
        self.assertEqual(_coerce_float("not a number"), 0.0)


class MathTests(unittest.TestCase):
    """Hand-derived expected values on a controlled fixture."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="obj_part_")
        self.db_path = pathlib.Path(self.tmpdir) / "rewind.db"

    def tearDown(self):
        try:
            os.remove(self.db_path)
        except OSError:
            pass
        try:
            os.rmdir(self.tmpdir)
        except OSError:
            pass

    def test_half_share_returns_zero_point_five(self):
        _build_full_team_match(self.db_path)
        conn = sqlite3.connect(str(self.db_path))
        try:
            ratio = compute_obj_participation(conn, "NA1_TEST", "PUUID_SELF")
        finally:
            conn.close()
        self.assertAlmostEqual(ratio, 0.5)

    def test_operator_owns_all_team_objectives(self):
        # Operator = 6, allies all zero -> 6/6 = 1.0
        rows = [
            {
                "match_id": "M1", "team_id": 100, "puuid": "SELF",
                "dragon_kills": 3, "baron_kills": 1,
                "objectives_stolen": 1, "objectives_stolen_assists": 0,
                "first_tower_kill": 1, "first_tower_assist": 0,
            },
            {"match_id": "M1", "team_id": 100, "puuid": "A1"},
            {"match_id": "M1", "team_id": 100, "puuid": "A2"},
            {"match_id": "M1", "team_id": 100, "puuid": "A3"},
            {"match_id": "M1", "team_id": 100, "puuid": "A4"},
        ]
        _seed_db(self.db_path, rows)
        conn = sqlite3.connect(str(self.db_path))
        try:
            ratio = compute_obj_participation(conn, "M1", "SELF")
        finally:
            conn.close()
        self.assertEqual(ratio, 1.0)

    def test_operator_contributes_nothing_returns_zero(self):
        # Operator row exists but all 0; teammates have all the objectives.
        rows = [
            {"match_id": "M2", "team_id": 100, "puuid": "SELF"},
            {
                "match_id": "M2", "team_id": 100, "puuid": "A1",
                "dragon_kills": 3, "baron_kills": 1,
                "first_tower_kill": 1,
            },
            {"match_id": "M2", "team_id": 100, "puuid": "A2"},
            {"match_id": "M2", "team_id": 100, "puuid": "A3"},
            {"match_id": "M2", "team_id": 100, "puuid": "A4"},
        ]
        _seed_db(self.db_path, rows)
        conn = sqlite3.connect(str(self.db_path))
        try:
            ratio = compute_obj_participation(conn, "M2", "SELF")
        finally:
            conn.close()
        self.assertEqual(ratio, 0.0)

    def test_enemy_team_objectives_do_not_pollute(self):
        # Operator team has just 1 objective; enemy team has 100. Ratio
        # should be 1/1 = 1.0, NOT 1/101.
        rows = [
            {
                "match_id": "M3", "team_id": 100, "puuid": "SELF",
                "dragon_kills": 1,
            },
            {"match_id": "M3", "team_id": 100, "puuid": "A1"},
            {"match_id": "M3", "team_id": 100, "puuid": "A2"},
            {"match_id": "M3", "team_id": 100, "puuid": "A3"},
            {"match_id": "M3", "team_id": 100, "puuid": "A4"},
            {
                "match_id": "M3", "team_id": 200, "puuid": "E1",
                "dragon_kills": 50, "baron_kills": 25,
                "objectives_stolen": 10, "objectives_stolen_assists": 10,
                "first_tower_kill": 1, "first_tower_assist": 4,
            },
        ]
        _seed_db(self.db_path, rows)
        conn = sqlite3.connect(str(self.db_path))
        try:
            ratio = compute_obj_participation(conn, "M3", "SELF")
        finally:
            conn.close()
        self.assertEqual(ratio, 1.0)

    def test_assists_and_stolens_count_in_numerator(self):
        # Operator has only assists/stolens; team also only has those.
        rows = [
            {
                "match_id": "M4", "team_id": 100, "puuid": "SELF",
                "objectives_stolen_assists": 2, "first_tower_assist": 1,
            },
            {
                "match_id": "M4", "team_id": 100, "puuid": "A1",
                "objectives_stolen": 1,
            },
            {"match_id": "M4", "team_id": 100, "puuid": "A2"},
        ]
        _seed_db(self.db_path, rows)
        conn = sqlite3.connect(str(self.db_path))
        try:
            ratio = compute_obj_participation(conn, "M4", "SELF")
        finally:
            conn.close()
        # operator = 3, team total = 4 -> 0.75
        self.assertAlmostEqual(ratio, 0.75)

    def test_first_tower_kill_counts(self):
        rows = [
            {
                "match_id": "M5", "team_id": 100, "puuid": "SELF",
                "first_tower_kill": 1,
            },
            {"match_id": "M5", "team_id": 100, "puuid": "A1"},
        ]
        _seed_db(self.db_path, rows)
        conn = sqlite3.connect(str(self.db_path))
        try:
            ratio = compute_obj_participation(conn, "M5", "SELF")
        finally:
            conn.close()
        self.assertEqual(ratio, 1.0)


class ClampTests(unittest.TestCase):
    """Output range is rigorously [0.0, 1.0]."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="obj_clamp_")
        self.db_path = pathlib.Path(self.tmpdir) / "rewind.db"

    def tearDown(self):
        try:
            os.remove(self.db_path)
        except OSError:
            pass
        try:
            os.rmdir(self.tmpdir)
        except OSError:
            pass

    def test_zero_input_returns_zero(self):
        rows = [
            {"match_id": "M0", "team_id": 100, "puuid": "SELF"},
            {"match_id": "M0", "team_id": 100, "puuid": "A1"},
        ]
        _seed_db(self.db_path, rows)
        conn = sqlite3.connect(str(self.db_path))
        try:
            ratio = compute_obj_participation(conn, "M0", "SELF")
        finally:
            conn.close()
        self.assertEqual(ratio, 0.0)

    def test_full_share_caps_at_one(self):
        rows = [
            {
                "match_id": "M_ONE", "team_id": 100, "puuid": "SELF",
                "dragon_kills": 5,
            },
            {"match_id": "M_ONE", "team_id": 100, "puuid": "A1"},
        ]
        _seed_db(self.db_path, rows)
        conn = sqlite3.connect(str(self.db_path))
        try:
            ratio = compute_obj_participation(conn, "M_ONE", "SELF")
        finally:
            conn.close()
        self.assertGreaterEqual(ratio, 0.0)
        self.assertLessEqual(ratio, 1.0)

    def test_result_always_in_range(self):
        # Cumulative sanity sweep.
        _build_full_team_match(self.db_path)
        conn = sqlite3.connect(str(self.db_path))
        try:
            ratio = compute_obj_participation(conn, "NA1_TEST", "PUUID_SELF")
        finally:
            conn.close()
        self.assertGreaterEqual(ratio, 0.0)
        self.assertLessEqual(ratio, 1.0)


class FailSoftTests(unittest.TestCase):
    """No exception path - returns 0.0 on every degenerate input."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="obj_fs_")
        self.db_path = pathlib.Path(self.tmpdir) / "rewind.db"

    def tearDown(self):
        try:
            os.remove(self.db_path)
        except OSError:
            pass
        try:
            os.rmdir(self.tmpdir)
        except OSError:
            pass

    def test_blank_match_id_returns_zero(self):
        _build_full_team_match(self.db_path)
        conn = sqlite3.connect(str(self.db_path))
        try:
            self.assertEqual(compute_obj_participation(conn, "", "PUUID_SELF"), 0.0)
        finally:
            conn.close()

    def test_blank_puuid_returns_zero(self):
        _build_full_team_match(self.db_path)
        conn = sqlite3.connect(str(self.db_path))
        try:
            self.assertEqual(compute_obj_participation(conn, "NA1_TEST", ""), 0.0)
        finally:
            conn.close()

    def test_unknown_match_id_returns_zero(self):
        _build_full_team_match(self.db_path)
        conn = sqlite3.connect(str(self.db_path))
        try:
            self.assertEqual(
                compute_obj_participation(conn, "UNKNOWN", "PUUID_SELF"), 0.0,
            )
        finally:
            conn.close()

    def test_unknown_puuid_returns_zero(self):
        _build_full_team_match(self.db_path)
        conn = sqlite3.connect(str(self.db_path))
        try:
            self.assertEqual(
                compute_obj_participation(conn, "NA1_TEST", "NOT_REAL"), 0.0,
            )
        finally:
            conn.close()

    def test_zero_team_total_returns_zero(self):
        # All 5 teammates have zero objectives across the match. Returns
        # 0.0 not divide-by-zero.
        rows = [
            {"match_id": "MZ", "team_id": 100, "puuid": "SELF"},
            {"match_id": "MZ", "team_id": 100, "puuid": "A1"},
            {"match_id": "MZ", "team_id": 100, "puuid": "A2"},
            {"match_id": "MZ", "team_id": 100, "puuid": "A3"},
            {"match_id": "MZ", "team_id": 100, "puuid": "A4"},
        ]
        _seed_db(self.db_path, rows)
        conn = sqlite3.connect(str(self.db_path))
        try:
            self.assertEqual(
                compute_obj_participation(conn, "MZ", "SELF"), 0.0,
            )
        finally:
            conn.close()

    def test_missing_table_returns_zero(self):
        # Empty DB - the participants table doesn't exist.
        sqlite3.connect(str(self.db_path)).close()
        conn = sqlite3.connect(str(self.db_path))
        try:
            self.assertEqual(
                compute_obj_participation(conn, "any", "any"), 0.0,
            )
        finally:
            conn.close()

    def test_non_string_match_id_returns_zero(self):
        _build_full_team_match(self.db_path)
        conn = sqlite3.connect(str(self.db_path))
        try:
            # type-coerced inputs (a future caller passing an int by
            # mistake) must NOT raise.
            self.assertEqual(
                compute_obj_participation(conn, 12345, "PUUID_SELF"), 0.0,
            )
            self.assertEqual(
                compute_obj_participation(conn, "NA1_TEST", 99), 0.0,
            )
            self.assertEqual(
                compute_obj_participation(conn, None, "PUUID_SELF"), 0.0,
            )
            self.assertEqual(
                compute_obj_participation(conn, "NA1_TEST", None), 0.0,
            )
        finally:
            conn.close()

    def test_null_team_id_returns_zero(self):
        # Operator row exists but team_id is NULL (malformed row).
        conn = sqlite3.connect(str(self.db_path))
        cur = conn.cursor()
        cur.executescript(
            """
            CREATE TABLE participants (
                id INTEGER PRIMARY KEY,
                match_id TEXT,
                team_id INTEGER,
                puuid TEXT,
                dragon_kills INTEGER,
                baron_kills INTEGER,
                objectives_stolen INTEGER,
                objectives_stolen_assists INTEGER,
                first_tower_kill INTEGER,
                first_tower_assist INTEGER
            );
            INSERT INTO participants
              (match_id, team_id, puuid, dragon_kills)
              VALUES ('MN', NULL, 'SELF', 1);
            """
        )
        conn.commit()
        try:
            self.assertEqual(
                compute_obj_participation(conn, "MN", "SELF"), 0.0,
            )
        finally:
            conn.close()


class ReadOnlyConnectionTests(unittest.TestCase):
    """The route opens conn via URI mode=ro; ensure helper works there."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="obj_ro_")
        self.db_path = pathlib.Path(self.tmpdir) / "rewind.db"
        _build_full_team_match(self.db_path)

    def tearDown(self):
        try:
            os.remove(self.db_path)
        except OSError:
            pass
        try:
            os.rmdir(self.tmpdir)
        except OSError:
            pass

    def test_works_against_readonly_uri_connection(self):
        conn = sqlite3.connect(
            f"file:{self.db_path}?mode=ro", uri=True, timeout=2.0,
        )
        try:
            ratio = compute_obj_participation(conn, "NA1_TEST", "PUUID_SELF")
        finally:
            conn.close()
        self.assertAlmostEqual(ratio, 0.5)


class AsciiHygieneTests(unittest.TestCase):
    """Module is pure ASCII (no em/en-dash, no smart quotes)."""

    def test_module_is_ascii(self):
        path = ROOT / "core" / "obj_participation.py"
        body = path.read_bytes()
        for i, b in enumerate(body):
            self.assertLess(b, 128, f"non-ASCII byte 0x{b:02x} at offset {i}")


if __name__ == "__main__":
    unittest.main()
