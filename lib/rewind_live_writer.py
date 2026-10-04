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
        (a 429 there instead reschedules, up to MAX_ID_RATE_LIMIT_RETRIES)
      - ``get_match`` returns None (404 / 403 / network / event mode
        like ARAM Mayhem queue 2400) -> abort silently
      - ``get_match`` / ``get_match_timeline`` rate-limited (429) after
        the in-thread bounded retry -> the match is parked in the
        ``fetch_retry`` table for the catchup drain, never recorded as a
        permanent has_timeline=0 (2026-09-20 fix)
      - Match already present in DB (operator played 2 games + cron
        ran between) -> skip
      - Very short game (gameDuration < ``MIN_DURATION_S`` = 180) ->
        skip (DC / remake; not meaningful sample)
      - DB write error -> rollback + log debug; never raises
  * Max wait wall (legacy unpinned path): 90s + 60s + 1 fetch round =
    ~150s. The pinned chain (below) runs 90s + sum(STAGED_DELAYS_S).
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

Target pinning (Y-01, external reference M - behaviour only):

  * DEFECT it fixes: the writer asked for ``count=1`` recent ids and took
    ``ids[0]``. When Match-V5 had not indexed the just-ended game inside the
    90 s delay, ``ids[0]`` was the PREVIOUS game, the PK probe found it and
    the writer returned ``already_present`` with no retry - the new game
    waited for the Sunday catchup while the status claimed success. After an
    ARAM Mayhem game (q2400, never served by Match-V5) ``ids[0]`` is always
    the last indexable game, so the event-mode branch almost never fired.
  * SEAM: ``app/_game_lifecycle.py`` is FROZEN and does not know the gameId at
    ``on_game_end`` time anyway - the LCU post-game collector reads it from the
    EOG block seconds later. So the collector publishes an atomic pin file
    (``write_game_end_pin`` -> ``ops/runtime/last_game_end.json``, gitignored
    because it carries the live Riot ID) and the writer reads it.
  * The writer builds ``<PLATFORM>_<gameId>`` with the platform from config
    (``core.operator_identity.platform``), never from the regional route, and
    makes staged attempts against THAT id on the fixed ``STAGED_DELAYS_S``
    schedule. The id is remembered from the first probe that resolved it and
    carried to every later attempt, so a newer game's pin cannot retarget a
    running chain. Not listed in recent ids / a 404 on detail = "not indexed
    yet, retry". ``already_present`` only when the TARGET itself is in the DB.
  * Only the LAST attempt may take a fallback: with no pin at all it runs the
    legacy unpinned path once (``fallback=True``); with a pin whose target
    never got indexed it parks the target in ``fetch_retry`` for the catchup.
  * q2400 / KIWI ends ``event_mode_excluded`` without any Riot call.
  * Concurrent chains are deduped by target id under ``_WRITE_LOCK``; pending
    Timers are capped at ``MAX_STAGED_TIMERS``, counted at accept time; every
    Timer is a daemon, so a restart only drops staged work the catchup picks
    up later.
  * LEDGER 357 FUTURE folded in: the pin also carries the live LCU Riot ID,
    resolved through Account-V1 ahead of the possibly-stale state PUUID.
