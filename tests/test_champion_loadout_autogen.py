"""s215 (2026-05-15) - champion_loadout_autogen tests.

Verifies the 3-variant fill policy, hand-curated preservation, mode
isolation, key-stability semantics, and the archetype-triplet
resolver. DS engine calls are stubbed end-to-end via
``unittest.mock.patch`` so tests don't require a running :8893.

Pinning these behaviors keeps the generator stable even if the
underlying DS scorer rankings shift patch-to-patch.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# Project root: tests/ → C:\Riot Commander\
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools import champion_loadout_autogen as autogen


def _fake_rank(item_names: list[str]):
    """Build a fake DS-engine response shaped like the real dispatcher."""
    return {
        "ok": True,
        "scorer": "dps",
        "archetype": "carry",
        "ranked": [
            {"item_id": str(1000 + i), "item_name": nm,
             "delta_dps": 50.0 - i, "delta_ehp": 0.0,
             "gold": 3000, "shares_dead_unique": False, "dead_unique_key": ""}
            for i, nm in enumerate(item_names)
        ],
        "fell_back": False,
    }


class VariantKeyTests(unittest.TestCase):
    def test_key_combines_mode_slot_archetype(self):
        self.assertEqual(
            autogen.variant_key("sr", "primary", "bruiser"),
            "auto-sr-primary-bruiser",
        )

    def test_key_modes_dont_collide(self):
        sr = autogen.variant_key("sr", "primary", "bruiser")
        aram = autogen.variant_key("aram", "primary", "bruiser")
        arena = autogen.variant_key("arena", "primary", "bruiser")
        self.assertEqual(len({sr, aram, arena}), 3)

    def test_key_prefix_is_auto(self):
        key = autogen.variant_key("sr", "flavor", "carry")
        self.assertTrue(key.startswith(autogen.AUTO_KEY_PREFIX))


class SummonersForTests(unittest.TestCase):
    def test_aram_always_flash_mark(self):
        self.assertEqual(autogen.summoners_for("aram", "carry"), [4, 32])
        self.assertEqual(autogen.summoners_for("aram", "tank"), [4, 32])

    def test_arena_always_flash_heal(self):
        self.assertEqual(autogen.summoners_for("arena", "bruiser"), [4, 7])
        self.assertEqual(autogen.summoners_for("arena", "enchanter"), [4, 7])

    def test_sr_carry_is_flash_barrier(self):
        self.assertEqual(autogen.summoners_for("sr", "carry"), [4, 21])

    def test_sr_bruiser_is_flash_tp(self):
        self.assertEqual(autogen.summoners_for("sr", "bruiser"), [4, 12])

    def test_sr_mage_is_flash_ignite(self):
        self.assertEqual(autogen.summoners_for("sr", "mage"), [4, 14])

    def test_sr_enchanter_is_flash_exhaust(self):
        self.assertEqual(autogen.summoners_for("sr", "enchanter"), [4, 3])

    def test_unknown_archetype_falls_back_to_flash_ignite(self):
        # Defensive: unknown arch → mid-default 4+14
        self.assertEqual(autogen.summoners_for("sr", "xyz"), [4, 14])


class ResolveArchetypeTripletTests(unittest.TestCase):
    def test_distinct_primary_secondary_keeps_both(self):
        triplet = autogen.resolve_archetype_triplet("bruiser", "tank")
        slots = [s for s, _ in triplet]
        archs = [a for _, a in triplet]
        self.assertEqual(slots, ["primary", "secondary", "flavor"])
        self.assertEqual(archs[0], "bruiser")
        self.assertEqual(archs[1], "tank")
        # Flavor for bruiser primary → carry per heuristic
        self.assertEqual(archs[2], "carry")

    def test_primary_equals_secondary_picks_alternate_secondary(self):
        triplet = autogen.resolve_archetype_triplet("tank", "tank")
        archs = [a for _, a in triplet]
        self.assertEqual(archs[0], "tank")
        self.assertNotEqual(archs[1], "tank")

    def test_flavor_avoids_collision(self):
        # If heuristic would pick something already in triplet, cascade.
        # bruiser primary, carry secondary → heuristic flavor would be carry
        # (collision) → must pick something else.
        triplet = autogen.resolve_archetype_triplet("bruiser", "carry")
        archs = [a for _, a in triplet]
        self.assertEqual(len(set(archs)), 3)

    def test_flavor_for_mage_is_assassin(self):
        triplet = autogen.resolve_archetype_triplet("mage", "tank")
        self.assertEqual(triplet[2][1], "assassin")

    def test_enchanter_flavor_is_mage(self):
        triplet = autogen.resolve_archetype_triplet("enchanter", "mage")
        # heuristic third is mage but secondary is mage → cascade to next
        archs = [a for _, a in triplet]
        self.assertEqual(len(set(archs)), 3)
        self.assertEqual(archs[0], "enchanter")
        self.assertEqual(archs[1], "mage")
        # third must be != enchanter and != mage
        self.assertNotIn(archs[2], ("enchanter", "mage"))


class CountExistingModeVariantsTests(unittest.TestCase):
    def test_curated_counted_when_mode_matches(self):
        variants = {
            "bruiser": {"modes": ["sr", "aram"]},
            "tank":    {"modes": ["sr"]},
        }
        self.assertEqual(
            autogen.count_existing_mode_variants(variants, "sr"), 2,
        )
        self.assertEqual(
            autogen.count_existing_mode_variants(variants, "aram"), 1,
        )

    def test_auto_entries_not_counted(self):
        variants = {
            "bruiser":                    {"modes": ["sr"]},
            "auto-sr-primary-bruiser":    {"modes": ["sr"], "_auto": True},
            "auto-sr-secondary-tank":     {"modes": ["sr"], "_auto": True},
        }
        # Only curated `bruiser` counts toward the 3-slot budget.
        self.assertEqual(
            autogen.count_existing_mode_variants(variants, "sr"), 1,
        )

    def test_empty_variants_returns_zero(self):
        self.assertEqual(autogen.count_existing_mode_variants({}, "sr"), 0)
        self.assertEqual(autogen.count_existing_mode_variants(None, "sr"), 0)


class GenerateForChampionTests(unittest.TestCase):
    """End-to-end gen test with DS engine stubbed."""

    def _patch_ds(self, item_names: list[str]):
        return mock.patch.object(
            autogen.dsc,
            "rank_for_primary_archetype",
            return_value=_fake_rank(item_names),
        )

    def test_zero_curated_fills_to_three(self):
        with self._patch_ds(["Item A", "Item B", "Item C"]):
            new_vars, stats = autogen.generate_for_champion(
                "Aatrox", {}, modes=("sr",), level=11,
            )
        self.assertEqual(stats["sr"]["curated"], 0)
        self.assertEqual(stats["sr"]["auto"], 3)
        self.assertEqual(stats["sr"]["unfilled"], 0)
        auto_keys = [k for k in new_vars.keys() if k.startswith("auto-")]
        self.assertEqual(len(auto_keys), 3)

    def test_three_curated_skips_auto(self):
        curated = {
            "bruiser":   {"label": "Bruiser",   "modes": ["sr"],
                          "runes": {}, "summoners": [4, 12], "items": ["X"]},
            "tank":      {"label": "Tank",      "modes": ["sr"],
                          "runes": {}, "summoners": [4, 12], "items": ["Y"]},
            "splitpush": {"label": "Splitpush", "modes": ["sr"],
                          "runes": {}, "summoners": [4, 12], "items": ["Z"]},
        }
        with self._patch_ds(["Item A"]):
            new_vars, stats = autogen.generate_for_champion(
                "Aatrox", curated, modes=("sr",), level=11,
            )
        self.assertEqual(stats["sr"]["curated"], 3)
        self.assertEqual(stats["sr"]["auto"], 0)
        # No auto-* keys for SR
        self.assertFalse(any(k.startswith("auto-sr-") for k in new_vars.keys()))
        # Curated all preserved
        self.assertIn("bruiser", new_vars)
        self.assertIn("tank", new_vars)
        self.assertIn("splitpush", new_vars)

    def test_one_curated_fills_two_auto(self):
        curated = {
            "bruiser": {"label": "Bruiser", "modes": ["sr"],
                        "runes": {}, "summoners": [4, 12], "items": ["X"]},
        }
        with self._patch_ds(["Item A"]):
            new_vars, stats = autogen.generate_for_champion(
                "Aatrox", curated, modes=("sr",), level=11,
            )
        self.assertEqual(stats["sr"]["curated"], 1)
        self.assertEqual(stats["sr"]["auto"], 2)
        auto_keys = [k for k in new_vars.keys() if k.startswith("auto-sr-")]
        self.assertEqual(len(auto_keys), 2)
        self.assertIn("bruiser", new_vars)  # curated preserved

    def test_modes_isolated(self):
        # SR curated saturated, ARAM empty → only ARAM gets auto entries
        curated = {
            f"v{i}": {"label": f"v{i}", "modes": ["sr"], "runes": {},
                      "summoners": [4, 12], "items": ["X"]}
            for i in range(3)
        }
        with self._patch_ds(["Item A"]):
            new_vars, stats = autogen.generate_for_champion(
                "Aatrox", curated, modes=("sr", "aram"), level=11,
            )
        self.assertEqual(stats["sr"]["auto"], 0)
        self.assertEqual(stats["aram"]["auto"], 3)
        self.assertFalse(any(k.startswith("auto-sr-") for k in new_vars.keys()))
        self.assertTrue(any(k.startswith("auto-aram-") for k in new_vars.keys()))

    def test_curated_entry_with_two_modes_counts_for_both(self):
        # A single curated variant with modes=[sr, aram] fills BOTH slots.
        curated = {
            "bruiser": {"label": "Bruiser", "modes": ["sr", "aram"],
                        "runes": {}, "summoners": [4, 12], "items": ["X"]},
        }
        with self._patch_ds(["Item A"]):
            _new_vars, stats = autogen.generate_for_champion(
                "Aatrox", curated, modes=("sr", "aram"), level=11,
            )
        # 1 counted in BOTH sr and aram → 2 auto each
        self.assertEqual(stats["sr"]["curated"], 1)
        self.assertEqual(stats["sr"]["auto"], 2)
        self.assertEqual(stats["aram"]["curated"], 1)
        self.assertEqual(stats["aram"]["auto"], 2)

    def test_ds_engine_miss_marks_unfilled(self):
        # DS returns None (engine down) → all 3 slots unfilled
        with mock.patch.object(autogen.dsc, "rank_for_primary_archetype",
                               return_value=None):
            new_vars, stats = autogen.generate_for_champion(
                "Aatrox", {}, modes=("sr",), level=11,
            )
        self.assertEqual(stats["sr"]["auto"], 0)
        self.assertEqual(stats["sr"]["unfilled"], 3)
        self.assertFalse(any(k.startswith("auto-") for k in new_vars.keys()))

    def test_rerun_refreshes_auto_entries_in_place(self):
        """A second run with different DS items should overwrite, not bloat."""
        with self._patch_ds(["Item A", "Item B", "Item C"]):
            first, _ = autogen.generate_for_champion(
                "Aatrox", {}, modes=("sr",), level=11,
            )
        first_auto_keys = {k for k in first.keys() if k.startswith("auto-")}
        with self._patch_ds(["Refreshed X", "Y", "Z"]):
            second, _ = autogen.generate_for_champion(
                "Aatrox", first, modes=("sr",), level=11,
            )
        second_auto_keys = {k for k in second.keys() if k.startswith("auto-")}
        self.assertEqual(first_auto_keys, second_auto_keys)
        # Items refreshed
        for k in second_auto_keys:
            self.assertEqual(second[k]["items"][0], "Refreshed X")


class VariantShapeTests(unittest.TestCase):
    """Pin the wire-shape of auto entries so the resolver doesn't break."""

    def setUp(self):
        self.ds_patch = mock.patch.object(
            autogen.dsc,
            "rank_for_primary_archetype",
            return_value=_fake_rank(["Item A", "Item B", "Item C"]),
        )
        self.ds_patch.start()

    def tearDown(self):
        self.ds_patch.stop()

    def test_variant_carries_required_fields(self):
        v = autogen.build_variant("Aatrox", "bruiser", "sr", level=11)
        self.assertIn("label", v)
        self.assertIn("modes", v)
        self.assertIn("runes", v)
        self.assertIn("summoners", v)
        self.assertIn("items", v)
        self.assertIn("_auto", v)
        self.assertIn("_archetype", v)
        self.assertTrue(v["_auto"])
        self.assertEqual(v["_archetype"], "bruiser")

    def test_runes_shape_matches_curated(self):
        v = autogen.build_variant("Aatrox", "bruiser", "sr", level=11)
        runes = v["runes"]
        self.assertIn("keystone", runes)
        self.assertIn("primary", runes)
        self.assertIn("secondary", runes)
        self.assertEqual(runes["keystone"], "Conqueror")

    def test_summoners_is_two_ints(self):
        v = autogen.build_variant("Aatrox", "bruiser", "sr", level=11)
        self.assertEqual(len(v["summoners"]), 2)
        for s in v["summoners"]:
            self.assertIsInstance(s, int)

    def test_items_exact_target_len_per_mode(self):
        # Item s8 (2026-06-10): generation-time length invariant - SR 7
        # (6 engine picks + boots at index 1), ARAM 6 (5 + boots),
        # Arena 6 (no boots). Overlong engine returns are tail-trimmed,
        # short ones padded from the shared item-213 pools.
        with mock.patch.object(
            autogen.dsc, "rank_for_primary_archetype",
            return_value=_fake_rank([f"Item {i}" for i in range(10)]),
        ):
            v_sr = autogen.build_variant("Aatrox", "bruiser", "sr", level=11)
            v_aram = autogen.build_variant("Aatrox", "bruiser", "aram", level=11)
            v_arena = autogen.build_variant("Aatrox", "bruiser", "arena", level=11)
        self.assertEqual(len(v_sr["items"]), 7)
        self.assertEqual(len(v_aram["items"]), 6)
        self.assertEqual(len(v_arena["items"]), 6)

    def test_sr_items_carry_boots_at_index_1_arena_none(self):
        # The boots slot is injected at generation time (same Cleaner
        # reseat the item-s8 sweep uses) so a regen emits canonical rows.
        boots = {
            "Berserker's Greaves", "Boots of Swiftness", "Plated Steelcaps",
            "Mercury's Treads", "Sorcerer's Shoes",
            "Ionian Boots of Lucidity", "Mobility Boots", "Symbiotic Soles",
            "Synchronized Souls", "Slightly Magical Footwear",
        }
        with mock.patch.object(
            autogen.dsc, "rank_for_primary_archetype",
            return_value=_fake_rank([f"Item {i}" for i in range(10)]),
        ):
            v_sr = autogen.build_variant("Aatrox", "bruiser", "sr", level=11)
            v_arena = autogen.build_variant("Aatrox", "bruiser", "arena", level=11)
        self.assertIn(v_sr["items"][1], boots)
        self.assertFalse(set(v_arena["items"]) & boots)

    def test_modes_is_single_entry_list(self):
        v_sr = autogen.build_variant("Aatrox", "bruiser", "sr", level=11)
        v_aram = autogen.build_variant("Aatrox", "bruiser", "aram", level=11)
        self.assertEqual(v_sr["modes"], ["sr"])
        self.assertEqual(v_aram["modes"], ["aram"])


