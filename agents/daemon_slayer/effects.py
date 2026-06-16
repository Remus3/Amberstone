"""Phase 4 - per-item conditional effects (thin slice + first expansion).

DDragon item ``stats`` blocks only carry the flat/percent stat lines
(AD, AS, crit, hp, ...). The DPS-relevant text - IE's crit-damage bump,
Kraken's every-3rd-attack proc, Stormrazor's Energized, Trinity Force's
Spellblade - lives in the description prose with the numbers stripped.
This module pins those numbers per-patch as Python constants so ``dps.py``
can layer them onto the rotation math.

Schema layers
~~~~~~~~~~~~~

* ``crit_damage_bonus`` - flat add to ``DEFAULT_CRIT_BONUS`` (IE).
* ``periodic`` - single ``PeriodicProc`` per item (every-N-attacks or
  every-N-seconds). ``bonus_damage`` is either a constant float OR a
  callable ``(CallContext) -> float`` for stat-scaling procs (TriForce
  spellblade off ``base_ad``, Wit's End off ``level``, etc.).
* ``armor_pen_pct`` / ``armor_pen_flat`` - physical penetration applied
  multiplicatively / additively after armor reduction.
* ``armor_reduction_pct`` - Black-Cleaver-style reduction applied BEFORE
  pen. Modeled at sustained-DPS values (full stacks); burst rotations
  see less.
* ``defensive_only`` - documents items whose effect is non-DPS (lifeline
  shields, executes, Grievous Wounds, anti-shield). Lives here so the
  schema is exercised end-to-end and "did we forget item X?" becomes a
  one-grep check.

Numbers below are pinned to patch 16.9.1 (matches
``data/daemon_slayer/current.txt``). Values are honest patch-pinned
approximations; promote to callables when the first item demands it
(Phase 4 expansion 2026-05-03 promoted the schema for TriForce, Wit's
End, Runaan's, Voltaic, Sundered Sky, Guinsoo's). When the snapshot
bumps, the extractor manifest will diverge from this constant table
and a patch-notes diff re-pins the values.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Union

from ._effects_data import ITEM_EFFECTS
from ._effects_types import (
    CallContext,
    DamageFn,
    ItemEffect,
    MAGICAL,
    PHYSICAL,
    PeriodicProc,
    TRUE,
    _DAMAGE_TYPES,
)


def collect_effects(item_ids: Iterable[str | int]) -> list[ItemEffect]:
    """Return the ItemEffect entries that match the build's items, in order.

    Items without an entry in ``ITEM_EFFECTS`` are silently skipped - they
    contribute their stat-block to the engine via ``stats.aggregate_item_stats``
    but no conditional layer applies. Duplicate item IDs (e.g. two IEs)
    are kept so the engine's existing item-stack semantics carry through;
    the engine does not enforce per-item uniqueness.

    Phase 4 batch 10 (2026-05-04): items that share a non-empty
    ``unique_passive_key`` are de-duplicated first-seen-wins. The duplicate
    item still contributes its stat block via ``aggregate_item_stats``
    (which lives outside this function), so the AD/HP/etc. from the
    duplicate item is unaffected - only the proc / armor-pen effects
    are dropped. Default ``unique_passive_key=""`` skips dedup so every
    pre-batch-10 entry passes through unchanged.
    """
    out: list[ItemEffect] = []
    seen_keys: set[str] = set()
    for iid in item_ids:
        eff = ITEM_EFFECTS.get(str(iid))
        if eff is None:
            continue
        if eff.unique_passive_key:
            if eff.unique_passive_key in seen_keys:
                continue
            seen_keys.add(eff.unique_passive_key)
        out.append(eff)
    return out


def total_crit_damage_bonus(effects: Iterable[ItemEffect]) -> float:
    """Sum ``crit_damage_bonus`` across the build's effects."""
    return sum(e.crit_damage_bonus for e in effects)