"""

from __future__ import annotations

import json
import logging
import math
import os
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

# A 429 on the match-id fetch gets its OWN retry budget (rescheduled Timers,
# ``retry_after_s`` apart), separate from the single "not indexed yet /
# event mode" retry - a throttle says nothing about whether the match exists.
MAX_ID_RATE_LIMIT_RETRIES = 3

# Serializes DB writes across concurrent Timers (operator playing 2 games
# back-to-back inside the retry window). Match-V5 calls are already
# token-bucketed in core.riot_api; this lock guards the sqlite write block.
# It also guards the staged-Timer registry and the in-flight target map below.
_WRITE_LOCK = threading.Lock()

# -- Y-01 target pinning ----------------------------------------------------

# Written by lcu/lcu_postgame_collector.py through write_game_end_pin().
# ops/runtime/ is gitignored, which matters: the pin carries the Riot ID.
PIN_PATH = _PROJECT_ROOT / "ops" / "runtime" / "last_game_end.json"

# A pin older than (scheduled_at - PIN_SLACK_S) belongs to an EARLIER game.
# The collector writes it AFTER on_game_end schedules the chain (it waits for
# the EndOfGame phase first), so the slack only absorbs clock jitter; any real
# previous game ended at least one queue + load + game ago.
PIN_SLACK_S = 60.0

# Gaps between staged attempts, after the initial DEFAULT_DELAY_S. Our own
# derivation, not a measured indexing latency (that is the live-gated Step 0):
# the 300 s and 600 s steps sit at and beyond core/riot_api.py's 300 s
# not_found negative-cache TTL, so a 404 cached by an earlier attempt has
# expired before the later ones ask the wire again. Total wall ~19.5 min.
STAGED_DELAYS_S: tuple[float, ...] = (60.0, 120.0, 300.0, 600.0)

# Pending Timers allowed at once, counted when a Timer is ACCEPTED. A chain
# holds one pending Timer at a time and a game lasts longer than a chain's
# spacing, so 2 is the normal ceiling; 4 leaves room for a rate-limit retry.
MAX_STAGED_TIMERS = 4

# How many recent ids to scan for the target. The list call costs the same
# for 1 or 5, and 5 still finds the target if a newer game already ended.
RECENT_ID_WINDOW = 5

# Event modes Match-V5 never serves (Settled: 403/empty is EXPECTED).
EVENT_MODE_QUEUE_IDS = frozenset({2400})
EVENT_MODE_GAME_MODES = frozenset({"KIWI"})

_STAGED_TIMERS: list[Any] = []
_INFLIGHT_TARGETS: dict[str, str] = {}


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
    # RM-413 (RM-233 shape): read the adopted mode; warn, never raise.
    jm_row = conn.execute("PRAGMA journal_mode=WAL").fetchone()
    journal_mode = str(jm_row[0]).lower() if jm_row else "unknown"
    if journal_mode != "wal":
        _log.warning(
            "rewind_live_writer journal_mode fell back to %r (wanted wal): %s - "
            "concurrent readers WILL block writers on this database",
            journal_mode, DB_PATH)
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
    rate_limit_attempt: int = 0,
    backoff_s: tuple[float, ...] | None = None,
    sleep: Any = None,
    scheduled_at: float | None = None,
    chain: str | None = None,
    attempt: int = 0,
    pin: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Timer entry point. Never raises.

    ``scheduled_at`` set (every chain started by ``schedule_live_insert``)
    selects the Y-01 target-pinned staged path. Without it this is the legacy
    unpinned single fetch, kept for direct callers and as the last-attempt
    fallback when no pin ever appeared.
    """
    fetch_kw: dict[str, Any] = {}
    if backoff_s is not None:
        fetch_kw["backoff_s"] = backoff_s
    if sleep is not None:
        fetch_kw["sleep"] = sleep
    if scheduled_at is None:
        return _legacy_fetch_and_insert(
            is_retry=is_retry, retry_after_s=retry_after_s,
            rate_limit_attempt=rate_limit_attempt, fetch_kw=fetch_kw)

    chain_id = chain or f"chain-{scheduled_at!r}"
    try:
        result = _staged_attempt(
            scheduled_at=float(scheduled_at), chain=chain_id,
            attempt=int(attempt), pin=pin, retry_after_s=retry_after_s,
            fetch_kw=fetch_kw)
    except Exception as exc:  # noqa: BLE001 - never raise from a Timer
        _log.debug("rewind_live_writer staged attempt error: %s", exc)
        result = {"status": "error", "cause": "unexpected"}
        if isinstance(pin, dict) and pin.get("target_id"):
            result["match_id"] = pin["target_id"]
    status = str(result.get("status") or "")
    if not status.endswith("_retry_scheduled"):
        if status != "duplicate_target":
            _release_chain(chain_id)
        _log.info("rewind_live_writer: chain %s attempt %d ended %s (%s)",
                  chain_id, int(attempt), status,
                  result.get("match_id") or "no target")
    return result


# ---------------------------------------------------------------------------
# Y-01 pin file (written by the collector, read by the writer)
# ---------------------------------------------------------------------------

