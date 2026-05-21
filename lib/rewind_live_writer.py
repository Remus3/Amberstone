"""
lib/rewind_live_writer.py
-------------------------

Live write of post-gameEnd match detail + timeline into
``data/rewind_history.db`` so the operator's "what did I just play"
surface is fresh shortly after the game ends, without waiting for the
weekly Sunday 04:00 ``RC-RewindCatchup`` cron.

Design contract (item 119, frozen-file grant headless-upgrade run):

  * Public API: ``schedule_live_insert(app)`` - non-blocking; spawns a
    daemon ``threading.Timer`` that fires after ``delay_s`` (default
    90s). RC process exit does NOT wait for the Timer because
    ``Timer`` inherits ``Thread(daemon=True)`` semantics when its
    ``.daemon = True`` flag is set explicitly.
  * Hook point: ``app/_game_lifecycle.py::on_game_end()`` (frozen)
    invokes ``schedule_live_insert(app)`` AFTER the existing
    ``_pgc.trigger(_gm)`` block; the wire is a 1-line import + call
    wrapped in its own try/except so any exception is logged + swallowed
    and never bubbles into the lifecycle.
  * Match-V5 detail + timeline + INSERT OR IGNORE into the same 5-table
    schema (matches / participants / teams / timeline_frames /
    timeline_events) using the canonical write fn shared with
    ``scripts/rewind_catchup.py::write_match()`` - which itself reuses
    ``scripts/rewind_scraper.py::insert_rows()``. Idempotency is
    guaranteed at the ``matches.match_id PRIMARY KEY`` boundary by
    INSERT OR IGNORE.
  * Failure modes - ALL silent (the lifecycle keeps moving even when
    the live write can't happen):
      - PUUID file missing / malformed -> abort
      - Match-V5 ``get_recent_matches`` returns None or empty -> 1
        retry after ``retry_after_s`` (default 60s), then abandon
      - ``get_match`` returns None (404 / 403 / network / event mode
        like ARAM Mayhem queue 2400) -> abort silently
      - Match already present in DB (operator played 2 games + cron
        ran between) -> skip
      - Very short game (gameDuration < ``MIN_DURATION_S`` = 180) ->
        skip (DC / remake; not meaningful sample)
      - DB write error -> rollback + log debug; never raises
  * Max wait wall: 90s + 60s + 1 fetch round = ~150s.
  * Thread-safety: a single module-scoped ``_WRITE_LOCK`` (re-entrant
    via ``threading.Lock`` - the writer never re-locks itself)
    serializes DB writes. Match-V5 ``_call()`` is already token-bucketed
    by ``core/riot_api.py``.
  * Cancelable: the live-side does not provide a public cancel hook.
    The cron writer is idempotent against this writer so a race is
    benign (last-writer-no-ops via INSERT OR IGNORE).

Constraints the design respects:

  * Reuses ``scripts/rewind_catchup.py::write_match`` verbatim - no
    duplication of the 5-table normalize logic.
  * Reads PUUID from ``data/rewind_catchup.state.json`` (written by
    the weekly cron) - if the cron has never run, this writer is inert
    by design; the cron is the bootstrap.
  * Uses ``threading.Timer`` (not ``threading.Thread``) per design
    decision: Timer cleans up after firing without needing manual join,
    and its delay is the model fit for "fire 90s after gameEnd".
  * Pure stdlib; no new requirements pinned.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

_log = logging.getLogger("rc.lib.rewind_live_writer")

# ---------------------------------------------------------------------------
# Paths + constants
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = _PROJECT_ROOT / "data" / "rewind_history.db"
STATE_PATH = _PROJECT_ROOT / "data" / "rewind_catchup.state.json"

REGION_REGIONAL = "americas"

# Filter out DCs / remakes - matches the operator's "real games" intuition.
# 3 min is the Riot remake threshold; sub-3-min games carry no useful timeline.
MIN_DURATION_S = 180

# Default schedule (seconds).
DEFAULT_DELAY_S = 90.0
DEFAULT_RETRY_AFTER_S = 60.0

# Serializes DB writes across concurrent Timers (operator playing 2 games
# back-to-back inside the retry window). Match-V5 calls are already
# token-bucketed in core.riot_api; this lock guards the sqlite write block.
_WRITE_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# PUUID + DB helpers
# ---------------------------------------------------------------------------

def _resolve_latest_puuid() -> str | None:
    """Read the operator's current PUUID from the catchup state sentinel.

    Returns None silently if the file is missing or malformed - this is
    the documented "abort silently" path. The weekly catchup cron writes
    this file via ``scripts/rewind_catchup.py::save_state``; without at
    least one prior cron run we have no PUUID to query Match-V5 with.
    """
    try:
        if not STATE_PATH.exists():
            return None
        raw = STATE_PATH.read_text(encoding="utf-8")
        if not raw.strip():
            return None
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    puuid = data.get("puuid")
    if not isinstance(puuid, str) or not puuid:
        return None
    return puuid


def _match_already_present(conn: sqlite3.Connection, match_id: str) -> bool:
    """True if the match_id is already in the matches table.

    Cheap PK probe - no SELECT count(*) needed; INSERT OR IGNORE would
    eventually no-op, but checking up front lets us skip the Match-V5
    detail+timeline fetch entirely (saves 2 HTTP round-trips + 1 rate
    bucket token each).
    """
    try:
        row = conn.execute(
            "SELECT 1 FROM matches WHERE match_id = ? LIMIT 1",
            (match_id,),
        ).fetchone()
    except sqlite3.Error:
        return False
    return row is not None


def _open_db() -> sqlite3.Connection:
    """Open ``rewind_history.db`` with the same PRAGMAs the cron uses.

    Mirrors ``scripts/rewind_catchup.py::open_db()`` for behavior parity.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ---------------------------------------------------------------------------
