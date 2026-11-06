"""
Match metrics recorder - persists every STATS panel field to a SQLite DB
with game-time + milestone tagging.

Purpose (per project memory queue items #6 and #9):
  - Post-game analysis: replay the metric trajectory by game_time_s
    ("you were +8 CSD at 10, -4 at 15 - what happened?").
  - Post-session aggregation: AVG/stddev across matches in a session.
  - Coach-guidance comparison: vs your baseline, vs rank-tier benchmarks.

Write cadence (hybrid - caller chooses which API to invoke):
  - Milestone snapshots: event-triggered (first_blood, l6_spike, drake_take,
    10min_mark, laning_end, game_end, etc.). Call record(milestone_tag=...).
  - Periodic snapshots: every 60s of in-game time. Call record() without
    milestone_tag, no change-check.
  - Change-driven: for discrete state (rank, streak, LP, promo). Call record()
    when the upstream value changes.

Storage:
  - Separate DB file at data/match_metrics.db to avoid touching the
    canonical rewind_history.db. match_id + session_id link rows back
    to the source match if you join across DBs.
  - Metrics values are stringified (the UI stringifies them anyway). A
    metric_type column carries a hint ("numeric" | "pct" | "duration_s"
    | "text" | "pair") for downstream analytics.

Importing this module opens NO database connection (s144 true-audit,
RM-1448): the schema is created lazily by the first flush() for the
current DB_PATH, and init_db() stays idempotent for callers that want it
up front. The `recorder` module-level singleton buffers writes in memory
and flushes on demand (every ~5s or at milestone boundaries - caller's
choice).

Row hygiene (RM-1449 / RM-1451): record() refuses a row without a
usable match_id or metric key (ValueError) and coerces every other column
to a bindable shape, so one malformed row can never fail the whole
executemany batch and wedge the buffer behind it. A flush whose schema
has vanished (DB file or data dir deleted under a running process)
re-creates it and retries once (RM-1450).
"""
from __future__ import annotations
import logging
import math
import sqlite3
import threading
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, ClassVar, Optional

logger = logging.getLogger("rc.match_metrics")

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "match_metrics.db"

_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS match_metrics (
  id                       INTEGER PRIMARY KEY AUTOINCREMENT,
  match_id                 TEXT    NOT NULL,
  session_id               TEXT,
  champion                 TEXT,
  mode                     TEXT,
  metric_key               TEXT    NOT NULL,
  metric_value             TEXT    NOT NULL,
  metric_type              TEXT,
  recorded_at_game_time_s  INTEGER,
  recorded_at_wall_time    TEXT    NOT NULL,
  milestone_tag            TEXT,
  provenance               TEXT    NOT NULL DEFAULT 'source_truth'
);
"""
# Indexes created after any ALTER TABLE migration so the provenance index
# is safe to create on pre-existing tables too.
_INDEX_DDL = [
    "CREATE INDEX IF NOT EXISTS idx_mm_match_key   ON match_metrics(match_id, metric_key)",
    "CREATE INDEX IF NOT EXISTS idx_mm_session_key ON match_metrics(session_id, metric_key)",
    "CREATE INDEX IF NOT EXISTS idx_mm_milestone   ON match_metrics(match_id, milestone_tag)",
    "CREATE INDEX IF NOT EXISTS idx_mm_champ_mode  ON match_metrics(champion, mode, metric_key)",
    "CREATE INDEX IF NOT EXISTS idx_mm_provenance  ON match_metrics(provenance)",
]

# Valid provenance tiers (see feedback_metric_provenance_tagging memory).
# Coach weighting guidance: source_truth=1.0, inferred_tight~0.75,
# inferred_wide~0.4. These are the ONLY accepted values.
PROVENANCE_TIERS = ("source_truth", "inferred_tight", "inferred_wide")

# Re-queue ceiling for Recorder.flush failure recovery (deep-audit
# P2-W1-A, 2026-06-11). A transient DB error re-queues the unwritten
# rows; this cap (oldest dropped first) bounds memory if the DB stays
# broken. ~90 metric rows per snapshot x ~50 snapshots per match keeps
# a full match comfortably under the cap.
_REQUEUE_MAX = 5000

# Canonical milestone tags - the coach emits one of these at the right
# moment so post-game tooling can slice the match at well-known phases.
CANONICAL_MILESTONES = frozenset([
    "game_start",
    "first_blood",
    "first_tower",
    "laning_end",
    "10min_mark", "15min_mark", "20min_mark", "25min_mark", "30min_mark",
    "l6_spike", "l11_spike", "l16_spike",
    "item_complete",
    "drake_take", "drake_contested_loss",
    "herald_take",
    "baron_take", "baron_contested_loss",
    "recall_start", "recall_end",
    "death", "kill", "assist",
    "game_end",
])


def init_db() -> None:
    """Idempotent schema initialisation. Safe to call on every import.
    Creates the table if missing, migrates older tables that predate the
    `provenance` column, then ensures all indexes exist.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(_TABLE_DDL)
        # Migration: add provenance column to any pre-existing table that
        # doesn't have it yet. ALTER can't use CREATE IF NOT EXISTS
        # semantics, so we check column existence via PRAGMA first.
        cols = {row[1] for row in conn.execute("PRAGMA table_info(match_metrics)")}
        if "provenance" not in cols:
            conn.execute(
                "ALTER TABLE match_metrics ADD COLUMN provenance TEXT "
                "NOT NULL DEFAULT 'source_truth'"
            )
        # Create/update indexes - safe after the column definitely exists.
        for idx_sql in _INDEX_DDL:
            conn.execute(idx_sql)
        conn.commit()
    finally:
        conn.close()


