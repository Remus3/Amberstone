"""cdragon `mFormulaParts` typed-part formula evaluator (Phase 6 step 3).

Pure-function interpreter for the GameCalculation struct shape Riot ships in
``arena_augments.json`` (cdragon's `cherry-augments.bin` lift). Each calculation
entry is `{mFormulaParts: [part, part, ...], mMultiplier: part?}`. The parts
are typed by `__type`; this module interprets the 4 shapes the formula-
evaluator slice (2026-05-20) committed to:

* ``NumberCalculationPart`` - literal `mNumber`.
* ``NamedDataValueCalculationPart`` - look up `mDataValue` in the augment's
  ``data_values`` dict (index 0 by default; caller can pass a level for the
  Arena S2 Augment Level-Up slice ahead).
* ``StatByNamedDataValueCalculationPart`` - ``data_values[mDataValue][idx] *
  stat[mStat]``. ``mStat`` is Riot's StatType enum; we map the subset that
  appears in cdragon 16.10.1's 220-augment payload.
* ``StatByCoefficientCalculationPart`` - ``mCoefficient * stat[mStat]``.
  When `mStat` is omitted (cdragon ships some parts with a bare coefficient
  that the runtime interprets as "constant base bias"), we treat it as a
  literal additive contribution. This matches what UndyingGuard's TotalDamage
  third part does ("0.0 + 1.1 (as bonus_hp percent)" - the coefficient is
  the constant). When ``mStatFormula`` is present, it refines which value to
  read for the stat (e.g. ``2`` = bonus-only); see ``read_stat`` below.

Composition: parts are SUMMED. ``mMultiplier`` (if present) is evaluated as a
single sub-part and the sum-of-parts is multiplied by it.

Out of scope for this slice (separate evaluator extensions on a future patch):

* ``ByCharLevelInterpolationCalculationPart`` - returns NaN-equivalent (0)
  via the unknown-shape sentinel; caller bears responsibility (used in
  LightemUp/QuantumComputing, level-anchored DAMAGE values not stat grants).
* ``ByCharLevelBreakpointsCalculationPart``, ``BuffCounterByCoefficient``,
  ``SumOfSubParts``, ``ProductOfSubParts``, ``AbilityResourceByCoefficient``,
  ``GameCalculationModified``, hash-name parts (``{...}``) - all return 0
  via the unknown-shape sentinel. None appear in stat-name calc keys at
  cdragon 16.10.1; they all carry damage/proc formulas the evaluator is not
  yet asked to drive.

The evaluator is intentionally PURE: it takes the augment record and a
``StatContext`` (resolved-stat dict from the engine) and returns a float.
It never raises on unknown shapes - returns 0.0 (so an unknown part is a
zero-contribution part, consistent with how the engine treats unregistered
augments). The caller decides whether the resulting number is a stat grant,
a damage value, a heal amount, etc., based on the calculation KEY name.

Input contract (S144-T-589). The payload is cdragon JSON RC does not author,
so every public function returns a FINITE float (or, for the overlay, a dict
of finite floats) and never raises, whatever the shape:

* a number field (``mNumber``, ``mCoefficient``, a ``dataValues`` entry, a
  ``StatContext`` stat) is read through ``_num``: a bool, NaN, +-inf, an int
  too large for a float or anything ``float()`` refuses reads 0.0; a numeric
  string ("0.5") still parses, as it did before;
* a key field (``__type``, ``mDataValue``, a calc name) must be a str and
  ``mStat`` an int or an integral float (never a bool - ``False`` used to
  hash as 0 and read HP); anything else is an unknown shape (0.0);
* ``level_index`` must be an int (never a bool); anything else reads level 0;
* a non-mapping ``data_values`` / ``calculations`` / ``stats`` reads empty,
  a non-mapping ``base_stats`` reads as absent, a missing or foreign context
  is the empty ``StatContext()``, a non-list / non-tuple ``mFormulaParts``
  has no parts, and an ``mStatFormula`` that is not a real number (a bool,
  an array) is no refinement;
* a part, sum or product that overflows to a non-finite value is 0.0.
"""

from __future__ import annotations

import math
import numbers
from dataclasses import dataclass, field
from typing import Mapping

from .augments import Augment


