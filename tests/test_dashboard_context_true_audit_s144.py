"""True-audit s144 (RM-1958..RM-1964): dashboard/_context.py, the shared reader
behind every dashboard builder and route (ro_conn, read_json,
read_json_checked).

Findings pinned here, each a failing test before the fix:
  - RM-1958 ro_conn built its sqlite URI by f-string from the raw path, so
    a '#' in a directory name truncated the path (a DIFFERENT file opened:
    "no such table") and a '%41' sequence was percent-decoded ("unable to
    open database file"). Now a percent-encoded URI (_ro_uri) - not
    Path.as_uri(), whose file://host/share form sqlite rejects for a UNC path
    (the core/ops_panels.py sibling carries that gap; filed, not fixed here).
  - RM-1959 ro_conn's contract is "None when the DB file is missing", but a
    directory at the path, or a file that vanished between the existence
    check and connect(), raised sqlite3.OperationalError out of the call -
    and the builders call it OUTSIDE their try.
  - RM-1960 a cached connection that any caller closed was handed back to
    every later same-thread caller ("Cannot operate on a closed database"),
    poisoning a long-lived SSE thread for its whole life.
  - RM-1961 the cache comment claimed ThreadingHTTPServer recycles worker
    threads; dashboard/server.py runs ONE thread per request, so every
    request thread dropped its connections unclosed at exit (ResourceWarning
    "unclosed database", handle held until GC). The cache now closes them
    when the thread's cache is released.
  - RM-1962 a UTF-8 BOM (PowerShell 5.1 Set-Content -Encoding UTF8, older
    Notepad) made read_json return {} and read_json_checked return ok=False
    forever, so the RM-278 writers never wrote coaching_data.json again.
  - RM-1963 a deeply nested JSON file raised RecursionError out of
    read_json_checked (it caught ValueError only) into the refresh /
    set_pregame writers.
  - RM-1964 read_json's blind `except Exception` also swallowed a caller
    bug (a non-path rel) as "file empty"; narrowed to the I/O and decode
    errors actually expected.
"""
from __future__ import annotations

import gc
import json
import sqlite3
import sys
import threading
import warnings
from pathlib import Path

import pytest

from dashboard import _context


def _make_db(path: Path, value: int = 7) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE t (x INTEGER)")
        conn.execute("INSERT INTO t VALUES (?)", (value,))
        conn.commit()
    finally:
        conn.close()
    return path


@pytest.fixture
def fresh_cache():
    """Run each test against an empty per-thread cache; close what it opened."""
    saved = getattr(_context.DB_CONN_LOCAL, "conns", None)
    if saved is not None:
        del _context.DB_CONN_LOCAL.conns
    yield
    conns = getattr(_context.DB_CONN_LOCAL, "conns", None)
    if conns is not None:
        for conn in list(conns.values()):
            conn.close()
        del _context.DB_CONN_LOCAL.conns
    if saved is not None:
        _context.DB_CONN_LOCAL.conns = saved


# -- characterization ---------------------------------------------------------

class TestRoConnContract:
    def test_missing_file_is_none(self, tmp_path, fresh_cache):
        assert _context.ro_conn(tmp_path / "absent.db") is None

    def test_reads_rows_and_is_read_only(self, tmp_path, fresh_cache):
        db = _make_db(tmp_path / "plain" / "x.db")
        conn = _context.ro_conn(db)
        assert conn.execute("SELECT x FROM t").fetchone() == (7,)
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("INSERT INTO t VALUES (1)")

    def test_same_thread_reuses_one_connection(self, tmp_path, fresh_cache):
        db = _make_db(tmp_path / "x.db")
        assert _context.ro_conn(db) is _context.ro_conn(db)

    def test_cache_keyed_by_str_path(self, tmp_path, fresh_cache):
        # The builders evict with conns.pop(str(db_path)); the key is a contract.
        db = _make_db(tmp_path / "x.db")
        conn = _context.ro_conn(db)
        assert _context.DB_CONN_LOCAL.conns[str(db)] is conn

    def test_other_thread_gets_its_own_connection(self, tmp_path, fresh_cache):
        db = _make_db(tmp_path / "x.db")
        mine = _context.ro_conn(db)
        seen = []

        def work():
            seen.append(_context.ro_conn(db))
            seen.append(seen[0].execute("SELECT x FROM t").fetchone())

        t = threading.Thread(target=work)
        t.start()
        t.join()
        assert seen[0] is not mine
        assert seen[1] == (7,)

    def test_space_in_path(self, tmp_path, fresh_cache):
        db = _make_db(tmp_path / "with space" / "x.db")
        assert _context.ro_conn(db).execute("SELECT x FROM t").fetchone() == (7,)


