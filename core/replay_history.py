"""
core/replay_history.py - read-only access to data/rewind_history.db for
the replay-scrubber dashboard view.

AUDIT 2026-04-28 (suggestion 2.3): rewind_history.db has 2846 matches
with full timeline_frames (per-minute level/gold/CS/position) and
timeline_events (kills, item buys, objective takes). This module
exposes:

    list_matches(limit, queue_filter)
        recent matches with per-row {match_id, queue_id, game_mode,
        duration_s, game_creation_ts, patch,
        tracked: {champion_id, champion_name, win}}.

    match_detail(match_id)
        full match data formatted for a scrubber UI: tracked seat,
        participants, per-minute snapshots (level/gold/CS/position/damage/
        items), kill events.

Items at minute T are computed by folding ITEM_PURCHASED / ITEM_SOLD /
ITEM_DESTROYED / ITEM_UNDO events with timestamp <= T*60000. The fold shows
what the events can prove, not the whole inventory: granted items (Poro-Snax,
often the starting trinket, rune and Arena grants) and most support quest final
choices have no event naming them.

AUDIT 2026-08-31 (lane 8 cycle 32): ITEM_UNDO is read from `raw_json`,
NOT from the `item_id` column. Riot does not send `itemId` on an
ITEM_UNDO event - it sends `beforeId` (the item the player had before
the undo) and `afterId` (the item they have after it), and
`parse_event` in scripts/rewind_scraper.py maps only `itemId`. So `item_id` is
NULL for every ITEM_UNDO row: MEASURED 28405 of 28405 in the live
database. The previous fold guarded on that column, so its undo branch
was structurally dead and had never once fired, while this docstring
claimed "UNDO reverses the most-recent matching purchase". Both
directions were wrong: 25917 of those rows undo a PURCHASE (the item
was wrongly LEFT IN) and 2488 undo a SELL (the item was wrongly LEFT
OUT). The scraper stores the verbatim event in `raw_json` and that
column is NULL for 0 of the 28405 rows, so reading the fold from there
repairs every historical row with no migration of the 1.87 GB file.
Pinned by tests/test_replay_history.py.

DDragon item id -> name resolution is deferred to the dashboard JS which
already has web/data/items_index.json loaded.
"""
from __future__ import annotations

import collections as _collections
import json
import logging
import sqlite3
import threading
from collections import defaultdict
from pathlib import Path
from typing import Optional

from core.failed_load_gate import FailedLoadGate

_log = logging.getLogger("rc.replay_history")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_REWIND_DB    = _PROJECT_ROOT / "data" / "rewind_history.db"
_DDR_CHAMPS   = _PROJECT_ROOT / "data" / "meta" / "ddragon_champions.json"

_id_to_champ: dict[int, str] = {}
_idx_lock = threading.Lock()

# AUDIT 2026-04-29 (item 8): LRU cache for match_detail(). Matches are
# immutable once recorded - no invalidation needed. 8 entries x ~75 KB
# JSON ~ 600 KB RAM. Returning to a previously-viewed match is now ~0
# ms instead of 7 ms warm / 100 ms cold-after-idle. A cached result is shared
# between callers, so treat it as read-only (the route only serializes it).
_MATCH_DETAIL_CACHE: "_collections.OrderedDict[str, dict]" = _collections.OrderedDict()
_MATCH_DETAIL_CACHE_MAX = 8
_match_cache_lock = threading.Lock()
# RM-443: per-source-path failure gates for the champion index.
_CHAMP_INDEX_GATES: dict = {}

# dashboard/routes_coach.py _limit_param caps the route at the same value.
_LIST_LIMIT_MAX = 200
_SQLITE_INT_MIN = -(2 ** 63)
_SQLITE_INT_MAX = 2 ** 63 - 1

