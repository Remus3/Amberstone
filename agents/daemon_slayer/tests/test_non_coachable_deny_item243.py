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
    _filter_candidates,
    _is_legal_in_mode,
    _is_purchasable,
    rank_items,
)

_GOLDEN_SPATULA = "994403"
_VEIGAR_TALISMAN = "663064"
_INFINITY_EDGE = "3031"  # a real terminal ADC item that MUST stay in the pool


class NonCoachableDenyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_engine_version_bumped(self) -> None:
        self.assertEqual(daemon_slayer.ENGINE_VERSION, "1.118.0")

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


if __name__ == "__main__":
    unittest.main()
