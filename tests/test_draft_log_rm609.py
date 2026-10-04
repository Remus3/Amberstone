"""RM-609 (directive X-09, external reference A): per-game champ-select draft log.

Everything here is driven from a SYNTHETIC, name-scrubbed champ-select session
(no real Riot ids, no summoner names). It pins:

  * a finalized session parses to ordered rows keyed by the GLOBAL action
    index (not by cell), including a pick-order swap (cell 1 picks before
    cell 0) and a champion trade (action-time championId != final post-swap
    championId);
  * the sibling ``draft_log`` table round-trips through rewind_history.db's
    real schema, and the game_id join attaches the log to a Match-V5 match
    row and resolves the enemy lane opponent from participants.team_position;
  * a game with no capture reads draft_source='none' and nothing is
    fabricated;
  * the live recorder only snapshots at finalize, waits for a game id, and
    drops a pending draft that never reached a game (dodge).
"""
from __future__ import annotations

import sqlite3

import pytest

from lcu import draft_log as dl


GAME_ID = 4100000001
MATCH_ID = f"NA1_{GAME_ID}"


def _team(cells, positions, champs):
    return [
        {"cellId": c, "assignedPosition": p, "championId": ch,
         "championPickIntent": 0, "summonerId": 0, "puuid": ""}
        for c, p, ch in zip(cells, positions, champs)
    ]


def _act(aid, cell, typ, champ, completed=True):
    return {"id": aid, "actorCellId": cell, "type": typ, "championId": champ,
            "completed": completed, "isInProgress": False, "isAllyAction": cell < 5}


def _session(phase="FINALIZATION", game_id=GAME_ID):
    """Synthetic SR draft. Local cell 2. Ally 0-4, enemy 5-9.

    Pick-order swap: cell 1 holds the FIRST ally pick (action 10) and cell 0
    the second (action 13). Trade: cell 2 locked 103 and cell 3 locked 22;
    they traded, so the final roster has cell 2 = 22, cell 3 = 103.
    """
    bans = [_act(i, cell, "ban", 200 + i) for i, cell in enumerate(range(10))]
    picks = [
        [_act(10, 1, "pick", 11)],
        [_act(11, 5, "pick", 51), _act(12, 6, "pick", 52)],
        [_act(13, 0, "pick", 10), _act(14, 2, "pick", 103)],
        [_act(15, 7, "pick", 53), _act(16, 8, "pick", 54)],
        [_act(17, 3, "pick", 22), _act(18, 4, "pick", 14)],
        [_act(19, 9, "pick", 55)],
    ]
    return {
        "gameId": game_id,
        "localPlayerCellId": 2,
        "timer": {"phase": phase},
        "actions": [bans] + picks,
        "myTeam": _team(range(5),
                        ["top", "jungle", "middle", "bottom", "utility"],
                        [10, 11, 22, 103, 14]),
        "theirTeam": _team(range(5, 10), [""] * 5, [51, 52, 53, 54, 55]),
        "gameData": {"queue": {"id": 420}},
    }


# -- pure parsing -------------------------------------------------------------

def test_parse_rows_are_ordered_by_global_action_index():
    rows = dl.parse_draft(_session())
    assert [r["action_index"] for r in rows] == list(range(20))
    picks = [r for r in rows if r["action_type"] == "pick"]
    # Pick ORDER is the action order, not the cell order: cell 1 first.
    assert [r["actor_cell_id"] for r in picks] == [1, 5, 6, 0, 2, 7, 8, 3, 4, 9]
    assert [r["turn"] for r in picks] == [1, 2, 2, 3, 3, 4, 4, 5, 5, 6]


def test_parse_pick_order_swap_and_trade_keep_both_champion_ids():
    rows = {r["action_index"]: r for r in dl.parse_draft(_session())}
    first = rows[10]
    assert (first["actor_cell_id"], first["assigned_position"]) == (1, "jungle")
    mine = rows[14]
    assert mine["actor_cell_id"] == 2 and mine["is_local"] == 1
    assert mine["champion_id"] == 103          # action-time lock
    assert mine["final_champion_id"] == 22     # post-trade roster
    mate = rows[17]
    assert (mate["champion_id"], mate["final_champion_id"]) == (22, 103)
    untouched = rows[10]
    assert untouched["champion_id"] == untouched["final_champion_id"] == 11


def test_parse_side_and_position_mapping():
    rows = dl.parse_draft(_session())
    for r in rows:
        assert r["side"] == ("ally" if r["actor_cell_id"] < 5 else "enemy")
        if r["side"] == "enemy":
            assert r["assigned_position"] == ""   # hidden in solo queue
    ban0 = rows[0]
    assert ban0["action_type"] == "ban" and ban0["completed"] == 1
    assert ban0["champion_id"] == 200


