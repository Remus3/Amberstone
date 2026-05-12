"""Phase 1 (s174, 2026-05-12) — Tank EHP scorer tests.

Mirrors ``test_dps`` shape: load the 16.9.1 snapshot once, exercise
``compute_ehp`` across champions × items × modes. EHP math is
closed-form so tests pin exact values where possible; comparative tests
use ratios so future patch HP rescaling doesn't redden CI.
"""
from __future__ import annotations

import math
import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import (
    EhpResult,
    _armor_factor,
    _aram_damage_taken,
    compute_ehp,
)


class ArmorFactorTests(unittest.TestCase):
    """Pure-math unit tests; no snapshot needed."""

    def test_zero_resist_no_mitigation(self) -> None:
        self.assertAlmostEqual(_armor_factor(0.0), 1.0)

    def test_hundred_resist_halves_damage(self) -> None:
        self.assertAlmostEqual(_armor_factor(100.0), 0.5)

    def test_two_hundred_resist_third_damage(self) -> None:
        self.assertAlmostEqual(_armor_factor(200.0), 1.0 / 3.0)

    def test_negative_resist_uses_inverted_formula(self) -> None:
        # -100 armor: 2 - 100/(100 - (-100)) = 2 - 0.5 = 1.5 → take 150% damage
        self.assertAlmostEqual(_armor_factor(-100.0), 1.5)

    def test_negative_resist_does_not_exceed_2x(self) -> None:
        # Asymptote at -∞ → 2.0 (200% damage). Never explodes.
        self.assertLess(_armor_factor(-1000.0), 2.0)
        self.assertGreater(_armor_factor(-1000.0), 1.9)


