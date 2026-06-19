"""Tests for core.personal_build_wr - personal per-champion build win-rate.

Synthetic-DB cases pin the math (baseline WR, per-item lift ranking, modal
build, confidence tiers, fail-soft shells). A guarded live-DB smoke test asserts
only the contract SHAPE on a real champion (values are data-fragile).
"""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from core import personal_build_wr as pbw

_SR_MAP = 11


def _make_db(path: Path, games: list[dict]) -> None:
    """games = [{win:0/1, items:[i0..i5], champ_name, champ_id, team, map_id}]."""
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE matches (match_id TEXT, tracked_champion_name TEXT, "
        "tracked_champion_id INTEGER, tracked_team_id INTEGER, tracked_win INTEGER, "
        "map_id INTEGER, game_duration_s INTEGER)"
    )
    conn.execute(
        "CREATE TABLE participants (match_id TEXT, champion_id INTEGER, team_id INTEGER, "
        "item0 INTEGER, item1 INTEGER, item2 INTEGER, item3 INTEGER, item4 INTEGER, "
        "item5 INTEGER)"
    )
    for i, g in enumerate(games):
        mid = f"T_{i}"
        cid = g.get("champ_id", 999)
        team = g.get("team", 100)
        conn.execute(
            "INSERT INTO matches VALUES (?,?,?,?,?,?,?)",
            (mid, g.get("champ_name", "TestChamp"), cid, team, g["win"],
             g.get("map_id", _SR_MAP), g.get("dur", 1800)),
        )
        items = (g["items"] + [0] * 6)[:6]
        conn.execute(
            "INSERT INTO participants VALUES (?,?,?,?,?,?,?,?,?)",
            (mid, cid, team, *items),
        )
    conn.commit()
    conn.close()


def _build_20() -> list[dict]:
    games: list[dict] = []
    # 12 wins with Infinity Edge (3031) + Boots (3009)
    for _ in range(12):
        games.append({"win": 1, "items": [3031, 3009]})
    # 6 losses with a bad item (3071) + Boots
    for _ in range(6):
        games.append({"win": 0, "items": [3071, 3009]})
    # 2 losses with IE + Boots (so 3031 also appears in losses)
    for _ in range(2):
        games.append({"win": 0, "items": [3031, 3009]})
    return games  # 20 games, 12 wins -> baseline 0.6


class PersonalBuildMathTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "rewind.db"
        pbw.reset_cache()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_baseline_and_confidence(self) -> None:
        _make_db(self.db, _build_20())
        r = pbw.compute_personal_build("TestChamp", "sr", db_path=self.db)
        self.assertEqual(r["games"], 20)
        self.assertAlmostEqual(r["win_rate"], 0.6, places=3)
        self.assertEqual(r["confidence"], "ok")
        self.assertEqual(r["mode"], "sr")
        self.assertEqual(r["source"], "rewind_history.db")

    def test_item_lift_ranking(self) -> None:
        _make_db(self.db, _build_20())
        r = pbw.compute_personal_build("TestChamp", "sr", db_path=self.db)
        by_id = {it["item_id"]: it for it in r["items"]}
        self.assertIn(3031, by_id)
        self.assertIn(3071, by_id)
        # The winning item has positive lift, the losing item negative.
        self.assertGreater(by_id[3031]["lift"], 0.0)
        self.assertLess(by_id[3071]["lift"], 0.0)
        # Ranked by lift descending -> 3031 precedes 3071.
        ids = [it["item_id"] for it in r["items"]]
        self.assertLess(ids.index(3031), ids.index(3071))
        # Boots are tagged.
        self.assertTrue(by_id[3009]["is_boots"])

    def test_modal_build(self) -> None:
        _make_db(self.db, _build_20())
        r = pbw.compute_personal_build("TestChamp", "sr", db_path=self.db)
        # ('3009','3031') occurs 14x vs ('3009','3071') 6x.
        self.assertEqual(sorted(r["most_common_build"]), [3009, 3031])

    def test_min_item_games_filters_noise(self) -> None:
        games = _build_20()
        games.append({"win": 1, "items": [3036]})  # 1-game legendary, below item-games floor
        _make_db(self.db, games)
        r = pbw.compute_personal_build("TestChamp", "sr", db_path=self.db)
        self.assertNotIn(3036, {it["item_id"] for it in r["items"]})

    def test_thin_confidence(self) -> None:
        _make_db(self.db, [{"win": i % 2, "items": [3031, 3009]} for i in range(10)])
        r = pbw.compute_personal_build("TestChamp", "sr", db_path=self.db)
        self.assertEqual(r["games"], 10)
        self.assertEqual(r["confidence"], "thin")

    def test_insufficient_returns_empty(self) -> None:
        _make_db(self.db, [{"win": 1, "items": [3031]} for _ in range(5)])
        r = pbw.compute_personal_build("TestChamp", "sr", db_path=self.db)
        self.assertEqual(r["confidence"], "insufficient")
        self.assertEqual(r["items"], [])

    def test_mode_filters_by_map(self) -> None:
        games = _build_20()
        # Add 20 ARAM games (map 12) that should NOT count for an sr query.
        for _ in range(20):
            games.append({"win": 1, "items": [3031], "map_id": 12})
        _make_db(self.db, games)
        r = pbw.compute_personal_build("TestChamp", "sr", db_path=self.db)
        self.assertEqual(r["games"], 20)  # only the SR rows
        r_aram = pbw.compute_personal_build("TestChamp", "aram", db_path=self.db)
        self.assertEqual(r_aram["games"], 20)  # only the ARAM rows

    def test_numeric_champion_id(self) -> None:
        _make_db(self.db, _build_20())
        r = pbw.compute_personal_build(999, "sr", db_path=self.db)
        self.assertEqual(r["games"], 20)
        self.assertEqual(r["champion_id"], 999)

    def test_bad_mode_and_missing_db(self) -> None:
        _make_db(self.db, _build_20())
        self.assertEqual(
            pbw.compute_personal_build("TestChamp", "nonsense", db_path=self.db)["confidence"],
            "bad_mode",
        )
        missing = Path(self._tmp.name) / "nope.db"
        self.assertEqual(
            pbw.compute_personal_build("TestChamp", "sr", db_path=missing)["confidence"],
            "no_db",
        )

    def test_short_games_dropped(self) -> None:
        games = [{"win": 1, "items": [3031, 3009], "dur": 120} for _ in range(20)]
        _make_db(self.db, games)
        r = pbw.compute_personal_build("TestChamp", "sr", db_path=self.db)
        # All 20 are remakes (<300s) -> insufficient sample after the filter.
        self.assertEqual(r["confidence"], "insufficient")


class PersonalBuildLiveSmokeTests(unittest.TestCase):
    """Contract-shape only against the real rewind_history.db (if present)."""

    def test_live_contract_shape(self) -> None:
        if not pbw._REWIND_DB.exists():
            self.skipTest("rewind_history.db absent (clean checkout / CI)")
        r = pbw.compute_personal_build("Vayne", "sr")
        for key in ("champion", "mode", "games", "confidence", "items",
                    "most_common_build", "source"):
            self.assertIn(key, r)
        self.assertIsInstance(r["items"], list)
        for it in r["items"]:
            self.assertIn("item_id", it)
            self.assertIn("lift", it)
            self.assertIn("adj_win_rate", it)


if __name__ == "__main__":
    unittest.main()
