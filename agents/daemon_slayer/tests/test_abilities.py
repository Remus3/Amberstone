"""Phase 4a (s177, 2026-05-12) — champion ability ingest + loader tests.

Two halves:

* Pure unit tests of the extractor's normalization helpers — synthetic
  Meraki-shaped dicts, no HTTP. These pin the unit-string → typed-field
  map, the damage-vs-modifier classifier, and the parse_status decision
  table so future Meraki schema drift can't silently downgrade coverage.
* End-to-end loader tests against the live 16.9.1 snapshot — Aatrox/Veigar/
  Ezreal/MonkeyKing/Jayce known shapes pinned. A coverage threshold
  assertion (``parse_status_counts["ok"] / damage_eligible >= 0.85``)
  defends against regressions on future patch extracts.
"""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from agents.daemon_slayer.abilities import (
    AbilitiesNotFound,
    AbilitiesSnapshot,
    AbilityForm,
    DamageBlock,
    load_default,
    reset_default_cache,
)

# Load the extractor module via importlib — tools/ has no __init__.py.
_EXTRACT_PATH = Path(__file__).resolve().parents[3] / "tools" / "daemon_slayer_abilities_extract.py"
_spec = importlib.util.spec_from_file_location("ds_abilities_extract", _EXTRACT_PATH)
extract = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(extract)


# ─── Extractor unit tests ────────────────────────────────────────────────────

class NormalizeDamageTypeTests(unittest.TestCase):
    def test_physical_damage(self) -> None:
        self.assertEqual(extract._normalize_damage_type("PHYSICAL_DAMAGE"), "PHYSICAL")

    def test_magic_damage(self) -> None:
        self.assertEqual(extract._normalize_damage_type("MAGIC_DAMAGE"), "MAGIC")

    def test_true_damage(self) -> None:
        self.assertEqual(extract._normalize_damage_type("TRUE_DAMAGE"), "TRUE")

    def test_mixed_damage(self) -> None:
        self.assertEqual(extract._normalize_damage_type("MIXED_DAMAGE"), "MIXED")

    def test_none_input(self) -> None:
        self.assertIsNone(extract._normalize_damage_type(None))

    def test_unknown_passes_through_as_none(self) -> None:
        self.assertIsNone(extract._normalize_damage_type("OTHER_DAMAGE"))


class IsAoeTests(unittest.TestCase):
    def test_enemies_plural_is_aoe(self) -> None:
        self.assertTrue(extract._is_aoe("Enemies", "Direction"))

    def test_enemy_singular_with_unit_is_not_aoe(self) -> None:
        self.assertFalse(extract._is_aoe("Enemy", "Unit"))

    def test_direction_targeting_is_aoe(self) -> None:
        self.assertTrue(extract._is_aoe(None, "Direction"))

    def test_location_targeting_is_aoe(self) -> None:
        self.assertTrue(extract._is_aoe(None, "Location"))

    def test_passive_with_no_signals_is_not_aoe(self) -> None:
        self.assertFalse(extract._is_aoe(None, "Passive"))


class ValuesTupleTests(unittest.TestCase):
    def test_pure_numeric_list(self) -> None:
        self.assertEqual(extract._values_tuple([1, 2.5, 3]), [1.0, 2.5, 3.0])

    def test_none_input(self) -> None:
        self.assertIsNone(extract._values_tuple(None))

    def test_empty_list(self) -> None:
        self.assertIsNone(extract._values_tuple([]))

    def test_string_with_percent_sign(self) -> None:
        # "5%" → 5.0
        self.assertEqual(extract._values_tuple(["5%", "10%"]), [5.0, 10.0])

    def test_garbage_input_returns_none(self) -> None:
        self.assertIsNone(extract._values_tuple([{"x": 1}]))


class NormalizeCooldownOrCostTests(unittest.TestCase):
    def test_dict_form_with_modifiers(self) -> None:
        raw = {"modifiers": [{"values": [6, 5.5, 5, 4.5, 4], "units": ["", "", "", "", ""]}]}
        self.assertEqual(extract._normalize_cooldown_or_cost(raw), [6.0, 5.5, 5.0, 4.5, 4.0])

    def test_bare_list_fallback(self) -> None:
        self.assertEqual(extract._normalize_cooldown_or_cost([14, 12, 10, 8, 6]),
                         [14.0, 12.0, 10.0, 8.0, 6.0])

    def test_empty_modifiers(self) -> None:
        self.assertIsNone(extract._normalize_cooldown_or_cost({"modifiers": []}))

    def test_none_input(self) -> None:
        self.assertIsNone(extract._normalize_cooldown_or_cost(None))


