"""DSP11 (1.135.0) - Cluster-B2 kit-axis item-credit seam (dps + burst rankers).

The dps/burst scorers emit a near-fixed generic AD template for every AD
carry/assassin (compute_dps / compute_burst_damage model a generic rotation that
cannot encode a kit's win-axis: Pyke R scales with lethality, Nilah doubles crit,
Ezreal Q + Manamune ramp), so the engine buries the items the player base WINS on
(DSP10 consolidated report's buried winners). The DEFAULT-OFF
``prefer_kit_axis_by_win`` seam reads the WIN-anchored ``kit_axis_item_credit``
table and, when ON: (1) un-strips those items from the ranged-marksman off-class
deny set (Ezreal's hard-excluded Trinity Force), and (2) floats every
positive-delta kit-axis item above the generic template.

Contract (mirrors the DSV1-4 / DSP4-8 seam convention):

* DEFAULT-OFF: ``prefer_kit_axis_by_win=False`` is byte-identical to today
  (``kit_axis_score`` stays 0.0, sort unchanged).
* A champ ABSENT from the table is a no-op even when the flag is ON.
* When ON for a tabled champ, the ranking is PARTITIONED: every surfaced
  kit-axis row (``kit_axis_score==1.0``) precedes every non-axis row, with
  model order preserved within each tier.

Assertions are partition / membership invariants + computed-quantity checks,
NOT fragile absolute cross-item rank pins.
"""
from __future__ import annotations

import unittest

from agents import daemon_slayer
from agents.daemon_slayer import kit_axis_credit
from agents.daemon_slayer.abilities import reset_default_cache
from agents.daemon_slayer.burst import rank_items_by_burst
from agents.daemon_slayer.rank import rank_items
from agents.daemon_slayer.data_loader import DataSnapshot

_LEVEL = 13


def _snap() -> DataSnapshot:
    reset_default_cache()
    kit_axis_credit.reset_cache()
    return DataSnapshot.load()


def _ids(res) -> list[str]:
    return [r.item_id for r in res.ranked]


def _partitioned(res) -> bool:
    """True iff all kit_axis_score==1.0 rows precede all 0.0 rows."""
    seen_zero = False
    for r in res.ranked:
        if r.kit_axis_score <= 0.0:
            seen_zero = True
        elif seen_zero:
            return False
    return True


class TestKitAxisLoader(unittest.TestCase):
    def setUp(self) -> None:
        kit_axis_credit.reset_cache()

    def test_pyke_lethality_ids_and_names(self) -> None:
        ids = kit_axis_credit.kit_axis_item_ids("Pyke")
        names = kit_axis_credit.kit_axis_item_names("Pyke")
        self.assertTrue({"6701", "3142", "6696"} <= ids)  # Opportunity/Youmuu's/Axiom
        self.assertIn("Youmuu's Ghostblade", names)

    def test_nilah_crit_ids(self) -> None:
        ids = kit_axis_credit.kit_axis_item_ids("Nilah")
        self.assertTrue({"3031", "6675"} <= ids)  # Infinity Edge / Navori

    def test_ezreal_manamune_ids(self) -> None:
        ids = kit_axis_credit.kit_axis_item_ids("Ezreal")
        self.assertIn("3078", ids)  # Trinity Force (the hard-stripped staple)

    def test_fresh_db_gate_dropped_anti_justified(self) -> None:
        # 2026-07-13 fresh-DB gate (build_kit_axis_item_credit): a pick is kept
        # only if its CURRENT all-mode rewind WR still clears the champ baseline
        # (off-class un-strip staples keep within a band). The coach-fidelity gate
        # diff (ops/audit/ds_perm_swarm/report/dsp11_gate_diff.md) showed Naafiri
        # (Hubris/Collector at/below base) and Ezreal Essence Reaver (40.9% vs
        # 47.4% base) no longer clear it; Trinity Force (3078) is the staple.
        self.assertEqual(kit_axis_credit.kit_axis_item_ids("Naafiri"), frozenset())
        self.assertNotIn("3508", kit_axis_credit.kit_axis_item_ids("Ezreal"))
        self.assertIn("3078", kit_axis_credit.kit_axis_item_ids("Ezreal"))

    def test_unknown_and_blank_empty(self) -> None:
        self.assertEqual(kit_axis_credit.kit_axis_item_ids("Garen"), frozenset())
        self.assertEqual(kit_axis_credit.kit_axis_item_ids(""), frozenset())
        self.assertEqual(kit_axis_credit.kit_axis_item_names(""), frozenset())


