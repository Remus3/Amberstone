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
              to have both an is_active player AND a same-position enemy.
              If position is blank or no opponent is found the key is
              omitted entirely so the frontend renders "-" (the default
              empty-field behaviour).

MODULE STATE:
  - One _LatchState per game_id, keyed under _state. Replaced on new
    game_id or time regression (which signals a new game or a reconnect).
  - Thread-safe: all reads/writes under _lock (same pattern as
    core/ward_events.py).

compute(summary) is the public entry point; it is called by
_state_builder.build_state() every /api/state tick.
"""
from __future__ import annotations

import threading
from typing import Any

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

def _find_opponent_cs(players: Any, active_position: str) -> int | None:
    """Return the creep_score of the first enemy with matching position.

    Returns None when the position is blank, the list is malformed, or
    no matching opponent exists (e.g. ARAM has no position labels).
    """
    if not isinstance(players, list):
        return None
    active_pos = str(active_position or "").strip()
    if not active_pos:
        return None
    # Active player's team so we can identify the enemy side.
    my_team: str | None = None
    for p in players:
        if not isinstance(p, dict):
            continue
        if p.get("is_active"):
            my_team = p.get("team")
            break
    if my_team is None:
        return None
    for p in players:
        if not isinstance(p, dict):
            continue
        if p.get("is_active"):
            continue
        if p.get("team") == my_team:
            continue  # same team, skip
        pos = str(p.get("position") or "").strip()
        if pos == active_pos:
            # Cycle-8 audit (slice B): a malformed creep_score (None /
            # non-numeric) must not raise - compute() promises no-raise
            # and is called unwrapped on the /api/state hot path
            # (_state_builder.py). Unresolvable -> None, key omitted.
            try:
                return int(p.get("creep_score", 0))
            except (TypeError, ValueError):
                return None
    return None


def _get_active_position(players: Any) -> str:
    """Return the position string of the is_active player, or '' if absent."""
    if not isinstance(players, list):
        return ""
    for p in players:
        if isinstance(p, dict) and p.get("is_active"):
            return str(p.get("position") or "").strip()
    return ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute(summary: Any) -> dict:
    """Derive latched adaptation metrics from a liveclient_summary dict.

    Reads the module latch state, updates it on threshold crossings, and
    returns only the currently-latched keys. Before any threshold is crossed
    returns {}. Malformed / missing input returns {} without raising.

    Keys returned when available:
      "cs_at_10"  : int  (all modes, game_time_s >= 600)
      "csd_at_15" : int  (SR only, game_time_s >= 900, signed diff)
    """
    global _game_id, _prev_time_s, _cs_at_10, _csd_at_15

    if not isinstance(summary, dict):
        return {}

    # Extract required fields defensively.
    try:
        game_time_s = int(summary["game_time_s"])
    except (KeyError, TypeError, ValueError):
        return {}

    game_id: str = str(summary.get("game_id") or "")
    cs_raw = summary.get("cs")
    if cs_raw is None:
        return {}
    try:
        cs = int(cs_raw)
    except (TypeError, ValueError):
        return {}

    players = summary.get("players")  # may be absent (ARAM, pre-extension)

    with _lock:
        # Detect game change or time regression - reset latch for the new
        # game. Time regression means a reconnect or game restart.
        if game_id != _game_id or game_time_s < _prev_time_s:
            _game_id = game_id
            _prev_time_s = game_time_s
            _cs_at_10 = None
            _csd_at_15 = None

        _prev_time_s = game_time_s

        # Latch cs_at_10 on first observation >= 600s.
        if _cs_at_10 is None and game_time_s >= 600:
            _cs_at_10 = cs

        # Latch csd_at_15 on first observation >= 900s (SR only via players).
        if _csd_at_15 is None and game_time_s >= 900:
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
