# arch: SQLite cache for core/riot_api.py | section=core | frozen=no
"""SQLite persistence layer for `core/riot_api.py` - FU02 fan-out backing.

Two tables, one SQLite file at `data/riot_api_cache.db`:

  cache_immutable(key TEXT PK, response_json TEXT, fetched_at INTEGER)
    Match-V5 detail + Match-V5 timeline + Account-V1 PUUID lookups.
    These rows never expire - Riot match data is historical record and
    Account PUUIDs are stable. Once cached, no need to re-fetch.

  cache_ttl(key TEXT PK, response_json TEXT, fetched_at INTEGER, expires_at INTEGER)
    League-V4 ranks (300s) + Champion-Mastery-V4 (300s). The 300s TTL
    is short enough that a champ-select fan-out kicked off twice in a
    minute hits cache the second time, but long enough that a single
    operator cycling lobbies sees fresh ranks every game.

Concurrency: the connection is opened per-call with `check_same_thread=False`
in AUTOCOMMIT mode (`isolation_level=None`). There is no explicit transaction
- an earlier version of this docstring described an immediate-mode one that
the code has never opened (lane 8 audit, 2026-08-03). It needs none: every
write is a single-statement `INSERT OR REPLACE`, which SQLite executes
atomically on its own, and writes are additionally serialized through the
instance lock. Reads take no lock; WAL keeps them from blocking the writer.

Soft-fail invariants:
  - Any DB error is caught + logged at WARNING; callers get None back
    so the rate limiter / fan-out treats the cache as cold.
  - File creation is lazy - first call to `get` or `set` opens the
    connection, runs the schema, and commits. No bootstrapping needed.
  - If the DB FILE disappears under a running process, the next call
    soft-fails and clears the schema flag, so the call after that rebuilds
    the schema. See `_heal_if_schema_vanished` - before that existed, the
    cache became a permanent no-op for the process lifetime.

SIZE: `cache_immutable` never expires BY DESIGN, so this file grows without
bound - measured at 3.33 GB / 12,305 rows on 2026-08-03, all live data. There
is no cap and no eviction; an eviction policy is filed as RM-153. `stats()`
reports bytes as well as rows so the growth is at least observable.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("rc.riot_api_cache")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_DB_PATH = _PROJECT_ROOT / "data" / "riot_api_cache.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cache_immutable (
    key           TEXT PRIMARY KEY,
    response_json TEXT NOT NULL,
    fetched_at    INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS cache_ttl (
    key           TEXT PRIMARY KEY,
    response_json TEXT NOT NULL,
    fetched_at    INTEGER NOT NULL,
    expires_at    INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ttl_expiry ON cache_ttl(expires_at);
"""


