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

What --apply does, per affected match:
  * participants, teams: deletes rows that are EXACT duplicates of an earlier
    row (every column except ``id`` equal), keeping the lowest id. A copy that
    differs in any column is kept and reported, never guessed at.
  * timeline_frames / timeline_events: NOT deleted here. Events have no key
    that separates a legitimate repeat from a copy, so the match is queued in
    ``fetch_retry`` for a canonical timeline re-fetch; the catchup drain
    (``rewind_catchup.py --retry-only``) replaces the frame and event rows
    only when that fetch succeeds.

Usage (from the repo root):
  python scripts/rewind_dedup_children.py            # dry run, report only
  python scripts/rewind_dedup_children.py --apply    # dedup + queue re-fetch
  python scripts/rewind_catchup.py --retry-only      # re-fetch timelines
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import rewind_catchup as rc  # noqa: E402

DEDUP_TABLES = ("participants", "teams")
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


def _timeline_duplicated(conn: sqlite3.Connection, match_id: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM timeline_frames WHERE match_id=? "
        "GROUP BY timestamp_ms, participant_id HAVING COUNT(*) > 1 LIMIT 1",
        (match_id,)).fetchone() is not None


def scan(conn: sqlite3.Connection) -> list[dict]:
    """Read-only. Every match with a duplicated participant, team or frame
    row, with (rows, distinct) counts per table."""
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
        report.append({
            "match_id": mid,
            "queue_id": row[0] if row else None,
            "has_timeline": row[1] if row else None,
            "participants": _counts(conn, "participants", mid),
            "teams": _counts(conn, "teams", mid),
            "frames": conn.execute("SELECT COUNT(*) FROM timeline_frames WHERE match_id=?",
                                   (mid,)).fetchone()[0],
            "events": conn.execute("SELECT COUNT(*) FROM timeline_events WHERE match_id=?",
                                   (mid,)).fetchone()[0],
            "timeline_duplicated": _timeline_duplicated(conn, mid),
        })
    return report


def dedup_match(conn: sqlite3.Connection, match_id: str) -> None:
    """Delete exact-duplicate participant / team rows (keep lowest id) and
    queue a timeline re-fetch if frames are duplicated. Caller commits."""
    for table in DEDUP_TABLES:
        cl = ", ".join(_cols(conn, table))
        conn.execute(
            f"DELETE FROM {table} WHERE match_id = ? AND id NOT IN ("
            f"  SELECT MIN(id) FROM {table} WHERE match_id = ? GROUP BY {cl})",
            (match_id, match_id))
    if _timeline_duplicated(conn, match_id):
        rc.enqueue_retry(conn, match_id, "timeline", REFETCH_REASON)


def _print(report: list[dict], after: dict[str, dict] | None = None) -> None:
    print(f"matches with duplicated child rows: {len(report)}")
    for r in report:
        p, t = r["participants"], r["teams"]
        line = (f"  {r['match_id']} q{r['queue_id']} has_timeline={r['has_timeline']}: "
                f"participants {p[0]} (distinct {p[1]}), teams {t[0]} (distinct {t[1]}), "
                f"frames {r['frames']}, events {r['events']}, "
                f"timeline_duplicated={r['timeline_duplicated']}")
        if after is not None:
            a = after[r["match_id"]]
            line += (f"\n    after: participants {a['participants'][0]}, "
                     f"teams {a['teams'][0]}, frames {a['frames']} "
                     f"(re-fetch queued: {a['queued']})")
        print(line)
    excess = sum(r["participants"][0] - r["participants"][1] for r in report)
    print(f"excess participant rows: {excess}; excess team rows: "
          f"{sum(r['teams'][0] - r['teams'][1] for r in report)}")


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
        conn = sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True)
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
            dedup_match(conn, r["match_id"])
        conn.commit()
        queued = {row[0] for row in conn.execute("SELECT match_id FROM fetch_retry")}
        after = {}
        for r in report:
            mid = r["match_id"]
            after[mid] = {
                "participants": _counts(conn, "participants", mid),
                "teams": _counts(conn, "teams", mid),
                "frames": conn.execute(
                    "SELECT COUNT(*) FROM timeline_frames WHERE match_id=?",
                    (mid,)).fetchone()[0],
                "queued": mid in queued,
            }
    except sqlite3.Error as exc:
        conn.rollback()
        print(f"ERROR: dedup failed, rolled back: {exc}")
        return 1
    finally:
        conn.close()
    _print(report, after)
    print("applied. Next: python scripts/rewind_catchup.py --retry-only")
    return 0


if __name__ == "__main__":
    sys.exit(main())
