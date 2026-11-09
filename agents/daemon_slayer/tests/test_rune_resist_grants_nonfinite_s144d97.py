"""S144-D-97: ``rune_resist_grants`` never credits an infinite resist from a non-finite input.

OFFLINE ONLY - no DS :8860 call, no network. The r132 / r134 tests pin the
Aftershock / Conditioning / Unflinching magnitudes, the bonus-vs-total percent
base and the cap-before-probability order at FINITE inputs only.

Defects pinned (measured before the fix):
  * ``total_armor=inf`` on Conditioning 8429 (percent of TOTAL, uncapped)
    credited INFINITE bonus armor into ``ehp.compute_ehp``'s ``eff_armor``;
  * ``base_armor=-inf`` on Aftershock 8439 read an infinite BONUS resist and
    credited the full level cap (45.0 = 150 * 0.3 at level 18) instead of the
    flat term alone.

Contract (the S144-D-93 / D-95 rule, applied to the denominator lane): a
non-finite resist makes the PERCENT term unusable, so it reads 0.0 and the flat
term stands alone - the result a NaN resist already produced through the
``max(0.0, nan)`` clamp. A NaN ``game_minute`` is "no clock" and resolves to the
documented ``_ASSUMED_GAME_MINUTE`` default, as ``None`` does, instead of passing
the Conditioning gate by an accident of NaN comparison. The ``level`` clamp
(``aftershock_resist_cap``) is NOT touched - that is the RM-848 Tier-2 family.
Finite inputs are unchanged - pinned by the reference values below, which are
the pre-fix outputs.
"""

from __future__ import annotations

import math
import unittest

from agents.daemon_slayer._rune_resist_grants import (
    _ASSUMED_GAME_MINUTE,
    rune_resist_grants,
)

_INF = float("inf")
_NAN = float("nan")
_NON_FINITE = (_INF, -_INF, _NAN)
_KW = dict(level=18, total_armor=100.0, total_mr=80.0, base_armor=50.0, base_mr=40.0)


def _grant(rune_ids, **overrides):
    return rune_resist_grants(rune_ids, **{**_KW, **overrides})


class ConditioningNonFiniteTests(unittest.TestCase):
    def test_infinite_total_armor_is_finite(self) -> None:
        armor, mr = _grant(["8429"], total_armor=_INF)
        self.assertTrue(math.isfinite(armor))
        self.assertAlmostEqual(mr, 8.0 + 80.0 * 0.03)

    def test_non_finite_total_keeps_flat_term_only(self) -> None:
        for value in _NON_FINITE:
            with self.subTest(total=value):
                self.assertEqual(
                    _grant(["8429"], total_armor=value, total_mr=value), (8.0, 8.0)
                )


class AftershockNonFiniteTests(unittest.TestCase):
    def test_negative_infinite_base_does_not_read_as_infinite_bonus(self) -> None:
        armor, _mr = _grant(["8439"], base_armor=-_INF)
        self.assertAlmostEqual(armor, 45.0 * 0.3)

    def test_any_non_finite_pair_keeps_flat_term_only(self) -> None:
        for total in (*_NON_FINITE, 100.0):
            for base in (*_NON_FINITE, 50.0):
                if math.isfinite(total) and math.isfinite(base):
                    continue
                with self.subTest(total=total, base=base):
                    armor, _mr = _grant(["8439"], total_armor=total, base_armor=base)
                    self.assertAlmostEqual(armor, 45.0 * 0.3)


class GameMinuteTests(unittest.TestCase):
    def test_nan_minute_behaves_as_the_default(self) -> None:
        self.assertEqual(
            _grant(["8429"], game_minute=_NAN), _grant(["8429"], game_minute=None)
        )
        self.assertEqual(
            _grant(["8429"], game_minute=_NAN),
            _grant(["8429"], game_minute=_ASSUMED_GAME_MINUTE),
        )

    def test_finite_minutes_still_gate(self) -> None:
        self.assertEqual(_grant(["8429"], game_minute=5.0), (0.0, 0.0))
        self.assertEqual(_grant(["8429"], game_minute=-_INF), (0.0, 0.0))
        self.assertNotEqual(_grant(["8429"], game_minute=_INF), (0.0, 0.0))


class FiniteReferenceTests(unittest.TestCase):
    def test_finite_page_unchanged(self) -> None:
        armor, mr = _grant(["8439", "8429", "8242"])
        self.assertAlmostEqual(armor, 38.75)
        self.assertAlmostEqual(mr, 35.9)


if __name__ == "__main__":
    unittest.main()
