"""P1-L18 audit: beam-search build-ranker SEARCH correctness.

Lane: the multi-item beam ranker in ``agents/daemon_slayer/beam.py`` ITSELF
(frontier expansion, pruning, dedup, ordering, gold/score bookkeeping) - NOT
the per-item scorers (verified correct by prior layers) and NOT ``_build_gold``
gold sourcing (verified by P1-L13).

Every expected value here is derived IN THE TEST from ``compute_dps`` /
exhaustive enumeration / the documented beam semantics. No hardcoded magic
DPS numbers, no fragile cross-item comparison asserts.

Documented beam semantics being checked (from the beam.py module docstring):
  * top-K partial builds kept per slot depth, expanded in parallel
  * dedupe by ``frozenset(item_ids)`` - order-invariant
  * score each expansion via the FULL ``compute_dps`` chain
  * keep top ``beam_width`` by weighted DPS each generation
  * final survivors sorted desc, clipped to ``top_n``
  * search depth = ``slot_count - len(current_item_ids)``
  * exhaustion (no expansion possible) ranks the deepest produced layer

Outcome: the beam search is algorithmically correct; this file is
search-correctness hardening (a valid P1-L18 outcome - prior layers clean).
"""
from __future__ import annotations

import itertools
import unittest

from agents.daemon_slayer.beam import beam_search_build
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import compute_dps
from agents.daemon_slayer.rank import _filter_candidates

# Six terminal SR AD items with no shared boots tag - a controlled pool
# small enough to enumerate exhaustively, varied enough that the optimal
# k-subset is non-trivial (different from "top-k by single-item delta").
_WL6 = ["3031", "3072", "6673", "3508", "3036", "6676"]
_CHAMP = "Aatrox"
_LVL = 11
_TA = 80.0


def _dps(snap: DataSnapshot, ids) -> float:
    return compute_dps(
        snap, _CHAMP, level=_LVL, mode="SR", target_armor=_TA,
        item_ids=list(ids),
    ).weighted_dps


def _exhaustive_best(snap: DataSnapshot, pool, k: int):
    """(best_frozenset, best_dps) over every k-subset, scored by compute_dps."""
    best = None
    for combo in itertools.combinations(pool, k):
        d = _dps(snap, combo)
        if best is None or d > best[1]:
            best = (frozenset(combo), d)
    return best


