"""Tests for tools/gated_lx01_draft_check.py (LX-01 / RM-609 drain grader).

Rows are written by the real ``lcu.draft_log.store_draft`` from a parsed
synthetic session into a tmp_path DB; ids are hand-written synthetic values
(RM-906).
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone

import pytest

from lcu import draft_log as dl
from tools import gated_lx01_draft_check as g

GID = 9000000001
MID = f"XX1_{GID}"
CAPTURED = "2026-01-02T03:04:30Z"
CAP_T = datetime(2026, 1, 2, 3, 4, 30, tzinfo=timezone.utc).timestamp()
POS = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]
ALLY_FINAL = [101, 102, 104, 103, 105]  # cells 2 and 3 traded 103 <-> 104
ENEMY_FINAL = [201, 202, 203, 204, 205]


def _session(gid=GID, queue=420, local=2):
    my = [{"cellId": i, "championId": ALLY_FINAL[i], "assignedPosition": POS[i].lower()}
          for i in range(5)]
    their = [{"cellId": 5 + i, "championId": ENEMY_FINAL[i], "assignedPosition": ""}
             for i in range(5)]
    bans = [{"actorCellId": c, "type": "ban", "championId": 300 + c, "completed": True}
            for c in range(10)]
    locked = {0: 101, 1: 102, 2: 103, 3: 104, 4: 105}
    picks = [[{"actorCellId": c, "type": "pick", "championId": locked[c], "completed": True}]
             for c in range(5)]
    picks += [[{"actorCellId": 5 + i, "type": "pick", "championId": ENEMY_FINAL[i],
                "completed": True}] for i in range(5)]
    return {"gameId": gid, "localPlayerCellId": local, "myTeam": my, "theirTeam": their,
            "actions": [bans] + picks, "timer": {"phase": "FINALIZATION"},
            "gameData": {"queue": {"id": queue}}}


def _match_tables(conn):
    conn.executescript(
        "CREATE TABLE matches (match_id TEXT PRIMARY KEY, queue_id INTEGER, "
        "tracked_team_id INTEGER, tracked_champion_id INTEGER, game_creation_ts INTEGER);"
        "CREATE TABLE participants (match_id TEXT, team_id INTEGER, champion_id INTEGER, "
        "team_position TEXT);")


def _add_match(conn, mid=MID, queue=420, created_ms=None, enemy=ENEMY_FINAL, tracked=104):
    created_ms = int(CAP_T * 1000) if created_ms is None else created_ms
    conn.execute("INSERT INTO matches VALUES (?,?,?,?,?)", (mid, queue, 100, tracked, created_ms))
    for i in range(5):
        conn.execute("INSERT INTO participants VALUES (?,?,?,?)", (mid, 100, ALLY_FINAL[i], POS[i]))
        conn.execute("INSERT INTO participants VALUES (?,?,?,?)", (mid, 200, enemy[i], POS[i]))
    conn.commit()


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "rewind_history.db"
    conn = sqlite3.connect(path)
    _match_tables(conn)
    assert dl.store_draft(conn, GID, dl.parse_draft(_session()), queue_id=420) == 20
    conn.execute("UPDATE draft_log SET captured_at=?", (CAPTURED,))
    conn.commit()
    yield path, conn
    conn.close()


def _grade(path, **kw):
    conn = g._ro(path)
    try:
        return g.grade(conn, **kw)
    finally:
        conn.close()


def test_clean_draft_joins_ok(db):
    path, conn = db
    _add_match(conn)
    s = _grade(path)
    assert s["table_present"] is True
    (game,) = s["games"]
    assert game["problems"] == []
    assert game["actions"] == 20 and game["types"] == {"ban": 10, "pick": 10}
    assert (game["picks_ally"], game["picks_enemy"]) == (5, 5)
    assert game["swaps"] == 2
    assert game["enemy_position_hidden"] == 5
    j = game["join"]
    assert j["verdict"] == "JOIN_OK", j
    assert j["tracked_position"] == "MIDDLE"
    assert j["lane_opponent_champion_id"] == 203 == j["expected_opponent_champion_id"]
    assert j["local_picked_before_opponent"] is True


def test_table_absent_reads_empty(tmp_path):
    path = tmp_path / "r.db"
    c = sqlite3.connect(path)
    _match_tables(c)
    c.close()
    s = _grade(path)
    assert s == {"table_present": False, "games": [], "no_draft_matches": []}


def test_no_match_row(db):
    path, _ = db
    assert _grade(path)["games"][0]["join"] == {"verdict": "NO_MATCH_ROW"}


def test_other_suffix_does_not_join(db):
    path, conn = db
    _add_match(conn, mid=f"XX1_1{GID}")  # a LIKE '%_<gid>' near miss
    assert _grade(path)["games"][0]["join"]["verdict"] == "NO_MATCH_ROW"


def test_roster_disagreement_is_a_mismatch(db):
    path, conn = db
    _add_match(conn, enemy=[201, 202, 299, 204, 205], tracked=103)
    j = _grade(path)["games"][0]["join"]
    assert j["verdict"] == "JOIN_MISMATCH"
    assert "enemy pick finals != other team champions" in j["mismatches"]
    assert "local final != matches.tracked_champion_id" in j["mismatches"]


def test_queue_disagreement_is_a_mismatch(db):
    path, conn = db
    _add_match(conn, queue=400)
    j = _grade(path)["games"][0]["join"]
    assert j["mismatches"] == ["draft queue_id != matches.queue_id"]


def test_shape_problems(tmp_path):
    path = tmp_path / "r.db"
    c = sqlite3.connect(path)
    sess = _session(local=7)
    sess["actions"][1][0]["completed"] = False
    sess["myTeam"][1]["championId"] = 0
    dl.store_draft(c, GID, dl.parse_draft(sess), queue_id=420)
    c.execute("UPDATE draft_log SET captured_at=? WHERE action_index < 5", (CAPTURED,))
    c.commit()
    c.close()
    probs = _grade(path)["games"][0]["problems"]
    assert "more than one captured_at" in probs
    assert "an incomplete pick at finalize" in probs
    assert "a pick with no final champion" in probs
    assert "0 local pick rows (want 1)" not in probs  # cell 7 is an enemy pick: still 1
    sess2 = _session(local=-1)
    c = sqlite3.connect(path)
    dl.store_draft(c, GID, dl.parse_draft(sess2), queue_id=420)
    c.close()
    assert "0 local pick rows (want 1)" in _grade(path)["games"][0]["problems"]


def test_unowned_action_and_missing_queue_are_not_failures(tmp_path):
    path = tmp_path / "r.db"
    c = sqlite3.connect(path)
    _match_tables(c)
    sess = _session()
    sess.pop("gameData")
    sess["actions"].insert(1, [{"actorCellId": -1, "type": "ten_bans_reveal", "championId": 0,
                                "completed": True}])
    dl.store_draft(c, GID, dl.parse_draft(sess), queue_id=dl.session_queue_id(sess))
    _add_match(c)
    c.close()
    (game,) = _grade(path)["games"]
    assert game["problems"] == [] and game["unowned_actions"] == 1
    assert game["queue_id"] == 0
    assert game["join"]["verdict"] == "JOIN_OK"


def test_window_filters_draft_rows(db):
    path, _ = db
    assert len(_grade(path, since=CAP_T - 1, until=CAP_T + 1)["games"]) == 1
    assert _grade(path, since=CAP_T + 1)["games"] == []
    assert _grade(path, until=CAP_T - 1)["games"] == []


def test_no_draft_match_reads_clean_none(db):
    path, conn = db
    _add_match(conn)
    _add_match(conn, mid="XX1_9000000002", queue=2400)
    _add_match(conn, mid="XX1_9000000003", queue=450, created_ms=int((CAP_T - 999) * 1000))
    s = _grade(path, since=CAP_T - 10)
    assert [m["queue_id"] for m in s["no_draft_matches"]] == [2400]
    assert s["no_draft_matches"][0]["clean_none"] is True
    assert s["no_draft_matches"][0]["draft_source"] == "none"
    assert _grade(path)["no_draft_matches"] == []  # no window, no claim


@pytest.mark.parametrize("delta,path", [(-30, "FINALIZATION"), (-3, "FALLBACK"),
                                        (4, "FALLBACK"), (40, "LATE")])
def test_classify_path(delta, path):
    t0 = 1000.0
    tape = [(t0 - 120, None), (t0 - 90, "ChampSelect"), (t0, "GameStart"), (t0 + 60, "InProgress")]
    assert g.classify_path(t0 + delta, tape)["path"] == path


def test_classify_path_uses_the_last_champ_select():
    tape = [(100.0, "ChampSelect"), (150.0, "GameStart"), (900.0, "ChampSelect"),
            (960.0, "GameStart")]
    r = g.classify_path(930.0, tape)
    assert r["path"] == "FINALIZATION" and r["captured_minus_first_game_phase_s"] == -30.0


def test_classify_path_unknown():
    assert g.classify_path(5.0, [(1.0, "ChampSelect")])["path"] == "UNKNOWN"
    assert g.classify_path(None, [(1.0, "GameStart")])["path"] == "UNKNOWN"


def test_load_tape_prefers_lcu_ts_and_skips_torn(tmp_path):
    p = tmp_path / "t.jsonl"
    p.write_text('{"t": 0.5, "baseline": {"table_present": false, "rows": 0}}\n'
                 '{"t": 5, "phase": "GameStart", "lcu_ts": 4.5}\n{"t": 1, "phase": "Lobby",'
                 ' "lcu_ts": null}\n{torn\n[1]\n{"t": NaN, "phase": "x"}\n'
                 '{"t": true, "phase": "y"}\n{"t": 3, "witness": {"picks": {"2": 104}}}\n'
                 '{"t": 3, "witness": "bad"}\n', encoding="utf-8")
    tape = g.load_tape(p)
    assert tape["phases"] == [(1.0, "Lobby"), (4.5, "GameStart")]
    assert tape["start"] == 0.5 and tape["baseline"] == {"table_present": False, "rows": 0}
    assert tape["witness"] == [(3.0, {"2": 104})]


def _cs(final=None):
    final = final or {}
    mine = [{"cellId": i, "champion_locked": final.get(i, ALLY_FINAL[i]), "puuid": "p",
             "summonerName": "n"} for i in range(5)]
    theirs = [{"cellId": 5 + i, "champion_locked": final.get(5 + i, ENEMY_FINAL[i])}
              for i in range(5)]
    return {"phase": "FINALIZATION", "queue_id": 420, "my_team": mine, "their_team": theirs}


def test_record_tape_writes_baseline_changes_and_stops(tmp_path, db):
    path, conn = db
    seq = iter([None, {"lcu": {"phase": "Lobby", "ts": 1.0}}, {"lcu": {"phase": "Lobby", "ts": 2.0}},
                {"lcu": {"phase": "ChampSelect", "ts": 3.0}},
                {"lcu": {"phase": "ChampSelect", "ts": 3.5, "champ_select": _cs({2: 0})}},
                {"lcu": {"phase": "ChampSelect", "ts": 3.7, "champ_select": _cs({2: 0})}},
                {"lcu": {"phase": "ChampSelect", "ts": 4.0, "champ_select": _cs()}}, {"lcu": "bad"},
                {"lcu": {"phase": "GameStart", "ts": True}}] + [{"lcu": {"phase": "GameStart"}}] * 50)
    now = [0.0]
    out = tmp_path / "sub" / "tape.jsonl"
    n = g.record_tape(out, fetch=lambda _u: next(seq), clock=lambda: now[0],
                      sleep=lambda s: now.__setitem__(0, now[0] + s), db=path)
    text = out.read_text(encoding="utf-8")
    rows = [json.loads(x) for x in text.splitlines()]
    assert rows[0]["baseline"] == {"table_present": True, "rows": 20}
    assert n == 5
    assert [r.get("phase") for r in rows[1:] if "phase" in r] == ["Lobby", "ChampSelect", "GameStart"]
    wit = [r["witness"] for r in rows if "witness" in r]
    assert len(wit) == 2 and wit[1]["picks"]["2"] == 104 and wit[0]["picks"]["2"] == 0
    assert '"p"' not in text and "summonerName" not in text and "puuid" not in text
    assert rows[-1]["lcu_ts"] is None
    assert now[0] < 20
    with pytest.raises(FileExistsError):
        g.record_tape(out, fetch=lambda _u: None, max_s=0, db=None)


def test_record_tape_honours_max_s(tmp_path):
    now = [0.0]
    out = tmp_path / "t.jsonl"
    n = g.record_tape(out, max_s=10, fetch=lambda _u: {"lcu": {"phase": "Lobby"}},
                      clock=lambda: now[0], sleep=lambda s: now.__setitem__(0, now[0] + s),
                      db=tmp_path / "missing.db")
    assert n == 1 and 10 <= now[0] <= 11
    assert json.loads(out.read_text(encoding="utf-8").splitlines()[0])["baseline"] == {
        "error": "FileNotFoundError"}


def test_witness_check():
    rows = [(GID, i, 0, c, "ally" if c < 5 else "enemy", "", "pick", 0, 1, f, 0, 420, "lcu", CAPTURED)
            for i, (c, f) in enumerate(zip(range(10), ALLY_FINAL + ENEMY_FINAL))]
    good = {str(c): f for c, f in zip(range(10), ALLY_FINAL + ENEMY_FINAL)}
    bad = dict(good, **{"7": 999})
    assert g.check_witness(rows, 100.0, [(50.0, bad), (90.0, good)])["witness"] == "MATCH"
    r = g.check_witness(rows, 100.0, [(90.0, good), (95.0, bad)])
    assert r["witness"] == "MISMATCH" and r["cells_differing"] == 1
    assert g.check_witness(rows, 100.0, [(500.0, good)]) == {"witness": "NONE"}
    # A witness stamped within WITNESS_LAG_S after the write counts; a later one does not.
    assert g.check_witness(rows, 100.0, [(90.0, bad), (101.5, good)])["witness"] == "MATCH"
    assert g.check_witness(rows, 100.0, [(90.0, bad), (105.0, good)])["witness"] == "MISMATCH"
    assert g.check_witness([], 100.0, [(90.0, good)])["witness"] == "MISMATCH"


def test_scan_logs_both_shapes(tmp_path):
    agent = tmp_path / "lcu_agent.log"
    agent.write_text("2026-01-02 10:00:00,001 WARNING draft_log sink failed for game 1: x\n"
                     "2026-01-02 12:00:00,001 WARNING draft_log sink failed for game 1: y\n"
                     "no stamp database is locked\n", encoding="utf-8")
    day = tmp_path / "2026-01-02.log"
    day.write_text("10:00:05.123 ERROR    rc.x  [a.py:1] database is locked\n"
                   "10:00:06.123 INFO     rc.x  [a.py:1] fine\n", encoding="utf-8")
    since = g.parse_when("2026-01-02T09:59:00")
    until = g.parse_when("2026-01-02T10:01:00")
    r = g.scan_logs([agent, day], since, until)
    assert r["lines_in_window"] == 3
    assert r["counts"]["sink_failed"] == 1 and r["counts"]["database_locked"] == 1
    assert [(f["name"], f["lines_in_window"]) for f in r["files"]] == [
        ("lcu_agent.log", 1), ("2026-01-02.log", 2)]
    assert r["files"][1]["counts"]["database_locked"] == 1
    assert g.scan_logs([day], None, None)["lines_in_window"] == 2
    # A wrong-day log reads ZERO lines on its own, not hidden in the total.
    wrong = tmp_path / "2026-01-03.log"
    wrong.write_text("10:00:05.123 ERROR    rc.x  [a.py:1] database is locked\n", encoding="utf-8")
    r2 = g.scan_logs([agent, wrong], since, until)
    assert r2["files"][1] == {"name": "2026-01-03.log", "lines_in_window": 0,
                              "counts": {k: 0 for k in g.LOG_PATTERNS}}
    r3 = g.scan_logs([agent, tmp_path / "lcu_agent.log.1"], since, until)
    assert r3["files"][1]["missing"] is True and r3["lines_in_window"] == 1
    # A rotated day log (<day>.log.1) is reached through a glob and keeps its day.
    rotated = tmp_path / "2026-01-02.log.1"
    rotated.write_text("10:00:01.000 WARNING  rc.x  [a.py:1] database is locked\n", encoding="utf-8")
    specs = g.expand_logs([str(tmp_path / "2026-01-02.log*"), str(tmp_path / "nope*.log")])
    assert [p.rsplit("\\", 1)[-1].rsplit("/", 1)[-1] for p in specs] == [
        "2026-01-02.log", "2026-01-02.log.1", "nope*.log"]
    r4 = g.scan_logs(specs, since, until)
    assert r4["counts"]["database_locked"] == 2
    assert r4["files"][2]["missing"] is True


def test_parse_when():
    assert g.parse_when("2026-01-02T03:04:30Z") == CAP_T
    assert g.parse_when("2026-01-02T03:04:30+00:00") == CAP_T
    assert g.parse_when("nope") is None and g.parse_when(None) is None
    assert g.parse_when(str(int(CAP_T))) == CAP_T
    assert g.parse_when("1" * 40) is None


def test_grade_is_read_only(db):
    path, conn = db
    _add_match(conn)
    conn.close()
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    _grade(path, since=0.0, tape={"start": None, "baseline": None, "witness": [],
                                  "phases": [(CAP_T + 3, "GameStart")]})
    assert g.db_baseline(path) == {"table_present": True, "rows": 20}
    ro = g._ro(path)
    with pytest.raises(sqlite3.OperationalError):
        ro.execute("DELETE FROM draft_log")
    ro.close()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_main_redacts_ids_by_default(db, capsys):
    path, conn = db
    _add_match(conn)
    _add_match(conn, mid="XX1_9000000002", queue=2400)
    tape = path.parent / "tape.jsonl"
    tape_rows = [{"t": CAP_T - 60, "baseline": {"table_present": False, "rows": 0}},
                 {"t": CAP_T - 1, "witness": g._witness(_cs())},
                 {"t": CAP_T + 2, "phase": "GameStart"}]
    tape.write_text("".join(json.dumps(r) + "\n" for r in tape_rows), encoding="utf-8")
    args = ["grade", "--db", str(path), "--since", "2026-01-02T03:00:00Z", "--phase-tape", str(tape)]
    assert g.main(args + ["--json"]) == 0
    out = capsys.readouterr().out
    assert str(GID) not in out and "9000000002" not in out
    s = json.loads(out)
    assert s["games"][0]["game_id"] == "g1" and s["no_draft_matches"][0]["match_id"] == "m1"
    assert s["games"][0]["path"]["path"] == "FALLBACK"
    assert s["games"][0]["witness"]["witness"] == "MATCH"
    assert s["games"][0]["captured_after_tape_start"] is True
    assert s["tape_baseline"] == {"table_present": False, "rows": 0}
    assert g.main(args + ["--show-id"]) == 0
    text = capsys.readouterr().out
    assert str(GID) in text and "join: JOIN_OK" in text


def test_main_errors(tmp_path, capsys):
    assert g.main(["grade", "--db", str(tmp_path / "missing.db")]) == 2
    assert g.main(["grade", "--db", str(tmp_path / "x.db"), "--since", "garbage"]) == 2
    p = tmp_path / "exists.jsonl"
    p.write_text("", encoding="utf-8")
    assert g.main(["tape", "--out", str(p), "--max-s", "0"]) == 2
    err = capsys.readouterr().err
    assert str(tmp_path) not in err
