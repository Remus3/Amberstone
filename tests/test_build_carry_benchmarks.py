"""OQ12 slice A: scripts/build_carry_benchmarks.py characterization.

Stands up a throwaway rewind_history.db (minimal 3-table schema mirroring
the real participants/teams/matches columns the builder reads) and proves:

  - dual-group emission: a role-tagged participant lands in BOTH the
    "<team_position>|<bucket>" group AND the "<game_mode>|<bucket>" group
    (plus the always-emitted "|all" bucket for each);
  - hand-computed kp/gold/dmg percentile numbers (linear interpolation);
  - champion_kills=0 excludes the kp metric ONLY (gold/dmg still counted);
  - sub-300s matches and ""/"PRACTICETOOL" modes are skipped entirely;
  - the buckets map is emitted exactly;
  - the output file is pure 7-bit ASCII (CLAUDE.md hard rule).

ASCII-only authored content (CLAUDE.md hard rule).
"""
from __future__ import annotations

import json
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import scripts.build_carry_benchmarks as bcb


def _make_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE matches ("
        "  match_id TEXT PRIMARY KEY, game_mode TEXT,"
        "  game_duration_s INTEGER)"
    )
    conn.execute(
        "CREATE TABLE teams ("
        "  match_id TEXT, team_id INTEGER, champion_kills INTEGER)"
    )
    conn.execute(
        "CREATE TABLE participants ("
        "  match_id TEXT, team_id INTEGER, team_position TEXT,"
        "  kills INTEGER, deaths INTEGER, assists INTEGER,"
        "  total_damage_dealt_to_champs INTEGER, gold_earned INTEGER)"
    )
    matches = [
        ("M1", "CLASSIC",      1500),  # mid bucket
        ("M2", "ARAM",          900),  # short bucket, champion_kills=0
        ("M3", "CLASSIC",       200),  # sub-300s -> skipped
        ("M4", "PRACTICETOOL", 1500),  # mode filter -> skipped
        ("M5", "",             1500),  # empty mode -> skipped
        ("M6", "CLASSIC",      1800),  # long-bucket boundary
    ]
    conn.executemany("INSERT INTO matches VALUES (?,?,?)", matches)
    teams = [
        ("M1", 100, 10),
        ("M2", 100,  0),   # kp excluded for M2 team-100 rows
        ("M3", 100, 10),
        ("M4", 100, 10),
        ("M5", 100, 10),
        ("M6", 100,  6),
    ]
    conn.executemany("INSERT INTO teams VALUES (?,?,?)", teams)
    participants = [
        # (match, team, position, k, d, a, dmg, gold)
        ("M1", 100, "BOTTOM",  4, 2, 2, 20000, 10000),
        ("M1", 100, "UTILITY", 1, 3, 5,  5000,  5000),
        ("M2", 100, "",        5, 4, 5, 12000,  8000),
        ("M2", 100, "",        2, 6, 2,  4000,  2000),
        ("M3", 100, "TOP",     9, 0, 9, 30000, 15000),  # skipped (duration)
        ("M4", 100, "TOP",     9, 0, 9, 30000, 15000),  # skipped (mode)
        ("M5", 100, "TOP",     9, 0, 9, 30000, 15000),  # skipped (mode)
        ("M6", 100, "TOP",     3, 1, 3, 10000,  9000),
    ]
    conn.executemany(
        "INSERT INTO participants VALUES (?,?,?,?,?,?,?,?)", participants)
    conn.commit()
    conn.close()


class BuildCarryBenchmarksTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = TemporaryDirectory()
        tmp = Path(cls._tmp.name)
        db = tmp / "rewind_history.db"
        _make_db(db)
        cls.out_path = tmp / "carry_benchmarks.json"
        with mock.patch.object(bcb, "DB", db), \
             mock.patch.object(bcb, "OUT", cls.out_path):
            cls.rc = bcb.main([])
        cls.doc = json.loads(cls.out_path.read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_main_returns_zero(self):
        self.assertEqual(self.rc, 0)

    def test_missing_db_exits_2(self):
        with mock.patch.object(bcb, "DB", Path(self._tmp.name) / "nope.db"):
            self.assertEqual(bcb.main([]), 2)

    def test_dual_group_emission_role_and_mode(self):
        """The M1 BOTTOM participant lands in BOTH BOTTOM|* and CLASSIC|*."""
        g = self.doc["groups"]
        for key in ("BOTTOM|mid", "BOTTOM|all", "CLASSIC|mid", "CLASSIC|all",
                    "UTILITY|mid", "UTILITY|all"):
            self.assertIn(key, g, f"missing group {key}")

    def test_hand_computed_single_participant_group(self):
        """BOTTOM|mid = single row: kp 60.0, gold 66.7, dmg 80.0."""
        m = self.doc["groups"]["BOTTOM|mid"]["metrics"]
        for metric, want in (("kp_pct", 60.0),          # 100*(4+2)/10
                             ("gold_share_pct", 66.7),  # 100*10000/15000
                             ("dmg_share_pct", 80.0)):  # 100*20000/25000
            self.assertEqual(m[metric]["p25"], want)
            self.assertEqual(m[metric]["p50"], want)
            self.assertEqual(m[metric]["p75"], want)
            self.assertEqual(m[metric]["n"], 1)

    def test_hand_computed_linear_interpolation(self):
        """CLASSIC|mid gold shares are [33.333, 66.667] ->
        p25=41.7 p50=50.0 p75=58.3 (linear interpolation, round 1)."""
        m = self.doc["groups"]["CLASSIC|mid"]["metrics"]["gold_share_pct"]
        self.assertEqual(m["n"], 2)
        self.assertEqual(m["p25"], 41.7)
        self.assertEqual(m["p50"], 50.0)
        self.assertEqual(m["p75"], 58.3)
        # kp for both M1 rows is 60.0 -> all three percentiles pinned.
        kp = self.doc["groups"]["CLASSIC|mid"]["metrics"]["kp_pct"]
        self.assertEqual((kp["p25"], kp["p50"], kp["p75"]), (60.0, 60.0, 60.0))

    def test_champion_kills_zero_excludes_kp_only(self):
        """M2 team has champion_kills=0: no kp metric, but gold/dmg keep n=2."""
        m = self.doc["groups"]["ARAM|all"]["metrics"]
        self.assertNotIn("kp_pct", m)
        self.assertEqual(m["gold_share_pct"]["n"], 2)
        self.assertEqual(m["dmg_share_pct"]["n"], 2)
        # ARAM shares: gold [80, 20], dmg [75, 25]
        self.assertEqual(m["gold_share_pct"]["p50"], 50.0)
        self.assertEqual(m["dmg_share_pct"]["p50"], 50.0)

    def test_sub_300s_and_filtered_modes_skipped(self):
        g = self.doc["groups"]
        self.assertNotIn("PRACTICETOOL|all", g)
        self.assertNotIn("|all", g)  # empty-mode match never emits
        # M3/M4/M5 TOP rows all skipped -> only the M6 TOP row survives.
        self.assertEqual(g["TOP|all"]["n"], 1)
        # CLASSIC|all backs M1 (2 rows) + M6 (1 row) = 3, never M3.
        self.assertEqual(g["CLASSIC|all"]["n"], 3)

    def test_1800s_lands_in_long_bucket(self):
        g = self.doc["groups"]
        self.assertIn("CLASSIC|long", g)
        self.assertIn("TOP|long", g)
        self.assertEqual(g["TOP|long"]["metrics"]["kp_pct"]["p50"], 100.0)

    def test_buckets_map_exact(self):
        self.assertEqual(self.doc["buckets"], {
            "short": [0, 1199],
            "mid":   [1200, 1799],
            "long":  [1800, None],
        })

    def test_top_level_bookkeeping(self):
        self.assertEqual(self.doc["min_n"], 50)
        self.assertEqual(self.doc["source_matches"], 3)       # M1, M2, M6
        self.assertEqual(self.doc["source_participants"], 5)  # 2 + 2 + 1
        self.assertIn("generated_at", self.doc)
        self.assertIn("source_db", self.doc)

    def test_output_is_ascii(self):
        raw = self.out_path.read_text(encoding="utf-8")
        self.assertTrue(all(ord(c) < 128 for c in raw),
                        "carry_benchmarks.json must be 7-bit ASCII")


if __name__ == "__main__":
    unittest.main()
