"""Tests for tools/gated_live_probe.py - the lane-9 one-shot live-game evidence
probe. Pure-function + render-branch coverage; the HTTP collect() path is
fail-soft by construction and is exercised live by the lane, not mocked here.
"""
from __future__ import annotations

import unittest

from tools import gated_live_probe as g


class TestCcKeyFilter(unittest.TestCase):
    def test_matches_cc_panel_keys(self):
        for k in ("cc", "cc_blended", "cc_conditional", "team_cc", "foo_cc_bar"):
            self.assertTrue(g._is_cc_key(k), k)

    def test_excludes_false_positives(self):
        # the real /api/state carries lcu/config/auto_accept - a naive 'cc'
        # substring test matched it and manufactured a bogus serving surface.
        for k in ("auto_accept", "account", "access", "success", "accept"):
            self.assertFalse(g._is_cc_key(k), k)


class TestScanKeys(unittest.TestCase):
    def test_scan_excludes_auto_accept_finds_cc_panel(self):
        state = {"lcu": {"config": {"auto_accept": True}}, "cc_blended_panel": {"v": 1}}
        self.assertEqual(g._scan_keys(state, g._is_cc_key), ["/cc_blended_panel"])

    def test_scan_empty_when_no_serving_surface(self):
        state = {"lcu": {"config": {"auto_accept": True}}, "coach": {"action": "x"}}
        self.assertEqual(g._scan_keys(state, g._is_cc_key), [])

    def test_adapt_key_scan(self):
        state = {"st_kills": 1, "coach": {"adaptation_note": "y"}, "plain": 2}
        hits = g._scan_keys(state, g._is_adapt_key)
        self.assertIn("/st_kills", hits)
        self.assertIn("/coach/adaptation_note", hits)
        self.assertNotIn("/plain", hits)


class TestRender(unittest.TestCase):
    def test_unreachable(self):
        out = g._render({"reachable": False, "state_error": "boom"})
        self.assertIn("RC UNREACHABLE", out)
        self.assertIn("boom", out)

    def test_idle(self):
        out = g._render({"reachable": True, "in_game": False, "mode_key": "client", "gate": "GATE 1"})
        self.assertIn("IN-GAME: False", out)
        self.assertIn("PREP half", out)

    def test_in_game_flags_vision_dead_and_substitution(self):
        facts = {
            "reachable": True,
            "in_game": True,
            "mode_key": "aram",
            "gate": "GATE 3 (ARAM Mayhem q2400 KIWI)",
            "champion": "Lee Sin",
            "level": 16,
            "game_time": "15:00",
            "game_mode": "KIWI",
            "game_id": "",
            "ally_team": ["Kled", "Lee Sin"],
            "enemy_team": ["Swain", "Anivia"],
            "coach_source": "deterministic",
            "haiku_credit_paused": True,
            "coach": {"action": "All in now", "immediate": "(paused)", "fight_rule": "cc", "risk": "LOW"},
            "vision": {"frame_bytes": 0, "frame_dead": True, "relay_present": False},
            "serving_surfaces": {"cc_panel_in_state": [], "adapt_fields_in_state": []},
            "minimap_dot_count": 10,
            "zoi_present": True,
        }
        out = g._render(facts)
        self.assertIn("IN-GAME: True", out)
        self.assertIn("DEAD", out)  # zero-byte frame flagged as blocking
        self.assertIn("game-path inert", out)  # empty cc panel flags the substitution trap
        self.assertIn("haiku_credit_paused=True", out)


if __name__ == "__main__":
    unittest.main()
