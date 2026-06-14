"""
core/replay_history.py - read-only access to data/rewind_history.db for
the replay-scrubber dashboard view.

AUDIT 2026-04-28 (suggestion 2.3): rewind_history.db has 2846 matches
with full timeline_frames (per-minute level/gold/CS/position) and
timeline_events (kills, item buys, objective takes). This module
exposes:

    list_matches(limit, queue_filter)
        recent matches with per-row {match_id, queue_id, duration_s,
        game_creation_ts, win (for tracked player), tracked_champion}.

    match_detail(match_id)
        full match data formatted for a scrubber UI: participants,
        per-minute snapshots (level/gold/CS/items), kill events.

Items at minute T are computed by folding ITEM_PURCHASED / ITEM_SOLD /
ITEM_DESTROYED / ITEM_UNDO events with timestamp <= T*60000. UNDO
reverses the most-recent matching purchase.

DDragon item id -> name resolution is deferred to the dashboard JS which
already has web/data/items_index.json loaded.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

_log = logging.getLogger("rc.replay_history")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_REWIND_DB    = _PROJECT_ROOT / "data" / "rewind_history.db"
_DDR_CHAMPS   = _PROJECT_ROOT / "data" / "meta" / "ddragon_champions.json"

_id_to_champ: dict[int, str] = {}
_idx_lock = threading.Lock()

# AUDIT 2026-04-29 (item 8): LRU cache for match_detail(). Matches are
# immutable once recorded - no invalidation needed. 8 entries x ~75 KB
# JSON ~ 600 KB RAM. Returning to a previously-viewed match is now ~0
# ms instead of 7 ms warm / 100 ms cold-after-idle.
import collections as _collections
_MATCH_DETAIL_CACHE: "_collections.OrderedDict[str, dict]" = _collections.OrderedDict()
_MATCH_DETAIL_CACHE_MAX = 8
_match_cache_lock = threading.Lock()


def _load_champ_index() -> None:
    # AUDIT 2026-06-11 (deep-audit P2-W1-A): build the index in a local
    # dict and publish it complete. The previous loop populated the
    # module dict key-by-key, so a concurrent caller could observe a
    # truthy-but-partial index and resolve champion names to "?" - and
    # match_detail() would then cache that bad name in its LRU.
    if _id_to_champ:
        return
    try:
        data = json.loads(_DDR_CHAMPS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    built: dict[int, str] = {}
    for slug, entry in (data.get("data") or {}).items():
        try:
            cid = int(entry.get("key"))
        except (TypeError, ValueError):
            continue
        built[cid] = entry.get("name") or slug
    with _idx_lock:
        if _id_to_champ:
            return
        _id_to_champ.update(built)


def _open() -> Optional[sqlite3.Connection]:
    if not _REWIND_DB.exists():
        return None
    try:
        c = sqlite3.connect(str(_REWIND_DB))
        c.row_factory = sqlite3.Row
        return c
    except sqlite3.Error as exc:
        _log.warning("rewind_history open: %s", exc)
        return None


def list_matches(limit: int = 25, queue_filter: Optional[int] = None) -> list[dict]:
    """Recent matches sorted by game_creation_ts desc. Returns the metadata
    needed for the dashboard match picker - no per-frame data."""
    _load_champ_index()
    c = _open()
    if c is None:
        return []
    try:
        if queue_filter:
            rows = c.execute(
                """
                SELECT match_id, queue_id, game_mode, game_duration_s,
                       game_creation_ts, patch, tracked_champion_id
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
                       game_creation_ts, patch, tracked_champion_id
                FROM matches
                ORDER BY game_creation_ts DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        out = []
        for r in rows:
            mid = r["match_id"]
            tcid = r["tracked_champion_id"]
            tracked = {
                "champion_id":   tcid,
                "champion_name": _id_to_champ.get(tcid) if tcid else None,
            }
            # Win flag for tracked player: find their team and join teams.win
            if tcid:
                tw = c.execute(
                    """
                    SELECT t.win
                    FROM participants p
                    JOIN teams t
                      ON t.match_id = p.match_id AND t.team_id = p.team_id
                    WHERE p.match_id = ? AND p.champion_id = ?
                    LIMIT 1
                    """,
                    (mid, tcid),
                ).fetchone()
                tracked["win"] = bool(tw["win"]) if tw else None
            out.append({
                "match_id":         mid,
                "queue_id":         r["queue_id"],
                "game_mode":        r["game_mode"],
                "duration_s":       r["game_duration_s"],
                "game_creation_ts": r["game_creation_ts"],
                "patch":            r["patch"],
                "tracked":          tracked,
            })
        return out
    finally:
        try:
            c.close()
        except sqlite3.Error:
            pass


