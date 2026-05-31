# arch: tests for the cross-interaction scenario matrix + invariant checker | section=daemon_slayer | frozen=no
"""Tests for ``agents.daemon_slayer.scenario_matrix``.

Builds small REAL matrices over the live 16.11.1 snapshot (Caitlyn =
pure-AD marksman, Brand = pure-AP mage) and asserts:

  * ``sweep_scenarios`` returns exactly the cross-product cell count, all
    finite + non-negative for a real champion.
  * ``check_invariants`` finds 0 violations on a clean real sweep (Caitlyn
    armor-monotone dps + level-monotone; Brand MR-monotone burst).
  * A hand-built cells list that VIOLATES the level invariant is flagged
    with the right invariant name + offending cells (proves non-no-op).
  * Fail-soft: a sweep over an unknown champion records NaN cells + notes
    and does not raise.
  * ASCII hygiene (0 non-ASCII bytes in the module + this test file).
"""

from __future__ import annotations

import math
import unittest
from pathlib import Path

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.scenario_matrix import (
    InvariantViolation,
    ScenarioCell,
    check_invariants,
    sweep_scenarios,
)

# Real champion ids from data/daemon_slayer/16.11.1/champions.json.
_AD_CHAMP = "Caitlyn"   # tags ["Marksman"] - pure-AD auto-attacker
_AP_CHAMP = "Brand"     # pure-AP mage - ability burst is MR-gated

# Real item ids (str): 3031 Infinity Edge (AD), 6655 Luden's Companion (AP).
_AD_ITEMS = ("3031",)
_AD_ITEMS_2 = ("3031", "3094")  # + Rapid Firecannon
_AP_ITEMS = ("6655",)

_SNAP = DataSnapshot.load()


class SweepShapeTests(unittest.TestCase):
    """sweep_scenarios returns the exact cross-product, all finite."""

    def test_cell_count_is_product_of_dims(self):
        levels = (6, 11, 16)
        item_sets = (_AD_ITEMS, _AD_ITEMS_2)
        profiles = ((50.0, 0.0), (100.0, 0.0), (200.0, 0.0))
        cells = sweep_scenarios(
            _AD_CHAMP, levels, item_sets, profiles,
            modes=("SR",), metric="dps", snapshot=_SNAP,
        )
        # 3 levels x 2 item sets x 3 profiles x 1 mode = 18.
        self.assertEqual(len(cells), 3 * 2 * 3 * 1)

    def test_all_values_finite_and_non_negative(self):
        cells = sweep_scenarios(
            _AD_CHAMP, (6, 11, 16), (_AD_ITEMS,),
            ((50.0, 0.0), (100.0, 0.0), (200.0, 0.0)),
            modes=("SR",), metric="dps", snapshot=_SNAP,
        )
        for c in cells:
            self.assertFalse(math.isnan(c.value), f"NaN at {c}")
            self.assertGreaterEqual(c.value, 0.0, f"negative at {c}")
            self.assertEqual(c.note, "")

    def test_cells_carry_their_dimensions(self):
        cells = sweep_scenarios(
            _AD_CHAMP, (11,), (_AD_ITEMS,), ((100.0, 30.0),),
            modes=("SR",), metric="dps", snapshot=_SNAP,
        )
        self.assertEqual(len(cells), 1)
        c = cells[0]
        self.assertEqual(c.champion, _AD_CHAMP)
        self.assertEqual(c.level, 11)
        self.assertEqual(c.item_ids, _AD_ITEMS)
        self.assertEqual(c.target_armor, 100.0)
        self.assertEqual(c.target_mr, 30.0)
        self.assertEqual(c.mode, "SR")
        self.assertEqual(c.metric, "dps")

    def test_two_tuple_profile_defaults_hp_to_zero(self):
        # A 2-wide profile must work the same as a 4-wide with trailing 0s.
        cells = sweep_scenarios(
            _AD_CHAMP, (11,), (_AD_ITEMS,), ((80.0, 50.0),),
            modes=("SR",), metric="dps", snapshot=_SNAP,
        )
        self.assertEqual(cells[0].target_armor, 80.0)
        self.assertEqual(cells[0].target_mr, 50.0)

    def test_invalid_metric_raises(self):
        with self.assertRaises(ValueError):
            sweep_scenarios(
                _AD_CHAMP, (11,), (_AD_ITEMS,), ((80.0, 50.0),),
                metric="nonsense", snapshot=_SNAP,
            )


