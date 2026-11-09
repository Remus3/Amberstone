"""True-audit hardening of dashboard/builders_lcu_enrich.py (s144 cycle 217).

The module parses two payloads RC does not author - the LCU
/lol-match-history/v1/games/{gameId} detail and the Riot Match-V5
timeline - and its docstrings promise quiet degradation ("Returns an empty
dict on any structural mismatch", "Returns {} on any structural problem").
Measured before this file: both parsers RAISED on wrong-shaped input
(a non-dict entry, a non-numeric stat, a NaN timestamp, an unhashable id).
`_build_last_match` catches the raise at its outermost handler, so ONE bad
field in a stored LCU detail turned the whole Post Game Review payload -
the DB match row included - into "internal error - see logs".

Pinned here:
  F1  _enrich_from_lcu never raises; a bad field degrades only that field
  F2  _enrich_match_timeline never raises; a bad frame / event degrades only
      itself; a negative event timestamp clamps to 0:00
  F3  the Match-V5 region map routes OC1 and the SG2 / TW2 / VN2 / PH2 /
      TH2 platforms to "sea" and ME1 to "europe"; an unknown platform makes
      no call instead of a guaranteed-wrong "americas" call
  F4  a game id that is not a positive integer (bool, path-like string,
      dict) makes no Match-V5 call
  E2E a malformed stored LCU detail no longer blanks /api/last-match

Synthetic ids only (RM-906). ASCII only.
"""
from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path
from unittest import mock

import pytest

from dashboard import builders_lcu_enrich as ble

_PUUID = "synthetic-puuid-me"


def _detail(**over) -> dict:
    d = {
        "gameId": 4242, "platformId": "NA1", "gameMode": "CLASSIC",
        "queueId": 420, "mapId": 11, "gameDuration": 1800,
        "participantIdentities": [
            {"participantId": 1, "player": {"puuid": _PUUID,
                                            "gameName": "Me", "tagLine": "T1"}},
            {"participantId": 2, "player": {"puuid": "synthetic-puuid-2",
                                            "gameName": "Foe"}},
        ],
        "participants": [
            {"participantId": 1, "teamId": 100, "championId": 99,
             "stats": {"win": True, "kills": 5, "deaths": 2, "assists": 7,
                       "goldEarned": 9000, "champLevel": 14,
                       "totalMinionsKilled": 150, "neutralMinionsKilled": 10}},
            {"participantId": 2, "teamId": 200, "championId": 12,
             "stats": {"win": False, "kills": 2, "deaths": 5,
                       "goldEarned": 7000}},
        ],
        "teams": [
            {"teamId": 100, "win": "Win", "bans": [{"championId": 1}]},
            {"teamId": 200, "win": "Fail", "bans": []},
        ],
    }
    d.update(over)
    return d


# ------------------------------------------------------------------ F1

_BAD_DETAILS = [
    pytest.param(_detail(participantIdentities={"a": 1}), id="identities-dict"),
    pytest.param(_detail(participantIdentities="xyz"), id="identities-str"),
    pytest.param(_detail(participants={"1": {}}), id="participants-dict"),
    pytest.param(_detail(participants="abc"), id="participants-str"),
    pytest.param(_detail(participantIdentities=[
        "junk", None, {"participantId": 1, "player": {"puuid": _PUUID}}]),
        id="identity-entry-not-dict"),
    pytest.param(_detail(participantIdentities=[
        {"participantId": 1, "player": "not-a-dict"}]), id="player-not-dict"),
    pytest.param(_detail(participants=[
        "junk", {"participantId": 1, "teamId": 100, "stats": {}}]),
        id="participant-entry-not-dict"),
    pytest.param(_detail(participants=[
        {"participantId": 1, "teamId": 100, "stats": [1, 2]}]),
        id="stats-list"),
    pytest.param(_detail(participantIdentities=[
        {"participantId": [1], "player": {"puuid": "x"}},
        {"participantId": 1, "player": {"puuid": _PUUID}}]),
        id="unhashable-identity-pid"),
    pytest.param(_detail(teams={"teamId": 100}), id="teams-dict"),
    pytest.param(_detail(teams=["junk", {"teamId": 100, "bans": 7}]),
                 id="team-entry-and-bans-junk"),
    pytest.param(_detail(gameDuration="long"), id="duration-str"),
    pytest.param(_detail(gameDuration=float("nan")), id="duration-nan"),
]


@pytest.mark.parametrize("detail", _BAD_DETAILS)
def test_f1_enrich_from_lcu_never_raises(detail):
    out = ble._enrich_from_lcu(detail, _PUUID)
    assert isinstance(out, dict)


@pytest.mark.parametrize("bad", ["abc", float("nan"), float("inf"), 1e400,
                                 [1], {"x": 1}])
