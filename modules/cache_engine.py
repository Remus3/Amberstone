"""
cache_engine.py
SQLite decision cache for auto-coaching.
Thread-safe via connection-per-call. WAL mode for concurrent reads.

The cache is an OPTIMISATION in front of a paid Haiku call
(``coach_integration/_coach.py`` reads it before the call and writes it
after), so it never takes the coach down (s144 true-audit cycle 122):

  - A database failure (locked, corrupt, a missing table, an unopenable path)
    is a cache MISS on ``get`` and ``False`` from ``set`` / ``flag_bad``, with
    one WARNING per operation per ``_WARN_WINDOW_S``. Only ``sqlite3.Error``
    and ``OSError`` are absorbed; anything else is a bug and raises.
  - The constructor never raises on a bad database; the schema is re-tried on
    the next operation, so a database that becomes usable heals by itself.
  - Every connection is CLOSED (``with sqlite3.connect()`` only commits).
  - ``make_cache_key`` is total over a dict and keeps the exact digest of
    every WELL-TYPED state (name / id lists, an int / float clock, an int /
    float / None HP and mana, a dict of timers - the shape ``_convert`` builds
    from ``core/game_snapshot``; pinned by test), so no live row is re-keyed.
    Only junk changes key: an input that raised before (a None clock among
    them, now ``"unknown"``), a bool or a
    non-finite number, a non-float number type, or a str / dict where a list
    belongs (which now reads as an empty list, not as its characters or keys).
    A non-finite or non-number HP / mana / clock reads as ``"unknown"``,
    never as ``"critical"`` / ``"oom"`` / ``"late"``.
  - A refresh ``set`` resets ``use_count`` along with ``confidence``: a row
    retired by ``max_use_count`` is re-asked once and then served again,
    instead of costing a Haiku call on every recurrence forever.
  - A NULL or text ``confidence`` / ``use_count`` (SQLite stores a NaN
    product as NULL) is a miss, healed by the next ``set``; a non-finite or
    non-number multiplier is refused before it can write one.
"""

import hashlib
import json
import logging
import math
import os
import sqlite3
import threading
import time
from collections.abc import Mapping
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger("cache")

# RM-812: the ONE default location of the auto-coach decision cache, read at
# CALL time. A non-empty RC_DECISIONS_DB replaces it; the test suite points it
# at tmp_path, so a test that reaches a default-path caller (performance_tracker
# .save_rating -> coaches.feedback.apply_grade, CoachIntegration) leaves the
# live database alone.
DECISIONS_DB_ENV = "RC_DECISIONS_DB"
_DEFAULT_DECISIONS_DB = Path(__file__).resolve().parent.parent / "data" / "decisions.db"


def decisions_db_path() -> Path:
    """data/decisions.db, or a non-empty ``RC_DECISIONS_DB``."""
    override = (os.environ.get(DECISIONS_DB_ENV) or "").strip()
    return Path(override) if override else _DEFAULT_DECISIONS_DB

# RM-413: _conn opens a connection per operation, so the non-wal warning fires
# once per db path per process, not on every call. A set.add race is a
# harmless duplicate line at worst.
_WAL_WARNED: set = set()

# The only failures a cache operation absorbs. Anything else is a bug.
_DB_ERRORS = (sqlite3.Error, OSError)

# One WARNING per operation per window: a locked database at the coach's 2 s
# tick would otherwise write a line every tick.
_WARN_WINDOW_S = 60.0

_SEQUENCES = (list, tuple, set, frozenset)


def _is_num(v) -> bool:
    """A real, finite number. A bool is not one; an int is always finite."""
    if isinstance(v, bool):
        return False
    if isinstance(v, int):
        return True
    return isinstance(v, float) and math.isfinite(v)


def phase_bucket(t):
    if not _is_num(t):
        return "unknown"
    if t < 600:  return "early"
    if t < 1500: return "mid"
    return "late"

def hp_bucket(pct):
    if not _is_num(pct):
        return "unknown"
    if pct > 0.75:     return "full"
    if pct > 0.40:     return "half"
    if pct > 0.20:     return "low"
    return "critical"

def mana_bucket(pct):
    if not _is_num(pct):
        return "unknown"
    if pct > 0.60:     return "high"
    if pct > 0.25:     return "low"
    return "oom"

def obj_window(timers):
    if not isinstance(timers, Mapping) or not timers:
        return "none"
    soonest = None
    for t in timers.values():
        if _is_num(t) and (soonest is None or t < soonest):
            soonest = t
    if soonest is None: return "none"
    if soonest < 30:    return "imminent"
    if soonest < 90:    return "soon"
    return "none"

def items_key(items):
    if not isinstance(items, _SEQUENCES) or not items:
        return "none"
    return "|".join(sorted(str(i) for i in items))


