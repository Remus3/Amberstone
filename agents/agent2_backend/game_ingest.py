"""Live-match -> mode DB ingester.

Consumes ``game-summary`` tasks filed by the supervisor on game-end
transitions and inserts the corresponding row into the right mode DB.
This is what makes ``recency_30d`` populate - the rewind seed is all
>30 days old, so without this pipe no post-seed match ever reaches
Agent 4's analyzer.

Win/loss detection is deliberately left as ``NULL`` in this MVP: the
live coaching JSONs we can read from disk don't carry an authoritative
win flag, and inferring from rating grade would be noisy. The analyzer
correctly skips null-win rows from all win-rate aggregates, so the
inserted rows are benign until a follow-up wires real win capture.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("agent2.game_ingest")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_DIR = _PROJECT_ROOT / "data" / "db"

SOURCE_TAG = "live-phase3"

# game_mode string -> Phase 3 mode DB filename. Case-insensitive match.
# Mirrors the queue_id mapping from migration_rewind but keyed by the
# live coaching JSON's ``game_mode`` field (set by game_reader /
# coach_integration).
GAME_MODE_TO_DB = {
    "CLASSIC": "sr_ranked",      # default SR -> ranked; draft vs ranked
    "RANKED_SOLO": "sr_ranked",  #   can't be disambiguated from live data
    "RANKED_FLEX": "sr_ranked",
    "DRAFT": "sr_draft",
    "ARAM": "aram",
    "KIWI": "aram",              # ARAM Mayhem internal name
    "ARAM_UNRANKED_5X5": "aram",
    "ARAM_UNRANKED_5x5": "aram",
    "ARENA": "arena",
    "CHERRY": "arena",
    "NEXUSBLITZ": "brawl",
    "URF": "brawl",
    "ARURF": "brawl",
    "ONEFORALL": "brawl",
    "ULTBOOK": "brawl",
    "GAMEMODEX": "brawl",
}


class IngestError(RuntimeError):
    """Raised when the consumer can't make progress - caller should
    mark the task failed with this exception's message."""


def _select_mode_db(game_mode: str) -> str | None:
    """Return mode-DB key (aram/arena/brawl/sr_ranked/sr_draft) or None."""
    if not game_mode:
        return None
    return GAME_MODE_TO_DB.get(str(game_mode).upper())


def _parse_iso_or_now(ts: str | None) -> datetime:
    if ts:
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            pass
    return datetime.now(timezone.utc)


_WIN_STRINGS = {"victory", "win", "won"}
_LOSS_STRINGS = {"defeat", "loss", "lose", "lost"}


def _infer_win(task_payload: dict[str, Any]) -> int | None:
    """Extract a win/loss int from the post-game payload strings.

    Priority order (first non-empty wins):
      1. explicit ``win`` field (already an int) - already used upstream
      2. ``action``: coaching JSON's end-of-game marker ("Victory"/"Defeat")
      3. ``label``: rating JSON's grade label when it's a win/loss word
      4. ``stats.outcome`` / ``notes.outcome`` / nested strings

    Conservative - unknown / ambiguous values fall through to None, so
    the column stays NULL rather than recording a false positive. The
    analyzer skips NULL-win rows for win-rate aggregates.
    """
    # (1) explicit win - take precedence if caller already resolved it
    explicit = task_payload.get("win")
    if explicit is not None:
        try:
            return int(explicit)
        except (TypeError, ValueError):
            pass

    # (2)(3) direct string fields
    for key in ("action", "label", "outcome", "result"):
        raw = task_payload.get(key)
        if isinstance(raw, str):
            r = raw.strip().lower()
            if r in _WIN_STRINGS:
                return 1
            if r in _LOSS_STRINGS:
                return 0

    # (4) stats / notes dicts often carry a nested outcome
    for container_key in ("stats", "notes"):
        container = task_payload.get(container_key)
        if isinstance(container, dict):
            for sub in ("outcome", "result", "win"):
                v = container.get(sub)
                if isinstance(v, str):
                    r = v.strip().lower()
                    if r in _WIN_STRINGS:
                        return 1
                    if r in _LOSS_STRINGS:
                        return 0
                elif isinstance(v, bool):
                    return int(v)
                elif isinstance(v, (int, float)):
                    if v in (0, 1):
                        return int(v)
    return None


def _parse_kda(value: Any) -> tuple[int | None, int | None, int | None]:
    """Accept either the live-coach string form ``"10/3/15"`` or a dict
    ``{"k":10,"d":3,"a":15}``. Return ``(k,d,a)`` with Nones on parse
    failure. Never raises.
    """
    if value is None:
        return (None, None, None)
    if isinstance(value, dict):
        def _g(*keys: str) -> int | None:
            for k in keys:
                v = value.get(k)
                if v is None:
                    continue
                try:
                    return int(v)
                except (TypeError, ValueError):
                    continue
            return None
        return (_g("k", "kills"), _g("d", "deaths"), _g("a", "assists"))
    if isinstance(value, str):
        parts = value.strip().split("/")
        if len(parts) != 3:
            return (None, None, None)
        try:
            return (int(parts[0]), int(parts[1]), int(parts[2]))
        except ValueError:
            return (None, None, None)
    return (None, None, None)