def test_parse_tolerates_string_cells_and_null_groups():
    sess = _session()
    sess["localPlayerCellId"] = "2"
    sess["actions"] = [None, "x"] + sess["actions"]
    for a in sess["actions"][2]:
        a["actorCellId"] = str(a["actorCellId"])
    rows = dl.parse_draft(sess)
    assert len(rows) == 20 and rows[0]["actor_cell_id"] == 0
    assert dl.parse_draft({}) == [] and dl.parse_draft(None) == []


def test_is_finalized_gate():
    assert dl.is_finalized(_session("FINALIZATION"))
    assert not dl.is_finalized(_session("BAN_PICK"))
    assert not dl.is_finalized({"timer": None})


# -- storage + game_id join -----------------------------------------------------

def _rewind_db(tmp_path):
    from scripts.rewind_scraper import SCHEMA
    conn = sqlite3.connect(str(tmp_path / "rewind_history.db"))
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO matches (match_id, queue_id, tracked_team_id) "
                 "VALUES (?, 420, 100)", (MATCH_ID,))
    roster = [  # (participant_id, team_id, champion_id, team_position)
        (1, 100, 10, "TOP"), (2, 100, 11, "JUNGLE"), (3, 100, 22, "MIDDLE"),
        (4, 100, 103, "BOTTOM"), (5, 100, 14, "UTILITY"),
        (6, 200, 53, "TOP"), (7, 200, 51, "JUNGLE"), (8, 200, 55, "MIDDLE"),
        (9, 200, 52, "BOTTOM"), (10, 200, 54, "UTILITY"),
    ]
    conn.executemany(
        "INSERT INTO participants (match_id, participant_id, team_id, "
        "champion_id, team_position) VALUES (?, ?, ?, ?, ?)",
        [(MATCH_ID,) + r for r in roster])
    conn.commit()
    return conn


def test_store_and_join_attaches_log_and_resolves_lane_opponent(tmp_path):
    conn = _rewind_db(tmp_path)
    n = dl.store_draft(conn, GAME_ID, dl.parse_draft(_session()), queue_id=420)
    assert n == 20
    out = dl.attach_draft_log(conn, MATCH_ID)
    assert out["game_id"] == GAME_ID
    assert out["draft_source"] == dl.DRAFT_SOURCE_LCU
    assert [a["action_index"] for a in out["actions"]] == list(range(20))
    # Local final champ 22 plays MIDDLE (post-trade). Enemy MIDDLE is 55,
    # picked by cell 9 at action 19 - AFTER our action 14 (we were blind).
    opp = out["lane_opponent"]
    assert opp["champion_id"] == 55 and opp["team_position"] == "MIDDLE"
    assert opp["actor_cell_id"] == 9 and opp["action_index"] == 19
    assert out["local_picked_before_opponent"] is True
    # Every enemy pick row carries its Match-V5-resolved position.
    enemy = {a["final_champion_id"]: a["resolved_position"]
             for a in out["actions"]
             if a["side"] == "enemy" and a["action_type"] == "pick"}
    assert enemy == {51: "JUNGLE", 52: "BOTTOM", 53: "TOP",
                     54: "UTILITY", 55: "MIDDLE"}


def test_store_replaces_previous_snapshot_for_same_game(tmp_path):
    conn = _rewind_db(tmp_path)
    dl.store_draft(conn, GAME_ID, dl.parse_draft(_session()))
    dl.store_draft(conn, GAME_ID, dl.parse_draft(_session())[:3])
    (count,) = conn.execute("SELECT COUNT(*) FROM draft_log WHERE game_id=?",
                            (GAME_ID,)).fetchone()
    assert count == 3


def test_no_capture_is_draft_source_none_and_never_fabricated(tmp_path):
    conn = _rewind_db(tmp_path)
    out = dl.attach_draft_log(conn, MATCH_ID)
    assert out["draft_source"] == dl.DRAFT_SOURCE_NONE == "none"
    assert out["actions"] == [] and out["lane_opponent"] is None
    assert out["local_picked_before_opponent"] is None
    # The join is read-only: it must not even create the table.
    assert not dl._table_exists(conn, "draft_log")


def test_no_capture_on_db_without_table_and_bad_match_id(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "bare.db"))
    assert dl.attach_draft_log(conn, MATCH_ID)["draft_source"] == "none"
    assert dl.attach_draft_log(conn, "garbage")["draft_source"] == "none"
    assert dl.game_id_from_match_id("NA1_123") == 123
    assert dl.game_id_from_match_id("123") == 123
    assert dl.game_id_from_match_id("NA1_x") is None


def test_store_refuses_empty_or_bad_game_id(tmp_path):
    conn = _rewind_db(tmp_path)
    assert dl.store_draft(conn, 0, dl.parse_draft(_session())) == 0
    assert dl.store_draft(conn, GAME_ID, []) == 0
    assert dl.load_draft(conn, GAME_ID) == []
    assert dl.attach_draft_log(conn, MATCH_ID)["draft_source"] == "none"


# -- live recorder (no DB unless a sink is installed) ---------------------------

