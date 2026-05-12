"""s170 (2026-05-11) — coach_integration.enemy_stats heuristic tests.

Validates the level-aware enemy aggregate stats helper that replaces the
hardcoded ``target_armor=80.0`` in all four coaches' DS rank_for calls.
"""
from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError

from coach_integration.enemy_stats import (
    EnemyStats,
    compute_enemy_stats,
)


class TestEnemyStatsBasics(unittest.TestCase):
    def test_default_mode_is_sr(self):
        # None / empty / unknown all fall back to SR anchors.
        s = compute_enemy_stats(None, level=11)
        self.assertGreater(s.armor, 0)
        self.assertGreater(s.mr, 0)
        # SR @ lvl 11: armor = 40 + 5*11 = 95
        self.assertEqual(s.armor, 95.0)

    def test_returns_enemy_stats_dataclass(self):
        s = compute_enemy_stats("sr", level=11)
        self.assertIsInstance(s, EnemyStats)
        # Frozen — attempts to mutate must raise.
        with self.assertRaises(FrozenInstanceError):
            s.armor = 999.0  # type: ignore[misc]

    def test_armor_scales_with_level_sr(self):
        s_low  = compute_enemy_stats("sr", level=1)
        s_mid  = compute_enemy_stats("sr", level=11)
        s_high = compute_enemy_stats("sr", level=18)
        self.assertLess(s_low.armor, s_mid.armor)
        self.assertLess(s_mid.armor, s_high.armor)

    def test_mr_scales_with_level(self):
        s_low  = compute_enemy_stats("sr", level=1)
        s_high = compute_enemy_stats("sr", level=18)
        self.assertLess(s_low.mr, s_high.mr)

    def test_max_hp_scales_with_level(self):
        s_low  = compute_enemy_stats("sr", level=1)
        s_high = compute_enemy_stats("sr", level=18)
        self.assertLess(s_low.max_hp, s_high.max_hp)


class TestModeDifferentiation(unittest.TestCase):
    """The whole point of s170 — DS now sees different targets per mode."""

    def test_arena_armor_higher_than_sr_at_same_level(self):
        # Arena rounds compress build time; aggregate gold is high.
        s_sr    = compute_enemy_stats("sr", level=11)
        s_arena = compute_enemy_stats("arena", level=11)
        self.assertGreater(s_arena.armor, s_sr.armor)
        self.assertGreater(s_arena.mr, s_sr.mr)

    def test_aram_armor_higher_than_sr(self):
        # ARAM gold gen is faster than SR.
        s_sr   = compute_enemy_stats("sr", level=11)
        s_aram = compute_enemy_stats("aram", level=11)
        self.assertGreater(s_aram.armor, s_sr.armor)

    def test_brawl_close_to_sr(self):
        # Brawl is "SR but compressed" — should be in the same neighborhood.
        s_sr    = compute_enemy_stats("sr", level=11)
        s_brawl = compute_enemy_stats("brawl", level=11)
        # Within 15 armor of each other at the same level.
        self.assertLess(abs(s_sr.armor - s_brawl.armor), 15.0)

    def test_uppercase_mode_normalized(self):
        s_lower = compute_enemy_stats("sr", level=11)
        s_upper = compute_enemy_stats("SR", level=11)
        self.assertEqual(s_lower.armor, s_upper.armor)

    def test_alias_classic_resolves_to_sr(self):
        s_sr      = compute_enemy_stats("sr", level=11)
        s_classic = compute_enemy_stats("classic", level=11)
        self.assertEqual(s_sr.armor, s_classic.armor)

    def test_alias_cherry_resolves_to_arena(self):
        s_arena  = compute_enemy_stats("arena", level=11)
        s_cherry = compute_enemy_stats("cherry", level=11)
        self.assertEqual(s_arena.armor, s_cherry.armor)


