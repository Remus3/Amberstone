"""Win-signal reconciliation - postgame_stats.db -> mode DBs.

Live-phase3 rows (filed by ``game_ingest`` on game-end) start with
``win=NULL`` because the coaching JSON doesn't carry an authoritative
win flag. Separately, ``lcu/lcu_postgame_collector`` writes authoritative
WIN/LOSS into ``data/postgame_stats.db``'s ``<mode>_player_stats`` tables
within a few seconds of match end via the LCU ``/lol-end-of-game`` event.

This module bridges the two: for each live-phase3 match with no win
signal yet, find the matching postgame row (narrow captured_at window +
same champion + mode) and patch the win column. Runs as part of the
supervisor's ``_auto_analyze_after_idle`` so by the time the 2-min idle
window elapses, postgame_stats has been populated.

Safety:
  * Idempotent - only UPDATEs rows where win IS NULL.
  * Per-row confidence check: if multiple postgame rows are in-window,
    skip rather than guess.
  * Read-only to postgame_stats.db; write-only to the live-phase3 rows.
  * A live row whose ``ended_at`` is missing or unparseable is SKIPPED: it
    has no time to window against, and guessing "now" would hand it the
    result of whatever game is being played at reconcile time.
  * One batch per mode: the UPDATEs commit together, an sqlite error rolls
    them all back and the summary says so (``patched`` 0, ``rolled_back``).
  * Both connections are CLOSED on every path (sqlite3's own context
    manager only commits; the supervisor runs this every post-game idle).

Schema (RM-1946): the collector (``lcu/lcu_postgame_collector.py``
``_MODES_SQL``) keeps ``captured_at`` on ``<mode>_matches`` and the
champion / result / local flag on ``<mode>_player_stats``, so the lookup
JOINs the two on ``match_id``. Until 2026-11-06 the query read
``captured_at`` off ``player_stats``, raised "no such column" on every real
DB, counted that as an ordinary miss, and never patched a row.
"""
from __future__ import annotations

import logging
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("agent2.win_reconcile")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
# RM-170: env-overridable so a test can point the mode DBs at a tmp dir.
# Default unchanged. All five modules that define this path read the SAME
# var, so an override cannot split schema-init from ingest.
MODE_DB_DIR = Path(os.environ.get("RC_PHASE3_DB_DIR") or (_PROJECT_ROOT / "data" / "db"))
POSTGAME_DB = _PROJECT_ROOT / "data" / "postgame_stats.db"

LIVE_SOURCE_TAG = "live-phase3"

# Match window: postgame capture is usually within ~30s of our
# finished_at; widen to 10 min to absorb clock skew + collector lag.
MATCH_WINDOW_SEC = 600

# (mode_db_name, postgame_player_stats_table_name). Mode DB keys follow
# the sr_draft / sr_ranked / aram / arena / brawl convention; postgame
# uses the mode-string SR / ARAM / ARENA / BRAWL / TFT tables.
_MODE_TO_POSTGAME_TABLE = {
    "aram":       "aram_player_stats",
    "arena":      "arena_player_stats",
    "brawl":      "brawl_player_stats",
    "sr_ranked":  "sr_player_stats",
    "sr_draft":   "sr_player_stats",
}

# The collector writes captured_at as UTC "YYYY-MM-DDTHH:MM:SSZ"
# (lcu_postgame_collector.py). The SQL prefilter compares strings, so its
# cutoffs are rendered in that same UTC layout; the exact window is then
# re-checked in Python on parsed datetimes.
_COLLECTOR_TS_FMT = "%Y-%m-%dT%H:%M:%SZ"


