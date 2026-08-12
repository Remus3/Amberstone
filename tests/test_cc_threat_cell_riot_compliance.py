"""CC threat cell - the Riot-compliant replacement for the cooldown-window cell.

Riot compliance 2026-08-11. The v4 laning precompute used to carry a
``cooldown_window`` block built from ``agents.daemon_slayer.cooldown_watch``:
it named an enemy ability and shipped that ability's base COOLDOWN in seconds,
which the precomputed laning coach then rendered as "their Q cd ~20s". Riot's
third-party rules ban tracking enemy ability cooldowns, so the join, its route
and the number were removed.

This suite pins the rebuild. The cell keeps the useful half - WHICH enemy
ability is the threat and HOW LONG its crowd control lasts, both of which are
static kit facts the game client already shows in its own champion tooltips -
and carries no cooldown scalar for the enemy at any point. MY OWN ultimate
cooldown stays: it is the operator's own ability, not an opponent's.

See docs/OVERLAY_COMPLIANCE_PLAN.md.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from core import laning_scenario_precompute as lsp  # noqa: E402
from core import precomputed_laning_coach as plc  # noqa: E402


class CcThreatVerdictTests(unittest.TestCase):
    """The pure verdict function - no engine, deterministic, fail-soft."""

    def test_no_ult_is_wait_cd(self) -> None:
        self.assertEqual(lsp.cc_threat_verdict(1.25, 130.0, "no_ult"), "wait_cd")
        self.assertEqual(lsp.cc_threat_verdict(0.0, 0.0, "no_ult"), "wait_cd")

    def test_punish_when_ult_up_and_enemy_has_cc(self) -> None:
        self.assertEqual(lsp.cc_threat_verdict(1.25, 130.0, "all_up"), "punish_now")

    def test_even_when_enemy_has_no_cc(self) -> None:
        self.assertEqual(lsp.cc_threat_verdict(0.0, 130.0, "all_up"), "even")

    def test_malformed_input_fails_soft_to_even(self) -> None:
        self.assertEqual(lsp.cc_threat_verdict("nope", 130.0, "all_up"), "even")
        self.assertEqual(lsp.cc_threat_verdict(None, 130.0, "all_up"), "even")


class CcThreatCellShapeTests(unittest.TestCase):
    """The emitted block carries CC duration, never an enemy cooldown."""

    def _cell(self):
        return lsp.cc_threat_cell(
            None, "Ahri", 9, (), "all_up", "SR",
            lsp._enemy_cc_threat_card("Leona"),
        )

    def test_block_has_no_enemy_cooldown_key(self) -> None:
        cell = self._cell()
        self.assertNotIn("enemy_cd_s", cell)
        for key in cell:
            self.assertFalse(
                key.startswith("enemy_") and key.endswith("_cd_s"),
                f"{key} reintroduces an enemy cooldown scalar",
            )

    def test_block_carries_cc_duration_and_threat_spell(self) -> None:
        cell = self._cell()
        self.assertIn("enemy_cc_s", cell)
        self.assertIn("enemy_threat_spell", cell)
        self.assertIn("threat_verdict", cell)
        # Leona is a hard-CC champion in every registry RC ships, so a zero
        # here means the CC lookup silently degraded, not that Leona changed.
        self.assertGreater(float(cell["enemy_cc_s"]), 0.0)

    def test_my_own_ult_cooldown_is_still_carried(self) -> None:
        # Riot bans ENEMY cooldown tracking. The operator's own ult cooldown is
        # not an opponent's data and stays - it is half the window decision.
        self.assertIn("my_ult_cd_s", self._cell())

    def test_unknown_enemy_degrades_to_even_without_raising(self) -> None:
        cell = lsp.cc_threat_cell(
            None, "Ahri", 9, (), "all_up", "SR",
            lsp._enemy_cc_threat_card("NotAChampion"),
        )
        self.assertEqual(cell["threat_verdict"], "even")
        self.assertEqual(float(cell["enemy_cc_s"]), 0.0)


class CoachChipCarriesNoCooldownTests(unittest.TestCase):
    """The rendered coaching chip must not state an enemy cooldown."""

    def test_chip_text_has_no_enemy_cooldown_seconds(self) -> None:
        cell = {"cc_threat": {
            "enemy_threat_spell": "Q",
            "enemy_cc_s": 1.25,
            "my_ult_cd_s": 130.0,
            "threat_verdict": "punish_now",
        }}
        chip = plc._threat_chip(cell, "trade")
        self.assertIsNotNone(chip)
        text = f"{chip.label} {chip.expected_outcome}".lower()
        self.assertNotIn(" cd ", text)
        self.assertNotIn("cooldown", text)

    def test_v3_cell_without_the_block_emits_nothing(self) -> None:
        self.assertIsNone(plc._threat_chip({}, "trade"))


if __name__ == "__main__":
    unittest.main()
