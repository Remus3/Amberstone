"""S144-D-98: ``item_resist_grants`` never credits an infinite resist from a non-finite input.

OFFLINE ONLY - no DS :8860 call, no network. The r106 / r124 / r67 / r133
tests pin the Jak'Sho / Force of Nature / Shield of Molten Stone / Cloak of
Starry Night / Terminus magnitudes at FINITE inputs only.

Defects pinned (measured before the fix):
  * Jak'Sho 6665 (percent of BONUS) at ``total_armor=inf`` or
    ``base_armor=-inf`` credited INFINITE bonus armor into
    ``ehp.compute_ehp``'s ``eff_armor``;
  * Shield of Molten Stone 443058 / Cloak of Starry Night 443059 (percent of
    TOTAL) at an infinite total did the same on their axis.

Contract (the S144-D-97 rule, applied to the item twin of the rune lane): a
non-finite resist makes the PERCENT term unusable, so it reads 0.0 and the flat
term stands alone - the result a NaN resist already produced through the
``max(0.0, nan)`` clamp. The ``level`` clamp in ``_value_at_level`` is NOT
touched - that is the RM-848 Tier-2 family. Finite inputs are unchanged -
pinned by the reference values below, which are the pre-fix outputs.
"""

from __future__ import annotations

import math
import unittest

from agents.daemon_slayer._item_resist_grants import item_resist_grants

_INF = float("inf")
_NAN = float("nan")
_NON_FINITE = (_INF, -_INF, _NAN)
_KW = dict(total_armor=100.0, total_mr=80.0, base_armor=50.0, base_mr=40.0, level=18)


def _grant(item_ids, **overrides):
    return item_resist_grants(item_ids, **{**_KW, **overrides})


class BonusPercentNonFiniteTests(unittest.TestCase):
    def test_infinite_total_armor_is_finite(self) -> None:
        armor, mr = _grant(["6665"], total_armor=_INF)
        self.assertEqual(armor, 0.0)
        self.assertAlmostEqual(mr, 40.0 * 0.30 * 0.5)

    def test_negative_infinite_base_is_finite(self) -> None:
        armor, mr = _grant(["6665"], base_armor=-_INF, base_mr=-_INF)
        self.assertEqual((armor, mr), (0.0, 0.0))

    def test_every_non_finite_resist_is_finite(self) -> None:
        for field in ("total_armor", "total_mr", "base_armor", "base_mr"):
            for value in _NON_FINITE:
                with self.subTest(field=field, value=value):
                    armor, mr = _grant(["6665"], **{field: value})
                    self.assertTrue(math.isfinite(armor))
                    self.assertTrue(math.isfinite(mr))


class TotalPercentNonFiniteTests(unittest.TestCase):
    def test_molten_stone_infinite_total_armor_reads_zero(self) -> None:
        self.assertEqual(_grant(["443058"], total_armor=_INF), (0.0, 0.0))

    def test_starry_night_infinite_total_mr_reads_zero(self) -> None:
        self.assertEqual(_grant(["443059"], total_mr=_INF), (0.0, 0.0))

    def test_flat_term_survives_a_non_finite_pool(self) -> None:
        for value in _NON_FINITE:
            with self.subTest(value=value):
                self.assertEqual(
                    _grant(["4401", "3302"], total_mr=value, total_armor=value),
                    (24.0, 35.0 + 24.0),
                )


class FiniteParityTests(unittest.TestCase):
    """Pre-fix outputs at finite inputs - the fix must not move them."""

    def test_reference_values(self) -> None:
        self.assertEqual(_grant(["6665"]), (7.5, 6.0))
        self.assertEqual(_grant(["443058"]), (20.0, 0.0))
        self.assertEqual(_grant(["443059"]), (0.0, 16.0))
        self.assertEqual(_grant(["4401"]), (0.0, 35.0))
        self.assertEqual(_grant(["3302"], level=12), (21.0, 21.0))

    def test_below_base_build_still_clamps_to_zero(self) -> None:
        self.assertEqual(_grant(["6665"], total_armor=10.0, total_mr=10.0), (0.0, 0.0))


if __name__ == "__main__":
    unittest.main()
