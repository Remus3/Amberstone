"""S1-1: an OWNED item must not be re-recommended under a same-name alias id.

The DDragon alias-id dedup in ``rank._filter_candidates`` (operator 2026-07-12)
keeps the shortest id per item NAME, but it only dedups among CANDIDATES. An
owned id is dropped earlier by the raw-id ``current_ids`` skip, so its same-name
alias had no canonical sibling left to lose to and survived into the pool.

Measured repros at 16.18.1 (swarm validator):
  * /rank-bruiser Darius L11 ARAM owning 3084 -> 223084 Heartsteel #4
  * /rank-tank Malphite ARAM owning 3084      -> 223084 Heartsteel #17
  * /rank Tristana SR owning 6676             -> 667666 The Collector #14
  * /rank-assassin Zed SR owning 6676         -> 667666 The Collector #20
  * /rank-mage Lux SR owning 3146             -> 663146 Hextech Gunblade #14

DDragon 16.18.1 marks BOTH 3084 and 223084 ``maps["12"]=True`` (ARAM-legal), so
the ARAM pool carries the pair and the alias namespaces do NOT map-filter to a
single survivor there - the old comment claiming so was wrong.

Every scorer goes through ``_filter_candidates``, so the fix lives there. The
beam path builds its pool with ``current_ids=set()`` and excludes per beam by raw
id, so it gets its own per-beam name guard.
"""

import collections
import unittest

from agents.daemon_slayer.beam import beam_search_build
from agents.daemon_slayer.burst import rank_items_by_burst
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import rank_items_by_ehp
from agents.daemon_slayer.hybrid import rank_items_by_hybrid
from agents.daemon_slayer.rank import _filter_candidates, rank_items
from agents.daemon_slayer._rank_mage import rank_items_by_ability_dps

_HEARTSTEEL, _HEARTSTEEL_ALIAS = "3084", "223084"
_COLLECTOR, _COLLECTOR_ALIAS = "6676", "667666"
_GUNBLADE, _GUNBLADE_ALIAS = "3146", "663146"


def _names(snap, ids):
    return [str((snap.items.get(i) or {}).get("name")) for i in ids]


