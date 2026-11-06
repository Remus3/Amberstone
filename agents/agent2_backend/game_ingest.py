"""Live-match -> mode DB ingester.

Consumes ``game-summary`` tasks filed by the supervisor on game-end
transitions and inserts the corresponding row into the right mode DB.
This is what makes ``recency_30d`` populate - the rewind seed is all
>30 days old, so without this pipe no post-seed match ever reaches
Agent 4's analyzer.

Win/loss is inferred conservatively by ``_infer_win`` from the payload's
explicit ``win`` field or an unambiguous victory / defeat word; anything
else stays ``NULL`` (the analyzer skips null-win rows in every win-rate
aggregate, and ``win_reconcile`` patches them later from post-game data).

Trust boundary: the payload is copied from a coaching JSON and a rating
JSON RC wrote, but those files change shape, so every field is treated as
untrusted. A junk field is a skip (or a NULL column), never a raise; only
a real DB failure raises ``IngestError``. Timestamps are stored in UTC so
the started_at string comparisons the dedup and the reconciler run stay
ordered (true-audit s144t163).
"""
from __future__ import annotations

import json
import logging
import math
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("agent2.game_ingest")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
# RM-170: env-overridable so a test can point the mode DBs at a tmp dir.
# Default unchanged. All five modules that define this path read the SAME
# var, so an override cannot split schema-init from ingest.
DB_DIR = Path(os.environ.get("RC_PHASE3_DB_DIR") or (_PROJECT_ROOT / "data" / "db"))

SOURCE_TAG = "live-phase3"

# A game_time_s above this is not a game (and a large enough one overflows
# timedelta), so it is refused as junk rather than written.
_MAX_DURATION_SEC = 24 * 3600

# A finished_at year outside this band is junk and reads as "now".
_MIN_YEAR = 2000
_MAX_YEAR = 9000

# A kda component above this is junk (and above 2**63 - 1 it overflows the
# SQLite INTEGER bind, which raises OverflowError, not sqlite3.Error).
_MAX_KDA_COUNT = 10_000

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


def _select_mode_db(game_mode: Any) -> str | None:
    """Return mode-DB key (aram/arena/brawl/sr_ranked/sr_draft) or None.

    Only a string maps; surrounding whitespace and case are ignored.
    """
    if not isinstance(game_mode, str):
        return None
    key = game_mode.strip().upper()
    if not key:
        return None
    return GAME_MODE_TO_DB.get(key)


def _parse_iso_or_now(ts: Any) -> datetime:
    """Parse an ISO timestamp to an aware UTC datetime; else now (UTC).

    A naive timestamp is read as UTC (the supervisor stamps UTC, and
    ``win_reconcile`` reads a naive ``ended_at`` the same way); an offset
    one is converted, so every stored string carries ``+00:00``.
    """
    if isinstance(ts, str) and ts.strip():
        try:
            dt = datetime.fromisoformat(ts.strip().replace("Z", "+00:00"))
        except ValueError:
            dt = None
        # A year outside the plausible band is junk; it is also the only
        # way the UTC conversion or the start-time subtraction overflows.
        if dt is not None and _MIN_YEAR <= dt.year <= _MAX_YEAR:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
    return datetime.now(timezone.utc)


def _parse_duration(value: Any) -> int | None:
    """Return whole seconds for a ``game_time_s`` value, or None when junk.

    Accepts an int, a finite float or a numeric string. A bool, a
    non-finite or negative number, a non-numeric string and anything
    above ``_MAX_DURATION_SEC`` are junk. An absent value is 0, so the
    caller keeps its phantom-reconnect reason.
    """
    if value is None:
        return 0
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        try:
            value = float(value.strip())
        except ValueError:
            return None
    if not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value < 0 or value > _MAX_DURATION_SEC:
        return None
    return int(value)


_NO_CHAMPION = {"unknown", "none", "null"}
_MAX_CHAMPION_LEN = 64


