"""RM-610 (directive X-10, external reference A): unit tests for the one
resolved-WR helper, core.resolved_wr.

A row counts toward the win-rate denominator only when its result is
KNOWN (a boolean win, exactly one winner), it is not a remake (duration
under core.corpus_hygiene.REMAKE_MAX_SECONDS, or the Match-V5
gameEndedInEarlySurrender flag), and it is not draft-only / inferred.
Zero resolved games renders the operator-approved '-' sentinel.

Synthetic rows only. ASCII-only authored content.
"""
from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core import corpus_hygiene  # noqa: E402
from core import resolved_wr as R  # noqa: E402


class ClassifyTests(unittest.TestCase):

    def test_win_and_loss(self):
        self.assertEqual(R.classify({"win": 1}), "win")
        self.assertEqual(R.classify({"win": True}), "win")
        self.assertEqual(R.classify({"tracked_win": 0}), "loss")
        self.assertEqual(R.classify({"win": False}), "loss")
        self.assertEqual(R.classify({"win": "Win"}), "win")
        self.assertEqual(R.classify({"win": "Fail"}), "loss")

    def test_unknown_result(self):
        self.assertEqual(R.classify({"win": None}), "unknown")
        self.assertEqual(R.classify({}), "unknown")
        self.assertEqual(R.classify({"win": 2}), "unknown")
        self.assertEqual(R.classify({"win": "maybe"}), "unknown")

    def test_exactly_one_winner(self):
        self.assertEqual(R.classify({"win": 1, "winner_count": 1}), "win")
        self.assertEqual(R.classify({"win": 1, "winner_count": 2}), "unknown")
        self.assertEqual(R.classify({"win": 0, "winner_count": 0}), "unknown")

    def test_draft_only_and_inferred_are_unresolved(self):
        self.assertEqual(R.classify({"win": 1, "draft_only": 1}), "unknown")
        self.assertEqual(R.classify({"win": 1, "result_inferred": True}),
                         "unknown")
        self.assertEqual(R.classify({"win": 1, "draft_only": 0}), "win")

    def test_remake_by_duration_reuses_corpus_hygiene_constant(self):
        cut = corpus_hygiene.REMAKE_MAX_SECONDS
        self.assertEqual(R.REMAKE_MAX_SECONDS, cut)
        self.assertEqual(R.classify({"win": 1, "game_duration_s": cut - 1}),
                         "remake")
        self.assertEqual(R.classify({"win": 1, "game_duration_s": cut}), "win")
        # Unknown duration (0 / None) is not a remake - same rule as
        # corpus_hygiene.judge.
        self.assertEqual(R.classify({"win": 1, "game_duration_s": 0}), "win")
        self.assertEqual(R.classify({"win": 0, "gameDuration": 120}), "remake")

    def test_remake_by_early_surrender(self):
        self.assertEqual(
            R.classify({"win": 0, "game_ended_in_early_surrender": 1}),
            "remake")
        self.assertEqual(
            R.classify({"win": 0, "gameEndedInEarlySurrender": True}),
            "remake")
        self.assertEqual(
            R.classify({"win": 0, "game_ended_in_early_surrender": 0}),
            "loss")

    def test_remake_wins_over_unknown(self):
        self.assertEqual(R.classify({"win": None, "game_duration_s": 100}),
                         "remake")

    def test_sqlite_row(self):
        c = sqlite3.connect(":memory:")
        c.row_factory = sqlite3.Row
        row = c.execute("SELECT 1 AS win, 1500 AS game_duration_s").fetchone()
        self.assertEqual(R.classify(row), "win")
        row = c.execute("SELECT 1 AS win, 200 AS game_duration_s").fetchone()
        self.assertEqual(R.classify(row), "remake")


class ResolvedWrTests(unittest.TestCase):

    def test_fixture_is_fifty(self):
        rows = [{"win": 1}, {"win": 0},
                {"win": 0, "game_duration_s": 200}, {"win": None}]
        self.assertEqual(R.resolved_wr(rows), (1, 2, "50%"))

    def test_zero_resolved_is_sentinel(self):
        self.assertEqual(R.resolved_wr([]), (0, 0, "-"))
        self.assertEqual(R.resolved_wr([{"win": None}]), (0, 0, "-"))
        self.assertEqual(R.SENTINEL, "-")

    def test_rounding(self):
        self.assertEqual(R.resolved_wr([{"win": 1}, {"win": 1}, {"win": 0}]),
                         (2, 3, "67%"))

    def test_wr_pct(self):
        self.assertEqual(R.wr_pct(1, 2), 50.0)
        self.assertEqual(R.wr_pct(2, 3), 66.7)
        self.assertEqual(R.wr_pct(2, 3, 0), 67)
        self.assertIsNone(R.wr_pct(0, 0))

    def test_accepts_generator(self):
        self.assertEqual(R.resolved_wr(iter([{"win": 1}])), (1, 1, "100%"))


class ResolutionSelectTests(unittest.TestCase):

    def _conn(self, match_cols, part_cols):
        c = sqlite3.connect(":memory:")
        c.execute(f"CREATE TABLE matches (match_id TEXT{match_cols})")
        if part_cols is not None:
            c.execute(f"CREATE TABLE participants (match_id TEXT{part_cols})")
        return c

    def test_full_schema(self):
        c = self._conn(", game_duration_s INTEGER",
                       ", game_ended_in_early_surrender INTEGER")
        frag = R.resolution_select(c, "m")
        self.assertIn("m.game_duration_s AS game_duration_s", frag)
        self.assertIn("game_ended_in_early_surrender", frag)
        c.execute("INSERT INTO matches VALUES ('A', 200)")
        c.execute("INSERT INTO participants VALUES ('A', 1)")
        row = c.execute(f"SELECT 1 AS win{frag} FROM matches m").fetchone()
        self.assertEqual(row, (1, 200, 1))

    def test_missing_columns_degrade_to_empty(self):
        c = self._conn("", None)
        self.assertEqual(R.resolution_select(c, "m"), "")
        c2 = self._conn("", ", other INTEGER")
        self.assertEqual(R.resolution_select(c2, "m"), "")


if __name__ == "__main__":
    unittest.main()