# ---- Riot StatType enum -> canonical stat key -----------------------------
# Source: cdragon-arena `mStat` ordinals across the 16.10.1 augment payload
# cross-referenced with Riot's BaseStatStash / GameDataLibrary enum.
# Only the values that actually appear in the payload (or are within the
# canonical stats.py RESOLVED_STAT_ORDER) are mapped. The rest fall through
# to the unknown-stat zero-contribution path.
#
# Notes:
#  * mStat=2 is "AttackDamage" (total AD post-bonuses).
#  * mStat=3 is "AbilityPower".
#  * mStat=7 is "SpellBlock" (= magic resistance).
#  * mStat=8 is "AttackSpeed".
#  * mStat=9 is "CritChance".
#  * mStat=11 is "AbilityHaste" - NOT a canonical stats.py key today, so
#    an augment-sourced AH contribution is still dropped on merge. The
#    engine DOES model ability haste, just on a different lane: item AH
#    via ``_item_ability_haste.total_item_ability_haste``, which
#    ``ability_dps.compute_ability_dps`` adds into
#    ``ability_dps._total_ability_haste``. (An older comment here cited a
#    line of ``ability_dps.py`` for "the engine has no AH model" - that
#    cross-reference had rotted and the claim was wrong.)
#    Mapping mStat=11 still gives the calc its honest read; the caller is
#    responsible for whether to consume it. Returning a non-zero
#    contribution from `read_stat` for AH is fine - the only
#    canonical-stat-key calc that uses it would land in
#    ``compute_augment_stats`` and be silently dropped on merge.
#  * mStat=12 / mStat=34 are bonus-resource ordinals (`BonusAD`/`BonusHP`
#    via mStatFormula). The current engine doesn't expose "bonus" stat
#    splits cleanly through ResolvedStats, so we approximate "bonus" as
#    the engine's total minus naked-base when mStatFormula=2 ("bonus");
#    when only the ordinal is supplied (no mStatFormula refinement) we
#    fall back to total via the same mapping.
_STAT_ORDINAL_TO_KEY: dict[int, str] = {
    0: "hp",
    2: "ad",
    3: "ap",
    4: "mp",
    6: "armor",
    7: "mr",
    8: "as",
    9: "crit",
    10: "ms",
    11: "ability_haste",
    # 12 and 34 handled via mStatFormula refinement in read_stat().
}

# mStatFormula=2 ("Bonus") - read the bonus delta on top of naked base.
# Without an explicit bonus-stat surface the engine doesn't expose this
# directly, so the evaluator's StatContext optionally carries `base_stats`
# alongside the resolved totals; bonus = resolved - base. Callers that
# don't pass `base_stats` get the resolved total (a conservative fallback).
_STAT_FORMULA_BONUS = 2


@dataclass(frozen=True)
class StatContext:
    """Resolved-stat snapshot for a single evaluator call.

    Carries the resolved total stat dict (post-items, post-augments, before
    the calc evaluates) plus an OPTIONAL naked-base view used by parts that
    require "bonus" stat (mStatFormula=2). Both dicts use canonical stats.py
    keys ("hp", "ad", "ap", "armor", "mr", "as", "crit", "ms", "mp",
    "ability_haste"). Unknown keys read as 0.

    The `level_index` selects which entry of `data_values[mDataValue]` to
    read for level-aware augments. Default 0 (Arena S1 / S2 pre-LevelUp).
    Pre-staged for the Arena S2 Augment Level-Up slice (patch 26.09); not
    consumed by `compute_augment_stats` today.
    """

    stats: Mapping[str, float] = field(default_factory=dict)
    base_stats: Mapping[str, float] | None = None
    level_index: int = 0


_EMPTY_CTX = StatContext()


def _num(value: object) -> float:
    """Coerce one payload number to a finite float; 0.0 when it is not one.

    A bool is not a number here (``True`` used to read 1.0). ``float()``
    still parses a numeric string, so the pre-slice coercion is preserved,
    but NaN / +-inf (a float or the strings "nan" / "1e999") and an int too
    large for a float (OverflowError) read 0.0 instead of poisoning a sum
    or raising.
    """
    if isinstance(value, bool):
        return 0.0
    try:
        out = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return out if math.isfinite(out) else 0.0


def _finite(value: float) -> float:
    """Return ``value`` when finite, else 0.0 (a sum or product overflowed)."""
    return value if math.isfinite(value) else 0.0


def _ctx(ctx: object) -> StatContext:
    """A missing or foreign context reads as the empty ``StatContext()``."""
    return ctx if isinstance(ctx, StatContext) else _EMPTY_CTX


def _mapping(value: object) -> Mapping:
    """A non-mapping container reads as empty."""
    return value if isinstance(value, Mapping) else {}


def _stat_key(ordinal: object) -> str | None:
    """Map a Riot StatType ordinal to a canonical key, or None.

    Accepts an integral number (a numpy int included) or an integral float
    (2.0 hashed equal to 2 before this slice and keeps mapping); refuses a
    bool (``False`` hashed as 0 and read HP), an unhashable value (a list
    raised TypeError) and anything else.
    """
    if isinstance(ordinal, bool):
        return None
    if isinstance(ordinal, float):
        if not ordinal.is_integer():
            return None
        ordinal = int(ordinal)
    if not isinstance(ordinal, numbers.Integral):
        return None
    return _STAT_ORDINAL_TO_KEY.get(int(ordinal))


