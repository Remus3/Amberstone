"""Tests for tools/gated_lx07_recap_check.py (LX-07 PREP, s144 lane gated).

Every payload here is hand-built and name-scrubbed (RM-906): players are
``PlayerN#TST`` and the champions are ordinary champion names. Rows are written
by the REAL ``core.death_recap.process_kill`` (DS stubbed) into tmp_path, so
the grader is checked against the writer's own row shape, never a copy of it.
"""
from __future__ import annotations

import json
from pathlib import Path

from core import death_recap as dr
from tools import gated_lx07_recap_check as lx07

ME = "PlayerOne#TST"


def _agd(events, mode="CLASSIC", game_time=300.0, me_champ="Ashe") -> dict:
    return {
        "activePlayer": {"riotId": ME, "riotIdGameName": "PlayerOne",
                         "championStats": {"armor": 40.0, "magicResist": 30.0,
                                           "maxHealth": 1200.0}},
        "allPlayers": [
            {"championName": me_champ, "riotId": ME, "riotIdGameName": "PlayerOne",
             "team": "ORDER", "level": 7, "items": []},
            {"championName": "Zed", "riotId": "PlayerTwo#TST", "riotIdGameName": "PlayerTwo",
             "team": "CHAOS", "level": 8, "items": [{"itemID": 3142}]},
            {"championName": "Lux", "riotId": "PlayerThree#TST",
             "riotIdGameName": "PlayerThree", "team": "CHAOS", "level": 6, "items": []},
        ],
        "events": {"Events": events},
        "gameData": {"gameMode": mode, "gameTime": game_time},
    }


def _kill(eid=5, t=200.0, victim="PlayerOne", killer="PlayerTwo", assisters=("PlayerThree",)):
    return {"EventID": eid, "EventName": "ChampionKill", "EventTime": t,
            "VictimName": victim, "KillerName": killer, "Assisters": list(assisters)}


def _write(tmp_path: Path, payload: dict, ev: dict, burst=None) -> Path:
    path = tmp_path / "death_recaps.jsonl"
    dr.process_kill(ev, payload, path=path, up_fn=lambda: burst is not None,
                    burst_fn=burst or (lambda *a, **k: None))
    return path


def _burst(champ, **_k):
    return {"per_cast": [{"damage_type": "PHYSICAL" if champ == "Zed" else "MAGIC",
                          "final_damage": 300.0}]}


def _cap(tmp_path: Path, payload: dict, name="c1.json", ts=1.0) -> list:
    d = tmp_path / "caps"
    d.mkdir(exist_ok=True)
    (d / name).write_text(json.dumps({"ts": ts, "data": payload}), encoding="utf-8")
    return lx07.load(d)


def test_missing_log_is_no_result(tmp_path):
    s = lx07.check(lx07.read_log(tmp_path / "none.jsonl"))
    assert s["log_exists"] is False
    assert s["rows_verdict"] == "NO_RESULT"
    assert s["join"] is None


def test_real_writer_row_passes_and_joins(tmp_path):
    ev = _kill()
    payload = _agd([ev])
    path = _write(tmp_path, payload, ev, burst=_burst)
    s = lx07.check(lx07.read_log(path), _cap(tmp_path, payload))
    assert s["rows_verdict"] == "PASS", s["rows_failed"]
    assert s["modes"] == ["SR"]
    assert s["per_mode"]["SR"]["basis"] == {"ds": 1}
    assert s["per_mode"]["SR"]["ds_contributors"] == 2
    j = s["join"]
    assert j["join_verdict"] == "MATCH"
    assert j["own_deaths"] == 1 and j["tap_blind"] == 0
    assert j["victim_forms"] == {"player": 1}
    assert j["killer_forms"] == {"player": 1}
    assert j["deaths"][0]["contributors_match"] is True
    assert s["player_name_leaks"] == 0


def test_local_fallback_basis_and_mode_map(tmp_path):
    ev = _kill()
    payload = _agd([ev], mode="KIWI")
    path = _write(tmp_path, payload, ev)
    s = lx07.check(lx07.read_log(path))
    assert s["rows_verdict"] == "PASS", s["rows_failed"]
    assert s["modes"] == ["ARAM"]
    assert s["per_mode"]["ARAM"]["basis"] == {"local": 1}
    assert s["per_mode"]["ARAM"]["divergent"] == []
    assert s["per_mode"]["ARAM"]["ds_contributors"] == 0


def test_champion_name_victim_is_tap_blind(tmp_path):
    ev = _kill(victim="Ashe", killer="Zed")
    payload = _agd([ev])
    path = tmp_path / "death_recaps.jsonl"
    assert dr.process_kill(ev, payload, path=path, up_fn=lambda: False) is None
    s = lx07.check(lx07.read_log(path), _cap(tmp_path, payload))
    j = s["join"]
    assert j["join_verdict"] == "TAP_BLIND"
    assert j["tap_blind"] == 1 and j["deaths_without_row"] == 1
    assert j["victim_forms"] == {"champion": 1}
    assert j["killer_forms"] == {"champion": 1}


