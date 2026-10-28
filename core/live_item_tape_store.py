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
import math
import re
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable, Optional

from core import live_item_tape as lit

_log = logging.getLogger(__name__)

# Shape of a match id this store writes: an ASCII alphanumeric platform, then
# a positive gameId without leading zeros that fits a signed 64-bit int (the
# int64 bound is checked in match_id_for / _valid_match_id).
_MATCH_ID_RE = re.compile(r"[A-Z0-9]{1,16}_[1-9][0-9]{0,18}")
_MAX_GAME_ID = 2 ** 63 - 1
# Per-event sanity bounds. A tape event is built from Live Client payloads RC
# does not author (``count`` and ``itemID`` are unbounded there), so a junk
# event is DROPPED here rather than written, raised or fanned out into rows.
_MAX_GAME_TIME_S = 10 ** 6
_MAX_ITEM_ID = 2 ** 31 - 1
_MAX_COPIES = 100
_MAX_PLAYER_LEN = 128
_MAX_COMPONENTS = 16
_MAX_DELAY_S = 3600.0

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


def _game_id_int(game_id: Any) -> Optional[int]:
    """A positive int64 gameId from an int, an integral finite float or an
    ASCII-digit string, else None. Leading zeros are normalized away so the
    id matches Match-V5's ``NA1_7``, never ``NA1_007``."""
    if isinstance(game_id, bool):
        return None
    if isinstance(game_id, int):
        gid = game_id
    elif isinstance(game_id, float):
        if not math.isfinite(game_id) or not game_id.is_integer():
            return None
        gid = int(game_id)
    elif isinstance(game_id, str):
        s = game_id.strip()
        # isdigit() alone accepts superscripts and non-ASCII digits.
        if not (0 < len(s) <= 19 and s.isascii() and s.isdigit()):
            return None
        gid = int(s)
    else:
        return None
    return gid if 0 < gid <= _MAX_GAME_ID else None


def match_id_for(platform: Any, game_id: Any) -> Optional[str]:
    """Match-V5 style id ``<PLATFORM>_<gameId>`` (e.g. NA1_123), or None.

    The platform must be 1..16 ASCII alphanumerics (the rule
    ``core.operator_identity.platform`` applies); the gameId a positive int64.
    """
    if not isinstance(platform, str):
        return None
    plat = platform.strip().upper()
    if not (0 < len(plat) <= 16 and plat.isascii() and plat.isalnum()):
        return None
    gid = _game_id_int(game_id)
    if gid is None:
        return None
    return f"{plat}_{gid}"


def _valid_match_id(match_id: Any) -> bool:
    if not isinstance(match_id, str) or not _MATCH_ID_RE.fullmatch(match_id):
        return False
    return int(match_id.rsplit("_", 1)[1]) <= _MAX_GAME_ID


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


