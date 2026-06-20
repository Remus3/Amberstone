"""TODO item 77 / RC2 history P1+P2 - WIN-CAPTURE keystone.

Surfaces the per-match win/loss result on the History rows + the Home
Recent strip, plus a last-20 W/L summary and a REAL season win-rate, all
from data already on disk. Verified ground truth (2026-06-20):

  - The History + Home views read data/match_history.db, which has NO
    win column (cols probed live: id, timestamp, mode, champion, grade,
    game_time_s, kills, deaths, assists, cs, cs_per_min, gold,
    gold_per_min, kda_str, ..., raw_data, game_id). So win can NOT come
    from a SELECT column - the research doc's "add win to the SELECT"
    plan was wrong for this DB.
  - The win bool DOES live inside match_history.db.matches.raw_data ->
    "lcu_match_detail", reachable via the SAME puuid -> participantId ->
    stats walk that dashboard.builders_home._lcu_build_items already uses
    (it reads stats.itemN; win is stats.win). Coverage on recent rows is
    24/25 vs 1/20 for a rewind join, so raw_data is the right per-row
    source. Rows predating LCU ingest have no detail -> win is None.
  - The last-20 / season win-rate aggregate comes from
    data/rewind_history.db.matches.tracked_win (0/1, 2942 rows), the
    clean single-account historical win column.

No gitignored data is read - every DB here is a throwaway temp file.
ASCII-only authored content (CLAUDE.md hard rule).
"""
from __future__ import annotations

import json
import sqlite3
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def _raw_with_win(puuid: str, win: bool) -> str:
    """A match_history raw_data blob carrying an lcu_match_detail whose
    tracked player's stats.win == win (mirror of the real ingest shape
    that _lcu_build_items already walks for item0..item5)."""
    return json.dumps({
        "game_mode": "ARAM",
        "tracked_puuid": puuid,
        "lcu_match_detail": {
            "participantIdentities": [
                {"participantId": 1, "player": {"puuid": "someone-else"}},
                {"participantId": 2, "player": {"puuid": puuid}},
            ],
            "participants": [
                {"participantId": 1, "stats": {"win": not win}},
                {"participantId": 2, "stats": {"win": win}},
            ],
        },
    })


def _make_match_history_db(path: Path, rows: list[dict]) -> None:
    """Create a match_history.db whose `matches` table mirrors the live
    column set this feature touches, then insert the given rows."""
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE matches ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  timestamp TEXT, mode TEXT, champion TEXT, grade TEXT,"
        "  game_time_s INTEGER, kills INTEGER, deaths INTEGER,"
        "  assists INTEGER, cs INTEGER, cs_per_min REAL,"
        "  gold INTEGER, gold_per_min REAL, kda_str TEXT, kp_pct REAL,"
        "  label TEXT, raw_data TEXT, game_id INTEGER DEFAULT 0)"
    )
    for r in rows:
        conn.execute(
            "INSERT INTO matches (timestamp, mode, champion, grade,"
            " game_time_s, kills, deaths, assists, cs, cs_per_min,"
            " gold, gold_per_min, kda_str, kp_pct, label, raw_data,"
            " game_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (r["timestamp"], r.get("mode", "ARAM"), r.get("champion", "Lux"),
             r.get("grade", "A"), r.get("dur", 1500), r.get("k", 5),
             r.get("d", 3), r.get("a", 7), r.get("cs", 30), r.get("cspm", 1.2),
             r.get("gold", 9000), r.get("gpm", 360.0),
             r.get("kda", "5/3/7"), r.get("kp", 60.0), r.get("label", ""),
             r.get("raw_data", ""), r.get("game_id", 0)),
        )
    conn.commit()
    conn.close()


def _make_rewind_db(path: Path, wins: list[int]) -> None:
    """Minimal rewind_history.db with just the matches.tracked_win
    column the season/last-20 aggregate needs (+ tracked_champion_name,
    read by the existing season_stats favorite query)."""
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE matches ("
        "  match_id TEXT, game_creation_ts INTEGER,"
        "  tracked_champion_name TEXT, tracked_win INTEGER,"
        "  tracked_kills INTEGER, tracked_deaths INTEGER,"
        "  tracked_assists INTEGER)"
    )
    for i, w in enumerate(wins):
        conn.execute(
            "INSERT INTO matches (match_id, game_creation_ts,"
            " tracked_champion_name, tracked_win, tracked_kills,"
            " tracked_deaths, tracked_assists) VALUES (?,?,?,?,?,?,?)",
            (f"NA1_{1000 + i}", 1_700_000_000_000 + i, "Lux", w, 5, 3, 7),
        )
    conn.commit()
    conn.close()


def _evict(db_path: Path) -> None:
    from dashboard import _context
    cached = getattr(_context.DB_CONN_LOCAL, "conns", {}).pop(
        str(db_path), None)
    if cached is not None:
        cached.close()


PUUID = "tracked-player-puuid-abc"


class LcuWinResolverTests(unittest.TestCase):
    """_lcu_win extracts the tracked player's win from raw_data."""

    def test_resolves_true_and_false(self):
        from dashboard.builders_home import _lcu_win
        self.assertIs(_lcu_win(_raw_with_win(PUUID, True)), True)
        self.assertIs(_lcu_win(_raw_with_win(PUUID, False)), False)

    def test_missing_detail_returns_none(self):
        from dashboard.builders_home import _lcu_win
        self.assertIsNone(_lcu_win(""))
        self.assertIsNone(_lcu_win(None))
        self.assertIsNone(_lcu_win(json.dumps({"game_mode": "ARAM"})))


