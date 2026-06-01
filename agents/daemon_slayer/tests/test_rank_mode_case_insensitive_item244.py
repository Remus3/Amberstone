# arch: item 244 DS rank mode case-insensitivity hardening | section=daemon_slayer | frozen=no
"""Mode-string case-insensitivity for the rank-layer map/trinket filters (item 244).

Root cause (item 243 NEXT(1)): ``MODE_MAP_ID`` keys are UPPERCASE
(``SR``/``ARAM``/``ARENA``/``BRAWL``) and ``_is_legal_in_mode`` did a
case-sensitive ``MODE_MAP_ID.get(mode)``. A ``/rank`` request with a
LOWERCASE ``mode`` (e.g. ``mode=aram``) made ``.get("aram")`` return
None, so ``_is_legal_in_mode`` fell through to its allow-all branch and
admitted EVERY purchasable item - including the Arena 22-prefixed mirror
ids and DDragon maps-mislabelled joke items - into the pool for that
mode. The sibling ``strip_arena_trinkets`` had the same case bug
(``mode != "ARENA"``), so a lowercase ``arena`` never stripped the
Arcane Sweeper trinket. The live COACH path is unaffected (it dispatches
uppercase ``ARAM``/``SR``/...), so this is a robustness / Brawl-bug-class
hardening, not a live coaching regression - but ``/rank`` is callable
with arbitrary case from the route body.

Fix: ``_is_legal_in_mode`` and ``strip_arena_trinkets`` normalise the
mode with ``.upper()`` internally so the filter is case-insensitive. A
recognised mode now filters by its real DDragon map id regardless of the
request's case; an unrecognised mode still falls through to allow-all.

Discipline (mirrors test_rank_mode_legality_p1l23.py): every expectation
is derived FROM the source ``maps`` / ``gold`` fields inside the test. No
hardcoded engine-output magic numbers; no fragile cross-item comparison
asserts. The defining assertions are pool-equality between a lowercase
mode and its uppercase form, computed from the live snapshot.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.rank import (
    ARENA_TRINKET_IDS,
    MODE_MAP_ID,
    _filter_candidates,
    _is_legal_in_mode,
    rank_items,
    strip_arena_trinkets,
)

# Each live mode paired with a case-variant that must resolve identically.
_CASE_VARIANTS = {
    "SR": ("sr", "Sr", "sR"),
    "ARAM": ("aram", "Aram", "ArAm"),
    "ARENA": ("arena", "Arena", "ArEnA"),
    "BRAWL": ("brawl", "Brawl", "bRaWl"),
}


def _arena_only_item(snap: DataSnapshot):
    """Return (item_id, rec) for a purchasable terminal item that is
    map-30 (Arena) legal AND map-11/12/35 illegal, picked from the source
    ``maps`` field. Such an item is the cleanest probe for a leaked filter:
    pre-fix a lowercase ``sr`` admits it, post-fix it does not."""
    for item_id, rec in snap.items.items():
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
            return item_id, rec
    return None, None


class IsLegalInModeCaseInsensitiveTests(unittest.TestCase):
    """``_is_legal_in_mode`` must give the same verdict for any case of a
    recognised mode and mirror the source ``maps`` field exactly."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_arena_only_item_verdict_is_case_insensitive(self) -> None:
        item_id, rec = _arena_only_item(self.snap)
        self.assertIsNotNone(
            item_id, "snapshot has no Arena-only terminal item to probe"
        )
        # Arena: every case variant agrees with the canonical uppercase
        # (True, since the source maps['30'] is set).
        self.assertTrue(_is_legal_in_mode(rec, "ARENA"))
        for variant in _CASE_VARIANTS["ARENA"]:
            self.assertEqual(
                _is_legal_in_mode(rec, variant),
                _is_legal_in_mode(rec, "ARENA"),
                f"_is_legal_in_mode disagrees for {variant!r} vs 'ARENA'",
            )
        # SR: an Arena-only item is map-11 illegal; a lowercase 'sr' must
        # NOT silently allow it (the pre-fix bug returned True here).
        self.assertFalse(_is_legal_in_mode(rec, "SR"))
        for variant in _CASE_VARIANTS["SR"]:
            self.assertFalse(
                _is_legal_in_mode(rec, variant),
                f"Arena-only item wrongly legal for {variant!r} (map-11 false)",
            )

    def test_every_mode_case_variant_matches_uppercase_for_all_items(self) -> None:
        # Strong invariant: for every item and every recognised mode, each
        # case variant returns the identical verdict as the uppercase form.
        for canonical, variants in _CASE_VARIANTS.items():
            for item_id, rec in self.snap.items.items():
                base = _is_legal_in_mode(rec, canonical)
                for variant in variants:
                    self.assertEqual(
                        _is_legal_in_mode(rec, variant),
                        base,
                        f"item {item_id}: {variant!r} != {canonical!r}",
                    )

    def test_unknown_mode_still_allows_all_regardless_of_case(self) -> None:
        # An unrecognised mode falls through to allow-all (True) for any
        # item; case does not change that documented contract.
        any_rec = next(iter(self.snap.items.values()))
        for junk in ("TFT_DOUBLE_UP", "weird", "", "not_a_mode"):
            self.assertTrue(_is_legal_in_mode(any_rec, junk))


