"""S144-D-92: pin ``_rune_self_heal._coerce_share`` directly.

OFFLINE ONLY - no DS :8860 call, no network. Before this file the coercer was
reached only through ``second_wind_heal`` at -0.5 and 4.0; nothing named it,
and a NaN share was never fed in.

Defect pinned: ``max(0.0, min(1.0, nan))`` is 1.0, because ``min`` and ``max``
keep their first argument when the comparison with NaN is False. So a NaN
missing-health share became the MAXIMUM share and Second Wind was credited as
if the wielder were at zero health - the opposite of the module's fail-soft
contract ("a below-zero share would invert the heal ... clamped rather than
raising"; non-numeric input returns 0.0). A NaN share is now unusable input and
coerces to 0.0, the same as a non-numeric one. Every finite input, and the
documented clamp of +/-inf into [0.0, 1.0], is unchanged.
"""

from __future__ import annotations

import math
import unittest

from agents.daemon_slayer._rune_self_heal import (
    _coerce_share,
    second_wind_heal,
    sum_rune_self_heal,
)

_NAN = float("nan")
_INF = float("inf")


class CoerceShareTests(unittest.TestCase):
    def test_in_range_values_pass_through(self):
        for value in (0.0, 0.25, 0.5, 1.0):
            self.assertEqual(_coerce_share(value), value)

    def test_int_is_converted_to_float(self):
        self.assertIsInstance(_coerce_share(1), float)
        self.assertEqual(_coerce_share(0), 0.0)

    def test_numeric_string_is_accepted(self):
        self.assertEqual(_coerce_share("0.5"), 0.5)

    def test_below_zero_clamps_to_zero(self):
        self.assertEqual(_coerce_share(-0.5), 0.0)
        self.assertEqual(_coerce_share(-_INF), 0.0)

    def test_above_one_clamps_to_one(self):
        self.assertEqual(_coerce_share(4.0), 1.0)
        self.assertEqual(_coerce_share(_INF), 1.0)

    def test_non_numeric_is_zero(self):
        for value in (None, "lots", [], {}, object()):
            self.assertEqual(_coerce_share(value), 0.0, repr(value))

    def test_nan_is_zero_not_the_maximum_share(self):
        self.assertEqual(_coerce_share(_NAN), 0.0)

    def test_nan_string_is_zero(self):
        self.assertEqual(_coerce_share("nan"), 0.0)

    def test_result_is_always_finite_and_in_unit_interval(self):
        for value in (_NAN, _INF, -_INF, -1.0, 0.3, 2.0, "nan", None):
            got = _coerce_share(value)
            self.assertTrue(math.isfinite(got), repr(value))
            self.assertGreaterEqual(got, 0.0)
            self.assertLessEqual(got, 1.0)


class NanShareReachesNoCreditTests(unittest.TestCase):
    """The public entry points inherit the coercer, so a NaN share credits 0."""

    def test_second_wind_heal_nan_share_is_zero(self):
        self.assertEqual(
            second_wind_heal(max_health=1000.0, missing_hp_share=_NAN), 0.0
        )

    def test_sum_rune_self_heal_nan_share_is_zero(self):
        self.assertEqual(
            sum_rune_self_heal(["8444"], max_health=1000.0, missing_hp_share=_NAN),
            0.0,
        )

    def test_nan_share_is_not_the_full_missing_health_credit(self):
        full = second_wind_heal(max_health=1000.0, missing_hp_share=1.0)
        self.assertGreater(full, 0.0)
        self.assertNotEqual(
            second_wind_heal(max_health=1000.0, missing_hp_share=_NAN), full
        )


if __name__ == "__main__":
    unittest.main()
