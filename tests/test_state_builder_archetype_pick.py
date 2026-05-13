"""Tests for the s182 (2026-05-13) `cs_archetype_pick` stamping in
dashboard/_state_builder.py.

Two focal areas:
1. `_active_champion()` priority order: liveclient > coach > LCU.
2. `build_state()` stamps the dispatcher pick into the envelope when
   champion resolves; empty dict otherwise.

The state-builder reads a few JSON files + an HTTP relay. We mock at the
relay boundary (`lcu_summary` / `liveclient_summary`) plus `read_json`
so tests don't depend on disk state. `get_archetype_for` is also mocked
to keep tests deterministic across DDragon patch refreshes.
"""
from __future__ import annotations

import unittest
from unittest import mock

from dashboard import _state_builder
from dashboard._state_builder import _active_champion


class ActiveChampionResolverTests(unittest.TestCase):
    """Priority: liveclient > coach > LCU > empty."""

    def test_liveclient_wins(self):
        self.assertEqual(
            _active_champion(
                coach={"champion": "Ahri"},
                lc={"champion": "Caitlyn"},
                lcu_snapshot={"champ_select": {"local_pick": {"champion_name": "Lulu"}}},
            ),
            "Caitlyn",
        )

    def test_coach_wins_when_no_liveclient(self):
        self.assertEqual(
            _active_champion(
                coach={"champion": "Ahri"},
                lc=None,
                lcu_snapshot={"champ_select": {"local_pick": {"champion_name": "Lulu"}}},
            ),
            "Ahri",
        )

    def test_lcu_fallback(self):
        self.assertEqual(
            _active_champion(
                coach={},
                lc=None,
                lcu_snapshot={"champ_select": {"local_pick": {"champion_name": "Lulu"}}},
            ),
            "Lulu",
        )

    def test_lcu_local_member_fallback(self):
        # Some payloads use `local_member` instead of `local_pick`.
        self.assertEqual(
            _active_champion(
                coach={},
                lc=None,
                lcu_snapshot={"champ_select": {"local_member": {"championName": "Zed"}}},
            ),
            "Zed",
        )

    def test_lcu_camelcase_field(self):
        self.assertEqual(
            _active_champion(
                coach={},
                lc=None,
                lcu_snapshot={"champ_select": {"local_pick": {"championName": "Garen"}}},
            ),
            "Garen",
        )

    def test_lcu_plain_champion_field(self):
        self.assertEqual(
            _active_champion(
                coach={},
                lc=None,
                lcu_snapshot={"champ_select": {"local_pick": {"champion": "Yasuo"}}},
            ),
            "Yasuo",
        )

    def test_all_missing_returns_empty_string(self):
        self.assertEqual(_active_champion({}, None, None), "")

    def test_lc_empty_dict_falls_through(self):
        self.assertEqual(
            _active_champion(coach={"champion": "Ahri"}, lc={}, lcu_snapshot=None),
            "Ahri",
        )

    def test_lcu_no_champ_select_returns_empty(self):
        self.assertEqual(
            _active_champion(coach={}, lc=None, lcu_snapshot={"lobby": {}}),
            "",
        )

    def test_non_dict_inputs_safe(self):
        # Defensive: callers may pass None even when type hints say dict.
        self.assertEqual(_active_champion(None, None, None), "")
        self.assertEqual(_active_champion("not a dict", "also not", []), "")


class BuildStateStampsArchetypePickTests(unittest.TestCase):
    """`build_state` should stamp `cs_archetype_pick` derived from
    `get_archetype_for(active_champion)`."""

    def _patch_environment(
        self,
        *,
        health: dict | None = None,
        coach_payload: dict | None = None,
        lc_payload: dict | None = None,
        lcu_payload: dict | None = None,
        team_context: dict | None = None,
    ):
        """Returns the started mocks so tests can introspect call args."""
        if health is None:
            health = {"mode": "client"}

        def _read_json(p):
            if "health" in str(p):
                return health
            return coach_payload or {}

        patches = [
            mock.patch.object(_state_builder, "read_json", side_effect=_read_json),
            mock.patch.object(_state_builder, "lcu_summary",
                              return_value=(lcu_payload or {})),
            mock.patch.object(_state_builder, "liveclient_summary",
                              return_value=(lc_payload or {})),
            mock.patch.object(_state_builder, "get_team_context",
                              return_value=team_context),
            mock.patch.object(_state_builder, "validate_coaching_payload",
                              lambda *_a, **_kw: None),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    @mock.patch("core.archetype_picks.get_archetype_for")
    def test_stamps_pick_when_liveclient_has_champion(self, mock_arch):
        mock_arch.return_value = {
            "champion": "Caitlyn", "primary": "carry",
            "secondary": "bruiser", "source": "default",
        }
        self._patch_environment(
            health={"mode": "game", "has_game": True},
            coach_payload={"action": ""},
            lc_payload={"champion": "Caitlyn"},
        )
        state = _state_builder.build_state()
        self.assertEqual(state["cs_archetype_pick"]["primary"], "carry")
        self.assertEqual(state["cs_archetype_pick"]["champion"], "Caitlyn")
        mock_arch.assert_called_with("Caitlyn")

    @mock.patch("core.archetype_picks.get_archetype_for")
    def test_empty_dict_when_no_champion(self, mock_arch):
        # mock should NOT be called when champion is empty
        self._patch_environment(
            health={"mode": "client"},
            coach_payload={},
            lc_payload=None,
            lcu_payload=None,
        )
        state = _state_builder.build_state()
        self.assertEqual(state["cs_archetype_pick"], {})
        mock_arch.assert_not_called()

    @mock.patch("core.archetype_picks.get_archetype_for")
    def test_lcu_pre_game_pick(self, mock_arch):
        mock_arch.return_value = {
            "champion": "Lulu", "primary": "enchanter",
            "secondary": "mage", "source": "user_cs",
        }
        self._patch_environment(
            health={"mode": "client"},
            coach_payload={},
            lc_payload=None,
            lcu_payload={
                "champ_select": {
                    "local_pick": {"champion_name": "Lulu"},
                    "queue_id": 420,
                },
            },
        )
        state = _state_builder.build_state()
        self.assertEqual(state["cs_archetype_pick"]["primary"], "enchanter")
        mock_arch.assert_called_with("Lulu")

    @mock.patch("core.archetype_picks.get_archetype_for")
    def test_arch_lookup_error_returns_empty_dict(self, mock_arch):
        # If archetype lookup raises, the state-builder must not crash —
        # cs_archetype_pick falls back to empty dict.
        mock_arch.side_effect = RuntimeError("synthetic")
        self._patch_environment(
            health={"mode": "game", "has_game": True},
            coach_payload={},
            lc_payload={"champion": "Caitlyn"},
        )
        state = _state_builder.build_state()
        self.assertEqual(state["cs_archetype_pick"], {})


if __name__ == "__main__":
    unittest.main()
