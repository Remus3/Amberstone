# arch: pure game-math core (resists, growth, display rounding, freshness) pinned by external goldens | section=core | frozen=no
"""Pure game-math core: inputs in, numbers out, no I/O (P1-5).

Every formula here is pinned by EXTERNAL golden cases in
``tests/golden/game_math_cases.json`` (League wiki worked examples at a pinned
revision, Python / MDN documented examples for rounding). The same golden file
also checks the older copies of these formulas inside the DS engine
(``agents/daemon_slayer``) and the JavaScript built-ins the dashboards round
with, so a drift between any two of them is a red test, not a surprise.

Rounding is explicit. Internal math stays in float; DISPLAY rounding is a
separate, named step, because the game displays numbers rounded in specific
ways (HUD health rounds up; the attack-speed panel shows two decimals and its
tooltip three) and because Python's ``round`` (ties to even, on the binary
value) and JavaScript's ``Math.round`` (ties toward +infinity) and
``toFixed`` (ties up, on the binary value) disagree exactly at the ties.

``freshness`` answers whether a live observation is still current before it is
used. It fails CLOSED: an unknown or implausibly-future timestamp is never
fresh.
"""
from __future__ import annotations

import decimal
import math
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Iterable, Optional

__all__ = [
    "Freshness",
    "attack_speed",
    "average_crit_multiplier",
    "combine_percent",
    "damage_multiplier",
    "damage_reduction_fraction",
    "effective_health",
    "effective_resist",
    "freshness",
    "growth_multiplier",
    "growth_step_fraction",
    "hud_health",
    "js_math_round",
    "post_mitigation_damage",
    "reduction_damage_gain",
    "resist_with_multipliers",
    "round_half_even",
    "stat_at_level",
    "to_fixed",
]


# --------------------------------------------------------------------------
# Resists


def damage_multiplier(resist: float) -> float:
    """Post-mitigation damage multiplier for a resist value (armor or MR).

    ``100 / (100 + R)`` for ``R >= 0``; ``2 - 100 / (100 - R)`` below zero.
    """
    if resist >= 0:
        return 100.0 / (100.0 + resist)
    return 2.0 - 100.0 / (100.0 - resist)


def post_mitigation_damage(raw: float, resist: float) -> float:
    return raw * damage_multiplier(resist)


def damage_reduction_fraction(resist: float) -> float:
    return 1.0 - damage_multiplier(resist)


def effective_health(health: float, resist: float) -> float:
    """Raw damage of one type needed to remove ``health`` through ``resist``."""
    return health / damage_multiplier(resist)


def combine_percent(fractions: Iterable[float]) -> float:
    """Several percent reductions / penetrations stack multiplicatively."""
    keep = 1.0
    for f in fractions:
        keep *= 1.0 - f
    return 1.0 - keep


def reduction_damage_gain(resist: float, pct_reduction: float) -> float:
    """Fractional extra damage a percent resist reduction yields against ``resist``."""
    return damage_multiplier(resist * (1.0 - pct_reduction)) / damage_multiplier(resist) - 1.0


def effective_resist(
    base: float,
    bonus: float = 0.0,
    *,
    flat_reduction: float = 0.0,
    pct_reductions: Iterable[float] = (),
    pct_pens: Iterable[float] = (),
    bonus_pct_pens: Iterable[float] = (),
    flat_pen: float = 0.0,
) -> float:
    """Resist the damage is computed against, in the game's fixed order.

    1. flat reduction, split between base and bonus in proportion to each;
       it CAN take the resist below zero;
    2. percent reduction (stacking multiplicatively);
    3. percent penetration on the whole resist, bonus-only percent
       penetration on the bonus part;
    4. flat penetration (lethality / flat magic pen), which cannot take the
       resist below zero.

    Once the resist is zero or below after step 1, steps 2-4 are skipped:
    percent effects and penetration do nothing to a non-positive resist.
    """
    base = float(base)
    bonus = float(bonus)
    if flat_reduction:
        total = base + bonus
        if total > 0:
            base -= flat_reduction * base / total
            bonus -= flat_reduction * bonus / total
        else:
            base -= flat_reduction
    if base + bonus <= 0:
        return base + bonus
    keep = 1.0 - combine_percent(pct_reductions)
    base *= keep
    bonus *= keep
    pen_keep = 1.0 - combine_percent(pct_pens)
    bonus_keep = 1.0 - combine_percent(bonus_pct_pens)
    treated = base * pen_keep + bonus * bonus_keep * pen_keep
    return max(0.0, treated - flat_pen)


