"""True-audit s144t172: agents/agent2_backend/db_schema.py.

The supervisor calls ``init_all()`` at every boot (agents/supervisor.py) and
``migration_rewind.migrate`` calls both ``init_all()`` and ``open_db()``. The
audit found three defects, each pinned here by a test that failed before the
fix:

1. ``init_mode`` opened its connection with ``with sqlite3.connect(p) as
   conn``. A sqlite3 Connection's context manager only COMMITS or ROLLS BACK;
   it never closes. Measured on the project interpreter (3.14): every
   ``init_mode`` call left an open connection behind and emitted
   ``ResourceWarning: unclosed database`` when it was collected, and on the
   exception path the traceback kept the frame - and so the Windows file
   handle - alive.
2. ``open_db`` leaked its half-open connection when the setup pragmas raised
   (measured on a corrupt ``.db`` file: ``DatabaseError: file is not a
   database``). While the exception was alive the file could not be deleted
   on Windows (WinError 32), so the operator could not even move the bad file
   aside from the same process.
3. ``db_path`` raised ``TypeError`` (unhashable) for a non-str mode instead of
   the ``ValueError`` its contract names for an unknown mode.

Characterization tests pin the behaviour that stays: idempotent schema, WAL,
foreign keys on, every mode file created, fail-closed on a corrupt database.
"""
from __future__ import annotations

import gc
import sqlite3
import sys
import warnings
from pathlib import Path

import pytest

import agents.agent2_backend.db_schema as dbs

_REAL_CONNECT = sqlite3.connect
_CORRUPT = b"this is not a sqlite database header" * 8


