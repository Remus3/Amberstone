"""
scripts/repair_match_db_column_types.py - lane 8 cycle 16 backfill.

Repairs rows ALREADY written by the pre-fix `core/match_db.save_match`, which
defaulted every absent column to the empty string and so stored `''` as TEXT
in columns declared INTEGER / REAL. Measured on the live DB 2026-08-30:
8395 of 8395 rows carried at least one such value.

The writer fix (core/match_db.py, same slice) stops NEW bad rows. Per the
CLAUDE.md "Data Fixes" rule a guard that only prevents future occurrences is
an incomplete fix - the existing rows stay wrong until this runs.

Coercion is delegated to `core.match_db.coerce_numeric`, the SAME function the
writer binds through, so the repaired value is by construction identical to
what the fixed writer would have stored. It is deliberately not a hand-written
CAST: two definitions of "correct" drift.

Safe to re-run: idempotent (a fully repaired DB reports 0 rows to fix), and
the UPDATE runs in a single transaction so a crash mid-repair rolls back.

Usage:
    python scripts/repair_match_db_column_types.py                  # dry run
    python scripts/repair_match_db_column_types.py --apply
    python scripts/repair_match_db_column_types.py --apply --db <path>
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.match_db import NUMERIC_COLS, coerce_numeric  # noqa: E402

DEFAULT_DB = Path(r"C:\Riot Commander\data\match_history.db")

# typeof() values that mean "this is already a number".
_GOOD = ("integer", "real")


def _numeric_columns_present(conn: sqlite3.Connection) -> list:
    """Intersect the schema's numeric set with what this DB actually has.

    A legacy DB may predate some columns (see the Item 211 note in
    core/match_db.py), so never assume the full set exists.
    """
    have = {r[1] for r in conn.execute("PRAGMA table_info(matches)")}
    return sorted(NUMERIC_COLS & have)


def scan(conn: sqlite3.Connection) -> tuple:
    """Return (columns, rows_needing_repair, per_column_counts)."""
    cols = _numeric_columns_present(conn)
    if not cols:
        return [], [], {}
    counts = {}
    for col in cols:
        counts[col] = conn.execute(
            f"SELECT COUNT(*) FROM matches WHERE typeof({col}) NOT IN (?, ?)",
            _GOOD,
        ).fetchone()[0]
    where = " OR ".join(
        f"typeof({c}) NOT IN ('integer','real')" for c in cols)
    rows = conn.execute(
        f"SELECT id, {', '.join(cols)} FROM matches WHERE {where}"
    ).fetchall()
    return cols, rows, counts


def repair(db_path: Path, apply: bool = False) -> dict:
    """Scan and (optionally) repair. Returns a summary dict."""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA busy_timeout = 5000")
        total = conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
        cols, rows, counts = scan(conn)
        summary = {
            "db": str(db_path),
            "total_rows": total,
            "rows_to_fix": len(rows),
            "per_column": {c: n for c, n in counts.items() if n},
            "applied": False,
        }
        if not rows or not apply:
            return summary
        assignments = ", ".join(f"{c} = ?" for c in cols)
        payload = []
        for row in rows:
            row_id = row[0]
            payload.append(
                tuple(coerce_numeric(c, row[i + 1]) for i, c in enumerate(cols))
                + (row_id,))
        # One transaction: a crash mid-repair leaves the DB untouched rather
        # than half-converted.
        with conn:
            conn.executemany(
                f"UPDATE matches SET {assignments} WHERE id = ?", payload)
        # Re-scan on the same connection to prove the repair landed rather
        # than trusting the rowcount.
        _, remaining, _ = scan(conn)
        summary["applied"] = True
        summary["rows_remaining_bad"] = len(remaining)
        return summary
    finally:
        conn.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--apply", action="store_true",
                    help="write the repair (default is a dry run)")
    args = ap.parse_args(argv)
    if not args.db.exists():
        print(f"match DB not found: {args.db}")
        return 2
    s = repair(args.db, apply=args.apply)
    print(f"db:          {s['db']}")
    print(f"total rows:  {s['total_rows']}")
    print(f"rows to fix: {s['rows_to_fix']}")
    for col, n in sorted(s["per_column"].items()):
        print(f"   {col:<18} {n}")
    if s["applied"]:
        print("APPLIED. rows still bad after repair: "
              f"{s['rows_remaining_bad']}")
        return 0 if s["rows_remaining_bad"] == 0 else 1
    if s["rows_to_fix"]:
        print("DRY RUN - re-run with --apply to write the repair.")
    else:
        print("nothing to repair.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
