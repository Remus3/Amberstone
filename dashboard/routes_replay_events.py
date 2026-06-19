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
      "pos":             [x,y]|null
    }

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

Failures:

    400 - match_id missing/empty
    404 - match not in matches table
    503 - rewind_history.db not present on disk

Caching: 5 minute TTL keyed on (match_id, include_set). Same shape
+ size bound as ``routes_post_game_wpa``.

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
import sqlite3
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from dashboard._context import APP_DIR as _APP_DIR
from dashboard._dispatch import equals

log = logging.getLogger("rc.web_dashboard")

_REWIND_DB = _APP_DIR / "data" / "rewind_history.db"

# Cache: {(match_id, include_set_frozen, schema): (timestamp, payload)}
# The schema sentinel bumps when the event-dict shape changes so old
# entries (e.g. cached pre-participant-join payloads) evict on first hit
# without waiting out the 5-min TTL.
_CACHE_SCHEMA = "v2-participant-join"
_CACHE: dict[tuple, tuple[float, dict]] = {}
_CACHE_TTL_S = 300.0
_CACHE_MAX = 128

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


def _cache_get(key: tuple) -> dict | None:
    entry = _CACHE.get(key)
    if not entry:
        return None
    ts, payload = entry
    if (time.time() - ts) > _CACHE_TTL_S:
        _CACHE.pop(key, None)
        return None
    return payload


def _cache_put(key: tuple, payload: dict) -> None:
    _CACHE[key] = (time.time(), payload)
    if len(_CACHE) > _CACHE_MAX:
        victims = sorted(_CACHE.items(), key=lambda kv: kv[1][0])[:32]
        for k, _ in victims:
            _CACHE.pop(k, None)


def _match_exists(conn: sqlite3.Connection, match_id: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM matches WHERE match_id=? LIMIT 1", (match_id,)
    )
    return cur.fetchone() is not None


def _team_by_participant(conn: sqlite3.Connection, match_id: str) -> dict[int, int]:
    """Return {participant_id: team_id}. Cheap join used to surface
    team-tinted rows in the events ribbon."""
    out: dict[int, int] = {}
    cur = conn.execute(
        "SELECT participant_id, team_id FROM participants WHERE match_id=?",
        (match_id,),
    )
    for pid, tid in cur.fetchall():
        if pid is not None and tid is not None:
            out[int(pid)] = int(tid)
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
    for pid, sn, cn in cur.fetchall():
        if pid is None:
            continue
        out[int(pid)] = (
            (sn if isinstance(sn, str) and sn else None),
            (cn if isinstance(cn, str) and cn else None),
        )
    return out


def _row_team(row: sqlite3.Row, team_by_pid: dict[int, int]) -> int | None:
    """Best-effort team resolution. BUILDING_KILL carries team_id
    directly (it is the team that LOST the building - we flip to the
    team that DESTROYED it so the ribbon paints by destroyer-side).
    Other events derive from killer/participant -> team."""
    et = row["event_type"]
    if et == "BUILDING_KILL":
        # team_id field = team that owned the building. Flip.
        owner = row["team_id"]
        return (100 if owner == 200 else 200) if owner in (100, 200) else None
    actor = row["killer_id"] if row["killer_id"] not in (None, 0) else row["participant_id"]
    if actor and actor in team_by_pid:
        return team_by_pid[actor]
    return None


def _row_subtype(row: sqlite3.Row) -> str | None:
    et = row["event_type"]
    if et == "BUILDING_KILL":
        # tower_type wins (OUTER_TURRET / INNER_TURRET / BASE_TURRET /
        # NEXUS_TURRET) when present; else fall back to building_type.
        return (row["tower_type"] or row["building_type"] or None)
    if et == "ELITE_MONSTER_KILL":
        return (row["monster_subtype"] or row["monster_type"] or None)
    if et == "WARD_PLACED" or et == "WARD_KILL":
        return row["ward_type"]
    return None


def _assists(row: sqlite3.Row) -> list[int]:
    raw = row["assisting_ids_json"]
    if not raw:
        return []
    try:
        v = json.loads(raw)
        return [int(x) for x in v if isinstance(x, int) or (isinstance(x, str) and x.isdigit())]
    except (TypeError, ValueError, json.JSONDecodeError):
        return []