class BeamOptimalityWithinWidth(unittest.TestCase):
    """Sub-area 1: at width >= C(n,k) the beam MUST return the exhaustive
    optimum; at any narrower width it must never return a node worse than
    impossible-and-also never exceed the true optimum, and must never drop a
    node that strictly dominates a node it kept (the pruning-correctness
    invariant)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_full_width_returns_exhaustive_optimum_exactly(self) -> None:
        for k in (2, 3, 4):
            best_set, best_dps = _exhaustive_best(self.snap, _WL6, k)
            # C(6,k) <= 20; width 32 makes pruning impossible at every depth.
            r = beam_search_build(
                self.snap, _CHAMP, level=_LVL, mode="SR", target_armor=_TA,
                slot_count=k, beam_width=32, top_n=1, only_item_ids=_WL6,
            )
            self.assertEqual(
                frozenset(r.ranked[0].item_ids), best_set,
                f"k={k}: beam optimum != exhaustive optimum",
            )
            self.assertAlmostEqual(r.ranked[0].final_dps, best_dps, places=6)

    def test_narrow_beam_never_exceeds_true_optimum(self) -> None:
        # A correct (possibly approximate) beam can underperform the global
        # optimum but can NEVER report a build scoring higher than the real
        # best - that would mean a stale/double-counted score.
        best_set, best_dps = _exhaustive_best(self.snap, _WL6, 3)
        for w in (1, 2, 3, 5):
            r = beam_search_build(
                self.snap, _CHAMP, level=_LVL, mode="SR", target_armor=_TA,
                slot_count=3, beam_width=w, top_n=1, only_item_ids=_WL6,
            )
            self.assertLessEqual(
                r.ranked[0].final_dps, best_dps + 1e-9,
                f"width {w} reported a build above the exhaustive optimum",
            )

    def test_top_n_rows_are_the_n_best_distinct_sets_at_full_width(self) -> None:
        # At pruning-free width the ranked top_n must equal the n
        # highest-DPS distinct k-subsets by exhaustive enumeration, in order.
        k = 3
        scored = sorted(
            ((frozenset(c), _dps(self.snap, c))
             for c in itertools.combinations(_WL6, k)),
            key=lambda t: t[1], reverse=True,
        )
        want = scored[:4]
        r = beam_search_build(
            self.snap, _CHAMP, level=_LVL, mode="SR", target_armor=_TA,
            slot_count=k, beam_width=32, top_n=4, only_item_ids=_WL6,
        )
        got = [(frozenset(b.item_ids), b.final_dps) for b in r.ranked]
        self.assertEqual([s for s, _ in got], [s for s, _ in want])
        for (_, gd), (_, wd) in zip(got, want):
            self.assertAlmostEqual(gd, wd, places=6)


class BeamPruningKeepsTheTopKEachGeneration(unittest.TestCase):
    """Sub-area 1/3: reconstruct one expansion generation by hand and assert
    the beam keeps EXACTLY the beam_width highest-scoring expansions - no
    dominating node dropped, no mis-ordered frontier."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_first_generation_topk_is_exact_and_ordered(self) -> None:
        width = 4
        pool = [iid for iid, _ in _filter_candidates(
            self.snap, mode="SR", current_ids=set(), budget=None,
            include_components=False, only_ids=set(_WL6),
        )]
        # Generation 1 from the naked seed: every single-item build, scored
        # by the full chain, top-`width` by DPS in descending order.
        gen1 = sorted(
            ((iid, _dps(self.snap, [iid])) for iid in pool),
            key=lambda t: t[1], reverse=True,
        )[:width]
        r = beam_search_build(
            self.snap, _CHAMP, level=_LVL, mode="SR", target_armor=_TA,
            slot_count=1, beam_width=width, top_n=width, only_item_ids=_WL6,
        )
        got = [(b.item_ids[0], b.final_dps) for b in r.ranked]
        self.assertEqual([i for i, _ in got], [i for i, _ in gen1])
        for (_, gd), (_, wd) in zip(got, gen1):
            self.assertAlmostEqual(gd, wd, places=6)