def total_bonus_ap_from_hp(effects: Iterable[ItemEffect], caster_bonus_hp: float) -> float:
    """Cross-derived AP from caster bonus HP (Phase 4 batch 15).

    Sums ``ap_per_bonus_hp_pct * caster_bonus_hp`` across the build.
    Riftmaker's Void Infusion (2% bonus HP -> AP) is the first user;
    additive across multiple cross-derivation items if any land later
    (sums commute, no buff-system multiplicative subtlety here - each
    item's contribution is its own independent stat add).

    Returns 0.0 when no item carries the field - pre-batch-15 callers
    pass through unchanged. Negative ``caster_bonus_hp`` (defensive
    paranoia: shouldn't happen - engine floors at zero) is clamped at
    the call site, not here.
    """
    if caster_bonus_hp <= 0:
        return 0.0
    return sum(e.ap_per_bonus_hp_pct * caster_bonus_hp for e in effects)


def total_crit_chance_bonus(
    effects: Iterable[ItemEffect],
    caster_bonus_hp: float,
) -> float:
    """Sum item-effect-contributed crit chance (Phase 4 batch 26).

    Two flavors compose additively, returning a single fraction (0.0-N)
    intended to be added to the build's ``stats["crit"]`` and clamped at
    1.0 by the caller (compute_dps). The clamp lives at the call site so
    intermediate sums are exposed faithfully - a build with 60% Yun Tal
    flat + 50% Atma scaled would *want* 1.10 here so the caller can
    decide what to do with it (currently: cap at 100% - League's ceiling).

    - ``crit_chance_bonus_flat`` contributes unconditionally.
    - HP-scaled contributes only when both ``crit_chance_bonus_max_pct``
      AND ``crit_chance_bonus_per_bonus_hp_cap`` are positive AND
      ``caster_bonus_hp`` is positive. Otherwise the linear ramp would
      either divide by zero or contribute negative values - defensive.
      Atma's Reckoning is the canonical example: max=0.30, cap=3000 ->
      ramp = min(1.0, caster_bonus_hp / 3000) -> 0.0 at 0 bonus HP, 0.15
      at 1500, 0.30 at 3000+, capped past the threshold.

    Returns 0.0 when no item carries either field (pre-batch-26 builds
    pass through unchanged). Same return-zero-on-no-contribution shape
    as ``total_bonus_ap_from_hp``.
    """
    total = 0.0
    for e in effects:
        total += e.crit_chance_bonus_flat
        max_pct = e.crit_chance_bonus_max_pct
        cap = e.crit_chance_bonus_per_bonus_hp_cap
        if max_pct > 0 and cap > 0 and caster_bonus_hp > 0:
            ramp = min(1.0, caster_bonus_hp / cap)
            total += max_pct * ramp
    return total


def total_damage_amp_multiplier(effects: Iterable[ItemEffect]) -> float:
    """Multiplicative damage-amp factor across the build (Phase 4 batch 14).

    League stacks combat-state damage amplifiers via the buff system -
    Riftmaker's 8% x Conqueror's 8% = 1.08 * 1.08 = 1.1664x, not 1.16x.
    Returns 1.0 when no item carries an amp (pre-batch-14 baseline) so
    every existing rotation calculation passes through unchanged.

    The 1.0 floor matters even when items are present - only items with
    a non-zero ``damage_amp_pct`` contribute. Stat-only / pen-only /
    proc-only items skip the multiplication entirely.
    """
    factor = 1.0
    for e in effects:
        if e.damage_amp_pct:
            factor *= (1.0 + e.damage_amp_pct)
    return factor


def total_ap_amp_multiplier(effects: Iterable[ItemEffect]) -> float:
    """Multiplicative AP amplifier across the build (Phase 4 batch 32).

    Rabadon's Deathcap "Magical Opus" multiplies total AP by 1.30.
    Applied at DPS time: ``compute_dps`` multiplies the effective AP used
    by proc scaling and pen formulas by this factor before building
    ``CallContext``. Raw stat block is unchanged - same separation as
    ``ap_per_bonus_hp_pct`` (batch 15).

    Returns 1.0 when no item carries the field (pre-batch-32 builds pass
    through unchanged). Stacks multiplicatively per League's buff-system
    semantics - current patch has only Rabadon's, so the product is
    either 1.0 or 1.30.
    """
    factor = 1.0
    for e in effects:
        if e.ap_amp_pct:
            factor *= (1.0 + e.ap_amp_pct)
    return factor


