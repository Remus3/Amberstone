"""One resolved win-rate helper for every personal-WR builder (RM-610).

Directive X-10, external reference A (behaviour re-implemented here, no
code taken). Before this module each builder picked its own denominator:
total games, decided games, or decided games including remakes, so the
same history could read 25, 33 or 50 percent depending on the view.

A game is RESOLVED, and enters the denominator, only when:

  * its result is known - a boolean win for the tracked player, and,
    when the row carries a ``winner_count``, exactly one winning team;
  * it is NOT a remake - shorter than
    ``core.corpus_hygiene.REMAKE_MAX_SECONDS`` (our measured 300 s
    cutoff, reused rather than re-declared) or flagged by Match-V5's
    ``gameEndedInEarlySurrender``;
  * it is NOT draft-only or result-inferred (``draft_only`` /
    ``result_inferred`` truthy). No RC store sets these flags today
    (probe 2026-10-04: zero hits); they are honoured so a future source
    cannot leak guessed results into the denominator.

Win percent = wins / resolved. With zero resolved games the display is
the operator-approved ``"-"`` sentinel, never 0 percent or NaN.

Unresolved rows are NOT dropped from lists by this helper - callers keep
listing them and badge them via :func:`classify`.
"""
from __future__ import annotations

import math
import re
import sqlite3
from typing import Any, Iterable

from core.corpus_hygiene import REMAKE_MAX_SECONDS

SENTINEL = "-"

_WIN_KEYS = ("win", "tracked_win")
_DURATION_KEYS = ("game_duration_s", "gameDuration", "duration_s",
                  "duration_sec")
_EARLY_SURRENDER_KEYS = ("game_ended_in_early_surrender",
                         "gameEndedInEarlySurrender")
_UNRESOLVED_FLAG_KEYS = ("draft_only", "result_inferred")
_WINNER_COUNT_KEY = "winner_count"

_WIN_STRINGS = {"win": True, "true": True, "1": True,
                "loss": False, "fail": False, "lose": False,
                "false": False, "0": False}

# Only these spellings CLEAR a flag. Any other truthy value - including
# junk such as "maybe" or NaN - keeps the game out of the denominator
# (fail closed), so a malformed source can only shrink the sample, never
# leak a guessed or remade game into it (RM-1920).
_FLAG_FALSE_STRINGS = frozenset({"", "0", "false", "no", "n", "off"})

# A SQL identifier; resolution_select interpolates the alias (RM-1924).
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


def _get(row: Any, key: str) -> Any:
    """Read *key* from a dict or sqlite3.Row; missing -> None."""
    if isinstance(row, dict):
        return row.get(key)
    try:
        # sqlite3.Row: `key in row` tests the VALUES, so the column names
        # must be asked for explicitly (SIM118 does not apply here).
        names = row.keys()
        if key in names:
            return row[key]
    except (AttributeError, TypeError):
        pass
    return None


def _first(row: Any, keys: tuple[str, ...]) -> Any:
    for k in keys:
        v = _get(row, k)
        if v is not None:
            return v
    return None