# Items that turn into another with NO ITEM_PURCHASED: the source's
# ITEM_DESTROYED is the only event. Each row is a DDragon `specialRecipe` pair
# (pinned by tests/test_replay_history_audit_s144.py) whose source was destroyed
# in the stored matches: the stacking items and their Arena copies, and the
# support quest's automatic steps, current and retired. The current quest's last
# step is the player's choice of five, and most seats log no event naming it.
# Two DDragon entries are not copied as written. 223121 names 3119 as its source,
# but the Arena copy really comes from 223119, so that is the row here. 220007 ->
# 446693 is left out: its source is the Arena Prismatic Item box, destroyed 1361
# times with its target never once bought or destroyed.
_ITEM_TRANSFORMS = {
    2526: 2530,
    3003: 3040,
    3004: 3042,
    3119: 3121,
    3850: 3851,
    3851: 3853,
    3854: 3855,
    3855: 3857,
    3858: 3859,
    3859: 3860,
    3862: 3863,
    3863: 3864,
    3865: 3866,
    3866: 3867,
    222526: 222530,
    223003: 223040,
    223004: 223042,
    223119: 223121,
}

# Purchases sort first inside one millisecond. Riot logs a consumable that is
# used on purchase (an elixir, an Arena stat bonus) with its ITEM_DESTROYED
# BEFORE its ITEM_PURCHASED at the same timestamp: 2954 of 2975 such same-ms
# pairs in a 400-match sample. Folded in logged order, the removal missed and
# the item then stayed for the rest of the game.
_ITEM_EVENTS_SQL = """
    SELECT timestamp_ms, event_type, participant_id, item_id, raw_json
    FROM timeline_events
    WHERE match_id = ?
      AND typeof(timestamp_ms) = 'integer'
      AND event_type IN ('ITEM_PURCHASED','ITEM_SOLD',
                          'ITEM_DESTROYED','ITEM_UNDO')
    ORDER BY timestamp_ms,
             CASE event_type WHEN 'ITEM_PURCHASED' THEN 0 ELSE 1 END,
             id
"""


def _load_champ_index() -> bool:
    """Publish the champion id -> name index. True when it is loaded.

    RM-443: False means the DDragon read failed (or is inside the backoff that
    follows a failure, one gate per source path); match_detail must not cache
    a result built without the index, or the missing names stick in its LRU.
    """
    # AUDIT 2026-06-11 (deep-audit P2-W1-A): build the index in a local
    # dict and publish it complete. The previous loop populated the
    # module dict key-by-key, so a concurrent caller could observe a
    # truthy-but-partial index and resolve champion names to "?" - and
    # match_detail() would then cache that bad name in its LRU.
    if _id_to_champ:
        return True
    gate = _CHAMP_INDEX_GATES.setdefault(str(_DDR_CHAMPS), FailedLoadGate())
    if not gate.should_attempt():
        return False
    try:
        data = json.loads(_DDR_CHAMPS.read_text(encoding="utf-8"))
        # RM-450: the shape checks sit INSIDE the try. A non-object document
        # used to raise AttributeError out of every caller (data.get), and an
        # index that built empty returned True, so match_detail cached
        # name-less results. Both are failures now: not cached, retried after
        # the backoff.
        if not isinstance(data, dict):
            raise ValueError(f"top level is {type(data).__name__}, want object")
        rows = data.get("data")
        if not isinstance(rows, dict):
            raise ValueError("'data' is not an object")
        built: dict[int, str] = {}
        for slug, entry in rows.items():
            if not isinstance(entry, dict):
                continue
            key = entry.get("key")
            if not isinstance(key, (str, int)) or isinstance(key, bool):
                continue
            try:
                cid = int(key)
            except ValueError:
                continue
            name = entry.get("name")
            built[cid] = name if isinstance(name, str) and name else slug
        if not built:
            raise ValueError("no usable champion rows")
    # RM-291A: UnicodeDecodeError is a ValueError, not an OSError.
    except (OSError, ValueError) as exc:
        if gate.record_failure():
            _log.warning("replay_history: champion index load failed: %s", exc)
        return False
    gate.record_success()
    with _idx_lock:
        if _id_to_champ:
            return True
        _id_to_champ.update(built)
    return True