class LoadMatchRowsWinTests(unittest.TestCase):
    """_load_match_rows must carry a per-row `win` (bool|None)."""

    def test_win_on_each_row(self):
        import dashboard.builders as B
        with TemporaryDirectory() as td:
            app_dir = Path(td)
            (app_dir / "data").mkdir()
            db = app_dir / "data" / "match_history.db"
            _make_match_history_db(db, [
                {"timestamp": "2026-06-19 23:00:00",
                 "raw_data": _raw_with_win(PUUID, True), "game_id": 1000},
                {"timestamp": "2026-06-19 21:00:00",
                 "raw_data": _raw_with_win(PUUID, False), "game_id": 1001},
                {"timestamp": "2026-06-10 20:00:00",
                 "raw_data": "", "game_id": 1002},  # predates ingest
            ])
            try:
                with mock.patch.object(B, "_APP_DIR", app_dir):
                    rows = B._load_match_rows()
            finally:
                _evict(db)
        by_ts = {r["timestamp"]: r for r in rows}
        self.assertIn("win", rows[0])
        self.assertIs(by_ts["2026-06-19 23:00:00"]["win"], True)
        self.assertIs(by_ts["2026-06-19 21:00:00"]["win"], False)
        self.assertIsNone(by_ts["2026-06-10 20:00:00"]["win"])


class BuildHistoryWinTests(unittest.TestCase):
    """_build_history propagates win into session match rows and adds a
    last-20 W/L summary + a real season win-rate."""

    def _run(self, mh_rows, rewind_wins):
        import dashboard.builders as B
        with TemporaryDirectory() as td:
            app_dir = Path(td)
            (app_dir / "data").mkdir()
            mh = app_dir / "data" / "match_history.db"
            rw = app_dir / "data" / "rewind_history.db"
            _make_match_history_db(mh, mh_rows)
            _make_rewind_db(rw, rewind_wins)
            try:
                with mock.patch.object(B, "_APP_DIR", app_dir):
                    out = B._build_history("all")
            finally:
                _evict(mh)
                _evict(rw)
        return out

    def test_match_rows_have_win(self):
        out = self._run(
            [{"timestamp": "2026-06-19 23:00:00",
              "raw_data": _raw_with_win(PUUID, True), "game_id": 1000},
             {"timestamp": "2026-06-19 22:40:00",
              "raw_data": _raw_with_win(PUUID, False), "game_id": 1001}],
            [1, 0, 1])
        matches = []
        for s in out["sessions"]:
            matches.extend(s.get("matches", []))
        wins = {m["timestamp"]: m.get("win") for m in matches}
        self.assertIs(wins["2026-06-19 23:00:00"], True)
        self.assertIs(wins["2026-06-19 22:40:00"], False)

    def test_last20_and_win_rate_from_rewind(self):
        # 7 wins, 3 losses -> WR 70, last20 covers all 10.
        wins = [1, 1, 1, 1, 1, 1, 1, 0, 0, 0]
        out = self._run(
            [{"timestamp": "2026-06-19 23:00:00",
              "raw_data": _raw_with_win(PUUID, True), "game_id": 1000}],
            wins)
        ss = out["season_stats"]
        self.assertEqual(ss.get("wins"), 7)
        self.assertEqual(ss.get("losses"), 3)
        self.assertEqual(ss.get("win_rate"), 70.0)
        last20 = out.get("last20") or {}
        self.assertEqual(last20.get("wins"), 7)
        self.assertEqual(last20.get("losses"), 3)
        self.assertEqual(last20.get("win_rate"), 70.0)
        # results list newest-first, each 'W'/'L', len <= 20
        results = last20.get("results")
        self.assertIsInstance(results, list)
        self.assertLessEqual(len(results), 20)
        self.assertEqual(len(results), 10)
        self.assertTrue(set(results) <= {"W", "L"})

    def test_last20_caps_at_20(self):
        wins = [1, 0] * 15  # 30 matches
        out = self._run(
            [{"timestamp": "2026-06-19 23:00:00",
              "raw_data": _raw_with_win(PUUID, True), "game_id": 1000}],
            wins)
        last20 = out.get("last20") or {}
        self.assertEqual(len(last20.get("results") or []), 20)
        self.assertEqual(last20.get("wins", 0) + last20.get("losses", 0), 20)


class HomeSummaryWinTests(unittest.TestCase):
    """Home Recent strip rows must carry win too (builders_home:101)."""

    def test_recent_rows_have_win(self):
        import dashboard.builders_home as H
        with TemporaryDirectory() as td:
            app_dir = Path(td)
            (app_dir / "data").mkdir()
            db = app_dir / "data" / "match_history.db"
            _make_match_history_db(db, [
                {"timestamp": "2026-06-19 23:00:00",
                 "raw_data": _raw_with_win(PUUID, True), "game_id": 1000},
                {"timestamp": "2026-06-10 20:00:00",
                 "raw_data": "", "game_id": 1001},
            ])
            try:
                with mock.patch.object(H, "_APP_DIR", app_dir):
                    out = H._build_home_summary()
            finally:
                _evict(db)
        recent = out.get("recent") or []
        self.assertTrue(recent, "no recent rows built")
        self.assertIn("win", recent[0])
        self.assertIs(recent[0]["win"], True)
        # the pre-ingest row reports None, not a crash
        none_row = [r for r in recent if r["timestamp"].startswith("2026-06-10")]
        if none_row:
            self.assertIsNone(none_row[0]["win"])


if __name__ == "__main__":
    unittest.main()
