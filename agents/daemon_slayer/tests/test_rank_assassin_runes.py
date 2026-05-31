"""DS V2 S3 wire: optional runes into rank_items_by_burst + /rank-assassin.

Version-agnostic. The runes layer is ADDITIVE: when runes is None/empty the
ranking is BYTE-IDENTICAL to the no-runes call (the None path of
compute_burst_damage is unchanged since S3). When runes are passed, every
build's burst gains the rune-proc layer, so per-candidate burst rises but the
delta still isolates the item gain.

Uses an EXISTING registry rune (8112 Electrocute, proc_type=on_proc_burst) so
this slice is independent of any rune-registry expansion. Loads the live
DataSnapshot once.
"""

from __future__ import annotations

import unittest

from agents.daemon_slayer.burst import rank_items_by_burst
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.server import _CACHE, _route_rank_assassin

# Electrocute - an existing on_proc_burst rune; contributes to burst totals.
_ELECTROCUTE = 8112

# Assassin candidates; the first that resolves is used.
_ASSASSIN_CANDIDATES = ("Zed", "Talon", "Qiyana")


def _resolve_assassin(snap: DataSnapshot) -> str:
    """First assassin champ id that resolves a non-empty baseline ranking."""
    for champ in _ASSASSIN_CANDIDATES:
        try:
            r = rank_items_by_burst(snap, champ, 11, top_n=5)
        except (KeyError, ValueError):
            continue
        if r.ranked:
            return champ
    raise unittest.SkipTest(
        f"no assassin from {_ASSASSIN_CANDIDATES} resolved a ranking"
    )


class RankAssassinRunesByteIdenticalTests(unittest.TestCase):
    """runes=None (and default) must reproduce the no-runes ranking exactly."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()
        cls.champ = _resolve_assassin(cls.snap)

    def test_runes_none_is_byte_identical_to_default(self) -> None:
        # No runes kwarg at all (defaults to None).
        base = rank_items_by_burst(self.snap, self.champ, 11, top_n=10)
        # Explicit runes=None.
        none = rank_items_by_burst(self.snap, self.champ, 11, top_n=10, runes=None)
        base_ids = [ri.item_id for ri in base.ranked]
        none_ids = [ri.item_id for ri in none.ranked]
        self.assertEqual(base_ids, none_ids)
        self.assertEqual(len(base_ids), len(none_ids))
        for rb, rn in zip(base.ranked, none.ranked):
            self.assertEqual(rb.item_id, rn.item_id)
            self.assertAlmostEqual(rb.delta_burst, rn.delta_burst, places=6)
            self.assertAlmostEqual(rb.new_burst, rn.new_burst, places=6)
        self.assertAlmostEqual(
            base.baseline_burst, none.baseline_burst, places=6
        )

    def test_empty_runes_list_is_byte_identical(self) -> None:
        base = rank_items_by_burst(self.snap, self.champ, 11, top_n=10)
        empty = rank_items_by_burst(self.snap, self.champ, 11, top_n=10, runes=[])
        self.assertEqual(
            [ri.item_id for ri in base.ranked],
            [ri.item_id for ri in empty.ranked],
        )
        for rb, re in zip(base.ranked, empty.ranked):
            self.assertAlmostEqual(rb.delta_burst, re.delta_burst, places=6)


class RankAssassinRunesRerankSaneTests(unittest.TestCase):
    """runes=[8112] must produce a sane, finite ranking of the same length."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()
        cls.champ = _resolve_assassin(cls.snap)

    def test_runes_list_is_finite_and_same_length(self) -> None:
        base = rank_items_by_burst(self.snap, self.champ, 11, top_n=10)
        runed = rank_items_by_burst(
            self.snap, self.champ, 11, top_n=10, runes=[_ELECTROCUTE]
        )
        self.assertGreater(len(runed.ranked), 0)
        # Same top-N length (rune layer scales both baseline + candidates).
        self.assertEqual(len(base.ranked), len(runed.ranked))
        for ri in runed.ranked:
            self.assertTrue(
                ri.delta_burst == ri.delta_burst,  # not NaN
                f"delta_burst is NaN for {ri.item_id}",
            )
            self.assertTrue(
                ri.new_burst == ri.new_burst,  # not NaN
                f"new_burst is NaN for {ri.item_id}",
            )
            self.assertNotEqual(ri.new_burst, float("inf"))

    def test_electrocute_raises_per_candidate_burst(self) -> None:
        # Electrocute (on_proc_burst) adds to every build's burst, so the
        # top candidate's new_burst with runes >= without runes.
        base = rank_items_by_burst(self.snap, self.champ, 11, top_n=10)
        runed = rank_items_by_burst(
            self.snap, self.champ, 11, top_n=10, runes=[_ELECTROCUTE]
        )
        # Compare the per-candidate burst for the SAME top item if present.
        base_by_id = {ri.item_id: ri.new_burst for ri in base.ranked}
        bumped = False
        for ri in runed.ranked:
            if ri.item_id in base_by_id:
                self.assertGreaterEqual(ri.new_burst, base_by_id[ri.item_id])
                if ri.new_burst > base_by_id[ri.item_id]:
                    bumped = True
        # At least one shared candidate must show the rune-proc uplift.
        self.assertTrue(
            bumped, "Electrocute did not raise any shared candidate's burst"
        )


class RankAssassinRunesRouteTests(unittest.TestCase):
    """/rank-assassin route accepts an optional runes field, byte-identical."""

    @classmethod
    def setUpClass(cls) -> None:
        # Prime the module-level snapshot cache the route reads from.
        cls.snap = DataSnapshot.load()
        _CACHE.set(cls.snap)

    def test_route_no_runes_returns_ok_shape(self) -> None:
        out = _route_rank_assassin({"champion": "Zed", "level": 11})
        self.assertIsInstance(out, dict)
        self.assertIn("ranked", out)
        self.assertIsInstance(out["ranked"], list)

    def test_route_with_runes_returns_ok_shape(self) -> None:
        out = _route_rank_assassin(
            {"champion": "Zed", "level": 11, "runes": [_ELECTROCUTE]}
        )
        self.assertIsInstance(out, dict)
        self.assertIn("ranked", out)

    def test_route_no_runes_equals_byte_identical_baseline(self) -> None:
        # No runes key vs the direct rank_items_by_burst with runes=None.
        out = _route_rank_assassin({"champion": "Zed", "level": 11})
        direct = rank_items_by_burst(
            self.snap, "Zed", 11, current_item_ids=[], mode="SR",
            top_n=20, sort_by="delta", runes=None,
        )
        route_ids = [r["item_id"] for r in out["ranked"]]
        direct_ids = [ri.item_id for ri in direct.ranked]
        self.assertEqual(route_ids, direct_ids)

    def test_route_runes_string_form_accepted(self) -> None:
        # Comma string + junk ids: junk dropped, valid id kept, no crash.
        out = _route_rank_assassin(
            {"champion": "Zed", "level": 11, "runes": "8112,notanid"}
        )
        self.assertIsInstance(out, dict)
        self.assertIn("ranked", out)


class AsciiHygieneTests(unittest.TestCase):
    def test_test_file_is_ascii(self) -> None:
        with open(__file__, "rb") as fh:
            data = fh.read()
        for i, b in enumerate(data):
            self.assertLess(b, 128, f"non-ASCII byte {b} at offset {i}")


if __name__ == "__main__":
    unittest.main()
