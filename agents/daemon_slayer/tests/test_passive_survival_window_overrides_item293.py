"""Item 293 - effects-text GUARANTEED-SURVIVAL WINDOW registry.

The NINTH survivability axis and the SECOND EHP-NUMERATOR term (after the item
288 revive). A SELF window during which the champion cannot be damaged or killed
(untargetable / stasis / invulnerable) voids ALL incoming damage for its
duration, so it adds the avoided ``window_s / fight_window_s`` damage FRACTION to
the EHP numerator - the operator-chosen BOUNDED additive model (the revive
shape), capped at the whole fight, amortized by availability.

Seam: ``compute_ehp(apply_survival_window=...)`` multiplies the per-type EHP by
``survival_window_multiplier`` = ``1 + sum(min(window_s/_FIGHT_WINDOW_S, 1.0) *
prob)``. The window DURATION is EXACT from the ability text; only the availability
midpoint (ult 0.35 / basic 0.5) is the assumption. EXHAUSTIVE roster scan: 10
self windows (6 ults + 4 basics). ``apply_survival_window`` defaults False ->
byte-identical.
"""
from __future__ import annotations

import unittest

import agents.daemon_slayer as daemon_slayer
from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import compute_ehp, _FIGHT_WINDOW_S
from agents.daemon_slayer._passive_survival_window_overrides import (
    _PASSIVE_SURVIVAL_WINDOW_OVERRIDES,
    _SURVIVAL_WINDOW_ULT_PROB,
    _SURVIVAL_WINDOW_BASIC_PROB,
    SurvivalWindowEntry,
    survival_window_multiplier,
)
from agents.daemon_slayer._passive_revive_overrides import _PASSIVE_REVIVE_OVERRIDES

_SEED_CHAMPS = {
    "Tryndamere", "Kindred", "Taric", "Kayle", "Lissandra", "Xayah",
    "Vladimir", "Elise", "Fizz", "Mel",
}


class MidpointConstantTests(unittest.TestCase):
    def test_values(self):
        self.assertEqual(_SURVIVAL_WINDOW_ULT_PROB, 0.35)
        self.assertEqual(_SURVIVAL_WINDOW_BASIC_PROB, 0.5)

    def test_in_unit_range_and_basic_gt_ult(self):
        for p in (_SURVIVAL_WINDOW_ULT_PROB, _SURVIVAL_WINDOW_BASIC_PROB):
            self.assertGreater(p, 0.0)
            self.assertLess(p, 1.0)
        # A short-cooldown basic is up more often than a long-cooldown ult.
        self.assertGreater(_SURVIVAL_WINDOW_BASIC_PROB, _SURVIVAL_WINDOW_ULT_PROB)


class RegistryShapeTests(unittest.TestCase):
    def test_exactly_ten_entries_ten_champs(self):
        # EXHAUSTIVE scan: the clean self guaranteed-survival-window set is these 10.
        self.assertEqual(len(_PASSIVE_SURVIVAL_WINDOW_OVERRIDES), 10)
        self.assertEqual(
            {k[0] for k in _PASSIVE_SURVIVAL_WINDOW_OVERRIDES}, _SEED_CHAMPS
        )

    def test_elise_keyed_at_spider_form_e(self):
        # Rappel is the spider-form E (form_index 1), not the human-form E (a stun).
        self.assertIn(("Elise", "E", 1), _PASSIVE_SURVIVAL_WINDOW_OVERRIDES)
        self.assertNotIn(("Elise", "E", 0), _PASSIVE_SURVIVAL_WINDOW_OVERRIDES)

    def test_ult_basic_split_and_windows(self):
        ults = {"Tryndamere", "Kindred", "Taric", "Kayle", "Lissandra", "Xayah"}
        basics = {"Vladimir", "Elise", "Fizz", "Mel"}
        for (cid, _k, _f), e in _PASSIVE_SURVIVAL_WINDOW_OVERRIDES.items():
            self.assertGreater(e.window_s, 0.0)
            self.assertFalse(e.rank_scaled)
            self.assertFalse(e.level_scaled)
            if cid in ults:
                self.assertEqual(e.conditional_probability, _SURVIVAL_WINDOW_ULT_PROB)
            elif cid in basics:
                self.assertEqual(e.conditional_probability, _SURVIVAL_WINDOW_BASIC_PROB)

    def test_known_window_durations(self):
        win = {k: v.window_s for k, v in _PASSIVE_SURVIVAL_WINDOW_OVERRIDES.items()}
        self.assertEqual(win[("Tryndamere", "R", 0)], 5.0)
        self.assertEqual(win[("Kindred", "R", 0)], 4.0)
        self.assertEqual(win[("Vladimir", "W", 0)], 2.0)
        self.assertEqual(win[("Fizz", "E", 0)], 0.75)


