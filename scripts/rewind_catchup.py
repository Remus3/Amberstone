"""
scripts/rewind_catchup.py
-------------------------
Catches rewind_history.db up to the present using the official Riot Web API
(via core/riot_api.py).

Why this exists: the original rewind.lol scraper (rewind_scraper.py) lost
the upstream feed mid-2025. FU04 (2026-05-09) approved a Personal-tier
Riot API key, so we can now pull our own match history straight from
Match-V5. This script paginates ``/lol/match/v5/matches/by-puuid/{puuid}/ids``
forward from the newest ``game_creation_ts`` in the DB, fetches detail +
timeline for each missing match, and writes into the existing 5-table
schema (matches, participants, teams, timeline_frames, timeline_events).

Idempotent + resumable:
  * INSERT OR IGNORE on all writes - existing rows survive.
  * Progress sentinel at ``data/rewind_catchup.state.json`` records the
    last seen ``game_creation_ts`` and next page cursor; safe to Ctrl+C
    and re-run.
  * Token bucket from core.riot_api throttles to Personal-tier headline
    (20/s + 100/2min) with 429 cooldown.

Usage:
  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe scripts\\rewind_catchup.py                # full catch-up
  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe scripts\\rewind_catchup.py --limit 50     # ceiling on detail fetches
  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe scripts\\rewind_catchup.py --puuid X      # override operator PUUID
  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe scripts\\rewind_catchup.py --dry-run      # list IDs only, no writes
  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe scripts\\rewind_catchup.py --no-timeline  # skip timeline (faster)
  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe scripts\\rewind_catchup.py --retry-only   # drain 429-parked matches only

A Riot 429 is never recorded as "no data": a match whose detail or timeline
stays rate-limited is parked in the ``fetch_retry`` table and re-fetched by
every later run (see drain_retry_queue).
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
import time
from pathlib import Path

# Make `core` importable when run as a script.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import riot_api  # noqa: E402
from scripts.rewind_scraper import (  # noqa: E402
    insert_rows,
    parse_event,
    parse_frame,
    parse_participant,
    parse_team,
)

_log = logging.getLogger("rc.scripts.rewind_catchup")

DB_PATH = ROOT / "data" / "rewind_history.db"
STATE_PATH = ROOT / "data" / "rewind_catchup.state.json"

REGION_REGIONAL = "americas"  # Match-V5 lives on the regional cluster

# How far back to look on first run if the DB has no rows at all.
# Cold-start should not happen (DB has 2846 rows); guardrail only.
COLD_START_DAYS = 30
COLD_START_SECS = COLD_START_DAYS * 86400

# --- 429 handling ------------------------------------------------------
#
# Every Match-V5 helper returns a bare None for BOTH "Riot has no such
# resource" (404/403 - permanent) and "Riot rate-limited us" (429 - ask
# again later). Reading that None as "no data" wrote a 429 into the DB as
# has_timeline=0 for good, because nothing revisits a written match. The
# fix reads riot_api.track_outcomes().rate_limited to tell them apart,
# retries a 429 a bounded number of times in-call, and if it persists
# parks the match in the ``fetch_retry`` table, which drain_retry_queue()
# works off on later runs (bounded again, by MAX_RETRY_RUNS).
#
# Event-mode matches (ARAM Mayhem, queue 2400 / gameMode KIWI) have NO
# Match-V5 timeline: Riot answers 403/404, which is FETCH_ABSENT, so their
# has_timeline=0 stays - it is the correct, permanent answer.

FETCH_OK = "ok"
FETCH_ABSENT = "absent"
FETCH_RATE_LIMITED = "rate_limited"

# Seconds to wait before each in-call re-attempt after a 429. The bucket in
# core.riot_api already enforces the Retry-After cooldown; these waits keep
# the next attempt from spending itself inside that same cooldown.
DEFAULT_BACKOFF_S: tuple[float, ...] = (5.0, 20.0)

# How many catchup runs may see a parked match rate-limited before it is
# abandoned (logged, removed from the queue, has_timeline left at 0).
MAX_RETRY_RUNS = 5

# Queues / modes whose Match-V5 timeline legitimately does not exist. Used
# by the backfill to avoid re-queueing rows whose has_timeline=0 is correct.
EVENT_MODE_NO_TIMELINE_QUEUES = frozenset({2400})
EVENT_MODE_NO_TIMELINE_GAME_MODES = frozenset({"KIWI"})

RETRY_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS fetch_retry (
        match_id        TEXT PRIMARY KEY,
        kind            TEXT NOT NULL,     -- 'timeline' | 'match'
        reason          TEXT,
        attempts        INTEGER NOT NULL DEFAULT 0,
        enqueued_at     TEXT,
        last_attempt_at TEXT
    )
"""


