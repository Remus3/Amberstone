"""
tests/test_match_db_column_types.py - lane 8 cycle 16.

Regression + characterization tests for core/match_db.py column typing.

THE DEFECT (measured 2026-08-30 against the live DB, 8395 rows):
`save_match` built its row with `{c: data.get(c, "") for c in cols}` - every
missing column defaulted to the empty STRING, including the columns declared
INTEGER / REAL. SQLite type affinity converts a numeric-looking TEXT value
but stores a non-numeric one AS TEXT, so `''` landed in `kills`, `deaths`,
`cs_per_min`, `tft_placement` and ten more. Two consequences, both measured:

  1. `get_mode_stats("TFT")` raised TypeError unconditionally - ZERO of the
     8041 live TFT rows carried a numeric `kills`, so `sum(r["kills"] ...)`
     hit `int + str` every time.
  2. SQLite orders TEXT above INTEGER, so `'' > 0` is TRUE and the
     `tft_placement > 0` guard - whose entire job is to exclude rows with no
     placement - ADMITTED them. Latent on live data only because the
     `mode = 'TFT'` predicate happened to shield it (all 354 live rows with a
     non-numeric placement are ARAM/ARENA/SR), but a TFT row saved without a
     placement reaches it directly.
"""

import json
import sqlite3
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.match_db import MatchDB  # noqa: E402

# Columns whose declared affinity in _SCHEMA is INTEGER or REAL.
NUMERIC_COLUMNS = (
    "game_time_s", "kills", "deaths", "assists", "cs", "cs_per_min",
    "gold", "gold_per_min", "kp_pct", "tft_placement", "tft_stage",
    "tft_level", "arena_rounds_won", "arena_placement", "game_id",
)

TEXT_COLUMNS = (
    "timestamp", "mode", "champion", "grade", "kda_str", "tft_comp",
    "tft_traits", "tft_units", "tft_augments", "tft_items", "notes",
    "label", "raw_data",
)


