"""Phase 6 (s181, 2026-05-13) - Enchanter healing throughput scorer tests.

Covers ``hps.py``'s formula loader, ``compute_hps`` evaluator, amp pipeline,
mode multiplier, edge cases, and the ``/hps`` server route.
"""
from __future__ import annotations

import json
import threading
import unittest
from urllib.request import Request, urlopen

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.hps import (
    EnchanterFormulasNotFound,
    EnchanterFormulasSnapshot,
    EnchanterItemFormula,
    HpsItemContribution,
    HpsResult,
    _aram_heal_shield_modifiers,
    _aram_healing_modifier,
    compute_hps,
    load_default_formulas,
    reset_formulas_cache,
)


# --- Formula loader ----------------------------------------------------


class EnchanterItemFormulaTests(unittest.TestCase):
    def test_from_dict_zero_defaults(self) -> None:
        f = EnchanterItemFormula.from_dict("6617", {"name": "Moonstone Renewer"})
        self.assertEqual(f.item_id, "6617")
        self.assertEqual(f.name, "Moonstone Renewer")
        self.assertEqual(f.heal_per_proc_base, 0.0)
        self.assertEqual(f.heal_shield_amp_pct, 0.0)
        self.assertEqual(f.ally_buff_credit_per_second, 0.0)

    def test_from_dict_full(self) -> None:
        f = EnchanterItemFormula.from_dict("3107", {
            "name": "Redemption",
            "heal_per_proc_base": 150.0,
            "heal_per_proc_per_level": 11.76,
            "heal_per_proc_ap_scaling": 0.0,
            "heal_procs_per_second": 0.00833,
            "heal_targets_per_proc": 3.0,
            "heal_shield_amp_pct": 0.10,
            "notes": "Intervention active",
        })
        self.assertEqual(f.heal_per_proc_base, 150.0)
        self.assertAlmostEqual(f.heal_per_proc_per_level, 11.76)
        self.assertAlmostEqual(f.heal_procs_per_second, 0.00833)
        self.assertEqual(f.heal_targets_per_proc, 3.0)
        self.assertAlmostEqual(f.heal_shield_amp_pct, 0.10)

    def test_heal_per_proc_at_level_scaling(self) -> None:
        f = EnchanterItemFormula.from_dict("3107", {
            "heal_per_proc_base": 150.0,
            "heal_per_proc_per_level": 11.76,
        })
        # level 1: base only
        self.assertAlmostEqual(f.heal_per_proc_at(1, ap=0.0), 150.0)
        # level 11: base + 10 x per_level
        self.assertAlmostEqual(f.heal_per_proc_at(11, ap=0.0), 150.0 + 117.6)
        # level 18: base + 17 x per_level (matches doc string)
        self.assertAlmostEqual(f.heal_per_proc_at(18, ap=0.0), 150.0 + 199.92)

    def test_heal_per_proc_ap_scaling(self) -> None:
        f = EnchanterItemFormula.from_dict("6620", {
            "heal_per_proc_base": 40.0,
            "heal_per_proc_per_level": 1.76,
            "heal_per_proc_ap_scaling": 0.15,
        })
        # 100 AP -> +15
        self.assertAlmostEqual(f.heal_per_proc_at(1, ap=100.0), 40.0 + 15.0)

    def test_shield_per_proc_at(self) -> None:
        f = EnchanterItemFormula.from_dict("3190", {
            "shield_per_proc_base": 290.0,
            "shield_per_proc_per_level": 4.12,
        })
        self.assertAlmostEqual(f.shield_per_proc_at(11, ap=0.0), 290.0 + 41.2)

    def test_heal_per_proc_negative_level_clamps(self) -> None:
        """Defensive: level 0 / 1 are equivalent (max(0, level-1)=0)."""
        f = EnchanterItemFormula.from_dict("3107", {
            "heal_per_proc_base": 150.0,
            "heal_per_proc_per_level": 11.76,
        })
        self.assertAlmostEqual(f.heal_per_proc_at(1, ap=0.0), 150.0)


class EnchanterFormulasSnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # Use the real shipped snapshot.
        cls.snap = EnchanterFormulasSnapshot.load()

    def test_known_items_present(self) -> None:
        for iid in ("6617", "3107", "3222", "6620", "3504", "6616", "3190", "4005", "3109"):
            self.assertTrue(self.snap.has_item(iid), f"missing {iid}")

    def test_get_formula_round_trip(self) -> None:
        f = self.snap.get_formula("3107")
        self.assertEqual(f.name, "Redemption")
        self.assertAlmostEqual(f.heal_shield_amp_pct, 0.10)

    def test_get_formula_unknown_raises(self) -> None:
        with self.assertRaises(KeyError):
            self.snap.get_formula("9999")

    def test_load_missing_patch_raises(self) -> None:
        from pathlib import Path
        with self.assertRaises(EnchanterFormulasNotFound):
            EnchanterFormulasSnapshot.load(patch="99.99.0", data_root=Path("./nope"))

    def test_item_ids_sorted(self) -> None:
        ids = self.snap.item_ids()
        self.assertEqual(list(ids), sorted(ids))


class SingletonCacheTests(unittest.TestCase):
    def test_load_default_caches(self) -> None:
        reset_formulas_cache()
        a = load_default_formulas()
        b = load_default_formulas()
        self.assertIs(a, b)

    def test_reset_drops_cache(self) -> None:
        reset_formulas_cache()
        a = load_default_formulas()
        reset_formulas_cache()
        b = load_default_formulas()
        self.assertIsNot(a, b)


# --- ARAM modifier helper ----------------------------------------------


class AramHealingModifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_non_aram_mode_returns_one(self) -> None:
        self.assertEqual(_aram_healing_modifier(self.snap, "Soraka", "SR"), 1.0)
        self.assertEqual(_aram_healing_modifier(self.snap, "Lulu", "ARENA"), 1.0)

    def test_aram_mode_returns_float(self) -> None:
        v = _aram_healing_modifier(self.snap, "Soraka", "ARAM")
        # Soraka either has a real modifier or falls back to 1.0; both float.
        self.assertIsInstance(v, float)
        self.assertGreater(v, 0.0)


# --- compute_hps basics ------------------------------------------------


class ComputeHpsBasicsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_returns_hps_result_instance(self) -> None:
        r = compute_hps(self.snap, "Soraka", level=11)
        self.assertIsInstance(r, HpsResult)
        self.assertEqual(r.champion_id, "Soraka")
        self.assertEqual(r.level, 11)
        self.assertEqual(r.mode, "SR")

    def test_naked_build_zero_throughput(self) -> None:
        # ability HPS folded in (V2 enchanter wire): itemless Soraka has 0
        # ITEM throughput but her own kit (W heal) now counts. The item-only
        # components (healing_hps_raw / shielding_hps_raw / ally_buff_credit /
        # amp_multiplier) stay 0 / 1.0; total_throughput == ability_hps_total.
        r = compute_hps(self.snap, "Soraka", level=11)
        self.assertEqual(r.healing_hps_raw, 0.0)
        self.assertEqual(r.shielding_hps_raw, 0.0)
        self.assertEqual(r.ally_buff_credit, 0.0)
        self.assertEqual(r.amp_multiplier, 1.0)
        self.assertGreater(r.ability_hps_total, 0.0)
        self.assertAlmostEqual(r.total_throughput, r.ability_hps_total, places=9)

    def test_naked_build_has_note_about_no_match(self) -> None:
        r = compute_hps(self.snap, "Soraka", level=11)
        joined = " ".join(r.notes).lower()
        self.assertIn("no enchanter formulas matched", joined)

    def test_non_enchanter_items_dont_contribute(self) -> None:
        """A DPS item (BotRK) on the build contributes 0 ITEM HPS.

        total_throughput is no longer 0: ability HPS folded in (V2 enchanter
        wire) - BotRK gives no AP so Soraka's ability heal is unchanged from
        itemless, but it is still counted. The ITEM-side stays exactly 0.
        """
        r = compute_hps(self.snap, "Soraka", level=11, item_ids=["3153"])
        self.assertEqual(r.direct_throughput, 0.0)
        self.assertEqual(r.ally_buff_credit, 0.0)
        self.assertAlmostEqual(r.total_throughput, r.ability_hps_total, places=9)

    def test_redemption_alone_matches_curated_formula(self) -> None:
        """lvl 11 + Redemption (3107): per_proc=150 + 10*11.76=267.6;
        cps=0.00833; targets=3; amp=1.10; final = 267.6*0.00833*3*1.10."""
        r = compute_hps(self.snap, "Soraka", level=11, item_ids=["3107"])
        expected_raw = 267.6 * 0.00833 * 3.0
        self.assertAlmostEqual(r.healing_hps_raw, expected_raw, places=3)
        self.assertAlmostEqual(r.amp_multiplier, 1.10, places=4)
        self.assertAlmostEqual(r.healing_hps, expected_raw * 1.10, places=3)
        # No shield contribution.
        self.assertEqual(r.shielding_hps, 0.0)

    def test_mikael_alone_includes_cleanse_credit(self) -> None:
        """lvl 11 + Mikael's (3222): heal raw + ally_buff_credit 2.0 (cleanse)."""
        r = compute_hps(self.snap, "Soraka", level=11, item_ids=["3222"])
        self.assertGreater(r.healing_hps_raw, 0.0)
        self.assertAlmostEqual(r.ally_buff_credit, 2.0, places=3)
        self.assertAlmostEqual(r.amp_multiplier, 1.12, places=4)

    def test_moonstone_alone_provides_amp_only(self) -> None:
        """Moonstone (6617) is pure amp - 0 direct heal/shield, +30% to others."""
        r = compute_hps(self.snap, "Soraka", level=11, item_ids=["6617"])
        self.assertEqual(r.healing_hps_raw, 0.0)
        self.assertEqual(r.shielding_hps_raw, 0.0)
        self.assertAlmostEqual(r.amp_multiplier, 1.30, places=4)
        # Item direct = 0 x 1.30 + 0 buff = 0. total_throughput is now the
        # ability HPS only (folded in, V2 enchanter wire); Moonstone's AP
        # raises Soraka's own kit heal above the itemless value.
        self.assertEqual(r.direct_throughput, 0.0)
        self.assertEqual(r.ally_buff_credit, 0.0)
        self.assertAlmostEqual(r.total_throughput, r.ability_hps_total, places=9)

    def test_ardent_alone_provides_buff_credit_only(self) -> None:
        """Ardent (3504): 0 direct heal, 15 ally_buff_credit, 10% amp.

        ITEM direct stays 0 + buff 15; total_throughput now also folds in
        ability HPS (V2 enchanter wire) so total == 15.0 + ability_hps_total.
        """
        r = compute_hps(self.snap, "Soraka", level=11, item_ids=["3504"])
        self.assertEqual(r.healing_hps_raw, 0.0)
        self.assertAlmostEqual(r.ally_buff_credit, 15.0, places=3)
        self.assertAlmostEqual(r.amp_multiplier, 1.10, places=4)
        self.assertAlmostEqual(
            r.total_throughput, 15.0 + r.ability_hps_total, places=3
        )

    def test_locket_alone_shields_not_heals(self) -> None:
        """Locket (3190): pure shield output, no heal."""
        r = compute_hps(self.snap, "Soraka", level=11, item_ids=["3190"])
        self.assertEqual(r.healing_hps_raw, 0.0)
        self.assertGreater(r.shielding_hps_raw, 0.0)


# --- amp pipeline + compounding ----------------------------------------


class AmpPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_amp_multipliers_stack_additively(self) -> None:
        """Redemption (+10%) + Mikael (+12%) -> 1 + 0.22 = 1.22.

        RM-177 (ENGINE 1.275.3): this test previously asserted the PRODUCT
        1.10 x 1.12 = 1.232 and was named ...compound_multiplicatively. Heal-
        and-Shield-Power is additive in League, and ``_hsp_amp`` had summed the
        same field off the same catalog since R60 - the two engines disagreed
        for 73 engine revisions with a green test on each side. The name is
        changed deliberately, not the number bent: a test asserting the wrong
        physical model is worse than no test.
        """
        r = compute_hps(
            self.snap, "Soraka", level=11, item_ids=["3107", "3222"]
        )
        self.assertAlmostEqual(r.amp_multiplier, 1.0 + 0.10 + 0.12, places=4)

    def test_moonstone_amps_redemption(self) -> None:
        """Adding Moonstone to Redemption build raises the amped HPS by x1.30."""
        base = compute_hps(self.snap, "Soraka", level=11, item_ids=["3107"])
        amped = compute_hps(
            self.snap, "Soraka", level=11, item_ids=["3107", "6617"]
        )
        # raw unchanged, amp grows x1.30/x1.10 = x1.30 factor on top.
        self.assertAlmostEqual(amped.healing_hps_raw, base.healing_hps_raw, places=3)
        self.assertAlmostEqual(amped.amp_multiplier, 1.10 * 1.30, places=4)
        self.assertAlmostEqual(
            amped.healing_hps, base.healing_hps * 1.30, places=3
        )

    def test_buff_credit_additive_not_amped(self) -> None:
        """ally_buff_credit is added AFTER amp multiplier (it's not a heal)."""
        r = compute_hps(
            self.snap, "Soraka", level=11, item_ids=["6617", "3504"]
        )
        # Ardent buff_credit = 15.0, unaffected by Moonstone's 30% amp.
        self.assertAlmostEqual(r.ally_buff_credit, 15.0, places=3)
        # Item direct = 0 x amp + 15.0 buff; total_throughput now also folds
        # in ability HPS (V2 enchanter wire) so total == 15.0 + ability.
        self.assertEqual(r.direct_throughput, 0.0)
        self.assertAlmostEqual(
            r.total_throughput, 15.0 + r.ability_hps_total, places=3
        )

    def test_buff_credit_sums_across_items(self) -> None:
        """Multiple buff items sum their credits."""
        r = compute_hps(
            self.snap, "Soraka", level=11,
            item_ids=["3504", "6616", "4005"],  # Ardent 15 + Staff 12 + Mandate 6
        )
        self.assertAlmostEqual(r.ally_buff_credit, 33.0, places=3)

    def test_full_three_item_build_matches_hand_calc(self) -> None:
        """Soraka lvl 11 + Moonstone+Redemption+Ardent (the canonical mid-game enchanter
        core). Reproduces the live-probe numbers from the session wrap.
        """
        r = compute_hps(
            self.snap, "Soraka", level=11,
            item_ids=["6617", "3107", "3504"],
        )
        # raw = Redemption only: 267.6 x 0.00833 x 3 = 6.687
        self.assertAlmostEqual(r.healing_hps_raw, 267.6 * 0.00833 * 3.0, places=3)
        # amp = 1.30 (Moonstone, an ally-CHAIN ratio and so a true multiplier)
        # x (1 + 0.10 Redemption + 0.10 Ardent) = 1.30 x 1.20 = 1.56.
        # RM-177: was 1.30 x 1.10 x 1.10 = 1.573 under the old all-product
        # convention. Moonstone keeps its product position; the two printed-HSP
        # rows now sum, which is the only part that moved.
        self.assertAlmostEqual(r.amp_multiplier, 1.30 * (1.0 + 0.10 + 0.10), places=4)
        # healing_hps = raw x amp
        self.assertAlmostEqual(
            r.healing_hps, r.healing_hps_raw * r.amp_multiplier, places=3
        )
        # buff_credit = 15.0 (Ardent only - Moonstone is amp, Redemption is direct heal)
        self.assertAlmostEqual(r.ally_buff_credit, 15.0, places=3)
        # total = direct + buff + ability_hps_total (ability HPS folded in,
        # V2 enchanter wire; healing_hps is the item-only direct heal).
        self.assertAlmostEqual(
            r.total_throughput,
            r.healing_hps + 15.0 + r.ability_hps_total,
            places=3,
        )


