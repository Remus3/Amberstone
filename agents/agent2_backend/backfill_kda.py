"""Round 23 - backfill ``matches.kills/deaths/assists`` for rows
migrated from ``rewind_history.db``.

The rewind migration (see ``migration_rewind.py``) ran before the KDA
columns existed, so every pre-round-23 row has NULLs. Rewind's own
``matches`` table already stores the tracked player's KDA directly
on the row (``tracked_kills/tracked_deaths/tracked_assists``). This
script joins mode-DB rows to their source rewind rows via the
``_migration_state`` table and UPDATEs in bulk.

Idempotent: the query skips rows where any of ``kills/deaths/assists``
is already populated (re-running never overwrites live-match data or
a previous backfill).

Usage:
  python -m agents.agent2_backend.backfill_kda
  python -m agents.agent2_backend.backfill_kda --mode aram
  python -m agents.agent2_backend.backfill_kda --dry-run
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Iterable

from agents.agent2_backend.db_schema import MODE_DB_FILES, db_path
from agents.agent2_backend.db_migrate_kda import ensure_kda_columns
from agents.agent2_backend.migration_rewind import SOURCE_TAG

logger = logging.getLogger("agent2.backfill_kda")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
REWIND_DB = _PROJECT_ROOT / "data" / "rewind_history.db"

BATCH_SIZE = 500


def _open_rewind() -> sqlite3.Connection:
    if not REWIND_DB.exists():
        raise FileNotFoundError(f"rewind DB missing: {REWIND_DB}")
    uri = f"file:{REWIND_DB.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _fetch_kda_for_refs(
    rewind: sqlite3.Connection, refs: list[str]
) -> dict[str, tuple[int | None, int | None, int | None]]:
    """Pull {rewind_match_id: (k, d, a)} for the given source_refs.
    Breaks the IN list into 500-row batches (SQLite's default cap is 999)."""
    out: dict[str, tuple[int | None, int | None, int | None]] = {}
    for i in range(0, len(refs), BATCH_SIZE):
        chunk = refs[i : i + BATCH_SIZE]
        qs = ",".join("?" for _ in chunk)
        rows = rewind.execute(
            f"""
            SELECT match_id, tracked_kills, tracked_deaths, tracked_assists
            FROM matches
            WHERE match_id IN ({qs})
            """,
            chunk,
        ).fetchall()
        for r in rows:
            out[str(r["match_id"])] = (
                r["tracked_kills"],
                r["tracked_deaths"],
                r["tracked_assists"],
            )
    return out


def backfill_mode(
    mode: str, rewind: sqlite3.Connection, dry_run: bool = False
) -> dict:
    """Backfill KDA for one mode DB. Returns summary dict."""
    mpath = db_path(mode)
    if not mpath.exists():
        return {"mode": mode, "skipped": True, "reason": "DB missing"}

    # Ensure columns exist before any SELECT/UPDATE references them.
    ensure_kda_columns(mpath)

    conn = sqlite3.connect(mpath)
    conn.row_factory = sqlite3.Row
    try:
        # Find rewind-sourced rows that still have NULL KDA.
        rows = conn.execute(
            """
            SELECT m.match_id AS local_id, ms.source_ref AS ref
            FROM matches m
            JOIN _migration_state ms
              ON ms.local_match_id = m.match_id
             AND ms.source = ?
            WHERE (m.kills IS NULL OR m.deaths IS NULL OR m.assists IS NULL)
            """,
            (SOURCE_TAG,),
        ).fetchall()
        if not rows:
            return {
                "mode": mode,
                "candidates": 0,
                "updated": 0,
                "missing_in_rewind": 0,
            }

        refs = [r["ref"] for r in rows]
        kda_map = _fetch_kda_for_refs(rewind, refs)

        updates: list[tuple[int | None, int | None, int | None, int]] = []
        missing = 0
        for r in rows:
            triple = kda_map.get(r["ref"])
            if triple is None:
                missing += 1
                continue
            k, d, a = triple
            if k is None and d is None and a is None:
                # Rewind has the row but its tracked_* cols are NULL - skip,
                # but don't count as missing (row *was* findable).
                continue
            updates.append((k, d, a, int(r["local_id"])))

        if dry_run:
            return {
                "mode": mode,
                "candidates": len(rows),
                "would_update": len(updates),
                "missing_in_rewind": missing,
                "dry_run": True,
            }

        if updates:
            conn.executemany(
                "UPDATE matches SET kills = ?, deaths = ?, assists = ? "
                "WHERE match_id = ?",
                updates,
            )
            conn.commit()
        return {
            "mode": mode,
            "candidates": len(rows),
            "updated": len(updates),
            "missing_in_rewind": missing,
        }
    finally:
        conn.close()


def backfill_all(dry_run: bool = False, modes: Iterable[str] | None = None) -> dict:
    target_modes = tuple(modes) if modes else tuple(MODE_DB_FILES)
    rewind = _open_rewind()
    try:
        per_mode: dict[str, dict] = {}
        for m in target_modes:
            per_mode[m] = backfill_mode(m, rewind, dry_run=dry_run)
    finally:
        rewind.close()
    total_updated = sum(v.get("updated", 0) for v in per_mode.values())
    return {
        "per_mode": per_mode,
        "total_updated": total_updated,
        "dry_run": dry_run,
    }


def main(argv: Iterable[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Backfill rewind KDA into mode DBs")
    p.add_argument("--mode", choices=tuple(MODE_DB_FILES),
                   help="Backfill one mode (default: all)")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(list(argv) if argv is not None else None)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    t0 = time.time()
    modes = (args.mode,) if args.mode else None
    summary = backfill_all(dry_run=args.dry_run, modes=modes)
    print(json.dumps(summary, indent=2))
    print(f"[backfill_kda] elapsed {time.time()-t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
