"""tests/test_smoothed_rates.py - CLAUDE.md #90 decision (2).

Unit + parity coverage for the shared smoothed-rate primitive
(`core/smoothed_rates.py`): Laplace/Beta-smoothed success rate,
n/(n+K) shrinkage, and the convex external-seed blend.

The parity block pins the exact numeric vectors that
`tests/test_augment_recommender.py` asserts, so the extraction of the
inline `_own_wr` / `_pair_wr` / `w = n/(n+k)` / `base = w*own +
(1-w)*ext` math from `core/augment_recommender.py` onto this module is
provably byte-identical (same formulas, same guards).
"""
import sys
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from core import smoothed_rates as S


class LaplaceRateTests(unittest.TestCase):
    def test_basic_smoothing(self):
        # (1 + 1) / (4 + 2*1) = 2/6 - the test_augment_recommender anchor.
        self.assertAlmostEqual(S.laplace_rate(1, 4, 1.0), 2 / 6)

    def test_default_alpha_is_one(self):
        self.assertEqual(S.laplace_rate(1, 4), S.laplace_rate(1, 4, 1.0))

    def test_unseen_is_neutral_half(self):
        # (0 + 1) / (0 + 2) = 0.5 - unseen augment -> neutral baseline.
        self.assertAlmostEqual(S.laplace_rate(0, 0, 1.0), 0.5)

    def test_pair_anchor(self):
        # _pair_wr anchor: (2 + 1) / (2 + 2) = 3/4. Beta == Laplace on
        # pair counts; one primitive serves both.
        self.assertAlmostEqual(S.laplace_rate(2, 2, 1.0), 0.75)

    def test_all_wins_pulled_toward_half(self):
        # (5 + 1) / (5 + 2) = 6/7 - the BlendRegime w_mid own_wr anchor.
        self.assertAlmostEqual(S.laplace_rate(5, 5, 1.0), 6 / 7)

    def test_large_sample_pulled_less(self):
        self.assertAlmostEqual(S.laplace_rate(50, 50, 1.0), 51 / 52)

    def test_zero_winrate(self):
        self.assertAlmostEqual(S.laplace_rate(0, 4, 1.0), 1 / 6)

    def test_custom_alpha_strength(self):
        # Larger alpha -> stronger pull toward 0.5.
        weak = S.laplace_rate(8, 10, 0.5)
        strong = S.laplace_rate(8, 10, 10.0)
        self.assertGreater(weak, strong)
        self.assertAlmostEqual(S.laplace_rate(8, 10, 0.5), 8.5 / 11.0)

    def test_nonpositive_denominator_guards_to_half(self):
        # games + 2*alpha <= 0 is unreachable from any RC caller (all
        # pass alpha=1.0 so denom >= 2). The guard makes the primitive
        # safe rather than crashing; it never changes a reachable result.
        self.assertEqual(S.laplace_rate(0, 0, 0.0), 0.5)
        self.assertEqual(S.laplace_rate(3, -10, 1.0), 0.5)

    def test_alpha_one_makes_guard_unreachable(self):
        # Proof for the byte-identical extraction claim: with alpha=1.0
        # denom = games + 2 >= 2 for any games >= 0, so the guard branch
        # never fires for real callers.
        for g in range(0, 200):
            self.assertGreater(g + 2 * 1.0, 0)
            self.assertAlmostEqual(
                S.laplace_rate(0, g, 1.0), 1.0 / (g + 2.0)
            )


