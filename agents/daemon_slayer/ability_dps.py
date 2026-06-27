"""Phase 4b + 4c (s178/s179, 2026-05-12) - Mage ability DPS scorer.

Sibling of ``dps.py``. ``compute_ability_dps()`` returns the caster's
per-spell ability DPS (and total) for a resolved build at a given level.
``rank_items_by_ability_dps()`` (Phase 4c, s179) drives the ``/rank-mage``
ranker - same candidate-filtering pipeline as the DPS/EHP/hybrid
scorers, but each candidate is scored by total ability-DPS gain over
the baseline rather than by auto-attack DPS or blended EHP.

For each of the four active spell keys (Q/W/E/R):

1. Resolve the rank at the given champion level using a canonical
   max-priority order (default Q > W > E; R unlocks at lvl 6/11/16).
2. Evaluate the first damage block of the canonical ability form via the
   Phase 4a ``DamageBlock`` schema - sums ``base`` plus each scaling
   field times its corresponding caster/target stat from the resolved
   build / caller-supplied context.
3. Apply mode damage multiplier (``aramDamageDealt`` for ARAM).
4. Apply mitigation factor per damage type: PHYSICAL->target_armor,
   MAGIC->target_mr, TRUE->none, MIXED->half-half.
5. Multiply per-cast damage by measured casts/sec from
   ``cast_rates.get_spell_casts_per_sec``. If the dataset has no entry
   for this champion x mode, fall back to ``1 / cooldown x mana_uptime``.
6. Sum per-spell DPS into ``total_ability_dps``.

Block-strategy notes
~~~~~~~~~~~~~~~~~~~~

Most damage-dealing mages (Veigar, Lux, Annie, Brand, Syndra, Xerath)
expose a single ``damage`` block per ability key - straightforward to
evaluate. A minority of champions (Aatrox Q's chain variants, Aphelios's
weapon stances, Ezreal's R splash component) ship multiple damage blocks
per form. Phase 4b uses ``block_strategy="first"`` by default - only the
first damage block of the canonical form_index=0 contributes. Phase 5.9
(s191, 2026-05-14) layered a per-(champion, key) ``block_index_overrides``
registry on top - ``champion_block_index.json`` ships defaults for
Cassiopeia E (poisoned-target enhanced), Anivia E (chilled-target
enhanced), Diana W (all-orbs total), Veigar R (executed-target maximum),
Brand W (CC'd-target increased), etc. When a key is in the resolved
override map, the engine switches to the new ``"indexed"`` strategy with
that specific block; keys without an entry honor the global strategy.

Phase 4b deliberate omissions (deferred):
* Passive (P) ability damage - needs different rank model (level-scaled
  rather than rank-locked); typically on-hit which ``compute_dps`` covers.
* Multi-form abilities (Aphelios weapons, Jayce stance, Sylas-stolen ult)
  - ``form_index=0`` only. Operator can pass ``form_index_overrides`` to
  pick a different form per key.
* On-cast triggers, ability-amp items like Liandry's ramp damage -
  modeled at the rotation level in ``dps.py``, not at per-cast level
  here. Items that pump ``ap`` flow through to ability DPS naturally
  via the resolved stat block.
* Conditional damage amps (Ahri R-into-Q, Zoe E-into-Q) - single
  per-cast scoring with no combo-multiplier. Champion-specific.

ENGINE 1.23.0 (2026-05-20) - ability-haste consumption
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Closes the half-shipped state from ENGINE 1.19.0: the engine layer
exposes ``scaled["aram_ability_haste"]`` (flat delta; default 0) and
``scaled["aram_tenacity_mult"]`` (multiplier; default 1.0) via
``engine._apply_mode_modifiers``; this module now CONSUMES the haste
delta to shorten per-spell effective cooldowns using Riot's canonical
haste formula ``eff_cd = base_cd / (1 + total_AH / 100)`` (mirrors
``core/summoner_cooldowns.py`` shipped 2026-05-20 ``58d1e87``).

The total ability-haste plumbed into the formula is the sum of:

* the per-spell ``base_ah`` caller param (defaults to 0; reserved for
  the future item-AH lane - the dataclass shape in ``_effects_types.py``
  does not yet ship an ``ability_haste_flat`` field, so item-AH source
  is currently always 0 and the only non-zero source is the ARAM delta);
* ``scaled.get("aram_ability_haste", 0.0)`` when ``mode == "ARAM"``
  (SR and other modes strip the delta defensively even if a caller
  pre-populates the key).

Per-spell ``AbilitySpellDps`` grows two new fields:

* ``base_cooldown`` - the pre-haste rank cooldown from
  ``_form_cooldown_at_rank`` (back-compat: same value as the pre-1.23
  ``cooldown`` in SR mode with no haste sources).
* ``total_ability_haste`` - the haste sum used in the formula (0.0
  outside ARAM, the aramAbilityHaste delta inside ARAM).

The ``cooldown`` field becomes the EFFECTIVE post-haste value (identity
to ``base_cooldown`` when total haste is 0, the natural case for SR
and most ARAM champions). Result top-level grows ``aram_ability_haste``
and ``aram_tenacity_mult`` for downstream consumer visibility.

TODO (future EHP-side enemy-CC consumer): ``aram_tenacity_mult`` is
plumbed forward but NOT consumed in this slice - the consumption point
is in a future EHP scorer that ingests enemy CC durations applied
against the receiving champion. The marker is in place so when that
scorer ships, the data is already on the result.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Iterable, Optional, Sequence

from ._ability_amp_overrides import (
    _DEFAULT_AMP_PROBABILITY,
    _ability_amp_for,
    _amp_multiplier,
    _cross_spell_amp_for,
    _staged_amp_block_route_for,
)
from .abilities import (
    AbilitiesNotFound,
    AbilitiesSnapshot,
    AbilityForm,
    DamageBlock,
)
from .data_loader import DataSnapshot
from .dps import _ASSUMED_ABILITY_AMP_STACKS, _armor_factor, _periodic_proc_dps
from ._effects_types import CallContext
from .ehp import effective_cc_duration
from .effects import (
    ITEM_EFFECTS,
    collect_effects,
    effective_target_armor,
    effective_target_mr,
    total_ability_damage_amp,
    total_ap_amp_multiplier,
    total_bonus_ap_from_hp,
    total_caster_hp_scaled_ap_amp,
    total_damage_amp_multiplier,
    total_giant_slayer_multiplier,
    total_magic_amp_multiplier,
    total_stacked_ap,
    total_target_bonus_hp_amp_multiplier,
)
from .engine import build_champion
from ._item_ability_haste import effective_cooldown, total_item_ability_haste
from .rank import (
    DEFAULT_SLOT_COUNT,
    DEFAULT_TOP_N,
    SORT_KEYS,
    _filter_candidates,
    _is_terminal,
    strip_arena_trinkets,
)
from .stats import clamp_level
from .ult_rates import get_spell_casts_per_sec, get_ult_casts_per_sec

# --- relocated seams (item 241 A2); re-exported so consumer import paths
# (from .ability_dps import ...) and the cache-reset / cc monkeypatch seams
# keep working unchanged. ----------------------------------------------------
from ._registries import (  # noqa: F401
    DEFAULT_MAX_PRIORITY,
    _BLOCK_INDEX_CACHE,
    _BLOCK_INDEX_CONDITIONS,
    _BLOCK_INDEX_DEFAULT_KEY,
    _BLOCK_INDEX_LOCK,
    _BLOCK_INDEX_PATH,
    _BLOCK_STRATEGIES,
    _FORM_INDEX_CACHE,
    _FORM_INDEX_LOCK,
    _FORM_INDEX_PATH,
    _MAX_PRIORITY_CACHE,
    _MAX_PRIORITY_LOCK,
    _MAX_PRIORITY_PATH,
    _SCALING_TARGETS,
    _load_block_index_table,
    _load_form_index_table,
    _load_max_priority_table,
    _normalize_block_index_value,
    _resolve_block_index_overrides,
    _resolve_form_index_overrides,
    _resolve_max_priority,
    get_block_index_for,
    get_form_index_for,
    get_max_priority_for,
    reset_block_index_cache,
    reset_form_index_cache,
    reset_max_priority_cache,
)
from ._per_spell_cc import (  # noqa: F401
    _PER_SPELL_CC_DURATIONS,
    _PER_SPELL_CC_RANGE,
    _apply_tenacity_to_cc_tuple,
    _build_per_spell_cc_durations,
    _build_per_spell_cc_range,
    _per_spell_cc_for,
    _per_spell_cc_range_for,
)
from ._rank_mage import (  # noqa: F401
    AbilityDpsRankResult,
    AbilityDpsRankedItem,
    rank_items_by_ability_dps,
)

# Canonical 4-active-spell set. Passive (P) is intentionally excluded -
# the ``compute_dps`` auto-attack scorer covers on-hit passives, and
# level-scaled passive damage doesn't fit the per-rank model.
SPELL_KEYS: tuple[str, ...] = ("Q", "W", "E", "R")

# Standard max-priority rank tables (0-indexed rank at champion level).
# Pin to the conventional "Q-first, W-second, E-third" max order; Phase 4d
# (s185) ships per-champion overrides via ``champion_max_priority.json``
# loaded by ``get_max_priority_for`` below.
_PRIORITY_TABLES: dict[str, tuple[int, ...]] = {
    # Indexed 1-18 (idx 0 unused so lookup reads naturally).
    "priority_1": (-1, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4),
    "priority_2": (-1, -1, 0, 0, 0, 0, 0, 0, 1, 1, 2, 2, 3, 4, 4, 4, 4, 4, 4),
    "priority_3": (-1, -1, -1, -1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 2, 2, 3, 4),
    # R unlocks at 6/11/16 - three ranks total.
    "ultimate":   (-1, -1, -1, -1, -1, -1, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 2, 2, 2),
}



@dataclass(frozen=True)
class AbilityContext:
    """Resolved caster/target stats fed into the per-cast damage formula.

    Mirrors ``effects.CallContext`` but with a name + shape tuned for
    ability evaluation. Decoupled from the auto-attack scorer's
    ``CallContext`` so future Phase 4b/4c changes don't ripple back.
    """
    base_ad: float
    total_ad: float        # base + bonus
    bonus_ad: float
    ap: float
    caster_max_hp: float
    caster_bonus_hp: float
    caster_bonus_armor: float
    caster_bonus_mr: float
    caster_max_mp: float
    caster_mp_regen_per_5: float
    target_armor: float
    target_mr: float
    target_max_hp: float
    target_current_hp: float
    target_missing_hp: float
    target_bonus_hp: float
    # 2026-05-30 unit-map exhaustion: deterministic caster-stat scalings.
    # Defaulted so existing manual AbilityContext(...) constructions (test
    # helpers) stay valid; from_build sets real values by keyword.
    caster_armor: float = 0.0
    caster_bonus_mp: float = 0.0
    caster_bonus_ms: float = 0.0

    @staticmethod
    def from_build(
        stats: dict[str, float],
        base_stats: dict[str, float] | None,
        target_armor: float,
        target_mr: float,
        target_max_hp: float,
        target_bonus_hp: float,
        target_current_hp_pct: float = 1.0,
    ) -> "AbilityContext":
        """Build a context from a resolved champion's ``stats`` dict.

        ``target_current_hp_pct`` is the assumed fraction of target's max
        HP they're sitting at - defaults to 1.0 (full HP). Operators can
        override for ``target_missing_hp_pct`` / ``target_current_hp_pct``
        damage blocks (Eve's R is full at low HP, etc.).
        """
        base = base_stats or {}
        base_ad = float(base.get("ad", 0.0))
        total_ad = float(stats.get("ad", 0.0))
        bonus_ad = max(0.0, total_ad - base_ad)
        caster_max_hp = float(stats.get("hp", 0.0))
        caster_base_hp = float(base.get("hp", 0.0))
        caster_bonus_hp = max(0.0, caster_max_hp - caster_base_hp)
        caster_base_armor = float(base.get("armor", 0.0))
        caster_bonus_armor = max(0.0, float(stats.get("armor", 0.0)) - caster_base_armor)
        caster_base_mr = float(base.get("mr", 0.0))
        caster_bonus_mr = max(0.0, float(stats.get("mr", 0.0)) - caster_base_mr)
        caster_armor = float(stats.get("armor", 0.0))
        caster_max_mp = float(stats.get("mp", 0.0))
        caster_bonus_mp = max(0.0, caster_max_mp - float(base.get("mp", 0.0)))
        caster_bonus_ms = max(0.0, float(stats.get("ms", 0.0)) - float(base.get("ms", 0.0)))

        current_pct = max(0.0, min(1.0, target_current_hp_pct))
        target_current_hp = target_max_hp * current_pct
        target_missing_hp = target_max_hp * (1.0 - current_pct)

        return AbilityContext(
            base_ad=base_ad,
            total_ad=total_ad,
            bonus_ad=bonus_ad,
            ap=float(stats.get("ap", 0.0)),
            caster_max_hp=caster_max_hp,
            caster_bonus_hp=caster_bonus_hp,
            caster_bonus_armor=caster_bonus_armor,
            caster_bonus_mr=caster_bonus_mr,
            caster_armor=caster_armor,
            caster_max_mp=caster_max_mp,
            caster_bonus_mp=caster_bonus_mp,
            caster_bonus_ms=caster_bonus_ms,
            caster_mp_regen_per_5=float(stats.get("mpregen", 0.0)),
            target_armor=float(target_armor),
            target_mr=float(target_mr),
            target_max_hp=float(target_max_hp),
            target_current_hp=target_current_hp,
            target_missing_hp=target_missing_hp,
            target_bonus_hp=float(target_bonus_hp),
        )


def rank_at_level(
    key: str,
    level: int,
    max_priority: Sequence[str] = ("Q", "W", "E"),
) -> int:
    """Return the rank (0-indexed) the spell would have at champion level.

    Uses the canonical "1 ability point per level" distribution with
    priorities: first key in ``max_priority`` is maxed first, second
    is maxed second, third is maxed third. ``R`` is always treated as
    the ultimate and unlocks at lvl 6/11/16.

    Returns ``-1`` when the spell is not yet unlocked at that level -
    consumers treat as zero damage.

    ``key='P'`` is treated as level-scaled passive: returns ``level - 1``
    clamped to [0, 17]. ``DamageBlock.value_at`` clamps further to the
    block's actual length.
    """
    level = clamp_level(level)
    if key == "P":
        return max(0, min(17, level - 1))
    if key == "R":
        return _PRIORITY_TABLES["ultimate"][level]
    if key not in {"Q", "W", "E"}:
        raise ValueError(f"unknown ability key: {key!r}")
    if key not in max_priority:
        # Operator passed an unusual priority list - fall back to a
        # safe rank-0 unlock at lvl 1 (treat as priority_3).
        return _PRIORITY_TABLES["priority_3"][level]
    idx = list(max_priority).index(key)
    table = _PRIORITY_TABLES[f"priority_{idx + 1}"]
    return table[level]


def _mitigation_factor(damage_type: str | None, target_armor: float, target_mr: float) -> float:
    """League's mitigation factor for a damage block.

    Delegates to the single source of truth ``dps._armor_factor`` for
    both resists (League's resist->multiplier curve is identical for
    armor and MR). MIXED splits 50/50 armor/MR (rare; mostly utility
    abilities). TRUE bypasses all resists. Unknown / None defaults to
    MAGIC routing - most multi-block abilities without a form-level
    damage_type are magical. Was a local copy of the formula until the
    2026-05-18 audit folded it onto _armor_factor to kill the drift
    risk (a one-sided edit would silently desync the DPS / ability-DPS
    / burst scorers).
    """
    dt = (damage_type or "MAGIC").upper()
    if dt == "TRUE":
        return 1.0
    if dt == "PHYSICAL":
        return _armor_factor(target_armor)
    if dt == "MIXED":
        return 0.5 * _armor_factor(target_armor) + 0.5 * _armor_factor(target_mr)
    return _armor_factor(target_mr)  # MAGIC + fallback


def _evaluate_block(
    block: DamageBlock,
    rank: int,
    ctx: AbilityContext,
) -> float:
    """Sum a damage block's contribution at the given rank.

    Base damage is taken directly. Each scaling field is multiplied by
    its corresponding context attribute, divided by 100 (Meraki stores
    percentages as floats, e.g. 50.0 = 50%). Missing fields contribute 0
    via ``DamageBlock.value_at``'s default.

    item 248 bilinear schema lift: ``block.bilinear_terms`` adds each
    ``factor * ctx[attr_a] * ctx[attr_b]`` PRODUCT term - the one damage form a
    single linear ``_SCALING_TARGETS`` field cannot express (Gwen P
    "0.55% per 100 AP of target max HP" = AP * target_max_hp). The factor is
    flat (level-independent) so it is summed after the per-rank linear terms.
    Default ``()`` leaves every existing block byte-identical.
    """
    if rank < 0:
        return 0.0
    total = block.value_at("base", rank)
    for field_name, ctx_attr in _SCALING_TARGETS:
        scaling_pct = block.value_at(field_name, rank)
        if scaling_pct == 0.0:
            continue
        ctx_val = getattr(ctx, ctx_attr, 0.0)
        total += (scaling_pct / 100.0) * ctx_val
    for factor, attr_a, attr_b in block.bilinear_terms:
        if factor == 0.0:
            continue
        total += factor * getattr(ctx, attr_a, 0.0) * getattr(ctx, attr_b, 0.0)
    return total


def _select_blocks(
    blocks: tuple[DamageBlock, ...],
    rank: int,
    ctx: AbilityContext,
    strategy: str,
    block_index: "int | Sequence[int] | dict[str, int | Sequence[int]]" = 0,
) -> float:
    """Combine damage blocks per the configured strategy.

    ``block_index`` is consulted only when ``strategy == "indexed"`` (added
    in Phase 5.9, s191). For ``"first"`` it is ignored (block 0 always
    used); for ``"max"`` / ``"sum"`` it is also ignored (all blocks
    aggregated). Out-of-range indexes clamp to the last available damage
    block, preserving forward-compat with future patches that may add
    extra blocks to existing forms.

    Phase 5.9.20 (s207, 2026-05-14): ``block_index`` may now be an int OR
    a sequence of ints. When a sequence is supplied under ``"indexed"``
    strategy, the evaluated damage at each (clamped) index is summed -
    used to express "operator commits to landing every component" cases
    where the realistic single-target damage is the sum across multiple
    Meraki blocks (Camille W base + outer-cone, Malphite W active cast
    + first-AA bonus, Heimerdinger W initial + 4 subsequent rockets,
    Katarina R full physical + magic dagger volleys). An empty sequence
    returns 0.0. Single-int callers retain identical pre-s207 behavior.

    Phase 5.9.28 (s228, 2026-05-16): ``block_index`` may now also be a
    conditional ``dict`` (target-state schema lift, operator-signed-off
    option B). Part 1 resolves it to its ``"default"`` branch
    unconditionally - the operator-commits/canonical block, byte-identical
    to an equivalent unconditional int/list entry. Live target-state
    predicate evaluation (selecting a downgrade branch from real
    liveclient HP%/CC) is Part 2 (B-2 plumbing); the int/list paths stay
    byte-identical to pre-s228.
    """
    damage_blocks = tuple(b for b in blocks if b.attribute_kind == "damage")
    if not damage_blocks:
        return 0.0
    if strategy == "first":
        return _evaluate_block(damage_blocks[0], rank, ctx)
    if strategy == "indexed":
        bi = block_index
        if isinstance(bi, dict):
            # Phase 5.9.28 (s228): conditional schema. Part 1 resolves to
            # the operator-commits / canonical "default" branch
            # unconditionally - live target-state predicate evaluation
            # (Part 2 / B-2) selects downgrade branches from real
            # liveclient HP%/CC. ``"default"`` is guaranteed present by
            # ``_normalize_block_index_value``; the ``.get(..., 0)``
            # fallback only guards a caller dict that bypassed it.
            bi = bi.get(_BLOCK_INDEX_DEFAULT_KEY, 0)
        if isinstance(bi, int):
            indices: tuple[int, ...] = (bi,)
        else:
            indices = tuple(int(x) for x in bi)
        if not indices:
            return 0.0
        total = 0.0
        for raw_idx in indices:
            idx = raw_idx
            if idx < 0:
                idx = 0
            if idx >= len(damage_blocks):
                idx = len(damage_blocks) - 1
            total += _evaluate_block(damage_blocks[idx], rank, ctx)
        return total
    evals = [_evaluate_block(b, rank, ctx) for b in damage_blocks]
    if strategy == "max":
        return max(evals) if evals else 0.0
    if strategy == "sum":
        return sum(evals)
    raise ValueError(f"unknown block_strategy: {strategy!r}")


def _form_cooldown_at_rank(
    form: AbilityForm,
    rank: int,
    fallback_form: AbilityForm | None = None,
) -> float:
    """Return the cooldown at this rank.

    Phase 5.9.19 (s206, 2026-05-14): when ``form`` has no per-rank CD data
    (Meraki snapshots set ``cooldown=None`` for every non-form-0 entry of a
    form-swap ability - Riven R / Renekton E / AurelionSol R / Qiyana Q
    etc.), inherit from ``fallback_form`` (typically form 0) which carries
    the canonical CD list. Form-swap mechanics share the actual game CD
    with their parent form, so inheritance is correct.

    Final fallback: 60s generic default (preserves pre-s206 behavior when
    no fallback is available - single-form abilities with malformed CD).
    """
    if form.cooldown:
        if rank < 0:
            rank = 0
        if rank >= len(form.cooldown):
            return float(form.cooldown[-1])
        return float(form.cooldown[rank])
    if fallback_form is not None and fallback_form.cooldown:
        if rank < 0:
            rank = 0
        if rank >= len(fallback_form.cooldown):
            return float(fallback_form.cooldown[-1])
        return float(fallback_form.cooldown[rank])
    return 60.0


def _effective_ability_cd(base_cd: float, total_haste: float) -> float:
    """Apply Riot's canonical haste formula to an ability base cooldown.

    ENGINE 1.23.0 (2026-05-20): mirrors ``core.summoner_cooldowns._effective_cd``
    so the engine + summoner-CD ledger use the same math (the summoner
    module landed 2026-05-20 ``58d1e87``; this helper is the ability-side
    sibling).

    Formula: ``eff_cd = base_cd / (1 + total_haste / 100)``.
      * ``total_haste = 0`` -> identity (eff_cd == base_cd).
      * ``total_haste > 0`` -> shorter eff_cd.
      * ``total_haste < 0`` (event-mode penalties; Seraphine -20, Teemo
        -15, Ziggs -20 etc) -> longer eff_cd via the same formula.

    Defensive floor on the denominator: a hypothetical
    ``total_haste <= -100`` would otherwise divide by zero / invert. The
    helper clamps the denominator to a 0.01 floor so result stays
    finite + monotone-increasing as haste approaches -100 from above.
    Real engine values never approach this edge but the floor keeps the
    helper robust against caller-supplied test extremes.

    A ``base_cd`` of 0 returns 0 regardless of haste (locked spells,
    pre-rank states).

    Delegates to ``_item_ability_haste.effective_cooldown`` (the shared
    single-source formula); this wrapper stays as the ability-side name +
    docstring anchor. Byte-identical to the prior inline implementation.
    """
    return effective_cooldown(base_cd, total_haste)


def _total_ability_haste(
    scaled_stats: dict[str, float],
    mode: str,
    base_ah: float = 0.0,
) -> float:
    """Sum the total ability-haste applied to per-spell cooldowns.

    ENGINE 1.23.0 (2026-05-20): mode-gated read of the engine-exposed
    ``aram_ability_haste`` delta (engine.py line ~210). SR + every
    non-ARAM mode strip the delta defensively even if a caller
    pre-populates the key (the engine's _apply_mode_modifiers gates
    on mode == "ARAM"; this helper double-gates so a malformed
    scaled-dict can't leak ARAM haste into SR rankings).

    ``base_ah`` is the caller-supplied baseline (defaults 0). ENGINE
    1.24.0 (2026-05-21) wired the item-AH lane via
    ``_item_ability_haste.total_item_ability_haste(item_ids)`` -
    ``compute_ability_dps`` now passes the sum of per-item flat AH
    here. The registry covers patch 16.10.1's 220 AH-carrying items
    (parsed from DDragon items.json description text). Test/CLI
    callers passing builds with no AH items see the floor case
    (base_ah=0.0, identity).

    Negative deltas (Seraphine -20, Teemo -15, etc) pass through; the
    haste formula handles them via ``_effective_ability_cd``.
    """
    if mode != "ARAM":
        return float(base_ah)
    aram_ah = float(scaled_stats.get("aram_ability_haste", 0.0))
    return float(base_ah) + aram_ah




def _form_cost_at_rank(form: AbilityForm, rank: int) -> float:
    """Return mana/resource cost at rank, or 0.0 when None / empty."""
    if form.cost is None or not form.cost:
        return 0.0
    if rank < 0:
        rank = 0
    if rank >= len(form.cost):
        return float(form.cost[-1])
    return float(form.cost[rank])


def _mana_uptime_factor(
    cost_per_cast: float,
    cooldown: float,
    ctx: AbilityContext,
    resource: str | None,
) -> float:
    """Fraction of theoretical 1/cooldown rate sustainable by mana regen.

    Only meaningful when the resource is MANA AND the champion has a
    non-zero mana pool AND the cost is non-zero. Energy / manaless /
    HP-cost users return 1.0 (no economy constraint).

    Returns a value in (0, 1]. Used only by the fallback path that
    doesn't have measured rewind data - measured casts/sec already
    encodes mana downtime.
    """
    if resource != "MANA":
        return 1.0
    if cost_per_cast <= 0:
        return 1.0
    if ctx.caster_max_mp <= 0:
        return 1.0
    if cooldown <= 0:
        return 1.0
    # Regen per second from per-5 value.
    regen_per_sec = ctx.caster_mp_regen_per_5 / 5.0
    cost_per_sec_theoretical = cost_per_cast / cooldown
    if cost_per_sec_theoretical <= regen_per_sec:
        return 1.0
    return max(0.05, regen_per_sec / cost_per_sec_theoretical)


# --- per-spell evaluation ----------------------------------------------------


@dataclass(frozen=True)
class AbilitySpellDps:
    """Per-spell-key breakdown returned by ``compute_ability_dps``.

    ENGINE 1.23.0 (2026-05-20): added ``base_cooldown`` + ``total_ability_haste``
    fields. The existing ``cooldown`` field now stores the EFFECTIVE
    post-haste cooldown (``base_cooldown / (1 + total_ability_haste / 100)``).
    SR mode + most ARAM champions (those with aramAbilityHaste=0) see
    identity: ``cooldown == base_cooldown``.

    ENGINE 1.29.0 (2026-05-21): added ``cc_duration_s`` +
    ``cc_duration_post_tenacity`` per-spell tuples (2nd consumer of the
    ``effective_cc_duration`` helper shipped 1.25.0). Both default to
    ``()`` empty tuple because the ``_PER_SPELL_CC_DURATIONS`` registry
    is empty at 1.29.0 by design (forward-marker; future patches
    populate it when a downstream EHP-vs-CC blended scorer / fight-sim
    consumer ships). When populated, ``cc_duration_s`` is the per-rank
    base (length 5 for Q/W/E, length 3 for R) and
    ``cc_duration_post_tenacity`` is the same shape after element-wise
    ``effective_cc_duration(base, aram_tenacity_mult)`` - identity in
    SR + non-ARAM modes; lengthened in ARAM for the 15 champs with
    aramTenacity > 1.0.
    """
    key: str
    form_name: str
    form_index: int
    rank: int
    cooldown: float                     # effective post-haste cooldown
    cost: float
    damage_type: str | None
    resource: str | None
    raw_damage_per_cast: float          # base + all scaling, pre-mode, pre-mitigation
    post_mode_damage_per_cast: float    # x mode_multiplier
    post_mitigation_damage_per_cast: float
    casts_per_sec: float                # measured (if available) or theoretical
    casts_per_sec_source: str           # "measured" | "theoretical_with_mana_uptime" | "missing"
    mana_uptime_factor: float
    dps: float
    base_cooldown: float = 0.0          # pre-haste rank cooldown (ENGINE 1.23.0)
    total_ability_haste: float = 0.0    # haste sum used in haste formula (ENGINE 1.23.0)
    cc_duration_s: tuple[float, ...] = ()                # per-rank base CC duration (ENGINE 1.29.0)
    cc_duration_post_tenacity: tuple[float, ...] = ()    # cc_duration_s x aram_tenacity_mult (ENGINE 1.29.0)
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "form_name": self.form_name,
            "form_index": self.form_index,
            "rank": self.rank,
            "cooldown": self.cooldown,
            "cost": self.cost,
            "damage_type": self.damage_type,
            "resource": self.resource,
            "raw_damage_per_cast": self.raw_damage_per_cast,
            "post_mode_damage_per_cast": self.post_mode_damage_per_cast,
            "post_mitigation_damage_per_cast": self.post_mitigation_damage_per_cast,
            "casts_per_sec": self.casts_per_sec,
            "casts_per_sec_source": self.casts_per_sec_source,
            "mana_uptime_factor": self.mana_uptime_factor,
            "dps": self.dps,
            "base_cooldown": self.base_cooldown,
            "total_ability_haste": self.total_ability_haste,
            "cc_duration_s": list(self.cc_duration_s),
            "cc_duration_post_tenacity": list(self.cc_duration_post_tenacity),
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class AbilityDpsResult:
    """Top-level result from ``compute_ability_dps``.

    ENGINE 1.23.0 (2026-05-20): added ``aram_ability_haste`` (consumed
    by the per-spell cooldown haste formula) and ``aram_tenacity_mult``
    (forwarded for a future EHP-side enemy-CC consumer; not consumed in
    this slice - see module-level TODO).
    """
    champion_id: str
    champion_name: str
    level: int
    item_ids: tuple[str, ...]
    mode: str
    target_armor: float
    target_mr: float
    target_max_hp: float
    target_bonus_hp: float
    mode_multiplier: float                          # aramDamageDealt; 1.0 outside ARAM
    per_spell: tuple[AbilitySpellDps, ...]
    total_ability_dps: float
    primary_scaling: str                            # "AP" | "AD" | "HP" | "MIXED" | "TRUE"
    max_priority: tuple[str, str, str]
    block_strategy: str
    max_priority_source: str = "default"            # "override" | "champion" | "default"
    form_index_source: str = "default"              # "override" | "champion" | "default"
    form_index_resolved: dict[str, int] = field(default_factory=dict)
    block_index_source: str = "default"             # "override" | "champion" | "default"
    block_index_resolved: "dict[str, int | list[int] | dict[str, int | list[int]]]" = field(default_factory=dict)
    stats: dict[str, float] = field(default_factory=dict)
    aram_ability_haste: float = 0.0                 # consumed haste delta (ENGINE 1.23.0)
    aram_tenacity_mult: float = 1.0                 # forwarded for future EHP consumer (ENGINE 1.23.0)
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "champion_id": self.champion_id,
            "champion_name": self.champion_name,
            "level": self.level,
            "item_ids": list(self.item_ids),
            "mode": self.mode,
            "target_armor": self.target_armor,
            "target_mr": self.target_mr,
            "target_max_hp": self.target_max_hp,
            "target_bonus_hp": self.target_bonus_hp,
            "mode_multiplier": self.mode_multiplier,
            "per_spell": [s.to_dict() for s in self.per_spell],
            "total_ability_dps": self.total_ability_dps,
            "primary_scaling": self.primary_scaling,
            "max_priority": list(self.max_priority),
            "max_priority_source": self.max_priority_source,
            "block_strategy": self.block_strategy,
            "form_index_source": self.form_index_source,
            "form_index_resolved": dict(self.form_index_resolved),
            "block_index_source": self.block_index_source,
            "block_index_resolved": dict(self.block_index_resolved),
            "stats": dict(self.stats),
            "aram_ability_haste": self.aram_ability_haste,
            "aram_tenacity_mult": self.aram_tenacity_mult,
            "notes": list(self.notes),
        }

    def format_table(self) -> str:
        head = (
            f"{self.champion_name} ({self.champion_id}) - lvl {self.level} "
            f"- mode {self.mode}  [MAGE]"
        )
        rows = [head, "-" * len(head)]
        if self.item_ids:
            rows.append(f"items: {', '.join(self.item_ids)}")
        else:
            rows.append("items: (none)")
        rows.append(
            f"target: armor={self.target_armor:.0f}  mr={self.target_mr:.0f}"
            f"  max_hp={self.target_max_hp:.0f}"
        )
        rows.append(
            f"priority: {'>'.join(self.max_priority)}  "
            f"block: {self.block_strategy}  primary_scaling: {self.primary_scaling}"
        )
        rows.append("")
        rows.append(
            f"  {'spell':<6}  {'rank':>4}  {'cd':>5}  {'dpc':>7}  "
            f"{'cps':>6}  {'dps':>7}"
        )
        rows.append("  " + "-" * 60)
        for s in self.per_spell:
            rows.append(
                f"  {s.key + ' ' + s.form_name[:4]:<6}  {s.rank:>4}  "
                f"{s.cooldown:>5.1f}  {s.post_mitigation_damage_per_cast:>7.1f}  "
                f"{s.casts_per_sec:>6.3f}  {s.dps:>7.2f}"
            )
        rows.append("")
        rows.append(f"  total_ability_dps    {self.total_ability_dps:.2f}")
        if self.notes:
            rows.append("")
            for n in self.notes:
                rows.append(f"  note: {n}")
        return "\n".join(rows)


# --- primary-scaling classifier ----------------------------------------------


def _classify_primary_scaling(per_spell: Sequence[AbilitySpellDps],
                              forms: Sequence[AbilityForm]) -> str:
    """Identify which stat the champion's abilities mainly scale off.

    Inspects the un-evaluated damage blocks rather than the post-build
    DPS so the classification is stable across builds. Used by Phase 4c
    to route between the mage / bruiser / carry ranker.
    """
    ap_score = 0.0
    ad_score = 0.0
    hp_score = 0.0
    true_score = 0.0
    for form in forms:
        for block in form.damage_blocks:
            if block.attribute_kind != "damage":
                continue
            if block.ap_pct:
                ap_score += sum(block.ap_pct)
            if block.total_ad_pct:
                ad_score += sum(block.total_ad_pct)
            if block.bonus_ad_pct:
                ad_score += sum(block.bonus_ad_pct)
            if block.caster_max_hp_pct:
                hp_score += sum(block.caster_max_hp_pct)
            if block.caster_bonus_hp_pct:
                hp_score += sum(block.caster_bonus_hp_pct)
    # Heuristic: pick the dominant signal.
    scores = {"AP": ap_score, "AD": ad_score, "HP": hp_score}
    top = max(scores, key=lambda k: scores[k])
    if scores[top] <= 0:
        # No scaling found - could be all-base or unparsed.
        return "MIXED"
    if scores[top] < 1.5 * sum(v for k, v in scores.items() if k != top):
        return "MIXED"
    return top


# --- top-level compute -------------------------------------------------------


def compute_ability_dps(
    snapshot: DataSnapshot,
    champion_id: str,
    level: int,
    item_ids: Optional[Iterable[str | int]] = None,
    mode: str = "SR",
    target_armor: float = 0.0,
    target_mr: float = 0.0,
    target_max_hp: float = 0.0,
    target_bonus_hp: float = 0.0,
    target_current_hp_pct: float = 1.0,
    augments: Optional[Iterable] = None,
    abilities_snapshot: Optional[AbilitiesSnapshot] = None,
    max_priority: Optional[Sequence[str]] = None,
    block_strategy: str = "first",
    form_index_overrides: Optional[dict[str, int]] = None,
    block_index_overrides: "Optional[dict[str, int | list[int] | dict[str, int | list[int]]]]" = None,
    apply_ability_amps: bool = False,
    assume_ability_amp: bool = False,
    assume_magic_burst: bool = False,
) -> AbilityDpsResult:
    """Compute total ability DPS for the resolved build.

    Mirror of ``compute_dps``'s contract - same ``snapshot``, ``mode``,
    ``target_*``, and ``augments`` plumbing - but the result decomposes by
    spell key instead of by rotation phase.

    Parameters
    ----------
    target_current_hp_pct:
        Assumed fraction of max HP the target sits at when the cast lands
        (default 1.0 = full HP). Affects ``target_missing_hp_pct`` /
        ``target_current_hp_pct`` blocks only.
    abilities_snapshot:
        Optional override - defaults to the lazy-cached snapshot from
        ``abilities.load_default()``. Test fixtures pass synthetic ones.
    max_priority:
        Optional three ability keys (e.g. ``("E", "Q", "W")``) describing
        max order - first key is maxed first, third last. When ``None``,
        the per-champion override registry (``champion_max_priority.json``)
        is consulted; falls back to Q-W-E for unmapped champions.
    block_strategy:
        Global strategy for multi-block abilities - ``"first"`` (default),
        ``"sum"``, ``"max"``, or ``"indexed"``. Per-key overrides via
        ``block_index_overrides`` switch a specific key to ``"indexed"``
        with the supplied block_index; keys without an entry fall back to
        the global strategy. See module docstring for rationale.
    form_index_overrides:
        Per-key form index overrides - e.g. ``{"Q": 2}`` to evaluate
        Aphelios's Q with the 3rd weapon stance. Default 0 for all keys.
    block_index_overrides:
        Per-key damage-block index overrides - e.g. ``{"E": 1}`` to evaluate
        Cassiopeia E's "Total Enhanced Damage" block instead of the default
        "Bonus Magic Damage" block0. When ``None``, the per-champion override
        registry (``champion_block_index.json``) is consulted; falls back
        to block 0 for unmapped (champion, key) pairs.
    """
    if block_strategy not in _BLOCK_STRATEGIES:
        raise ValueError(
            f"block_strategy must be one of {_BLOCK_STRATEGIES}, "
            f"got {block_strategy!r}"
        )
    max_priority, max_priority_source = _resolve_max_priority(champion_id, max_priority)
    form_index_overrides, form_index_source = _resolve_form_index_overrides(
        champion_id, form_index_overrides,
    )
    block_index_overrides, block_index_source = _resolve_block_index_overrides(
        champion_id, block_index_overrides,
    )
    if not 0.0 <= target_current_hp_pct <= 1.0:
        raise ValueError(
            f"target_current_hp_pct must be in [0,1], got {target_current_hp_pct}"
        )

    level = clamp_level(level)

    # Load ability data; defer the import-time cost to the first call.
    abil_snap = abilities_snapshot
    if abil_snap is None:
        from .abilities import load_default  # local import keeps test fixtures cheap
        try:
            abil_snap = load_default()
        except AbilitiesNotFound as e:
            # Surface a structured 0-result with a single note rather than
            # crashing - the server can return a body explaining the missing
            # snapshot.
            return _empty_result(
                snapshot, champion_id, level, item_ids, mode,
                target_armor, target_mr, target_max_hp, target_bonus_hp,
                max_priority, block_strategy,
                max_priority_source=max_priority_source,
                form_index_source=form_index_source,
                form_index_resolved=form_index_overrides,
                block_index_source=block_index_source,
                block_index_resolved=block_index_overrides,
                note=f"abilities snapshot missing: {e}",
            )

    # Resolve build stats. Reuses the same engine pipeline as compute_dps.
    resolved = build_champion(
        snapshot, champion_id, level, item_ids=item_ids, mode=mode,
        augments=augments,
    )

    # Mode damage multiplier (ARAM aramDamageDealt only - EHP scorer uses
    # aramDamageTaken on the receiving side).
    champ_rec = snapshot.champion(resolved.champion_id)
    aram = ((champ_rec.get("lolmath") or {}).get("aram_modifiers") or {})
    mode_mult = 1.0
    if mode == "ARAM":
        mode_mult = float(aram.get("aramDamageDealt", 1.0))

    # Build ability context.
    ctx = AbilityContext.from_build(
        stats=resolved.stats,
        base_stats=resolved.base_stats,
        target_armor=target_armor,
        target_mr=target_mr,
        target_max_hp=target_max_hp,
        target_bonus_hp=target_bonus_hp,
        target_current_hp_pct=target_current_hp_pct,
    )

    # Mirror the AP cross-derivations + damage amps that ``compute_dps``
    # applies (Phase 4 batches 14/15/19/32/34/38/54/56). Without this,
    # Rabadon's 30% AP amp / Liandry's 6% damage amp / Abyssal Mask
    # magic amp would be invisible to the ability scorer - making item
    # rankings disagree with the auto-attack DPS scorer for no good
    # reason. All amps preserve the same precedence as compute_dps:
    #   ap += ap_from_hp + stacked_ap
    #   ap *= ap_amp (Rabadon's)
    #   ap *= hp_ap_amp (Demonic Embrace HP-scaled)
    # then per-cast damage flows through:
    #   damage *= damage_amp (Riftmaker/Liandry's)
    #   damage *= target_bonus_hp_amp (LDR Giant Slayer @ bonus HP)
    #   damage *= giant_slayer_amp (Perplexity @ max HP diff)
    # plus magic-only damage gets an extra ``magic_amp`` (Abyssal Mask)
    # applied inside the per-spell loop based on the form's damage_type.
    item_effects = collect_effects(resolved.item_ids)
    ap_from_hp = total_bonus_ap_from_hp(item_effects, ctx.caster_bonus_hp)
    stacked_ap = total_stacked_ap(item_effects)
    ap_total = ctx.ap + ap_from_hp + stacked_ap
    ap_amp = total_ap_amp_multiplier(item_effects)
    if ap_amp != 1.0:
        ap_total *= ap_amp
    hp_ap_amp = total_caster_hp_scaled_ap_amp(item_effects, ctx.caster_max_hp)
    if hp_ap_amp != 1.0:
        ap_total *= hp_ap_amp
    # Replace ctx with a copy carrying the boosted AP. AbilityContext is
    # frozen - use dataclasses.replace.
    ctx = replace(ctx, ap=ap_total)

    # Build-wide damage amps applied at per-cast level (not per-spell -
    # amps don't discriminate between Q and W). Folded into ``damage_amp``
    # which multiplies the post-mitigation per-cast damage.
    damage_amp = total_damage_amp_multiplier(item_effects)
    damage_amp *= total_target_bonus_hp_amp_multiplier(item_effects, target_bonus_hp)
    damage_amp *= total_giant_slayer_multiplier(
        item_effects, target_max_hp, ctx.caster_max_hp,
    )
    magic_amp = total_magic_amp_multiplier(item_effects)

    # Effective resists: armor pipeline mirrors compute_dps via
    # ``effective_target_armor`` - flat reduction -> % reduction -> %
    # pen -> flat pen (lethality is level-scaled into the flat-pen
    # term). Magic has the symmetric pipeline (Void Staff %,
    # Sorcerer's Shoes flat).
    target_armor_eff = effective_target_armor(target_armor, item_effects, level)
    target_mr_eff = effective_target_mr(target_mr, item_effects)

    # ENGINE 1.23.0 (2026-05-20) - ability-haste consumption.
    # Read the engine-exposed aramAbilityHaste delta (stripped to 0
    # outside ARAM mode by ``_total_ability_haste``).
    # ENGINE 1.24.0 (2026-05-21) - item-AH lane wired via
    # ``_item_ability_haste`` registry. ``base_ah`` is the sum of flat
    # AH across the build's item ids (DDragon items.json strips AH from
    # the structured ``stats`` block, so the registry carries the
    # parsed-from-description values). SR Black Cleaver + Cosmic Drive
    # = 20 + 25 = 45 AH -> 7s base CD -> 4.83s effective. Single
    # haste-total applies uniformly to all 4 spell keys (Q/W/E/R) at
    # the engine layer - per-spell amplifiers are out of scope.
    base_ah = total_item_ability_haste(resolved.item_ids)
    total_ah = _total_ability_haste(resolved.stats, mode, base_ah=base_ah)
    # Forward the tenacity multiplier for downstream EHP consumers.
    # NOT consumed in this slice - see module-level TODO.
    aram_tenacity_mult = float(resolved.stats.get("aram_tenacity_mult", 1.0))

    # Resolve forms for Q/W/E/R. Champions may lack a key in the snapshot
    # - surface a zero spell rather than raising so partial coverage is
    # tolerated.
    if not abil_snap.has_champion(resolved.champion_id):
        return _empty_result(
            snapshot, resolved.champion_id, level, item_ids, mode,
            target_armor, target_mr, target_max_hp, target_bonus_hp,
            max_priority, block_strategy,
            max_priority_source=max_priority_source,
            form_index_source=form_index_source,
            form_index_resolved=form_index_overrides,
            block_index_source=block_index_source,
            block_index_resolved=block_index_overrides,
            champion_name=resolved.champion_name,
            note=f"champion {resolved.champion_id!r} absent from abilities snapshot",
        )
    per_key_forms = abil_snap.get_abilities(resolved.champion_id)
    overrides = form_index_overrides or {}
    block_overrides = block_index_overrides or {}

    per_spell: list[AbilitySpellDps] = []
    forms_for_classification: list[AbilityForm] = []
    for key in SPELL_KEYS:
        forms = per_key_forms.get(key, ())
        if not forms:
            per_spell.append(_zero_spell(key, "missing", -1, notes=(
                f"no {key} ability recorded for {resolved.champion_id} - skipped",
            )))
            continue
        form_idx = overrides.get(key, 0)
        if form_idx < 0 or form_idx >= len(forms):
            form_idx = 0
        form = forms[form_idx]
        forms_for_classification.append(form)
        rank = rank_at_level(key, level, max_priority=max_priority)
        if rank < 0:
            per_spell.append(_zero_spell(
                key, form.name, form_idx,
                notes=(f"{key} locked at level {level}",),
            ))
            continue
        # Phase 5.9.19 (s206): when form_idx != 0, pass form 0 as fallback
        # so non-form-0 entries with cooldown=None inherit from the parent
        # form's CD list (Riven R / Renekton E / AurelionSol R / Qiyana Q).
        fallback = forms[0] if form_idx != 0 else None
        base_cooldown = _form_cooldown_at_rank(form, rank, fallback_form=fallback)
        # ENGINE 1.23.0 - apply haste formula to the rank cooldown so
        # the theoretical fallback rate + the surfaced .cooldown field
        # reflect the operator's true rotation cadence. Identity for
        # total_ah == 0 (SR mode + most ARAM champions).
        cooldown = _effective_ability_cd(base_cooldown, total_ah)
        cost = _form_cost_at_rank(form, rank)
        # C1 (item 246, gap-plan Phase C1): staged-amp block-route. Under
        # apply_ability_amps, route a staged candidate (Hwei Q f2 "Maximum
        # Damage" ceiling) to the block that already models its full value -
        # avoids the double-counting an amp would cause. Gated on the flag so
        # the default path is byte-identical, and takes precedence over the
        # standard block_overrides for that (champion, key, form) only. Sion Q
        # needs no route: champion_block_index.json {Q:2} already selects its
        # Maximum block by default (the s191 routing predates this seam).
        _staged_route = (
            _staged_amp_block_route_for(resolved.champion_id, key, form.form_index)
            if apply_ability_amps else None
        )
        # Phase 5.9 (s191): if this key has a block_index override (caller
        # or per-(champion, key) registry), switch to "indexed" strategy
        # with that specific block; otherwise honor the global block_strategy.
        if _staged_route is not None:
            raw_dpc = _select_blocks(
                form.damage_blocks, rank, ctx, "indexed",
                block_index=_staged_route,
            )
        elif key in block_overrides:
            raw_dpc = _select_blocks(
                form.damage_blocks, rank, ctx, "indexed",
                block_index=block_overrides[key],
            )
        else:
            raw_dpc = _select_blocks(form.damage_blocks, rank, ctx, block_strategy)
        post_mode = raw_dpc * mode_mult
        # Per-spell magic_amp only applies to magic damage (Abyssal Mask
        # Unmake doesn't touch physical Garen Q or true Talon E).
        dt = (form.damage_type or "MAGIC").upper()
        spell_magic_amp = magic_amp if dt == "MAGIC" else 1.0
        # GAP 1 (item 239): opt-in ability self-damage-amp (Illaoi Q always-on,
        # Mordekaiser Q isolation, Hwei/Sion charge, etc). Default OFF -> 1.0 ->
        # byte-identical to prior. Only base=="ability" entries fire here; base==
        # "aa" entries are AA empowerments inert in ability_dps.
        amp_factor = 1.0
        if apply_ability_amps:
            _amp_entry = _ability_amp_for(resolved.champion_id, key, form.form_index)
            if _amp_entry is not None and _amp_entry.base == "ability":
                amp_factor = _amp_multiplier(_amp_entry, rank, _DEFAULT_AMP_PROBABILITY)
            # C2x (item 257): cross-spell self-state amp - a DIFFERENT spell's
            # rank + active buff scales THIS spell (AurelionSol Q amplified by W
            # Astral Flight's flat-damage modifier while W flight is active). The
            # magnitude is indexed by the SOURCE spell's rank (resolved at this
            # level via rank_at_level) and gated on the W-flight self-state
            # midpoint. Skipped when the source spell is unleveled (rank < 0 ->
            # no buff). Multiplies on top of any same-form ability amp.
            _xs_entry = _cross_spell_amp_for(resolved.champion_id, key, form.form_index)
            if _xs_entry is not None:
                _src_rank = rank_at_level(
                    _xs_entry.source_key, level, max_priority=max_priority
                )
                if _src_rank >= 0:
                    amp_factor *= _amp_multiplier(
                        _xs_entry, _src_rank, _DEFAULT_AMP_PROBABILITY
                    )
        # Build-wide damage_amp + spell-magic_amp scale per-cast pre-mit.
        post_amps = post_mode * damage_amp * spell_magic_amp * amp_factor
        mit_factor = _mitigation_factor(form.damage_type, target_armor_eff, target_mr_eff)
        post_mit = post_amps * mit_factor

        measured = get_spell_casts_per_sec(resolved.champion_name, key, mode)
        cps_source = "measured"
        mana_uptime = 1.0
        if measured <= 0:
            theoretical = (1.0 / cooldown) if cooldown > 0 else 0.0
            mana_uptime = _mana_uptime_factor(cost, cooldown, ctx, form.resource)
            measured = theoretical * mana_uptime
            cps_source = "theoretical_with_mana_uptime" if theoretical > 0 else "missing"

        dps = post_mit * measured
        # ENGINE 1.29.0 (2026-05-21) - per-spell CC duration extractor.
        # Reads ``_PER_SPELL_CC_DURATIONS`` (empty at 1.29.0, forward-marker
        # for a future EHP-vs-CC blended scorer / fight-sim consumer). The
        # post-tenacity tuple is the same shape with each element passed
        # through ``effective_cc_duration(base, aram_tenacity_mult)``;
        # identity in SR + non-ARAM modes; lengthened in ARAM for 15
        # champs with aramTenacity > 1.0.
        cc_base = _per_spell_cc_for(resolved.champion_id, key)
        cc_post_ten = _apply_tenacity_to_cc_tuple(cc_base, aram_tenacity_mult)
        per_spell.append(AbilitySpellDps(
            key=key,
            form_name=form.name,
            form_index=form_idx,
            rank=rank,
            cooldown=cooldown,
            cost=cost,
            damage_type=form.damage_type,
            resource=form.resource,
            raw_damage_per_cast=raw_dpc,
            post_mode_damage_per_cast=post_mode,
            post_mitigation_damage_per_cast=post_mit,
            casts_per_sec=measured,
            casts_per_sec_source=cps_source,
            mana_uptime_factor=mana_uptime,
            dps=dps,
            base_cooldown=base_cooldown,
            total_ability_haste=total_ah,
            cc_duration_s=cc_base,
            cc_duration_post_tenacity=cc_post_ten,
        ))

    total_dps = sum(s.dps for s in per_spell)
    # DSV4 (1.127.0): Spear of Shojin Focused Will ability/passive amp.
    # assume_ability_amp=False -> no multiply, byte-identical. When True, the
    # per-stack amp (3%/stack, 4 stacks = 12%) scales the spell ability damage;
    # the item DoT procs added below are NOT amped (conservative - they are a
    # separately-modeled passive layer the single-rotation model already counts).
    if assume_ability_amp:
        ability_amp_bonus = total_ability_damage_amp(
            item_effects, _ASSUMED_ABILITY_AMP_STACKS
        )
        if ability_amp_bonus > 0.0:
            total_dps *= 1.0 + ability_amp_bonus
    # DSV6 (1.152.0): assume_magic_burst is accepted for caller API symmetry with
    # compute_burst_damage but is DELIBERATELY INERT here (byte-identical ON or
    # OFF). The on-cast magic procs the seam values (Luden's Echo / Stormsurge
    # Squall / Malignance Hatefog) are a one-shot burst magnitude, not sustained
    # ability-rotation DPS - folding a one-shot magnitude into this per-second
    # metric would be wrong-units, and compute_dps already values these at their
    # PeriodicProc rate (ability_dot_only=False), so adding them here would also
    # partially double-count. The burst-window valuation lives in
    # compute_burst_damage; compute_ability_dps owns only the sustained ability
    # rotation + ability-DoT burns (the proc layer below, ability_dot_only=True).
    _ = assume_magic_burst  # documented-inert seam; see comment above
    # DSV1 (P6-G5 residual 1): complete the compute_dps item-handling mirror.
    # The amp + pen layers above (lines ~950-995) already mirror compute_dps so
    # the two scorers agree on item value; the time-based item PERIODIC procs
    # were the missing half. Ability-triggered burn DoTs (Liandry's Torment
    # %max-HP burn, Blackfire's Baleful Blaze, Demonic's Azakana's Gaze) plus
    # the other every_n_seconds AP procs (Malignance, Stormsurge, Luden's,
    # spellblades) deal real sustained magic the single-rotation ability model
    # omitted - the same "always-active convention" compute_dps already uses.
    # Reuse _periodic_proc_dps directly: every_n_attacks procs are skipped
    # (total_attacks=0.0), and duration cancels for time-based procs so 1.0 is
    # a unit anchor. The proc DPS already carries magic-amp + effective-resist
    # mitigation (magic->MR, physical->armor, true unmitigated).
    proc_ctx = CallContext(
        base_ad=ctx.base_ad,
        bonus_ad=ctx.bonus_ad,
        level=level,
        target_armor=target_armor_eff,
        target_mr=target_mr_eff,
        ap=ctx.ap,
        target_max_hp=target_max_hp,
        caster_max_hp=ctx.caster_max_hp,
        caster_bonus_hp=ctx.caster_bonus_hp,
        target_bonus_hp=target_bonus_hp,
        caster_max_mp=ctx.caster_max_mp,
        ult_casts_per_sec=get_ult_casts_per_sec(resolved.champion_name, mode),
        target_current_hp_pct=target_current_hp_pct,
    )
    item_proc_dps = _periodic_proc_dps(
        item_effects, 0.0, 1.0, target_armor_eff, target_mr_eff,
        mode_mult, proc_ctx, magic_amp=magic_amp, ability_dot_only=True,
    )
    if item_proc_dps > 0.0:
        total_dps += item_proc_dps
    primary = _classify_primary_scaling(per_spell, forms_for_classification)

    notes: list[str] = list(resolved.notes)
    if mode == "ARAM" and mode_mult != 1.0:
        notes.append(f"ARAM aramDamageDealt={mode_mult:.3f} on per-cast damage")
    n_missing = sum(1 for s in per_spell if s.casts_per_sec_source == "missing")
    if n_missing:
        notes.append(
            f"{n_missing}/4 spells had no measured cast rate AND no cooldown "
            "fallback - DPS contribution is 0"
        )
    n_theoretical = sum(1 for s in per_spell if s.casts_per_sec_source == "theoretical_with_mana_uptime")
    if n_theoretical:
        notes.append(
            f"{n_theoretical}/4 spells used theoretical 1/cooldown x mana_uptime "
            f"(no measured rewind data for {resolved.champion_name} x {mode})"
        )
    if ap_amp != 1.0:
        notes.append(
            f"AP amplified x{ap_amp:.3f} by item amp (effective AP for ability "
            f"scaling: {ap_total:.1f})"
        )
    if hp_ap_amp != 1.0:
        notes.append(
            f"AP HP-scaled amp x{hp_ap_amp:.3f} (Demonic Embrace at "
            f"{ctx.caster_max_hp:.0f} HP)"
        )
    if ap_from_hp > 0:
        notes.append(
            f"AP cross-derived from bonus HP: +{ap_from_hp:.1f} "
            "(Riftmaker Void Infusion)"
        )
    if stacked_ap > 0:
        notes.append(f"Mejai's stacked AP: +{stacked_ap:.0f}")
    if damage_amp != 1.0:
        notes.append(
            f"build damage amp x{damage_amp:.3f} "
            f"(+{(damage_amp - 1.0) * 100:.1f}% to all ability damage)"
        )
    if magic_amp != 1.0:
        notes.append(
            f"magic damage amp x{magic_amp:.3f} on magic-typed spells "
            "(Abyssal Mask Unmake)"
        )
    if item_proc_dps > 0.0:
        notes.append(
            f"item burn/proc DPS +{item_proc_dps:.1f} folded into total "
            "(time-based item periodics: Liandry / Blackfire / Demonic burns etc.)"
        )
    if target_armor_eff != target_armor:
        notes.append(
            f"effective target armor {target_armor:.1f} -> {target_armor_eff:.1f} "
            "after reduction + lethality + % pen"
        )
    if target_mr_eff != target_mr:
        notes.append(
            f"effective target MR {target_mr:.1f} -> {target_mr_eff:.1f} "
            "after flat + % magic pen"
        )

    if block_overrides:
        notes.append(
            "block_index overrides applied: "
            + ", ".join(f"{k}={block_overrides[k]}" for k in sorted(block_overrides))
        )

    # ENGINE 1.23.0: surface a note when haste actually shortened or
    # lengthened the rotation so consumers can see the consumed delta.
    if total_ah != 0.0:
        notes.append(
            f"ARAM aramAbilityHaste={total_ah:+.0f} on per-spell cooldowns "
            f"(eff_cd = base / (1 + AH/100))"
        )

    return AbilityDpsResult(
        champion_id=resolved.champion_id,
        champion_name=resolved.champion_name,
        level=level,
        item_ids=resolved.item_ids,
        mode=mode,
        target_armor=target_armor,
        target_mr=target_mr,
        target_max_hp=target_max_hp,
        target_bonus_hp=target_bonus_hp,
        mode_multiplier=mode_mult,
        per_spell=tuple(per_spell),
        total_ability_dps=total_dps,
        primary_scaling=primary,
        max_priority=tuple(max_priority),
        max_priority_source=max_priority_source,
        block_strategy=block_strategy,
        form_index_source=form_index_source,
        form_index_resolved=dict(form_index_overrides),
        block_index_source=block_index_source,
        block_index_resolved=dict(block_index_overrides),
        stats=dict(resolved.stats),
        aram_ability_haste=total_ah,
        aram_tenacity_mult=aram_tenacity_mult,
        notes=tuple(notes),
    )


# --- helpers for partial / empty results --------------------------------------


def _zero_spell(key: str, form_name: str, form_index: int,
                notes: tuple[str, ...] = ()) -> AbilitySpellDps:
    return AbilitySpellDps(
        key=key, form_name=form_name, form_index=form_index, rank=-1,
        cooldown=0.0, cost=0.0, damage_type=None, resource=None,
        raw_damage_per_cast=0.0, post_mode_damage_per_cast=0.0,
        post_mitigation_damage_per_cast=0.0,
        casts_per_sec=0.0, casts_per_sec_source="missing",
        mana_uptime_factor=1.0, dps=0.0, notes=notes,
    )


def _empty_result(
    snapshot: DataSnapshot,
    champion_id: str,
    level: int,
    item_ids: Optional[Iterable[str | int]],
    mode: str,
    target_armor: float,
    target_mr: float,
    target_max_hp: float,
    target_bonus_hp: float,
    max_priority: tuple[str, str, str],
    block_strategy: str,
    *,
    max_priority_source: str = "default",
    form_index_source: str = "default",
    form_index_resolved: Optional[dict[str, int]] = None,
    block_index_source: str = "default",
    block_index_resolved: "Optional[dict[str, int | list[int] | dict[str, int | list[int]]]]" = None,
    champion_name: str | None = None,
    note: str = "",
) -> AbilityDpsResult:
    """Build a structured zero-DPS result when ability data is missing.

    Surfaces the cause via ``notes`` so consumers can disambiguate
    "no data" from "0 DPS". Used by ``compute_ability_dps`` when the
    snapshot can't be loaded or the champion is absent.
    """
    name = champion_name or champion_id
    items = tuple(str(i) for i in (item_ids or ()))
    per_spell = tuple(
        _zero_spell(k, "missing", -1, notes=("ability data unavailable",))
        for k in SPELL_KEYS
    )
    return AbilityDpsResult(
        champion_id=champion_id, champion_name=name, level=level,
        item_ids=items, mode=mode,
        target_armor=target_armor, target_mr=target_mr,
        target_max_hp=target_max_hp, target_bonus_hp=target_bonus_hp,
        mode_multiplier=1.0, per_spell=per_spell, total_ability_dps=0.0,
        primary_scaling="MIXED",
        max_priority=tuple(max_priority),
        max_priority_source=max_priority_source,
        block_strategy=block_strategy,
        form_index_source=form_index_source,
        form_index_resolved=dict(form_index_resolved or {}),
        block_index_source=block_index_source,
        block_index_resolved=dict(block_index_resolved or {}),
        stats={},
        notes=(note,) if note else (),
    )

