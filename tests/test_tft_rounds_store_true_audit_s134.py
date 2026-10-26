"""s134 true-audit (lane 8, cycle 12): tft/rounds/store.py validator cluster.

Contract under test (store.py module docstring): every public write validates
its input in the caller's thread, and invalid input "is dropped and counted as
`invalid`"; `begin_match` / `put_frame` return the id only when the row was
accepted. Three validator holes let a value through that the writer thread then
could not bind, or that the exports could not serialise:

  V1  `_v_int` had no 64-bit bound: 2**63 passed, then sqlite3 raised
      OverflowError at bind time inside the writer. The row was lost as a
      `write_errors` "database write failed" (a misdiagnosis), and begin_match
      had already returned a match_id for a match row that never existed.
  V2  `_v_num` took NaN and +/-inf. SQLite stores NaN as NULL (a timestamp
      silently lost) and keeps inf, which export_fixture / export_jsonl then
      wrote as the non-JSON token `Infinity`.
  V3  `_v_text` took a lone surrogate (json.loads of an external file yields
      one from a bare \\ud800 escape); sqlite3 cannot encode it, so the same
      writer-side loss as V1 followed.

Measured at main 4486a09bb: begin_match returned "m1" for game_id 2**63 and
"m2" for set_core_name "\\ud800", stats showed invalid 0 / write_errors 2, and
a fixture exported after put_event(ts=inf) contained "Infinity".
"""
from __future__ import annotations

import json
import logging
import sqlite3

import pytest

from tft.rounds import store as st
from tft.rounds.store import Env, RoundStore

T0 = 1_761_000_000.0
I64_MAX = 2 ** 63 - 1
I64_MIN = -(2 ** 63)
SURROGATE = chr(0xD800)  # built with chr(): source stays 7-bit ASCII


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "tft" / "tft_rounds.db"


@pytest.fixture
def store(db_path):
    s = RoundStore.open(db_path)
    try:
        yield s
    finally:
        s.close()


def _matches(path):
    conn = sqlite3.connect(str(path))
    try:
        return [r[0] for r in conn.execute("SELECT match_id FROM match ORDER BY match_id")]
    finally:
        conn.close()


def _open_match(store, mid="m-ok"):
    assert store.begin_match({"match_id": mid, "game_id": 1, "queue_id": 1090,
                              "started_at": T0}) == mid
    return mid


def _key():
    return st.player_key("SyntheticPlayer1#SYN1", b"s134-true-audit-salt")


# ---------------------------------------------------------------- V1 int64


def test_v1_begin_match_refuses_a_game_id_past_int64(store, db_path):
    got = store.begin_match({"match_id": "m-big", "game_id": I64_MAX + 1, "queue_id": 1090,
                             "started_at": T0})
    assert store.flush()
    assert got is None  # no id handed back for a row that is never written
    stats = store.stats()
    assert stats["invalid"] == 1 and stats["write_errors"] == 0
    assert _matches(db_path) == []


def test_v1_the_int64_edges_themselves_are_accepted(store, db_path):
    assert store.begin_match({"match_id": "m-max", "game_id": I64_MAX, "queue_id": 1090,
                              "started_at": T0}) == "m-max"
    mid = _open_match(store)
    assert store.upsert_round(mid, 1, streak=Env(I64_MIN, 1.0, "derived"))
    assert store.flush()
    assert store.stats()["write_errors"] == 0
    assert store.get_match("m-max", rounds=False)["match"]["game_id"] == I64_MAX
    assert next(store.iter_rounds(mid))["streak"] == I64_MIN


