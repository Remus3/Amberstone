"""Ranged-only item purchasability gate (2026-07-02, patch 16.13.1).

Live practice-SR drain bug: ``POST /rank {"champion":"Irelia"}`` surfaced
Runaan's Hurricane (3085) - a RANGED-ONLY item the in-game shop blocks for
melee champions - in Irelia's recommended build (it ranked #1 in the DPS
scorer, delta ~134). DS was recommending an item the champ literally cannot
buy.

Root cause: the candidate pool (``rank._filter_candidates``, shared by every
ranker lane) had NO gate for ranged-only items. This is a PURCHASABILITY gate
(the game shop rule), DISTINCT from:
  * ``_is_ranged_marksman`` (rank.py) - a MARKSMAN off-class deny (Trinity /
    Heartsteel stripped from a crit ADC), a different axis.
  * ``dps.apply_melee_aa_gate`` (default-OFF) - zeroes only the Runaan BOLT
    DPS on melee, never excludes the item from the pool.

Authoritative ranged-only set for 16.13.1 (verified vs wiki.leagueoflegends.com
2026-07-02): Runaan's Hurricane ONLY. The bug report also named Rapid
Firecannon (3094) and Statikk Shiv (3087), but the wiki confirms NEITHER is
purchase-restricted ("Limited to 1" only) - melee CAN buy both, so they are
NOT in the deny set (a narrow-but-correct set, not an over-broad one). The
DDragon item.json carries NO structured ranged-only flag (not in tags / maps /
effect / requiredChampion), so the set is an explicit id set anchored on wiki
ground truth - a documented data-gap.

Melee/ranged split reuses the engine's own predicate threshold (attackrange
<= 250 = melee, matching ehp._is_ranged which uses > 250 for ranged). This is
deliberately the 250 threshold, NOT the 500 RANGED_MARKSMAN_RANGE_FLOOR:
Graves (attackrange 425) and Kindred (500) are ranged marksmen that CAN buy
Runaan's in-game, so they must NOT be gated.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.rank import (
    RANGED_ONLY_ITEM_IDS,
    _champion_is_melee,
    _filter_candidates,
    rank_items,
)

# Runaan's Hurricane canonical id + Arena-mirror alias.
_RUNAAN = "3085"
_RUNAAN_ARENA = "223085"
# Confirmed NOT restricted - must stay buyable for melee (guards over-filter).
_RFC = "3094"       # Rapid Firecannon
_STATIKK = "3087"   # Statikk Shiv

_MELEE = ("Irelia", "Jax", "Camille")
_RANGED_MARKSMEN = ("Caitlyn", "Jinx")


class DenySetShapeTests(unittest.TestCase):
    def test_ranged_only_set_is_frozenset_of_ascii_str(self) -> None:
        self.assertIsInstance(RANGED_ONLY_ITEM_IDS, frozenset)
        self.assertTrue(RANGED_ONLY_ITEM_IDS)
        for iid in RANGED_ONLY_ITEM_IDS:
            self.assertIsInstance(iid, str)
            self.assertTrue(iid.isascii(), f"non-ascii id: {iid!r}")

    def test_runaan_and_alias_in_set(self) -> None:
        self.assertIn(_RUNAAN, RANGED_ONLY_ITEM_IDS)
        self.assertIn(_RUNAAN_ARENA, RANGED_ONLY_ITEM_IDS)

    def test_non_restricted_items_absent_from_set(self) -> None:
        # RFC + Statikk are NOT purchase-restricted (wiki 16.13.1); they must
        # not be in the deny set or melee would wrongly lose them.
        self.assertNotIn(_RFC, RANGED_ONLY_ITEM_IDS)
        self.assertNotIn(_STATIKK, RANGED_ONLY_ITEM_IDS)


class MeleePredicateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_melee_champs_classified_melee(self) -> None:
        for champ in _MELEE + ("Yasuo", "Yone"):
            rec = self.snap.champions.get(champ)
            self.assertIsNotNone(rec, champ)
            self.assertTrue(_champion_is_melee(rec), f"{champ} should be melee")

    def test_ranged_champs_classified_ranged(self) -> None:
        # Includes Graves (425) / Kindred (500) - ranged marksmen below the
        # 500 marksman floor that MUST still be treated as ranged (can buy Runaan).
        for champ in ("Caitlyn", "Jinx", "Graves", "Kindred"):
            rec = self.snap.champions.get(champ)
            self.assertIsNotNone(rec, champ)
            self.assertFalse(_champion_is_melee(rec), f"{champ} should be ranged")


class RunaanPurchasabilityGateTests(unittest.TestCase):
    """The reproduction + fix oracle. RED before the fix (Runaan present for
    Irelia); GREEN after (Runaan gated for melee, kept for ranged)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_runaan_is_ranged_only_ground_truth(self) -> None:
        # Sanity: the item exists and is SR/ARAM-legal (so the exclusion is
        # a real gate, not a vacuous mode-illegal pass-through).
        rec = self.snap.items.get(_RUNAAN)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["name"], "Runaan's Hurricane")
        self.assertTrue(rec["maps"]["11"])  # SR legal
        self.assertTrue(rec["maps"]["12"])  # ARAM legal

    def test_melee_rank_pool_excludes_runaan(self) -> None:
        for champ in _MELEE:
            for mode in ("SR", "ARAM"):
                res = rank_items(self.snap, champ, 11, mode=mode, top_n=40)
                ids = {r.item_id for r in res.ranked}
                self.assertNotIn(
                    _RUNAAN, ids,
                    f"Runaan's (ranged-only) surfaced for melee {champ} in {mode}",
                )

    def test_ranged_marksman_rank_pool_keeps_runaan(self) -> None:
        for champ in _RANGED_MARKSMEN:
            res = rank_items(self.snap, champ, 11, mode="SR", top_n=60)
            ids = {r.item_id for r in res.ranked}
            self.assertIn(
                _RUNAAN, ids,
                f"Runaan's wrongly dropped for ranged marksman {champ} (SR)",
            )

    def test_filter_candidates_melee_flag_drops_runaan(self) -> None:
        # Direct pool-level assertion at the chokepoint.
        melee_pool = {
            iid for iid, _ in _filter_candidates(
                self.snap, "SR", set(), None, False, None,
                champion_is_melee=True,
            )
        }
        ranged_pool = {
            iid for iid, _ in _filter_candidates(
                self.snap, "SR", set(), None, False, None,
                champion_is_melee=False,
            )
        }
        self.assertNotIn(_RUNAAN, melee_pool)
        self.assertIn(_RUNAAN, ranged_pool)

    def test_non_restricted_crit_items_kept_for_melee(self) -> None:
        # Guard against over-filter: RFC + Statikk are buyable by melee, so a
        # melee pool must still contain them (they are mode-legal on SR).
        melee_pool = {
            iid for iid, _ in _filter_candidates(
                self.snap, "SR", set(), None, False, None,
                champion_is_melee=True,
            )
        }
        self.assertIn(_RFC, melee_pool, "Rapid Firecannon wrongly gated for melee")
        self.assertIn(_STATIKK, melee_pool, "Statikk Shiv wrongly gated for melee")


