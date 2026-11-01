"""tests/test_replay_history_audit_s144.py - true-audit of core/replay_history.py.

The module backs /api/replay/matches and /api/replay/match/<id> (the replay
scrubber in web/js/panels/dev.js). Measured against the live rewind DB with a
read-only connection before anything was changed, on a seeded sample of 400
matches (4090 player rows), comparing the end of the inventory fold with
Riot's own end-game item slots and leaving out eight granted and trinket-slot
items, most of which often have no event (2052, 2010, 2422, 3330, 3340, 3348,
3363, 3364):

- 2530 of 4090 rows matched before these fixes. Riot logs an elixir's
  ITEM_DESTROYED BEFORE its ITEM_PURCHASED in the same millisecond (2954 of 2975
  such pairs), so the fold missed the removal and then kept the item for the
  rest of the game.
- Seraph's Embrace, Muramana, Fimbulwinter and the support quest upgrades have
  NO ITEM_PURCHASED at all. The source item's ITEM_DESTROYED is the only event.
- 74 of 2966 list rows had no win verdict, most of them Arena team 200, which
  has no `teams` row (0 of 2966 after). `participants.win` agreed with
  `teams.win` on every one of 29203 rows that have both, and it is never NULL.
- 11 matches have the tracked champion on both teams. The list took their
  verdict from whichever team came first, and it disagreed with the stored flag
  on 6 of them.

Fixtures use a real sqlite database in the production column names, not stub
rows, and hand-written synthetic ids.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from core import replay_history as X  # noqa: E402

_SCHEMA = """
CREATE TABLE matches (
    match_id TEXT PRIMARY KEY, queue_id INTEGER, game_mode TEXT,
    game_duration_s INTEGER, game_creation_ts INTEGER, patch TEXT,
    tracked_champion_id INTEGER, tracked_champion_name TEXT,
    tracked_team_id INTEGER, tracked_win INTEGER);
CREATE TABLE participants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id TEXT, participant_id INTEGER, team_id INTEGER,
    champion_id INTEGER, champion_name TEXT, riot_id_game_name TEXT,
    summoner_name TEXT, summoner_level INTEGER, win INTEGER);
CREATE TABLE teams (match_id TEXT, team_id INTEGER, win INTEGER);
CREATE TABLE timeline_frames (
    match_id TEXT, timestamp_ms INTEGER, participant_id INTEGER,
    level INTEGER, total_gold INTEGER, minions_killed INTEGER,
    jungle_minions INTEGER, pos_x INTEGER, pos_y INTEGER,
    total_dmg_done INTEGER, total_dmg_taken INTEGER);
CREATE TABLE timeline_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, match_id TEXT,
    timestamp_ms INTEGER, event_type TEXT, participant_id INTEGER,
    item_id INTEGER, killer_id INTEGER, victim_id INTEGER,
    assisting_ids_json TEXT, kill_pos_x INTEGER, kill_pos_y INTEGER,
    raw_json TEXT);
