"""Per-interval composite PERFORMANCE-score curve over the local rewind_history.db.

An aggregator-A-style "OP-Score" line: a single 0-100 composite performance score for
the tracked player at each game minute, split into the games the player WON vs
LOST, per mode - computed entirely over the operator's OWN match corpus (no
global / cross-player data, no Riot or Claude call). DISTINCT from the shipped
per-minute single-stat gold/CS curve (core.perf_curve, item 494): that plots one
raw cumulative stat; this folds several pace stats into one transparent index so
the line reads as "how well was I playing at minute N", not "how much gold did I
have". Also distinct from the win-probability curve (web pgr_winprob): that is a
single-match outcome estimate, this is a per-minute corpus-averaged performance
index.

THE FORMULA (fully transparent - no black box):
  At each per-minute frame the tracked player's four cumulative pace stats are
  read straight from timeline_frames (all four confirmed present in the corpus
  schema - rewind_scraper.py timeline_frames):
    - gold pace  = total_gold
    - xp pace    = xp
    - cs pace    = minions_killed + jungle_minions
    - combat     = total_dmg_done   (cumulative all-units damage dealt)
  Each stat is min-max normalized to 0..100 against the MAX value any tracked
  game (win OR loss) reached at that same minute in this corpus + mode (a self-
  relative scale: 100 = the operator's own best-ever pace at that minute). The
  per-frame composite is the fixed-weight mean of the four normalized parts:
    OP = 0.35*gold + 0.20*xp + 0.20*cs + 0.25*combat
  The four weights sum to 1.0, so OP is always in [0, 100]. The minute's win
  curve is the mean OP over the won games present at that minute; the loss curve
  the mean over the lost games. Reading the split: a win curve that sits well
  above the loss curve early reads as "I play measurably better in games I win
  from the start"; the two converging late reads as "my late-game performance
  looks the same win or lose".

Why this is honest: every input is a real per-frame field, the normalization
baseline is the operator's own corpus (not an invented external rating), and the
weights are a single documented constant - there is no Riot/aggregator A rating, ML, or
hidden model anywhere. It is a DESCRIPTIVE re-expression of stats the dashboard
already shows.

Read-only. Mirrors core.perf_curve's map_id mode mapping + MIN_DURATION_S remake
gate + keep-first sentinel dedup + conn-injection seam (so tests inject an
in-memory db and the suite stays clean-checkout safe; the db is gitignored).
The tracked participant's frames are reached by the same join core.perf_curve /
core.player_gpi use (matches.tracked_champion_id + tracked_team_id ->
participants.participant_id -> timeline_frames).
"""
from __future__ import annotations

import logging
import math
import sqlite3
from pathlib import Path
from typing import Optional

from core import op_score_shape

log = logging.getLogger("rc.op_score_curve")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_REWIND_DB = _PROJECT_ROOT / "data" / "rewind_history.db"

# map_id per mode - same convention as core.perf_curve / core.duration_winrate.
MODE_MAPS: dict[str, int] = {"sr": 11, "aram": 12, "arena": 30}
VALID_MODES = ("sr", "aram", "arena")
# ARAM-dominant corpus -> default to the most-populated curve (mirror perf_curve).
DEFAULT_MODE = "aram"

# This curve has a single composite metric (unlike perf_curve's gold/cs toggle),
# but the symbol is exported for route-layer parity with perf_curve.
VALID_METRICS = ("opscore",)
DEFAULT_METRIC = "opscore"

# Transparent composite weights (sum == 1.0 -> composite stays in [0, 100]).
W_GOLD = 0.35
W_XP = 0.20
W_CS = 0.20
W_COMBAT = 0.25

MIN_DURATION_S = 300      # drop remakes / very-early surrenders (mirror perf_curve)
MAX_MINUTE = 45           # cap the curve; a real game frame never exceeds this
MIN_GAMES_N = 5           # below this a minute's average is untrustworthy -> None


