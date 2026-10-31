"""Tests for tools/gated_g246_killer_readers.py (G2-46 PREP, s144 lane gated).

Every payload is hand-built and name-scrubbed (RM-906): players are
``PlayerN#TST`` and the champions are ordinary champion names. The tool is a
read-only grader; these tests check its per-reader grading, its verdicts, that
the two mirrored readers still match their source, and that no name ever
reaches its output.
"""
from __future__ import annotations

import json
from pathlib import Path

from tools import gated_g246_killer_readers as g246

ROOT = Path(__file__).resolve().parent.parent


def _player(champ: str, game_name: str, team: str) -> dict:
    return {"championName": champ, "summonerName": f"{game_name}#TST",
            "riotId": f"{game_name}#TST", "riotIdGameName": game_name,
            "riotIdTagLine": "TST", "team": team}


ROSTER = [_player("Ashe", "PlayerOne", "ORDER"),
          _player("Leona", "PlayerTwo", "ORDER"),
          _player("Zed", "PlayerThree", "CHAOS"),
          _player("Lux", "PlayerFour", "CHAOS")]
NAMES = ["Ashe", "Leona", "Zed", "Lux", "PlayerOne", "PlayerTwo", "PlayerThree",
         "PlayerFour", "TST"]


def _payload(events: list, roster: list | None = None, me: str = "PlayerOne#TST",
             game_time: float = 900.0) -> dict:
    return {"activePlayer": {"summonerName": me},
            "allPlayers": roster if roster is not None else ROSTER,
            "events": {"Events": events},
            "gameData": {"gameMode": "CLASSIC", "gameTime": game_time}}


def _kill(eid: int, killer: str, victim: str, t: float = 300.0) -> dict:
    return {"EventID": eid, "EventName": "ChampionKill", "EventTime": t,
            "KillerName": killer, "VictimName": victim, "Assisters": []}


def _obj(eid: int, name: str, killer: str, t: float = 600.0, **extra) -> dict:
    e = {"EventID": eid, "EventName": name, "EventTime": t, "KillerName": killer,
         "Stolen": "False", "Assisters": []}
    e.update(extra)
    return e


def _set(tmp_path: Path, events: list, n: int = 2, span: float = 60.0, **kw) -> Path:
    d = tmp_path / "caps"
    d.mkdir()
    for i in range(n):
        body = _payload(events, game_time=900.0 + i * span, **kw)
        wrapped = {"ts": 1000.0 + i * span, "data": body}
        (d / f"c{i}.json").write_text(json.dumps(wrapped), encoding="utf-8")
    return d


def _run(path: Path) -> dict:
    return g246.check(g246.lx02.load(path))


# -- verdicts ----------------------------------------------------------------

def test_player_form_everywhere_flags_the_champion_only_readers(tmp_path):
    ev = [_kill(1, "PlayerThree", "PlayerOne"),
          _obj(2, "DragonKill", "PlayerThree", DragonType="Fire"),
          _obj(3, "HordeKill", "PlayerTwo")]
    s = _run(_set(tmp_path, ev))
    g = s["g246"]
    assert g["verdict"] == "SETTLED"
    assert (g["championkill_form"], g["objective_form"]) == ("PLAYER", "PLAYER")
    assert g["row_premise"] == "SAME_FORM"
    assert g["silent_features"] == "CONFIRMED"
    r = s["readers"]
    assert r["dashboard_liveclient"]["verdict"] == "BLIND"
    assert r["live_event_deriver"]["verdict"] == "RESOLVES"
    assert r["death_recap"]["verdict"] == "RESOLVES"
    assert r["snapshot_normalizer"]["verdict"] == "RESOLVES"
    # decision_detector compares summonerName OR riotIdGameName: a present
    # summonerName ("PlayerThree#TST") shadows the bare game name
    assert r["decision_detector"]["verdict"] == "BLIND"
    assert g["blind_readers"] == ["dashboard_liveclient", "decision_detector"]


