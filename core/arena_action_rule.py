"""Deterministic Arena action verdict (Stage 1, Tier-1, no live wiring).

The Arena mirror of ``core.aram_action_rule``: a pure, fail-soft
encoding of the HP-band decision tree the Arena coach already documents
in its own Haiku prompt (``coaches/arena_coach.py:137-142`` priority
tree, ``151-156`` camp phase, ``168`` Action label vocabulary). As with
ARAM, the viable path is NOT to predict Haiku - it is to emit the
operator's OWN documented rule deterministically. This module is that
rule and nothing more; a later stage wires it into the coach.

Rule order (first match wins; the returned label is always one of the
prompt's canonical UPPERCASE strings):

    1. camp_phase truthy    -> "BUY ITEMS"    (between rounds the only
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

Fail-soft guards (this function NEVER raises):
    * hp_pct None / non-coercible / NaN / inf -> "FIGHT SMART" (neutral,
      the Arena mirror of ARAM's HOLD default).
    * camp_phase whose truthiness itself raises -> treated as falsy.
    * low_opp_count anything but a clean int -> treated as 0 (a float
      like 1.5 is not a count; the ALL IN promotion needs an explicit
      >=1 integer signal).
"""
from __future__ import annotations

import math

# Neutral fallback label used when HP is unknown / unusable and the mid
# band; the safest standing order in a 2v2v2v2 round.
_NEUTRAL = "FIGHT SMART"


def _coerce_float(value):
    """Best-effort float coercion. Returns None on any failure or NaN/inf.

    NaN is rejected because all NaN comparisons are False, which would
    silently bypass every HP band; callers must treat it as 'unknown'.
    """
    if value is None:
        return None
    try:
        out = float(value)
    except Exception:  # noqa: BLE001 - a raising __float__ is still 'unknown'
        return None
    if math.isnan(out) or math.isinf(out):
        return None
    return out


def decide_action(hp_pct, camp_phase, low_opp_count) -> str:
    """Return the deterministic Arena action label for the given state.

    See the module docstring for the full rule-order contract. Always
    returns one of the five canonical UPPERCASE labels and never raises.
    """
    # Camp phase wins outright: between rounds there is nothing to fight,
    # so the shop verdict beats any HP band. A camp_phase whose __bool__
    # itself raises is treated as falsy (fail-soft, not a signal).
    try:
        in_camp = bool(camp_phase)
    except Exception:  # noqa: BLE001 - hard fail-soft contract
        in_camp = False
    if in_camp:
        return "BUY ITEMS"

    hp = _coerce_float(hp_pct)
    if hp is None:
        return _NEUTRAL

    if hp < 25:
        return "KITE BACK"
    if hp > 70:
        # ALL IN needs an explicit low-HP-opponent count. Only a clean
        # int qualifies: bool is excluded (True is not a count) and a
        # float like 1.5 is garbage, so the promotion stays dormant
        # until a real opponent-HP source exists.
        if isinstance(low_opp_count, int) and not isinstance(low_opp_count, bool):
            low = low_opp_count
        else:
            low = 0
        if low >= 1:
            return "ALL IN"
        return "PLAY AGGRO"
    return _NEUTRAL  # 25..70 inclusive band


__all__ = ["decide_action"]