def _build_inventory_at(events: list[sqlite3.Row], up_to_ms: int) -> dict[int, list[int]]:
    """Per-participant item list at timestamp `up_to_ms`. Folds
    ITEM_PURCHASED / ITEM_SOLD / ITEM_DESTROYED / ITEM_UNDO in order.
    Returns {participant_id: [item_id, ...]}."""
    inv: dict[int, list[int]] = defaultdict(list)
    for e in events:
        if e["timestamp_ms"] > up_to_ms:
            break
        et = e["event_type"]
        pid = e["participant_id"]
        item = e["item_id"]
        if et == "ITEM_PURCHASED" and pid and item:
            inv[pid].append(item)
        elif et in ("ITEM_SOLD", "ITEM_DESTROYED") and pid and item:
            try:
                inv[pid].remove(item)
            except ValueError:
                pass
        elif et == "ITEM_UNDO" and pid and item:
            try:
                inv[pid].remove(item)
            except ValueError:
                pass
    return dict(inv)


def match_detail(match_id: str, *, max_frames: int = 60) -> Optional[dict]:
    """Full match data for the replay scrubber. Returns None if missing.

    `max_frames` caps per-minute snapshots so a 90-minute Aram doesn't
    explode the response. Frames are sampled evenly across the match
    duration when the cap is hit."""
    cache_key = f"{match_id}|{max_frames}"
    with _match_cache_lock:
        cached = _MATCH_DETAIL_CACHE.get(cache_key)
        if cached is not None:
            # touch - move to end of OrderedDict (most-recent)
            _MATCH_DETAIL_CACHE.move_to_end(cache_key)
            return cached
    _load_champ_index()
    c = _open()
    if c is None:
        return None
    try:
        m = c.execute(
            """
            SELECT match_id, queue_id, game_mode, game_duration_s,
                   game_creation_ts, patch, tracked_champion_id
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
                   t.win
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
            "WHERE match_id = ? ORDER BY timestamp_ms",
            (match_id,),
        ).fetchall()
        timestamps = [r["timestamp_ms"] for r in ts_rows]
        # Sample down to max_frames if needed.
        if len(timestamps) > max_frames:
            step = len(timestamps) / max_frames
            timestamps = [timestamps[int(i * step)] for i in range(max_frames)]

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
        event_rows = c.execute(
            """
            SELECT timestamp_ms, event_type, participant_id, item_id
            FROM timeline_events
            WHERE match_id = ?
              AND event_type IN ('ITEM_PURCHASED','ITEM_SOLD',
                                  'ITEM_DESTROYED','ITEM_UNDO')
            ORDER BY timestamp_ms, id
            """,
            (match_id,),
        ).fetchall()

        # Build per-minute frame summaries.
        snapshots = []
        for ts in timestamps:
            inv = _build_inventory_at(event_rows, ts)
            entries = []
            for p in participants:
                pid = p["participant_id"]
                f = by_ts_pid.get((ts, pid)) or {}
                entries.append({
                    "participant_id": pid,
                    "level":          f.get("level"),
                    "total_gold":     f.get("total_gold"),
                    "cs":             (f.get("minions_killed") or 0) +
                                       (f.get("jungle_minions") or 0),
                    "pos":            [f.get("pos_x"), f.get("pos_y")]
                                       if f.get("pos_x") is not None else None,
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
            ORDER BY timestamp_ms
            """,
            (match_id,),
        ).fetchall()
        kills = []
        for r in kill_rows:
            try:
                assists = json.loads(r["assisting_ids_json"] or "[]")
            except (TypeError, ValueError, json.JSONDecodeError):
                assists = []
            kills.append({
                "timestamp_ms": r["timestamp_ms"],
                "minute":       round(r["timestamp_ms"] / 60000.0, 1),
                "killer_id":    r["killer_id"],
                "victim_id":    r["victim_id"],
                "assists":      assists,
                "pos":          [r["kill_pos_x"], r["kill_pos_y"]]
                                  if r["kill_pos_x"] is not None else None,
            })

        result = {
            "match_id":         m["match_id"],
            "queue_id":         m["queue_id"],
            "game_mode":        m["game_mode"],
            "duration_s":       m["game_duration_s"],
            "game_creation_ts": m["game_creation_ts"],
            "patch":            m["patch"],
            "tracked": {
                "champion_id":   m["tracked_champion_id"],
                "champion_name": _id_to_champ.get(m["tracked_champion_id"])
                                  if m["tracked_champion_id"] else None,
            },
            "participants":     participants,
            "snapshots":        snapshots,
            "kills":            kills,
        }
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