class ShrinkTests(unittest.TestCase):
    def test_basic(self):
        # 2 / (2 + 5) = 2/7 - the Synergy shrink anchor.
        self.assertAlmostEqual(S.shrink(2, 5), 2 / 7)

    def test_default_k_is_five(self):
        self.assertEqual(S.shrink(2), S.shrink(2, 5.0))

    def test_zero_n_is_zero(self):
        # n_own = 0 -> w = 0 -> pure external prior.
        self.assertEqual(S.shrink(0, 5), 0.0)

    def test_midpoint(self):
        # 5 / (5 + 5) = 0.5 - the BlendRegime w_mid blend weight.
        self.assertAlmostEqual(S.shrink(5, 5), 0.5)

    def test_large_n_approaches_one(self):
        self.assertGreater(S.shrink(50, 5), 0.9)
        self.assertAlmostEqual(S.shrink(50, 5), 50 / 55)

    def test_nonpositive_denominator_guards_to_zero(self):
        # Mirrors the original `if (n + k) > 0 else 0.0` exactly: strict
        # > 0, so n+k == 0 also yields 0.0.
        self.assertEqual(S.shrink(0, 0), 0.0)
        self.assertEqual(S.shrink(2, -2), 0.0)
        self.assertEqual(S.shrink(-5, 5), 0.0)

    def test_monotonic_in_n(self):
        prev = -1.0
        for n in range(0, 100):
            cur = S.shrink(n, 5)
            self.assertGreaterEqual(cur, prev)
            prev = cur


class BlendTests(unittest.TestCase):
    def test_weight_zero_is_pure_prior(self):
        self.assertAlmostEqual(S.blend(0.9, 0.40, 0.0), 0.40)

    def test_weight_one_is_pure_own(self):
        self.assertAlmostEqual(S.blend(0.9, 0.40, 1.0), 0.9)

    def test_midpoint_blend(self):
        # The BlendRegime w_mid score: 0.5*(6/7) + 0.5*0.5.
        self.assertAlmostEqual(
            S.blend(6 / 7, 0.5, 0.5), 0.5 * (6 / 7) + 0.5 * 0.5
        )

    def test_convex_combination_bounds(self):
        for w in (0.0, 0.25, 0.5, 0.75, 1.0):
            v = S.blend(0.8, 0.2, w)
            self.assertGreaterEqual(v, 0.2)
            self.assertLessEqual(v, 0.8)


class AugmentRecommenderParityTests(unittest.TestCase):
    """End-to-end vector parity with the exact arithmetic
    tests/test_augment_recommender.py pins, so the refactor cannot
    silently shift the recommender's output."""

    def test_w_zero_regime(self):
        # n_own=0 -> w=0 -> score == ext_wr (test_w_zero_is_pure_external).
        w = S.shrink(0, 5.0)
        own = S.laplace_rate(0, 0, 1.0)
        self.assertEqual(w, 0.0)
        self.assertAlmostEqual(S.blend(own, 0.70, w), 0.70)

    def test_w_mid_regime(self):
        # games=5 all wins, ext=0.5 (test_w_mid_blends).
        own = S.laplace_rate(5, 5, 1.0)
        w = S.shrink(5, 5.0)
        self.assertAlmostEqual(own, 6 / 7)
        self.assertAlmostEqual(w, 0.5)
        self.assertAlmostEqual(
            S.blend(own, 0.50, w), 0.5 * (6 / 7) + 0.5 * 0.5
        )

    def test_w_to_one_regime(self):
        # games=50 all wins, ext=0.10 (test_w_to_one_own_dominates).
        own = S.laplace_rate(50, 50, 1.0)
        w = S.shrink(50, 5.0)
        self.assertGreater(w, 0.9)
        self.assertGreater(S.blend(own, 0.10, w), 0.88)

    def test_greedy_synergy_vector(self):
        # test_greedy_synergy_shrunk_and_signed:
        #   own_wr(A) = (2+1)/(4+2) = 0.5
        #   pair_wr   = (2+1)/(2+2) = 0.75 ; m = 2
        #   shrink    = 2/(2+5)
        #   contrib   = shrink * (pair_wr - own_wr)
        own = S.laplace_rate(2, 4, 1.0)
        pair = S.laplace_rate(2, 2, 1.0)
        sh = S.shrink(2, 5.0)
        self.assertAlmostEqual(own, 0.5)
        self.assertAlmostEqual(pair, 0.75)
        self.assertAlmostEqual(sh * (pair - own), (2 / 7) * (0.75 - 0.5))


if __name__ == "__main__":
    unittest.main()
