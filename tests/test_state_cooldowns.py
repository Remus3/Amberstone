"""Tests for ``dashboard._state_cooldowns`` + the ``summoner_cooldowns``
key stamped onto the ``/api/state`` payload by ``build_state()``.

Two layers covered:

1. ``compute_state_cooldowns`` adapter shape (no real game required):
   - lc empty -> None
   - lc non-empty + cached snapshot returns 10 rows in the documented
     shape; spell names map to integer ids; sides translate ORDER/CHAOS.
   - Cache stale (age >= 8s) -> None.
2. End-to-end through ``build_state``:
   - liveclient empty -> ``summoner_cooldowns`` is None.
   - liveclient non-empty -> ``summoner_cooldowns`` is a list of dicts
     matching the spec (puuid/summoner_name/champion_id/side/summs/ult).
"""
from __future__ import annotations

import unittest
from unittest import mock

from dashboard import _state_builder, _state_cooldowns


def _player(idx: int, team: str = "ORDER", d_name: str = "Flash",
            f_name: str = "Ignite", items=None) -> dict:
    return {
        "summonerName": f"Player{idx}",
        "championName": f"Champ{idx}",
        "team": team,
        "summonerSpells": {
            "summonerSpellOne": {"displayName": d_name, "rawDescription": ""},
            "summonerSpellTwo": {"displayName": f_name, "rawDescription": ""},
        },
        "items": [{"itemID": i} for i in (items or [])],
        "scores": {"kills": 0, "deaths": 0, "assists": 0, "creepScore": 0},
        "level": 1,
        "position": "MIDDLE",
        "isDead": False,
    }


def _fake_allgamedata(num_players: int = 10, me_name: str = "Player0",
                     active_runes: list[int] | None = None,
                     me_items: list[int] | None = None) -> dict:
    players: list[dict] = []
    for i in range(num_players):
        team = "ORDER" if i < 5 else "CHAOS"
        items = me_items if i == 0 else None
        players.append(_player(i, team=team, items=items))
    return {
        "allPlayers": players,
        "activePlayer": {
            "summonerName": me_name,
            "level": 1,
            "currentGold": 0,
            "championStats": {"currentHealth": 1, "maxHealth": 1,
                              "resourceValue": 0, "resourceMax": 0},
            "fullRunes": {
                "keystone": {"id": 8347},  # Cosmic Insight as keystone (synthetic)
                "generalRunes": [
                    {"id": r} for r in (active_runes or [])
                ],
            },
        },
        "gameData": {"gameTime": 60.0, "gameMode": "CLASSIC", "gameId": 1234},
        "events": {"Events": []},
    }


class _FakeSnap:
    def __init__(self, data, age_s: float = 0.0):
        self.data = data
        self.ts = 0.0
        self.fetched_at = 0.0
        self.no_game = False
        self._age = age_s

    @property
    def age_s(self) -> float:
        return self._age


# ---------------------------------------------------------------------------
# compute_state_cooldowns adapter
# ---------------------------------------------------------------------------

