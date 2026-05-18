"""Round 23 - idempotent schema upgrade adding ``kills/deaths/assists``
columns to every mode DB's ``matches`` table.

New DBs get these columns natively via ``db_schema.SCHEMA_STATEMENTS``.
Pre-existing DBs (anything created before this round) need the ALTER.
SQLite's ``ALTER TABLE ADD COLUMN`` is O(1) and safe on WAL databases.

Runs automatically on supervisor boot right after ``init_all()``. Also
exposes a CLI for manual/one-shot use.
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
from pathlib import Path
from typing import Iterable

from agents.agent2_backend.db_schema import MODE_DB_FILES, db_path

logger = logging.getLogger("agent2.db_migrate_kda")

KDA_COLUMNS = ("kills", "deaths", "assists")


def _existing_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {r[1] for r in rows}


def ensure_kda_columns(path: Path) -> dict[str, bool]:
    """Add any missing KDA columns to the ``matches`` table at ``path``.

    Returns ``{col: added_bool}``. ``added=False`` means the column was
    already present. Never raises on the duplicate-column path.
    """
    if not path.exists():
        return {c: False for c in KDA_COLUMNS}
    added: dict[str, bool] = {}
    with sqlite3.connect(path) as conn:
        existing = _existing_columns(conn, "matches")
        for col in KDA_COLUMNS:
            if col in existing:
                added[col] = False
                continue
            try:
                conn.execute(f"ALTER TABLE matches ADD COLUMN {col} INTEGER")
                added[col] = True
                logger.info("added matches.%s to %s", col, path.name)
            except sqlite3.OperationalError as e:
                # Race / someone beat us to it - check again.
                if "duplicate column name" in str(e).lower():
                    added[col] = False
                else:
                    raise
        conn.commit()
    return added


def ensure_all() -> dict[str, dict[str, bool]]:
    out: dict[str, dict[str, bool]] = {}
    for mode in MODE_DB_FILES:
        out[mode] = ensure_kda_columns(db_path(mode))
    return out


def main(argv: Iterable[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(list(argv) if argv is not None else None)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    result = ensure_all()
    import json as _json
    print(_json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
