"""Tests for the s184 (2026-05-13) ``archetype_nudge`` stamping in
dashboard/_state_builder.py.

Three focal areas:
1. ``build_state()`` includes ``archetype_nudge`` in the envelope.
2. Empty payload when no mismatch evaluator signal is available.
3. Hot path forwards the nudge dict through unchanged.

Mocks at the same boundary as ``test_state_builder_archetype_pick`` —
``lcu_summary`` / ``liveclient_summary`` / ``read_json`` /
``get_archetype_for`` — plus the new ``compute_nudge_payload`` boundary
so we don't need a live DS server.
"""
from __future__ import annotations

import unittest
from unittest import mock

from dashboard import _state_builder


class BuildStateStampsNudgeTests(unittest.TestCase):

    def _patches(self, health=None, lcu=None, lc=None, coach=None, nudge=None):
        """Bundle the standard mock set used by every test below."""
        health = health or {"alive": True, "pid": 1, "mode": "client", "ui_pulse_age_s": 0}
        lcu = lcu or {}
        lc = lc or {}
        coach = coach or {}
        return [
            mock.patch.object(
                _state_builder, "read_json",
                side_effect=lambda p: health if p == "ops/runtime/health.json" else coach,
            ),
            mock.patch.object(_state_builder, "lcu_summary", return_value=lcu),
            mock.patch.object(_state_builder, "liveclient_summary", return_value=lc),
            mock.patch.object(_state_builder, "get_team_context", return_value=None),
            mock.patch(
                "core.archetype_picks.get_archetype_for",
                return_value={"champion": "Nasus", "primary": "tank", "source": "user_cs"},
            ),
            mock.patch(
                "core.archetype_mismatch.compute_nudge_payload",
                return_value=nudge if nudge is not None else {},
            ),
            mock.patch.object(
                _state_builder, "validate_coaching_payload", lambda *_a, **_k: None,
            ),
            mock.patch("coaches.sr_draft_profile.is_sr_draft_queue", return_value=False),
        ]

    def test_state_has_archetype_nudge_key(self):
        with mock.patch.object(
            _state_builder, "read_json",
            return_value={"alive": True, "pid": 1, "mode": "client"},
        ), mock.patch.object(
            _state_builder, "lcu_summary", return_value={},
        ), mock.patch.object(
            _state_builder, "liveclient_summary", return_value={},
        ), mock.patch.object(
            _state_builder, "get_team_context", return_value=None,
        ), mock.patch.object(
            _state_builder, "validate_coaching_payload", lambda *_a, **_k: None,
        ):
            state = _state_builder.build_state()
        self.assertIn("archetype_nudge", state)
        # No champion + no archetype → empty dict
        self.assertEqual(state["archetype_nudge"], {})

    def test_state_carries_fired_nudge(self):
        fired_payload = {
            "fired":           True,
            "phase":           "fired",
            "champion":        "Nasus",
            "primary":         "tank",
            "first_item_id":   "3031",
            "first_item_name": "Infinity Edge",
            "message":         "Picked Tank but bought IE — switch?",
            "expected_items":  ["Warmog's", "Heartsteel"],
        }
        patches = self._patches(
            lc={"champion": "Nasus", "game_id": "g1", "owned_item_ids": ["3031"]},
            nudge=fired_payload,
        )
        for p in patches:
            p.start()
        try:
            state = _state_builder.build_state()
        finally:
            for p in patches:
                p.stop()

        self.assertEqual(state["archetype_nudge"], fired_payload)
        # cs_archetype_pick also present (sibling field)
        self.assertEqual(state["cs_archetype_pick"]["primary"], "tank")

    def test_state_empty_nudge_when_evaluator_returns_empty(self):
        patches = self._patches(
            lc={"champion": "Nasus", "owned_item_ids": []},
            nudge={},
        )
        for p in patches:
            p.start()
        try:
            state = _state_builder.build_state()
        finally:
            for p in patches:
                p.stop()
        self.assertEqual(state["archetype_nudge"], {})

    def test_state_pending_nudge_passthrough(self):
        pending_payload = {
            "fired":    False,
            "phase":    "pending",
            "champion": "Nasus",
            "primary":  "tank",
        }
        patches = self._patches(
            lc={"champion": "Nasus", "owned_item_ids": ["3047"]},
            nudge=pending_payload,
        )
        for p in patches:
            p.start()
        try:
            state = _state_builder.build_state()
        finally:
            for p in patches:
                p.stop()
        self.assertEqual(state["archetype_nudge"], pending_payload)

    def test_state_resilient_to_evaluator_exception(self):
        patches = [
            mock.patch.object(
                _state_builder, "read_json",
                return_value={"alive": True, "pid": 1, "mode": "client"},
            ),
            mock.patch.object(_state_builder, "lcu_summary", return_value={}),
            mock.patch.object(
                _state_builder, "liveclient_summary",
                return_value={"champion": "Nasus", "owned_item_ids": ["3031"]},
            ),
            mock.patch.object(_state_builder, "get_team_context", return_value=None),
            mock.patch(
                "core.archetype_picks.get_archetype_for",
                return_value={"champion": "Nasus", "primary": "tank", "source": "user_cs"},
            ),
            mock.patch(
                "core.archetype_mismatch.compute_nudge_payload",
                side_effect=RuntimeError("boom"),
            ),
            mock.patch.object(
                _state_builder, "validate_coaching_payload", lambda *_a, **_k: None,
            ),
        ]
        for p in patches:
            p.start()
        try:
            state = _state_builder.build_state()
        finally:
            for p in patches:
                p.stop()
        # Exception swallowed → empty dict, no crash
        self.assertEqual(state["archetype_nudge"], {})


if __name__ == "__main__":
    unittest.main()
