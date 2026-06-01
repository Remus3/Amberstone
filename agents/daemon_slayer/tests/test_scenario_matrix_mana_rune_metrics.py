# arch: tests for scenario_matrix mana_bounded_dps + rune_burst metrics | section=daemon_slayer | frozen=no
"""Tests for the 2 newer ``scenario_matrix`` metrics (item-229-NEXT 2).

``mana_bounded_dps`` and ``rune_burst`` are HARNESS metrics: they reuse the
existing ``mana_sim.compute_mana_bounded_combo`` and
``burst.compute_burst_damage`` scorers respectively. These tests build small
REAL matrices over the live snapshot (Lux = mana champ + in the rune
registry path) and assert:

  * ``VALID_METRICS`` carries both new metrics.
  * a ``mana_bounded_dps`` sweep returns the exact cell count, all finite +
    non-negative, ``metric`` field stamped correctly, and is
    level-monotone-clean through ``check_invariants``.
  * a ``rune_burst`` sweep WITH Electrocute (8112) is >= the same sweep with
    ``runes=None`` for each matched cell (a proc rune ADDS burst).
  * BYTE-IDENTICAL guards: passing ``runes`` to ``metric="burst"`` does not
    change it; passing ``sequence`` to ``metric="dps"`` does not change it.
    (Only ``rune_burst`` consumes ``runes``. ``sequence`` is honored by
    burst/combo/rune_burst/mana_bounded_dps; only ``dps`` ignores it - see
    ``test_scenario_matrix_sequence_honored.py``.)
  * an invalid metric still raises ValueError.
  * ASCII hygiene (0 non-ASCII bytes in the module + this test file).

The single shared ``DataSnapshot.load()`` is threaded into every sweep via
``snapshot=`` so the suite never re-parses the snapshot per call.
"""

from __future__ import annotations

import math
import unittest
from pathlib import Path

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.scenario_matrix import (
    VALID_METRICS,
    check_invariants,
    sweep_scenarios,
)

# Real champion id + items from data/daemon_slayer/<patch>/. Lux is a MANA
# champion (so bounded may differ from unbounded but bounded_dps stays
# finite >= 0) and a clean target for the rune-proc burst layer.
_CHAMP = "Lux"
_ITEMS = ("3020", "3157")  # Sorcerer's Shoes + Zhonya's (AP build)

# Electrocute keystone id (already in the rune_procs registry per item 227).
_ELECTROCUTE = 8112

_SNAP = DataSnapshot.load()


def _matched(cells, level, armor, mr, mode):
    """Return the single cell matching the fixed coordinates (or None)."""
    for c in cells:
        if (c.level == level and c.target_armor == armor
                and c.target_mr == mr and c.mode == mode):
            return c
    return None


class ValidMetricsTests(unittest.TestCase):
    """Both new metrics are registered."""

    def test_mana_bounded_dps_in_valid_metrics(self):
        self.assertIn("mana_bounded_dps", VALID_METRICS)

    def test_rune_burst_in_valid_metrics(self):
        self.assertIn("rune_burst", VALID_METRICS)

    def test_legacy_three_metrics_still_present(self):
        for m in ("dps", "burst", "combo"):
            self.assertIn(m, VALID_METRICS)


class ManaBoundedDpsSweepTests(unittest.TestCase):
    """mana_bounded_dps sweeps a finite, non-negative, stamped grid."""

    def setUp(self):
        self.cells = sweep_scenarios(
            _CHAMP, levels=[9, 14], item_sets=[list(_ITEMS)],
            target_profiles=[(80.0, 60.0)], modes=("SR",),
            metric="mana_bounded_dps", snapshot=_SNAP,
        )

    def test_returns_two_cells(self):
        # 2 levels x 1 item_set x 1 profile x 1 mode.
        self.assertEqual(len(self.cells), 2)

    def test_all_cells_finite(self):
        for c in self.cells:
            self.assertFalse(math.isnan(c.value), msg=c.note)

    def test_all_cells_non_negative(self):
        for c in self.cells:
            self.assertGreaterEqual(c.value, 0.0)

    def test_metric_field_stamped(self):
        for c in self.cells:
            self.assertEqual(c.metric, "mana_bounded_dps")

    def test_level_monotone_no_violation(self):
        viols = check_invariants(self.cells)
        level_viols = [
            v for v in viols
            if v.invariant == "value_non_decreasing_in_level"
        ]
        self.assertEqual(level_viols, [], msg=str(level_viols))

    def test_no_nan_or_negative_violation(self):
        viols = check_invariants(self.cells)
        bad = [v for v in viols if v.invariant in ("no_nan", "no_negative")]
        self.assertEqual(bad, [], msg=str(bad))


