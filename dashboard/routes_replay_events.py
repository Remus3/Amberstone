"""s220 PGR S5 - Match-V5 timeline events for the Replay page.

GET /api/replay/events?match_id=<id>[&include=items]

Reads discrete events from ``data/rewind_history.db.timeline_events``
and returns the chronological ribbon the Replay page renders under
the per-frame scrubber. Companion to ``routes_coach._serve_replay_match``
which already returns per-minute *snapshots* (state); this serves the
*events* (state transitions) at sub-second precision.

Returned event shape per row:

    {
      "clock_s":         int,      # timestamp_ms // 1000
      "type":            str,      # CHAMPION_KILL | BUILDING_KILL | ...
      "team":            int|None, # 100 / 200 / None for neutral events
      "actor":           int|None, # participant_id (killer for kills)
      "actor_name":      str|None, # summoner_name joined from participants
      "actor_champion":  str|None, # champion_name joined from participants
      "victim":          int|None, # participant_id (victim for kills)
      "victim_name":     str|None, # summoner_name joined from participants
      "victim_champion": str|None, # champion_name joined from participants
      "assists":         list[int],          # participant_ids
      "assists_names":   list[str|None],     # summoner_name per id (null parity)
      "assists_champs":  list[str|None],     # champion_name per id (null parity)
      "subtype":         str|None, # DRAGON / BARON / HERALD / NEXUS_TURRET / ...
      "lane":            str|None, # TOP / MID / BOT / NONE
      "pos":             [x,y]|null,
      "timestamp_ms":    int|None  # the event's own ms (floored); null
                                   # where the stored timestamp is NULL
    }

``timestamp_ms`` (S144-U-195) lets a Timeline seek put the minimap on
the event's own millisecond: the map opens a death window at a kill's
exact ms, so a seek to ``clock_s * 1000`` showed the victim still alive.

Defaults to the "strong" event types only (CHAMPION_KILL +
BUILDING_KILL + ELITE_MONSTER_KILL + TURRET_PLATE_DESTROYED). The
``include`` query param adds:

    items        : ITEM_PURCHASED + ITEM_SOLD + ITEM_DESTROYED + ITEM_UNDO
    skills       : SKILL_LEVEL_UP + LEVEL_UP
    wards        : WARD_PLACED + WARD_KILL
    all          : every event_type in the table

Filtering is server-side so a per-match request stays a few KB even
when the operator opts into items + wards. The default ribbon for a
35-minute SR match returns ~80-160 strong events; an items+skills
opt-in lands closer to ~800-1200 events.

A repeated ``include`` parameter is the union of its values, so
``include=items&include=wards`` and ``include=items,wards`` are one
request (and one cache entry).

Failures:

    400 - match_id missing, empty, given more than once, or not 1-64
          characters of A-Z, a-z, 0-9, _ or - (starting with a letter
          or digit; never stripped - a padded id is malformed)
    404 - match not in matches table
    503 - rewind_history.db not present on disk, or a SQLite read
          failed (corrupt file, missing table, locked): retryable
    500 - anything else; the traceback goes to the log, never the body

Rows are read fail-soft: a participant row whose id is not an integer
is ignored, a non-numeric or infinite kill position reads ``pos: null``,
and an event whose timestamp is present but not a finite number is
dropped (counted in one warning per request) - one bad row never takes
the whole ribbon down. A NULL timestamp keeps its historical clock 0.

Caching: 5 minute monotonic TTL keyed on (match_id, include_set,
schema). Reads and writes hold ``_CACHE_LOCK`` (ThreadingHTTPServer).
Same shape + size bound as ``routes_post_game_wpa``.

s144 true-audit cycle 109 hardened the lines above; the tests are
tests/test_routes_replay_events_audit_s144.py.

Architecture / cleanroom boundary: see `docs/adr/ADR-009-replay-events-cleanroom.md`.
Short version: `league_record` (GPLv3) is the methodology reference
for pairing this event sidecar with a future OBS video overlay; the
GPL license forbids vendoring its source. Do NOT pull league_record
in - the sidecar shape is also Match-V5 timeline's natural shape, no
implementation borrowed.
"""
from __future__ import annotations

