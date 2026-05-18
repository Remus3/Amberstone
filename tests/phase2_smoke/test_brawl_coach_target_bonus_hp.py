"""
tests/phase2_smoke/test_brawl_coach_target_bonus_hp.py
s75 - brawl_coach._estimate_target_bonus_hp + DS mode routing.

Brawl coach is the umbrella for BRAWL / NEXUSBLITZ / URF / OFA modes.
DS mode routing splits BRAWL (map 35) from the SR-on-other-map modes
(URF/OFA on SR, NEXUSBLITZ on map 21). Both paths give correct base
HP values; the regression to avoid is leaking the 22XXXX Arena alias
HP into Brawl callers (would happen if mode argument got dropped).
"""
import sys
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from coaches import brawl_coach


class _StubCoach:
    """Minimal stand-in: estimator + mode routers are pure of self.

    Static methods need the staticmethod() re-wrap because accessing
    ``Coach._ds_resolver_mode`` via class returns the unwrapped function;
    raw assignment would treat it as a regular method and pass ``self``.
    """

    _estimate_target_bonus_hp = brawl_coach.Coach._estimate_target_bonus_hp
    _ds_resolver_mode = staticmethod(brawl_coach.Coach._ds_resolver_mode)
    _ds_engine_mode = staticmethod(brawl_coach.Coach._ds_engine_mode)


class DsModeRoutingTests(unittest.TestCase):
    """Routing helpers split BRAWL from SR-fallback modes."""

    def test_brawl_routes_to_brawl(self) -> None:
        c = _StubCoach()
        self.assertEqual(c._ds_resolver_mode("BRAWL"), "brawl")
        self.assertEqual(c._ds_engine_mode("BRAWL"), "BRAWL")

    def test_urf_routes_to_sr(self) -> None:
        c = _StubCoach()
        self.assertEqual(c._ds_resolver_mode("URF"), "sr")
        self.assertEqual(c._ds_engine_mode("URF"), "SR")

    def test_ultbook_routes_to_sr(self) -> None:
        # ULTBOOK is the LCU's Ultimate Spellbook code (URF cousin).
        c = _StubCoach()
        self.assertEqual(c._ds_resolver_mode("ULTBOOK"), "sr")
        self.assertEqual(c._ds_engine_mode("ULTBOOK"), "SR")

    def test_oneforall_routes_to_sr(self) -> None:
        c = _StubCoach()
        self.assertEqual(c._ds_resolver_mode("ONEFORALL"), "sr")
        self.assertEqual(c._ds_engine_mode("ONEFORALL"), "SR")

    def test_nexusblitz_routes_to_sr(self) -> None:
        # Map 21 isn't in the resolver yet; SR base IDs are valid for
        # Nexus Blitz (it inherits the SR item pool).
        c = _StubCoach()
        self.assertEqual(c._ds_resolver_mode("NEXUSBLITZ"), "sr")
        self.assertEqual(c._ds_engine_mode("NEXUSBLITZ"), "SR")

    def test_empty_or_none_mode_routes_to_sr(self) -> None:
        # Defensive: no game_mode field shouldn't crash. Default SR.
        c = _StubCoach()
        self.assertEqual(c._ds_resolver_mode(""), "sr")
        self.assertEqual(c._ds_resolver_mode(None), "sr")
        self.assertEqual(c._ds_engine_mode(""), "SR")

    def test_brawl_substring_match(self) -> None:
        # "BRAWL" should match even when LCU adds suffixes - matches
        # 'in BRAWL' style game_mode strings if they ever appear.
        c = _StubCoach()
        self.assertEqual(c._ds_resolver_mode("BRAWL_RANKED"), "brawl")
        self.assertEqual(c._ds_engine_mode("BRAWL_RANKED"), "BRAWL")


