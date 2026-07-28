"""Tests for the R221 ``minion_spawn_events`` list emitted by
``dashboard/_liveclient.py`` :: ``liveclient_summary``.

The Live Client events stream emits a bare ``MinionsSpawning`` marker every
wave: ``{"EventID": int, "EventName": "MinionsSpawning", "EventTime": float}``.
Unlike InhibKilled / TurretKilled (structure name) or DragonKill (DragonType)
it carries NO extra payload key, so the extract surfaces only
``{spawn_at_s, event_id}`` - the wave clock and the stream's own ordinal.

Covers: a single spawn surfaced in the shared extract shape, unrelated events
filtered out, multiple spawns preserved in stream order, an absent / empty
events block degrading to [] instead of raising, malformed entries skipped, and
the anti-regression pin that events nested under ``gameData`` are NOT read (the
Live Client puts ``events`` at the TOP level of allgamedata; a fixture shaped to
that bug hid an empty-list parse for sessions).
"""
from __future__ import annotations

import contextlib
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
    # HARD TRAP: the Live Client /liveclientdata/allgamedata payload puts
    # ``events`` at the TOP LEVEL (a sibling of gameData), NOT inside gameData
    # - verified live 2026-06-27. A fixture that nested events under gameData
    # matched a parse bug 1:1, so the parse looked covered while it emitted
    # nothing in a real game. Keep this fixture top-level.
    return {
        "activePlayer": {
            "summonerName": active_name, "level": 14, "currentGold": 1200,
            "championStats": {"currentHealth": 1500, "maxHealth": 2000,
                              "resourceValue": 200, "resourceMax": 300},
        },
        "allPlayers": players,
        "events": {"Events": events},
        "gameData": {"gameTime": game_time, "gameMode": "CLASSIC"},
    }


@contextlib.contextmanager
def _patched(allgamedata, ts=None):
    # HOT-02 (2026-07-09): seed the shared liveclient cache Snapshot the summary
    # reads, instead of mocking a per-call urlopen.
    from core.liveclient_cache import Snapshot
    snap = Snapshot(data=allgamedata, ts=time.time() if ts is None else ts)
    with mock.patch("core.liveclient_cache.get", return_value=snap):
        yield


def _summary(allgamedata, ts=None) -> dict:
    with _patched(allgamedata, ts=ts):
        return _liveclient.liveclient_summary()


# A standard 5v5 roster: active "Ashe" on ORDER, enemies on CHAOS.
_PLAYERS = [
    _player("Ashe", "ORDER"), _player("Leona", "ORDER"),
    _player("Zed", "CHAOS"), _player("Lux", "CHAOS"), _player("Thresh", "CHAOS"),
]


