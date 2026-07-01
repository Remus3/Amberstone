"""R51 (ENGINE 1.163.0): target_hp gate seam for Cut Down / Coup de Grace.

Cut Down (8017) and Coup de Grace (8014) are Precision slot-4 stacking_amp
runes. Pre-R51 the burst-MAX scorer applied their flat 8% amp UNCONDITIONALLY
in ``keystone_amp`` (the burst-window approximation: a burst spans the target
HP range, so both gates are met somewhere inside the window). R51 adds a
DEFAULT-OFF ``gate_target_hp`` seam that, when flipped ON, gates each amp on the
supplied ``target_hp_pct`` per the live DDragon 16.13.1 longDesc:

  8017 Cut Down       :: +8% to champions who have MORE than 60% health.
  8014 Coup de Grace  :: +8% to champions who have LESS than 40% health.

Magnitude (1.08) and thresholds (0.60 / 0.40) are verbatim from
data/meta_build/ddragon/16.13.1/runesReforged.json (DDragon wins per the repo
DON'T-REDO rule). At the DEFAULT ``gate_target_hp=False`` every call is
BYTE-IDENTICAL to the pre-R51 engine (the seam block is skipped entirely). The
live default-ON flip is operator-gated (docs/LIVE_GAME_GATED_SYNC.md); this run
ships the seam OFF only.
"""

from __future__ import annotations

import unittest

from agents.daemon_slayer.rune_procs import keystone_amp

_CUT_DOWN = 8017
_COUP_DE_GRACE = 8014
_AMP = 1.08


class ByteIdenticalWhenOffTests(unittest.TestCase):
    """gate_target_hp=False (default) -> unconditional amp, unchanged."""

    def test_cut_down_default_unconditional(self):
        # No gate flag -> pre-R51 unconditional 1.08 (byte-identical).
        self.assertAlmostEqual(keystone_amp(_CUT_DOWN, 100.0), 108.0, places=6)

    def test_coup_de_grace_default_unconditional(self):
        self.assertAlmostEqual(keystone_amp(_COUP_DE_GRACE, 100.0), 108.0, places=6)

    def test_default_ignores_target_hp_pct(self):
        # With the gate OFF, target_hp_pct is inert (forward-compat metadata).
        for thp in (0.05, 0.40, 0.60, 1.0):
            self.assertAlmostEqual(
                keystone_amp(_CUT_DOWN, 100.0, target_hp_pct=thp), 108.0, places=6
            )
            self.assertAlmostEqual(
                keystone_amp(_COUP_DE_GRACE, 100.0, target_hp_pct=thp), 108.0, places=6
            )

    def test_explicit_gate_false_matches_default(self):
        self.assertAlmostEqual(
            keystone_amp(_CUT_DOWN, 100.0, target_hp_pct=0.10, gate_target_hp=False),
            108.0,
            places=6,
        )


class CutDownGateOnTests(unittest.TestCase):
    """gate_target_hp=True -> amp only when target ABOVE 60% health."""

    def test_high_hp_amped(self):
        for thp in (0.61, 0.75, 1.0):
            self.assertAlmostEqual(
                keystone_amp(_CUT_DOWN, 100.0, target_hp_pct=thp, gate_target_hp=True),
                100.0 * _AMP,
                places=6,
                msg=f"thp={thp}",
            )

    def test_low_hp_no_amp(self):
        for thp in (0.0, 0.30, 0.59):
            self.assertAlmostEqual(
                keystone_amp(_CUT_DOWN, 100.0, target_hp_pct=thp, gate_target_hp=True),
                100.0,
                places=6,
                msg=f"thp={thp}",
            )

    def test_boundary_60pct_excluded(self):
        # "more than 60%" is strict -> exactly 0.60 is NOT amped.
        self.assertAlmostEqual(
            keystone_amp(_CUT_DOWN, 100.0, target_hp_pct=0.60, gate_target_hp=True),
            100.0,
            places=6,
        )


class CoupDeGraceGateOnTests(unittest.TestCase):
    """gate_target_hp=True -> amp only when target BELOW 40% health."""

    def test_low_hp_amped(self):
        for thp in (0.0, 0.20, 0.39):
            self.assertAlmostEqual(
                keystone_amp(
                    _COUP_DE_GRACE, 100.0, target_hp_pct=thp, gate_target_hp=True
                ),
                100.0 * _AMP,
                places=6,
                msg=f"thp={thp}",
            )

    def test_high_hp_no_amp(self):
        for thp in (0.41, 0.60, 1.0):
            self.assertAlmostEqual(
                keystone_amp(
                    _COUP_DE_GRACE, 100.0, target_hp_pct=thp, gate_target_hp=True
                ),
                100.0,
                places=6,
                msg=f"thp={thp}",
            )

    def test_boundary_40pct_excluded(self):
        # "less than 40%" is strict -> exactly 0.40 is NOT amped.
        self.assertAlmostEqual(
            keystone_amp(
                _COUP_DE_GRACE, 100.0, target_hp_pct=0.40, gate_target_hp=True
            ),
            100.0,
            places=6,
        )


class GateDoesNotTouchOtherAmpRunesTests(unittest.TestCase):
    """gate_target_hp only gates the two target_hp_* runes; others unchanged."""

    def test_press_the_attack_unaffected(self):
        # 8005 PtA is condition="unconditional" -> gate flag inert.
        self.assertAlmostEqual(
            keystone_amp(8005, 100.0, target_hp_pct=0.10, gate_target_hp=True),
            108.0,
            places=6,
        )

    def test_first_strike_unaffected(self):
        self.assertAlmostEqual(
            keystone_amp(8369, 100.0, target_hp_pct=0.10, gate_target_hp=True),
            107.0,
            places=6,
        )

    def test_last_stand_still_caster_gated(self):
        # 8299 Last Stand is caster-hp gated; target gate flag must not disturb
        # its caster-hp amp path (default caster full HP -> no amp).
        self.assertAlmostEqual(
            keystone_amp(8299, 100.0, target_hp_pct=0.10, gate_target_hp=True),
            100.0,
            places=6,
        )
        self.assertAlmostEqual(
            keystone_amp(
                8299, 100.0, caster_hp_pct=0.30, target_hp_pct=0.10, gate_target_hp=True
            ),
            111.0,
            places=6,
        )


class FailSoftTests(unittest.TestCase):
    def test_bad_base_fail_soft_with_gate(self):
        self.assertEqual(
            keystone_amp(_CUT_DOWN, "nope", gate_target_hp=True), 0.0
        )

    def test_unknown_rune_passthrough_with_gate(self):
        self.assertEqual(
            keystone_amp(999999, 100.0, gate_target_hp=True), 100.0
        )


if __name__ == "__main__":
    unittest.main()
