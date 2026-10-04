"""core/opening_tendency.py - per-puuid opening-tendency metrics (RM-613).

Directive X-13 (provenance: external reference I, behaviour only - no code,
constants or data taken from it). The reference replays level-1 positioning,
the jungle route to the first gank and pre-5:00 kills but computes no
aggregates; this module computes them over the Match-V5 timelines already
stored in data/rewind_history.db.

Metrics per puuid (Summoner's Rift only):

  jungle_start_side  - the jungler's 1:00 frame position classified by
                       core.minimap_districts.district_of (sr grid) into a
                       map side ("top" / "bot"); when the 1:00 frame lands
                       in a side-less district (mid square, a base) the
                       2:00 frame decides (the mid corridor and the
                       centre river square carry no side). Jungle only.
  invade_rate        - share of jungle games where the 1:00 frame sits on
                       the ENEMY half (team-relative, the base-to-base
                       diagonal splits the halves, with a margin) outside a
                       base district: a level-1 invade.
  first_gank_lane    - district bucket of the first CHAMPION_KILL before
                       5:00 where the jungler is the killer or an assister;
                       "none" when there is none. Jungle games only.
  level1_lane        - district bucket of the player's own 1:00 frame
                       (any role).

Every rate goes through core.smoothed_rates.laplace_rate (Beta(1,1)
shrinkage toward 0.5, so 4/4 reads 0.833 not 1.0). A metric whose sample
is below MIN_GAMES returns the '-' sentinel instead of a number.

Exclusions: event modes (queue 2400), non-Rift maps (map_id != 11, the
district grid used is the sr grid) and games without a timeline
(has_timeline = 0 or no frame rows for the player).

Trinket timing is not derivable (NOT computed here): Match-V5 WARD_PLACED events carry no
position (and no participant frame fixes when the trinket was used), so a
"first ward at X" metric cannot be built from this data.

Known coarseness: frames are one per minute, and the sr district grid
keeps a legacy convention whose "river" ids are really the mid-lane
corridor (measured; see _BUCKET_BY_DISTRICT). Buckets are coarse map
regions, not exact camps. At 1:00 laners are often still leashing, so a
"jungle" level-1 bucket for a laner is real behaviour, not an error.

Pure layer (classify_game / tendencies_from_games) works on plain dicts;
load_games reads a sqlite connection; opening_tendencies is the fail-soft
entry point used by POST /api/scouting. Never raises.
"""
from __future__ import annotations

import json
import logging
import math
import sqlite3
import threading
import time
from pathlib import Path
from typing import Iterable, Optional

from core.minimap_districts import district_of
from core.smoothed_rates import laplace_rate

log = logging.getLogger("rc.opening_tendency")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_REWIND_DB = _PROJECT_ROOT / "data" / "rewind_history.db"

SENTINEL = "-"

# Our own constants (not taken from any external reference):
#: Below 3 games a single game decides the mode; we report '-' instead.
MIN_GAMES = 3
#: SR playable extent in Match-V5 units - same value RC already uses in
#: core/mia_reachability.py:66 and core/champion_movespeed.py:58.
SR_MAP_EXTENT = 14800.0
SR_MAP_ID = 11
EVENT_QUEUE_ID = 2400
ONE_MIN_MS = 60000
TWO_MIN_MS = 120000
FIRST_GANK_CUTOFF_MS = 300000
#: Frames land a few ms after the minute (60008, 60014...); accept a
#: frame within 15 s of the target minute, nothing further.
FRAME_TOLERANCE_MS = 15000
#: Half-split margin in box-fractions (~740 units): positions this close
#: to the base-to-base diagonal are not called an invade.
INVADE_MARGIN = 0.05
#: Most-recent eligible games read per puuid (bounds the DB cost of a
#: 10-player scouting request).
PER_PUUID_LIMIT = 40

SMITE_SPELL_ID = 11

#: Per-puuid result cache (same 5-min horizon as the scouting rank cache in
#: dashboard/routes_scouting.py _RANK_TTL_S), bounded drop-oldest.
_CACHE_TTL_S = 300.0
_CACHE_MAX = 256
_CACHE: dict = {}
_CACHE_LOCK = threading.Lock()


def _reset_cache_for_tests():
    """Test seam: drop every cached opening result."""
    with _CACHE_LOCK:
        _CACHE.clear()