def _plain_int(value: Any, lo: int, hi: int) -> Optional[int]:
    """``value`` when it is an int (never a bool) in ``lo..hi``, else None."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if lo <= value <= hi else None


def _clean_event(e: Any) -> Optional[tuple]:
    """``(segment, game_time_s, player, team, event_type, item_id, count,
    components)`` for a well-formed PERSISTED-type tape event, else None.

    Every field is checked because a junk one used to raise out of the
    game-end persist (NaN / inf clock, str count, non-JSON components, a str
    segment) or fan out into rows (an unbounded Live Client ``count``)."""
    if not isinstance(e, lit.TapeEvent):
        return None
    if not isinstance(e.event_type, str) or e.event_type not in lit.PERSISTED_TYPES:
        return None
    segment = _plain_int(e.segment, 0, _MAX_GAME_ID)
    item_id = _plain_int(e.item_id, 1, _MAX_ITEM_ID)
    count = _plain_int(e.count, 1, _MAX_COPIES)
    t = e.game_time_s
    if isinstance(t, bool) or not isinstance(t, (int, float)):
        return None
    if not (math.isfinite(t) and 0 <= t <= _MAX_GAME_TIME_S):
        return None
    if segment is None or item_id is None or count is None:
        return None
    player, team = e.player, e.team
    if not (isinstance(player, str) and player.strip()
            and len(player) <= _MAX_PLAYER_LEN and isinstance(team, str)):
        return None
    comps = e.components
    if not isinstance(comps, (tuple, list)) or len(comps) > _MAX_COMPONENTS:
        return None
    comps = tuple(_plain_int(c, 1, _MAX_ITEM_ID) for c in comps)
    if None in comps:
        return None
    return (segment, float(t), player, team, e.event_type, item_id, count, comps)


def build_rows(match_id: str, events: Iterable[lit.TapeEvent],
               participant_ids: dict | None = None) -> list[dict]:
    """Persisted-type events -> timeline_events rows (one row per copy, the
    Match-V5 convention). Other tape types are not rows, and a malformed
    event (see ``_clean_event``) is dropped, never raised on or written."""
    pids = participant_ids or {}
    events = list(events)
    # Only the LATEST game segment belongs to this match_id: anything from an
    # earlier segment is a previous game whose end was missed (never invent).
    # Taken over EVERY tape event with a sane segment, persisted type or not:
    # a new game that so far only has baselines still outranks the old one.
    latest = max((s for s in (_plain_int(e.segment, 0, _MAX_GAME_ID)
                              for e in events if isinstance(e, lit.TapeEvent))
                  if s is not None), default=0)
    clean = [c for c in map(_clean_event, events) if c is not None]
    rows: list[dict] = []
    for segment, t, player, team, event_type, item_id, count, comps in clean:
        if segment != latest:
            continue
        team_id = _TEAM_ID.get(team)
        raw: dict = {"riot_id": player, "team": team}
        if comps:
            raw["components"] = list(comps)
        row = {
            "match_id": match_id,
            "timestamp_ms": int(round(t * 1000)),
            "event_type": event_type,
            "participant_id": pids.get((player, team_id)),
            "item_id": item_id,
            "team_id": team_id,
            "raw_json": json.dumps(raw, sort_keys=True),
            SOURCE_COLUMN: SOURCE_TAPE,
        }
        rows.extend(dict(row) for _ in range(count))
    return rows


def persist_tape(conn: sqlite3.Connection, match_id: str,
                 events: Iterable[lit.TapeEvent]) -> dict:
    """Write one game's tape in a single transaction. Match-V5 wins: when its
    item rows already exist nothing is written. Re-persisting replaces.

    The "Match-V5 present?" check and the write share ONE write transaction
    (``BEGIN IMMEDIATE``), so a Match-V5 writer in another connection or
    process cannot land between them and leave tape rows beside its own
    (readers that do not filter on ``source`` would double count). When the
    caller's connection already holds an open transaction, it is used as is.
    Any error rolls the transaction back and re-raises. A ``match_id`` that
    is not a ``<PLATFORM>_<gameId>`` id is refused without touching the DB.
    """
    if not _valid_match_id(match_id):
        return {"status": "bad_match_id", "match_id": None, "rows": 0}
    events = list(events)
    with _WRITE_LOCK:
        began = not conn.in_transaction
        if began:
            conn.execute("BEGIN IMMEDIATE")
        try:
            if _v5_item_rows_exist(conn, match_id, has_source_column(conn)):
                status = "v5_present"
                rows: list[dict] = []
            else:
                rows = build_rows(match_id, events,
                                  _participant_ids(conn, match_id))
                status = "written" if rows else "empty"
            if not rows:
                if began:
                    conn.rollback()     # nothing written: release the lock
                return {"status": status, "match_id": match_id, "rows": 0}
            ensure_source_column(conn)
            conn.execute(f"DELETE FROM timeline_events WHERE match_id=? "
                         f"AND {SOURCE_COLUMN}=?", (match_id, SOURCE_TAPE))
            cols = list(rows[0].keys())
            conn.executemany(
                f"INSERT INTO timeline_events ({', '.join(cols)}) "
                f"VALUES ({', '.join('?' * len(cols))})",
                [tuple(r[c] for c in cols) for r in rows])
            conn.commit()
        except BaseException:
            # Not only sqlite3.Error: an OverflowError at bind time used to
            # leave the DELETE pending on the caller's connection.
            if conn.in_transaction:
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
    """Open the EXISTING rewind DB and persist. Never raises: it is the body
    of a daemon Timer (an exception there kills the thread with a traceback
    on a console ``pythonw`` does not have, and the tape is lost silently)
    and the inline game-end path promises the same."""
    db_path = Path(db_path)
    if not db_path.is_file():
        # The rewind DB is created by the Match-V5 pipeline; never create it.
        return {"status": "no_db", "match_id": match_id, "rows": 0}
    try:
        # mode=rw: the file can vanish after the is_file check, and a plain
        # connect() would then create an empty rewind DB in its place.
        conn = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=rw",
                               uri=True, timeout=10.0)
    except (sqlite3.Error, OSError, ValueError) as exc:
        _log.warning("live_item_tape_store: open failed: %s", exc)
        return {"status": "error", "match_id": match_id, "rows": 0}
    try:
        return persist_tape(conn, match_id, events)
    except sqlite3.Error as exc:
        _log.warning("live_item_tape_store: write failed for %s: %s", match_id, exc)
        return {"status": "error", "match_id": match_id, "rows": 0}
    except Exception as exc:  # noqa: BLE001 - lifecycle hook must not raise
        _log.warning("live_item_tape_store: unexpected %s persisting %s: %s",
                     type(exc).__name__, match_id, exc)
        return {"status": "error", "match_id": match_id, "rows": 0}
    finally:
        conn.close()


def _delay_or_default(delay_s: Any) -> float:
    """A real finite number up to ``_MAX_DELAY_S``, else ``DEFAULT_DELAY_S``.
    A NaN / inf / huge delay used to schedule a Timer whose wait raised
    OverflowError in its thread (the tape lost while the caller was told
    "scheduled"); a str delay raised TypeError out of ``on_game_end``."""
    if isinstance(delay_s, bool) or not isinstance(delay_s, (int, float)):
        return DEFAULT_DELAY_S
    if not math.isfinite(delay_s) or delay_s > _MAX_DELAY_S:
        return DEFAULT_DELAY_S
    return float(delay_s)


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
    returns ``{"status": "scheduled"}``. A junk ``delay_s`` (NaN, inf, a
    str, a bool, over an hour) keeps ``DEFAULT_DELAY_S``; a ``match_id``
    that is not a ``<PLATFORM>_<gameId>`` id is ``no_match_id``. The tape is
    drained either way (a game end always closes it). Never raises."""
    try:
        evs = list(events) if events is not None else lit.drain_tape()
    except Exception as exc:  # noqa: BLE001 - lifecycle hook must not raise
        _log.warning("live_item_tape_store: drain failed: %s", exc)
        return {"status": "error", "events": 0}
    if not _valid_match_id(match_id):
        return {"status": "no_match_id", "events": len(evs)}
    path = Path(db_path) if db_path is not None else _DEFAULT_DB
    delay = _delay_or_default(delay_s)
    if delay <= 0:
        return _persist_to_path(path, match_id, evs)
    timer = threading.Timer(delay, _persist_to_path, args=(path, match_id, evs))
    timer.daemon = True
    timer.name = "rc-item-tape-persist"
    timer.start()
    return {"status": "scheduled", "match_id": match_id, "events": len(evs)}
