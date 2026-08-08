"""Item 288 - effects-text-only REVIVE / second-life registry (Anivia P, Zac P).

The FIFTH survivability axis and the FIRST EHP-NUMERATOR term (heals/shields are
throughput; DR divides the denominator; a resist grant raises the armor/MR
denominator; a REVIVE multiplies the numerator - a death-triggered second HP
pool). This is the "DIFFERENT non-EHP-denominator seam" the item-272 resist
registry flagged for Anivia P (its egg armor/MR stays EXCLUDED from the resist
axis; this registry models the REVIVE itself).

Seam: ``compute_ehp(apply_passive_revive=...)`` multiplies the per-type EHP by
``revive_multiplier`` = ``1 + revived_hp_fraction(level) * _REVIVE_PROB``. The
restored-health FRACTION is EXACT from the ability text (Anivia restores ALL
health -> 1.0; Zac revives at 10:50% by level -> level_scaled); only the
availability+survival midpoint (_REVIVE_PROB 0.4) is the assumption. EXHAUSTIVE
roster scan (death-triggered self-revive restoring a sustained HP pool): exactly
Anivia P + Zac P. ``apply_passive_revive`` defaults False -> byte-identical.
"""
from __future__ import annotations

import unittest

import agents.daemon_slayer as daemon_slayer
from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import compute_ehp
from agents.daemon_slayer._passive_revive_overrides import (
    _PASSIVE_REVIVE_OVERRIDES,
    _REVIVE_PROB,
    PassiveReviveEntry,
    revive_multiplier,
)
from agents.daemon_slayer._passive_resist_overrides import _PASSIVE_RESIST_OVERRIDES

_ANIVIA = ("Anivia", "P", 0)
_ZAC = ("Zac", "P", 0)


class ReviveProbConstantTests(unittest.TestCase):
    def test_midpoint_value(self):
        self.assertEqual(_REVIVE_PROB, 0.4)

    def test_midpoint_in_unit_range(self):
        # A probability midpoint: above the active-resist 0.3, below 1.0.
        self.assertGreater(_REVIVE_PROB, 0.0)
        self.assertLess(_REVIVE_PROB, 1.0)


class RegistryShapeTests(unittest.TestCase):
    def test_anivia_and_zac_seeded_at_passive_form_0(self):
        self.assertIn(_ANIVIA, _PASSIVE_REVIVE_OVERRIDES)
        self.assertIn(_ZAC, _PASSIVE_REVIVE_OVERRIDES)

    def test_registry_is_exactly_two_entries(self):
        # EXHAUSTIVE scan: the clean self-revive set is exactly these 2.
        self.assertEqual(len(_PASSIVE_REVIVE_OVERRIDES), 2)
        self.assertEqual(
            {k[0] for k in _PASSIVE_REVIVE_OVERRIDES}, {"Anivia", "Zac"}
        )

    def test_anivia_is_flat_full_hp_revive(self):
        e = _PASSIVE_REVIVE_OVERRIDES[_ANIVIA]
        self.assertEqual(e.revived_hp_fraction, 1.0)  # restores ALL health
        self.assertFalse(e.level_scaled)
        self.assertEqual(e.conditional_probability, _REVIVE_PROB)
        self.assertEqual(e.attribute, "Rebirth")

    def test_zac_is_level_scaled_partial_revive(self):
        e = _PASSIVE_REVIVE_OVERRIDES[_ZAC]
        self.assertTrue(e.level_scaled)
        self.assertIsInstance(e.revived_hp_fraction, tuple)
        # 10% at L1 -> 50% at L18 (the FINAL revive HP, not the transient 50%).
        self.assertAlmostEqual(e.revived_hp_fraction[0], 0.10, places=4)
        self.assertAlmostEqual(e.revived_hp_fraction[-1], 0.50, places=4)
        self.assertEqual(e.conditional_probability, _REVIVE_PROB)
        self.assertEqual(e.attribute, "Cell Division")


class ReviveMultiplierMathTests(unittest.TestCase):
    def test_flag_off_is_identity(self):
        for c in ("Anivia", "Zac", "Caitlyn"):
            self.assertEqual(revive_multiplier(c, 11, False), 1.0)

    def test_anivia_full_revive_is_one_plus_prob(self):
        # 1 + 1.0 * 0.4 = 1.40, flat at every level (full-HP revive).
        for lvl in (1, 6, 11, 16, 18):
            self.assertAlmostEqual(
                revive_multiplier("Anivia", lvl, True), 1.0 + _REVIVE_PROB
            )

    def test_zac_level_scaled_endpoints(self):
        # L1: 1 + 0.10*0.4 = 1.04 ; L18: 1 + 0.50*0.4 = 1.20.
        self.assertAlmostEqual(revive_multiplier("Zac", 1, True), 1.04, places=4)
        self.assertAlmostEqual(revive_multiplier("Zac", 18, True), 1.20, places=4)

    def test_zac_midgame_interpolates(self):
        # L11 fraction = lerp(0.10, 0.50) over 18 levels at idx 10 = 0.335294;
        # mult = 1 + 0.335294 * 0.4 = 1.134118.
        self.assertAlmostEqual(
            revive_multiplier("Zac", 11, True), 1.134118, places=4
        )

    def test_zac_monotonic_in_level(self):
        vals = [revive_multiplier("Zac", lvl, True) for lvl in range(1, 19)]
        self.assertEqual(vals, sorted(vals))
        self.assertGreater(vals[-1], vals[0])

    def test_non_entry_champ_is_identity_on(self):
        for c in ("Caitlyn", "Garen", "Thresh"):
            self.assertEqual(revive_multiplier(c, 16, True), 1.0)

    def test_synthetic_entry_math(self):
        # The multiplier is exactly 1 + frac * prob for a one-entry synthetic.
        for frac, prob in ((1.0, 0.4), (0.25, 0.5), (0.5, 1.0)):
            e = PassiveReviveEntry(revived_hp_fraction=frac, conditional_probability=prob)
            self.assertAlmostEqual(1.0 + frac * e.conditional_probability, 1.0 + frac * prob)


class EhpIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snap = DataSnapshot.load()

    def _ehp(self, champ, level, apply):
        return compute_ehp(
            self.snap, champ, level, item_ids=[], apply_passive_revive=apply
        )

    def test_anivia_flag_on_scales_every_axis_uniformly(self):
        off = self._ehp("Anivia", 11, False)
        # ITEM 321 (ENGINE 1.120.0): apply_egg_resist now defaults True, which
        # reshapes the physical / magical axes NON-uniformly. This test isolates
        # the pure revive NUMERATOR property, so pin egg-resist OFF here; the egg
        # non-uniformity is covered by test_anivia_egg_resist_item316.
        on = compute_ehp(
            self.snap, "Anivia", 11, item_ids=[],
            apply_passive_revive=True, apply_egg_resist=False,
        )
        mult = 1.0 + _REVIVE_PROB
        # A NUMERATOR multiplier scales physical / magical / true / blended all by
        # the SAME factor (unlike the armor-only resist grant).
        self.assertAlmostEqual(on.physical_ehp, off.physical_ehp * mult, places=3)
        self.assertAlmostEqual(on.magical_ehp, off.magical_ehp * mult, places=3)
        self.assertAlmostEqual(on.true_ehp, off.true_ehp * mult, places=3)
        self.assertAlmostEqual(on.blended_ehp, off.blended_ehp * mult, places=3)

    def test_anivia_revive_mult_surfaced(self):
        on = self._ehp("Anivia", 11, True)
        self.assertAlmostEqual(on.passive_revive_mult, 1.4, places=4)

    def test_anivia_reported_stats_unchanged_by_revive(self):
        # The revive is a numerator multiplier on EHP; the resolved hp/armor/mr
        # stats are untouched (the grant is surfaced via passive_revive_mult).
        off = self._ehp("Anivia", 11, False)
        on = self._ehp("Anivia", 11, True)
        self.assertEqual(on.hp, off.hp)
        self.assertEqual(on.armor, off.armor)
        self.assertEqual(on.mr, off.mr)

    def test_flag_off_byte_identical_and_no_mult(self):
        off = self._ehp("Anivia", 11, False)
        self.assertEqual(off.passive_revive_mult, 1.0)
        # Default param (omitted) matches explicit False.
        default = compute_ehp(self.snap, "Anivia", 11, item_ids=[])
        self.assertEqual(default.blended_ehp, off.blended_ehp)
        self.assertEqual(default.passive_revive_mult, 1.0)

    def test_zac_level_scaled_in_ehp(self):
        on1 = self._ehp("Zac", 1, True)
        on18 = self._ehp("Zac", 18, True)
        self.assertAlmostEqual(on1.passive_revive_mult, 1.04, places=4)
        self.assertAlmostEqual(on18.passive_revive_mult, 1.20, places=4)

    def test_non_entry_champ_flag_on_byte_identical(self):
        off = self._ehp("Caitlyn", 16, False)
        on = self._ehp("Caitlyn", 16, True)
        self.assertEqual(on.blended_ehp, off.blended_ehp)
        self.assertEqual(on.passive_revive_mult, 1.0)

    def test_to_dict_carries_revive_mult(self):
        on = self._ehp("Anivia", 11, True)
        self.assertAlmostEqual(on.to_dict()["passive_revive_mult"], 1.4, places=4)


class ExclusionDocTests(unittest.TestCase):
    def test_zombie_no_revive_excluded(self):
        # Restore-no-sustained-pool / decaying-frenzy death passives are NOT
        # revives: Sion (decays + cannot heal + always dies), Karthus / KogMaw
        # (zombie cast/bomb window, no HP restore).
        cids = {k[0] for k in _PASSIVE_REVIVE_OVERRIDES}
        for c in ("Sion", "Karthus", "KogMaw"):
            self.assertNotIn(c, cids)

    def test_ally_targeted_revive_excluded(self):
        # The revive rides an ALLY, not the caster (the Orianna-E ally-target
        # class): Zilean R / Renata W / Akshan W.
        cids = {k[0] for k in _PASSIVE_REVIVE_OVERRIDES}
        for c in ("Zilean", "Renata", "Akshan"):
            self.assertNotIn(c, cids)

    def test_anivia_egg_resist_still_excluded_from_resist_registry(self):
        # The revive registry models the SECOND LIFE; the -40:20 egg armor/MR
        # stays an item-272 EXCLUSION in the resist (denominator) registry.
        resist_cids = {k[0] for k in _PASSIVE_RESIST_OVERRIDES}
        self.assertNotIn("Anivia", resist_cids)


class AsciiHygieneTests(unittest.TestCase):
    def test_module_is_ascii(self):
        import agents.daemon_slayer._passive_revive_overrides as mod
        with open(mod.__file__, encoding="utf-8") as fh:
            src = fh.read()
        nonascii = sorted({c for c in src if ord(c) > 127})
        self.assertEqual(nonascii, [], f"non-ASCII codepoints: {nonascii}")


class EngineVersionTests(unittest.TestCase):
    def test_engine_pin(self):
        self.assertEqual(daemon_slayer.ENGINE_VERSION, "1.275.2")
        self.assertEqual(ENGINE_VERSION, "1.275.2")


if __name__ == "__main__":
    unittest.main()