def test_decision_detector_resolves_the_full_summoner_name(tmp_path):
    ev = [_kill(1, "PlayerThree#TST", "PlayerOne#TST"),
          _obj(2, "DragonKill", "Zed", DragonType="Fire")]
    s = _run(_set(tmp_path, ev))
    assert s["readers"]["decision_detector"]["verdict"] == "RESOLVES"
    assert s["readers"]["death_recap"]["verdict"] == "RESOLVES"


def test_fixture_like_split_reads_form_by_event(tmp_path):
    ev = [_kill(1, "PlayerThree#TST", "PlayerOne#TST"),
          _obj(2, "DragonKill", "Zed", DragonType="Fire"),
          _obj(3, "BaronKill", "Ashe")]
    s = _run(_set(tmp_path, ev))
    g = s["g246"]
    assert g["verdict"] == "SETTLED"
    assert (g["championkill_form"], g["objective_form"]) == ("PLAYER", "CHAMPION")
    assert g["row_premise"] == "FORM_BY_EVENT"
    assert g["silent_features"] == "REFUTED"
    assert s["readers"]["dashboard_liveclient"]["verdict"] == "RESOLVES"
    assert s["readers"]["live_event_deriver"]["verdict"] == "RESOLVES"
    assert g["blind_readers"] == []


def test_champion_kill_in_champion_form_blinds_decision_detector(tmp_path):
    ev = [_kill(1, "Zed", "Ashe"), _obj(2, "DragonKill", "Zed", DragonType="Fire")]
    s = _run(_set(tmp_path, ev))
    assert s["g246"]["championkill_form"] == "CHAMPION"
    assert s["readers"]["decision_detector"]["verdict"] == "BLIND"
    # death_recap accepts a champion name when it is unique on the roster
    assert s["readers"]["death_recap"]["verdict"] == "RESOLVES"


def test_mixed_class_reads_mixed(tmp_path):
    ev = [_kill(1, "PlayerThree#TST", "PlayerOne#TST"),
          _obj(2, "DragonKill", "Zed", DragonType="Fire"),
          _obj(3, "DragonKill", "PlayerThree", DragonType="Earth")]
    s = _run(_set(tmp_path, ev))
    assert s["g246"]["objective_form"] == "MIXED"
    assert s["g246"]["verdict"] == "MIXED"
    assert s["g246"]["row_premise"] is None
    assert s["readers"]["dashboard_liveclient"]["verdict"] == "PARTIAL"


def test_no_objective_reads_partial(tmp_path):
    s = _run(_set(tmp_path, [_kill(1, "PlayerThree#TST", "PlayerOne#TST")]))
    assert s["g246"]["objective_form"] == "NONE"
    assert s["g246"]["verdict"] == "PARTIAL"
    assert s["g246"]["silent_features"] == "UNDETERMINED"
    assert s["readers"]["dashboard_liveclient"]["verdict"] == "NO_DATA"


def test_grub_only_capture_cannot_decide_the_silent_callouts(tmp_path):
    # verifier repro (s144 c39): the three callouts read dragon / baron takes
    # only, so a blind dashboard on HordeKill alone must not CONFIRM them
    ev = [_kill(1, "PlayerThree#TST", "PlayerOne#TST"),
          _obj(2, "HordeKill", "PlayerThree"), _obj(3, "HordeKill", "PlayerThree")]
    s = _run(_set(tmp_path, ev))
    assert s["g246"]["verdict"] == "SETTLED"
    assert s["readers"]["dashboard_liveclient"]["verdict"] == "BLIND"
    assert s["dashboard_epic_counts"] == {}
    assert s["g246"]["silent_features"] == "UNDETERMINED"


