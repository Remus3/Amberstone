"""S144-D-96: ``_rune_shield_grants`` honours its FAIL-SOFT contract on non-finite input.

OFFLINE ONLY - no DS :8860 call, no network. ``rune_shield_grants``'s docstring
promises "an empty / None / non-iterable rune list, a garbage entry, or a
non-numeric pool argument returns 0.0 rather than raising". The r142 tests cover
None / garbage / non-numeric strings; none hands in inf, an infinite level or a
page whose truthiness raises.

Defects pinned (measured before the fix):
  * ``total_hp=inf`` (or ``base_hp=-inf``) credited an INFINITE shield, through
    both ``rune_shield_grants`` and ``guardian_self_shield``;
  * ``level=inf`` RAISED OverflowError (``int(inf)``) - the seam caught only
    TypeError / ValueError;
  * the ``not rune_ids`` guard sat OUTSIDE any try, so a page whose truthiness
    raises (a multi-element array) escaped as ValueError - the S144-D-94
    ``_rune_self_heal`` defect, in its shield sibling.

Contract: a non-finite pool makes the 6%-of-BONUS-health term unusable, so it
reads 0.0 and the level-scaled flat term stands alone - the same result a NaN
pool already produced through the ``max(0.0, nan)`` clamp. An unusable level or
page returns 0.0. ``_lerp_by_level`` itself is NOT touched (its clamp is the
RM-848 Tier-2 family). Finite inputs are unchanged - pinned by the reference
values below, which are the pre-fix outputs.
"""

from __future__ import annotations

import math
import unittest

from agents.daemon_slayer._rune_shield_grants import (
    guardian_shield_base,
    guardian_self_shield,
    rune_shield_grants,
)

_INF = float("inf")
_NAN = float("nan")
_NON_FINITE = (_INF, -_INF, _NAN)


def _seam(rune_ids=("8465",), *, level=10, total_hp=2000.0, base_hp=1000.0):
    return rune_shield_grants(
        rune_ids,
        level=level,
        total_hp=total_hp,
        base_hp=base_hp,
        apply_rune_shield_grants=True,
    )


class _AmbiguousTruth:
    """Iterable whose truthiness raises, like a multi-element array."""

    def __bool__(self) -> bool:
        raise ValueError("truth value is ambiguous")

    def __iter__(self):
        return iter(["8465"])


class NonFinitePoolTests(unittest.TestCase):
    def test_non_finite_total_keeps_flat_term_only(self) -> None:
        flat = guardian_shield_base(10)
        for total in _NON_FINITE:
            with self.subTest(total_hp=total):
                self.assertEqual(
                    guardian_self_shield(level=10, total_hp=total, base_hp=1000.0),
                    flat,
                )

    def test_non_finite_base_keeps_flat_term_only(self) -> None:
        flat = guardian_shield_base(10)
        for base in _NON_FINITE:
            with self.subTest(base_hp=base):
                self.assertEqual(
                    guardian_self_shield(level=10, total_hp=2000.0, base_hp=base),
                    flat,
                )

    def test_seam_is_finite_for_every_non_finite_pool(self) -> None:
        for total in (*_NON_FINITE, 2000.0):
            for base in (*_NON_FINITE, 1000.0):
                with self.subTest(total_hp=total, base_hp=base):
                    self.assertTrue(math.isfinite(_seam(total_hp=total, base_hp=base)))


class SeamFailSoftTests(unittest.TestCase):
    def test_infinite_level_returns_zero(self) -> None:
        for level in (_INF, -_INF):
            with self.subTest(level=level):
                self.assertEqual(_seam(level=level), 0.0)

    def test_nan_level_returns_zero(self) -> None:
        self.assertEqual(_seam(level=_NAN), 0.0)

    def test_page_with_raising_truthiness_returns_zero(self) -> None:
        self.assertEqual(_seam(_AmbiguousTruth()), 0.0)

    def test_flag_off_never_touches_the_page(self) -> None:
        self.assertEqual(
            rune_shield_grants(
                _AmbiguousTruth(), level=10, total_hp=2000.0, base_hp=1000.0
            ),
            0.0,
        )


class FiniteReferenceTests(unittest.TestCase):
    def test_finite_values_unchanged(self) -> None:
        # 40 + 110 * 9 / 17 = 98.235..., + 6% of 1000 bonus = 158.235...,
        # amortized by _RUNE_GUARDIAN_SHIELD_PROB 0.2.
        self.assertAlmostEqual(
            guardian_self_shield(level=10, total_hp=2000.0, base_hp=1000.0),
            158.23529411764707,
        )
        self.assertAlmostEqual(_seam(), 31.647058823529417)
        self.assertAlmostEqual(_seam(total_hp=900.0), guardian_shield_base(10) * 0.2)


if __name__ == "__main__":
    unittest.main()