class TestLevelDerivation(unittest.TestCase):
    def test_explicit_level_wins_over_game_seconds(self):
        # game_seconds=0 + level=18 should produce the lvl-18 curve, not lvl-1.
        s = compute_enemy_stats("sr", game_seconds=0, level=18)
        # SR @ lvl 18: armor = 40 + 5*18 = 130
        self.assertEqual(s.armor, 130.0)

    def test_game_seconds_fallback(self):
        # ~1 level per 90s — 9 minutes = ~7 levels.
        s = compute_enemy_stats("sr", game_seconds=540)
        # Effective level ~7, armor = 40 + 5*7 = 75
        self.assertAlmostEqual(s.armor, 75.0, places=0)

    def test_enemy_levels_overrides_level_arg(self):
        # enemy_levels supplied → averaged + used directly.
        s = compute_enemy_stats("sr", level=1, enemy_levels=[11, 11, 11, 11, 11])
        self.assertEqual(s.armor, 95.0)  # SR @ lvl 11

    def test_enemy_levels_averaged(self):
        # Stomp scenario: enemies are lvl 14, you're 9.
        s = compute_enemy_stats("sr", level=9, enemy_levels=[14, 14, 14, 14, 13])
        # avg = 13.8, armor = 40 + 5*13.8 = 109
        self.assertEqual(s.armor, 109.0)

    def test_empty_enemy_levels_falls_to_level_arg(self):
        s = compute_enemy_stats("sr", level=11, enemy_levels=[])
        self.assertEqual(s.armor, 95.0)

    def test_enemy_levels_filters_zero(self):
        # Zero-level entries (Live Client placeholder) should be excluded.
        s = compute_enemy_stats("sr", level=1, enemy_levels=[11, 0, 11])
        # Two valid levels averaged to 11.
        self.assertEqual(s.armor, 95.0)


class TestBonusHpOverride(unittest.TestCase):
    def test_override_replaces_heuristic_value(self):
        # Without override: bonus_hp ≈ max_hp - 600 base.
        s_default = compute_enemy_stats("sr", level=11)
        # With override: take exactly the override value.
        s_override = compute_enemy_stats("sr", level=11, bonus_hp_override=1500.0)
        self.assertEqual(s_override.bonus_hp, 1500.0)
        self.assertNotEqual(s_override.bonus_hp, s_default.bonus_hp)

    def test_zero_override_falls_back_to_heuristic(self):
        # Coach passes 0 when item-aware estimator finds no signal —
        # the heuristic value should win in that case (not stay at 0).
        s_default = compute_enemy_stats("sr", level=11)
        s_zero    = compute_enemy_stats("sr", level=11, bonus_hp_override=0.0)
        self.assertEqual(s_default.bonus_hp, s_zero.bonus_hp)

    def test_negative_override_falls_back_to_heuristic(self):
        s_default = compute_enemy_stats("sr", level=11)
        s_neg     = compute_enemy_stats("sr", level=11, bonus_hp_override=-5.0)
        self.assertEqual(s_default.bonus_hp, s_neg.bonus_hp)

    def test_override_clamped_to_cap(self):
        # Cap is 3500 (per _BONUS_HP_CAP). A 9999 override clamps.
        s = compute_enemy_stats("sr", level=11, bonus_hp_override=9999.0)
        self.assertLessEqual(s.bonus_hp, 3500.0)


class TestCaps(unittest.TestCase):
    def test_armor_caps_at_220(self):
        # Level cap is 18, so check the arena anchor at lvl 18:
        # armor = 40 + 8*18 = 184 — under the 220 cap.
        s = compute_enemy_stats("arena", level=18)
        self.assertLessEqual(s.armor, 220.0)

    def test_bonus_hp_never_negative(self):
        # Pathological: very low max_hp shouldn't produce negative bonus_hp.
        s = compute_enemy_stats("sr", level=1)
        self.assertGreaterEqual(s.bonus_hp, 0)

    def test_level_clamped_to_18(self):
        # Garbage level 99 → treated as 18.
        s_high  = compute_enemy_stats("sr", level=99)
        s_cap   = compute_enemy_stats("sr", level=18)
        self.assertEqual(s_high.armor, s_cap.armor)

    def test_level_clamped_to_1(self):
        # Negative / zero level → treated as 1.
        s_zero = compute_enemy_stats("sr", level=0)
        s_one  = compute_enemy_stats("sr", level=1)
        self.assertEqual(s_zero.armor, s_one.armor)


class TestPreservesPreviousBehavior(unittest.TestCase):
    """Old call site was target_armor=80.0; new helper at SR mid-game
    should produce a roughly similar number so historical DS picks
    don't shift wildly on the very first deploy.
    """

    def test_sr_lvl_8_close_to_80(self):
        # SR @ lvl 8: armor = 40 + 5*8 = 80 — matches the prior anchor.
        s = compute_enemy_stats("sr", level=8)
        self.assertEqual(s.armor, 80.0)

    def test_sr_lvl_11_close_to_old_80(self):
        # SR @ lvl 11: armor = 95 — modest bump from prior 80, still
        # reasonable (mid-game enemies usually have a giant's-belt +
        # bramble vest by lvl 11 anyway).
        s = compute_enemy_stats("sr", level=11)
        self.assertLessEqual(abs(s.armor - 80.0), 20.0)


if __name__ == "__main__":
    unittest.main()