def test_silent_features_ignores_grub_takes_beside_a_drake(tmp_path):
    ev = [_kill(1, "PlayerThree#TST", "PlayerOne#TST"),
          _obj(2, "HordeKill", "PlayerThree"),
          _obj(3, "DragonKill", "Zed", DragonType="Fire")]
    s = _run(_set(tmp_path, ev))
    assert s["dashboard_epic_counts"] == {"resolved": 2}
    assert s["g246"]["silent_features"] == "REFUTED"


# -- capture-set validity (the substitution look-alikes) -------------------------

def test_single_capture_is_no_result(tmp_path):
    ev = [_kill(1, "PlayerThree#TST", "PlayerOne#TST"),
          _obj(2, "DragonKill", "Zed", DragonType="Fire")]
    s = _run(_set(tmp_path, ev, n=1))
    assert s["valid"] is False
    assert s["g246"]["verdict"] == "NO_RESULT"
    assert s["g246"]["silent_features"] == "UNDETERMINED"


def test_short_span_is_no_result(tmp_path):
    ev = [_obj(2, "DragonKill", "Zed", DragonType="Fire"),
          _kill(1, "PlayerThree#TST", "PlayerOne#TST")]
    s = _run(_set(tmp_path, ev, span=10.0))
    assert s["relay_ts_span_s"] == 10.0
    assert s["g246"]["verdict"] == "NO_RESULT"


def test_unwrapped_captures_have_no_span_and_are_no_result(tmp_path):
    d = tmp_path / "raw"
    d.mkdir()
    for i in range(2):
        body = _payload([_kill(1, "PlayerThree#TST", "PlayerOne#TST"),
                         _obj(2, "DragonKill", "Zed", DragonType="Fire")],
                        game_time=900.0 + i)
        (d / f"r{i}.json").write_text(json.dumps(body), encoding="utf-8")
    s = _run(d)
    assert s["relay_ts_span_s"] is None
    assert s["g246"]["verdict"] == "NO_RESULT"


def test_one_body_restamped_with_a_new_ts_is_no_result(tmp_path):
    # the relay stamps ts per upload, so a re-pushed cached body differs only
    # in its wrapper ts: one game moment, one read
    d = tmp_path / "restamp"
    d.mkdir()
    body = _payload([_kill(1, "PlayerThree#TST", "PlayerOne#TST"),
                     _obj(2, "DragonKill", "Zed", DragonType="Fire")])
    for i, ts in enumerate((1000.0, 1100.0)):
        (d / f"s{i}.json").write_text(json.dumps({"ts": ts, "data": body}), encoding="utf-8")
    s = _run(d)
    assert s["duplicates"] == 0
    assert s["distinct_game_times"] == 1
    assert s["valid"] is False
    assert s["g246"]["verdict"] == "NO_RESULT"


def test_mode_and_game_time_are_reported(tmp_path):
    s = _run(_set(tmp_path, [_obj(2, "DragonKill", "Zed", DragonType="Fire")]))
    assert s["game_modes"] == ["CLASSIC"]
    assert s["game_time_max"] == 960.0
    assert s["distinct_game_times"] == 2


def test_duplicate_file_is_no_result(tmp_path):
    d = _set(tmp_path, [_obj(2, "DragonKill", "Zed", DragonType="Fire")])
    (d / "copy.json").write_bytes((d / "c0.json").read_bytes())
    s = _run(d)
    assert s["duplicates"] == 1
    assert s["g246"]["verdict"] == "NO_RESULT"


def test_rm601_fixture_reads_synthetic_and_no_result():
    s = _run(g246.lx02.FIXTURE)
    assert s["synthetic"] == 1
    assert s["g246"]["verdict"] == "NO_RESULT"


# -- what is counted but never graded --------------------------------------------

def test_turret_and_minion_killers_are_not_graded(tmp_path):
    ev = [_kill(1, "Turret_T2_L_03_A", "PlayerOne#TST"),
          _obj(2, "HeraldKill", "SRU_RiftHerald17.1.1")]
    s = _run(_set(tmp_path, ev))
    r = s["readers"]
    assert r["death_recap"]["verdict"] == "NO_DATA"
    assert r["death_recap"]["counts"] == {"not_member_unresolved": 2}
    assert r["dashboard_liveclient"]["counts"] == {"not_member_unresolved": 2}
    assert s["forms_by_class"]["objective"] == {"nonplayer": 2}


