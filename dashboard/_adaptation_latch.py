# arch: cs/csd latch for STATS panel | section=dashboard | frozen=no
"""dashboard/_adaptation_latch.py - time-latched CS metrics for the STATS view.

Produces two keys consumed by the STATS panel (web/js/panels/right_now.js
`renderStats(p)`):

  cs_at_10  - active player creep score latched at the FIRST observation
              where game_time_s >= 600 (10:00). Valid for all modes
              (SR / ARAM / Arena). Once latched for a game it never changes.

  csd_at_15 - CS-differential vs the lane opponent at 15:00, SR ONLY.
              Latched at the first observation where game_time_s >= 900.
              Requires the summary's ``players`` list (see _liveclient.py)
              to have exactly one is_active player AND exactly one enemy
              with the same position. If position or team is blank, or the
              opponent is missing or ambiguous, the key is omitted entirely
              so the frontend renders "-" (the default empty-field
              behaviour).

INPUT VOCABULARY (s144 true-audit). A count (cs, creep_score) is an int that
is not a bool, a finite integral float or a str of ASCII digits, in
0.._MAX_CS. The clock is the same but a finite float is floored, in
0.._MAX_GAME_S (dashboard/_liveclient._MAX_GAME_S). Anything else is no
reading: the tick returns {} and leaves the latch untouched. A clock of 0 is
also no reading - the producer reads a missing or out-of-range gameTime as 0,
and nothing latches at 0 - so one junk tick can never pose as the time
regression that resets the latch (it used to, and the next tick re-latched
cs_at_10 at the current, late clock). game_id is a str (stripped, at most
_MAX_GAME_ID chars) or an int that is not a bool; anything else is "".

MODULE STATE:
  - One latch for the current game. Replaced on a new game_id or a time
    regression of a READABLE clock (a new game or a reconnect).
  - Thread-safe: all reads/writes under _lock (same pattern as
    core/ward_events.py).

compute(summary) is the public entry point; it is called unwrapped by
_state_builder.build_state() every /api/state tick, so it never raises.
"""
from __future__ import annotations

import math
import threading
from typing import Any

# Bounds. _MAX_GAME_S matches dashboard/_liveclient._MAX_GAME_S; a creep score
# past _MAX_CS is not a real game.
_MAX_GAME_S = 10 ** 6
_MAX_CS = 10 ** 5
_MAX_DIGITS = 20
_MAX_GAME_ID = 64
_MAX_LABEL = 32

_CS_AT_10_S = 600
_CSD_AT_15_S = 900

# ---------------------------------------------------------------------------
# Module state
# ---------------------------------------------------------------------------

_lock = threading.Lock()

# Latch values and bookkeeping for the current game.
# Reset on new game_id or time regression.
_game_id: str | None = None
_prev_time_s: int = 0
_cs_at_10: int | None = None
_csd_at_15: int | None = None  # None means "not yet latched or unresolvable"


def reset() -> None:
    """Clear all latch state. Test helper; also safe to call between games."""
    global _game_id, _prev_time_s, _cs_at_10, _csd_at_15
    with _lock:
        _game_id = None
        _prev_time_s = 0
        _cs_at_10 = None
        _csd_at_15 = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _bounded_int(v: Any, limit: int, *, floor_floats: bool) -> int | None:
    """A non-negative int in 0..limit, else None. Never raises.

    Accepts an int that is not a bool, a finite float (integral only unless
    ``floor_floats``) and a str of 1.._MAX_DIGITS ASCII digits. A bool, a
    NaN / inf, a fractional count, "7_8" / "+7" / " 7" and any container is
    None."""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        n = v
    elif isinstance(v, float):
        if not math.isfinite(v) or v < 0:
            return None
        if not floor_floats and not v.is_integer():
            return None
        if v > limit:
            return None
        n = int(v)
    elif isinstance(v, str):
        if not (0 < len(v) <= _MAX_DIGITS and v.isascii() and v.isdigit()):
            return None
        n = int(v)
    else:
        return None
    return n if 0 <= n <= limit else None


def _count(v: Any) -> int | None:
    return _bounded_int(v, _MAX_CS, floor_floats=False)


def _clock(v: Any) -> int | None:
    return _bounded_int(v, _MAX_GAME_S, floor_floats=True)


def _label(v: Any) -> str:
    """A stripped, non-blank str of at most _MAX_LABEL chars, else ''."""
    if not isinstance(v, str):
        return ""
    s = v.strip()
    return s if len(s) <= _MAX_LABEL else ""


