"""
tests/phase2_smoke/test_daemon_slayer_resolver_modes.py
s74 - mode-aware byName lookup in daemon_slayer_resolver.

The resolver builds a per-mode byName index from DDragon's ``maps``
field so SR/ARAM/Brawl callers don't accidentally pick up the 22XXXX
Arena alias IDs that the legacy ``items_index.json`` byName surfaces
(see ``reference_items_index_alias_ids``). These tests pin the
mode-keyed lookups against the patch-current snapshot.

HP values flow through correctly when callers pass the right mode:
- mode='aram'/'sr'/'brawl' -> 3084 (Heartsteel SR base, 900 HP)
- mode='arena'             -> 223084 (Heartsteel Arena alias, 700 HP)
- mode=None                -> legacy quirk (whatever items_index byName picks)
"""
import sys
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from core import daemon_slayer_resolver as ds_res


class NameToIdModeAwareTests(unittest.TestCase):
    """name_to_id(name, mode=...) returns map-correct IDs."""

    def test_heartsteel_aram_returns_sr_base_id(self) -> None:
        # ARAM uses map 12; SR base item 3084 is valid there.
        self.assertEqual(ds_res.name_to_id("Heartsteel", mode="aram"), "3084")

    def test_heartsteel_sr_returns_sr_base_id(self) -> None:
        self.assertEqual(ds_res.name_to_id("Heartsteel", mode="sr"), "3084")

    def test_heartsteel_brawl_returns_sr_base_id(self) -> None:
        # Brawl is map 35; uses SR/ARAM base items, NOT Arena aliases.
        self.assertEqual(ds_res.name_to_id("Heartsteel", mode="brawl"), "3084")

    def test_heartsteel_arena_returns_alias_id(self) -> None:
        # Arena (map 30) has its own 22XXXX-prefixed variants with
        # different HP/cost. arena_coach explicitly relies on this.
        self.assertEqual(ds_res.name_to_id("Heartsteel", mode="arena"), "223084")

    def test_riftmaker_aram_returns_sr_base_id(self) -> None:
        self.assertEqual(ds_res.name_to_id("Riftmaker", mode="aram"), "4633")

    def test_riftmaker_arena_returns_alias_id(self) -> None:
        self.assertEqual(ds_res.name_to_id("Riftmaker", mode="arena"), "224633")

    def test_mode_uppercase_normalized(self) -> None:
        # Coach loops carry mode as "ARAM" / "ARENA"; resolver handles
        # case insensitively.
        self.assertEqual(ds_res.name_to_id("Heartsteel", mode="ARAM"), "3084")
        self.assertEqual(ds_res.name_to_id("Heartsteel", mode="ARENA"), "223084")

    def test_mode_none_resolves_canonical_id(self) -> None:
        # items_index.json was fixed (commit 41c87bc) to sort by ID length
        # so 4-digit canonical IDs win over 6-digit 22XXXX aliases. The
        # old "setdefault first-seen-wins alias quirk" is gone - mode=None
        # now returns the canonical base ID, same as mode='aram'/'sr'.
        self.assertEqual(ds_res.name_to_id("Heartsteel"), "3084")
        self.assertEqual(ds_res.name_to_id("Heartsteel", mode=None), "3084")

    def test_unknown_mode_falls_through_to_legacy(self) -> None:
        # Unknown modes (e.g. 'tft') fall through to legacy lookup
        # rather than raising. Defensive - bad mode strings shouldn't
        # break coach loops. Post-41c87bc the legacy path returns 3084.
        self.assertEqual(ds_res.name_to_id("Heartsteel", mode="tft"), "3084")

    def test_unknown_name_returns_none_in_any_mode(self) -> None:
        for m in (None, "aram", "arena", "sr", "brawl"):
            self.assertIsNone(ds_res.name_to_id("Not An Item", mode=m), msg=f"mode={m}")

    def test_empty_name_returns_none(self) -> None:
        self.assertIsNone(ds_res.name_to_id("", mode="aram"))
        self.assertIsNone(ds_res.name_to_id(None, mode="aram"))


class ResolveManyModeAwareTests(unittest.TestCase):
    """resolve_many forwards mode and skips unknowns."""

    def test_resolve_many_aram_returns_sr_base_ids(self) -> None:
        ids = ds_res.resolve_many(["Heartsteel", "Riftmaker"], mode="aram")
        self.assertEqual(ids, ["3084", "4633"])

    def test_resolve_many_arena_returns_alias_ids(self) -> None:
        ids = ds_res.resolve_many(["Heartsteel", "Riftmaker"], mode="arena")
        self.assertEqual(ids, ["223084", "224633"])

    def test_resolve_many_skips_unknowns(self) -> None:
        ids = ds_res.resolve_many(
            ["Heartsteel", "Not An Item", "Riftmaker"], mode="aram",
        )
        self.assertEqual(ids, ["3084", "4633"])

    def test_resolve_many_empty_input_stable(self) -> None:
        self.assertEqual(ds_res.resolve_many([], mode="aram"), [])
        self.assertEqual(ds_res.resolve_many(None, mode="aram"), [])


