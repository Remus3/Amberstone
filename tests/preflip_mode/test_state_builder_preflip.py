"""Tests for dashboard._state_builder pre-flip from LCU queue_id.

Pins the contract that when the LiveClient mode flag is dark
(arena_mode/aram_mode/tft_mode/has_game all false), the dashboard
pre-flips mode_key from the LCU lobby/champ-select queue_id so the
right per-mode coach panel renders during the lobby/champ-select
window.

LiveClient flags are authoritative once the game is running, so
those tests pin the priority order too.
"""
from __future__ import annotations

import unittest
from unittest import mock

from dashboard import _state_builder


def _empty_health() -> dict:
    return {"alive": True, "pid": 1, "mode": "client",
            "has_game": False, "ui_pulse_age_s": 0.1,
            "game_poll_worker_age_s": 0.1}


class TestPreflipModeFromLcu(unittest.TestCase):
    """Direct unit tests for the pre-flip helper."""

    def test_champ_select_queue_id_wins(self):
        snap = {"champ_select": {"queue_id": 1700},
                "lobby":         {"queue_id": 450}}
        self.assertEqual(_state_builder._preflip_mode_from_lcu(snap), "arena")

    def test_lobby_used_when_champ_select_missing(self):
        snap = {"lobby": {"queue_id": 1700, "is_custom": False}}
        self.assertEqual(_state_builder._preflip_mode_from_lcu(snap), "arena")

    def test_lobby_skipped_when_custom(self):
        # Custom games / Practice Tool carry the queue_id of whatever
        # mode template they're built off of, but they shouldn't drive
        # the dashboard panel — there's no coach payload for customs.
        snap = {"lobby": {"queue_id": 1700, "is_custom": True}}
        self.assertIsNone(_state_builder._preflip_mode_from_lcu(snap))

    def test_unknown_queue_id_falls_through(self):
        snap = {"lobby": {"queue_id": 99999, "is_custom": False}}
        self.assertIsNone(_state_builder._preflip_mode_from_lcu(snap))

    def test_no_lcu_returns_none(self):
        self.assertIsNone(_state_builder._preflip_mode_from_lcu(None))
        self.assertIsNone(_state_builder._preflip_mode_from_lcu({}))


class TestBuildStateModeResolution(unittest.TestCase):
    """End-to-end mode_key resolution via build_state()."""

    def setUp(self):
        # Stub the heavy IO bits of build_state — we only care about
        # mode_key resolution here.
        self._patches = [
            mock.patch.object(_state_builder, "validate_coaching_payload",
                              lambda x: None),
            mock.patch.object(_state_builder, "liveclient_summary",
                              return_value={}),
            mock.patch.object(_state_builder, "get_team_context",
                              return_value=None),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in reversed(self._patches):
            p.stop()

    def _run(self, health: dict, lcu: dict, coach: dict | None = None) -> dict:
        coach = coach or {}

        def _read_json(path: str) -> dict:
            if path.endswith("health.json"):
                return health
            return dict(coach)

        with mock.patch.object(_state_builder, "read_json",
                               side_effect=_read_json), \
             mock.patch.object(_state_builder, "lcu_summary",
                               return_value=lcu):
            return _state_builder.build_state()

    def test_liveclient_arena_mode_overrides_lcu(self):
        # LiveClient says arena, LCU still in lobby for an aram queue
        # (impossible but pins priority): LiveClient wins.
        health = _empty_health() | {"arena_mode": True}
        lcu = {"lobby": {"queue_id": 450, "is_custom": False}}
        out = self._run(health, lcu)
        self.assertEqual(out["mode_key"], "arena")

    def test_lcu_arena_lobby_preflips_when_liveclient_dark(self):
        health = _empty_health()  # all mode flags false
        lcu = {"lobby": {"queue_id": 1700, "is_custom": False}}
        out = self._run(health, lcu)
        self.assertEqual(out["mode_key"], "arena")
        self.assertEqual(out["coach_source"], "data/arena_coaching_data.json")

    def test_lcu_champ_select_aram_preflips(self):
        health = _empty_health()
        lcu = {"champ_select": {"queue_id": 450}}
        out = self._run(health, lcu)
        self.assertEqual(out["mode_key"], "aram")
        self.assertEqual(out["coach_source"], "data/aram_coaching_data.json")

    def test_no_lcu_falls_back_to_client(self):
        health = _empty_health()
        out = self._run(health, {})
        self.assertEqual(out["mode_key"], "client")

    def test_unknown_lcu_queue_falls_back_to_client(self):
        health = _empty_health()
        lcu = {"lobby": {"queue_id": 99999, "is_custom": False}}
        out = self._run(health, lcu)
        self.assertEqual(out["mode_key"], "client")

    def test_custom_lobby_does_not_preflip(self):
        health = _empty_health()
        lcu = {"lobby": {"queue_id": 1700, "is_custom": True}}
        out = self._run(health, lcu)
        self.assertEqual(out["mode_key"], "client")

    def test_health_mode_field_still_used_when_no_lcu_match(self):
        # If LiveClient is dark AND LCU has no recognised queue, but
        # health.mode is explicitly stamped (e.g. legacy code path),
        # we honor it rather than dropping to "client".
        health = _empty_health() | {"mode": "tft"}
        out = self._run(health, {})
        self.assertEqual(out["mode_key"], "tft")


if __name__ == "__main__":
    unittest.main()