def _parse_iso(ts: object) -> datetime | None:
    """Parse an ISO-8601 timestamp to an AWARE datetime (naive = UTC).

    Returns None for a missing, non-text or unparseable value.
    """
    if not ts or not isinstance(ts, str):
        return None
    try:
        dt = datetime.fromisoformat(ts.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _lookup_postgame_result(
    pg_conn: sqlite3.Connection,
    pg_table: str,
    champion: str,
    ended_at: datetime,
    window_sec: int,
) -> tuple[int | None, str]:
    """Return (win_int, reason) for the best matching postgame row.

    ``pg_table`` is a ``<mode>_player_stats`` name from
    ``_MODE_TO_POSTGAME_TABLE`` (never caller text); its ``<mode>_matches``
    sibling carries ``captured_at``.

    Strategy:
      1. Filter to ``is_local_player=1`` and exact champion match.
      2. Keep rows whose match ``captured_at`` is within +/-window_sec.
      3. If exactly one candidate remains, use its ``team_result``.
      4. If 0 - return (None, "no candidate").
      5. If >1 - pick the row with captured_at closest to ended_at.
         If the two closest rows are within 5s of each other and have
         different team_result, bail out ("ambiguous").

    A query failure returns (None, "postgame query error: ...").
    """
    matches_table = pg_table.replace("_player_stats", "_matches")
    if ended_at.tzinfo is None:
        ended_at = ended_at.replace(tzinfo=timezone.utc)
    ended_utc = ended_at.astimezone(timezone.utc)
    cutoff_before = (ended_utc - timedelta(seconds=window_sec)).strftime(_COLLECTOR_TS_FMT)
    # +1s: the cutoff is truncated to whole seconds; the Python re-check is exact.
    cutoff_after = (ended_utc + timedelta(seconds=window_sec + 1)).strftime(_COLLECTOR_TS_FMT)
    try:
        rows = pg_conn.execute(
            f"""
            SELECT m.captured_at, ps.team_result
            FROM {pg_table} AS ps
            JOIN {matches_table} AS m ON m.match_id = ps.match_id
            WHERE ps.is_local_player = 1
              AND ps.champion_name = ?
              AND m.captured_at BETWEEN ? AND ?
            """,
            (champion, cutoff_before, cutoff_after),
        ).fetchall()
    except sqlite3.Error as e:
        return None, f"postgame query error: {e}"

    if not rows:
        return None, "no candidate"

    scored: list[tuple[float, str]] = []
    for cap_at, team_result in rows:
        cap_dt = _parse_iso(cap_at)
        if cap_dt is None:
            continue
        delta = abs((cap_dt - ended_utc).total_seconds())
        if delta > window_sec:
            continue
        scored.append((delta, team_result if isinstance(team_result, str) else ""))

    if not scored:
        return None, "no parseable captured_at in window"

    scored.sort(key=lambda x: x[0])
    closest_delta, closest_result = scored[0]

    if len(scored) > 1:
        second_delta, second_result = scored[1]
        # Ambiguity: two candidates within 5s of each other, different results.
        if abs(second_delta - closest_delta) < 5.0 and second_result != closest_result:
            return None, f"ambiguous: {closest_result} vs {second_result}"

    result_upper = closest_result.strip().upper()
    if result_upper == "WIN":
        return 1, "matched"
    if result_upper == "LOSS":
        return 0, "matched"
    return None, f"unexpected team_result {closest_result!r}"


def _postgame_ro_uri() -> str:
    """Read-only SQLite URI for POSTGAME_DB.

    ``Path.as_uri`` percent-encodes '#', '?' and '%', which a hand-built
    ``f"file:{path}?mode=ro"`` let SQLite read as URI syntax (a '#' in any
    parent directory silently opened a different, truncated path).
    """
    return Path(POSTGAME_DB).resolve().as_uri() + "?mode=ro"


def reconcile_mode(mode: str) -> dict[str, Any]:
    """Scan one mode DB and patch win on all live-phase3 rows where
    we can find an authoritative postgame match. Returns a summary.

    Summary keys on a completed scan: ``mode``, ``scanned``, ``patched``,
    ``skipped_no_match``, ``skipped_ambig``, ``skipped_error`` (postgame
    query failed - logged) and ``skipped_bad_ended_at``. A skipped mode
    returns ``skipped`` + ``reason``; an sqlite failure returns ``error``
    with ``patched`` 0 and ``rolled_back`` True.
    """
    pg_table = _MODE_TO_POSTGAME_TABLE.get(mode) if isinstance(mode, str) else None
    if pg_table is None:
        return {"mode": mode, "skipped": True, "reason": "no postgame mapping"}
    mode_db = Path(MODE_DB_DIR) / f"{mode}.db"
    if not mode_db.exists():
        return {"mode": mode, "skipped": True, "reason": "mode DB missing"}
    if not Path(POSTGAME_DB).exists():
        return {"mode": mode, "skipped": True, "reason": "postgame_stats.db missing"}

    patched = 0
    skipped_no_match = 0
    skipped_ambig = 0
    skipped_error = 0
    skipped_bad_ended = 0
    scanned = 0
    first_error = ""

    try:
        with closing(sqlite3.connect(mode_db)) as mode_conn, \
                closing(sqlite3.connect(_postgame_ro_uri(), uri=True)) as pg_conn:
            # No explicit rollback: an sqlite error skips the commit, and
            # closing() then closes the connection, which discards the open
            # transaction - the whole batch, never a half of it.
            rows = mode_conn.execute(
                """
                SELECT match_id, champion, ended_at
                FROM matches
                WHERE source = ? AND win IS NULL
                """,
                (LIVE_SOURCE_TAG,),
            ).fetchall()
            for mid, champion, ended_at_iso in rows:
                scanned += 1
                ended = _parse_iso(ended_at_iso)
                if ended is None:
                    skipped_bad_ended += 1
                    continue
                win_val, reason = _lookup_postgame_result(
                    pg_conn, pg_table, champion, ended, MATCH_WINDOW_SEC,
                )
                if win_val is None:
                    if reason.startswith("ambiguous"):
                        skipped_ambig += 1
                    elif reason.startswith("postgame query error"):
                        skipped_error += 1
                        first_error = first_error or reason
                    else:
                        skipped_no_match += 1
                    continue
                mode_conn.execute(
                    "UPDATE matches SET win = ? WHERE match_id = ? AND source = ? AND win IS NULL",
                    (win_val, mid, LIVE_SOURCE_TAG),
                )
                patched += 1
            mode_conn.commit()
    except sqlite3.Error as e:
        logger.warning("reconcile %s: sqlite error, batch rolled back: %s", mode, e)
        return {
            "mode": mode, "error": str(e), "scanned": scanned,
            "patched": 0, "rolled_back": True,
        }

    if first_error:
        logger.warning(
            "reconcile %s: %d row(s) not reconciled, %s",
            mode, skipped_error, first_error,
        )
    logger.info(
        "reconcile %s: scanned=%d patched=%d no_match=%d ambig=%d error=%d bad_ended_at=%d",
        mode, scanned, patched, skipped_no_match, skipped_ambig,
        skipped_error, skipped_bad_ended,
    )
    return {
        "mode": mode,
        "scanned": scanned,
        "patched": patched,
        "skipped_no_match": skipped_no_match,
        "skipped_ambig": skipped_ambig,
        "skipped_error": skipped_error,
        "skipped_bad_ended_at": skipped_bad_ended,
    }


def reconcile_all() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for mode in _MODE_TO_POSTGAME_TABLE:
        out[mode] = reconcile_mode(mode)
    return out