import json
import logging
import math
import re
import sqlite3
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from dashboard._context import APP_DIR as _APP_DIR
from dashboard._dispatch import equals

log = logging.getLogger("rc.web_dashboard")

_REWIND_DB = _APP_DIR / "data" / "rewind_history.db"

# Same id contract as routes_post_game_wpa: Riot ids are
# "<PLATFORM>_<gameId>"; bare gameIds and test ids ("TEST-M1") pass.
_MATCH_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
_MATCH_ID_ERROR = ("match_id must be 1-64 characters of A-Z, a-z, 0-9, "
                   "_ or -, starting with a letter or digit")

# Cache: {(match_id, include_set_frozen, schema): (monotonic_ts, payload)}
# The schema sentinel bumps when the event-dict shape changes so old
# entries (e.g. cached pre-participant-join payloads) evict on first hit
# without waiting out the 5-min TTL.
# v3 (S144-U-195): each event gains timestamp_ms.
_CACHE_SCHEMA = "v3-timestamp-ms"
_CACHE: dict[tuple, tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_TTL_S = 300.0
_CACHE_MAX = 128
_CACHE_EVICT = 32

# Only the columns the ribbon reads. ``SELECT *`` also dragged every
# CHAMPION_KILL's victim_damage_json blob (and raw_json) out of SQLite.
_EVENT_COLUMNS = (
    "timestamp_ms, event_type, participant_id, killer_id, victim_id, "
    "assisting_ids_json, kill_pos_x, kill_pos_y, building_type, lane_type, "
    "tower_type, team_id, monster_type, monster_subtype, ward_type"
)

_STRONG_TYPES = (
    "CHAMPION_KILL",
    "BUILDING_KILL",
    "ELITE_MONSTER_KILL",
    "TURRET_PLATE_DESTROYED",
)
_ITEM_TYPES   = ("ITEM_PURCHASED", "ITEM_SOLD", "ITEM_DESTROYED", "ITEM_UNDO")
_SKILL_TYPES  = ("SKILL_LEVEL_UP", "LEVEL_UP")
_WARD_TYPES   = ("WARD_PLACED", "WARD_KILL")


def _parse_include(qs_value: str | None) -> frozenset[str]:
    """Parse a comma-separated ``include`` query value into a normalized
    frozenset. ``all`` is a sentinel that the caller resolves to "every
    event_type" via a wildcard SELECT (no IN filter)."""
    if not qs_value:
        return frozenset()
    parts = {p.strip().lower() for p in qs_value.split(",") if p.strip()}
    valid = {"items", "skills", "wards", "all"}
    return frozenset(p for p in parts if p in valid)


def _event_types_for(include: frozenset[str]) -> tuple[str, ...] | None:
    """Resolve the include-set to the concrete tuple of event_type
    strings to SELECT. Returns ``None`` for "all" (the caller skips
    the IN filter)."""
    if "all" in include:
        return None
    out: list[str] = list(_STRONG_TYPES)
    if "items"  in include: out.extend(_ITEM_TYPES)
    if "skills" in include: out.extend(_SKILL_TYPES)
    if "wards"  in include: out.extend(_WARD_TYPES)
    return tuple(out)


def _parse_query(path: str) -> tuple[str | None, frozenset[str], str | None]:
    """(match_id, include_set, None) or (None, frozenset(), 400 message)."""
    qs = parse_qs(urlparse(path).query, keep_blank_values=True)
    values = qs.get("match_id") or []
    if len(values) > 1:
        return None, frozenset(), "match_id given more than once"
    # Not stripped: a padded or newline-terminated id is malformed.
    match_id = values[0] if values else ""
    if not match_id:
        return None, frozenset(), "match_id required"
    if not _MATCH_ID_RE.fullmatch(match_id):
        return None, frozenset(), _MATCH_ID_ERROR
    include = _parse_include(",".join(qs.get("include") or []))
    return match_id, include, None


def _as_int(value: object) -> int | None:
    """An integer read from a row column, or None when the column does not
    hold one: an int, an integral finite float, or an ASCII digit string.
    bool, a fractional / infinite / NaN float and anything else is None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if math.isfinite(value) and value.is_integer():
            return int(value)
        return None
    if isinstance(value, str) and value.isascii() and value.isdigit():
        return int(value)
    return None


def _pid(value: object) -> int | None:
    """A participant id (positive integer); 0 / negative / junk is None."""
    n = _as_int(value)
    return n if n is not None and n > 0 else None


def _cache_get(key: tuple) -> dict | None:
    now = time.monotonic()
    with _CACHE_LOCK:
        entry = _CACHE.get(key)
        if entry is None:
            return None
        ts, payload = entry
        if (now - ts) > _CACHE_TTL_S:
            _CACHE.pop(key, None)
            return None
        return payload


def _cache_put(key: tuple, payload: dict) -> None:
    now = time.monotonic()
    with _CACHE_LOCK:
        _CACHE[key] = (now, payload)
        if len(_CACHE) > _CACHE_MAX:
            victims = sorted(_CACHE.items(), key=lambda kv: kv[1][0])
            for k, _ in victims[:_CACHE_EVICT]:
                _CACHE.pop(k, None)


def _open_rewind_db_ro() -> sqlite3.Connection:
    """Read-only connection. ``Path.as_uri`` percent-encodes the path, so
    a '#', '%' or '?' in the checkout path no longer truncates the URI
    (an f-string ``file:{path}?mode=ro`` opened the wrong file)."""
    uri = Path(_REWIND_DB).absolute().as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=2.0)


def _match_exists(conn: sqlite3.Connection, match_id: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM matches WHERE match_id=? LIMIT 1", (match_id,)
    )
    return cur.fetchone() is not None


def _team_by_participant(conn: sqlite3.Connection, match_id: str) -> dict[int, int]:
    """Return {participant_id: team_id}. Cheap join used to surface
    team-tinted rows in the events ribbon. A row whose id or team is not
    an integer is ignored, never a 500."""
    out: dict[int, int] = {}
    cur = conn.execute(
        "SELECT participant_id, team_id FROM participants WHERE match_id=?",
        (match_id,),
    )
    for raw_pid, raw_tid in cur.fetchall():
        pid, tid = _pid(raw_pid), _as_int(raw_tid)
        if pid is not None and tid is not None:
            out[pid] = tid
    return out


def _participant_meta(conn: sqlite3.Connection, match_id: str) -> dict[int, tuple[str | None, str | None]]:
    """Return {participant_id: (summoner_name, champion_name)}.
    Carry-forward from s220 S5: the ribbon previously surfaced P1..P10
    chips; the join lets the ribbon paint real names + champion icons.
    Payload bloat ~10 bytes/event x ~200 events = ~2 KB acceptable per
    operator's authorization scope."""
    out: dict[int, tuple[str | None, str | None]] = {}
    cur = conn.execute(
        "SELECT participant_id, summoner_name, champion_name "
        "FROM participants WHERE match_id=?",
        (match_id,),
    )
    for raw_pid, sn, cn in cur.fetchall():
        pid = _pid(raw_pid)
        if pid is None:
            continue
        out[pid] = (
            (sn if isinstance(sn, str) and sn else None),
            (cn if isinstance(cn, str) and cn else None),
        )
    return out


def _row_actor(row: sqlite3.Row) -> int | None:
    """The acting participant: the killer when there is one, else the
    event's participant (purchases, wards, level-ups). 0 = no participant
    (a minion / turret kill) and junk both read as None."""
    killer = _pid(row["killer_id"])
    return killer if killer is not None else _pid(row["participant_id"])


def _row_team(row: sqlite3.Row, team_by_pid: dict[int, int],
              actor: int | None) -> int | None:
    """Best-effort team resolution. BUILDING_KILL carries team_id
    directly (it is the team that LOST the building - we flip to the
    team that DESTROYED it so the ribbon paints by destroyer-side).
    Other events derive from the actor -> team."""
    if row["event_type"] == "BUILDING_KILL":
        # team_id field = team that owned the building. Flip.
        owner = _as_int(row["team_id"])
        return (100 if owner == 200 else 200) if owner in (100, 200) else None
    return team_by_pid.get(actor) if actor is not None else None


def _row_subtype(row: sqlite3.Row) -> str | None:
    et = row["event_type"]
    if et == "BUILDING_KILL":
        # tower_type wins (OUTER_TURRET / INNER_TURRET / BASE_TURRET /
        # NEXUS_TURRET) when present; else fall back to building_type.
        return (row["tower_type"] or row["building_type"] or None)
    if et == "ELITE_MONSTER_KILL":
        return (row["monster_subtype"] or row["monster_type"] or None)
    if et in ("WARD_PLACED", "WARD_KILL"):
        return row["ward_type"]
    return None


def _assists(row: sqlite3.Row) -> list[int]:
    """Assisting participant ids from the row's JSON list. Anything but a
    list is no assists (a JSON STRING '"12"' used to iterate into [1, 2]);
    inside the list only positive integers or ASCII digit strings count
    (JSON true is not participant 1, a float is not an id)."""
    raw = row["assisting_ids_json"]
    if not raw:
        return []
    try:
        v = json.loads(raw)
    except (TypeError, ValueError, RecursionError):
        return []
    if not isinstance(v, list):
        return []
    out: list[int] = []
    for x in v:
        if isinstance(x, float):
            continue
        pid = _pid(x)
        if pid is not None:
            out.append(pid)
    return out


def _pos(row: sqlite3.Row) -> list[int] | None:
    """[x, y] map position, or None when either axis is absent or not a
    finite number (a junk value used to 500 the whole ribbon)."""
    x, y = row["kill_pos_x"], row["kill_pos_y"]
    out = []
    for v in (x, y):
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return None
        if isinstance(v, float) and not math.isfinite(v):
            return None
        out.append(int(v))
    return out


def _clock_s(row: sqlite3.Row) -> tuple[int | None, bool]:
    """(clock seconds, usable). NULL keeps its historical clock 0; a value
    that is present but not a finite number is unusable (the row is
    dropped - SQLite also sorts such a value out of chronological order)."""
    ts = row["timestamp_ms"]
    if ts is None:
        return 0, True
    if isinstance(ts, bool) or not isinstance(ts, (int, float)):
        return None, False
    if isinstance(ts, float) and not math.isfinite(ts):
        return None, False
    return int(ts // 1000), True


def _timestamp_ms(row: sqlite3.Row) -> int | None:
    """S144-U-195: the event's own ms for a row ``_clock_s`` found usable,
    floored like its clock; None where the stored timestamp is NULL."""
    ts = row["timestamp_ms"]
    if ts is None:
        return None
    return math.floor(ts)


def _you_flagged(match_id: str) -> list[dict]:
    """RM-638: the player's in-game "mark this moment" pins for this match
    (core/moment_marks.py). ADDITIVE field, read per request (never cached)
    so a late attach shows up; any failure is an empty list."""
    try:
        from core.moment_marks import pins_for_match
        return pins_for_match(match_id)
    except Exception as exc:  # noqa: BLE001
        log.debug("api/replay/events: you_flagged unavailable: %s", exc)
        return []


def _send_json(h, status: int, obj: dict) -> None:
    h._send(status, json.dumps(obj).encode("utf-8"), "application/json")


def _read_events(conn: sqlite3.Connection, match_id: str,
                 include: frozenset[str]) -> list[dict] | None:
    """The event ribbon for ``match_id``, or None when the match is not in
    the matches table. Raises sqlite3.Error on a read failure."""
    conn.row_factory = sqlite3.Row
    if not _match_exists(conn, match_id):
        return None
    team_by_pid = _team_by_participant(conn, match_id)
    meta_by_pid = _participant_meta(conn, match_id)
    types = _event_types_for(include)
    if types is None:
        cur = conn.execute(
            f"SELECT {_EVENT_COLUMNS} FROM timeline_events "
            "WHERE match_id=? ORDER BY timestamp_ms ASC",
            (match_id,),
        )
    else:
        placeholders = ",".join("?" * len(types))
        cur = conn.execute(
            f"SELECT {_EVENT_COLUMNS} FROM timeline_events "
            f"WHERE match_id=? AND event_type IN ({placeholders}) "
            "ORDER BY timestamp_ms ASC",
            (match_id, *types),
        )
    events: list[dict] = []
    skipped = 0
    for row in cur.fetchall():
        clock_s, usable = _clock_s(row)
        if not usable:
            skipped += 1
            continue
        actor = _row_actor(row)
        victim = _pid(row["victim_id"])
        assists = _assists(row)
        actor_name, actor_champion = meta_by_pid.get(actor, (None, None))
        victim_name, victim_champion = meta_by_pid.get(victim, (None, None))
        assists_names: list[str | None] = []
        assists_champs: list[str | None] = []
        for aid in assists:
            sn, cn = meta_by_pid.get(aid, (None, None))
            assists_names.append(sn)
            assists_champs.append(cn)
        events.append({
            "clock_s":         clock_s,
            "type":            row["event_type"],
            "team":            _row_team(row, team_by_pid, actor),
            "actor":           actor,
            "actor_name":      actor_name,
            "actor_champion":  actor_champion,
            "victim":          victim,
            "victim_name":     victim_name,
            "victim_champion": victim_champion,
            "assists":         assists,
            "assists_names":   assists_names,
            "assists_champs":  assists_champs,
            "subtype":         _row_subtype(row),
            "lane":            row["lane_type"] or None,
            "pos":             _pos(row),
            "timestamp_ms":    _timestamp_ms(row),
        })
    if skipped:
        log.warning("api/replay/events: %s: skipped %d event row(s) with an "
                    "unusable timestamp", match_id, skipped)
    return events


def _serve_replay_events(h) -> None:
    """GET /api/replay/events?match_id=<id>[&include=items,skills,...]."""
    try:
        match_id, include, err = _parse_query(h.path)
        if err is not None:
            _send_json(h, 400, {"ok": False, "error": err})
            return

        if not _REWIND_DB.exists():
            _send_json(h, 503, {"ok": False,
                                "error": "rewind_history.db missing"})
            return

        t0 = time.perf_counter()
        cache_key = (match_id, include, _CACHE_SCHEMA)
        cached = _cache_get(cache_key)
        if cached is not None:
            payload = dict(cached)
            payload["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)
            payload["cached"] = True
            payload["you_flagged"] = _you_flagged(match_id)
            _send_json(h, 200, payload)
            return

        try:
            conn = _open_rewind_db_ro()
            try:
                events = _read_events(conn, match_id, include)
            finally:
                conn.close()
        except sqlite3.Error as exc:
            # Corrupt file, missing table, locked DB, or the file vanished
            # after the exists() check: retryable, not an internal error.
            log.warning("api/replay/events: rewind_history.db read failed "
                        "for %s: %s: %s", match_id, type(exc).__name__, exc)
            _send_json(h, 503, {
                "ok": False,
                "error": "rewind history unavailable - retry shortly",
            })
            return

        if events is None:
            _send_json(h, 404, {"ok": False, "error": "match_id not found",
                                "match_id": match_id})
            return

        payload = {
            "ok":         True,
            "match_id":   match_id,
            "events":     events,
            "count":      len(events),
            "include":    sorted(include),
            "elapsed_ms": int((time.perf_counter() - t0) * 1000),
            "cached":     False,
        }
        _cache_put(cache_key, dict(payload))
        payload["you_flagged"] = _you_flagged(match_id)
        _send_json(h, 200, payload)
    except Exception:  # generic 500 wrapper
        log.exception("api/replay/events: unexpected failure")
        try:
            # Raw exception text can leak file paths - log it, never
            # render it (same policy as dashboard/_handler.do_POST).
            _send_json(h, 500, {"ok": False,
                                "error": "internal error - see logs"})
        except OSError as send_exc:
            log.warning("api/replay/events: could not send the 500: %s: %s",
                        type(send_exc).__name__, send_exc)


GET_ROUTES = [
    (equals("/api/replay/events"), _serve_replay_events),
]

POST_ROUTES: list = []
