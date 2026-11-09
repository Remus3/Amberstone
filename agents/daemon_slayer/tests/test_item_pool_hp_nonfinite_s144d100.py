"""S144-D-100 / S144-D-101: the item pool-to-HP registries never return inf or NaN.

OFFLINE ONLY - no DS :8860 call, no network. The r105 (Awe, mana -> HP) and
r107 (Warmog's Vitality, bonus HP amp) tests pin the magnitudes at FINITE
pools only.

Defects pinned (measured before the fix):
  * S144-D-100 ``item_mana_health_hp`` at ``bonus_mana=inf`` returned inf for
    Winter's Approach 3119, and NaN (``0.0 * inf``) for a build carrying NO Awe
    item at all - a NaN folded into every ``compute_ehp`` numerator;
  * S144-D-101 ``item_bonus_hp_amp_hp`` at ``bonus_hp_from_items=inf`` did the
    same (inf with Warmog's 3083, NaN without it).

Contract (the S144-D-93 / D-95 rule): a non-finite pool is unusable and reads
0.0 - the result -inf and NaN already produced through the ``max(0.0, ...)``
clamp. Finite pools are unchanged - pinned by the reference values below,
which are the pre-fix outputs.
"""

from __future__ import annotations

import unittest

from agents.daemon_slayer._item_bonus_hp_amp import item_bonus_hp_amp_hp
from agents.daemon_slayer._item_mana_health import item_mana_health_hp

_INF = float("inf")
_NAN = float("nan")
_NON_FINITE = (_INF, -_INF, _NAN)
_CASES = (
    (item_mana_health_hp, "3119"),
    (item_bonus_hp_amp_hp, "3083"),
)


class NonFinitePoolTests(unittest.TestCase):
    def test_registered_item_infinite_pool_reads_zero(self) -> None:
        for fn, iid in _CASES:
            with self.subTest(fn=fn.__name__):
                self.assertEqual(fn([iid], _INF), 0.0)

    def test_unregistered_build_infinite_pool_is_not_nan(self) -> None:
        for fn, _iid in _CASES:
            for ids in ([], ["1001"]):
                with self.subTest(fn=fn.__name__, ids=ids):
                    self.assertEqual(fn(ids, _INF), 0.0)

    def test_every_non_finite_pool_reads_zero(self) -> None:
        for fn, iid in _CASES:
            for ids in ([iid], [], ["1001"]):
                for value in _NON_FINITE:
                    with self.subTest(fn=fn.__name__, ids=ids, value=value):
                        self.assertEqual(fn(ids, value), 0.0)


class FiniteParityTests(unittest.TestCase):
    """Pre-fix outputs at finite pools - the fix must not move them."""

    def test_reference_values(self) -> None:
        self.assertEqual(item_mana_health_hp(["3119"], 1000.0), 150.0)
        self.assertEqual(item_mana_health_hp(["1001"], 1000.0), 0.0)
        self.assertEqual(item_mana_health_hp(["3119"], -5.0), 0.0)
        self.assertEqual(item_bonus_hp_amp_hp(["3083"], 1000.0), 120.0)
        self.assertEqual(item_bonus_hp_amp_hp([], 1000.0), 0.0)
        self.assertEqual(item_bonus_hp_amp_hp(["3083"], 0.0), 0.0)


if __name__ == "__main__":
    unittest.main()
