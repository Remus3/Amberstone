"""Detect ARAM Mayhem from a game-state snapshot or raw state dict.

Riot exposes Mayhem under several internal strings depending on the API
surface — `KIWI` from /liveclientdata, `ARAM_MAYHEM` from select LCU
endpoints, the literal `MAYHEM` if Riot ever cleans it up. This helper
is the single source of truth so individual call sites don't each
hand-roll their own substring check (and miss `KIWI`, the actual live
value, which is what aram_coach.py was doing pre-2026-05-03).

Usage:
    from core.mayhem_detect import is_mayhem
    if is_mayhem(state):
        ...

`state` may be:
  - a dict with a `game_mode` key (the canonical coach state shape)
  - any object with a `game_mode` attribute (AramSnapshot et al.)
  - a raw string (already extracted)
"""
from __future__ import annotations

from typing import Any

_MAYHEM_TOKENS = ("KIWI", "MAYHEM", "ARAM_MAYHEM")


def _coerce_string(state: Any) -> str:
    if state is None:
        return ""
    if isinstance(state, str):
        return state
    if isinstance(state, dict):
        return str(state.get("game_mode") or state.get("gameMode") or "")
    gm = getattr(state, "game_mode", None)
    if gm is None:
        gm = getattr(state, "gameMode", None)
    return str(gm or "")


def is_mayhem(state: Any) -> bool:
    """Return True if `state`'s game_mode field is one of the known
    Mayhem aliases. Safe on None / missing field — returns False."""
    gm = _coerce_string(state).upper()
    if not gm:
        return False
    return any(tok in gm for tok in _MAYHEM_TOKENS)
