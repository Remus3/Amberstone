"""Tests for tools/gated_lx08_ranks_check.py (LX-08 PREP, s144 lane gated).

Every payload here is hand-built and name-scrubbed (RM-906): players are
``PlayerN#TST`` and the champions are ordinary champion names. The tool is a
read-only grader, so the tests check its classification, its verdicts and that
no player name ever reaches its output.
"""
from __future__ import annotations

import json
from pathlib import Path

from tools import gated_lx08_ranks_check as lx08

ME = "PlayerOne#TST"


def _abilities(q=0, w=0, e=0, r=0, names=True) -> dict:
    out = {}
    for slot, lvl in zip(("Q", "W", "E", "R"), (q, w, e, r)):
        entry = {"abilityLevel": lvl}
        if names:
            entry["displayName"] = f"Spell{slot}"
        out[slot] = entry
    out["Passive"] = {"displayName": "Passive"}
    return out


def _agd(champ="Ashe", level=1, abilities=None, mode="CLASSIC", me_name=ME) -> dict:
    return {
        "activePlayer": {"summonerName": me_name, "riotIdGameName": "PlayerOne",
                         "level": level,
                         "abilities": _abilities() if abilities is None else abilities},
        "allPlayers": [
            {"championName": champ, "summonerName": ME, "riotId": ME,
             "riotIdGameName": "PlayerOne", "team": "ORDER"},
            {"championName": "Zed", "summonerName": "PlayerTwo#TST",
             "riotId": "PlayerTwo#TST", "riotIdGameName": "PlayerTwo", "team": "CHAOS"},
        ],
        "events": {"Events": []},
        "gameData": {"gameMode": mode, "gameTime": 90.0},
    }


def _write(tmp_path: Path, name: str, obj: dict) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(obj), encoding="utf-8")
    return p


def _wrap(obj: dict, ts: float) -> dict:
    return {"ts": ts, "data": obj}


def _run(tmp_path: Path) -> dict:
    return lx08.check(lx08.load(tmp_path))


def test_kind_classes():
    assert lx08.kind(_agd()) == "allgamedata"
    assert lx08.kind({"gameData": {}}) == "allgamedata"
    assert lx08.kind(_abilities()) == "apa"
    assert lx08.kind({"foo": 1}) == "other"


def test_relay_wrapper_is_unwrapped_and_ranks_present(tmp_path):
    _write(tmp_path, "a.json", _wrap(_agd(level=1, abilities=_abilities(q=1)), 100.0))
    _write(tmp_path, "b.json", _wrap(_agd(level=3, abilities=_abilities(1, 1, 1)), 160.0))
    s = _run(tmp_path)
    assert s["kinds"] == {"allgamedata": 2, "apa": 0, "other": 0}
    assert s["ranks"]["verdict"] == "PRESENT"
    assert s["ranks"]["reads"] == 2
    assert s["relay_ts_span_s"] == 60.0
    assert s["ranks"]["abilityLevel_types"]["Q"] == {"number": 2}
    assert s["self"]["exact"] == 2
    assert s["per_mode"]["CLASSIC"]["verdict"] == "CONSISTENT"
    assert s["per_mode"]["CLASSIC"]["unspent_min"] == 0
    assert s["modes_agree"] is True


def test_missing_abilities_reads_absent(tmp_path):
    p = _agd()
    p["activePlayer"].pop("abilities")
    _write(tmp_path, "a.json", p)
    s = _run(tmp_path)
    assert s["ranks"]["verdict"] == "ABSENT"
    assert s["ranks"]["abilityLevel_types"]["R"] == {"missing": 1}
    assert s["per_mode"] == {}
    assert s["modes_agree"] is False


def test_one_slot_missing_level_reads_partial(tmp_path):
    ab = _abilities(q=1)
    ab["R"].pop("abilityLevel")
    _write(tmp_path, "a.json", _agd(abilities=ab))
    _write(tmp_path, "b.json", _agd(level=2, abilities=_abilities(q=1, w=1)))
    s = _run(tmp_path)
    assert s["ranks"]["verdict"] == "PARTIAL"
    assert s["ranks"]["reads"] == 1


