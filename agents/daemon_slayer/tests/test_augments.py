"""Phase 6 step 2 tests — Arena augment data layer + stat-overlay scaffold."""

import unittest

from agents.daemon_slayer.augments import (
    Augment,
    RARITY_GOLD,
    RARITY_HERO,
    RARITY_PRISMATIC,
    RARITY_SILVER,
    compute_augment_stats,
    list_augments_by_rarity,
)
from agents.daemon_slayer.data_loader import DataSnapshot


class AugmentDataLayerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.snap = DataSnapshot.load()

    def test_augments_loaded_from_snapshot(self) -> None:
        # Phase 6 ships 219 cdragon arena augments at the time of writing;
        # tolerate ±20 on either side as cdragon "latest" rotates.
        n = len(self.snap.arena_augments_by_id)
        self.assertGreaterEqual(n, 200)
        self.assertEqual(n, len(self.snap.arena_augments_by_api))

    def test_lookup_by_id_and_apiname(self) -> None:
        rec_api = self.snap.arena_augment("ApexInventor")
        rec_id = self.snap.arena_augment(int(rec_api["id"]))
        self.assertIs(rec_api, rec_id)

    def test_unknown_augment_raises(self) -> None:
        with self.assertRaises(KeyError):
            self.snap.arena_augment("NotARealAugment")

    def test_rarity_split(self) -> None:
        silver = list_augments_by_rarity(self.snap, RARITY_SILVER)
        gold = list_augments_by_rarity(self.snap, RARITY_GOLD)
        prism = list_augments_by_rarity(self.snap, RARITY_PRISMATIC)
        hero = list_augments_by_rarity(self.snap, RARITY_HERO)
        self.assertGreater(len(silver), 50)
        self.assertGreater(len(gold), 50)
        self.assertGreater(len(prism), 30)
        self.assertGreater(len(hero), 10)
        # Rarity=4 mixes Guardian-of-Heaven hero augments (apiName starts
        # with "GoH") with arena meta-mechanic augments (CraftingPrisStatAnvil,
        # CraftingSellAugment, ReplaceAugment, CraftingAugmentSlot, GainStatAnvil).
        # Both belong here per cdragon's taxonomy.
        goh = [h for h in hero if h.api_name.startswith("GoH")]
        self.assertGreater(len(goh), 5)


class AugmentStatOverlayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.snap = DataSnapshot.load()

    def test_brutalizer_grants_ad(self) -> None:
        totals = compute_augment_stats(["TheBrutalizer"], self.snap)
        # Verified against cdragon dataValues[0] for The Brutalizer.
        self.assertEqual(totals.get("ad"), 20.0)

    def test_celestial_body_grants_hp(self) -> None:
        totals = compute_augment_stats(["CelestialBody"], self.snap)
        self.assertEqual(totals.get("hp"), 1000.0)

    def test_witchful_thinking_grants_ap(self) -> None:
        totals = compute_augment_stats(["WitchfulThinking"], self.snap)
        self.assertEqual(totals.get("ap"), 60.0)

    def test_unknown_augment_silently_skipped(self) -> None:
        # Real augment exists but has no overlay registered yet — fine.
        totals = compute_augment_stats(["ApexInventor"], self.snap)
        self.assertEqual(totals, {})

    def test_multiple_augments_sum(self) -> None:
        totals = compute_augment_stats(
            ["TheBrutalizer", "CelestialBody", "WitchfulThinking"],
            self.snap,
        )
        self.assertEqual(totals["ad"], 20.0)
        self.assertEqual(totals["hp"], 1000.0)
        self.assertEqual(totals["ap"], 60.0)

    def test_accepts_int_id(self) -> None:
        # TheBrutalizer's id is stable across cdragon revs; resolve by id.
        rec = self.snap.arena_augment("TheBrutalizer")
        totals = compute_augment_stats([int(rec["id"])], self.snap)
        self.assertEqual(totals.get("ad"), 20.0)

    def test_accepts_augment_dataclass(self) -> None:
        rec = self.snap.arena_augment("WitchfulThinking")
        a = Augment.from_record(rec)
        totals = compute_augment_stats([a], self.snap)
        self.assertEqual(totals.get("ap"), 60.0)


class EngineIntegrationTests(unittest.TestCase):
    """Engine wiring: build_champion(augments=[...]) lands stats in resolved."""

    def setUp(self) -> None:
        self.snap = DataSnapshot.load()

    def test_brutalizer_adds_to_aatrox_ad(self) -> None:
        from agents.daemon_slayer.engine import build_champion
        bare = build_champion(self.snap, "Aatrox", level=11, mode="ARENA")
        with_aug = build_champion(
            self.snap, "Aatrox", level=11, mode="ARENA",
            augments=["TheBrutalizer"],
        )
        self.assertEqual(with_aug.stats["ad"] - bare.stats["ad"], 20.0)
        self.assertEqual(with_aug.augments, ("TheBrutalizer",))

    def test_celestial_body_adds_hp(self) -> None:
        from agents.daemon_slayer.engine import build_champion
        bare = build_champion(self.snap, "Garen", level=11, mode="ARENA")
        with_aug = build_champion(
            self.snap, "Garen", level=11, mode="ARENA",
            augments=["CelestialBody"],
        )
        self.assertEqual(with_aug.stats["hp"] - bare.stats["hp"], 1000.0)

    def test_multiple_augments_stack(self) -> None:
        from agents.daemon_slayer.engine import build_champion
        bare = build_champion(self.snap, "Lux", level=11, mode="ARENA")
        with_augs = build_champion(
            self.snap, "Lux", level=11, mode="ARENA",
            augments=["WitchfulThinking", "CelestialBody"],
        )
        self.assertEqual(with_augs.stats["ap"] - bare.stats["ap"], 60.0)
        self.assertEqual(with_augs.stats["hp"] - bare.stats["hp"], 1000.0)

    def test_unregistered_augment_logs_note(self) -> None:
        from agents.daemon_slayer.engine import build_champion
        r = build_champion(
            self.snap, "Aatrox", level=11, mode="ARENA",
            augments=["ApexInventor"],  # real, but no registry entry
        )
        self.assertEqual(r.augments, ("ApexInventor",))
        self.assertTrue(any("none in stat-overlay registry" in n for n in r.notes))

    def test_no_augments_means_empty_tuple(self) -> None:
        from agents.daemon_slayer.engine import build_champion
        r = build_champion(self.snap, "Aatrox", level=11)
        self.assertEqual(r.augments, ())

    def test_to_dict_surfaces_augments(self) -> None:
        from agents.daemon_slayer.engine import build_champion
        r = build_champion(
            self.snap, "Aatrox", level=11, mode="ARENA",
            augments=["TheBrutalizer", "WitchfulThinking"],
        )
        d = r.to_dict()
        self.assertEqual(d["augments"], ["TheBrutalizer", "WitchfulThinking"])


if __name__ == "__main__":
    unittest.main()
