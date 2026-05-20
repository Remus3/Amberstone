"""Tests for ``core.draft_elo`` (pure math) + ``core.draft_elo_db``
(rewind_history.db queries).

The route layer is covered separately by tests/test_routes_draft_elo.py.
"""
from __future__ import annotations

import math
import sqlite3
import unittest

from core import draft_elo, draft_elo_db


class WinrateRatingRoundTripTests(unittest.TestCase):
    """Identity: rating_to_winrate(winrate_to_rating(wr)) == wr."""

    def test_round_trip_at_0_5(self):
        r = draft_elo.winrate_to_rating(0.5)
        self.assertAlmostEqual(r, 0.0, places=9)
        self.assertAlmostEqual(draft_elo.rating_to_winrate(0.0), 0.5, places=9)

    def test_round_trip_across_range(self):
        for wr in (0.10, 0.25, 0.40, 0.55, 0.65, 0.80, 0.90):
            rating = draft_elo.winrate_to_rating(wr)
            wr2 = draft_elo.rating_to_winrate(rating)
            self.assertAlmostEqual(wr, wr2, places=6, msg=f"wr={wr}")

    def test_above_50_is_positive_rating(self):
        self.assertGreater(draft_elo.winrate_to_rating(0.55), 0)
        self.assertGreater(draft_elo.winrate_to_rating(0.99), 0)

    def test_below_50_is_negative_rating(self):
        self.assertLess(draft_elo.winrate_to_rating(0.45), 0)
        self.assertLess(draft_elo.winrate_to_rating(0.01), 0)

    def test_extreme_inputs_clamped(self):
        """1.0 / 0.0 inputs are clamped to (eps, 1-eps) so the log
        doesn't blow up. Result should be finite + saturating."""
        r_one = draft_elo.winrate_to_rating(1.0)
        r_zero = draft_elo.winrate_to_rating(0.0)
        self.assertTrue(math.isfinite(r_one))
        self.assertTrue(math.isfinite(r_zero))
        self.assertGreater(r_one, 0)
        self.assertLess(r_zero, 0)

    def test_known_value_55_pct(self):
        """55% winrate per the chess-scale convention: ~35 rating points."""
        r = draft_elo.winrate_to_rating(0.55)
        self.assertAlmostEqual(r, 34.91, delta=0.1)


class TeamScoreTests(unittest.TestCase):
    """Aggregate behavior of DraftSide + team_score."""

    def _balanced_side(self) -> draft_elo.DraftSide:
        return draft_elo.DraftSide(
            champ_ratings=(0.0,) * 5,
            pair_ratings=(0.0,) * 10,
            matchup_ratings=(0.0,) * 25,
        )

    def test_balanced_teams_score_zero(self):
        ally = self._balanced_side()
        enemy = draft_elo.DraftSide(
            champ_ratings=(0.0,) * 5,
            pair_ratings=(0.0,) * 10,
        )
        self.assertEqual(draft_elo.team_score(ally, enemy), 0.0)
        self.assertAlmostEqual(draft_elo.draft_winrate(ally, enemy), 0.5)

    def test_ally_above_enemy_pushes_winrate_above_50(self):
        ally = draft_elo.DraftSide(
            champ_ratings=(50.0,) * 5,
            pair_ratings=(0.0,) * 10,
            matchup_ratings=(0.0,) * 25,
        )
        enemy = draft_elo.DraftSide(
            champ_ratings=(0.0,) * 5,
            pair_ratings=(0.0,) * 10,
        )
        score = draft_elo.team_score(ally, enemy)
        self.assertEqual(score, 250.0)
        wr = draft_elo.draft_winrate(ally, enemy)
        self.assertGreater(wr, 0.5)

    def test_matchup_ratings_only_credit_ally(self):
        """Matchups are accrued ally-side, NOT subtracted on enemy."""
        ally = draft_elo.DraftSide(
            champ_ratings=(0.0,) * 5,
            pair_ratings=(0.0,) * 10,
            matchup_ratings=(20.0,) * 25,  # +500 ally rating
        )
        enemy = draft_elo.DraftSide(
            champ_ratings=(0.0,) * 5,
            pair_ratings=(0.0,) * 10,
        )
        self.assertEqual(draft_elo.team_score(ally, enemy), 500.0)


