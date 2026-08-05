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

SIZE POLICY (RM-153, decided 2026-08-04): OBSERVE BY DEFAULT, EVICT ON DEMAND.
`cache_immutable` never expires BY DESIGN, so this file grows without bound -
measured 3,353,591,808 bytes / 12,561 rows, `freelist_count = 0`, so it is all
live payload and a VACUUM reclaims nothing. The two halves are deliberately
asymmetric:

  Observability is DEFAULT-ON. `stats_fast()` feeds the `/metrics` gauges in
  `dashboard/routes_metrics.py`, so the size is reported on every scrape with
  an over-cap alarm at DEFAULT_MAX_IMMUTABLE_BYTES. Before this, nothing
  anywhere surfaced the number and the DB reached 3.3 GB unnoticed.

  Eviction is DEFAULT-OFF and opt-in. `evict_to_cap` refuses to delete
  anything without EVICT_CONFIRM_TOKEN, and nothing in RC calls it (pinned by
  a grep guard in tests/test_riot_api_cache_eviction.py). This is not
  timidity - it is the measured finding. RM-153 supposed `rewind_history.db`
  and the `.rofl` archive might already hold this data, making the cache a
  redundant second copy. Measured on the live tree 2026-08-04, that is FALSE:
  of 3123 cached timelines only 117 (3.75 pct) are in `rewind_history.db` and
  only 316 (10.12 pct) have a `.rofl`, leaving 2698 (86.39 pct) in NEITHER.
  Nor does a `.rofl` substitute: `core/rofl_archive.py:611 extract_stats`
  does parse the replay's own trailing Layer-1 blob, but that blob is a final
  scoreboard (10 players x ~367 end-of-game fields) with no time series, and
  a timeline is per-minute frames plus events. The two stores are near-
  disjoint populations. Evicting therefore destroys the only local copy of
  86 pct of the timeline mass, recoverable only by re-fetching against the
  rate limit - and not at all once Riot ages a match out, or for the event
  modes whose Match-V5 route already 403s.

Never put `stats()` on a request path. Measured on the live DB, three runs:
its `SUM(LENGTH(response_json))` takes 4.36-4.59s because it reads every
payload (8.37s cold), against 0.0004-0.0009s for the covering-index counts in
`stats_fast()`.
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

# -- size policy (RM-153) -------------------------------------------------

# Shared with core/data_retention.DEFAULT_MAX_CACHE_BYTES - one number, two
# modules, pinned equal by a test. That module alarms on the same threshold.
DEFAULT_MAX_IMMUTABLE_BYTES = 2 * 1024**3

# The only string evict_to_cap() accepts as authorization. Same shape as
# core/data_retention.CONFIRM_TOKEN: the policy has an enforcement arm, and
# that arm stays inert unless someone deliberately opens it.
EVICT_CONFIRM_TOKEN = "yes-evict-immutable-rows"

# Eviction preference, most-expendable first. Timelines lead because they are
# the mass: measured 2026-08-04, 3123 timeline rows hold 2.53 GB (810 KB each,
# 76 pct of the file) against 9324 match details at 86 KB each. Freeing a
# gigabyte costs ~1200 timelines or ~12000 details, so evicting timelines
# first loses the fewest matches per byte reclaimed.
_EVICT_ORDER = ("match:v5:timeline:", "match:v5:")

# Account-V1 rows are never candidates. They are 114 rows / 15 KB total on the
# live DB, so there is no space to win, and re-resolving a PUUID costs a
# rate-limited round trip. They are also keyed by an API-key fingerprint, so a
# stale one is already inert rather than wrong.
_NEVER_EVICT = ("account:v1:",)

# SQLite WAL sidecars are part of the database (RM-153 Windows trap): a size
# reading that ignores them under-reports whatever is still unflushed.
_DB_SIDECAR_SUFFIXES = ("-wal", "-shm")

