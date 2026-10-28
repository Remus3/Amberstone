"""Deterministic Arena action verdict (Stage 1, Tier-1, no live wiring).

The Arena mirror of ``core.aram_action_rule``: a pure, fail-soft
encoding of the HP-band decision tree the Arena coach already documents
in its own Haiku prompt (``coaches/arena_coach.py`` ``_SYSTEM_PROMPT``:
the ``=== ARENA PRIORITY DECISION TREE ===`` block, the
``=== CAMP PHASE ===`` block and the OUTPUT FORMAT ``Action:`` label
vocabulary). As with ARAM, the viable path is NOT to predict Haiku - it
is to emit the operator's OWN documented rule deterministically. This
module is that rule and nothing more; a later stage wires it into the
coach.

Rule order (first match wins; the returned label is always one of the
prompt's canonical UPPERCASE strings):

    1. camp_phase is True   -> "BUY ITEMS"    (between rounds the only
                               correct action is the shop/campfire,
                               regardless of HP - even at 5%)
    2. hp_pct < 25          -> "KITE BACK"    (prompt: NEVER all-in
                               below 25; survive to next camp phase)
    3. hp_pct > 70 and
       low_opp_count >= 1   -> "ALL IN"       (dormant: no live low-
                               opponent-HP source exists today, so
                               callers pass None - the same shape as
                               ARAM's low_enemy_count gate)
    4. hp_pct > 70          -> "PLAY AGGRO"
    5. else (25..70 incl.)  -> "FIGHT SMART"  (strict < / > comparisons
                               put both band edges here)

What counts as a reading (s144 true-audit; the same gate as
core/aram_action_rule.py and core/arena_deterministic_coach.py). A
reading is an int or a float (subclasses included), never a bool (a
flag, not a measurement: True hp read 1% and coached KITE BACK) and
never a str (it used to be float()-parsed, so " 9e1 " read 90%), that
is finite and inside its band:

    hp_pct         0..150   (the producer admits hp up to 1.5x max, so
                             a transient over-max reading is full HP,
                             not junk; -50 used to read KITE BACK and
                             1e300 PLAY AGGRO)
    low_opp_count  a whole number 0..14 (Arena fields eight teams of
                             two; an integral float like 2.0 is a
                             count, 1.5 is not; 10**400 used to promote
                             ALL IN)
    camp_phase     a signal only as the bool True (the arena vision
                             schema writes a bool; a NaN, "false" or [0]
                             used to be truthy and route BUY ITEMS)

Fail-soft guards (this function NEVER raises):
    * hp_pct that is not a reading -> "FIGHT SMART" (neutral, the Arena
      mirror of ARAM's HOLD default).
    * camp_phase that is not True -> not in camp (it is never called,
      so a raising __bool__ cannot raise).
    * low_opp_count that is not a reading -> 0 (the ALL IN promotion
      needs an explicit >=1 whole-number signal).
    * A value whose conversion raises (an int past the float range, a
      subclass with a raising __float__, an object whose __class__
      raises inside isinstance) is not a reading. Before this pass a
      hostile __class__ on low_opp_count raised out of the function.
"""
from __future__ import annotations

# Neutral fallback label used when HP is unknown / unusable and the mid
# band; the safest standing order in a 2v2v2v2 round.
_NEUTRAL = "FIGHT SMART"

# Reading bands (see the module docstring).
_HP_PCT_MAX = 150.0
_MAX_LOW_OPPONENTS = 14


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
    """A whole number of low opponents in ``0..14``, else 0. Never raises."""
    num = _reading(value, 0.0, float(_MAX_LOW_OPPONENTS))
    if num is None or not num.is_integer():
        return 0
    return int(num)


def decide_action(hp_pct, camp_phase, low_opp_count) -> str:
    """Return the deterministic Arena action label for the given state.

    See the module docstring for the full rule-order contract. Always
    returns one of the five canonical UPPERCASE labels and never raises.
    """
    # Camp phase wins outright: between rounds there is nothing to fight,
    # so the shop verdict beats any HP band. Only the bool True is a
    # signal; an identity test never calls a hostile __bool__ / __eq__.
    if camp_phase is True:
        return "BUY ITEMS"

    hp = _reading(hp_pct, 0.0, _HP_PCT_MAX)
    if hp is None:
        return _NEUTRAL

    if hp < 25:
        return "KITE BACK"
    if hp > 70:
        # ALL IN needs an explicit low-HP-opponent count, so the
        # promotion stays dormant until a real opponent-HP source exists.
        if _low_count(low_opp_count) >= 1:
            return "ALL IN"
        return "PLAY AGGRO"
    return _NEUTRAL  # 25..70 inclusive band


__all__ = ["decide_action"]