class ClassifyAttributeTests(unittest.TestCase):
    def test_first_cast_damage_is_damage(self) -> None:
        self.assertEqual(extract._classify_attribute("First Cast Damage"), "damage")

    def test_magic_damage_is_damage(self) -> None:
        self.assertEqual(extract._classify_attribute("Magic Damage"), "damage")

    def test_burn_attribute_is_damage(self) -> None:
        self.assertEqual(extract._classify_attribute("Burn Per Second"), "damage")

    def test_damage_reduction_is_modifier(self) -> None:
        self.assertEqual(extract._classify_attribute("Damage Reduction"), "modifier")

    def test_critical_damage_is_modifier(self) -> None:
        self.assertEqual(extract._classify_attribute("Critical Damage"), "modifier")

    def test_monster_damage_is_modifier(self) -> None:
        self.assertEqual(extract._classify_attribute("Monster Bonus Damage"), "modifier")

    def test_healing_strength_is_heal(self) -> None:
        self.assertEqual(extract._classify_attribute("Healing Strength"), "heal")

    def test_shield_strength_is_shield(self) -> None:
        self.assertEqual(extract._classify_attribute("Shield Strength"), "shield")

    def test_slow_strength_is_slow(self) -> None:
        self.assertEqual(extract._classify_attribute("Slow Strength"), "slow")

    def test_stun_duration_is_duration(self) -> None:
        self.assertEqual(extract._classify_attribute("Stun Duration"), "duration")

    def test_unknown_attribute_is_other(self) -> None:
        self.assertEqual(extract._classify_attribute("Bench Press Reps"), "other")


class NormalizeModifiersTests(unittest.TestCase):
    def test_pure_flat_base(self) -> None:
        mods = [{"values": [10, 25, 40, 55, 70], "units": ["", "", "", "", ""]}]
        typed, unparsed = extract._normalize_modifiers(mods)
        self.assertEqual(typed, {"base": [10.0, 25.0, 40.0, 55.0, 70.0]})
        self.assertEqual(unparsed, [])

    def test_total_ad_scaling(self) -> None:
        mods = [{"values": [60, 67.5, 75, 82.5, 90], "units": ["% AD"] * 5}]
        typed, unparsed = extract._normalize_modifiers(mods)
        self.assertEqual(typed, {"total_ad_pct": [60.0, 67.5, 75.0, 82.5, 90.0]})
        self.assertEqual(unparsed, [])

    def test_bonus_ad_scaling(self) -> None:
        mods = [{"values": [75], "units": ["% bonus AD"]}]
        typed, unparsed = extract._normalize_modifiers(mods)
        self.assertEqual(typed, {"bonus_ad_pct": [75.0]})

    def test_ap_scaling(self) -> None:
        mods = [{"values": [40], "units": ["% AP"]}]
        typed, _ = extract._normalize_modifiers(mods)
        self.assertEqual(typed, {"ap_pct": [40.0]})

    def test_target_max_hp_scaling(self) -> None:
        mods = [{"values": [10], "units": ["% of target's maximum health"]}]
        typed, _ = extract._normalize_modifiers(mods)
        self.assertEqual(typed, {"target_max_hp_pct": [10.0]})

    def test_target_max_hp_double_space_variant(self) -> None:
        """Meraki sometimes ships ``"%  of target's maximum health"`` with
        two spaces — caught by the explicit alias in ``_UNIT_TO_FIELD``."""
        mods = [{"values": [10], "units": ["%  of target's maximum health"]}]
        typed, _ = extract._normalize_modifiers(mods)
        self.assertEqual(typed, {"target_max_hp_pct": [10.0]})

    def test_multi_modifier_typed_separate(self) -> None:
        mods = [
            {"values": [5, 30, 55, 80], "units": ["", "", "", ""]},
            {"values": [75], "units": ["% AD"]},
            {"values": [40], "units": ["% AP"]},
        ]
        typed, unparsed = extract._normalize_modifiers(mods)
        self.assertEqual(typed["base"], [5.0, 30.0, 55.0, 80.0])
        self.assertEqual(typed["total_ad_pct"], [75.0])
        self.assertEqual(typed["ap_pct"], [40.0])
        self.assertEqual(unparsed, [])

    def test_unknown_unit_goes_to_unparsed(self) -> None:
        mods = [{"values": [10], "units": ["% of weird unit"]}]
        typed, unparsed = extract._normalize_modifiers(mods)
        self.assertEqual(typed, {})
        self.assertEqual(unparsed, mods)

    def test_known_non_damage_unit_is_silently_dropped(self) -> None:
        mods = [{"values": [3.5], "units": [" seconds"]}]
        typed, unparsed = extract._normalize_modifiers(mods)
        self.assertEqual(typed, {})
        self.assertEqual(unparsed, [])

    def test_same_field_from_two_modifiers_sums(self) -> None:
        # Two modifiers both mapping to "base" — sum element-wise (rare but
        # happens with Sweetspot-merged blocks).
        mods = [
            {"values": [10, 20], "units": ["", ""]},
            {"values": [5, 10], "units": ["", ""]},
        ]
        typed, _ = extract._normalize_modifiers(mods)
        self.assertEqual(typed["base"], [15.0, 30.0])