# Core work fn (testable; returns a status dict)
# ---------------------------------------------------------------------------

def _do_live_fetch_and_insert(
    *,
    is_retry: bool = False,
    retry_after_s: float = DEFAULT_RETRY_AFTER_S,
) -> dict[str, Any]:
    """Fetch the most recent Match-V5 detail + timeline and write to DB.

    Returns a status dict for test assertions:
      ``status`` one of: ``no_puuid``, ``no_api_key``, ``no_id``,
        ``already_present``, ``no_detail``, ``short_game``, ``ok``,
        ``error``, ``retry_scheduled``.
      ``match_id``: present when an id was resolved.
      ``duration_s``: present when detail was fetched.

    Never raises. The 1-shot retry path is the only branch that
    schedules another Timer; the second attempt receives is_retry=True
    so it cannot recursively schedule a third.
    """
    puuid = _resolve_latest_puuid()
    if puuid is None:
        return {"status": "no_puuid"}

    # Lazy import - keeps module load light + avoids pulling riot_api at
    # RC process boot (the module is loaded on-demand from on_game_end).
    try:
        from core import riot_api
        from scripts.rewind_catchup import write_match
    except ImportError as exc:
        _log.debug("rewind_live_writer import error: %s", exc)
        return {"status": "error", "cause": "import"}

    if not riot_api.is_configured():
        return {"status": "no_api_key"}

    # Fetch the 1 most-recent match id for the operator.
    ids = riot_api.get_recent_matches(
        puuid,
        count=1,
        region=REGION_REGIONAL,
    )
    if not ids:
        # Likely Match-V5 hasn't seen the just-ended game yet; schedule
        # a single retry. Event modes (ARAM Mayhem queue 2400) also
        # return None / empty here - those will silently abandon after
        # the retry (Match-V5 will continue to return empty / 403).
        if not is_retry:
            try:
                t = threading.Timer(
                    retry_after_s,
                    _do_live_fetch_and_insert,
                    kwargs={"is_retry": True, "retry_after_s": retry_after_s},
                )
                t.daemon = True
                t.start()
            except RuntimeError as exc:
                _log.debug("rewind_live_writer retry-schedule error: %s", exc)
            return {"status": "retry_scheduled"}
        return {"status": "no_id"}

    match_id = ids[0]

    # PK probe before any further HTTP.
    try:
        conn = _open_db()
    except sqlite3.Error as exc:
        _log.debug("rewind_live_writer open_db error: %s", exc)
        return {"status": "error", "cause": "open_db", "match_id": match_id}

    try:
        if _match_already_present(conn, match_id):
            return {"status": "already_present", "match_id": match_id}
    finally:
        # Re-open for the actual write below if needed - keeps connection
        # lifetime tight + matches the cron's per-match conn pattern.
        try:
            conn.close()
        except sqlite3.Error:
            pass

    # Fetch detail.
    detail = riot_api.get_match(match_id, region=REGION_REGIONAL)
    if detail is None:
        # 404 / 403 / network / event-mode-key-policy. Silent.
        return {"status": "no_detail", "match_id": match_id}

    info = detail.get("info") or {}
    duration_s = int(info.get("gameDuration") or 0)
    if duration_s < MIN_DURATION_S:
        return {
            "status": "short_game",
            "match_id": match_id,
            "duration_s": duration_s,
        }

    # Fetch timeline (may legitimately be None for event modes; the
    # cron's write_match handles None timeline by setting has_timeline=0).
    timeline = riot_api.get_match_timeline(match_id, region=REGION_REGIONAL)

    # Write under the lock.
    with _WRITE_LOCK:
        try:
            conn = _open_db()
        except sqlite3.Error as exc:
            _log.debug("rewind_live_writer reopen_db error: %s", exc)
            return {
                "status": "error",
                "cause": "open_db",
                "match_id": match_id,
            }
        try:
            write_match(conn, match_id, detail, timeline)
            conn.commit()
        except sqlite3.Error as exc:
            _log.debug("rewind_live_writer write error: %s", exc)
            try:
                conn.rollback()
            except sqlite3.Error:
                pass
            return {
                "status": "error",
                "cause": "write",
                "match_id": match_id,
            }
        except Exception as exc:  # noqa: BLE001 - never raise from live path
            # write_match calls into parse_participant / parse_team etc;
            # those are resilient but any unforeseen shape break must
            # not bubble up.
            _log.debug("rewind_live_writer unexpected error: %s", exc)
            return {
                "status": "error",
                "cause": "unexpected",
                "match_id": match_id,
            }
        finally:
            try:
                conn.close()
            except sqlite3.Error:
                pass

    _log.info(
        "rewind_live_writer wrote %s (duration=%ds, has_timeline=%d)",
        match_id, duration_s, 1 if timeline else 0,
    )
    return {
        "status": "ok",
        "match_id": match_id,
        "duration_s": duration_s,
        "has_timeline": bool(timeline),
    }


