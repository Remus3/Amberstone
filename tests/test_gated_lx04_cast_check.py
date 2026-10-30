"""Tests for tools/gated_lx04_cast_check.py - the lane-9 read-only replay of one
LX-03 session recording through core.self_cast_log, graded against a Match-V5
participant row (LX-04, RM-606). Sessions are hand-built lines in the recorder's
documented file format, read back through the recorder's own reader; the cost
table is hand-built so no test depends on the DS data patch. Every game id,
match id and player name here is synthetic (RM-906).
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from tools import gated_lx04_cast_check as g

_HDR = {"kind": "header", "schema": 1, "config_key": "unknown",
        "patch": "16.21", "ENGINE_VERSION": "9.9", "mode_key": "sr"}
STEM = "1234567890"
COSTS = {"Q": ("MANA", (50.0, 60.0)), "W": ("MANA", (30.0, 30.0)),
         "E": (None, None), "R": ("MANA", (100.0,))}
RANKS = {"Q": 1, "W": 1, "E": 1, "R": 1}

# (game_time, resourceValue): Q exact at 1.0, Q partial (45 of 50) at 2.0,
# W at 3.0, an R across a 2.5 s poll gap at 6.0, an unmatched 11-point drain
# at 7.0, and a 3-point fall under FALL_THRESHOLD at 8.0.
TAPE = [(0.0, 300), (0.5, 250), (1.0, 251), (1.5, 252), (2.0, 207), (2.5, 208),
        (3.0, 178), (3.5, 179), (6.0, 79), (6.5, 80), (7.0, 69), (7.5, 69),
        (8.0, 66), (8.5, 67)]


def _snap(gt, value, rtype="MANA", maximum=400.0, champ="Ahri"):
    return {
        "activePlayer": {
            "riotId": "Synth#T1",
            "championStats": {"resourceValue": value, "resourceMax": maximum,
                              "resourceType": rtype},
            "abilities": {s: {"abilityLevel": n} for s, n in RANKS.items()},
        },
        "allPlayers": [{"riotId": "Synth#T1", "championName": champ},
                       {"riotId": "Other#T2", "championName": "Garen"}],
        "gameData": {"gameTime": gt},
    }


def _write(path: Path, tape=TAPE, **kw) -> Path:
    lines = [_HDR] + [{"kind": "frame", "seq": i, "captured_at": 1.0e9 + gt,
                       "game_time": gt, "snapshot": _snap(gt, v, **kw)}
                      for i, (gt, v) in enumerate(tape)]
    path.write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")
    return path


def _truth(q=2, w=1, e=0, r=1):
    return {"spell1Casts": q, "spell2Casts": w, "spell3Casts": e, "spell4Casts": r}


def _db(path: Path, rows) -> Path:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE matches (match_id TEXT PRIMARY KEY, queue_id INTEGER,"
                 " game_mode TEXT, game_duration_s INTEGER)")
    conn.execute("CREATE TABLE participants (id INTEGER PRIMARY KEY, match_id TEXT,"
                 " champion_name TEXT, spell1_casts INTEGER, spell2_casts INTEGER,"
                 " spell3_casts INTEGER, spell4_casts INTEGER)")
    conn.execute("INSERT INTO matches VALUES (?, 420, 'CLASSIC', 1800)", ("NA1_" + STEM,))
    conn.execute("INSERT INTO matches VALUES ('NA1_999', 450, 'ARAM', 900)")
    for champ, t in rows:
        conn.execute("INSERT INTO participants (match_id, champion_name, spell1_casts,"
                     " spell2_casts, spell3_casts, spell4_casts) VALUES (?,?,?,?,?,?)",
                     ("NA1_" + STEM, champ, t["spell1Casts"], t["spell2Casts"],
                      t["spell3Casts"], t["spell4Casts"]))
    conn.commit()
    conn.close()
    return path


def test_replay_counts_and_no_truth(tmp_path):
    s = g.check(_write(tmp_path / f"{STEM}.jsonl"), costs=COSTS)
    assert s["verdict"] == "NO_TRUTH"
    assert s["truth_status"] == "none" and s["validation"] is None
    assert s["champions"] == ["Ahri"]
    assert s["frames"] == s["readings"] == len(TAPE)
    assert s["totals"] == {"Q": 2, "W": 1, "E": 0, "R": 1, "unattributed": 1}
    assert s["gap_events"] == 1
    assert s["costs"]["E"]["observable"] is False
    assert s["costs"]["Q"]["observable"] is True
    assert s["unattributed_top"] == [[11, 1]]


def test_remeasure_inputs(tmp_path):
    s = g.check(_write(tmp_path / f"{STEM}.jsonl"), costs=COSTS)
    assert s["cadence"]["over_gap_s"] == 1 and s["cadence"]["max"] == 2.5
    assert s["cadence"]["median"] == 0.5
    assert s["sub_threshold"]["n"] == 1 and s["sub_threshold"]["max"] == 3.0
    sf = s["shortfall"]
    # Q exact, Q partial, W exact; the gap R is a floor and is not graded here.
    assert sf["n"] == 3 and sf["max"] == 5.0
    assert sf["frac_of_tolerance"]["n"] == 1
    assert sf["frac_of_tolerance"]["max"] == pytest.approx(5.0 / 8.0, abs=1e-3)
    assert sf["near_edge"] == 0


def test_truth_json_pass_and_fail(tmp_path):
    p = _write(tmp_path / f"{STEM}.jsonl")
    ok = g.check(p, truth_participant=_truth(), costs=COSTS)
    assert ok["verdict"] == "PASS" and ok["truth_status"] == "ok"
    assert ok["validation"]["slots"]["E"]["compared"] is False
    assert ok["validation"]["slots"]["Q"]["rel_diff"] == 0.0
    bad = g.check(p, truth_participant=_truth(q=20), costs=COSTS)
    assert bad["verdict"] == "FAIL"
    assert bad["validation"]["slots"]["Q"]["within"] is False
    assert bad["validation"]["slots"]["Q"]["rel_diff"] == -0.9


def test_truth_json_without_cast_fields(tmp_path):
    s = g.check(_write(tmp_path / f"{STEM}.jsonl"),
                truth_participant={"championName": "Ahri"}, costs=COSTS)
    assert s["truth_status"] == "json_not_participant" and s["verdict"] == "NO_TRUTH"


def test_truth_db_read_only_join_by_stem(tmp_path):
    d = tmp_path / "dir with space"
    d.mkdir()
    db = _db(d / "rewind.db", [("Ahri", _truth()), ("Garen", _truth(q=99))])
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    s = g.check(_write(tmp_path / f"{STEM}.jsonl"), truth_db=db, costs=COSTS)
    assert s["truth_status"] == "ok" and s["verdict"] == "PASS"
    assert s["truth_match"] == {"queue_id": 420, "game_mode": "CLASSIC",
                                "game_duration_s": 1800}
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before
    assert sorted(p.name for p in d.iterdir()) == ["rewind.db"]


def test_truth_db_statuses(tmp_path):
    db = _db(tmp_path / "rewind.db", [("Ahri", _truth())])
    nog = g.check(_write(tmp_path / "nogameid-1700000000.jsonl"), truth_db=db, costs=COSTS)
    assert nog["truth_status"] == "nogameid_stem" and nog["stem_kind"] == "nogameid"
    miss = g.check(_write(tmp_path / "555.jsonl"), truth_db=db, costs=COSTS)
    assert miss["truth_status"] == "no_match_row" and miss["verdict"] == "NO_TRUTH"
    db2 = _db(tmp_path / "twice.db", [("Ahri", _truth()), ("Ahri", _truth())])
    two = g.check(_write(tmp_path / f"{STEM}.jsonl"), truth_db=db2, costs=COSTS)
    assert two["truth_status"] == "champion_not_unique"
    bad = g.check(_write(tmp_path / f"{STEM}.jsonl"), truth_db=tmp_path / "absent.db",
                  costs=COSTS)
    assert bad["truth_status"] == "db_error"


def test_untracked_resource_is_not_observable(tmp_path):
    s = g.check(_write(tmp_path / f"{STEM}.jsonl", rtype="RAGE"), costs=COSTS)
    assert s["verdict"] == "NOT_OBSERVABLE" and s["events"] == 0


def test_costless_and_unknown_champion(tmp_path):
    p = _write(tmp_path / f"{STEM}.jsonl")
    assert g.check(p, costs={})["verdict"] == "NO_COSTS"
    unk = _write(tmp_path / "77.jsonl", champ="")
    assert g.check(unk, costs=COSTS)["verdict"] == "CHAMPION_UNKNOWN"
    assert g.check(unk, costs=COSTS, champion_id="Ahri")["verdict"] == "NO_TRUTH"


def test_main_prints_no_ids(tmp_path, capsys):
    db = _db(tmp_path / "rewind.db", [("Ahri", _truth())])
    p = _write(tmp_path / f"{STEM}.jsonl")
    for extra in (["--json"], []):
        assert g.main([str(p), "--truth-db", str(db), *extra]) == 0
        out = capsys.readouterr().out
        assert STEM not in out and "Synth" not in out and "Other" not in out
        assert "PASS" in out
        out.encode("ascii")


def test_main_exit_codes(tmp_path, capsys):
    assert g.main([str(tmp_path / "nope.jsonl")]) == 2
    p = _write(tmp_path / f"{STEM}.jsonl")
    bad = tmp_path / "t.json"
    bad.write_text("[1, 2]", encoding="utf-8")
    assert g.main([str(p), "--truth-json", str(bad)]) == 2
    bad.write_text("{not json", encoding="utf-8")
    assert g.main([str(p), "--truth-json", str(bad)]) == 2
    junk = tmp_path / "junk.jsonl"
    junk.write_text("not a header\n", encoding="utf-8")
    assert g.main([str(junk)]) == 2
    err = capsys.readouterr().err
    assert STEM not in err


def test_live_ds_cost_table_is_used_when_present(tmp_path):
    root = Path(g._ROOT) / "data" / "daemon_slayer"
    if not (root / "current.txt").is_file():
        pytest.skip("no DS data in this checkout")
    s = g.check(_write(tmp_path / f"{STEM}.jsonl"))
    assert s["champion_id"] == "Ahri"
    assert s["costs"]["Q"]["resource"] == "MANA" and s["costs"]["Q"]["observable"]
