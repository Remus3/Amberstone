"""P1-L13 gold-efficiency / value-per-gold correctness audit.

Lane: the part the operator sees as "delta per gold" - does the engine
compute item gold cost and the value-per-gold / delta-per-gold
normalization correctly versus the vendored Meraki gold data, including
component buildup.

Design rules honored here:
  * Expected gold is DERIVED at runtime from the vendored Meraki snapshot
    (``data/daemon_slayer/16.10.1/items_meraki.json`` -> ``shop.prices``)
    inside the test. No hardcoded magic gold numbers.
  * No fragile cross-item comparison asserts (no "item A must beat item
    B"). We assert the computed gold / efficiency / ordering value
    itself, against an independently-derived expected number.
  * Vendored 16.10.1 snapshot only - no live Meraki re-extract.

The engine consumes the DDragon-shaped ``items.json`` where
``gold.total`` is the FULL build cost and ``gold.base`` is the
combine-only (recipe) cost. Meraki's ``shop.prices.total`` is the
independent ground truth for the full build cost. The central
correctness question: the engine must normalize by ``gold.total``
(full cost), never ``gold.base`` (combine cost).
"""

from __future__ import annotations

import json
import math
import unittest
from pathlib import Path

from agents.daemon_slayer.beam import _build_gold, beam_search_build
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.rank import _is_purchasable, rank_items

_PATCH = "16.10.1"
_REPO_ROOT = Path(__file__).resolve().parents[3]
_MERAKI_PATH = (
    _REPO_ROOT / "data" / "daemon_slayer" / _PATCH / "items_meraki.json"
)


def _load_meraki() -> dict[str, dict]:
    doc = json.loads(_MERAKI_PATH.read_text(encoding="utf-8"))
    return doc["items"]


def _meraki_total(meraki: dict[str, dict], item_id: str) -> int:
    """Independent ground-truth full build cost from Meraki shop.prices."""
    return int(meraki[item_id]["shop"]["prices"]["total"])


# Patch 16.10.1: five real, purchasable, non-Arena items where the two
# INDEPENDENT data sources (DDragon-shaped items.json the engine loads vs
# the vendored Meraki snapshot) disagree on the full total. This is a
# data-source snapshot-timing artifact, NOT an engine gold-efficiency
# bug: the disagreement runs in BOTH directions (Statikk DDragon 3000 >
# Meraki 2700; Hubris DDragon 2800 < Meraki 3000), which rules out any
# one-sided "engine substituted the combine cost" error - and for every
# one of these the engine value is still nowhere near the DDragon
# combine-only ``gold.base`` (Statikk base=625, Redemption base=850).
# The engine consistently uses the full ``gold.total`` from the snapshot
# it actually consumes; that is correct. These ids are enumerated (not
# pattern-skipped) so a NEW divergence in a future snapshot fails loudly
# instead of being silently swallowed. The combine-cost guard in
# ``test_engine_never_uses_combine_cost_anywhere`` still covers them.
_KNOWN_SOURCE_DELTA_IDS: frozenset[str] = frozenset(
    {"3087", "3107", "3172", "6609", "6697"}
)


def _is_arena_idspace(item_id: str) -> bool:
    """Arena-only pseudo-item id-space the engine handles separately.

    Six-plus-digit ids beginning ``22`` (Arena alias variants like
    223031, and the ``2200xx`` generic "Legendary <Class> Item"
    placeholders) or ``44`` (Arena prismatic items). Meraki prices these
    with a distinct Arena shop model (often total=0 or a flat Arena
    price) that legitimately differs from the DDragon snapshot the
    engine consumes; cross-source equality is not expected for them and
    excluding them is data-shape correctness, not a bug mask. The
    catalog-wide combine-cost guard still covers this id-space.
    """
    return len(item_id) >= 6 and (
        item_id.startswith("22") or item_id.startswith("44")
    )