class ComputeEhpBasicsTests(unittest.TestCase):
    """End-to-end tests against the loaded snapshot."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_returns_ehp_result_instance(self) -> None:
        r = compute_ehp(self.snap, "Aatrox", level=11)
        self.assertIsInstance(r, EhpResult)
        self.assertEqual(r.champion_id, "Aatrox")
        self.assertEqual(r.level, 11)
        self.assertEqual(r.mode, "SR")

    def test_hp_armor_mr_match_build_resolver(self) -> None:
        from agents.daemon_slayer.engine import build_champion
        r = compute_ehp(self.snap, "Aatrox", level=11)
        resolved = build_champion(self.snap, "Aatrox", level=11)
        self.assertAlmostEqual(r.hp, resolved.stats["hp"], places=4)
        self.assertAlmostEqual(r.armor, resolved.stats["armor"], places=4)
        self.assertAlmostEqual(r.mr, resolved.stats["mr"], places=4)

    def test_true_ehp_equals_hp_in_sr_mode(self) -> None:
        # SR mode_multiplier=1.0 → true_ehp == hp exactly (no resists apply
        # to true damage).
        r = compute_ehp(self.snap, "Aatrox", level=11)
        self.assertAlmostEqual(r.true_ehp, r.hp, places=4)

    def test_blended_pure_true_share_equals_hp(self) -> None:
        # ad_share=0 + ap_share=0 → 100% true damage → blended_ehp == hp.
        r = compute_ehp(self.snap, "Aatrox", level=11,
                        enemy_ad_share=0.0, enemy_ap_share=0.0)
        self.assertAlmostEqual(r.blended_ehp, r.hp, places=4)
        self.assertAlmostEqual(r.enemy_true_share, 1.0, places=4)

    def test_blended_pure_ad_equals_physical_ehp(self) -> None:
        r = compute_ehp(self.snap, "Aatrox", level=11,
                        enemy_ad_share=1.0, enemy_ap_share=0.0)
        self.assertAlmostEqual(r.blended_ehp, r.physical_ehp, places=4)

    def test_blended_pure_ap_equals_magical_ehp(self) -> None:
        r = compute_ehp(self.snap, "Aatrox", level=11,
                        enemy_ad_share=0.0, enemy_ap_share=1.0)
        self.assertAlmostEqual(r.blended_ehp, r.magical_ehp, places=4)

    def test_blended_60_40_split_linear_combination(self) -> None:
        r = compute_ehp(self.snap, "Aatrox", level=11,
                        enemy_ad_share=0.6, enemy_ap_share=0.4)
        expected = r.physical_ehp * 0.6 + r.magical_ehp * 0.4
        self.assertAlmostEqual(r.blended_ehp, expected, places=4)
        self.assertAlmostEqual(r.enemy_true_share, 0.0, places=4)

    def test_physical_ehp_formula_matches_armor_factor(self) -> None:
        r = compute_ehp(self.snap, "Aatrox", level=11)
        expected = r.hp / _armor_factor(r.armor)
        self.assertAlmostEqual(r.physical_ehp, expected, places=4)

    def test_magical_ehp_formula_matches_mr_factor(self) -> None:
        r = compute_ehp(self.snap, "Aatrox", level=11)
        expected = r.hp / _armor_factor(r.mr)
        self.assertAlmostEqual(r.magical_ehp, expected, places=4)


class ItemContributionTests(unittest.TestCase):
    """Adding items should shift the EHP components in the expected direction."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_thornmail_lifts_physical_ehp_meaningfully(self) -> None:
        # 3075 Thornmail = 70 armor (raises armor by ~70, lifting physical_ehp).
        naked = compute_ehp(self.snap, "Malphite", level=11)
        with_thornmail = compute_ehp(self.snap, "Malphite", level=11,
                                     item_ids=["3075"])
        self.assertGreater(with_thornmail.armor, naked.armor + 60)
        self.assertGreater(with_thornmail.physical_ehp, naked.physical_ehp * 1.10)

    def test_force_of_nature_lifts_mr_more_than_armor(self) -> None:
        # 4401 Force of Nature = 55 MR + 400 HP (16.9.1). The HP component
        # lifts physical_ehp too, so the magical/physical delta ratio is
        # ~2.3x rather than the naive "pure-MR" expectation. Pin the
        # qualitative claim: magical_delta strictly greater than
        # physical_delta.
        naked = compute_ehp(self.snap, "Malphite", level=11)
        with_fon = compute_ehp(self.snap, "Malphite", level=11, item_ids=["4401"])
        self.assertGreater(with_fon.mr, naked.mr + 50)
        physical_delta = with_fon.physical_ehp - naked.physical_ehp
        magical_delta = with_fon.magical_ehp - naked.magical_ehp
        self.assertGreater(magical_delta, physical_delta)
        # And materially so — at least 1.5× the physical lift.
        self.assertGreater(magical_delta, physical_delta * 1.5)

    def test_pure_ap_enemy_doesnt_value_armor(self) -> None:
        # ap_share=1.0 → blended_ehp tracks magical_ehp only; adding armor
        # items should leave blended_ehp ALMOST unchanged (small Jak'Sho-like
        # cross-amps aside, plain Chain Vest = +40 armor, 0 MR, 0 HP).
        naked = compute_ehp(self.snap, "Malphite", level=11,
                            enemy_ad_share=0.0, enemy_ap_share=1.0)
        with_armor = compute_ehp(self.snap, "Malphite", level=11,
                                 item_ids=["1031"],  # Chain Vest
                                 enemy_ad_share=0.0, enemy_ap_share=1.0)
        self.assertAlmostEqual(with_armor.blended_ehp, naked.blended_ehp, places=2)

    def test_pure_ad_enemy_doesnt_value_mr(self) -> None:
        # ad_share=1.0 → blended_ehp tracks physical_ehp only. Null-Magic
        # Mantle adds 25 MR + 0 armor + 0 HP → no physical_ehp shift.
        naked = compute_ehp(self.snap, "Malphite", level=11,
                            enemy_ad_share=1.0, enemy_ap_share=0.0)
        with_mr = compute_ehp(self.snap, "Malphite", level=11,
                              item_ids=["1033"],  # Null-Magic Mantle
                              enemy_ad_share=1.0, enemy_ap_share=0.0)
        self.assertAlmostEqual(with_mr.blended_ehp, naked.blended_ehp, places=2)

    def test_giants_belt_adds_raw_hp(self) -> None:
        # 1011 Giant's Belt = +380 HP (or whatever the current patch sets it).
        naked = compute_ehp(self.snap, "Malphite", level=11)
        with_belt = compute_ehp(self.snap, "Malphite", level=11, item_ids=["1011"])
        self.assertGreater(with_belt.hp, naked.hp + 300)
        # All three EHP components scale with HP, so all should lift.
        self.assertGreater(with_belt.physical_ehp, naked.physical_ehp)
        self.assertGreater(with_belt.magical_ehp, naked.magical_ehp)
        self.assertGreater(with_belt.true_ehp, naked.true_ehp)

    def test_kindlegem_adds_hp(self) -> None:
        # 3067 Kindlegem — small HP component.
        naked = compute_ehp(self.snap, "Malphite", level=11)
        with_kindle = compute_ehp(self.snap, "Malphite", level=11, item_ids=["3067"])
        self.assertGreater(with_kindle.hp, naked.hp)

    def test_chain_vest_adds_armor(self) -> None:
        naked = compute_ehp(self.snap, "Malphite", level=11)
        with_cv = compute_ehp(self.snap, "Malphite", level=11, item_ids=["1031"])
        self.assertGreater(with_cv.armor, naked.armor + 30)

    def test_null_magic_mantle_adds_mr(self) -> None:
        # 1033 Null-Magic Mantle = 20 MR exactly in 16.9.1. assertGreaterEqual
        # accepts the exact-equal case; the floor stays at the live patch value.
        naked = compute_ehp(self.snap, "Malphite", level=11)
        with_nmm = compute_ehp(self.snap, "Malphite", level=11, item_ids=["1033"])
        self.assertGreaterEqual(with_nmm.mr, naked.mr + 20)


class LevelScalingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_higher_level_more_resists(self) -> None:
        lv1 = compute_ehp(self.snap, "Malphite", level=1)
        lv18 = compute_ehp(self.snap, "Malphite", level=18)
        self.assertGreater(lv18.hp, lv1.hp)
        self.assertGreater(lv18.armor, lv1.armor)
        self.assertGreater(lv18.mr, lv1.mr)

    def test_higher_level_more_blended_ehp(self) -> None:
        lv1 = compute_ehp(self.snap, "Malphite", level=1)
        lv18 = compute_ehp(self.snap, "Malphite", level=18)
        self.assertGreater(lv18.blended_ehp, lv1.blended_ehp)


class ARAMModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_sr_mode_multiplier_is_1(self) -> None:
        r = compute_ehp(self.snap, "Aatrox", level=11, mode="SR")
        self.assertAlmostEqual(r.mode_multiplier, 1.0)

    def test_aram_modifier_at_1_equals_sr(self) -> None:
        # Aatrox has aramDamageTaken=1.0 → ARAM EHP == SR EHP (modulo any
        # ARAM AS changes that affect bonus AS, which don't touch EHP).
        sr = compute_ehp(self.snap, "Aatrox", level=11, mode="SR")
        aram = compute_ehp(self.snap, "Aatrox", level=11, mode="ARAM")
        self.assertAlmostEqual(sr.blended_ehp, aram.blended_ehp, places=2)

    def test_aram_damage_taken_below_one_inflates_ehp(self) -> None:
        # Find a champion whose aramDamageTaken < 1.0 (takes less damage in
        # ARAM, so effective HP scales UP).
        candidate = None
        for cid, rec in self.snap.champions.items():
            aram = ((rec.get("lolmath") or {}).get("aram_modifiers") or {})
            mult = aram.get("aramDamageTaken")
            if isinstance(mult, (int, float)) and 0.5 <= mult < 1.0:
                candidate = (cid, float(mult))
                break
        if candidate is None:
            self.skipTest("no champion with aramDamageTaken < 1.0 in snapshot")
        cid, mult = candidate
        sr = compute_ehp(self.snap, cid, level=11, mode="SR")
        aram = compute_ehp(self.snap, cid, level=11, mode="ARAM")
        self.assertGreater(aram.true_ehp, sr.true_ehp)
        # All three EHP components should scale by exactly 1/mult.
        self.assertAlmostEqual(aram.true_ehp / sr.true_ehp, 1.0 / mult, places=3)
        self.assertAlmostEqual(aram.physical_ehp / sr.physical_ehp, 1.0 / mult, places=2)

    def test_aram_damage_taken_above_one_deflates_ehp(self) -> None:
        candidate = None
        for cid, rec in self.snap.champions.items():
            aram = ((rec.get("lolmath") or {}).get("aram_modifiers") or {})
            mult = aram.get("aramDamageTaken")
            if isinstance(mult, (int, float)) and 1.0 < mult <= 1.5:
                candidate = (cid, float(mult))
                break
        if candidate is None:
            self.skipTest("no champion with aramDamageTaken > 1.0 in snapshot")
        cid, mult = candidate
        sr = compute_ehp(self.snap, cid, level=11, mode="SR")
        aram = compute_ehp(self.snap, cid, level=11, mode="ARAM")
        self.assertLess(aram.true_ehp, sr.true_ehp)

    def test_aram_damage_taken_helper_returns_1_outside_aram(self) -> None:
        # Helper path: even in ARENA, aramDamageTaken doesn't apply.
        self.assertAlmostEqual(
            _aram_damage_taken(self.snap, "Aatrox", "SR"), 1.0
        )
        self.assertAlmostEqual(
            _aram_damage_taken(self.snap, "Aatrox", "ARENA"), 1.0
        )


class ValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_unknown_champion_raises(self) -> None:
        with self.assertRaises(KeyError):
            compute_ehp(self.snap, "Nonexistentius", level=11)

    def test_invalid_level_raises(self) -> None:
        with self.assertRaises(ValueError):
            compute_ehp(self.snap, "Aatrox", level=99)
        with self.assertRaises(ValueError):
            compute_ehp(self.snap, "Aatrox", level=0)

    def test_share_sum_over_one_raises(self) -> None:
        with self.assertRaises(ValueError):
            compute_ehp(self.snap, "Aatrox", level=11,
                        enemy_ad_share=0.7, enemy_ap_share=0.7)

    def test_share_negative_raises(self) -> None:
        with self.assertRaises(ValueError):
            compute_ehp(self.snap, "Aatrox", level=11,
                        enemy_ad_share=-0.1, enemy_ap_share=0.5)
        with self.assertRaises(ValueError):
            compute_ehp(self.snap, "Aatrox", level=11,
                        enemy_ad_share=0.5, enemy_ap_share=-0.1)

    def test_share_above_one_raises(self) -> None:
        with self.assertRaises(ValueError):
            compute_ehp(self.snap, "Aatrox", level=11,
                        enemy_ad_share=1.5, enemy_ap_share=0.0)

    def test_share_sum_exactly_one_ok(self) -> None:
        # No true damage assumption — should not raise.
        r = compute_ehp(self.snap, "Aatrox", level=11,
                        enemy_ad_share=0.5, enemy_ap_share=0.5)
        self.assertAlmostEqual(r.enemy_true_share, 0.0, places=4)


class SerializationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_to_dict_includes_all_ehp_fields(self) -> None:
        r = compute_ehp(self.snap, "Aatrox", level=11)
        d = r.to_dict()
        for key in (
            "champion_id", "champion_name", "level", "item_ids", "mode",
            "hp", "armor", "mr",
            "physical_ehp", "magical_ehp", "true_ehp", "blended_ehp",
            "enemy_ad_share", "enemy_ap_share", "enemy_true_share",
            "mode_multiplier", "stats", "notes",
        ):
            self.assertIn(key, d, f"to_dict() missing key: {key}")

    def test_format_table_includes_blended_value(self) -> None:
        r = compute_ehp(self.snap, "Aatrox", level=11)
        tbl = r.format_table()
        self.assertIn("blended_ehp", tbl)
        self.assertIn("physical_ehp", tbl)
        self.assertIn("magical_ehp", tbl)
        self.assertIn("true_ehp", tbl)

    def test_to_dict_item_ids_is_list_not_tuple(self) -> None:
        # Tuples don't survive JSON serialization in stdlib http.server; the
        # to_dict() path needs to convert.
        r = compute_ehp(self.snap, "Aatrox", level=11, item_ids=["3075"])
        d = r.to_dict()
        self.assertIsInstance(d["item_ids"], list)
        self.assertEqual(d["item_ids"], ["3075"])