"""

ELIXIR = 2140
TEAR_STAFF = 3003
SERAPH = 3040
LATE = 10 ** 9


@pytest.fixture
def db(tmp_path, monkeypatch):
    """A fresh rewind DB holding the schema, with the module pointed at it."""
    path = tmp_path / "rewind_history.db"
    con = sqlite3.connect(str(path))
    con.executescript(_SCHEMA)
    con.commit()
    monkeypatch.setattr(X, "_REWIND_DB", path)
    champs = tmp_path / "ddragon_champions.json"
    champs.write_text(json.dumps({"data": {
        "Ahri": {"key": "103", "name": "Ahri"},
        "Annie": {"key": "1", "name": "Annie"},
    }}), encoding="utf-8")
    monkeypatch.setattr(X, "_DDR_CHAMPS", champs)
    X._MATCH_DETAIL_CACHE.clear()
    X._id_to_champ.clear()
    yield con
    con.close()
    X._MATCH_DETAIL_CACHE.clear()
    X._id_to_champ.clear()


def _match(con, mid="M1", *, cid=103, name="Ahri", team=100, win=1, queue=420):
    con.execute(
        "INSERT INTO matches (match_id, queue_id, game_mode, game_duration_s,"
        " game_creation_ts, patch, tracked_champion_id, tracked_champion_name,"
        " tracked_team_id, tracked_win) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (mid, queue, "CLASSIC", 1200, 5, "16.15", cid, name, team, win))


def _part(con, pid, team, cid, *, win=None, mid="M1", name="Ahri"):
    con.execute(
        "INSERT INTO participants (match_id, participant_id, team_id,"
        " champion_id, champion_name, riot_id_game_name, summoner_name,"
        " summoner_level, win) VALUES (?,?,?,?,?,?,?,?,?)",
        (mid, pid, team, cid, name, "gn", "sn", 30, win))


def _team(con, team, win, mid="M1"):
    con.execute("INSERT INTO teams VALUES (?,?,?)", (mid, team, win))


def _frame(con, ts, pid=1, *, minions=10, jungle=2, x=100, y=200, mid="M1"):
    con.execute(
        "INSERT INTO timeline_frames VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (mid, ts, pid, 3, 500, minions, jungle, x, y, 7, 8))


def _event(con, ts, etype, pid=1, item=None, raw=None, mid="M1"):
    con.execute(
        "INSERT INTO timeline_events (match_id, timestamp_ms, event_type,"
        " participant_id, item_id, raw_json) VALUES (?,?,?,?,?,?)",
        (mid, ts, etype, pid, item, raw))


def _kill(con, ts, assists="[]", x=100, y=200, mid="M1"):
    con.execute(
        "INSERT INTO timeline_events (match_id, timestamp_ms, event_type,"
        " killer_id, victim_id, assisting_ids_json, kill_pos_x, kill_pos_y)"
        " VALUES (?,?,'CHAMPION_KILL',?,?,?,?,?)",
        (mid, ts, 1, 2, assists, x, y))


def _items_at_end(con, *events):
    """The tracked seat's items in the last snapshot of a match holding only
    `events` (ts, type, item), folded through match_detail's real SQL."""
    _match(con)
    _part(con, 1, 100, 103, win=1)
    _team(con, 100, 1)
    for ts, etype, item in events:
        _event(con, ts, etype, item=item)
    _frame(con, LATE)
    con.commit()
    return X.match_detail("M1")["snapshots"][-1]["entries"][0]["items"]


def _list_row(con):
    con.commit()
    return X.list_matches()[0]


# -- F1: a same-millisecond destroy logged before its purchase ----------------

def test_destroy_logged_before_its_purchase_in_one_ms_nets_out(db):
    """The measured elixir shape: without purchase-first ordering the removal
    misses, the purchase lands, and the elixir stays for the whole game."""
    got = _items_at_end(db, (1000, "ITEM_DESTROYED", ELIXIR),
                        (1000, "ITEM_PURCHASED", ELIXIR))
    assert got == []


def test_purchases_in_one_ms_keep_their_logged_order(db):
    got = _items_at_end(db, (1000, "ITEM_PURCHASED", 1055),
                        (1000, "ITEM_PURCHASED", 1001),
                        (1000, "ITEM_PURCHASED", 2003))
    assert got == [1055, 1001, 2003]


def test_an_earlier_destroy_stays_a_miss_for_a_later_purchase(db):
    """Only a tie reorders: a real rebuy a second later stays in inventory."""
    got = _items_at_end(db, (1000, "ITEM_DESTROYED", 2003),
                        (2000, "ITEM_PURCHASED", 2003))
    assert got == [2003]


# -- F2: items that transform with no purchase event --------------------------

