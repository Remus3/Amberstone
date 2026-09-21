"""ARAM must not recommend augment-granted 6000g mega-items (16.18.1 refresh).

MEASURED 2026-09-20: DDragon 16.17.1 added ``226668`` Ultra Hydra (6000g, no
recipe, ``maps`` = {"12": true} only). The wiki item page states it is
"Available on ARAM: Mayhem" and "Obtained from the Ultra Hydra augment" - it
is an augment REWARD, not a shop purchase. Unexcluded, the 16.18.1 regen put
it first in 195 of 519 Lane B ARAM builds. ``223069`` Void Immolation is the
same class (its wiki page: obtained from the "Quest: Icathia's Fall" Mayhem
augment) and has been excluded since 136e74f5f.

The structural guard below makes the NEXT such item fail loudly instead of
silently taking over the ARAM tables: every purchasable map-12 item that costs
6000g or more and has no recipe must be either excluded or explicitly
reviewed here.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.rank import _ARAM_EXCLUDED_ITEM_IDS, _filter_candidates

_REPO = Path(__file__).resolve().parents[3]
_DS = _REPO / "data" / "daemon_slayer"

# Reviewed, and kept out of the ARAM pool by a DIFFERENT, structural gate:
# 228002 Wooglet's Witchcap is an Ornn masterwork (rank._is_ornn_masterwork,
# the <ornnBonus> tag), so it needs no entry in _ARAM_EXCLUDED_ITEM_IDS.
# DDragon carries no structured "augment reward" field (searched 2026-09-20:
# no Quest/augment text, requiredChampion or specialRecipe on 223069/226668),
# so price + no recipe + map 12 is the best available tripwire.
_REVIEWED_KEEP: frozenset[str] = frozenset({"228002"})
_MEGA_GOLD = 6000


def _mega_map12(items: dict) -> set[str]:
    out = set()
    for iid, rec in items.items():
        gold = rec.get("gold") or {}
        if (
            (rec.get("maps") or {}).get("12")
            and gold.get("purchasable")
            and int(gold.get("total") or 0) >= _MEGA_GOLD
            and not rec.get("from")
        ):
            out.add(iid)
    return out


class AramMegaItemExclusion(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_ultra_hydra_is_excluded_from_the_aram_pool(self) -> None:
        self.assertIn("226668", _ARAM_EXCLUDED_ITEM_IDS)
        pool = {i for i, _ in _filter_candidates(
            self.snap, "ARAM", set(), None, False, None)}
        self.assertNotIn("226668", pool)
        self.assertNotIn("223069", pool)
        for iid in _REVIEWED_KEEP:
            self.assertNotIn(iid, pool, f"{iid} reviewed as gated elsewhere")

    def test_every_map12_mega_item_is_excluded_or_reviewed(self) -> None:
        mega = _mega_map12(self.snap.items)
        self.assertTrue(mega, "guard is vacuous: no map-12 mega item found")
        unreviewed = sorted(mega - _ARAM_EXCLUDED_ITEM_IDS - _REVIEWED_KEEP)
        self.assertEqual(
            unreviewed, [],
            f"new map-12 {_MEGA_GOLD}g+ recipe-less item(s) {unreviewed}: check "
            "whether they are augment rewards (exclude) or real purchases "
            "(add to _REVIEWED_KEEP with evidence)",
        )

    def test_committed_aram_tables_carry_no_excluded_item(self) -> None:
        patch = (_DS / "current.txt").read_text(encoding="utf-8").strip()
        paths = [
            _DS / patch / "build_orders_aram.json",
            _DS / "build_orders" / patch / "build_orders_aram.json",
            _DS / "build_orders" / patch / "build_order_variants_aram.json",
        ]
        for path in paths:
            text = path.read_text(encoding="utf-8")
            json.loads(text)  # the file must parse; a pointer/stub would not
            for iid in sorted(_ARAM_EXCLUDED_ITEM_IDS):
                self.assertNotIn(f'"{iid}"', text, f"{iid} in {path.name}")

    def test_no_single_item_opens_most_aram_builds(self) -> None:
        # Backstop, deliberately loose: measured top first-slot share across
        # the 16.15.1 and 16.18.1 ARAM tables is 0.27-0.39 (3153 BotRK), so a
        # share above one half means one item has taken over the table.
        patch = (_DS / "current.txt").read_text(encoding="utf-8").strip()
        data = json.loads((_DS / patch / "build_orders_aram.json").read_text(
            encoding="utf-8"))
        firsts: dict[str, int] = {}
        n = 0
        for cells in data["build_orders"].values():
            for seq in cells.values():
                if seq:
                    n += 1
                    firsts[str(seq[0])] = firsts.get(str(seq[0]), 0) + 1
        self.assertGreater(n, 100)
        top, count = max(firsts.items(), key=lambda kv: kv[1])
        self.assertLessEqual(count / n, 0.5, f"{top} opens {count}/{n} builds")


if __name__ == "__main__":
    unittest.main()