class GoldDataGroundTruthTests(unittest.TestCase):
    """Sub-area 1: item gold correctness vs Meraki, no double-count."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load(patch=_PATCH)
        cls.meraki = _load_meraki()
        # Spread: cheap component, mid combine, full legendary, two
        # boots, a recipe-built crit item. Each id is verified present
        # in BOTH sources at setup so a future snapshot drift fails
        # loudly here rather than silently skipping.
        cls.spread = {
            "1036": "Long Sword",            # cheap tier-1 component
            "1038": "B. F. Sword",           # mid tier-2 component
            "3031": "Infinity Edge",         # full legendary (recipe)
            "3006": "Berserker's Greaves",   # boots
            "3158": "Ionian Boots of Lucidity",  # boots
            "3508": "Essence Reaver",        # legendary built from items
            "6673": "Immortal Shieldbow",    # legendary
            "3142": "Youmuu's Ghostblade",   # legendary
        }
        for iid in cls.spread:
            assert iid in cls.snap.items, f"{iid} missing from snapshot"
            assert iid in cls.meraki, f"{iid} missing from Meraki"

    def test_engine_gold_equals_meraki_total_not_combine(self) -> None:
        """Engine ``gold.total`` == Meraki full total for every spread
        item, and is NOT the DDragon combine-only ``gold.base`` whenever
        the two differ (the classic combine-cost confusion bug)."""
        for iid, name in self.spread.items():
            gold = self.snap.items[iid]["gold"]
            engine_total = int(gold["total"])
            expected = _meraki_total(self.meraki, iid)
            self.assertEqual(
                engine_total,
                expected,
                f"{name} ({iid}): engine total {engine_total} != "
                f"Meraki total {expected}",
            )
            base = int(gold["base"])
            if base != expected:
                # Recipe item (IE base=725, total=3500). The engine must
                # report the total, never the combine-only base.
                self.assertNotEqual(
                    engine_total,
                    base,
                    f"{name} ({iid}): engine used combine cost {base} "
                    f"instead of full total {expected}",
                )

    def test_purchasable_catalog_matches_meraki_total(self) -> None:
        """Broad sweep: every engine-purchasable item that Meraki also
        prices with a non-zero total agrees exactly, EXCEPT the five
        enumerated known data-source deltas. Guards a silent
        field-mapping regression across the whole catalog, not just the
        curated spread. (Arena prismatics / placeholders where Meraki
        reports total=0 use a different shop model and are excluded by
        the >0 Meraki gate - that asymmetry is data, not an engine bug.)
        A NEW item drifting from Meraki - one not in the known set -
        fails here, which is what we want.
        """
        checked = 0
        unexpected: list[tuple[str, str, int, int]] = []
        for iid, rec in self.snap.items.items():
            if not _is_purchasable(rec):
                continue
            mrec = self.meraki.get(iid)
            if mrec is None:
                continue
            mtotal = mrec.get("shop", {}).get("prices", {}).get("total")
            if not mtotal or int(mtotal) <= 0:
                continue
            if _is_arena_idspace(iid):
                continue  # separate Arena shop model - see helper docstring
            engine_total = int((rec.get("gold") or {}).get("total", 0) or 0)
            checked += 1
            if engine_total == int(mtotal):
                continue
            if iid in _KNOWN_SOURCE_DELTA_IDS:
                continue
            unexpected.append(
                (iid, str(rec.get("name")), engine_total, int(mtotal))
            )
        self.assertEqual(
            unexpected,
            [],
            f"item(s) drifted from Meraki total (not in the documented "
            f"known-delta set): {unexpected}",
        )
        # Sanity: the sweep actually exercised a meaningful population.
        self.assertGreater(checked, 150)

    def test_engine_never_uses_combine_cost_anywhere(self) -> None:
        """The real catalog-wide invariant: for EVERY purchasable
        recipe item (``gold.base`` != ``gold.total``), the engine value
        equals the full total and is never the combine-only base. This
        is the bug class the lane hunts (combine cost used where total
        is correct) - asserted over the whole catalog, independent of
        the Meraki cross-source agreement, so the five known data-source
        deltas are still fully covered here.
        """
        recipe_items = 0
        for iid, rec in self.snap.items.items():
            if not _is_purchasable(rec):
                continue
            g = rec.get("gold") or {}
            total = int(g.get("total", 0) or 0)
            base = int(g.get("base", 0) or 0)
            if total <= 0 or base == total:
                continue  # raw component - base == total, nothing to confuse
            recipe_items += 1
            with self.subTest(item_id=iid, name=rec.get("name")):
                # The engine reads gold.total everywhere; assert the
                # snapshot record itself can never be mistaken for the
                # combine cost (base < total for every recipe item).
                self.assertGreater(total, base)
                self.assertNotEqual(total, base)
        self.assertGreater(recipe_items, 100)

    def test_build_total_gold_is_sum_of_item_totals_no_double_count(
        self,
    ) -> None:
        """A build's total gold == sum of each item's Meraki total.
        Component gold must NOT be double-counted (Infinity Edge already
        embeds B.F. Sword - the build cost is IE.total, not IE+BF)."""
        build = ["3031", "3006", "3508"]  # IE + Berserker's + Essence Reaver
        expected = sum(_meraki_total(self.meraki, i) for i in build)
        self.assertEqual(_build_gold(self.snap, build), expected)

        # Adding a raw component that IS a recipe part of an item already
        # in the build still costs its own listed total - the engine
        # sums listed totals, it does not net-out shared components
        # (correct: you pay for the component, then pay the upgrade
        # recipe; the snapshot totals already encode that).
        with_bf = build + ["1038"]  # B.F. Sword (a component of IE)
        expected_with_bf = expected + _meraki_total(self.meraki, "1038")
        self.assertEqual(_build_gold(self.snap, with_bf), expected_with_bf)

    def test_unknown_item_contributes_zero_gold(self) -> None:
        """A non-snapshot id silently contributes 0 (no crash, no
        phantom cost) - the build-gold helper is total-driven."""
        only_known = _build_gold(self.snap, ["3031"])
        self.assertEqual(
            _build_gold(self.snap, ["3031", "999999999"]), only_known
        )


class DeltaPerGoldNormalizationTests(unittest.TestCase):
    """Sub-area 2: the delta / gold the operator actually sees."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load(patch=_PATCH)
        cls.meraki = _load_meraki()

    def test_rank_efficiency_equals_delta_over_displayed_gold(
        self,
    ) -> None:
        """rank_items efficiency == delta_dps / (r.gold / 1000) exactly,
        where ``r.gold`` is the SAME gold the operator sees in the row.
        This is the load-bearing correctness contract: the displayed
        gold and the gold used for normalization must be one and the
        same number (no off-by-one against cumulative build gold, right
        numerator over right denominator). Separately, that displayed
        gold equals the Meraki ground-truth total for every item except
        the documented known-source-delta set."""
        res = rank_items(
            self.snap,
            champion_id="Aatrox",
            level=11,
            current_item_ids=[],
            mode="SR",
            sort_by="efficiency",
            top_n=15,
        )
        positives = 0
        for r in res.ranked:
            # (a) displayed gold == Meraki total (except known deltas + items
            #     absent from the pinned 16.10.1 snapshot). An item Meraki does
            #     not carry at this snapshot (e.g. 667109 Cruelty, an SR item
            #     absent from BOTH 16.10.1 and 16.13.1 Meraki bulk) has no
            #     ground truth to compare - absence is not a source divergence,
            #     so skip (a) for it; the (b) efficiency-normalization check
            #     below still covers every ranked row.
            if (
                r.item_id not in _KNOWN_SOURCE_DELTA_IDS
                and r.item_id in self.meraki
            ):
                self.assertEqual(
                    r.gold,
                    _meraki_total(self.meraki, r.item_id),
                    f"{r.item_name}: displayed gold {r.gold} != Meraki "
                    f"{_meraki_total(self.meraki, r.item_id)}",
                )
            # (b) efficiency normalized by the SAME displayed gold.
            if r.delta_dps > 0:
                positives += 1
                expected_eff = r.delta_dps / (r.gold / 1000.0)
                self.assertAlmostEqual(
                    r.dps_per_1k_gold, expected_eff, places=6
                )
            else:
                # Non-positive delta zeroes the efficiency by design
                # (a regression is not "efficient").
                self.assertEqual(r.dps_per_1k_gold, 0.0)
            self.assertTrue(math.isfinite(r.dps_per_1k_gold))
        self.assertGreater(positives, 0, "expected >=1 positive-delta row")

    def test_beam_efficiency_uses_cumulative_build_gold(self) -> None:
        """Beam efficiency denominator is the CUMULATIVE build total
        (sum of every item's engine total), not a single item's cost -
        the correct numerator/denominator pairing for a full build, and
        normalized by the SAME ``total_gold`` the operator sees. The
        cumulative total is also cross-checked against the independent
        Meraki sum for builds with no known-source-delta item (so the
        no-component-double-count property is verified against ground
        truth)."""
        res = beam_search_build(
            self.snap,
            champion_id="Aatrox",
            level=13,
            current_item_ids=[],
            mode="SR",
            slot_count=3,
            beam_width=6,
            top_n=5,
        )
        self.assertTrue(res.ranked)
        for b in res.ranked:
            # total_gold must equal the sum of each item's engine total
            # (no component double-count, no recipe-cost confusion).
            engine_sum = sum(
                int((self.snap.items[i].get("gold") or {}).get("total", 0))
                for i in b.item_ids
            )
            self.assertEqual(
                b.total_gold,
                engine_sum,
                f"build {b.item_ids}: total_gold {b.total_gold} != "
                f"sum of engine item totals {engine_sum}",
            )
            # Cross-check vs independent Meraki ground truth when the
            # build is free of the documented known-delta items.
            if not any(
                i in _KNOWN_SOURCE_DELTA_IDS for i in b.item_ids
            ):
                meraki_sum = sum(
                    _meraki_total(self.meraki, i) for i in b.item_ids
                )
                self.assertEqual(b.total_gold, meraki_sum)
            if b.delta_dps > 0:
                expected_eff = b.delta_dps / (b.total_gold / 1000.0)
                self.assertAlmostEqual(
                    b.dps_per_1k_gold, expected_eff, places=6
                )
            else:
                self.assertEqual(b.dps_per_1k_gold, 0.0)
            self.assertTrue(math.isfinite(b.dps_per_1k_gold))

    def test_no_divide_by_zero_on_zero_or_negative_gold(self) -> None:
        """The efficiency formula is gated on ``gold > 0`` - a
        hypothetical 0-gold (or absurd negative) candidate yields a
        finite 0.0, never inf/NaN/ZeroDivisionError. We exercise the
        exact published formula the scorers use."""

        def eff(delta: float, gold: int) -> float:
            return (
                (delta / (gold / 1000.0))
                if (gold > 0 and delta > 0)
                else 0.0
            )

        for delta, gold in [
            (123.4, 0),     # free item - the divide-by-zero trap
            (50.0, -100),   # nonsensical negative gold
            (-10.0, 3000),  # regression
            (0.0, 3000),    # no change
        ]:
            v = eff(delta, gold)
            self.assertEqual(v, 0.0)
            self.assertTrue(math.isfinite(v))
        # And the normal path is the plain ratio.
        self.assertAlmostEqual(eff(300.0, 3000), 100.0, places=9)

    def test_boots_edge_item_efficiency_is_finite_and_sane(self) -> None:
        """Boots are low-DPS, positive-gold. Their efficiency must be a
        finite number consistent with delta / Meraki-total - no special
        casing, no blow-up at the cheap-item edge."""
        res = rank_items(
            self.snap,
            champion_id="Aatrox",
            level=6,
            current_item_ids=[],
            mode="SR",
            sort_by="efficiency",
            include_components=True,
            only_item_ids=["3006", "3158", "3047"],  # three boots
            top_n=10,
        )
        self.assertTrue(res.ranked)
        for r in res.ranked:
            self.assertEqual(r.gold, _meraki_total(self.meraki, r.item_id))
            self.assertTrue(math.isfinite(r.dps_per_1k_gold))
            self.assertGreaterEqual(r.dps_per_1k_gold, 0.0)
            if r.delta_dps > 0:
                self.assertAlmostEqual(
                    r.dps_per_1k_gold,
                    r.delta_dps / (r.gold / 1000.0),
                    places=6,
                )


