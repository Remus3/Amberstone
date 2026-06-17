"""Regression: champions whose laning-scenario rotations encode zero basic
attacks collapsed compute_dps ``weighted_dps`` to 0.0, producing an all-zero,
starter-only ranking (the coach surfaced an all-Doran's recommendation).

Root cause: ``_phase_rotations`` reads ``settings.scenario.{early,mid,late}``
and ``_rotation_attack_dps`` scores only the basic-attack portion; the upstream
lolmath scenario for Aphelios (weapon-swap kit) + 4 casters encodes ``basic: 0``
in every rotation, so every phase DPS is 0, every item delta is 0, and the
ranker degenerates to starters. compute_dps now falls back to
``raw_attack_dps`` (base AD * AS, item-responsive) when NO phase has any
basic-attack DPS and raw is positive.

Found 2026-06-16 in the comprehensive per-champion DS scorer cross-eval
(ops/audit/ds_cross_eval/SYSTEMIC_FINDINGS.md Cluster C). The fallback fires for
4 champs at patch 16.12.1: Aphelios (the live dps/carry bug) + the casters
Cassiopeia / Fiddlesticks / Sylas (routed to the ability scorer, so latent).
The mode_mult>0 gate keeps an ARAM-disabled champ (Yunara pre-16.11.1,
aramDamageDealt=0) at weighted_dps=0.0.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import compute_dps

IE = "3031"  # Infinity Edge


class TestApheliosDegenerateScenario(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_aphelios_weighted_dps_nonzero(self) -> None:
        r = compute_dps(self.snap, "Aphelios", level=13, item_ids=[IE],
                        mode="ARAM", target_armor=60, target_mr=50)
        self.assertGreater(
            r.weighted_dps, 0.0,
            "Aphelios weighted_dps must not collapse to 0 (degenerate scenario)")

    def test_aphelios_item_responsive(self) -> None:
        naked = compute_dps(self.snap, "Aphelios", level=13, item_ids=[],
                            mode="ARAM", target_armor=60, target_mr=50)
        ie = compute_dps(self.snap, "Aphelios", level=13, item_ids=[IE],
                         mode="ARAM", target_armor=60, target_mr=50)
        self.assertGreater(
            ie.weighted_dps, naked.weighted_dps,
            "adding Infinity Edge must raise Aphelios dps (ranking responsive)")

    def test_aphelios_fallback_equals_raw_with_note(self) -> None:
        r = compute_dps(self.snap, "Aphelios", level=13, item_ids=[IE],
                        mode="ARAM", target_armor=60, target_mr=50)
        # fallback = raw_attack_dps * mode_multiplier (mode-adjusted, so a
        # mode-disabled champ stays 0); Aphelios mode_mult is 1.0 at 16.12.1.
        self.assertAlmostEqual(
            r.weighted_dps, r.raw_attack_dps * r.mode_multiplier, places=6)
        self.assertTrue(
            any("raw_attack_dps" in n for n in r.notes),
            "fallback must leave an auditable note")

    def test_normal_adc_unchanged_by_fallback(self) -> None:
        # Jinx has real basic-attack rotations -> the phase model drives
        # weighted_dps, which is diluted below raw_attack_dps; the fallback
        # must NOT trigger (regression guard for the 167 healthy champs).
        r = compute_dps(self.snap, "Jinx", level=13, item_ids=[IE],
                        mode="ARAM", target_armor=60, target_mr=50)
        self.assertGreater(r.weighted_dps, 0.0)
        self.assertNotAlmostEqual(r.weighted_dps, r.raw_attack_dps, places=2)


if __name__ == "__main__":
    unittest.main()
