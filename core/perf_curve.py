"""Per-minute averaged performance curve over the local rewind_history.db.

A per-mode curve of the tracked player's average cumulative gold (or creep
score) at each game minute, split into the games the player WON vs LOST -
the per-minute "performance graph" popularized by public player-analytics
sites, here computed over the operator's OWN match corpus (no global /
cross-player data, no Riot or Claude call). Reading the split: a win curve
that pulls away from the loss curve early reads as "I snowball my leads";
a loss curve that flattens around a minute reads as "my losses stall there".

Read-only. Mirrors core.duration_winrate's map_id mode mapping + MIN_DURATION_S
remake gate + conn-injection seam (so tests inject an in-memory db and the
suite stays clean-checkout safe; the db is gitignored).

The tracked participant's per-minute frames are reached by the same join
core.player_gpi uses (matches.tracked_champion_id + tracked_team_id ->
participants.participant_id) then participants.participant_id ->
timeline_frames. total_gold + minions_killed + jungle_minions are cumulative
to each frame in the Match-V5 timeline, so the per-minute value is the running
total at that minute (exactly a gold/CS curve). Damage is intentionally NOT
offered here: timeline total_dmg is cumulative AND all-units (not to-champs),
so a damage curve would mislead - a separate batch with the right field.
"""
from __future__ import annotations

import logging
import math
import sqlite3
from pathlib import Path
from typing import Optional

log = logging.getLogger("rc.perf_curve")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_REWIND_DB = _PROJECT_ROOT / "data" / "rewind_history.db"

# map_id per mode - same convention as core.duration_winrate / core.player_gpi.
MODE_MAPS: dict[str, int] = {"sr": 11, "aram": 12, "arena": 30}
VALID_MODES = ("sr", "aram", "arena")
# ARAM-dominant corpus -> default to the most-populated curve (mirror
# duration_winrate).
DEFAULT_MODE = "aram"

VALID_METRICS = ("gold", "cs")
DEFAULT_METRIC = "gold"

MIN_DURATION_S = 300      # drop remakes / very-early surrenders (mirror player_gpi)
MAX_MINUTE = 45           # cap the curve; a real game frame never exceeds this
MIN_GAMES_N = 5           # below this a minute's average is untrustworthy -> None


def _open_ro() -> Optional[sqlite3.Connection]:
    """A read-only handle to the local rewind db, or None.

    The URI comes from ``Path.as_uri()``, never an f-string over the raw path:
    a '#' (URI fragment) or '%' in the checkout path would otherwise open a
    different file and the curve would go silently empty (mirror
    core.duration_winrate._open_ro).
    """
    if not _REWIND_DB.exists():
        return None
    try:
        return sqlite3.connect(_REWIND_DB.resolve().as_uri() + "?mode=ro",
                               uri=True)
    except sqlite3.Error as exc:
        log.warning("perf_curve open: %s", exc)
        return None


# SQLite binds a signed 64-bit INTEGER; a larger Python int raises
# OverflowError (not sqlite3.Error) at execute time.
_SQLITE_INT_MIN = -(2 ** 63)
_SQLITE_INT_MAX = 2 ** 63 - 1
_SQLITE_INT_DIGITS = len(str(_SQLITE_INT_MAX))

# A stored gold / CS / timestamp magnitude above this is corruption (a real
# game's cumulative gold is under 1e6), and bounding every addend keeps the
# per-minute sums finite, so the payload never carries inf / nan.
_MAX_ABS_VALUE = 1e12


def _coerce_champion(value) -> Optional[int]:
    """An integral champion id, or None for anything that is not one.

    Accepts an int (never a bool), an integral finite float and a str of an
    optionally signed decimal integer (surrounding whitespace ignored).
    Everything else - bool, text, bytes, NaN, inf, a fractional float, a
    container - is None, and so is any id outside SQLite's signed 64-bit
    range (no stored row can carry it, and binding it raises OverflowError).
    A digit string longer than that range is refused BEFORE int(), which
    would otherwise raise past Python's 4300-digit conversion limit. Same
    contract as core.duration_winrate._coerce_champion.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        number = value
    elif isinstance(value, float):
        # is_integer() is False for NaN and +-inf.
        if not value.is_integer():
            return None
        number = int(value)
    elif isinstance(value, str):
        text = value.strip()
        body = text[1:] if text[:1] in ("+", "-") else text
        if not body or not body.isascii() or not body.isdigit():
            return None
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
    None: an unknown result, which is never read as a loss (mirror
    core.duration_winrate._as_result)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return {1: True, 0: False}.get(value)
    return None


def _as_number(value) -> Optional[float]:
    """A stored int / float as a bounded finite float, else None.

    SQLite is dynamically typed, so an INTEGER column can hand back text, a
    BLOB or an infinite REAL; none of those is a usable gold / CS / timestamp
    value (a bool is refused too - it is never a stored count).
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    if not math.isfinite(number) or abs(number) > _MAX_ABS_VALUE:
        return None
    return number


def _frame_value(metric: str, gold, minions, jungle) -> Optional[float]:
    """The per-frame curve value, or None when the frame is unusable.

    gold -> total_gold. cs -> minions_killed + jungle_minions, where a NULL
    operand reads as 0 (the historical COALESCE contract) but a non-NULL
    operand that is not a number makes the whole frame unusable instead of
    silently reading as 0.
    """
    if metric == "gold":
        return _as_number(gold)
    total = 0.0
    for operand in (minions, jungle):
        if operand is None:
            continue
        number = _as_number(operand)
        if number is None:
            return None
        total += number
    return total


