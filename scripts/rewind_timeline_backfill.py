"""
scripts/rewind_timeline_backfill.py
-----------------------------------
One-shot recovery for rewind_history.db rows that a Riot 429 may have
written as a PERMANENT has_timeline=0.

Before the 2026-09-20 fix, lib/rewind_live_writer.py and
scripts/rewind_catchup.py read the None a rate-limited timeline fetch
returns as "this match has no timeline" and wrote has_timeline=0, which no
later run ever revisits. The fix parks such matches in the ``fetch_retry``
table; this script puts the ALREADY-WRITTEN suspects into that same queue so
the existing catchup drain (``rewind_catchup.py --retry-only``) re-fetches
them. It never flips has_timeline itself and never deletes timeline rows -
only a successful re-fetch does that, and a 404/403 on re-fetch leaves the
row exactly as it is.

Which rows are suspects. The logs from the write dates are gone, so a 429
cannot be proven per row; instead the script excludes every row whose
has_timeline=0 is known to be CORRECT or cannot be judged:

  * event-mode matches (queue 2400 / gameMode KIWI - ARAM Mayhem): Match-V5
    has no timeline for them, permanently (CLAUDE.md Settled);
  * rows with no queue id at all (the .rofl sidecar backfill inserts them;
    the replay tool cannot tell ARAM 450 from Mayhem 2400, so they may well
    be event-mode);
  * rows with has_stats=0 (never fetched from Match-V5 at all);
  * rows already queued.

Everything else with has_timeline=0 is a normal Match-V5 queue that DOES
carry a timeline, so a 0 there is a 429 casualty or some other transient -
either way, worth one bounded re-fetch.

Usage (from the repo root):
  python scripts/rewind_timeline_backfill.py --dry-run   # read-only report
  python scripts/rewind_timeline_backfill.py             # enqueue suspects
  python scripts/rewind_catchup.py --retry-only          # re-fetch them
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import rewind_catchup as rc  # noqa: E402

BACKFILL_REASON = "backfill: has_timeline=0 on a non-event queue (suspected 429)"


def _retry_table_exists(conn: sqlite3.Connection) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='fetch_retry'"
    ).fetchone() is not None


def classify(conn: sqlite3.Connection) -> dict:
    """Read-only. Split every has_timeline=0 row into candidates and the
    named exclusion buckets."""
    queued: set[str] = set()
    if _retry_table_exists(conn):
        queued = {r[0] for r in conn.execute("SELECT match_id FROM fetch_retry")}
    report: dict = {
        "candidates": [],
        "excluded_event_mode": [],
        "excluded_unknown_queue": [],
        "excluded_no_stats": [],
        "excluded_already_queued": [],
    }
    rows = conn.execute(
        "SELECT m.match_id, m.queue_id, m.game_mode, m.has_stats, "
        "  (SELECT COUNT(*) FROM timeline_frames f WHERE f.match_id = m.match_id) "
        "FROM matches m WHERE m.has_timeline = 0 ORDER BY m.match_id"
    ).fetchall()
    for match_id, queue_id, game_mode, has_stats, n_frames in rows:
        if match_id in queued:
            report["excluded_already_queued"].append(match_id)
        elif (queue_id in rc.EVENT_MODE_NO_TIMELINE_QUEUES
              or (game_mode or "") in rc.EVENT_MODE_NO_TIMELINE_GAME_MODES):
            report["excluded_event_mode"].append(match_id)
        elif queue_id is None:
            report["excluded_unknown_queue"].append(match_id)
        elif not has_stats:
            report["excluded_no_stats"].append(match_id)
        else:
            report["candidates"].append({
                "match_id": match_id,
                "queue_id": queue_id,
                "game_mode": game_mode or "",
                "frames_present": int(n_frames),
            })
    return report


def _print_report(report: dict) -> None:
    cands = report["candidates"]
    by_queue = Counter((c["queue_id"], c["game_mode"]) for c in cands)
    print(f"candidates (re-fetch): {len(cands)}")
    for (queue_id, game_mode), n in sorted(by_queue.items()):
        print(f"  queue {queue_id} {game_mode}: {n}")
    for c in cands:
        note = (f"  ({c['frames_present']} frame rows already present - "
                f"replaced only on a successful re-fetch)"
                if c["frames_present"] else "")
        print(f"    {c['match_id']}{note}")
    for key in ("excluded_event_mode", "excluded_unknown_queue",
                "excluded_no_stats", "excluded_already_queued"):
        ids = report[key]
        print(f"{key}: {len(ids)}" + (f"  {ids}" if ids else ""))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--db", default=str(rc.DB_PATH),
                        help="Path to rewind_history.db (default: data/)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report only; opens the DB read-only")
    args = parser.parse_args(argv)

    db = Path(args.db)
    if not db.exists():
        print(f"ERROR: no database at {db}")
        return 2

    if args.dry_run:
        conn = sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True)
        try:
            _print_report(classify(conn))
        finally:
            conn.close()
        print("dry run: nothing written")
        return 0

    conn = sqlite3.connect(str(db))
    try:
        report = classify(conn)
        _print_report(report)
        rc.ensure_retry_table(conn)
        for c in report["candidates"]:
            rc.enqueue_retry(conn, c["match_id"], "timeline", BACKFILL_REASON)
        conn.commit()
        n = conn.execute("SELECT COUNT(*) FROM fetch_retry").fetchone()[0]
    except sqlite3.Error as exc:
        conn.rollback()
        print(f"ERROR: backfill failed, rolled back: {exc}")
        return 1
    finally:
        conn.close()
    print(f"enqueued {len(report['candidates'])}; fetch_retry now holds {n}. "
          f"Next: python scripts/rewind_catchup.py --retry-only")
    return 0


if __name__ == "__main__":
    sys.exit(main())