class TestDpsSeam(unittest.TestCase):
    def setUp(self) -> None:
        self.snap = _snap()

    def test_off_is_byte_identical(self) -> None:
        a = rank_items(self.snap, "Nilah", _LEVEL, mode="ARAM", top_n=30)
        b = rank_items(self.snap, "Nilah", _LEVEL, mode="ARAM", top_n=30,
                       prefer_kit_axis_by_win=False)
        self.assertEqual(_ids(a), _ids(b))
        self.assertTrue(all(r.kit_axis_score == 0.0 for r in b.ranked))

    def test_on_floats_kit_axis_items(self) -> None:
        off = rank_items(self.snap, "Nilah", _LEVEL, mode="ARAM", top_n=30)
        on = rank_items(self.snap, "Nilah", _LEVEL, mode="ARAM", top_n=30,
                        prefer_kit_axis_by_win=True)
        self.assertTrue(_partitioned(on))
        surfaced = {r.item_id for r in on.ranked if r.kit_axis_score > 0.0}
        # At least IE (3031) was buried (>top tier) off and surfaces on.
        self.assertIn("3031", surfaced)
        off_top4 = set(_ids(off)[:4])
        self.assertNotIn("3031", off_top4)  # was buried before the seam
        self.assertIn("3031", set(_ids(on)[:4]))  # floated after

    def test_untabled_champ_is_noop(self) -> None:
        off = rank_items(self.snap, "Caitlyn", _LEVEL, mode="ARAM", top_n=20)
        on = rank_items(self.snap, "Caitlyn", _LEVEL, mode="ARAM", top_n=20,
                        prefer_kit_axis_by_win=True)
        self.assertEqual(_ids(off), _ids(on))
        self.assertTrue(all(r.kit_axis_score == 0.0 for r in on.ranked))

    def test_ezreal_trinity_unstripped(self) -> None:
        off = rank_items(self.snap, "Ezreal", _LEVEL, mode="ARAM", top_n=45)
        on = rank_items(self.snap, "Ezreal", _LEVEL, mode="ARAM", top_n=45,
                        prefer_kit_axis_by_win=True)
        self.assertNotIn("3078", _ids(off))   # Trinity hard-stripped off-class
        self.assertIn("3078", _ids(on))       # un-stripped by the seam


class TestBurstSeam(unittest.TestCase):
    def setUp(self) -> None:
        self.snap = _snap()

    def test_off_is_byte_identical(self) -> None:
        a = rank_items_by_burst(self.snap, "Pyke", _LEVEL, mode="ARAM", top_n=30)
        b = rank_items_by_burst(self.snap, "Pyke", _LEVEL, mode="ARAM", top_n=30,
                                prefer_kit_axis_by_win=False)
        self.assertEqual(_ids(a), _ids(b))
        self.assertTrue(all(r.kit_axis_score == 0.0 for r in b.ranked))

    def test_on_floats_kit_axis_items(self) -> None:
        on = rank_items_by_burst(self.snap, "Pyke", _LEVEL, mode="ARAM", top_n=30,
                                 prefer_kit_axis_by_win=True)
        self.assertTrue(_partitioned(on))
        surfaced = {r.item_id for r in on.ranked if r.kit_axis_score > 0.0}
        # Youmuu's (3142) / Axiom Arc (6696) are positive-delta lethality items.
        self.assertTrue({"3142", "6696"} & surfaced)


class TestEnginePin(unittest.TestCase):
    def test_engine_version(self) -> None:
        self.assertEqual(daemon_slayer.ENGINE_VERSION, "1.234.0")


if __name__ == "__main__":
    unittest.main()