class DataPremiseTests(unittest.TestCase):
    """Pin the DDragon facts the repros depend on, so a data refresh that
    removes an alias makes the failure legible instead of vacuous."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_alias_pairs_share_a_name(self) -> None:
        for a, b in (
            (_HEARTSTEEL, _HEARTSTEEL_ALIAS),
            (_COLLECTOR, _COLLECTOR_ALIAS),
            (_GUNBLADE, _GUNBLADE_ALIAS),
        ):
            self.assertIn(a, self.snap.items)
            self.assertIn(b, self.snap.items)
            self.assertEqual(
                self.snap.items[a]["name"], self.snap.items[b]["name"], (a, b)
            )

    def test_heartsteel_and_alias_both_aram_legal(self) -> None:
        for iid in (_HEARTSTEEL, _HEARTSTEEL_ALIAS):
            self.assertTrue(self.snap.items[iid]["maps"].get("12"), iid)


class FilterCandidatesOwnedNameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def _pool(self, mode, owned, comps=False):
        return {
            iid for iid, _ in _filter_candidates(
                self.snap, mode, set(owned), None, comps, None,
            )
        }

    def test_aram_owning_heartsteel_drops_alias(self) -> None:
        self.assertNotIn(_HEARTSTEEL_ALIAS, self._pool("ARAM", {_HEARTSTEEL}))

    def test_aram_owning_alias_drops_canonical(self) -> None:
        self.assertNotIn(_HEARTSTEEL, self._pool("ARAM", {_HEARTSTEEL_ALIAS}))

    def test_sr_owning_collector_drops_alias(self) -> None:
        self.assertNotIn(_COLLECTOR_ALIAS, self._pool("SR", {_COLLECTOR}))

    def test_sr_owning_gunblade_drops_alias(self) -> None:
        self.assertNotIn(_GUNBLADE_ALIAS, self._pool("SR", {_GUNBLADE}))

    def test_unowned_pool_unchanged(self) -> None:
        """Control: owning an UNRELATED item removes only that item - the
        name guard must not widen beyond same-name ids."""
        base = self._pool("SR", set())
        owned = self._pool("SR", {_COLLECTOR})
        self.assertEqual(base - owned, {_COLLECTOR})

    def test_no_owned_name_survives_any_mode(self) -> None:
        """Sweep: for every pool item in every mode (terminal and with
        components), owning ANY id that carries its name leaves no candidate
        with that name in the pool."""
        ids_by_name = collections.defaultdict(set)
        for iid, rec in self.snap.items.items():
            ids_by_name[rec.get("name")].add(iid)
        checked = 0
        for comps in (False, True):
            for mode in ("SR", "ARAM", "ARENA"):
                base = _filter_candidates(self.snap, mode, set(), None, comps, None)
                self.assertTrue(base, f"empty {mode} pool makes the sweep vacuous")
                leaks = []
                for name in {rec.get("name") for _, rec in base}:
                    if name is None:
                        continue
                    for owned in ids_by_name[name]:
                        pool = _filter_candidates(
                            self.snap, mode, {owned}, None, comps, None,
                        )
                        checked += 1
                        leaks += [
                            (owned, j) for j, r in pool if r.get("name") == name
                        ]
                self.assertEqual(
                    leaks, [], f"{mode} comps={comps}: owned-name leaks {leaks[:20]}"
                )
        self.assertGreater(checked, 500)


class RouteReproTests(unittest.TestCase):
    """The exact swarm-validator repros, one per scorer entry point."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def _assert_no_owned_name(self, res, owned_id) -> None:
        owned_name = self.snap.items[owned_id]["name"]
        hits = [
            (r.item_id, i + 1)
            for i, r in enumerate(res.ranked)
            if self.snap.items.get(r.item_id, {}).get("name") == owned_name
        ]
        self.assertEqual(hits, [], f"{owned_name} re-recommended after owning {owned_id}")
        self.assertGreater(len(res.ranked), 5, "ranked list too short to be meaningful")

    def test_bruiser_darius_aram_heartsteel(self) -> None:
        res = rank_items_by_hybrid(
            self.snap, "Darius", 11, current_item_ids=[_HEARTSTEEL],
            mode="ARAM", top_n=60,
        )
        self._assert_no_owned_name(res, _HEARTSTEEL)

    def test_tank_malphite_aram_heartsteel(self) -> None:
        res = rank_items_by_ehp(
            self.snap, "Malphite", 11, current_item_ids=[_HEARTSTEEL],
            mode="ARAM", top_n=60,
        )
        self._assert_no_owned_name(res, _HEARTSTEEL)

    def test_carry_tristana_sr_collector(self) -> None:
        res = rank_items(
            self.snap, "Tristana", 11, current_item_ids=[_COLLECTOR],
            mode="SR", top_n=60,
        )
        self._assert_no_owned_name(res, _COLLECTOR)

    def test_assassin_zed_sr_collector(self) -> None:
        res = rank_items_by_burst(
            self.snap, "Zed", 11, current_item_ids=[_COLLECTOR],
            mode="SR", top_n=60,
        )
        self._assert_no_owned_name(res, _COLLECTOR)

    def test_mage_lux_sr_gunblade(self) -> None:
        res = rank_items_by_ability_dps(
            self.snap, "Lux", 11, current_item_ids=[_GUNBLADE],
            mode="SR", top_n=60,
        )
        self._assert_no_owned_name(res, _GUNBLADE)


class BeamOwnedAliasTests(unittest.TestCase):
    """beam_search_build pools with current_ids=set() and skips per beam by
    raw id, so a SEEDED alias let the canonical twin join the same build."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_seeded_alias_never_paired_with_canonical(self) -> None:
        res = beam_search_build(
            self.snap, "Tristana", 18, current_item_ids=[_COLLECTOR_ALIAS],
            mode="SR", slot_count=2, beam_width=10, top_n=10,
            only_item_ids=[_COLLECTOR, "3031", "3094"],
        )
        self.assertTrue(res.ranked, "empty beam result makes this vacuous")
        for build in res.ranked:
            names = _names(self.snap, build.item_ids)
            self.assertEqual(
                len(names), len(set(names)),
                f"same-name duplicate in beam build {build.item_ids}: {names}",
            )


if __name__ == "__main__":
    unittest.main()
