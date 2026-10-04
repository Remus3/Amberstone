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


def _get(row: Any, key: str) -> Any:
    """Read *key* from a dict or sqlite3.Row; missing -> None."""
    if isinstance(row, dict):
        return row.get(key)
    try:
        if key in row.keys():
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


def _as_win(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return {1: True, 0: False}.get(value)
    if isinstance(value, str):
        return _WIN_STRINGS.get(value.strip().lower())
    return None


def is_remake(row: Any) -> bool:
    if _first(row, _EARLY_SURRENDER_KEYS):
        return True
    try:
        duration = int(_first(row, _DURATION_KEYS) or 0)
    except (TypeError, ValueError):
        duration = 0
    # Unknown duration (0) is not a remake - same rule as
    # corpus_hygiene.judge.
    return bool(duration) and duration < REMAKE_MAX_SECONDS


def classify(row: Any) -> str:
    """'win' | 'loss' | 'remake' | 'unknown' for one game row."""
    if is_remake(row):
        return "remake"
    if any(_get(row, k) for k in _UNRESOLVED_FLAG_KEYS):
        return "unknown"
    winners = _get(row, _WINNER_COUNT_KEY)
    if winners is not None and winners != 1:
        return "unknown"
    win = _as_win(_first(row, _WIN_KEYS))
    if win is None:
        return "unknown"
    return "win" if win else "loss"


def wr_pct(wins: int, resolved: int, ndigits: int | None = 1):
    """Numeric percent rounded to *ndigits*, or None when resolved == 0."""
    if not resolved:
        return None
    pct = 100.0 * wins / resolved
    if ndigits == 0:
        return int(round(pct))
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
    """
    frag = ""
    if "game_duration_s" in _cols(conn, "matches"):
        frag += f", {matches_alias}.game_duration_s AS game_duration_s"
    if "game_ended_in_early_surrender" in _cols(conn, "participants"):
        frag += (", (SELECT MAX(px.game_ended_in_early_surrender)"
                 " FROM participants px"
                 f" WHERE px.match_id = {matches_alias}.match_id)"
                 " AS game_ended_in_early_surrender")
    return frag
