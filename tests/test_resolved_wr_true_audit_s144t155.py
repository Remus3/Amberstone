"""True-audit s144 cycle 155: core/resolved_wr.py hardening.

One test (or one small group) per finding, named for it. Every finding
was RED against the pre-fix module; each was mutation-probed after the
fix. The characterization block pins the well-formed path so the
hardening cannot move a resolved game in or out of the denominator.

Findings (provisional ids, the merger mints RM ids):
  RM-1917  an infinite / huge duration raised OverflowError out of
              classify() and resolved_wr(), taking the whole builder down
  RM-1918  a negative or bool duration read as a remake and dropped a
              resolved game from the denominator (NaN already fell back
              to unknown; inf is RM-1917)
  RM-1919  an unknown (0 / junk / sub-second) duration under the
              first key masked a real duration under a later key
  RM-1920  an explicit-false STRING flag ("false", "0", "no")
              for early-surrender / draft_only / result_inferred was
              truthy and dropped a resolved game ("" was already falsy;
              it is pinned here so it stays that way)
  RM-1921  a junk value under "win" masked a valid "tracked_win";
              an integral float 1.0 / 0.0 read as unknown
  RM-1922  winner_count "1" (string) read as unknown, while a bool
              True was accepted as a count of one (1.0 already passed;
              pinned here)
  RM-1923  wr_pct returned NaN (and raised at ndigits=0, so
              display_pct raised) on a NaN count, and returned
              out-of-range percents for impossible counts
  RM-1924  resolution_select interpolated an unchecked alias into SQL
"""
from __future__ import annotations

import math
import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import resolved_wr as R  # noqa: E402

CUT = R.REMAKE_MAX_SECONDS


class CharacterizationTests(unittest.TestCase):
    """Well-formed rows keep their pre-audit verdicts."""

    def test_well_formed_verdicts_unchanged(self):
        cases = [
            ({"win": 1}, "win"),
            ({"win": 0}, "loss"),
            ({"win": True, "game_duration_s": 1800}, "win"),
            ({"tracked_win": 0, "gameDuration": 1500}, "loss"),
            ({"win": "Win"}, "win"),
            ({"win": " fail "}, "loss"),
            ({"win": 1, "game_duration_s": CUT - 1}, "remake"),
            ({"win": 1, "game_duration_s": CUT}, "win"),
            ({"win": 1, "game_duration_s": 0}, "win"),
            ({"win": 1, "game_duration_s": None}, "win"),
            ({"win": 0, "game_ended_in_early_surrender": 1}, "remake"),
            ({"win": 0, "gameEndedInEarlySurrender": True}, "remake"),
            ({"win": 0, "game_ended_in_early_surrender": 0}, "loss"),
            ({"win": 1, "draft_only": 1}, "unknown"),
            ({"win": 1, "result_inferred": True}, "unknown"),
            ({"win": 1, "draft_only": 0}, "win"),
            ({"win": 1, "winner_count": 1}, "win"),
            ({"win": 1, "winner_count": 2}, "unknown"),
            ({"win": 0, "winner_count": 0}, "unknown"),
            ({"win": 2}, "unknown"),
            ({"win": "maybe"}, "unknown"),
            ({}, "unknown"),
            ({"win": None, "game_duration_s": 100}, "remake"),
        ]
        for row, want in cases:
            with self.subTest(row=row):
                self.assertEqual(R.classify(row), want)

    def test_string_duration_still_parsed(self):
        self.assertEqual(R.classify({"win": 1, "game_duration_s": "200"}),
                         "remake")
        self.assertEqual(R.classify({"win": 1, "game_duration_s": "1800"}),
                         "win")
        self.assertEqual(R.classify({"win": 1, "game_duration_s": 299.9}),
                         "remake")

    def test_wr_pct_and_display_unchanged(self):
        self.assertEqual(R.wr_pct(1, 2), 50.0)
        self.assertEqual(R.wr_pct(2, 3), 66.7)
        self.assertEqual(R.wr_pct(2, 3, 0), 67)
        self.assertEqual(R.wr_pct(1, 3, None), 100.0 / 3)
        self.assertIsNone(R.wr_pct(0, 0))
        self.assertEqual(R.wr_pct(0, 4), 0.0)
        self.assertEqual(R.wr_pct(4, 4, 0), 100)
        self.assertEqual(R.display_pct(2, 3), "67%")
        self.assertEqual(R.display_pct(0, 0), "-")

    def test_sqlite_row_still_read(self):
        c = sqlite3.connect(":memory:")
        c.row_factory = sqlite3.Row
        row = c.execute(
            "SELECT 1 AS tracked_win, 1500 AS game_duration_s,"
            " 0 AS game_ended_in_early_surrender").fetchone()
        self.assertEqual(R.classify(row), "win")
        c.close()


