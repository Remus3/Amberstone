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
"""

from __future__ import annotations

import argparse
import json
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

DB_PATH = ROOT / "data" / "rewind_history.db"
STATE_PATH = ROOT / "data" / "rewind_catchup.state.json"

REGION_REGIONAL = "americas"  # Match-V5 lives on the regional cluster

# How far back to look on first run if the DB has no rows at all.
# Cold-start should not happen (DB has 2846 rows); guardrail only.
COLD_START_DAYS = 30
COLD_START_SECS = COLD_START_DAYS * 86400


# --- DB helpers -------------------------------------------------------

def open_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


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

    conn.execute("""
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

    part_rows = [parse_participant(p, match_id) for p in participants]
    insert_rows(conn, "participants", part_rows)
    team_rows = [parse_team(t, match_id) for t in (info.get("teams") or [])]
    insert_rows(conn, "teams", team_rows)

    if timeline:
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


# --- Catch-up loop ----------------------------------------------------

def collect_new_match_ids(
    puuid: str,
    start_time_unix_s: int,
    existing: set[str],
    *,
    page_size: int = 100,
    max_pages: int = 100,
    limit: int = 0,
) -> list[str]:
    """Walk Match-V5 pages forward from start_time_unix_s until we see an
    empty page or hit max_pages. Returns NEW match ids only.
    """
    new_ids: list[str] = []
    for page in range(max_pages):
        start = page * page_size
        ids = riot_api.get_recent_matches(
            puuid,
            count=page_size,
            region=REGION_REGIONAL,
            start=start,
            start_time_unix_s=start_time_unix_s,
        )
        if ids is None:
            print(f"    page {page}: API call returned None (rate-limited or key issue)")
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


def hydrate_match(match_id: str, fetch_timeline: bool) -> tuple[dict | None, dict | None]:
    detail = riot_api.get_match(match_id, region=REGION_REGIONAL)
    timeline = None
    if detail is not None and fetch_timeline:
        timeline = riot_api.get_match_timeline(match_id, region=REGION_REGIONAL)
    return detail, timeline


def main() -> int:
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
    args = parser.parse_args()

    if not riot_api.is_configured():
        print("ERROR: Riot API key not configured. "
              "Place RGAPI-... in 'API-Key-Riot.txt' at project root.")
        return 2

    conn = open_db()
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
    save_state(state)

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
    new_ids = collect_new_match_ids(
        puuid, start_unix_s, existing,
        max_pages=args.max_pages, limit=args.limit,
    )
    if not new_ids:
        print("No new matches.  DB is up to date.")
        return 0

    print(f"\n{len(new_ids)} match(es) to hydrate")
    if args.dry_run:
        for mid in new_ids[:20]:
            print(f"  {mid}")
        if len(new_ids) > 20:
            print(f"  ... and {len(new_ids) - 20} more")
        return 0

    done = errs = 0
    t0 = time.time()
    for i, mid in enumerate(new_ids, 1):
        detail, timeline = hydrate_match(mid, not args.no_timeline)
        if detail is None:
            errs += 1
            print(f"  [{i}/{len(new_ids)}] {mid}: detail fetch failed")
            continue
        try:
            write_match(conn, mid, detail, timeline)
            conn.commit()
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
    conn.close()
    return 0 if errs == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
