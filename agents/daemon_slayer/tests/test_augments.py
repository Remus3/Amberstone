"""Phase 6 step 2 tests - Arena augment data layer + stat-overlay scaffold."""

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
        # Real augment exists but has no overlay registered yet - fine.
        totals = compute_augment_stats(["ApexInventor"], self.snap)
        self.assertEqual(totals, {})

    def test_its_critical_grants_crit(self) -> None:
        totals = compute_augment_stats(["ItsCritical"], self.snap)
        self.assertEqual(totals.get("crit"), 0.5)

    def test_jeweled_gauntlet_grants_crit(self) -> None:
        totals = compute_augment_stats(["JeweledGauntlet"], self.snap)
        self.assertEqual(totals.get("crit"), 0.25)

    def test_critical_healing_grants_crit(self) -> None:
        totals = compute_augment_stats(["CriticalHealing"], self.snap)
        self.assertEqual(totals.get("crit"), 0.25)

    def test_soul_siphon_grants_crit(self) -> None:
        totals = compute_augment_stats(["SoulSiphon"], self.snap)
        self.assertEqual(totals.get("crit"), 0.25)

    def test_vulnerability_grants_crit(self) -> None:
        totals = compute_augment_stats(["Vulnerability"], self.snap)
        self.assertEqual(totals.get("crit"), 0.25)

    def test_tank_it_or_leave_it_grants_crit(self) -> None:
        totals = compute_augment_stats(["TankItOrLeaveIt"], self.snap)
        self.assertEqual(totals.get("crit"), 0.25)

    def test_leg_day_grants_flat_ms(self) -> None:
        totals = compute_augment_stats(["LegDay"], self.snap)
        self.assertEqual(totals.get("ms"), 10.0)

    def test_stacked_crit_augments_sum_in_overlay(self) -> None:
        # Overlay aggregator sums; engine caps at 1.0 separately.
        totals = compute_augment_stats(
            ["ItsCritical", "JeweledGauntlet", "Vulnerability", "SoulSiphon"],
            self.snap,
        )
        self.assertAlmostEqual(totals["crit"], 0.5 + 0.25 + 0.25 + 0.25)

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

    def test_its_critical_adds_crit_to_resolved(self) -> None:
        from agents.daemon_slayer.engine import build_champion
        bare = build_champion(self.snap, "Jinx", level=11, mode="ARENA")
        with_aug = build_champion(
            self.snap, "Jinx", level=11, mode="ARENA",
            augments=["ItsCritical"],
        )
        self.assertAlmostEqual(with_aug.stats["crit"] - bare.stats["crit"], 0.5)

    def test_leg_day_adds_flat_ms_to_resolved(self) -> None:
        from agents.daemon_slayer.engine import build_champion
        bare = build_champion(self.snap, "Garen", level=11, mode="ARENA")
        with_aug = build_champion(
            self.snap, "Garen", level=11, mode="ARENA",
            augments=["LegDay"],
        )
        self.assertAlmostEqual(with_aug.stats["ms"] - bare.stats["ms"], 10.0)

    def test_stacked_crit_augments_cap_at_one(self) -> None:
        # ItsCritical(0.5) + JeweledGauntlet(0.25) + Vulnerability(0.25) +
        # SoulSiphon(0.25) = 1.25 in overlay, but engine must cap at 1.0
        # to keep DPS calc honest.
        from agents.daemon_slayer.engine import build_champion
        r = build_champion(
            self.snap, "Aatrox", level=11, mode="ARENA",
            augments=["ItsCritical", "JeweledGauntlet",
                      "Vulnerability", "SoulSiphon"],
        )
        self.assertEqual(r.stats["crit"], 1.0)


class AugmentsThroughDpsAndRankTests(unittest.TestCase):
    """Phase 6 step 6 - augments thread through compute_dps + rank_items."""

    def setUp(self) -> None:
        self.snap = DataSnapshot.load()

    def test_compute_dps_accepts_augments(self) -> None:
        from agents.daemon_slayer.dps import compute_dps
        bare = compute_dps(self.snap, "Aatrox", level=11, mode="ARENA")
        with_aug = compute_dps(
            self.snap, "Aatrox", level=11, mode="ARENA",
            augments=["TheBrutalizer"],
        )
        # +20 AD must produce strictly higher weighted DPS.
        self.assertGreater(with_aug.weighted_dps, bare.weighted_dps)

    def test_rank_items_accepts_augments(self) -> None:
        from agents.daemon_slayer.rank import rank_items
        result = rank_items(
            self.snap, "Aatrox", level=11, mode="ARENA",
            augments=["TheBrutalizer"], top_n=5,
        )
        self.assertGreater(len(result.ranked), 0)

    def test_rank_baseline_shifts_with_augments(self) -> None:
        # The baseline DPS that delta is measured against MUST include
        # augment overlay - otherwise rank deltas would double-count the
        # augment contribution into every candidate's score.
        from agents.daemon_slayer.rank import rank_items
        from agents.daemon_slayer.dps import compute_dps
        bare = compute_dps(self.snap, "Aatrox", level=11, mode="ARENA")
        aug_baseline = compute_dps(
            self.snap, "Aatrox", level=11, mode="ARENA",
            augments=["TheBrutalizer"],
        )
        # Sanity: TheBrutalizer raises baseline DPS.
        self.assertGreater(aug_baseline.weighted_dps, bare.weighted_dps)
        result = rank_items(
            self.snap, "Aatrox", level=11, mode="ARENA",
            augments=["TheBrutalizer"], top_n=3,
        )
        # First-rank delta should be measured off the augmented baseline,
        # not the bare one - i.e. delta + aug_baseline ≈ first pick's
        # absolute new_dps. (Allow small float wobble from candidate filter.)
        top = result.ranked[0]
        self.assertAlmostEqual(top.new_dps, aug_baseline.weighted_dps + top.delta_dps,
                               places=2)

    def test_unknown_augment_is_zero_overlay_in_dps(self) -> None:
        # Unknown augments are silent zero-overlay (matches engine policy).
        # compute_dps should not crash on a fictional apiName.
        from agents.daemon_slayer.dps import compute_dps
        bare = compute_dps(self.snap, "Aatrox", level=11, mode="ARENA")
        unknown = compute_dps(
            self.snap, "Aatrox", level=11, mode="ARENA",
            augments=["TotallyMadeUp"],
        )
        self.assertAlmostEqual(unknown.weighted_dps, bare.weighted_dps)


if __name__ == "__main__":
    unittest.main()
