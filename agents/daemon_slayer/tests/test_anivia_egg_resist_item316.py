"""Item 316 - Anivia Rebirth EGG-STATE resist seam.

The SIXTH survivability seam: the death-triggered second-life pool (Anivia P
Rebirth, item 288) must survive the resurrection EGG, which fights through
MODIFIED resists (-40:20 by level bonus armor + MR). This module adds
``egg_resist_armor`` / ``egg_resist_mr`` fields to PassiveReviveEntry, seeds
the Anivia entry with the per-level tuples, and exposes ``revive_egg_resist``
which compute_ehp consumes via the ``apply_egg_resist`` flag. Item 321
(2026-06-06, ENGINE 1.120.0) flipped that flag default False -> True
(default-ON cutover); pass False to recover the item-288 scalar path.

The egg resist reshapes the SELF-REVIVE EXTRA (``revive_mult - 1``) per damage
type; true EHP is unchanged (true damage ignores resists); ally revive +
survival-window stay multiplicative on the whole.
"""
from __future__ import annotations

import unittest

import agents.daemon_slayer as daemon_slayer
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import compute_ehp
from agents.daemon_slayer._passive_revive_overrides import (
    _PASSIVE_REVIVE_OVERRIDES,
    _REVIVE_PROB,
    revive_egg_resist,
)

_ANIVIA = ("Anivia", "P", 0)
_ZAC = ("Zac", "P", 0)


class RegistryShapeTests(unittest.TestCase):
    def test_anivia_egg_resist_armor_is_tuple(self):
        e = _PASSIVE_REVIVE_OVERRIDES[_ANIVIA]
        self.assertIsInstance(e.egg_resist_armor, tuple)

    def test_anivia_egg_resist_mr_is_tuple(self):
        e = _PASSIVE_REVIVE_OVERRIDES[_ANIVIA]
        self.assertIsInstance(e.egg_resist_mr, tuple)

    def test_anivia_egg_resist_armor_l1_is_minus40(self):
        e = _PASSIVE_REVIVE_OVERRIDES[_ANIVIA]
        self.assertAlmostEqual(e.egg_resist_armor[0], -40.0, places=3)

    def test_anivia_egg_resist_armor_l18_is_plus20(self):
        e = _PASSIVE_REVIVE_OVERRIDES[_ANIVIA]
        self.assertAlmostEqual(e.egg_resist_armor[-1], 20.0, places=3)

    def test_anivia_egg_resist_mr_l1_is_minus40(self):
        e = _PASSIVE_REVIVE_OVERRIDES[_ANIVIA]
        self.assertAlmostEqual(e.egg_resist_mr[0], -40.0, places=3)

    def test_anivia_egg_resist_mr_l18_is_plus20(self):
        e = _PASSIVE_REVIVE_OVERRIDES[_ANIVIA]
        self.assertAlmostEqual(e.egg_resist_mr[-1], 20.0, places=3)

    def test_zac_egg_resist_armor_is_zero_float(self):
        e = _PASSIVE_REVIVE_OVERRIDES[_ZAC]
        self.assertEqual(e.egg_resist_armor, 0.0)

    def test_zac_egg_resist_mr_is_zero_float(self):
        e = _PASSIVE_REVIVE_OVERRIDES[_ZAC]
        self.assertEqual(e.egg_resist_mr, 0.0)


class ReviveEggResistFunctionTests(unittest.TestCase):
    def test_flag_off_returns_zero_zero_for_anivia(self):
        self.assertEqual(revive_egg_resist("Anivia", 11, False), (0.0, 0.0))

    def test_flag_off_returns_zero_zero_for_zac(self):
        self.assertEqual(revive_egg_resist("Zac", 11, False), (0.0, 0.0))

    def test_flag_off_returns_zero_zero_for_non_entry(self):
        self.assertEqual(revive_egg_resist("Caitlyn", 11, False), (0.0, 0.0))

    def test_anivia_on_level1_returns_minus40_minus40(self):
        armor, mr = revive_egg_resist("Anivia", 1, True)
        self.assertAlmostEqual(armor, -40.0, places=3)
        self.assertAlmostEqual(mr, -40.0, places=3)

    def test_anivia_on_level18_returns_plus20_plus20(self):
        armor, mr = revive_egg_resist("Anivia", 18, True)
        self.assertAlmostEqual(armor, 20.0, places=3)
        self.assertAlmostEqual(mr, 20.0, places=3)

    def test_anivia_armor_series_monotonic_nondecreasing(self):
        vals = [revive_egg_resist("Anivia", lvl, True)[0] for lvl in range(1, 19)]
        self.assertEqual(vals, sorted(vals))

    def test_anivia_mr_series_monotonic_nondecreasing(self):
        vals = [revive_egg_resist("Anivia", lvl, True)[1] for lvl in range(1, 19)]
        self.assertEqual(vals, sorted(vals))

    def test_zac_on_returns_zero_zero(self):
        for lvl in (1, 9, 18):
            self.assertEqual(revive_egg_resist("Zac", lvl, True), (0.0, 0.0))

    def test_non_entry_champ_on_returns_zero_zero(self):
        self.assertEqual(revive_egg_resist("Caitlyn", 11, True), (0.0, 0.0))


class EhpIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snap = DataSnapshot.load()

    def _ehp(self, champ, level, **kw):
        return compute_ehp(self.snap, champ, level, item_ids=[], **kw)

    def test_default_now_matches_explicit_true(self):
        # ITEM 321 (2026-06-06): apply_egg_resist default flipped False -> True
        # (egg-resist default-ON cutover, ENGINE 1.120.0). Omitting the flag
        # now equals explicit True - the egg-state resist reshapes the
        # self-revive extra by default.
        explicit_on = self._ehp(
            "Anivia", 11, apply_passive_revive=True, apply_egg_resist=True
        )
        default_on = self._ehp("Anivia", 11, apply_passive_revive=True)
        self.assertEqual(explicit_on.physical_ehp, default_on.physical_ehp)
        self.assertEqual(explicit_on.magical_ehp, default_on.magical_ehp)
        self.assertEqual(explicit_on.true_ehp, default_on.true_ehp)
        self.assertEqual(explicit_on.blended_ehp, default_on.blended_ehp)

    def test_no_revive_egg_on_is_byte_identical_to_no_revive_egg_off(self):
        # apply_passive_revive False + apply_egg_resist True ->
        # no revive extra -> same as both False (no second life to reshape).
        both_off = self._ehp(
            "Anivia", 11, apply_passive_revive=False, apply_egg_resist=False
        )
        revive_off_egg_on = self._ehp(
            "Anivia", 11, apply_passive_revive=False, apply_egg_resist=True
        )
        self.assertEqual(both_off.physical_ehp, revive_off_egg_on.physical_ehp)
        self.assertEqual(both_off.magical_ehp, revive_off_egg_on.magical_ehp)
        self.assertEqual(both_off.true_ehp, revive_off_egg_on.true_ehp)

    def test_anivia_level1_egg_on_phys_mag_strictly_less_than_egg_off(self):
        # Level 1: egg has -40 bonus armor/MR -> harder to survive egg -> lower
        # physical + magical EHP vs egg-off.
        egg_off = self._ehp(
            "Anivia", 1, apply_passive_revive=True, apply_egg_resist=False
        )
        egg_on = self._ehp(
            "Anivia", 1, apply_passive_revive=True, apply_egg_resist=True
        )
        self.assertLess(egg_on.physical_ehp, egg_off.physical_ehp)
        self.assertLess(egg_on.magical_ehp, egg_off.magical_ehp)

    def test_anivia_level1_egg_on_true_ehp_unchanged_vs_egg_off(self):
        # True damage ignores resists; the egg resist never reshapes true EHP.
        egg_off = self._ehp(
            "Anivia", 1, apply_passive_revive=True, apply_egg_resist=False
        )
        egg_on = self._ehp(
            "Anivia", 1, apply_passive_revive=True, apply_egg_resist=True
        )
        self.assertAlmostEqual(egg_on.true_ehp, egg_off.true_ehp, places=6)

    def test_anivia_level18_egg_on_phys_mag_strictly_greater_than_egg_off(self):
        # Level 18: egg has +20 bonus armor/MR -> easier to survive egg -> higher
        # physical + magical EHP vs egg-off.
        egg_off = self._ehp(
            "Anivia", 18, apply_passive_revive=True, apply_egg_resist=False
        )
        egg_on = self._ehp(
            "Anivia", 18, apply_passive_revive=True, apply_egg_resist=True
        )
        self.assertGreater(egg_on.physical_ehp, egg_off.physical_ehp)
        self.assertGreater(egg_on.magical_ehp, egg_off.magical_ehp)

    def test_anivia_level18_egg_on_true_ehp_unchanged_vs_egg_off(self):
        egg_off = self._ehp(
            "Anivia", 18, apply_passive_revive=True, apply_egg_resist=False
        )
        egg_on = self._ehp(
            "Anivia", 18, apply_passive_revive=True, apply_egg_resist=True
        )
        self.assertAlmostEqual(egg_on.true_ehp, egg_off.true_ehp, places=6)

    def test_zac_egg_on_byte_identical_to_egg_off(self):
        # Zac has no egg resist (0.0 deltas) -> unchanged by the flag.
        egg_off = self._ehp(
            "Zac", 11, apply_passive_revive=True, apply_egg_resist=False
        )
        egg_on = self._ehp(
            "Zac", 11, apply_passive_revive=True, apply_egg_resist=True
        )
        self.assertEqual(egg_on.physical_ehp, egg_off.physical_ehp)
        self.assertEqual(egg_on.magical_ehp, egg_off.magical_ehp)
        self.assertEqual(egg_on.true_ehp, egg_off.true_ehp)

    def test_passive_revive_mult_unchanged_by_egg_flag(self):
        # The egg effect lives in the per-type EHP, not in the surfaced
        # passive_revive_mult scalar (which is still 1 + 1.0 * 0.4 = 1.4).
        egg_off = self._ehp(
            "Anivia", 11, apply_passive_revive=True, apply_egg_resist=False
        )
        egg_on = self._ehp(
            "Anivia", 11, apply_passive_revive=True, apply_egg_resist=True
        )
        self.assertAlmostEqual(egg_off.passive_revive_mult, 1.0 + _REVIVE_PROB, places=4)
        self.assertAlmostEqual(egg_on.passive_revive_mult, 1.0 + _REVIVE_PROB, places=4)


class AsciiHygieneTests(unittest.TestCase):
    def test_module_is_ascii(self):
        import agents.daemon_slayer._passive_revive_overrides as mod
        with open(mod.__file__, encoding="utf-8") as fh:
            src = fh.read()
        nonascii = sorted({c for c in src if ord(c) > 127})
        self.assertEqual(nonascii, [], f"non-ASCII codepoints: {nonascii}")


class EngineVersionTests(unittest.TestCase):
    def test_engine_pin(self):
        self.assertEqual(daemon_slayer.ENGINE_VERSION, "1.176.0")


if __name__ == "__main__":
    unittest.main()
