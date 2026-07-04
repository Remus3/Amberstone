"""LIFT 3 - home last-20 W/L pip strip + recent-form win-rate.

The home summary payload now carries a ``last20`` dict (results /
wins / losses / win_rate) read from
``data/rewind_history.db.matches.tracked_win`` (0/1, the clean
single-account historical win column), via the same
``dashboard.builders._compute_last20`` helper the History season block
uses. These tests pin the computed quantities (newest-first order,
counts, win-rate) on a THROWAWAY temp rewind DB - no gitignored data is
read, so they pass on a clean checkout / CI where the live
``data/rewind_history.db`` is absent.

ASCII-only authored content (CLAUDE.md hard rule).
"""
from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def _make_rewind_db(path: Path, wins: list[int]) -> None:
    """Minimal rewind_history.db with the matches.tracked_win column the
    last-20 aggregate needs. ``wins`` is oldest-first; rows get an
    ascending game_creation_ts so the newest-first SELECT reverses it."""
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE matches ("
        "  match_id TEXT, game_creation_ts INTEGER,"
        "  tracked_champion_name TEXT, tracked_win INTEGER)"
    )
    for i, w in enumerate(wins):
        conn.execute(
            "INSERT INTO matches (match_id, game_creation_ts,"
            " tracked_champion_name, tracked_win) VALUES (?,?,?,?)",
            (f"NA1_{1000 + i}", 1_700_000_000_000 + i, "Lux", w),
        )
    conn.commit()
    conn.close()


def _make_rewind_db_q(path: Path, rows: list[tuple[int, int, int]]) -> None:
    """Rewind DB carrying queue_id + an explicit game_creation_ts (epoch
    MILLISECONDS) so the season-WR window + ranked-queue filter can be
    exercised deterministically. ``rows`` is a list of
    ``(tracked_win, queue_id, game_creation_ts_ms)``."""
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE matches ("
        "  match_id TEXT, game_creation_ts INTEGER,"
        "  tracked_champion_name TEXT, tracked_win INTEGER,"
        "  queue_id INTEGER)"
    )
    for i, (w, q, ts) in enumerate(rows):
        conn.execute(
            "INSERT INTO matches (match_id, game_creation_ts,"
            " tracked_champion_name, tracked_win, queue_id)"
            " VALUES (?,?,?,?,?)",
            (f"NA1_{2000 + i}", ts, "Lux", w, q),
        )
    conn.commit()
    conn.close()


def _evict(db_path: Path) -> None:
    from dashboard import _context
    cached = getattr(_context.DB_CONN_LOCAL, "conns", {}).pop(
        str(db_path), None)
    if cached is not None:
        cached.close()


def _evict_under(root: Path) -> None:
    """Close + drop every cached read-only conn whose path is under
    ``root``. _build_home_summary opens match_history.db across several
    helpers (trends / streaks); each cached conn must be released before
    the TemporaryDirectory teardown or Windows raises WinError 32 on
    unlink. Sweeping by prefix is robust to how many distinct conns the
    builder opened."""
    from dashboard import _context
    conns = getattr(_context.DB_CONN_LOCAL, "conns", {})
    prefix = str(root)
    for key in [k for k in list(conns.keys()) if k.startswith(prefix)]:
        conn = conns.pop(key, None)
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001 - best-effort teardown
                pass


class ComputeLast20Tests(unittest.TestCase):
    """_compute_last20 turns tracked_win rows into a W/L pip trail."""

    def _last20(self, wins: list[int]) -> dict:
        import dashboard.builders as B
        with TemporaryDirectory() as td:
            rw = Path(td) / "rewind_history.db"
            _make_rewind_db(rw, wins)
            from dashboard._context import ro_conn
            conn = ro_conn(rw)
            try:
                return B._compute_last20(conn)
            finally:
                _evict(rw)

    def test_results_newest_first_counts_and_wr(self):
        # oldest-first inserts: 7 wins then 3 losses. Newest-first SELECT
        # (ts DESC) -> the 3 losses come FIRST, then the 7 wins.
        out = self._last20([1, 1, 1, 1, 1, 1, 1, 0, 0, 0])
        self.assertEqual(out["results"],
                         ["L", "L", "L", "W", "W", "W", "W", "W", "W", "W"])
        self.assertEqual(out["wins"], 7)
        self.assertEqual(out["losses"], 3)
        self.assertEqual(out["win_rate"], 70.0)
        self.assertEqual(len(out["results"]), 10)
        self.assertTrue(set(out["results"]) <= {"W", "L"})

    def test_caps_at_20(self):
        out = self._last20([1, 0] * 15)  # 30 decided matches
        self.assertEqual(len(out["results"]), 20)
        self.assertEqual(out["wins"] + out["losses"], 20)
        # newest-first: last inserted was a loss (i=29 even index -> 0).
        self.assertEqual(out["results"][0], "L")

    def test_all_wins_wr_100(self):
        out = self._last20([1, 1, 1, 1])
        self.assertEqual(out["wins"], 4)
        self.assertEqual(out["losses"], 0)
        self.assertEqual(out["win_rate"], 100.0)

    def test_none_conn_returns_empty(self):
        import dashboard.builders as B
        self.assertEqual(B._compute_last20(None), {})