def compute_perf_curve(mode: str = DEFAULT_MODE,
                       champion: Optional[int] = None,
                       metric: str = DEFAULT_METRIC,
                       conn: Optional[sqlite3.Connection] = None) -> dict:
    """Per-minute average of ``metric`` for the tracked player, win vs loss.

    ``mode`` in VALID_MODES (else - including a non-string - DEFAULT_MODE).
    ``metric`` in VALID_METRICS (else - including a non-string -
    DEFAULT_METRIC): "gold" -> cumulative total_gold, "cs" -> cumulative
    minions_killed + jungle_minions (a NULL operand reads as 0).
    ``champion`` is an optional Riot integer champion id (filters
    tracked_champion_id): an int, an integral float or a decimal string,
    echoed back as an int. Anything else (a bool, text, NaN, a fractional
    float, an id outside SQLite's 64-bit range) is a filter nothing
    satisfies - zero games, champion echoed as None, no query run - never a
    silent widening to every champion.
    ``conn`` injects a db connection for tests; when None a read-only handle
    to the local rewind db is opened + closed.

    Only a resolved result (tracked_win 0 or 1) is counted; an unknown one
    (NULL, 2, text) is skipped, never read as a loss, and is not in
    ``n_games``. A frame whose timestamp is unusable (NULL, text, BLOB,
    non-finite) or whose value is unusable (text, BLOB, non-finite, a
    magnitude above 1e12) is skipped - never bucketed at minute 0, never
    read as 0 - so every number in the payload is finite (strict JSON).
    Never raises - an unavailable db or empty corpus returns an ok payload
    with minutes == [].
    """
    if not isinstance(mode, str) or mode not in MODE_MAPS:
        mode = DEFAULT_MODE
    if not isinstance(metric, str) or metric not in VALID_METRICS:
        metric = DEFAULT_METRIC
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
            where = ["m.map_id = ?", "m.has_stats = 1", "m.game_duration_s >= ?"]
            params: list = [map_id, MIN_DURATION_S]
            if champ_id is not None:
                where.append("m.tracked_champion_id = ?")
                params.append(champ_id)
            sql = (
                "SELECT m.match_id, m.tracked_win, p.participant_id, "
                "f.timestamp_ms, f.total_gold, f.minions_killed, "
                "f.jungle_minions "
                "FROM matches m "
                "JOIN participants p ON p.match_id = m.match_id "
                "AND p.champion_id = m.tracked_champion_id "
                "AND p.team_id = m.tracked_team_id "
                "JOIN timeline_frames f ON f.match_id = m.match_id "
                "AND f.participant_id = p.participant_id "
                "WHERE " + " AND ".join(where) + " "
                "ORDER BY m.match_id, p.participant_id, f.timestamp_ms"
            )
            rows = conn.execute(sql, params).fetchall()
        except sqlite3.Error as exc:
            log.warning("perf_curve query: %s", exc)
            rows = []
        finally:
            if own:
                try:
                    conn.close()
                except sqlite3.Error:
                    pass

    # Per match: lock onto the first participant_id seen (sentinel tracked ids
    # can multi-match the join; mirror player_gpi's keep-first dedup) and keep
    # one cumulative value per (match, minute) - the last frame wins if two
    # frames ever land in the same minute bucket. A match whose result is
    # unknown is still locked (so its colliding participant rows stay out)
    # but never enters the curve.
    locked_pid: dict = {}
    win_by_match: dict = {}
    per_match_minute: dict = {}
    for match_id, tracked_win, pid, ts_ms, gold, minions, jungle in rows:
        if match_id not in locked_pid:
            locked_pid[match_id] = pid
            result = _as_result(tracked_win)
            if result is not None:
                win_by_match[match_id] = result
                per_match_minute[match_id] = {}
        if pid != locked_pid[match_id] or match_id not in per_match_minute:
            continue
        val = _frame_value(metric, gold, minions, jungle)
        if val is None:
            continue
        ts = _as_number(ts_ms)
        if ts is None:
            continue
        minute = int(ts // 60000)
        if minute < 0 or minute > MAX_MINUTE:
            continue
        per_match_minute[match_id][minute] = val

    # Aggregate across matches per minute, split win vs loss.
    win_sum: dict[int, float] = {}
    win_cnt: dict[int, int] = {}
    loss_sum: dict[int, float] = {}
    loss_cnt: dict[int, int] = {}
    for match_id, minute_vals in per_match_minute.items():
        won = win_by_match.get(match_id, False)
        for minute, val in minute_vals.items():
            if won:
                win_sum[minute] = win_sum.get(minute, 0.0) + val
                win_cnt[minute] = win_cnt.get(minute, 0) + 1
            else:
                loss_sum[minute] = loss_sum.get(minute, 0.0) + val
                loss_cnt[minute] = loss_cnt.get(minute, 0) + 1

    last_minute = -1
    for minute in list(win_cnt) + list(loss_cnt):
        if (win_cnt.get(minute, 0) >= MIN_GAMES_N
                or loss_cnt.get(minute, 0) >= MIN_GAMES_N):
            last_minute = max(last_minute, minute)

    minutes = []
    for minute in range(last_minute + 1):
        wc = win_cnt.get(minute, 0)
        lc = loss_cnt.get(minute, 0)
        win_avg = round(win_sum[minute] / wc, 1) if wc >= MIN_GAMES_N else None
        loss_avg = round(loss_sum[minute] / lc, 1) if lc >= MIN_GAMES_N else None
        if win_avg is None and loss_avg is None:
            continue
        minutes.append({
            "minute": minute,
            "win_avg": win_avg,
            "win_n": wc,
            "loss_avg": loss_avg,
            "loss_n": lc,
        })

    n_games = len(per_match_minute)
    return {
        "ok": True,
        "mode": mode,
        "metric": metric,
        "champion": champ_id,
        "n_games": n_games,
        "min_games_n": MIN_GAMES_N,
        "minutes": minutes,
    }