def resist_with_multipliers(
    base: float,
    bonus: float,
    bonus_multipliers: Iterable[float] = (),
    total_multipliers: Iterable[float] = (),
) -> float:
    """``(base + bonus * (1 + sum(bonus mult))) * prod(1 + total mult)``."""
    total_factor = 1.0
    for m in total_multipliers:
        total_factor *= 1.0 + m
    return (base + bonus * (1.0 + sum(bonus_multipliers))) * total_factor


# --------------------------------------------------------------------------
# Champion statistics


def growth_multiplier(level: int) -> float:
    """``(n - 1) * (0.7025 + 0.0175 * (n - 1))``: 0 at level 1, 17 at level 18."""
    return (level - 1) * (0.7025 + 0.0175 * (level - 1))


def growth_step_fraction(level: int) -> float:
    """Fraction of the growth stat gained when reaching ``level`` (>= 2)."""
    if level < 2:
        raise ValueError("a level-up step starts at level 2")
    return 0.65 + 0.035 * level


def stat_at_level(base: float, growth: float, level: int, bonus: float = 0.0) -> float:
    return base + bonus + growth * growth_multiplier(level)


def attack_speed(base_as: float, as_ratio: float, bonus_as: float, as_growth: float, level: int) -> float:
    """``base + (bonus + growth * growth_multiplier(level)) * ratio``."""
    return base_as + (bonus_as + as_growth * growth_multiplier(level)) * as_ratio


def average_crit_multiplier(crit_chance: float, bonus_crit_damage: float = 0.0) -> float:
    return 1.0 + crit_chance * (1.0 + bonus_crit_damage)


# --------------------------------------------------------------------------
# Display rounding (explicit modes)


def round_half_even(value: float, ndigits: int = 0):
    """Python's built-in rounding: nearest, exact binary ties to even."""
    if ndigits == 0:
        return round(value)
    return round(value, ndigits)


def js_math_round(value: float) -> float:
    """JavaScript ``Math.round``: nearest integer, ties toward +infinity.

    Returns ``-0.0`` for ``-0.5 <= value < 0`` as JavaScript does.

    Exact without Decimal (s144 true-audit, RM-1602): ``value - floor(value)``
    is exact for every finite double, so the tie test needs no extended
    precision and nothing here reads the caller's thread-local decimal context
    (a lowered ``prec`` used to turn 12345.4 into 12300.0, and an ``Inexact``
    trap made it raise).
    """
    if math.isnan(value) or math.isinf(value):
        return value
    if value == 0:
        return value
    floor = math.floor(value)
    out = float(floor + 1 if value - floor >= 0.5 else floor)
    if out == 0 and value < 0:
        return -0.0
    return out


# A private decimal context for to_fixed (RM-1601 / -241). A finite result
# below 1e21 has at most 22 integer digits plus 100 fraction digits, so 200
# significant digits always hold it exactly; the ambient context (28 digits by
# default, and per-thread mutable) raised InvalidOperation on any longer
# result and let a caller's lowered precision or traps change the output.
_FIXED_CONTEXT = decimal.Context(prec=200, rounding=ROUND_HALF_UP, traps=[decimal.InvalidOperation])


def to_fixed(value: float, digits: int) -> str:
    """JavaScript ``Number.prototype.toFixed`` (ECMA-262 sec-number.prototype.tofixed).

    Works on the EXACT binary value (so 2.55 shows "2.5" and 2.35 shows
    "2.4"); an exact binary tie rounds away from zero (the larger magnitude).
    The sign is taken off first, as the spec does, so a negative value that
    rounds to zero keeps it ("-0.00"); only -0 itself prints unsigned.
    NaN / +-Infinity print as JavaScript prints them, and ``abs(value) >=
    1e21`` returns the shortest round-trip exponent form ("1e+21"), the
    spec's ``ToString(x)``. ``digits`` must be an int (not a bool) in 0..100;
    anything else is a ValueError.
    """
    if isinstance(digits, bool) or not isinstance(digits, int) or not 0 <= digits <= 100:
        raise ValueError("digits must be an int in 0..100")
    if math.isnan(value):
        return "NaN"
    if math.isinf(value):
        return "-Infinity" if value < 0 else "Infinity"
    if abs(value) >= 1e21:
        return repr(float(value))
    sign = "-" if value < 0 else ""
    with decimal.localcontext(_FIXED_CONTEXT):
        # Decimal(float) is exact whatever the precision; inside the private
        # context a caller's FloatOperation trap cannot fire on it either.
        exact = Decimal(value)
        q = Decimal((0, (1,), -digits))
        mag = exact.copy_abs().quantize(q, context=_FIXED_CONTEXT)
    return sign + format(mag, "f")