class RiotApiCache:
    """SQLite-backed cache for Riot API responses.

    Singleton-friendly: most callers should use `get_cache()` to share
    a single instance across the dashboard process. Tests can construct
    fresh instances with explicit DB paths for isolation.
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self._db_path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        # Re-entrant: set_immutable/set_ttl take it for write serialization
        # and call _ensure_schema underneath, which also takes it.
        self._lock = threading.RLock()
        self._initialized = False

    def _connect(self) -> sqlite3.Connection:
        # Ensure parent directory exists (tests may use temp paths).
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            str(self._db_path),
            timeout=5.0,
            check_same_thread=False,
            isolation_level=None,   # autocommit; we manage TX explicitly
        )
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            conn.executescript(_SCHEMA)
            self._initialized = True

    def _heal_if_schema_vanished(self, exc: BaseException) -> None:
        """Clear the init flag when the error says our tables are gone.

        ``_initialized`` is PROCESS state, not FILE state. If the DB file goes
        away under a long-lived process - rotation, a cleanup pass, disk
        trouble - SQLite recreates an EMPTY file on the next connect, and
        because the flag is still True the schema is never re-run. Every
        operation then fails "no such table", gets caught, logs a WARNING and
        returns None/False, which callers cannot distinguish from a cache
        miss. RC re-fetches from the Riot API forever, burning rate limit,
        until the process restarts. Measured before this fix: set -> False and
        get -> None permanently, with ``_initialized`` still True.

        Clearing the flag here costs the CALL that noticed (it still soft-
        fails, which is the established contract) and lets the very next call
        rebuild the schema. A same-call retry was considered and rejected as
        more control flow than the failure justifies - the caller's next
        attempt heals it, and pretending a lost write succeeded would be
        worse than reporting it.
        """
        if isinstance(exc, sqlite3.OperationalError) and \
                "no such table" in str(exc).lower():
            with self._lock:
                self._initialized = False

    # -- immutable cache (Match-V5 details/timeline, Account-V1) ---------

    def get_immutable(self, key: str) -> Optional[dict]:
        try:
            conn = self._connect()
            try:
                self._ensure_schema(conn)
                row = conn.execute(
                    "SELECT response_json FROM cache_immutable WHERE key = ?",
                    (key,),
                ).fetchone()
                if row is None:
                    return None
                return json.loads(row[0])
            finally:
                conn.close()
        except (sqlite3.Error, OSError, ValueError) as exc:
            self._heal_if_schema_vanished(exc)
            log.warning("cache.get_immutable(%s) failed: %s", key, exc)
            return None

    def set_immutable(self, key: str, response: dict) -> bool:
        # Serialize writes via the instance lock - SQLite WAL + per-call
        # connections + tight thread contention can produce "database is
        # locked" errors on Windows even under busy_timeout. The cache
        # is low-traffic (capped by the API rate limiter), so giving up
        # write parallelism is essentially free.
        try:
            payload = json.dumps(response, ensure_ascii=False)
            now = int(time.time())
            with self._lock:
                conn = self._connect()
                try:
                    self._ensure_schema(conn)
                    conn.execute(
                        "INSERT OR REPLACE INTO cache_immutable "
                        "(key, response_json, fetched_at) VALUES (?, ?, ?)",
                        (key, payload, now),
                    )
                    return True
                finally:
                    conn.close()
        except (sqlite3.Error, OSError, TypeError, ValueError) as exc:
            self._heal_if_schema_vanished(exc)
            log.warning("cache.set_immutable(%s) failed: %s", key, exc)
            return False

    # -- TTL cache (League-V4, Champion-Mastery-V4) -----------------------

    def get_ttl(self, key: str) -> Optional[dict]:
        try:
            now = int(time.time())
            conn = self._connect()
            try:
                self._ensure_schema(conn)
                row = conn.execute(
                    "SELECT response_json, expires_at FROM cache_ttl "
                    "WHERE key = ?",
                    (key,),
                ).fetchone()
                if row is None:
                    return None
                response_json, expires_at = row
                if expires_at <= now:
                    return None
                return json.loads(response_json)
            finally:
                conn.close()
        except (sqlite3.Error, OSError, ValueError) as exc:
            self._heal_if_schema_vanished(exc)
            log.warning("cache.get_ttl(%s) failed: %s", key, exc)
            return None

    def set_ttl(self, key: str, response: dict, ttl_s: int) -> bool:
        try:
            payload = json.dumps(response, ensure_ascii=False)
            now = int(time.time())
            expires_at = now + max(0, int(ttl_s))
            with self._lock:
                conn = self._connect()
                try:
                    self._ensure_schema(conn)
                    conn.execute(
                        "INSERT OR REPLACE INTO cache_ttl "
                        "(key, response_json, fetched_at, expires_at) "
                        "VALUES (?, ?, ?, ?)",
                        (key, payload, now, expires_at),
                    )
                    return True
                finally:
                    conn.close()
        except (sqlite3.Error, OSError, TypeError, ValueError) as exc:
            self._heal_if_schema_vanished(exc)
            log.warning("cache.set_ttl(%s) failed: %s", key, exc)
            return False

    # -- housekeeping -----------------------------------------------------

    def purge_expired_ttl(self) -> int:
        """Drop expired TTL rows. Returns count purged.

        NOTE (lane 8, 2026-08-03): this has no PRODUCTION callers - only
        tests call it. The previous docstring named a caller inside the
        rate-limit prune; no such caller exists. Kept because it is
        correct and cheap, and because expired rows otherwise accumulate
        forever - it is simply not required for correctness, since get_ttl()
        filters on expires_at. Wire it or drop it deliberately; do not
        re-add a claim that something calls it."""
        try:
            now = int(time.time())
            conn = self._connect()
            try:
                self._ensure_schema(conn)
                cur = conn.execute(
                    "DELETE FROM cache_ttl WHERE expires_at <= ?", (now,)
                )
                return cur.rowcount or 0
            finally:
                conn.close()
        except (sqlite3.Error, OSError) as exc:
            self._heal_if_schema_vanished(exc)
            log.debug("cache.purge_expired_ttl failed: %s", exc)
            return 0

    def stats(self) -> dict:
        """Read-only counters. No PRODUCTION callers as of 2026-08-03 (lane
        8) - only tests call it.

        The previous docstring named a dashboard metrics consumer; no such
        consumer exists. It also reported ROW COUNTS only, which is
        the wrong dimension for this cache: `cache_immutable` never expires,
        and the live DB reached 3.33 GB across 12,305 rows with nothing
        anywhere surfacing that. `immutable_bytes` and `db_file_bytes` are
        reported so a future consumer can see growth, not just cardinality.
        The row keys are preserved for any caller that appears later.
        """
        out = {"immutable_rows": 0, "ttl_live_rows": 0,
               "immutable_bytes": 0, "db_file_bytes": 0}
        try:
            out["db_file_bytes"] = self._db_path.stat().st_size
        except OSError:
            pass
        try:
            conn = self._connect()
            try:
                self._ensure_schema(conn)
                imm, imm_bytes = conn.execute(
                    "SELECT COUNT(*), COALESCE(SUM(LENGTH(response_json)), 0) "
                    "FROM cache_immutable"
                ).fetchone()
                ttl = conn.execute(
                    "SELECT COUNT(*) FROM cache_ttl WHERE expires_at > ?",
                    (int(time.time()),),
                ).fetchone()[0]
                out.update(immutable_rows=int(imm), ttl_live_rows=int(ttl),
                           immutable_bytes=int(imm_bytes))
                return out
            finally:
                conn.close()
        except (sqlite3.Error, OSError) as exc:
            self._heal_if_schema_vanished(exc)
            log.debug("cache.stats failed: %s", exc)
            return out


# -- module-level singleton ----------------------------------------------

_SINGLETON: Optional[RiotApiCache] = None
_SINGLETON_LOCK = threading.Lock()


def get_cache() -> RiotApiCache:
    """Return the shared cache instance. Lazy-initialised on first call."""
    global _SINGLETON
    if _SINGLETON is not None:
        return _SINGLETON
    with _SINGLETON_LOCK:
        if _SINGLETON is None:
            _SINGLETON = RiotApiCache()
        return _SINGLETON


def _reset_for_tests(db_path: Optional[Path] = None) -> RiotApiCache:
    """Test helper - replace the singleton with a fresh instance."""
    global _SINGLETON
    with _SINGLETON_LOCK:
        _SINGLETON = RiotApiCache(db_path=db_path)
        return _SINGLETON


# Convenience re-exports for callers that prefer module-level fns.

def get_immutable(key: str) -> Optional[dict]:
    return get_cache().get_immutable(key)


def set_immutable(key: str, response: dict) -> bool:
    return get_cache().set_immutable(key, response)


def get_ttl(key: str) -> Optional[dict]:
    return get_cache().get_ttl(key)


def set_ttl(key: str, response: dict, ttl_s: int) -> bool:
    return get_cache().set_ttl(key, response, ttl_s)


def cached_get(
    key: str,
    fetch_fn: Any,
    ttl_s: Optional[int] = None,
) -> Optional[dict]:
    """Cache-aware fetch. If `ttl_s` is None, uses the immutable cache
    (no expiry). Otherwise uses the TTL cache with `ttl_s` seconds.

    `fetch_fn` is called only on cache miss; it must return `dict | None`.
    A None return from fetch_fn is NOT cached (transient errors retry on
    the next call rather than poisoning the cache with empty rows).
    """
    cache = get_cache()
    if ttl_s is None:
        cached = cache.get_immutable(key)
    else:
        cached = cache.get_ttl(key)
    if cached is not None:
        return cached
    fresh = fetch_fn()
    if fresh is None:
        return None
    if ttl_s is None:
        cache.set_immutable(key, fresh)
    else:
        cache.set_ttl(key, fresh, ttl_s)
    return fresh
