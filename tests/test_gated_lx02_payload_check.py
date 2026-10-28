"""Tests for tools/gated_lx02_payload_check.py (LX-02 PREP, s144 lane gated).

Every payload here is hand-built and name-scrubbed (RM-906): players are
``PlayerN#TST`` and the champions are ordinary champion names. The tool is a
read-only grader, so the tests check its classification, its verdicts and that
no name ever reaches its output.
"""
from __future__ import annotations

import json
from pathlib import Path

from tools import gated_lx02_payload_check as lx02

FIXTURE = lx02.FIXTURE


def _player(champ: str, game_name: str, team: str) -> dict:
    return {"championName": champ, "summonerName": f"{game_name}#TST",
            "riotId": f"{game_name}#TST", "riotIdGameName": game_name,
            "riotIdTagLine": "TST", "team": team}


def _payload(events: list, mode: str = "CLASSIC", game_time: float = 600.0) -> dict:
    return {
        "activePlayer": {"summonerName": "PlayerOne#TST"},
        "allPlayers": [_player("Ashe", "PlayerOne", "ORDER"),
                       _player("Leona", "PlayerTwo", "ORDER"),
                       _player("Zed", "PlayerThree", "CHAOS")],
        "events": {"Events": events},
        "gameData": {"gameMode": mode, "gameTime": game_time},
    }


def _write(tmp_path: Path, name: str, obj: dict) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(obj), encoding="utf-8")
    return p


def _horde(killer: str, stolen: object = "False") -> dict:
    return {"EventID": 1, "EventName": "HordeKill", "EventTime": 400.0,
            "Stolen": stolen, "KillerName": killer, "Assisters": []}


def test_name_form_classes():
    champs, players = {"ashe", "zed"}, {"playerone", "ashe"}
    assert lx02.name_form("Zed", champs, players) == "champion"
    assert lx02.name_form("PlayerOne#TST", champs, players) == "player"
    assert lx02.name_form("PlayerOne", champs, players) == "player"
    assert lx02.name_form("Ashe", champs, players) == "both"
    assert lx02.name_form("Minion_T100L1S04N0003", champs, players) == "nonplayer"
    assert lx02.name_form("Turret_T2_L_03_A", champs, players) == "nonplayer"
    assert lx02.name_form("Somebody", champs, players) == "unmapped"
    assert lx02.name_form("", champs, players) == "empty"
    assert lx02.name_form(None, champs, players) == "empty"


def test_fixture_reads_champion_name_and_firstblood():
    s = lx02.check(lx02.load(FIXTURE))
    assert s["payloads"] == 1
    assert s["synthetic"] == 1
    assert s["rm673"]["verdict"] == "CHAMPION_NAME"
    assert s["rm674"]["verdict"] == "FIRSTBLOOD"
    assert s["horde"]["verdict"] == "MATCH"
    assert s["horde"]["count"] == 3
    assert s["horde"]["types"]["Stolen"] == {"string": 3}
    assert s["rm673"]["champion_exact"] == 4


def test_player_name_killers_confirm_rm673(tmp_path):
    ev = [_horde("PlayerOne"),
          {"EventID": 2, "EventName": "DragonKill", "EventTime": 500.0,
           "DragonType": "Fire", "Stolen": "False", "KillerName": "PlayerThree",
           "Assisters": ["PlayerTwo"]}]
    s = lx02.check(lx02.load(_write(tmp_path, "a.json", _payload(ev))))
    assert s["rm673"]["verdict"] == "PLAYER_NAME"
    assert s["rm673"]["objective_killer_forms"] == {"player": 2}
    assert s["name_forms"]["DragonKill"]["Assisters[]"] == {"player": 1}
    assert s["synthetic"] == 0


def test_mixed_and_nonplayer_objective_killers(tmp_path):
    ev = [_horde("PlayerOne"), _horde("Zed"), _horde("SRU_Horde_Minion1")]
    s = lx02.check(lx02.load(_write(tmp_path, "a.json", _payload(ev))))
    assert s["rm673"]["verdict"] == "MIXED"
    assert s["rm673"]["objective_killer_forms"]["nonplayer"] == 1


def test_player_beside_nonplayer_still_player_name(tmp_path):
    s = lx02.check(lx02.load(_write(tmp_path, "a.json",
                                    _payload([_horde("PlayerOne"),
                                              _horde("SRU_Horde_Minion1")]))))
    assert s["rm673"]["verdict"] == "PLAYER_NAME"


def test_no_objective_event_is_no_result(tmp_path):
    ev = [{"EventID": 0, "EventName": "GameStart", "EventTime": 0.0}]
    s = lx02.check(lx02.load(_write(tmp_path, "a.json", _payload(ev))))
    assert s["rm673"]["verdict"] == "NO_RESULT"
    assert s["rm674"]["verdict"] == "NO_RESULT"
    assert s["horde"]["verdict"] == "NO_RESULT"