class BuildDamageBlockTests(unittest.TestCase):
    def test_damage_attribute_typed(self) -> None:
        lvl = {
            "attribute": "First Cast Damage",
            "modifiers": [{"values": [10, 25, 40, 55, 70], "units": ["", "", "", "", ""]}],
        }
        block = extract._build_damage_block(lvl)
        self.assertEqual(block["attribute_kind"], "damage")
        self.assertEqual(block["base"], [10.0, 25.0, 40.0, 55.0, 70.0])

    def test_modifier_attribute_preserves_raw(self) -> None:
        lvl = {
            "attribute": "Damage Reduction",
            "modifiers": [{"values": [40, 50, 60], "units": ["%", "%", "%"]}],
        }
        block = extract._build_damage_block(lvl)
        self.assertEqual(block["attribute_kind"], "modifier")
        self.assertEqual(block["raw_modifiers"], lvl["modifiers"])

    def test_heal_attribute_kind(self) -> None:
        lvl = {
            "attribute": "Healing per Second",
            "modifiers": [{"values": [20, 30, 40], "units": ["", "", ""]}],
        }
        block = extract._build_damage_block(lvl)
        self.assertEqual(block["attribute_kind"], "heal")
        self.assertIn("raw_modifiers", block)


class BuildFormTests(unittest.TestCase):
    def _veigar_q_payload(self) -> dict:
        return {
            "name": "Baleful Strike",
            "icon": "https://example/q.png",
            "cooldown": {"modifiers": [{"values": [6, 5.5, 5, 4.5, 4], "units": ["", "", "", "", ""]}]},
            "cost": {"modifiers": [{"values": [30, 35, 40, 45, 50], "units": ["", "", "", "", ""]}]},
            "damageType": "MAGIC_DAMAGE",
            "targeting": "Unit",
            "affects": "Enemies",
            "resource": "MANA",
            "effects": [
                {
                    "description": "Active text.",
                    "leveling": [
                        {
                            "attribute": "Magic Damage",
                            "modifiers": [
                                {"values": [80, 120, 160, 200, 240], "units": ["", "", "", "", ""]},
                                {"values": [50, 55, 60, 65, 70], "units": ["% AP"] * 5},
                            ],
                        }
                    ],
                }
            ],
        }

    def test_parse_status_ok_for_full_form(self) -> None:
        form = extract._build_form(self._veigar_q_payload(), 0, "Q")
        self.assertEqual(form["parse_status"], "ok")
        self.assertEqual(form["damage_type"], "MAGIC")
        self.assertEqual(form["cooldown"], [6.0, 5.5, 5.0, 4.5, 4.0])
        self.assertEqual(form["cost"], [30.0, 35.0, 40.0, 45.0, 50.0])
        self.assertTrue(form["is_aoe"])  # "Enemies" plural
        block = form["damage_blocks"][0]
        self.assertEqual(block["base"], [80.0, 120.0, 160.0, 200.0, 240.0])
        self.assertEqual(block["ap_pct"], [50.0, 55.0, 60.0, 65.0, 70.0])

    def test_parse_status_no_damage_when_no_damage_block(self) -> None:
        passive = {
            "name": "Phenomenal Evil Power",
            "effects": [{"description": "Stacking AP passive.", "leveling": []}],
        }
        form = extract._build_form(passive, 0, "P")
        self.assertEqual(form["parse_status"], "no_damage")

    def test_parse_status_partial_when_aggregate_block_empty(self) -> None:
        """One typed block + one damage-attribute block with no modifiers
        (aggregate field) → partial."""
        payload = {
            "name": "Test",
            "effects": [{
                "description": "x",
                "leveling": [
                    {"attribute": "Minimum Magic Damage",
                     "modifiers": [{"values": [10, 20, 30], "units": ["", "", ""]}]},
                    {"attribute": "Maximum Aggregate Damage", "modifiers": []},
                ],
            }],
        }
        form = extract._build_form(payload, 0, "Q")
        self.assertEqual(form["parse_status"], "partial")

    def test_parse_status_unparsed_when_all_modifiers_unknown(self) -> None:
        payload = {
            "name": "Test",
            "effects": [{
                "description": "x",
                "leveling": [
                    {"attribute": "Magic Damage",
                     "modifiers": [{"values": [10], "units": ["% of weird"]}]},
                ],
            }],
        }
        form = extract._build_form(payload, 0, "Q")
        self.assertEqual(form["parse_status"], "unparsed")