class MultiplierMathTests(unittest.TestCase):
    def test_flag_off_is_identity(self):
        for c in ("Tryndamere", "Vladimir", "Caitlyn"):
            self.assertEqual(survival_window_multiplier(c, 11, False), 1.0)

    def test_tryndamere_5s_ult(self):
        # 1 + min(5/6,1)*0.35 = 1 + 0.833333*0.35.
        exp = 1.0 + (5.0 / _FIGHT_WINDOW_S) * _SURVIVAL_WINDOW_ULT_PROB
        self.assertAlmostEqual(
            survival_window_multiplier("Tryndamere", 11, True, _FIGHT_WINDOW_S),
            exp, places=6,
        )

    def test_vladimir_2s_basic(self):
        exp = 1.0 + (2.0 / _FIGHT_WINDOW_S) * _SURVIVAL_WINDOW_BASIC_PROB
        self.assertAlmostEqual(
            survival_window_multiplier("Vladimir", 11, True, _FIGHT_WINDOW_S),
            exp, places=6,
        )

    def test_fizz_075s_basic(self):
        exp = 1.0 + (0.75 / _FIGHT_WINDOW_S) * _SURVIVAL_WINDOW_BASIC_PROB
        self.assertAlmostEqual(
            survival_window_multiplier("Fizz", 11, True, _FIGHT_WINDOW_S),
            exp, places=6,
        )

    def test_every_seed_above_one(self):
        for c in _SEED_CHAMPS:
            self.assertGreater(survival_window_multiplier(c, 18, True), 1.0)

    def test_non_entry_champ_identity_on(self):
        for c in ("Caitlyn", "Garen", "Thresh", "Zed", "Shaco"):
            self.assertEqual(survival_window_multiplier(c, 16, True), 1.0)

    def test_window_fraction_capped_at_one(self):
        # A synthetic window longer than the fight voids the whole fight ONCE, not
        # more: min(window/fight, 1.0) caps the avoided fraction.
        e = SurvivalWindowEntry(window_s=100.0, conditional_probability=1.0)
        capped = min(e.window_s / _FIGHT_WINDOW_S, 1.0) * e.conditional_probability
        self.assertEqual(capped, 1.0)

    def test_default_fight_window_when_nonpositive(self):
        # A non-positive fight window falls back to the 6.0 default (no div-by-zero).
        self.assertAlmostEqual(
            survival_window_multiplier("Fizz", 11, True, 0.0),
            survival_window_multiplier("Fizz", 11, True, 6.0),
            places=9,
        )


class EhpIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snap = DataSnapshot.load()

    def _ehp(self, champ, level, apply):
        return compute_ehp(
            self.snap, champ, level, item_ids=[], apply_survival_window=apply
        )

    def test_flag_on_scales_every_axis_uniformly(self):
        off = self._ehp("Tryndamere", 11, False)
        on = self._ehp("Tryndamere", 11, True)
        mult = survival_window_multiplier("Tryndamere", 11, True, _FIGHT_WINDOW_S)
        self.assertGreater(mult, 1.0)
        self.assertAlmostEqual(on.physical_ehp, off.physical_ehp * mult, places=3)
        self.assertAlmostEqual(on.magical_ehp, off.magical_ehp * mult, places=3)
        self.assertAlmostEqual(on.true_ehp, off.true_ehp * mult, places=3)
        self.assertAlmostEqual(on.blended_ehp, off.blended_ehp * mult, places=3)

    def test_survival_window_mult_surfaced(self):
        on = self._ehp("Vladimir", 11, True)
        exp = survival_window_multiplier("Vladimir", 11, True, _FIGHT_WINDOW_S)
        self.assertAlmostEqual(on.survival_window_mult, exp, places=6)

    def test_reported_stats_unchanged(self):
        off = self._ehp("Tryndamere", 11, False)
        on = self._ehp("Tryndamere", 11, True)
        self.assertEqual(on.hp, off.hp)
        self.assertEqual(on.armor, off.armor)
        self.assertEqual(on.mr, off.mr)

    def test_flag_off_byte_identical_and_no_mult(self):
        off = self._ehp("Tryndamere", 11, False)
        self.assertEqual(off.survival_window_mult, 1.0)
        default = compute_ehp(self.snap, "Tryndamere", 11, item_ids=[])
        self.assertEqual(default.blended_ehp, off.blended_ehp)
        self.assertEqual(default.survival_window_mult, 1.0)

    def test_non_entry_champ_flag_on_byte_identical(self):
        off = self._ehp("Caitlyn", 16, False)
        on = self._ehp("Caitlyn", 16, True)
        self.assertEqual(on.blended_ehp, off.blended_ehp)
        self.assertEqual(on.survival_window_mult, 1.0)

    def test_to_dict_carries_mult(self):
        on = self._ehp("Fizz", 11, True)
        exp = survival_window_multiplier("Fizz", 11, True, _FIGHT_WINDOW_S)
        self.assertAlmostEqual(on.to_dict()["survival_window_mult"], exp, places=6)

    def test_composes_with_revive_independently(self):
        # The window multiplier and the revive multiplier are SEPARATE flags; one on
        # does not enable the other (Anivia has a revive, no survival window).
        on_win = compute_ehp(
            self.snap, "Anivia", 11, item_ids=[], apply_survival_window=True
        )
        self.assertEqual(on_win.survival_window_mult, 1.0)  # no window for Anivia
        self.assertEqual(on_win.passive_revive_mult, 1.0)   # revive flag still off


class ExclusionDocTests(unittest.TestCase):
    def setUp(self):
        self.cids = {k[0] for k in _PASSIVE_SURVIVAL_WINDOW_OVERRIDES}

    def test_offensive_dash_untargetability_excluded(self):
        # Cast-bound offensive dash / strike untargetability is a byproduct of an
        # offensive ability, not a deployable defensive window.
        for c in ("Zed", "Camille", "MasterYi", "Maokai", "Evelynn", "Galio", "Sion"):
            self.assertNotIn(c, self.cids)

    def test_pet_clone_untargetability_excluded(self):
        for c in ("Shaco", "MonkeyKing", "Azir", "Caitlyn", "Lulu", "Neeko"):
            self.assertNotIn(c, self.cids)

    def test_post_death_frenzy_excluded(self):
        # The post-death stasis / untargetable always ends in death (item 288 class).
        for c in ("Karthus", "KogMaw"):
            self.assertNotIn(c, self.cids)

    def test_revive_domain_excluded(self):
        # Zac P's untargetable is the egg state of its item-288 REVIVE; Zilean R is
        # an ally revive; Kayn P is a one-time transform.
        for c in ("Zac", "Zilean", "Kayn"):
            self.assertNotIn(c, self.cids)
        # And Zac is in the revive registry, not this one.
        self.assertIn("Zac", {k[0] for k in _PASSIVE_REVIVE_OVERRIDES})

    def test_ally_or_enemy_applied_excluded(self):
        for c in ("Kalista", "TahmKench", "Urgot", "Poppy", "Bard"):
            self.assertNotIn(c, self.cids)

    def test_conditional_positional_invuln_excluded(self):
        # Xin Zhao R (invuln only vs far enemies), Pantheon E (directional), Gwen W
        # (untargetable only outside the mist) are positional, not clean windows.
        for c in ("XinZhao", "Pantheon", "Gwen"):
            self.assertNotIn(c, self.cids)

    def test_sustained_attach_state_excluded(self):
        # Yuumi W is untargetable for most of the game while attached - not a finite
        # cooldown-gated window.
        self.assertNotIn("Yuumi", self.cids)


class AsciiHygieneTests(unittest.TestCase):
    def test_module_is_ascii(self):
        import agents.daemon_slayer._passive_survival_window_overrides as mod
        with open(mod.__file__, encoding="utf-8") as fh:
            src = fh.read()
        nonascii = sorted({c for c in src if ord(c) > 127})
        self.assertEqual(nonascii, [], f"non-ASCII codepoints: {nonascii}")


class EngineVersionTests(unittest.TestCase):
    def test_engine_pin(self):
        self.assertEqual(daemon_slayer.ENGINE_VERSION, "1.138.0")
        self.assertEqual(ENGINE_VERSION, "1.138.0")


if __name__ == "__main__":
    unittest.main()