def integrity_check() -> tuple[bool, str]:
    """PRAGMA integrity_check - returns (ok, message). Caller should run
    this before every retro-fill batch so a corrupt DB doesn't mask bad
    writes silently.

    A MISSING database is initialised first (a first-run retrofill must
    pass its own pre-flight now that import no longer creates the file).
    A file that is not a database at all reports (False, <error>) instead
    of raising, so the caller's clean abort branch runs (RM-1452).
    """
    if not DB_PATH.exists():
        init_db()
    try:
        conn = sqlite3.connect(DB_PATH)
        try:
            row = conn.execute("PRAGMA integrity_check").fetchone()
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        return (False, f"{type(exc).__name__}: {exc}")
    msg = str(row[0]) if row else "no result"
    return (msg == "ok", msg)


def row_count() -> int:
    """Row count of match_metrics (the schema is created when absent)."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    try:
        return conn.execute("SELECT COUNT(*) FROM match_metrics").fetchone()[0]
    finally:
        conn.close()


# --- row coercion (RM-1449 / RM-1451) -----------------------------
# Every bound parameter must be str / int / None: anything else makes
# sqlite3 raise ProgrammingError for the WHOLE executemany batch.

def _text_or_none(value: Any) -> Optional[str]:
    """A bindable optional TEXT column: str kept, int / finite float
    stringified, anything else (dict, list, bool, NaN, objects) -> None."""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float) and math.isfinite(value):
        return str(value)
    return None


def _required_text(value: Any, what: str) -> str:
    """A NOT NULL identifier column: non-empty str, or a (non-bool) int."""
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, str) and value:
        return value
    raise ValueError(f"match_metrics: {what} must be a non-empty str or int, "
                     f"got {type(value).__name__}")


def _game_time_or_none(value: Any) -> Optional[int]:
    """Game clock in whole seconds: a non-negative finite number, else None
    (a bool, string, NaN, infinity or negative clock is not a game time)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value < 0:
        return None
    return int(value)


def _is_missing_schema(exc: sqlite3.OperationalError) -> bool:
    """True when the error means the DB file / table is gone (heal + retry),
    not a transient lock (re-queue + raise)."""
    msg = str(exc).lower()
    return "no such table" in msg or "unable to open database file" in msg