def _game_key(v: Any) -> str:
    """The game_id as a key: a stripped str or a positive non-bool int of at
    most _MAX_DIGITS digits, else '' (the missing id)."""
    if isinstance(v, bool):
        return ""
    if isinstance(v, int):
        return str(v) if 0 < v < 10 ** _MAX_DIGITS else ""
    if isinstance(v, str):
        s = v.strip()
        return s if len(s) <= _MAX_GAME_ID else ""
    return ""


def _active_row(players: Any) -> dict | None:
    """The single row whose is_active is JSON true, else None (none or two)."""
    if not isinstance(players, list):
        return None
    rows = [p for p in players
            if isinstance(p, dict) and p.get("is_active") is True]
    return rows[0] if len(rows) == 1 else None


def _find_opponent_cs(players: Any, active_position: str) -> int | None:
    """Return the creep_score of the one enemy with matching position.

    Returns None when the position is blank, the list is malformed, the
    active player or its team is unresolvable, the opponent is missing (e.g.
    ARAM has no position labels) or ambiguous, or its creep_score is not a
    count (see _count). A row with a blank or non-str team is no enemy.
    """
    active_pos = _label(active_position)
    if not active_pos:
        return None
    me = _active_row(players)
    if me is None:
        return None
    my_team = _label(me.get("team"))
    if not my_team:
        return None
    opponents = [
        p for p in players
        if isinstance(p, dict)
        and p.get("is_active") is not True
        and _label(p.get("team")) not in ("", my_team)
        and _label(p.get("position")) == active_pos
    ]
    if len(opponents) != 1:
        return None
    # Cycle-8 audit (slice B), s144 true-audit: a malformed creep_score must
    # not raise - compute() promises no-raise and is called unwrapped on the
    # /api/state hot path (_state_builder.py). Unresolvable -> None, key
    # omitted.
    return _count(opponents[0].get("creep_score"))


def _get_active_position(players: Any) -> str:
    """Return the position of the single is_active player, or '' if absent."""
    me = _active_row(players)
    return _label(me.get("position")) if me is not None else ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute(summary: Any) -> dict:
    """Derive latched adaptation metrics from a liveclient_summary dict.

    Reads the module latch state, updates it on threshold crossings, and
    returns only the currently-latched keys. Before any threshold is crossed
    returns {}. Malformed / missing input, a junk count and a junk or zero
    clock return {} without raising and without touching the latch.

    Keys returned when available:
      "cs_at_10"  : int  (all modes, game_time_s >= 600)
      "csd_at_15" : int  (SR only, game_time_s >= 900, signed diff)
    """
    global _game_id, _prev_time_s, _cs_at_10, _csd_at_15

    if not isinstance(summary, dict):
        return {}

    game_time_s = _clock(summary.get("game_time_s"))
    if game_time_s is None:
        return {}
    cs = _count(summary.get("cs"))
    if cs is None:
        return {}

    game_id = _game_key(summary.get("game_id"))
    players = summary.get("players")  # may be absent (ARAM, pre-extension)

    with _lock:
        # A new game_id resets the latch on any tick.
        if game_id != _game_id:
            _game_id = game_id
            _prev_time_s = 0
            _cs_at_10 = None
            _csd_at_15 = None

        # A zero clock is the producer's missing value: nothing can latch at
        # 0, and treating it as a regression would erase a true latch.
        if game_time_s == 0:
            return {}

        # A readable clock running backwards means a reconnect or a game
        # restart (the only new-game signal when game_id is "").
        if game_time_s < _prev_time_s:
            _cs_at_10 = None
            _csd_at_15 = None
        _prev_time_s = game_time_s

        # Latch cs_at_10 on first observation >= 600s.
        if _cs_at_10 is None and game_time_s >= _CS_AT_10_S:
            _cs_at_10 = cs

        # Latch csd_at_15 on first observation >= 900s (SR only via players).
        if _csd_at_15 is None and game_time_s >= _CSD_AT_15_S:
            active_pos = _get_active_position(players)
            if active_pos:
                opp_cs = _find_opponent_cs(players, active_pos)
                if opp_cs is not None:
                    _csd_at_15 = cs - opp_cs

        # Build result from whatever is currently latched.
        out: dict = {}
        if _cs_at_10 is not None:
            out["cs_at_10"] = _cs_at_10
        if _csd_at_15 is not None:
            out["csd_at_15"] = _csd_at_15

    return out
