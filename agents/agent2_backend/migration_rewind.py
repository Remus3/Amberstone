"""One-shot (re-runnable) migration from ``data/rewind_history.db`` to the
five Phase 3 mode DBs.

Rewind is a 1.62 GB historic archive of 2,846 matches. It is read-only; this
script never writes to it. It reads matches + participants (+ a tracked-player
slice of timeline_events) and splits them by queue into the new mode DBs,
stamping ``source='rewind_migration'`` on every row.

Re-runnability: per-mode ``_migration_state`` table tracks
``(source='rewind_migration', source_ref=<rewind match_id>) → local_match_id``.
Second run is a no-op on already-migrated matches.

Usage:
  python -m agents.agent2_backend.migration_rewind
  python -m agents.agent2_backend.migration_rewind --dry-run
  python -m agents.agent2_backend.migration_rewind --events          # also migrate tracked-player events
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from agents.agent2_backend.db_schema import MODE_DB_FILES, db_path, init_all, open_db

logger = logging.getLogger("agent2.migration_rewind")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
REWIND_DB = _PROJECT_ROOT / "data" / "rewind_history.db"

SOURCE_TAG = "rewind_migration"

# Riot queue_id → Phase 3 mode. Unmapped queues are skipped.
QUEUE_TO_MODE: dict[int, str] = {
    400: "sr_draft",   # Normal Draft
    420: "sr_ranked",  # Ranked Solo/Duo
    430: "sr_draft",   # Blind
    440: "sr_ranked",  # Ranked Flex
    450: "aram",       # ARAM
    480: "sr_draft",   # Swiftplay
    700: "sr_draft",   # Clash
    720: "aram",       # ARAM Clash
    740: "sr_draft",
    830: "sr_draft",   # co-op vs AI
    840: "sr_draft",
    850: "sr_draft",
    900: "sr_draft",   # URF
    1020: "sr_draft",  # One for All
    1400: "sr_draft",  # Ultimate Spellbook
    1700: "arena",     # Arena
    1710: "arena",     # Arena variant
    1900: "sr_draft",  # URF pick
}

# arch: phase 3 - rewind timeline_events → match_events migration (coach-decision moments per §9)
TRACKED_EVENT_TYPES = (
    "CHAMPION_KILL",
    "ITEM_PURCHASED",
    "LEVEL_UP",
    "SKILL_LEVEL_UP",
    "ELITE_MONSTER_KILL",
    "BUILDING_KILL",
)


def _iso_utc(ms: int | None) -> str | None:
    if not ms:
        return None
    try:
        return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).isoformat()
    except (OSError, OverflowError, ValueError):
        return None


def _open_rewind() -> sqlite3.Connection:
    if not REWIND_DB.exists():
        raise FileNotFoundError(f"rewind_history.db not found at {REWIND_DB}")
    uri = f"file:{REWIND_DB.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _already_migrated(conn: sqlite3.Connection, source_ref: str) -> int | None:
    row = conn.execute(
        "SELECT local_match_id FROM _migration_state WHERE source = ? AND source_ref = ?",
        (SOURCE_TAG, source_ref),
    ).fetchone()
    return row[0] if row else None


def _participants_for_match(rewind: sqlite3.Connection, match_id: str) -> list[sqlite3.Row]:
    rows = rewind.execute(
        "SELECT participant_id, team_id, champion_name, puuid "
        "FROM participants WHERE match_id = ? ORDER BY participant_id",
        (match_id,),
    ).fetchall()
    return rows


def _split_comp(participants: list[sqlite3.Row], tracked_team_id: int) -> tuple[list[str], list[str]]:
    allies: list[str] = []
    enemies: list[str] = []
    for p in participants:
        name = p["champion_name"] or "Unknown"
        if p["team_id"] == tracked_team_id:
            allies.append(name)
        else:
            enemies.append(name)
    return allies, enemies


def _insert_match(
    mode_conn: sqlite3.Connection,
    m: sqlite3.Row,
    allies: list[str],
    enemies: list[str],
) -> int:
    started = _iso_utc(m["game_creation_ts"]) or datetime.now(timezone.utc).isoformat()
    ended = _iso_utc(m["game_end_ts"])
    cur = mode_conn.execute(
        """
        INSERT INTO matches
          (started_at, ended_at, champion, ally_champions, enemy_champions,
           duration_sec, win, final_rating_json, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            started,
            ended,
            m["tracked_champion_name"] or "Unknown",
            json.dumps(allies),
            json.dumps(enemies),
            m["game_duration_s"],
            int(m["tracked_win"]) if m["tracked_win"] is not None else None,
            None,
            SOURCE_TAG,
        ),
    )
    return int(cur.lastrowid)


