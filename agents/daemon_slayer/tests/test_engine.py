import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.engine import _apply_mode_modifiers, build_champion


class BuildChampionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_aatrox_naked_lvl_1(self) -> None:
        r = build_champion(self.snap, "Aatrox", level=1)
        self.assertEqual(r.stats["hp"], 650)
        self.assertEqual(r.stats["ad"], 60)
        self.assertEqual(r.stats["armor"], 38)
        self.assertEqual(r.stats["mr"], 32)
        self.assertAlmostEqual(r.stats["as"], 0.651, places=3)
        self.assertEqual(r.stats["ms"], 345)
        self.assertEqual(r.gold_spent, 0)

    def test_aatrox_naked_lvl_18(self) -> None:
        r = build_champion(self.snap, "Aatrox", level=18)
        # hp = 650 + 114 * 17 = 2588
        self.assertEqual(r.stats["hp"], 2588)
        # armor = 38 + 4.8 * 17 = 119.6
        self.assertAlmostEqual(r.stats["armor"], 119.6, places=2)
        # AS at lvl 18 = 0.651 * 1.425
        self.assertAlmostEqual(r.stats["as"], 0.651 * 1.425, places=3)

    def test_bloodthirster_adds_ad_and_lifesteal(self) -> None:
        # Aatrox lvl 1 + Bloodthirster (3072): AD 60 + 80 = 140; lifesteal 15%
        # (DDragon 16.9.1: SR Bloodthirster is 15%; the 22-prefix arena variant is 18%)
        r = build_champion(self.snap, "Aatrox", level=1, item_ids=["3072"])
        self.assertEqual(r.stats["ad"], 140)
        self.assertAlmostEqual(r.stats["lifesteal"], 0.15)
        bt_gold = self.snap.item("3072")["gold"]["total"]
        self.assertEqual(r.gold_spent, bt_gold)

    def test_berserkers_stacks_attack_speed_pct_on_base(self) -> None:
        # Berserker's (3006): +25% AS, +45 MS
        # Aatrox lvl 1 base AS = 0.651 -> +25% bonus -> 0.651 * 1.25 = 0.81375
        r = build_champion(self.snap, "Aatrox", level=1, item_ids=["3006"])
        self.assertAlmostEqual(r.stats["as"], 0.651 * 1.25, places=3)
        # MS = base 345 + flat 45 = 390 (no pct)
        self.assertEqual(r.stats["ms"], 390)

    def test_berserkers_at_lvl_18_combines_per_level_and_item_bonus(self) -> None:
        # AS = base * (1 + bonus_levels + bonus_items) = 0.651 * (1 + 2.5/100*17 + 0.25)
        r = build_champion(self.snap, "Aatrox", level=18, item_ids=["3006"])
        expected = 0.651 * (1 + 0.025 * 17 + 0.25)
        self.assertAlmostEqual(r.stats["as"], expected, places=3)

    def test_infinity_edge_crit_caps_at_100pct(self) -> None:
        # Two IEs would be 50% but you can't actually own two; the cap test
        # simulates what happens if the engine is fed an absurd build.
        r = build_champion(self.snap, "Aatrox", level=1, item_ids=["3031", "3031", "3031", "3031", "3031"])
        # 5 * 25% = 125% -> clamped to 100%
        self.assertEqual(r.stats["crit"], 1.0)

    def test_eclipse_ad_adds_to_aatrox(self) -> None:
        r = build_champion(self.snap, "Aatrox", level=11, item_ids=["6692"])
        # Aatrox base AD 60, perlevel 5. Riot stat growth (not linear):
        # lvl 11 -> 60 + 5 * growth_multiplier(11) = 60 + 5*8.775 = 103.875.
        # + Eclipse 60 AD = 163.875 (the +60 item delta is unchanged).
        self.assertAlmostEqual(r.stats["ad"], 163.875, places=4)

    def test_unknown_champion_raises(self) -> None:
        with self.assertRaises(KeyError):
            build_champion(self.snap, "Notarealchamp", level=1)

    def test_unknown_item_raises(self) -> None:
        with self.assertRaises(KeyError):
            build_champion(self.snap, "Aatrox", level=1, item_ids=["999999"])

    def test_invalid_level_raises(self) -> None:
        with self.assertRaises(ValueError):
            build_champion(self.snap, "Aatrox", level=20)

    def test_to_dict_roundtrip(self) -> None:
        r = build_champion(self.snap, "Aatrox", level=11, item_ids=["6692", "3006"])
        d = r.to_dict()
        self.assertEqual(d["champion_id"], "Aatrox")
        self.assertEqual(d["level"], 11)
        self.assertEqual(d["item_ids"], ["6692", "3006"])
        self.assertIn("ad", d["stats"])

    def test_format_table_contains_basics(self) -> None:
        r = build_champion(self.snap, "Aatrox", level=11, item_ids=["6692"])
        table = r.format_table()
        self.assertIn("Aatrox", table)
        self.assertIn("lvl 11", table)
        self.assertIn("6692", table)
        self.assertIn("ad", table)


