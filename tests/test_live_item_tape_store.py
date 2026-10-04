"""Tests for ``core/live_item_tape_store.py`` - RM-607 game-end persistence.

Every test builds a TEMP database from the real shared schema
(``scripts.rewind_scraper.SCHEMA``) so the additive ``source`` migration is
proven against the exact table the rewind writers create. No test touches
``data/rewind_history.db``. Players are synthetic (``TapeP<n>#TST``).
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from core import live_item_tape as lit
from core import live_item_tape_store as store
from scripts.rewind_scraper import SCHEMA

MID = "NA1_9000000001"


@pytest.fixture()
def conn(tmp_path):
    c = sqlite3.connect(str(tmp_path / "rewind.db"))
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    yield c
    c.close()


def _ev(kind, iid, *, t=60.0, who="TapeP1#TST", team="ORDER", count=1, comps=()):
    return lit.TapeEvent(t, who, team, kind, iid, count, tuple(comps))


def _v5_row(c, kind="ITEM_PURCHASED", iid=3031, pid=1, t=1000):
    c.execute("INSERT INTO timeline_events (match_id, timestamp_ms, event_type, "
              "participant_id, item_id) VALUES (?,?,?,?,?)", (MID, t, kind, pid, iid))


def _cols(c) -> list[str]:
    return [r[1] for r in c.execute("PRAGMA table_info(timeline_events)")]


def test_source_column_is_appended_at_the_end_with_null_default(conn):
    _v5_row(conn)
    before = _cols(conn)
    assert "source" not in before
    assert store.ensure_source_column(conn) is True
    after = _cols(conn)
    assert after == before + ["source"]
    info = {r[1]: r for r in conn.execute("PRAGMA table_info(timeline_events)")}
    # dflt_value is the SQL text of the default: NULL, never a source label
    assert info["source"][4] in (None, "NULL")
    # the pre-existing Match-V5 row still reads as Match-V5
    (src,) = conn.execute("SELECT source FROM timeline_events").fetchone()
    assert store.source_label(src) == "match_v5"


def test_ensure_source_column_is_idempotent(conn):
    assert store.ensure_source_column(conn) is True
    assert store.ensure_source_column(conn) is False
    assert _cols(conn).count("source") == 1


def test_v5_writer_rows_after_migration_still_read_as_v5(conn):
    store.ensure_source_column(conn)
    _v5_row(conn)                 # a writer that never names the column
    (src,) = conn.execute("SELECT source FROM timeline_events").fetchone()
    assert store.source_label(src) == "match_v5"


def test_persist_writes_only_the_three_types_tagged_live_tape(conn):
    events = [
        _ev(lit.EV_BASELINE, 1055),
        _ev(lit.EV_PURCHASED, 2003, count=2),
        _ev(lit.EV_CONSUMABLE_USED, 2003),
        _ev(lit.EV_TRINKET_SWAP, 3364, comps=(3340,)),
        _ev(lit.EV_COMBINED, 3031, comps=(1037, 1038), t=61.5),
        _ev(lit.EV_SOLD, 1055, who="TapeP6#TST", team="CHAOS"),
        _ev(lit.EV_GRANTED, 228002),
    ]
    res = store.persist_tape(conn, MID, events)
    assert res["status"] == "written" and res["rows"] == 4
    rows = conn.execute("SELECT event_type, item_id, timestamp_ms, team_id, source, "
                        "raw_json FROM timeline_events ORDER BY id").fetchall()
    assert [(r[0], r[1]) for r in rows] == [
        ("ITEM_PURCHASED", 2003), ("ITEM_PURCHASED", 2003),
        ("ITEM_COMBINED", 3031), ("ITEM_SOLD", 1055)]
    assert {r[4] for r in rows} == {"live_tape"}
    assert rows[2][2] == 61500 and rows[3][3] == 200 and rows[0][3] == 100
    assert json.loads(rows[2][5])["components"] == [1037, 1038]


def test_participant_id_is_resolved_by_riot_id_and_team_never_by_order(conn):
    conn.execute("INSERT INTO participants (match_id, participant_id, team_id, "
                 "riot_id_game_name, riot_id_tagline) VALUES (?,?,?,?,?)",
                 (MID, 7, 200, "TapeP1", "TST"))
    conn.execute("INSERT INTO participants (match_id, participant_id, team_id, "
                 "riot_id_game_name, riot_id_tagline) VALUES (?,?,?,?,?)",
                 (MID, 2, 100, "TapeP1", "TST"))
    store.persist_tape(conn, MID, [_ev(lit.EV_PURCHASED, 1036, team="CHAOS"),
                                   _ev(lit.EV_PURCHASED, 1037, who="TapeP9#TST")])
    rows = conn.execute("SELECT item_id, participant_id FROM timeline_events "
                        "ORDER BY id").fetchall()
    assert [tuple(r) for r in rows] == [(1036, 7), (1037, None)]


def test_persist_drops_events_from_an_earlier_game_segment(conn):
    """Verifier probe: game A (segment 0) bought 1036, game B (segment 1)
    bought 1055; persisting under B's match_id writes ONLY B's purchase."""
    a = lit.TapeEvent(600.0, "TapeP1#TST", "ORDER", lit.EV_PURCHASED, 1036, 1, (), 0)
    b = lit.TapeEvent(20.0, "TapeP1#TST", "ORDER", lit.EV_PURCHASED, 1055, 1, (), 1)
    assert [r["item_id"] for r in store.build_rows("NA1_2", [a, b])] == [1055]
    res = store.persist_tape(conn, "NA1_2", [a, b])
    assert res["rows"] == 1
    items = [r[0] for r in conn.execute("SELECT item_id FROM timeline_events")]
    assert items == [1055]


def test_match_v5_present_means_no_tape_write(conn):
    _v5_row(conn)
    res = store.persist_tape(conn, MID, [_ev(lit.EV_PURCHASED, 1036)])
    assert res["status"] == "v5_present"
    n = conn.execute("SELECT COUNT(*) FROM timeline_events").fetchone()[0]
    assert n == 1


def test_repersist_replaces_instead_of_duplicating(conn):
    evs = [_ev(lit.EV_PURCHASED, 1036)]
    store.persist_tape(conn, MID, evs)
    store.persist_tape(conn, MID, evs)
    n = conn.execute("SELECT COUNT(*) FROM timeline_events").fetchone()[0]
    assert n == 1


def test_read_rule_match_v5_wins_when_both_exist(conn):
    store.persist_tape(conn, MID, [_ev(lit.EV_PURCHASED, 1036)])
    assert [r["item_id"] for r in store.item_events(conn, MID)] == [1036]
    _v5_row(conn, iid=3031)   # V5 lands later (a writer that predates source)
    rows = store.item_events(conn, MID)
    assert [r["item_id"] for r in rows] == [3031]
    assert {store.source_label(r["source"]) for r in rows} == {"match_v5"}


def test_read_rule_without_the_column_returns_v5_rows(conn):
    _v5_row(conn, iid=3031)
    assert "source" not in _cols(conn)
    assert [r["item_id"] for r in store.item_events(conn, MID)] == [3031]


def test_purge_drops_only_superseded_tape_rows(conn):
    other = "NA1_9000000002"
    store.persist_tape(conn, MID, [_ev(lit.EV_PURCHASED, 1036)])
    store.persist_tape(conn, other, [_ev(lit.EV_PURCHASED, 1037)])
    _v5_row(conn, iid=3031)
    assert store.purge_superseded_tape_rows(conn) == 1
    left = conn.execute("SELECT match_id, item_id FROM timeline_events "
                        "ORDER BY id").fetchall()
    assert sorted(tuple(r) for r in left) == [(MID, 3031), (other, 1037)]


def test_purge_without_column_is_a_noop(conn):
    _v5_row(conn)
    assert store.purge_superseded_tape_rows(conn) == 0
    assert "source" not in _cols(conn)


def test_match_id_for():
    assert store.match_id_for("NA1", 9000000001) == MID
    assert store.match_id_for("", 1) is None
    assert store.match_id_for("NA1", None) is None


def test_on_game_end_without_match_id_writes_nothing(tmp_path):
    db = tmp_path / "rewind.db"
    res = store.on_game_end(None, db_path=db, delay_s=0,
                            events=[_ev(lit.EV_PURCHASED, 1036)])
    assert res["status"] == "no_match_id" and res["events"] == 1
    assert not db.exists()


def test_on_game_end_inline_persists(tmp_path):
    db = tmp_path / "rewind.db"
    c = sqlite3.connect(str(db))
    c.executescript(SCHEMA)
    c.close()
    res = store.on_game_end(MID, db_path=db, delay_s=0,
                            events=[_ev(lit.EV_PURCHASED, 1036)])
    assert res["status"] == "written" and res["rows"] == 1


def test_on_game_end_missing_db_is_silent(tmp_path):
    res = store.on_game_end(MID, db_path=tmp_path / "absent.db", delay_s=0,
                            events=[_ev(lit.EV_PURCHASED, 1036)])
    assert res["status"] == "no_db"
    assert not (tmp_path / "absent.db").exists()
