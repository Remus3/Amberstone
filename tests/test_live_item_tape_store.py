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


@pytest.fixture
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


# ---- s144 true-audit hardening (F1-F7) ------------------------------------

def _good():
    return _ev(lit.EV_PURCHASED, 1036)


def _junk_events():
    """One junk field per event; every one must be dropped, none may raise."""
    T = lit.TapeEvent
    P = lit.EV_PURCHASED
    return [
        T(float("nan"), "TapeP1#TST", "ORDER", P, 1001),
        T(float("inf"), "TapeP1#TST", "ORDER", P, 1001),
        T(-5.0, "TapeP1#TST", "ORDER", P, 1001),
        T(10.0 ** 7, "TapeP1#TST", "ORDER", P, 1001),
        T(True, "TapeP1#TST", "ORDER", P, 1001),
        T("60", "TapeP1#TST", "ORDER", P, 1001),
        T(60.0, "TapeP1#TST", "ORDER", P, 1001, "x"),
        T(60.0, "TapeP1#TST", "ORDER", P, 1001, 0),
        T(60.0, "TapeP1#TST", "ORDER", P, 1001, 10 ** 6),
        T(60.0, "TapeP1#TST", "ORDER", P, 1001, True),
        T(60.0, "TapeP1#TST", "ORDER", P, True),
        T(60.0, "TapeP1#TST", "ORDER", P, "abc"),
        T(60.0, "TapeP1#TST", "ORDER", P, 0),
        T(60.0, "TapeP1#TST", "ORDER", P, 2 ** 70),
        T(60.0, "TapeP1#TST", "ORDER", lit.EV_COMBINED, 3031, 1, (object(),)),
        T(60.0, "TapeP1#TST", "ORDER", lit.EV_COMBINED, 3031, 1, (True,)),
        T(60.0, "TapeP1#TST", "ORDER", lit.EV_COMBINED, 3031, 1, "1037"),
        T(60.0, "TapeP1#TST", "ORDER", P, 1001, 1, (), "a"),
        T(60.0, "TapeP1#TST", "ORDER", P, 1001, 1, (), True),
        T(60.0, "TapeP1#TST", "ORDER", ["ITEM_PURCHASED"], 1001),
        T(60.0, None, "ORDER", P, 1001),
        T(60.0, "  ", "ORDER", P, 1001),
        T(60.0, "x" * 500, "ORDER", P, 1001),
        T(60.0, "TapeP1#TST", 100, P, 1001),
        None,
        {"event_type": P, "item_id": 1001},
    ]


def test_build_rows_drops_junk_events_and_never_raises():
    rows = store.build_rows(MID, [*_junk_events(), _good()])
    assert [(r["event_type"], r["item_id"]) for r in rows] == [
        ("ITEM_PURCHASED", 1036)]
    assert all(type(r["item_id"]) is int for r in rows)


def test_build_rows_junk_segment_never_hides_the_real_game():
    a = lit.TapeEvent(60.0, "TapeP1#TST", "ORDER", lit.EV_PURCHASED, 1036, 1, (), 0)
    j = lit.TapeEvent(60.0, "TapeP1#TST", "ORDER", lit.EV_PURCHASED, 1001, 1, (),
                      10 ** 30)
    assert [r["item_id"] for r in store.build_rows(MID, [a, j])] == [1036]
    # a bool segment is not segment 1 (True == 1 in Python)
    b = lit.TapeEvent(60.0, "TapeP1#TST", "ORDER", lit.EV_PURCHASED, 1055, 1, (), 1)
    t = lit.TapeEvent(60.0, "TapeP1#TST", "ORDER", lit.EV_PURCHASED, 1001, 1, (),
                      True)
    assert [r["item_id"] for r in store.build_rows(MID, [b, t])] == [1055]


def test_build_rows_a_baseline_only_new_segment_still_outranks_the_old_game():
    """b1a1d8837 contract: a new game whose tape so far holds only baselines
    (not a persisted type) must still hide the previous game's purchases."""
    a = lit.TapeEvent(600.0, "TapeP1#TST", "ORDER", lit.EV_PURCHASED, 1036, 1, (), 0)
    b = lit.TapeEvent(5.0, "TapeP1#TST", "ORDER", lit.EV_BASELINE, 1055, 1, (), 1)
    assert store.build_rows("NA1_2", [a, b]) == []