def test_string_rank_is_not_an_int_rank(tmp_path):
    # The tracker accepts a numeric string; the wire contract LX-08 checks is
    # an integer, so a string rank keeps the verdict off PRESENT.
    _write(tmp_path, "a.json", _agd(abilities=_abilities(q="1")))
    s = _run(tmp_path)
    assert s["ranks"]["abilityLevel_types"]["Q"] == {"string": 1}
    assert s["ranks"]["verdict"] == "PARTIAL"


def test_bool_rank_reads_bool_type(tmp_path):
    _write(tmp_path, "a.json", _agd(abilities=_abilities(q=True)))
    s = _run(tmp_path)
    assert s["ranks"]["abilityLevel_types"]["Q"] == {"bool": 1}
    # The tracker rejects a bool (True is not rank 1), so nothing reads, while
    # W/E/R still carry integer ranks: PARTIAL, never PRESENT.
    assert s["ranks"]["reads"] == 0
    assert s["ranks"]["verdict"] == "PARTIAL"


def test_free_r_reads_1(tmp_path):
    _write(tmp_path, "a.json", _agd(champ="Jayce", level=1, abilities=_abilities(q=1, r=1)))
    _write(tmp_path, "b.json", _agd(champ="Jayce", level=2,
                                   abilities=_abilities(q=1, w=1, r=1)))
    s = _run(tmp_path)
    assert s["free_r"]["verdict"] == "READS_1"
    assert s["free_r"]["level1_payloads"] == 1
    assert s["free_r"]["champions"] == ["Jayce"]
    # free rank excluded from the spent sum: level 1, Q 1 + R 1 (free) = 0 unspent
    assert s["per_mode"]["CLASSIC"]["unspent_min"] == 0
    assert s["per_mode"]["CLASSIC"]["verdict"] == "CONSISTENT"


def test_free_r_reads_0_and_mixed(tmp_path):
    _write(tmp_path, "a.json", _agd(champ="Elise", level=1, abilities=_abilities(q=1)))
    assert _run(tmp_path)["free_r"]["verdict"] == "READS_0"
    _write(tmp_path, "b.json", _agd(champ="Karma", level=1, abilities=_abilities(r=1)))
    s = _run(tmp_path)
    assert s["free_r"]["verdict"] == "MIXED"
    assert s["free_r"]["champions"] == ["Elise", "Karma"]


def test_free_r_no_result_without_level1_free_kit(tmp_path):
    _write(tmp_path, "a.json", _agd(champ="Ashe", level=1))
    _write(tmp_path, "b.json", _agd(champ="Nidalee", level=4,
                                   abilities=_abilities(1, 1, 1, 1)))
    assert _run(tmp_path)["free_r"]["verdict"] == "NO_RESULT"


def test_free_r_kits_track_the_tracker_table():
    assert set(lx08.FREE_R_KITS) == {"Jayce", "Elise", "Nidalee", "Karma"}
    assert lx08.FENCED_KITS == ("Aphelios",)


def test_aphelios_is_recorded_not_graded(tmp_path):
    _write(tmp_path, "a.json", _agd(champ="Aphelios", level=1,
                                   abilities=_abilities(q=1, w=1, e=1)))
    s = _run(tmp_path)
    assert s["fenced"] == [{"champion": "Aphelios", "level": 1,
                            "ranks": {"q": 1, "w": 1, "e": 1, "r": 0}}]
    assert s["per_mode"] == {}


def test_inconsistent_mode_out_of_range_and_over_cap(tmp_path):
    # ARAM at level 3 with 4 ranks spent -> unspent -1 (out of range).
    _write(tmp_path, "a.json", _agd(level=3, mode="ARAM", abilities=_abilities(2, 1, 1)))
    # Rift at level 6 with Q at rank 4 -> over the level-6 basic cap of 3.
    _write(tmp_path, "b.json", _agd(level=6, abilities=_abilities(4, 1, 1)))
    # Arena consistent.
    _write(tmp_path, "c.json", _agd(level=3, mode="CHERRY", abilities=_abilities(1, 1, 1)))
    s = _run(tmp_path)
    assert s["per_mode"]["ARAM"]["verdict"] == "INCONSISTENT"
    assert s["per_mode"]["ARAM"]["out_of_range"] == 1
    assert s["per_mode"]["CLASSIC"]["verdict"] == "INCONSISTENT"
    assert s["per_mode"]["CLASSIC"]["over_cap"] == 1
    assert s["per_mode"]["CHERRY"]["verdict"] == "CONSISTENT"
    assert s["modes_agree"] is False
    assert s["game_modes"] == ["ARAM", "CHERRY", "CLASSIC"]