# -- RM-1958: URI built from the raw path ---------------------------------

@pytest.mark.parametrize("dirname", ["a#b", "p%41q", "u%2Fv", "m#n%20o"])
def test_t518_uri_special_chars_open_the_right_file(tmp_path, fresh_cache, dirname):
    # A decoy at the truncated / decoded path must never be the file opened.
    _make_db(tmp_path / "a" / "decoy.db", value=99)
    db = _make_db(tmp_path / dirname / "x.db", value=7)
    conn = _context.ro_conn(db)
    assert conn is not None
    assert conn.execute("SELECT x FROM t").fetchone() == (7,)


def _admin_share_path(local: Path, host: str) -> Path | None:
    """The same file reached over the host's own admin share, or None."""
    s = str(local.resolve())
    if sys.platform != "win32" or len(s) < 3 or s[1] != ":":
        return None
    bs = chr(92)
    unc = Path(bs + bs + host + bs + s[0] + "$" + s[2:])
    try:
        return unc if unc.is_file() else None
    except OSError:
        return None


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1"])
def test_t518_unc_path_opens(tmp_path, fresh_cache, host):
    # Path.as_uri() gives file://host/share/..., which sqlite rejects as a URI
    # authority; the f-string form it replaced did open UNC paths.
    db = _make_db(tmp_path / "u#nc" / "x.db")
    unc = _admin_share_path(db, host)
    if unc is None:
        pytest.skip("admin share not reachable on this machine")
    conn = _context.ro_conn(unc)
    assert conn is not None
    assert conn.execute("SELECT x FROM t").fetchone() == (7,)


@pytest.mark.skipif(sys.platform != "win32", reason="drive-letter paths")
def test_t518_drive_path_uri_shape(tmp_path):
    uri = _context._ro_uri(tmp_path / "a b#c" / "x.db")
    assert uri.startswith("file:///")
    assert uri.endswith("/a%20b%23c/x.db?mode=ro")


# -- RM-1959: directory / vanished file raised ---------------------------

def test_t519_directory_at_path_is_none(tmp_path, fresh_cache, caplog):
    d = tmp_path / "dir.db"
    d.mkdir()
    with caplog.at_level("WARNING", logger="rc.web_dashboard"):
        assert _context.ro_conn(d) is None
    # Not a regular file: refused up front, never handed to sqlite.
    assert not [r for r in caplog.records if "cannot open" in r.getMessage()]


def test_t519_file_vanished_before_connect_is_none(tmp_path, fresh_cache,
                                                   monkeypatch):
    db = tmp_path / "gone.db"   # never created: connect() would fail
    monkeypatch.setattr(Path, "is_file", lambda self: True)
    monkeypatch.setattr(Path, "exists", lambda self: True)
    assert _context.ro_conn(db) is None
    assert str(db) not in getattr(_context.DB_CONN_LOCAL, "conns", {})


def test_t519_open_failure_is_logged(tmp_path, fresh_cache, monkeypatch,
                                     caplog):
    db = tmp_path / "gone.db"
    monkeypatch.setattr(Path, "is_file", lambda self: True)
    monkeypatch.setattr(Path, "exists", lambda self: True)
    with caplog.at_level("WARNING", logger="rc.web_dashboard"):
        _context.ro_conn(db)
    assert any("gone.db" in r.getMessage() for r in caplog.records)


# -- RM-1960: a closed cached connection poisoned the thread -------------

def test_t520_closed_cached_connection_is_replaced(tmp_path, fresh_cache):
    db = _make_db(tmp_path / "x.db")
    first = _context.ro_conn(db)
    first.close()
    second = _context.ro_conn(db)
    assert second is not first
    assert second.execute("SELECT x FROM t").fetchone() == (7,)


def test_t520_open_cached_connection_is_kept(tmp_path, fresh_cache):
    db = _make_db(tmp_path / "x.db")
    first = _context.ro_conn(db)
    first.execute("SELECT 1").fetchone()
    assert _context.ro_conn(db) is first