# ─── Loader tests against the live snapshot ──────────────────────────────────

class SnapshotLoadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        reset_default_cache()
        cls.snap = AbilitiesSnapshot.load()

    def test_patch_label_set(self) -> None:
        self.assertTrue(self.snap.patch)
        self.assertTrue(self.snap.fetched_at)

    def test_source_url_recorded(self) -> None:
        self.assertIn("merakianalytics", self.snap.source)

    def test_champion_count_close_to_172(self) -> None:
        # DDragon has 172; Meraki bulk lags brand-new releases by 1-3 patches.
        # Assert >= 160 to allow some slack but flag a major regression.
        self.assertGreaterEqual(len(self.snap.champions), 160)

    def test_aatrox_present(self) -> None:
        self.assertTrue(self.snap.has_champion("Aatrox"))

    def test_monkeyking_keyed_by_ddragon_id(self) -> None:
        """Wukong's DDragon ID is "MonkeyKing"; Meraki bulk uses that as the
        top-level key. Verify the snapshot doesn't accidentally key by
        "Wukong" (the display name) since that breaks downstream resolvers."""
        self.assertTrue(self.snap.has_champion("MonkeyKing"))
        self.assertFalse(self.snap.has_champion("Wukong"))

    def test_ksante_keyed_by_ddragon_id(self) -> None:
        """K'Sante's DDragon ID is "KSante" (no apostrophe)."""
        self.assertTrue(self.snap.has_champion("KSante"))

    def test_unknown_champion_raises(self) -> None:
        with self.assertRaises(KeyError):
            self.snap.get_abilities("ChampionDoesNotExist")

    def test_unknown_ability_key_raises(self) -> None:
        with self.assertRaises(KeyError):
            self.snap.get_ability("Aatrox", "Z")

    def test_form_index_out_of_range_raises(self) -> None:
        # Aatrox has only one Q form.
        with self.assertRaises(KeyError):
            self.snap.get_ability("Aatrox", "Q", form_index=5)


class AatroxQTests(unittest.TestCase):
    """Pin Aatrox.Q[0] to known values so Meraki text changes can't silently
    redden the engine math."""

    @classmethod
    def setUpClass(cls) -> None:
        reset_default_cache()
        cls.q = AbilitiesSnapshot.load().get_ability("Aatrox", "Q")

    def test_form_basics(self) -> None:
        self.assertEqual(self.q.key, "Q")
        self.assertEqual(self.q.name, "The Darkin Blade")
        self.assertEqual(self.q.damage_type, "PHYSICAL")
        self.assertTrue(self.q.is_aoe)

    def test_first_cast_damage_base(self) -> None:
        damage = self.q.damage_blocks_only()
        first = next(b for b in damage if b.attribute == "First Cast Damage")
        self.assertEqual(first.base, (10.0, 25.0, 40.0, 55.0, 70.0))
        # At rank-5 (0-index 4) the base damage is 70.
        self.assertEqual(first.value_at("base", 4), 70.0)
        # No AP scaling on Aatrox Q.
        self.assertEqual(first.value_at("ap_pct", 0), 0.0)

    def test_first_cast_total_ad_pct(self) -> None:
        first = next(
            b for b in self.q.damage_blocks_only() if b.attribute == "First Cast Damage"
        )
        self.assertEqual(first.total_ad_pct, (60.0, 67.5, 75.0, 82.5, 90.0))


class VeigarQTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        reset_default_cache()
        cls.q = AbilitiesSnapshot.load().get_ability("Veigar", "Q")

    def test_cooldown_per_rank(self) -> None:
        self.assertEqual(self.q.cooldown, (6.0, 5.5, 5.0, 4.5, 4.0))

    def test_cost_per_rank(self) -> None:
        self.assertEqual(self.q.cost, (30.0, 35.0, 40.0, 45.0, 50.0))

    def test_magic_damage_block(self) -> None:
        damage = self.q.damage_blocks_only()
        self.assertEqual(len(damage), 1)
        block = damage[0]
        self.assertEqual(block.attribute, "Magic Damage")
        self.assertEqual(block.base, (80.0, 120.0, 160.0, 200.0, 240.0))
        self.assertEqual(block.ap_pct, (50.0, 55.0, 60.0, 65.0, 70.0))


class EzrealQTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        reset_default_cache()
        cls.q = AbilitiesSnapshot.load().get_ability("Ezreal", "Q")

    def test_q_has_total_ad_pct(self) -> None:
        damage = self.q.damage_blocks_only()
        block = next(b for b in damage if b.total_ad_pct is not None)
        # Q is Mystic Shot — 130% AD scaling at all ranks (same value 5x).
        self.assertEqual(block.total_ad_pct[0], 130.0)


class EzrealRTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        reset_default_cache()
        cls.r = AbilitiesSnapshot.load().get_ability("Ezreal", "R")

    def test_ult_has_three_rank_cooldown(self) -> None:
        self.assertEqual(len(self.r.cooldown), 3)

    def test_ult_damage_type_magic(self) -> None:
        self.assertEqual(self.r.damage_type, "MAGIC")


class MultiFormTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        reset_default_cache()
        cls.snap = AbilitiesSnapshot.load()

    def test_jayce_q_has_two_forms(self) -> None:
        forms = self.snap.get_abilities("Jayce")["Q"]
        self.assertEqual(len(forms), 2)
        self.assertNotEqual(forms[0].name, forms[1].name)

    def test_aphelios_q_has_six_forms(self) -> None:
        forms = self.snap.get_abilities("Aphelios")["Q"]
        # Aphelios has 5 weapons + 1 base form = 6.
        self.assertEqual(len(forms), 6)

    def test_aatrox_q_has_one_form(self) -> None:
        forms = self.snap.get_abilities("Aatrox")["Q"]
        self.assertEqual(len(forms), 1)


class DamageBlockTests(unittest.TestCase):
    def test_from_dict_round_trip(self) -> None:
        block = DamageBlock.from_dict({
            "attribute": "Magic Damage",
            "attribute_kind": "damage",
            "base": [80, 120, 160, 200, 240],
            "ap_pct": [50, 55, 60, 65, 70],
        })
        self.assertEqual(block.base, (80.0, 120.0, 160.0, 200.0, 240.0))
        self.assertEqual(block.ap_pct, (50.0, 55.0, 60.0, 65.0, 70.0))
        self.assertIsNone(block.total_ad_pct)
        self.assertTrue(block.has_damage_scaling())

    def test_value_at_clamps_to_last_when_short(self) -> None:
        block = DamageBlock(attribute="X", attribute_kind="damage",
                            total_ad_pct=(75.0,))
        # Single value should apply at every rank.
        self.assertEqual(block.value_at("total_ad_pct", 0), 75.0)
        self.assertEqual(block.value_at("total_ad_pct", 4), 75.0)

    def test_value_at_negative_rank_clamps_to_zero(self) -> None:
        block = DamageBlock(attribute="X", attribute_kind="damage",
                            base=(10.0, 20.0))
        self.assertEqual(block.value_at("base", -1), 10.0)

    def test_value_at_missing_field_returns_zero(self) -> None:
        block = DamageBlock(attribute="X", attribute_kind="damage",
                            base=(10.0,))
        self.assertEqual(block.value_at("ap_pct", 0), 0.0)

    def test_has_damage_scaling_false_for_empty_block(self) -> None:
        block = DamageBlock(attribute="X", attribute_kind="damage")
        self.assertFalse(block.has_damage_scaling())


