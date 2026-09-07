"""
scripts/prune_synthetic_matches.py
----------------------------------
One-shot cleanup for synthetic test rows in `data/match_history.db` and
`data/ds_calibration.jsonl`. Run with --dry-run first to see what would
be removed; rerun without the flag to commit. Both targets are backed
up to .bak-YYYY-MM-DD-prune-synthetic before any write.

What counts as synthetic (conservative - keeps anything ambiguous):
  * matches.champion = 'Dark Star Vertical' (TFT comp name leaked into
    the champion field during a dev test pass - not a real champion).
  * matches.champion = '' AND matches.game_time_s = 0 (no champion AND
    no gameplay duration).

DS calibration JSONL: an entry is synthetic when its `champion` field is
empty/None or one of the known dev-only labels.

Usage:
  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe scripts\\prune_synthetic_matches.py --dry-run
  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe scripts\\prune_synthetic_matches.py
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MATCH_DB = ROOT / "data" / "match_history.db"
DS_JSONL = ROOT / "data" / "ds_calibration.jsonl"

# Champions/comps that are NOT real League champions - when they appear
# in the matches.champion column they're test fixture leakage.
SYNTHETIC_CHAMPION_NAMES: set[str] = {
    "Dark Star Vertical",
}


def backup_path(orig: Path, suffix: str) -> Path:
    today = time.strftime("%Y-%m-%d")
    return orig.with_suffix(orig.suffix + f".bak-{today}-{suffix}")


def prune_match_db(dry_run: bool) -> dict:
    if not MATCH_DB.exists():
        print(f"  {MATCH_DB} missing; skipping")
        return {}
    conn = sqlite3.connect(str(MATCH_DB))
    cur = conn.cursor()

    # Build the WHERE clauses; report row counts BEFORE deleting so the
    # dry-run output is honest.
    placeholders = ",".join("?" * len(SYNTHETIC_CHAMPION_NAMES))
    where_synthetic_name = f"champion IN ({placeholders})"
    args_synthetic_name = tuple(SYNTHETIC_CHAMPION_NAMES)

    where_empty_zero = "champion = '' AND game_time_s = 0"

    cur.execute(
        f"SELECT COUNT(*) FROM matches WHERE {where_synthetic_name}",
        args_synthetic_name,
    )
    n_named = cur.fetchone()[0]
    cur.execute(f"SELECT COUNT(*) FROM matches WHERE {where_empty_zero}")
    n_empty_zero = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM matches")
    n_total = cur.fetchone()[0]

    print(f"  match_history.db rows: {n_total}")
    print(f"    synthetic-named (champion IN {sorted(SYNTHETIC_CHAMPION_NAMES)}): {n_named}")
    print(f"    empty champion + zero duration: {n_empty_zero}")

    if dry_run:
        print("  --dry-run set; no writes performed")
        conn.close()
        return {"named": n_named, "empty_zero": n_empty_zero, "deleted": 0}

    if n_named + n_empty_zero == 0:
        print("  nothing to prune")
        conn.close()
        return {"named": 0, "empty_zero": 0, "deleted": 0}

    bak = backup_path(MATCH_DB, "prune-synthetic")
    if bak.exists():
        bak = bak.with_suffix(bak.suffix + f"-{int(time.time())}")
    print(f"  Backing up -> {bak.name}")
    # close before copy so WAL state is consistent
    conn.close()
    shutil.copy2(MATCH_DB, bak)
    conn = sqlite3.connect(str(MATCH_DB))
    cur = conn.cursor()

    cur.execute(
        f"DELETE FROM matches WHERE {where_synthetic_name}",
        args_synthetic_name,
    )
    cur.execute(f"DELETE FROM matches WHERE {where_empty_zero}")
    conn.commit()

    cur.execute("SELECT COUNT(*) FROM matches")
    n_after = cur.fetchone()[0]
    conn.close()
    deleted = n_total - n_after
    print(f"  Deleted: {deleted} rows ({n_total} -> {n_after})")
    return {"named": n_named, "empty_zero": n_empty_zero, "deleted": deleted}


def prune_ds_calibration(dry_run: bool) -> dict:
    if not DS_JSONL.exists():
        print(f"  {DS_JSONL} missing; skipping")
        return {}
    lines = DS_JSONL.read_text(encoding="utf-8").splitlines()
    n_in = len(lines)
    keep: list[str] = []
    drop: list[dict] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            keep.append(line)
            continue
        champ = (entry.get("champion") or "").strip()
        is_synthetic = (
            not champ
            or champ in SYNTHETIC_CHAMPION_NAMES
            or champ.lower().startswith(("test", "fake", "sim"))
        )
        if is_synthetic:
            drop.append(entry)
        else:
            keep.append(line)
    print(f"  ds_calibration.jsonl entries: {n_in}")
    print(f"    would drop: {len(drop)}")

    if dry_run or not drop:
        return {"in": n_in, "dropped": len(drop) if not dry_run else 0,
                "kept": len(keep)}

    bak = backup_path(DS_JSONL, "prune-synthetic")
    if bak.exists():
        bak = bak.with_suffix(bak.suffix + f"-{int(time.time())}")
    print(f"  Backing up -> {bak.name}")
    shutil.copy2(DS_JSONL, bak)
    tmp = DS_JSONL.with_suffix(".tmp")
    tmp.write_text("\n".join(keep) + ("\n" if keep else ""), encoding="utf-8")
    tmp.replace(DS_JSONL)
    print(f"  Wrote {len(keep)} kept entries")
    return {"in": n_in, "dropped": len(drop), "kept": len(keep)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip())
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would be deleted; no writes")
    args = parser.parse_args()

    print("== match_history.db ==")
    mh = prune_match_db(args.dry_run)
    print("\n== ds_calibration.jsonl ==")
    ds = prune_ds_calibration(args.dry_run)

    print("\n== summary ==")
    print(f"  match_history.db: {mh}")
    print(f"  ds_calibration:   {ds}")
    if args.dry_run:
        print("\n  (dry-run) Re-run without --dry-run to commit.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