# -- RM-1961: request threads dropped their connections unclosed --------

def test_t521_thread_exit_closes_its_connections(tmp_path, fresh_cache):
    db = _make_db(tmp_path / "x.db")
    held = []

    def request_thread():
        conn = _context.ro_conn(db)
        conn.execute("SELECT x FROM t").fetchone()
        held.append(conn)   # keep the object alive past the thread

    with warnings.catch_warnings(record=True) as rec:
        warnings.simplefilter("always")
        t = threading.Thread(target=request_thread)
        t.start()
        t.join()
        gc.collect()
        # total_changes checks "closed" but not "same thread", so this
        # cannot pass on the cross-thread guard alone.
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            held[0].total_changes  # noqa: B018
        held.clear()
        gc.collect()
    unclosed = [r for r in rec if issubclass(r.category, ResourceWarning)
                and "unclosed database" in str(r.message)]
    assert unclosed == []


def test_t521_cache_still_supports_builder_eviction(tmp_path, fresh_cache):
    # builders.py / builders_home.py / builders_last_match.py evict with
    # getattr(DB_CONN_LOCAL, "conns", {}).pop(str(db_path), None).
    db = _make_db(tmp_path / "x.db")
    first = _context.ro_conn(db)
    popped = getattr(_context.DB_CONN_LOCAL, "conns", {}).pop(str(db), None)
    assert popped is first
    popped.close()
    second = _context.ro_conn(db)
    assert second is not first
    assert second.execute("SELECT x FROM t").fetchone() == (7,)


# -- RM-1962: a UTF-8 BOM read as unreadable ------------------------------

@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(_context, "APP_DIR", tmp_path)
    return tmp_path


def test_t522_bom_json_reads(root):
    (root / "c.json").write_bytes(b"\xef\xbb\xbf" + json.dumps({"a": 1}).encode())
    assert _context.read_json("c.json") == {"a": 1}
    assert _context.read_json_checked("c.json") == ({"a": 1}, True)


def test_t522_bom_only_file_is_empty_not_unreadable(root):
    (root / "c.json").write_bytes(b"\xef\xbb\xbf\r\n")
    assert _context.read_json_checked("c.json") == ({}, True)


def test_t522_invalid_utf8_still_not_ok(root):
    (root / "c.json").write_bytes(b'{"a": "\xff"}')
    assert _context.read_json_checked("c.json") == ({}, False)
    assert _context.read_json("c.json") == {}


# -- RM-1963: deep nesting escaped read_json_checked ---------------------

def test_t523_deeply_nested_json_is_not_ok_and_never_raises(root):
    (root / "c.json").write_bytes(b"[" * 200000 + b"]" * 200000)
    assert _context.read_json_checked("c.json") == ({}, False)
    assert _context.read_json("c.json") == {}


def test_t523_deeply_nested_dict_value_is_not_ok(root):
    (root / "c.json").write_bytes(b'{"a": ' + b"[" * 200000 + b"]" * 200000 + b"}")
    assert _context.read_json_checked("c.json") == ({}, False)


# -- RM-1964: the blind except swallowed caller bugs ---------------------

def test_t524_caller_bug_is_not_swallowed(root):
    with pytest.raises(TypeError):
        _context.read_json(None)


def test_t524_unexpected_error_inside_the_read_surfaces(root, monkeypatch):
    (root / "c.json").write_text("{}", encoding="utf-8")

    def bug(raw):
        raise TypeError("programming error, not a bad file")

    monkeypatch.setattr(_context, "_decode", bug)
    with pytest.raises(TypeError):
        _context.read_json("c.json")


def test_t524_io_error_still_returns_empty(root, monkeypatch):
    (root / "c.json").write_text("{}", encoding="utf-8")

    def boom(self, *a, **k):
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(Path, "read_bytes", boom)
    monkeypatch.setattr(Path, "read_text", boom)
    assert _context.read_json("c.json") == {}
    assert _context.read_json_checked("c.json") == ({}, False)


def test_read_json_non_dict_and_corrupt_are_empty(root):
    (root / "l.json").write_text("[1, 2]", encoding="utf-8")
    (root / "bad.json").write_text("{nope", encoding="utf-8")
    assert _context.read_json("l.json") == {}
    assert _context.read_json("bad.json") == {}
    assert _context.read_json("absent.json") == {}
