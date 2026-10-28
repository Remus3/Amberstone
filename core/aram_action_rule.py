"""Deterministic ARAM action verdict (Stage 1, Tier-1, no live wiring).

A pure, fail-soft encoding of the ARAM HP-band / wave-position decision
tree that the ARAM coach already documents in its user prompt, the
``=== ARAM DECISION TREE ===`` block of ``coaches/aram_coach.py``. This
is the correct-by-construction replacement surface for the ARAM per-tick
Haiku *action* verdict.

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
prompt's HP lines):

    hp_pct > 80           -> tier 0 ALL-IN  IF low_enemy_count >= 2
                             else tier 1 POKE
    60 <= hp_pct <= 80    -> tier 1 POKE
    40 <= hp_pct < 60     -> tier 2 HOLD
    30 <= hp_pct < 40     -> tier 3 DISENGAGE
    hp_pct < 30           -> tier 4 FALL BACK

Wave shift on the tier INDEX, then clamp to [0, 4] (the prompt's
WAVE POSITION lines):

    wave_pct > 65         -> index - 1  (one tier MORE aggressive)
    wave_pct < 35         -> index + 1  (one tier LESS aggressive)
    35 <= wave_pct <= 65  -> no shift
    wave_pct is None      -> no shift

What counts as a reading (s144 true-audit). A reading is an int or a
float (subclasses included), never a bool (a flag, not a measurement:
True hp read 1% and coached FALL BACK) and never a str (it used to be
float()-parsed, so " 6e1 " read 60% and "1_000" read 1000%), that is
finite and inside its band:

    hp_pct           0..150   (the producer admits hp up to 1.5x max,
                               so a transient over-max reading is full
                               HP, not junk - the same band
                               core/aram_deterministic_coach.py gates)
    wave_pct         0..100   (a percent)
    low_enemy_count  a whole number 0..5 (ARAM fields five enemies; an
                               integral float like 2.0 is a count, 2.9
                               is not - it used to truncate to 2 and
                               promote ALL-IN)

Fail-soft guards (this function NEVER raises):
    * hp_pct that is not a reading -> "HOLD" (neutral).
    * wave_pct that is not a reading -> the no-shift case.
    * low_enemy_count that is not a reading -> 0 (cannot reach the
      ALL-IN top tier without an explicit >=2 low signal).
    * A number whose conversion raises (an int past the float range, a
      subclass with a raising __float__, an object whose __class__
      raises) is not a reading. Before this
      pass int(inf) and float(10**400) raised OverflowError out of the
      function.
"""
from __future__ import annotations

# Index-ordered ladder, most -> least aggressive.
_LADDER = ("ALL-IN", "POKE", "HOLD", "DISENGAGE", "FALL BACK")

# Neutral fallback label (index 2) used when HP is unknown / unusable.
_NEUTRAL = "HOLD"


# Reading bands (see the module docstring).
_HP_PCT_MAX = 150.0
_WAVE_PCT_MAX = 100.0
_MAX_LOW_ENEMIES = 5


def _reading(value, lo: float, hi: float):
    """A finite int / float in ``lo..hi`` as a float, else None. Never raises.

    The bounds are finite, so the band check also rejects NaN (every
    comparison is False, which would silently bypass every HP band) and
    +/-inf.
    """
    try:
        # isinstance sits inside the try too: an object whose __class__
        # raises makes isinstance raise.
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        out = float(value)
    except Exception:  # noqa: BLE001 - OverflowError or a hostile __float__ / __class__
        return None
    if not lo <= out <= hi:
        return None
    return out


def _low_count(value) -> int:
    """A whole number of low enemies in ``0..5``, else 0. Never raises."""
    num = _reading(value, 0.0, float(_MAX_LOW_ENEMIES))
    if num is None or not num.is_integer():
        return 0
    return int(num)


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
    hp = _reading(hp_pct, 0.0, _HP_PCT_MAX)
    if hp is None:
        return _NEUTRAL

    # low_enemy_count gates only the >80 ALL-IN promotion. Anything that
    # is not a whole count in 0..5 cannot promote (defensive default 0).
    index = _base_tier(hp, _low_count(low_enemy_count))

    wave = _reading(wave_pct, 0.0, _WAVE_PCT_MAX)
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