def test_no_self_identification_is_counted_not_graded(tmp_path):
    ev = [_kill(1, "PlayerThree#TST", "PlayerOne#TST"),
          _obj(2, "DragonKill", "Zed", DragonType="Fire")]
    s = _run(_set(tmp_path, ev, me="NotOnRoster#TST"))
    r = s["readers"]
    assert s["self_identified"] == {"dashboard_liveclient": 0, "decision_detector": 0,
                                    "live_event_deriver": 0}
    for name in ("dashboard_liveclient", "live_event_deriver", "decision_detector"):
        assert r[name]["verdict"] == "NO_DATA", name
        assert r[name]["counts"].get("no_self") == 2, name
    # death_recap and the normalizer need no self-identification
    assert r["death_recap"]["verdict"] == "RESOLVES"
    assert r["snapshot_normalizer"]["verdict"] == "RESOLVES"


def test_mirror_champion_is_ambiguous_for_the_dashboard(tmp_path):
    roster = ROSTER[:3] + [_player("Leona", "PlayerFour", "CHAOS")]
    ev = [_obj(2, "DragonKill", "Leona", DragonType="Fire")]
    s = _run(_set(tmp_path, ev, roster=roster))
    r = s["readers"]
    assert r["dashboard_liveclient"]["counts"] == {"ambiguous": 2}
    assert r["dashboard_liveclient"]["verdict"] == "NO_DATA"
    # the deriver drops a duplicated championName; the normalizer drops shared keys
    assert r["live_event_deriver"]["verdict"] == "BLIND"
    assert r["snapshot_normalizer"]["verdict"] == "BLIND"


def test_elder_is_outside_the_normalizer_scope(tmp_path):
    ev = [_obj(2, "DragonKill", "Zed", DragonType="Elder")]
    s = _run(_set(tmp_path, ev))
    assert s["readers"]["snapshot_normalizer"]["counts"] == {}
    assert s["readers"]["dashboard_liveclient"]["verdict"] == "RESOLVES"


def test_objective_without_event_id_is_not_emitted_by_the_deriver(tmp_path):
    e = _obj(2, "DragonKill", "Zed", DragonType="Fire")
    del e["EventID"]
    s = _run(_set(tmp_path, [e]))
    assert s["readers"]["live_event_deriver"]["counts"] == {"not_emitted": 2}


def test_event_without_killer_key_is_skipped(tmp_path):
    e = _obj(2, "DragonKill", "Zed", DragonType="Fire")
    del e["KillerName"]
    s = _run(_set(tmp_path, [e]))
    assert s["forms_by_class"] == {"ChampionKill": {}, "objective": {}}


def test_mirror_champion_on_self_leaves_the_deriver_without_self(tmp_path):
    # the deriver drops BOTH rows of a duplicated championName, so a mirror on
    # the active player's own champion costs it self-identification
    roster = ROSTER[:3] + [_player("Ashe", "PlayerFour", "CHAOS")]
    s = _run(_set(tmp_path, [_obj(2, "DragonKill", "Zed", DragonType="Fire")],
                  roster=roster))
    assert s["self_identified"]["live_event_deriver"] == 0
    assert s["readers"]["live_event_deriver"]["counts"] == {"no_self": 2}


def test_junk_shapes_do_not_raise(tmp_path):
    d = tmp_path / "junk"
    d.mkdir()
    bodies = [{"ts": 1.0, "data": {"gameData": {}, "events": "x", "allPlayers": 5}},
              {"ts": 99.0, "data": {"gameData": {}, "allPlayers": [1, None],
                                    "events": {"Events": [None, {"EventName": 7},
                                                          {"EventName": "ChampionKill",
                                                           "KillerName": 3}]}}}]
    for i, b in enumerate(bodies):
        (d / f"j{i}.json").write_text(json.dumps(b), encoding="utf-8")
    s = _run(d)
    assert s["payloads"] == 2
    assert s["forms_by_class"]["ChampionKill"] == {"empty": 1}