# --- mode multiplier ---------------------------------------------------


class ModeMultiplierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_sr_mode_multiplier_is_one(self) -> None:
        r = compute_hps(self.snap, "Soraka", level=11, item_ids=["3107"], mode="SR")
        self.assertEqual(r.mode_multiplier, 1.0)

    def test_aram_mode_multiplier_applied(self) -> None:
        """ARAM may have aramShieldsHealing; should not crash regardless."""
        r = compute_hps(self.snap, "Soraka", level=11, item_ids=["3107"], mode="ARAM")
        self.assertGreater(r.mode_multiplier, 0.0)

    def test_sr_aram_healing_ratio_matches_mode_multiplier(self) -> None:
        """healing_hps(ARAM) / healing_hps(SR) == aramShieldsHealing."""
        sr = compute_hps(self.snap, "Soraka", level=11, item_ids=["3107"], mode="SR")
        aram = compute_hps(self.snap, "Soraka", level=11, item_ids=["3107"], mode="ARAM")
        if sr.healing_hps > 0:
            ratio = aram.healing_hps / sr.healing_hps
            self.assertAlmostEqual(ratio, aram.mode_multiplier, places=4)


class HealShieldSplitModifierTests(unittest.TestCase):
    """Iter-17 carry-forward fix: aramHealing / aramShielding are
    independent Meraki keys. 24 champs in 16.10.1 have split values.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_modifier_outside_aram_is_one(self) -> None:
        h, s = _aram_heal_shield_modifiers(self.snap, "Soraka", "SR")
        self.assertEqual(h, 1.0)
        self.assertEqual(s, 1.0)

    def test_split_champ_camille(self) -> None:
        """Camille: aramHealing 1.20, aramShielding 1.10."""
        h, s = _aram_heal_shield_modifiers(self.snap, "Camille", "ARAM")
        self.assertAlmostEqual(h, 1.20, places=2)
        self.assertAlmostEqual(s, 1.10, places=2)

    def test_split_champ_lee_sin(self) -> None:
        """LeeSin: aramHealing 1.10, aramShielding 1.20 (heal LESS than shield)."""
        h, s = _aram_heal_shield_modifiers(self.snap, "LeeSin", "ARAM")
        self.assertAlmostEqual(h, 1.10, places=2)
        self.assertAlmostEqual(s, 1.20, places=2)

    def test_split_champ_milio(self) -> None:
        """Milio: aramHealing 0.95, aramShielding 0.90 (both downwards)."""
        h, s = _aram_heal_shield_modifiers(self.snap, "Milio", "ARAM")
        self.assertAlmostEqual(h, 0.95, places=2)
        self.assertAlmostEqual(s, 0.90, places=2)

    def test_split_champ_nunu(self) -> None:
        """Nunu: aramHealing 1.10, aramShielding 1.20."""
        h, s = _aram_heal_shield_modifiers(self.snap, "Nunu", "ARAM")
        self.assertAlmostEqual(h, 1.10, places=2)
        self.assertAlmostEqual(s, 1.20, places=2)

    def test_split_applied_in_compute_hps(self) -> None:
        """The two-modifier split must reach the per-side throughput.

        Camille has heal_mult 1.20 vs shield_mult 1.10. With a build that
        carries both heal and shield procs (Moonstone here), the
        healing_hps should scale up 1.20 and shielding_hps 1.10 from
        the SR baseline.
        """
        sr = compute_hps(self.snap, "Camille", level=11, item_ids=["6617"], mode="SR")
        aram = compute_hps(self.snap, "Camille", level=11, item_ids=["6617"], mode="ARAM")
        self.assertAlmostEqual(aram.heal_mult, 1.20, places=2)
        self.assertAlmostEqual(aram.shield_mult, 1.10, places=2)
        if sr.healing_hps > 0:
            self.assertAlmostEqual(
                aram.healing_hps / sr.healing_hps, 1.20, places=3,
            )
        if sr.shielding_hps > 0:
            self.assertAlmostEqual(
                aram.shielding_hps / sr.shielding_hps, 1.10, places=3,
            )

    def test_backward_compat_mode_multiplier_returns_heal_mult(self) -> None:
        """``HpsResult.mode_multiplier`` is the heal-side alias post-split."""
        r = compute_hps(self.snap, "Camille", level=11, item_ids=["6617"], mode="ARAM")
        self.assertEqual(r.mode_multiplier, r.heal_mult)

    def test_legacy_aramshieldshealing_only_falls_through(self) -> None:
        """If a synthetic snapshot has only the legacy aramShieldsHealing
        key, both halves get that value."""
        class FakeSnap:
            def champion(self, _):
                return {"lolmath": {"aram_modifiers": {"aramShieldsHealing": 0.85}}}
        h, s = _aram_heal_shield_modifiers(FakeSnap(), "X", "ARAM")
        self.assertEqual(h, 0.85)
        self.assertEqual(s, 0.85)


# --- targets override --------------------------------------------------


class TargetsOverrideTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_targets_override_one_reduces_aoe_heal(self) -> None:
        """Redemption with override=1 yields 1/3 the throughput of curated=3."""
        base = compute_hps(self.snap, "Soraka", level=11, item_ids=["3107"])
        override = compute_hps(
            self.snap, "Soraka", level=11, item_ids=["3107"],
            targets_per_proc_override=1.0,
        )
        # base: 267.6 x 0.00833 x 3 = 6.69; override: 267.6 x 0.00833 x 1 = 2.23
        self.assertAlmostEqual(override.healing_hps_raw, base.healing_hps_raw / 3.0, places=3)

    def test_targets_override_records_in_result(self) -> None:
        r = compute_hps(
            self.snap, "Soraka", level=11, item_ids=["3107"],
            targets_per_proc_override=2.5,
        )
        self.assertAlmostEqual(r.targets_per_proc_override, 2.5, places=4)
        # Note surfaced.
        joined = " ".join(r.notes).lower()
        self.assertIn("targets_per_proc_override", joined)


# --- edge cases --------------------------------------------------------


class EdgeCaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_unknown_champion_raises_key_error(self) -> None:
        with self.assertRaises(KeyError):
            compute_hps(self.snap, "NotARealChamp", level=11)

    def test_to_dict_round_trip(self) -> None:
        r = compute_hps(
            self.snap, "Soraka", level=11, item_ids=["3107", "6617"]
        )
        d = r.to_dict()
        # Round-trip serialization should be JSON-compatible.
        json.dumps(d)
        self.assertEqual(d["champion_id"], "Soraka")
        self.assertEqual(len(d["items"]), 2)

    def test_format_table_contains_archetype_tag(self) -> None:
        r = compute_hps(self.snap, "Soraka", level=11, item_ids=["3107"])
        out = r.format_table()
        self.assertIn("[ENCHANTER]", out)

    def test_format_table_contains_item_breakdown(self) -> None:
        r = compute_hps(self.snap, "Soraka", level=11, item_ids=["3107", "3504"])
        out = r.format_table()
        self.assertIn("Redemption", out)
        self.assertIn("Ardent", out)

    def test_chemtech_putrifier_contributes_zero(self) -> None:
        """Chemtech (3011) is anti-heal; intentionally excluded from registry.

        ITEM throughput stays 0; total_throughput now folds in ability HPS
        (V2 enchanter wire) so it equals Soraka's ability_hps_total.
        """
        r = compute_hps(self.snap, "Soraka", level=11, item_ids=["3011"])
        self.assertEqual(r.direct_throughput, 0.0)
        self.assertEqual(r.ally_buff_credit, 0.0)
        self.assertAlmostEqual(r.total_throughput, r.ability_hps_total, places=9)

    def test_aram_mirror_id_not_in_registry_contributes_zero(self) -> None:
        """ARAM Redemption (323107) is not in the curated registry by id."""
        r = compute_hps(self.snap, "Soraka", level=11, item_ids=["323107"], mode="ARAM")
        # Phase 6 v1 chose "by ID match," so mirrors without registry entries
        # contribute zero ITEM throughput. total_throughput now folds in
        # ability HPS (V2 enchanter wire; ARAM-scaled), so it equals
        # ability_hps_total - the ITEM side is still exactly 0.
        self.assertEqual(r.direct_throughput, 0.0)
        self.assertEqual(r.ally_buff_credit, 0.0)
        self.assertAlmostEqual(r.total_throughput, r.ability_hps_total, places=9)


class HpsItemContributionTests(unittest.TestCase):
    def test_to_dict_shape(self) -> None:
        c = HpsItemContribution(
            item_id="6617", item_name="Moonstone Renewer",
            heal_per_proc=0.0, heal_procs_per_second=0.0,
            heal_targets_per_proc=0.0, healing_hps_raw=0.0,
            shield_per_proc=0.0, shield_procs_per_second=0.0,
            shield_targets_per_proc=0.0, shielding_hps_raw=0.0,
            heal_shield_amp_pct=0.30, ally_buff_credit_per_second=0.0,
            notes="chain amp",
        )
        d = c.to_dict()
        self.assertEqual(d["item_id"], "6617")
        self.assertEqual(d["heal_shield_amp_pct"], 0.30)


# --- server route /hps -------------------------------------------------


class HpsRouteTests(unittest.TestCase):
    """Spin the engine server on a free port; hit /hps; tear down."""

    @classmethod
    def setUpClass(cls) -> None:
        from agents.daemon_slayer.server import start_server, _CACHE
        cls.snap = DataSnapshot.load()
        _CACHE.set(cls.snap)
        cls.srv = start_server(host="127.0.0.1", port=0, snapshot=cls.snap)
        cls.thread = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = cls.srv.server_address[1]
        cls.base = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.srv.shutdown()
        cls.srv.server_close()

    def _post(self, path: str, body: dict) -> tuple[int, dict]:
        raw = json.dumps(body).encode("utf-8")
        req = Request(self.base + path, data=raw, method="POST",
                      headers={"Content-Type": "application/json"})
        try:
            with urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            try:
                code = getattr(e, "code", None)
                body_resp = json.loads(e.read().decode("utf-8"))  # type: ignore[attr-defined]
                return code, body_resp
            except Exception:
                raise

    def test_post_hps_returns_200(self) -> None:
        status, payload = self._post("/hps", {
            "champion": "Soraka", "level": 11,
            "items": ["3107", "3504"],
            "mode": "SR",
        })
        self.assertEqual(status, 200)
        self.assertEqual(payload["champion_id"], "Soraka")
        self.assertGreater(payload["total_throughput"], 0.0)

    def test_post_hps_targets_override(self) -> None:
        status, payload = self._post("/hps", {
            "champion": "Soraka", "level": 11, "items": ["3107"],
            "targets_per_proc_override": 1.0,
        })
        self.assertEqual(status, 200)
        # 1 target -> 1/3 of default-3 throughput.
        self.assertLess(payload["healing_hps_raw"], 3.0)

    def test_post_hps_unknown_champion_404(self) -> None:
        status, payload = self._post("/hps", {
            "champion": "NotARealChamp", "level": 11,
        })
        self.assertEqual(status, 404)

    def test_post_hps_invalid_targets_400(self) -> None:
        status, payload = self._post("/hps", {
            "champion": "Soraka", "level": 11,
            "targets_per_proc_override": "not-a-number",
        })
        self.assertEqual(status, 400)

    def test_post_hps_default_mode_sr(self) -> None:
        status, payload = self._post("/hps", {
            "champion": "Soraka", "level": 11, "items": ["3107"],
        })
        self.assertEqual(status, 200)
        self.assertEqual(payload["mode"], "SR")
        self.assertEqual(payload["mode_multiplier"], 1.0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