def total_magic_amp_multiplier(effects: Iterable[ItemEffect]) -> float:
    """Magic-only damage multiplier from target-debuff auras (Phase 4 batch 34).

    Abyssal Mask's "Unmake" causes nearby enemies to take 12% more magic
    damage from ALL sources. Modeled as a caster-side multiplier on
    magic-type proc DPS only - does NOT amplify physical auto-attack
    damage (unlike the general ``damage_amp_pct`` path). Applied inside
    ``_periodic_proc_dps`` per-proc when ``damage_type != PHYSICAL``.

    Returns 1.0 when no item carries the field. Stacks multiplicatively
    per League's buff-system semantics.
    """
    factor = 1.0
    for e in effects:
        if e.magic_amp_pct:
            factor *= (1.0 + e.magic_amp_pct)
    return factor


def total_target_bonus_hp_amp_multiplier(
    effects: Iterable[ItemEffect],
    target_bonus_hp: float,
) -> float:
    """Target-conditional multiplicative amp factor (Phase 4 batch 19).

    Each item with a non-zero ``target_bonus_hp_amp_max_pct`` contributes
    ``min(max_pct, max_pct * target_bonus_hp / cap)``: a linear ramp from
    0 to ``max_pct`` that caps once the target's bonus HP reaches
    ``cap``. LDR Giant Slayer is the canonical example - 0% at 0 bonus
    HP, 7.5% at 750, 15% at 1500, 15% past 1500.

    Stacks multiplicatively with ``total_damage_amp_multiplier`` per
    League's buff-system semantics (batch 14 doctrine). Returns 1.0
    when ``target_bonus_hp <= 0`` OR when no item carries the field -
    pre-batch-19 callers (no target_bonus_hp signal) and pre-batch-19
    builds (no Giant Slayer) both pass through unchanged.

    ``cap <= 0`` is treated as "no scaling defined" and contributes 0
    (defensive guard against partial item entries).
    """
    if target_bonus_hp <= 0:
        return 1.0
    factor = 1.0
    for e in effects:
        max_pct = e.target_bonus_hp_amp_max_pct
        cap = e.target_bonus_hp_amp_cap
        if max_pct <= 0 or cap <= 0:
            continue
        ramp = min(1.0, target_bonus_hp / cap)
        factor *= (1.0 + max_pct * ramp)
    return factor


def total_giant_slayer_multiplier(
    effects: Iterable[ItemEffect],
    target_max_hp: float,
    caster_max_hp: float,
) -> float:
    """Giant Slayer target HP advantage damage amp (Phase 4 batch 38).

    Perplexity's Giant Slayer deals 0-15% increased damage based on how
    much more max HP the target has vs the caster (0.6% per 100 HP diff,
    capped at 15%). Keyed off MAX HP difference - distinct from LDR's
    ``target_bonus_hp_amp`` which is keyed off target BONUS HP only.

    Returns 1.0 when the caster out-HPs the target OR when no item
    carries the schema. Stacks multiplicatively per League's buff-system
    semantics (batch 14 doctrine).
    """
    hp_diff = max(0.0, target_max_hp - caster_max_hp)
    if hp_diff == 0.0:
        return 1.0
    factor = 1.0
    for e in effects:
        if e.giant_slayer_pct_per_100hp:
            amp = min(e.giant_slayer_max_pct, hp_diff / 100.0 * e.giant_slayer_pct_per_100hp)
            factor *= (1.0 + amp)
    return factor


def total_caster_hp_scaled_ap_amp(
    effects: Iterable[ItemEffect],
    caster_max_hp: float,
) -> float:
    """Caster max-HP-scaled multiplicative AP amplifier (batch 56).

    Demonic Embrace (444637 Arena) Sinister Pact: +1.5% AP per 100 current HP,
    capped at 45% (3000 HP threshold). Modeled with caster max HP as a sustained
    approximation. Applied multiplicatively and stacks with Rabadon's ap_amp_pct.

    Returns 1.0 when caster_max_hp <= 0 or no item carries the field (pre-batch-56
    builds pass through unchanged). ``cap <= 0`` items are skipped defensively.
    """
    if caster_max_hp <= 0:
        return 1.0
    factor = 1.0
    for e in effects:
        rate = e.ap_amp_pct_per_100_caster_hp
        cap = e.ap_amp_pct_per_100_caster_hp_cap
        if rate <= 0 or cap <= 0:
            continue
        amp = min(cap, caster_max_hp / 100.0 * rate)
        factor *= (1.0 + amp)
    return factor