def write_game_end_pin(
    game_id: Any,
    *,
    queue_id: Any = None,
    game_mode: Any = "",
    riot_id: tuple[str, str] | None = None,
) -> bool:
    """Atomically publish the just-ended game's id for the live writer.

    Called by ``lcu/lcu_postgame_collector.py`` from the gameId it already
    reads off the EOG block. Returns False (never raises) on a non-numeric id
    or an OS error. ``riot_id`` is the live LCU ``(gameName, tagLine)``.
    """
    gid = str(game_id if game_id is not None else "").strip()
    if not gid.isdigit() or not gid.isascii():
        return False
    try:
        qid = int(queue_id) if queue_id not in (None, "") else None
    except (TypeError, ValueError, OverflowError):
        qid = None
    payload: dict[str, Any] = {
        "game_id": gid,
        "queue_id": qid,
        "game_mode": str(game_mode or "").strip().upper(),
        "game_name": "",
        "tag_line": "",
        "written_at": float(time.time()),
    }
    if riot_id and len(riot_id) == 2:
        payload["game_name"] = str(riot_id[0] or "").strip()
        payload["tag_line"] = str(riot_id[1] or "").strip()
    tmp = PIN_PATH.with_name(
        f"{PIN_PATH.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        PIN_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(PIN_PATH)
    except OSError as exc:
        _log.debug("rewind_live_writer pin write error: %s", exc)
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return False
    return True


def _read_game_end_pin(scheduled_at: float) -> dict[str, Any] | None:
    """The pin for THIS chain's game, or None (absent / stale / malformed)."""
    try:
        data = json.loads(PIN_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    gid = str(data.get("game_id") or "").strip()
    if not gid.isdigit() or not gid.isascii():
        return None
    try:
        written_at = float(data.get("written_at"))
    except (TypeError, ValueError):
        return None
    # NaN compares False against everything, so it would pass the age check
    # below; +inf would read as newer than every chain. Neither is a time.
    if not math.isfinite(written_at):
        return None
    if written_at < scheduled_at - PIN_SLACK_S:
        return None
    qid = data.get("queue_id")
    qid = qid if isinstance(qid, int) and not isinstance(qid, bool) else None
    name = str(data.get("game_name") or "").strip()
    tag = str(data.get("tag_line") or "").strip()
    from core import operator_identity
    return {
        "target_id": f"{operator_identity.platform()}_{gid}",
        "queue_id": qid,
        "game_mode": str(data.get("game_mode") or "").strip().upper(),
        "riot_id": [name, tag] if name and tag else None,
    }


def _is_event_mode(pin: dict[str, Any]) -> bool:
    return (pin.get("queue_id") in EVENT_MODE_QUEUE_IDS
            or pin.get("game_mode") in EVENT_MODE_GAME_MODES)


# ---------------------------------------------------------------------------
# Y-01 staging: Timer cap + per-target dedupe (both under _WRITE_LOCK)
# ---------------------------------------------------------------------------

def _timer_alive(t: Any) -> bool:
    try:
        return bool(t.is_alive())
    except Exception:  # noqa: BLE001 - a broken handle holds no slot
        return False


def _accept_timer(delay_s: float, kwargs: dict[str, Any]) -> bool:
    """Start a daemon Timer for the next attempt if under the cap.

    The cap is counted at ACCEPT time over Timers still pending. The Timer
    thread running this call is excluded: it is about to finish.
    """
    t = threading.Timer(delay_s, _do_live_fetch_and_insert, kwargs=kwargs)
    t.daemon = True
    with _WRITE_LOCK:
        me = threading.current_thread()
        _STAGED_TIMERS[:] = [x for x in _STAGED_TIMERS
                             if x is not me and _timer_alive(x)]
        if len(_STAGED_TIMERS) >= MAX_STAGED_TIMERS:
            _log.info("rewind_live_writer: %d staged Timers pending (cap); "
                      "not staging another", len(_STAGED_TIMERS))
            return False
        _STAGED_TIMERS.append(t)
    try:
        t.start()
    except RuntimeError as exc:
        # Process at shutdown can refuse new threads.
        _log.debug("rewind_live_writer schedule error: %s", exc)
        with _WRITE_LOCK:
            if t in _STAGED_TIMERS:
                _STAGED_TIMERS.remove(t)
        return False
    return True


def _claim_target(target: str, chain: str) -> bool:
    """First chain to resolve a target owns it; a second chain backs off."""
    with _WRITE_LOCK:
        owner = _INFLIGHT_TARGETS.get(target)
        if owner is not None and owner != chain:
            return False
        _INFLIGHT_TARGETS[target] = chain
        return True


def _release_chain(chain: str) -> None:
    with _WRITE_LOCK:
        for target in [t for t, c in _INFLIGHT_TARGETS.items() if c == chain]:
            del _INFLIGHT_TARGETS[target]


def _track_timer_for_tests(t: Any) -> None:
    with _WRITE_LOCK:
        _STAGED_TIMERS.append(t)


def _reset_staging_for_tests() -> None:
    with _WRITE_LOCK:
        _STAGED_TIMERS.clear()
        _INFLIGHT_TARGETS.clear()


def _park_target(rc: Any, match_id: str, reason: str) -> None:
    """Hand a target the live path could not finish to the catchup drain."""
    with _WRITE_LOCK:
        try:
            conn = _open_db()
            try:
                rc.enqueue_retry(conn, match_id, "match", reason)
                conn.commit()
            finally:
                conn.close()
        except (sqlite3.Error, OSError) as exc:
            _log.debug("rewind_live_writer park error: %s", exc)


def _resolve_puuid_for(pin: dict[str, Any], riot_api: Any) -> str | None:
    """Live LCU Riot ID (via Account-V1) first, then the catchup state.

    LEDGER 357 FUTURE: the state PUUID goes stale after an account switch
    until someone runs ``catchup --riot-id``; the live client already knows
    who is playing.
    """
    rid = pin.get("riot_id")
    if rid and len(rid) == 2:
        try:
            acct = riot_api.get_account_by_riot_id(
                rid[0], rid[1], region=REGION_REGIONAL)
        except Exception as exc:  # noqa: BLE001 - fall through to the state
            _log.debug("rewind_live_writer account lookup error: %s", exc)
            acct = None
        if isinstance(acct, dict):
            puuid = acct.get("puuid")
            if isinstance(puuid, str) and puuid:
                return puuid
    return _resolve_latest_puuid()


def _staged_attempt(
    *,
    scheduled_at: float,
    chain: str,
    attempt: int,
    pin: dict[str, Any] | None,
    retry_after_s: float,
    fetch_kw: dict[str, Any],
) -> dict[str, Any]:
    last = attempt >= len(STAGED_DELAYS_S)

    def _next(status: str, target: str | None, rc: Any = None,
              cause: str = "") -> dict[str, Any]:
        out: dict[str, Any] = {"status": status, "pinned": target is not None,
                               "attempt": attempt}
        if target:
            out["match_id"] = target
        if cause:
            out["cause"] = cause
        kwargs = {"retry_after_s": retry_after_s, "scheduled_at": scheduled_at,
                  "chain": chain, "attempt": attempt + 1, "pin": pin}
        if _accept_timer(STAGED_DELAYS_S[attempt], kwargs):
            return out
        out["status"] = "staged_cap_reached"
        if target and rc is not None:
            _park_target(rc, target, "live staged cap")
        return out

    if pin is None:
        pin = _read_game_end_pin(scheduled_at)
    if pin is None:
        if not last:
            return _next("awaiting_pin_retry_scheduled", None)
        # The ONLY fallback, and only on the last attempt: one unpinned
        # legacy fetch that stages nothing further.
        res = _legacy_fetch_and_insert(
            is_retry=True, retry_after_s=retry_after_s,
            rate_limit_attempt=MAX_ID_RATE_LIMIT_RETRIES, fetch_kw=fetch_kw)
        res["fallback"] = True
        res["pinned"] = False
        return res

    target = str(pin["target_id"])
    if _is_event_mode(pin):
        return {"status": "event_mode_excluded", "match_id": target,
                "pinned": True, "queue_id": pin.get("queue_id")}
    if not _claim_target(target, chain):
        return {"status": "duplicate_target", "match_id": target,
                "pinned": True}

    try:
        from core import riot_api
        from scripts import rewind_catchup as rc
    except ImportError as exc:
        _log.debug("rewind_live_writer import error: %s", exc)
        return {"status": "error", "cause": "import", "match_id": target}
    if not riot_api.is_configured():
        return {"status": "no_api_key", "match_id": target}

    puuid = _resolve_puuid_for(pin, riot_api)
    if puuid is None:
        return {"status": "no_puuid", "match_id": target}

    try:
        conn = _open_db()
    except (sqlite3.Error, OSError) as exc:
        _log.debug("rewind_live_writer open_db error: %s", exc)
        return {"status": "error", "cause": "open_db", "match_id": target}
    try:
        if _match_already_present(conn, target):
            return {"status": "already_present", "match_id": target,
                    "pinned": True}
    finally:
        try:
            conn.close()
        except sqlite3.Error:
            pass

    def _not_indexed(cause: str) -> dict[str, Any]:
        if not last:
            return _next("not_indexed_retry_scheduled", target, rc, cause)
        _park_target(rc, target, f"live target not indexed ({cause})")
        return {"status": "target_not_indexed", "match_id": target,
                "pinned": True, "cause": cause}

    with riot_api.track_outcomes() as id_scope:
        ids = riot_api.get_recent_matches(
            puuid, count=RECENT_ID_WINDOW, region=REGION_REGIONAL)
    if not isinstance(ids, list) or target not in ids:
        return _not_indexed("ids_rate_limited" if id_scope.rate_limited
                            else "not_listed")

    detail_outcomes: list[str] = []
    res = _hydrate_and_write(target, riot_api, rc, fetch_kw, detail_outcomes)
    if res.get("status") == "no_detail" and (
            not detail_outcomes or "not_found" in detail_outcomes):
        # Listed but 404 (or a cached 404 that recorded nothing): Match-V5
        # has the id before the detail. Not indexed yet - retry.
        return _not_indexed("detail_404")
    res["pinned"] = True
    return res


# ---------------------------------------------------------------------------
# Legacy unpinned path (direct callers + the last-attempt fallback)
# ---------------------------------------------------------------------------

def _legacy_fetch_and_insert(
    *,
    is_retry: bool,
    retry_after_s: float,
    rate_limit_attempt: int,
    fetch_kw: dict[str, Any],
) -> dict[str, Any]:
    """Fetch the most recent Match-V5 detail + timeline and write to DB.

    Returns a status dict for test assertions:
      ``status`` one of: ``no_puuid``, ``no_api_key``, ``no_id``,
        ``already_present``, ``no_detail``, ``short_game``, ``ok``,
        ``error``, ``retry_scheduled``, ``rate_limited_retry_scheduled``,
        ``rate_limited``, ``detail_rate_limited``.
      ``match_id``: present when an id was resolved.
      ``duration_s``: present when detail was fetched.
      ``timeline_status``: on ``ok`` - FETCH_OK / FETCH_ABSENT /
        FETCH_RATE_LIMITED (the last means the match is parked in
        ``fetch_retry`` for the catchup to finish, NOT a permanent 0).

    Never raises. Two bounded rescheduling budgets: the 1-shot "empty id
    list" retry (is_retry) and, separately, up to MAX_ID_RATE_LIMIT_RETRIES
    reschedules when the id fetch was rate-limited (rate_limit_attempt).
    Detail/timeline 429s get an in-thread bounded retry and are then parked
    in the ``fetch_retry`` table rather than recorded as absent.
    """
    puuid = _resolve_latest_puuid()
    if puuid is None:
        return {"status": "no_puuid"}

    # Lazy import - keeps module load light + avoids pulling riot_api at
    # RC process boot (the module is loaded on-demand from on_game_end).
    try:
        from core import riot_api
        from scripts import rewind_catchup as rc
    except ImportError as exc:
        _log.debug("rewind_live_writer import error: %s", exc)
        return {"status": "error", "cause": "import"}

    if not riot_api.is_configured():
        return {"status": "no_api_key"}

    # Fetch the 1 most-recent match id for the operator.
    with riot_api.track_outcomes() as id_scope:
        ids = riot_api.get_recent_matches(
            puuid,
            count=1,
            region=REGION_REGIONAL,
        )
    if not ids and id_scope.rate_limited:
        # Throttled, not "not indexed yet": its own bounded budget, and it
        # does not consume the event-mode retry below.
        if rate_limit_attempt >= MAX_ID_RATE_LIMIT_RETRIES:
            _log.info("rewind_live_writer: match-id fetch still rate-limited "
                      "after %d retries; the catchup cron will pick it up",
                      rate_limit_attempt)
            return {"status": "rate_limited"}
        if not _accept_timer(retry_after_s, {
                "is_retry": is_retry,
                "retry_after_s": retry_after_s,
                "rate_limit_attempt": rate_limit_attempt + 1}):
            return {"status": "staged_cap_reached"}
        return {"status": "rate_limited_retry_scheduled"}
    if not ids:
        # Likely Match-V5 hasn't seen the just-ended game yet; schedule
        # a single retry. Event modes (ARAM Mayhem queue 2400) also
        # return None / empty here - those will silently abandon after
        # the retry (Match-V5 will continue to return empty / 403).
        if not is_retry:
            if not _accept_timer(retry_after_s, {
                    "is_retry": True,
                    "retry_after_s": retry_after_s,
                    "rate_limit_attempt": rate_limit_attempt}):
                return {"status": "staged_cap_reached"}
            return {"status": "retry_scheduled"}
        return {"status": "no_id"}

    match_id = ids[0]

    # PK probe before any further HTTP. OSError covers the mkdir inside
    # _open_db (audit cycle 10 - never-raises contract).
    try:
        conn = _open_db()
    except (sqlite3.Error, OSError) as exc:
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

    return _hydrate_and_write(match_id, riot_api, rc, fetch_kw, None)


def _hydrate_and_write(
    match_id: str,
    riot_api: Any,
    rc: Any,
    fetch_kw: dict[str, Any],
    detail_outcomes: list[str] | None,
) -> dict[str, Any]:
    """Detail + timeline fetch and the locked DB write for ONE match id.

    Shared by the legacy and the pinned path. ``detail_outcomes`` (when given)
    receives the raw outcome labels of the final detail attempt so the pinned
    path can tell a 404 (retry) from a 403 (no_detail).
    """
    # Fetch detail.
    detail, d_status = rc.fetch_with_rate_limit_retry(
        lambda: riot_api.get_match(match_id, region=REGION_REGIONAL),
        outcomes_out=detail_outcomes, **fetch_kw)
    if detail is None and d_status == rc.FETCH_RATE_LIMITED:
        # Park the whole match: a later live write for a newer game would
        # otherwise move the catchup window past this one for good.
        with _WRITE_LOCK:
            try:
                conn = _open_db()
                try:
                    rc.enqueue_retry(conn, match_id, "match", "live detail 429")
                    conn.commit()
                finally:
                    conn.close()
            except (sqlite3.Error, OSError) as exc:
                _log.debug("rewind_live_writer enqueue error: %s", exc)
        return {"status": "detail_rate_limited", "match_id": match_id}
    if detail is None:
        # 404 / 403 / network / event-mode-key-policy. Silent.
        return {"status": "no_detail", "match_id": match_id}

    info = detail.get("info") or {}
    # Audit cycle 10 (P2-W1-app-B): Match-V5 JSON boundary - a NaN/inf/
    # garbage gameDuration must keep the never-raises contract (int(NaN)
    # raised ValueError into the Timer thread pre-fix).
    try:
        duration_s = int(info.get("gameDuration") or 0)
    except (TypeError, ValueError, OverflowError):
        duration_s = 0
    if duration_s < MIN_DURATION_S:
        return {
            "status": "short_game",
            "match_id": match_id,
            "duration_s": duration_s,
        }

    # Fetch timeline. A 404/403 (event modes such as ARAM Mayhem) is a
    # permanent has_timeline=0; a persistent 429 writes has_timeline=0 AND
    # parks the match in fetch_retry (record_hydrated), so the catchup
    # finishes it instead of the 0 standing forever.
    timeline, t_status = rc.fetch_with_rate_limit_retry(
        lambda: riot_api.get_match_timeline(match_id, region=REGION_REGIONAL),
        **fetch_kw)

    # Write under the lock.
    with _WRITE_LOCK:
        try:
            conn = _open_db()
        except (sqlite3.Error, OSError) as exc:
            _log.debug("rewind_live_writer reopen_db error: %s", exc)
            return {
                "status": "error",
                "cause": "open_db",
                "match_id": match_id,
            }
        try:
            rc.record_hydrated(conn, match_id, detail, timeline, t_status)
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
        "rewind_live_writer wrote %s (duration=%ds, has_timeline=%d, "
        "timeline=%s)",
        match_id, duration_s, 1 if timeline else 0, t_status,
    )
    return {
        "status": "ok",
        "match_id": match_id,
        "duration_s": duration_s,
        "has_timeline": bool(timeline),
        "timeline_status": t_status,
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
    used. Y-01 considered passing the gameId through it and rejected that:
    at ``on_game_end`` time nothing on ``app`` knows the gameId yet (the
    LCU collector reads it off the EOG block seconds later), so the seam is
    the collector's pin file instead (``write_game_end_pin``).

    Every call starts a new target-pinned chain (``scheduled_at`` + a chain
    id); the Timer counts against ``MAX_STAGED_TIMERS``. Never raises.
    """
    try:
        now = float(time.time())
        _accept_timer(delay_s, {
            "is_retry": False,
            "retry_after_s": retry_after_s,
            "scheduled_at": now,
            "chain": f"chain-{now:.6f}-{threading.get_ident()}",
            "attempt": 0,
        })
    except Exception as exc:  # noqa: BLE001 - lifecycle must never see this
        _log.debug("rewind_live_writer schedule error: %s", exc)