def _already_ingested(
    conn: sqlite3.Connection,
    started_at: str,
    champion: str,
    duration_sec: int = 0,
) -> bool:
    # Exact-match dedup (original behaviour).
    row = conn.execute(
        "SELECT match_id FROM matches WHERE source=? AND started_at=? AND champion=? LIMIT 1",
        (SOURCE_TAG, started_at, champion),
    ).fetchone()
    if row:
        return True
    # Window dedup: short summaries (< 120s) created by disconnect/reconnect
    # polling look like a new game but are phantom entries for an ongoing one.
    # If a match for the same champion already exists within the past 90 minutes,
    # treat the short entry as a duplicate.
    if duration_sec < 120:
        try:
            dt = datetime.fromisoformat(started_at)
            window_start = (dt - timedelta(minutes=90)).isoformat()
            row = conn.execute(
                """SELECT match_id FROM matches
                   WHERE source=? AND champion=? AND started_at >= ? LIMIT 1""",
                (SOURCE_TAG, champion, window_start),
            ).fetchone()
            if row:
                return True
        except Exception:
            pass
    return False


def ingest_game_summary(task_payload: dict[str, Any]) -> dict[str, Any]:
    """Insert the match described by ``task_payload`` into the right
    mode DB. Returns a result dict the dispatcher stores on the task.

    Never raises on ordinary skip conditions (unknown mode, already
    ingested, no champion). Only raises ``IngestError`` on hard failures
    (DB write error).
    """
    champion = task_payload.get("champion") or "Unknown"
    game_mode_raw = (task_payload.get("game_mode")
                     or task_payload.get("mode_category") or "")
    mode_db = _select_mode_db(game_mode_raw)
    if mode_db is None:
        return {
            "inserted": False,
            "reason": f"unknown game_mode {game_mode_raw!r}",
            "champion": champion,
        }
    if not champion or champion == "Unknown":
        return {
            "inserted": False,
            "reason": "missing champion",
        }

    db_path = DB_DIR / f"{mode_db}.db"
    if not db_path.exists():
        return {
            "inserted": False,
            "reason": f"mode DB missing: {db_path.name}",
        }

    finished_at_dt = _parse_iso_or_now(task_payload.get("finished_at"))
    duration_sec = int(task_payload.get("game_time_s") or 0)
    if duration_sec == 0:
        return {
            "inserted": False,
            "reason": "zero-duration - phantom reconnect event",
            "champion": champion,
        }
    started_at_dt = finished_at_dt - timedelta(seconds=duration_sec)
    started_iso = started_at_dt.isoformat()
    ended_iso = finished_at_dt.isoformat()

    rating_fields: dict[str, Any] = {}
    for k in ("rating", "label", "stats", "notes", "mode_category"):
        if k in task_payload:
            rating_fields[k] = task_payload[k]

    # Comp is usually unknown from the post-game summary (coach JSON
    # doesn't reliably carry full ally/enemy rosters). We insert the
    # tracked champion as the only known ally so the row is at least
    # parseable by the analyzer; matchup aggregation will simply not
    # see any enemy pairs for this row.
    ally_champs = [champion]
    enemy_champs: list[str] = []
    try:
        ec = task_payload.get("enemy_comp")
        if isinstance(ec, list):
            enemy_champs = [str(x) for x in ec if isinstance(x, str) and x]
    except Exception:    # noqa: BLE001
        enemy_champs = []

    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            if _already_ingested(conn, started_iso, champion, duration_sec=duration_sec):
                return {
                    "inserted": False,
                    "reason": "duplicate - already ingested",
                    "mode_db": mode_db,
                    "champion": champion,
                    "started_at": started_iso,
                }
            k, d, a = _parse_kda(task_payload.get("kda"))
            win_signal = _infer_win(task_payload)
            cur = conn.execute(
                """
                INSERT INTO matches
                  (started_at, ended_at, champion, ally_champions, enemy_champions,
                   duration_sec, win, final_rating_json, source,
                   kills, deaths, assists)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    started_iso,
                    ended_iso,
                    champion,
                    json.dumps(ally_champs),
                    json.dumps(enemy_champs),
                    duration_sec or None,
                    win_signal,
                    json.dumps(rating_fields) if rating_fields else None,
                    SOURCE_TAG,
                    k, d, a,
                ),
            )
            conn.commit()
            match_id = cur.lastrowid
    except sqlite3.Error as e:
        raise IngestError(f"DB write failed: {e}") from e

    logger.info(
        "live-match ingested: mode=%s champ=%s match_id=%s duration=%ss",
        mode_db, champion, match_id, duration_sec,
    )
    return {
        "inserted": True,
        "mode_db": mode_db,
        "champion": champion,
        "match_id": match_id,
        "started_at": started_iso,
        "ended_at": ended_iso,
        "duration_sec": duration_sec or None,
        "has_win_signal": win_signal is not None,
        "win": win_signal,
        "kda": {"k": k, "d": d, "a": a} if k is not None else None,
    }