class EstimateTargetBonusHpTests(unittest.TestCase):
    """Item-aware HP estimator over Brawl enemies struct."""

    def test_no_state_returns_zero(self) -> None:
        c = _StubCoach()
        self.assertEqual(c._estimate_target_bonus_hp(), 0.0)
        self.assertEqual(c._estimate_target_bonus_hp({}), 0.0)
        self.assertEqual(c._estimate_target_bonus_hp(None), 0.0)

    def test_no_enemies_returns_zero(self) -> None:
        c = _StubCoach()
        self.assertEqual(
            c._estimate_target_bonus_hp({"game_mode": "BRAWL", "enemies": []}),
            0.0,
        )

    def test_all_enemies_dead_returns_zero(self) -> None:
        c = _StubCoach()
        state = {"game_mode": "BRAWL", "enemies": [
            {"name": "Sett", "is_dead": True, "items": ["Heartsteel"]},
            {"name": "Yone", "is_dead": True, "items": ["Riftmaker"]},
        ]}
        self.assertEqual(c._estimate_target_bonus_hp(state), 0.0)

    def test_brawl_uses_brawl_resolver_mode(self) -> None:
        # BRAWL game_mode → resolver mode='brawl' → Heartsteel→3084 (900 HP).
        # Regression pin: if this returns 700, the Arena alias path leaked.
        c = _StubCoach()
        state = {"game_mode": "BRAWL", "enemies": [
            {"name": "Sett", "is_dead": False, "items": ["Heartsteel"]},
        ]}
        self.assertAlmostEqual(c._estimate_target_bonus_hp(state), 900.0, places=1)

    def test_urf_uses_sr_resolver_mode(self) -> None:
        # URF rides on SR (map 11) → resolver mode='sr' → Heartsteel→3084.
        c = _StubCoach()
        state = {"game_mode": "URF", "enemies": [
            {"name": "Sett", "is_dead": False, "items": ["Heartsteel"]},
        ]}
        self.assertAlmostEqual(c._estimate_target_bonus_hp(state), 900.0, places=1)

    def test_oneforall_uses_sr_resolver_mode(self) -> None:
        c = _StubCoach()
        state = {"game_mode": "ONEFORALL", "enemies": [
            {"name": "Sett", "is_dead": False,
             "items": ["Heartsteel", "Riftmaker"]},
        ]}
        # Heartsteel(900) + Riftmaker(350) = 1250
        self.assertAlmostEqual(c._estimate_target_bonus_hp(state), 1250.0, places=1)

    def test_max_across_alive_enemies_not_avg(self) -> None:
        # 5 enemies; only Sett tanky. MAX wins, not avg-of-team 250.
        c = _StubCoach()
        state = {"game_mode": "BRAWL", "enemies": [
            {"name": "Sett",   "is_dead": False, "items": ["Heartsteel", "Riftmaker"]},
            {"name": "Yone",   "is_dead": False, "items": []},
            {"name": "Akali",  "is_dead": False, "items": []},
            {"name": "Lulu",   "is_dead": False, "items": []},
            {"name": "Thresh", "is_dead": False, "items": []},
        ]}
        self.assertAlmostEqual(c._estimate_target_bonus_hp(state), 1250.0, places=1)

    def test_dead_enemy_excluded_from_max(self) -> None:
        c = _StubCoach()
        state = {"game_mode": "BRAWL", "enemies": [
            {"name": "Sett", "is_dead": True,  "items": ["Heartsteel", "Riftmaker"]},
            {"name": "Yone", "is_dead": False, "items": ["Riftmaker"]},
        ]}
        self.assertAlmostEqual(c._estimate_target_bonus_hp(state), 350.0, places=1)

    def test_pen_only_build_returns_zero(self) -> None:
        c = _StubCoach()
        state = {"game_mode": "BRAWL", "enemies": [
            {"name": "Caitlyn", "is_dead": False,
             "items": ["Lord Dominik's Regards", "Mortal Reminder"]},
        ]}
        self.assertEqual(c._estimate_target_bonus_hp(state), 0.0)

    def test_caps_at_giant_slayer_threshold(self) -> None:
        c = _StubCoach()
        state = {"game_mode": "BRAWL", "enemies": [
            {"name": "Sion", "is_dead": False,
             "items": ["Heartsteel", "Riftmaker", "Sunfire Aegis", "Warmog's Armor"]},
        ]}
        self.assertEqual(c._estimate_target_bonus_hp(state), 1500.0)

    def test_missing_game_mode_defaults_to_sr_path(self) -> None:
        # No game_mode field: routes via sr fallback. Heartsteel resolves
        # to SR base ID (3084) regardless. Ensures missing field doesn't
        # crash the estimator.
        c = _StubCoach()
        state = {"enemies": [
            {"name": "Sett", "is_dead": False, "items": ["Heartsteel"]},
        ]}
        self.assertAlmostEqual(c._estimate_target_bonus_hp(state), 900.0, places=1)


if __name__ == "__main__":
    unittest.main()
