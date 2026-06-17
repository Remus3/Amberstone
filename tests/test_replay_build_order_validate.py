"""Characterization tests for tools/replay_build_order_validate.py - the Lane-B
BUILD-ORDER Haiku-flip gate.

All tests inject their own ``comp_lean_fn`` + ``table_lookup_fn`` and build an
in-memory sqlite fixture, so NOTHING here reads the real HZ-B2 table or
rewind_history.db. Pure scoring helpers are tested directly; the DB readers +
``run_validation`` use a hand-built temp schema mirroring the columns the gate
queries.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_TOOLS = _ROOT / "tools"
for _p in (str(_ROOT), str(_TOOLS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import replay_build_order_validate as gate  # noqa: E402


# --------------------------------------------------------------------- fixtures
def _make_db() -> sqlite3.Connection:
    """In-memory DB with the minimal matches / participants / timeline_events
    schema the gate reads."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE matches (
            match_id TEXT, game_mode TEXT, has_timeline INTEGER,
            game_creation_ts INTEGER
        );
        CREATE TABLE participants (
            match_id TEXT, participant_id INTEGER, team_id INTEGER,
            champion_name TEXT, win INTEGER,
            item0 INTEGER, item1 INTEGER, item2 INTEGER, item3 INTEGER,
            item4 INTEGER, item5 INTEGER, item6 INTEGER
        );
        CREATE TABLE timeline_events (
            match_id TEXT, timestamp_ms INTEGER, event_type TEXT,
            participant_id INTEGER, item_id INTEGER
        );
        """
    )
    return conn


def _add_match(conn, mid="M1", ts=1000):
    conn.execute(
        "INSERT INTO matches VALUES (?, 'CLASSIC', 1, ?)", (mid, ts))


def _add_participant(conn, mid, pid, team, champ, win, items):
    cols = list(items) + [0] * (7 - len(items))
    conn.execute(
        "INSERT INTO participants VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (mid, pid, team, champ, 1 if win else 0, *cols[:7]),
    )


# A trivial table-lookup over a dict-of-dicts {champ: {variant: {"order": [...]}}}.
def _lookup_from(table):
    def _lk(champ, variant):
        return (table.get(champ) or {}).get(variant) or {}
    return _lk


# --------------------------------------------------------------------- statistics
def test_two_prop_diff_ci_basic():
    diff, lo, hi = gate.two_prop_diff_ci(60, 100, 50, 100)
    assert diff == pytest.approx(0.10)
    assert lo < diff < hi


def test_two_prop_diff_ci_empty_sample():
    assert gate.two_prop_diff_ci(0, 0, 5, 10) == (None, None, None)
    assert gate.two_prop_diff_ci(5, 10, 0, 0) == (None, None, None)


# --------------------------------------------------------------- distinctive_sets
def test_distinctive_sets_splits_orders():
    table = {"Cho": {"anti_tank": {"order": ["1", "2", "3"]},
                     "anti_squishy": {"order": ["1", "4", "5"]}}}
    at_only, as_only = gate.distinctive_sets("Cho", _lookup_from(table))
    assert at_only == frozenset({"2", "3"})
    assert as_only == frozenset({"4", "5"})


def test_distinctive_sets_uncovered_champ_is_none():
    assert gate.distinctive_sets("Nobody", _lookup_from({})) is None


def test_distinctive_sets_identical_orders_is_none():
    table = {"X": {"anti_tank": {"order": ["1", "2"]},
                   "anti_squishy": {"order": ["1", "2"]}}}
    assert gate.distinctive_sets("X", _lookup_from(table)) is None


def test_distinctive_sets_missing_order_is_none():
    table = {"X": {"anti_tank": {"order": []},
                   "anti_squishy": {"order": ["1"]}}}
    assert gate.distinctive_sets("X", _lookup_from(table)) is None


# --------------------------------------------------------- classify_actual_lean
def test_classify_actual_lean_anti_tank():
    at, as_ = frozenset({"2", "3"}), frozenset({"4", "5"})
    assert gate.classify_actual_lean(["1", "2", "3"], at, as_) == "anti_tank"


def test_classify_actual_lean_anti_squishy():
    at, as_ = frozenset({"2", "3"}), frozenset({"4", "5"})
    assert gate.classify_actual_lean(["4", "5", "9"], at, as_) == "anti_squishy"


def test_classify_actual_lean_tie_is_none():
    at, as_ = frozenset({"2"}), frozenset({"4"})
    assert gate.classify_actual_lean(["2", "4"], at, as_) is None
    assert gate.classify_actual_lean(["9"], at, as_) is None


# ------------------------------------------------------------------- score_row
def _row(champ="Cho", enemy=("Malphite",), items=("2",), win=True):
    return gate.BuildRow(match_id="M1", champion=champ, enemy_comp=tuple(enemy),
                         items=tuple(items), win=win, participant_id=1)


def test_score_row_uncovered_comp():
    lean = lambda comp: None  # noqa: E731
    table = {"Cho": {"anti_tank": {"order": ["2"]}, "anti_squishy": {"order": ["4"]}}}
    status, rec, act, win = gate.score_row(_row(), lean, _lookup_from(table))
    assert status == "uncovered_comp" and rec is None and act is None


def test_score_row_uncovered_champ():
    lean = lambda comp: ("anti_tank", "high")  # noqa: E731
    status, rec, act, _ = gate.score_row(_row(champ="Ghost"), lean, _lookup_from({}))
    assert status == "uncovered_champ" and rec == "anti_tank" and act is None


def test_score_row_ambiguous():
    lean = lambda comp: ("anti_tank", "high")  # noqa: E731
    table = {"Cho": {"anti_tank": {"order": ["2"]}, "anti_squishy": {"order": ["4"]}}}
    status, rec, act, _ = gate.score_row(_row(items=("9",)), lean, _lookup_from(table))
    assert status == "ambiguous" and rec == "anti_tank" and act is None


def test_score_row_decisive_followed_and_not():
    table = {"Cho": {"anti_tank": {"order": ["2"]}, "anti_squishy": {"order": ["4"]}}}
    lk = _lookup_from(table)
    # build leans anti_tank, recommended anti_tank -> followed
    s, rec, act, _ = gate.score_row(_row(items=("2",)),
                                    lambda c: ("anti_tank", "high"), lk)
    assert (s, rec, act) == ("decisive", "anti_tank", "anti_tank")
    # build leans anti_squishy, recommended anti_tank -> not followed
    s, rec, act, _ = gate.score_row(_row(items=("4",)),
                                    lambda c: ("anti_tank", "high"), lk)
    assert (s, rec, act) == ("decisive", "anti_tank", "anti_squishy")


# ------------------------------------------------------------ extract_build_rows
def test_extract_build_rows_enemy_comp_and_items():
    conn = _make_db()
    _add_match(conn)
    _add_participant(conn, "M1", 1, 100, "Cho", True, [2, 3])
    _add_participant(conn, "M1", 6, 200, "Malphite", False, [4, 5])
    rows = gate.extract_build_rows(conn, "M1")
    assert len(rows) == 2
    cho = next(r for r in rows if r.champion == "Cho")
    assert cho.enemy_comp == ("Malphite",)
    assert set(cho.items) == {"2", "3"}
    assert cho.win is True


def test_extract_build_rows_requires_two_teams():
    conn = _make_db()
    _add_match(conn)
    _add_participant(conn, "M1", 1, 100, "Cho", True, [2])
    assert gate.extract_build_rows(conn, "M1") == []


def test_extract_build_rows_skips_zero_items():
    conn = _make_db()
    _add_match(conn)
    _add_participant(conn, "M1", 1, 100, "Cho", True, [2, 0, 0])
    _add_participant(conn, "M1", 6, 200, "Lux", False, [4])
    cho = next(r for r in gate.extract_build_rows(conn, "M1") if r.champion == "Cho")
    assert cho.items == ("2",)


# ------------------------------------------------ first_recommended_purchase_min
def test_first_purchase_min_earliest():
    conn = _make_db()
    for ts, iid in ((600000, 2), (300000, 2), (900000, 9)):
        conn.execute(
            "INSERT INTO timeline_events VALUES ('M1', ?, 'ITEM_PURCHASED', 1, ?)",
            (ts, iid))
    got = gate.first_recommended_purchase_min(conn, "M1", 1, frozenset({"2"}))
    assert got == pytest.approx(5.0)  # 300000ms / 60000


def test_first_purchase_min_never_bought_is_none():
    conn = _make_db()
    conn.execute(
        "INSERT INTO timeline_events VALUES ('M1', 600000, 'ITEM_PURCHASED', 1, 9)")
    assert gate.first_recommended_purchase_min(conn, "M1", 1, frozenset({"2"})) is None


def test_first_purchase_min_empty_distinctive_is_none():
    conn = _make_db()
    assert gate.first_recommended_purchase_min(conn, "M1", 1, frozenset()) is None


# ----------------------------------------------------------------- run_validation
def test_run_validation_followed_vs_not(tmp_path):
    db = tmp_path / "t.db"
    conn = sqlite3.connect(str(db))
    conn.executescript(_make_db_schema())
    # Two matches. Enemy comp is a tank wall -> recommended anti_tank.
    # M1: Cho builds anti_tank (item 2) and WINS -> followed+win.
    # M2: Cho builds anti_squishy (item 4) and LOSES -> not_followed+loss.
    conn.execute("INSERT INTO matches VALUES ('M1','CLASSIC',1,2)")
    conn.execute("INSERT INTO matches VALUES ('M2','CLASSIC',1,1)")
    _ins(conn, "M1", 1, 100, "Cho", True, [2])
    _ins(conn, "M1", 6, 200, "Malphite", False, [9])
    _ins(conn, "M2", 1, 100, "Cho", False, [4])
    _ins(conn, "M2", 6, 200, "Malphite", True, [9])
    conn.commit()
    conn.close()

    table = {"Cho": {"anti_tank": {"order": ["2"]}, "anti_squishy": {"order": ["4"]}}}
    lean = lambda comp: ("anti_tank", "high")  # noqa: E731 - tank wall
    report = gate.run_validation(
        db, limit=0, comp_lean_fn=lean, table_lookup_fn=_lookup_from(table),
        with_timing=False)
    assert report["followed"]["n"] == 1
    assert report["followed"]["wins"] == 1
    assert report["not_followed"]["n"] == 1
    assert report["not_followed"]["wins"] == 0
    assert report["matrix"]["anti_tank"]["anti_tank"]["wins"] == 1
    assert report["matrix"]["anti_tank"]["anti_squishy"]["wins"] == 0
    # Malphite is uncovered in the toy table -> uncovered_champ counted.
    assert report["status_counts"]["uncovered_champ"] == 2


def test_run_validation_flip_ready_false_small_n(tmp_path):
    db = tmp_path / "t.db"
    conn = sqlite3.connect(str(db))
    conn.executescript(_make_db_schema())
    conn.execute("INSERT INTO matches VALUES ('M1','CLASSIC',1,1)")
    _ins(conn, "M1", 1, 100, "Cho", True, [2])
    _ins(conn, "M1", 6, 200, "Lux", False, [9])
    conn.commit()
    conn.close()
    table = {"Cho": {"anti_tank": {"order": ["2"]}, "anti_squishy": {"order": ["4"]}}}
    report = gate.run_validation(
        db, limit=0, comp_lean_fn=lambda c: ("anti_tank", "high"),
        table_lookup_fn=_lookup_from(table), with_timing=False)
    # One row cannot meet the >=300/arm rail.
    assert report["difference"]["flip_ready"] is False


def test_timing_report_median_split():
    rep = gate._timing_report([(5.0, True), (10.0, False), (20.0, True), (30.0, False)])
    assert rep["n"] == 4
    assert rep["median_min"] == pytest.approx(15.0)
    assert rep["fast"]["n"] == 2
    assert rep["slow"]["n"] == 2


def test_timing_report_empty():
    rep = gate._timing_report([])
    assert rep["n"] == 0 and rep["median_min"] is None


# --- helpers reused by the run_validation tests (named schema string) ----------
def _make_db_schema() -> str:
    return (
        "CREATE TABLE matches (match_id TEXT, game_mode TEXT, has_timeline INTEGER, "
        "game_creation_ts INTEGER);"
        "CREATE TABLE participants (match_id TEXT, participant_id INTEGER, team_id INTEGER, "
        "champion_name TEXT, win INTEGER, item0 INTEGER, item1 INTEGER, item2 INTEGER, "
        "item3 INTEGER, item4 INTEGER, item5 INTEGER, item6 INTEGER);"
        "CREATE TABLE timeline_events (match_id TEXT, timestamp_ms INTEGER, event_type TEXT, "
        "participant_id INTEGER, item_id INTEGER);"
    )


def _ins(conn, mid, pid, team, champ, win, items):
    cols = list(items) + [0] * (7 - len(items))
    conn.execute(
        "INSERT INTO participants VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (mid, pid, team, champ, 1 if win else 0, *cols[:7]))
