# arch: P1-L23 DS rank mode-legality / candidate-pool filtering audit | section=daemon_slayer | frozen=no
"""Mode-legality matrix + candidate-pool filtering hardening (audit P1-L23).

Lane: ``agents/daemon_slayer/rank.py`` top-level orchestration plus the
candidate-pool / mode-legality FILTERING that decides which items are
eligible per mode/map (``_is_purchasable``, ``_is_legal_in_mode``,
``strip_arena_trinkets``, ``_filter_candidates``, ``MODE_MAP_ID``). A
wrong filter silently removes a legal item (false-negative: missing
recommendations) or admits an illegal one (false-positive: an item the
player cannot buy in that mode) for a whole mode - a high-impact
recommendation bug.

Discipline: every expectation is derived FROM the item source
``maps`` / ``gold.purchasable`` / ``gold.total`` fields inside the test.
No hardcoded magic numbers for engine outputs. No fragile cross-item
comparison assertions (no "item A delta > item B delta"); all asserts
are on set membership computed from the source fields, or on structural
properties (determinism, no-dups, non-empty, no-crash).

P1-L23 finding: BUG-FOUND - ``MODE_MAP_ID`` lacked the Brawl map id
(35). ``coaches/brawl_coach.py._ds_engine_mode("BRAWL")`` returns the
literal ``"BRAWL"`` (see tests/test_cross_mode_ds_p1l6.py
CrossModeBrawlRoutingTests), so ``rank_items`` genuinely receives
``mode="BRAWL"`` for real Brawl games. With no ``"BRAWL"`` key,
``_is_legal_in_mode`` returned True for EVERY item, admitting ~281
``maps["35"]==False`` items (Doran's, jungle companions, the whole
22-prefixed Arena-mirror set) into Brawl recommendations. Fixed by
mapping ``"BRAWL" -> "35"`` so Brawl filters by its real DDragon map id
exactly like SR/ARAM/ARENA. These tests pin the corrected matrix and
the structural invariants so a regression is caught.
"""
from __future__ import annotations

import collections
import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.rank import (
    MODE_MAP_ID,
    _filter_candidates,
    _is_legal_in_mode,
    _is_purchasable,
    _is_terminal,
    rank_items,
)

# DDragon map ids the live coaches actually dispatch through the DS
# engine. Brawl is map 35 (see brawl_coach._ds_engine_mode -> "BRAWL").
# These are asserted to be wired in MODE_MAP_ID; the per-mode pool is
# then derived purely from the snapshot ``maps`` field for the id.
_LIVE_MODE_MAP = {"SR": "11", "ARAM": "12", "ARENA": "30", "BRAWL": "35"}


def _source_legal_purchasable_terminal(snap: DataSnapshot, map_id: str) -> set[str]:
    """Expected terminal pool for a map id, computed from source fields.

    eligible == purchasable (gold.purchasable AND gold.total>0) AND
    maps[map_id] is truthy AND terminal (no ``into``). This mirrors
    _filter_candidates' documented contract but is derived independently
    here from the raw records so the test does not just restate the impl.
    """
    out: set[str] = set()
    for item_id, rec in snap.items.items():
        gold = rec.get("gold") or {}
        purchasable = bool(gold.get("purchasable")) and int(
            gold.get("total", 0) or 0
        ) > 0
        if not purchasable:
            continue
        if not (rec.get("maps") or {}).get(map_id):
            continue
        into = rec.get("into")
        if into:  # non-terminal component
            continue
        out.add(item_id)
    return out