class ConsistencyTests(unittest.TestCase):
    """Sanity checks across calls that should agree."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_none_items_equals_empty_items(self) -> None:
        r_none = compute_ehp(self.snap, "Aatrox", level=11)
        r_empty = compute_ehp(self.snap, "Aatrox", level=11, item_ids=[])
        self.assertAlmostEqual(r_none.blended_ehp, r_empty.blended_ehp, places=4)
        self.assertEqual(r_none.item_ids, r_empty.item_ids)

    def test_blended_ehp_monotone_in_resists_when_relevant(self) -> None:
        # Pure-AD enemy: adding more armor → strictly higher blended_ehp.
        zero = compute_ehp(self.snap, "Malphite", level=11,
                           enemy_ad_share=1.0, enemy_ap_share=0.0)
        one = compute_ehp(self.snap, "Malphite", level=11,
                          item_ids=["1031"],  # Chain Vest
                          enemy_ad_share=1.0, enemy_ap_share=0.0)
        two = compute_ehp(self.snap, "Malphite", level=11,
                          item_ids=["1031", "3076"],  # Chain Vest + Bramble Vest
                          enemy_ad_share=1.0, enemy_ap_share=0.0)
        self.assertLess(zero.blended_ehp, one.blended_ehp)
        self.assertLess(one.blended_ehp, two.blended_ehp)

    def test_physical_ehp_always_at_least_hp_when_positive_armor(self) -> None:
        # When armor > 0, physical_ehp > hp (positive mitigation). This
        # invariant holds for every champion at every level.
        for cid in list(self.snap.champions)[:10]:
            r = compute_ehp(self.snap, cid, level=11)
            if r.armor > 0:
                self.assertGreaterEqual(
                    r.physical_ehp, r.hp,
                    f"{cid} at lvl 11: armor={r.armor} but physical_ehp < hp",
                )

    def test_blended_ehp_in_range_of_components(self) -> None:
        r = compute_ehp(self.snap, "Malphite", level=11,
                        enemy_ad_share=0.5, enemy_ap_share=0.5)
        # Weighted average must lie within [min, max] of the three components.
        low = min(r.physical_ehp, r.magical_ehp, r.true_ehp)
        high = max(r.physical_ehp, r.magical_ehp, r.true_ehp)
        self.assertGreaterEqual(r.blended_ehp, low - 1e-6)
        self.assertLessEqual(r.blended_ehp, high + 1e-6)


class NotesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_aram_modifier_note_surfaced(self) -> None:
        # Find a champion with aramDamageTaken != 1.0 and assert the note
        # appears in the result.
        candidate = None
        for cid, rec in self.snap.champions.items():
            aram = ((rec.get("lolmath") or {}).get("aram_modifiers") or {})
            mult = aram.get("aramDamageTaken")
            if isinstance(mult, (int, float)) and not math.isclose(mult, 1.0):
                candidate = cid
                break
        if candidate is None:
            self.skipTest("no champion with non-unit aramDamageTaken in snapshot")
        r = compute_ehp(self.snap, candidate, level=11, mode="ARAM")
        self.assertTrue(
            any("aramDamageTaken" in n for n in r.notes),
            f"expected aramDamageTaken note for {candidate}, got: {r.notes}",
        )

    def test_sr_mode_no_aram_note(self) -> None:
        r = compute_ehp(self.snap, "Aatrox", level=11, mode="SR")
        self.assertFalse(any("aramDamageTaken" in n for n in r.notes))


if __name__ == "__main__":
    unittest.main()