class SiblingLaneGateTests(unittest.TestCase):
    """The same ``_filter_candidates`` chokepoint feeds every ranker lane, so
    the gate must fire through ALL of them, not just the DPS scorer that the
    bug was reported on. Melee -> Runaan gated; ranged marksman -> kept."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    @staticmethod
    def _ids(result) -> set:
        return {r.item_id for r in result.ranked}

    def test_hybrid_bruiser_lane(self) -> None:
        from agents.daemon_slayer.hybrid import rank_items_by_hybrid

        self.assertNotIn(
            _RUNAAN,
            self._ids(rank_items_by_hybrid(self.snap, "Irelia", 11, mode="SR", top_n=50)),
            "Runaan leaked into /rank-bruiser for melee Irelia",
        )
        self.assertIn(
            _RUNAAN,
            self._ids(rank_items_by_hybrid(self.snap, "Caitlyn", 11, mode="SR", top_n=60)),
            "Runaan wrongly dropped from /rank-bruiser for ranged Caitlyn",
        )

    def test_burst_assassin_lane(self) -> None:
        from agents.daemon_slayer.burst import rank_items_by_burst

        self.assertNotIn(
            _RUNAAN,
            self._ids(rank_items_by_burst(self.snap, "Camille", 11, mode="SR", top_n=50)),
            "Runaan leaked into /burst for melee Camille",
        )
        self.assertIn(
            _RUNAAN,
            self._ids(rank_items_by_burst(self.snap, "Caitlyn", 11, mode="SR", top_n=60)),
            "Runaan wrongly dropped from /burst for ranged Caitlyn",
        )

    def test_ehp_tank_lane(self) -> None:
        from agents.daemon_slayer.ehp import rank_items_by_ehp

        # Direct pool-level assertion via _filter_candidates is the robust check
        # (an EHP scorer may not RANK Runaan high, but it must not be in the
        # candidate pool for a melee tank).
        self.assertNotIn(
            _RUNAAN,
            self._ids(rank_items_by_ehp(self.snap, "Irelia", 11, mode="SR", top_n=80)),
            "Runaan leaked into /rank-tank pool for melee Irelia",
        )

    def test_mage_ability_lane(self) -> None:
        from agents.daemon_slayer._rank_mage import rank_items_by_ability_dps

        self.assertNotIn(
            _RUNAAN,
            self._ids(rank_items_by_ability_dps(self.snap, "Diana", 11, mode="SR", top_n=80)),
            "Runaan leaked into /rank-mage for melee ability caster Diana",
        )


class ModuleAsciiTests(unittest.TestCase):
    def test_module_file_is_ascii(self) -> None:
        from pathlib import Path

        raw = Path(__file__).read_bytes()
        bad = [(i, b) for i, b in enumerate(raw) if b > 127]
        self.assertFalse(bad, f"non-ascii bytes at {bad[:5]}")


if __name__ == "__main__":
    unittest.main()
