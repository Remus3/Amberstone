"""Win-signal reconciliation — postgame_stats.db → mode DBs.

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
  * Idempotent — only UPDATEs rows where win IS NULL.
  * Per-row confidence check: if multiple postgame rows are in-window,
    skip rather than guess.
  * Read-only to postgame_stats.db; write-only to the live-phase3 rows.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("agent2.win_reconcile")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
MODE_DB_DIR = _PROJECT_ROOT / "data" / "db"
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


def _parse_iso(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _lookup_postgame_result(
    pg_conn: sqlite3.Connection,
    pg_table: str,
    champion: str,
    ended_at: datetime,
    window_sec: int,
) -> tuple[int | None, str]:
    """Return (win_int, reason) for the best matching postgame row.

    Strategy:
      1. Filter to ``is_local_player=1`` and exact champion match.
      2. Keep rows whose ``captured_at`` is within ±window_sec.
      3. If exactly one candidate remains, use its ``team_result``.
      4. If 0 — return (None, "no candidate").
      5. If >1 — pick the row with captured_at closest to ended_at.
         If the two closest rows are within 5s of each other and have
         different team_result, bail out ("ambiguous").
    """
    cutoff_before = (ended_at - timedelta(seconds=window_sec)).isoformat()
    cutoff_after = (ended_at + timedelta(seconds=window_sec)).isoformat()
    try:
        rows = pg_conn.execute(
            f"""
            SELECT captured_at, team_result FROM {pg_table}
            WHERE is_local_player = 1
              AND champion_name = ?
              AND captured_at BETWEEN ? AND ?
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
        if cap_dt.tzinfo is None:
            cap_dt = cap_dt.replace(tzinfo=timezone.utc)
        delta = abs((cap_dt - ended_at).total_seconds())
        scored.append((delta, team_result or ""))

    if not scored:
        return None, "no parseable captured_at"

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


def reconcile_mode(mode: str) -> dict[str, Any]:
    """Scan one mode DB and patch win on all live-phase3 rows where
    we can find an authoritative postgame match. Returns a summary.
    """
    pg_table = _MODE_TO_POSTGAME_TABLE.get(mode)
    if pg_table is None:
        return {"mode": mode, "skipped": True, "reason": "no postgame mapping"}
    mode_db = MODE_DB_DIR / f"{mode}.db"
    if not mode_db.exists():
        return {"mode": mode, "skipped": True, "reason": "mode DB missing"}
    if not POSTGAME_DB.exists():
        return {"mode": mode, "skipped": True, "reason": "postgame_stats.db missing"}

    patched = 0
    skipped_no_match = 0
    skipped_ambig = 0
    scanned = 0

    try:
        with sqlite3.connect(mode_db) as mode_conn, \
                sqlite3.connect(f"file:{POSTGAME_DB}?mode=ro", uri=True) as pg_conn:
            cur = mode_conn.execute(
                """
                SELECT match_id, champion, ended_at
                FROM matches
                WHERE source = ? AND win IS NULL
                """,
                (LIVE_SOURCE_TAG,),
            )
            rows = cur.fetchall()
            for mid, champion, ended_at_iso in rows:
                scanned += 1
                ended = _parse_iso(ended_at_iso) or datetime.now(timezone.utc)
                if ended.tzinfo is None:
                    ended = ended.replace(tzinfo=timezone.utc)
                win_val, reason = _lookup_postgame_result(
                    pg_conn, pg_table, champion, ended, MATCH_WINDOW_SEC,
                )
                if win_val is None:
                    if "ambiguous" in reason:
                        skipped_ambig += 1
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
        return {"mode": mode, "error": str(e), "scanned": scanned, "patched": patched}

    logger.info(
        "reconcile %s: scanned=%d patched=%d no_match=%d ambig=%d",
        mode, scanned, patched, skipped_no_match, skipped_ambig,
    )
    return {
        "mode": mode,
        "scanned": scanned,
        "patched": patched,
        "skipped_no_match": skipped_no_match,
        "skipped_ambig": skipped_ambig,
    }


def reconcile_all() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for mode in _MODE_TO_POSTGAME_TABLE:
        out[mode] = reconcile_mode(mode)
    return out
