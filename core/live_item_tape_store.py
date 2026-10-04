# arch: RM-607 live inventory tape - game-end timeline_events persistence | section=core | frozen=no
"""Game-end persistence for the RM-607 live inventory tape.

Writes the tape's ITEM_PURCHASED / ITEM_SOLD / ITEM_COMBINED events into
``data/rewind_history.db`` ``timeline_events`` with a ``source`` column.

``source`` column decision (recorded per the RM-607 brief)
----------------------------------------------------------
* Appended at the END of ``timeline_events`` by an additive
  ``ALTER TABLE ... ADD COLUMN source TEXT`` with DEFAULT NULL.
* NULL means "match_v5": every row written before the column existed, and
  every row written by a writer that never names the column (the Match-V5
  writers ``scripts/rewind_catchup.py`` / ``lib/rewind_live_writer.py`` /
  ``scripts/rewind_scraper.py``), reads back as Match-V5. ``source_label``
  maps NULL to ``"match_v5"``.
* Tape rows always write ``source = 'live_tape'`` explicitly.
* Rejected: DEFAULT 'live_tape' (the directive's wording) - it would label
  every existing and every future Match-V5 row as tape. Rejected: DEFAULT
  'match_v5' - it asserts a provenance the DB never verified for rows that
  arrived from the older scraper; NULL says "no writer claimed a source".
* The shared ``SCHEMA`` text in ``scripts/rewind_scraper.py`` is NOT edited.
  The column is added lazily, only by ``persist_tape``; every reader here
  works whether or not it exists.

Read rule: Match-V5 rows win
----------------------------
For one match, if ANY non-tape item row (ITEM_PURCHASED / ITEM_SOLD /
ITEM_DESTROYED / ITEM_UNDO with ``source`` NULL or not 'live_tape') exists,
readers use ONLY those rows; tape rows are a fallback for matches Match-V5
never served (ARAM Mayhem / KIWI queue 2400, other event modes). Enforced at
three points: ``persist_tape`` refuses to write when Match-V5 rows exist,
``item_events`` applies the rule on read, and
``purge_superseded_tape_rows`` deletes tape rows once Match-V5 arrives.
EXISTING readers (core/item_wpa.py, core/aram_item_interaction.py,
core/ds_calibration_agreement.py, dashboard/routes_replay_events.py, ...) do
not filter on ``source``. They never double count because
``scripts/rewind_catchup.py::_insert_timeline_rows`` (the single Match-V5
timeline insert path, also used by lib/rewind_live_writer.py) calls
``purge_superseded_tape_rows`` right after inserting, so tape rows survive
only for matches with no Match-V5 item rows.

Wiring (RC_ITEM_TAPE, default OFF): the listener is installed from
``core.liveclient_cache._install_optional_taps``; the persist is scheduled by
``on_game_end_if_enabled`` from
``lcu.lcu_postgame_collector.PostgameCollector._publish_game_end_pin``. With
the flag OFF nothing is installed or written and the shared
``timeline_events`` table is never altered.

No ``matches`` row is ever created here: ``write_match`` treats an existing
``matches`` row as "children already written" and would skip participants /
teams for that match. Tape rows reference their match_id like Match-V5 rows
do; the connection leaves SQLite foreign-key enforcement at its default (off).
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable, Optional

from core import live_item_tape as lit

_log = logging.getLogger(__name__)

SOURCE_COLUMN = "source"
SOURCE_TAPE = "live_tape"
SOURCE_V5 = "match_v5"

# Match-V5 item event types (the rows that "win").
V5_ITEM_TYPES: tuple[str, ...] = (
    "ITEM_PURCHASED", "ITEM_SOLD", "ITEM_DESTROYED", "ITEM_UNDO")
_READ_TYPES: tuple[str, ...] = tuple(sorted(set(V5_ITEM_TYPES) | lit.PERSISTED_TYPES))

_TEAM_ID = {"ORDER": 100, "CHAOS": 200}

_DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "rewind_history.db"

# Our own number: lib/rewind_live_writer.py documents a ~150 s worst-case wall
# (90 s delay + 60 s retry + one fetch). Waiting past it lets the
# "Match-V5 present -> skip" check see the live writer's rows.
DEFAULT_DELAY_S = 180.0

_WRITE_LOCK = threading.Lock()


def source_label(value: Any) -> str:
    """Read-side meaning of a ``source`` cell: NULL is Match-V5."""
    return SOURCE_V5 if value is None else str(value)


def has_source_column(conn: sqlite3.Connection) -> bool:
    return any(r[1] == SOURCE_COLUMN
               for r in conn.execute("PRAGMA table_info(timeline_events)"))


def ensure_source_column(conn: sqlite3.Connection) -> bool:
    """Additive, idempotent migration. True when the column was added now."""
    if has_source_column(conn):
        return False
    try:
        conn.execute(f"ALTER TABLE timeline_events ADD COLUMN {SOURCE_COLUMN} "
                     "TEXT DEFAULT NULL")
    except sqlite3.OperationalError as exc:
        if "duplicate column" in str(exc).lower():   # a racing writer won
            return False
        raise
    return True


def match_id_for(platform: Any, game_id: Any) -> Optional[str]:
    """Match-V5 style id ``<PLATFORM>_<gameId>`` (e.g. NA1_123), or None."""
    if not isinstance(platform, str) or not platform.strip():
        return None
    if isinstance(game_id, bool) or game_id is None:
        return None
    gid = str(game_id).strip()
    if not gid.isdigit():
        return None
    return f"{platform.strip().upper()}_{gid}"


def _v5_item_rows_exist(conn: sqlite3.Connection, match_id: str,
                        with_source: bool) -> bool:
    ph = ",".join("?" * len(V5_ITEM_TYPES))
    sql = (f"SELECT 1 FROM timeline_events WHERE match_id=? "
           f"AND event_type IN ({ph})")
    if with_source:
        sql += f" AND ({SOURCE_COLUMN} IS NULL OR {SOURCE_COLUMN} != ?)"
        args: tuple = (match_id, *V5_ITEM_TYPES, SOURCE_TAPE)
    else:
        args = (match_id, *V5_ITEM_TYPES)
    return conn.execute(sql + " LIMIT 1", args).fetchone() is not None


def _participant_ids(conn: sqlite3.Connection, match_id: str) -> dict:
    """``(riot id, team_id) -> participant_id`` from the participants table,
    when Match-V5 detail is present. Identity-keyed, never positional."""
    out: dict = {}
    try:
        rows = conn.execute(
            "SELECT participant_id, team_id, riot_id_game_name, riot_id_tagline "
            "FROM participants WHERE match_id=?", (match_id,)).fetchall()
    except sqlite3.Error:
        return out
    for pid, team_id, name, tag in rows:
        if name and tag:
            out[(f"{name}#{tag}", team_id)] = pid
    return out


def build_rows(match_id: str, events: Iterable[lit.TapeEvent],
               participant_ids: dict | None = None) -> list[dict]:
    """Persisted-type events -> timeline_events rows (one row per copy, the
    Match-V5 convention). Other tape types are not rows."""
    pids = participant_ids or {}
    rows: list[dict] = []
    for e in events:
        if e.event_type not in lit.PERSISTED_TYPES:
            continue
        team_id = _TEAM_ID.get(e.team)
        raw = {"riot_id": e.player, "team": e.team}
        if e.components:
            raw["components"] = list(e.components)
        for _ in range(max(1, int(e.count))):
            rows.append({
                "match_id": match_id,
                "timestamp_ms": int(round(e.game_time_s * 1000)),
                "event_type": e.event_type,
                "participant_id": pids.get((e.player, team_id)),
                "item_id": e.item_id,
                "team_id": team_id,
                "raw_json": json.dumps(raw, sort_keys=True),
                SOURCE_COLUMN: SOURCE_TAPE,
            })
    return rows


def persist_tape(conn: sqlite3.Connection, match_id: str,
                 events: Iterable[lit.TapeEvent]) -> dict:
    """Write one game's tape in a single transaction. Match-V5 wins: when its
    item rows already exist nothing is written. Re-persisting replaces."""
    events = list(events)
    with _WRITE_LOCK:
        if _v5_item_rows_exist(conn, match_id, has_source_column(conn)):
            return {"status": "v5_present", "match_id": match_id, "rows": 0}
        rows = build_rows(match_id, events, _participant_ids(conn, match_id))
        if not rows:
            return {"status": "empty", "match_id": match_id, "rows": 0}
        try:
            ensure_source_column(conn)
            conn.execute(f"DELETE FROM timeline_events WHERE match_id=? "
                         f"AND {SOURCE_COLUMN}=?", (match_id, SOURCE_TAPE))
            cols = list(rows[0].keys())
            conn.executemany(
                f"INSERT INTO timeline_events ({', '.join(cols)}) "
                f"VALUES ({', '.join('?' * len(cols))})",
                [tuple(r[c] for c in cols) for r in rows])
            conn.commit()
        except sqlite3.Error:
            conn.rollback()
            raise
    return {"status": "written", "match_id": match_id, "rows": len(rows)}


def item_events(conn: sqlite3.Connection, match_id: str) -> list:
    """Item rows for one match under the read rule (Match-V5 wins)."""
    ph = ",".join("?" * len(_READ_TYPES))
    base = (f"SELECT * FROM timeline_events WHERE match_id=? "
            f"AND event_type IN ({ph})")
    if not has_source_column(conn):
        return conn.execute(base + " ORDER BY timestamp_ms, id",
                            (match_id, *_READ_TYPES)).fetchall()
    if _v5_item_rows_exist(conn, match_id, True):
        cond = f" AND ({SOURCE_COLUMN} IS NULL OR {SOURCE_COLUMN} != ?)"
    else:
        cond = f" AND {SOURCE_COLUMN} = ?"
    return conn.execute(base + cond + " ORDER BY timestamp_ms, id",
                        (match_id, *_READ_TYPES, SOURCE_TAPE)).fetchall()


def purge_superseded_tape_rows(conn: sqlite3.Connection,
                               match_id: str | None = None) -> int:
    """Delete tape rows for every match (or one) that now has Match-V5 item
    rows. Never adds the column. Caller commits. Returns rows deleted."""
    if not has_source_column(conn):
        return 0
    ph = ",".join("?" * len(V5_ITEM_TYPES))
    sql = (f"DELETE FROM timeline_events WHERE {SOURCE_COLUMN} = ? "
           f"AND match_id IN (SELECT match_id FROM timeline_events "
           f"WHERE event_type IN ({ph}) AND ({SOURCE_COLUMN} IS NULL "
           f"OR {SOURCE_COLUMN} != ?))")
    args: list = [SOURCE_TAPE, *V5_ITEM_TYPES, SOURCE_TAPE]
    if match_id is not None:
        sql += " AND match_id = ?"
        args.append(match_id)
    return conn.execute(sql, args).rowcount


def _persist_to_path(db_path: Path, match_id: str,
                     events: list[lit.TapeEvent]) -> dict:
    if not Path(db_path).is_file():
        # The rewind DB is created by the Match-V5 pipeline; never create it.
        return {"status": "no_db", "match_id": match_id, "rows": 0}
    try:
        conn = sqlite3.connect(str(db_path), timeout=10.0)
    except sqlite3.Error as exc:
        _log.warning("live_item_tape_store: open failed: %s", exc)
        return {"status": "error", "match_id": match_id, "rows": 0}
    try:
        return persist_tape(conn, match_id, events)
    except sqlite3.Error as exc:
        _log.warning("live_item_tape_store: write failed for %s: %s", match_id, exc)
        return {"status": "error", "match_id": match_id, "rows": 0}
    finally:
        conn.close()


def on_game_end_if_enabled(game_id: Any, *, platform: str | None = None) -> dict:
    """Flag-gated game-end hook, called from
    ``lcu.lcu_postgame_collector.PostgameCollector._publish_game_end_pin`` with
    the end-of-game gameId. Flag OFF: returns at once - no drain, no write,
    the shared table is never altered. Flag ON: builds
    ``<PLATFORM>_<gameId>`` (platform from ``core.operator_identity``) and
    schedules ``on_game_end`` on a daemon Timer (DEFAULT_DELAY_S), so the
    collector thread is never blocked."""
    if not lit.is_enabled():
        return {"status": "disabled"}
    if platform is None:
        try:
            from core.operator_identity import platform as _platform
            platform = _platform()
        except Exception:  # noqa: BLE001
            platform = None
    return on_game_end(match_id_for(platform, game_id))


def on_game_end(match_id: str | None, *, db_path: Path | None = None,
                delay_s: float = DEFAULT_DELAY_S,
                events: list[lit.TapeEvent] | None = None) -> dict:
    """Game-end entry point. Drains the process tape (or uses ``events``)
    and persists it under ``match_id``. ``delay_s <= 0`` runs inline and
    returns the write result; otherwise a daemon Timer fires later and this
    returns ``{"status": "scheduled"}``. Never raises."""
    try:
        evs = list(events) if events is not None else lit.drain_tape()
    except Exception as exc:  # noqa: BLE001 - lifecycle hook must not raise
        _log.warning("live_item_tape_store: drain failed: %s", exc)
        return {"status": "error", "events": 0}
    if not match_id:
        return {"status": "no_match_id", "events": len(evs)}
    path = Path(db_path) if db_path is not None else _DEFAULT_DB
    if delay_s <= 0:
        return _persist_to_path(path, match_id, evs)
    timer = threading.Timer(delay_s, _persist_to_path, args=(path, match_id, evs))
    timer.daemon = True
    timer.start()
    return {"status": "scheduled", "match_id": match_id, "events": len(evs)}
