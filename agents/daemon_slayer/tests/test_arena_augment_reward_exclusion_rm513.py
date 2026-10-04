"""RM-513: Arena must not recommend augment-granted 6000g mega-items.

MEASURED 2026-10-03: ``223069`` Void Immolation opened 217 of 519 (42 percent)
Arena builds in ``data/daemon_slayer/16.18.1/build_orders_arena.json``. DDragon
marks it ``gold.purchasable`` with ``maps`` {"12": true, "30": true}, but the
wiki item page (fetched 2026-10-03) reads "Available on Arena and ARAM:
Mayhem" and "Obtained from the Quest: Icathia's Fall augment" - an augment
REWARD in BOTH modes, not a shop purchase. ARAM already excluded it
(``rank._ARAM_EXCLUDED_ITEM_IDS``, 136e74f5f); Arena did not, and
``test_cost_aware_top_f2`` even pinned it as Arena-legal on the
maps-flag premise this row refutes.

The structural guard makes the NEXT map-30 mega item fail loudly.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.rank import _ARENA_EXCLUDED_ITEM_IDS, _filter_candidates

_REPO = Path(__file__).resolve().parents[3]
_DS = _REPO / "data" / "daemon_slayer"

# Reviewed, kept out of the pool by a DIFFERENT structural gate:
# 228002 Wooglet's Witchcap is an Ornn masterwork (rank._is_ornn_masterwork).
_REVIEWED_KEEP: frozenset[str] = frozenset({"228002"})
_MEGA_GOLD = 6000


def _mega_map30(items: dict) -> set[str]:
    out = set()
    for iid, rec in items.items():
        gold = rec.get("gold") or {}
        if (
            (rec.get("maps") or {}).get("30")
            and gold.get("purchasable")
            and int(gold.get("total") or 0) >= _MEGA_GOLD
            and not rec.get("from")
        ):
            out.add(iid)
    return out


class ArenaAugmentRewardExclusion(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_void_immolation_is_excluded_from_the_arena_pool(self) -> None:
        self.assertIn("223069", _ARENA_EXCLUDED_ITEM_IDS)
        for mode in ("arena", "ARENA"):
            pool = {i for i, _ in _filter_candidates(
                self.snap, mode, set(), None, False, None)}
            self.assertNotIn("223069", pool, mode)
            for iid in _REVIEWED_KEEP:
                self.assertNotIn(iid, pool, f"{iid} reviewed as gated elsewhere")

    def test_sr_pool_unaffected_positive_control(self) -> None:
        # The Arena gate must not leak into other modes' pools: an ordinary
        # Arena item stays admitted in Arena.
        pool = {i for i, _ in _filter_candidates(
            self.snap, "arena", set(), None, False, None)}
        self.assertIn("223031", pool)  # Infinity Edge Arena mirror

    def test_every_map30_mega_item_is_excluded_or_reviewed(self) -> None:
        mega = _mega_map30(self.snap.items)
        self.assertTrue(mega, "guard is vacuous: no map-30 mega item found")
        unreviewed = sorted(mega - _ARENA_EXCLUDED_ITEM_IDS - _REVIEWED_KEEP)
        self.assertEqual(
            unreviewed, [],
            f"new map-30 {_MEGA_GOLD}g+ recipe-less item(s) {unreviewed}: check "
            "whether they are augment rewards (exclude) or real purchases "
            "(add to _REVIEWED_KEEP with evidence)",
        )

    def test_committed_arena_tables_carry_no_excluded_item(self) -> None:
        patch = (_DS / "current.txt").read_text(encoding="utf-8").strip()
        paths = [
            p for p in (
                _DS / patch / "build_orders_arena.json",
                _DS / "build_orders" / patch / "build_orders_arena.json",
                _DS / "build_orders" / patch / "build_order_variants_arena.json",
            ) if p.exists()
        ]
        self.assertTrue(paths)
        for path in paths:
            text = path.read_bytes().decode("utf-8")
            json.loads(text)
            for iid in sorted(_ARENA_EXCLUDED_ITEM_IDS):
                self.assertNotIn(f'"{iid}"', text, f"{iid} in {path}")


if __name__ == "__main__":
    unittest.main()
