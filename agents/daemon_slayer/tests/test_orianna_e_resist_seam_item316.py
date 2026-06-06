"""Item 316 - end-to-end regression: Orianna E ally-resist grant seam.

Locks in the already-shipped item-289 behavior:
  - granter-side value resolution via ally_resist_grant
  - protected-ally EHP lift via the external_resist_armor/mr seam in compute_ehp
  - monotonicity + max-cap invariants across the E rank-up ladder
  - byte-identical default + negative-clamp guards

ASCII-only source (Class 3 self-check included).
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer._passive_ally_grant_overrides import ally_resist_grant
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import _armor_factor, compute_ehp

# The 7 probe levels used throughout this module.
_PROBE_LEVELS = (1, 3, 6, 9, 12, 15, 18)

# Pinned armor-grant tuple for Orianna at the probe levels.
# Captured 2026-06-06 against engine 1.101.0+ (item-289 shipped).
_ORIANNA_ARMOR_PINNED = (0.0, 0.0, 6.0, 6.0, 6.0, 18.0, 30.0)


class Class1FlagOffTests(unittest.TestCase):
    """Flag OFF -> (0.0, 0.0) for any champion at any level."""

    def test_flag_off_orianna(self):
        for lvl in _PROBE_LEVELS:
            self.assertEqual(ally_resist_grant("Orianna", lvl, False), (0.0, 0.0))

    def test_flag_off_braum(self):
        for lvl in _PROBE_LEVELS:
            self.assertEqual(ally_resist_grant("Braum", lvl, False), (0.0, 0.0))

    def test_flag_off_caitlyn(self):
        for lvl in _PROBE_LEVELS:
            self.assertEqual(ally_resist_grant("Caitlyn", lvl, False), (0.0, 0.0))


class Class1OriannaScalingTests(unittest.TestCase):
    """Orianna E rank-up ladder: armor==mr, monotonic, max 30 at level 18."""

    def _armor_values(self):
        return tuple(ally_resist_grant("Orianna", lvl, True)[0] for lvl in _PROBE_LEVELS)

    def _mr_values(self):
        return tuple(ally_resist_grant("Orianna", lvl, True)[1] for lvl in _PROBE_LEVELS)

    def test_pinned_regression_snapshot(self):
        self.assertEqual(self._armor_values(), _ORIANNA_ARMOR_PINNED)

    def test_armor_equals_mr_at_all_probe_levels(self):
        for lvl in _PROBE_LEVELS:
            a, m = ally_resist_grant("Orianna", lvl, True)
            self.assertAlmostEqual(a, m, places=6, msg=f"level {lvl}")

    def test_monotonic_non_decreasing(self):
        vals = self._armor_values()
        for i in range(1, len(vals)):
            self.assertGreaterEqual(
                vals[i], vals[i - 1],
                msg=f"level {_PROBE_LEVELS[i]} < level {_PROBE_LEVELS[i - 1]}",
            )

    def test_max_at_level_18_is_30(self):
        a, m = ally_resist_grant("Orianna", 18, True)
        self.assertAlmostEqual(a, 30.0, places=6)
        self.assertAlmostEqual(m, 30.0, places=6)

    def test_level_1_is_first_series_value_or_zero(self):
        # E not yet learned at level 1 by the engine-default priority order.
        # The engine actually returns 0.0 - pin that exact value.
        a, m = ally_resist_grant("Orianna", 1, True)
        self.assertEqual((a, m), (0.0, 0.0))

    def test_self_contained_ignores_granter_resists(self):
        # Flat grant: does not depend on granter build stats.
        a0, m0 = ally_resist_grant("Orianna", 18, True)
        a1, m1 = ally_resist_grant(
            "Orianna", 18, True,
            granter_total_armor=300.0, granter_total_mr=300.0,
        )
        self.assertEqual((a0, m0), (a1, m1))


class Class1NonGranterTests(unittest.TestCase):
    """Non-granter champ ON -> (0.0, 0.0)."""

    def test_caitlyn_on_is_zero(self):
        for lvl in _PROBE_LEVELS:
            self.assertEqual(ally_resist_grant("Caitlyn", lvl, True), (0.0, 0.0))

    def test_garen_on_is_zero(self):
        self.assertEqual(ally_resist_grant("Garen", 18, True), (0.0, 0.0))


class Class2EhpApplicationTests(unittest.TestCase):
    """End-to-end: Orianna E grant flows into a protected ally's EHP."""

    @classmethod
    def setUpClass(cls):
        cls.snap = DataSnapshot.load()

    def _ally(self, level, **kw):
        return compute_ehp(self.snap, "Caitlyn", level, item_ids=[], **kw)

    def test_boosted_physical_and_magical_ehp_exceed_base(self):
        lvl = 11
        base = self._ally(lvl)
        a, m = ally_resist_grant("Orianna", lvl, True)
        boosted = self._ally(lvl, external_resist_armor=a, external_resist_mr=m)
        self.assertGreater(boosted.physical_ehp, base.physical_ehp)
        self.assertGreater(boosted.magical_ehp, base.magical_ehp)

    def test_true_ehp_unchanged_by_resist_grant(self):
        # True damage ignores armor/MR -> true_ehp must stay equal.
        lvl = 11
        base = self._ally(lvl)
        a, m = ally_resist_grant("Orianna", lvl, True)
        boosted = self._ally(lvl, external_resist_armor=a, external_resist_mr=m)
        self.assertAlmostEqual(boosted.true_ehp, base.true_ehp, places=3)

    def test_physical_ehp_ratio_matches_armor_factor(self):
        # boosted.physical_ehp / base.physical_ehp ==
        #   _armor_factor(base.armor) / _armor_factor(base.armor + a)
        # (the external add shifts the denominator exactly once).
        lvl = 11
        base = self._ally(lvl)
        a, _ = ally_resist_grant("Orianna", lvl, True)
        boosted = self._ally(lvl, external_resist_armor=a)
        expected_ratio = _armor_factor(base.armor) / _armor_factor(base.armor + a)
        actual_ratio = boosted.physical_ehp / base.physical_ehp
        self.assertAlmostEqual(actual_ratio, expected_ratio, places=4)

    def test_magical_ehp_ratio_matches_mr_factor(self):
        lvl = 11
        base = self._ally(lvl)
        _, m = ally_resist_grant("Orianna", lvl, True)
        boosted = self._ally(lvl, external_resist_mr=m)
        expected_ratio = _armor_factor(base.mr) / _armor_factor(base.mr + m)
        actual_ratio = boosted.magical_ehp / base.magical_ehp
        self.assertAlmostEqual(actual_ratio, expected_ratio, places=4)

    def test_default_byte_identical_to_explicit_zeros(self):
        # Omitting external params must equal passing 0.0/0.0/1.0 on all axes.
        lvl = 11
        omitted = self._ally(lvl)
        explicit = self._ally(
            lvl,
            external_resist_armor=0.0,
            external_resist_mr=0.0,
            external_revive_multiplier=1.0,
        )
        self.assertEqual(omitted.physical_ehp, explicit.physical_ehp)
        self.assertEqual(omitted.magical_ehp, explicit.magical_ehp)
        self.assertEqual(omitted.true_ehp, explicit.true_ehp)
        self.assertEqual(omitted.blended_ehp, explicit.blended_ehp)

    def test_negative_external_armor_clamped_to_zero(self):
        lvl = 11
        base = self._ally(lvl)
        clamped = self._ally(lvl, external_resist_armor=-50.0)
        self.assertEqual(clamped.blended_ehp, base.blended_ehp)
        self.assertEqual(clamped.ally_grant_armor, 0.0)

    def test_negative_external_mr_clamped_to_zero(self):
        lvl = 11
        base = self._ally(lvl)
        clamped = self._ally(lvl, external_resist_mr=-50.0)
        self.assertEqual(clamped.blended_ehp, base.blended_ehp)
        self.assertEqual(clamped.ally_grant_mr, 0.0)


class Class3AsciiHygieneTest(unittest.TestCase):
    """Assert this test file contains only 7-bit ASCII codepoints."""

    def test_file_is_7bit_ascii(self):
        import pathlib
        src = pathlib.Path(__file__).read_text(encoding="utf-8")
        bad = [
            (i + 1, ch)
            for i, ch in enumerate(src)
            if ord(ch) > 127
        ]
        self.assertEqual(
            bad, [],
            msg=f"Non-ASCII codepoints found: {bad[:5]}",
        )


if __name__ == "__main__":
    unittest.main()