def _open_ro() -> Optional[sqlite3.Connection]:
    """A read-only handle to the local rewind db, or None.

    The URI comes from ``Path.as_uri()``, never an f-string over the raw path:
    a '#' (URI fragment) or '%' in the checkout path would otherwise open a
    different file and the curve would go silently empty (mirror
    core.perf_curve._open_ro).
    """
    if not _REWIND_DB.exists():
        return None
    try:
        return sqlite3.connect(_REWIND_DB.resolve().as_uri() + "?mode=ro",
                               uri=True)
    except sqlite3.Error as exc:
        log.warning("op_score_curve open: %s", exc)
        return None


# SQLite binds a signed 64-bit INTEGER; a larger Python int raises
# OverflowError (not sqlite3.Error) at execute time.
_SQLITE_INT_MIN = -(2 ** 63)
_SQLITE_INT_MAX = 2 ** 63 - 1
_SQLITE_INT_DIGITS = len(str(_SQLITE_INT_MAX))

# A stored stat / timestamp magnitude above this is corruption (a real game's
# cumulative gold, xp, cs or damage is far below it). Such a value would
# otherwise become the per-minute normalization max and read every real game
# at that minute as 0.
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
    contract as core.perf_curve._coerce_champion.
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
    core.perf_curve._as_result)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return {1: True, 0: False}.get(value)
    return None