@pytest.mark.parametrize("call", [
    pytest.param(lambda s, m: s.upsert_round(m, I64_MAX + 1), id="round_seq"),
    pytest.param(lambda s, m: s.upsert_round(m, 1, streak=Env(I64_MIN - 1, 1.0, "derived")),
                 id="envelope-below"),
    pytest.param(lambda s, m: s.upsert_round(m, 1, damage_dealt=Env(2 ** 70, 1.0, "lcu")),
                 id="envelope-above"),
    pytest.param(lambda s, m: s.put_shop_refresh(m, 1, 0, gold_before=2 ** 64, conf=1.0,
                                                 src="ocr"), id="gold_before"),
    pytest.param(lambda s, m: s.put_player_round(m, 1, _key(), hp=-(2 ** 64), conf=1.0,
                                                 src="lcu"), id="hp"),
    pytest.param(lambda s, m: s.put_accuracy(m, [{"field": "hp", "n": 2 ** 63}]), id="n"),
])
def test_v1_every_int_column_refuses_past_int64_as_invalid(store, call):
    mid = _open_match(store)
    assert store.flush()
    before = store.stats()
    assert call(store, mid) is False
    assert store.flush()
    after = store.stats()
    assert after["invalid"] == before["invalid"] + 1
    assert after["write_errors"] == before["write_errors"] == 0


# ---------------------------------------------------------------- V2 finite


@pytest.mark.parametrize("bad", [float("inf"), float("-inf"), float("nan")],
                         ids=["inf", "-inf", "nan"])
def test_v2_a_non_finite_timestamp_is_invalid(store, bad):
    mid = _open_match(store)
    assert store.flush()
    calls = (
        lambda: store.put_event(mid, "phase", {}, ts=bad, src="tft_log"),
        lambda: store.upsert_round(mid, 1, planning_ts=bad),
        lambda: store.record_obs(mid, 1, "planning", "hp", 50, 1.0, "ocr", ts=bad),
        lambda: store.put_frame(mid, 1, "planning", "a/b.png", ts=bad),
        lambda: store.end_match(mid, ended_at=bad),
        lambda: store.attach_ground_truth(mid, "lcu_eog", [], [
            {"player_key": _key(), "placement": 1, "eliminated_at": bad}]),
        lambda: store.begin_match({"match_id": "m-nf", "game_id": 2, "queue_id": 1090,
                                   "started_at": bad}),
    )
    for call in calls:
        assert call() in (False, None)
    assert store.flush()
    assert store.stats()["invalid"] == len(calls)
    assert store.stats()["write_errors"] == 0


def test_v2_a_float_overflowing_int_is_invalid_and_named(store, caplog):
    mid = _open_match(store)
    with caplog.at_level(logging.WARNING, logger=st.__name__):
        assert store.put_event(mid, "phase", {}, ts=10 ** 400, src="tft_log") is False
    msgs = [r.getMessage() for r in caplog.records if r.name == st.__name__]
    # the drop names the field and the rule, not just an exception class
    assert len(msgs) == 1 and "ts" in msgs[0] and "finite" in msgs[0]


def test_v2_finite_extremes_still_pass(store):
    mid = _open_match(store)
    assert store.put_event(mid, "phase", {}, ts=-1.5, src="tft_log")
    assert store.upsert_round(mid, 1, planning_ts=1e300, combat_ts=10 ** 300)
    assert store.flush()
    assert store.stats()["invalid"] == 0 and store.stats()["write_errors"] == 0


def test_v2_exports_stay_strict_json(store, tmp_path):
    """Before the fix ts=inf reached the db and the fixture held `Infinity`."""
    mid = _open_match(store)
    store.put_event(mid, "phase", {}, ts=float("inf"), src="tft_log")
    assert store.put_event(mid, "phase", {"ok": 1}, ts=T0 + 5, src="tft_log")
    assert store.flush()
    fixture = store.export_fixture(mid, tmp_path, name="fx").read_text(encoding="ascii")
    jsonl = store.export_jsonl([mid], tmp_path / "a.jsonl").read_text(encoding="ascii")

    def strict(s):
        return json.loads(s, parse_constant=lambda c: pytest.fail(f"non-JSON constant {c}"))

    strict(fixture)
    for line in jsonl.splitlines():
        strict(line)