# District id -> map side / lane bucket. The sr grid keeps the legacy
# convention (core/minimap_districts.py docstring): its "top_river" /
# "bot_river" (and the baron_pit / dragon_pit diamonds sitting on the same
# line) are the two halves of the BASE-TO-BASE corridor, which on the real
# Match-V5 map is MID LANE; its "mid_lane" square, minus that corridor, is
# the real river around the centre. Measured 2026-10-04 over the local
# rewind_history.db (SR queues 400/420/430/440/490, 1309 MIDDLE 2:00
# frames): 1285 (98 percent) land in top_river/bot_river, 6 in mid_lane.
# So the corridor districts bucket as "mid" and carry NO side; the
# mid_lane square buckets as "river" and carries no side either (its two
# halves are both sides of the river and the id cannot tell them apart).
# Side is GEOMETRIC (which side of the base-to-base corridor), not read
# from the id: the left strip "jungle_bot_blue" is TOP side and the right
# strip "jungle_top_red" is BOT side (verifier-measured on the local DB:
# 14/14 and 10/10 jungler frames; pinned in the tests).
_SIDE_BY_DISTRICT = {
    "top_lane": "top", "jungle_top_blue": "top", "jungle_bot_blue": "top",
    "bot_lane": "bot", "jungle_bot_red": "bot", "jungle_top_red": "bot",
}

_BUCKET_BY_DISTRICT = {
    "top_lane": "top", "bot_lane": "bot",
    "top_river": "mid", "bot_river": "mid",
    "baron_pit": "mid", "dragon_pit": "mid",
    "mid_lane": "river",
    "jungle_top_blue": "jungle", "jungle_top_red": "jungle",
    "jungle_bot_blue": "jungle", "jungle_bot_red": "jungle",
    "blue_base": "base", "red_base": "base",
}

LANE_BUCKETS = ("top", "mid", "bot", "jungle", "river", "base", "other")
GANK_BUCKETS = LANE_BUCKETS + ("none",)


# --- geometry -----------------------------------------------------------------

def to_frac(pos_x, pos_y):
    """Match-V5 map units (y-up) -> minimap box-fraction (y-down, blue base
    bottom-left), the frame core.minimap_districts expects. Garbage in ->
    (nan, nan), which district_of maps to its fallback. Never raises."""
    try:
        x = float(pos_x) / SR_MAP_EXTENT
        y = 1.0 - float(pos_y) / SR_MAP_EXTENT
    except (TypeError, ValueError):
        return (math.nan, math.nan)
    return (x, y)


def _district(pos_x, pos_y):
    x, y = to_frac(pos_x, pos_y)
    return district_of(x, y, "sr")


def _bucket(district_id):
    return _BUCKET_BY_DISTRICT.get(district_id, "other")


def _on_enemy_half(pos_x, pos_y, team_id):
    x, y = to_frac(pos_x, pos_y)
    if not (math.isfinite(x) and math.isfinite(y)):
        return False
    # Blue half is below-left of the base-to-base diagonal (y > x in the
    # y-down frame); red half is above-right.
    if team_id == 100:
        return y < x - INVADE_MARGIN
    if team_id == 200:
        return y > x + INVADE_MARGIN
    return False


# --- per-game classification ------------------------------------------------------

def _frame_at(frames, pid, target_ms):
    best = None
    best_d = None
    for f in frames:
        if f.get("participant_id") != pid:
            continue
        if f.get("pos_x") is None or f.get("pos_y") is None:
            continue
        try:
            d = abs(int(f.get("timestamp_ms")) - target_ms)
        except (TypeError, ValueError):
            continue
        if d <= FRAME_TOLERANCE_MS and (best_d is None or d < best_d):
            best, best_d = f, d
    return best


def _is_jungler(part):
    if str(part.get("team_position") or "").upper() == "JUNGLE":
        return True
    return SMITE_SPELL_ID in (part.get("summoner1_id"), part.get("summoner2_id"))


def _eligible(game):
    if game.get("queue_id") == EVENT_QUEUE_ID:
        return False
    if game.get("map_id") != SR_MAP_ID:
        return False
    return bool(game.get("has_timeline"))


