"""S144-T-598 - agents/agent2_backend/db_migrate_kda.py hardening.

The supervisor runs ``ensure_all()`` on every boot (agents/supervisor.py
start(), right after init_all_dbs) and backfill_kda calls
``ensure_kda_columns`` before its SELECT. Measured on the old module
(Python 3.14, SQLite 3.50):

- every call leaked its sqlite3 Connection (``with sqlite3.connect(...)``
  only commits, it never closes): ResourceWarning: unclosed database, and on
  a raise the Windows file handle lived as long as the traceback;
- a database with no ``matches`` table raised OperationalError
  "no such table: matches" out of the ALTER;
- ``ensure_all`` stopped at the FIRST mode that raised, so every later mode
  (sr_draft is first; aram, arena, brawl come after it) was never migrated;
- a str path raised AttributeError ('str' has no attribute 'exists');
- a file that vanished between the exists() check and the connect was
  re-created by sqlite3.connect as a 0-byte database.
"""
from __future__ import annotations

import gc
import logging
import sqlite3
import warnings
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

import agents.agent2_backend.db_migrate_kda as mk
import agents.agent2_backend.db_schema as dbs

_REAL_CONNECT = sqlite3.connect


def _make_db(path: Path, ddl: str = "CREATE TABLE matches (match_id INTEGER PRIMARY KEY, champion TEXT)") -> Path:
    conn = _REAL_CONNECT(path)
    try:
        conn.execute(ddl)
        conn.commit()
    finally:
        conn.close()
    return path


def _columns(path: Path, table: str = "matches") -> list[str]:
    conn = _REAL_CONNECT(path)
    try:
        return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
    finally:
        conn.close()


@pytest.fixture
def opened(monkeypatch):
    """Record every connection the module opens."""
    seen: list[sqlite3.Connection] = []

    def _connect(*args, **kwargs):
        conn = _REAL_CONNECT(*args, **kwargs)
        seen.append(conn)
        return conn

    monkeypatch.setattr(mk.sqlite3, "connect", _connect)
    return seen