class ModeModifierHookTests(unittest.TestCase):
    """Phase 2 step 2 - _apply_mode_modifiers covers ARAM aramAttackSpeed.

    Live snapshot 16.9.1 has aramAttackSpeed=1 for every champion, so we
    exercise the multiplier path with a synthetic champion record.
    """

    def test_aram_attack_speed_scales_bonus_as_only(self) -> None:
        # base=0.6, scaled=0.9 -> bonus=0.3. With aramAS=1.5 -> bonus*1.5=0.45 -> 1.05.
        scaled = {"as": 0.9}
        raw_base = {"as": 0.6}
        champion = {"lolmath": {"aram_modifiers": {"aramAttackSpeed": 1.5}}}
        out, notes = _apply_mode_modifiers(scaled, raw_base, "ARAM", champion)
        self.assertAlmostEqual(out["as"], 1.05)
        self.assertTrue(any("aramAttackSpeed" in n for n in notes))

    def test_aram_attack_speed_one_is_noop(self) -> None:
        scaled = {"as": 0.9}
        raw_base = {"as": 0.6}
        champion = {"lolmath": {"aram_modifiers": {"aramAttackSpeed": 1.0}}}
        out, notes = _apply_mode_modifiers(scaled, raw_base, "ARAM", champion)
        self.assertAlmostEqual(out["as"], 0.9)
        self.assertEqual(notes, [])

    def test_sr_mode_skips_modifiers(self) -> None:
        scaled = {"as": 0.9}
        raw_base = {"as": 0.6}
        champion = {"lolmath": {"aram_modifiers": {"aramAttackSpeed": 99.0}}}
        out, notes = _apply_mode_modifiers(scaled, raw_base, "SR", champion)
        self.assertAlmostEqual(out["as"], 0.9)
        self.assertEqual(notes, [])

    def test_aram_mode_no_lolmath_block_does_not_crash(self) -> None:
        scaled = {"as": 0.9}
        raw_base = {"as": 0.6}
        out, notes = _apply_mode_modifiers(scaled, raw_base, "ARAM", {})
        self.assertAlmostEqual(out["as"], 0.9)
        self.assertEqual(notes, [])


