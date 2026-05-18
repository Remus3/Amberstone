"""
tests/phase2_smoke/test_arena_coach_target_bonus_hp.py
Phase 4 batch 19 wire-in - arena_coach._estimate_target_bonus_hp.

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
        # (5-1) * 1500 / 9 = 666.67 - about 1 HP item by mid-arena.
        c = _StubCoach(5)
        self.assertAlmostEqual(c._estimate_target_bonus_hp(), 666.667, places=2)

    def test_round_ten_hits_cap(self) -> None:
        # (10-1) * 1500 / 9 = 1500.0 exactly.
        c = _StubCoach(10)
        self.assertAlmostEqual(c._estimate_target_bonus_hp(), 1500.0, places=2)

    def test_round_above_cap_clamps(self) -> None:
        # Late Arena (round 15+) - past LDR's saturation.
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


class EstimateTargetBonusHpItemAwareTests(unittest.TestCase):
    """Phase 4 batch 19 wire-in (s73) - primary path: item-summed HP.

    When teams[] carries enemy items, the estimator resolves names →
    DDragon HP and uses MAX across alive opponents. Heuristic only
    fires when no enemy items are visible. Verified against the live
    DDragon snapshot via ``daemon_slayer_resolver``.
    """

    def _state_with_teams(self, teams: list[dict]) -> dict:
        return {"teams": teams}

    def test_no_state_uses_round_fallback(self) -> None:
        # Back-compat: pre-s73 callers passed nothing. Round fallback
        # path still fires.
        c = _StubCoach(5)
        self.assertAlmostEqual(c._estimate_target_bonus_hp(), 666.667, places=2)

    def test_empty_teams_uses_round_fallback(self) -> None:
        # Pre-game state - no enemies parsed yet.
        c = _StubCoach(5)
        result = c._estimate_target_bonus_hp(self._state_with_teams([]))
        self.assertAlmostEqual(result, 666.667, places=2)

    def test_all_opps_dead_uses_round_fallback(self) -> None:
        # Mid-round-transition state - all enemies dead. Fall back to
        # round count rather than emitting 0 (player still wants Giant
        # Slayer recommendations for next round).
        c = _StubCoach(5)
        teams = [
            {"name": "You", "is_you": True, "items": ["Long Sword"]},
            {"name": "Partner", "is_partner": True, "items": []},
            {"name": "Enemy1", "is_dead": True, "items": ["Heartsteel"]},
            {"name": "Enemy2", "is_dead": True, "items": ["Riftmaker"]},
        ]
        result = c._estimate_target_bonus_hp(self._state_with_teams(teams))
        # Round-5 heuristic value, not 0.
        self.assertAlmostEqual(result, 666.667, places=2)

    def test_single_opp_with_items_uses_item_sum(self) -> None:
        # One alive enemy with Heartsteel (900 HP) + Riftmaker (350 HP)
        # → expects 1250. Round count is 5 (heuristic would say 667),
        # so item path winning proves the priority.
        c = _StubCoach(5)
        teams = [
            {"name": "You", "is_you": True, "items": []},
            {"name": "Enemy1", "items": ["Heartsteel", "Riftmaker"]},
        ]
        result = c._estimate_target_bonus_hp(self._state_with_teams(teams))
        # Heartsteel (Arena alias 223084 = 700 HP) + Riftmaker (Arena
        # alias 224633 = 350 HP) = 1050. items_index picks alias IDs
        # for Arena items per reference_items_index_alias_ids.
        self.assertAlmostEqual(result, 1050.0, places=1)

    def test_multi_opps_uses_max_not_avg(self) -> None:
        # Two alive enemies - one tanky (1050 HP from Heart+Rift),
        # one squishy (0 HP from LDR alone). Estimator picks 1050,
        # not the avg (525). LDR Giant Slayer recommendation should
        # escalate against the tanky enemy specifically.
        c = _StubCoach(5)
        teams = [
            {"name": "You", "is_you": True, "items": []},
            {"name": "Tank", "items": ["Heartsteel", "Riftmaker"]},
            {"name": "Squishy", "items": ["Lord Dominik's Regards"]},
        ]
        result = c._estimate_target_bonus_hp(self._state_with_teams(teams))
        self.assertAlmostEqual(result, 1050.0, places=1)

    def test_all_opps_have_no_hp_items_falls_back(self) -> None:
        # Both alive enemies built pure-AD pen - total bonus HP is 0
        # despite items being present. Estimator should fall back to
        # round count rather than emit 0.
        c = _StubCoach(5)
        teams = [
            {"name": "You", "is_you": True, "items": []},
            {"name": "Enemy1", "items": ["Lord Dominik's Regards"]},
            {"name": "Enemy2", "items": ["Mortal Reminder"]},
        ]
        result = c._estimate_target_bonus_hp(self._state_with_teams(teams))
        # Round-5 heuristic, not 0.
        self.assertAlmostEqual(result, 666.667, places=2)

    def test_caps_at_engine_saturation_point(self) -> None:
        # Hypothetical 5-HP-item build sums above 1500. Estimator must
        # clamp to match Giant Slayer's 1500 saturation point - past
        # that, the engine amp is at full 15% so precision stops
        # mattering and we shouldn't pretend to know more.
        c = _StubCoach(15)  # round count high - fallback also caps
        teams = [
            {"name": "You", "is_you": True, "items": []},
            {"name": "BigTank", "items": [
                "Heartsteel", "Riftmaker", "Sunfire Aegis",
                "Warmog's Armor", "Spirit Visage",
            ]},
        ]
        result = c._estimate_target_bonus_hp(self._state_with_teams(teams))
        self.assertEqual(result, 1500.0)

    def test_skips_self_and_partner(self) -> None:
        # Tanky teammate + tanky partner - neither should count toward
        # enemy bonus HP. Only the alive opponent's items matter.
        c = _StubCoach(5)
        teams = [
            {"name": "You", "is_you": True,
             "items": ["Heartsteel", "Riftmaker"]},
            {"name": "Pal", "is_partner": True,
             "items": ["Heartsteel", "Heartsteel"]},
            {"name": "Enemy1", "items": ["Sunfire Aegis"]},  # 350 HP arena
        ]
        result = c._estimate_target_bonus_hp(self._state_with_teams(teams))
        # Just Sunfire's 350 - neither self nor partner counts.
        self.assertAlmostEqual(result, 350.0, places=1)


if __name__ == "__main__":
    unittest.main()