def _is_bonus_formula(stat_formula: object) -> bool:
    """True when ``mStatFormula`` is the bonus refinement (2, or 2.0).

    Only a real number is compared (a bool never equals 2, so it needs no
    guard of its own); an array-like (``numpy.ndarray == 2`` has no single
    truth value) used to raise ValueError from the ``and``.
    """
    if not isinstance(stat_formula, numbers.Real):
        return False
    return bool(stat_formula == _STAT_FORMULA_BONUS)


def read_stat(
    ctx: StatContext,
    ordinal: int | None,
    stat_formula: int | None = None,
) -> float:
    """Read a stat value from the resolved context by Riot StatType ordinal.

    Returns 0.0 for unknown ordinals (zero-contribution sentinel).
    ``stat_formula=2`` reads the bonus delta when ``base_stats`` is
    available; otherwise the total is returned. A stat value that is not a
    finite number reads 0.0 (see ``_num``); a non-mapping ``base_stats``
    reads as absent.
    """
    key = _stat_key(ordinal)
    if key is None:
        return 0.0
    ctx = _ctx(ctx)
    total = _num(_mapping(ctx.stats).get(key, 0.0))
    if _is_bonus_formula(stat_formula) and isinstance(ctx.base_stats, Mapping):
        return _finite(total - _num(ctx.base_stats.get(key, 0.0)))
    return total


def _level_index(ctx: StatContext) -> int:
    """The context's level index; a non-integral value (or a bool) reads 0."""
    idx = ctx.level_index
    if isinstance(idx, bool) or not isinstance(idx, numbers.Integral):
        return 0
    return int(idx)


def _read_data_value(
    aug: Augment,
    name: str | None,
    idx: int,
) -> float:
    """Read ``aug.data_values[name][idx]`` with float-cast + bounds-check."""
    if not isinstance(name, str) or not name:
        return 0.0
    arr = _mapping(getattr(aug, "data_values", None)).get(name)
    if isinstance(arr, list):
        if 0 <= idx < len(arr):
            return _num(arr[idx])
        # If the requested level index is out of range, fall back to the
        # last entry (the cdragon dataValues arrays are 7-long and pad the
        # tail; level-7 reads land here when an augment caps below level 7).
        if arr:
            return _num(arr[-1])
        return 0.0
    if isinstance(arr, (int, float)):
        return _num(arr)
    return 0.0


# ---- Typed-part interpreters ---------------------------------------------
#
# Each interpreter takes (part_dict, augment, stat_context) and returns a
# float contribution. Unknown shapes return 0.0. Multipliers (mMultiplier)
# are evaluated by recursing into the same dispatch (a multiplier is a
# single typed-part with no sum-of-parts wrapper).


def _eval_number(part: dict, aug: Augment, ctx: StatContext) -> float:
    return _num(part.get("mNumber", 0.0))


def _eval_named_data_value(part: dict, aug: Augment, ctx: StatContext) -> float:
    name = part.get("mDataValue")
    return _read_data_value(aug, name, _level_index(ctx))


def _eval_stat_by_named_data_value(
    part: dict, aug: Augment, ctx: StatContext
) -> float:
    name = part.get("mDataValue")
    val = _read_data_value(aug, name, _level_index(ctx))
    stat = read_stat(ctx, part.get("mStat"), part.get("mStatFormula"))
    return val * stat


def _eval_stat_by_coefficient(
    part: dict, aug: Augment, ctx: StatContext
) -> float:
    coef = _num(part.get("mCoefficient", 0.0))
    ordinal = part.get("mStat")
    if ordinal is None:
        # Bare coefficient (no stat target): the cdragon runtime treats
        # this as a literal additive constant. Matches what UndyingGuard's
        # TotalDamage third part does. Returning the coefficient itself
        # gives the constant contribution.
        return coef
    stat = read_stat(ctx, ordinal, part.get("mStatFormula"))
    return coef * stat


# Dispatch table - keyed by Riot's ``__type`` string.
_PART_DISPATCH = {
    "NumberCalculationPart": _eval_number,
    "NamedDataValueCalculationPart": _eval_named_data_value,
    "StatByNamedDataValueCalculationPart": _eval_stat_by_named_data_value,
    "StatByCoefficientCalculationPart": _eval_stat_by_coefficient,
}