def _sort_token(v) -> str:
    """Total order for a list sorted() cannot order (mixed or unorderable)."""
    try:
        body = json.dumps(v, sort_keys=True, default=str)
    except (TypeError, ValueError):
        body = repr(v)
    return f"{type(v).__name__}:{body}"


def _sorted_names(v) -> list:
    """sorted(v) for a list of names, exactly as before; [] for a non-list,
    and a deterministic order for a list sorted() rejects."""
    if not isinstance(v, _SEQUENCES):
        return []
    try:
        return sorted(v)
    except TypeError:
        return sorted(v, key=_sort_token)


def _patch(state) -> str:
    """The patch label a row is stored and compared under."""
    v = state.get("patch_version", "")
    if v is None:
        return ""
    return v if isinstance(v, str) else str(v)


def make_cache_key(state):
    lane = state.get("lane_matchup", {})
    key_data = {
        "champion":       state.get("champion", ""),
        "ally_comp":      _sorted_names(state.get("ally_comp", [])),    # CRITICAL: different allies = different advice
        "enemy_adc":      lane.get("enemy_adc", "") if isinstance(lane, Mapping) else "",
        "game_phase":     phase_bucket(state.get("game_time_s", 0)),
        "wave_state":     state.get("wave_state", "unknown"),
        "hp_bucket":      hp_bucket(state.get("my_hp_pct")),
        "mana_bucket":    mana_bucket(state.get("my_mana_pct")),
        "items_key":      items_key(state.get("my_items", [])),
        "obj_window":     obj_window(state.get("objective_timers", {})),
        "nearby_enemies": _sorted_names(state.get("nearby_enemies", [])),
        "patch_version":  state.get("patch_version", ""),
    }
    try:
        raw = json.dumps(key_data, sort_keys=True, default=str)
    except (TypeError, ValueError):
        # A nested dict with mixed key types, or a self-referencing list.
        raw = repr(sorted((k, repr(v)) for k, v in key_data.items()))
    return hashlib.sha256(raw.encode("utf-8", "backslashreplace")).hexdigest()[:20]