class EnsureDefaultPerModeTests(unittest.TestCase):
    def test_sets_default_when_missing(self):
        entry = {
            "variants": {
                "auto-sr-primary-bruiser": {"modes": ["sr"]},
                "auto-sr-secondary-tank":  {"modes": ["sr"]},
            },
        }
        autogen.ensure_default_per_mode(entry, "sr", "bruiser")
        self.assertEqual(entry["default_per_mode"]["sr"], "auto-sr-primary-bruiser")

    def test_preserves_existing_default(self):
        # Operator already set a default - do not overwrite
        entry = {
            "default_per_mode": {"sr": "custom-bruiser"},
            "variants": {
                "custom-bruiser":          {"modes": ["sr"]},
                "auto-sr-primary-bruiser": {"modes": ["sr"]},
            },
        }
        autogen.ensure_default_per_mode(entry, "sr", "bruiser")
        self.assertEqual(entry["default_per_mode"]["sr"], "custom-bruiser")

    def test_no_default_when_auto_primary_missing(self):
        # DS engine returned nothing for primary → no auto-primary key →
        # don't fabricate a broken default pointer.
        entry = {"variants": {"auto-sr-secondary-tank": {"modes": ["sr"]}}}
        autogen.ensure_default_per_mode(entry, "sr", "bruiser")
        self.assertNotIn("sr", entry.get("default_per_mode", {}))