@pytest.mark.parametrize("source, target", [
    (2526, 2530), (TEAR_STAFF, SERAPH), (3004, 3042), (3119, 3121),
    (3850, 3851), (3851, 3853), (3854, 3855), (3855, 3857), (3858, 3859),
    (3859, 3860), (3862, 3863), (3863, 3864), (3865, 3866), (3866, 3867),
    (222526, 222530), (223003, 223040), (223004, 223042), (223119, 223121),
])
def test_destroying_a_transform_source_yields_its_target(db, source, target):
    got = _items_at_end(db, (1000, "ITEM_PURCHASED", source),
                        (2000, "ITEM_DESTROYED", source))
    assert got == [target]


def test_destroying_a_source_the_seat_does_not_hold_yields_nothing(db):
    """The live shape: repeated destroys of one source, no purchase. Appending
    the target anyway ended a real seat with four copies Riot never showed."""
    got = _items_at_end(db, (1000, "ITEM_DESTROYED", 3866),
                        (2000, "ITEM_DESTROYED", 3866))
    assert got == []


def test_the_support_quest_chain_follows_each_step(db):
    got = _items_at_end(db, (1000, "ITEM_PURCHASED", 3865),
                        (2000, "ITEM_DESTROYED", 3865),
                        (3000, "ITEM_DESTROYED", 3866))
    assert got == [3867]


def test_selling_a_transform_source_does_not_transform_it(db):
    got = _items_at_end(db, (1000, "ITEM_PURCHASED", TEAR_STAFF),
                        (2000, "ITEM_SOLD", TEAR_STAFF))
    assert got == []


def test_destroying_an_ordinary_item_adds_nothing(db):
    got = _items_at_end(db, (1000, "ITEM_PURCHASED", 1036),
                        (2000, "ITEM_DESTROYED", 1036))
    assert got == []


def test_a_transform_is_not_applied_before_it_happened(db):
    _match(db)
    _part(db, 1, 100, 103, win=1)
    _event(db, 1000, "ITEM_PURCHASED", item=TEAR_STAFF)
    _event(db, 5000, "ITEM_DESTROYED", item=TEAR_STAFF)
    _frame(db, 2000)
    _frame(db, 6000)
    db.commit()
    snaps = X.match_detail("M1")["snapshots"]
    assert [s["entries"][0]["items"] for s in snaps] == [[TEAR_STAFF], [SERAPH]]


def test_every_transform_matches_the_ddragon_special_recipe():
    """The table is a constant, so pin it to the tracked DDragon file: a target
    whose `specialRecipe` stops naming its source is a stale row. A target Riot
    has since removed stays valid for the old matches that hold it, and this is
    deliberately not a completeness check, so a new patch cannot turn it red.
    DDragon names 3119 as the source of the Arena copy 223121, while the seats
    that end holding it destroyed 223119, so that one row is checked as written
    in DDragon."""
    doc = json.loads((_REPO / "data" / "meta" / "ddragon_items.json")
                     .read_text(encoding="utf-8"))["data"]
    present = {s: t for s, t in X._ITEM_TRANSFORMS.items() if str(t) in doc}
    assert present
    named_by_ddragon = {223119: 3119}
    for source, target in present.items():
        want = named_by_ddragon.get(source, source)
        assert doc[str(target)].get("specialRecipe") == want, (source, target)


# -- F3: the win verdict and the tracked seat ---------------------------------

def test_list_verdict_covers_a_team_with_no_teams_row(db):
    """Arena team 200 has no `teams` row; the list used to answer None. The
    stored flag disagrees on purpose, so only the player's own flag can pass."""
    _match(db, team=200, win=0, queue=1700)
    _part(db, 1, 200, 103, win=1)
    assert _list_row(db)["tracked"]["win"] is True


def test_list_verdict_uses_the_tracked_team_when_the_champion_is_on_both(db):
    _match(db, team=200, win=0, queue=1700)
    _part(db, 1, 100, 103, win=0)
    _part(db, 2, 200, 103, win=1)
    assert _list_row(db)["tracked"]["win"] is True


def test_list_verdict_is_the_stored_flag_when_the_seat_has_no_result(db):
    _match(db, win=1)
    _part(db, 1, 100, 103, win=None)
    assert _list_row(db)["tracked"]["win"] is True