class HomeSummaryLast20Tests(unittest.TestCase):
    """_build_home_summary embeds last20 from the rewind DB, and degrades
    to {} when the DB is absent (the CI-safe clean-checkout path)."""

    def _run(self, mh_present: bool, rewind_wins=None,
             rewind_q_rows=None) -> dict:
        import dashboard.builders_home as H
        with TemporaryDirectory() as td:
            app_dir = Path(td)
            (app_dir / "data").mkdir()
            mh = app_dir / "data" / "match_history.db"
            rw = app_dir / "data" / "rewind_history.db"
            if mh_present:
                # Minimal match_history.db so the summary builds at all
                # (it returns early with an error if this DB is missing).
                conn = sqlite3.connect(str(mh))
                conn.execute(
                    "CREATE TABLE matches ("
                    "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                    "  timestamp TEXT, mode TEXT, champion TEXT, grade TEXT,"
                    "  game_time_s INTEGER, kills INTEGER, deaths INTEGER,"
                    "  assists INTEGER, cs INTEGER, cs_per_min REAL,"
                    "  gold INTEGER, gold_per_min REAL, kda_str TEXT,"
                    "  kp_pct REAL, label TEXT, raw_data TEXT,"
                    "  game_id INTEGER DEFAULT 0)"
                )
                conn.commit()
                conn.close()
            if rewind_q_rows is not None:
                _make_rewind_db_q(rw, rewind_q_rows)
            elif rewind_wins is not None:
                _make_rewind_db(rw, rewind_wins)
            try:
                # Pin rank to Unranked so the builder never touches a live
                # LCU client during the test.
                with mock.patch.object(H, "_get_lcu_for_rank",
                                       return_value=None):
                    with mock.patch.object(H, "_APP_DIR", app_dir):
                        out = H._build_home_summary()
            finally:
                _evict_under(app_dir)
        return out

    def test_last20_present_from_rewind(self):
        out = self._run(True, [1, 1, 1, 1, 1, 1, 1, 0, 0, 0])
        last20 = out.get("last20") or {}
        self.assertEqual(last20.get("wins"), 7)
        self.assertEqual(last20.get("losses"), 3)
        self.assertEqual(last20.get("win_rate"), 70.0)
        self.assertEqual(len(last20.get("results") or []), 10)

    def test_last20_empty_when_rewind_absent(self):
        # match_history present (summary builds) but NO rewind DB -> the
        # clean-checkout / CI shape: last20 is {} and nothing crashes.
        out = self._run(True, rewind_wins=None)
        self.assertEqual(out.get("last20"), {})


class SeasonWrRemovedGuardTests(unittest.TestCase):
    """HOME_QA H5: the ranked season-WR readout was removed - the
    _compute_season_wr builder is gone and no season_wr key ships in the
    home payload. (This file kept its last20 coverage above; the former
    ComputeSeasonWrTests / HomeSummarySeasonWrTests classes were converted
    to these deletion guards.)"""

    def test_compute_season_wr_gone(self):
        import dashboard.builders as B
        self.assertFalse(hasattr(B, "_compute_season_wr"),
                         "dashboard.builders still exposes _compute_season_wr")

    def test_season_wr_not_in_payload(self):
        out = HomeSummaryLast20Tests()._run(
            True, rewind_q_rows=[(1, 420, 1_782_000_000_000)])
        self.assertNotIn("season_wr", out,
                         "home payload still carries season_wr")


if __name__ == "__main__":
    unittest.main()
