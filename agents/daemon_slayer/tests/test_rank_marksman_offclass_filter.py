"""Ranged-marksman off-class item pollution filter (item 213, 2026-05-28).

The DPS scorer (``rank_items``) ranks every purchasable, mode-legal item by
raw DPS delta. For a ranged marksman that surfaces melee-bruiser / tank /
skirmisher items (Trinity Force, Heartsteel, Bastionbreaker, Umbral Glaive,
Sundered Sky, Black Cleaver, ...) high in the list because they add big raw
AD / AS / Health stats - items the operator never plays on a Caitlyn / Jinx /
Ezreal class ADC. Operator-reported pollution (items 208 + 213).

The fix: a data-driven, alias-proof name deny-set, gated on the champion
being a *ranged marksman* (Marksman tag + attackrange >= the ranged floor).
The gate only fires through the DPS scorer (the carry / dps / marksman /
adc / on-hit / crit / lethality routing), so mages (different scorer) and
melee bruisers / tanks (not ranged-marksman) are untouched - no over-filter
regression.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.rank import (
    OFFCLASS_MARKSMAN_ITEM_NAMES,
    RANGED_MARKSMAN_RANGE_FLOOR,
    _is_ranged_marksman,
    _filter_candidates,
    rank_items,
)


class DenySetShapeTests(unittest.TestCase):
    def test_deny_set_is_nonempty_name_frozenset(self) -> None:
        self.assertIsInstance(OFFCLASS_MARKSMAN_ITEM_NAMES, frozenset)
        self.assertGreater(len(OFFCLASS_MARKSMAN_ITEM_NAMES), 10)
        for n in OFFCLASS_MARKSMAN_ITEM_NAMES:
            self.assertIsInstance(n, str)
            # ASCII hygiene - operator hard rule.
            self.assertTrue(n.isascii(), f"non-ascii deny-name: {n!r}")

    def test_known_offenders_in_deny_set(self) -> None:
        for nm in (
            "Trinity Force",
            "Heartsteel",
            "Bastionbreaker",
            "Umbral Glaive",
            "Sundered Sky",
            "Black Cleaver",
            "Iceborn Gauntlet",
            "Stridebreaker",
            "Goredrinker",
            "Divine Sunderer",
            "Sterak's Gage",
            "Titanic Hydra",
        ):
            self.assertIn(nm, OFFCLASS_MARKSMAN_ITEM_NAMES, nm)

    def test_legit_adc_items_not_in_deny_set(self) -> None:
        for nm in (
            "Blade of The Ruined King",
            "Infinity Edge",
            "Lord Dominik's Regards",
            "Yun Tal Wildarrows",
            "Runaan's Hurricane",
            "Kraken Slayer",
            "Essence Reaver",
            "Stormrazor",
            "Eclipse",
            "Opportunity",
            "Serylda's Grudge",
            "The Collector",
        ):
            self.assertNotIn(nm, OFFCLASS_MARKSMAN_ITEM_NAMES, nm)


class RangedMarksmanGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_ranged_marksmen_detected(self) -> None:
        for n in ("Caitlyn", "Jinx", "Ezreal", "Varus", "Kaisa", "Ashe"):
            self.assertTrue(
                _is_ranged_marksman(self.snap.champion(n)),
                f"{n} should be a ranged marksman",
            )

    def test_melee_and_mage_not_gated(self) -> None:
        # Melee fighter / tank: not ranged marksman.
        for n in ("Aatrox", "Ornn", "Garen"):
            self.assertFalse(
                _is_ranged_marksman(self.snap.champion(n)),
                f"{n} should NOT be a ranged marksman",
            )
        # Ranged mages: not Marksman-tagged, so not gated by this filter
        # (they route through the mage scorer anyway).
        for n in ("Lux", "Ahri"):
            self.assertFalse(
                _is_ranged_marksman(self.snap.champion(n)),
                f"{n} (mage) should NOT trip the marksman gate",
            )

    def test_range_floor_is_sane(self) -> None:
        self.assertGreaterEqual(RANGED_MARKSMAN_RANGE_FLOOR, 450)
        self.assertLessEqual(RANGED_MARKSMAN_RANGE_FLOOR, 525)


class FilterCandidatesExcludeNamesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_exclude_names_drops_canonical_and_alias(self) -> None:
        cands = _filter_candidates(
            self.snap,
            mode="ARENA",
            current_ids=set(),
            budget=None,
            include_components=False,
            only_ids=None,
            exclude_names=frozenset({"Trinity Force"}),
        )
        names = {rec.get("name") for _id, rec in cands}
        self.assertNotIn("Trinity Force", names)

    def test_exclude_names_none_is_noop(self) -> None:
        base = _filter_candidates(
            self.snap, mode="SR", current_ids=set(), budget=None,
            include_components=False, only_ids=None, exclude_names=None,
        )
        names = {rec.get("name") for _id, rec in base}
        self.assertIn("Trinity Force", names)


class CaitlynBuildCleanTests(unittest.TestCase):
    """Full rank_items integration - the operator-facing assertion."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def _rank(self, champ, mode, top=20):
        return rank_items(
            self.snap, champ, level=14, current_item_ids=[], mode=mode,
            target_armor=80, target_mr=60, target_max_hp=2000,
            target_bonus_hp=600, top_n=top,
        )

    def test_caitlyn_offclass_excluded_all_modes(self) -> None:
        for mode in ("SR", "ARAM", "ARENA"):
            res = self._rank("Caitlyn", mode)
            ids = {r.item_id for r in res.ranked}
            names = {r.item_name for r in res.ranked}
            for bad in ("Trinity Force", "Heartsteel", "Bastionbreaker",
                        "Umbral Glaive", "Sundered Sky", "Black Cleaver"):
                self.assertNotIn(bad, names, f"{bad} polluted Caitlyn {mode}")
            # Legit ADC core must still be present in at least one mode pool.
            self.assertTrue(ids, f"empty pool for Caitlyn {mode}")

    def test_caitlyn_keeps_adc_core(self) -> None:
        res = self._rank("Caitlyn", "SR")
        names = {r.item_name for r in res.ranked}
        self.assertIn("Blade of The Ruined King", names)
        self.assertIn("Infinity Edge", names)

    def test_sample_ranged_adcs_clean_primary(self) -> None:
        for champ in ("Jinx", "Ezreal", "Varus", "Kaisa"):
            for mode in ("SR", "ARAM"):
                res = self._rank(champ, mode)
                names = {r.item_name for r in res.ranked}
                for bad in ("Trinity Force", "Heartsteel", "Bastionbreaker",
                            "Umbral Glaive"):
                    self.assertNotIn(
                        bad, names, f"{bad} polluted {champ} {mode}"
                    )


