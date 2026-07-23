"""CLI to recover "Unknown / 0-0-0" match rows from local .rofl sidecars.

The offending rows are NOT missing - they exist in rewind_history.db with the
correct queue_id/game_mode (from Match-V5) but tracked_* NULL, so the dashboard
renders the operator's champion as "Unknown" and the KDA as "0-0-0". This tool
extracts the Layer-1 stats sidecars from the archived replays, then fills
matches.tracked_* on every existing NULL-tracked row whose sidecar carries an
operator account. queue_id/game_mode are never touched.

It is a thin wrapper over core.rofl_stats_backfill.backfill_tracked_summary; all
the join rules (file->row by match_id, player->operator by RIOT ID never puuid,
champion id never invented) live there.

Usage:
    python tools/rofl_tracked_backfill.py                 # dry-run (default)
    python tools/rofl_tracked_backfill.py --commit        # write the UPDATEs
    python tools/rofl_tracked_backfill.py --no-extract    # skip re-extraction
    python tools/rofl_tracked_backfill.py --archive DIR --db PATH

--dry-run is the DEFAULT: nothing is written unless --commit is passed. Exit 0
on success (dry-run or committed), 1 on an unexpected error.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import rofl_archive  # noqa: E402
from core import rofl_stats_backfill  # noqa: E402

_DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "rewind_history.db"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Backfill tracked_* on Unknown/0-0-0 rows from .rofl sidecars."
    )
    ap.add_argument("--archive", default=None,
                    help="archive dir holding the .rofl files + stats/ sidecars")
    ap.add_argument("--db", default=None, help="rewind_history.db path")
    ap.add_argument("--no-extract", action="store_true",
                    help="do not (re-)extract sidecars first; use what is on disk")
    ap.add_argument("--commit", action="store_true",
                    help="write the UPDATEs (default is a dry-run that writes nothing)")
    ap.add_argument("--dry-run", action="store_true",
                    help="explicit no-op flag; the default is already dry-run")
    args = ap.parse_args(argv)

    archive = Path(args.archive) if args.archive else rofl_archive.default_archive_dir()
    db_path = Path(args.db) if args.db else _DEFAULT_DB
    stats_dir = archive / "stats"

    if not db_path.is_file():
        print(f"db absent: {db_path}")
        return 1

    if not args.no_extract:
        ex = rofl_archive.extract_archive(archive)
        print(f"extract: extracted={len(ex.extracted)} skipped={len(ex.skipped)} "
              f"failed={len(ex.failed)} -> {stats_dir}")

    if not stats_dir.is_dir():
        print(f"no sidecars to read: {stats_dir}")
        return 0

    sidecars = sorted(stats_dir.glob("*.json"))
    print(f"sidecars: {len(sidecars)} under {stats_dir}")

    dry_run = not args.commit
    report = rofl_stats_backfill.backfill_tracked_summary(
        db_path, sidecars, dry_run=dry_run
    )

    mode = "DRY-RUN (nothing written; pass --commit to write)" if dry_run else "COMMITTED"
    print(f"mode: {mode}")
    print(f"updated={len(report['updated'])} "
          f"skipped_no_operator={len(report['skipped_no_operator'])} "
          f"skipped_already_filled={len(report['skipped_already_filled'])} "
          f"net_new={len(report['net_new'])} "
          f"unresolved_champions={len(report['unresolved_champions'])}")
    for match_id in report["updated"]:
        print(f"  v {match_id}")
    for entry in report["unresolved_champions"]:
        print(f"  ? unresolved champion {entry}")
    for match_id in report["net_new"]:
        print(f"  + net-new (not in DB; use the INSERT path) {match_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