def hud_health(value: float) -> int:
    """In-game HUD health display: rounds UP (771.4 shows 772).

    ``math.ceil`` is exact on a double and reads no decimal context. A NaN or
    infinite health has no display value: ValueError (an infinite one used to
    raise OverflowError, a NaN one ValueError).
    """
    if math.isnan(value) or math.isinf(value):
        raise ValueError("hud_health needs a finite value")
    return math.ceil(value)


# --------------------------------------------------------------------------
# Freshness of live observations

#: Same-host clock jitter tolerated before a future timestamp is distrusted.
MAX_CLOCK_SKEW_S = 5.0


@dataclass(frozen=True)
class Freshness:
    fresh: bool
    #: Seconds since the observation; None when it could not be established.
    age_s: Optional[float]
    #: "fresh" | "stale" | "unknown" | "future"
    reason: str


def _finite_real(raw: Any) -> Optional[float]:
    """``raw`` as a finite float, or None.

    Total: None for a bool (``float(True)`` is 1.0, a 1970 clock), any
    non-int / non-float, NaN, +-inf and an int too large for a double (which
    used to raise OverflowError out of the helpers below, RM-1599).
    """
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    try:
        value = float(raw)
    except OverflowError:
        return None
    if math.isnan(value) or math.isinf(value):
        return None
    return value


def _coerce_ts(raw: Any) -> Optional[float]:
    value = _finite_real(raw)
    if value is None or value <= 0.0:
        return None
    return value


def _check_skew(max_skew_s: Any) -> float:
    """A usable clock-skew tolerance, or ValueError (RM-1598).

    A NaN skew made ``age < -skew`` always False and so silently disabled the
    future check (fail OPEN); an infinite one does the same on purpose and a
    negative one rejects observations from the past. All are caller
    configuration errors, refused like a bad ``max_age_s``.
    """
    skew = _finite_real(max_skew_s)
    if skew is None or skew < 0.0:
        raise ValueError("max_skew_s must be a finite number >= 0")
    return skew


def observation_age(observed_at: Any, *, now: float, max_skew_s: float = MAX_CLOCK_SKEW_S) -> Optional[float]:
    """Seconds since ``observed_at`` (unix time), or None when untrustworthy.

    None for an absent / non-numeric / non-positive / non-finite / out-of-range
    timestamp, for one further in the future than ``max_skew_s``, and for an
    unusable reference clock ``now`` (non-numeric, bool or non-finite: a NaN
    ``now`` used to read as age 0.0, i.e. perfectly fresh, RM-1597); small
    future jitter reads as age 0. ``max_skew_s`` must be a finite number >= 0
    (ValueError otherwise).
    """
    skew = _check_skew(max_skew_s)
    ts = _coerce_ts(observed_at)
    clock = _finite_real(now)
    if ts is None or clock is None:
        return None
    age = clock - ts
    if age < -skew:
        return None
    return max(0.0, age)


def freshness(
    observed_at: Any,
    max_age_s: float,
    *,
    now: float,
    max_skew_s: float = MAX_CLOCK_SKEW_S,
) -> Freshness:
    """Is an observation made at ``observed_at`` still usable at ``now``?

    Fresh only when its age is known and ``<= max_age_s``. Fails closed:
    reason "unknown" when the timestamp or the reference clock ``now`` is
    unusable, "future" when the timestamp is ahead of ``now`` by more than
    ``max_skew_s``. ``max_age_s`` must be a positive finite number (not a
    bool; an infinite window would never go stale) and ``max_skew_s`` a
    finite number >= 0: anything else is a ValueError (RM-1600).
    """
    window = _finite_real(max_age_s)
    if window is None or not window > 0.0:
        raise ValueError("max_age_s must be a positive finite number")
    _check_skew(max_skew_s)
    ts = _coerce_ts(observed_at)
    if ts is None or _finite_real(now) is None:
        return Freshness(False, None, "unknown")
    age = observation_age(ts, now=now, max_skew_s=max_skew_s)
    if age is None:
        return Freshness(False, None, "future")
    if age <= window:
        return Freshness(True, age, "fresh")
    return Freshness(False, age, "stale")
