"""Shared context for dashboard builders/routes.

Module-level state used by `dashboard.builders` and (later) the
`dashboard.routes_*` handlers. Self-initialising - APP_DIR derives
from this file's location, the per-thread sqlite cache spins up on
first use, no init() required.
"""
import json
import logging
import sqlite3
import threading
from pathlib import Path
from urllib.parse import quote

# dashboard/_context.py is one level under the project root.
APP_DIR: Path = Path(__file__).resolve().parent.parent

# Shared with web_dashboard.py for log-filter continuity.
log = logging.getLogger("rc.web_dashboard")


class _ThreadConnCache(dict):
    """One thread's {str(db_path): read-only sqlite3.Connection} map.

    A plain dict so the builders' eviction idiom
    `getattr(DB_CONN_LOCAL, "conns", {}).pop(str(db_path), None)` keeps
    working. It CLOSES every connection it still holds when it is released,
    which happens when its thread ends (threading.local drops the thread's
    attributes then). dashboard/server.py runs ONE thread per request
    (RM-738 `_GuardedThreadStartMixin`), so without this every request
    thread left its connections for the garbage collector - a file handle
    held past the request plus a ResourceWarning "unclosed database" each
    (RM-1961).
    """

    def __del__(self) -> None:
        for conn in list(self.values()):
            try:
                conn.close()
            # A finalizer must not raise: at interpreter shutdown module
            # globals (sqlite3 itself) may already be torn down, and a
            # cross-thread close raises sqlite3.ProgrammingError; either way
            # the connection's own dealloc still closes it.
            except Exception:  # noqa: BLE001, S110
                pass


# Per-thread read-only sqlite connection cache. dashboard/server.py starts
# one thread per request, so for an ordinary request this saves repeat
# connects WITHIN that request (several builders read the same DB); the
# long-lived SSE stream threads (/api/state-stream, /api/events) reuse one
# connection for their whole life. Each conn is pinned to its owning thread
# (sqlite3 default) and closed when the thread ends (_ThreadConnCache).
# Safe because: (a) all consumers use mode=ro, (b) the DBs are append-only -
# writers add rows without rename/replace, so cached RO conns see new rows
# on subsequent queries. Note an open handle blocks deleting or replacing
# the DB file on Windows (WinError 32, measured), which is one more reason
# connections must not outlive their thread.
DB_CONN_LOCAL = threading.local()


def _is_open(conn: sqlite3.Connection) -> bool:
    """False once any caller closed the shared connection (RM-1960)."""
    try:
        conn.total_changes  # noqa: B018 - raises ProgrammingError when closed
    except sqlite3.ProgrammingError:
        return False
    return True


def _ro_uri(db_path: Path) -> str:
    """Percent-encoded read-only sqlite URI for db_path (RM-1958).

    Not Path.as_uri(): for a UNC path that yields file://host/share/...,
    which sqlite reads as a URI AUTHORITY ("invalid uri authority", or
    "unable to open" for localhost - measured), while the four-slash form
    file:////host/share/... opens. A drive path gives file:///<drive>:/....
    """
    posix = db_path.resolve().as_posix()
    quoted = quote(posix, safe="/:")
    if not quoted.startswith("/"):
        quoted = "/" + quoted
    return f"file://{quoted}?mode=ro"


def ro_conn(db_path: Path) -> sqlite3.Connection | None:
    """Per-thread read-only sqlite connection for db_path, opened
    lazily on first call per thread and reused thereafter. Returns
    None if the DB file is missing, is not a regular file, or cannot be
    opened (logged) - the caller decides the fallback.

    The URI is percent-encoded (_ro_uri): an f-string "file:{path}" let a
    '#' truncate the path (a different file opened) and a '%41' decode
    (RM-1958). A connection a caller closed is
    replaced rather than handed back (RM-1960)."""
    if not db_path.is_file():
        return None
    cache = getattr(DB_CONN_LOCAL, "conns", None)
    if not isinstance(cache, _ThreadConnCache):
        cache = _ThreadConnCache(cache or {})
        DB_CONN_LOCAL.conns = cache
    key = str(db_path)
    conn = cache.get(key)
    if conn is not None and not _is_open(conn):
        cache.pop(key, None)
        conn = None
    if conn is None:
        try:
            conn = sqlite3.connect(_ro_uri(db_path), uri=True)
        except sqlite3.Error as exc:
            # The file vanished after is_file(), or is locked / unreadable
            # (RM-1959). The builders call ro_conn outside their try.
            log.warning("ro_conn %s: cannot open (%s: %s)", db_path,
                        type(exc).__name__, exc)
            return None
        cache[key] = conn
    return conn


def _decode(raw: bytes) -> str:
    """UTF-8 with an optional BOM (PowerShell 5.1 / older Notepad write one).

    A BOM made json.loads fail, so read_json returned {} and
    read_json_checked said "unreadable" forever (RM-1962).
    """
    return raw.decode("utf-8-sig")


def read_json(rel: str) -> dict:
    # 2026-04-27 audit: guarantee dict return. If the file is empty,
    # contains a list/string/null, or hits a JSON error, callers get
    # {} rather than a value that crashes downstream .get() chains.
    # RM-1964: only the I/O, decode and nesting errors are caught; a
    # caller bug (a rel that is not a path) raises instead of reading as {}.
    p = APP_DIR / rel
    try:
        if p.exists():
            d = json.loads(_decode(p.read_bytes()))
            if isinstance(d, dict):
                return d
            log.debug("read %s: not a dict (%s)", rel, type(d).__name__)
    except (OSError, ValueError, RecursionError) as exc:
        log.debug("read %s: %s", rel, exc)
    return {}


def read_json_checked(rel: str) -> tuple[dict, bool]:
    """Like `read_json`, but says whether the read can be TRUSTED (RM-278).

    `read_json` returns {} on every failure, so a read-modify-write caller
    cannot tell "nothing there yet" from "could not read it" and writes {}
    back over a good file. Returns (data, ok):
      - absent file, or an empty / whitespace-only file (a lone BOM counts
        as empty) -> ({}, True): a first-run write must still land;
      - unreadable (I/O error, e.g. the measured WinError 5 / ENOENT window
        against a concurrent replace - so a FileNotFoundError AFTER the
        existence check stays not-ok), undecodable bytes, invalid JSON,
        JSON nested past the recursion limit (RM-1963), or non-dict
        content -> ({}, False);
      - a dict -> (dict, True).
    `read_json` is deliberately left alone for its many read-only callers.
    """
    p = APP_DIR / rel
    try:
        if not p.exists():
            return {}, True
        raw = _decode(p.read_bytes())
    except (OSError, ValueError) as exc:
        log.warning("read %s: unreadable (%s: %s)", rel, type(exc).__name__, exc)
        return {}, False
    if not raw.strip():
        return {}, True
    try:
        d = json.loads(raw)
    except (ValueError, RecursionError) as exc:
        log.warning("read %s: invalid JSON (%s: %s)", rel,
                    type(exc).__name__, exc)
        return {}, False
    if not isinstance(d, dict):
        log.warning("read %s: not a dict (%s)", rel, type(d).__name__)
        return {}, False
    return d, True
