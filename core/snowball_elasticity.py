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
import math
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
    """A read-only handle to the local rewind db, or None when it is absent
    or unopenable. The URI comes from Path.as_uri, which percent-escapes the
    path: an f-string URI let a '#' (fragment) or '%' (escape) in the
    checkout path truncate or mangle it, so the real db was never opened
    (same fix as core.duration_winrate._open_ro)."""
    if not _REWIND_DB.exists():
        return None
    try:
        return sqlite3.connect(_REWIND_DB.resolve().as_uri() + "?mode=ro",
                               uri=True)
    except sqlite3.Error as exc:
        log.warning("snowball_elasticity open: %s", exc)
        return None


def _as_result(value) -> Optional[bool]:
    """tracked_win 1 -> True, 0 -> False, anything else (NULL, 2, text) ->
    None: an unknown result, which never enters a bucket and is never read
    as a loss (RM-610; mirror core.duration_winrate._as_result)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return {1: True, 0: False}.get(value)
    return None


_TEAMS = (100, 200)


def _as_team(value) -> Optional[int]:
    """A stored team id: exactly int 100 or 200 (never a bool), else None.
    SQLite is dynamically typed, so tracked_team_id can hand back text or a
    BLOB; int() on those raised out of the never-raises contract."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value in _TEAMS else None


def _bucket_index(diff: float, buckets) -> Optional[int]:
    for i, (_label, lo, hi) in enumerate(buckets):
        if (lo is None or diff >= lo) and (hi is None or diff < hi):
            return i
    return None


# One row per (match, frame timestamp, team) inside the checkpoint's
# tolerance window: the team's summed total_gold plus the counts that prove
# the sum is honest. TOTAL (a float that never overflows) replaces SUM, whose
# int64 "integer overflow" error on ONE junk row used to discard every match
# of the checkpoint. rows_n counts joined rows, pids_n distinct participants
# and nums_n rows whose gold is a real number: rows_n == pids_n rules out a
# duplicated frame or participant row, rows_n == nums_n rules out a NULL or
# text gold value (SUM / TOTAL skip a NULL and read text as 0, both silently
# wrong). The tolerance window both bounds the scan and drops games too
# short to have reached the checkpoint.
_TEAM_GOLD_IN_WINDOW_SQL = """
SELECT tf.match_id, tf.timestamp_ms, p.team_id,
       TOTAL(tf.total_gold) AS team_gold,
       COUNT(*) AS rows_n,
       COUNT(DISTINCT tf.participant_id) AS pids_n,
       SUM(CASE WHEN typeof(tf.total_gold) IN ('integer', 'real')
                THEN 1 ELSE 0 END) AS nums_n
FROM timeline_frames tf
JOIN matches m ON m.match_id = tf.match_id
JOIN participants p
  ON p.match_id = tf.match_id AND p.participant_id = tf.participant_id
WHERE m.map_id = ? AND m.has_timeline = 1
  AND tf.timestamp_ms BETWEEN ? AND ?
GROUP BY tf.match_id, tf.timestamp_ms, p.team_id
"""


def _team_sum(entry) -> Optional[tuple]:
    """(gold, roster_size) for one team at one frame, or None when the sum
    cannot be trusted: a duplicated row, a NULL / text gold value, or an
    empty roster. TOTAL always returns a float; a non-finite one (an
    infinite REAL) is refused by the caller's finite-difference check."""
    gold, rows_n, pids_n, nums_n = entry
    if not rows_n or rows_n != pids_n or rows_n != nums_n:
        return None
    return float(gold), rows_n


def _checkpoint_diffs(conn: sqlite3.Connection, target_ms: int,
                      tracked: Optional[dict] = None) -> dict:
    """Map match_id -> (tracked_team_gold - enemy_team_gold) at the frame
    nearest ``target_ms`` (within CHECKPOINT_TOLERANCE_MS; ties go to the
    earlier frame) at which both teams' rosters are duplicate-free and the
    SAME size (equal size, not a full 5v5: a frame missing one player on
    each side still counts) and every gold value is a number giving a finite
    difference. A frame failing that is skipped for
    the next-nearest one in the window; a match with no such frame (or no
    resolved tracked meta) is absent from the result. ``tracked`` is
    _tracked_meta's map, read once per call by compute_snowball_elasticity;
    None reads it here."""
    lo = target_ms - CHECKPOINT_TOLERANCE_MS
    hi = target_ms + CHECKPOINT_TOLERANCE_MS
    try:
        rows = conn.execute(
            _TEAM_GOLD_IN_WINDOW_SQL, (SR_MAP_ID, lo, hi),
        ).fetchall()
    except sqlite3.Error as exc:
        log.warning("snowball_elasticity checkpoint %d: %s", target_ms, exc)
        return {}

    if tracked is None:
        tracked = _tracked_meta(conn)

    # match -> frame timestamp -> team -> (gold, rows_n, pids_n, nums_n)
    per_match: dict = {}
    for mid, ts, team, gold, rows_n, pids_n, nums_n in rows:
        if mid not in tracked or isinstance(ts, bool) or not isinstance(ts, int):
            continue
        per_match.setdefault(mid, {}).setdefault(ts, {})[team] = (
            gold, rows_n, pids_n, nums_n)

    diffs: dict = {}
    for mid, frames in per_match.items():
        tracked_team = tracked[mid][0]
        enemy_team = 200 if tracked_team == 100 else 100
        for ts in sorted(frames, key=lambda t: (abs(t - target_ms), t)):
            teams = frames[ts]
            if tracked_team not in teams or enemy_team not in teams:
                continue
            own = _team_sum(teams[tracked_team])
            foe = _team_sum(teams[enemy_team])
            if own is None or foe is None or own[1] != foe[1]:
                continue
            diff = own[0] - foe[0]
            if not math.isfinite(diff):
                continue
            diffs[mid] = diff
            break
    return diffs


def _tracked_meta(conn: sqlite3.Connection) -> dict:
    """Map match_id -> (tracked_team_id, tracked_win) for SR matches with a
    timeline whose team is 100 / 200 and whose result is resolved (0 / 1).
    Read once per compute call and passed down; never cached on the
    connection (an attribute cache was inert on a plain sqlite3.Connection,
    which takes no attributes, and stale across calls on a subclass that
    does)."""
    meta: dict = {}
    try:
        rows = conn.execute(
            "SELECT match_id, tracked_team_id, tracked_win FROM matches "
            "WHERE map_id = ? AND has_timeline = 1",
            (SR_MAP_ID,),
        ).fetchall()
    except sqlite3.Error as exc:
        log.warning("snowball_elasticity tracked meta: %s", exc)
        return meta
    for mid, team, win in rows:
        team_id = _as_team(team)
        result = _as_result(win)
        if team_id is None or result is None:
            continue
        meta[mid] = (team_id, result)
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
    opened + closed. Only a resolved result (tracked_win 0 or 1) on a 100 /
    200 tracked team is counted; an unknown one is skipped, never read as a
    loss. Never raises on stored data - an unavailable db, a junk row or an
    empty corpus returns an ok payload with every checkpoint + bucket present
    (winrate None where a bucket is empty).

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
            diffs = (_checkpoint_diffs(conn, target_ms, tracked)
                     if conn is not None and tracked else {})
            tally = [[0, 0] for _ in buckets]  # [wins, games] per bucket
            for mid, diff in diffs.items():
                _team, win = tracked[mid]
                bi = _bucket_index(diff, buckets)
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