class CaitlynPhysicalInvariantTests(unittest.TestCase):
    """Pure-AD Caitlyn: dps non-increasing in armor + non-decreasing in level."""

    def setUp(self):
        self.cells = sweep_scenarios(
            _AD_CHAMP, (6, 11, 16), (_AD_ITEMS, _AD_ITEMS_2),
            ((50.0, 0.0), (100.0, 0.0), (200.0, 0.0)),
            modes=("SR",), metric="dps", snapshot=_SNAP,
        )

    def test_zero_violations(self):
        v = check_invariants(self.cells, ad_champions=[_AD_CHAMP])
        self.assertEqual(v, [], f"unexpected violations: {[x.invariant for x in v]}")

    def test_dps_strictly_drops_as_armor_rises(self):
        # Pin the directional truth the invariant relies on at L11 IE-only.
        by_armor = {
            c.target_armor: c.value
            for c in self.cells
            if c.level == 11 and c.item_ids == _AD_ITEMS
        }
        self.assertGreater(by_armor[50.0], by_armor[100.0])
        self.assertGreater(by_armor[100.0], by_armor[200.0])

    def test_dps_rises_with_level(self):
        by_level = {
            c.level: c.value
            for c in self.cells
            if c.target_armor == 100.0 and c.item_ids == _AD_ITEMS
        }
        self.assertLess(by_level[6], by_level[11])
        self.assertLess(by_level[11], by_level[16])


class BrandMagicInvariantTests(unittest.TestCase):
    """Pure-AP Brand: burst (ability dmg) non-increasing in MR, 0 violations."""

    def setUp(self):
        self.cells = sweep_scenarios(
            _AP_CHAMP, (6, 11, 16), (_AP_ITEMS,),
            ((0.0, 30.0), (0.0, 80.0), (0.0, 200.0)),
            modes=("SR",), metric="burst", snapshot=_SNAP,
        )

    def test_zero_violations(self):
        v = check_invariants(self.cells, ap_champions=[_AP_CHAMP])
        self.assertEqual(v, [], f"unexpected violations: {[x.invariant for x in v]}")

    def test_burst_drops_as_mr_rises(self):
        by_mr = {
            c.target_mr: c.value
            for c in self.cells
            if c.level == 16
        }
        self.assertGreater(by_mr[30.0], by_mr[80.0])
        self.assertGreater(by_mr[80.0], by_mr[200.0])


class CheckerCatchesViolationTests(unittest.TestCase):
    """Hand-built cells that BREAK an invariant must be flagged (non-no-op)."""

    def _cell(self, level, value, armor=100.0, mr=0.0, mode="SR", metric="dps"):
        return ScenarioCell(
            champion="Caitlyn", level=level, item_ids=("3031",),
            target_armor=armor, target_mr=mr, mode=mode, metric=metric,
            value=value,
        )

    def test_level_decrease_is_flagged(self):
        # dps DROPS as level rises (16 < 11) - violates invariant 3.
        cells = [
            self._cell(6, 40.0),
            self._cell(11, 60.0),
            self._cell(16, 30.0),  # broken: should be >= 60.0
        ]
        violations = check_invariants(cells, ad_champions=["Caitlyn"])
        names = {v.invariant for v in violations}
        self.assertIn("value_non_decreasing_in_level", names)
        offending = [
            v for v in violations
            if v.invariant == "value_non_decreasing_in_level"
        ]
        self.assertEqual(len(offending), 1)
        # The offending pair is the L11 -> L16 reversal.
        pair = offending[0].cells
        self.assertEqual(pair[0].level, 11)
        self.assertEqual(pair[1].level, 16)

    def test_clean_level_curve_not_flagged(self):
        cells = [self._cell(6, 40.0), self._cell(11, 60.0), self._cell(16, 70.0)]
        v = check_invariants(cells, ad_champions=["Caitlyn"])
        self.assertEqual(v, [])

    def test_armor_increase_is_flagged(self):
        # dps RISES as armor rises - violates invariant 1.
        cells = [
            self._cell(11, 50.0, armor=50.0),
            self._cell(11, 80.0, armor=200.0),  # broken: should be <= 50.0
        ]
        violations = check_invariants(cells, ad_champions=["Caitlyn"])
        names = {v.invariant for v in violations}
        self.assertIn("dps_non_increasing_in_armor", names)

    def test_negative_value_is_flagged(self):
        cells = [self._cell(11, -5.0)]
        violations = check_invariants(cells)
        self.assertIn("no_negative", {v.invariant for v in violations})

    def test_nan_value_is_flagged(self):
        cells = [self._cell(11, float("nan"))]
        violations = check_invariants(cells)
        self.assertIn("no_nan", {v.invariant for v in violations})

    def test_nan_cell_does_not_fail_ordering_invariant(self):
        # A NaN at L16 must NOT count as a level-monotone break (it trips
        # no_nan instead). The L6->L11 pair stays clean.
        cells = [self._cell(6, 40.0), self._cell(11, 60.0), self._cell(16, float("nan"))]
        violations = check_invariants(cells, ad_champions=["Caitlyn"])
        names = [v.invariant for v in violations]
        self.assertIn("no_nan", names)
        self.assertNotIn("value_non_decreasing_in_level", names)

    def test_violation_is_dataclass(self):
        cells = [self._cell(11, -1.0)]
        v = check_invariants(cells)
        self.assertTrue(all(isinstance(x, InvariantViolation) for x in v))
        self.assertTrue(all(isinstance(c, ScenarioCell) for x in v for c in x.cells))


