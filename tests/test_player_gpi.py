"""Hermetic tests for core/player_gpi.py - the 8-axis GPI radar compute.

Self-contained in-memory rewind DB (no live data/rewind_history.db needed),
passed to compute_gpi(conn=...). One test also exercises the open_ro env path
(RC_REWIND_DB) the route layer uses.
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from core import player_gpi

_MATCH_COLS = (
    "match_id TEXT PRIMARY KEY, game_duration_s INTEGER, game_creation_ts INTEGER, "
    "has_stats INTEGER, map_id INTEGER, tracked_champion_id INTEGER, "
    "tracked_team_id INTEGER"
)
_PART_COLS = (
    "id INTEGER PRIMARY KEY, match_id TEXT, champion_id INTEGER, team_id INTEGER, "
    "total_minions_killed INTEGER, neutral_minions_killed INTEGER, "
    "vision_score INTEGER, gold_earned INTEGER, total_damage_dealt_to_champs INTEGER, "
    "deaths INTEGER, kills INTEGER, assists INTEGER, dragon_kills INTEGER, "
    "baron_kills INTEGER, turret_takedowns INTEGER, inhibitor_takedowns INTEGER"
)


class _Builder:
    """Build an in-memory rewind DB and insert operator games."""

    def __init__(self, path: str | None = None) -> None:
        self.conn = sqlite3.connect(path if path else ":memory:")
        self.conn.execute(f"CREATE TABLE matches ({_MATCH_COLS})")
        self.conn.execute(f"CREATE TABLE participants ({_PART_COLS})")
        self._mid = 0
        self._pid = 0
        self._ts = 0

    def add(self, champ=22, dmg=12000, deaths=6, cs=180, vis=30, gold=12000,
            obj=2, kills=5, assists=8, dur_s=1800, map_id=11, has_stats=1,
            team=100, dup=False):
        """Insert one operator game (newest = latest call). ``dup`` adds a
        second participant row sharing the join keys to exercise dedupe."""
        self._mid += 1
        self._ts += 1
        mid = f"M{self._mid}"
        self.conn.execute(
            "INSERT INTO matches VALUES (?,?,?,?,?,?,?)",
            (mid, dur_s, self._ts, has_stats, map_id, champ, team),
        )
        rows = 2 if dup else 1
        for _ in range(rows):
            self._pid += 1
            self.conn.execute(
                "INSERT INTO participants VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (self._pid, mid, champ, team, cs, 0, vis, gold, dmg, deaths,
                 kills, assists, obj, 0, 0, 0),
            )
        return self

    def close(self):
        self.conn.close()


class GpiCoreTests(unittest.TestCase):
    """Main fixture: 20 low-output older games + 10 high-output recent games."""

    @classmethod
    def setUpClass(cls):
        b = _Builder()
        # 20 older games: low damage, MANY deaths, low cs/vis/gold/obj.
        for _ in range(20):
            b.add(champ=22, dmg=9000, deaths=12, cs=120, vis=12, gold=9000, obj=0,
                  kills=2, assists=4)
        # 10 recent games: high damage, FEW deaths, high cs/vis/gold/obj, mixed champs.
        for i in range(10):
            b.add(champ=(60 + i % 5), dmg=27000, deaths=3, cs=240, vis=42,
                  gold=18000, obj=4, kills=9, assists=7)
        cls.b = b
        cls.res = player_gpi.compute_gpi(mode="sr", window=10, conn=b.conn)

    @classmethod
    def tearDownClass(cls):
        cls.b.close()

    def test_ok_and_shape(self):
        self.assertTrue(self.res["ok"])
        self.assertEqual(self.res["n_games"], 30)
        self.assertEqual(self.res["confidence"], "high")
        keys = [a["key"] for a in self.res["axes"]]
        self.assertEqual(keys, ["aggression", "farming", "vision", "objectives",
                                "survival", "tempo", "versatility", "consistency"])

    def test_recent_above_baseline_pushes_relative_axes_high(self):
        by = {a["key"]: a for a in self.res["axes"]}
        # Recent 10 games are the top of the distribution -> percentile high.
        self.assertGreater(by["aggression"]["score"], 60)
        self.assertGreater(by["farming"]["score"], 60)
        self.assertGreater(by["tempo"]["score"], 60)

    def test_survival_axis_inverts_deaths(self):
        by = {a["key"]: a for a in self.res["axes"]}
        # Recent games have FEWER deaths than baseline -> survival scores high
        # even though the raw metric (deaths/min) is lower.
        self.assertGreater(by["survival"]["score"], 60)
        self.assertFalse(by["survival"]["higher_is_better"])

    def test_overall_is_axis_mean(self):
        mean = round(sum(a["score"] for a in self.res["axes"])
                     / len(self.res["axes"]), 1)
        self.assertEqual(self.res["overall"], mean)

    def test_recent_value_and_baseline_present(self):
        agg = next(a for a in self.res["axes"] if a["key"] == "aggression")
        self.assertEqual(agg["unit"], "dmg/min")
        self.assertGreater(agg["recent_value"], 0)
        self.assertIsNotNone(agg["baseline_p50"])

    def test_weakest_axis_is_a_relative_skill_axis_with_tip(self):
        self.assertIn(self.res["weakest_axis"], player_gpi._AXIS_TIPS)
        self.assertEqual(self.res["tip"],
                         player_gpi._AXIS_TIPS[self.res["weakest_axis"]])


class GpiTipTests(unittest.TestCase):
    def test_weakest_axis_drives_the_tip(self):
        b = _Builder()
        # Older games: strong vision. Recent games: vision craters, everything
        # else improves -> vision is unambiguously the weakest relative axis.
        for _ in range(20):
            b.add(vis=60, dmg=9000, deaths=12, cs=120, gold=9000, obj=0)
        for _ in range(10):
            b.add(vis=2, dmg=27000, deaths=3, cs=240, gold=18000, obj=4)
        res = player_gpi.compute_gpi(mode="sr", window=10, conn=b.conn)
        self.assertEqual(res["weakest_axis"], "vision")
        self.assertEqual(res["tip"], player_gpi._AXIS_TIPS["vision"])
        b.close()

    def test_shape_axes_never_selected_as_weakest(self):
        # All-same champ (versatility=0) must NOT win the tip - shape axes are
        # ineligible; a relative axis is always chosen.
        b = _Builder()
        for _ in range(12):
            b.add(champ=22)
        res = player_gpi.compute_gpi(mode="sr", window=12, conn=b.conn)
        self.assertNotIn(res["weakest_axis"], ("versatility", "consistency"))
        self.assertIn(res["weakest_axis"], player_gpi._AXIS_TIPS)
        b.close()

    def test_insufficient_has_null_tip(self):
        b = _Builder()
        for _ in range(5):
            b.add()
        res = player_gpi.compute_gpi(mode="sr", conn=b.conn)
        self.assertIsNone(res["weakest_axis"])
        self.assertIsNone(res["tip"])
        b.close()


class GpiThresholdTests(unittest.TestCase):
    def test_insufficient_below_min_games(self):
        b = _Builder()
        for _ in range(player_gpi.MIN_GAMES - 1):
            b.add()
        res = player_gpi.compute_gpi(mode="sr", conn=b.conn)
        self.assertTrue(res["ok"])
        self.assertEqual(res["confidence"], "insufficient")
        self.assertEqual(res["axes"], [])
        self.assertIsNone(res["overall"])
        b.close()

    def test_mode_filter_excludes_other_maps(self):
        b = _Builder()
        for _ in range(15):
            b.add(map_id=11)          # SR
        for _ in range(15):
            b.add(map_id=12)          # ARAM noise
        res = player_gpi.compute_gpi(mode="sr", conn=b.conn)
        self.assertEqual(res["n_games"], 15)
        b.close()

    def test_champion_filter(self):
        b = _Builder()
        for _ in range(12):
            b.add(champ=22)
        for _ in range(12):
            b.add(champ=64)
        res = player_gpi.compute_gpi(mode="sr", champion=64, conn=b.conn)
        self.assertEqual(res["n_games"], 12)
        b.close()

    def test_dedupe_collapses_duplicate_join_rows(self):
        b = _Builder()
        for _ in range(12):
            b.add(dup=True)           # 2 participant rows per match
        res = player_gpi.compute_gpi(mode="sr", conn=b.conn)
        self.assertEqual(res["n_games"], 12)
        b.close()

    def test_short_game_excluded(self):
        b = _Builder()
        for _ in range(12):
            b.add(dur_s=1800)
        b.add(dur_s=120)              # remake, under MIN_DURATION_S
        res = player_gpi.compute_gpi(mode="sr", conn=b.conn)
        self.assertEqual(res["n_games"], 12)
        b.close()


class GpiVersatilityTests(unittest.TestCase):
    def test_one_trick_scores_zero(self):
        b = _Builder()
        for _ in range(12):
            b.add(champ=22)
        res = player_gpi.compute_gpi(mode="sr", window=12, conn=b.conn)
        v = next(a for a in res["axes"] if a["key"] == "versatility")
        self.assertEqual(v["score"], 0.0)
        b.close()

    def test_all_distinct_scores_full(self):
        b = _Builder()
        for i in range(12):
            b.add(champ=100 + i)
        res = player_gpi.compute_gpi(mode="sr", window=12, conn=b.conn)
        v = next(a for a in res["axes"] if a["key"] == "versatility")
        self.assertEqual(v["score"], 100.0)
        self.assertEqual(v["recent_value"], 12)
        b.close()


class GpiConsistencyTests(unittest.TestCase):
    def test_steady_kda_scores_full(self):
        b = _Builder()
        for _ in range(12):
            b.add(kills=5, assists=5, deaths=5)     # identical kda every game
        res = player_gpi.compute_gpi(mode="sr", window=12, conn=b.conn)
        c = next(a for a in res["axes"] if a["key"] == "consistency")
        self.assertEqual(c["score"], 100.0)
        b.close()

    def test_volatile_kda_scores_below_steady(self):
        b = _Builder()
        for i in range(12):
            if i % 2:
                b.add(kills=15, assists=10, deaths=1)   # huge kda
            else:
                b.add(kills=0, assists=1, deaths=12)    # tiny kda
        res = player_gpi.compute_gpi(mode="sr", window=12, conn=b.conn)
        c = next(a for a in res["axes"] if a["key"] == "consistency")
        self.assertLess(c["score"], 60.0)
        b.close()


class GpiEnvPathTests(unittest.TestCase):
    """Exercise the open_ro / RC_REWIND_DB path the route uses (no conn arg)."""

    def test_compute_via_env_db(self):
        tmp = tempfile.TemporaryDirectory(prefix="rc_gpi_")
        try:
            path = Path(tmp.name) / "rewind_history.db"
            b = _Builder(path=str(path))
            for _ in range(12):
                b.add()
            b.conn.commit()
            b.close()
            prev = os.environ.get("RC_REWIND_DB")
            os.environ["RC_REWIND_DB"] = str(path)
            try:
                res = player_gpi.compute_gpi(mode="sr")
                self.assertTrue(res["ok"])
                self.assertEqual(res["n_games"], 12)
                self.assertEqual(len(res["axes"]), 8)
            finally:
                if prev is None:
                    os.environ.pop("RC_REWIND_DB", None)
                else:
                    os.environ["RC_REWIND_DB"] = prev
        finally:
            tmp.cleanup()


class GpiAsciiTests(unittest.TestCase):
    def test_module_is_ascii(self):
        raw = Path(player_gpi.__file__).read_bytes()
        self.assertEqual(raw.decode("ascii", "ignore").encode("ascii"),
                         raw.replace(b"\r", b""))


class ListChampionsTests(unittest.TestCase):
    """list_champions: the per-champion drilldown pool (item 511)."""

    def _db(self):
        b = _Builder()
        for _ in range(5):
            b.add(champ=22)
        for _ in range(3):
            b.add(champ=64)
        b.add(champ=99)
        return b

    def test_counts_and_desc_order(self):
        b = self._db()
        try:
            out = player_gpi.list_champions("sr", conn=b.conn)
        finally:
            b.close()
        self.assertEqual(out, [
            {"champion_id": 22, "n_games": 5},
            {"champion_id": 64, "n_games": 3},
            {"champion_id": 99, "n_games": 1},
        ])

    def test_dedupes_multi_match_join_rows(self):
        # A dup participant row sharing the join keys must NOT double-count the
        # match (mirror _fetch_operator_games' per-match dedupe).
        b = _Builder()
        b.add(champ=22, dup=True)
        b.add(champ=22)
        try:
            out = player_gpi.list_champions("sr", conn=b.conn)
        finally:
            b.close()
        self.assertEqual(out, [{"champion_id": 22, "n_games": 2}])

    def test_mode_map_filter_excludes_other_modes(self):
        b = _Builder()
        b.add(champ=22, map_id=11)        # SR
        b.add(champ=777, map_id=12)       # ARAM
        try:
            sr = player_gpi.list_champions("sr", conn=b.conn)
            aram = player_gpi.list_champions("aram", conn=b.conn)
        finally:
            b.close()
        self.assertEqual([c["champion_id"] for c in sr], [22])
        self.assertEqual([c["champion_id"] for c in aram], [777])

    def test_excludes_no_stats_and_short_games(self):
        b = _Builder()
        b.add(champ=22)                                  # kept
        b.add(champ=22, has_stats=0)                     # dropped (no stats)
        b.add(champ=22, dur_s=player_gpi.MIN_DURATION_S - 1)  # dropped (remake)
        try:
            out = player_gpi.list_champions("sr", conn=b.conn)
        finally:
            b.close()
        self.assertEqual(out, [{"champion_id": 22, "n_games": 1}])

    def test_empty_db_returns_empty_list(self):
        b = _Builder()
        try:
            self.assertEqual(player_gpi.list_champions("sr", conn=b.conn), [])
        finally:
            b.close()

    def test_invalid_mode_falls_back_to_sr(self):
        b = _Builder()
        b.add(champ=22, map_id=11)
        try:
            self.assertEqual(
                player_gpi.list_champions("urf", conn=b.conn),
                [{"champion_id": 22, "n_games": 1}])
        finally:
            b.close()


if __name__ == "__main__":
    unittest.main()
