"""S144-D-108..110: item revive, item ally grant and rune flat DR fail soft.

OFFLINE ONLY - no DS :8860 call, no network. The r102 (Guardian Angel revive),
team_blended ally-grant and RM-101 (rune flat mitigation) tests pin the
magnitudes at FINITE, well-typed inputs only.

Defects pinned (measured before the fix):
  * S144-D-108 ``item_revive_max_hp_fraction(["3026"], ...)`` returned inf at
    ``base_hp=inf`` (and on a finite ratio that overflows, 1e308 / 1e-308), NaN
    at ``total_hp=nan`` (``nan <= 0.0`` is False, so the division guard let it
    through), NaN at ``base_hp=nan`` and at ``inf / inf``, and a NEGATIVE
    fraction (-0.06) at ``base_hp=-600`` - a revive that LOWERED the EHP
    numerator multiplier below 1.0;
  * S144-D-109 ``ally_grant_hp`` documents "never raises" but raised
    ValueError / OverflowError / TypeError on a NaN / +-inf / None level and
    TypeError / ValueError on a None / non-numeric ``ap``; and at ``ap=inf`` the
    AP-scaled Echoes of Helia row (6620) returned inf;
  * S144-D-110 ``rune_flat_mitigation_hp`` raised ValueError / OverflowError /
    TypeError out of the ``compute_ehp`` seam on a NaN / +-inf / None /
    non-numeric level.

Contract (the S144-D-93 / D-95 / D-96 rule): a non-finite or unusable quantity
reads 0.0 credit, never inf, NaN or an exception. A NaN ``ap`` already read as
0.0 AP through the ``max(0.0, ...)`` clamp; +-inf / garbage now does the same.
Finite, well-typed inputs are unchanged - pinned by the reference values below,
which are the pre-fix outputs. The level CLAMP semantics are untouched (RM-848
family): only a level ``int()`` cannot convert is new.
"""

from __future__ import annotations

import math
import unittest

from agents.daemon_slayer._item_ally_grant import (
    ally_grant_hp,
    total_item_ally_grant_hp,
)
from agents.daemon_slayer._item_revive import item_revive_max_hp_fraction
from agents.daemon_slayer._rune_flat_mitigation import rune_flat_mitigation_hp

_INF = float("inf")
_NAN = float("nan")
_NON_FINITE = (_INF, -_INF, _NAN)
_BAD_LEVELS = (_INF, -_INF, _NAN, None, "x")


class ItemReviveNonFiniteTests(unittest.TestCase):
    """S144-D-108."""

    def test_non_finite_pools_read_zero(self) -> None:
        cases = [(v, 2000.0) for v in _NON_FINITE] + [
            (600.0, _NAN),
            (_INF, _INF),
            (_NAN, _NAN),
        ]
        for base, total in cases:
            for iid in ("3026", "223026"):
                with self.subTest(base=base, total=total, iid=iid):
                    self.assertEqual(
                        item_revive_max_hp_fraction([iid], base, total), 0.0
                    )

    def test_overflowing_ratio_reads_zero(self) -> None:
        self.assertEqual(item_revive_max_hp_fraction(["3026"], 1e308, 1e-308), 0.0)

    def test_negative_base_never_credits_negative(self) -> None:
        self.assertEqual(item_revive_max_hp_fraction(["3026"], -600.0, 2000.0), 0.0)

    def test_finite_reference_unchanged(self) -> None:
        self.assertAlmostEqual(
            item_revive_max_hp_fraction(["3026"], 600.0, 2000.0), 0.06, places=12
        )
        self.assertEqual(item_revive_max_hp_fraction(["3026"], 600.0, 0.0), 0.0)
        self.assertEqual(item_revive_max_hp_fraction(["3026"], 600.0, -_INF), 0.0)
        self.assertEqual(item_revive_max_hp_fraction(["1001"], 600.0, 2000.0), 0.0)


class ItemAllyGrantFailSoftTests(unittest.TestCase):
    """S144-D-109."""

    def test_unusable_level_reads_zero_never_raises(self) -> None:
        for lvl in _BAD_LEVELS:
            for iid in ("6620", "3190", "3107", "326620"):
                with self.subTest(level=lvl, iid=iid):
                    self.assertEqual(ally_grant_hp(iid, lvl), 0.0)
            with self.subTest(level=lvl, total=True):
                self.assertEqual(total_item_ally_grant_hp(["6620", "3190"], lvl), 0.0)

    def test_unusable_ap_reads_as_zero_ap(self) -> None:
        for ap in (_INF, -_INF, _NAN, None, "x"):
            for iid in ("6620", "3190"):
                with self.subTest(ap=ap, iid=iid):
                    self.assertEqual(
                        ally_grant_hp(iid, 10, ap), ally_grant_hp(iid, 10, 0.0)
                    )

    def test_result_is_always_finite(self) -> None:
        for ap in (0.0, 100.0, 1e308, _INF, _NAN):
            with self.subTest(ap=ap):
                self.assertTrue(math.isfinite(ally_grant_hp("6620", 18, ap)))

    def test_finite_reference_unchanged(self) -> None:
        self.assertAlmostEqual(ally_grant_hp("6620", 10, 0.0), 55.84, places=9)
        self.assertAlmostEqual(ally_grant_hp("3190", 10, 0.0), 981.24, places=9)
        self.assertAlmostEqual(ally_grant_hp("326620", 10, 0.0), 55.84, places=9)
        self.assertEqual(ally_grant_hp("3109", 10, 0.0), 0.0)
        self.assertEqual(ally_grant_hp("", 10, 0.0), 0.0)


class RuneFlatMitigationFailSoftTests(unittest.TestCase):
    """S144-D-110."""

    def test_unusable_level_reads_zero_never_raises(self) -> None:
        for lvl in _BAD_LEVELS:
            with self.subTest(level=lvl):
                self.assertEqual(
                    rune_flat_mitigation_hp(
                        ["8473"], level=lvl, apply_rune_flat_mitigation=True
                    ),
                    (0.0, 0.0, 0.0),
                )

    def test_off_gate_still_inert(self) -> None:
        self.assertEqual(
            rune_flat_mitigation_hp(["8473"], level=_NAN), (0.0, 0.0, 0.0)
        )

    def test_finite_reference_unchanged(self) -> None:
        phys, mag, true = rune_flat_mitigation_hp(
            ["8473"], level=10, apply_rune_flat_mitigation=True
        )
        for got in (phys, mag, true):
            self.assertAlmostEqual(got, 34.41176475, places=9)
        self.assertEqual(
            rune_flat_mitigation_hp(
                ["8473"], level=1e300, apply_rune_flat_mitigation=True
            ),
            (45.0, 45.0, 45.0),
        )


if __name__ == "__main__":
    unittest.main()