class RuneBurstAddsTests(unittest.TestCase):
    """rune_burst WITH a proc rune is >= the no-rune burst per matched cell."""

    def setUp(self):
        self.levels = [9, 14]
        self.profiles = [(80.0, 60.0)]
        self.with_rune = sweep_scenarios(
            _CHAMP, levels=self.levels, item_sets=[list(_ITEMS)],
            target_profiles=self.profiles, modes=("SR",),
            metric="rune_burst", snapshot=_SNAP, runes=[_ELECTROCUTE],
        )
        self.no_rune = sweep_scenarios(
            _CHAMP, levels=self.levels, item_sets=[list(_ITEMS)],
            target_profiles=self.profiles, modes=("SR",),
            metric="rune_burst", snapshot=_SNAP, runes=None,
        )

    def test_same_cell_count(self):
        self.assertEqual(len(self.with_rune), len(self.no_rune))
        self.assertEqual(len(self.with_rune), 2)

    def test_all_finite(self):
        for c in self.with_rune + self.no_rune:
            self.assertFalse(math.isnan(c.value), msg=c.note)

    def test_rune_adds_burst_per_matched_cell(self):
        # Electrocute is on_proc_burst: total >= no-rune total for every cell.
        for lv in self.levels:
            a, m = self.profiles[0]
            wr = _matched(self.with_rune, lv, a, m, "SR")
            nr = _matched(self.no_rune, lv, a, m, "SR")
            self.assertIsNotNone(wr)
            self.assertIsNotNone(nr)
            self.assertGreaterEqual(wr.value + 1e-6, nr.value)


class BurstIgnoresRunesByteIdenticalTests(unittest.TestCase):
    """metric='burst' is byte-identical whether runes is passed or None."""

    def test_burst_with_runes_equals_no_runes(self):
        a = sweep_scenarios(
            _CHAMP, levels=[9, 14], item_sets=[list(_ITEMS)],
            target_profiles=[(80.0, 60.0)], modes=("SR",),
            metric="burst", snapshot=_SNAP, runes=[_ELECTROCUTE],
        )
        b = sweep_scenarios(
            _CHAMP, levels=[9, 14], item_sets=[list(_ITEMS)],
            target_profiles=[(80.0, 60.0)], modes=("SR",),
            metric="burst", snapshot=_SNAP, runes=None,
        )
        self.assertEqual(len(a), len(b))
        for ca, cb in zip(a, b):
            self.assertEqual(ca.level, cb.level)
            self.assertEqual(ca.value, cb.value)


class DpsIgnoresSequenceByteIdenticalTests(unittest.TestCase):
    """metric='dps' is byte-identical whether sequence/runes is passed."""

    def test_dps_with_sequence_equals_none(self):
        a = sweep_scenarios(
            _CHAMP, levels=[9, 14], item_sets=[list(_ITEMS)],
            target_profiles=[(80.0, 60.0)], modes=("SR",),
            metric="dps", snapshot=_SNAP, sequence=["Q", "AA"],
        )
        b = sweep_scenarios(
            _CHAMP, levels=[9, 14], item_sets=[list(_ITEMS)],
            target_profiles=[(80.0, 60.0)], modes=("SR",),
            metric="dps", snapshot=_SNAP,
        )
        self.assertEqual(len(a), len(b))
        for ca, cb in zip(a, b):
            self.assertEqual(ca.level, cb.level)
            self.assertEqual(ca.value, cb.value)


class InvalidMetricTests(unittest.TestCase):
    """An unknown metric still raises ValueError (gate unchanged)."""

    def test_bogus_metric_raises(self):
        with self.assertRaises(ValueError):
            sweep_scenarios(
                _CHAMP, levels=[9], item_sets=[list(_ITEMS)],
                target_profiles=[(80.0, 60.0)], modes=("SR",),
                metric="bogus", snapshot=_SNAP,
            )


class AsciiHygieneTests(unittest.TestCase):
    """The module + this test file are pure ASCII."""

    def _assert_ascii(self, rel: str):
        path = Path(__file__).resolve().parents[1] / rel
        data = path.read_bytes()
        bad = [(i, b) for i, b in enumerate(data) if b > 0x7F]
        self.assertEqual(bad, [], msg=f"{rel} has non-ASCII bytes: {bad[:5]}")

    def test_scenario_matrix_module_ascii(self):
        self._assert_ascii("scenario_matrix.py")

    def test_this_test_file_ascii(self):
        path = Path(__file__).resolve()
        data = path.read_bytes()
        bad = [(i, b) for i, b in enumerate(data) if b > 0x7F]
        self.assertEqual(bad, [], msg=f"test file has non-ASCII bytes: {bad[:5]}")


if __name__ == "__main__":
    unittest.main()