def test_f1_one_bad_stat_degrades_only_that_field(bad):
    d = _detail()
    d["participants"][0]["stats"]["kills"] = bad
    d["participants"][0]["stats"]["totalDamageTaken"] = bad
    d["participants"][0]["stats"]["item3"] = bad
    out = ble._enrich_from_lcu(d, _PUUID)
    assert out, "one bad stat must not blank the whole enrichment"
    me = next(r for r in out["roster"] if r["is_me"])
    assert me["kills"] == 0
    assert me["deaths"] == 2 and me["assists"] == 7
    assert me["cs"] == 160
    assert out["damage"]["taken"] == 0
    assert out["items"][3] == 0 and len(out["items"]) == 7
    assert out["champ_level"] == 14


def test_f1_numeric_strings_and_floats_still_coerce():
    d = _detail()
    d["participants"][0]["stats"]["kills"] = "5"
    d["participants"][0]["stats"]["goldEarned"] = 9000.9
    d["participants"][0]["stats"]["deaths"] = " 2 "
    out = ble._enrich_from_lcu(d, _PUUID)
    me = next(r for r in out["roster"] if r["is_me"])
    assert (me["kills"], me["gold"], me["deaths"]) == (5, 9000, 2)


def test_f1_junk_entries_are_skipped_not_fatal():
    d = _detail()
    d["participantIdentities"].insert(0, "junk")
    d["participants"].insert(0, None)
    d["teams"].insert(0, 17)
    out = ble._enrich_from_lcu(d, _PUUID)
    assert out["champion_id"] == 99
    assert len(out["roster"]) == 2
    assert [t["team_id"] for t in out["teams"]] == [100, 200]


def test_f1_string_participant_id_still_matches_int():
    d = _detail()
    d["participantIdentities"][0]["participantId"] = "1"
    out = ble._enrich_from_lcu(d, _PUUID)
    assert out and out["champion_id"] == 99
    assert [r["is_me"] for r in out["roster"]] == [True, False]


def test_f1_huge_digit_string_ids_never_raise():
    d = _detail()
    huge = "9" * 5000
    d["participantIdentities"].insert(0, {"participantId": huge,
                                          "player": {"puuid": "x"}})
    d["participants"].insert(0, {"participantId": huge, "stats": {
        "kills": huge}})
    out = ble._enrich_from_lcu(d, _PUUID)
    assert out["champion_id"] == 99
    assert out["roster"][0]["participant_id"] is None
    assert out["roster"][0]["kills"] == 0


def test_f1_non_string_names_and_bans_are_not_passed_through():
    d = _detail()
    d["participantIdentities"][0]["player"]["gameName"] = {"x": 1}
    d["participantIdentities"][0]["player"]["tagLine"] = 7
    d["teams"][1]["bans"] = "abc"
    out = ble._enrich_from_lcu(d, _PUUID)
    me = next(r for r in out["roster"] if r["is_me"])
    assert me["game_name"] == "" and me["tag_line"] == ""
    assert out["teams"][1]["bans"] == []
    assert out["teams"][0]["bans"] == [{"championId": 1}]


def test_f1_non_string_tracked_puuid_is_empty():
    assert ble._enrich_from_lcu(_detail(), 12345) == {}
    assert ble._enrich_from_lcu(_detail(), ["x"]) == {}
    # Even when its str() would equal an identity's puuid, a non-string
    # tracked puuid never resolves an operator.
    d = _detail()
    d["participantIdentities"][0]["player"]["puuid"] = "12345"
    assert ble._enrich_from_lcu(d, 12345) == {}
    assert ble._enrich_from_lcu(d, "12345")["champion_id"] == 99


# ------------------------------------------------------------------ F2

def _timeline(frames) -> dict:
    return {"info": {"frameInterval": 60000, "frames": frames}}


def _frame(ts, g1=1000, g2=900, events=None) -> dict:
    return {
        "timestamp": ts,
        "participantFrames": {
            "1": {"participantId": 1, "totalGold": g1, "xp": 100,
                  "minionsKilled": 10},
            "2": {"participantId": 2, "totalGold": g2, "xp": 90,
                  "minionsKilled": 8},
        },
        "events": events or [],
    }


def _good_frames():
    return [_frame(0), _frame(60000), _frame(120000)]