def _as_number(value) -> Optional[float]:
    """A stored int / float as a bounded finite float, else None.

    SQLite is dynamically typed, so an INTEGER column can hand back text, a
    BLOB or an infinite REAL; none of those is a usable stat or timestamp
    (a bool is refused too - it is never a stored count).
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


def _frame_stats(gold, xp, minions, jungle, combat) -> Optional[tuple]:
    """The (gold, xp, cs, combat) tuple of one frame, or None if unusable.

    A NULL stat reads as 0 (the historical contract: ``float(x or 0)`` for
    gold / xp / combat and COALESCE for the two cs operands). A non-NULL stat
    that is not a bounded finite number (text, BLOB, +-inf, a magnitude above
    1e12) makes the whole frame unusable - it is skipped, never read as 0 and
    never allowed to become the normalization max.
    """
    out = []
    for value in (gold, xp, minions, jungle, combat):
        if value is None:
            out.append(0.0)
            continue
        number = _as_number(value)
        if number is None:
            return None
        out.append(number)
    g, x, m, j, c = out
    return (g, x, m + j, c)


def _empty(mode: str, champion: Optional[int]) -> dict:
    return {
        "ok": True,
        "mode": mode,
        "metric": DEFAULT_METRIC,
        "champion": champion,
        "n_games": 0,
        "min_games_n": MIN_GAMES_N,
        "weights": {"gold": W_GOLD, "xp": W_XP, "cs": W_CS, "combat": W_COMBAT},
        "minutes": [],
    }


def compute_op_score_curve(mode: str = DEFAULT_MODE,
                           champion: Optional[int] = None,
                           conn: Optional[sqlite3.Connection] = None) -> dict:
    """Per-minute composite 0-100 OP-Score for the tracked player, win vs loss.

    ``mode`` in VALID_MODES (else - including a non-string - DEFAULT_MODE).
    ``champion`` is an optional Riot integer champion id (filters
    tracked_champion_id): an int, an integral float or a decimal string,
    echoed back as an int. Anything else (a bool, text, NaN, a fractional
    float, an id outside SQLite's 64-bit range) is a filter nothing
    satisfies - zero games, champion echoed as None, no query run - never a
    silent widening to every champion.
    ``conn`` injects a db connection for tests; when None a read-only handle
    to the local rewind db is opened + closed.

    Only a resolved result (tracked_win 0 or 1) is counted; an unknown one
    (NULL, 2, text) is skipped - never read as a loss, never part of the
    normalization baseline, not in ``n_games``. A frame whose timestamp is
    unusable (NULL, text, BLOB, non-finite) or whose stat is unusable (see
    _frame_stats) is skipped, so every number in the payload is finite
    (strict JSON). Never raises - an unavailable db or empty corpus returns
    an ok payload with minutes == []. See the module docstring for the
    exact, fully transparent composite formula.
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
            where = ["m.map_id = ?", "m.has_stats = 1", "m.game_duration_s >= ?"]
            params: list = [map_id, MIN_DURATION_S]
            if champ_id is not None:
                where.append("m.tracked_champion_id = ?")
                params.append(champ_id)
            sql = (
                "SELECT m.match_id, m.tracked_win, p.participant_id, "
                "f.timestamp_ms, "
                "f.total_gold, f.xp, f.minions_killed, f.jungle_minions, "
                "f.total_dmg_done "
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
            log.warning("op_score_curve query: %s", exc)
            rows = []
        finally:
            if own:
                try:
                    conn.close()
                except sqlite3.Error:
                    pass

    # Per match: lock onto the first participant_id seen (sentinel tracked ids
    # can multi-match the join; mirror perf_curve's keep-first dedup) and keep
    # the last raw stat tuple per (match, minute). A match whose result is
    # unknown is still locked (so its colliding participant rows stay out)
    # but never enters the curve or the normalization baseline.
    locked_pid: dict = {}
    win_by_match: dict = {}
    # match_id -> {minute -> (gold, xp, cs, combat)}
    per_match_minute: dict = {}
    for (match_id, tracked_win, pid, ts_ms,
         gold, xp, minions, jungle, combat) in rows:
        if match_id not in locked_pid:
            locked_pid[match_id] = pid
            result = _as_result(tracked_win)
            if result is not None:
                win_by_match[match_id] = result
                per_match_minute[match_id] = {}
        if pid != locked_pid[match_id] or match_id not in per_match_minute:
            continue
        ts = _as_number(ts_ms)
        if ts is None:
            continue
        minute = int(ts // 60000)
        if minute < 0 or minute > MAX_MINUTE:
            continue
        stats = _frame_stats(gold, xp, minions, jungle, combat)
        if stats is None:
            continue
        per_match_minute[match_id][minute] = stats

    # Pass 1: per-minute corpus max for each raw stat (over win + loss alike) -
    # the self-relative normalization baseline.
    max_gold: dict[int, float] = {}
    max_xp: dict[int, float] = {}
    max_cs: dict[int, float] = {}
    max_combat: dict[int, float] = {}
    for minute_vals in per_match_minute.values():
        for minute, (gold, xp, cs, combat) in minute_vals.items():
            if gold > max_gold.get(minute, 0.0):
                max_gold[minute] = gold
            if xp > max_xp.get(minute, 0.0):
                max_xp[minute] = xp
            if cs > max_cs.get(minute, 0.0):
                max_cs[minute] = cs
            if combat > max_combat.get(minute, 0.0):
                max_combat[minute] = combat

    def _norm(val: float, mx: float) -> float:
        if mx <= 0:
            return 0.0
        return max(0.0, min(100.0, (val / mx) * 100.0))

    # Pass 2: per-minute composite per match, then split-bucket aggregate.
    win_sum: dict[int, float] = {}
    win_cnt: dict[int, int] = {}
    loss_sum: dict[int, float] = {}
    loss_cnt: dict[int, int] = {}
    for match_id, minute_vals in per_match_minute.items():
        won = win_by_match.get(match_id, False)
        for minute, (gold, xp, cs, combat) in minute_vals.items():
            op = (
                W_GOLD * _norm(gold, max_gold.get(minute, 0.0))
                + W_XP * _norm(xp, max_xp.get(minute, 0.0))
                + W_CS * _norm(cs, max_cs.get(minute, 0.0))
                + W_COMBAT * _norm(combat, max_combat.get(minute, 0.0))
            )
            if won:
                win_sum[minute] = win_sum.get(minute, 0.0) + op
                win_cnt[minute] = win_cnt.get(minute, 0) + 1
            else:
                loss_sum[minute] = loss_sum.get(minute, 0.0) + op
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
    out = _empty(mode, champ_id)
    out["n_games"] = n_games
    out["minutes"] = minutes
    # Descriptive arc-shape read of each result bucket's curve (pure, derived
    # from the minutes just computed - no extra DB read). See core.op_score_shape.
    out["arc"] = op_score_shape.summarize_curve(out)
    return out