def classify_game(game: dict, puuid: str) -> Optional[dict]:
    """One game's opening observation for ``puuid``, or None when the game
    is excluded (event mode, non-Rift, no timeline, player absent or no
    1:00 frame). Never raises."""
    try:
        if not isinstance(game, dict) or not _eligible(game):
            return None
        part = next((p for p in game.get("participants") or ()
                     if p.get("puuid") == puuid), None)
        if part is None:
            return None
        pid = part.get("participant_id")
        frames = game.get("frames") or ()
        f1 = _frame_at(frames, pid, ONE_MIN_MS)
        if f1 is None:
            return None
        d1 = _district(f1["pos_x"], f1["pos_y"])
        obs = {"match_id": game.get("match_id"),
               "jungler": _is_jungler(part),
               "level1_lane": _bucket(d1),
               "start_side": None, "invade": None, "first_gank_lane": None}
        if not obs["jungler"]:
            return obs
        side = _SIDE_BY_DISTRICT.get(d1)
        if side is None:
            f2 = _frame_at(frames, pid, TWO_MIN_MS)
            if f2 is not None:
                side = _SIDE_BY_DISTRICT.get(_district(f2["pos_x"], f2["pos_y"]))
        obs["start_side"] = side
        obs["invade"] = (_bucket(d1) != "base"
                         and _on_enemy_half(f1["pos_x"], f1["pos_y"],
                                            part.get("team_id")))
        obs["first_gank_lane"] = _first_gank_bucket(game.get("kills") or (), pid)
        return obs
    except Exception as exc:  # noqa: BLE001 - fail-soft per game
        log.debug("opening_tendency classify: %s", exc)
        return None


def _first_gank_bucket(kills, pid):
    hits = []
    for k in kills:
        try:
            ts = int(k.get("timestamp_ms"))
        except (TypeError, ValueError):
            continue
        if ts >= FIRST_GANK_CUTOFF_MS:
            continue
        assists = k.get("assists") or ()
        if k.get("killer_id") == pid or pid in assists:
            hits.append((ts, k))
    if not hits:
        return "none"
    _ts, k = min(hits, key=lambda h: h[0])
    if k.get("pos_x") is None or k.get("pos_y") is None:
        return "other"
    return _bucket(_district(k["pos_x"], k["pos_y"]))


# --- aggregation ----------------------------------------------------------------------

def _rate(count, n):
    return round(laplace_rate(count, n), 3)


def _distribution(values, buckets, min_games):
    n = len(values)
    if n < min_games:
        return SENTINEL
    counts = {b: 0 for b in buckets}
    for v in values:
        counts[v if v in counts else "other"] += 1
    mode = max(buckets, key=lambda b: (counts[b], -buckets.index(b)))
    return {"n": n, "mode": mode,
            "rates": {b: _rate(c, n) for b, c in counts.items() if c}}


def aggregate(observations: Iterable[dict], min_games: int = MIN_GAMES) -> dict:
    obs = [o for o in observations if o]
    jg = [o for o in obs if o.get("jungler")]
    out = {"games": len(obs), "jungle_games": len(jg)}
    out["level1_lane"] = _distribution(
        [o["level1_lane"] for o in obs], LANE_BUCKETS, min_games)
    sides = [o["start_side"] for o in jg if o.get("start_side") in ("top", "bot")]
    if len(sides) < min_games:
        out["jungle_start_side"] = SENTINEL
    else:
        n = len(sides)
        top = sides.count("top")
        top_rate = _rate(top, n)
        bot_rate = _rate(n - top, n)
        mode = "top" if top_rate > bot_rate else (
            "bot" if bot_rate > top_rate else "even")
        out["jungle_start_side"] = {"n": n, "mode": mode,
                                    "top_rate": top_rate, "bot_rate": bot_rate}
    if len(jg) < min_games:
        out["invade_rate"] = SENTINEL
    else:
        out["invade_rate"] = _rate(sum(1 for o in jg if o.get("invade")), len(jg))
    out["first_gank_lane"] = _distribution(
        [o["first_gank_lane"] for o in jg], GANK_BUCKETS, min_games)
    return out


def tendencies_from_games(games: Iterable[dict], puuids: Iterable[str],
                          min_games: int = MIN_GAMES) -> dict:
    games = list(games or ())
    result = {}
    for p in puuids:
        obs = [classify_game(g, p) for g in games]
        result[p] = aggregate(obs, min_games)
    return result


# --- sqlite loader -----------------------------------------------------------------------

