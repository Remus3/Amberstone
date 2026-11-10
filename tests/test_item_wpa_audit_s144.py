"""s144 lane 8 (true-audit) cycle 91 - core/item_wpa.py hardening.

One test per audited weakness (F1-F10), each written RED against the
pre-fix module. Synthetic data only: hand-written match ids, a tmp
catalog, an in-memory or tmp sqlite DB (never the live corpus).

F1  sqlite3.Error inside the per-match loop was swallowed, so a locked
    DB served a silently partial corpus as ok=True (RM-1256).
F2  a match that failed half-way kept the purchases counted before the
    failure - "skipped" matches were half-counted.
F3  one malformed event row (non-numeric item / participant id) dropped
    every later purchase of its match; an event with no timestamp was
    counted as a purchase at 0:00.
F4  the per-match catch was ``except Exception``, so a programming error
    (or a broken model) was logged once per match and answered ok=True.
F5  load_legendary_ids promised fail-soft but raised on a wrong-shape
    catalog; a string ``tags`` field dodged the Boots/Consumable gate.
F6  _load_frames compared the RAW timestamp against the normalised one,
    so NULL-timestamp rows each became their own duplicate frame.
F7  elapsed_ms came from the wall clock (negative on a clock step).
F8  compute_item_wpa_from_db built its read-only URI with an f-string,
    so a '#' or '%' in the path opened the wrong file (RM-1257).
F9  compute_item_wpa_from_db treated a DIRECTORY as a present DB and
    raised, instead of the documented "missing" dict.
F10 min_n was never validated (None / bool / negative / str).
"""
from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING
from unittest import mock

import pytest

from core import item_wpa
from tests.test_item_wpa import IE, _add_match, _build_db

if TYPE_CHECKING:
    from pathlib import Path

_SCHEMA = """
CREATE TABLE matches (
    match_id TEXT, queue_id INTEGER, patch TEXT, has_timeline INTEGER
);
CREATE TABLE timeline_frames (
    match_id TEXT, timestamp_ms INTEGER, participant_id INTEGER,
    total_gold INTEGER, xp INTEGER
);
CREATE TABLE timeline_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id TEXT, timestamp_ms INTEGER, event_type TEXT,
    participant_id INTEGER, item_id INTEGER
);
CREATE TABLE participants (
    match_id TEXT, participant_id INTEGER, team_id INTEGER, win INTEGER
);
"""

_GOOD_ITEM = {
    "name": "Audit Blade",
    "gold": {"purchasable": True, "total": 3000},
    "into": [],
    "from": ["1038"],
    "tags": ["Damage"],
    "maps": {"11": True, "12": True},
}


def _catalog(tmp_path: Path, data) -> Path:
    p = tmp_path / "items.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


@pytest.fixture
def cat(tmp_path):
    """A one-item catalog: IE (3031) is the only legendary."""
    return _catalog(tmp_path, {"data": {str(IE): dict(_GOOD_ITEM,
                                                       name="IE")}})


def _ie(result: dict) -> dict | None:
    for it in result["items"]:
        if it["item_id"] == IE:
            return it
    return None


class _Proxy:
    """Connection proxy that raises on the Nth timeline_events query."""

    def __init__(self, conn, fail_on: int, exc: Exception):
        self._conn = conn
        self._fail_on = fail_on
        self._exc = exc
        self.ev_calls = 0

    def execute(self, sql, *args):
        if "FROM timeline_events" in sql:
            self.ev_calls += 1
            if self.ev_calls == self._fail_on:
                raise self._exc
        return self._conn.execute(sql, *args)


# -- F1: sqlite3.Error propagates out of the sweep --------------------------

def test_f1_locked_db_mid_sweep_raises_instead_of_partial_ok(cat):
    conn = _build_db()
    for i in range(3):
        _add_match(conn, f"NA1_90{i}", team100_gold=5000, team200_gold=0,
                   team100_win=1, purchases=[(120_000, 1, IE)])
    proxy = _Proxy(conn, 2, sqlite3.OperationalError("database is locked"))
    with pytest.raises(sqlite3.OperationalError):
        item_wpa.compute_item_wpa(proxy, min_n=1, items_json=cat)


def test_f1_route_answers_503_and_caches_nothing(cat, tmp_path):
    from dashboard import routes_item_wpa as riw
    from tests.test_routes_item_wpa_audit_s144 import _one, _serve

    db = tmp_path / "rh.db"
    seed = sqlite3.connect(str(db))
    seed.executescript(_SCHEMA)
    for i in range(3):
        _add_match(seed, f"NA1_91{i}", team100_gold=5000, team200_gold=0,
                   team100_win=1, purchases=[(120_000, 1, IE)])
    seed.close()

    real_open = riw._open_rewind_db_ro

    class _Wrap:
        def __init__(self):
            self._p = _Proxy(real_open(), 2,
                             sqlite3.OperationalError("database is locked"))

        def execute(self, sql, *a):
            return self._p.execute(sql, *a)

        def close(self):
            self._p._conn.close()

    riw._CACHE.clear()
    try:
        with mock.patch.object(riw, "_open_rewind_db_ro", _Wrap):
            status, payload = _one(_serve("/api/item-wpa?min_n=1", db))
        assert status == 503, payload
        assert payload["ok"] is False
        assert not riw._CACHE
    finally:
        riw._CACHE.clear()