class HpFlowThroughModeAwarePathTests(unittest.TestCase):
    """End-to-end: resolve in mode -> look up HP. Validates the wire-in
    ARAM coach uses (which is the whole point of s74 - non-Arena modes
    must get base-ID HP values, not alias HP)."""

    def test_aram_heartsteel_hp_is_900(self) -> None:
        iid = ds_res.name_to_id("Heartsteel", mode="aram")
        self.assertAlmostEqual(ds_res.bonus_hp_for_id(iid), 900.0, places=1)

    def test_arena_heartsteel_hp_is_700(self) -> None:
        iid = ds_res.name_to_id("Heartsteel", mode="arena")
        self.assertAlmostEqual(ds_res.bonus_hp_for_id(iid), 700.0, places=1)

    def test_sr_heartsteel_hp_is_900(self) -> None:
        iid = ds_res.name_to_id("Heartsteel", mode="sr")
        self.assertAlmostEqual(ds_res.bonus_hp_for_id(iid), 900.0, places=1)

    def test_aram_total_bonus_hp_uses_base_values(self) -> None:
        # A 3-item bruiser core in ARAM:
        # Heartsteel(900) + Riftmaker(350) + Sunfire(350) = 1600
        ids = ds_res.resolve_many(
            ["Heartsteel", "Riftmaker", "Sunfire Aegis"], mode="aram",
        )
        self.assertAlmostEqual(ds_res.total_bonus_hp(ids), 1600.0, places=1)

    def test_arena_total_bonus_hp_uses_alias_values(self) -> None:
        # Same names, mode='arena' - Arena Heartsteel is 700, not 900.
        # Riftmaker+Sunfire happen to share the alias HP value (350)
        # in the current patch but that's coincidence, not a guarantee.
        ids = ds_res.resolve_many(
            ["Heartsteel", "Riftmaker", "Sunfire Aegis"], mode="arena",
        )
        # Heart_arena(700) + Rift_arena(350) + Sun_arena(350) = 1400
        self.assertAlmostEqual(ds_res.total_bonus_hp(ids), 1400.0, places=1)


class ResolveInventoryFiltersTrinketsAndConsumablesTests(unittest.TestCase):
    """s156 regression - DS engine /rank refuses calls when
    current_item_ids fills slot_count. Live-Client serializes trinkets +
    consumables alongside shop items, so the resolver was returning a
    ``len(items) == 6`` list once the user bought 5 components +
    Farsight. resolve_inventory drops those non-shop items so the SR
    coach passes a 5-item list with 1 slot free for DS to recommend."""

    def test_drops_farsight_alteration(self) -> None:
        # Replicates the Kai'Sa-mid-game payload that surfaced the bug.
        items = ["Doran's Bow", "Infinity Edge", "Amplifying Tome",
                 "Kraken Slayer", "Recurve Bow", "Farsight Alteration"]
        ids = ds_res.resolve_inventory(items, mode="sr")
        # Farsight (3363) dropped -> 5 inventory items remain.
        self.assertNotIn("3363", ids)
        self.assertEqual(len(ids), 5)

    def test_drops_stealth_ward_default_trinket(self) -> None:
        ids = ds_res.resolve_inventory(["Stealth Ward", "Infinity Edge"], mode="sr")
        self.assertNotIn("3340", ids)
        self.assertEqual(ids, ["3031"])

    def test_drops_oracle_lens(self) -> None:
        ids = ds_res.resolve_inventory(["Oracle Lens", "Infinity Edge"], mode="sr")
        self.assertNotIn("3364", ids)
        self.assertEqual(ids, ["3031"])

    def test_drops_consumables(self) -> None:
        items = ["Health Potion", "Refillable Potion", "Control Ward",
                 "Infinity Edge"]
        ids = ds_res.resolve_inventory(items, mode="sr")
        # Only IE survives.
        self.assertEqual(ids, ["3031"])

    def test_drops_elixirs(self) -> None:
        items = ["Elixir of Iron", "Elixir of Sorcery", "Elixir of Wrath",
                 "Infinity Edge"]
        ids = ds_res.resolve_inventory(items, mode="sr")
        self.assertEqual(ids, ["3031"])

    def test_resolve_many_unaffected(self) -> None:
        # Sanity - resolve_many keeps trinkets so calibration / mirror
        # callers see the full live-client item set.
        items = ["Farsight Alteration", "Infinity Edge"]
        self.assertEqual(ds_res.resolve_many(items, mode="sr"),
                         ["3363", "3031"])

    def test_resolve_inventory_preserves_order(self) -> None:
        items = ["Health Potion", "Infinity Edge", "Stealth Ward",
                 "Kraken Slayer"]
        ids = ds_res.resolve_inventory(items, mode="sr")
        self.assertEqual(ids, ["3031", "6672"])


if __name__ == "__main__":
    unittest.main()