# ---------------------------------------------------------------- V3 surrogate


def test_v3_begin_match_refuses_a_lone_surrogate(store, db_path):
    got = store.begin_match({"match_id": "m-sur", "game_id": 1, "queue_id": 1090,
                             "started_at": T0, "set_core_name": "TFTSet18" + SURROGATE})
    assert store.flush()
    assert got is None
    assert store.stats()["invalid"] == 1 and store.stats()["write_errors"] == 0
    assert _matches(db_path) == []


@pytest.mark.parametrize("call", [
    pytest.param(lambda s, m: s.put_units(m, 1, "combat", _key(), [
        {"zone": "board", "champion_api": "DA_18_Leona" + SURROGATE, "star": 1,
         "conf": 1.0, "src": "lcu"}]), id="champion_api"),
    pytest.param(lambda s, m: s.put_units(m, 1, "combat", _key(), [
        {"zone": "board", "champion_api": "DA_18_Leona", "items": [SURROGATE],
         "star": 1, "conf": 1.0, "src": "lcu"}]), id="items"),
    pytest.param(lambda s, m: s.upsert_round(m, 1, label="2-1" + SURROGATE), id="label"),
    pytest.param(lambda s, m: s.put_augment(m, 1, 0, ["DA_18_BranchingOut"], SURROGATE,
                                            conf=1.0, src="lcu"), id="chosen_api"),
])
def test_v3_every_text_column_refuses_a_lone_surrogate(store, call):
    mid = _open_match(store)
    assert store.flush()
    assert call(store, mid) is False
    assert store.flush()
    assert store.stats()["invalid"] == 1 and store.stats()["write_errors"] == 0


def test_v3_non_ascii_text_that_encodes_is_still_accepted(store):
    """The rule is 'encodable', not 'ASCII': OCR name_text may hold real
    non-ASCII letters (Kai'Sa style names in other locales)."""
    mid = _open_match(store)
    assert store.put_units(mid, 1, "combat", _key(), [
        {"zone": "board", "champion_api": "DA_18_" + chr(0xE9), "star": 1, "conf": 1.0,
         "src": "lcu"}])
    assert store.flush()
    assert store.stats()["write_errors"] == 0 and store.stats()["invalid"] == 0


# ---------------------------------------------------------------- V4 log echo


def test_v4_a_non_sqlite_writer_error_never_echoes_its_message(store, caplog):
    """Section 1.2: a log line names a field and a rule, never a value. Before
    V3 a UnicodeEncodeError reached the writer and its message, which quotes
    the offending character, went into logs/. Any non-sqlite exception raised
    while a row is applied is logged by class only; a sqlite3.Error keeps its
    message (SQLite names tables and columns, not bound values)."""
    marker = "SyntheticPlayer9#SYN9"

    def bad_build():
        def fn(conn):
            raise ValueError(f"value {marker} could not be bound")
        return fn

    with caplog.at_level(logging.WARNING, logger=st.__name__):
        assert store._submit("probe", bad_build)
        assert store.flush()
    msgs = [r.getMessage() for r in caplog.records if r.name == st.__name__]
    assert len(msgs) == 1 and "ValueError" in msgs[0] and "probe" in msgs[0]
    assert marker not in msgs[0] and "could not be bound" not in msgs[0]
    assert store.stats()["write_errors"] == 1


def test_v4_a_sqlite_error_keeps_its_message(store, db_path, caplog):
    mid = _open_match(store)
    assert store.flush()
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("DROP TABLE event")
        conn.commit()
    finally:
        conn.close()
    with caplog.at_level(logging.WARNING, logger=st.__name__):
        assert store.put_event(mid, "phase", {}, src="tft_log")
        assert store.flush()
    msgs = [r.getMessage() for r in caplog.records if r.name == st.__name__]
    assert len(msgs) == 1 and "OperationalError" in msgs[0] and "no such table" in msgs[0]
