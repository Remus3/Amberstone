"""Tests for ``core.draft_elo`` (pure math) + ``core.draft_elo_db``
(rewind_history.db queries).

The route layer is covered separately by tests/test_routes_draft_elo.py.
"""
from __future__ import annotations

import math
import sqlite3
import unittest

from core import draft_elo, draft_elo_db
from tests._draft_elo_fixture import DraftEloFixture


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


class TopContributionsTests(unittest.TestCase):
    """top_contributions: signed delta + sort by abs(delta).

    Sign convention (ally-team perspective):
      ally-pair  delta = +rating
      enemy-pair delta = -rating  (positive enemy rating SUBTRACTS from
                                   team_score, so it shows as negative)
      matchup    delta = +rating
    """

    def test_ally_pair_positive_rating_helps_ally(self):
        c = draft_elo.top_contributions(
            ally_pairs=[(1, 2)],
            enemy_pairs=[],
            matchup_cross=[],
            ally_pair_ratings=(50.0,),
            enemy_pair_ratings=(),
            matchup_ratings=(),
            ally_pair_counts=[10],
            enemy_pair_counts=[],
            matchup_counts=[],
        )
        self.assertEqual(len(c), 1)
        self.assertEqual(c[0].kind, "ally-pair")
        self.assertEqual(c[0].a, 1)
        self.assertEqual(c[0].b, 2)
        self.assertEqual(c[0].delta, 50.0)
        self.assertEqual(c[0].n, 10)

    def test_enemy_pair_positive_rating_hurts_ally(self):
        """Enemy team's positive rating subtracts from team_score - the
        contribution delta is the FLIPPED sign so the hover row reads
        as a negative for ally."""
        c = draft_elo.top_contributions(
            ally_pairs=[],
            enemy_pairs=[(3, 4)],
            matchup_cross=[],
            ally_pair_ratings=(),
            enemy_pair_ratings=(80.0,),
            matchup_ratings=(),
            ally_pair_counts=[],
            enemy_pair_counts=[7],
            matchup_counts=[],
        )
        self.assertEqual(len(c), 1)
        self.assertEqual(c[0].kind, "enemy-pair")
        self.assertEqual(c[0].delta, -80.0)
        self.assertEqual(c[0].n, 7)

    def test_matchup_rating_credit_ally(self):
        c = draft_elo.top_contributions(
            ally_pairs=[],
            enemy_pairs=[],
            matchup_cross=[(1, 10)],
            ally_pair_ratings=(),
            enemy_pair_ratings=(),
            matchup_ratings=(25.0,),
            ally_pair_counts=[],
            enemy_pair_counts=[],
            matchup_counts=[42],
        )
        self.assertEqual(len(c), 1)
        self.assertEqual(c[0].kind, "matchup")
        self.assertEqual(c[0].a, 1)
        self.assertEqual(c[0].b, 10)
        self.assertEqual(c[0].delta, 25.0)
        self.assertEqual(c[0].n, 42)

    def test_sort_by_abs_delta_descending(self):
        """Mixed kinds - the top entry is the LARGEST absolute delta
        regardless of sign or source kind."""
        c = draft_elo.top_contributions(
            ally_pairs=[(1, 2), (3, 4)],
            enemy_pairs=[(5, 6)],
            matchup_cross=[(7, 8)],
            # ally-pair (1,2) delta=+10 ; (3,4) delta=+100
            # enemy-pair (5,6) delta=-30
            # matchup (7,8) delta=-50
            # Expected sort by abs: (3,4)=100, (7,8)=50, (5,6)=30, (1,2)=10
            ally_pair_ratings=(10.0, 100.0),
            enemy_pair_ratings=(30.0,),
            matchup_ratings=(-50.0,),
            ally_pair_counts=[1, 2],
            enemy_pair_counts=[3],
            matchup_counts=[4],
            limit=10,
        )
        self.assertEqual(len(c), 4)
        self.assertEqual(c[0].a, 3)
        self.assertEqual(c[0].b, 4)
        self.assertEqual(c[0].delta, 100.0)
        self.assertEqual(c[1].kind, "matchup")
        self.assertEqual(abs(c[1].delta), 50.0)
        self.assertEqual(c[2].kind, "enemy-pair")
        self.assertEqual(abs(c[2].delta), 30.0)
        self.assertEqual(c[3].delta, 10.0)

    def test_top_3_limit(self):
        """Default limit=3. Caller passes 5 entries -> returns top 3."""
        c = draft_elo.top_contributions(
            ally_pairs=[(1, 2), (3, 4), (5, 6), (7, 8), (9, 10)],
            enemy_pairs=[],
            matchup_cross=[],
            ally_pair_ratings=(10.0, 20.0, 30.0, 40.0, 50.0),
            enemy_pair_ratings=(),
            matchup_ratings=(),
            ally_pair_counts=[1] * 5,
            enemy_pair_counts=[],
            matchup_counts=[],
        )
        self.assertEqual(len(c), 3)
        self.assertEqual(c[0].delta, 50.0)
        self.assertEqual(c[1].delta, 40.0)
        self.assertEqual(c[2].delta, 30.0)

    def test_limit_zero_returns_all(self):
        c = draft_elo.top_contributions(
            ally_pairs=[(1, 2), (3, 4)],
            enemy_pairs=[],
            matchup_cross=[],
            ally_pair_ratings=(10.0, 20.0),
            enemy_pair_ratings=(),
            matchup_ratings=(),
            ally_pair_counts=[1, 1],
            enemy_pair_counts=[],
            matchup_counts=[],
            limit=0,
        )
        self.assertEqual(len(c), 2)

    def test_empty_input_returns_empty_list(self):
        c = draft_elo.top_contributions(
            ally_pairs=[],
            enemy_pairs=[],
            matchup_cross=[],
            ally_pair_ratings=(),
            enemy_pair_ratings=(),
            matchup_ratings=(),
            ally_pair_counts=[],
            enemy_pair_counts=[],
            matchup_counts=[],
        )
        self.assertEqual(c, [])

    def test_length_mismatch_silently_zips_shortest(self):
        """Defensive: a future schema drift that passes shorter counts
        than ratings should not crash - zip stops at shortest."""
        c = draft_elo.top_contributions(
            ally_pairs=[(1, 2), (3, 4)],
            enemy_pairs=[],
            matchup_cross=[],
            ally_pair_ratings=(10.0, 20.0),
            enemy_pair_ratings=(),
            matchup_ratings=(),
            ally_pair_counts=[5],  # shorter than ratings
            enemy_pair_counts=[],
            matchup_counts=[],
            limit=10,
        )
        # Only the entry that matches all 3 inputs survives.
        self.assertEqual(len(c), 1)
        self.assertEqual(c[0].a, 1)

    def test_contribution_dataclass_is_frozen(self):
        """The Contribution dataclass is frozen for safe pass-through to
        the JSON layer."""
        import dataclasses
        c = draft_elo.Contribution(
            kind="ally-pair", a=1, b=2, delta=10.0, n=5,
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            c.delta = 999.0  # frozen dataclass refuses mutation


class DraftEloDbReadOnlyTests(unittest.TestCase):
    """Smoke tests against a self-contained rewind_history fixture DB.

    The fixture (tests/_draft_elo_fixture.py) carries the matches +
    participants schema + a small deterministic seed, so these tests run
    without the gitignored live DB. They verify the SQL is well-formed and
    the smoothed rates fall in (0, 1); specific WR values are NOT pinned.
    """

    @classmethod
    def setUpClass(cls):
        # Self-contained fixture DB (the live rewind_history.db is
        # gitignored / absent on a clean checkout). open_ro() honors the
        # RC_REWIND_DB override the fixture sets.
        cls._fix = DraftEloFixture()
        cls._fix.start()
        cls.conn = draft_elo_db.open_ro()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.conn.close()
        except Exception:
            pass
        cls._fix.stop()

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
