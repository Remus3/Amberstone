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
        return sqlite3.connect(_REWIND_DB.resolve().as_uri() + "?mode=ro", uri=True)
    except sqlite3.Error as exc:
        log.warning("duration_winrate open: %s", exc)
        return None


# SQLite binds a signed 64-bit INTEGER; a larger Python int raises
# OverflowError (not sqlite3.Error) at execute time.
_SQLITE_INT_MIN = -(2 ** 63)
_SQLITE_INT_MAX = 2 ** 63 - 1
_SQLITE_INT_DIGITS = len(str(_SQLITE_INT_MAX))


def _coerce_champion(value) -> Optional[int]:
    """An integral champion id, or None for anything that is not one.

    Accepts an int (never a bool), an integral finite float and a str of
    an optionally signed decimal integer (surrounding whitespace ignored).
    Everything else - bool, text, bytes, NaN, inf, a fractional float, a
    container - is None, and so is any id outside SQLite's signed 64-bit
    range (no stored row can carry it, and binding it raises OverflowError).
    A digit string longer than that range is refused BEFORE int(), which
    would otherwise raise past Python's 4300-digit conversion limit.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        number = value
    elif isinstance(value, float):
        # is_integer() is False for NaN and +-inf, so this one test also
        # refuses the two values int() would raise on.
        if not value.is_integer():
            return None
        number = int(value)
    elif isinstance(value, str):
        text = value.strip()
        body = text[1:] if text[:1] in ("+", "-") else text
        if not body or not body.isascii() or not body.isdigit():
            return None
        # Python's digit limit counts leading zeros too, so parse the
        # zero-stripped digits, never the raw text.
        digits = body.lstrip("0") or "0"
        if len(digits) > _SQLITE_INT_DIGITS:
            return None
        number = -int(digits) if text[:1] == "-" else int(digits)
    else:
        return None
    if not _SQLITE_INT_MIN <= number <= _SQLITE_INT_MAX:
        return None
    return number


def _as_result(value) -> Optional[bool]:
    """tracked_win 1 -> True, 0 -> False, anything else (NULL, 2, text) ->
    None: an unknown result, which never enters a bucket (RM-610)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return {1: True, 0: False}.get(value)
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

    ``mode`` in VALID_MODES (else - including a non-string - falls back to
    DEFAULT_MODE). ``champion`` is an optional Riot integer champion id
    (filters tracked_champion_id): an int, an integral float or a decimal
    string, echoed back as an int. Anything else (a bool, text, NaN, a
    fractional float, an id outside SQLite's 64-bit range) is a filter
    nothing satisfies - zero games, champion echoed as None, no query run -
    never a silent widening to every champion.
    ``conn`` injects a db connection for tests; when None a read-only handle to
    the local rewind db is opened + closed. Only a resolved result
    (tracked_win 0 or 1) is counted; an unknown one is skipped, never read as
    a loss. Never raises - an unavailable db or empty corpus returns an ok
    payload with every bucket present and winrate None.
    """
    if not isinstance(mode, str) or mode not in MODE_MAPS:
        mode = DEFAULT_MODE
    map_id = MODE_MAPS[mode]

    champ_id: Optional[int] = None
    matchable = True
    if champion is not None:
        champ_id = _coerce_champion(champion)
        matchable = champ_id is not None

    own = conn is None
    if own and matchable:
        conn = _open_ro()

    rows: list = []
    if conn is not None and matchable:
        try:
            where = ["map_id = ?", "game_duration_s >= ?", "game_duration_s < ?"]
            params: list = [map_id, MIN_DURATION_S, MAX_DURATION_S]
            if champ_id is not None:
                where.append("tracked_champion_id = ?")
                params.append(champ_id)
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
        result = _as_result(win)
        if result is None:
            continue
        bi = _bucket_index(int(dur_s), buckets)
        if bi is None:
            continue
        tally[bi][1] += 1
        if result:
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
        "champion": champ_id,
        "n": total,
        "min_bucket_n": MIN_BUCKET_N,
        "buckets": out_buckets,
    }
