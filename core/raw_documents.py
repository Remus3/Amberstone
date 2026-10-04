"""RM-611 (X-11, external reference E): retained raw League documents.

The post-game collector (lcu/lcu_postgame_collector.py) already fetches three
documents per game - the end-of-game stats block, the match-history game
entry (fallback path) and the LCU timeline - and used to discard each one
after parsing. This module keeps them, gzipped, so a display field that turns
out to be wrongly extracted is fixed by re-running a versioned extractor over
the retained bytes instead of by a hand-written backfill.

Storage: one additive table ``raw_documents`` in the DB the collector already
writes (data/postgame_stats.db, gitignored by ``**/*.db``). Raw documents
name nine other players, so they never leave that gitignored path.

One row per (match_id, kind). The first capture wins: a finished game's
documents do not change, and keeping the first copy makes a repeat capture
(history fallback after an EOG save, a re-trigger) a no-op.
"""
from __future__ import annotations

import gzip
import json
import sqlite3
import time
from typing import Any

KINDS = ("eog", "match", "timeline")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS raw_documents (
    match_id    TEXT NOT NULL,
    kind        TEXT NOT NULL,
    fetched_at  TEXT NOT NULL,
    body        BLOB NOT NULL,
    PRIMARY KEY (match_id, kind)
)
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(SCHEMA_SQL)


def encode(doc: Any) -> bytes:
    """Compact JSON, gzip with mtime=0 so equal documents give equal bytes."""
    raw = json.dumps(doc, separators=(",", ":"), sort_keys=True,
                     default=str).encode("utf-8")
    return gzip.compress(raw, mtime=0)


def decode(body: bytes) -> Any:
    return json.loads(gzip.decompress(bytes(body)).decode("utf-8"))


def store(conn: sqlite3.Connection, match_id: str, kind: str, doc: Any,
          fetched_at: str | None = None) -> bool:
    """Insert one document. Returns True when a row was written, False when
    that (match_id, kind) was already held. The caller commits."""
    match_id = str(match_id or "").strip()
    if not match_id:
        raise ValueError("raw_documents: empty match_id")
    if kind not in KINDS:
        raise ValueError(f"raw_documents: unknown kind {kind!r}")
    if fetched_at is None:
        fetched_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    cur = conn.execute(
        "INSERT OR IGNORE INTO raw_documents (match_id, kind, fetched_at, body)"
        " VALUES (?,?,?,?)",
        (match_id, kind, fetched_at, sqlite3.Binary(encode(doc))))
    return cur.rowcount == 1


def load(conn: sqlite3.Connection, match_id: str, kind: str) -> Any | None:
    row = conn.execute(
        "SELECT body FROM raw_documents WHERE match_id=? AND kind=?",
        (str(match_id), kind)).fetchone()
    return decode(row[0]) if row else None


def kinds_for(conn: sqlite3.Connection, match_id: str) -> list[str]:
    return [r[0] for r in conn.execute(
        "SELECT kind FROM raw_documents WHERE match_id=? ORDER BY kind",
        (str(match_id),))]