_BAD_TIMELINE_CASES = [
    pytest.param(_timeline(_good_frames()), [1, 2], id="lcu-detail-list"),
    pytest.param(_timeline(["junk"] + _good_frames()), None,
                 id="frame-not-dict"),
    pytest.param(_timeline([{"timestamp": 0, "participantFrames": [1, 2]}]
                           + _good_frames()), None, id="pframes-list"),
    pytest.param(_timeline([_frame("x")] + _good_frames()), None,
                 id="timestamp-str"),
    pytest.param(_timeline([_frame(float("nan"))] + _good_frames()), None,
                 id="timestamp-nan"),
    pytest.param(_timeline([_frame(0, g1="lots")] + _good_frames()), None,
                 id="gold-str"),
    pytest.param(_timeline(_good_frames() + [_frame(180000, events=[
        {"type": "ELITE_MONSTER_KILL", "monsterType": ["DRAGON"],
         "timestamp": 1000},
        {"type": "ELITE_MONSTER_KILL", "monsterType": "DRAGON",
         "monsterSubType": 5, "timestamp": 2000},
        {"type": "CHAMPION_KILL", "timestamp": "soon", "killerId": 1},
        {"type": ["BUILDING_KILL"], "timestamp": 3000},
    ])]), None, id="events-junk"),
    pytest.param({"info": {"frameInterval": "fast",
                           "frames": _good_frames()}}, None,
                 id="interval-str"),
]


@pytest.mark.parametrize("timeline, detail", _BAD_TIMELINE_CASES)
def test_f2_timeline_never_raises(timeline, detail):
    out = ble._enrich_match_timeline(
        timeline, _detail() if detail is None else detail, 100)
    assert isinstance(out, dict)


def test_f2_mixed_type_team_ids_do_not_raise():
    d = _detail()
    d["participants"][1]["teamId"] = "200"
    out = ble._enrich_match_timeline(_timeline(_good_frames()), d, 100)
    assert isinstance(out, dict)


def test_f2_one_bad_frame_keeps_the_rest():
    frames = ["junk", _frame(0), {"timestamp": 30000,
                                  "participantFrames": "x"},
              _frame(60000, g1="lots"), _frame(120000)]
    out = ble._enrich_match_timeline(_timeline(frames), _detail(), 100)
    assert out, "one bad frame must not drop the whole timeline"
    # The good frames still produce gold diffs; the bad gold reads as 0.
    assert out["series"]["gold"][-1] == 100
    assert -900 in out["series"]["gold"]


def test_f2_one_bad_event_keeps_the_rest():
    evs = [
        {"type": "ELITE_MONSTER_KILL", "monsterType": ["X"],
         "timestamp": 1000, "killerId": 1},
        {"type": "ELITE_MONSTER_KILL", "monsterType": "DRAGON",
         "monsterSubType": 5, "timestamp": 2000, "killerId": 1},
        {"type": "BUILDING_KILL", "buildingType": "TOWER_BUILDING",
         "timestamp": "late", "teamId": 200},
        {"type": "ELITE_MONSTER_KILL", "monsterType": "BARON_NASHOR",
         "timestamp": 90000, "killerId": 2},
    ]
    out = ble._enrich_match_timeline(
        _timeline(_good_frames() + [_frame(180000, events=evs)]),
        _detail(), 100)
    kinds = [(e["kind"], e["label"], e["team"]) for e in out["events"]]
    assert ("baron", "Baron", "enemy") in kinds
    assert ("dragon", "Dragon", "ally") in kinds
    assert ("objective", "Objective", "ally") in kinds


def test_f2_negative_timestamp_clamps_to_zero_clock():
    evs = [{"type": "CHAMPION_KILL", "timestamp": -500, "killerId": 1}]
    out = ble._enrich_match_timeline(
        _timeline([_frame(0, events=evs)] + _good_frames()[1:]),
        _detail(), 100)
    fb = out["events"][0]
    assert fb["kind"] == "first_blood"
    assert fb["t_s"] == 0 and fb["clock"] == "0:00"


def test_f2_good_timeline_shape_unchanged():
    evs = [{"type": "CHAMPION_KILL", "timestamp": 65000, "killerId": 1},
           {"type": "ELITE_MONSTER_KILL", "monsterType": "DRAGON",
            "monsterSubType": "FIRE_DRAGON", "timestamp": 70000,
            "killerId": 2}]
    frames = [_frame(0), _frame(60000, events=evs), _frame(120000)]
    out = ble._enrich_match_timeline(_timeline(frames), _detail(), 100)
    assert out["frame_interval_ms"] == 60000
    assert out["duration_s"] == 1800
    assert out["minutes"] == [0, 1, 2]
    assert out["series"] == {"gold": [100, 100, 100], "xp": [10, 10, 10],
                             "cs": [2, 2, 2]}
    assert out["final"] == {"gold": 100, "xp": 10, "cs": 2}
    assert out["at_n"]["by_pid"]["1"] == {"gold": 1000, "cs": 10}
    assert [(e["kind"], e["team"], e["clock"], e["label"])
            for e in out["events"]] == [
        ("first_blood", "ally", "1:05", "First Blood"),
        ("dragon", "enemy", "1:10", "Fire Dragon")]


def test_f2_non_finite_values_never_reach_the_series():
    frames = [_frame(0, g1=float("inf")), _frame(60000)]
    out = ble._enrich_match_timeline(_timeline(frames), _detail(), 100)
    for series in out["series"].values():
        assert all(isinstance(v, int) and math.isfinite(v) for v in series)


