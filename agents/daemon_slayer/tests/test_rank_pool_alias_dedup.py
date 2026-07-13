"""DDragon alias-id dedup in the candidate pool (operator 2026-07-12).

DDragon 16.9.1+ ships duplicate ids for many items: the real 4-digit id AND a
longer alias variant (the "32xxxx" / "66xxxx" mirror namespaces). The alias
carries ``maps["11"]=True`` so BOTH survive the SR map-filter, and the pool
double-counts the item. Live-observed: a Jhin SR reco emitted "The Collector"
via 6676 AND 667666; the greedy build can then pick the same item twice.

Fix: ``_filter_candidates`` keeps only the CANONICAL (shortest) id per item
name. A strictly-longer same-name id is a DDragon alias and is dropped.
Same-length collisions (Kalista's Black Spear 3599/3600, the jungle-pet tiers
1101-1107 that share a display name) are NOT aliases and are left untouched, so
the pass is byte-identical off SR (ARAM/Arena/Brawl have only the same-length
Kalista collision - the alias namespaces are map-filtered to a single survivor
there).
"""

import collections
import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.rank import _filter_candidates, rank_items


def _pool_by_name(snap, mode):
    cands = _filter_candidates(
        snap, mode=mode, current_ids=set(), budget=None,
        include_components=False, only_ids=None,
    )
    byname = collections.defaultdict(list)
    for item_id, rec in cands:
        byname[rec.get("name")].append(item_id)
    return byname


class PoolAliasDedupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_sr_pool_has_no_strictly_longer_alias(self) -> None:
        """No item name may survive the SR pool under two ids of DIFFERENT
        length - a strictly-longer same-name id is a DDragon alias leak."""
        byname = _pool_by_name(self.snap, "SR")
        offenders = {
            name: sorted(ids, key=lambda x: (len(x), x))
            for name, ids in byname.items()
            if name is not None and len({len(i) for i in ids}) > 1
        }
        self.assertEqual(
            offenders, {},
            f"DDragon alias duplicates leaked into the SR pool: {offenders}",
        )

    def test_collector_single_canonical_id_on_sr(self) -> None:
        byname = _pool_by_name(self.snap, "SR")
        collector_ids = byname.get("The Collector", [])
        self.assertEqual(
            collector_ids, ["6676"],
            f"The Collector must appear once as canonical 6676, got {collector_ids}",
        )

    def test_jhin_sr_ranked_output_has_no_duplicate_names(self) -> None:
        """The user-visible symptom: the carry (ds.dps) ranked output for Jhin
        must not list the same item name twice (Collector / Hextech Gunblade /
        Manamune all double-appeared via their aliases)."""
        res = rank_items(
            self.snap, "Jhin", level=18, mode="SR",
            target_armor=80.0, top_n=40,
        )
        names = [r.item_name for r in res.ranked]
        dups = [n for n, c in collections.Counter(names).items() if c > 1]
        self.assertEqual(dups, [], f"duplicate item names in Jhin SR reco: {dups}")

    def test_aram_pool_unchanged_control(self) -> None:
        """Control: ARAM has no strictly-longer alias collision (the alias
        namespaces map-filter to a single survivor), so the pool is already
        clean and stays byte-identical."""
        byname = _pool_by_name(self.snap, "ARAM")
        offenders = {
            name: sorted(ids, key=lambda x: (len(x), x))
            for name, ids in byname.items()
            if name is not None and len({len(i) for i in ids}) > 1
        }
        self.assertEqual(offenders, {}, f"unexpected ARAM alias leak: {offenders}")


if __name__ == "__main__":
    unittest.main()