def test_self_folded_and_none(tmp_path):
    _write(tmp_path, "a.json", _agd(champ="Karma", level=1, me_name="playerone",
                                   abilities=_abilities(r=1)))
    s = _run(tmp_path)
    assert s["self"] == {"exact": 0, "folded": 1, "none": 0}
    assert s["free_r"]["verdict"] == "READS_1"
    p = _agd(me_name="Nobody#TST")
    p["activePlayer"]["riotIdGameName"] = "Nobody"
    _write(tmp_path, "b.json", p)
    assert _run(tmp_path)["self"]["none"] == 1


def test_apa_readable_drop_and_no_rank(tmp_path):
    _write(tmp_path, "apa1.json", _abilities(q=1))
    s = _run(tmp_path)
    assert s["kinds"]["apa"] == 1
    assert s["apa"]["verdict"] == "READABLE"
    assert s["ranks"]["verdict"] == "NO_RESULT"
    nameless = _abilities(q=1)
    nameless["E"]["displayName"] = ""
    _write(tmp_path, "apa2.json", nameless)
    s = _run(tmp_path)
    assert s["apa"]["verdict"] == "DROPS_SLOT"
    assert s["apa"]["dropped_slots"] == ["E"]


def test_apa_no_rank(tmp_path):
    ab = _abilities()
    ab["W"].pop("abilityLevel")
    _write(tmp_path, "apa.json", ab)
    assert _run(tmp_path)["apa"]["verdict"] == "NO_RANK"


def test_duplicates_and_synthetic(tmp_path):
    p = _agd()
    _write(tmp_path, "a.json", p)
    _write(tmp_path, "b.json", p)
    syn = _agd()
    syn["_comment"] = "SYNTHETIC fixture"
    _write(tmp_path, "c.json", syn)
    s = _run(tmp_path)
    assert s["duplicates"] == 1
    assert s["synthetic"] == 1


def test_no_player_name_in_output(tmp_path, capsys):
    _write(tmp_path, "a.json", _wrap(_agd(champ="Jayce", abilities=_abilities(q=1, r=1)), 1.0))
    _write(tmp_path, "apa.json", _abilities(q=1))
    for argv in ([str(tmp_path)], [str(tmp_path), "--json"]):
        assert lx08.main(argv) == 0
        out = capsys.readouterr().out
        assert "Player" not in out
        assert "TST" not in out
        assert "SpellQ" not in out
        assert "Jayce" in out


def test_main_exit_2_on_nothing(tmp_path, capsys):
    assert lx08.main([str(tmp_path / "missing")]) == 2
    assert lx08.main([str(tmp_path)]) == 2
    capsys.readouterr()


def test_tool_is_read_only_source():
    src = Path(lx08.__file__).read_text(encoding="utf-8")
    for needle in ("write_text", "write_bytes", "unlink", "rename(", "replace(",
                   "urlopen", "requests", "socket", "subprocess", "open("):
        assert needle not in src, needle


def test_dashboard_reader_is_the_one_run():
    # The ranks verdict runs the dashboard's exact call, not a copy.
    src = Path(lx08.__file__).read_text(encoding="utf-8")
    assert "spt.read_skill_snapshot(" in src
    dash = (Path(lx08.__file__).resolve().parent.parent / "dashboard" / "_liveclient.py"
            ).read_text(encoding="utf-8")
    assert "read_skill_snapshot(" in dash
    assert '"abilities": ap.get("abilities")' in dash


def test_lower_case_apa_and_level_fallback_and_bad_roster(tmp_path):
    # The normalizer accepts lower-case slots and a `level` key; so does the grader.
    body = {s.lower(): {"displayName": f"Spell{s}", "level": 1} for s in "QWER"}
    _write(tmp_path, "apa.json", body)
    s = _run(tmp_path)
    assert s["kinds"]["apa"] == 1
    assert s["apa"]["verdict"] == "READABLE"
    p = _agd()
    p["allPlayers"] = 5
    assert lx08.self_row(p) == ("none", None)