class MinionSpawnEventsTests(unittest.TestCase):
    def test_single_spawn_surfaced(self) -> None:
        events = [{"EventID": 12, "EventName": "MinionsSpawning",
                   "EventTime": 1290.0}]
        out = _summary(_allgamedata("Ashe", _PLAYERS, events))
        mses = out.get("minion_spawn_events")
        self.assertEqual(mses, [{"spawn_at_s": 1290.0, "event_id": 12}])

    def test_spawn_time_is_float(self) -> None:
        # An int EventTime off the wire must normalize to float, matching the
        # down_at_s convention of the sibling extracts.
        events = [{"EventID": 3, "EventName": "MinionsSpawning",
                   "EventTime": 65}]
        out = _summary(_allgamedata("Ashe", _PLAYERS, events))
        row = out["minion_spawn_events"][0]
        self.assertIsInstance(row["spawn_at_s"], float)
        self.assertEqual(row["spawn_at_s"], 65.0)

    def test_missing_event_id_is_none(self) -> None:
        # EventID is stream metadata, not payload - absent or junk must not
        # drop the row, it degrades to None.
        events = [{"EventName": "MinionsSpawning", "EventTime": 100.0},
                  {"EventID": "x", "EventName": "MinionsSpawning",
                   "EventTime": 130.0}]
        out = _summary(_allgamedata("Ashe", _PLAYERS, events))
        self.assertEqual(out["minion_spawn_events"],
                         [{"spawn_at_s": 100.0, "event_id": None},
                          {"spawn_at_s": 130.0, "event_id": None}])

    def test_unrelated_events_filtered(self) -> None:
        events = [
            {"EventID": 0, "EventName": "GameStart", "EventTime": 0.0},
            {"EventID": 1, "EventName": "MinionsSpawning", "EventTime": 65.0},
            {"EventID": 2, "EventName": "ChampionKill", "EventTime": 200.0,
             "KillerName": "Zed"},
            {"EventID": 3, "EventName": "TurretKilled", "EventTime": 300.0,
             "TurretKilled": "Turret_T1_C_05_A"},
            {"EventID": 4, "EventName": "DragonKill", "EventTime": 400.0,
             "KillerName": "Zed", "DragonType": "Fire"},
        ]
        out = _summary(_allgamedata("Ashe", _PLAYERS, events))
        self.assertEqual(out["minion_spawn_events"],
                         [{"spawn_at_s": 65.0, "event_id": 1}])

    def test_multiple_spawns_in_stream_order(self) -> None:
        events = [
            {"EventID": 1, "EventName": "MinionsSpawning", "EventTime": 65.0},
            {"EventID": 2, "EventName": "ChampionKill", "EventTime": 70.0},
            {"EventID": 3, "EventName": "MinionsSpawning", "EventTime": 95.0},
            {"EventID": 4, "EventName": "MinionsSpawning", "EventTime": 125.0},
        ]
        out = _summary(_allgamedata("Ashe", _PLAYERS, events))
        self.assertEqual([r["spawn_at_s"] for r in out["minion_spawn_events"]],
                         [65.0, 95.0, 125.0])
        self.assertEqual([r["event_id"] for r in out["minion_spawn_events"]],
                         [1, 3, 4])

    def test_no_events_empty_list(self) -> None:
        out = _summary(_allgamedata("Ashe", _PLAYERS, []))
        self.assertEqual(out["minion_spawn_events"], [])

    def test_absent_events_block_empty_list(self) -> None:
        agd = _allgamedata("Ashe", _PLAYERS, [])
        agd.pop("events")
        out = _summary(agd)
        self.assertEqual(out["minion_spawn_events"], [])

    def test_malformed_entries_skipped(self) -> None:
        events = [
            "bad", 7, None, [],
            {"EventName": "MinionsSpawning"},                     # no EventTime
            {"EventName": "MinionsSpawning", "EventTime": None},
            {"EventName": "MinionsSpawning", "EventTime": "soon"},
            {"EventName": "MinionsSpawning", "EventTime": True},   # bool is not a time
            {"EventID": 9, "EventName": "MinionsSpawning", "EventTime": 95.0},
        ]
        out = _summary(_allgamedata("Ashe", _PLAYERS, events))
        self.assertEqual(out["minion_spawn_events"],
                         [{"spawn_at_s": 95.0, "event_id": 9}])

    def test_events_nested_under_gamedata_not_read(self) -> None:
        # ANTI-REGRESSION PIN: reading ``gd.get("events")`` instead of
        # ``d.get("events")`` silently empties every event-derived extract in a
        # real game. A fixture that nests events under gameData must therefore
        # yield [] - if this ever passes with a populated list, the extract is
        # reading the wrong side of the payload.
        agd = _allgamedata("Ashe", _PLAYERS, [])
        agd["gameData"]["events"] = {"Events": [
            {"EventID": 1, "EventName": "MinionsSpawning", "EventTime": 65.0}]}
        out = _summary(agd)
        self.assertEqual(out["minion_spawn_events"], [])

    def test_existing_extracts_untouched(self) -> None:
        # The three sibling extracts keep parsing off the same stream.
        events = [
            {"EventID": 1, "EventName": "MinionsSpawning", "EventTime": 65.0},
            {"EventID": 2, "EventName": "TurretKilled", "EventTime": 1290.0,
             "TurretKilled": "Turret_T1_C_05_A"},
            {"EventID": 3, "EventName": "InhibKilled", "EventTime": 1305.0,
             "InhibKilled": "Barracks_T1_L1"},
            {"EventID": 4, "EventName": "DragonKill", "EventTime": 1310.0,
             "KillerName": "Zed", "DragonType": "Fire"},
        ]
        out = _summary(_allgamedata("Ashe", _PLAYERS, events))
        self.assertEqual(out["turret_events"],
                         [{"down_at_s": 1290.0, "name": "Turret_T1_C_05_A"}])
        self.assertEqual(out["inhib_events"],
                         [{"down_at_s": 1305.0, "name": "Barracks_T1_L1"}])
        self.assertEqual(len(out["objective_events"]), 1)
        self.assertEqual(out["objective_events"][0]["name"], "dragon")
        self.assertEqual(out["minion_spawn_events"],
                         [{"spawn_at_s": 65.0, "event_id": 1}])


class AsciiHygieneTests(unittest.TestCase):
    def test_module_is_ascii(self) -> None:
        for path in (Path(_liveclient.__file__), Path(__file__)):
            text = path.read_text(encoding="utf-8")
            for cp in (0x2013, 0x2014, 0x2018, 0x2019, 0x201C, 0x201D):
                self.assertNotIn(chr(cp), text)


if __name__ == "__main__":
    unittest.main()
