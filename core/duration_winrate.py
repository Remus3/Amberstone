"""Win-rate-by-game-length aggregation over the local rewind_history.db.

A per-mode curve of the tracked player's win % bucketed by match duration -
the win-rate-by-game-length surface popularized by public stats sites, here
computed over the operator's OWN match corpus (no global / cross-player data,
no Riot or Claude call). An upward slope across buckets reads as a
scaling / late-game tendency; a downward slope as an early-game / snowball
tendency.

Read-only. Mirrors core.player_gpi's map_id mode mapping + MIN_DURATION_S
remake gate + conn-injection seam (so tests inject an in-memory db and the
suite stays clean-checkout safe; the db is gitignored).

Win + duration both live on the ``matches`` table (tracked_win,
game_duration_s, map_id, tracked_champion_id), so no participants/teams join
is needed - unlike core.replay_history.list_matches which joins only because
it does not select the tracked_win column.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Optional

log = logging.getLogger("rc.duration_winrate")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_REWIND_DB = _PROJECT_ROOT / "data" / "rewind_history.db"

# map_id per mode - same convention as core.player_gpi.MODE_MAPS. Filtering on
# map_id (not queue_id) folds every ARAM queue (450/720/920/2400) into map 12
# automatically.
MODE_MAPS: dict[str, int] = {"sr": 11, "aram": 12, "arena": 30}
VALID_MODES = ("sr", "aram", "arena")
# The operator's corpus is ARAM-dominant (~70% of tracked matches), so the
# duration curve is most populated there - default to it (its sibling
# routes_player_profile defaults to sr; this surface is corpus-driven instead).
DEFAULT_MODE = "aram"

MIN_DURATION_S = 300      # drop remakes / very-early surrenders (mirror player_gpi)
MAX_DURATION_S = 7200     # drop corrupt / ms-encoded outliers; a real game never reaches 2h
MIN_BUCKET_N = 5          # below this a bucket's winrate is untrustworthy -> None

# (label, lo_s inclusive, hi_s exclusive | None for open-ended). One bucket set
# spans both short ARAM (~15-25m) and longer SR (~25-40m) corpora.
DEFAULT_BUCKETS = (
    ("<15m", 0, 900),
    ("15-20m", 900, 1200),
    ("20-25m", 1200, 1500),
    ("25-30m", 1500, 1800),
    ("30-35m", 1800, 2100),
    ("35m+", 2100, None),
)


def _open_ro() -> Optional[sqlite3.Connection]:
    if not _REWIND_DB.exists():
        return None
    try:
        return sqlite3.connect(f"file:{_REWIND_DB}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        log.warning("duration_winrate open: %s", exc)
        return None


def _bucket_index(dur_s: int, buckets) -> Optional[int]:
    for i, (_label, lo, hi) in enumerate(buckets):
        if dur_s >= lo and (hi is None or dur_s < hi):
            return i
    return None


def compute_duration_winrate(mode: str = DEFAULT_MODE,
                             champion: Optional[int] = None,
                             conn: Optional[sqlite3.Connection] = None,
                             buckets=DEFAULT_BUCKETS) -> dict:
    """Win % per duration bucket for the tracked player.

    ``mode`` in VALID_MODES (else falls back to DEFAULT_MODE). ``champion`` is
    an optional Riot integer champion id (filters tracked_champion_id).
    ``conn`` injects a db connection for tests; when None a read-only handle to
    the local rewind db is opened + closed. Never raises - an unavailable db or
    empty corpus returns an ok payload with every bucket present and
    winrate None.
    """
    if mode not in MODE_MAPS:
        mode = DEFAULT_MODE
    map_id = MODE_MAPS[mode]

    own = conn is None
    if own:
        conn = _open_ro()

    rows: list = []
    if conn is not None:
        try:
            where = ["map_id = ?", "game_duration_s >= ?", "game_duration_s < ?"]
            params: list = [map_id, MIN_DURATION_S, MAX_DURATION_S]
            if champion is not None:
                where.append("tracked_champion_id = ?")
                params.append(int(champion))
            sql = ("SELECT game_duration_s, tracked_win FROM matches WHERE "
                   + " AND ".join(where))
            rows = conn.execute(sql, params).fetchall()
        except sqlite3.Error as exc:
            log.warning("duration_winrate query: %s", exc)
            rows = []
        finally:
            if own:
                try:
                    conn.close()
                except sqlite3.Error:
                    pass

    tally = [[0, 0] for _ in buckets]  # [wins, games] per bucket
    for dur_s, win in rows:
        if dur_s is None:
            continue
        bi = _bucket_index(int(dur_s), buckets)
        if bi is None:
            continue
        tally[bi][1] += 1
        if win:
            tally[bi][0] += 1

    out_buckets = []
    total = 0
    for (label, lo, hi), (wins, games) in zip(buckets, tally):
        total += games
        winrate = round(100.0 * wins / games, 1) if games >= MIN_BUCKET_N else None
        out_buckets.append({
            "label": label,
            "lo_s": lo,
            "hi_s": hi,
            "wins": wins,
            "games": games,
            "winrate": winrate,
        })

    return {
        "ok": True,
        "mode": mode,
        "champion": champion,
        "n": total,
        "min_bucket_n": MIN_BUCKET_N,
        "buckets": out_buckets,
    }