def test_non_string_name_fields_do_not_raise(tmp_path):
    roster = [dict(ROSTER[0]), dict(ROSTER[1]), dict(ROSTER[2], championName=["Zed"]),
              dict(ROSTER[3], summonerName={"x": 1})]
    ev = [_kill(1, "PlayerThree#TST", "PlayerOne#TST"),
          _obj(2, "DragonKill", "Zed", DragonType="Fire")]
    s = _run(_set(tmp_path, ev, roster=roster))
    assert s["payloads"] == 2
    assert s["forms_by_class"]["objective"] == {"unmapped": 2}


# -- output safety and the CLI ---------------------------------------------------

def test_no_name_reaches_the_output(tmp_path, capsys):
    ev = [_kill(1, "PlayerThree#TST", "PlayerOne#TST"),
          _obj(2, "DragonKill", "Zed", DragonType="Fire"),
          _obj(3, "HordeKill", "Leona")]
    d = _set(tmp_path, ev)
    for args in ([str(d)], [str(d), "--json"]):
        assert g246.main(args) == 0
        out = capsys.readouterr().out
        for n in NAMES:
            assert n not in out, n


def test_exit_codes(tmp_path, capsys):
    assert g246.main([str(tmp_path / "missing")]) == 2
    empty = tmp_path / "empty"
    empty.mkdir()
    assert g246.main([str(empty)]) == 2
    one = _set(tmp_path, [_obj(2, "DragonKill", "Zed", DragonType="Fire")], n=1)
    assert g246.main([str(one)]) == 3
    capsys.readouterr()


def test_reader_table_is_the_five_named():
    assert g246.READERS == {"dashboard_liveclient": "mirror", "decision_detector": "real",
                            "live_event_deriver": "real", "death_recap": "real",
                            "snapshot_normalizer": "mirror"}


# -- source pins: the two mirrors and the scopes the tool assumes ----------------

def _src(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_pin_dashboard_reader_is_champion_only():
    s = _src("dashboard/_liveclient.py")
    assert 'enemy_team = [_str_or(p.get("championName"), "")' in s
    assert "enemy_set = {c for c in enemy_team if c}" in s
    assert "elif killer in enemy_set:" in s
    assert 'killer = ev.get("KillerName")' in s


def test_pin_normalizer_side_keys_and_shared_drop():
    s = _src("game_reader/snapshot_normalizer.py")
    assert ('for field in ("riotIdGameName", "summonerName", "riotIdPlusTagLine",\n'
            '                      "riotId", "championName"):') in s
    assert "_shared = _ally_keys & _enemy_keys" in s
    assert 'if isinstance(dtype, str) and dtype.strip().lower() == "elder":' in s
    assert 'return name.split("#")[0].strip().lower()' in s


def test_pin_decision_detector_scope_and_rule():
    s = _src("core/decision_detector.py")
    assert s.count('"KillerName"') == 1
    assert 'if ev.get("EventName") != "ChampionKill":' in s
    assert '(p.get("summonerName") or p.get("riotIdGameName")) == name' in s


def test_pin_death_recap_scope():
    s = _src("core/death_recap.py")
    assert 'names: list[tuple[str, Any]] = [("killer", ev.get("KillerName"))]' in s
    assert 'if ev.get("EventName") != "ChampionKill":' in s


def test_pin_deriver_identity_keys():
    s = _src("core/live_event_deriver.py")
    assert '_IDENTITY_KEYS = ("summonerName", "riotId", "riotIdGameName")' in s
    assert '"killer_team": _killer_team(e.get("KillerName"), c, cp, my_team),' in s