def _insert_events(
    rewind: sqlite3.Connection,
    mode_conn: sqlite3.Connection,
    rewind_match_id: str,
    local_match_id: int,
    tracked_participant_id: int | None,
) -> int:
    # Only tracked-player or team-wide events. This keeps the seed tractable.
    types_placeholders = ",".join("?" for _ in TRACKED_EVENT_TYPES)
    rows = rewind.execute(
        f"""
        SELECT timestamp_ms, event_type, participant_id, killer_id, victim_id,
               item_id, monster_type, monster_subtype, building_type, tower_type,
               team_id, skill_slot, level, bounty, shutdown_bounty,
               assisting_ids_json, raw_json
        FROM timeline_events
        WHERE match_id = ? AND event_type IN ({types_placeholders})
        ORDER BY timestamp_ms
        """,
        (rewind_match_id, *TRACKED_EVENT_TYPES),
    ).fetchall()

    inserted = 0
    for e in rows:
        et = e["event_type"]
        # Relevance filter - keep events involving tracked player, plus team macro events.
        relevant = False
        if tracked_participant_id is not None:
            if e["participant_id"] == tracked_participant_id:
                relevant = True
            elif et == "CHAMPION_KILL" and (
                e["killer_id"] == tracked_participant_id
                or e["victim_id"] == tracked_participant_id
            ):
                relevant = True
        if et in ("ELITE_MONSTER_KILL", "BUILDING_KILL"):
            relevant = True
        if not relevant:
            continue

        state = {
            "participant_id": e["participant_id"],
            "killer_id": e["killer_id"],
            "victim_id": e["victim_id"],
            "item_id": e["item_id"],
            "monster_type": e["monster_type"],
            "monster_subtype": e["monster_subtype"],
            "building_type": e["building_type"],
            "tower_type": e["tower_type"],
            "team_id": e["team_id"],
            "skill_slot": e["skill_slot"],
            "level": e["level"],
            "bounty": e["bounty"],
            "shutdown_bounty": e["shutdown_bounty"],
        }
        # Drop nulls to save space.
        state = {k: v for k, v in state.items() if v is not None}
        ts_sec = (e["timestamp_ms"] or 0) / 1000.0
        mode_conn.execute(
            """
            INSERT INTO match_events
              (match_id, ts_game_sec, event_type, state_json,
               coach_output_json, outcome_30s_json)
            VALUES (?, ?, ?, ?, NULL, NULL)
            """,
            (local_match_id, ts_sec, et, json.dumps(state)),
        )
        inserted += 1
    return inserted


def migrate(dry_run: bool = False, include_events: bool = False) -> dict:
    if not REWIND_DB.exists():
        raise FileNotFoundError(f"rewind DB missing: {REWIND_DB}")

    # Ensure all target DBs exist with schema.
    init_all()

    rewind = _open_rewind()
    mode_conns: dict[str, sqlite3.Connection] = {m: open_db(m) for m in MODE_DB_FILES}

    stats: dict[str, dict] = {m: {"ingested": 0, "skipped": 0, "events": 0} for m in MODE_DB_FILES}
    unmapped = 0
    inspected = 0

    try:
        cur = rewind.execute(
            """
            SELECT match_id, queue_id, game_mode, game_duration_s, game_creation_ts,
                   game_end_ts, tracked_champion_name, tracked_team_id, tracked_win
            FROM matches
            ORDER BY game_creation_ts
            """
        )
        for m in cur:
            inspected += 1
            mode = QUEUE_TO_MODE.get(m["queue_id"])
            if mode is None:
                unmapped += 1
                continue
            conn = mode_conns[mode]

            existing = _already_migrated(conn, m["match_id"])
            if existing is not None:
                stats[mode]["skipped"] += 1
                continue

            parts = _participants_for_match(rewind, m["match_id"])
            if not parts:
                stats[mode]["skipped"] += 1
                continue
            # Audit M2: don't guess blue/red when tracked_team_id is null -
            # the ally/enemy split would be scrambled for every red-side
            # game. Skip instead so Agent 4 isn't trained on garbage comps.
            if m["tracked_team_id"] is None:
                logger.debug("skip match %s: tracked_team_id is NULL", m["match_id"])
                stats[mode]["skipped"] += 1
                continue
            allies, enemies = _split_comp(parts, m["tracked_team_id"])

            # Find tracked participant_id by champion_name + team.
            tracked_pid: int | None = None
            for p in parts:
                if (
                    p["champion_name"] == m["tracked_champion_name"]
                    and p["team_id"] == m["tracked_team_id"]
                ):
                    tracked_pid = p["participant_id"]
                    break

            if dry_run:
                stats[mode]["ingested"] += 1
                continue

            try:
                local_id = _insert_match(conn, m, allies, enemies)
                conn.execute(
                    """
                    INSERT OR REPLACE INTO _migration_state
                      (source, source_ref, local_match_id, migrated_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (SOURCE_TAG, m["match_id"], local_id, datetime.now(timezone.utc).isoformat()),
                )
                if include_events:
                    ev = _insert_events(rewind, conn, m["match_id"], local_id, tracked_pid)
                    stats[mode]["events"] += ev
                conn.commit()
                stats[mode]["ingested"] += 1
            except sqlite3.Error as e:
                conn.rollback()
                logger.error("insert failed for %s (%s): %s", m["match_id"], mode, e)
                stats[mode]["skipped"] += 1
    finally:
        rewind.close()
        for c in mode_conns.values():
            c.close()

    summary = {
        "inspected": inspected,
        "unmapped_queues": unmapped,
        "per_mode": stats,
        "dry_run": dry_run,
        "include_events": include_events,
    }
    logger.info("migration summary: %s", summary)
    return summary


def main(argv: Iterable[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--events", action="store_true", help="also migrate tracked-player timeline events")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(list(argv) if argv is not None else None)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    t0 = time.time()
    summary = migrate(dry_run=args.dry_run, include_events=args.events)
    print(json.dumps(summary, indent=2))
    print(f"[migration_rewind] elapsed {time.time()-t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