def _open() -> Optional[sqlite3.Connection]:
    """A query-only connection, or None when the database cannot be opened.

    `mode=rw` never creates the file: a plain connect after the exists() check
    could leave a new empty database behind if the file had just gone. It is
    not `mode=ro`: the writers set WAL, where that would work, but a file in
    rollback-journal mode (a restored copy, say) can hold a hot journal that a
    read-only connection cannot roll back, and every read would then fail until
    something else repaired it. `query_only` is what refuses writes."""
    if not _REWIND_DB.exists():
        return None
    c = None
    try:
        c = sqlite3.connect(_REWIND_DB.as_uri() + "?mode=rw", uri=True)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA query_only = ON")
        return c
    except sqlite3.Error as exc:
        _log.warning("rewind_history open: %s", exc)
        if c is not None:
            c.close()
        return None


def _tracked_seat(
    c: sqlite3.Connection, m: sqlite3.Row,
) -> tuple[Optional[int], Optional[bool]]:
    """(team_id, win) of the tracked player, each None when unknown.

    The seat comes from the stored team, because a champion id alone does not
    name one: the same champion can sit on both teams (measured on 11 matches,
    Arena and other non-draft modes). The verdict comes from Riot's per-player
    `participants.win`, which agreed with `teams.win` on all 29203 rows that
    have both and also covers Arena team 200, which has no `teams` row.
    `matches.tracked_win` is the last resort: on the rows the scraper wrote it
    comes from the history site, and it disagrees with Riot on some of those,
    mostly short games."""
    tracked_team = m["tracked_team_id"] or None
    stored = None if m["tracked_win"] is None else bool(m["tracked_win"])
    rows = c.execute(
        """
        SELECT p.team_id, COALESCE(p.win, t.win) AS win
        FROM participants p
        LEFT JOIN teams t
          ON t.match_id = p.match_id AND t.team_id = p.team_id
        WHERE p.match_id = ? AND p.champion_id = ?
        """,
        (m["match_id"], m["tracked_champion_id"]),
    ).fetchall()
    if tracked_team is not None:
        rows = [r for r in rows if r["team_id"] == tracked_team]
    teams = {r["team_id"] for r in rows}
    if len(teams) != 1:
        return tracked_team, stored
    wins = {bool(r["win"]) for r in rows if r["win"] is not None}
    return teams.pop(), (wins.pop() if len(wins) == 1 else stored)


def _tracked_name(m: sqlite3.Row) -> Optional[str]:
    """The index name, else the name stored with the match. A champion newer
    than the local DDragon file, or a failed index load, has only the latter."""
    return (_id_to_champ.get(m["tracked_champion_id"])
            or m["tracked_champion_name"] or None)


def _position(x, y) -> Optional[list]:
    """[x, y], or None unless BOTH exist. (0, 0) is a real position."""
    return [x, y] if x is not None and y is not None else None


def _seat_ids(raw) -> list[int]:
    """The assisting seats from `assisting_ids_json`, dropping anything that is
    not a seat. Bad data degrades to fewer assists, not a broken view."""
    try:
        ids = json.loads(raw or "[]")
    except (TypeError, ValueError, RecursionError):
        return []
    if not isinstance(ids, list):
        return []
    return [i for i in ids if type(i) is int and i > 0]