@pytest.mark.parametrize("stored, want", [(0, False), (1, True)])
def test_list_verdict_is_the_stored_flag_when_one_team_disagrees(db, stored, want):
    """The champion twice on one team with different results names no seat."""
    _match(db, team=100, win=stored, queue=1700)
    _part(db, 1, 100, 103, win=0)
    _part(db, 2, 100, 103, win=1)
    assert _list_row(db)["tracked"]["win"] is want


def test_the_player_flag_outranks_the_teams_row(db):
    """Never measured apart live; pinned so the source cannot drift silently."""
    _match(db, win=0)
    _part(db, 1, 100, 103, win=1)
    _team(db, 100, 0)
    db.commit()
    assert X.list_matches()[0]["tracked"]["win"] is True
    d = X.match_detail("M1")
    assert d["tracked"]["win"] is True
    assert d["participants"][0]["team_won"] is True


def test_detail_team_won_falls_back_to_the_teams_row(db):
    _match(db)
    _part(db, 1, 100, 103, win=None)
    _team(db, 100, 1)
    db.commit()
    assert X.match_detail("M1")["participants"][0]["team_won"] is True


def test_list_verdict_is_the_stored_flag_when_the_seat_is_ambiguous(db):
    """No tracked team and the champion on both teams: no seat can be picked."""
    _match(db, team=0, win=1, queue=1700)
    _part(db, 1, 100, 103, win=0)
    _part(db, 2, 200, 103, win=1)
    assert _list_row(db)["tracked"]["win"] is True


def test_list_verdict_falls_back_to_the_teams_row_for_a_null_player_flag(db):
    _match(db, win=None)
    _part(db, 1, 100, 103, win=None)
    _team(db, 100, 1)
    assert _list_row(db)["tracked"]["win"] is True


def test_list_verdict_with_no_participants_is_the_stored_flag(db):
    _match(db, win=0)
    assert _list_row(db)["tracked"]["win"] is False


def test_an_unknown_result_is_none_never_a_loss(db):
    """bool(NULL) reported a NULL team result as a loss."""
    _match(db, win=None)
    _part(db, 1, 100, 103, win=None)
    _team(db, 100, None)
    assert _list_row(db)["tracked"]["win"] is None


def test_the_tracked_row_always_carries_win(db):
    _match(db, cid=None, name=None, team=None, win=None)
    assert _list_row(db)["tracked"] == {
        "champion_id": None, "champion_name": None, "win": None}


def test_detail_team_won_covers_a_team_with_no_teams_row(db):
    _match(db, team=200, queue=1700)
    _part(db, 1, 100, 103, win=0)
    _part(db, 2, 200, 1, win=1, name="Annie")
    _team(db, 100, 0)
    db.commit()
    got = {p["participant_id"]: p["team_won"]
           for p in X.match_detail("M1")["participants"]}
    assert got == {1: False, 2: True}


def test_detail_tracked_names_the_seat_and_the_verdict(db):
    _match(db, team=200, win=1, queue=1700)
    _part(db, 1, 100, 103, win=0)
    _part(db, 2, 200, 103, win=1)
    db.commit()
    tracked = X.match_detail("M1")["tracked"]
    assert tracked["team_id"] == 200
    assert tracked["win"] is True


def test_detail_tracked_seat_comes_from_the_row_when_no_team_was_stored(db):
    _match(db, team=0, win=None)
    _part(db, 1, 200, 103, win=1)
    db.commit()
    tracked = X.match_detail("M1")["tracked"]
    assert tracked["team_id"] == 200
    assert tracked["win"] is True


def test_detail_tracked_seat_is_unknown_when_ambiguous(db):
    _match(db, team=0, win=None, queue=1700)
    _part(db, 1, 100, 103, win=0)
    _part(db, 2, 200, 103, win=1)
    db.commit()
    tracked = X.match_detail("M1")["tracked"]
    assert tracked["team_id"] is None
    assert tracked["win"] is None