class _Sink:
    def __init__(self):
        self.calls = []

    def __call__(self, game_id, rows, queue_id):
        self.calls.append((game_id, len(rows), queue_id))


def test_recorder_snapshots_only_at_finalize():
    sink = _Sink()
    rec = dl.DraftRecorder(sink=sink)
    rec.observe_session(_session("BAN_PICK"))
    assert sink.calls == []
    rec.observe_session(_session("FINALIZATION"))
    assert sink.calls == [(GAME_ID, 20, 420)]
    rec.observe_session(_session("FINALIZATION"))   # unchanged -> no rewrite
    assert len(sink.calls) == 1


def test_recorder_waits_for_gameflow_game_id_when_session_has_none():
    sink = _Sink()
    rec = dl.DraftRecorder(sink=sink)
    rec.observe_session(_session("FINALIZATION", game_id=0))
    assert sink.calls == []
    rec.note_game_id(str(GAME_ID))
    assert sink.calls == [(GAME_ID, 20, 420)]


def test_recorder_drops_pending_draft_on_dodge():
    sink = _Sink()
    rec = dl.DraftRecorder(sink=sink)
    rec.observe_session(_session("FINALIZATION", game_id=0))
    rec.observe_phase("Lobby")          # dodged: back to lobby
    rec.note_game_id(str(GAME_ID))      # a later, unrelated game
    assert sink.calls == []


def test_recorder_without_sink_never_writes_and_never_raises():
    rec = dl.DraftRecorder()
    rec.observe_session(_session())
    rec.note_game_id("x")
    rec.observe_session("not a dict")


def test_sink_failure_is_swallowed():
    def boom(*_a):
        raise sqlite3.OperationalError("locked")
    rec = dl.DraftRecorder(sink=boom)
    rec.observe_session(_session())     # must not raise


def test_sqlite_sink_writes_to_given_path(tmp_path):
    db = tmp_path / "rewind_history.db"
    sink = dl.sqlite_sink(db)
    sink(GAME_ID, dl.parse_draft(_session()), 420)
    conn = sqlite3.connect(str(db))
    out = dl.attach_draft_log(conn, MATCH_ID)
    assert out["draft_source"] == "lcu" and len(out["actions"]) == 20
    assert out["lane_opponent"] is None     # no Match-V5 rows yet


def test_shape_champ_select_feeds_module_recorder(monkeypatch):
    from lcu.champ_select_shape import shape_champ_select
    sink = _Sink()
    monkeypatch.setattr(dl, "_RECORDER", dl.DraftRecorder(sink=sink))
    sess = _session()

    def req(method, path, body=None):
        return (sess, None) if path == "/lol-champ-select/v1/session" else (None, None)

    shape_champ_select(req, "ChampSelect")
    assert sink.calls == [(GAME_ID, 20, 420)]


def test_snapshot_shape_notes_gameflow_game_id(monkeypatch):
    from lcu import snapshot_shape
    sink = _Sink()
    monkeypatch.setattr(dl, "_RECORDER", dl.DraftRecorder(sink=sink))
    dl._RECORDER.observe_session(_session(game_id=0))
    gflow = {"gameData": {"gameId": GAME_ID, "queue": {"id": 420}}}

    def req(method, path, body=None):
        if path == "/lol-gameflow/v1/gameflow-phase":
            return "InProgress", None
        if path == "/lol-gameflow/v1/session":
            return gflow, None
        return None, None

    monkeypatch.setattr(snapshot_shape, "_maybe_refresh_mastery", lambda r: None)
    snapshot_shape.shape_snapshot(req, {})
    assert sink.calls == [(GAME_ID, 20, 420)]


def test_agent_installs_sink_into_rewind_history_db(monkeypatch):
    import sys
    from pathlib import Path
    tools = str(Path(__file__).resolve().parent.parent / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    import lcu_agent as agent
    seen = []
    monkeypatch.setattr(dl, "install_sink", seen.append)
    monkeypatch.setattr(dl, "sqlite_sink", lambda p: ("sink", Path(p)))
    agent._install_draft_log_sink()
    assert len(seen) == 1
    kind, path = seen[0]
    assert kind == "sink"
    assert path.parts[-2:] == ("data", "rewind_history.db")


def test_importing_agent_does_not_install_a_sink():
    import sys
    from pathlib import Path
    tools = str(Path(__file__).resolve().parent.parent / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    import lcu_agent  # noqa: F401
    assert dl._RECORDER._sink is None


@pytest.mark.parametrize("phase", ["Lobby", "None", None, "Matchmaking"])
def test_shape_champ_select_non_cs_phase_drops_pending(monkeypatch, phase):
    from lcu.champ_select_shape import shape_champ_select
    sink = _Sink()
    monkeypatch.setattr(dl, "_RECORDER", dl.DraftRecorder(sink=sink))
    dl._RECORDER.observe_session(_session(game_id=0))
    shape_champ_select(lambda *a, **k: (None, None), phase)
    dl._RECORDER.note_game_id(str(GAME_ID))
    assert sink.calls == []