def _finite_number(value: Any) -> float | None:
    """*value* as a finite float, or None. Bools are not numbers here."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            number = float(value)
        except OverflowError:
            return None
    elif isinstance(value, str):
        try:
            number = float(value.strip())
        except ValueError:
            return None
    else:
        return None
    return number if math.isfinite(number) else None


def _as_int(value: Any) -> int | None:
    """An integral finite number (1, 1.0, "1") as int; else None."""
    number = _finite_number(value)
    if number is None or not number.is_integer():
        return None
    return int(number)


def _as_win(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return _WIN_STRINGS.get(value.strip().lower())
    return {1: True, 0: False}.get(_as_int(value))


def _first_win(row: Any) -> bool | None:
    """The first win key whose value PARSES (RM-1921): a junk ``win``
    no longer hides a valid ``tracked_win``."""
    for k in _WIN_KEYS:
        win = _as_win(_get(row, k))
        if win is not None:
            return win
    return None


def _flag_set(value: Any) -> bool:
    """True unless *value* is missing or an explicit false (RM-1920)."""
    if value is None or value is False:
        return False
    if isinstance(value, str) and value.strip().lower() in _FLAG_FALSE_STRINGS:
        return False
    number = _finite_number(value)
    if number is not None:
        return number != 0
    # True, NaN, inf or any other type: not an explicit false.
    return True


def _duration_s(row: Any) -> int:
    """The first KNOWN duration in seconds, or 0 for unknown.

    Unknown = missing, zero, negative, bool, non-finite or unparseable
    (RM-1917 / RM-1918); an unknown value under one key does not
    hide a real value under a later key (RM-1919).
    """
    for k in _DURATION_KEYS:
        number = _finite_number(_get(row, k))
        # Under one whole second truncates to 0 = unknown, so it must not
        # hide a later key either.
        if number is not None and number >= 1:
            return int(number)
    return 0


def is_remake(row: Any) -> bool:
    if any(_flag_set(_get(row, k)) for k in _EARLY_SURRENDER_KEYS):
        return True
    duration = _duration_s(row)
    # Unknown duration (0) is not a remake - same rule as
    # corpus_hygiene.judge.
    return bool(duration) and duration < REMAKE_MAX_SECONDS


def classify(row: Any) -> str:
    """'win' | 'loss' | 'remake' | 'unknown' for one game row."""
    if is_remake(row):
        return "remake"
    if any(_flag_set(_get(row, k)) for k in _UNRESOLVED_FLAG_KEYS):
        return "unknown"
    winners = _get(row, _WINNER_COUNT_KEY)
    # RM-1922: "1" / 1.0 count as one winner; a bool or junk count
    # is not a count, so the result is unknown.
    if winners is not None and _as_int(winners) != 1:
        return "unknown"
    win = _first_win(row)
    if win is None:
        return "unknown"
    return "win" if win else "loss"


def wr_pct(wins: int, resolved: int, ndigits: int | None = 1):
    """Numeric percent rounded to *ndigits*, or None when resolved == 0.

    None also for counts that cannot be a record (RM-1923): a bool,
    a non-integral or non-finite number, a negative count or more wins
    than resolved games. The display then reads the ``"-"`` sentinel
    instead of raising or showing an impossible percent.
    """
    if isinstance(wins, bool) or isinstance(resolved, bool):
        return None
    w = _as_int(wins) if isinstance(wins, (int, float)) else None
    n = _as_int(resolved) if isinstance(resolved, (int, float)) else None
    if w is None or n is None or n <= 0 or w < 0 or w > n:
        return None
    pct = 100.0 * w / n
    if ndigits == 0:
        return round(pct)
    return round(pct, ndigits) if ndigits is not None else pct


def display_pct(wins: int, resolved: int) -> str:
    pct = wr_pct(wins, resolved, 0)
    return SENTINEL if pct is None else f"{pct}%"


def resolved_wr(rows: Iterable[Any]) -> tuple[int, int, str]:
    """(wins, resolved, display) over *rows*."""
    wins = resolved = 0
    for row in rows:
        kind = classify(row)
        if kind == "win":
            wins += 1
            resolved += 1
        elif kind == "loss":
            resolved += 1
    return wins, resolved, display_pct(wins, resolved)


def _cols(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    except sqlite3.Error:
        return set()


def resolution_select(conn: sqlite3.Connection, matches_alias: str) -> str:
    """Extra SELECT-list fragment (leading comma, or '') that pulls the
    remake signals out of a rewind_history.db-shaped schema.

    Column-tolerant: an older or minimal DB without
    ``matches.game_duration_s`` / ``participants.game_ended_in_early_surrender``
    simply contributes nothing, and the row is judged on its result only.
    The early-surrender flag is game-wide in Match-V5, so MAX over the
    match's participants is the game's value.

    *matches_alias* is interpolated into SQL, so anything but a plain
    identifier raises ValueError (RM-1924).
    """
    if not isinstance(matches_alias, str) or not _IDENT_RE.match(
            matches_alias):
        raise ValueError(f"matches_alias must be a SQL identifier,"
                         f" got {matches_alias!r}")
    frag = ""
    if "game_duration_s" in _cols(conn, "matches"):
        frag += f", {matches_alias}.game_duration_s AS game_duration_s"
    if "game_ended_in_early_surrender" in _cols(conn, "participants"):
        frag += (", (SELECT MAX(px.game_ended_in_early_surrender)"
                 " FROM participants px"
                 f" WHERE px.match_id = {matches_alias}.match_id)"
                 " AS game_ended_in_early_surrender")
    return frag