class AramAbilityHasteExposureTests(unittest.TestCase):
    """ENGINE 1.21.0+: aramAbilityHaste delta exposed via
    ``scaled['aram_ability_haste']`` regardless of consumer presence."""

    def test_aram_ah_positive_delta_exposed(self) -> None:
        champion = {"lolmath": {"aram_modifiers": {"aramAbilityHaste": 20}}}
        out, notes = _apply_mode_modifiers({}, {}, "ARAM", champion)
        self.assertEqual(out["aram_ability_haste"], 20.0)
        self.assertTrue(any("aramAbilityHaste=+20" in n for n in notes))

    def test_aram_ah_negative_delta_exposed(self) -> None:
        champion = {"lolmath": {"aram_modifiers": {"aramAbilityHaste": -15}}}
        out, notes = _apply_mode_modifiers({}, {}, "ARAM", champion)
        self.assertEqual(out["aram_ability_haste"], -15.0)
        self.assertTrue(any("aramAbilityHaste=-15" in n for n in notes))

    def test_aram_ah_default_zero_no_note(self) -> None:
        champion = {"lolmath": {"aram_modifiers": {}}}
        out, notes = _apply_mode_modifiers({}, {}, "ARAM", champion)
        self.assertEqual(out["aram_ability_haste"], 0.0)
        self.assertFalse(any("aramAbilityHaste" in n for n in notes))

    def test_sr_mode_does_not_inject_aram_ah(self) -> None:
        champion = {"lolmath": {"aram_modifiers": {"aramAbilityHaste": 20}}}
        out, notes = _apply_mode_modifiers({}, {}, "SR", champion)
        self.assertNotIn("aram_ability_haste", out)
        self.assertEqual(notes, [])


class AramTenacityExposureTests(unittest.TestCase):
    """ENGINE 1.21.0+: aramTenacity multiplier exposed via
    ``scaled['aram_tenacity_mult']`` (default 1.0)."""

    def test_aram_tenacity_above_one_exposed(self) -> None:
        champion = {"lolmath": {"aram_modifiers": {"aramTenacity": 1.20}}}
        out, notes = _apply_mode_modifiers({}, {}, "ARAM", champion)
        self.assertAlmostEqual(out["aram_tenacity_mult"], 1.20)
        self.assertTrue(any("aramTenacity=1.20" in n for n in notes))

    def test_aram_tenacity_default_one_no_note(self) -> None:
        champion = {"lolmath": {"aram_modifiers": {}}}
        out, notes = _apply_mode_modifiers({}, {}, "ARAM", champion)
        self.assertEqual(out["aram_tenacity_mult"], 1.0)
        self.assertFalse(any("aramTenacity" in n for n in notes))

    def test_sr_mode_does_not_inject_aram_tenacity(self) -> None:
        champion = {"lolmath": {"aram_modifiers": {"aramTenacity": 1.20}}}
        out, notes = _apply_mode_modifiers({}, {}, "SR", champion)
        self.assertNotIn("aram_tenacity_mult", out)


class AramAhTenacityLiveSnapshotTests(unittest.TestCase):
    """Verify exposure via the full build_champion path with live data."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_live_soraka_aram_ah_plus_10(self) -> None:
        r = build_champion(self.snap, "Soraka", level=6, mode="ARAM")
        self.assertEqual(r.stats.get("aram_ability_haste"), 10.0)
        self.assertEqual(r.stats.get("aram_tenacity_mult"), 1.0)

    def test_live_katarina_aram_tenacity_plus_20(self) -> None:
        r = build_champion(self.snap, "Katarina", level=6, mode="ARAM")
        self.assertAlmostEqual(r.stats.get("aram_tenacity_mult"), 1.2)
        # Katarina also has aramAbilityHaste +10 in 16.10.1.
        self.assertEqual(r.stats.get("aram_ability_haste"), 10.0)

    def test_live_seraphine_aram_ah_minus_20(self) -> None:
        r = build_champion(self.snap, "Seraphine", level=6, mode="ARAM")
        self.assertEqual(r.stats.get("aram_ability_haste"), -20.0)

    def test_sr_mode_strips_aram_fields(self) -> None:
        r = build_champion(self.snap, "Soraka", level=6, mode="SR")
        self.assertNotIn("aram_ability_haste", r.stats)
        self.assertNotIn("aram_tenacity_mult", r.stats)


class WukongAliasTest(unittest.TestCase):
    """Sanity check the DDragon-id aliases from the extractor still resolve."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_wukong_resolves_as_monkeyking(self) -> None:
        r = build_champion(self.snap, "MonkeyKing", level=1)
        self.assertEqual(r.champion_name, "Wukong")

    def test_renata_resolves(self) -> None:
        r = build_champion(self.snap, "Renata", level=1)
        self.assertEqual(r.champion_id, "Renata")


if __name__ == "__main__":
    unittest.main()