class MatchDBTypeBase(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = MatchDB(Path(self._tmp.name) / "match_history.db")
        self.addCleanup(self.db.close)

    def typeof(self, column, row_id=1):
        cur = self.db._conn().execute(
            f"SELECT typeof({column}) FROM matches WHERE id = ?", (row_id,))
        return cur.fetchone()[0]


class TestNumericColumnsNeverStoreText(MatchDBTypeBase):
    """A save that omits a numeric column must store a NUMBER, not ''."""

    def test_tft_shaped_save_stores_numbers_in_sr_columns(self):
        # Exactly the shape the TFT writer uses: no kills/deaths/cs/gold.
        self.db.save_match(
            {"mode": "TFT", "tft_placement": 3, "tft_comp": "Rebels"})
        for col in NUMERIC_COLUMNS:
            with self.subTest(column=col):
                self.assertIn(
                    self.typeof(col), ("integer", "real"),
                    f"{col} stored as TEXT - SQLite affinity leaves a "
                    "non-numeric string as text")

    def test_sr_shaped_save_stores_numbers_in_tft_columns(self):
        self.db.save_match({"mode": "SR", "kills": 7, "deaths": 2})
        for col in NUMERIC_COLUMNS:
            with self.subTest(column=col):
                self.assertIn(self.typeof(col), ("integer", "real"))

    def test_empty_string_input_is_coerced_not_stored(self):
        """A caller explicitly passing '' still must not poison the column."""
        self.db.save_match({"mode": "SR", "kills": "", "cs_per_min": ""})
        self.assertIn(self.typeof("kills"), ("integer", "real"))
        self.assertIn(self.typeof("cs_per_min"), ("integer", "real"))

    def test_none_input_is_coerced_not_stored(self):
        self.db.save_match({"mode": "SR", "kills": None, "kp_pct": None})
        self.assertIn(self.typeof("kills"), ("integer", "real"))
        self.assertIn(self.typeof("kp_pct"), ("integer", "real"))

    def test_garbage_input_falls_back_to_zero_not_text(self):
        self.db.save_match({"mode": "SR", "kills": "not-a-number"})
        self.assertIn(self.typeof("kills"), ("integer", "real"))


class TestAggregateReadersSurviveSparseRows(MatchDBTypeBase):
    """The live crash: get_mode_stats('TFT') raised for every TFT row."""

    def test_get_mode_stats_tft_does_not_raise(self):
        for placement in (1, 4, 8):
            self.db.save_match(
                {"mode": "TFT", "tft_placement": placement,
                 "tft_comp": "Rebels", "grade": "A"})
        stats = self.db.get_mode_stats("TFT")  # raised TypeError pre-fix
        self.assertEqual(stats["games"], 3)
        self.assertEqual(stats["avg_kills"], 0.0)

    def test_get_tft_streak_survives_row_saved_without_placement(self):
        self.db.save_match({"mode": "TFT", "tft_comp": "Rebels"})
        self.db.save_match(
            {"mode": "TFT", "tft_placement": 2, "tft_comp": "Rebels"})
        streak = self.db.get_tft_streak()  # raised TypeError pre-fix
        for p in streak.get("placements", []):
            self.assertIsInstance(p, int)


class TestPlacementGuardExcludesUnplacedRows(MatchDBTypeBase):
    """`tft_placement > 0` must mean what it says.

    SQLite sorts TEXT above INTEGER, so a stored `''` satisfies `> 0`.
    """

    def test_unplaced_tft_row_is_not_admitted_by_the_placement_filter(self):
        self.db.save_match({"mode": "TFT", "tft_comp": "Rebels"})
        admitted = self.db._conn().execute(
            "SELECT COUNT(*) FROM matches WHERE tft_placement > 0"
        ).fetchone()[0]
        self.assertEqual(
            admitted, 0,
            "a row saved with no placement passed `tft_placement > 0`")

    def test_unplaced_row_does_not_reach_best_comps_ranking(self):
        # Pre-fix this ranked as avg_place 0.0, sorting FIRST under
        # `ORDER BY avg_place ASC` - an unplayed comp as the top pick.
        self.db.save_match({"mode": "TFT", "tft_comp": "Ghost"})
        self.db.save_match({"mode": "TFT", "tft_comp": "Ghost"})
        self.db.save_match(
            {"mode": "TFT", "tft_comp": "Real", "tft_placement": 2})
        self.db.save_match(
            {"mode": "TFT", "tft_comp": "Real", "tft_placement": 2})
        comps = self.db.get_best_comps(min_games=2, limit=5)
        names = [c["tft_comp"] for c in comps]
        self.assertNotIn(
            "Ghost", names,
            "a comp with no recorded placements ranked as a best comp")


class TestExistingBehaviourPreserved(MatchDBTypeBase):
    """Characterization - what worked before must keep working."""

    def test_text_columns_still_default_to_empty_string(self):
        self.db.save_match({"mode": "SR"})
        for col in TEXT_COLUMNS:
            with self.subTest(column=col):
                self.assertEqual(self.typeof(col), "text")

    def test_game_id_coercion_still_applies(self):
        self.db.save_match({"mode": "SR", "game_id": "12345"})
        row = self.db.get_recent("SR", 1)[0]
        self.assertEqual(row["game_id"], 12345)

    def test_game_id_garbage_still_becomes_zero(self):
        self.db.save_match({"mode": "SR", "game_id": "abc"})
        self.assertEqual(self.db.get_recent("SR", 1)[0]["game_id"], 0)

    def test_timestamp_autofilled_when_absent(self):
        self.db.save_match({"mode": "SR"})
        self.assertTrue(self.db.get_recent("SR", 1)[0]["timestamp"])

    def test_raw_data_autofilled_with_the_source_dict(self):
        self.db.save_match({"mode": "SR", "champion": "Vayne"})
        raw = json.loads(self.db.get_recent("SR", 1)[0]["raw_data"])
        self.assertEqual(raw["champion"], "Vayne")

    def test_list_fields_still_json_serialized(self):
        self.db.save_match({"mode": "TFT", "tft_traits": ["a", "b"],
                            "notes": ["x"], "tft_placement": 1})
        row = self.db.get_recent("TFT", 1)[0]
        self.assertEqual(json.loads(row["tft_traits"]), ["a", "b"])
        self.assertEqual(json.loads(row["notes"]), ["x"])

    def test_numeric_values_supplied_are_preserved_exactly(self):
        self.db.save_match({"mode": "SR", "kills": 7, "deaths": 3,
                            "cs_per_min": 6.5, "kp_pct": 61.25})
        row = self.db.get_recent("SR", 1)[0]
        self.assertEqual(row["kills"], 7)
        self.assertEqual(row["deaths"], 3)
        self.assertAlmostEqual(row["cs_per_min"], 6.5)
        self.assertAlmostEqual(row["kp_pct"], 61.25)

    def test_numeric_string_input_is_parsed_to_a_number(self):
        self.db.save_match({"mode": "SR", "kills": "7", "cs_per_min": "6.5"})
        row = self.db.get_recent("SR", 1)[0]
        self.assertEqual(row["kills"], 7)
        self.assertAlmostEqual(row["cs_per_min"], 6.5)

    def test_get_recent_roundtrip_and_mode_filter(self):
        self.db.save_match({"mode": "SR", "champion": "Vayne"})
        self.db.save_match({"mode": "ARAM", "champion": "Ziggs"})
        self.assertEqual(len(self.db.get_recent("SR")), 1)
        self.assertEqual(len(self.db.get_recent()), 2)


class TestModuleDocstringUsageIsCallable(unittest.TestCase):
    """The module docstring advertises the public API - it must be true.

    It read `db.get_best_comps(min_placement=4, limit=10)` against a real
    signature of `(min_games=2, limit=10)` - a documented call that raises
    TypeError. 4a: where code and docstring disagree, pin the truth.
    """

    def test_advertised_get_best_comps_kwargs_exist(self):
        import inspect

        import core.match_db as mod

        params = set(
            inspect.signature(mod.MatchDB.get_best_comps).parameters)
        for line in (mod.__doc__ or "").splitlines():
            if "get_best_comps(" in line:
                kwargs = [
                    part.split("=")[0].strip()
                    for part in line.split("(", 1)[1].rsplit(")", 1)[0].split(",")
                    if "=" in part
                ]
                for kw in kwargs:
                    with self.subTest(kwarg=kw):
                        self.assertIn(
                            kw, params,
                            f"module docstring advertises get_best_comps({kw}"
                            "=...) but the signature has no such parameter")


class TestSchemaAffinityIsDeclaredNotAssumed(unittest.TestCase):
    """Pin the numeric column set against the real schema.

    If a future column is added with INTEGER/REAL affinity, this fails until
    NUMERIC_COLUMNS is updated - so the coercion set cannot silently drift
    behind the schema.
    """

    def test_numeric_column_set_matches_schema_affinity(self):
        with TemporaryDirectory() as tmp:
            db = MatchDB(Path(tmp) / "m.db")
            try:
                info = db._conn().execute(
                    "PRAGMA table_info(matches)").fetchall()
            finally:
                db.close()
        declared = {
            r[1] for r in info
            if r[2].upper() in ("INTEGER", "REAL") and r[1] != "id"
        }
        self.assertEqual(
            declared, set(NUMERIC_COLUMNS),
            "schema numeric columns drifted from the coercion set")


if __name__ == "__main__":
    unittest.main()