def list_matches(limit: int = 25, queue_filter: Optional[int] = None) -> list[dict]:
    """Recent matches sorted by game_creation_ts desc. Returns the metadata
    needed for the dashboard match picker - no per-frame data.

    AUDIT 2026-08-31 (lane 8 cycle 32): `limit` is clamped here and not
    only at the route. SQLite reads LIMIT -1 as UNLIMITED, and this
    function runs one extra join PER ROW, so a negative limit was a
    full-table read amplified into an N+1. `dashboard/routes_coach.py`
    clamps to 1..200, so that was latent - but the clamp belongs to the
    function that owns the query. s144: both bounds, because a huge limit is the
    same read and past 64 bits sqlite3 raises OverflowError. A wrong TYPE is a
    caller bug and raises TypeError; a queue outside 64 bits cannot match."""
    if type(limit) is not int:
        raise TypeError(f"limit must be int, not {type(limit).__name__}")
    if queue_filter is not None:
        if type(queue_filter) is not int:
            raise TypeError(
                f"queue_filter must be int, not {type(queue_filter).__name__}")
        if not _SQLITE_INT_MIN <= queue_filter <= _SQLITE_INT_MAX:
            return []
    limit = min(max(limit, 0), _LIST_LIMIT_MAX)
    _load_champ_index()
    c = _open()
    if c is None:
        return []
    try:
        # `is not None`, not truthiness: queue_id 0 is a real queue
        # (custom game) and was silently falling through to "no filter".
        if queue_filter is not None:
            rows = c.execute(
                """
                SELECT match_id, queue_id, game_mode, game_duration_s,
                       game_creation_ts, patch, tracked_champion_id,
                       tracked_champion_name, tracked_team_id, tracked_win
                FROM matches
                WHERE queue_id = ?
                ORDER BY game_creation_ts DESC
                LIMIT ?
                """,
                (queue_filter, limit),
            ).fetchall()
        else:
            rows = c.execute(
                """
                SELECT match_id, queue_id, game_mode, game_duration_s,
                       game_creation_ts, patch, tracked_champion_id,
                       tracked_champion_name, tracked_team_id, tracked_win
                FROM matches
                ORDER BY game_creation_ts DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        out = []
        for r in rows:
            out.append({
                "match_id":         r["match_id"],
                "queue_id":         r["queue_id"],
                "game_mode":        r["game_mode"],
                "duration_s":       r["game_duration_s"],
                "game_creation_ts": r["game_creation_ts"],
                "patch":            r["patch"],
                "tracked": {
                    "champion_id":   r["tracked_champion_id"],
                    "champion_name": _tracked_name(r),
                    "win":           _tracked_seat(c, r)[1],
                },
            })
        return out
    finally:
        try:
            c.close()
        except sqlite3.Error:
            pass


def _undo_pair(event: sqlite3.Row) -> tuple[int, int]:
    """(beforeId, afterId) for an ITEM_UNDO row, read from `raw_json`.

    Returns (0, 0) for a row whose `raw_json` is empty or malformed: the
    scraper writes that column, so a bad row degrades to "no undo
    applied" rather than taking down the whole match view.

    A row with no `raw_json` COLUMN AT ALL is a different thing and is
    deliberately left to raise. That is a caller that forgot to select
    it, not bad data, and swallowing it would silently restore exactly
    the dead-branch bug this function exists to fix - a mutation that
    dropped the column from the SELECT survived the suite until this
    distinction was drawn."""
    raw = event["raw_json"]
    if not raw:
        return 0, 0
    try:
        d = json.loads(raw)
    except (TypeError, ValueError, RecursionError):
        return 0, 0
    if not isinstance(d, dict):
        return 0, 0
    def _slot(key: str) -> int:
        value = d.get(key)
        return value if type(value) is int and value > 0 else 0
    return _slot("beforeId"), _slot("afterId")


def _build_inventory_at(events: list[sqlite3.Row], up_to_ms: int) -> dict[int, list[int]]:
    """Per-participant item list at timestamp `up_to_ms`. Folds
    ITEM_PURCHASED / ITEM_SOLD / ITEM_DESTROYED / ITEM_UNDO in order.
    Returns {participant_id: [item_id, ...]}.

    `events` must carry `raw_json` as well as `item_id` - see the module
    docstring for why ITEM_UNDO cannot be folded from `item_id` - and come in
    `_ITEM_EVENTS_SQL` order. A held item with an `_ITEM_TRANSFORMS` entry becomes
    its target when destroyed. A source the fold does not hold yields nothing:
    live seats log repeated ITEM_DESTROYED rows for one source, and following
    them would invent copies Riot's end-game slots do not have."""
    inv: dict[int, list[int]] = defaultdict(list)
    for e in events:
        if e["timestamp_ms"] > up_to_ms:
            break
        et = e["event_type"]
        pid = e["participant_id"]
        item = e["item_id"]
        if not pid:
            continue
        if et == "ITEM_PURCHASED" and item:
            inv[pid].append(item)
        elif et in ("ITEM_SOLD", "ITEM_DESTROYED") and item:
            try:
                inv[pid].remove(item)
            except ValueError:
                continue
            if et == "ITEM_DESTROYED" and item in _ITEM_TRANSFORMS:
                inv[pid].append(_ITEM_TRANSFORMS[item])
        elif et == "ITEM_UNDO":
            before, after = _undo_pair(e)
            if before:
                try:
                    inv[pid].remove(before)
                except ValueError:
                    pass
            if after:
                inv[pid].append(after)
    return dict(inv)


def match_detail(match_id: str, *, max_frames: int = 60) -> Optional[dict]:
    """Full match data for the replay scrubber. Returns None if missing.

    `max_frames` caps per-minute snapshots so a 90-minute Aram doesn't
    explode the response. Frames are sampled evenly across the match
    duration when the cap is hit.

    A row with a non-integer timestamp is skipped, so one bad row costs that
    row and not the whole view. A `cs` of None means no counter was recorded,
    which the grid renders as "-", not as a real 0."""
    if not isinstance(match_id, str) or not match_id:
        return None
    cache_key = f"{match_id}|{max_frames}"
    with _match_cache_lock:
        cached = _MATCH_DETAIL_CACHE.get(cache_key)
        if cached is not None:
            # touch - move to end of OrderedDict (most-recent)
            _MATCH_DETAIL_CACHE.move_to_end(cache_key)
            return cached
    index_ok = _load_champ_index()
    c = _open()
    if c is None:
        return None
    try:
        m = c.execute(
            """
            SELECT match_id, queue_id, game_mode, game_duration_s,
                   game_creation_ts, patch, tracked_champion_id,
                   tracked_champion_name, tracked_team_id, tracked_win
            FROM matches WHERE match_id = ?
            """,
            (match_id,),
        ).fetchone()
        if not m:
            return None
        # Participants + team win.
        parts_rows = c.execute(
            """
            SELECT p.participant_id, p.team_id, p.champion_id, p.champion_name,
                   p.riot_id_game_name, p.summoner_name, p.summoner_level,
                   COALESCE(p.win, t.win) AS win
            FROM participants p
            LEFT JOIN teams t
              ON t.match_id = p.match_id AND t.team_id = p.team_id
            WHERE p.match_id = ?
            ORDER BY p.team_id, p.participant_id
            """,
            (match_id,),
        ).fetchall()
        participants = [
            {
                "participant_id":  r["participant_id"],
                "team_id":         r["team_id"],
                "champion_id":     r["champion_id"],
                "champion_name":   r["champion_name"]
                                    or _id_to_champ.get(r["champion_id"], "?"),
                "summoner_name":   r["riot_id_game_name"] or r["summoner_name"] or "",
                "summoner_level":  r["summoner_level"],
                "team_won":        bool(r["win"]) if r["win"] is not None else None,
            }
            for r in parts_rows
        ]

        # All frame timestamps for this match.
        ts_rows = c.execute(
            "SELECT DISTINCT timestamp_ms FROM timeline_frames "
            "WHERE match_id = ? AND typeof(timestamp_ms) = 'integer' "
            "ORDER BY timestamp_ms",
            (match_id,),
        ).fetchall()
        timestamps = [r["timestamp_ms"] for r in ts_rows]
        # Sample down to max_frames if needed.
        #
        # AUDIT 2026-08-31 (lane 8 cycle 32): the old sampler was
        # `timestamps[int(i * len/max)]` for i in range(max), which can
        # never reach the final index - at 90 frames capped to 60 it kept
        # index 88 and dropped 89, losing the END of the game, the single
        # most-looked-at moment of a match. Anchor both ends instead.
        # max_frames < 1 used to be a ZeroDivisionError on a public
        # signature (the route does not pass it today, so it was latent).
        cap = max(1, int(max_frames))
        if len(timestamps) > cap:
            if cap == 1:
                timestamps = [timestamps[-1]]
            else:
                last = len(timestamps) - 1
                keep = sorted({round(i * last / (cap - 1)) for i in range(cap)})
                timestamps = [timestamps[i] for i in keep]

        # Pre-load all frame data for this match so we don't N+1.
        frame_rows = c.execute(
            """
            SELECT timestamp_ms, participant_id, level, total_gold,
                   minions_killed, jungle_minions, pos_x, pos_y,
                   total_dmg_done, total_dmg_taken
            FROM timeline_frames
            WHERE match_id = ?
            """,
            (match_id,),
        ).fetchall()
        # Index: (ts, pid) -> frame
        by_ts_pid: dict[tuple, dict] = {}
        for r in frame_rows:
            by_ts_pid[(r["timestamp_ms"], r["participant_id"])] = dict(r)

        # All item events for inventory folding.
        event_rows = c.execute(_ITEM_EVENTS_SQL, (match_id,)).fetchall()

        # Build per-minute frame summaries.
        snapshots = []
        for ts in timestamps:
            inv = _build_inventory_at(event_rows, ts)
            entries = []
            for p in participants:
                pid = p["participant_id"]
                f = by_ts_pid.get((ts, pid)) or {}
                minions, jungle = f.get("minions_killed"), f.get("jungle_minions")
                entries.append({
                    "participant_id": pid,
                    "level":          f.get("level"),
                    "total_gold":     f.get("total_gold"),
                    "cs":             None if minions is None and jungle is None
                                       else (minions or 0) + (jungle or 0),
                    "pos":            _position(f.get("pos_x"), f.get("pos_y")),
                    "dmg_done":       f.get("total_dmg_done"),
                    "dmg_taken":      f.get("total_dmg_taken"),
                    "items":          inv.get(pid, []),
                })
            snapshots.append({
                "timestamp_ms": ts,
                "minute":       round(ts / 60000.0, 1),
                "entries":      entries,
            })

        # Kill events for the timeline overlay.
        kill_rows = c.execute(
            """
            SELECT timestamp_ms, killer_id, victim_id, assisting_ids_json,
                   kill_pos_x, kill_pos_y
            FROM timeline_events
            WHERE match_id = ? AND event_type = 'CHAMPION_KILL'
              AND typeof(timestamp_ms) = 'integer'
            ORDER BY timestamp_ms
            """,
            (match_id,),
        ).fetchall()
        kills = []
        for r in kill_rows:
            kills.append({
                "timestamp_ms": r["timestamp_ms"],
                "minute":       round(r["timestamp_ms"] / 60000.0, 1),
                "killer_id":    r["killer_id"],
                "victim_id":    r["victim_id"],
                "assists":      _seat_ids(r["assisting_ids_json"]),
                "pos":          _position(r["kill_pos_x"], r["kill_pos_y"]),
            })

        tracked_team, tracked_win = _tracked_seat(c, m)
        result = {
            "match_id":         m["match_id"],
            "queue_id":         m["queue_id"],
            "game_mode":        m["game_mode"],
            "duration_s":       m["game_duration_s"],
            "game_creation_ts": m["game_creation_ts"],
            "patch":            m["patch"],
            "tracked": {
                "champion_id":   m["tracked_champion_id"],
                "champion_name": _tracked_name(m),
                "team_id":       tracked_team,
                "win":           tracked_win,
            },
            "participants":     participants,
            "snapshots":        snapshots,
            "kills":            kills,
        }
        if not index_ok:
            # RM-443: names resolved without the index; serve, do not cache.
            return result
        with _match_cache_lock:
            _MATCH_DETAIL_CACHE[cache_key] = result
            while len(_MATCH_DETAIL_CACHE) > _MATCH_DETAIL_CACHE_MAX:
                _MATCH_DETAIL_CACHE.popitem(last=False)  # evict LRU
        return result
    finally:
        try:
            c.close()
        except sqlite3.Error:
            pass
