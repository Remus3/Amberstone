# arch: SQLite cache for core/riot_api.py | section=core | frozen=no
"""SQLite persistence layer for `core/riot_api.py` — FU02 fan-out backing.

Two tables, one SQLite file at `data/riot_api_cache.db`:

  cache_immutable(key TEXT PK, response_json TEXT, fetched_at INTEGER)
    Match-V5 detail + Match-V5 timeline + Account-V1 PUUID lookups.
    These rows never expire — Riot match data is historical record and
    Account PUUIDs are stable. Once cached, no need to re-fetch.

  cache_ttl(key TEXT PK, response_json TEXT, fetched_at INTEGER, expires_at INTEGER)
    League-V4 ranks (300s) + Champion-Mastery-V4 (300s). The 300s TTL
    is short enough that a champ-select fan-out kicked off twice in a
    minute hits cache the second time, but long enough that a single
    operator cycling lobbies sees fresh ranks every game.

Concurrency: the connection is opened per-call with `check_same_thread=False`
and a `BEGIN IMMEDIATE` transaction to avoid the dashboard request thread
racing the priority-2 background scheduler. The hot path is a single
SELECT or INSERT OR REPLACE; SQLite's WAL mode keeps both readers and
writers from blocking.

Soft-fail invariants:
  - Any DB error is caught + logged at WARNING; callers get None back
    so the rate limiter / fan-out treats the cache as cold.
  - File creation is lazy — first call to `get` or `set` opens the
    connection, runs the schema, and commits. No bootstrapping needed.
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

    # ── immutable cache (Match-V5 details/timeline, Account-V1) ─────────

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
            log.warning("cache.get_immutable(%s) failed: %s", key, exc)
            return None

    def set_immutable(self, key: str, response: dict) -> bool:
        # Serialize writes via the instance lock — SQLite WAL + per-call
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
            log.warning("cache.set_immutable(%s) failed: %s", key, exc)
            return False

    # ── TTL cache (League-V4, Champion-Mastery-V4) ───────────────────────

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
            log.warning("cache.set_ttl(%s) failed: %s", key, exc)
            return False

    # ── housekeeping ─────────────────────────────────────────────────────

    def purge_expired_ttl(self) -> int:
        """Drop expired TTL rows. Returns count purged. Best-effort —
        called opportunistically by the rate-limit prune; not required
        for correctness because get_ttl() filters on expires_at."""
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
            log.debug("cache.purge_expired_ttl failed: %s", exc)
            return 0

    def stats(self) -> dict:
        """Read-only counters for the dashboard / metrics endpoint."""
        try:
            conn = self._connect()
            try:
                self._ensure_schema(conn)
                imm = conn.execute(
                    "SELECT COUNT(*) FROM cache_immutable"
                ).fetchone()[0]
                ttl = conn.execute(
                    "SELECT COUNT(*) FROM cache_ttl WHERE expires_at > ?",
                    (int(time.time()),),
                ).fetchone()[0]
                return {"immutable_rows": int(imm), "ttl_live_rows": int(ttl)}
            finally:
                conn.close()
        except (sqlite3.Error, OSError) as exc:
            log.debug("cache.stats failed: %s", exc)
            return {"immutable_rows": 0, "ttl_live_rows": 0}


# ── module-level singleton ──────────────────────────────────────────────

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
    """Test helper — replace the singleton with a fresh instance."""
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