class FailSoftTests(unittest.TestCase):
    """Unknown champion records NaN cells + notes; the sweep never raises."""

    def test_unknown_champion_records_nan_no_raise(self):
        cells = sweep_scenarios(
            "NotARealChampion", (6, 11), (_AD_ITEMS,),
            ((50.0, 0.0), (100.0, 0.0)),
            modes=("SR",), metric="dps", snapshot=_SNAP,
        )
        # 2 levels x 1 set x 2 profiles x 1 mode = 4 cells, all NaN + noted.
        self.assertEqual(len(cells), 4)
        for c in cells:
            self.assertTrue(math.isnan(c.value))
            self.assertNotEqual(c.note, "")

    def test_unknown_champion_trips_no_nan_invariant(self):
        cells = sweep_scenarios(
            "NotARealChampion", (6,), (_AD_ITEMS,), ((50.0, 0.0),),
            metric="dps", snapshot=_SNAP,
        )
        v = check_invariants(cells)
        self.assertIn("no_nan", {x.invariant for x in v})

    def test_empty_levels_yields_no_cells(self):
        cells = sweep_scenarios(
            _AD_CHAMP, (), (_AD_ITEMS,), ((50.0, 0.0),),
            metric="dps", snapshot=_SNAP,
        )
        self.assertEqual(cells, [])

    def test_combo_metric_runs_real_champion(self):
        # metric="combo" must dispatch through compute_combo (fully
        # fail-soft itself) and produce finite non-negative cells.
        cells = sweep_scenarios(
            _AP_CHAMP, (11, 16), (_AP_ITEMS,),
            ((30.0, 30.0), (80.0, 80.0)),
            modes=("SR",), metric="combo", snapshot=_SNAP,
        )
        self.assertEqual(len(cells), 4)
        for c in cells:
            self.assertFalse(math.isnan(c.value))
            self.assertGreaterEqual(c.value, 0.0)


class ModeConsistencyTests(unittest.TestCase):
    """Invariant 5: SR vs ARAM differ by a scalar, not a sign / NaN split."""

    def test_sr_vs_aram_same_sign_no_violation(self):
        cells = sweep_scenarios(
            _AD_CHAMP, (11,), (_AD_ITEMS,), ((100.0, 0.0),),
            modes=("SR", "ARAM"), metric="dps", snapshot=_SNAP,
        )
        self.assertEqual(len(cells), 2)
        v = check_invariants(cells, ad_champions=[_AD_CHAMP])
        self.assertNotIn(
            "mode_multiplier_consistency", {x.invariant for x in v}
        )

    def test_sign_flip_across_modes_is_flagged(self):
        sr = ScenarioCell(
            champion="Caitlyn", level=11, item_ids=("3031",),
            target_armor=100.0, target_mr=0.0, mode="SR", metric="dps",
            value=50.0,
        )
        aram = ScenarioCell(
            champion="Caitlyn", level=11, item_ids=("3031",),
            target_armor=100.0, target_mr=0.0, mode="ARAM", metric="dps",
            value=-50.0,  # impossible sign flip
        )
        v = check_invariants([sr, aram])
        self.assertIn(
            "mode_multiplier_consistency", {x.invariant for x in v}
        )


class AsciiHygieneTests(unittest.TestCase):
    """The module + this test file carry zero non-ASCII bytes."""

    def test_module_is_ascii(self):
        p = Path(__file__).resolve().parent.parent / "scenario_matrix.py"
        raw = p.read_bytes()
        bad = [b for b in raw if b > 0x7F]
        self.assertEqual(bad, [], "scenario_matrix.py has non-ASCII bytes")

    def test_test_file_is_ascii(self):
        raw = Path(__file__).resolve().read_bytes()
        bad = [b for b in raw if b > 0x7F]
        self.assertEqual(bad, [], "test file has non-ASCII bytes")


if __name__ == "__main__":
    unittest.main()