# -- F4: a malformed ITEM_UNDO row ---------------------------------------------

@pytest.mark.parametrize("raw", [
    pytest.param('{"beforeId": 1e999, "afterId": 0}', id="infinity"),
    pytest.param('{"beforeId": true, "afterId": true}', id="bool"),
    pytest.param('{"beforeId": 3.5, "afterId": 3.5}', id="float"),
    pytest.param('{"beforeId": -1, "afterId": -1}', id="negative"),
    pytest.param('{"beforeId": "1055", "afterId": "1055"}', id="string"),
    pytest.param('{"beforeId": [1], "afterId": {"a": 1}}', id="container"),
    pytest.param("[" * 200000, id="deep-nesting"),
])
def test_a_bad_undo_slot_changes_nothing(db, raw):
    _match(db)
    _part(db, 1, 100, 103, win=1)
    _event(db, 1000, "ITEM_PURCHASED", item=1)
    _event(db, 1001, "ITEM_PURCHASED", item=2)
    _event(db, 2000, "ITEM_UNDO", raw=raw)
    _frame(db, LATE)
    db.commit()
    assert X.match_detail("M1")["snapshots"][-1]["entries"][0]["items"] == [1, 2]


def test_a_valid_undo_still_applies(db):
    assert X._undo_pair({"raw_json": '{"beforeId": 5, "afterId": 6}'}) == (5, 6)


# -- F5: assists shape ---------------------------------------------------------

@pytest.mark.parametrize("raw, want", [
    pytest.param("[2, 3]", [2, 3], id="good"),
    pytest.param(None, [], id="null"),
    pytest.param("not json", [], id="garbage"),
    pytest.param('{"a": 1}', [], id="object"),
    pytest.param("7", [], id="scalar"),
    pytest.param('[2, "x", null, true, -1, 3.5, 3]', [2, 3], id="mixed-list"),
    pytest.param("[" * 200000, [], id="deep-nesting"),
])
def test_assists_is_always_a_list_of_seats(db, raw, want):
    _match(db)
    _kill(db, 1000, assists=raw)
    db.commit()
    assert X.match_detail("M1")["kills"][0]["assists"] == want


# -- F6: half a position -------------------------------------------------------

def test_frame_with_half_a_position_has_no_position(db):
    _match(db)
    _part(db, 1, 100, 103, win=1)
    _frame(db, 1000, y=None)
    db.commit()
    assert X.match_detail("M1")["snapshots"][0]["entries"][0]["pos"] is None


def test_kill_with_half_a_position_has_no_position(db):
    _match(db)
    _kill(db, 1000, y=None)
    db.commit()
    assert X.match_detail("M1")["kills"][0]["pos"] is None


def test_position_at_the_origin_is_a_position(db):
    _match(db)
    _part(db, 1, 100, 103, win=1)
    _frame(db, 1000, x=0, y=0)
    _kill(db, 1000, x=0, y=0)
    db.commit()
    d = X.match_detail("M1")
    assert d["snapshots"][0]["entries"][0]["pos"] == [0, 0]
    assert d["kills"][0]["pos"] == [0, 0]


# -- F7: CS is not zero when it was never recorded -----------------------------

def test_cs_is_none_for_a_seat_with_no_frame(db):
    _match(db)
    _part(db, 1, 100, 103, win=1)
    _part(db, 2, 200, 1, win=0, name="Annie")
    _frame(db, 1000, pid=1)
    db.commit()
    entries = X.match_detail("M1")["snapshots"][0]["entries"]
    assert [(e["participant_id"], e["cs"]) for e in entries] == [(1, 12), (2, None)]


def test_cs_is_none_when_both_counters_are_null(db):
    _match(db)
    _part(db, 1, 100, 103, win=1)
    _frame(db, 1000, minions=None, jungle=None)
    db.commit()
    assert X.match_detail("M1")["snapshots"][0]["entries"][0]["cs"] is None