class ComputeStateCooldownsAdapterTests(unittest.TestCase):

    def test_lc_empty_returns_none(self):
        """No live game -> adapter returns None."""
        self.assertIsNone(_state_cooldowns.compute_state_cooldowns(None))
        self.assertIsNone(_state_cooldowns.compute_state_cooldowns({}))

    def test_lc_non_empty_returns_ten_rows(self):
        """10-player allgamedata -> 10-entry list, shape per spec."""
        data = _fake_allgamedata(num_players=10)
        with mock.patch("core.liveclient_cache.get",
                        return_value=_FakeSnap(data, age_s=0.5)):
            out = _state_cooldowns.compute_state_cooldowns(
                {"champion": "Champ0"})  # lc just has to be truthy
        self.assertIsNotNone(out)
        self.assertEqual(len(out), 10)
        row0 = out[0]
        self.assertEqual(
            set(row0.keys()),
            {"puuid", "summoner_name", "champion_id", "side", "summs", "ult"},
        )
        s = row0["summs"]
        self.assertEqual(
            set(s.keys()),
            {"d_id", "d_name", "d_used_at_s", "d_ready_at_s", "d_cd_remaining_s",
             "f_id", "f_name", "f_used_at_s", "f_ready_at_s", "f_cd_remaining_s",
             "summoner_haste"},
        )
        u = row0["ult"]
        self.assertEqual(
            set(u.keys()),
            {"id", "used_at_s", "ready_at_s", "cd_remaining_s", "ability_haste"},
        )

    def test_spell_names_map_to_riot_ids(self):
        """displayName 'Flash' -> 4, 'Ignite' -> 14."""
        data = _fake_allgamedata(num_players=1)
        with mock.patch("core.liveclient_cache.get",
                        return_value=_FakeSnap(data, age_s=0.5)):
            out = _state_cooldowns.compute_state_cooldowns({"any": True})
        self.assertEqual(out[0]["summs"]["d_id"], 4)   # Flash
        self.assertEqual(out[0]["summs"]["f_id"], 14)  # Ignite
        self.assertEqual(out[0]["summs"]["d_name"], "Flash")
        self.assertEqual(out[0]["summs"]["f_name"], "Ignite")

    def test_unknown_spell_name_maps_to_none(self):
        """Cherry Flash / Poro Toss / Mark fall to None (renders READY 0-cd)."""
        data = _fake_allgamedata(num_players=1)
        data["allPlayers"][0]["summonerSpells"]["summonerSpellOne"]["displayName"] = "Poro Toss"
        with mock.patch("core.liveclient_cache.get",
                        return_value=_FakeSnap(data, age_s=0.5)):
            out = _state_cooldowns.compute_state_cooldowns({"any": True})
        self.assertIsNone(out[0]["summs"]["d_id"])
        # READY since base CD is 0 for unknown id.
        self.assertEqual(out[0]["summs"]["d_cd_remaining_s"], 0.0)

    def test_side_translation_order_and_chaos(self):
        """ORDER -> blue, CHAOS -> red."""
        data = _fake_allgamedata(num_players=10)
        with mock.patch("core.liveclient_cache.get",
                        return_value=_FakeSnap(data, age_s=0.5)):
            out = _state_cooldowns.compute_state_cooldowns({"any": True})
        sides = sorted({r["side"] for r in out})
        self.assertEqual(sides, ["blue", "red"])

    def test_stale_cache_returns_none(self):
        """Snapshot age >= 8 s -> caller treats as no live data."""
        data = _fake_allgamedata(num_players=10)
        with mock.patch("core.liveclient_cache.get",
                        return_value=_FakeSnap(data, age_s=12.0)):
            out = _state_cooldowns.compute_state_cooldowns({"any": True})
        self.assertIsNone(out)

    def test_cache_no_data_returns_none(self):
        """Snapshot.data is None -> None."""
        with mock.patch("core.liveclient_cache.get",
                        return_value=_FakeSnap(None, age_s=0.0)):
            out = _state_cooldowns.compute_state_cooldowns({"any": True})
        self.assertIsNone(out)

    def test_active_player_items_propagate(self):
        """Operator's items reach the adapter as integer ids -> CDR applies."""
        # Item 3158 = Ionian Boots of Lucidity -> -10 percent on summs.
        # Without an event, ready_at_s is 0 anyway; we just sanity-check the
        # items list was actually wired by inspecting the adapter's
        # participants directly.
        data = _fake_allgamedata(num_players=1, me_items=[3158, 3001])
        ps = _state_cooldowns._participants_from_liveclient(data)
        self.assertEqual(ps[0]["items"], [3158, 3001])

    def test_active_player_runes_only_to_self(self):
        """Only the active player gets the rune list; others stay [] ."""
        data = _fake_allgamedata(num_players=3, active_runes=[8009])
        ps = _state_cooldowns._participants_from_liveclient(data)
        # Player0 is the active player in our fixture.
        self.assertIn(8347, ps[0]["runes"])   # keystone
        self.assertIn(8009, ps[0]["runes"])   # general
        self.assertEqual(ps[1]["runes"], [])
        self.assertEqual(ps[2]["runes"], [])

    def test_events_from_liveclient_is_empty(self):
        """Live Client never emits SUMMONER_SPELL_USED -> we ship []."""
        data = _fake_allgamedata(num_players=10)
        evs = _state_cooldowns._events_from_liveclient(data)
        self.assertEqual(evs, [])

    def test_exception_in_liveclient_cache_returns_none(self):
        """Any exception in the cache lookup degrades to None (fail-soft)."""
        with mock.patch(
            "core.liveclient_cache.get",
            side_effect=RuntimeError("boom"),
        ):
            out = _state_cooldowns.compute_state_cooldowns({"any": True})
        self.assertIsNone(out)


