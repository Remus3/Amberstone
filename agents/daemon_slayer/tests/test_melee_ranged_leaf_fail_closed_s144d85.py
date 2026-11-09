"""S144-D-85: the shared melee/ranged leaf keeps its fail-closed contract.

``agents/daemon_slayer/_melee_ranged.attackrange_is_ranged`` is the ONE
predicate every scorer routes through since RM-123 (ehp, rank, burst, engine).
Its docstring promises it "fails CLOSED to False (melee) on a missing /
malformed value", so a missing champ record is never over-classified as
ranged (which would, e.g., offer a melee champion ranged-only items).

The existing RM-123 regression pins the 350 boundary through the ehp / rank
wrappers on real roster records only; no test called the leaf itself with a
missing or malformed value, so the fail-closed clause was unguarded. This
pins it directly, plus the numeric-string spelling the ``float()`` coercion
accepts today.

Out of scope here (filed as a spec, not changed by a lane): a NON-FINITE
value. ``float("inf")`` classifies as ranged today; NaN happens to read as
melee only because every NaN comparison is False. Neither is reachable from
the DDragon roster, and changing the engine leaf is the merger's call.
"""

import unittest

from agents.daemon_slayer._melee_ranged import (
    MELEE_RANGED_ATTACKRANGE_SPLIT,
    attackrange_is_ranged,
)


class MeleeRangedLeafFailClosed(unittest.TestCase):
    def test_split_constant_is_350(self) -> None:
        self.assertEqual(MELEE_RANGED_ATTACKRANGE_SPLIT, 350.0)

    def test_missing_value_is_melee(self) -> None:
        for value in (None, 0, 0.0, ""):
            with self.subTest(value=value):
                self.assertIs(attackrange_is_ranged(value), False)

    def test_malformed_value_is_melee_not_an_error(self) -> None:
        for value in ("abc", "350 units", [350], {"attackrange": 550}, object()):
            with self.subTest(value=repr(value)):
                self.assertIs(attackrange_is_ranged(value), False)

    def test_numeric_string_is_coerced(self) -> None:
        self.assertIs(attackrange_is_ranged("349"), False)
        self.assertIs(attackrange_is_ranged("350"), True)
        self.assertIs(attackrange_is_ranged("550.0"), True)

    def test_boundary_on_the_leaf(self) -> None:
        self.assertIs(attackrange_is_ranged(349.999), False)
        self.assertIs(attackrange_is_ranged(350), True)
        self.assertIs(attackrange_is_ranged(350.0), True)
        self.assertIs(attackrange_is_ranged(-500.0), False)

    def test_returns_a_real_bool(self) -> None:
        # Callers negate it (``not attackrange_is_ranged(...)``) and compare
        # it with ``is``-style equality in tests; a truthy non-bool would
        # still pass ``not`` but would break an ``assertIs`` pin elsewhere.
        for value in (125.0, 550.0, None, "abc"):
            with self.subTest(value=value):
                self.assertIsInstance(attackrange_is_ranged(value), bool)


if __name__ == "__main__":
    unittest.main()