# Keys per DELETE. Each chunk is one statement, which SQLite executes
# atomically on its own - the same single-statement pattern the writes use,
# so eviction needs no explicit transaction either.
_EVICT_CHUNK = 500


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

    # -- size policy (RM-153) --------------------------------------------

    def disk_bytes(self) -> int:
        """Total bytes this database occupies, sidecars included.

        Cheap by construction - three `stat()` calls, no connection. This is
        what `/metrics` reads on every scrape. The `-wal` and `-shm` files ARE
        the database under `journal_mode=WAL`, so a reading that counts only
        the `.db` under-reports the real disk cost.
        """
        total = 0
        for suffix in ("",) + _DB_SIDECAR_SUFFIXES:
            try:
                total += self._db_path.with_name(
                    self._db_path.name + suffix).stat().st_size
            except OSError:
                pass
        return total

    def stats_fast(self) -> dict:
        """Counters cheap enough for a request path. NO payload byte sum.

        `stats()` is correct but unusable here: its
        `SUM(LENGTH(response_json))` reads every payload and was measured at
        4.36-4.59s warm on the live 3.3 GB DB and 8.37s cold, which would be
        added to every Prometheus scrape. The counts below ride covering
        indexes at under a millisecond, and `disk_bytes()` is a bare stat, so
        the size alarm costs nothing.
        """
        out = {"immutable_rows": 0, "ttl_live_rows": 0,
               "db_file_bytes": 0, "disk_bytes": self.disk_bytes()}
        try:
            out["db_file_bytes"] = self._db_path.stat().st_size
        except OSError:
            pass
        try:
            conn = self._connect()
            try:
                self._ensure_schema(conn)
                out["immutable_rows"] = int(conn.execute(
                    "SELECT COUNT(*) FROM cache_immutable").fetchone()[0])
                out["ttl_live_rows"] = int(conn.execute(
                    "SELECT COUNT(*) FROM cache_ttl WHERE expires_at > ?",
                    (int(time.time()),)).fetchone()[0])
                return out
            finally:
                conn.close()
        except (sqlite3.Error, OSError) as exc:
            self._heal_if_schema_vanished(exc)
            log.debug("cache.stats_fast failed: %s", exc)
            return out

    def plan_eviction(
        self,
        max_bytes: int = DEFAULT_MAX_IMMUTABLE_BYTES,
    ) -> dict:
        """Which immutable rows WOULD be dropped to get under `max_bytes`.

        READ-ONLY - names victims and deletes nothing. Oldest `fetched_at`
        first within each class of `_EVICT_ORDER`, with the key as a
        tiebreaker because `fetched_at` has one-second resolution and a
        fan-out writes many rows inside the same second.

        `max_bytes` here means SUMMED PAYLOAD BYTES, which is not what the
        `rc_riot_api_cache_over_cap` gauge measures - that one compares the
        same default constant against `disk_bytes()` (file plus WAL sidecars).
        Disk is always the larger of the two, so the gauge can read 1 while
        this planner still reports `over_cap: False`. That is intended, not a
        drift: the alarm is allowed to lead, and making them agree would put
        the multi-second payload scan on the scrape path. Documented at the
        gauge too, in `dashboard/routes_metrics.py`.
        """
        max_bytes = max(0, int(max_bytes))
        out: dict = {"over_cap": False, "current_bytes": 0,
                     "max_bytes": max_bytes, "keys": [], "bytes_freed": 0}
        try:
            conn = self._connect()
            try:
                self._ensure_schema(conn)
                total = int(conn.execute(
                    "SELECT COALESCE(SUM(LENGTH(response_json)), 0) "
                    "FROM cache_immutable").fetchone()[0])
                out["current_bytes"] = total
                if total <= max_bytes:
                    return out
                out["over_cap"] = True

                need = total - max_bytes
                freed = 0
                chosen: list[str] = []
                seen: set[str] = set()
                for prefix in _EVICT_ORDER:
                    if freed >= need:
                        break
                    # substr() rather than LIKE: match ids carry underscores
                    # ("NA1_5585328637") and LIKE would read them as its
                    # single-character wildcard.
                    rows = conn.execute(
                        "SELECT key, LENGTH(response_json) "
                        "FROM cache_immutable WHERE substr(key, 1, ?) = ? "
                        "ORDER BY fetched_at ASC, key ASC",
                        (len(prefix), prefix),
                    ).fetchall()
                    for key, size in rows:
                        if freed >= need:
                            break
                        # A later prefix can re-match an earlier one's rows
                        # ("match:v5:" also matches every timeline key).
                        if key in seen or key.startswith(_NEVER_EVICT):
                            continue
                        seen.add(key)
                        chosen.append(key)
                        freed += int(size or 0)
                out["keys"] = chosen
                out["bytes_freed"] = freed
                return out
            finally:
                conn.close()
        except (sqlite3.Error, OSError) as exc:
            self._heal_if_schema_vanished(exc)
            log.warning("cache.plan_eviction failed: %s", exc)
            return out

    def evict_to_cap(
        self,
        max_bytes: int = DEFAULT_MAX_IMMUTABLE_BYTES,
        *,
        confirm: Optional[str] = None,
    ) -> dict:
        """Enforcement arm for the size cap. OPT-IN - inert without a token.

        This is the destructive half of RM-153 and it is deliberately not the
        default. The row's premise that this data is a redundant second copy
        of `rewind_history.db` / the `.rofl` archive was MEASURED FALSE (see
        the module docstring), so an evicted timeline is usually the only
        local copy and comes back only via a rate-limited re-fetch. Deleting
        the operator's match history unprompted is worse than the unbounded
        growth it would fix.

        The immutable contract survives eviction: an evicted key reads as a
        clean MISS, so `cached_get` re-fetches and re-caches it exactly.
        Nothing is ever rewritten in place, so a surviving row cannot change.

        Returns a result dict and never raises. Note `vacuum_required`:
        deleting rows moves pages to the freelist but does NOT shrink the
        file, so the disk is only returned to the OS by a subsequent VACUUM,
        which needs free space equal to the DB and is left to the operator.
        """
        plan = self.plan_eviction(max_bytes)
        result = dict(plan)
        result.update(applied=False, deleted=0,
                      vacuum_required=False, errors=[])

        if confirm != EVICT_CONFIRM_TOKEN:
            return result
        result["applied"] = True
        keys = plan["keys"]
        if not keys:
            return result

        try:
            with self._lock:
                conn = self._connect()
                try:
                    self._ensure_schema(conn)
                    deleted = 0
                    for i in range(0, len(keys), _EVICT_CHUNK):
                        chunk = keys[i:i + _EVICT_CHUNK]
                        marks = ",".join("?" * len(chunk))
                        cur = conn.execute(
                            "DELETE FROM cache_immutable "
                            f"WHERE key IN ({marks})", chunk)
                        deleted += cur.rowcount or 0
                    result["deleted"] = deleted
                    result["vacuum_required"] = deleted > 0
                    log.warning(
                        "cache eviction: dropped %d immutable row(s), ~%d "
                        "bytes of payload; VACUUM required to return the "
                        "space to the OS", deleted, plan["bytes_freed"])
                    return result
                finally:
                    conn.close()
        except (sqlite3.Error, OSError) as exc:
            self._heal_if_schema_vanished(exc)
            log.warning("cache.evict_to_cap failed: %s", exc)
            result["errors"].append(str(exc))
            return result


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