class PaginationRateLimited(RuntimeError):
    """A match-id page stayed rate-limited after the bounded retries.

    Raised instead of treating the page as the end of the window: ids come
    newest-first, so hydrating what was collected would advance the DB's
    newest ``game_creation_ts`` past the older, never-listed matches, and
    the next run (which starts its window there) would never see them.
    """

    def __init__(self, collected: list[str]):
        super().__init__(f"match-id pagination rate-limited after "
                         f"{len(collected)} new id(s)")
        self.collected = collected


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def fetch_with_rate_limit_retry(
    call,
    *,
    backoff_s: tuple[float, ...] = DEFAULT_BACKOFF_S,
    sleep=time.sleep,
):
    """Run ``call()`` (a Riot helper returning data-or-None) with 429 retry.

    Returns ``(result, status)``; status is FETCH_OK, FETCH_ABSENT (None for
    any reason other than a rate limit - permanent) or FETCH_RATE_LIMITED
    (still throttled after ``len(backoff_s) + 1`` attempts).
    """
    attempts = len(backoff_s) + 1
    for i in range(attempts):
        with riot_api.track_outcomes() as scope:
            result = call()
        if result is not None:
            return result, FETCH_OK
        if not scope.rate_limited:
            return None, FETCH_ABSENT
        if i < attempts - 1:
            sleep(backoff_s[i])
    return None, FETCH_RATE_LIMITED


def ensure_retry_table(conn: sqlite3.Connection) -> None:
    conn.execute(RETRY_TABLE_SQL)


def enqueue_retry(
    conn: sqlite3.Connection, match_id: str, kind: str, reason: str,
) -> None:
    """Park ``match_id`` for a later re-fetch. Idempotent (keeps an existing
    entry and its attempt count). Caller commits."""
    if kind not in ("timeline", "match"):
        raise ValueError(f"unknown retry kind: {kind!r}")
    ensure_retry_table(conn)
    conn.execute(
        "INSERT OR IGNORE INTO fetch_retry "
        "(match_id, kind, reason, attempts, enqueued_at) VALUES (?,?,?,0,?)",
        (match_id, kind, reason, _now_iso()),
    )


# --- DB helpers -------------------------------------------------------

def open_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    # RM-413 (RM-233 shape): read the adopted mode; warn, never raise - a
    # hard failure here would turn a degraded DB into a dead batch job.
    jm_row = conn.execute("PRAGMA journal_mode=WAL").fetchone()
    journal_mode = str(jm_row[0]).lower() if jm_row else "unknown"
    if journal_mode != "wal":
        _log.warning(
            "rewind_catchup journal_mode fell back to %r (wanted wal): %s - "
            "concurrent readers WILL block writers on this database",
            journal_mode, DB_PATH)
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def open_db_readonly(db_path: Path | None = None) -> sqlite3.Connection:
    """Read-only connection (URI mode=ro) for --dry-run paths: no PRAGMA
    writes, no table creation, no journal-mode change."""
    path = Path(db_path or DB_PATH)
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)


def pending_retry_counts(db_path: Path | None = None) -> dict[str, int]:
    """Read-only tally of the fetch_retry queue by kind; a missing DB or a
    missing table is an empty queue, never a reason to create one."""
    path = Path(db_path or DB_PATH)
    if not path.exists():
        return {}
    conn = open_db_readonly(path)
    try:
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                        "AND name='fetch_retry'").fetchone() is None:
            return {}
        return dict(conn.execute(
            "SELECT kind, COUNT(*) FROM fetch_retry GROUP BY kind").fetchall())
    finally:
        conn.close()


