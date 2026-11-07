"""Detect ARAM Mayhem from a game-state snapshot or raw state dict.

Riot exposes Mayhem under several internal strings depending on the API
surface - `KIWI` from /liveclientdata, `ARAM_MAYHEM` from select LCU
endpoints, the literal `MAYHEM` if Riot ever cleans it up. This helper
is the single source of truth so individual call sites don't each
hand-roll their own substring check (and miss `KIWI`, the actual live
value, which is what aram_coach.py was doing pre-2026-05-03).

Usage:
    from core.mayhem_detect import is_mayhem
    if is_mayhem(state):
        ...

`state` may be:
  - a mapping with a `game_mode` (or Riot's `gameMode`) key - the
    canonical coach state shape
  - any object with a `game_mode` / `gameMode` attribute (AramSnapshot
    et al.)
  - a raw string (already extracted)

Contract (pinned by tests/test_mayhem_detect.py):
  - The first NON-EMPTY STRING among `game_mode`, `gameMode` is the mode;
    a non-string value (list, bytes, dict, number) is skipped, never
    str()-ed, so `["KIWI"]` or `b"KIWI"` cannot read as Mayhem.
  - The mode must be 7-bit ASCII and at most `_MAX_MODE_LEN` characters:
    Riot game_mode values are short ASCII identifiers, so a lookalike
    (dotless i upper-cases to `I`) or a long payload is not Mayhem.
  - A str subclass is read as its exact-str value, so overriding
    `upper` / `split` cannot forge a match.
  - The alias must be a WHOLE TOKEN (letters split on anything else):
    `KIWI`, `KIWI_JADE`, `ARAM_MAYHEM` match; `KIWIFRUIT`, `NOTMAYHEM`
    do not.
  - It never raises: a raising accessor reads as "no mode" (False).
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

# Known Mayhem aliases, each matched as a whole token. ARAM_MAYHEM needs no
# entry of its own: it tokenizes to ARAM + MAYHEM.
_MAYHEM_TOKENS = frozenset({"KIWI", "MAYHEM"})

# Riot game_mode values are short identifiers (CLASSIC, KIWI, CHERRY,
# ARAM_UNRANKED_5X5 at 17 chars). Anything longer is not a mode name and is
# refused without a scan.
_MAX_MODE_LEN = 64

# Field names read off a mapping or object, in priority order.
_MODE_KEYS = ("game_mode", "gameMode")

_NON_LETTERS = re.compile(r"[^A-Z]+")


def _mode_value(state: Any) -> str:
    """The first non-empty string mode field of `state`, else "".

    Never raises: a raising `get` / property / `__getattr__` reads as no
    mode, because every caller treats a missing mode as "not Mayhem".
    """
    if state is None:
        return ""
    if _is_str(state):
        return state
    for key in _MODE_KEYS:
        try:
            if isinstance(state, Mapping):
                value = state.get(key)
            else:
                value = getattr(state, key, None)
        except Exception:  # noqa: BLE001 - fail-soft contract: a raising accessor is no mode
            return ""
        if _is_str(value) and str.__len__(value):
            return value
    return ""


def _is_str(value: Any) -> bool:
    # type(), not isinstance(): isinstance falls back to the instance's own
    # __class__ attribute, which can raise or claim to be str, and a value
    # that only CLAIMS to be str would make str.__str__ raise TypeError.
    return issubclass(type(value), str)


def _coerce_string(state: Any) -> str:
    """The upper-cased mode string, or "" when it is not a plausible mode."""
    # str.__str__ yields the exact-str value even for a subclass, so no
    # override of len / upper / split below can redirect the result.
    gm = str.__str__(_mode_value(state))
    if len(gm) > _MAX_MODE_LEN or not gm.isascii():
        return ""
    return gm.upper()


def is_mayhem(state: Any) -> bool:
    """Return True if `state`'s game_mode field is one of the known
    Mayhem aliases (whole-token, case-insensitive). Safe on None, a
    missing or non-string field and a raising accessor - returns False."""
    gm = _coerce_string(state)
    if not gm:
        return False
    return any(tok in _MAYHEM_TOKENS for tok in _NON_LETTERS.split(gm))