def _clean_champion(value: Any) -> str | None:
    """Return the stripped champion name, or None when absent or junk.

    Junk = not a string, blank, a placeholder word, longer than
    ``_MAX_CHAMPION_LEN``, or holding a non-printable character. The
    printable test also refuses a lone surrogate (category Cs) from a
    JSON ``\\ud800`` escape, which would make the sqlite3 bind raise
    UnicodeEncodeError - not an sqlite3.Error, so it escaped the caller.
    """
    if not isinstance(value, str):
        return None
    name = value.strip()
    if not name or name.lower() in _NO_CHAMPION or len(name) > _MAX_CHAMPION_LEN:
        return None
    if not name.isprintable():
        return None
    return name


def _short_repr(value: Any) -> str:
    """A bounded repr for a skip reason that never raises."""
    try:
        text = repr(value)
    # ValueError: an int past the str-conversion digit limit;
    # RecursionError: a structure nested past the interpreter's limit.
    except (ValueError, RecursionError):
        text = f"<{type(value).__name__}>"
    return text if len(text) <= 80 else text[:77] + "..."


_WIN_STRINGS = {"victory", "win", "won"}
_LOSS_STRINGS = {"defeat", "loss", "lose", "lost"}


def _explicit_win(value: Any) -> int | None:
    """0 / 1 from an explicit win field, or None when it is not one."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, str):
        v = value.strip()
        return int(v) if v in ("0", "1") else None
    if isinstance(value, (int, float)) and value in (0, 1):
        return int(value)
    return None


def _infer_win(task_payload: dict[str, Any]) -> int | None:
    """Extract a win/loss int from the post-game payload strings.

    Priority order (first non-empty wins):
      1. explicit ``win`` field, only when it is 0 / 1 (bool, int, float
         or the strings "0" / "1"); any other value falls through
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
        resolved = _explicit_win(explicit)
        if resolved is not None:
            return resolved

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


def _count(value: Any) -> int | None:
    """A whole-number kda component in 0.._MAX_KDA_COUNT, or None."""
    if isinstance(value, bool):
        return None
    n: int | None = None
    if isinstance(value, str):
        v = value.strip()
        if v.isascii() and v.isdigit() and len(v) <= 6:
            n = int(v)
    elif isinstance(value, int):
        n = value
    elif isinstance(value, float):
        if math.isfinite(value) and value.is_integer():
            n = int(value)
    if n is None or n < 0 or n > _MAX_KDA_COUNT:
        return None
    return n


def _parse_kda(value: Any) -> tuple[int | None, int | None, int | None]:
    """Accept either the live-coach string form ``"10/3/15"`` or a dict
    ``{"k":10,"d":3,"a":15}``. Return ``(k,d,a)`` with Nones on parse
    failure. Never raises. A component must be a non-negative whole
    number; a bool, a fraction, a negative or a non-finite value is None.
    """
    if value is None:
        return (None, None, None)
    if isinstance(value, dict):
        def _g(*keys: str) -> int | None:
            for k in keys:
                c = _count(value.get(k))
                if c is not None:
                    return c
            return None
        return (_g("k", "kills"), _g("d", "deaths"), _g("a", "assists"))
    if isinstance(value, str):
        parts = value.strip().split("/")
        if len(parts) != 3:
            return (None, None, None)
        k, d, a = (_count(p) for p in parts)
        if k is None or d is None or a is None:
            return (None, None, None)
        return (k, d, a)
    return (None, None, None)


def _rating_json(fields: dict[str, Any]) -> str | None:
    """JSON text for the rating fields, never raising.

    Per top-level field: default=str stores a non-JSON value as its text;
    a field json still refuses (a dict key it cannot encode such as a
    tuple, a cycle, an int
    past the digit limit, nesting past the recursion limit) is stored as
    its bounded repr rather than raising past the IngestError contract.
    The object is joined from the per-field texts, so it adds no nesting
    level a field passed alone could then fail on. A NaN float is kept as
    Python's json does (``NaN``), which every RC reader (Python json)
    loads.
    """
    if not fields:
        return None
    parts: list[str] = []
    for k, v in fields.items():
        try:
            text = json.dumps(v, default=str)
        except (TypeError, ValueError, RecursionError):
            text = json.dumps(_short_repr(v))
        parts.append(f"{json.dumps(str(k))}: {text}")
    return "{" + ", ".join(parts) + "}"