def test_mirror_champion_victim_not_counted_as_own(tmp_path):
    ev = _kill(victim="Zed", killer="PlayerThree", assisters=())
    payload = _agd([ev], me_champ="Zed")
    s = lx07.check(lx07.read_log(tmp_path / "none.jsonl"), _cap(tmp_path, payload))
    assert s["join"]["own_deaths"] == 0
    assert s["join"]["join_verdict"] == "NO_RESULT"


def test_death_without_row_is_missing(tmp_path):
    ev = _kill()
    s = lx07.check(lx07.read_log(tmp_path / "none.jsonl"), _cap(tmp_path, _agd([ev])))
    assert s["join"]["join_verdict"] == "MISSING"
    assert s["join"]["deaths_without_row"] == 1


def test_other_players_death_is_ignored(tmp_path):
    ev = _kill(victim="PlayerTwo", killer="PlayerOne", assisters=())
    s = lx07.check(lx07.read_log(tmp_path / "none.jsonl"), _cap(tmp_path, _agd([ev])))
    assert s["join"]["own_deaths"] == 0


def test_dedupe_across_captures_and_first_capture_contributors(tmp_path):
    ev = _kill()
    p1 = _agd([ev], game_time=210.0)
    p2 = _agd([ev, _kill(eid=9, t=250.0, victim="PlayerTwo", killer="PlayerOne",
                         assisters=())], game_time=260.0)
    path = _write(tmp_path, p1, ev)
    _cap(tmp_path, p1, "a.json")
    loaded = _cap(tmp_path, p2, "b.json")
    s = lx07.check(lx07.read_log(path), loaded)
    assert s["join"]["own_deaths"] == 1
    assert s["join"]["join_verdict"] == "MATCH"
    assert s["join"]["game_time_max"] == 260.0


def test_row_with_wrong_event_time_does_not_join(tmp_path):
    ev = _kill()
    payload = _agd([ev])
    path = _write(tmp_path, payload, ev)
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    rows[0]["game_time_s"] = 999.0
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    s = lx07.check(lx07.read_log(path), _cap(tmp_path, payload))
    assert s["join"]["join_verdict"] == "MISSING"
    assert s["join"]["rows_after_last_capture"] == 1


def test_orphan_row_inside_capture_window(tmp_path):
    ev = _kill()
    payload = _agd([ev])
    path = _write(tmp_path, payload, ev)
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    rows[0]["event_id"] = 77
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    s = lx07.check(lx07.read_log(path), _cap(tmp_path, payload))
    assert s["join"]["rows_without_wire_death"] == 1


def test_contributor_mismatch_is_counted(tmp_path):
    ev = _kill()
    payload = _agd([ev])
    path = _write(tmp_path, payload, ev)
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    rows[0]["contributors"] = rows[0]["contributors"][:1]
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    s = lx07.check(lx07.read_log(path), _cap(tmp_path, payload))
    assert s["join"]["contributors_mismatch"] == 1
    assert s["join"]["deaths"][0]["contributors_match"] is False


def _row(**over) -> dict:
    row = {"schema": dr.ROW_SCHEMA, "provenance": "estimated", "event_id": 1,
           "game_time_s": 100.0, "mode": "SR", "killer_kind": "champion",
           "contributors": [{"role": "killer", "champion": "Zed", "level": 8, "items": [],
                             "source": "local_ddragon",
                             "split": {"physical": 0.8, "magic": 0.2, "true": 0.0},
                             "weight": 2.0}],
           "shares": {"physical": 0.8, "magic": 0.2, "true": 0.0}, "basis": "local",
           "our_resists": {"armor": 40.0, "mr": 30.0}, "recorded_at": 1000.0}
    row.update(over)
    return row


def _grade(row, players=frozenset()) -> list:
    return lx07.grade_row(row, lx07.champion_keys(), set(players))["problems"]


def test_grade_row_flags_each_defect():
    assert _grade(_row()) == []
    assert _grade(_row(schema=2)) == ["schema"]
    assert _grade(_row(provenance="measured")) == ["provenance"]
    assert _grade(_row(mode="TFT")) == ["mode"]
    assert _grade(_row(shares={"physical": 0.9, "magic": 0.2, "true": 0.0})) == ["shares"]
    assert _grade(_row(shares={"physical": "x"})) == ["shares"]
    assert _grade(_row(basis="ds")) == ["basis"]
    assert _grade(_row(contributors=[], shares=None, basis="none")) == []
    assert _grade(_row(contributors=[], shares=None, basis="local")) == ["basis"]
    assert _grade(_row(contributors="x")) == ["contributors", "shares", "basis"]


def test_grade_row_names_only_and_leaks():
    c = _row()["contributors"][0]
    assert _grade(_row(contributors=[dict(c, champion="PlayerTwo")])) == ["names_only"]
    assert _grade(_row(contributors=[dict(c, summonerName="x")])) == ["names_only"]
    assert _grade(_row(contributors=[dict(c, role="victim")])) == ["names_only"]
    assert _grade(_row(note="PlayerTwo#TST"), players={"playertwo"}) == ["player_name_leak"]