class ModeMapIdWiringTests(unittest.TestCase):
    """Every live-dispatched mode must have its real DDragon map id wired.

    A missing entry makes ``_is_legal_in_mode`` a silent no-op (returns
    True for all items) for that whole mode - the Brawl bug class.
    """

    def test_all_live_modes_have_correct_map_id(self) -> None:
        for mode, map_id in _LIVE_MODE_MAP.items():
            self.assertIn(
                mode, MODE_MAP_ID,
                f"{mode} not wired in MODE_MAP_ID - per-mode item filter "
                f"silently no-ops for the entire mode",
            )
            self.assertEqual(
                MODE_MAP_ID[mode], map_id,
                f"{mode} mapped to {MODE_MAP_ID[mode]!r}, expected DDragon "
                f"map id {map_id!r}",
            )

    def test_brawl_is_map_35(self) -> None:
        # Regression pin for the P1-L23 fix: Brawl is DDragon map 35, NOT
        # SR (11). coaches/brawl_coach.py._ds_engine_mode('BRAWL') returns
        # the literal 'BRAWL', so this id is what gates the Brawl pool.
        self.assertEqual(MODE_MAP_ID.get("BRAWL"), "35")


class ModeLegalityMatrixTests(unittest.TestCase):
    """For every live mode, the eligible terminal pool == exactly the
    items whose source ``maps[<mode-map>]`` is true AND purchasable,
    with the documented exception that non-purchasable trinkets
    (Arcane Sweeper) are excluded via _is_purchasable."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_pool_equals_source_field_derived_set_every_mode(self) -> None:
        for mode, map_id in _LIVE_MODE_MAP.items():
            expected = _source_legal_purchasable_terminal(self.snap, map_id)
            actual = {
                i for i, _ in _filter_candidates(
                    self.snap, mode, set(), None, False, None
                )
            }
            # No legal item filtered out (false-negative = silently
            # missing recommendations).
            missing = expected - actual
            self.assertEqual(
                missing, set(),
                f"mode={mode}: {len(missing)} legal+purchasable+terminal "
                f"items filtered OUT of the pool (false-negative): "
                f"{sorted(missing)[:10]}",
            )
            # No illegal/non-purchasable item admitted (false-positive =
            # recommending an item the player cannot buy in that mode).
            extra = actual - expected
            self.assertEqual(
                extra, set(),
                f"mode={mode}: {len(extra)} items admitted that are NOT "
                f"map-legal+purchasable+terminal (false-positive): "
                f"{sorted(extra)[:10]}",
            )

    def test_brawl_pool_excludes_map35_illegal_items(self) -> None:
        # The defining P1-L23 assertion. Pre-fix the Brawl pool admitted
        # every purchasable item (no map filter); post-fix every item in
        # the pool must be maps['35']-legal per its own source record.
        pool = _filter_candidates(
            self.snap, "BRAWL", set(), None, False, None
        )
        offenders = [
            (i, r.get("name"))
            for i, r in pool
            if not (r.get("maps") or {}).get("35")
        ]
        self.assertEqual(
            offenders, [],
            f"{len(offenders)} map-35-ILLEGAL items admitted into the "
            f"Brawl pool (false-positive recommendations): "
            f"{offenders[:12]}",
        )

    def test_arena_only_item_not_in_sr_aram_brawl_pools(self) -> None:
        # Pick the Arena-only proof item from the source maps field, not a
        # hardcoded id: an item that is map-30 true AND map 11/12/35 false
        # AND purchasable+terminal must appear ONLY in the Arena pool.
        arena_only = None
        for item_id, rec in self.snap.items.items():
            mp = rec.get("maps") or {}
            gold = rec.get("gold") or {}
            purchasable = bool(gold.get("purchasable")) and int(
                gold.get("total", 0) or 0
            ) > 0
            if (
                purchasable
                and not rec.get("into")
                and mp.get("30")
                and not mp.get("11")
                and not mp.get("12")
                and not mp.get("35")
            ):
                arena_only = item_id
                break
        self.assertIsNotNone(
            arena_only, "snapshot has no Arena-only terminal item to test"
        )
        for mode in ("SR", "ARAM", "BRAWL"):
            ids = {
                i for i, _ in _filter_candidates(
                    self.snap, mode, set(), None, False, None
                )
            }
            self.assertNotIn(
                arena_only, ids,
                f"Arena-only item {arena_only} leaked into the {mode} pool",
            )
        arena_ids = {
            i for i, _ in _filter_candidates(
                self.snap, "ARENA", set(), None, False, None
            )
        }
        self.assertIn(
            arena_only, arena_ids,
            f"Arena-only item {arena_only} missing from the Arena pool "
            f"(false-negative)",
        )


class KnownExceptionScopingTests(unittest.TestCase):
    """The settled-truth exceptions hold, asserted via the source maps /
    gold fields rather than a hardcoded id allow/deny list."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_arcane_sweeper_3348_excluded_by_purchasable_every_mode(self) -> None:
        rec = self.snap.item("3348")
        # Source proof: it is map-30 legal but non-purchasable, so the
        # exclusion is via _is_purchasable, NOT a map filter.
        self.assertFalse(
            bool((rec.get("gold") or {}).get("purchasable"))
            and int((rec.get("gold") or {}).get("total", 0) or 0) > 0,
            "Arcane Sweeper source must be non-purchasable",
        )
        self.assertFalse(_is_purchasable(rec))
        for mode in _LIVE_MODE_MAP:
            ids = {
                i for i, _ in _filter_candidates(
                    self.snap, mode, set(), None, True, None  # incl components
                )
            }
            self.assertNotIn(
                "3348", ids,
                f"Arcane Sweeper (non-purchasable) leaked into {mode} pool",
            )

    def test_galeforce_446671_arena_only_via_maps_not_global_denylist(self) -> None:
        rec = self.snap.item("446671")
        maps = rec.get("maps") or {}
        # Assert by the source maps field (settled truth: map 30 only).
        self.assertTrue(maps.get("30"))
        self.assertFalse(maps.get("11"))
        self.assertFalse(maps.get("12"))
        self.assertFalse(maps.get("35"))
        # _is_legal_in_mode must mirror the source field exactly.
        self.assertTrue(_is_legal_in_mode(rec, "ARENA"))
        self.assertFalse(_is_legal_in_mode(rec, "SR"))
        self.assertFalse(_is_legal_in_mode(rec, "ARAM"))
        self.assertFalse(_is_legal_in_mode(rec, "BRAWL"))
        # And it is not deny-listed globally: it IS in the Arena pool.
        if _is_purchasable(rec):
            arena_ids = {
                i for i, _ in _filter_candidates(
                    self.snap, "ARENA", set(), None, False, None
                )
            }
            self.assertIn(
                "446671", arena_ids,
                "Galeforce wrongly absent from the Arena pool",
            )

    def test_22_prefixed_mirror_ids_resolve_to_arena_only(self) -> None:
        # The 22-prefixed Arena-mirror ids are deliberate. Each one's
        # source maps must be map-30-only; assert they appear in the
        # Arena pool and NOT in SR/ARAM/Brawl - derived from the field,
        # no hardcoded id list.
        mirror_ids = [
            k for k, r in self.snap.items.items()
            if k.startswith("22") and len(k) == 6 and _is_purchasable(r)
            and _is_terminal(r) and (r.get("maps") or {}).get("30")
        ]
        self.assertGreater(
            len(mirror_ids), 0, "no purchasable 22-prefixed mirror items"
        )
        arena_ids = {
            i for i, _ in _filter_candidates(
                self.snap, "ARENA", set(), None, False, None
            )
        }
        sr_ids = {
            i for i, _ in _filter_candidates(
                self.snap, "SR", set(), None, False, None
            )
        }
        brawl_ids = {
            i for i, _ in _filter_candidates(
                self.snap, "BRAWL", set(), None, False, None
            )
        }
        for mid in mirror_ids:
            rec = self.snap.items[mid]
            mp = rec.get("maps") or {}
            self.assertIn(
                mid, arena_ids,
                f"22-mirror {mid} missing from Arena pool",
            )
            # If its source says NOT map-11/35, it must not be in those.
            if not mp.get("11"):
                self.assertNotIn(
                    mid, sr_ids, f"22-mirror {mid} leaked into SR pool"
                )
            if not mp.get("35"):
                self.assertNotIn(
                    mid, brawl_ids,
                    f"22-mirror {mid} leaked into Brawl pool",
                )