class BeamConstraintPreservationAtEveryDepth(unittest.TestCase):
    """Sub-area 2: no path contains a duplicate item or >1 boots item at ANY
    depth; owned/excluded never enter a path; path length bounded."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def _boots(self, iid: str) -> bool:
        return "Boots" in (self.snap.items.get(iid, {}).get("tags") or [])

    def test_no_duplicate_item_in_any_returned_path(self) -> None:
        r = beam_search_build(
            self.snap, _CHAMP, level=_LVL, mode="SR", target_armor=_TA,
            beam_width=12, top_n=10,
        )
        for b in r.ranked:
            self.assertEqual(
                len(b.item_ids), len(set(b.item_ids)),
                f"duplicate item id in path {b.item_ids}",
            )

    def test_owned_items_pinned_and_never_re_added(self) -> None:
        owned = ["3031", "3072"]
        r = beam_search_build(
            self.snap, _CHAMP, level=_LVL, mode="SR", target_armor=_TA,
            current_item_ids=owned, beam_width=10, top_n=8,
        )
        for b in r.ranked:
            for o in owned:
                self.assertEqual(
                    b.item_ids.count(o), 1,
                    f"owned {o} not exactly once in {b.item_ids}",
                )
            self.assertEqual(len(b.item_ids), len(set(b.item_ids)))
            self.assertEqual(len(b.item_ids), 6)

    def test_excluded_pool_whitelist_holds_for_every_path(self) -> None:
        wl = set(_WL6)
        r = beam_search_build(
            self.snap, _CHAMP, level=_LVL, mode="SR", target_armor=_TA,
            slot_count=4, beam_width=8, top_n=6, only_item_ids=list(wl),
        )
        for b in r.ranked:
            self.assertTrue(set(b.item_ids).issubset(wl))

    def test_at_most_one_boots_at_every_depth_when_unique(self) -> None:
        # Search every depth 1..4 and assert no produced ranked build at any
        # depth carries two boots (boots-unique enforced during expansion,
        # not just on the final build).
        for sc in (2, 3, 4, 6):
            r = beam_search_build(
                self.snap, "MissFortune", level=_LVL, mode="SR",
                target_armor=_TA, slot_count=sc, beam_width=15, top_n=10,
            )
            for b in r.ranked:
                n_boots = sum(1 for i in b.item_ids if self._boots(i))
                self.assertLessEqual(
                    n_boots, 1,
                    f"slot_count={sc}: {n_boots} boots in {b.item_ids}",
                )

    def test_path_length_bounded_by_slot_count(self) -> None:
        for sc in (1, 2, 3, 5, 6):
            r = beam_search_build(
                self.snap, _CHAMP, level=_LVL, mode="SR", target_armor=_TA,
                slot_count=sc, beam_width=6, top_n=3,
            )
            for b in r.ranked:
                self.assertLessEqual(len(b.item_ids), sc)


class BeamDeterminismAndFrontierOrder(unittest.TestCase):
    """Sub-area 3: identical input -> byte-identical ranked output, including
    order; ties broken deterministically (no set/dict iteration leaking into
    result order)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_repeated_runs_identical_ids_and_order(self) -> None:
        def run():
            r = beam_search_build(
                self.snap, _CHAMP, level=_LVL, mode="SR", target_armor=_TA,
                beam_width=10, top_n=10,
            )
            return [(b.item_ids, round(b.final_dps, 9), b.total_gold)
                    for b in r.ranked], r.builds_evaluated, r.depth_reached

        a = run()
        b = run()
        c = run()
        self.assertEqual(a, b)
        self.assertEqual(b, c)

    def test_ranked_strictly_sorted_descending_by_final_dps(self) -> None:
        r = beam_search_build(
            self.snap, _CHAMP, level=_LVL, mode="SR", target_armor=_TA,
            beam_width=12, top_n=12,
        )
        finals = [b.final_dps for b in r.ranked]
        self.assertEqual(finals, sorted(finals, reverse=True))

    def test_tie_breaking_is_stable_and_deterministic(self) -> None:
        # Yunara in ARAM: mode_multiplier=0 forces EVERY build to 0.0 DPS,
        # so the entire frontier is a tie. A correct stable sort must then
        # return an identical (pool-insertion-order-driven) sequence every
        # run - any nondeterministic set/dict iteration would shuffle it.
        def run():
            r = beam_search_build(
                self.snap, "Yunara", level=_LVL, mode="ARAM",
                beam_width=8, top_n=8,
            )
            return [b.item_ids for b in r.ranked]

        first = run()
        self.assertTrue(all(
            compute_dps(self.snap, "Yunara", level=_LVL, mode="ARAM",
                        item_ids=list(ids)).weighted_dps == 0.0
            for ids in first
        ))
        for _ in range(4):
            self.assertEqual(run(), first)


