"""
tests/phase2_smoke/test_arena_coach_target_bonus_hp.py
Phase 4 batch 19 wire-in — arena_coach._estimate_target_bonus_hp.

The estimator is a pure function of self._event_round_count. Tested
via a stub class (mirrors test_arena_augment_hud's pattern) to avoid
pulling the full Coach lifecycle / Anthropic SDK.
"""
import sys
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from coaches import arena_coach


class _StubCoach:
    """Minimal stand-in: the only attr the estimator reads."""

    def __init__(self, round_count: int):
        self._event_round_count = round_count

    # Bind the real method so we test the shipped code path.
    _estimate_target_bonus_hp = arena_coach.Coach._estimate_target_bonus_hp


class EstimateTargetBonusHpCurveTests(unittest.TestCase):
    """Pin the round → estimated_bonus_hp curve."""

    def test_round_zero_returns_zero(self) -> None:
        # Pre-game / state gap.
        c = _StubCoach(0)
        self.assertEqual(c._estimate_target_bonus_hp(), 0.0)

    def test_round_one_returns_zero(self) -> None:
        # Round 1: champ-select / opening, no items yet.
        c = _StubCoach(1)
        self.assertEqual(c._estimate_target_bonus_hp(), 0.0)

    def test_round_two_starts_ramp(self) -> None:
        # (2-1) * 1500 / 9 = 166.67
        c = _StubCoach(2)
        self.assertAlmostEqual(c._estimate_target_bonus_hp(), 166.667, places=2)

    def test_round_five_at_quarter_cap_ish(self) -> None:
        # (5-1) * 1500 / 9 = 666.67 — about 1 HP item by mid-arena.
        c = _StubCoach(5)
        self.assertAlmostEqual(c._estimate_target_bonus_hp(), 666.667, places=2)

    def test_round_ten_hits_cap(self) -> None:
        # (10-1) * 1500 / 9 = 1500.0 exactly.
        c = _StubCoach(10)
        self.assertAlmostEqual(c._estimate_target_bonus_hp(), 1500.0, places=2)

    def test_round_above_cap_clamps(self) -> None:
        # Late Arena (round 15+) — past LDR's saturation.
        c = _StubCoach(15)
        self.assertEqual(c._estimate_target_bonus_hp(), 1500.0)

    def test_negative_round_returns_zero(self) -> None:
        # Defensive guard against state-corruption edge cases.
        c = _StubCoach(-3)
        self.assertEqual(c._estimate_target_bonus_hp(), 0.0)

    def test_curve_monotonic(self) -> None:
        # Sanity: never decreases as round count rises.
        c1 = _StubCoach(1)
        c2 = _StubCoach(2)
        c5 = _StubCoach(5)
        c10 = _StubCoach(10)
        c20 = _StubCoach(20)
        seq = [c._estimate_target_bonus_hp() for c in (c1, c2, c5, c10, c20)]
        self.assertEqual(seq, sorted(seq))


if __name__ == "__main__":
    unittest.main()
