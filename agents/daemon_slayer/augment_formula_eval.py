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
"""

from __future__ import annotations

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
#  * mStat=11 is "AbilityHaste" - NOT a canonical stats.py key today (the
#    engine has no AH model per `ability_dps.py:49`), but mapping it gives
#    the calc its honest read; the caller is responsible for whether to
#    consume it. Returning a non-zero contribution from `read_stat` for AH
#    is fine - the only canonical-stat-key calc that uses it would land in
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


def read_stat(
    ctx: StatContext,
    ordinal: int | None,
    stat_formula: int | None = None,
) -> float:
    """Read a stat value from the resolved context by Riot StatType ordinal.

    Returns 0.0 for unknown ordinals (zero-contribution sentinel).
    ``stat_formula=2`` reads the bonus delta when ``base_stats`` is
    available; otherwise the total is returned.
    """
    if ordinal is None:
        return 0.0
    key = _STAT_ORDINAL_TO_KEY.get(ordinal)
    if key is None:
        return 0.0
    total = float(ctx.stats.get(key, 0.0) or 0.0)
    if stat_formula == _STAT_FORMULA_BONUS and ctx.base_stats is not None:
        base = float(ctx.base_stats.get(key, 0.0) or 0.0)
        return total - base
    return total


def _read_data_value(
    aug: Augment,
    name: str | None,
    idx: int,
) -> float:
    """Read ``aug.data_values[name][idx]`` with float-cast + bounds-check."""
    if not name:
        return 0.0
    arr = aug.data_values.get(name)
    if isinstance(arr, list):
        if 0 <= idx < len(arr):
            try:
                return float(arr[idx])
            except (TypeError, ValueError):
                return 0.0
        # If the requested level index is out of range, fall back to the
        # last entry (the cdragon dataValues arrays are 7-long and pad the
        # tail; level-7 reads land here when an augment caps below level 7).
        if arr:
            try:
                return float(arr[-1])
            except (TypeError, ValueError):
                return 0.0
        return 0.0
    if isinstance(arr, (int, float)):
        return float(arr)
    return 0.0


# ---- Typed-part interpreters ---------------------------------------------
#
# Each interpreter takes (part_dict, augment, stat_context) and returns a
# float contribution. Unknown shapes return 0.0. Multipliers (mMultiplier)
# are evaluated by recursing into the same dispatch (a multiplier is a
# single typed-part with no sum-of-parts wrapper).


def _eval_number(part: dict, aug: Augment, ctx: StatContext) -> float:
    try:
        return float(part.get("mNumber", 0.0))
    except (TypeError, ValueError):
        return 0.0


def _eval_named_data_value(part: dict, aug: Augment, ctx: StatContext) -> float:
    name = part.get("mDataValue")
    return _read_data_value(aug, name, ctx.level_index)


def _eval_stat_by_named_data_value(
    part: dict, aug: Augment, ctx: StatContext
) -> float:
    name = part.get("mDataValue")
    val = _read_data_value(aug, name, ctx.level_index)
    stat = read_stat(ctx, part.get("mStat"), part.get("mStatFormula"))
    return val * stat


def _eval_stat_by_coefficient(
    part: dict, aug: Augment, ctx: StatContext
) -> float:
    try:
        coef = float(part.get("mCoefficient", 0.0))
    except (TypeError, ValueError):
        coef = 0.0
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
    """
    if not isinstance(part, dict):
        return 0.0
    ptype = part.get("__type")
    fn = _PART_DISPATCH.get(ptype)
    if fn is None:
        return 0.0
    return fn(part, aug, ctx)


def evaluate_calculation(
    calc: dict | None, aug: Augment, ctx: StatContext
) -> float:
    """Evaluate a single GameCalculation entry.

    Sums ``mFormulaParts`` entries; multiplies the sum by ``mMultiplier``
    when present. Returns 0.0 for an empty/missing calc.
    """
    if not isinstance(calc, dict):
        return 0.0
    parts = calc.get("mFormulaParts") or ()
    total = 0.0
    for p in parts:
        total += evaluate_part(p, aug, ctx)
    multiplier_part = calc.get("mMultiplier")
    if isinstance(multiplier_part, dict):
        mult = evaluate_part(multiplier_part, aug, ctx)
        total = total * mult
    return total


def evaluate_named_calculation(
    aug: Augment, name: str, ctx: StatContext
) -> float:
    """Look up a named calculation on the augment and evaluate it.

    Returns 0.0 if the calc name is absent or the augment carries no
    calculations.
    """
    if not aug.calculations:
        return 0.0
    return evaluate_calculation(aug.calculations.get(name), aug, ctx)


# ---- Stat-grant calc key -> canonical stat overlay key --------------------
# When an augment ships a `calculations` entry whose KEY name maps to a
# canonical stat, the evaluator can produce a stat-grant value that
# DISPLACES the hand-maintained `_AUGMENT_STAT_OVERLAYS` entry. At cdragon
# 16.10.1 NO augment ships a stat-named calculation key (every key is
# damage/heal/shield/conversion), so this map is the door for the next
# patch - the registry remains the source of truth for today's 137/220
# overlay-covered augments.
#
# This is intentionally narrow: only keys that unambiguously land as stat
# grants (not damage formulas or tooltips that happen to share a stat
# substring).
STAT_GRANT_CALC_KEYS: dict[str, str] = {
    # No entries today; this map is the seam for the next-patch slice. The
    # absence is the honest signal: the displacement of overlay -> calc
    # evaluation is wired through, awaiting Riot to ship a stat-named
    # calc on a future Arena patch.
}


def stat_overlay_from_calculations(
    aug: Augment, ctx: StatContext | None = None
) -> dict[str, float]:
    """Produce a stat-overlay dict from the augment's `calculations` field.

    Returns an empty dict when the augment has no calculations or none of
    its calc keys map to a canonical stat grant via
    :data:`STAT_GRANT_CALC_KEYS`. This is the wiring path that, once
    populated, displaces the hand-maintained `_AUGMENT_STAT_OVERLAYS`
    registry entry for that augment.
    """
    if not aug.calculations:
        return {}
    if not STAT_GRANT_CALC_KEYS:
        return {}
    if ctx is None:
        ctx = StatContext()
    out: dict[str, float] = {}
    for calc_key, stat_key in STAT_GRANT_CALC_KEYS.items():
        if calc_key not in aug.calculations:
            continue
        v = evaluate_named_calculation(aug, calc_key, ctx)
        if v:
            out[stat_key] = out.get(stat_key, 0.0) + float(v)
    return out