def total_stacked_ap(effects: Iterable[ItemEffect]) -> float:
    """Sum kill-stacking AP not captured in DDragon item stat blocks (batch 54).

    Mejai's Soulstealer Glory grants 5 AP per stack (max 25 = 125 AP).
    Engine pins at full stacks - same sustained-peak convention as Black
    Cleaver's full-stack armor reduction. Returns 0.0 when no item carries
    the field - pre-batch-54 builds pass through unchanged.
    """
    return sum(e.bonus_ap_stacked for e in effects)


def total_conditional_as(effects: Iterable[ItemEffect]) -> float:
    """Sum conditional bonus AS from uptime-weighted passives (batch 54).

    Yun Tal Wildarrows Flurry: 30% AS for 6s on-champion-attack (30s CD,
    attack-driven CD reduction). Sustained uptime ~ 27% at typical ADC AS
    with 25% crit -> effective contribution = 0.30 x 0.27 ~ 0.08 bonus AS.
    Added to stats_for_rotation["as"] in compute_dps so attack counts in
    each rotation reflect the conditional boost. Returns 0.0 when no item
    carries the field.
    """
    return sum(e.bonus_as_conditional for e in effects)


def total_takedown_bonus_ad(
    effects: Iterable[ItemEffect],
    assumed_stacks: float,
) -> float:
    """Sum on-takedown bonus AD across the build (DSV2, kill-state seam).

    Hubris Eminence grants ``base + per_stack * stacks`` bonus AD on a
    champion takedown (Meraki 16.12.1: "15 (+2 per stack)"). ``assumed_stacks``
    is the consumer's kill-state assumption (``dps._ASSUMED_TAKEDOWN_STACKS``
    = 1 -> 15 + 2*1 = 17 AD). Returns 0.0 when no item carries the field, so a
    build without Hubris contributes nothing even with the seam ON. Additive
    across items per the engine's stat-stacking convention (no current pair of
    takedown-AD items, but sums commute if one lands later).
    """
    return sum(
        e.takedown_bonus_ad_base + e.takedown_bonus_ad_per_stack * assumed_stacks
        for e in effects
    )


def total_execute_max_hp_pct(effects: Iterable[ItemEffect]) -> float:
    """Sum the kill-state execute threshold across the build (DSV2 seam).

    The Collector's Death executes a champion left below 5% of their MAXIMUM
    health (Meraki 16.12.1). Returned as a fraction of target max HP; the burst
    scorer multiplies by ``target_max_hp`` for the finisher's true-damage worth.
    Returns 0.0 when no item carries the field. Summed additively (only one
    Collector exists today, so in practice this is 0.0 or 0.05).
    """
    return sum(e.execute_max_hp_pct for e in effects)


