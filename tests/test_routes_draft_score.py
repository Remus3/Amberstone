"""Tests for the /api/draft-score route helpers - specifically the DS
spike-derived scaling resolver that activates the (previously inert) scaling
layer. The pure _peak_timing math is covered deterministically here (no DS
engine needed); the _SpikeScalingResolver fail-soft contract is covered with a
bad champion id so the layer degrades rather than raising.
"""
from __future__ import annotations

import unittest

from dashboard import routes_draft_score as rds


class TestPeakTiming(unittest.TestCase):
    def test_empty_or_none_is_none(self):
        self.assertIsNone(rds._peak_timing(None))
        self.assertIsNone(rds._peak_timing([]))

    def test_all_zero_curve_is_none(self):
        self.assertIsNone(rds._peak_timing([0.0] * 41))

    def test_early_crossing_reads_low(self):
        # crosses 70% of max at index 4 of 41 -> 4/40 = 0.1
        curve = [0.8] + [1.0] * 40   # max 1.0, index 0 already >= 0.7
        self.assertAlmostEqual(rds._peak_timing(curve), 0.0)

    def test_mid_crossing_normalizes_to_fraction(self):
        # linear 0..1 over 41 points; 70% of max(1.0)=0.7 first at index 29
        curve = [i / 40 for i in range(41)]
        # index 28 -> 0.700 is the first entry >= 0.7 (threshold = max*0.70)
        self.assertAlmostEqual(rds._peak_timing(curve), 28 / 40)

    def test_late_only_crossing_reads_high(self):
        # power flat-low then a single late spike at the last index
        curve = [0.1] * 40 + [1.0]
        self.assertAlmostEqual(rds._peak_timing(curve), 1.0)

    def test_threshold_is_relative_to_own_max(self):
        # scaling the whole curve does not move the crossing fraction
        base = [i / 40 for i in range(41)]
        scaled = [v * 1000 for v in base]
        self.assertEqual(rds._peak_timing(base), rds._peak_timing(scaled))


class TestSpikeScalingResolver(unittest.TestCase):
    def test_default_resolver_is_callable(self):
        r = rds._default_scaling_resolver()
        self.assertTrue(callable(r))

    def test_unknown_champ_id_returns_none_not_raise(self):
        # A champ id absent from the DDragon map must fail soft to None so the
        # scaling layer drops that champ instead of raising.
        r = rds._default_scaling_resolver()
        self.assertIsNone(r(999999999))

    def test_resolver_never_raises_on_garbage(self):
        r = rds._default_scaling_resolver()
        for bad in (None, "not-an-int", -1, 0):
            self.assertIsNone(r(bad))


if __name__ == "__main__":
    unittest.main()