class PoolDeterminismCompletenessTests(unittest.TestCase):
    """Sub-area 3: same mode -> same pool; no duplicate ids; pool
    non-empty for every live mode; a garbage mode degrades to a defined
    default (no crash, not silently empty)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_pool_is_deterministic_per_mode(self) -> None:
        for mode in _LIVE_MODE_MAP:
            p1 = [i for i, _ in _filter_candidates(
                self.snap, mode, set(), None, False, None)]
            p2 = [i for i, _ in _filter_candidates(
                self.snap, mode, set(), None, False, None)]
            self.assertEqual(
                p1, p2, f"mode={mode} pool not deterministic"
            )

    def test_no_duplicate_ids_in_pool(self) -> None:
        for mode in _LIVE_MODE_MAP:
            ids = [i for i, _ in _filter_candidates(
                self.snap, mode, set(), None, False, None)]
            dups = [
                x for x, n in collections.Counter(ids).items() if n > 1
            ]
            self.assertEqual(
                dups, [], f"mode={mode} pool has duplicate ids: {dups}"
            )

    def test_pool_non_empty_for_every_live_mode(self) -> None:
        for mode in _LIVE_MODE_MAP:
            ids = [i for i, _ in _filter_candidates(
                self.snap, mode, set(), None, False, None)]
            self.assertGreater(
                len(ids), 0,
                f"mode={mode} pool is EMPTY - would silently yield no "
                f"recommendation",
            )

    def test_garbage_mode_degrades_to_nonempty_default_no_crash(self) -> None:
        # An unknown mode is documented to fall through with no per-mode
        # filter (allow-all) - it must NOT crash and must NOT be empty
        # (an empty pool silently yields zero recommendations).
        for junk in ("TFT_DOUBLE_UP", "weird", "", "12345", "ArEnA"):
            try:
                pool = _filter_candidates(
                    self.snap, junk, set(), None, False, None
                )
            except Exception as exc:  # noqa: BLE001 - assert no crash
                self.fail(
                    f"garbage mode {junk!r} crashed _filter_candidates: "
                    f"{exc!r}"
                )
            self.assertGreater(
                len(pool), 0,
                f"garbage mode {junk!r} produced an EMPTY pool",
            )

    def test_rank_items_garbage_mode_returns_result_with_note(self) -> None:
        # End-to-end: a garbage mode through rank_items must produce a
        # RankResult (not raise) and annotate the no-filter fallback.
        r = rank_items(
            self.snap, "Aatrox", level=11, mode="NOT_A_REAL_MODE",
            target_armor=80, top_n=5,
        )
        self.assertGreater(len(r.ranked), 0)
        self.assertTrue(
            any("not in MODE_MAP_ID" in n for n in r.notes),
            "garbage mode must carry the no-per-mode-filter note",
        )

    def test_rank_items_brawl_pool_is_map35_constrained_end_to_end(self) -> None:
        # End-to-end through rank_items: every ranked Brawl item must be
        # map-35 legal per its own source record (proves the fix reaches
        # the public API, not just _filter_candidates).
        r = rank_items(
            self.snap, "Aatrox", level=11, mode="BRAWL",
            target_armor=80, top_n=50,
        )
        self.assertGreater(len(r.ranked), 0)
        for ri in r.ranked:
            rec = self.snap.items.get(ri.item_id, {})
            self.assertTrue(
                (rec.get("maps") or {}).get("35"),
                f"ranked Brawl item {ri.item_id} ({ri.item_name}) is "
                f"map-35-ILLEGAL per its source maps field",
            )
        self.assertTrue(
            any("maps id 35" in n for n in r.notes),
            "Brawl result must note the map-35 filter is applied",
        )


if __name__ == "__main__":
    unittest.main()