def test_cs_counts_the_one_counter_that_exists(db):
    _match(db)
    _part(db, 1, 100, 103, win=1)
    _frame(db, 1000, minions=None, jungle=4)
    db.commit()
    assert X.match_detail("M1")["snapshots"][0]["entries"][0]["cs"] == 4


# -- F8: list_matches argument bounds ------------------------------------------

def test_a_huge_limit_is_capped_not_an_overflow(db):
    for i in range(X._LIST_LIMIT_MAX + 3):
        _match(db, f"M{i}", cid=None, name=None, team=None, win=None)
    db.commit()
    assert len(X.list_matches(limit=10 ** 30)) == X._LIST_LIMIT_MAX


def test_the_limit_cap_matches_the_route_cap():
    """dashboard/routes_coach.py _limit_param defaults hi to 200."""
    import inspect

    from dashboard import routes_coach
    assert (inspect.signature(routes_coach._limit_param).parameters["hi"].default
            == X._LIST_LIMIT_MAX)


@pytest.mark.parametrize("limit", ["5", 2.5, True, None])
def test_a_non_integer_limit_is_refused(db, limit):
    with pytest.raises(TypeError):
        X.list_matches(limit=limit)


@pytest.mark.parametrize("queue", ["420", 4.5, True])
def test_a_non_integer_queue_is_refused(db, queue):
    with pytest.raises(TypeError):
        X.list_matches(queue_filter=queue)


@pytest.mark.parametrize("queue", [2 ** 63, -(2 ** 63) - 1, 10 ** 30])
def test_a_queue_outside_64_bits_matches_nothing_not_an_overflow(db, queue):
    _match(db)
    db.commit()
    assert X.list_matches(queue_filter=queue) == []


@pytest.mark.parametrize("queue", [2 ** 63 - 1, -(2 ** 63)])
def test_a_queue_at_the_64_bit_edge_is_still_a_query(db, queue):
    _match(db, queue=queue)
    db.commit()
    assert [m["match_id"] for m in X.list_matches(queue_filter=queue)] == ["M1"]


# -- F9: one bad row must not take the whole match down ------------------------

@pytest.mark.parametrize("bad", [None, "not a time", 1.5, 9e999])
def test_a_frame_with_a_bad_timestamp_is_skipped(db, bad):
    _match(db)
    _part(db, 1, 100, 103, win=1)
    _frame(db, bad)
    _frame(db, 1000)
    db.commit()
    assert [s["timestamp_ms"] for s in X.match_detail("M1")["snapshots"]] == [1000]


@pytest.mark.parametrize("bad", [None, "not a time", 1.5, 9e999])
def test_an_item_event_with_a_bad_timestamp_is_skipped(db, bad):
    _match(db)
    _part(db, 1, 100, 103, win=1)
    _event(db, bad, "ITEM_PURCHASED", item=1055)
    _event(db, 500, "ITEM_PURCHASED", item=1001)
    _frame(db, 1000)
    db.commit()
    assert X.match_detail("M1")["snapshots"][0]["entries"][0]["items"] == [1001]


@pytest.mark.parametrize("bad", [None, "not a time", 1.5, 9e999])
def test_a_kill_with_a_bad_timestamp_is_skipped(db, bad):
    _match(db)
    _kill(db, bad)
    _kill(db, 1000)
    db.commit()
    assert [k["timestamp_ms"] for k in X.match_detail("M1")["kills"]] == [1000]


# -- F10: the connection really is read-only and creates nothing ---------------

def test_the_connection_refuses_writes(db):
    _match(db)
    db.commit()
    c = X._open()
    try:
        with pytest.raises(sqlite3.OperationalError):
            c.execute("DELETE FROM matches")
    finally:
        c.close()
    assert db.execute("SELECT COUNT(*) FROM matches").fetchone()[0] == 1


def test_a_database_removed_after_the_check_is_not_created(tmp_path, monkeypatch):
    """exists() then connect() is a race; a plain connect() creates a new empty
    file, which then answers every later read with `no such table`."""
    gone = tmp_path / "gone.db"
    monkeypatch.setattr(X, "_REWIND_DB", gone)
    with mock.patch.object(type(gone), "exists", return_value=True):
        assert X._open() is None
    assert not gone.exists()


