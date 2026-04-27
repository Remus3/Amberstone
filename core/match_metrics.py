"""
Match metrics recorder — persists every STATS panel field to a SQLite DB
with game-time + milestone tagging.

Purpose (per project memory queue items #6 and #9):
  - Post-game analysis: replay the metric trajectory by game_time_s
    ("you were +8 CSD at 10, −4 at 15 — what happened?").
  - Post-session aggregation: AVG/stddev across matches in a session.
  - Coach-guidance comparison: vs your baseline, vs rank-tier benchmarks.

Write cadence (hybrid — caller chooses which API to invoke):
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

This module is IMPORT-ONLY safe — calling init_db() is idempotent.
The `recorder` module-level singleton buffers writes in memory and
flushes on demand (every ~5s or at milestone boundaries — caller's choice).
"""
from __future__ import annotations
import sqlite3
import threading
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Optional

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
# Coach weighting guidance: source_truth=1.0, inferred_tight≈0.75,
# inferred_wide≈0.4. These are the ONLY accepted values.
PROVENANCE_TIERS = ("source_truth", "inferred_tight", "inferred_wide")

# Canonical milestone tags — the coach emits one of these at the right
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
        # Create/update indexes — safe after the column definitely exists.
        for idx_sql in _INDEX_DDL:
            conn.execute(idx_sql)
        conn.commit()
    finally:
        conn.close()


def integrity_check() -> tuple[bool, str]:
    """PRAGMA integrity_check — returns (ok, message). Caller should run
    this before every retro-fill batch so a corrupt DB doesn't mask bad
    writes silently."""
    conn = sqlite3.connect(DB_PATH)
    try:
        row = conn.execute("PRAGMA integrity_check").fetchone()
        msg = row[0] if row else "no result"
        return (msg == "ok", msg)
    finally:
        conn.close()


def row_count() -> int:
    conn = sqlite3.connect(DB_PATH)
    try:
        return conn.execute("SELECT COUNT(*) FROM match_metrics").fetchone()[0]
    finally:
        conn.close()


class Recorder:
    """Thread-safe buffered recorder. Call record(...) to queue a row;
    flush() commits in a single transaction."""

    def __init__(self) -> None:
        init_db()
        self._buf: list[tuple] = []
        self._lock = threading.Lock()

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
        PROVENANCE_TIERS — defaults to source_truth (direct data read);
        callers deriving values with math should pass 'inferred_tight'
        (small-margin) or 'inferred_wide' (notable uncertainty)."""
        if provenance not in PROVENANCE_TIERS:
            provenance = "inferred_wide"  # unknown tier → treat as widest
        wall = datetime.now(timezone.utc).isoformat()
        row = (
            match_id, session_id, champion, mode,
            key, "" if value is None else str(value), metric_type,
            game_time_s, wall, milestone_tag, provenance,
        )
        with self._lock:
            self._buf.append(row)

    def flush(self) -> int:
        """Commit buffered rows. Returns number of rows written."""
        with self._lock:
            if not self._buf:
                return 0
            rows, self._buf = self._buf, []
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
        return len(rows)

    def buffered(self) -> int:
        with self._lock:
            return len(self._buf)

    # ─── Payload snapshot helper ───────────────────────────────────────
    # Map from state-payload key → (recorder metric_key, metric_type).
    # When the coach writes coaching_data.json, a caller can invoke
    # record_state_snapshot(payload, match_id=..., game_time_s=...) to
    # emit every tracked field to match_metrics in one call. Keys absent
    # from the payload are silently skipped. NO FABRICATION.
    _PAYLOAD_METRIC_MAP: dict[str, tuple[str, str]] = {
        # Core game state
        "kda":                     ("kda_string",           "text"),
        "cs":                      ("cs_current",           "numeric"),
        "gold":                    ("gold_current",         "numeric"),
        "level":                   ("level_current",        "numeric"),
        "hp_pct":                  ("hp_pct",               "pct"),
        "mp_pct":                  ("mp_pct",               "pct"),
        "vision_score":            ("vision_score",         "numeric"),
        # STATS panel fields — mirror the UI's renderStats() reads.
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
        "enemy_summs_tracked":     ("enemy_summs_tracked",  "text"),
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
        """
        n = 0
        if not isinstance(payload, dict) or not match_id:
            return 0
        if champion is None:
            champion = payload.get("champion") or ""
        if mode is None:
            mode = payload.get("game_mode") or payload.get("mode") or ""
        if game_time_s is None:
            gt = payload.get("game_time_s")
            if isinstance(gt, (int, float)):
                game_time_s = int(gt)
        overrides = provenance_overrides or {}
        for pkey, (mkey, mtype) in self._PAYLOAD_METRIC_MAP.items():
            val = payload.get(pkey)
            if val is None or val == "" or val == "—":
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