def effective_target_armor(
    target_armor: float,
    effects: Iterable[ItemEffect],
    level: int | None = None,
) -> float:
    """Apply armor reduction -> % pen -> flat pen pipeline.

    Mirrors League's order: ``armor_reduction_flat`` then
    ``armor_reduction_pct`` (Black Cleaver stacks) reduce target armor
    first; then ``armor_pen_pct`` (LDR / Mortal Reminder / Serylda's)
    reduces what's left; then flat pen (``armor_pen_flat`` raw +
    ``lethality`` level-scaled) subtracts.

    League distinguishes the two rules: REDUCTION can take armor below
    zero (a negative resist amplifies incoming damage via
    ``dps._armor_factor``'s ``2 - 100/(100-R)`` branch); PENETRATION
    cannot push armor below zero and is a no-op on an already
    non-positive post-reduction value. Only the penetration tail floors
    at zero - physical damage against exactly-zero armor uses the
    ``armor=0`` factor (1.0).

    Phase 4 batch 30 (2026-05-04, original): ``level`` is the caster's
    champion level. When provided, lethality contributions are folded
    into the flat-pen sum. ENGINE_VERSION 1.10.0 (2026-05-19,
    audit-lethality): the Riot V14.1 (2024-01) change REMOVED the
    historical level-scaling on lethality - it now grants 1:1 flat armor
    pen at every champion level. The engine reflects that: when a
    ``level`` is supplied, lethality folds in at its full value (the
    factor is 1.0 at every level). The ``level`` parameter is kept on
    the signature for back-compat with the original Phase 4 batch 30
    contract and to honor the "level=None means lethality contributes
    nothing (non-DPS path)" invariant; production caller (compute_dps)
    always passes the resolved level. The pre-V14.1 scaling formula
    ``lethality * (0.6 + 0.4 * level / 18)`` is OBSOLETE - do not
    re-introduce it (it under-applied lethality at every level except
    18, max 37.78 pp under-pen at L1). See League wiki "Armor
    penetration" + V14.1 patch notes.

    Effects without armor modifiers contribute nothing here. Order
    among items in ``effects`` doesn't matter for the FLAT terms (sums
    commute), and for the percent terms because we compose them as the
    product ``Pi (1 - p_i)`` which is also order-independent. The four
    layers (flat-red, pct-red, pct-pen, flat-pen) are then applied in
    fixed order.

    Percent composition rule (ENGINE_VERSION 1.5.1, audit-multi-pen):
    multiple ``armor_pen_pct`` sources compose MULTIPLICATIVELY per
    League's documented mechanic, NOT additively. Two 35% pen items
    yield ``1 - 0.65*0.65 = 0.5775`` (57.75%), not 0.70. The same rule
    applies to multiple ``armor_reduction_pct`` sources. Single-source
    builds are unaffected (composition of one factor is the factor).
    """
    eff_list = list(effects)
    red_flat = sum(e.armor_reduction_flat for e in eff_list)
    # Percent reduction composes MULTIPLICATIVELY across sources per
    # League rule (e.g. Black Cleaver + Obsidian Cleaver). The naive
    # sum would overshoot, e.g. 0.30 + 0.35 = 0.65 vs the real
    # 1 - 0.70*0.65 = 0.545.
    red_pct = 1.0 - _composed_keep_factor(
        e.armor_reduction_pct for e in eff_list
    )
    # Percent armor penetration also composes multiplicatively (LDR
    # 0.35 + Serylda 0.35 = 0.5775 effective pen, NOT 0.70). Pre-1.5.1
    # this was an additive sum which over-penetrated multi-pen builds.
    pen_pct = 1.0 - _composed_keep_factor(
        e.armor_pen_pct for e in eff_list
    )
    pen_flat = sum(e.armor_pen_flat for e in eff_list)
    if level is not None:
        lethality_total = sum(e.lethality for e in eff_list)
        if lethality_total > 0:
            # Post-V14.1 (Riot 2024-01): lethality = flat pen 1:1 at all
            # caster levels. The historical (0.6 + 0.4*level/18) scaling
            # was removed in that patch. Engine is on patch 16.10.x so
            # the 1:1 rule is the correct math. ``level`` is retained
            # only as the "lethality contributes nothing" sentinel.
            pen_flat += lethality_total
    if not (red_flat or red_pct or pen_pct or pen_flat):
        # Passthrough - preserves negative armor inputs (external shred,
        # tests of the armor curve itself).
        return target_armor
    if target_armor < 0:
        # Pen / reduction is a no-op on already-negative armor - items
        # don't amplify beyond what the shred already gave.
        return target_armor
    # League rule: armor REDUCTION (flat then %) is applied first and
    # CAN take armor below zero - a negative resist amplifies incoming
    # damage via _armor_factor's ``2 - 100/(100-R)`` branch. Armor
    # PENETRATION (% then flat) is applied next and CANNOT push armor
    # below zero; on an already non-positive post-reduction value it is
    # a pure no-op (you neither penetrate negative armor further nor
    # heal it back toward 0). Flooring the WHOLE pipeline at zero would
    # discard the reduction-driven negative-resist amp (e.g. Flesheater
    # 30 flat armor reduction vs a ~27-armor squishy = -3 effective,
    # ~1.03x physical) - conflating the two distinct League rules.
    armor = target_armor - red_flat       # flat reduction (League order)
    armor = armor * (1.0 - red_pct)      # % reduction (Black Cleaver) - composed
    if armor <= 0.0:
        # Reduction alone already crossed zero - penetration is a no-op.
        return armor
    armor = armor * (1.0 - pen_pct)      # % penetration (LDR / Serylda's) - composed
    armor = armor - pen_flat             # flat penetration (lethality)
    return max(0.0, armor)               # pen cannot go below zero


