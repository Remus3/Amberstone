"""S144-D-95: ``_rune_health_grants`` never credits inf / NaN or raises on a non-finite input.

OFFLINE ONLY - no DS :8860 call, no network. The r136 tests pin the DDragon
magnitudes, the quantized block, the one-shot threshold and the ranged factor at
FINITE inputs only; no test ever handed these helpers inf.

Defects pinned (measured before the fix):
  * ``overgrowth_hp_for_absorbed(inf, 1000.0)`` RAISED OverflowError
    (``math.floor(inf / 8)``);
  * ``grasp_heal_hp(0.0, inf)`` returned NaN (``inf * 0.0``);
  * ``grasp_heal_hp(inf, 1000.0)``, ``grasp_permanent_hp(inf)`` and
    ``overgrowth_hp_for_absorbed(120.0, inf)`` returned inf;
  * ``rune_health_grants(..., max_hp=inf)`` returned ``(inf, inf)``, which the
    only production caller (``ehp.compute_ehp``, DEFAULT-OFF
    ``apply_rune_health_grants`` seam) would fold straight into every EHP
    numerator.

Contract (the S144-D-93 ``_rune_self_heal._coerce_pool`` rule, applied to the
numerator twin): a non-finite stack count or pool is UNUSABLE and resolves to
0.0, exactly as NaN already did. Finite inputs are unchanged - pinned by the
reference values below, which are the pre-fix outputs.
"""

from __future__ import annotations

import math
import unittest

from agents.daemon_slayer._rune_health_grants import (
    grasp_heal_hp,
    grasp_permanent_hp,
    overgrowth_hp_for_absorbed,
    rune_health_grants,
)

_INF = float("inf")
_NAN = float("nan")
_NON_FINITE = (_INF, -_INF, _NAN)


def _page(max_hp: float, level: int = 18, is_ranged: bool = False):
    return rune_health_grants(
        ["8437", "8451"],
        level=level,
        max_hp=max_hp,
        is_ranged=is_ranged,
        apply_rune_health_grants=True,
    )


class OvergrowthNonFiniteTests(unittest.TestCase):
    def test_infinite_absorbed_does_not_raise(self) -> None:
        self.assertEqual(overgrowth_hp_for_absorbed(_INF, 1000.0), 0.0)

    def test_non_finite_absorbed_reads_as_zero(self) -> None:
        for absorbed in _NON_FINITE:
            with self.subTest(absorbed=absorbed):
                self.assertEqual(overgrowth_hp_for_absorbed(absorbed, 1000.0), 0.0)

    def test_non_finite_pool_drops_only_the_percent_term(self) -> None:
        # 120 absorbed = 15 blocks * 3 = 45 flat; the 3.5% term reads the pool.
        for pool in _NON_FINITE:
            with self.subTest(pool=pool):
                self.assertEqual(overgrowth_hp_for_absorbed(120.0, pool), 45.0)

    def test_finite_reference_values_unchanged(self) -> None:
        self.assertEqual(overgrowth_hp_for_absorbed(119.0, 1000.0), 42.0)
        self.assertAlmostEqual(overgrowth_hp_for_absorbed(120.0, 1000.0), 80.0)


class GraspNonFiniteTests(unittest.TestCase):
    def test_infinite_pool_at_zero_procs_is_not_nan(self) -> None:
        value = grasp_heal_hp(0.0, _INF)
        self.assertFalse(math.isnan(value))
        self.assertEqual(value, 0.0)

    def test_non_finite_pool_heals_zero(self) -> None:
        for pool in _NON_FINITE:
            with self.subTest(pool=pool):
                self.assertEqual(grasp_heal_hp(2.0, pool), 0.0)

    def test_non_finite_procs_heal_zero(self) -> None:
        for procs in _NON_FINITE:
            with self.subTest(procs=procs):
                self.assertEqual(grasp_heal_hp(procs, 1000.0), 0.0)

    def test_non_finite_procs_grant_no_permanent_hp(self) -> None:
        for procs in _NON_FINITE:
            for ranged in (False, True):
                with self.subTest(procs=procs, ranged=ranged):
                    self.assertEqual(grasp_permanent_hp(procs, is_ranged=ranged), 0.0)

    def test_finite_reference_values_unchanged(self) -> None:
        self.assertAlmostEqual(grasp_heal_hp(2.0, 1000.0), 26.0)
        self.assertAlmostEqual(grasp_heal_hp(2.0, 1000.0, is_ranged=True), 10.4)
        self.assertEqual(grasp_permanent_hp(45.0), 225.0)
        self.assertAlmostEqual(grasp_permanent_hp(45.0, is_ranged=True), 90.0)


class PageNonFiniteTests(unittest.TestCase):
    def test_infinite_pool_returns_finite_pair(self) -> None:
        for pool in _NON_FINITE:
            for ranged in (False, True):
                with self.subTest(pool=pool, ranged=ranged):
                    perm, heal = _page(pool, is_ranged=ranged)
                    self.assertTrue(math.isfinite(perm))
                    self.assertTrue(math.isfinite(heal))

    def test_non_finite_pool_keeps_only_the_pool_free_terms(self) -> None:
        # Level 18: Grasp 45 procs * 5 = 225, Overgrowth 160 absorbed = 20
        # blocks * 3 = 60. The pool-scaled terms (3.5% threshold, 1.3% heal)
        # read an unusable pool as 0.0.
        self.assertEqual(_page(_INF), (285.0, 0.0))

    def test_finite_reference_value_unchanged(self) -> None:
        perm, heal = _page(2000.0)
        self.assertAlmostEqual(perm, 355.0)
        self.assertAlmostEqual(heal, 52.0)


if __name__ == "__main__":
    unittest.main()