class PairEnumerationTests(unittest.TestCase):
    def test_unordered_pairs_count(self):
        ids = (1, 2, 3, 4, 5)
        pairs = draft_elo.unordered_pairs(ids)
        self.assertEqual(len(pairs), 10)
        # No (a, a); ascending order within each pair.
        for a, b in pairs:
            self.assertLess(a, b)

    def test_unordered_pairs_deterministic_swap(self):
        """If the input list is reordered, the pairs are still keyed
        on the same (lower, higher) form."""
        a = draft_elo.unordered_pairs((1, 2, 3))
        b = draft_elo.unordered_pairs((3, 2, 1))
        self.assertEqual(sorted(a), sorted(b))

    def test_cross_pairs_count(self):
        ally = (1, 2, 3, 4, 5)
        enemy = (10, 20, 30, 40, 50)
        cross = draft_elo.cross_pairs(ally, enemy)
        self.assertEqual(len(cross), 25)
        # Each pair carries (ally, enemy) order.
        self.assertEqual(cross[0], (1, 10))
        self.assertEqual(cross[-1], (5, 50))


class SmoothedRatesCompositionTests(unittest.TestCase):
    """Verify the algorithm composes on smoothed_rates rather than
    duplicating it: an unseen pair (games=0) returns 0.5 -> rating 0."""

    def test_zero_games_pair_is_neutral(self):
        from core import smoothed_rates
        rate = smoothed_rates.laplace_rate(0, 0)
        self.assertEqual(rate, 0.5)
        self.assertEqual(draft_elo.winrate_to_rating(rate), 0.0)


class DraftEloDbReadOnlyTests(unittest.TestCase):
    """Live-data smoke tests against rewind_history.db.

    rewind_history.db is read-only; these tests verify the SQL is well-
    formed and the smoothed rates fall in (0, 1). Specific WR values
    are NOT pinned (snapshot drifts over time).
    """

    @classmethod
    def setUpClass(cls):
        cls.conn = draft_elo_db.open_ro()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.conn.close()
        except Exception:
            pass

    def test_solo_winrate_runs(self):
        wins, games, rate = draft_elo_db.solo_winrate(self.conn, 64)  # Lee Sin
        self.assertGreaterEqual(games, 0)
        self.assertGreaterEqual(wins, 0)
        self.assertGreater(rate, 0.0)
        self.assertLess(rate, 1.0)

    def test_solo_unseen_champ_is_neutral(self):
        # 9999 is not a valid champion id; smoothed rate should pin 0.5.
        _, games, rate = draft_elo_db.solo_winrate(self.conn, 9999)
        self.assertEqual(games, 0)
        self.assertEqual(rate, 0.5)

    def test_pair_winrate_runs(self):
        _, games, rate = draft_elo_db.pair_winrate(self.conn, 64, 22)
        self.assertGreaterEqual(games, 0)
        self.assertGreater(rate, 0.0)
        self.assertLess(rate, 1.0)

    def test_pair_self_pair_is_zero_games(self):
        """A 'pair' of the same champion id has zero rows in the
        cross-table (same participant can't appear twice in one match)."""
        _, games, rate = draft_elo_db.pair_winrate(self.conn, 64, 64, side="ally")
        self.assertEqual(games, 0)
        self.assertEqual(rate, 0.5)

    def test_matchup_winrate_runs(self):
        _, games, rate = draft_elo_db.matchup_winrate(self.conn, 64, 22)
        self.assertGreaterEqual(games, 0)
        self.assertGreater(rate, 0.0)
        self.assertLess(rate, 1.0)

    def test_queue_filter_narrows_results(self):
        _, games_all, _ = draft_elo_db.solo_winrate(self.conn, 64)
        _, games_q420, _ = draft_elo_db.solo_winrate(
            self.conn, 64, queue_ids=[420],
        )
        # ranked solo/duo is a subset of the SR set.
        self.assertLessEqual(games_q420, games_all)


if __name__ == "__main__":
    unittest.main()