def _pos(row: sqlite3.Row) -> list[int] | None:
    x, y = row["kill_pos_x"], row["kill_pos_y"]
    if x is None or y is None:
        return None
    return [int(x), int(y)]


def _serve_replay_events(h) -> None:
    """GET /api/replay/events?match_id=<id>[&include=items,skills,...]"""
    try:
        qs = parse_qs(urlparse(h.path).query)
        match_id = (qs.get("match_id") or [""])[0].strip()
        include = _parse_include((qs.get("include") or [""])[0])
        if not match_id:
            h._send(400, json.dumps({
                "ok": False, "error": "match_id required",
            }).encode(), "application/json")
            return

        if not _REWIND_DB.exists():
            h._send(503, json.dumps({
                "ok": False, "error": "rewind_history.db missing",
            }).encode(), "application/json")
            return

        t0 = time.time()
        cache_key = (match_id, include, _CACHE_SCHEMA)
        cached = _cache_get(cache_key)
        if cached is not None:
            payload = dict(cached)
            payload["elapsed_ms"] = int((time.time() - t0) * 1000)
            payload["cached"] = True
            h._send(200, json.dumps(payload).encode("utf-8"),
                    "application/json")
            return

        conn = sqlite3.connect(
            f"file:{_REWIND_DB}?mode=ro", uri=True, timeout=2.0
        )
        try:
            conn.row_factory = sqlite3.Row
            if not _match_exists(conn, match_id):
                h._send(404, json.dumps({
                    "ok": False, "error": "match_id not found",
                    "match_id": match_id,
                }).encode(), "application/json")
                return

            team_by_pid = _team_by_participant(conn, match_id)
            meta_by_pid = _participant_meta(conn, match_id)
            types = _event_types_for(include)
            if types is None:
                cur = conn.execute(
                    "SELECT * FROM timeline_events "
                    "WHERE match_id=? ORDER BY timestamp_ms ASC",
                    (match_id,),
                )
            else:
                placeholders = ",".join("?" * len(types))
                cur = conn.execute(
                    f"SELECT * FROM timeline_events "
                    f"WHERE match_id=? AND event_type IN ({placeholders}) "
                    f"ORDER BY timestamp_ms ASC",
                    (match_id, *types),
                )
            events: list[dict] = []
            for row in cur.fetchall():
                actor = (row["killer_id"]
                         if row["killer_id"] not in (None, 0)
                         else (row["participant_id"]
                               if row["participant_id"] not in (None, 0) else None))
                victim = row["victim_id"] if row["victim_id"] not in (None, 0) else None
                assists = _assists(row)
                actor_name, actor_champion = (meta_by_pid.get(actor, (None, None))
                                              if actor is not None else (None, None))
                victim_name, victim_champion = (meta_by_pid.get(victim, (None, None))
                                                if victim is not None else (None, None))
                assists_names: list[str] = []
                assists_champs: list[str] = []
                for aid in assists:
                    sn, cn = meta_by_pid.get(aid, (None, None))
                    assists_names.append(sn)
                    assists_champs.append(cn)
                events.append({
                    "clock_s":         int((row["timestamp_ms"] or 0) // 1000),
                    "type":            row["event_type"],
                    "team":            _row_team(row, team_by_pid),
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
                })
        finally:
            conn.close()

        payload = {
            "ok":         True,
            "match_id":   match_id,
            "events":     events,
            "count":      len(events),
            "include":    sorted(include),
            "elapsed_ms": int((time.time() - t0) * 1000),
            "cached":     False,
        }
        _cache_put(cache_key, dict(payload))
        h._send(200, json.dumps(payload).encode("utf-8"), "application/json")
    except Exception as exc:  # noqa: BLE001 - generic 500 wrapper
        log.warning("api/replay/events: %s", exc)
        try:
            # Raw exception text can leak file paths - log it, never
            # render it (same policy as dashboard/_handler.do_POST).
            h._send(500, json.dumps({
                "ok": False, "error": "internal error - see logs",
            }).encode(), "application/json")
        except Exception:  # noqa: BLE001
            pass


GET_ROUTES = [
    (equals("/api/replay/events"), _serve_replay_events),
]

POST_ROUTES: list = []