def test_window_filters_on_recorded_at(tmp_path):
    path = tmp_path / "r.jsonl"
    path.write_text("".join(json.dumps(_row(recorded_at=t)) + "\n" for t in (10, 20, 30))
                    + "{torn\n", encoding="utf-8")
    log = lx07.read_log(path)
    assert log["torn"] == 1 and log["lines"] == 4
    s = lx07.check(log, since=15, until=25)
    assert s["rows_in_window"] == 1 and s["rows_outside_window"] == 2
    assert s["recorded_at_first"] == 20 and s["recorded_at_last"] == 20


def test_huge_int_and_deep_torn_line_do_not_crash(tmp_path):
    path = tmp_path / "r.jsonl"
    path.write_text(json.dumps(_row(recorded_at=10 ** 400)) + "\n" + "[" * 100000 + "\n", encoding="utf-8")
    log = lx07.read_log(path)
    assert log["torn"] == 1
    s = lx07.check(log, since=0.0)
    assert s["rows_in_window"] == 0 and s["rows_outside_window"] == 1


def test_divergent_ds_contributor_is_recorded_not_failed():
    c = dict(_row()["contributors"][0], champion="Lux", source="ds_burst",
             split={"physical": 1.0, "magic": 0.0, "true": 0.0})
    row = _row(contributors=[c], basis="ds", shares={"physical": 1.0, "magic": 0.0, "true": 0.0})
    s = lx07.check({"exists": True, "lines": 1, "torn": 0, "rows": [row]})
    assert s["rows_verdict"] == "PASS"
    div = s["per_mode"]["SR"]["divergent"]
    assert div and div[0]["champion"] == "Lux"


def test_captures_from_an_earlier_game_are_dropped_by_the_window(tmp_path):
    old_ev = _kill(eid=3, t=150.0)
    _cap(tmp_path, _agd([old_ev], game_time=160.0), "game1.json", ts=1000.0)
    ev = _kill(eid=5, t=200.0)
    payload = _agd([ev])
    path = _write(tmp_path, payload, ev)
    rec = lx07.read_log(path)
    t = rec["rows"][0]["recorded_at"]
    loaded = _cap(tmp_path, payload, "game2.json", ts=t - 1.0)
    unbounded = lx07.check(rec, loaded)
    assert unbounded["join"]["join_verdict"] == "MISSING"
    s = lx07.check(rec, loaded, since=t - 100.0, until=t + 60.0)
    assert s["captures_outside_window"] == 1 and s["payloads"] == 1
    assert s["join"]["join_verdict"] == "MATCH"


def test_all_captures_outside_window_still_reports_join(tmp_path):
    loaded = _cap(tmp_path, _agd([_kill()]), ts=5.0)
    s = lx07.check(lx07.read_log(tmp_path / "none.jsonl"), loaded, since=100.0)
    assert s["captures_outside_window"] == 1
    assert s["join"]["join_verdict"] == "NO_RESULT"


def test_unhashable_values_do_not_crash(tmp_path):
    c = dict(_row()["contributors"][0], source=["ds_burst"])
    assert "basis" in _grade(_row(contributors=[c]))
    ev = dict(_kill(), EventID=[1], EventTime={"t": 1})
    s = lx07.check(lx07.read_log(tmp_path / "none.jsonl"), _cap(tmp_path, _agd([ev])))
    assert s["join"]["own_deaths"] == 1


def test_non_dict_contributor_fails_names_only():
    assert _grade(_row(contributors=["SomePlayer"], shares=None,
                       basis="none")) == ["names_only"]


def test_player_named_like_a_champion_is_not_a_leak():
    assert _grade(_row(), players={"zed", "sr", "estimated", "3142"}) == []


def test_main_never_prints_player_names(tmp_path, capsys):
    ev = _kill()
    payload = _agd([ev])
    path = _write(tmp_path, payload, ev, burst=_burst)
    _cap(tmp_path, payload)
    outs = []
    for extra in ([], ["--json"]):
        assert lx07.main(["--recaps", str(path), "--captures", str(tmp_path / "caps")]
                         + extra) == 0
        out = capsys.readouterr().out
        assert "PlayerOne" not in out and "PlayerTwo" not in out and "PlayerThree" not in out
        assert out.isascii()
        outs.append(out)
    assert json.loads(outs[1])["join"]["join_verdict"] == "MATCH"


def test_main_exit_codes(tmp_path, capsys):
    assert lx07.main(["--recaps", str(tmp_path / "x"), "--captures",
                      str(tmp_path / "nope")]) == 2
    empty = tmp_path / "empty"
    empty.mkdir()
    assert lx07.main(["--recaps", str(tmp_path / "x"), "--captures", str(empty)]) == 2
    assert lx07.main(["--recaps", str(tmp_path / "x"), "--since", "nan"]) == 2
    assert lx07.main(["--recaps", str(tmp_path / "x"), "--since", "abc"]) == 2
    assert lx07.main(["--recaps", str(tmp_path / "x")]) == 0
    capsys.readouterr()