class Recorder:
    """Thread-safe buffered recorder. Call record(...) to queue a row;
    flush() commits in a single transaction."""

    def __init__(self) -> None:
        # No DB I/O here (RM-1448): the schema is created by the first
        # flush for whichever DB_PATH is current at that moment.
        self._buf: list[tuple] = []
        self._lock = threading.Lock()
        self._schema_ready_for: Optional[Path] = None

    def record(
        self,
        *,
        match_id: str,
        key: str,
        value: Any,
        metric_type: str = "text",
        game_time_s: Optional[int] = None,
        milestone_tag: Optional[str] = None,
        session_id: Optional[str] = None,
        champion: Optional[str] = None,
        mode: Optional[str] = None,
        provenance: str = "source_truth",
    ) -> None:
        """Buffer one metric row. `provenance` must be one of
        PROVENANCE_TIERS - defaults to source_truth (direct data read);
        callers deriving values with math should pass 'inferred_tight'
        (small-margin) or 'inferred_wide' (notable uncertainty).

        Raises ValueError when `match_id` or `key` is not a non-empty str
        (an int match_id is kept as its text). Every other column is
        coerced to a bindable shape: an unusable champion / mode /
        session_id / milestone_tag becomes NULL, an unusable metric_type
        falls back to "text", and a game clock that is not a non-negative
        finite number becomes NULL (floats truncate to whole seconds).
        """
        mid = _required_text(match_id, "match_id")
        if not isinstance(key, str) or not key:
            raise ValueError("match_metrics: key must be a non-empty str, "
                             f"got {type(key).__name__}")
        if provenance not in PROVENANCE_TIERS:
            provenance = "inferred_wide"  # unknown tier -> treat as widest
        mtype = metric_type if isinstance(metric_type, str) and metric_type else "text"
        wall = datetime.now(timezone.utc).isoformat()
        row = (
            mid, _text_or_none(session_id), _text_or_none(champion),
            _text_or_none(mode),
            key, "" if value is None else str(value), mtype,
            _game_time_or_none(game_time_s), wall,
            _text_or_none(milestone_tag), provenance,
        )
        with self._lock:
            self._buf.append(row)

    def _write(self, rows: list[tuple]) -> None:
        """One transaction for `rows`; creates the schema for the current
        DB_PATH on first use and heals a vanished schema once."""
        path = DB_PATH
        if self._schema_ready_for != path:
            init_db()
            self._schema_ready_for = path
        try:
            self._insert(rows)
        except sqlite3.OperationalError as exc:
            if not _is_missing_schema(exc):
                raise
            # The DB file or its directory vanished under a running process;
            # a bare connect would just create an empty DB and fail again
            # on every flush. Re-create the schema and retry ONCE.
            logger.warning("match_metrics: schema missing at flush (%s); "
                           "re-initialising", exc)
            self._schema_ready_for = None
            init_db()
            self._schema_ready_for = path
            self._insert(rows)

    @staticmethod
    def _insert(rows: list[tuple]) -> None:
        conn = sqlite3.connect(DB_PATH)
        try:
            conn.executemany(
                """
                INSERT INTO match_metrics
                  (match_id, session_id, champion, mode,
                   metric_key, metric_value, metric_type,
                   recorded_at_game_time_s, recorded_at_wall_time, milestone_tag,
                   provenance)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                rows,
            )
            conn.commit()
        finally:
            conn.close()

    def flush(self) -> int:
        """Commit buffered rows. Returns number of rows written.

        AUDIT 2026-06-11 (deep-audit P2-W1-A): on a write failure
        (sqlite "database is locked" class) the rows are re-queued at
        the FRONT of the buffer instead of being dropped, so the next
        flush retries them in original order. The exception still
        propagates (callers - metric_streamer via live_metrics.stream -
        already contain it). Re-queue is capped at _REQUEUE_MAX rows
        (oldest dropped) so a permanently failing DB cannot grow the
        buffer without bound. A cap drop is logged at WARNING with the
        number of rows lost (RM-1452) - it is never silent.
        """
        with self._lock:
            if not self._buf:
                return 0
            rows, self._buf = self._buf, []
        try:
            self._write(rows)
        except Exception:
            # Broad on purpose: whatever failed, the rows go back on the
            # buffer and the error still propagates to the caller.
            dropped = 0
            with self._lock:
                requeued = rows + self._buf
                if len(requeued) > _REQUEUE_MAX:
                    dropped = len(requeued) - _REQUEUE_MAX
                    requeued = requeued[-_REQUEUE_MAX:]
                self._buf = requeued
            if dropped:
                logger.warning("match_metrics: flush failed; re-queue cap %d "
                               "reached, dropped %d oldest row(s)",
                               _REQUEUE_MAX, dropped)
            raise
        return len(rows)

    def buffered(self) -> int:
        with self._lock:
            return len(self._buf)

    # --- Payload snapshot helper ---------------------------------------
    # Map from state-payload key -> (recorder metric_key, metric_type).
    # When the coach writes coaching_data.json, a caller can invoke
    # record_state_snapshot(payload, match_id=..., game_time_s=...) to
    # emit every tracked field to match_metrics in one call. Keys absent
    # from the payload are silently skipped. NO FABRICATION.
    _PAYLOAD_METRIC_MAP: ClassVar[dict[str, tuple[str, str]]] = {
        # Core game state
        "kda":                     ("kda_string",           "text"),
        "cs":                      ("cs_current",           "numeric"),
        "gold":                    ("gold_current",         "numeric"),
        "level":                   ("level_current",        "numeric"),
        "hp_pct":                  ("hp_pct",               "pct"),
        "mp_pct":                  ("mp_pct",               "pct"),
        "vision_score":            ("vision_score",         "numeric"),
        # STATS panel fields - mirror the UI's renderStats() reads.
        "cannon_cs_summary":       ("cannon_cs",            "pair"),
        "cs_at_10":                ("cs_at_10_str",         "text"),
        "csd_at_15":               ("csd_at_15_str",        "text"),
        "gd_at_15":                ("gd_at_15_str",         "text"),
        "wave_state_now":          ("wave_state_now",       "text"),
        "back_gold_summary":       ("back_gold",            "pair"),
        "enemy_side_pct":          ("enemy_side_pct",       "pct"),
        "build_deviation":         ("build_deviation",      "text"),
        "next_spike":              ("next_spike",           "text"),
        "wave_control":            ("wave_control",         "pair"),
        "trade_winrate":           ("trade_winrate",        "pair"),
        "roams_summary":           ("roams",                "pair"),
        "wave_freezes":            ("wave_freezes",         "text"),
        "jungle_pathing":          ("jungle_pathing",       "text"),
        "lane_prio":               ("lane_prio",            "text"),
        "enemy_laner_mastery":     ("enemy_laner_mastery",  "text"),
        "powerspike_status":       ("powerspike_status",    "text"),
        "first_recall_timing":     ("first_recall_timing",  "text"),
        # Combat
        "kill_participation_pct":  ("kill_participation_pct","pct"),
        "damage_share_summary":    ("damage_share",         "pair"),
        "damage_taken_summary":    ("damage_taken",         "pair"),
        "cc_score_summary":        ("cc_score",             "pair"),
        "heal_shield_summary":     ("heal_shield",          "pair"),
        "peel_on_carry":           ("peel_on_carry",        "text"),
        "time_dead_summary":       ("time_dead",            "pair"),
        "time_alive_pct":          ("time_alive_pct",       "pct"),
        "skillshot_summary":       ("skillshot",            "pair"),
        "combo_hit_rate":          ("combo_hit_rate",       "pair"),
        "engage_count":            ("engage_count",         "pair"),
        "ult_efficiency":          ("ult_efficiency",       "pair"),
        "teamfight_outcomes":      ("teamfight_outcomes",   "pair"),
        "dive_outcomes":           ("dive_outcomes",        "pair"),
        "flash_discipline":        ("flash_discipline",     "pct"),
        "solo_death_rate":         ("solo_death_rate",      "pair"),
        "top_enemy_threat":        ("top_enemy_threat",     "text"),
        "team_comp_id":            ("team_comp_id",         "text"),
        "carry_index":             ("carry_index",          "text"),
        "auto_attack_mix":         ("auto_attack_mix",      "pair"),
        "wasted_clicks":           ("wasted_clicks",        "text"),
        "apm":                     ("apm",                  "pair"),
        "reaction_time":           ("reaction_time",        "pair"),
        "cancel_windows":          ("cancel_windows",       "pair"),
        "animation_cancels":       ("animation_cancels",    "pair"),
        "fight_windows":           ("fight_windows",        "text"),
        "wall_collision_deaths":   ("wall_collision_deaths","numeric"),
        "death_locations":         ("death_locations",      "text"),
        "death_pattern":           ("death_pattern",        "text"),
        "wincon_ability_up":       ("wincon_ability_up",    "pair"),
        "ally_summs_up":           ("ally_summs_up",        "text"),
        # "enemy_summs_tracked" removed 2026-08-12 (B1 residual, Riot
        # compliance). The tracker and its dashboard row went with B1; this
        # registry entry outlived them and would have persisted an
        # enemy-summoner metric to match_metrics.db had anything ever emitted
        # the payload key. Nothing did - the live DB held 246,928 rows and
        # ZERO for it. Guarded by tests/test_cc_threat_cell_riot_compliance.py
        # (EnemySummsRegistryResidualTests). Own-party "ally_summs_up" above
        # stays: B2 permits own-party summoner rows.
        "flank_success":           ("flank_success",        "pair"),
        # Map presence
        "vision_summary":          ("vision_summary",       "pair"),
        "trinket_uptime":          ("trinket_uptime",       "pct"),
        "pink_ward_uptime":        ("pink_ward_uptime",     "pair"),
        "vision_denied":           ("vision_denied",        "pair"),
        "objective_setup":         ("objective_setup",      "pair"),
        "objective_dance":         ("objective_dance",      "pair"),
        "baron_prep":              ("baron_prep",           "pair"),
        "scuttle_control":         ("scuttle_control",      "pair"),
        "jungler_tracking":        ("jungler_tracking",     "text"),
        "split_push_pressure":     ("split_push_pressure",  "text"),
        # Identity
        "mastery_summary":         ("mastery",              "text"),
        "runes_chosen":            ("runes",                "text"),
        "power_spike_map":         ("power_spike_map",      "text"),
        "matchup_history":         ("matchup_history",      "text"),
        "counter_warning":         ("counter_warning",      "text"),
        "champ_key_metric":        ("champ_key_metric",     "pair"),
        "keystone_procs":          ("keystone_procs",       "pair"),
        "rune_adapt_hint":         ("rune_adapt_hint",      "text"),
        # Rank / session
        "current_rank_lp":         ("current_rank_lp",      "text"),
        "lp_forecast":             ("lp_forecast",          "pair"),
        "lp_session_delta":        ("lp_session_delta",     "pair"),
        "session_duration":        ("session_duration",     "pair"),
        "team_gold_diff_trend":    ("team_gold_diff_trend", "text"),
        "promo_status":            ("promo_status",         "text"),
        "rank_goal_progress":      ("rank_goal_progress",   "pair"),
        "break_recommendation":    ("break_recommendation", "text"),
        "lobby_mmr":               ("lobby_mmr",            "text"),
        "rank_benchmark":          ("rank_benchmark",       "text"),
        "improvement_target":      ("improvement_target",   "text"),
        "chat_tone":               ("chat_tone",            "text"),
        "strength_of_game":        ("strength_of_game",     "text"),
        "weakness_of_game":        ("weakness_of_game",     "text"),
        "adjustment_rate":         ("adjustment_rate",      "text"),
        "tilt_meter":              ("tilt_meter",           "text"),
        "comeback_odds":           ("comeback_odds",        "pct"),
        "comp_alignment":          ("comp_alignment",       "text"),
        "wincon_phase":            ("wincon_phase",         "text"),
        "session_to_session_delta":("session_to_session_delta","text"),
        "game_close_eta":          ("game_close_eta",       "text"),
        "comp_synergy":            ("comp_synergy",         "pair"),
        "self_judgement":          ("self_judgement",       "text"),
        "coach_interventions":     ("coach_interventions",  "pair"),
        # Game Sense (aftergame only)
        "game_sense_early":        ("game_sense_early",     "text"),
        "game_sense_mid":          ("game_sense_mid",       "text"),
        "game_sense_late":         ("game_sense_late",      "text"),
        "game_sense_early_blurb":  ("game_sense_early_blurb","text"),
        "game_sense_mid_blurb":    ("game_sense_mid_blurb", "text"),
        "game_sense_late_blurb":   ("game_sense_late_blurb","text"),
        # Digest (cross-session)
        "digest_state":            ("digest_state",         "text"),
        "digest_streak":           ("digest_streak",        "text"),
        "digest_recent":           ("digest_recent",        "text"),
    }

    def record_state_snapshot(
        self,
        payload: dict,
        *,
        match_id: str,
        game_time_s: Optional[int] = None,
        milestone_tag: Optional[str] = None,
        session_id: Optional[str] = None,
        champion: Optional[str] = None,
        mode: Optional[str] = None,
        provenance: str = "source_truth",
        provenance_overrides: Optional[dict] = None,
    ) -> int:
        """Buffer every payload key listed in _PAYLOAD_METRIC_MAP that's
        present in `payload`. Returns number of metrics buffered.

        Provenance handling:
          - `provenance` sets the default tier for every emitted metric.
          - `provenance_overrides` (optional) is a {metric_key: tier} map
            for per-metric exceptions. Example: a live-coach snapshot
            might pass provenance="source_truth" for payload keys that
            come from the Riot API, but override "enemy_side_pct" to
            "inferred_tight" because it's computed from position samples.

        Typical caller: the coach writes coaching_data.json, then calls
        recorder.record_state_snapshot(payload, match_id=mid,
        game_time_s=gt, milestone_tag="10min_mark"|None). Periodic
        60-second flushes + milestone-specific calls are the intended
        cadence.

        A payload clock that is not a non-negative finite number is
        recorded as NULL (never raised), a non-finite float metric value
        (NaN / infinity) is skipped like a missing one - it is not a
        measurement - and a non-dict `provenance_overrides` is ignored.
        """
        n = 0
        if not isinstance(payload, dict) or not match_id:
            return 0
        if champion is None:
            champion = payload.get("champion") or ""
        if mode is None:
            mode = payload.get("game_mode") or payload.get("mode") or ""
        if game_time_s is None:
            game_time_s = _game_time_or_none(payload.get("game_time_s"))
        overrides = provenance_overrides if isinstance(provenance_overrides, dict) else {}
        for pkey, (mkey, mtype) in self._PAYLOAD_METRIC_MAP.items():
            val = payload.get(pkey)
            if val is None or val in ("", "-"):
                continue
            if isinstance(val, float) and not math.isfinite(val):
                continue
            prov = overrides.get(mkey) or overrides.get(pkey) or provenance
            self.record(
                match_id=match_id, key=mkey, value=val, metric_type=mtype,
                game_time_s=game_time_s, milestone_tag=milestone_tag,
                session_id=session_id, champion=champion, mode=mode,
                provenance=prov,
            )
            n += 1
        return n


# Module-level singleton. Callers import and use directly.
recorder = Recorder()