def test_a_path_with_uri_metacharacters_opens_the_right_file(tmp_path, monkeypatch):
    folder = tmp_path / "a b#c%d"
    folder.mkdir()
    path = folder / "rewind_history.db"
    con = sqlite3.connect(str(path))
    con.executescript("CREATE TABLE marker (x INTEGER); INSERT INTO marker VALUES (7);")
    con.commit()
    con.close()
    monkeypatch.setattr(X, "_REWIND_DB", path)
    c = X._open()
    try:
        assert c.execute("SELECT x FROM marker").fetchone()[0] == 7
    finally:
        c.close()
    assert sorted(p.name for p in folder.iterdir()) == ["rewind_history.db"]


_CRASHING_WRITER = """
import os, sqlite3, sys
c = sqlite3.connect(sys.argv[1])
c.execute("PRAGMA cache_size = 1")
c.execute("BEGIN IMMEDIATE")
c.execute("UPDATE marker SET x = 8")
c.executemany("INSERT INTO marker VALUES (?)", [(i,) for i in range(50000)])
os._exit(0)
"""


def test_a_wal_database_reads_the_committed_state_after_a_crashed_writer(
    tmp_path, monkeypatch,
):
    """The live shape: scripts/rewind_scraper.py sets journal_mode=WAL."""
    path = tmp_path / "rewind_history.db"
    con = sqlite3.connect(str(path))
    assert con.execute("PRAGMA journal_mode = WAL").fetchone()[0] == "wal"
    con.executescript("CREATE TABLE marker (x INTEGER); INSERT INTO marker VALUES (7);")
    con.commit()
    con.close()
    subprocess.run(
        [sys.executable, "-c", _CRASHING_WRITER, str(path)], check=True, timeout=60,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    monkeypatch.setattr(X, "_REWIND_DB", path)
    c = X._open()
    try:
        assert [r[0] for r in c.execute("SELECT x FROM marker")] == [7]
        with pytest.raises(sqlite3.OperationalError):
            c.execute("DELETE FROM marker")
    finally:
        c.close()


def test_a_hot_journal_left_by_a_crashed_writer_is_recovered(tmp_path, monkeypatch):
    """Why _open is mode=rw plus query_only and not mode=ro. In rollback-journal
    mode a writer that dies mid-transaction leaves a hot journal; the next read
    must roll it back and answer with the last committed state, not fail."""
    path = tmp_path / "rewind_history.db"
    con = sqlite3.connect(str(path))
    con.executescript("CREATE TABLE marker (x INTEGER); INSERT INTO marker VALUES (7);")
    con.commit()
    con.close()
    subprocess.run(
        [sys.executable, "-c", _CRASHING_WRITER, str(path)], check=True, timeout=60,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    journal = path.with_name(path.name + "-journal")
    assert journal.exists() and journal.stat().st_size > 0, "no hot journal to test"
    monkeypatch.setattr(X, "_REWIND_DB", path)
    c = X._open()
    try:
        assert [r[0] for r in c.execute("SELECT x FROM marker")] == [7]
    finally:
        c.close()


def test_open_closes_the_connection_when_setup_fails(db, caplog):
    closed = []

    class _Bad:
        row_factory = None

        def execute(self, *_a):
            raise sqlite3.OperationalError("injected")

        def close(self):
            closed.append(True)

    with mock.patch.object(X.sqlite3, "connect", return_value=_Bad()):
        with caplog.at_level(logging.WARNING, logger=X._log.name):
            assert X._open() is None
    assert closed == [True]
    assert "injected" in caplog.text


# -- F11: champion index shape ---------------------------------------------------

def _champ_doc(tmp_path, monkeypatch, rows):
    path = tmp_path / "champs.json"
    path.write_text(json.dumps({"data": rows}), encoding="utf-8")
    monkeypatch.setattr(X, "_DDR_CHAMPS", path)
    X._id_to_champ.clear()


@pytest.mark.parametrize("key", [float("inf"), True, 555.7, None, "abc", [1]])
def test_a_bad_champion_key_is_skipped_not_fatal(tmp_path, monkeypatch, key):
    _champ_doc(tmp_path, monkeypatch, {
        "Bad": {"key": key, "name": "Bad"},
        "Ahri": {"key": "103", "name": "Ahri"}})
    try:
        assert X._load_champ_index() is True
        assert X._id_to_champ == {103: "Ahri"}
    finally:
        X._id_to_champ.clear()


@pytest.mark.parametrize("name", [5, ["x"], {"a": 1}, "", None])
def test_a_bad_champion_name_falls_back_to_the_slug(tmp_path, monkeypatch, name):
    _champ_doc(tmp_path, monkeypatch, {"Ahri": {"key": "103", "name": name}})
    try:
        assert X._load_champ_index() is True
        assert X._id_to_champ == {103: "Ahri"}
    finally:
        X._id_to_champ.clear()


def test_an_integer_champion_key_still_loads(tmp_path, monkeypatch):
    _champ_doc(tmp_path, monkeypatch, {"Ahri": {"key": 103, "name": "Ahri"}})
    try:
        assert X._load_champ_index() is True
        assert X._id_to_champ == {103: "Ahri"}
    finally:
        X._id_to_champ.clear()


# -- F12: the stored name is used when the index has no answer -------------------

def test_list_name_falls_back_to_the_stored_name(db):
    _match(db, cid=999, name="Newchamp")
    assert _list_row(db)["tracked"]["champion_name"] == "Newchamp"


def test_detail_name_falls_back_to_the_stored_name(db):
    _match(db, cid=999, name="Newchamp")
    db.commit()
    assert X.match_detail("M1")["tracked"]["champion_name"] == "Newchamp"


def test_an_empty_stored_name_is_no_name(db):
    _match(db, cid=999, name="")
    assert _list_row(db)["tracked"]["champion_name"] is None


def test_the_index_name_wins_over_the_stored_name(db):
    _match(db, cid=103, name="Stale")
    assert _list_row(db)["tracked"]["champion_name"] == "Ahri"


# -- F13: match_detail argument --------------------------------------------------

@pytest.mark.parametrize("mid", [None, "", 5, b"M1", ["M1"]])
def test_a_non_string_match_id_is_not_found(db, mid):
    _match(db)
    db.commit()
    assert X.match_detail(mid) is None


# -- Characterization: the payload shape the dashboard reads ---------------------

def test_list_row_shape(db):
    _match(db)
    _part(db, 1, 100, 103, win=1)
    assert _list_row(db) == {
        "match_id": "M1", "queue_id": 420, "game_mode": "CLASSIC",
        "duration_s": 1200, "game_creation_ts": 5, "patch": "16.15",
        "tracked": {"champion_id": 103, "champion_name": "Ahri", "win": True},
    }


def test_detail_shape_is_strict_json(db):
    _match(db)
    _part(db, 1, 100, 103, win=1)
    _team(db, 100, 1)
    _frame(db, 60000)
    _kill(db, 30000, assists="[2]")
    _event(db, 1000, "ITEM_PURCHASED", item=1055)
    db.commit()
    d = X.match_detail("M1")
    json.dumps(d, allow_nan=False)
    assert d["snapshots"] == [{
        "timestamp_ms": 60000, "minute": 1.0,
        "entries": [{
            "participant_id": 1, "level": 3, "total_gold": 500, "cs": 12,
            "pos": [100, 200], "dmg_done": 7, "dmg_taken": 8, "items": [1055],
        }],
    }]
    assert d["kills"] == [{
        "timestamp_ms": 30000, "minute": 0.5, "killer_id": 1, "victim_id": 2,
        "assists": [2], "pos": [100, 200],
    }]
    assert d["participants"][0]["team_won"] is True