def _already_ingested(
    conn: sqlite3.Connection,
    started_at: str,
    champion: str,
    duration_sec: int = 0,
) -> bool:
    """True when this game is already a row. A DB error propagates, so
    the caller turns it into ``IngestError`` instead of inserting a
    duplicate behind a swallowed query failure."""
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
        except ValueError:
            return False
        window_start = (dt - timedelta(minutes=90)).isoformat()
        row = conn.execute(
            """SELECT match_id FROM matches
               WHERE source=? AND champion=? AND started_at >= ? LIMIT 1""",
            (SOURCE_TAG, champion, window_start),
        ).fetchone()
        if row:
            return True
    return False


def ingest_game_summary(task_payload: Any) -> dict[str, Any]:
    """Insert the match described by ``task_payload`` into the right
    mode DB. Returns a result dict the dispatcher stores on the task.

    Never raises on ordinary skip conditions (not a dict, unknown mode,
    missing champion, junk duration, already ingested). Only raises
    ``IngestError`` on hard failures (a DB read or write error).
    """
    if not isinstance(task_payload, dict):
        return {
            "inserted": False,
            "reason": f"payload is not a dict ({type(task_payload).__name__})",
        }
    champion = _clean_champion(task_payload.get("champion"))
    game_mode_raw = (task_payload.get("game_mode")
                     or task_payload.get("mode_category") or "")
    mode_db = _select_mode_db(game_mode_raw)
    if mode_db is None:
        return {
            "inserted": False,
            "reason": f"unknown game_mode {_short_repr(game_mode_raw)}",
            "champion": champion or "Unknown",
        }
    if champion is None:
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

    duration_sec = _parse_duration(task_payload.get("game_time_s"))
    if duration_sec is None:
        return {
            "inserted": False,
            "reason": f"invalid game_time_s {_short_repr(task_payload.get('game_time_s'))}",
            "champion": champion,
        }
    if duration_sec == 0:
        return {
            "inserted": False,
            "reason": "zero-duration - phantom reconnect event",
            "champion": champion,
        }
    finished_at_dt = _parse_iso_or_now(task_payload.get("finished_at"))
    started_at_dt = finished_at_dt - timedelta(seconds=duration_sec)
    started_iso = started_at_dt.isoformat()
    ended_iso = finished_at_dt.isoformat()

    rating_fields: dict[str, Any] = {}
    for k in ("rating", "label", "stats", "notes", "mode_category"):
        if k in task_payload:
            rating_fields[k] = task_payload[k]
    rating_json = _rating_json(rating_fields)

    # Comp is usually unknown from the post-game summary (coach JSON
    # doesn't reliably carry full ally/enemy rosters). We insert the
    # tracked champion as the only known ally so the row is at least
    # parseable by the analyzer; matchup aggregation will simply not
    # see any enemy pairs for this row.
    ally_champs = [champion]
    enemy_champs: list[str] = []
    ec = task_payload.get("enemy_comp")
    if isinstance(ec, list):
        enemy_champs = [x.strip() for x in ec if isinstance(x, str) and x.strip()]

    k, d, a = _parse_kda(task_payload.get("kda"))
    win_signal = _infer_win(task_payload)

    try:
        # closing(): sqlite3's own context manager only commits or rolls
        # back; it never closes, so each ingest leaked a handle until GC.
        with closing(sqlite3.connect(db_path)) as conn, conn:
            conn.execute("PRAGMA foreign_keys = ON")
            if _already_ingested(conn, started_iso, champion, duration_sec=duration_sec):
                return {
                    "inserted": False,
                    "reason": "duplicate - already ingested",
                    "mode_db": mode_db,
                    "champion": champion,
                    "started_at": started_iso,
                }
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
                    duration_sec,
                    win_signal,
                    rating_json,
                    SOURCE_TAG,
                    k, d, a,
                ),
            )
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
        "duration_sec": duration_sec,
        "has_win_signal": win_signal is not None,
        "win": win_signal,
        "kda": {"k": k, "d": d, "a": a} if k is not None else None,
    }