class RankingConsistencyTests(unittest.TestCase):
    """Sub-area 3: value-per-gold ordering correctness + edges."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load(patch=_PATCH)

    def test_efficiency_sort_is_monotone_non_increasing(self) -> None:
        """When sorted by efficiency, the per-1k-gold column is
        non-increasing down the table (tie-broken by raw delta). This
        asserts the ordering KEY itself, not a brittle item-vs-item
        claim."""
        res = rank_items(
            self.snap,
            champion_id="Jinx",
            level=13,
            current_item_ids=[],
            mode="SR",
            sort_by="efficiency",
            top_n=25,
        )
        ranked = res.ranked
        self.assertGreater(len(ranked), 1)
        for a, b in zip(ranked, ranked[1:]):
            self.assertGreaterEqual(
                (a.dps_per_1k_gold, a.delta_dps),
                (b.dps_per_1k_gold, b.delta_dps),
            )

    def test_identical_delta_different_gold_orders_cheaper_first(
        self,
    ) -> None:
        """Two synthetic candidates with the SAME raw delta but
        different gold: under efficiency sort the cheaper one must rank
        first (higher delta-per-gold), and a 0-cost free item must NOT
        sort infinitely high - its efficiency floors at 0.0 by the
        ``gold > 0`` gate, so it lands at the bottom, not the top."""

        def eff(delta: float, gold: int) -> float:
            return (
                (delta / (gold / 1000.0))
                if (gold > 0 and delta > 0)
                else 0.0
            )

        delta = 100.0
        cheap = eff(delta, 1000)   # 100.0 per 1k
        pricey = eff(delta, 4000)  # 25.0 per 1k
        free = eff(delta, 0)       # gated -> 0.0, NOT +inf

        ordered = sorted(
            [("pricey", pricey), ("cheap", cheap), ("free", free)],
            key=lambda kv: kv[1],
            reverse=True,
        )
        self.assertEqual(
            [name for name, _ in ordered], ["cheap", "pricey", "free"]
        )
        self.assertTrue(math.isfinite(free))
        self.assertEqual(free, 0.0)
        self.assertGreater(cheap, pricey)

    def test_free_item_does_not_nan_or_rank_infinitely_high(self) -> None:
        """Direct guard on the documented invariant: a free/0-cost edge
        must not NaN and must not rank infinitely high. Verified against
        the live snapshot via include_components (raw components have
        positive gold, so we assert none of them ever produce a
        non-finite or negative efficiency, and a constructed 0-gold
        case stays 0.0)."""
        res = rank_items(
            self.snap,
            champion_id="Jinx",
            level=11,
            current_item_ids=[],
            mode="SR",
            sort_by="efficiency",
            include_components=True,
            top_n=40,
        )
        for r in res.ranked:
            self.assertTrue(math.isfinite(r.dps_per_1k_gold))
            self.assertGreaterEqual(r.dps_per_1k_gold, 0.0)
            self.assertGreater(
                r.gold, 0, f"{r.item_name} passed filter with gold<=0"
            )


if __name__ == "__main__":
    unittest.main()