def existing_match_ids(conn: sqlite3.Connection) -> set[str]:
    return {row[0] for row in conn.execute("SELECT match_id FROM matches")}


def newest_creation_ts(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT MAX(game_creation_ts) FROM matches").fetchone()
    return int(row[0] or 0)


def operator_puuid_from_db(conn: sqlite3.Connection) -> str:
    """Pick the PUUID with the most rows in participants - the player the DB tracks.

    May be a STALE PUUID (Riot rotates PUUIDs on certain account events).
    Use ``resolve_current_puuid`` to refresh via Account-V1 before hitting
    Match-V5 endpoints.
    """
    row = conn.execute("""
        SELECT puuid FROM participants
        WHERE puuid IS NOT NULL AND puuid != ''
        GROUP BY puuid
        ORDER BY COUNT(*) DESC
        LIMIT 1
    """).fetchone()
    if not row or not row[0]:
        raise SystemExit(
            "rewind_history.db has no participants - cannot infer operator PUUID. "
            "Pass --puuid or --riot-id explicitly."
        )
    return row[0]


def operator_riot_id_from_db(conn: sqlite3.Connection) -> tuple[str, str] | None:
    """Try to pull the operator's Riot ID (gameName, tagLine) from the participants
    table by looking at the dominant PUUID's most-recent row. Returns None if
    the riot_id columns are blank for every row.
    """
    stale = operator_puuid_from_db(conn)
    row = conn.execute("""
        SELECT riot_id_game_name, riot_id_tagline
        FROM participants
        WHERE puuid = ? AND riot_id_game_name != ''
        ORDER BY id DESC LIMIT 1
    """, (stale,)).fetchone()
    if not row:
        return None
    name, tag = row
    if not name or not tag:
        return None
    return name, tag


def resolve_current_puuid(
    conn: sqlite3.Connection,
    *,
    explicit_puuid: str = "",
    explicit_riot_id: str = "",
    state_riot_id: str = "",
) -> str:
    """Resolve the operator's CURRENT PUUID for Match-V5 calls.

    Priority order:
      1) ``--puuid`` flag value.
      2) ``--riot-id NAME#TAG`` looked up via Account-V1.
      3) The Riot ID persisted in the state sentinel (set by a prior
         ``--riot-id`` run) via Account-V1 - an authoritative, sticky
         override that BEATS the DB-majority fallback.
      4) DB-derived Riot ID looked up via Account-V1 (and cross-checks the
         stale DB PUUID; if it differs, prints a warning).
      5) Stale DB PUUID as last-resort (likely fails on Match-V5; surfaced
         so the user knows what happened).

    Step 3 fixes the 2026-06-08 staleness (REPLAY1): when the operator
    switched Riot IDs, the DB stayed dominated by the OLD account's rows, so
    step 4 kept re-resolving the old account and the live writer never
    ingested the new one. A persisted current Riot ID breaks that
    self-reinforcing loop - the new account has zero DB rows yet, so it can
    only be discovered from an explicit/persisted identity, never the
    majority.
    """
    if explicit_puuid:
        return explicit_puuid

    if explicit_riot_id:
        if "#" not in explicit_riot_id:
            raise SystemExit(f"--riot-id must be NAME#TAG, got: {explicit_riot_id!r}")
        name, tag = explicit_riot_id.split("#", 1)
        acct = riot_api.get_account_by_riot_id(name, tag)
        if acct is None or not acct.get("puuid"):
            raise SystemExit(f"Account-V1 lookup failed for {explicit_riot_id!r}")
        return acct["puuid"]

    if state_riot_id and "#" in state_riot_id:
        name, tag = state_riot_id.split("#", 1)
        acct = riot_api.get_account_by_riot_id(name, tag)
        if acct is not None and acct.get("puuid"):
            print(f"Resolved PUUID from persisted Riot ID {state_riot_id} "
                  f"via Account-V1 (sticky current account)")
            return acct["puuid"]
        print(f"  Persisted Riot ID {state_riot_id} failed Account-V1; "
              f"falling back to DB-derived account")

    riot_id = operator_riot_id_from_db(conn)
    if riot_id is not None:
        name, tag = riot_id
        print(f"Resolving current PUUID for {name}#{tag} via Account-V1...")
        acct = riot_api.get_account_by_riot_id(name, tag)
        if acct is None or not acct.get("puuid"):
            stale = operator_puuid_from_db(conn)
            print(f"  Account-V1 lookup failed; falling back to DB PUUID {stale[:24]}...")
            return stale
        fresh = acct["puuid"]
        stale = operator_puuid_from_db(conn)
        if fresh != stale:
            print(f"  PUUID rotated: DB has {stale[:24]}..., current is {fresh[:24]}...")
        return fresh

    stale = operator_puuid_from_db(conn)
    print(f"  No Riot ID in DB - using stale DB PUUID {stale[:24]}... (may fail)")
    return stale


# --- State sentinel ---------------------------------------------------

def load_state() -> dict:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_state(state: dict) -> None:
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(STATE_PATH)


# --- Riot API -> DB writer ---------------------------------------------

def write_match(
    conn: sqlite3.Connection,
    match_id: str,
    detail: dict,
    timeline: dict | None,
) -> None:
    info = detail.get("info", {}) or {}
    participants = info.get("participants", []) or []

    # Tracked player resolution: match against the current operator PUUID
    # first; if not found, fall back to the legacy stale PUUID stored on
    # earlier rows (kept in state["stale_puuid"]) so cross-Match-V5/rewind
    # rows stay consistent.
    state = load_state()
    candidates = {
        (state.get("puuid") or "").lower(),
        (state.get("stale_puuid") or "").lower(),
    }
    candidates.discard("")
    tracked = None
    for p in participants:
        ppuuid = (p.get("puuid", "") or "").lower()
        if ppuuid in candidates:
            tracked = p
            break

    # Patch field: cdragon uses "16.9.1" style; Match-V5 gives "16.9.501"
    # (game_version). Normalize to "MAJOR.MINOR" so cross-source joins work.
    game_version = info.get("gameVersion", "") or ""
    parts = game_version.split(".")
    patch = f"{parts[0]}.{parts[1]}" if len(parts) >= 2 else game_version

    cur = conn.execute("""
        INSERT OR IGNORE INTO matches
        (match_id, platform, queue_id, game_mode, game_type, map_id,
         game_version, patch, game_duration_s, game_creation_ts,
         game_end_ts, end_of_game_result, tournament_code,
         tracked_champion_id, tracked_champion_name, tracked_team_id,
         tracked_win, tracked_kills, tracked_deaths, tracked_assists,
         tracked_kp, tracked_lane, tracked_side, tracked_ff,
         tracked_ttmga_t, has_stats, has_timeline, fetched_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        match_id,
        info.get("platformId", ""),
        info.get("queueId", 0),
        info.get("gameMode", ""),
        info.get("gameType", ""),
        info.get("mapId", 0),
        game_version,
        patch,
        info.get("gameDuration", 0),
        info.get("gameCreation", 0),
        info.get("gameEndTimestamp", 0),
        info.get("endOfGameResult", ""),
        info.get("tournamentCode", ""),
        tracked.get("championId", 0) if tracked else 0,
        tracked.get("championName", "") if tracked else "",
        tracked.get("teamId", 0) if tracked else 0,
        int(bool(tracked.get("win", False))) if tracked else 0,
        tracked.get("kills", 0) if tracked else 0,
        tracked.get("deaths", 0) if tracked else 0,
        tracked.get("assists", 0) if tracked else 0,
        0,  # tracked_kp - derived in the legacy DB from the history list;
            # not directly in Match-V5. Leave 0; the new column is a
            # convenience cache, not a source of truth.
        0,  # tracked_lane - same; legacy enum, not in V5 detail directly
        "100" if (tracked and tracked.get("teamId", 0) == 100)
              else ("200" if tracked else ""),
        "",  # tracked_ff
        "",  # tracked_ttmga_t
        1,   # has_stats - by definition true here, we just fetched detail
        1 if timeline else 0,
        time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    ))

    if cur.rowcount == 0:
        # The match row already existed. The child tables have no natural
        # unique key, so inserting again APPENDS a full copy - which is how
        # three matches reached 11-12 copies (concurrent live-writer Timers
        # all passing the pre-lock presence probe). Only attach a timeline
        # the existing row lacks; never re-insert participants / teams.
        if timeline:
            row = conn.execute(
                "SELECT has_timeline FROM matches WHERE match_id = ?",
                (match_id,)).fetchone()
            if row is not None and not row[0]:
                apply_timeline(conn, match_id, timeline)
        return

    part_rows = [parse_participant(p, match_id) for p in participants]
    insert_rows(conn, "participants", part_rows)
    team_rows = [parse_team(t, match_id) for t in (info.get("teams") or [])]
    insert_rows(conn, "teams", team_rows)

    if timeline:
        _insert_timeline_rows(conn, match_id, timeline)


def _insert_timeline_rows(
    conn: sqlite3.Connection, match_id: str, timeline: dict,
) -> None:
    tl_info = timeline.get("info", {}) or {}
    frames = tl_info.get("frames", []) or []
    frame_rows: list[dict] = []
    event_rows: list[dict] = []
    for frame in frames:
        frame_rows.extend(parse_frame(frame, match_id))
        for ev in (frame.get("events") or []):
            event_rows.append(parse_event(ev, match_id))
    insert_rows(conn, "timeline_frames", frame_rows)
    insert_rows(conn, "timeline_events", event_rows)


def apply_timeline(
    conn: sqlite3.Connection, match_id: str, timeline: dict,
) -> None:
    """Attach a late-fetched timeline to an already-written match.

    REPLACES any frame/event rows for the match (the two tables have no
    natural unique key, so INSERT OR IGNORE would append a second copy) and
    flips has_timeline to 1. Only call with a timeline actually in hand - a
    failed fetch must never delete what is there. Caller commits.
    """
    conn.execute("DELETE FROM timeline_frames WHERE match_id = ?", (match_id,))
    conn.execute("DELETE FROM timeline_events WHERE match_id = ?", (match_id,))
    _insert_timeline_rows(conn, match_id, timeline)
    conn.execute("UPDATE matches SET has_timeline = 1 WHERE match_id = ?",
                 (match_id,))


def record_hydrated(
    conn: sqlite3.Connection,
    match_id: str,
    detail: dict,
    timeline: dict | None,
    timeline_status: str,
) -> None:
    """write_match, plus parking the match for a timeline re-fetch when the
    timeline was rate-limited (instead of leaving has_timeline=0 as if Riot
    had said "no timeline"). Caller commits, so both land in one txn."""
    write_match(conn, match_id, detail, timeline)
    if timeline is None and timeline_status == FETCH_RATE_LIMITED:
        enqueue_retry(conn, match_id, "timeline", "timeline 429")


def drain_retry_queue(
    conn: sqlite3.Connection,
    *,
    max_runs: int = MAX_RETRY_RUNS,
    limit: int = 0,
    backoff_s: tuple[float, ...] = DEFAULT_BACKOFF_S,
    sleep=time.sleep,
) -> dict[str, int]:
    """Re-fetch every parked match. Commits per match.

    Per entry: success -> write / attach timeline, dequeue ("recovered");
    404/403 -> dequeue, has_timeline stays 0 ("permanent" - the event-mode
    case); still 429 -> attempts += 1 and stop draining this run, because
    the bucket is hot ("deferred"), or dequeue once attempts reaches
    ``max_runs`` ("abandoned").
    """
    ensure_retry_table(conn)
    conn.commit()
    counts = {"recovered": 0, "permanent": 0, "deferred": 0, "abandoned": 0}
    sql = "SELECT match_id, kind, attempts FROM fetch_retry ORDER BY enqueued_at, match_id"
    if limit:
        sql += f" LIMIT {int(limit)}"
    rows = conn.execute(sql).fetchall()
    for match_id, kind, attempts in rows:
        if kind == "timeline" and conn.execute(
                "SELECT 1 FROM matches WHERE match_id = ?", (match_id,)
        ).fetchone() is None:
            kind = "match"

        rate_limited = False
        if kind == "match":
            detail, d_status = fetch_with_rate_limit_retry(
                lambda m=match_id: riot_api.get_match(m, region=REGION_REGIONAL),
                backoff_s=backoff_s, sleep=sleep)
            if d_status == FETCH_OK:
                timeline, t_status = fetch_with_rate_limit_retry(
                    lambda m=match_id: riot_api.get_match_timeline(
                        m, region=REGION_REGIONAL),
                    backoff_s=backoff_s, sleep=sleep)
                write_match(conn, match_id, detail, timeline)
                if t_status == FETCH_RATE_LIMITED:
                    # Detail landed; only the timeline is still owed.
                    conn.execute(
                        "UPDATE fetch_retry SET kind='timeline', "
                        "attempts=attempts+1, last_attempt_at=? WHERE match_id=?",
                        (_now_iso(), match_id))
                    conn.commit()
                    counts["deferred"] += 1
                    break
                outcome = "recovered"
            elif d_status == FETCH_ABSENT:
                outcome = "permanent"
            else:
                rate_limited = True
        else:
            timeline, t_status = fetch_with_rate_limit_retry(
                lambda m=match_id: riot_api.get_match_timeline(
                    m, region=REGION_REGIONAL),
                backoff_s=backoff_s, sleep=sleep)
            if t_status == FETCH_OK:
                apply_timeline(conn, match_id, timeline)
                outcome = "recovered"
            elif t_status == FETCH_ABSENT:
                outcome = "permanent"
            else:
                rate_limited = True

        if rate_limited:
            if attempts + 1 >= max_runs:
                conn.execute("DELETE FROM fetch_retry WHERE match_id=?", (match_id,))
                _log.warning("rewind_catchup: %s still rate-limited after %d runs; "
                             "abandoned (has_timeline stays 0)", match_id, attempts + 1)
                counts["abandoned"] += 1
            else:
                conn.execute(
                    "UPDATE fetch_retry SET attempts=attempts+1, last_attempt_at=? "
                    "WHERE match_id=?", (_now_iso(), match_id))
                counts["deferred"] += 1
            conn.commit()
            break

        conn.execute("DELETE FROM fetch_retry WHERE match_id=?", (match_id,))
        conn.commit()
        counts[outcome] += 1
    return counts


# --- Catch-up loop ----------------------------------------------------

def collect_new_match_ids(
    puuid: str,
    start_time_unix_s: int,
    existing: set[str],
    *,
    page_size: int = 100,
    max_pages: int = 100,
    limit: int = 0,
    backoff_s: tuple[float, ...] = DEFAULT_BACKOFF_S,
    sleep=time.sleep,
) -> list[str]:
    """Walk Match-V5 pages forward from start_time_unix_s until we see an
    empty page or hit max_pages. Returns NEW match ids only.

    Raises PaginationRateLimited when a page stays rate-limited after the
    bounded retries - see that class for why this must not end the window.
    """
    new_ids: list[str] = []
    for page in range(max_pages):
        start = page * page_size
        ids, status = fetch_with_rate_limit_retry(
            lambda s=start: riot_api.get_recent_matches(
                puuid,
                count=page_size,
                region=REGION_REGIONAL,
                start=s,
                start_time_unix_s=start_time_unix_s,
            ),
            backoff_s=backoff_s, sleep=sleep,
        )
        if status == FETCH_RATE_LIMITED:
            print(f"    page {page}: still rate-limited after retries - "
                  f"aborting so the window does not skip older matches")
            raise PaginationRateLimited(new_ids)
        if ids is None:
            print(f"    page {page}: API call returned None (key issue or not found)")
            break
        if not ids:
            print(f"    page {page}: empty - end of window")
            break
        page_new = [m for m in ids if m not in existing]
        new_ids.extend(page_new)
        print(f"    page {page}: {len(ids)} ids, {len(page_new)} new "
              f"(total new={len(new_ids)})")
        if limit and len(new_ids) >= limit:
            new_ids = new_ids[:limit]
            print(f"    --limit {limit} reached, stopping pagination")
            break
        if len(ids) < page_size:
            # Riot returns fewer than page_size on the last page.
            break
    return new_ids


def hydrate_match(
    match_id: str,
    fetch_timeline: bool,
    *,
    backoff_s: tuple[float, ...] = DEFAULT_BACKOFF_S,
    sleep=time.sleep,
) -> tuple[dict | None, dict | None, str, str]:
    """Fetch detail (+ timeline). Returns ``(detail, timeline, detail_status,
    timeline_status)``; a skipped timeline (``fetch_timeline=False`` or no
    detail) reports FETCH_ABSENT, which never enqueues a retry."""
    detail, d_status = fetch_with_rate_limit_retry(
        lambda: riot_api.get_match(match_id, region=REGION_REGIONAL),
        backoff_s=backoff_s, sleep=sleep)
    timeline, t_status = None, FETCH_ABSENT
    if detail is not None and fetch_timeline:
        timeline, t_status = fetch_with_rate_limit_retry(
            lambda: riot_api.get_match_timeline(match_id, region=REGION_REGIONAL),
            backoff_s=backoff_s, sleep=sleep)
    return detail, timeline, d_status, t_status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip())
    parser.add_argument("--limit", type=int, default=0,
                        help="Cap number of NEW matches hydrated this run (0 = unlimited)")
    parser.add_argument("--puuid", default="",
                        help="Override operator PUUID (default: inferred from DB)")
    parser.add_argument("--riot-id", default="",
                        help="Resolve PUUID from Riot ID (format: NAME#TAG)")
    parser.add_argument("--dry-run", action="store_true",
                        help="List the match ids that would be fetched; no writes")
    parser.add_argument("--no-timeline", action="store_true",
                        help="Skip the timeline fetch for each match")
    parser.add_argument("--max-pages", type=int, default=100,
                        help="Cap on Riot pagination depth (each page = 100 ids)")
    parser.add_argument("--retry-only", action="store_true",
                        help="Only drain the fetch_retry queue (429-parked "
                             "matches); skip the new-match walk")
    args = parser.parse_args(argv)

    if args.retry_only and args.dry_run:
        # Needs no API key and must not touch the DB (read-only open; a
        # missing fetch_retry table reads as an empty queue).
        print(f"fetch_retry pending: {pending_retry_counts(DB_PATH)}")
        return 0

    if not riot_api.is_configured():
        print("ERROR: Riot API key not configured. "
              "Place RGAPI-... in 'API-Key-Riot.txt' at project root.")
        return 2

    # --dry-run never writes: DB opened read-only, state sentinel not saved.
    conn = open_db_readonly() if args.dry_run else open_db()
    state = load_state()
    puuid = resolve_current_puuid(
        conn,
        explicit_puuid=args.puuid,
        explicit_riot_id=args.riot_id,
        state_riot_id=str(state.get("riot_id") or ""),
    )
    print(f"Operator PUUID: {puuid[:24]}...")

    state["puuid"] = puuid
    # Persist the explicit current account so it sticks across runs + keeps
    # the live-writer path anchored to the right account even while the DB
    # majority still lags a freshly-switched Riot ID (REPLAY1 fix).
    if args.riot_id and "#" in args.riot_id:
        state["riot_id"] = args.riot_id
    try:
        legacy = operator_puuid_from_db(conn)
        if legacy and legacy != puuid:
            state["stale_puuid"] = legacy
    except SystemExit:
        pass
    if not args.dry_run:
        save_state(state)

    if args.retry_only:
        return _drain_and_report(conn)

    newest_ms = newest_creation_ts(conn)
    if newest_ms <= 0:
        start_unix_s = int(time.time()) - COLD_START_SECS
        print(f"Cold start (empty DB): starting {COLD_START_DAYS} days back")
    else:
        start_unix_s = newest_ms // 1000
        print(f"Newest match in DB: {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(start_unix_s))} UTC")

    existing = existing_match_ids(conn)
    print(f"Already in DB: {len(existing):,} matches")

    print("\nFetching new match ids...")
    try:
        new_ids = collect_new_match_ids(
            puuid, start_unix_s, existing,
            max_pages=args.max_pages, limit=args.limit,
        )
    except PaginationRateLimited as exc:
        print(f"Riot rate-limited the match-id walk ({exc}); nothing hydrated "
              f"so the next run's window still covers every unlisted match.")
        conn.close()
        return 3
    if not new_ids:
        print("No new matches.  DB is up to date.")
        if args.dry_run:
            conn.close()
            return 0
        return _drain_and_report(conn)

    print(f"\n{len(new_ids)} match(es) to hydrate")
    if args.dry_run:
        for mid in new_ids[:20]:
            print(f"  {mid}")
        if len(new_ids) > 20:
            print(f"  ... and {len(new_ids) - 20} more")
        conn.close()
        return 0

    done = errs = 0
    t0 = time.time()
    for i, mid in enumerate(new_ids, 1):
        detail, timeline, d_status, t_status = hydrate_match(
            mid, not args.no_timeline)
        if detail is None:
            errs += 1
            if d_status == FETCH_RATE_LIMITED:
                # Park it: newer matches written this run advance the window
                # past it, so only the retry queue can bring it back.
                enqueue_retry(conn, mid, "match", "detail 429")
                conn.commit()
                print(f"  [{i}/{len(new_ids)}] {mid}: detail rate-limited "
                      f"- parked in fetch_retry")
            else:
                print(f"  [{i}/{len(new_ids)}] {mid}: detail fetch failed")
            continue
        try:
            record_hydrated(conn, mid, detail, timeline, t_status)
            conn.commit()
            if t_status == FETCH_RATE_LIMITED:
                print(f"  [{i}/{len(new_ids)}] {mid}: timeline rate-limited "
                      f"- parked in fetch_retry")
            done += 1
            if done % 5 == 0 or done == 1:
                elapsed = time.time() - t0
                rate = done / max(elapsed, 1)
                eta = (len(new_ids) - done) / max(rate, 1e-6)
                print(f"  [{i}/{len(new_ids)}] {mid} hydrated "
                      f"(rate={rate:.2f}/s, ETA={int(eta // 60)}m)")
        except sqlite3.Error as e:
            errs += 1
            print(f"  [{i}/{len(new_ids)}] {mid}: write failed: {e}")
            conn.rollback()

    # State checkpoint with the new max ts.
    new_newest = newest_creation_ts(conn)
    state["last_run_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    state["last_run_done"] = done
    state["last_run_errors"] = errs
    state["newest_creation_ts_ms"] = new_newest
    save_state(state)

    bucket = riot_api.bucket_snapshot()
    print(
        f"\n=== Done in {(time.time() - t0)/60:.1f} min ===\n"
        f"  hydrated:        {done}\n"
        f"  errors:          {errs}\n"
        f"  newest in DB:    {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime((new_newest or 0)//1000))} UTC\n"
        f"  riot bucket:     {bucket}"
    )
    drain_rc = _drain_and_report(conn)
    return 0 if errs == 0 and drain_rc == 0 else 1


def _drain_and_report(conn: sqlite3.Connection) -> int:
    """Drain the 429 retry queue, print the tally, close ``conn``."""
    try:
        counts = drain_retry_queue(conn)
    except sqlite3.Error as e:
        conn.rollback()
        conn.close()
        print(f"fetch_retry drain failed: {e}")
        return 1
    pending = conn.execute("SELECT COUNT(*) FROM fetch_retry").fetchone()[0]
    conn.close()
    print(f"fetch_retry drain: {counts}  (still pending: {pending})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
