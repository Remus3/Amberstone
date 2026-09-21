"""
scripts/rewind_dedup_children.py
--------------------------------
Recovery for rewind_history.db matches whose child rows were written more
than once. DRY RUN BY DEFAULT; ``--apply`` writes.

Why the duplicates exist: scripts/rewind_catchup.write_match inserted
participants / teams / timeline rows on EVERY call, while only the
``matches`` row was protected (INSERT OR IGNORE on its PRIMARY KEY; the child
tables have no natural unique key). lib/rewind_live_writer probed "already
present?" before fetching and outside its write lock, so concurrent Timers for
one game end all passed the probe and all wrote. Measured 2026-09-20: three
matches, 11-12 copies each, one contiguous id block per match. write_match is
now idempotent (2026-09-20 fix); this script repairs the rows already written.

Which matches: only those with STRUCTURAL proof of a repeated write - a
participant_id, team_id or (frame timestamp, participant_id) that occurs
more than once, none of which a single write can produce. Identical EVENT
rows are NOT proof: measured 2026-09-20, 2952 clean matches carry them
legitimately (e.g. two potions bought in the same tick), so a blind
exact-row dedup of timeline_events would destroy real data.

What --apply does, per affected match, in ONE transaction:
  * participants, teams, timeline_frames: deletes rows that are EXACT
    duplicates of an earlier row (every column except ``id`` equal),
    keeping the lowest id. Safe because each of these carries a per-write
    unique key. A copy that differs in any column is kept, never guessed at.
  * timeline_events, COPY-AWARE: k = how many times the timeline was
    written, read off the frame multiplicity (every (timestamp,
    participant_id) group must show the same k). The events' own copy
    count is the gcd of their identical-group sizes: 1 = written once, no
    delete (the state of all three affected matches on 2026-09-20); k = the
    same copies as the frames, so each group of n keeps n / k (lowest ids)
    and a potion pair written 6 times keeps 2; anything else is skipped and
    reported, never guessed at.
  This makes the DB correct immediately: readers such as
  dashboard/routes_replay_events.py and core/post_game_score.py read every
  event row with no DISTINCT, so they must not wait on a re-fetch that may
  404 or be abandoned.
  * a match whose timeline rows were duplicated is ALSO queued in
    ``fetch_retry`` for an optional canonical re-fetch
    (``rewind_catchup.py --retry-only``); on success it replaces the frame
    and event rows and flips has_timeline=1, on 404/403 nothing changes.

Usage (from the repo root):
  python scripts/rewind_dedup_children.py            # dry run, report only
  python scripts/rewind_dedup_children.py --apply    # dedup + queue re-fetch
  python scripts/rewind_catchup.py --retry-only      # optional re-fetch
"""

from __future__ import annotations

import argparse
import math
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import rewind_catchup as rc  # noqa: E402

# report key -> table. Exact-row dedup applies to the first three only;
# events are deduped copy-aware (see module docstring).
DEDUP_TABLES = {
    "participants": "participants",
    "teams": "teams",
    "frames": "timeline_frames",
    "events": "timeline_events",
}
EXACT_DEDUP_TABLES = ("participants", "teams", "timeline_frames")
REFETCH_REASON = "dedup: duplicated timeline rows, canonical re-fetch"


def _cols(conn: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")
            if r[1] != "id"]


def _counts(conn: sqlite3.Connection, table: str, match_id: str) -> tuple[int, int]:
    """(rows, distinct rows ignoring id) for one match."""
    cl = ", ".join(_cols(conn, table))
    total = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE match_id=?",
                         (match_id,)).fetchone()[0]
    distinct = conn.execute(
        f"SELECT COUNT(*) FROM (SELECT DISTINCT {cl} FROM {table} WHERE match_id=?)",
        (match_id,)).fetchone()[0]
    return total, distinct


def _timeline_copies(conn: sqlite3.Connection, match_id: str) -> int | None:
    """How many times the timeline was written, from frame multiplicity.
    0 = no frames; None = non-uniform (cannot be trusted)."""
    counts = {r[0] for r in conn.execute(
        "SELECT COUNT(*) FROM timeline_frames WHERE match_id=? "
        "GROUP BY timestamp_ms, participant_id", (match_id,))}
    if not counts:
        return 0
    if len(counts) != 1:
        return None
    return counts.pop()