def test_build_rows_keeps_a_valid_count_and_integral_values():
    e = lit.TapeEvent(61, "TapeP1#TST", "ORDER", lit.EV_PURCHASED, 2003, 3)
    rows = store.build_rows(MID, [e])
    assert len(rows) == 3 and rows[0]["timestamp_ms"] == 61000


def test_on_game_end_inline_never_raises_on_a_junk_event(tmp_path):
    db = tmp_path / "rewind.db"
    c = sqlite3.connect(str(db))
    c.executescript(SCHEMA)
    c.close()
    res = store.on_game_end(MID, db_path=db, delay_s=0,
                            events=[*_junk_events(), _good()])
    assert res["status"] == "written" and res["rows"] == 1


def test_persist_rolls_back_on_a_non_sqlite_error(conn, monkeypatch):
    store.persist_tape(conn, MID, [_good()])
    bad = store.build_rows(MID, [_good()])
    bad[0]["item_id"] = 2 ** 70           # OverflowError at bind, not sqlite3.Error
    monkeypatch.setattr(store, "build_rows", lambda *a, **k: bad)
    with pytest.raises(OverflowError):
        store.persist_tape(conn, MID, [_good()])
    assert not conn.in_transaction
    n = conn.execute("SELECT COUNT(*) FROM timeline_events").fetchone()[0]
    assert n == 1                          # the earlier tape row survived


def _wal_db(tmp_path):
    db = tmp_path / "wal.db"
    c = sqlite3.connect(str(db))
    c.execute("PRAGMA journal_mode=WAL")
    c.executescript(SCHEMA)
    c.close()
    return db


def test_v5_check_and_tape_write_are_one_write_transaction(tmp_path, monkeypatch):
    """A Match-V5 writer in ANOTHER connection that lands between the
    "V5 present?" check and the tape insert must not leave both sets."""
    db = _wal_db(tmp_path)
    landed = []
    real = store._participant_ids

    def racing(conn, match_id):
        other = sqlite3.connect(str(db), timeout=0)
        try:
            _v5_row(other)
            other.commit()
            landed.append(True)
        except sqlite3.OperationalError:
            landed.append(False)
        finally:
            other.close()
        return real(conn, match_id)

    monkeypatch.setattr(store, "_participant_ids", racing)
    c = sqlite3.connect(str(db), timeout=0)
    try:
        store.persist_tape(c, MID, [_good()])
    finally:
        c.close()
    c = sqlite3.connect(str(db))
    rows = c.execute("SELECT source FROM timeline_events").fetchall()
    c.close()
    sources = {store.source_label(r[0]) for r in rows}
    assert landed == [False]
    assert sources == {"live_tape"}


def test_early_returns_release_the_write_lock(tmp_path):
    db = _wal_db(tmp_path)
    c = sqlite3.connect(str(db))
    _v5_row(c)
    c.commit()
    assert store.persist_tape(c, MID, [_good()])["status"] == "v5_present"
    assert not c.in_transaction
    assert store.persist_tape(c, "NA1_5", [])["status"] == "empty"
    assert not c.in_transaction
    other = sqlite3.connect(str(db), timeout=0)
    _v5_row(other, iid=3032)
    other.commit()
    other.close()
    c.close()


def test_persist_to_path_opens_a_db_under_a_path_with_spaces(tmp_path):
    """The live DB sits under a checkout path that may hold a real space
    (CLAUDE.md spelling trap); the mode=rw URI open must still find it."""
    d = tmp_path / "Some Dir #1"
    d.mkdir()
    db = d / "rewind history.db"
    c = sqlite3.connect(str(db))
    c.executescript(SCHEMA)
    c.close()
    res = store._persist_to_path(db, MID, [_good()])
    assert res["status"] == "written" and res["rows"] == 1


