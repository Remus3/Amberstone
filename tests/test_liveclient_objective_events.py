"""Tests for the RC2 P5.7 (WS4) ``objective_events`` list emitted by
``dashboard/_liveclient.py`` :: ``liveclient_summary``.

The Live Client ``gameData.events.Events`` stream carries DragonKill / BaronKill
/ HeraldKill events (same stream that feeds inhib_events). The summary surfaces a
parallel ``objective_events`` list of ``{name, killer_team, down_at_s}`` where
``killer_team`` is classified by matching ``KillerName`` against the enemy / ally
rosters. ``core.macro_response`` keys the lost-objective response on enemy kills.

Covers: a normal enemy + ally objective kill (team classification + name map),
the unknown-killer fallback, non-objective events skipped, malformed-event
fail-soft, and the ASCII module guard. Reuses the urlopen-monkeypatch fixture
shape from test_liveclient_kp.py.
"""
from __future__ import annotations

import contextlib
import json
import time
import unittest
from pathlib import Path
from unittest import mock

from dashboard import _liveclient


def _player(name: str, team: str) -> dict:
    return {"summonerName": name, "championName": name, "team": team,
            "items": [], "scores": {"kills": 0, "deaths": 0, "assists": 0,
                                    "creepScore": 0, "wardScore": 0.0}}


def _allgamedata(active_name: str, players: list, events: list,
                 game_time: float = 1300.0) -> dict:
    return {
        "activePlayer": {
            "summonerName": active_name, "level": 14, "currentGold": 1200,
            "championStats": {"currentHealth": 1500, "maxHealth": 2000,
                              "resourceValue": 200, "resourceMax": 300},
        },
        "allPlayers": players,
        "gameData": {"gameTime": game_time, "gameMode": "CLASSIC",
                     "events": {"Events": events}},
    }


@contextlib.contextmanager
def _patched(allgamedata, ts=None):
    wrap = {"ts": time.time() if ts is None else ts, "data": allgamedata}
    payload = json.dumps(wrap).encode("utf-8")

    class _Resp:
        def __enter__(self_inner):
            return self_inner

        def __exit__(self_inner, *exc):
            return False

        def read(self_inner):
            return payload

    with mock.patch.object(_liveclient.urllib.request, "urlopen",
                           return_value=_Resp()):
        yield


def _summary(allgamedata, ts=None) -> dict:
    with _patched(allgamedata, ts=ts):
        return _liveclient.liveclient_summary()


# A standard 5v5 roster: active "Ashe" on ORDER, enemies on CHAOS.
_PLAYERS = [
    _player("Ashe", "ORDER"), _player("Leona", "ORDER"),
    _player("Zed", "CHAOS"), _player("Lux", "CHAOS"), _player("Thresh", "CHAOS"),
]


class ObjectiveEventsTests(unittest.TestCase):
    def test_enemy_dragon_kill_classified(self) -> None:
        events = [{"EventName": "DragonKill", "EventTime": 1290.0,
                   "KillerName": "Zed", "DragonType": "Fire"}]
        out = _summary(_allgamedata("Ashe", _PLAYERS, events))
        oes = out.get("objective_events")
        self.assertEqual(len(oes), 1)
        self.assertEqual(oes[0]["name"], "dragon")
        self.assertEqual(oes[0]["killer_team"], "enemy")
        self.assertEqual(oes[0]["down_at_s"], 1290.0)

    def test_ally_baron_kill_classified(self) -> None:
        events = [{"EventName": "BaronKill", "EventTime": 1295.0,
                   "KillerName": "Leona"}]
        out = _summary(_allgamedata("Ashe", _PLAYERS, events))
        oes = out["objective_events"]
        self.assertEqual(oes[0]["name"], "baron")
        self.assertEqual(oes[0]["killer_team"], "ally")

    def test_dragon_type_captured_for_elder_discriminator(self) -> None:
        # DragonKill carries a DragonType; surface it as an additive key so the
        # epic-buff countdown can tell Elder from an elemental drake. name stays
        # "dragon" (macro_response unchanged).
        events = [{"EventName": "DragonKill", "EventTime": 2000.0,
                   "KillerName": "Ashe", "DragonType": "Elder"}]
        out = _summary(_allgamedata("Ashe", _PLAYERS, events, game_time=2050.0))
        oes = out["objective_events"]
        self.assertEqual(oes[0]["name"], "dragon")
        self.assertEqual(oes[0]["dragon_type"], "Elder")
        self.assertEqual(oes[0]["killer_team"], "ally")

    def test_baron_kill_has_no_dragon_type(self) -> None:
        events = [{"EventName": "BaronKill", "EventTime": 1295.0,
                   "KillerName": "Leona"}]
        out = _summary(_allgamedata("Ashe", _PLAYERS, events))
        self.assertNotIn("dragon_type", out["objective_events"][0])

    def test_herald_and_unknown_killer(self) -> None:
        events = [{"EventName": "HeraldKill", "EventTime": 800.0,
                   "KillerName": "Minion_CHAOS"}]
        out = _summary(_allgamedata("Ashe", _PLAYERS, events))
        oes = out["objective_events"]
        self.assertEqual(oes[0]["name"], "herald")
        self.assertEqual(oes[0]["killer_team"], "unknown")

    def test_non_objective_events_skipped(self) -> None:
        events = [
            {"EventName": "ChampionKill", "EventTime": 100.0, "KillerName": "Zed"},
            {"EventName": "TurretKilled", "EventTime": 200.0, "KillerName": "Zed"},
            {"EventName": "InhibKilled", "EventTime": 300.0, "KillerName": "Zed"},
            {"EventName": "DragonKill", "EventTime": 1290.0, "KillerName": "Zed"},
        ]
        out = _summary(_allgamedata("Ashe", _PLAYERS, events))
        self.assertEqual(len(out["objective_events"]), 1)  # only the dragon
        self.assertEqual(out["objective_events"][0]["name"], "dragon")

    def test_malformed_event_no_raise(self) -> None:
        events = ["bad", 7, None, {"EventName": "DragonKill"},  # no EventTime
                  {"EventName": "BaronKill", "EventTime": "soon", "KillerName": "Zed"},
                  {"EventName": "DragonKill", "EventTime": 1290.0, "KillerName": "Zed"}]
        out = _summary(_allgamedata("Ashe", _PLAYERS, events))
        self.assertEqual(len(out["objective_events"]), 1)  # only the valid one

    def test_no_events_empty_list(self) -> None:
        out = _summary(_allgamedata("Ashe", _PLAYERS, []))
        self.assertEqual(out["objective_events"], [])


class AsciiHygieneTests(unittest.TestCase):
    def test_module_is_ascii(self) -> None:
        text = Path(_liveclient.__file__).read_text(encoding="utf-8")
        for cp in (0x2013, 0x2014, 0x2018, 0x2019, 0x201C, 0x201D):
            self.assertNotIn(chr(cp), text)


if __name__ == "__main__":
    unittest.main()
