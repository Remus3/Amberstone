"""S144-D-93: pin ``_rune_self_heal._coerce_pool`` directly.

OFFLINE ONLY - no DS :8860 call, no network. Before this file the coercer was
reached only through the public functions at None, -500 and "lots"; nothing
named it, and no non-finite pool was ever fed in.

Defect pinned: ``_coerce_pool`` promises "a non-negative float, or 0.0 if
unusable", but ``max(0.0, float(inf))`` is inf. An infinite pool made
``second_wind_heal`` return inf, and with a zero missing share it returned NaN
(``inf * 0.0``) - a NaN EHP numerator term that would poison every comparison
downstream. A non-finite pool is now unusable input and coerces to 0.0. NaN
already coerced to 0.0 (``max`` keeps its first argument against NaN); that is
pinned here so a reordering of the ``max`` arguments cannot regress it. Every
finite input is unchanged.
"""

from __future__ import annotations

import math
import unittest

from agents.daemon_slayer._rune_self_heal import (
    _coerce_pool,
    second_wind_heal,
    sum_rune_self_heal,
)

_NAN = float("nan")
_INF = float("inf")


class CoercePoolTests(unittest.TestCase):
    def test_positive_values_pass_through(self):
        for value in (0.0, 1.0, 2500.0, 1e6):
            self.assertEqual(_coerce_pool(value), value)

    def test_int_is_converted_to_float(self):
        self.assertIsInstance(_coerce_pool(3000), float)
        self.assertEqual(_coerce_pool(3000), 3000.0)

    def test_numeric_string_is_accepted(self):
        self.assertEqual(_coerce_pool("1500"), 1500.0)

    def test_negative_clamps_to_zero(self):
        self.assertEqual(_coerce_pool(-500.0), 0.0)
        self.assertEqual(_coerce_pool(-_INF), 0.0)

    def test_non_numeric_is_zero(self):
        for value in (None, "lots", [], {}, object()):
            self.assertEqual(_coerce_pool(value), 0.0, repr(value))

    def test_nan_is_zero(self):
        self.assertEqual(_coerce_pool(_NAN), 0.0)
        self.assertEqual(_coerce_pool("nan"), 0.0)

    def test_positive_infinity_is_unusable_and_zero(self):
        self.assertEqual(_coerce_pool(_INF), 0.0)
        self.assertEqual(_coerce_pool("inf"), 0.0)

    def test_result_is_always_finite_and_non_negative(self):
        for value in (_NAN, _INF, -_INF, -1.0, 10.0, "inf", None):
            got = _coerce_pool(value)
            self.assertTrue(math.isfinite(got), repr(value))
            self.assertGreaterEqual(got, 0.0)


class NonFinitePoolReachesNoCreditTests(unittest.TestCase):
    def test_second_wind_heal_infinite_pool_is_zero(self):
        self.assertEqual(second_wind_heal(max_health=_INF), 0.0)

    def test_infinite_pool_with_zero_share_is_zero_not_nan(self):
        got = second_wind_heal(max_health=_INF, missing_hp_share=0.0)
        self.assertFalse(math.isnan(got))
        self.assertEqual(got, 0.0)

    def test_sum_rune_self_heal_infinite_pool_is_zero(self):
        self.assertEqual(sum_rune_self_heal(["8444"], max_health=_INF), 0.0)

    def test_sum_rune_self_heal_nan_pool_is_zero(self):
        self.assertEqual(sum_rune_self_heal(["8444"], max_health=_NAN), 0.0)

    def test_finite_pool_value_is_unchanged(self):
        # 0.04 * 3000 * 0.5 * (6 / 10) = 36.0, the r142 hand-computed pair.
        self.assertAlmostEqual(
            second_wind_heal(max_health=3000.0, missing_hp_share=0.5), 36.0
        )


if __name__ == "__main__":
    unittest.main()
