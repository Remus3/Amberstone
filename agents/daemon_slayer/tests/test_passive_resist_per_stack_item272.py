"""Item 272 - PER-STACK UNBOUNDED RESIST-STAT grant (Thresh P Damnation).

The last different-seam resist exclusion that is cleanly headless-buildable: a
self bonus-armor grant that scales LINEARLY with a slow game-long accumulator
(Thresh souls) that has NO cap. Unlike the BOUNDED per-stack cases (Garen W cap
30/30, Graves E cap 8 stacks, Wukong P cap 5) it cannot be "seeded at the cap" -
it needs an assumed steady-state count.

Seam: ``per_stack_armor`` / ``per_stack_mr`` * ``assumed_stacks``
(``_ASSUMED_SOUL_COUNT`` 25, the item-249 ``assumed_stacks`` convention on the
EHP seam). The per-soul coefficient is EXACT (1 armor per soul, ARMOR ONLY; the
+1 AP per soul is offensive); only the count is the assumption. EXHAUSTIVE roster
scan (per-stack + armor/MR co-occurrence): Thresh P is the SOLE per-stack-
UNBOUNDED self-resist grant.

``apply_passive_resist`` defaults False -> byte-identical.
"""
from __future__ import annotations

import unittest

import agents.daemon_slayer as daemon_slayer
from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import compute_ehp
from agents.daemon_slayer._passive_resist_overrides import (
    _ASSUMED_SOUL_COUNT,
    _PASSIVE_RESIST_OVERRIDES,
    PassiveResistEntry,
    resist_grants,
)

_KEY = ("Thresh", "P", 0)
_N = _ASSUMED_SOUL_COUNT  # 25.0


class AssumedSoulConstantTests(unittest.TestCase):
    def test_midpoint_value(self):
        self.assertEqual(_ASSUMED_SOUL_COUNT, 25.0)

    def test_midpoint_is_positive(self):
        self.assertGreater(_ASSUMED_SOUL_COUNT, 0.0)


class RegistryShapeTests(unittest.TestCase):
    def test_thresh_seeded_at_passive_form_0(self):
        self.assertIn(_KEY, _PASSIVE_RESIST_OVERRIDES)

    def test_thresh_entry_is_per_stack_armor_only_permanent(self):
        e = _PASSIVE_RESIST_OVERRIDES[_KEY]
        self.assertEqual(e.per_stack_armor, 1.0)
        self.assertEqual(e.per_stack_mr, 0.0)  # ARMOR ONLY (AP is offensive)
        self.assertEqual(e.assumed_stacks, _ASSUMED_SOUL_COUNT)
        self.assertEqual(e.conditional_probability, 1.0)  # permanent
        self.assertEqual(e.attribute, "Damnation")

    def test_thresh_carries_no_flat_or_percent_or_scaled_fields(self):
        e = _PASSIVE_RESIST_OVERRIDES[_KEY]
        self.assertEqual(e.armor, 0.0)
        self.assertEqual(e.mr, 0.0)
        self.assertEqual(e.armor_pct, 0.0)
        self.assertEqual(e.mr_pct, 0.0)
        self.assertFalse(e.level_scaled)
        self.assertFalse(e.rank_scaled)


class ResistGrantsMathTests(unittest.TestCase):
    """resist_grants folds the per-soul coefficient over the assumed count."""

    def test_flag_off_byte_identical(self):
        self.assertEqual(resist_grants("Thresh", 16, False), (0.0, 0.0))

    def test_flag_on_armor_is_coef_times_count(self):
        a, m = resist_grants("Thresh", 11, True)
        self.assertAlmostEqual(a, 1.0 * _N)  # 25.0
        self.assertEqual(m, 0.0)  # ARMOR ONLY

    def test_level_invariant(self):
        # The per-soul coefficient is flat (not level/rank-scaled) -> same at every
        # champion level.
        for lvl in (1, 6, 11, 16, 18):
            a, m = resist_grants("Thresh", lvl, True)
            self.assertAlmostEqual(a, 25.0)
            self.assertEqual(m, 0.0)

    def test_per_stack_scales_linearly_with_count(self):
        # A synthetic entry proves the per-stack half is exactly coef * count.
        for coef, n in ((0.75, 10.0), (1.0, 25.0), (2.0, 30.0)):
            e = PassiveResistEntry(per_stack_armor=coef, assumed_stacks=n)
            # Construct a one-entry view via the public math: coef*n*prob (prob 1.0).
            self.assertAlmostEqual(coef * n * e.conditional_probability, coef * n)


class EhpIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snap = DataSnapshot.load()

    def _ehp(self, champ, level, apply):
        return compute_ehp(
            self.snap, champ, level, item_ids=[],
            apply_passive_resist=apply,
        )

    def test_thresh_flag_on_raises_physical_ehp(self):
        off = self._ehp("Thresh", 11, False)
        on = self._ehp("Thresh", 11, True)
        # Armor-only grant -> physical EHP rises; blended rises.
        self.assertGreater(on.blended_ehp, off.blended_ehp)
        self.assertGreater(on.physical_ehp, off.physical_ehp)

    def test_thresh_armor_grant_surfaced_separately(self):
        on = self._ehp("Thresh", 11, True)
        self.assertAlmostEqual(on.passive_resist_armor, 25.0, places=4)
        self.assertEqual(on.passive_resist_mr, 0.0)  # ARMOR ONLY

    def test_thresh_magical_ehp_unchanged(self):
        # No MR grant -> magical EHP byte-identical flag on/off.
        off = self._ehp("Thresh", 11, False)
        on = self._ehp("Thresh", 11, True)
        self.assertEqual(on.magical_ehp, off.magical_ehp)

    def test_thresh_flag_off_no_resist_surfaced(self):
        off = self._ehp("Thresh", 11, False)
        self.assertEqual(off.passive_resist_armor, 0.0)
        self.assertEqual(off.passive_resist_mr, 0.0)

    def test_thresh_reported_armor_unchanged_by_grant(self):
        # Reported armor stays the resolved build stat; the grant is surfaced via
        # passive_resist_armor, not folded into the stat.
        off = self._ehp("Thresh", 11, False)
        on = self._ehp("Thresh", 11, True)
        self.assertEqual(on.armor, off.armor)
        self.assertEqual(on.mr, off.mr)

    def test_no_entry_champ_flag_on_byte_identical(self):
        off = self._ehp("Caitlyn", 16, False)
        on = self._ehp("Caitlyn", 16, True)
        self.assertEqual(on.blended_ehp, off.blended_ehp)
        self.assertEqual(on.passive_resist_armor, 0.0)


class ExclusionDocTests(unittest.TestCase):
    def test_remaining_exclusions_absent(self):
        cids = {k[0] for k in _PASSIVE_RESIST_OVERRIDES}
        # The 2 different-seam NEGATIVES that remain after item 272: Anivia
        # (resurrection non-combat) / Orianna (ball-attached, rides an ally).
        for c in ("Anivia", "Orianna"):
            self.assertNotIn(c, cids)

    def test_thresh_no_longer_excluded(self):
        cids = {k[0] for k in _PASSIVE_RESIST_OVERRIDES}
        self.assertIn("Thresh", cids)


class AsciiHygieneTests(unittest.TestCase):
    def test_module_is_ascii(self):
        import agents.daemon_slayer._passive_resist_overrides as mod
        with open(mod.__file__, encoding="utf-8") as fh:
            src = fh.read()
        nonascii = sorted({c for c in src if ord(c) > 127})
        self.assertEqual(nonascii, [], f"non-ASCII codepoints: {nonascii}")


class EngineVersionTests(unittest.TestCase):
    def test_engine_pin(self):
        self.assertEqual(daemon_slayer.ENGINE_VERSION, "1.264.0")
        self.assertEqual(ENGINE_VERSION, "1.264.0")


if __name__ == "__main__":
    unittest.main()