# ---------------------------------------------------------------------------
# Public scheduling API
# ---------------------------------------------------------------------------

def schedule_live_insert(
    app: Any,  # noqa: ARG001 - unused; reserved for future per-app context
    *,
    delay_s: float = DEFAULT_DELAY_S,
    retry_after_s: float = DEFAULT_RETRY_AFTER_S,
) -> None:
    """Schedule a fire-and-forget live write 90s after gameEnd.

    Non-blocking by contract: spawns a ``threading.Timer`` (daemon) and
    returns immediately. The 90s delay gives Match-V5 + riotgames.com
    time to index the just-ended match; the documented internal latency
    is 30-60s but 90 is a comfortable buffer that still keeps the
    operator's "just played" surface fresh.

    ``app`` is accepted as the design's standard hook seam but is not
    used today - the writer self-contains its dependencies. Reserved
    so future call sites can pass per-app context (queue id hints,
    spectator mode flag, etc.) without changing the wire.
    """
    try:
        t = threading.Timer(
            delay_s,
            _do_live_fetch_and_insert,
            kwargs={"is_retry": False, "retry_after_s": retry_after_s},
        )
        t.daemon = True
        t.start()
    except RuntimeError as exc:
        # Process at shutdown can refuse new threads.
        _log.debug("rewind_live_writer schedule error: %s", exc)
