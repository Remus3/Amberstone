"""item 243: non-coachable joke/anvil item deny-set in the DS rank pool.

Golden Spatula (994403) carries DDragon maps['12']=True (ARAM) with a full
all-stats block, so the DPS scorer ranked it #2 in a live ARAM Varus build.
Item 213 stripped it from the curated champion_loadouts.json, but the live
rank pool reads the DDragon maps flag directly, so it leaked back into
daemon_slayer_picks. _NON_COACHABLE_ITEM_IDS denies it (+ Veigar's Talisman
of Ascension, a stat-less meme item) unconditionally, every mode + scorer.
"""
from __future__ import annotations

import unittest

from agents import daemon_slayer
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.rank import (
    _NON_COACHABLE_ITEM_IDS,
    _SR_EXCLUDED_ITEM_IDS,
    _filter_candidates,
    _is_legal_in_mode,
    _is_purchasable,
    rank_items,
)

_GOLDEN_SPATULA = "994403"
_VEIGAR_TALISMAN = "663064"
_INFINITY_EDGE = "3031"  # a real terminal ADC item that MUST stay in the pool
_BLOODSONG = "3877"
_WORLD_ATLAS = "3865"
_ZAZZAKS = "3871"


class NonCoachableDenyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_engine_version_bumped(self) -> None:
        self.assertEqual(daemon_slayer.ENGINE_VERSION, "1.261.0")

    def test_deny_set_membership(self) -> None:
        self.assertIn(_GOLDEN_SPATULA, _NON_COACHABLE_ITEM_IDS)
        self.assertIn(_VEIGAR_TALISMAN, _NON_COACHABLE_ITEM_IDS)

    def test_golden_spatula_would_pass_without_deny(self) -> None:
        # Proves the deny is load-bearing: 994403 IS purchasable AND ARAM-legal
        # in the snapshot, so ONLY _NON_COACHABLE_ITEM_IDS keeps it out.
        rec = self.snap.items.get(_GOLDEN_SPATULA)
        self.assertIsNotNone(rec, "Golden Spatula missing from snapshot")
        self.assertTrue(_is_purchasable(rec))
        self.assertTrue(_is_legal_in_mode(rec, "ARAM"))

    def test_denied_ids_absent_from_pool_all_modes(self) -> None:
        for mode in ("ARAM", "SR", "ARENA", "BRAWL"):
            pool = {iid for iid, _ in _filter_candidates(
                self.snap, mode, set(), None, False, None)}
            self.assertNotIn(_GOLDEN_SPATULA, pool,
                             f"Golden Spatula leaked into {mode} pool")
            self.assertNotIn(_VEIGAR_TALISMAN, pool,
                             f"Veigar's Talisman leaked into {mode} pool")

    def test_real_items_still_present(self) -> None:
        pool = {iid for iid, _ in _filter_candidates(
            self.snap, "ARAM", set(), None, False, None)}
        self.assertGreater(len(pool), 40, "ARAM pool unexpectedly tiny")
        self.assertIn(_INFINITY_EDGE, pool, "real item Infinity Edge dropped")

    def test_rank_items_aram_excludes_golden_spatula(self) -> None:
        res = rank_items(self.snap, "Varus", 11, mode="ARAM", top_n=30)
        ids = {r.item_id for r in res.ranked}
        self.assertNotIn(_GOLDEN_SPATULA, ids,
                         "Golden Spatula ranked into live ARAM Varus picks")

    def test_module_file_is_ascii(self) -> None:
        from pathlib import Path
        raw = Path(__file__).read_bytes()
        bad = [(i, b) for i, b in enumerate(raw) if b > 127]
        self.assertFalse(bad, f"non-ASCII at {bad[:3]}")


class SrExcludeDenyTests(unittest.TestCase):
    """DDragon-override SR-exclude deny for support-quest upgrades (2026-07-06)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_sr_exclude_set_membership(self) -> None:
        self.assertIn(_WORLD_ATLAS, _SR_EXCLUDED_ITEM_IDS)
        self.assertIn(_ZAZZAKS, _SR_EXCLUDED_ITEM_IDS)
        self.assertIn(_BLOODSONG, _SR_EXCLUDED_ITEM_IDS)

    def test_world_atlas_is_defensive_only(self) -> None:
        # World Atlas is already defensive_only (no DPS proc), but it must still
        # be excluded from SR - the ehp/tank rankers would surface it.
        rec = self.snap.items.get(_WORLD_ATLAS)
        self.assertIsNotNone(rec, "World Atlas missing from snapshot")

    def test_bloodsong_leaks_into_sr_without_deny(self) -> None:
        # Prove the deny is load-bearing: Bloodsong IS purchasable AND maps[11]=True
        # in DDragon (upstream bug) - only _SR_EXCLUDED_ITEM_IDS keeps it out of SR.
        rec = self.snap.items.get(_BLOODSONG)
        self.assertIsNotNone(rec, "Bloodsong missing from snapshot")
        self.assertTrue(_is_purchasable(rec))
        self.assertTrue(_is_legal_in_mode(rec, "SR"),
                        "DDragon still marks Bloodsong SR-legal - deny is load-bearing")

    def test_sr_excluded_from_sr_pool(self) -> None:
        pool = {iid for iid, _ in _filter_candidates(
            self.snap, "SR", set(), None, False, None)}
        self.assertNotIn(_WORLD_ATLAS, pool, "World Atlas leaked into SR pool")
        self.assertNotIn(_ZAZZAKS, pool, "Zaz'Zak's leaked into SR pool")
        self.assertNotIn(_BLOODSONG, pool, "Bloodsong leaked into SR pool")

    def test_bloodsong_ddragon_maps_inverted(self) -> None:
        # DDragon has maps[11]=True + maps[12]=False for all three support-quest
        # items - a full upstream inversion (should be ARAM-only, not SR). Our
        # _SR_EXCLUDED_ITEM_IDS deny fixes the SR half; the ARAM half (maps[12]=False
        # dropping them from ARAM) is an upstream DDragon bug tracked separately.
        rec = self.snap.items.get(_BLOODSONG)
        self.assertIsNotNone(rec)
        self.assertTrue(_is_legal_in_mode(rec, "SR"),
                        "DDragon admits Bloodsong on SR - deny is load-bearing")
        self.assertFalse(_is_legal_in_mode(rec, "ARAM"),
                         "DDragon excludes Bloodsong from ARAM - upstream inversion (tracked)")

    def test_rank_items_sr_excludes_bloodsong(self) -> None:
        res = rank_items(self.snap, "Jinx", 9, mode="SR", top_n=30)
        ids = {r.item_id for r in res.ranked}
        self.assertNotIn(_BLOODSONG, ids,
                         "Bloodsong ranked into live SR Jinx picks")


if __name__ == "__main__":
    unittest.main()