@pytest.fixture
def db_dir(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setattr(dbs, "DB_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def opened(monkeypatch) -> list[sqlite3.Connection]:
    """Record every connection the module opens through sqlite3.connect."""
    conns: list[sqlite3.Connection] = []

    def _connect(*args, **kwargs):
        conn = _REAL_CONNECT(*args, **kwargs)
        conns.append(conn)
        return conn

    monkeypatch.setattr(sqlite3, "connect", _connect)
    return conns


def _is_closed(conn: sqlite3.Connection) -> bool:
    # total_changes reads no file, so an OPEN connection to a corrupt database
    # answers normally (False) instead of raising DatabaseError; only a closed
    # connection raises ProgrammingError here.
    try:
        _ = conn.total_changes
    except sqlite3.ProgrammingError:
        return True
    return False


def _tables(path: Path) -> set[str]:
    conn = _REAL_CONNECT(path)
    try:
        return {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
    finally:
        conn.close()


# -- finding 1: init_mode never closed its connection ------------------------

def test_init_mode_closes_its_connection(db_dir, opened):
    dbs.init_mode("aram")
    assert opened, "init_mode opened no connection - test would be vacuous"
    assert all(_is_closed(c) for c in opened)


def _resource_warnings_from(action) -> list[str]:
    """The ResourceWarnings `action` itself causes, collected strictly.

    Garbage that already exists (connections an EARLIER test on the same
    xdist worker leaked) is collected first and its warnings discarded, so
    the recording window holds only what `action` leaves behind."""
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        gc.collect()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        action()
        gc.collect()
    return [str(w.message) for w in caught if issubclass(w.category, ResourceWarning)]


def test_init_mode_emits_no_unclosed_database_warning(db_dir):
    leaked = _resource_warnings_from(lambda: dbs.init_mode("arena"))
    assert leaked == [], leaked


def _leak_an_unclosed_connection(path: Path) -> None:
    """Open a real connection and drop it inside a reference cycle, so only a
    garbage collection finalizes it - the shape of a connection an EARLIER
    test on the same xdist worker leaked."""
    conn = sqlite3.connect(path)
    cycle: list = [conn]
    cycle.append(cycle)


def test_the_warning_check_ignores_connections_leaked_before_it(tmp_path):
    """s153 gated run 2 (LEDGER 2073): the check above read 23 "unclosed
    database" warnings, none from init_mode - they were connections earlier
    tests on its xdist worker leaked, finalized by its own gc.collect().
    Garbage that exists before the check starts is not the check's subject;
    a leak made inside the checked action still is (strictness kept)."""
    was_enabled = gc.isenabled()
    gc.disable()
    try:
        _leak_an_unclosed_connection(tmp_path / "earlier_test.db")
        assert _resource_warnings_from(lambda: None) == []
        own = _resource_warnings_from(
            lambda: _leak_an_unclosed_connection(tmp_path / "inside_the_check.db"))
    finally:
        if was_enabled:
            gc.enable()
    if sys.version_info >= (3, 13):  # sqlite3 warns on an unclosed connection from 3.13
        assert any("unclosed database" in m for m in own), own


def test_init_mode_closes_its_connection_when_schema_fails(db_dir, opened):
    bad = db_dir / "brawl.db"
    bad.write_bytes(_CORRUPT)
    with pytest.raises(sqlite3.DatabaseError):
        dbs.init_mode("brawl")
    assert opened and all(_is_closed(c) for c in opened)
    bad.unlink()  # WinError 32 here while a leaked handle is alive


# -- finding 2: open_db leaked a half-open connection on setup failure --------

def test_open_db_closes_connection_when_setup_fails(db_dir, opened):
    bad = db_dir / "arena.db"
    bad.write_bytes(_CORRUPT)
    with pytest.raises(sqlite3.DatabaseError) as excinfo:
        dbs.open_db("arena")
    assert excinfo.value is not None  # keeps the traceback alive on purpose
    assert opened and all(_is_closed(c) for c in opened)
    bad.unlink()  # WinError 32 here while the leaked handle is alive


def test_open_db_success_returns_an_open_wal_connection(db_dir):
    dbs.init_mode("sr_ranked")
    conn = dbs.open_db("sr_ranked")
    try:
        assert not _is_closed(conn)
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    finally:
        conn.close()


# -- finding 3: db_path raised TypeError for a non-str mode ------------------

@pytest.mark.parametrize("mode", [["aram"], {"aram": 1}, None, 1, b"aram", "ARAM", ""],
                         ids=["list", "dict", "none", "int", "bytes", "upper", "empty"])
def test_db_path_rejects_unknown_or_non_str_mode_with_value_error(db_dir, mode):
    with pytest.raises(ValueError, match="unknown mode"):
        dbs.db_path(mode)


def test_open_db_and_init_mode_reject_bad_mode_before_touching_disk(db_dir, opened):
    for fn in (dbs.open_db, dbs.init_mode):
        with pytest.raises(ValueError):
            fn(["aram"])
    assert opened == []
    assert list(db_dir.iterdir()) == []


# -- characterization: what stays ---------------------------------------------

def test_init_mode_is_idempotent_and_builds_the_schema(db_dir):
    p1 = dbs.init_mode("sr_draft")
    p2 = dbs.init_mode("sr_draft")
    assert p1 == p2 == db_dir / "sr_draft.db"
    assert {"matches", "match_events", "adaptation_buckets",
            "matchup_modifiers", "_migration_state"} <= _tables(p1)


def test_init_mode_leaves_the_file_in_wal(db_dir):
    p = dbs.init_mode("aram")
    conn = _REAL_CONNECT(p)
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    finally:
        conn.close()


def test_init_all_creates_every_mode_file(db_dir, opened):
    out = dbs.init_all()
    assert set(out) == set(dbs.MODE_DB_FILES)
    for mode, fname in dbs.MODE_DB_FILES.items():
        assert out[mode] == str(db_dir / fname)
        assert (db_dir / fname).is_file()
    assert len(opened) == len(dbs.MODE_DB_FILES)
    assert all(_is_closed(c) for c in opened)


def test_init_all_stays_fail_closed_on_a_corrupt_mode_db(db_dir):
    (db_dir / "aram.db").write_bytes(_CORRUPT)
    with pytest.raises(sqlite3.DatabaseError):
        dbs.init_all()
