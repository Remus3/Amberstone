"""S144-D-104..106: three more item EHP-registry helpers never return inf or NaN.

OFFLINE ONLY - no DS :8860 call, no network. The r137 (Heartsteel stack),
RM-103 (Unending Despair proc heal) and RM-91 T2 (caster-HP proc) tests pin the
magnitudes at FINITE inputs only.

Defects pinned (measured before the fix):
  * S144-D-104 ``item_health_stack_hp(["3084"], inf, 18)`` returned inf - folded
    straight into every ``compute_ehp`` numerator under
    ``assume_item_health_stacks``;
  * S144-D-105 ``item_proc_heal_hp(["2502"], ...)`` returned inf at
    ``bonus_hp=inf``, ``triggers_per_fight=inf`` or ``champions_in_range=inf``,
    and at finite inputs whose product overflows (1e300 x 1e300);
  * S144-D-106 ``proc_converted_points`` returned inf for an infinite pool, and
    NaN (``0.0 * inf``) when the infinite pool was the one the entry does NOT
    read (Heartsteel 3084 reads the max pool only, so an infinite bonus pool
    made 180.0 points NaN).

Contract (the S144-D-93 / D-95 / D-100 rule): a non-finite quantity is unusable
and reads 0.0 - the result -inf and NaN already produced through the
``max(0.0, ...)`` clamps. Finite inputs are unchanged - pinned by the reference
values below, which are the pre-fix outputs.
"""

from __future__ import annotations

import math
import unittest

from agents.daemon_slayer._item_caster_hp_proc import (
    item_caster_hp_proc,
    proc_converted_points,
)
from agents.daemon_slayer._item_health_stack import item_health_stack_hp
from agents.daemon_slayer._item_proc_heal import item_proc_heal_hp

_INF = float("inf")
_NAN = float("nan")
_NON_FINITE = (_INF, -_INF, _NAN)


class HealthStackNonFiniteTests(unittest.TestCase):
    """S144-D-104."""

    def test_non_finite_max_hp_reads_zero(self) -> None:
        for v in _NON_FINITE:
            for iid in ("3084", "223084", "1001"):
                with self.subTest(hp=v, iid=iid):
                    self.assertEqual(item_health_stack_hp([iid], v, 18), 0.0)

    def test_finite_reference_unchanged(self) -> None:
        self.assertEqual(item_health_stack_hp(["3084"], 3000.0, 18), 325.0)
        self.assertEqual(item_health_stack_hp(["3084"], 3000.0, 6), 0.0)
        self.assertTrue(math.isfinite(item_health_stack_hp(["3084"], 1e308, 18)))


class ProcHealNonFiniteTests(unittest.TestCase):
    """S144-D-105."""

    def _heal(self, **kw: float) -> float:
        args: dict = {"bonus_hp": 1200.0}
        args.update(kw)
        bonus_hp = args.pop("bonus_hp")
        return item_proc_heal_hp(
            ["2502"], bonus_hp, assume_item_proc_heal=True, **args
        )

    def test_non_finite_quantity_reads_zero(self) -> None:
        for kw in ("bonus_hp", "triggers_per_fight", "champions_in_range"):
            for v in _NON_FINITE:
                with self.subTest(kw=kw, v=v):
                    self.assertEqual(self._heal(**{kw: v}), 0.0)

    def test_overflowing_product_reads_zero(self) -> None:
        got = self._heal(
            bonus_hp=1e300, triggers_per_fight=1e300, champions_in_range=1e10
        )
        self.assertEqual(got, 0.0)

    def test_result_always_finite_over_target_mr(self) -> None:
        for mr in (_INF, -_INF, _NAN, -1e308, 1e308, 0.0):
            with self.subTest(mr=mr):
                self.assertTrue(math.isfinite(self._heal(target_mr=mr)))

    def test_finite_reference_unchanged(self) -> None:
        self.assertEqual(self._heal(), 56.25)
        self.assertEqual(
            self._heal(
                target_mr=30.0, triggers_per_fight=4.0, champions_in_range=2.0
            ),
            553.8461538461539,
        )

    def test_flag_off_still_exact_zero(self) -> None:
        for v in _NON_FINITE:
            with self.subTest(v=v):
                self.assertEqual(item_proc_heal_hp(["2502"], v), 0.0)


class ConvertedPointsNonFiniteTests(unittest.TestCase):
    """S144-D-106."""

    def test_non_finite_pool_reads_zero(self) -> None:
        heartsteel = item_caster_hp_proc("3084")
        despair = item_caster_hp_proc("2502")
        assert heartsteel is not None and despair is not None
        for v in _NON_FINITE:
            with self.subTest(v=v):
                self.assertEqual(proc_converted_points(heartsteel, v, 1500.0), 0.0)
                self.assertEqual(proc_converted_points(despair, 3000.0, v), 0.0)
                self.assertEqual(
                    proc_converted_points(heartsteel, 3000.0, v), 180.0
                )
                self.assertEqual(proc_converted_points(despair, v, 1500.0), 45.0)

    def test_finite_reference_unchanged(self) -> None:
        heartsteel = item_caster_hp_proc("3084")
        despair = item_caster_hp_proc("2502")
        assert heartsteel is not None and despair is not None
        self.assertEqual(proc_converted_points(heartsteel, 3000.0, 1500.0), 180.0)
        self.assertEqual(proc_converted_points(despair, 3000.0, 1500.0), 45.0)


if __name__ == "__main__":
    unittest.main()