def test_persist_to_path_never_creates_the_db(tmp_path, monkeypatch):
    """The DB vanishing between the is_file check and the open must not
    leave a new empty rewind DB behind."""
    absent = tmp_path / "absent.db"
    monkeypatch.setattr(store.Path, "is_file", lambda self: True)
    res = store._persist_to_path(absent, MID, [_good()])
    assert res["status"] in ("no_db", "error")
    assert not absent.exists()


@pytest.mark.parametrize("platform, game_id, want", [
    ("NA1", 9000000001, MID),
    (" euw1 ", "42", "EUW1_42"),
    ("NA1", "007", "NA1_7"),
    ("NA1", 123.0, "NA1_123"),
    ("NA1", 2 ** 63 - 1, f"NA1_{2 ** 63 - 1}"),
    ("NA1", chr(0xB2), None),                 # superscript two
    ("NA1", chr(0x661) + chr(0x662), None),   # Arabic-Indic digits
    ("NA1", 0, None),
    ("NA1", "0", None),
    ("NA1", -5, None),
    ("NA1", "+5", None),
    ("NA1", 123.5, None),
    ("NA1", float("nan"), None),
    ("NA1", float("inf"), None),
    ("NA1", True, None),
    ("NA1", 2 ** 63, None),
    ("NA1", "9" * 5000, None),
    ("NA1", [1], None),
    ("na1; x", 1, None),
    ("N" + chr(0xC1) + "1", 1, None),         # non-ASCII alphanumeric
    ("A" * 17, 1, None),
    (5, 1, None),
], ids=lambda v: repr(v)[:24])
def test_match_id_for_accepts_only_real_ids(platform, game_id, want):
    assert store.match_id_for(platform, game_id) == want


@pytest.mark.parametrize("mid", [12345, "NA1_1; x", "", "  ", "NA1_" + chr(0xB2),
                                 "NA1_0", ["NA1_1"], "na1_1", "NA1_007",
                                 "NA1_" + "9" * 19, "NA1_1\n"])
def test_persist_and_on_game_end_refuse_a_junk_match_id(conn, tmp_path, mid):
    res = store.persist_tape(conn, mid, [_good()])
    assert res["status"] == "bad_match_id" and res["rows"] == 0
    assert "source" not in _cols(conn)
    res = store.on_game_end(mid, db_path=tmp_path / "x.db", delay_s=0,
                            events=[_good()])
    assert res["status"] == "no_match_id"
    assert not (tmp_path / "x.db").exists()


class _FakeTimer:
    made: list = []

    def __init__(self, interval, function, args=None, kwargs=None):
        self.interval = interval
        self.function = function
        self.args = args or ()
        self.daemon = False
        self.name = ""
        self.started = False
        _FakeTimer.made.append(self)

    def start(self):
        self.started = True


@pytest.mark.parametrize("delay, want", [
    (5.0, 5.0), (7, 7.0),
    (float("nan"), store.DEFAULT_DELAY_S), (float("inf"), store.DEFAULT_DELAY_S),
    ("5", store.DEFAULT_DELAY_S), (True, store.DEFAULT_DELAY_S),
    (None, store.DEFAULT_DELAY_S), (1e12, store.DEFAULT_DELAY_S),
])
def test_on_game_end_junk_delay_keeps_the_default(tmp_path, monkeypatch, delay, want):
    _FakeTimer.made = []
    monkeypatch.setattr(store.threading, "Timer", _FakeTimer)
    res = store.on_game_end(MID, db_path=tmp_path / "x.db", delay_s=delay,
                            events=[_good()])
    assert res["status"] == "scheduled"
    (t,) = _FakeTimer.made
    assert t.interval == want and t.daemon is True and t.started
    assert t.name == "rc-item-tape-persist"


def test_scheduled_persist_never_raises_out_of_the_timer_thread(tmp_path,
                                                                 monkeypatch):
    db = tmp_path / "rewind.db"
    c = sqlite3.connect(str(db))
    c.executescript(SCHEMA)
    c.close()
    _FakeTimer.made = []
    monkeypatch.setattr(store.threading, "Timer", _FakeTimer)
    store.on_game_end(MID, db_path=db, delay_s=5, events=[_good()])
    (t,) = _FakeTimer.made

    def boom(*a, **k):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(store, "persist_tape", boom)
    res = t.function(*t.args)
    assert res["status"] == "error"