def _event_deletions(conn: sqlite3.Connection, match_id: str
                     ) -> tuple[list[int] | None, int]:
    """Copy-aware event dedup plan: (ids to delete, rows kept), or
    (None, rows) when the copy count cannot be established safely."""
    total = conn.execute("SELECT COUNT(*) FROM timeline_events WHERE match_id=?",
                         (match_id,)).fetchone()[0]
    k = _timeline_copies(conn, match_id)
    if k is None or (k == 0 and total):
        return None, total
    if k <= 1:
        return [], total
    cols = _cols(conn, "timeline_events")
    groups: dict[tuple, list[int]] = {}
    for row in conn.execute(
            f"SELECT id, {', '.join(cols)} FROM timeline_events "
            f"WHERE match_id=? ORDER BY id", (match_id,)):
        groups.setdefault(tuple(row[1:]), []).append(row[0])
    # The events' own copy count is the gcd of the identical-group sizes:
    # 1 means they were written once (legit identical pairs are fine), k
    # means they carry the same k copies the frames do. Anything else is
    # ambiguous and is skipped rather than guessed at.
    k_events = 0
    for ids in groups.values():
        k_events = math.gcd(k_events, len(ids))
    if k_events == 1:
        return [], total
    if k_events != k:
        return None, total
    doomed: list[int] = []
    for ids in groups.values():
        doomed.extend(ids[len(ids) // k:])
    return doomed, total - len(doomed)


def scan(conn: sqlite3.Connection) -> list[dict]:
    """Read-only. Every match with STRUCTURAL proof of a repeated write,
    with (rows, rows after dedup) per table."""
    suspects: set[str] = set()
    suspects.update(r[0] for r in conn.execute(
        "SELECT match_id FROM participants GROUP BY match_id, participant_id "
        "HAVING COUNT(*) > 1"))
    suspects.update(r[0] for r in conn.execute(
        "SELECT match_id FROM teams GROUP BY match_id, team_id HAVING COUNT(*) > 1"))
    suspects.update(r[0] for r in conn.execute(
        "SELECT match_id FROM timeline_frames GROUP BY match_id, timestamp_ms, "
        "participant_id HAVING COUNT(*) > 1"))
    report = []
    for mid in sorted(suspects):
        row = conn.execute("SELECT queue_id, has_timeline FROM matches WHERE match_id=?",
                           (mid,)).fetchone()
        entry = {
            "match_id": mid,
            "queue_id": row[0] if row else None,
            "has_timeline": row[1] if row else None,
            "participants": _counts(conn, "participants", mid),
            "teams": _counts(conn, "teams", mid),
            "frames": _counts(conn, "timeline_frames", mid),
        }
        doomed, kept = _event_deletions(conn, mid)
        total = conn.execute("SELECT COUNT(*) FROM timeline_events WHERE match_id=?",
                             (mid,)).fetchone()[0]
        entry["events"] = (total, kept)
        entry["events_skipped"] = doomed is None
        entry["timeline_duplicated"] = entry["frames"][0] > entry["frames"][1]
        report.append(entry)
    return report


def dedup_match(conn: sqlite3.Connection, match_id: str, *,
                queue_refetch: bool) -> bool:
    """Delete duplicate child rows; optionally queue a canonical timeline
    re-fetch. Returns False when events were skipped (copy count unsafe).
    Caller commits. Events are planned BEFORE frames are deduped, because
    the frame multiplicity is what tells us the copy count."""
    doomed, _kept = _event_deletions(conn, match_id)
    if doomed:
        conn.executemany("DELETE FROM timeline_events WHERE id = ?",
                         [(i,) for i in doomed])
    for table in EXACT_DEDUP_TABLES:
        cl = ", ".join(_cols(conn, table))
        conn.execute(
            f"DELETE FROM {table} WHERE match_id = ? AND id NOT IN ("
            f"  SELECT MIN(id) FROM {table} WHERE match_id = ? GROUP BY {cl})",
            (match_id, match_id))
    if queue_refetch:
        rc.enqueue_retry(conn, match_id, "timeline", REFETCH_REASON)
    return doomed is not None


def _fmt(pair: tuple[int, int]) -> str:
    return f"{pair[0]} -> {pair[1]}"


def _print(report: list[dict], after: dict[str, dict] | None = None) -> None:
    print(f"matches with duplicated child rows: {len(report)} "
          f"(rows before -> after dedup)")
    for r in report:
        print(f"  {r['match_id']} q{r['queue_id']} has_timeline={r['has_timeline']}: "
              + ", ".join(f"{k} {_fmt(r[k])}" for k in DEDUP_TABLES)
              + ("  [EVENTS SKIPPED: copy count ambiguous]"
                 if r["events_skipped"] else ""))
        if after is not None:
            a = after[r["match_id"]]
            print("    after: " + ", ".join(f"{k} {a[k][0]}" for k in DEDUP_TABLES)
                  + f" (re-fetch queued: {a['queued']})")
    for k in DEDUP_TABLES:
        print(f"excess {k} rows: {sum(r[k][0] - r[k][1] for r in report)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--db", default=str(rc.DB_PATH),
                        help="Path to rewind_history.db (default: data/)")
    parser.add_argument("--apply", action="store_true",
                        help="Write the dedup (default is a read-only dry run)")
    args = parser.parse_args(argv)

    db = Path(args.db)
    if not db.exists():
        print(f"ERROR: no database at {db}")
        return 2

    if not args.apply:
        conn = rc.open_db_readonly(db)
        try:
            _print(scan(conn))
        finally:
            conn.close()
        print("dry run: nothing written (pass --apply to write)")
        return 0

    conn = sqlite3.connect(str(db))
    try:
        report = scan(conn)
        rc.ensure_retry_table(conn)
        for r in report:
            dedup_match(conn, r["match_id"], queue_refetch=r["timeline_duplicated"])
        conn.commit()
        queued = {row[0] for row in conn.execute("SELECT match_id FROM fetch_retry")}
        after = {}
        for r in report:
            mid = r["match_id"]
            after[mid] = {k: (conn.execute(
                f"SELECT COUNT(*) FROM {t} WHERE match_id=?", (mid,)).fetchone()[0],)
                for k, t in DEDUP_TABLES.items()}
            after[mid]["queued"] = mid in queued
    except sqlite3.Error as exc:
        conn.rollback()
        print(f"ERROR: dedup failed, rolled back: {exc}")
        return 1
    finally:
        conn.close()
    _print(report, after)
    print("applied. Optional refresh: python scripts/rewind_catchup.py --retry-only")
    return 0


if __name__ == "__main__":
    sys.exit(main())
