"""Round 23 - idempotent schema upgrade adding ``kills/deaths/assists``
columns to every mode DB's ``matches`` table.

New DBs get these columns natively via ``db_schema.SCHEMA_STATEMENTS``.
Pre-existing DBs (anything created before this round) need the ALTER.
SQLite's ``ALTER TABLE ADD COLUMN`` is O(1) and safe on WAL databases.

Runs automatically on supervisor boot right after ``init_all()``. Also
exposes a CLI for manual/one-shot use (exit 1 when any mode failed).

Contract (S144-T-598):

- The connection is CLOSED on every path. ``with sqlite3.connect(...)``
  alone only commits or rolls back, it never closes.
- The database is opened read-write WITHOUT create (SQLite URI
  ``mode=rw``), so a file that vanishes between the existence check and the
  open is never re-created as an empty database. A UNC path (a file: URI
  with an authority is refused by a default SQLite build) falls back to a
  plain connect after the existence check.
- A database with no ``matches`` table has nothing to migrate: every column
  reads False and a warning is logged; no table is created.
- ``ensure_all`` migrates EVERY mode even when one raises a database or OS
  error, then raises ``KdaMigrationError`` naming the failed modes and the
  exception TYPE only, carrying the per-mode results that did succeed. Any
  other exception is a programming error and propagates at once.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
import sqlite3
from pathlib import Path, PurePath
from typing import Iterable

from agents.agent2_backend.db_schema import MODE_DB_FILES, db_path

logger = logging.getLogger("agent2.db_migrate_kda")

KDA_COLUMNS = ("kills", "deaths", "assists")


class KdaMigrationError(RuntimeError):
    """One or more mode databases could not be migrated.

    ``failed`` maps mode -> exception type name; ``results`` holds the
    per-mode outcome of every mode that DID migrate.
    """

    def __init__(self, failed: dict[str, str], results: dict[str, dict[str, bool]]):
        self.failed = dict(failed)
        self.results = dict(results)
        detail = ", ".join(f"{mode}: {name}" for mode, name in self.failed.items())
        super().__init__(f"KDA migration failed for {len(self.failed)} mode(s) ({detail})")


def _rw_uri(path: PurePath) -> str | None:
    """SQLite URI opening ``path`` read-write without create, or None for a
    UNC path (its file: URI carries an authority SQLite refuses).

    The UNC check runs on the RESOLVED path: a local-looking path can
    resolve to a share (a symlink to one, or a mapped network drive)."""
    unc = ("\\\\", "//")
    if str(path).startswith(unc):
        return None  # already UNC: no need to touch the network to resolve it
    resolved = (path if isinstance(path, Path) else Path(path)).resolve()
    if str(resolved).startswith(unc):
        return None
    return f"{resolved.as_uri()}?mode=rw"


def _connect_existing(path: Path) -> sqlite3.Connection:
    uri = _rw_uri(path)
    if uri is None:
        return sqlite3.connect(path)
    return sqlite3.connect(uri, uri=True)


def _existing_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {r[1] for r in rows}


def _add_column(conn: sqlite3.Connection, col: str) -> None:
    conn.execute(f"ALTER TABLE matches ADD COLUMN {col} INTEGER")


def ensure_kda_columns(path: str | os.PathLike) -> dict[str, bool]:
    """Add any missing KDA columns to the ``matches`` table at ``path``.

    Returns ``{col: added_bool}``. ``added=False`` means the column was
    already present - or that there was nothing to migrate (no database
    file, or no ``matches`` table in it). Never raises on the
    duplicate-column path; any other database error propagates after the
    connection is closed.
    """
    # A Path (or subclass) is used as given; a str / str os.PathLike is
    # wrapped, and Path() raises TypeError for anything else (None, an int,
    # a bool, bytes, a list) before any database is touched.
    if not isinstance(path, Path):
        path = Path(path)
    if not path.exists():
        return dict.fromkeys(KDA_COLUMNS, False)
    added: dict[str, bool] = {}
    with contextlib.closing(_connect_existing(path)) as conn:
        existing = _existing_columns(conn, "matches")
        if not existing:
            # A table always has at least one column, so an empty answer
            # means there is no matches table to migrate.
            logger.warning("no matches table in %s - nothing to migrate", path.name)
            return dict.fromkeys(KDA_COLUMNS, False)
        # SQLite column names are case-insensitive.
        existing_folded = {name.casefold() for name in existing}
        for col in KDA_COLUMNS:
            if col in existing_folded:
                added[col] = False
                continue
            try:
                _add_column(conn, col)
                added[col] = True
                logger.info("added matches.%s to %s", col, path.name)
            except sqlite3.OperationalError as e:
                # Race / someone beat us to it.
                if "duplicate column name" in str(e).lower():
                    added[col] = False
                else:
                    raise
        conn.commit()
    return added


def ensure_all() -> dict[str, dict[str, bool]]:
    """Migrate every mode database; see the module contract for failures."""
    out: dict[str, dict[str, bool]] = {}
    failed: dict[str, str] = {}
    for mode in MODE_DB_FILES:
        try:
            out[mode] = ensure_kda_columns(db_path(mode))
        except (sqlite3.Error, OSError) as e:
            failed[mode] = type(e).__name__
            logger.warning("KDA migration failed for mode %s: %s", mode, type(e).__name__)
    if failed:
        raise KdaMigrationError(failed, out)
    return out


def main(argv: Iterable[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(list(argv) if argv is not None else None)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    try:
        result = ensure_all()
    except KdaMigrationError as e:
        print(json.dumps({"results": e.results, "failed": e.failed}, indent=2))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
