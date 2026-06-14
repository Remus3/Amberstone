"""
tests/phase2_smoke/test_aram_coach_target_bonus_hp.py
s74 - aram_coach._estimate_target_bonus_hp wire-in.

ARAM port of arena_coach's s73 estimator. Differs in two ways:
1. No round-count fallback - ARAM has no rounds. Vision gap -> 0.0
   (engine treats as "no signal", no escalation).
2. Resolves with mode='aram' -> SR base item IDs (3084 not 223084),
   so HP values are SR base (900 Heartsteel) not Arena alias (700).

Tested via a stub class (mirrors arena_coach test pattern) to avoid
pulling the full BaseCoach lifecycle / Anthropic SDK / LCU.
"""
import sys
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from coaches import aram_coach


class _StubCoach:
    """Minimal stand-in: estimator only reads the state arg, no self."""

    _estimate_target_bonus_hp = aram_coach.Coach._estimate_target_bonus_hp


class EstimateTargetBonusHpTests(unittest.TestCase):
    """Item-aware HP estimator over ARAM enemies struct."""

    def test_no_state_returns_zero(self) -> None:
        c = _StubCoach()
        self.assertEqual(c._estimate_target_bonus_hp(), 0.0)
        self.assertEqual(c._estimate_target_bonus_hp({}), 0.0)
        self.assertEqual(c._estimate_target_bonus_hp(None), 0.0)

    def test_no_enemies_returns_zero(self) -> None:
        c = _StubCoach()
        # No enemies key - vision gap or pre-game.
        self.assertEqual(c._estimate_target_bonus_hp({"enemies": []}), 0.0)

    def test_all_enemies_dead_returns_zero(self) -> None:
        # Mid-team-fight wipe: 5 dead enemies, no signal until they
        # respawn. Engine should not escalate Giant Slayer here.
        c = _StubCoach()
        state = {"enemies": [
            {"name": "Sett", "is_dead": True, "items": ["Heartsteel"]},
            {"name": "Yone", "is_dead": True, "items": ["Riftmaker"]},
        ]}
        self.assertEqual(c._estimate_target_bonus_hp(state), 0.0)

    def test_all_enemies_no_items_returns_zero(self) -> None:
        # Early game / no items bought yet.
        c = _StubCoach()
        state = {"enemies": [
            {"name": "Sett", "is_dead": False, "items": []},
            {"name": "Yone", "is_dead": False, "items": []},
        ]}
        self.assertEqual(c._estimate_target_bonus_hp(state), 0.0)

    def test_single_alive_tank_uses_aram_hp_values(self) -> None:
        # Heartsteel (3084) = 900 HP at ARAM mode (NOT 700 Arena alias).
        # Single tank build summed: Heartsteel + Riftmaker = 1250.
        c = _StubCoach()
        state = {"enemies": [
            {"name": "Sett", "is_dead": False,
             "items": ["Heartsteel", "Riftmaker"]},
        ]}
        self.assertAlmostEqual(c._estimate_target_bonus_hp(state), 1250.0, places=1)

    def test_max_across_alive_enemies_not_avg(self) -> None:
        # 5 enemies; only Sett is tanky. MAX wins, not avg.
        # Avg would be 1250 / 5 = 250 (wrong - would miss LDR escalation).
        c = _StubCoach()
        state = {"enemies": [
            {"name": "Sett",   "is_dead": False, "items": ["Heartsteel", "Riftmaker"]},
            {"name": "Yone",   "is_dead": False, "items": []},
            {"name": "Akali",  "is_dead": False, "items": []},
            {"name": "Lulu",   "is_dead": False, "items": []},
            {"name": "Thresh", "is_dead": False, "items": []},
        ]}
        self.assertAlmostEqual(c._estimate_target_bonus_hp(state), 1250.0, places=1)

    def test_dead_enemy_excluded_from_max(self) -> None:
        # Tank is dead - don't count their HP. Live signal only.
        # Live opponent has Riftmaker (350); dead one has Heartsteel+Rift (1250).
        # Result should be 350, not 1250.
        c = _StubCoach()
        state = {"enemies": [
            {"name": "Sett", "is_dead": True,  "items": ["Heartsteel", "Riftmaker"]},
            {"name": "Yone", "is_dead": False, "items": ["Riftmaker"]},
        ]}
        self.assertAlmostEqual(c._estimate_target_bonus_hp(state), 350.0, places=1)

    def test_pen_only_build_returns_zero(self) -> None:
        # Glass cannon ADC enemy: LDR + Mortal Reminder + nothing tanky.
        # No HP signal -> 0 (engine: no Giant Slayer escalation).
        c = _StubCoach()
        state = {"enemies": [
            {"name": "Caitlyn", "is_dead": False,
             "items": ["Lord Dominik's Regards", "Mortal Reminder"]},
        ]}
        self.assertEqual(c._estimate_target_bonus_hp(state), 0.0)

    def test_caps_at_giant_slayer_threshold(self) -> None:
        # 4-stack tank build sums past 1500 -> clamps at LDR's cap.
        # Heart(900) + Rift(350) + Sun(350) + Warmog's = will exceed 1500.
        c = _StubCoach()
        state = {"enemies": [
            {"name": "Sion", "is_dead": False,
             "items": ["Heartsteel", "Riftmaker", "Sunfire Aegis", "Warmog's Armor"]},
        ]}
        self.assertEqual(c._estimate_target_bonus_hp(state), 1500.0)

    def test_uses_aram_mode_not_arena_aliases(self) -> None:
        # Regression-pin the s74 fix: the ARAM estimator MUST resolve with
        # mode='aram' so Heartsteel->3084 (900 HP), not Heartsteel->223084
        # (700 HP, Arena alias). If this test starts returning 700, the
        # resolver mode argument was dropped somewhere in the wire-in.
        c = _StubCoach()
        state = {"enemies": [
            {"name": "Sett", "is_dead": False, "items": ["Heartsteel"]},
        ]}
        self.assertAlmostEqual(c._estimate_target_bonus_hp(state), 900.0, places=1)


if __name__ == "__main__":
    unittest.main()
