"""item 281: ``coach.cleared_at`` force-clear sentinel must be honored.

Bug: an operator force-clear wrote ``cleared_at`` into a coaching artifact
(``data/aram_coaching_data.json``) but nothing consumed it, so the stale
11-day-old Kai'Sa game kept rendering as a live ACTIVE MATCH whenever
``mode_key`` resolved back to ARAM (e.g. sitting in an ARAM Mayhem lobby).

``apply_cleared_at`` blanks the served coach payload when the sentinel is
present AND there is no live game to overlay. A real game overwrites the
artifact without the sentinel, so live coaching is unaffected.
"""
from __future__ import annotations

import unittest
from unittest import mock

from dashboard import _state_builder
from dashboard._state_builder import apply_cleared_at


class ApplyClearedAtTests(unittest.TestCase):
    def test_blanks_when_sentinel_and_no_live_game(self):
        coach = {
            "cleared_at": 1779562489.0,
            "action": "WAIT RESPAWN",
            "kda": "13/7/15",
            "game_time": "14:54",
            "champion": "Kai'Sa",
        }
        self.assertEqual(apply_cleared_at(coach, None), {})
        self.assertEqual(apply_cleared_at(coach, {}), {})

    def test_keeps_payload_when_live_game_present(self):
        # Defensive: a live game overlay must never be hidden, even if a
        # stray sentinel is present.
        coach = {"cleared_at": 1.0, "action": "WAIT"}
        lc = {"champion": "Kai'Sa", "game_time": "14:54"}
        self.assertIs(apply_cleared_at(coach, lc), coach)

    def test_noop_without_sentinel(self):
        coach = {"action": "PUSH", "kda": "1/0/2"}
        self.assertIs(apply_cleared_at(coach, None), coach)

    def test_non_dict_safe(self):
        self.assertEqual(apply_cleared_at(None, None), None)
        self.assertEqual(apply_cleared_at("nope", None), "nope")


class BuildStateHonorsClearedAtTests(unittest.TestCase):
    """End-to-end: build_state must not surface a cleared artifact's
    live-game fields when idle."""

    def _patch(self, *, health, coach_payload, lc_payload):
        def _read_json(p):
            if "health" in str(p):
                return health
            return coach_payload

        for p in [
            mock.patch.object(_state_builder, "read_json", side_effect=_read_json),
            mock.patch.object(_state_builder, "lcu_summary", return_value={}),
            mock.patch.object(_state_builder, "liveclient_summary",
                              return_value=(lc_payload or {})),
            mock.patch.object(_state_builder, "get_team_context", return_value=None),
            mock.patch.object(_state_builder, "validate_coaching_payload",
                              lambda *_a, **_kw: None),
        ]:
            p.start()
            self.addCleanup(p.stop)

    def test_cleared_aram_artifact_not_served_as_live(self):
        self._patch(
            health={"mode": "client", "aram_mode": True},
            coach_payload={
                "cleared_at": 1779562489.0,
                "action": "WAIT RESPAWN",
                "kda": "13/7/15",
                "game_time": "14:54",
                "champion": "Kai'Sa",
                "items_display": "Infinity Edge, Hubris",
            },
            lc_payload=None,
        )
        state = _state_builder.build_state()
        coach = state["coach"]
        # Stale live-game fields must be gone.
        self.assertNotIn("action", coach)
        self.assertNotIn("kda", coach)
        self.assertNotIn("champion", coach)
        self.assertNotIn("game_time", coach)
        # mode_key still reflects the ARAM lobby (pill/lobby view is fine).
        self.assertEqual(state["mode_key"], "aram")

    def test_live_aram_game_still_served(self):
        # With a live game the same artifact (sans sentinel) flows through.
        self._patch(
            health={"mode": "client", "aram_mode": True},
            coach_payload={"action": "TRADE", "champion": "Kai'Sa"},
            lc_payload={"champion": "Kai'Sa", "game_time": "03:10"},
        )
        state = _state_builder.build_state()
        self.assertEqual(state["coach"].get("action"), "TRADE")


if __name__ == "__main__":
    unittest.main()
