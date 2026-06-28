"""Deterministic ARAM action verdict (Stage 1, Tier-1, no live wiring).

A pure, fail-soft encoding of the ARAM HP-band / wave-position decision
tree that the ARAM coach already documents in its user prompt at
``coaches/aram_coach.py:251-260``. This is the correct-by-construction
replacement surface for the ARAM per-tick Haiku *action* verdict.

Rationale: the earlier ARAM laning-VERDICT precompute was measured at
23% agreement vs Haiku and is a settled dead-end. The viable path is
NOT to predict Haiku - it is to emit the operator's OWN documented rule
deterministically. This module is that rule and nothing more; a later
stage wires it into the coach.

Decision ladder, most -> least aggressive (the returned label is always
one of these canonical UPPERCASE strings):

    index 0  "ALL-IN"
    index 1  "POKE"
    index 2  "HOLD"
    index 3  "DISENGAGE"
    index 4  "FALL BACK"

Base tier from HP percent (exact, non-overlapping bands - mirrors the
prompt lines 256-260):

    hp_pct > 80           -> tier 0 ALL-IN  IF low_enemy_count >= 2
                             else tier 1 POKE
    60 <= hp_pct <= 80    -> tier 1 POKE
    40 <= hp_pct < 60     -> tier 2 HOLD
    30 <= hp_pct < 40     -> tier 3 DISENGAGE
    hp_pct < 30           -> tier 4 FALL BACK

Wave shift on the tier INDEX, then clamp to [0, 4] (prompt lines
252-255):

    wave_pct > 65         -> index - 1  (one tier MORE aggressive)
    wave_pct < 35         -> index + 1  (one tier LESS aggressive)
    35 <= wave_pct <= 65  -> no shift
    wave_pct is None      -> no shift

Fail-soft guards (this function NEVER raises):
    * hp_pct is None / non-coercible / NaN -> "HOLD" (neutral).
    * wave_pct non-coercible / NaN -> treated as the no-shift case.
    * low_enemy_count non-coercible -> treated as 0 (cannot reach the
      ALL-IN top tier without an explicit >=2 low signal).
"""
from __future__ import annotations

import math

# Index-ordered ladder, most -> least aggressive.
_LADDER = ("ALL-IN", "POKE", "HOLD", "DISENGAGE", "FALL BACK")

# Neutral fallback label (index 2) used when HP is unknown / unusable.
_NEUTRAL = "HOLD"


def _coerce_float(value):
    """Best-effort float coercion. Returns None on any failure or NaN.

    NaN is rejected because all NaN comparisons are False, which would
    silently bypass every HP band; callers must treat it as 'unknown'.
    """
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(out) or math.isinf(out):
        return None
    return out


def _base_tier(hp_pct: float, low_enemy_count: int) -> int:
    """Resolve the base ladder index from HP percent (no wave shift)."""
    if hp_pct > 80:
        return 0 if low_enemy_count >= 2 else 1
    if hp_pct >= 60:          # 60..80 inclusive
        return 1
    if hp_pct >= 40:          # 40..<60
        return 2
    if hp_pct >= 30:          # 30..<40
        return 3
    return 4                  # <30


def decide_action(hp_pct, wave_pct, low_enemy_count) -> str:
    """Return the deterministic ARAM action label for the given state.

    See the module docstring for the full band / shift / clamp contract.
    Always returns one of the five canonical UPPERCASE labels and never
    raises.
    """
    hp = _coerce_float(hp_pct)
    if hp is None:
        return _NEUTRAL

    # low_enemy_count gates only the >80 ALL-IN promotion. Anything that
    # is not a clean integer >=2 cannot promote (defensive default 0).
    try:
        low = int(low_enemy_count)
    except (TypeError, ValueError):
        low = 0

    index = _base_tier(hp, low)

    wave = _coerce_float(wave_pct)
    if wave is not None:
        if wave > 65:
            index -= 1
        elif wave < 35:
            index += 1
        # 35..65 -> no shift

    # Clamp into the valid ladder range.
    if index < 0:
        index = 0
    elif index > 4:
        index = 4

    return _LADDER[index]


__all__ = ["decide_action"]