class ResetAutoEntriesTests(unittest.TestCase):
    def test_drops_auto_keeps_curated(self):
        payload = {
            "champions": {
                "Aatrox": {
                    "variants": {
                        "bruiser":                {"modes": ["sr"]},
                        "auto-sr-primary-bruiser": {"modes": ["sr"]},
                        "auto-aram-flavor-carry":  {"modes": ["aram"]},
                    },
                },
            },
        }
        autogen.reset_auto_entries(payload)
        variants = payload["champions"]["Aatrox"]["variants"]
        self.assertIn("bruiser", variants)
        self.assertFalse(any(k.startswith("auto-") for k in variants.keys()))


class AtomicWriteLoadoutsTests(unittest.TestCase):
    def test_writes_sorted_champions(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp) / "champion_loadouts.json"
            with mock.patch.object(autogen, "_LOADOUTS_PATH", tmp_path):
                payload = {
                    "champions": {
                        "Zed":     {"default_per_mode": {}, "variants": {"a": {}}},
                        "Aatrox":  {"default_per_mode": {}, "variants": {"b": {}}},
                        "Lulu":    {"default_per_mode": {}, "variants": {"c": {}}},
                    },
                }
                autogen.atomic_write_loadouts(payload)
                written = json.loads(tmp_path.read_text(encoding="utf-8"))
                champs = list(written["champions"].keys())
                self.assertEqual(champs, sorted(champs, key=str.lower))


if __name__ == "__main__":
    unittest.main()