class AbilityFormTests(unittest.TestCase):
    def test_damage_blocks_only_filters_non_damage(self) -> None:
        form = AbilityForm.from_dict({
            "key": "Q",
            "name": "Test",
            "form_index": 0,
            "icon": None,
            "cooldown": [10],
            "cost": [50],
            "damage_type": "MAGIC",
            "targeting": "Direction",
            "affects": "Enemies",
            "resource": "MANA",
            "is_aoe": True,
            "damage_blocks": [
                {"attribute": "Magic Damage", "attribute_kind": "damage", "base": [10]},
                {"attribute": "Damage Reduction", "attribute_kind": "modifier"},
                {"attribute": "Heal", "attribute_kind": "heal"},
            ],
            "raw_effects_count": 1,
            "raw_leveling_count": 3,
            "parse_status": "ok",
            "parse_notes": [],
        })
        damage = form.damage_blocks_only()
        self.assertEqual(len(damage), 1)
        self.assertEqual(damage[0].attribute, "Magic Damage")


class CoverageThresholdTests(unittest.TestCase):
    """Lock in the Phase 4a coverage promise — ~80% target per the plan,
    measured at 98% on first extract. Drop below 85% should redden CI to
    surface Meraki schema drift quickly."""

    @classmethod
    def setUpClass(cls) -> None:
        reset_default_cache()
        cls.snap = AbilitiesSnapshot.load()

    def test_ok_rate_above_threshold(self) -> None:
        coverage = self.snap.coverage
        self.assertGreaterEqual(
            coverage.get("ok_rate", 0.0), 0.85,
            f"ok_rate dropped below 0.85: coverage={coverage}",
        )

    def test_parsed_rate_above_threshold(self) -> None:
        coverage = self.snap.coverage
        self.assertGreaterEqual(
            coverage.get("parsed_rate", 0.0), 0.95,
            f"parsed_rate dropped below 0.95: coverage={coverage}",
        )

    def test_parse_status_counts_matches_coverage(self) -> None:
        computed = self.snap.parse_status_counts()
        snapshot_counts = self.snap.coverage.get("status_counts", {})
        for key in ("ok", "partial", "unparsed", "no_damage"):
            self.assertEqual(
                computed.get(key, 0), snapshot_counts.get(key, 0),
                f"status count drift for {key!r}",
            )

    def test_iter_forms_total_matches_snapshot(self) -> None:
        total = sum(1 for _ in self.snap.iter_forms())
        self.assertEqual(total, self.snap.coverage.get("total_forms", 0))


# ─── Module-level helpers ────────────────────────────────────────────────────

class SingletonCacheTests(unittest.TestCase):
    def test_load_default_caches(self) -> None:
        reset_default_cache()
        a = load_default()
        b = load_default()
        self.assertIs(a, b)

    def test_reset_default_cache_drops_singleton(self) -> None:
        a = load_default()
        reset_default_cache()
        b = load_default()
        self.assertIsNot(a, b)


class MissingSnapshotTests(unittest.TestCase):
    def test_missing_patch_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / "current.txt").write_text("99.9.9", encoding="utf-8")
            with self.assertRaises(AbilitiesNotFound):
                AbilitiesSnapshot.load(data_root=tmp)

    def test_missing_pointer_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            with self.assertRaises(AbilitiesNotFound):
                AbilitiesSnapshot.load(data_root=tmp)

    def test_empty_pointer_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / "current.txt").write_text("   ", encoding="utf-8")
            with self.assertRaises(AbilitiesNotFound):
                AbilitiesSnapshot.load(data_root=tmp)

    def test_load_with_explicit_patch_argument(self) -> None:
        """Bypass current.txt by passing the patch label directly."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            patch_dir = tmp / "16.9.1"
            patch_dir.mkdir()
            (patch_dir / "champion_abilities.json").write_text(json.dumps({
                "version": "16.9.1",
                "fetched_at": "2026-05-12T12:00:00",
                "source": "https://example/champions.json",
                "engine_phase": "4a",
                "count": 1,
                "coverage": {"total_forms": 0, "status_counts": {}, "ok_rate": 0.0, "parsed_rate": 0.0},
                "data": {"Aatrox": {"Q": [], "W": [], "E": [], "R": [], "P": []}},
            }), encoding="utf-8")
            snap = AbilitiesSnapshot.load(patch="16.9.1", data_root=tmp)
            self.assertEqual(snap.patch, "16.9.1")
            self.assertTrue(snap.has_champion("Aatrox"))


if __name__ == "__main__":
    unittest.main()