# ---------------------------------------------------------------------------
# Hextech Drake event -> participant.hextech_drakes wire
# ---------------------------------------------------------------------------

class HextechDrakeWireTests(unittest.TestCase):
    """Item-110 carry-forward (c): wire DragonKill+DragonType=Hextech events
    from gameData.events.Events into each participant's ``hextech_drakes``
    field. Killer's team gets the stack; other team unaffected. The CD ledger
    is per-participant so every player on that team sees their team's count.
    """

    def _drake_event(self, killer_name: str, dragon_type: str = "Hextech",
                     event_id: int = 1, event_time: float = 120.0) -> dict:
        return {
            "EventID": event_id,
            "EventName": "DragonKill",
            "DragonType": dragon_type,
            "KillerName": killer_name,
            "EventTime": event_time,
        }

    def test_zero_drakes_default_zero_per_participant(self):
        """No DragonKill events -> every participant sees hextech_drakes=0."""
        data = _fake_allgamedata(num_players=10)
        ps = _state_cooldowns._participants_from_liveclient(data)
        for p in ps:
            self.assertEqual(p["hextech_drakes"], 0)

    def test_ally_hextech_only_increments_ally_team(self):
        """1 Hextech killed by an ally (Player0, team ORDER) ->
        ally team count=1, enemy team (CHAOS) count=0.
        """
        data = _fake_allgamedata(num_players=10)
        data["events"]["Events"] = [self._drake_event("Player0")]
        ps = _state_cooldowns._participants_from_liveclient(data)
        # Players 0..4 are ORDER, 5..9 are CHAOS in the fixture.
        for p in ps[:5]:
            self.assertEqual(p["hextech_drakes"], 1)
        for p in ps[5:]:
            self.assertEqual(p["hextech_drakes"], 0)

    def test_enemy_hextech_only_increments_enemy_team(self):
        """1 Hextech killed by an enemy (Player7, CHAOS) ->
        enemy count=1, ally count=0.
        """
        data = _fake_allgamedata(num_players=10)
        data["events"]["Events"] = [self._drake_event("Player7")]
        ps = _state_cooldowns._participants_from_liveclient(data)
        for p in ps[:5]:
            self.assertEqual(p["hextech_drakes"], 0)
        for p in ps[5:]:
            self.assertEqual(p["hextech_drakes"], 1)

    def test_two_hextechs_for_enemy_team_stack_to_two(self):
        """2 Hextechs both killed by CHAOS -> enemy count=2 -> +10 AH on ult."""
        data = _fake_allgamedata(num_players=10)
        data["events"]["Events"] = [
            self._drake_event("Player7", event_id=1, event_time=300.0),
            self._drake_event("Player8", event_id=2, event_time=600.0),
        ]
        ps = _state_cooldowns._participants_from_liveclient(data)
        for p in ps[:5]:
            self.assertEqual(p["hextech_drakes"], 0)
        for p in ps[5:]:
            self.assertEqual(p["hextech_drakes"], 2)

    def test_non_hextech_dragon_types_ignored(self):
        """Earth/Air/Fire/Water/Elder DragonKill events do NOT add Hextech stacks."""
        data = _fake_allgamedata(num_players=10)
        data["events"]["Events"] = [
            self._drake_event("Player0", dragon_type="Earth", event_id=1),
            self._drake_event("Player0", dragon_type="Air", event_id=2),
            self._drake_event("Player0", dragon_type="Fire", event_id=3),
            self._drake_event("Player0", dragon_type="Water", event_id=4),
            self._drake_event("Player0", dragon_type="Elder", event_id=5),
        ]
        ps = _state_cooldowns._participants_from_liveclient(data)
        for p in ps:
            self.assertEqual(p["hextech_drakes"], 0)

    def test_malformed_events_dropped_safely(self):
        """Missing EventName, missing DragonType, missing KillerName,
        unresolved KillerName, non-dict entries - all dropped, no crash.
        """
        data = _fake_allgamedata(num_players=10)
        data["events"]["Events"] = [
            None,                                                  # Non-dict
            42,                                                    # Non-dict
            {},                                                    # No EventName
            {"EventName": "DragonKill"},                           # No DragonType
            {"EventName": "DragonKill", "DragonType": "Hextech"},  # No KillerName
            {"EventName": "DragonKill", "DragonType": "Hextech",
             "KillerName": "Ghost42"},                             # Unknown killer
            {"EventName": "ChampionKill", "DragonType": "Hextech",
             "KillerName": "Player0"},                             # Wrong event
            self._drake_event("Player0"),                          # 1 good
        ]
        ps = _state_cooldowns._participants_from_liveclient(data)
        self.assertEqual(ps[0]["hextech_drakes"], 1)
        self.assertEqual(ps[5]["hextech_drakes"], 0)

    def test_mixed_dragon_types_counts_only_hextech(self):
        """Mixed Hextech + other dragons -> only Hextechs count toward the stack."""
        data = _fake_allgamedata(num_players=10)
        data["events"]["Events"] = [
            self._drake_event("Player0", dragon_type="Earth", event_id=1),
            self._drake_event("Player0", dragon_type="Hextech", event_id=2),
            self._drake_event("Player0", dragon_type="Fire", event_id=3),
            self._drake_event("Player7", dragon_type="Hextech", event_id=4),
            self._drake_event("Player7", dragon_type="Hextech", event_id=5),
            self._drake_event("Player7", dragon_type="Elder", event_id=6),
        ]
        ps = _state_cooldowns._participants_from_liveclient(data)
        for p in ps[:5]:
            self.assertEqual(p["hextech_drakes"], 1)
        for p in ps[5:]:
            self.assertEqual(p["hextech_drakes"], 2)

    def test_events_block_missing_or_malformed(self):
        """Missing events block, non-dict events, missing Events list, non-list -> 0 across the board."""
        # Missing whole block
        data = _fake_allgamedata(num_players=2)
        data.pop("events", None)
        ps = _state_cooldowns._participants_from_liveclient(data)
        for p in ps:
            self.assertEqual(p["hextech_drakes"], 0)

        # Non-dict events block
        data = _fake_allgamedata(num_players=2)
        data["events"] = "not a dict"
        ps = _state_cooldowns._participants_from_liveclient(data)
        for p in ps:
            self.assertEqual(p["hextech_drakes"], 0)

        # Missing Events list
        data = _fake_allgamedata(num_players=2)
        data["events"] = {}
        ps = _state_cooldowns._participants_from_liveclient(data)
        for p in ps:
            self.assertEqual(p["hextech_drakes"], 0)

        # Non-list Events
        data = _fake_allgamedata(num_players=2)
        data["events"] = {"Events": "not a list"}
        ps = _state_cooldowns._participants_from_liveclient(data)
        for p in ps:
            self.assertEqual(p["hextech_drakes"], 0)

    def test_helper_returns_dict_keyed_by_team_strings(self):
        """``_hextech_drakes_by_team`` keys are the raw ORDER/CHAOS team strings
        (NOT the blue/red side aliases) - they match ``allPlayers[].team`` directly.
        """
        data = _fake_allgamedata(num_players=10)
        data["events"]["Events"] = [
            self._drake_event("Player0"),                          # ORDER kill
            self._drake_event("Player7"),                          # CHAOS kill
            self._drake_event("Player8"),                          # CHAOS kill
        ]
        counts = _state_cooldowns._hextech_drakes_by_team(data)
        self.assertEqual(counts.get("ORDER"), 1)
        self.assertEqual(counts.get("CHAOS"), 2)

    def test_hextech_drakes_propagate_through_compute_state_cooldowns(self):
        """End-to-end: enemy Hextech drake -> ult.ability_haste increases by 5 per stack."""
        data = _fake_allgamedata(num_players=10)
        # CHAOS team killed 2 Hextechs.
        data["events"]["Events"] = [
            self._drake_event("Player7", event_id=1),
            self._drake_event("Player8", event_id=2),
        ]
        with mock.patch("core.liveclient_cache.get",
                        return_value=_FakeSnap(data, age_s=0.5)):
            out = _state_cooldowns.compute_state_cooldowns({"any": True})
        # Pull rows back out by side; sort order is by next-up CD which
        # is the same for everyone with no events, so we just verify each
        # red row has ability_haste >= 10 and each blue row has 0.
        red_rows = [r for r in out if r["side"] == "red"]
        blue_rows = [r for r in out if r["side"] == "blue"]
        self.assertEqual(len(red_rows), 5)
        self.assertEqual(len(blue_rows), 5)
        for r in red_rows:
            self.assertEqual(r["ult"]["ability_haste"], 10.0)
        for r in blue_rows:
            self.assertEqual(r["ult"]["ability_haste"], 0.0)