# ------------------------------------------------------------------ F3 / F4

@pytest.mark.parametrize("platform, region", [
    ("NA1", "americas"), ("BR1", "americas"), ("LA1", "americas"),
    ("LA2", "americas"),
    ("EUW1", "europe"), ("EUN1", "europe"), ("TR1", "europe"),
    ("RU", "europe"), ("ME1", "europe"),
    ("KR", "asia"), ("JP1", "asia"),
    ("OC1", "sea"), ("SG2", "sea"), ("TW2", "sea"), ("VN2", "sea"),
    ("PH2", "sea"), ("TH2", "sea"),
    ("oc1", "sea"),
])
def test_f3_match_v5_region_routing(platform, region):
    from core import riot_api
    with mock.patch.object(riot_api, "get_match_timeline",
                           return_value=None) as gm:
        ble._attach_match_timeline({}, _detail(platformId=platform))
    assert gm.call_count == 1
    args, kwargs = gm.call_args
    assert kwargs.get("region") == region
    assert args[0] == f"{platform.upper()}_4242"


@pytest.mark.parametrize("platform", ["PBE1", "XX9", "", None, 7,
                                      {"p": 1}, "NA1/../x"])
def test_f3_unknown_platform_makes_no_call(platform):
    from core import riot_api
    with mock.patch.object(riot_api, "get_match_timeline",
                           side_effect=AssertionError("called")) as gm:
        enriched: dict = {}
        ble._attach_match_timeline(enriched, _detail(platformId=platform))
    assert gm.call_count == 0
    assert "timeline" not in enriched


@pytest.mark.parametrize("game_id", [True, False, 0, -5, "12/34", "1e3",
                                     {"id": 1}, [1], 1.5, float("nan"), ""])
def test_f4_bad_game_id_makes_no_call(game_id):
    from core import riot_api
    with mock.patch.object(riot_api, "get_match_timeline",
                           side_effect=AssertionError("called")) as gm:
        ble._attach_match_timeline({}, _detail(gameId=game_id))
    assert gm.call_count == 0


@pytest.mark.parametrize("game_id", [4242, "4242", 4242.0])
def test_f4_integer_game_id_forms_still_call(game_id):
    from core import riot_api
    with mock.patch.object(riot_api, "get_match_timeline",
                           return_value=None) as gm:
        ble._attach_match_timeline({}, _detail(gameId=game_id))
    assert gm.call_count == 1
    assert gm.call_args[0][0] == "NA1_4242"


def test_attach_non_dict_detail_is_quiet():
    enriched: dict = {}
    ble._attach_match_timeline(enriched, ["not", "a", "dict"])
    assert "timeline" not in enriched


# ------------------------------------------------------------------ E2E

def _make_db(path: Path, raw: str) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE matches ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  timestamp TEXT, mode TEXT, champion TEXT, grade TEXT,"
        "  kda_str TEXT, game_time_s INTEGER, game_id INTEGER DEFAULT 0,"
        "  kills INTEGER, deaths INTEGER, assists INTEGER,"
        "  cs INTEGER, cs_per_min REAL, gold INTEGER, gold_per_min REAL,"
        "  kp_pct REAL, label TEXT, raw_data TEXT)"
    )
    conn.execute(
        "INSERT INTO matches (timestamp, mode, champion, grade, kda_str,"
        " game_time_s, kills, deaths, assists, cs, cs_per_min, gold,"
        " gold_per_min, kp_pct, label, raw_data)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("2026-06-03 14:45:00", "SR", "Nami", "A", "5/2/7", 1800, 5, 2, 7,
         160, 5.3, 9000, 300.0, 60.0, "", raw),
    )
    conn.commit()
    conn.close()


def test_e2e_malformed_stored_detail_keeps_the_last_match_page(tmp_path):
    import dashboard.builders_last_match as blm
    from dashboard import _context

    d = _detail()
    d.pop("platformId")  # no Match-V5 call from a unit test
    d["participants"][0]["stats"]["kills"] = "N/A"
    d["participantIdentities"].append("junk")
    raw = json.dumps({"lcu_match_detail": d, "tracked_puuid": _PUUID})
    (tmp_path / "data").mkdir()
    db = tmp_path / "data" / "match_history.db"
    _make_db(db, raw)
    try:
        with mock.patch.object(blm, "_APP_DIR", tmp_path):
            out = blm._build_last_match()
    finally:
        cached = getattr(_context.DB_CONN_LOCAL, "conns", {}).pop(
            str(db), None)
        if cached is not None:
            cached.close()
    assert "error" not in out, out.get("error")
    assert out.get("found") is True
    enriched = out["match"]["enriched"]
    assert enriched and enriched["champion_id"] == 99
