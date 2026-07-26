"""Item 271 - FORM-OCCUPANCY-gated RESIST-STAT grant (Jayce R Hammer).

The last clean headless resist-grant exclusion class from items 264/267/268/270:
a self bonus armor / MR grant that exists ONLY in one stance of a 2-form toggle.
Cannon stance (Jayce R form 0) carries ZERO of the grant (its R only shreds the
TARGET's resists, an offensive debuff), so unlike K'Sante All Out / Kayn R the
base cannot be seeded gate-independently.

Seam: amortize by ``_FORM_OCCUPANCY_PROB`` (0.5 = a roughly even Cannon/Hammer
split), reusing the existing ``conditional_probability`` field - NO new schema
field (the item-270 hand-authoring convention). EXHAUSTIVE roster scan: Jayce R
Hammer is the SOLE form-gated self flat-resist grant (Kled forms are HP not
resist; Elise/Nidalee/Gnar/Shyvana/Swain forms grant no flat resist).

``apply_passive_resist`` defaults False -> byte-identical.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import compute_ehp
from agents.daemon_slayer._passive_damage_overrides import _step_per_level
from agents.daemon_slayer._passive_resist_overrides import (
    _FORM_OCCUPANCY_PROB,
    _PASSIVE_RESIST_OVERRIDES,
    resist_grants,
)

_KEY = ("Jayce", "R", 1)
_FP = _FORM_OCCUPANCY_PROB  # 0.5
# 5/15/25/35 (based on level) discrete TIER step, even-quarters over 18 levels.
_STEP = _step_per_level((5.0, 15.0, 25.0, 35.0))


class FormOccupancyConstantTests(unittest.TestCase):
    def test_midpoint_value(self):
        self.assertEqual(_FORM_OCCUPANCY_PROB, 0.5)

    def test_midpoint_is_a_probability(self):
        self.assertGreater(_FORM_OCCUPANCY_PROB, 0.0)
        self.assertLessEqual(_FORM_OCCUPANCY_PROB, 1.0)


class RegistryShapeTests(unittest.TestCase):
    def test_jayce_hammer_seeded_at_form_index_1(self):
        self.assertIn(_KEY, _PASSIVE_RESIST_OVERRIDES)

    def test_jayce_entry_is_level_scaled_form_amortized(self):
        e = _PASSIVE_RESIST_OVERRIDES[_KEY]
        self.assertTrue(e.level_scaled)
        self.assertFalse(e.rank_scaled)
        self.assertEqual(e.conditional_probability, _FP)
        self.assertEqual(e.attribute, "Transform Mercury Hammer")

    def test_armor_equals_mr_step_tuple(self):
        e = _PASSIVE_RESIST_OVERRIDES[_KEY]
        self.assertEqual(tuple(e.armor), _STEP)
        self.assertEqual(tuple(e.mr), _STEP)

    def test_no_percent_fields(self):
        e = _PASSIVE_RESIST_OVERRIDES[_KEY]
        self.assertEqual(e.armor_pct, 0.0)
        self.assertEqual(e.mr_pct, 0.0)

    def test_cannon_form_0_not_seeded(self):
        # Cannon stance R (form 0) only shreds the TARGET - never a self-grant.
        self.assertNotIn(("Jayce", "R", 0), _PASSIVE_RESIST_OVERRIDES)


class StepTierTests(unittest.TestCase):
    def test_even_quarter_breakpoints(self):
        # 18 levels, 4 tiers, seg=4: L1-4 -> 5, L5-8 -> 15, L9-12 -> 25, L13-18 -> 35.
        self.assertEqual(_STEP[0], 5.0)    # L1
        self.assertEqual(_STEP[4], 15.0)   # L5
        self.assertEqual(_STEP[8], 25.0)   # L9
        self.assertEqual(_STEP[10], 25.0)  # L11
        self.assertEqual(_STEP[12], 35.0)  # L13
        self.assertEqual(_STEP[15], 35.0)  # L16
        self.assertEqual(_STEP[17], 35.0)  # L18

    def test_tuple_is_eighteen_long(self):
        self.assertEqual(len(_STEP), 18)


class ResistGrantsMathTests(unittest.TestCase):
    """resist_grants amortizes the step value by the form-occupancy midpoint."""

    def test_flag_off_byte_identical(self):
        self.assertEqual(resist_grants("Jayce", 16, False), (0.0, 0.0))

    def test_level_1(self):
        a, m = resist_grants("Jayce", 1, True)
        self.assertAlmostEqual(a, 5.0 * _FP)   # 2.5
        self.assertAlmostEqual(m, 5.0 * _FP)

    def test_level_11(self):
        a, m = resist_grants("Jayce", 11, True)
        self.assertAlmostEqual(a, 25.0 * _FP)  # 12.5
        self.assertAlmostEqual(m, 25.0 * _FP)

    def test_level_16(self):
        a, m = resist_grants("Jayce", 16, True)
        self.assertAlmostEqual(a, 35.0 * _FP)  # 17.5
        self.assertAlmostEqual(m, 35.0 * _FP)

    def test_armor_equals_mr_all_levels(self):
        for lvl in (1, 5, 9, 11, 13, 16, 18):
            a, m = resist_grants("Jayce", lvl, True)
            self.assertEqual(a, m)


class EhpIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snap = DataSnapshot.load()

    def _ehp(self, champ, level, apply):
        return compute_ehp(
            self.snap, champ, level, item_ids=[],
            apply_passive_resist=apply,
        )

    def test_jayce_flag_on_raises_ehp(self):
        off = self._ehp("Jayce", 16, False)
        on = self._ehp("Jayce", 16, True)
        self.assertGreater(on.blended_ehp, off.blended_ehp)

    def test_jayce_resist_surfaced_separately_l16(self):
        on = self._ehp("Jayce", 16, True)
        # 35 (L16 step) * 0.5 form-occupancy = 17.5 each.
        self.assertAlmostEqual(on.passive_resist_armor, 17.5, places=4)
        self.assertAlmostEqual(on.passive_resist_mr, 17.5, places=4)

    def test_jayce_resist_l11(self):
        on = self._ehp("Jayce", 11, True)
        self.assertAlmostEqual(on.passive_resist_armor, 12.5, places=4)
        self.assertAlmostEqual(on.passive_resist_mr, 12.5, places=4)

    def test_jayce_flag_off_no_resist_surfaced(self):
        off = self._ehp("Jayce", 16, False)
        self.assertEqual(off.passive_resist_armor, 0.0)
        self.assertEqual(off.passive_resist_mr, 0.0)

    def test_jayce_reported_armor_unchanged_by_grant(self):
        # The reported armor / MR stay the RESOLVED build stats; the grant is
        # surfaced via passive_resist_armor / _mr (not folded into the stat).
        off = self._ehp("Jayce", 16, False)
        on = self._ehp("Jayce", 16, True)
        self.assertEqual(on.armor, off.armor)
        self.assertEqual(on.mr, off.mr)

    def test_no_entry_champ_flag_on_byte_identical(self):
        # Caitlyn has no resist grant -> flag-on is byte-identical.
        off = self._ehp("Caitlyn", 16, False)
        on = self._ehp("Caitlyn", 16, True)
        self.assertEqual(on.blended_ehp, off.blended_ehp)
        self.assertEqual(on.passive_resist_armor, 0.0)


class ExclusionDocTests(unittest.TestCase):
    def test_remaining_exclusions_absent(self):
        cids = {k[0] for k in _PASSIVE_RESIST_OVERRIDES}
        # The 2 different-seam NEGATIVES that remain after item 272 (Thresh was the
        # per-stack-unbounded exclusion -> SEEDED per_stack by item 272):
        # Anivia (resurrection non-combat) / Orianna (ball-attached, rides an ally
        # not the caster).
        for c in ("Anivia", "Orianna"):
            self.assertNotIn(c, cids)

    def test_jayce_no_longer_excluded(self):
        cids = {k[0] for k in _PASSIVE_RESIST_OVERRIDES}
        self.assertIn("Jayce", cids)


class EngineVersionTests(unittest.TestCase):
    def test_engine_pin(self):
        import agents.daemon_slayer as ds

        self.assertEqual(ds.ENGINE_VERSION, "1.259.0")
        self.assertEqual(ENGINE_VERSION, "1.259.0")


class AsciiHygieneTests(unittest.TestCase):
    def test_module_and_test_ascii(self):
        import agents.daemon_slayer._passive_resist_overrides as mod

        for path in (mod.__file__, __file__):
            with open(path, "rb") as fh:
                raw = fh.read()
            self.assertEqual(raw, raw.decode("ascii", "strict").encode("ascii"))


if __name__ == "__main__":
    unittest.main()