def test_nonplayer_only_objective_is_no_result(tmp_path):
    s = lx02.check(lx02.load(_write(tmp_path, "a.json",
                                    _payload([_horde("SRU_Horde_Minion1")]))))
    assert s["rm673"]["verdict"] == "NO_RESULT"


def test_firstbloodkill_and_both_verdicts(tmp_path):
    fbk = {"EventID": 3, "EventName": "FirstBloodKill", "EventTime": 90.0}
    fb = {"EventID": 4, "EventName": "FirstBlood", "EventTime": 90.0,
          "Recipient": "PlayerOne"}
    s = lx02.check(lx02.load(_write(tmp_path, "a.json", _payload([fbk]))))
    assert s["rm674"]["verdict"] == "FIRSTBLOODKILL"
    s = lx02.check(lx02.load(_write(tmp_path, "b.json", _payload([fbk, fb]))))
    assert s["rm674"]["verdict"] == "BOTH"
    assert s["name_forms"]["FirstBlood"]["Recipient"] == {"player": 1}


def test_horde_shape_difference_is_reported(tmp_path):
    odd = _horde("PlayerOne", stolen=False)
    odd.pop("Assisters")
    odd["NewField"] = 1
    s = lx02.check(lx02.load(_write(tmp_path, "a.json", _payload([_horde("Zed"), odd]))))
    assert s["horde"]["verdict"] == "DIFFERS"
    assert s["horde"]["missing_keys"] == ["Assisters"]
    assert s["horde"]["extra_keys"] == ["NewField"]
    assert s["horde"]["types"]["Stolen"] == {"string": 1, "bool": 1}


def test_horde_type_unlike_fixture_differs(tmp_path):
    # one type per key is not enough: it must equal the fixture's (Stolen a string)
    s = lx02.check(lx02.load(_write(tmp_path, "a.json",
                                    _payload([_horde("Zed", stolen=False)]))))
    assert s["horde"]["missing_keys"] == [] and s["horde"]["extra_keys"] == []
    assert s["horde"]["types"]["Stolen"] == {"bool": 1}
    assert s["horde"]["fixture_types"]["Stolen"] == "string"
    assert s["horde"]["verdict"] == "DIFFERS"


def test_case_folded_champion_killer_is_inexact(tmp_path):
    # _liveclient.py tests the raw string against championName, so a killer
    # that only matches after the case fold still reads killer_team unknown
    s = lx02.check(lx02.load(_write(tmp_path, "a.json",
                                    _payload([_horde("zed"), _horde("Zed")]))))
    assert s["rm673"]["objective_killer_forms"] == {"champion": 2}
    assert s["rm673"]["champion_exact"] == 1
    assert s["rm673"]["verdict"] == "CHAMPION_NAME_INEXACT"


def test_champion_beside_unmapped_killer_is_mixed(tmp_path):
    # an unmapped killer may be a player form the roster misses: never REFUTED
    s = lx02.check(lx02.load(_write(tmp_path, "a.json",
                                    _payload([_horde("Zed"), _horde("Somebody"),
                                              _horde("SRU_Horde_Minion1")]))))
    assert s["rm673"]["objective_killer_forms"] == {
        "champion": 1, "unmapped": 1, "nonplayer": 1}
    assert s["rm673"]["verdict"] == "MIXED"


def test_champion_beside_nonplayer_or_empty_killer_is_mixed(tmp_path):
    # an underscore name or an empty killer must not reach CHAMPION_NAME either
    for odd in ("Bot_Smurf", "", None, 12):
        s = lx02.check(lx02.load(_write(tmp_path, "a.json",
                                        _payload([_horde("Ashe"), _horde(odd)]))))
        assert s["rm673"]["verdict"] == "MIXED", odd


def test_teamless_player_champion_is_not_exact(tmp_path):
    body = _payload([_horde("Zed")])
    body["allPlayers"][2]["team"] = ""
    s = lx02.check(lx02.load(_write(tmp_path, "a.json", body)))
    assert s["rm673"]["champion_exact"] == 0
    assert s["rm673"]["verdict"] == "CHAMPION_NAME_INEXACT"


def test_exact_champion_killers_read_champion_name(tmp_path):
    s = lx02.check(lx02.load(_write(tmp_path, "a.json",
                                    _payload([_horde("Zed"), _horde("Ashe")]))))
    assert s["rm673"]["reader_self_identified"] == 1
    assert s["rm673"]["reader_killer_team"] == {"enemy": 1, "ally": 1}
    assert s["rm673"]["verdict"] == "CHAMPION_NAME"


