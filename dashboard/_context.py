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

# dashboard/_context.py is one level under the project root.
APP_DIR: Path = Path(__file__).resolve().parent.parent

# Shared with web_dashboard.py for log-filter continuity.
log = logging.getLogger("rc.web_dashboard")


# Per-thread read-only sqlite connection cache. ThreadingHTTPServer
# recycles worker threads, so caching here amortizes sqlite3.connect()
# (which acquires the GIL'd lock, opens the file, parses the schema,
# init's the parser) across every request served by the same thread.
# Each conn is pinned to its owning thread (sqlite3 default).
# Safe because: (a) all consumers use ?mode=ro, (b) the DBs are
# append-only - writers add rows without rename/replace, so cached RO
# conns see new rows on subsequent queries.
DB_CONN_LOCAL = threading.local()


def ro_conn(db_path: Path) -> sqlite3.Connection | None:
    """Per-thread read-only sqlite connection for db_path, opened
    lazily on first call per thread and reused thereafter. Returns
    None if the DB file is missing - caller decides the fallback."""
    if not db_path.exists():
        return None
    cache = getattr(DB_CONN_LOCAL, "conns", None)
    if cache is None:
        cache = {}
        DB_CONN_LOCAL.conns = cache
    key = str(db_path)
    conn = cache.get(key)
    if conn is None:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        cache[key] = conn
    return conn


def read_json(rel: str) -> dict:
    # 2026-04-27 audit: guarantee dict return. If the file is empty,
    # contains a list/string/null, or hits a JSON error, callers get
    # {} rather than a value that crashes downstream .get() chains.
    try:
        p = APP_DIR / rel
        if p.exists():
            d = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(d, dict):
                return d
            log.debug("read %s: not a dict (%s)", rel, type(d).__name__)
    except Exception as exc:
        log.debug("read %s: %s", rel, exc)
    return {}
