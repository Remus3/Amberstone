"""Snowball-elasticity: personal win-rate bucketed by TEAM gold differential
at fixed early/mid checkpoints, over the local rewind_history.db timeline.

The "snowball" read popularized by public stats sites (Aggregator H F3):
given the tracked player's TEAM gold lead at ~10min and ~20min, what is their
win %? A steep rise from the behind buckets to the ahead buckets reads as a
high-elasticity / snowball-prone corpus (leads convert hard); a flat curve as a
scaling / comeback tendency (leads matter less). Computed over the operator's
OWN SR match corpus - no global / cross-player / Riot / Claude data.

Read-only. SR-only (map_id 11): the gold-lead-at-checkpoint signal is a
lane/objective-economy read that is meaningless in ARAM (shared XP, no lane
economy) and Arena (2v2 rounds, no 10/20min frames). Mirrors
core.duration_winrate's conn-injection seam + MIN_BUCKET_N gate so tests inject
an in-memory db and the suite stays clean-checkout safe (the db is gitignored).

The differential is a TEAM total_gold diff at the timeline frame nearest each
checkpoint: sum(total_gold) over the tracked team minus the enemy team, read
from timeline_frames joined to participants (participant_id -> team_id). Sparse
buckets are Laplace-shrunk toward 0.5 via core.smoothed_rates so a 2-0 bucket
does not read as a confident 100%.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Optional

from core import smoothed_rates

log = logging.getLogger("rc.snowball_elasticity")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_REWIND_DB = _PROJECT_ROOT / "data" / "rewind_history.db"

SR_MAP_ID = 11
VALID_MODES = ("sr",)
DEFAULT_MODE = "sr"

# (key, target_ms). ~10min and ~20min - the canonical snowball checkpoints.
CHECKPOINTS = (("10min", 600_000), ("20min", 1_200_000))
# A frame must fall within this of the checkpoint to count (Match-V5 frames are
# ~60s apart); a game that ended before the checkpoint has no near frame and so
# does not contribute to that checkpoint's buckets.
CHECKPOINT_TOLERANCE_MS = 90_000

MIN_BUCKET_N = 5  # below this a bucket's raw winrate is untrustworthy -> None

# Signed team-gold-differential buckets (gold): lo inclusive, hi exclusive,
# None = open-ended. Ordered behind -> ahead so the payload reads as a curve.
DEFAULT_BUCKETS = (
    ("behind_big", None, -2500),
    ("behind", -2500, -800),
    ("even", -800, 800),
    ("ahead", 800, 2500),
    ("ahead_big", 2500, None),
)


def _open_ro() -> Optional[sqlite3.Connection]:
    if not _REWIND_DB.exists():
        return None
    try:
        return sqlite3.connect(f"file:{_REWIND_DB}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        log.warning("snowball_elasticity open: %s", exc)
        return None


def _bucket_index(diff: int, buckets) -> Optional[int]:
    for i, (_label, lo, hi) in enumerate(buckets):
        if (lo is None or diff >= lo) and (hi is None or diff < hi):
            return i
    return None


# For each SR match with a timeline, the summed total_gold per team at the ONE
# frame nearest the checkpoint (deterministic: nearest by |ts-target|, ties
# broken by the earlier ts). Restricting to a tolerance window both bounds the
# scan and drops games too short to have reached the checkpoint.
_TEAM_GOLD_AT_CHECKPOINT_SQL = """
WITH cand AS (
    SELECT tf.match_id AS mid, tf.timestamp_ms AS ts, p.team_id AS team,
           tf.total_gold AS g, ABS(tf.timestamp_ms - ?) AS dist
    FROM timeline_frames tf
    JOIN matches m ON m.match_id = tf.match_id
    JOIN participants p
      ON p.match_id = tf.match_id AND p.participant_id = tf.participant_id
    WHERE m.map_id = ? AND m.has_timeline = 1
      AND tf.timestamp_ms BETWEEN ? AND ?
),
pick AS (
    SELECT mid, ts FROM (
        SELECT mid, ts,
               ROW_NUMBER() OVER (PARTITION BY mid ORDER BY ABS(ts - ?), ts) AS rn
        FROM (SELECT DISTINCT mid, ts FROM cand)
    ) WHERE rn = 1
)
SELECT c.mid, c.team, SUM(c.g) AS team_gold
FROM cand c
JOIN pick k ON k.mid = c.mid AND k.ts = c.ts
GROUP BY c.mid, c.team
"""


def _checkpoint_diffs(conn: sqlite3.Connection, target_ms: int) -> dict:
    """Map match_id -> (tracked_team_gold - enemy_team_gold) at the frame
    nearest ``target_ms``. A match missing either team's sum (no near frame) is
    absent from the result."""
    lo = target_ms - CHECKPOINT_TOLERANCE_MS
    hi = target_ms + CHECKPOINT_TOLERANCE_MS
    try:
        rows = conn.execute(
            _TEAM_GOLD_AT_CHECKPOINT_SQL,
            (target_ms, SR_MAP_ID, lo, hi, target_ms),
        ).fetchall()
    except sqlite3.Error as exc:
        log.warning("snowball_elasticity checkpoint %d: %s", target_ms, exc)
        return {}

    per_match: dict = {}
    for mid, team, team_gold in rows:
        per_match.setdefault(mid, {})[team] = team_gold

    tracked = _tracked_meta(conn)
    diffs: dict = {}
    for mid, teams in per_match.items():
        meta = tracked.get(mid)
        if meta is None:
            continue
        tracked_team, _win = meta
        enemy_team = 200 if tracked_team == 100 else 100
        if tracked_team not in teams or enemy_team not in teams:
            continue
        diffs[mid] = teams[tracked_team] - teams[enemy_team]
    return diffs


def _tracked_meta(conn: sqlite3.Connection) -> dict:
    """Map match_id -> (tracked_team_id, tracked_win) for SR matches with a
    timeline. Cached per call on the connection object to avoid re-querying for
    each checkpoint."""
    cache = getattr(conn, "_se_tracked_meta", None)
    if cache is not None:
        return cache
    meta: dict = {}
    try:
        for mid, team, win in conn.execute(
            "SELECT match_id, tracked_team_id, tracked_win FROM matches "
            "WHERE map_id = ? AND has_timeline = 1",
            (SR_MAP_ID,),
        ).fetchall():
            if team is None:
                continue
            meta[mid] = (int(team), int(win or 0))
    except sqlite3.Error as exc:
        log.warning("snowball_elasticity tracked meta: %s", exc)
    try:
        conn._se_tracked_meta = meta  # type: ignore[attr-defined]
    except (AttributeError, TypeError):
        pass
    return meta


def compute_snowball_elasticity(
    mode: str = DEFAULT_MODE,
    conn: Optional[sqlite3.Connection] = None,
    buckets=DEFAULT_BUCKETS,
) -> dict:
    """Win % per team-gold-differential bucket at each checkpoint, SR-only.

    ``mode`` is accepted for API symmetry with sibling surfaces but only "sr"
    is meaningful today (anything else falls back to it). ``conn`` injects a db
    connection for tests; when None a read-only handle to the local rewind db is
    opened + closed. Never raises - an unavailable db or empty corpus returns an
    ok payload with every checkpoint + bucket present and winrate None.

    Each bucket carries both ``winrate`` (raw %, gated to None below
    MIN_BUCKET_N) and ``winrate_smoothed`` (Laplace-shrunk %, present whenever
    games > 0) so the panel can draw a trustworthy curve on a sparse corpus.
    """
    mode = DEFAULT_MODE  # SR-only surface; symmetry arg is inert

    own = conn is None
    if own:
        conn = _open_ro()

    checkpoints_out = []
    try:
        tracked = _tracked_meta(conn) if conn is not None else {}
        for key, target_ms in CHECKPOINTS:
            diffs = _checkpoint_diffs(conn, target_ms) if conn is not None else {}
            tally = [[0, 0] for _ in buckets]  # [wins, games] per bucket
            for mid, diff in diffs.items():
                meta = tracked.get(mid)
                if meta is None:
                    continue
                _team, win = meta
                bi = _bucket_index(int(diff), buckets)
                if bi is None:
                    continue
                tally[bi][1] += 1
                if win:
                    tally[bi][0] += 1

            out_buckets = []
            total = 0
            for (label, lo, hi), (wins, games) in zip(buckets, tally):
                total += games
                raw = round(100.0 * wins / games, 1) if games >= MIN_BUCKET_N else None
                smoothed = (round(100.0 * smoothed_rates.laplace_rate(wins, games), 1)
                            if games > 0 else None)
                out_buckets.append({
                    "label": label,
                    "lo": lo,
                    "hi": hi,
                    "wins": wins,
                    "games": games,
                    "winrate": raw,
                    "winrate_smoothed": smoothed,
                })
            checkpoints_out.append({
                "key": key,
                "target_ms": target_ms,
                "n": total,
                "buckets": out_buckets,
            })
    finally:
        if own and conn is not None:
            try:
                conn.close()
            except sqlite3.Error:
                pass

    return {
        "ok": True,
        "mode": mode,
        "min_bucket_n": MIN_BUCKET_N,
        "checkpoints": checkpoints_out,
    }