class FilterCandidatesCaseInsensitiveTests(unittest.TestCase):
    """``_filter_candidates`` pool must be identical for a lowercase mode
    and its uppercase form - the core regression pin for item 244."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_pool_identical_lowercase_vs_uppercase_every_mode(self) -> None:
        for canonical, variants in _CASE_VARIANTS.items():
            upper_pool = {
                i for i, _ in _filter_candidates(
                    self.snap, canonical, set(), None, False, None
                )
            }
            for variant in variants:
                var_pool = {
                    i for i, _ in _filter_candidates(
                        self.snap, variant, set(), None, False, None
                    )
                }
                self.assertEqual(
                    var_pool, upper_pool,
                    f"mode={variant!r} pool differs from {canonical!r} pool "
                    f"(symmetric diff "
                    f"{sorted(var_pool ^ upper_pool)[:10]})",
                )

    def test_lowercase_mode_admits_no_map_illegal_item(self) -> None:
        # Directly assert the live bug is closed: a lowercase mode's pool
        # contains zero items whose source maps[<map-id>] is falsey.
        for canonical, variants in _CASE_VARIANTS.items():
            map_id = MODE_MAP_ID[canonical]
            for variant in variants:
                pool = _filter_candidates(
                    self.snap, variant, set(), None, False, None
                )
                offenders = [
                    (i, r.get("name"))
                    for i, r in pool
                    if not (r.get("maps") or {}).get(map_id)
                ]
                self.assertEqual(
                    offenders, [],
                    f"mode={variant!r}: {len(offenders)} map-{map_id}-ILLEGAL "
                    f"items admitted (lowercase bypass): {offenders[:8]}",
                )


class StripArenaTrinketsCaseInsensitiveTests(unittest.TestCase):
    """``strip_arena_trinkets`` must strip the Arcane Sweeper trinket for
    any case of ``arena`` and no-op for any case of a non-Arena mode."""

    def test_lowercase_arena_strips_trinket(self) -> None:
        trinket = next(iter(ARENA_TRINKET_IDS))
        current = (trinket, "1234")
        for variant in _CASE_VARIANTS["ARENA"]:
            kept, stripped = strip_arena_trinkets(current, variant)
            self.assertEqual(
                stripped, (trinket,),
                f"mode={variant!r} failed to strip the Arena trinket",
            )
            self.assertEqual(kept, ("1234",))

    def test_non_arena_modes_never_strip_any_case(self) -> None:
        trinket = next(iter(ARENA_TRINKET_IDS))
        current = (trinket, "1234")
        for mode in ("SR", "sr", "ARAM", "aram", "BRAWL", "brawl"):
            kept, stripped = strip_arena_trinkets(current, mode)
            self.assertEqual(
                stripped, (),
                f"mode={mode!r} wrongly stripped a trinket outside Arena",
            )
            self.assertEqual(kept, current)


class RankItemsLowercaseEndToEndTests(unittest.TestCase):
    """End-to-end through the public ``rank_items``: a lowercase mode must
    constrain the ranked pool to that mode's map exactly like uppercase."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_lowercase_aram_ranked_pool_is_map12_constrained(self) -> None:
        r = rank_items(
            self.snap, "Aatrox", level=11, mode="aram",
            target_armor=80, top_n=50,
        )
        self.assertGreater(len(r.ranked), 0)
        for ri in r.ranked:
            rec = self.snap.items.get(ri.item_id, {})
            self.assertTrue(
                (rec.get("maps") or {}).get("12"),
                f"lowercase aram ranked item {ri.item_id} ({ri.item_name}) "
                f"is map-12-ILLEGAL per its source maps field",
            )

    def test_lowercase_aram_ranked_ids_match_uppercase(self) -> None:
        lo = rank_items(
            self.snap, "Aatrox", level=11, mode="aram",
            target_armor=80, top_n=50,
        )
        up = rank_items(
            self.snap, "Aatrox", level=11, mode="ARAM",
            target_armor=80, top_n=50,
        )
        self.assertEqual(
            [ri.item_id for ri in lo.ranked],
            [ri.item_id for ri in up.ranked],
            "lowercase aram ranking diverges from uppercase ARAM",
        )


if __name__ == "__main__":
    unittest.main()
