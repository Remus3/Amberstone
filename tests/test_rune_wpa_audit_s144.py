"""s144 lane 8 (true-audit) cycle 93 - core/rune_wpa.py hardening.

One test per audited weakness (F1-F11), each written RED against the
pre-fix module. Synthetic data only: hand-written match ids, a tmp
catalog, an in-memory or tmp sqlite DB (never the live corpus).

F1  sqlite3.Error inside the per-match loop was swallowed, so a locked
    DB served a silently partial corpus as ok=True (RM-1262, rune half).
F2  a match that failed after its first participant was counted stayed
    half-counted; observations now merge only for a cleanly read match.
F3  one non-numeric rune column raised out of _participant_runes and
    dropped EVERY participant of its match; now only that rune is skipped.
F4  the per-match catch was ``except Exception``, so a programming error
    was logged once per match and answered ok=True.
F5  load_rune_catalog promised fail-soft but raised on a wrong-shape
    catalog (a tree / slot / rune entry that is not an object), and a
    bool id was read as rune 1.
F6  elapsed_ms came from the wall clock (negative on a clock step).
F7  compute_rune_wpa_from_db built its read-only URI with an f-string,
    so a '#' in the path opened the wrong file (RM-1257, rune half).
F8  compute_rune_wpa_from_db treated a DIRECTORY as a present DB and
    raised, instead of the documented "missing" dict.
F9  min_n was never validated (None / bool / negative / str / float).
F10 a rune id repeated inside ONE participant's minor slots was counted
    once per slot, inflating n for a corrupt row.
F11 a broken DS engine import silently emptied every proc_modeled flag
    with no log line.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import sys
from pathlib import Path
from unittest import mock

import pytest

from core import rune_wpa
from tests.test_rune_wpa import CHEAP_SHOT, ELECTROCUTE, _add_match, _build_db


def _rows(result: dict, rid: int, slot_kind: str) -> list[dict]:
    return [it for it in result["items"]
            if it["rune_id"] == rid and it["slot_kind"] == slot_kind]


def _n(result: dict, rid: int, slot_kind: str = "keystone") -> int:
    rows = _rows(result, rid, slot_kind)
    return rows[0]["n"] if rows else 0


class _Proxy:
    """Connection proxy that raises on the Nth participants query."""

    def __init__(self, conn, fail_on: int, exc: BaseException):
        self._conn = conn
        self._fail_on = fail_on
        self._exc = exc
        self.calls = 0

    def execute(self, sql, *args):
        if "FROM participants" in sql:
            self.calls += 1
            if self.calls == self._fail_on:
                raise self._exc
        return self._conn.execute(sql, *args)


def _three_matches() -> sqlite3.Connection:
    conn = _build_db()
    for i in range(3):
        _add_match(conn, f"NA1_93{i}", team100_gold=5000, team200_gold=0,
                   team100_win=1, runes={1: {"keystone": ELECTROCUTE}})
    return conn


# -- F1: sqlite3.Error propagates out of the sweep --------------------------

def test_f1_locked_db_mid_sweep_raises_instead_of_partial_ok():
    proxy = _Proxy(_three_matches(), 2,
                   sqlite3.OperationalError("database is locked"))
    with pytest.raises(sqlite3.OperationalError):
        rune_wpa.compute_rune_wpa(proxy, min_n=1)


def test_f1_route_answers_503_and_caches_nothing(tmp_path):
    from dashboard import routes_rune_wpa as rrw
    from tests.test_routes_rune_wpa_audit_s144 import _one, _seed, _serve

    db = _seed(tmp_path / "rh.db")
    real_open = rrw._open_rewind_db_ro

    class _Wrap:
        def __init__(self):
            self._p = _Proxy(real_open(), 2,
                             sqlite3.OperationalError("database is locked"))

        def execute(self, sql, *a):
            return self._p.execute(sql, *a)

        def close(self):
            self._p._conn.close()

    rrw._CACHE.clear()
    try:
        with mock.patch.object(rrw, "_open_rewind_db_ro", _Wrap):
            status, payload = _one(_serve("/api/rune-wpa?min_n=1", db))
        assert status == 503, payload
        assert payload["ok"] is False
        assert rrw._CACHE == {}
    finally:
        rrw._CACHE.clear()


# -- F2: a match skipped half-way contributes nothing -----------------------

def test_f2_match_failing_after_first_participant_is_rolled_back_whole():
    conn = _build_db()
    # One match, two Electrocute users (one per team): the second
    # participant's expected-win estimate raises a data error.
    _add_match(conn, "NA1_940", team100_gold=0, team200_gold=0,
               team100_win=1,
               runes={1: {"keystone": ELECTROCUTE},
                      6: {"keystone": ELECTROCUTE}})
    real = rune_wpa._expected_win_for_team
    calls = {"n": 0}

    def _flaky(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 2:
            raise ValueError("malformed frame value")
        return real(*a, **kw)

    with mock.patch.object(rune_wpa, "_expected_win_for_team", _flaky):
        out = rune_wpa.compute_rune_wpa(conn, min_n=0)
    assert out["ok"] is True
    assert _n(out, ELECTROCUTE) == 0, out["items"]


# -- F3: one malformed rune column skips that rune only ---------------------

def test_f3_non_numeric_rune_column_skips_only_that_rune():
    conn = _build_db()
    _add_match(conn, "NA1_950", team100_gold=0, team200_gold=0,
               team100_win=1,
               runes={1: {"keystone": ELECTROCUTE},
                      2: {"keystone": ELECTROCUTE,
                          "minors": [CHEAP_SHOT]}})
    conn.execute("UPDATE participants SET rune_p2='garbage' "
                 "WHERE match_id='NA1_950' AND participant_id=2")
    conn.commit()
    out = rune_wpa.compute_rune_wpa(conn, min_n=0)
    assert _n(out, ELECTROCUTE) == 2, out["items"]
    assert _n(out, CHEAP_SHOT, "minor") == 1, out["items"]


def test_f3_non_numeric_keystone_keeps_that_participants_minors():
    conn = _build_db()
    _add_match(conn, "NA1_951", team100_gold=0, team200_gold=0,
               team100_win=1,
               runes={1: {"keystone": ELECTROCUTE},
                      2: {"keystone": ELECTROCUTE,
                          "minors": [CHEAP_SHOT]}})
    conn.execute("UPDATE participants SET rune_keystone_id='x' "
                 "WHERE match_id='NA1_951' AND participant_id=2")
    conn.commit()
    out = rune_wpa.compute_rune_wpa(conn, min_n=0)
    assert _n(out, ELECTROCUTE) == 1, out["items"]
    assert _n(out, CHEAP_SHOT, "minor") == 1, out["items"]


# -- F4: a defect surfaces instead of a per-match log line ------------------

def test_f4_programming_error_surfaces():
    conn = _three_matches()
    with mock.patch.object(rune_wpa, "_expected_win_for_team",
                           side_effect=RuntimeError("defect")):
        with pytest.raises(RuntimeError):
            rune_wpa.compute_rune_wpa(conn, min_n=1)


def test_f4_data_error_still_skips_the_match(caplog):
    conn = _three_matches()
    real = rune_wpa._expected_win_for_team
    calls = {"n": 0}

    def _flaky(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TypeError("bad frame row")
        return real(*a, **kw)

    with caplog.at_level(logging.WARNING, logger="rc.rune_wpa"), \
         mock.patch.object(rune_wpa, "_expected_win_for_team", _flaky):
        out = rune_wpa.compute_rune_wpa(conn, min_n=1)
    assert out["ok"] is True
    assert _n(out, ELECTROCUTE) == 2
    assert any("skipped" in r.getMessage() for r in caplog.records)


# -- F5: wrong-shape catalog is fail-soft -----------------------------------

def _catalog(tmp_path: Path, data) -> Path:
    p = tmp_path / "runes.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


@pytest.mark.parametrize("doc", [
    [1, "tree"],
    [{"slots": 5}],
    [{"slots": [7, "slot"]}],
    [{"slots": [{"runes": 3}]}],
    [{"slots": [{"runes": [None, "rune", 4]}]}],
    {"not": "a list"},
    None,
])
def test_f5_wrong_shape_catalog_returns_empty_not_raise(tmp_path, doc):
    assert rune_wpa.load_rune_catalog(_catalog(tmp_path, doc)) == {}


def test_f5_bad_entries_skipped_good_ones_kept(tmp_path):
    doc = [
        "junk",
        {"slots": [
            "junk",
            {"runes": [
                "junk",
                {"id": True, "name": "Bool"},
                {"id": 8112, "name": "Electrocute", "icon": "e.png"},
            ]},
        ]},
    ]
    cat = rune_wpa.load_rune_catalog(_catalog(tmp_path, doc))
    assert cat == {8112: ("Electrocute", "e.png")}


# -- F6: elapsed_ms is monotonic --------------------------------------------

def test_f6_elapsed_ms_never_negative_on_a_wall_clock_step():
    clock = iter(range(10**9, 0, -1000))
    with mock.patch.object(rune_wpa.time, "time",
                           side_effect=lambda: float(next(clock))):
        out = rune_wpa.compute_rune_wpa(_build_db(), min_n=1)
    assert out["elapsed_ms"] >= 0


# -- F7 / F8: the from_db wrapper -------------------------------------------

def _seed_file(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.executescript(
        "CREATE TABLE matches (match_id TEXT, queue_id INTEGER, "
        "patch TEXT, has_timeline INTEGER);"
        "CREATE TABLE timeline_frames (match_id TEXT, timestamp_ms INTEGER, "
        "participant_id INTEGER, total_gold INTEGER, xp INTEGER);"
        "CREATE TABLE participants (match_id TEXT, participant_id INTEGER, "
        "team_id INTEGER, win INTEGER, rune_keystone_id INTEGER, "
        "rune_p0 INTEGER, rune_p1 INTEGER, rune_p2 INTEGER, rune_p3 INTEGER, "
        "rune_s0 INTEGER, rune_s1 INTEGER);"
    )
    _add_match(conn, "NA1_960", team100_gold=5000, team200_gold=0,
               team100_win=1, runes={1: {"keystone": ELECTROCUTE}})
    conn.close()
    return path


def test_f7_hash_in_the_db_path_opens_the_right_file(tmp_path):
    db = _seed_file(tmp_path / "a#b" / "rh.db")
    out = rune_wpa.compute_rune_wpa_from_db(
        db, min_n=0, model_path=tmp_path / "absent_model.json")
    assert out["ok"] is True, out
    assert _n(out, ELECTROCUTE) == 1


def test_f7_connect_uri_is_percent_encoded(tmp_path):
    db = _seed_file(tmp_path / "a#b" / "rh.db")
    seen: list[str] = []
    real = sqlite3.connect

    def _spy(database, *a, **kw):
        seen.append(database)
        return real(database, *a, **kw)

    with mock.patch.object(rune_wpa.sqlite3, "connect", _spy):
        rune_wpa.compute_rune_wpa_from_db(
            db, min_n=0, model_path=tmp_path / "absent_model.json")
    assert seen and seen[0].startswith("file:///"), seen
    assert "#" not in seen[0] and seen[0].endswith("?mode=ro"), seen


def test_f8_directory_db_path_is_the_missing_dict(tmp_path):
    d = tmp_path / "rewind_history.db"
    d.mkdir()
    assert rune_wpa.compute_rune_wpa_from_db(d) == {
        "ok": False, "error": "rewind_history.db missing"}


# -- F9: min_n validation ---------------------------------------------------

@pytest.mark.parametrize("bad", [None, True, False, -1, "20", 1.5])
def test_f9_bad_min_n_is_a_value_error(bad):
    with pytest.raises(ValueError):
        rune_wpa.compute_rune_wpa(_build_db(), min_n=bad)


def test_f9_min_n_zero_is_accepted():
    out = rune_wpa.compute_rune_wpa(_three_matches(), min_n=0)
    assert out["min_n"] == 0
    assert _n(out, ELECTROCUTE) == 3


# -- F10: one participant contributes one sample per (rune, slot) -----------

def test_f10_repeated_minor_in_one_participant_counts_once():
    conn = _build_db()
    _add_match(conn, "NA1_970", team100_gold=0, team200_gold=0,
               team100_win=1,
               runes={1: {"keystone": ELECTROCUTE,
                          "minors": [CHEAP_SHOT, CHEAP_SHOT, CHEAP_SHOT]}})
    out = rune_wpa.compute_rune_wpa(conn, min_n=0)
    assert _n(out, CHEAP_SHOT, "minor") == 1, out["items"]
    assert _n(out, ELECTROCUTE) == 1


# -- F11: a broken engine import is logged ----------------------------------

def test_f11_broken_engine_import_is_logged_and_degrades(caplog):
    with caplog.at_level(logging.WARNING, logger="rc.rune_wpa"), \
         mock.patch.dict(sys.modules,
                         {"agents.daemon_slayer.rune_procs": None}):
        ids = rune_wpa._proc_modeled_rune_ids()
    assert ids == frozenset()
    assert any("rune_procs" in r.getMessage() for r in caplog.records)


def test_f11_working_engine_import_still_returns_ids():
    ids = rune_wpa._proc_modeled_rune_ids()
    assert ids and all(isinstance(i, int) for i in ids)
