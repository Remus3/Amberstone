"""Tests for the HZ-A2 economy verdict (recall/back-timing + power-spike-ETA)
layered onto core.laning_scenario_precompute. The economy block is gold-income +
item-completion driven (reusing core.lead_projection) and is pure - no engine,
no snapshot. A handful of engine-backed tests confirm the block is embedded in
real cells alongside the HZ-A1 verdict + the v2 schema bump.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import core.laning_scenario_precompute as lsp  # noqa: E402
from core import lead_projection as lp  # noqa: E402


class EconomyCellPureTests(unittest.TestCase):
    """economy_cell is a pure (band, mana, verdict, mode, manaless) -> dict."""

    def _eco(self, band="L6", mana="full", mode="SR", manaless=False):
        return lsp.economy_cell(band, mana, mode=mode, manaless=manaless)

    def test_economy_cell_keys(self):
        # Slim v3 drops the intermediate spike_eta_s from the persisted block.
        self.assertEqual(
            set(self._eco()),
            {"recall", "next_spike", "gold_at_band"},
        )

    def test_recall_in_valid_set_across_grid(self):
        for band in lsp.LEVEL_BANDS:
            for mana in lsp.MANA_STATES:
                for manaless in (False, True):
                    eco = self._eco(band=band, mana=mana, manaless=manaless)
                    self.assertIn(eco["recall"], lsp.VALID_RECALLS)

    def test_gold_at_band_tracks_lead_projection(self):
        minutes = lp.minutes_for_level(lsp.level_for_band("L6"))
        self.assertEqual(
            self._eco(band="L6", mode="SR")["gold_at_band"],
            lsp._round(lp.expected_gold_earned(minutes, "SR")),
        )

    def test_gold_at_band_strictly_increases_with_band(self):
        golds = [self._eco(band=b)["gold_at_band"] for b in ("L2", "L6", "L11", "L16")]
        self.assertEqual(golds, sorted(golds))
        self.assertEqual(len(set(golds)), len(golds))

    def test_next_spike_label_is_valid(self):
        valid = {label for label, _ in lp.spike_ladder()} | {lp.SPIKE_COMPLETE}
        for band in lsp.LEVEL_BANDS:
            self.assertIn(self._eco(band=band)["next_spike"], valid)

    def test_low_mana_mana_champ_recalls(self):
        # a mana champ on its low-mana combo (not manaless) with gold to back
        # -> recall to reset resources. L2 isolates the forcing path (the gold
        # there is below a completed item, so only the OOM rule can fire it).
        self.assertEqual(
            self._eco(band="L2", mana="low", manaless=False)["recall"], "recall_now"
        )

    def test_low_mana_manaless_champ_not_forced_to_recall(self):
        # a manaless champ's "low" cell is NOT resource-starved; at L2 (sub-item
        # gold, imminent first spike) that reads back_soon, not recall_now.
        self.assertNotEqual(
            self._eco(band="L2", mana="low", manaless=True)["recall"], "recall_now"
        )

    def test_unspent_item_gold_recalls(self):
        # L6 (~min 10, ~4500 gold): past a completed item with the next spike far
        # off -> sitting on unspent power gold -> recall_now to buy it.
        self.assertEqual(self._eco(band="L6", mana="full")["recall"], "recall_now")

    def test_imminent_spike_reads_back_soon(self):
        # L2 (~ minute 2): no completed-item gold yet, but the first component
        # spike is within the back-soon window -> back_soon.
        self.assertEqual(self._eco(band="L2", mana="full")["recall"], "back_soon")

    def test_complete_build_phase_holds(self):
        # L16 (~min 30): the spike ladder is complete -> no item to back for, hold.
        self.assertEqual(self._eco(band="L16", mana="full")["recall"], "hold")

    def test_recall_varies_across_grid(self):
        seen = {
            self._eco(band=band, mana=mana, manaless=manaless)["recall"]
            for band in lsp.LEVEL_BANDS
            for mana in lsp.MANA_STATES
            for manaless in (False, True)
        }
        # all three recall states are reachable across the grid.
        self.assertEqual(seen, set(lsp.RECALL_STATES))

    def test_economy_cell_serializes_ascii(self):
        json.dumps(self._eco(), ensure_ascii=True).encode("ascii")


class EconomyIntegrationTests(unittest.TestCase):
    """The economy block is embedded in real engine cells + the v2 schema."""

    @classmethod
    def setUpClass(cls):
        from agents.daemon_slayer.data_loader import DataSnapshot
        cls.snap = DataSnapshot.load()

    def test_compute_cell_carries_economy_and_keeps_hz_a1_fields(self):
        cell = lsp.compute_cell(
            self.snap, "Garen", "Darius", "L6", "full", "all_up", mode="SR"
        )
        self.assertIn("economy", cell)
        self.assertIn(cell["economy"]["recall"], lsp.VALID_RECALLS)
        # HZ-A1 leaf fields are untouched.
        self.assertIn(cell["verdict"], lsp.VALID_VERDICTS)
        # Slim v3 drops the redundant per-cell sequence array.
        self.assertNotIn("sequence", cell)

    def test_generate_table_schema_v3_and_economy_dimensions(self):
        payload = lsp.generate_table(
            self.snap, ["Garen"], ["Darius"], mode="SR", bands=["L6"]
        )
        self.assertEqual(payload["schema"], "laning_scenarios/v3")
        eco_dim = payload["dimensions"]["economy"]
        self.assertIn("income_per_min", eco_dim)
        self.assertIn("spike_ladder", eco_dim)
        leaf = payload["scenarios"]["Garen"]["Darius"]["L6"]["full"]["all_up"]
        self.assertIn("economy", leaf)

    def test_generated_table_serializes_ascii(self):
        payload = lsp.generate_table(
            self.snap, ["Garen"], ["Darius"], mode="SR", bands=["L6"]
        )
        json.dumps(payload, ensure_ascii=True).encode("ascii")


if __name__ == "__main__":
    unittest.main()