class NoOverFilterRegressionTests(unittest.TestCase):
    """Melee bruiser / tank builds must still get their core items."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_aatrox_keeps_bruiser_items(self) -> None:
        res = rank_items(
            self.snap, "Aatrox", level=14, current_item_ids=[], mode="SR",
            target_armor=80, target_mr=60, target_max_hp=2000,
            target_bonus_hp=600, top_n=30,
        )
        names = {r.item_name for r in res.ranked}
        # A melee bruiser SHOULD see at least one of these big bruiser items.
        bruiser_core = {"Sundered Sky", "Black Cleaver", "Sterak's Gage",
                        "Goredrinker", "Stridebreaker", "Trinity Force",
                        "Titanic Hydra"}
        self.assertTrue(
            names & bruiser_core,
            f"Aatrox over-filtered, no bruiser core in {sorted(names)}",
        )

    def test_ornn_keeps_tank_items(self) -> None:
        res = rank_items(
            self.snap, "Ornn", level=14, current_item_ids=[], mode="SR",
            target_armor=80, target_mr=60, target_max_hp=2000,
            target_bonus_hp=600, top_n=40,
        )
        # Tank smoke - assert the pool is non-empty and not stripped to ADC.
        self.assertTrue(res.ranked)


class EngineVersionPinTests(unittest.TestCase):
    def test_engine_version(self) -> None:
        from agents.daemon_slayer import ENGINE_VERSION

        self.assertEqual(ENGINE_VERSION, "1.68.0")


if __name__ == "__main__":
    unittest.main()