# -- F2: a failing match is rolled back whole -------------------------------

def test_f2_match_failing_half_way_contributes_nothing(cat):
    conn = _build_db()
    # Purchase 1 (60s) reads the clean 60s frame; purchase 2 (700s) reads
    # the 600s frame, poisoned with a non-numeric gold value.
    _add_match(conn, "NA1_920", team100_gold=5000, team200_gold=0,
               team100_win=1, purchases=[(70_000, 1, IE), (700_000, 2, IE)])
    conn.execute("UPDATE timeline_frames SET total_gold='garbage' "
                 "WHERE match_id='NA1_920' AND timestamp_ms=600000 "
                 "AND participant_id=3")
    conn.commit()
    out = item_wpa.compute_item_wpa(conn, min_n=1, items_json=cat)
    assert out["ok"] is True
    assert _ie(out) is None, out["items"]


def test_f2_clean_match_beside_a_failing_one_is_kept(cat):
    conn = _build_db()
    _add_match(conn, "NA1_921", team100_gold=5000, team200_gold=0,
               team100_win=1, purchases=[(70_000, 1, IE), (700_000, 2, IE)])
    conn.execute("UPDATE timeline_frames SET total_gold='garbage' "
                 "WHERE match_id='NA1_921' AND timestamp_ms=600000 "
                 "AND participant_id=3")
    _add_match(conn, "NA1_922", team100_gold=5000, team200_gold=0,
               team100_win=1, purchases=[(70_000, 1, IE)])
    conn.commit()
    out = item_wpa.compute_item_wpa(conn, min_n=1, items_json=cat)
    assert _ie(out)["n"] == 1


# -- F3: a malformed event row skips only itself ----------------------------

@pytest.mark.parametrize("bad", [
    (60_000, 1, "not-an-item"),
    (60_000, "p?", IE),
])
def test_f3_bad_event_row_skips_only_that_event(cat, bad):
    conn = _build_db()
    _add_match(conn, "NA1_930", team100_gold=5000, team200_gold=0,
               team100_win=1, purchases=[bad, (120_000, 2, IE)])
    out = item_wpa.compute_item_wpa(conn, min_n=1, items_json=cat)
    got = _ie(out)
    assert got is not None and got["n"] == 1, out["items"]


def test_f3_event_without_timestamp_is_not_a_purchase_at_zero(cat):
    conn = _build_db()
    _add_match(conn, "NA1_931", team100_gold=5000, team200_gold=0,
               team100_win=1, purchases=[(None, 1, IE), (120_000, 2, IE)])
    out = item_wpa.compute_item_wpa(conn, min_n=1, items_json=cat)
    got = _ie(out)
    assert got["n"] == 1
    assert got["avg_purchase_time_s"] == 120.0


# -- F4: an unexpected error surfaces ---------------------------------------

def test_f4_programming_error_is_not_swallowed(cat):
    conn = _build_db()
    _add_match(conn, "NA1_940", team100_gold=5000, team200_gold=0,
               team100_win=1, purchases=[(120_000, 1, IE)])

    def _boom(*a, **k):
        raise RuntimeError("bug")

    with mock.patch.object(item_wpa, "_expected_win_for_team", _boom), \
            pytest.raises(RuntimeError):
        item_wpa.compute_item_wpa(conn, min_n=1, items_json=cat)


# -- F5: catalog shape is validated, fail-soft ------------------------------

@pytest.mark.parametrize("data", [
    [1, 2, 3],
    {"data": [1, 2]},
    "just a string",
    None,
])
def test_f5_wrong_shape_catalog_is_empty_not_a_crash(tmp_path, data):
    assert item_wpa.load_legendary_ids(_catalog(tmp_path, data)) == {}


@pytest.mark.parametrize("bad_entry", [
    "not a dict",
    None,
    dict(_GOOD_ITEM, gold=3000),
    dict(_GOOD_ITEM, gold={"purchasable": True, "total": "3000"}),
    dict(_GOOD_ITEM, gold={"purchasable": True, "total": True}),
    dict(_GOOD_ITEM, gold={"purchasable": True, "total": float("nan")}),
    dict(_GOOD_ITEM, maps=["11"]),
    dict(_GOOD_ITEM, tags="Boots"),
    dict(_GOOD_ITEM, tags=7),
])
def test_f5_bad_entry_is_skipped_others_kept(tmp_path, bad_entry):
    p = _catalog(tmp_path, {"data": {"9001": _GOOD_ITEM,
                                     "9002": bad_entry}})
    assert item_wpa.load_legendary_ids(p) == {9001: "Audit Blade"}