class CacheEngine:
    def __init__(self, db_path, confidence_threshold=0.6, max_use_count=50):
        self.db_path = Path(db_path)
        self.confidence_threshold = confidence_threshold
        self.max_use_count = max_use_count
        self._schema_ready = False
        self._warned_at: dict = {}
        self._warn_lock = threading.Lock()
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._warn("init", exc)
        self._init_db()

    def _warn(self, op, exc):
        now = time.monotonic()
        with self._warn_lock:
            last = self._warned_at.get(op)
            if last is not None and now - last < _WARN_WINDOW_S:
                return
            self._warned_at[op] = now
        logger.warning(
            "CacheEngine.%s failed (%s: %s) on %s - treated as a cache miss",
            op, type(exc).__name__, exc, self.db_path)

    def _conn(self):
        conn = sqlite3.connect(str(self.db_path), timeout=5.0)
        try:
            # RM-413 (RM-233 shape): read the adopted mode; warn, never raise.
            jm_row = conn.execute("PRAGMA journal_mode=WAL").fetchone()
        except BaseException:
            conn.close()
            raise
        journal_mode = str(jm_row[0]).lower() if jm_row else "unknown"
        if journal_mode != "wal" and str(self.db_path) not in _WAL_WARNED:
            _WAL_WARNED.add(str(self.db_path))
            logger.warning(
                "CacheEngine journal_mode fell back to %r (wanted wal): %s - "
                "concurrent readers WILL block writers on this database",
                journal_mode, self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _session(self):
        """One transaction on one connection, always closed."""
        conn = self._conn()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _create_schema(self):
        with self._session() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS decisions (
                    cache_key TEXT PRIMARY KEY, champion TEXT,
                    patch_version TEXT, game_state_json TEXT,
                    response TEXT, confidence REAL DEFAULT 1.0,
                    use_count INTEGER DEFAULT 0,
                    created_at INTEGER, last_used INTEGER
                );
                CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    cache_key TEXT, flag TEXT, flagged_at INTEGER
                );
                CREATE INDEX IF NOT EXISTS idx_champ ON decisions(champion, patch_version);
            """)
        self._schema_ready = True

    def _init_db(self):
        try:
            self._create_schema()
        except _DB_ERRORS as exc:
            self._schema_ready = False
            self._warn("init", exc)

    def _ensure_schema(self):
        if not self._schema_ready:
            self._create_schema()

    def get(self, state):
        # Single connection across SELECT + UPDATE so the use_count++ is
        # in the same transaction as the read, avoiding a race where
        # flag_bad() could DELETE the row between our two queries (which
        # made the UPDATE silently no-op). Also halves the per-hit
        # connection-open overhead (~1ms each).
        if not isinstance(state, Mapping):
            return None
        key = make_cache_key(state)
        hit = None
        try:
            self._ensure_schema()
            with self._session() as conn:
                row = conn.execute(
                    "SELECT response, confidence, use_count, patch_version "
                    "FROM decisions WHERE cache_key=?", (key,)
                ).fetchone()
                if row is None: return None
                if row["patch_version"] != _patch(state): return None
                response = row["response"]
                confidence = row["confidence"]
                uses = row["use_count"]
                if not isinstance(response, str) or not response: return None
                if not _is_num(confidence) or confidence < self.confidence_threshold:
                    return None
                if not _is_num(uses) or uses >= self.max_use_count: return None
                hit = response
                conn.execute("UPDATE decisions SET use_count=use_count+1, last_used=? WHERE cache_key=?",
                             (int(time.time()), key))
        except _DB_ERRORS as exc:
            self._schema_ready = False
            self._warn("get", exc)
            # A row already read is still a valid answer; only the counter
            # bump was lost (e.g. a writer held the lock past the timeout).
            return hit
        logger.debug("Cache HIT key=%s", key[:8])
        return hit

    def set(self, state, response):
        # game_state_json column is preserved for schema back-compat but
        # written empty - a grep across the codebase confirms it's never
        # read by get() or any analyzer. Saves a few KB per cache row at
        # scale.
        if not isinstance(state, Mapping):
            return False
        if not isinstance(response, str) or not response.strip():
            return False
        key = make_cache_key(state)
        now = int(time.time())
        champion = state.get("champion", "")
        champion = "" if champion is None else str(champion)
        try:
            self._ensure_schema()
            with self._session() as conn:
                conn.execute("""
                    INSERT INTO decisions (cache_key,champion,patch_version,game_state_json,
                        response,confidence,use_count,created_at,last_used)
                    VALUES (?,?,?,?,?,1.0,0,?,?)
                    ON CONFLICT(cache_key) DO UPDATE SET
                        response=excluded.response, confidence=1.0, use_count=0,
                        patch_version=excluded.patch_version, last_used=excluded.last_used
                """, (key, champion, _patch(state), "", response, now, now))
        except _DB_ERRORS as exc:
            self._schema_ready = False
            self._warn("set", exc)
            return False
        return True

    def flag_bad(self, state):
        if not isinstance(state, Mapping):
            return False
        key = make_cache_key(state)
        now = int(time.time())
        try:
            self._ensure_schema()
            with self._session() as conn:
                conn.execute("INSERT INTO feedback(cache_key,flag,flagged_at) VALUES(?,?,?)",
                             (key, "bad_advice", now))
                conn.execute("UPDATE decisions SET confidence=confidence*0.5 WHERE cache_key=?", (key,))
        except _DB_ERRORS as exc:
            self._schema_ready = False
            self._warn("flag_bad", exc)
            return False
        return True

    def bump_confidence(self, state, multiplier: float, *, flag: str = "graded"):
        """Apply a confidence multiplier to a cache entry - closes the
        positive end of the feedback loop. Confidence is clamped to
        [0.0, 1.0]. Used by `coaches/feedback.py` after a graded match.

        S -> 1.5  (capped at 1.0)         A -> 1.2
        B -> 1.0  (no-op)                  C -> 0.95
        D -> 0.8                           F -> use flag_bad() instead

        A non-finite or non-number multiplier is refused: SQLite stores a NaN
        product as NULL, which no later comparison can read.
        """
        if not isinstance(state, Mapping) or not _is_num(multiplier):
            return
        try:
            mult = float(multiplier)
        except OverflowError:
            return  # an int past float range
        if mult <= 0 or mult == 1.0:
            return  # no-op
        key = make_cache_key(state)
        now = int(time.time())
        try:
            self._ensure_schema()
            with self._session() as conn:
                conn.execute("INSERT INTO feedback(cache_key,flag,flagged_at) VALUES(?,?,?)",
                             (key, str(flag), now))
                # Clamp to [0,1]: MIN(1.0, MAX(0.0, confidence * multiplier))
                conn.execute(
                    "UPDATE decisions SET confidence = MIN(1.0, MAX(0.0, confidence * ?)) "
                    "WHERE cache_key=?",
                    (mult, key),
                )
            logger.debug("Cache bump key=%s mult=%.2f flag=%s", key[:8], mult, flag)
        except _DB_ERRORS as exc:
            self._schema_ready = False
            self._warn("bump_confidence", exc)

    def close(self):
        """No persistent connection to close - WAL connections are per-call."""
        logger.debug("CacheEngine.close() called - no-op (connection-per-call mode)")