# ---------------------------------------------------------------------------
# build_state stamping
# ---------------------------------------------------------------------------

class BuildStateSummonerCooldownsStampingTests(unittest.TestCase):

    def _common_patches(self, lc, allgamedata):
        """Mock the same set as test_state_builder_archetype_nudge for parity."""
        health = {"alive": True, "pid": 1, "mode": "client",
                  "ui_pulse_age_s": 0}
        return [
            mock.patch.object(
                _state_builder, "read_json",
                side_effect=lambda p: health if p == "ops/runtime/health.json"
                else {},
            ),
            mock.patch.object(_state_builder, "lcu_summary", return_value={}),
            mock.patch.object(_state_builder, "liveclient_summary", return_value=lc),
            mock.patch.object(_state_builder, "get_team_context", return_value=None),
            mock.patch.object(
                _state_builder, "validate_coaching_payload",
                lambda *_a, **_k: None,
            ),
            mock.patch(
                "core.archetype_picks.get_archetype_for",
                return_value={},
            ),
            mock.patch(
                "core.archetype_mismatch.compute_nudge_payload",
                return_value={},
            ),
            mock.patch("coaches.sr_draft_profile.is_sr_draft_queue",
                       return_value=False),
            mock.patch("core.liveclient_cache.get",
                       return_value=_FakeSnap(allgamedata, age_s=0.5)
                       if allgamedata else _FakeSnap(None)),
        ]

    def _run(self, lc, allgamedata):
        patches = self._common_patches(lc, allgamedata)
        for p in patches:
            p.start()
        try:
            return _state_builder.build_state()
        finally:
            for p in reversed(patches):
                p.stop()

    def test_lobby_returns_null_summoner_cooldowns(self):
        """No game (lc empty) -> summoner_cooldowns is null."""
        state = self._run(lc={}, allgamedata=None)
        self.assertIn("summoner_cooldowns", state)
        self.assertIsNone(state["summoner_cooldowns"])

    def test_in_game_returns_ten_entry_list(self):
        """liveclient non-empty + 10-player snapshot -> 10-entry list."""
        data = _fake_allgamedata(num_players=10)
        state = self._run(lc={"champion": "Champ0", "game_time_s": 60},
                          allgamedata=data)
        self.assertIn("summoner_cooldowns", state)
        cds = state["summoner_cooldowns"]
        self.assertIsNotNone(cds)
        self.assertIsInstance(cds, list)
        self.assertEqual(len(cds), 10)
        # Spot-check the documented shape on the first row.
        row = cds[0]
        self.assertIn("summoner_name", row)
        self.assertIn("summs", row)
        self.assertIn("ult", row)
        self.assertIn("d_cd_remaining_s", row["summs"])
        self.assertIn("cd_remaining_s", row["ult"])

    def test_in_game_with_stale_cache_falls_back_to_null(self):
        """lc non-empty but the cache went stale -> still null."""
        # Build the patch set but override the cache mock to stale.
        health = {"alive": True, "pid": 1, "mode": "client",
                  "ui_pulse_age_s": 0}
        with (
            mock.patch.object(_state_builder, "read_json",
                              side_effect=lambda p: health
                              if p == "ops/runtime/health.json" else {}),
            mock.patch.object(_state_builder, "lcu_summary", return_value={}),
            mock.patch.object(_state_builder, "liveclient_summary",
                              return_value={"champion": "Champ0"}),
            mock.patch.object(_state_builder, "get_team_context",
                              return_value=None),
            mock.patch.object(_state_builder, "validate_coaching_payload",
                              lambda *_a, **_k: None),
            mock.patch("core.archetype_picks.get_archetype_for",
                       return_value={}),
            mock.patch("core.archetype_mismatch.compute_nudge_payload",
                       return_value={}),
            mock.patch("coaches.sr_draft_profile.is_sr_draft_queue",
                       return_value=False),
            mock.patch("core.liveclient_cache.get",
                       return_value=_FakeSnap(_fake_allgamedata(num_players=10),
                                              age_s=20.0)),
        ):
            state = _state_builder.build_state()
        self.assertIsNone(state["summoner_cooldowns"])


if __name__ == "__main__":
    unittest.main()