class BeamGoldAndScoreMonotonicSanity(unittest.TestCase):
    """Sub-area 4: extending a path changes gold by exactly the new item's
    total gold; the path score is the scorer's value of the FULL path (no
    stale partial-score carried)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def _gold(self, iid: str) -> int:
        rec = self.snap.items.get(iid) or {}
        return int((rec.get("gold") or {}).get("total", 0) or 0)

    def test_path_gold_equals_sum_of_member_total_gold(self) -> None:
        r = beam_search_build(
            self.snap, _CHAMP, level=_LVL, mode="SR", target_armor=_TA,
            beam_width=10, top_n=10,
        )
        for b in r.ranked:
            self.assertEqual(
                b.total_gold, sum(self._gold(i) for i in b.item_ids),
                f"path gold mismatch for {b.item_ids}",
            )

    def test_owned_seed_gold_is_carried_into_path_gold(self) -> None:
        owned = ["3031", "3072"]
        r = beam_search_build(
            self.snap, _CHAMP, level=_LVL, mode="SR", target_armor=_TA,
            current_item_ids=owned, beam_width=8, top_n=5,
        )
        seed_gold = sum(self._gold(i) for i in owned)
        for b in r.ranked:
            extra = [i for i in b.item_ids if i not in owned]
            self.assertEqual(
                b.total_gold,
                seed_gold + sum(self._gold(i) for i in extra),
            )

    def test_reported_final_dps_is_full_path_compute_dps(self) -> None:
        # The carried beam score must be compute_dps over the WHOLE path,
        # not a stale prefix score. Recompute each ranked build from
        # scratch and require an exact match.
        r = beam_search_build(
            self.snap, _CHAMP, level=_LVL, mode="SR", target_armor=_TA,
            beam_width=10, top_n=10,
        )
        for b in r.ranked:
            fresh = _dps(self.snap, b.item_ids)
            self.assertAlmostEqual(b.final_dps, fresh, places=6)
            self.assertAlmostEqual(
                b.delta_dps, fresh - r.baseline_dps, places=6,
            )

    def test_delta_is_final_minus_baseline_and_eff_consistent(self) -> None:
        r = beam_search_build(
            self.snap, _CHAMP, level=_LVL, mode="SR", target_armor=_TA,
            beam_width=8, top_n=6,
        )
        for b in r.ranked:
            self.assertAlmostEqual(
                b.delta_dps, b.final_dps - b.baseline_dps, places=9,
            )
            if b.total_gold > 0 and b.delta_dps > 0:
                self.assertAlmostEqual(
                    b.dps_per_1k_gold,
                    b.delta_dps / (b.total_gold / 1000.0), places=6,
                )
            else:
                self.assertEqual(b.dps_per_1k_gold, 0.0)


class BeamDepthBookkeeping(unittest.TestCase):
    """Sub-area 1 (off-by-one): depth range produces exactly
    ``slot_count - len(owned)`` generations; exhaustion ranks the deepest
    produced layer and does NOT inflate depth_reached."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_full_search_reaches_exactly_remaining_depth(self) -> None:
        for sc in (3, 4, 6):
            r = beam_search_build(
                self.snap, _CHAMP, level=_LVL, mode="SR", target_armor=_TA,
                slot_count=sc, beam_width=5, top_n=1,
            )
            self.assertEqual(r.depth_reached, sc)
            self.assertEqual(len(r.ranked[0].item_ids), sc)

    def test_owned_seed_reduces_search_depth_by_owned_count(self) -> None:
        owned = ["3031", "3072", "3006"]
        r = beam_search_build(
            self.snap, _CHAMP, level=_LVL, mode="SR", target_armor=_TA,
            current_item_ids=owned, slot_count=6, beam_width=5, top_n=1,
        )
        self.assertEqual(r.depth_reached, 6 - len(owned))
        self.assertEqual(len(r.ranked[0].item_ids), 6)

    def test_exhaustion_ranks_deepest_layer_without_depth_inflation(self) -> None:
        # 2-item whitelist, slot_count=6: reaches depth 2 then cannot expand.
        r = beam_search_build(
            self.snap, _CHAMP, level=_LVL, mode="SR", target_armor=_TA,
            slot_count=6, beam_width=4, top_n=3, only_item_ids=["3031", "3072"],
        )
        self.assertEqual(r.depth_reached, 2)
        self.assertTrue(all(len(b.item_ids) == 2 for b in r.ranked))
        self.assertTrue(any("exhaust" in n for n in r.notes))

    def test_empty_effective_pool_returns_seed_at_depth_zero(self) -> None:
        # Whitelist a non-terminal component: terminal-only filter empties
        # the pool, no expansion ever happens, seed returned at depth 0.
        r = beam_search_build(
            self.snap, _CHAMP, level=_LVL, mode="SR", target_armor=_TA,
            slot_count=6, beam_width=4, top_n=1, only_item_ids=["1036"],
        )
        self.assertEqual(r.depth_reached, 0)
        self.assertEqual(r.builds_evaluated, 1)
        self.assertEqual(tuple(r.ranked[0].item_ids), ())


if __name__ == "__main__":
    unittest.main()