class DurationTests(unittest.TestCase):

    def test_t453_infinite_duration_never_raises(self):
        # Pre-fix: int(float("inf")) raised OverflowError out of classify.
        for bad in (math.inf, -math.inf, 1e400):
            with self.subTest(bad=bad):
                self.assertEqual(
                    R.classify({"win": 1, "game_duration_s": bad}), "win")
        rows = [{"win": 1, "game_duration_s": math.inf}, {"win": 0}]
        self.assertEqual(R.resolved_wr(rows), (1, 2, "50%"))

    def test_t454_junk_duration_is_unknown_not_remake(self):
        for bad in (-5, -1.0, True, math.nan, "-30", "nan", "abc", [], {}):
            with self.subTest(bad=bad):
                self.assertEqual(
                    R.classify({"win": 0, "game_duration_s": bad}), "loss")
                self.assertFalse(R.is_remake({"game_duration_s": bad}))

    def test_t455_unknown_first_key_does_not_mask_a_later_one(self):
        self.assertEqual(
            R.classify({"win": 1, "game_duration_s": 0, "gameDuration": 120}),
            "remake")
        self.assertEqual(
            R.classify({"win": 1, "game_duration_s": "junk",
                        "duration_s": 100}),
            "remake")
        self.assertEqual(
            R.classify({"win": 1, "game_duration_s": 0.5,
                        "gameDuration": 100}),
            "remake")
        # A real first value still wins over a later one.
        self.assertEqual(
            R.classify({"win": 1, "game_duration_s": 1800,
                        "gameDuration": 120}),
            "win")


class FlagTests(unittest.TestCase):

    def test_t456_explicit_false_string_flags_do_not_drop_a_game(self):
        for false_ in ("false", "False", "0", "no", "", " 0 ", 0.0, "0.0"):
            with self.subTest(flag=false_):
                self.assertEqual(
                    R.classify({"win": 1,
                                "game_ended_in_early_surrender": false_}),
                    "win")
                self.assertEqual(
                    R.classify({"win": 1, "draft_only": false_}), "win")
                self.assertEqual(
                    R.classify({"win": 0, "result_inferred": false_}), "loss")

    def test_t456_true_and_junk_flags_still_exclude(self):
        # Fail closed: only an explicitly-false value clears a flag.
        for true_ in ("true", "1", "yes", 1, True, 2, "maybe", math.nan):
            with self.subTest(flag=true_):
                self.assertEqual(
                    R.classify({"win": 1,
                                "game_ended_in_early_surrender": true_}),
                    "remake")
                self.assertEqual(
                    R.classify({"win": 1, "draft_only": true_}), "unknown")


class WinValueTests(unittest.TestCase):

    def test_t457_junk_win_does_not_mask_tracked_win(self):
        self.assertEqual(R.classify({"win": "", "tracked_win": 1}), "win")
        self.assertEqual(R.classify({"win": "maybe", "tracked_win": 0}),
                         "loss")
        # A parseable first key still wins.
        self.assertEqual(R.classify({"win": 1, "tracked_win": 0}), "win")

    def test_t457_integral_float_win(self):
        self.assertEqual(R.classify({"win": 1.0}), "win")
        self.assertEqual(R.classify({"win": 0.0}), "loss")
        for bad in (0.5, math.nan, math.inf):
            with self.subTest(bad=bad):
                self.assertEqual(R.classify({"win": bad}), "unknown")


class WinnerCountTests(unittest.TestCase):

    def test_t458_winner_count_parsed(self):
        self.assertEqual(R.classify({"win": 1, "winner_count": "1"}), "win")
        self.assertEqual(R.classify({"win": 1, "winner_count": 1.0}), "win")
        self.assertEqual(R.classify({"win": 1, "winner_count": "2"}),
                         "unknown")

    def test_t458_junk_winner_count_is_unknown(self):
        for bad in (True, False, "x", math.nan, 1.5, []):
            with self.subTest(bad=bad):
                self.assertEqual(
                    R.classify({"win": 1, "winner_count": bad}), "unknown")


class PercentTests(unittest.TestCase):

    def test_t459_non_finite_never_raises(self):
        for args in ((math.nan, 4), (1, math.nan), (math.inf, 4),
                     (1, math.inf)):
            with self.subTest(args=args):
                self.assertIsNone(R.wr_pct(*args, 0))
                self.assertIsNone(R.wr_pct(*args))
                self.assertEqual(R.display_pct(*args), "-")

    def test_t459_impossible_counts_are_none(self):
        for args in ((5, 4), (-1, 4), (1, -4), (True, 2), (1, True),
                     ("1", 2), (1.5, 3), (None, 2)):
            with self.subTest(args=args):
                self.assertIsNone(R.wr_pct(*args))
                self.assertEqual(R.display_pct(*args), "-")

    def test_t459_integral_floats_accepted(self):
        self.assertEqual(R.wr_pct(1.0, 2.0), 50.0)


class ResolutionSelectTests(unittest.TestCase):

    def _conn(self):
        c = sqlite3.connect(":memory:")
        c.execute("CREATE TABLE matches (match_id TEXT,"
                  " game_duration_s INTEGER)")
        c.execute("CREATE TABLE participants (match_id TEXT,"
                  " game_ended_in_early_surrender INTEGER)")
        return c

    def test_t460_alias_must_be_an_identifier(self):
        c = self._conn()
        for bad in ("m; DROP TABLE matches", "m.x", "", " m", "1m",
                    "m--", None, 5):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    R.resolution_select(c, bad)
        # The table survives every attempt.
        self.assertEqual(c.execute("SELECT COUNT(*) FROM matches")
                         .fetchone()[0], 0)
        c.close()

    def test_t460_identifier_aliases_still_work(self):
        c = self._conn()
        for good in ("m", "matches", "_m2"):
            with self.subTest(good=good):
                frag = R.resolution_select(c, good)
                self.assertIn(f"{good}.game_duration_s", frag)
                self.assertIn(f"px.match_id = {good}.match_id", frag)
        c.close()


if __name__ == "__main__":
    unittest.main()