def test_f5_good_catalog_unchanged(tmp_path):
    p = _catalog(tmp_path, {"data": {"9001": _GOOD_ITEM}})
    assert item_wpa.load_legendary_ids(p) == {9001: "Audit Blade"}
    assert item_wpa.load_legendary_ids(p, map_id=30) == {}


# -- F6: frames grouped on the normalised timestamp -------------------------

def test_f6_null_timestamp_rows_form_one_frame():
    conn = _build_db()
    for pid in (1, 6):
        conn.execute("INSERT INTO timeline_frames VALUES (?,?,?,?,?)",
                     ("NA1_960", None, pid, 500, 100))
    conn.execute("INSERT INTO timeline_frames VALUES (?,?,?,?,?)",
                 ("NA1_960", 60_000, 1, 900, 200))
    frames = item_wpa._load_frames(conn, "NA1_960")
    assert [ts for ts, _ in frames] == [0, 60_000]
    assert len(frames[0][1]) == 2


def test_f6_stringly_timestamp_rows_group_with_their_int_twin():
    class _Conn:
        def execute(self, sql, params):
            return iter([(0, 1, 10, 1), ("0", 6, 10, 1),
                         (60000, 1, 20, 2), ("60000", 6, 20, 2)])

    frames = item_wpa._load_frames(_Conn(), "NA1_961")
    assert [(ts, len(rows)) for ts, rows in frames] == [(0, 2), (60_000, 2)]


# -- F7: elapsed_ms is monotonic --------------------------------------------

def test_f7_wall_clock_step_back_never_gives_negative_elapsed(cat):
    conn = _build_db()
    clock = iter([1_000_000.0, 10.0, 10.0, 10.0])
    with mock.patch.object(item_wpa.time, "time",
                           lambda: next(clock, 10.0)):
        out = item_wpa.compute_item_wpa(conn, min_n=1, items_json=cat)
    assert out["elapsed_ms"] >= 0


# -- F8: the read-only URI survives '#', '%' and '?' in the path ------------

@pytest.mark.parametrize("dirname", ["a#b", "a%41b", "a?b"])
def test_f8_from_db_opens_the_named_file(tmp_path, dirname):
    d = tmp_path / dirname
    try:
        d.mkdir()
    except OSError:
        pytest.skip(f"filesystem refuses {dirname!r}")
    db = d / "rh.db"
    seed = sqlite3.connect(str(db))
    seed.executescript(_SCHEMA)
    _add_match(seed, "NA1_980", team100_gold=5000, team200_gold=0,
               team100_win=1, purchases=[(120_000, 1, IE)])
    seed.close()
    out = item_wpa.compute_item_wpa_from_db(
        db, min_n=1, model_path=tmp_path / "absent_model.json")
    assert out["ok"] is True, out
    assert _ie(out)["n"] == 1


def test_f8_from_db_connection_is_read_only(tmp_path):
    db = tmp_path / "rh.db"
    seed = sqlite3.connect(str(db))
    seed.executescript(_SCHEMA)
    seed.close()
    seen: list[str] = []
    real_connect = sqlite3.connect

    def _spy(database, *a, **k):
        seen.append(database)
        return real_connect(database, *a, **k)

    with mock.patch.object(item_wpa.sqlite3, "connect", _spy):
        item_wpa.compute_item_wpa_from_db(
            db, min_n=1, model_path=tmp_path / "absent_model.json")
    assert len(seen) == 1
    assert seen[0].startswith("file:") and seen[0].endswith("?mode=ro")


# -- F9: a directory is not a database --------------------------------------

def test_f9_directory_db_path_is_reported_missing(tmp_path):
    d = tmp_path / "rewind_history.db"
    d.mkdir()
    out = item_wpa.compute_item_wpa_from_db(
        d, model_path=tmp_path / "absent_model.json")
    assert out == {"ok": False, "error": "rewind_history.db missing"}


# -- F10: min_n is validated up front ---------------------------------------

@pytest.mark.parametrize("bad", [None, -1, True, "5", 2.5])
def test_f10_bad_min_n_is_a_value_error(cat, bad):
    conn = _build_db()
    with pytest.raises(ValueError):
        item_wpa.compute_item_wpa(conn, min_n=bad, items_json=cat)


@pytest.mark.parametrize("ok_n", [0, 1, 20])
def test_f10_good_min_n_accepted(cat, ok_n):
    conn = _build_db()
    out = item_wpa.compute_item_wpa(conn, min_n=ok_n, items_json=cat)
    assert out["ok"] is True and out["min_n"] == ok_n
