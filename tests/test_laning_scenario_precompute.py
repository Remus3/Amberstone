"""Tests for core.laning_scenario_precompute - the Lane A laning-scenario
precompute (HZ-A1). Characterization vs DS math: the precomputed cell verdict +
net_swing must equal a live ``agents.daemon_slayer.matchup.compute_matchup`` call
for the same (champ, enemy, level, sequence). Pure-helper + persist + reader
round-trip tests need no engine.

The engine-backed tests load a single shared DataSnapshot (mirrors
tests/test_pickban_targets.py). They use canonical DDragon ids that resolve in
the shipped data set (Garen = manaless, Annie = mana, Darius / Ahri laners).
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import core.laning_scenario_precompute as lsp  # noqa: E402


class PureHelperTests(unittest.TestCase):
    """Dimension helpers + constants - no engine, no snapshot."""

    def test_combo_sequence_all_up_has_ult(self) -> None:
        seq = lsp.combo_sequence("all_up")
        self.assertEqual(seq, ("Q", "W", "E", "R"))
        self.assertIn("R", seq)

    def test_combo_sequence_no_ult_drops_r(self) -> None:
        seq = lsp.combo_sequence("no_ult")
        self.assertNotIn("R", seq)
        self.assertEqual(seq, ("Q", "W", "E"))

    def test_combo_sequence_unknown_cd_state_falls_back_full(self) -> None:
        # An unrecognized cd_state degrades to the full rotation (fail-soft).
        self.assertEqual(lsp.combo_sequence("bogus"), ("Q", "W", "E", "R"))

    def test_dimension_constants(self) -> None:
        self.assertEqual(lsp.MANA_STATES, ("full", "low"))
        self.assertEqual(lsp.CD_STATES, ("all_up", "no_ult"))
        self.assertEqual(
            set(lsp.VALID_VERDICTS), {"all_in", "trade", "back_off", "even"}
        )

    def test_level_for_band_maps_known_bands(self) -> None:
        for band, level in lsp.LEVEL_BANDS.items():
            self.assertEqual(lsp.level_for_band(band), level)
            self.assertIsInstance(level, int)

    def test_round_is_stable(self) -> None:
        self.assertEqual(lsp._round(0.123456), lsp._round(0.123456))
        self.assertEqual(lsp._round(0.123456), 0.1235)


class PersistAndReaderTests(unittest.TestCase):
    """atomic_write round-trips ASCII JSON; lookup navigates the nesting;
    a missing DB fails soft to {}/{}."""

    def _payload(self) -> dict:
        cell = {
            "verdict": "trade", "net_swing": 0.2, "pct_my_removed": 0.1,
            "pct_enemy_removed": 0.3, "my_can_full_combo": True,
            "sequence": ["Q", "W", "E", "R"], "manaless": False,
        }
        return {
            "version": "16.11.1", "generated_at": "2026-06-08T00:00:00Z",
            "mode": "sr", "schema": "laning_scenarios/v1",
            "scenarios": {"Garen": {"Darius": {"L6": {"full": {"all_up": cell}}}}},
        }

    def test_atomic_write_roundtrip_ascii(self) -> None:
        payload = self._payload()
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "laning_scenarios_sr.json"
            lsp.atomic_write(payload, out)
            raw = out.read_bytes()
            raw.decode("ascii")  # raises if any non-ASCII byte slipped in
            self.assertEqual(json.loads(raw.decode("utf-8")), payload)

    def test_lookup_navigates_nesting(self) -> None:
        payload = self._payload()
        cell = lsp.lookup(payload, "Garen", "Darius", "L6", "full", "all_up")
        self.assertEqual(cell["verdict"], "trade")

    def test_lookup_missing_returns_empty(self) -> None:
        payload = self._payload()
        self.assertEqual(
            lsp.lookup(payload, "Nobody", "Darius", "L6", "full", "all_up"), {}
        )
        self.assertEqual(lsp.lookup({}, "Garen", "Darius", "L6", "full", "all_up"), {})

    def test_load_missing_db_failsoft(self) -> None:
        # A patch with no committed file must degrade to {} (never raise).
        self.assertEqual(lsp.load_laning_scenarios(mode="sr", patch="0.0.0"), {})


class EngineCharacterizationTests(unittest.TestCase):
    """Precompute cells must equal the live DS matchup engine (characterization).
    """

    @classmethod
    def setUpClass(cls) -> None:
        from agents.daemon_slayer.data_loader import DataSnapshot
        cls.snap = DataSnapshot.load()

    def test_cell_verdict_matches_compute_matchup(self) -> None:
        from agents.daemon_slayer.matchup import compute_matchup
        cell = lsp.compute_cell(
            self.snap, "Garen", "Darius", "L6", "full", "all_up", mode="SR"
        )
        # Enemy is modelled at full resources (sequence_b = full rotation) - the
        # single rule core.laning_scenario_precompute._matchup encodes.
        ref = compute_matchup(
            self.snap, "Garen", "Darius", 6, 6, mode="SR",
            sequence_a=["Q", "W", "E", "R"], sequence_b=["Q", "W", "E", "R"],
        )
        self.assertEqual(cell["verdict"], ref.verdict)
        self.assertEqual(cell["net_swing"], lsp._round(ref.net_swing))
        self.assertEqual(cell["pct_my_removed"], lsp._round(ref.pct_a_removed))
        self.assertEqual(cell["pct_enemy_removed"], lsp._round(ref.pct_b_removed))
        # Slim schema v3: the redundant per-cell sequence array is dropped (it is
        # derivable from cd_state via combo_sequence); the cell never carries it.
        self.assertNotIn("sequence", cell)

    def test_cell_verdict_in_valid_set(self) -> None:
        cell = lsp.compute_cell(
            self.snap, "Annie", "Ahri", "L11", "full", "all_up", mode="SR"
        )
        self.assertIn(cell["verdict"], lsp.VALID_VERDICTS)
        # Slim v3: the derived my_can_full_combo / manaless are not persisted.
        self.assertNotIn("my_can_full_combo", cell)
        self.assertNotIn("manaless", cell)

    def test_no_ult_cd_state_drops_r_from_sequence(self) -> None:
        # The cd_state -> rotation mapping lives in combo_sequence; the slim v3
        # cell no longer persists the sequence, so assert the function directly.
        self.assertIn("R", lsp.combo_sequence("all_up"))
        self.assertNotIn("R", lsp.combo_sequence("no_ult"))

    def test_manaless_champ_low_equals_full_sequence(self) -> None:
        seq, manaless = lsp.derive_sequence(
            self.snap, "Garen", 6, "low", "all_up", mode="SR"
        )
        self.assertTrue(manaless)
        self.assertEqual(seq, ("Q", "W", "E", "R"))

    def test_mana_champ_low_truncates_sequence(self) -> None:
        seq, manaless = lsp.derive_sequence(
            self.snap, "Annie", 6, "low", "all_up", mode="SR"
        )
        self.assertFalse(manaless)
        # Low mana yields an affordable prefix of the full rotation.
        self.assertLess(len(seq), 4)
        self.assertEqual(seq, tuple(("Q", "W", "E", "R")[: len(seq)]))
        self.assertGreaterEqual(len(seq), 1)

    def test_generate_table_structure_and_valid_leaves(self) -> None:
        payload = lsp.generate_table(
            self.snap, ["Garen", "Annie"], ["Darius", "Ahri"],
            mode="SR", bands=["L6", "L11"],
        )
        self.assertEqual(payload["mode"], "sr")
        self.assertEqual(payload["schema"], "laning_scenarios/v3")
        self.assertTrue(payload["version"])
        scen = payload["scenarios"]
        leaves = 0
        for my, per_enemy in scen.items():
            for en, per_band in per_enemy.items():
                for band, per_mana in per_band.items():
                    for mana, per_cd in per_mana.items():
                        for cd, cell in per_cd.items():
                            self.assertIn(cell["verdict"], lsp.VALID_VERDICTS)
                            self.assertNotIn("sequence", cell)
                            leaves += 1
        # 2 champs x 2 enemies x 2 bands x 2 mana x 2 cd = 32 leaf cells.
        self.assertEqual(leaves, 32)
        # ASCII-clean serialization.
        json.dumps(payload, ensure_ascii=True).encode("ascii")

    def test_atomic_write_is_compact_single_line(self) -> None:
        # Slim NxN: the full-roster table is written compact (no indent) so the
        # 467k-cell artifact stays ~55MB, not ~290MB. One trailing newline only.
        payload = lsp.generate_table(
            self.snap, ["Garen"], ["Darius"], mode="SR", bands=["L6"],
        )
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "laning_scenarios_sr.json"
            lsp.atomic_write(payload, out)
            text = out.read_text(encoding="utf-8")
        self.assertEqual(text.count("\n"), 1)
        self.assertNotIn(": ", text)
        self.assertEqual(json.loads(text)["schema"], "laning_scenarios/v3")

    def test_generate_table_fail_soft_skips_bad_pair(self) -> None:
        # A champ the engine cannot model must not abort a full-roster sweep;
        # the offending pair is skipped, the rest of the table still builds.
        real = lsp._matchup

        def flaky(snapshot, my, enemy, *a, **k):
            if enemy == "BadGuy":
                raise RuntimeError("engine blew up")
            return real(snapshot, my, enemy, *a, **k)

        lsp._matchup = flaky
        try:
            payload = lsp.generate_table(
                self.snap, ["Garen"], ["Darius", "BadGuy"],
                mode="SR", bands=["L6"],
            )
        finally:
            lsp._matchup = real
        per_enemy = payload["scenarios"]["Garen"]
        self.assertIn("Darius", per_enemy)
        self.assertNotIn("BadGuy", per_enemy)


if __name__ == "__main__":
    unittest.main()