def _is_closed(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute("SELECT 1")
    except sqlite3.ProgrammingError:
        return True
    return False


# -- resource lifetime -------------------------------------------------------

def test_connection_is_closed_after_a_migration(tmp_path, opened):
    db = _make_db(tmp_path / "aram.db")
    assert mk.ensure_kda_columns(db) == dict.fromkeys(mk.KDA_COLUMNS, True)
    assert len(opened) == 1
    assert _is_closed(opened[0])


def test_connection_is_closed_when_already_migrated(tmp_path, opened):
    db = _make_db(tmp_path / "aram.db")
    mk.ensure_kda_columns(db)
    assert mk.ensure_kda_columns(db) == dict.fromkeys(mk.KDA_COLUMNS, False)
    assert opened and all(_is_closed(c) for c in opened)


def test_connection_is_closed_when_the_alter_raises(tmp_path, monkeypatch, opened):
    db = _make_db(tmp_path / "aram.db")
    real_alter = mk._add_column

    def _boom(conn, col):
        if col == "deaths":
            raise sqlite3.OperationalError("disk I/O error")
        return real_alter(conn, col)

    monkeypatch.setattr(mk, "_add_column", _boom)
    with pytest.raises(sqlite3.OperationalError, match="disk I/O error"):
        mk.ensure_kda_columns(db)
    assert opened and all(_is_closed(c) for c in opened)


def test_connection_is_closed_on_a_corrupt_file(tmp_path, opened):
    db = tmp_path / "aram.db"
    db.write_bytes(b"this is not an sqlite database " * 8)
    with pytest.raises(sqlite3.DatabaseError):
        mk.ensure_kda_columns(db)
    assert opened and all(_is_closed(c) for c in opened)


def test_no_unclosed_database_resource_warning(tmp_path):
    db = _make_db(tmp_path / "aram.db")
    # s156 C9: flush garbage an EARLIER test left on this xdist worker first,
    # so the recorded window sees only connections ensure_kda_columns made.
    gc.collect()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        mk.ensure_kda_columns(db)
        mk.ensure_kda_columns(db)
        gc.collect()
    leaked = [w for w in caught if issubclass(w.category, ResourceWarning)
              and "unclosed database" in str(w.message)]
    assert leaked == []


# -- missing matches table ---------------------------------------------------

def test_db_without_a_matches_table_is_reported_not_raised(tmp_path, caplog):
    db = _make_db(tmp_path / "aram.db", "CREATE TABLE other (x INTEGER)")
    with caplog.at_level(logging.WARNING, logger="agent2.db_migrate_kda"):
        assert mk.ensure_kda_columns(db) == dict.fromkeys(mk.KDA_COLUMNS, False)
    assert "no matches table" in caplog.text
    # Nothing was created: the migration never invents a table.
    assert _columns(db) == []
    assert _columns(db, "other") == ["x"]


# -- the file is never created -----------------------------------------------

class _LyingPath(type(Path())):
    """A path whose exists() says True - the vanished-between-check race."""

    def exists(self, *args, **kwargs):  # noqa: D401
        return True


def test_a_vanished_file_is_not_recreated(tmp_path):
    target = _LyingPath(tmp_path / "gone.db")
    with pytest.raises(sqlite3.OperationalError):
        mk.ensure_kda_columns(target)
    assert not (tmp_path / "gone.db").exists()


def test_missing_db_returns_all_false_and_creates_nothing(tmp_path, opened):
    target = tmp_path / "missing.db"
    assert mk.ensure_kda_columns(target) == dict.fromkeys(mk.KDA_COLUMNS, False)
    assert opened == []
    assert not target.exists()


def test_rw_uri_quotes_and_marks_read_write(tmp_path):
    p = tmp_path / "sp ace#1.db"
    uri = mk._rw_uri(p)
    assert uri is not None
    assert uri.startswith("file:")
    assert uri.endswith("?mode=rw")
    assert " " not in uri and "#" not in uri.split("?", 1)[0]


def test_rw_uri_opens_a_path_with_a_space_and_a_hash(tmp_path):
    db = _make_db(tmp_path / "sp ace#1.db")
    assert mk.ensure_kda_columns(db) == dict.fromkeys(mk.KDA_COLUMNS, True)
    assert {"kills", "deaths", "assists"} <= set(_columns(db))


def test_rw_uri_declines_a_unc_path():
    # A file: URI with an authority is refused by a default SQLite build, so a
    # UNC path falls back to a plain connect (existence still checked).
    assert mk._rw_uri(PureWindowsPath(r"\\server\share\db\aram.db")) is None
    assert mk._rw_uri(PurePosixPath("//server/share/aram.db")) is None


class _ResolvesToUnc(type(Path())):
    """A local-looking path that resolves to a share (a symlink to one, or a
    mapped network drive)."""

    def resolve(self, strict=False):
        return type(Path())("//server/share/db/aram.db")


class _NoResolve(type(Path())):
    def resolve(self, strict=False):
        raise AssertionError("resolve() touched an already-UNC path")


def test_rw_uri_does_not_resolve_an_already_unc_path():
    # Resolving a UNC path can block on the network; it is declined first.
    assert mk._rw_uri(_NoResolve("//server/share/db/aram.db")) is None


def test_rw_uri_declines_a_local_path_that_resolves_to_unc(tmp_path):
    # Found by the verifier: checking only the INPUT string sent
    # file://server/... to SQLite, which refuses a URI with an authority.
    assert mk._rw_uri(_ResolvesToUnc(tmp_path / "link.db")) is None


# -- input shape -------------------------------------------------------------

def test_a_str_path_is_accepted(tmp_path):
    db = _make_db(tmp_path / "aram.db")
    assert mk.ensure_kda_columns(str(db)) == dict.fromkeys(mk.KDA_COLUMNS, True)


@pytest.mark.parametrize("bad", [None, 7, True, b"aram.db", ["aram.db"]])
def test_a_non_path_is_refused_with_typeerror(bad):
    with pytest.raises(TypeError):
        mk.ensure_kda_columns(bad)


# -- ensure_all isolates one bad mode ----------------------------------------

def _mode_dir(tmp_path: Path, monkeypatch, bad_mode: str, bad_ddl: str | None) -> Path:
    monkeypatch.setattr(dbs, "DB_DIR", tmp_path)
    for mode, fname in dbs.MODE_DB_FILES.items():
        if mode == bad_mode:
            if bad_ddl is None:
                (tmp_path / fname).write_bytes(b"corrupt corrupt corrupt " * 8)
            else:
                _make_db(tmp_path / fname, bad_ddl)
        else:
            _make_db(tmp_path / fname)
    return tmp_path


def test_ensure_all_migrates_every_mode_after_a_corrupt_one(tmp_path, monkeypatch):
    first = next(iter(dbs.MODE_DB_FILES))
    d = _mode_dir(tmp_path, monkeypatch, first, None)
    with pytest.raises(mk.KdaMigrationError) as ei:
        mk.ensure_all()
    err = ei.value
    assert list(err.failed) == [first]
    assert err.failed[first] == "DatabaseError"
    for mode, fname in dbs.MODE_DB_FILES.items():
        if mode == first:
            continue
        assert {"kills", "deaths", "assists"} <= set(_columns(d / fname)), mode
        assert err.results[mode] == dict.fromkeys(mk.KDA_COLUMNS, True)
    assert first not in err.results
    # The message names the mode and the exception TYPE only.
    assert first in str(err) and "DatabaseError" in str(err)


def test_ensure_all_is_an_exception_subclass_the_supervisor_catches():
    assert issubclass(mk.KdaMigrationError, Exception)


def test_ensure_all_happy_path_returns_every_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(dbs, "DB_DIR", tmp_path)
    for fname in dbs.MODE_DB_FILES.values():
        _make_db(tmp_path / fname)
    out = mk.ensure_all()
    assert list(out) == list(dbs.MODE_DB_FILES)
    assert all(v == dict.fromkeys(mk.KDA_COLUMNS, True) for v in out.values())
    assert mk.ensure_all() == {m: dict.fromkeys(mk.KDA_COLUMNS, False) for m in dbs.MODE_DB_FILES}


def test_ensure_all_with_no_db_dir_is_all_false(tmp_path, monkeypatch):
    monkeypatch.setattr(dbs, "DB_DIR", tmp_path / "nope")
    out = mk.ensure_all()
    assert out == {m: dict.fromkeys(mk.KDA_COLUMNS, False) for m in dbs.MODE_DB_FILES}
    assert not (tmp_path / "nope").exists()


def test_ensure_all_does_not_swallow_a_programming_error(tmp_path, monkeypatch):
    monkeypatch.setattr(dbs, "DB_DIR", tmp_path)
    for fname in dbs.MODE_DB_FILES.values():
        _make_db(tmp_path / fname)

    def _bug(path):
        raise KeyError("bug")

    monkeypatch.setattr(mk, "ensure_kda_columns", _bug)
    with pytest.raises(KeyError):
        mk.ensure_all()


# -- CLI ---------------------------------------------------------------------

def test_main_exits_one_and_prints_partial_results_on_failure(tmp_path, monkeypatch, capsys):
    first = next(iter(dbs.MODE_DB_FILES))
    _mode_dir(tmp_path, monkeypatch, first, None)
    assert mk.main([]) == 1
    out = capsys.readouterr().out
    assert '"aram"' in out
    assert first in out and "DatabaseError" in out


def test_main_exits_zero_on_success(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(dbs, "DB_DIR", tmp_path)
    for fname in dbs.MODE_DB_FILES.values():
        _make_db(tmp_path / fname)
    assert mk.main([]) == 0
    assert '"kills": true' in capsys.readouterr().out


# -- valid input is unchanged -------------------------------------------------

def test_partial_columns_only_adds_the_missing_ones(tmp_path, monkeypatch):
    db = _make_db(tmp_path / "aram.db",
                  "CREATE TABLE matches (match_id INTEGER PRIMARY KEY, KILLS INTEGER)")
    attempted: list[str] = []
    real_add = mk._add_column

    def _spy(conn, col):
        attempted.append(col)
        return real_add(conn, col)

    monkeypatch.setattr(mk, "_add_column", _spy)
    assert mk.ensure_kda_columns(db) == {"kills": False, "deaths": True, "assists": True}
    # Column names are case-insensitive, so no doomed ALTER for "kills".
    assert attempted == ["deaths", "assists"]
    cols = _columns(db)
    assert cols.count("KILLS") == 1 and "kills" not in cols
    assert cols[-2:] == ["deaths", "assists"]


def test_added_columns_are_integer_and_existing_rows_read_null(tmp_path):
    db = _make_db(tmp_path / "aram.db")
    conn = _REAL_CONNECT(db)
    conn.execute("INSERT INTO matches (champion) VALUES ('Ahri')")
    conn.commit()
    conn.close()
    mk.ensure_kda_columns(db)
    conn = _REAL_CONNECT(db)
    try:
        types = {r[1]: r[2] for r in conn.execute("PRAGMA table_info(matches)")}
        row = conn.execute("SELECT kills, deaths, assists FROM matches").fetchone()
    finally:
        conn.close()
    assert [types[c] for c in mk.KDA_COLUMNS] == ["INTEGER"] * 3
    assert row == (None, None, None)


def test_a_concurrent_duplicate_column_reads_as_already_present(tmp_path, monkeypatch):
    db = _make_db(tmp_path / "aram.db")
    real_existing = mk._existing_columns

    def _stale(conn, table):
        # Another writer added "kills" after this snapshot was taken.
        cols = real_existing(conn, table)
        conn.execute("ALTER TABLE matches ADD COLUMN kills INTEGER")
        return cols

    monkeypatch.setattr(mk, "_existing_columns", _stale)
    assert mk.ensure_kda_columns(db) == {"kills": False, "deaths": True, "assists": True}