def test_reader_without_self_identification_fails(tmp_path):
    # _liveclient.py finds "me" by raw summonerName; with no match both sets
    # stay empty and every objective row reads unknown
    for ap in ({"summonerName": "PlayerOne"}, {}):
        body = _payload([_horde("Zed")])
        body["activePlayer"] = ap
        s = lx02.check(lx02.load(_write(tmp_path, "a.json", body)))
        assert s["rm673"]["reader_self_identified"] == 0
        assert s["rm673"]["reader_killer_team"] == {"unknown": 1}
        assert s["rm673"]["verdict"] == "CHAMPION_NAME_READER_FAILS"


def test_mirror_champion_is_reader_fails(tmp_path):
    body = _payload([_horde("Ashe")])
    body["allPlayers"].append(_player("Ashe", "PlayerFour", "CHAOS"))
    s = lx02.check(lx02.load(_write(tmp_path, "a.json", body)))
    assert s["rm673"]["reader_killer_team"] == {"ambiguous": 1}
    assert s["rm673"]["verdict"] == "CHAMPION_NAME_READER_FAILS"


def test_reader_rule_still_matches_liveclient_source():
    # reader_sets is a hand copy of dashboard/_liveclient.py (importing it needs
    # a configured vision token); fail loudly when the source rule moves
    src = (Path(lx02.__file__).resolve().parent.parent / "dashboard"
           / "_liveclient.py").read_text(encoding="utf-8")
    for needle in ('me_name = ap.get("summonerName", "")',
                   'if p.get("summonerName") == me_name',
                   'if p.get("team") and p.get("team") != my_team]',
                   'if p.get("team") and p.get("team") == my_team]',
                   'if killer in enemy_set:',
                   'elif killer in ally_set:'):
        assert needle in src, needle


def test_other_firstblood_name(tmp_path):
    for name in ("FirstBloodTurret", "FIRSTBLOOD", "First_Blood"):
        ev = [{"EventID": 5, "EventName": name, "EventTime": 90.0}]
        s = lx02.check(lx02.load(_write(tmp_path, "a.json", _payload(ev))))
        assert s["rm674"]["verdict"] == "OTHER", name


def test_fixture_horde_keys_pinned():
    assert lx02.fixture_horde_keys() == {"EventID", "EventName", "EventTime",
                                         "Stolen", "KillerName", "Assisters"}


def test_relay_wrapper_ts_and_duplicates(tmp_path):
    body = _payload([_horde("Zed")])
    _write(tmp_path, "a.json", {"data": body, "ts": 1000.0})
    _write(tmp_path, "b.json", {"data": body, "ts": 1030.0})
    _write(tmp_path, "c.json", {"data": body, "ts": 1030.0})
    _write(tmp_path, "junk.json", {"nope": 1})
    (tmp_path / "bad.json").write_text("{not json", encoding="utf-8")
    loaded = lx02.load(tmp_path)
    # junk.json is a dict without gameData or data and still loads (shape_audit's rule)
    s = lx02.check(loaded)
    assert s["payloads"] == 4
    assert s["duplicates"] == 1
    assert s["relay_ts_span_s"] == 30.0
    assert s["game_time_max"] == 600.0


def test_no_name_reaches_output(tmp_path, capsys):
    ev = [_horde("PlayerOne"),
          {"EventID": 2, "EventName": "ChampionKill", "EventTime": 300.0,
           "KillerName": "PlayerThree", "VictimName": "PlayerTwo",
           "Assisters": ["PlayerOne"]}]
    body = _payload(ev)
    # a wrong-typed modelled field whose raw value would be quoted by shape_audit
    body["allPlayers"][0]["level"] = "PlayerOne"
    p = _write(tmp_path, "a.json", body)
    for argv in ([str(p)], [str(p), "--json"]):
        assert lx02.main(argv) == 0
        out = capsys.readouterr().out
        for name in ("PlayerOne", "PlayerTwo", "PlayerThree", "Ashe", "Leona", "Zed"):
            assert name not in out, (argv, name)


def test_missing_and_empty_paths_exit_2(tmp_path, capsys):
    assert lx02.main([str(tmp_path / "absent.json")]) == 2
    assert lx02.main([str(tmp_path)]) == 2
    capsys.readouterr()


def test_tool_is_read_only(tmp_path):
    p = _write(tmp_path, "a.json", _payload([_horde("Zed")]))
    before = (p.read_bytes(), p.stat().st_mtime_ns, sorted(tmp_path.iterdir()))
    assert lx02.main([str(tmp_path), "--json"]) == 0
    assert (p.read_bytes(), p.stat().st_mtime_ns, sorted(tmp_path.iterdir())) == before