def effective_target_mr(target_mr: float, effects: Iterable[ItemEffect]) -> float:
    """Apply MR reduction -> % magic pen -> flat magic pen pipeline.

    Mirrors League's order on the magic side: ``mr_reduction_flat``
    then ``mr_reduction_pct`` (Bloodletter's Curse Vile Decay -
    Phase 4 batch 39) reduce MR first; then ``magic_pen_pct`` (Void
    Staff, Cryptbloom) reduces what remains; then ``magic_pen_flat``
    (Sorcerer's Shoes, Shadowflame) subtracts. Same two-rule split as
    the armor side: REDUCTION can take MR below zero (negative MR
    amplifies magic damage via ``_armor_factor``'s negative branch);
    PENETRATION cannot and is a no-op on an already non-positive
    post-reduction value. Only the penetration tail floors at zero.

    Effects without magic-pen or MR-reduction modifiers contribute
    nothing here. Negative MR passes through unchanged - pen and
    reduction are no-ops on already-negative MR.

    Percent composition rule (ENGINE_VERSION 1.5.1, audit-multi-pen):
    multiple ``magic_pen_pct`` sources (Void Staff + Cryptbloom) and
    multiple ``mr_reduction_pct`` sources compose MULTIPLICATIVELY per
    League's documented mechanic, NOT additively. Mirrors the armor-side
    fix in ``effective_target_armor``.
    """
    eff_list = list(effects)
    red_flat = sum(e.mr_reduction_flat for e in eff_list)
    red_pct = 1.0 - _composed_keep_factor(
        e.mr_reduction_pct for e in eff_list
    )
    pen_pct = 1.0 - _composed_keep_factor(
        e.magic_pen_pct for e in eff_list
    )
    pen_flat = sum(e.magic_pen_flat for e in eff_list)
    if not (red_flat or red_pct or pen_pct or pen_flat):
        return target_mr
    if target_mr < 0:
        return target_mr
    # Symmetric to effective_target_armor: MR REDUCTION (flat then %)
    # is applied first and CAN take MR below zero (negative MR amplifies
    # magic damage via _armor_factor's negative branch). MR PENETRATION
    # (% then flat) cannot push MR below zero and is a no-op on an
    # already non-positive post-reduction value. Flesheater carries a
    # pure 30 flat MR reduction (no magic pen), so a low-MR squishy can
    # legitimately go negative.
    mr = target_mr - red_flat            # flat reduction (League order)
    mr = mr * (1.0 - red_pct)           # % reduction (Bloodletter's Curse) - composed
    if mr <= 0.0:
        # Reduction alone already crossed zero - penetration is a no-op.
        return mr
    mr = mr * (1.0 - pen_pct)           # % penetration (Void Staff) - composed
    mr = mr - pen_flat                   # flat penetration (Sorcerer's Shoes)
    return max(0.0, mr)                  # pen cannot go below zero


def _composed_keep_factor(pcts: Iterable[float]) -> float:
    """Return the multiplicative product of ``(1 - p)`` over all sources.

    Empty iterable returns 1.0 (identity / no-op). Single source returns
    ``1 - p`` (unchanged from prior additive behavior for the common
    one-pen-item case). Multiple sources compose multiplicatively per
    League's percent-pen / percent-reduction rule.

    Examples
    --------
    LDR (35%) alone:          keep = 1 - 0.35 = 0.65; pen layer = 0.35
    LDR + Serylda (35%+35%):  keep = 0.65 * 0.65 = 0.4225;
                              effective pen = 0.5775 (NOT 0.70)
    Void + Cryptbloom (40%+30%):  keep = 0.60 * 0.70 = 0.42;
                                  effective pen = 0.58 (NOT 0.70)

    Negative or > 1.0 inputs are not expected from the registry (the
    schema documents pen as 0..1 fractions); they are passed through
    arithmetically so a bad data row produces a sane (if wrong) number
    rather than a divide-by-zero or NaN.
    """
    keep = 1.0
    for p in pcts:
        if p:
            keep *= (1.0 - p)
    return keep