def load_games(conn: sqlite3.Connection, puuids: Iterable[str],
               per_puuid_limit: int = PER_PUUID_LIMIT) -> list:
    """Read eligible games (SR, not queue 2400, has_timeline) for the given
    puuids from a rewind_history.db-shaped connection. Only the player's own
    early frames (to 2:15) and the pre-5:00 kills are loaded."""
    puuids = [p for p in puuids if isinstance(p, str) and p]
    match_ids = []
    for p in puuids:
        rows = conn.execute(
            """
            SELECT m.match_id FROM participants p
            JOIN matches m ON m.match_id = p.match_id
            WHERE p.puuid = ? AND m.map_id = ? AND m.has_timeline = 1
              AND COALESCE(m.queue_id, -1) != ?
            ORDER BY m.game_creation_ts DESC LIMIT ?
            """,
            (p, SR_MAP_ID, EVENT_QUEUE_ID, int(per_puuid_limit)),
        ).fetchall()
        for (mid,) in rows:
            if mid not in match_ids:
                match_ids.append(mid)
    games = []
    wanted = set(puuids)
    for mid in match_ids:
        m = conn.execute(
            "SELECT queue_id, map_id, has_timeline FROM matches WHERE match_id = ?",
            (mid,)).fetchone()
        parts = [
            {"participant_id": r[0], "team_id": r[1], "puuid": r[2],
             "team_position": r[3], "summoner1_id": r[4], "summoner2_id": r[5]}
            for r in conn.execute(
                "SELECT participant_id, team_id, puuid, team_position,"
                " summoner1_id, summoner2_id FROM participants WHERE match_id = ?",
                (mid,))
            if r[2] in wanted
        ]
        frames = []
        for part in parts:
            frames.extend(
                {"timestamp_ms": r[0], "participant_id": part["participant_id"],
                 "pos_x": r[1], "pos_y": r[2]}
                for r in conn.execute(
                    "SELECT timestamp_ms, pos_x, pos_y FROM timeline_frames"
                    " WHERE match_id = ? AND participant_id = ?"
                    " AND timestamp_ms <= ?",
                    (mid, part["participant_id"],
                     TWO_MIN_MS + FRAME_TOLERANCE_MS)))
        kills = []
        for r in conn.execute(
                "SELECT timestamp_ms, killer_id, assisting_ids_json,"
                " kill_pos_x, kill_pos_y FROM timeline_events"
                " WHERE match_id = ? AND event_type = 'CHAMPION_KILL'"
                " AND timestamp_ms < ?",
                (mid, FIRST_GANK_CUTOFF_MS)):
            try:
                assists = json.loads(r[2] or "[]")
            except (TypeError, ValueError):
                assists = []
            kills.append({"timestamp_ms": r[0], "killer_id": r[1],
                          "assists": assists if isinstance(assists, list) else [],
                          "pos_x": r[3], "pos_y": r[4]})
        games.append({"match_id": mid, "queue_id": m[0], "map_id": m[1],
                      "has_timeline": bool(m[2]), "participants": parts,
                      "frames": frames, "kills": kills})
    return games


def opening_tendencies(puuids: Iterable[str], db_path=None,
                       min_games: int = MIN_GAMES) -> dict:
    """Fail-soft entry point: {puuid: metrics}. A missing / unreadable DB
    yields the empty-sample shape (all '-') for every puuid.

    Each puuid is scored over ITS OWN most-recent PER_PUUID_LIMIT eligible
    games only. Results are cached per (db, puuid, min_games) for
    _CACHE_TTL_S so a champ-select re-poll does not re-read the DB (the
    timeline DB only grows when a match download lands)."""
    puuids = [p for p in (puuids or ()) if isinstance(p, str) and p]
    path = Path(db_path) if db_path is not None else _REWIND_DB
    now = time.monotonic()
    out: dict = {}
    missing = []
    with _CACHE_LOCK:
        for p in puuids:
            hit = _CACHE.get((str(path), p, min_games))
            if hit is not None and now - hit[0] < _CACHE_TTL_S:
                out[p] = hit[1]
            else:
                missing.append(p)
    if not missing:
        return out
    fresh: dict = {}
    conn = None
    try:
        if path.exists():
            conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        for p in missing:
            games = load_games(conn, [p]) if conn is not None else []
            fresh[p] = tendencies_from_games(games, [p], min_games)[p]
    except sqlite3.Error as exc:
        log.warning("opening_tendency load: %s", exc)
        for p in missing:
            fresh.setdefault(p, aggregate([], min_games))
        # A failed read is not cached: the next poll retries.
        out.update(fresh)
        return out
    finally:
        if conn is not None:
            conn.close()
    with _CACHE_LOCK:
        for p, v in fresh.items():
            _CACHE[(str(path), p, min_games)] = (now, v)
        if len(_CACHE) > _CACHE_MAX:
            for k, _v in sorted(_CACHE.items(), key=lambda kv: kv[1][0])[
                    :len(_CACHE) - _CACHE_MAX]:
                _CACHE.pop(k, None)
    out.update(fresh)
    return out
