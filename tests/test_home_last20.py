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


class ComputeSeasonWrTests(unittest.TestCase):
    """_compute_season_wr counts only ranked (420 Solo/Duo, 440 Flex)
    games inside the season window (repo-canonical best-effort = last 90d),
    off a throwaway rewind DB with a deterministic injected ``now_ms``.
    game_creation_ts is epoch MILLISECONDS."""

    NOW_MS = 1_782_000_000_000  # fixed "now" for window math (mid-2026)
    DAY = 86_400_000

    def _season(self, rows, **kw):
        import dashboard.builders as B
        with TemporaryDirectory() as td:
            rw = Path(td) / "rewind_history.db"
            _make_rewind_db_q(rw, rows)
            from dashboard._context import ro_conn
            conn = ro_conn(rw)
            try:
                return B._compute_season_wr(conn, now_ms=self.NOW_MS, **kw)
            finally:
                _evict(rw)

    def test_counts_ranked_within_window(self):
        recent = self.NOW_MS - 10 * self.DAY
        out = self._season([
            (1, 420, recent), (1, 420, recent), (1, 440, recent),
            (0, 420, recent),
        ])
        self.assertEqual(out["wins"], 3)
        self.assertEqual(out["losses"], 1)
        self.assertEqual(out["n"], 4)
        self.assertEqual(out["win_rate"], 75.0)

    def test_excludes_non_ranked_queue(self):
        # An ARAM (450) win inside the window is NOT counted as season WR.
        recent = self.NOW_MS - 5 * self.DAY
        out = self._season([
            (1, 420, recent), (1, 450, recent), (1, 450, recent),
        ])
        self.assertEqual(out["wins"], 1)
        self.assertEqual(out["n"], 1)

    def test_excludes_outside_window(self):
        # A ranked win 120 days ago is outside the 90d season window.
        old = self.NOW_MS - 120 * self.DAY
        recent = self.NOW_MS - 3 * self.DAY
        out = self._season([(1, 420, old), (0, 420, recent)])
        self.assertEqual(out["wins"], 0)
        self.assertEqual(out["losses"], 1)
        self.assertEqual(out["n"], 1)
        self.assertEqual(out["win_rate"], 0.0)

    def test_no_ranked_games_win_rate_none(self):
        # DB present but only ARAM -> n=0, win_rate None (frontend hides).
        recent = self.NOW_MS - 2 * self.DAY
        out = self._season([(1, 450, recent), (0, 450, recent)])
        self.assertEqual(out["n"], 0)
        self.assertIsNone(out["win_rate"])

    def test_custom_window_and_queues(self):
        # 14d window, custom ranked set -> respects both knobs.
        in_win = self.NOW_MS - 7 * self.DAY
        out_win = self.NOW_MS - 20 * self.DAY
        out = self._season(
            [(1, 700, in_win), (0, 700, in_win), (1, 700, out_win)],
            window_days=14, ranked_queues=(700,))
        self.assertEqual(out["n"], 2)
        self.assertEqual(out["win_rate"], 50.0)

    def test_none_conn_returns_empty(self):
        import dashboard.builders as B
        self.assertEqual(B._compute_season_wr(None), {})


class HomeSummarySeasonWrTests(unittest.TestCase):
    """_build_home_summary embeds season_wr as a dict when rewind is
    present and degrades to {} on the clean-checkout / CI path."""

    def test_season_wr_present_dict_when_rewind_present(self):
        t = HomeSummaryLast20Tests()
        out = t._run(True, rewind_q_rows=[(1, 420, 1_782_000_000_000)])
        sw = out.get("season_wr")
        self.assertIsInstance(sw, dict)
        self.assertTrue(
            {"wins", "losses", "win_rate", "n"} <= set(sw.keys()))

    def test_season_wr_empty_when_rewind_absent(self):
        t = HomeSummaryLast20Tests()
        out = t._run(True, rewind_wins=None)
        self.assertEqual(out.get("season_wr"), {})


if __name__ == "__main__":
    unittest.main()