def evaluate_part(part: dict, aug: Augment, ctx: StatContext) -> float:
    """Dispatch a single typed-part to its interpreter.

    Unknown ``__type`` returns 0.0 (zero-contribution sentinel). The
    evaluator never raises on unknown shapes - keeping the
    contract symmetric with how the engine treats unregistered augments.
    A non-str ``__type`` is an unknown shape, and a contribution that
    overflows to a non-finite value is 0.0.
    """
    if not isinstance(part, dict):
        return 0.0
    ptype = part.get("__type")
    if not isinstance(ptype, str):
        return 0.0
    fn = _PART_DISPATCH.get(ptype)
    if fn is None:
        return 0.0
    return _finite(fn(part, aug, _ctx(ctx)))


def evaluate_calculation(
    calc: dict | None, aug: Augment, ctx: StatContext
) -> float:
    """Evaluate a single GameCalculation entry.

    Sums ``mFormulaParts`` entries; multiplies the sum by ``mMultiplier``
    when present. Returns 0.0 for an empty/missing calc, a non-list
    ``mFormulaParts`` and a sum or product that overflows.
    """
    if not isinstance(calc, dict):
        return 0.0
    ctx = _ctx(ctx)
    parts = calc.get("mFormulaParts")
    if not isinstance(parts, (list, tuple)):
        parts = ()
    total = 0.0
    for p in parts:
        total += evaluate_part(p, aug, ctx)
    multiplier_part = calc.get("mMultiplier")
    if isinstance(multiplier_part, dict):
        mult = evaluate_part(multiplier_part, aug, ctx)
        total = total * mult
    return _finite(total)


def evaluate_named_calculation(
    aug: Augment, name: str, ctx: StatContext
) -> float:
    """Look up a named calculation on the augment and evaluate it.

    Returns 0.0 if the calc name is absent or not a str, or the augment
    carries no (mapping of) calculations.
    """
    calcs = _mapping(getattr(aug, "calculations", None))
    if not calcs or not isinstance(name, str):
        return 0.0
    return evaluate_calculation(calcs.get(name), aug, ctx)


# ---- Stat-grant calc key -> canonical stat overlay key --------------------
# When an augment ships a `calculations` entry whose KEY name maps to a
# canonical stat, the evaluator can produce a stat-grant value that
# DISPLACES the hand-maintained `_AUGMENT_STAT_OVERLAYS` entry. At 16.13.1
# almost every calc key is damage/heal/shield/conversion; the lone
# stat-NAMED exception is MasterofDuality (id 54: `ADGained` 3->9 /
# `APGained` 6->18 by char-level), and it stays OUT of this map on purpose -
# those are UPTIME-conditional build-up grants (Attacks grant AP, Abilities
# grant AD, round-scoped), not a static overlay, so pinning a single-stack
# value would inject an uptime-dependent ranking change. This map is the
# door for a genuinely-static stat-named key on a future patch - the
# registry remains the source of truth for today's overlay-covered augments.
#
# This is intentionally narrow: only keys that unambiguously land as stat
# grants (not damage formulas, uptime-conditional build-ups, or tooltips
# that happen to share a stat substring).
STAT_GRANT_CALC_KEYS: dict[str, str] = {
    # No entries today; this map is the seam for the next-patch slice. The
    # absence is the honest signal: the displacement of overlay -> calc
    # evaluation is wired through, awaiting Riot to ship a GENUINELY-STATIC
    # stat-named calc on a future Arena patch. (16.13.1 does ship the
    # stat-named MasterofDuality ADGained/APGained, but those are
    # uptime-conditional build-up grants, not a static overlay - excluded.)
}


def stat_overlay_from_calculations(
    aug: Augment, ctx: StatContext | None = None
) -> dict[str, float]:
    """Produce a stat-overlay dict from the augment's `calculations` field.

    Returns an empty dict when the augment has no calculations or none of
    its calc keys map to a canonical stat grant via
    :data:`STAT_GRANT_CALC_KEYS`. This is the wiring path that, once
    populated, displaces the hand-maintained `_AUGMENT_STAT_OVERLAYS`
    registry entry for that augment. Every value is finite: a grant that
    evaluates non-finite is dropped, and an accumulated total that
    overflows is dropped too.
    """
    calcs = _mapping(getattr(aug, "calculations", None))
    if not calcs:
        return {}
    if not STAT_GRANT_CALC_KEYS:
        return {}
    ctx = _ctx(ctx)
    out: dict[str, float] = {}
    for calc_key, stat_key in STAT_GRANT_CALC_KEYS.items():
        if calc_key not in calcs:
            continue
        v = evaluate_named_calculation(aug, calc_key, ctx)
        if v:
            total = out.get(stat_key, 0.0) + v
            if math.isfinite(total):
                out[stat_key] = total
            else:
                out.pop(stat_key, None)
    return out
