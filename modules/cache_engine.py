"""
cache_engine.py
SQLite decision cache for auto-coaching.
Thread-safe via connection-per-call. WAL mode for concurrent reads.
"""

import sqlite3
import hashlib
import json
import time
import logging
from pathlib import Path

logger = logging.getLogger("cache")


def phase_bucket(t):
    if t < 600:  return "early"
    if t < 1500: return "mid"
    return "late"

def hp_bucket(pct):
    if pct is None:    return "unknown"
    if pct > 0.75:     return "full"
    if pct > 0.40:     return "half"
    if pct > 0.20:     return "low"
    return "critical"

def mana_bucket(pct):
    if pct is None:    return "unknown"
    if pct > 0.60:     return "high"
    if pct > 0.25:     return "low"
    return "oom"

def obj_window(timers):
    if not timers: return "none"
    soonest = None
    for t in timers.values():
        if t is not None and (soonest is None or t < soonest):
            soonest = t
    if soonest is None: return "none"
    if soonest < 30:    return "imminent"
    if soonest < 90:    return "soon"
    return "none"

def items_key(items):
    if not items: return "none"
    return "|".join(sorted(str(i) for i in items))

def make_cache_key(state):
    key_data = {
        "champion":       state.get("champion", ""),
        "ally_comp":      sorted(state.get("ally_comp", [])),    # CRITICAL: different allies = different advice
        "enemy_adc":      state.get("lane_matchup", {}).get("enemy_adc", ""),
        "game_phase":     phase_bucket(state.get("game_time_s", 0)),
        "wave_state":     state.get("wave_state", "unknown"),
        "hp_bucket":      hp_bucket(state.get("my_hp_pct")),
        "mana_bucket":    mana_bucket(state.get("my_mana_pct")),
        "items_key":      items_key(state.get("my_items", [])),
        "obj_window":     obj_window(state.get("objective_timers", {})),
        "nearby_enemies": sorted(state.get("nearby_enemies", [])),
        "patch_version":  state.get("patch_version", ""),
    }
    raw = json.dumps(key_data, sort_keys=True).encode()
    return hashlib.sha256(raw).hexdigest()[:20]


class CacheEngine:
    def __init__(self, db_path, confidence_threshold=0.6, max_use_count=50):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.confidence_threshold = confidence_threshold
        self.max_use_count = max_use_count
        self._init_db()

    def _conn(self):
        conn = sqlite3.connect(str(self.db_path), timeout=5.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._conn() as conn:
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

    def get(self, state):
        # Single connection across SELECT + UPDATE so the use_count++ is
        # in the same transaction as the read, avoiding a race where
        # flag_bad() could DELETE the row between our two queries (which
        # made the UPDATE silently no-op). Also halves the per-hit
        # connection-open overhead (~1ms each).
        key = make_cache_key(state)
        with self._conn() as conn:
            row = conn.execute(
                "SELECT response, confidence, use_count, patch_version "
                "FROM decisions WHERE cache_key=?", (key,)
            ).fetchone()
            if row is None: return None
            if row["patch_version"] != state.get("patch_version", ""): return None
            if row["confidence"] < self.confidence_threshold: return None
            if row["use_count"] >= self.max_use_count: return None
            conn.execute("UPDATE decisions SET use_count=use_count+1, last_used=? WHERE cache_key=?",
                         (int(time.time()), key))
        logger.debug("Cache HIT key=%s", key[:8])
        return row["response"]

    def set(self, state, response):
        # game_state_json column is preserved for schema back-compat but
        # written empty - a grep across the codebase confirms it's never
        # read by get() or any analyzer. Saves a few KB per cache row at
        # scale.
        key = make_cache_key(state)
        now = int(time.time())
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO decisions (cache_key,champion,patch_version,game_state_json,
                    response,confidence,use_count,created_at,last_used)
                VALUES (?,?,?,?,?,1.0,0,?,?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    response=excluded.response, confidence=1.0,
                    patch_version=excluded.patch_version, last_used=excluded.last_used
            """, (key, state.get("champion",""), state.get("patch_version",""),
                  "", response, now, now))

    def flag_bad(self, state):
        key = make_cache_key(state)
        now = int(time.time())
        with self._conn() as conn:
            conn.execute("INSERT INTO feedback(cache_key,flag,flagged_at) VALUES(?,?,?)",
                         (key, "bad_advice", now))
            conn.execute("UPDATE decisions SET confidence=confidence*0.5 WHERE cache_key=?", (key,))

    def bump_confidence(self, state, multiplier: float, *, flag: str = "graded"):
        """Apply a confidence multiplier to a cache entry - closes the
        positive end of the feedback loop. Confidence is clamped to
        [0.0, 1.0]. Used by `coaches/feedback.py` after a graded match.

        S -> 1.5  (capped at 1.0)         A -> 1.2
        B -> 1.0  (no-op)                  C -> 0.95
        D -> 0.8                           F -> use flag_bad() instead
        """
        if multiplier <= 0 or multiplier == 1.0:
            return  # no-op
        key = make_cache_key(state)
        now = int(time.time())
        try:
            with self._conn() as conn:
                conn.execute("INSERT INTO feedback(cache_key,flag,flagged_at) VALUES(?,?,?)",
                             (key, flag, now))
                # Clamp to [0,1]: MIN(1.0, MAX(0.0, confidence * multiplier))
                conn.execute(
                    "UPDATE decisions SET confidence = MIN(1.0, MAX(0.0, confidence * ?)) "
                    "WHERE cache_key=?",
                    (float(multiplier), key),
                )
            logger.debug("Cache bump key=%s mult=%.2f flag=%s", key[:8], multiplier, flag)
        except Exception as exc:
            logger.warning("bump_confidence failed key=%s: %s", key[:8], exc)

    def close(self):
        """No persistent connection to close - WAL connections are per-call."""
        logger.debug("CacheEngine.close() called - no-op (connection-per-call mode)")
