"""Phase 1 (s174, 2026-05-12) - Tank EHP scorer.

Sibling of ``dps.py``. ``compute_ehp()`` returns the caster's Effective HP
under a given enemy damage profile; ``rank_items_by_ehp()`` scores every
purchasable mode-legal item by how much EHP it adds (mirroring ``rank.py``
shape).

EHP = HP / damage_taken_factor. For physical damage,
``damage_taken_factor = armor_factor(armor) = 100/(100+armor)``
(or the inverted form when armor is negative). For magical, same formula
applied to MR. For true, ``damage_taken_factor = 1.0``. ARAM's
``aramDamageTaken`` modifier multiplies every damage_taken_factor - a
champion with ``aramDamageTaken=0.95`` takes 5% less damage so effective
HP scales by ``1/0.95`` for ALL damage types (including true).

``blended_ehp`` weights physical/magical/true components by caller-supplied
enemy damage shares. ``enemy_ad_share + enemy_ap_share <= 1.0``; remainder
is true-damage share.

Phase 1 deliberate omissions:
* Shield throughput (Sterak's lifeline, Doran's Shield, Bloodthirster) -
  Phase 1.5 (ENGINE 1.27.0, 2026-05-21) shipped lifeline shields;
  Phase 6 (ENGINE 1.28.0, 2026-05-21) added BT Ichorshield via the
  same pipeline. Doran's Shield block-per-source still DEFERRED to
  Phase 6.5+
* Healing throughput (lifesteal, Spirit Visage amp) - Phase 6
  (ENGINE 1.28.0, 2026-05-21) shipped via ItemHeal + heal_amp_pct +
  lifesteal-derived heal pool. Death's Dance Defy heal-on-takedown
  still DEFERRED to Phase 6.5 (takedown-rate uncertain)
* Caster-side enemy pen/reduction (Black Cleaver shred ON the tank,
  Void Staff %MR pen ON the tank) - needs enemy build plumbing

Bonus HP amps (Jak'Sho's Voidborne Resilience +6% bonus resists fully
stacked, Cinderhulk +15% bonus HP) flow through ``build_champion`` already
via the existing stat schema - no new field needed; EHP picks them up
automatically because ``stats["hp"]/["armor"]/["mr"]`` reflect the amp.

ENGINE 1.25.0 (2026-05-21) - aram_tenacity_mult consumer wired (closes the
BACKLOG "Future EHP enemy-CC model" carry from item 113). 17 ARAM champs
carry a non-1.0 ``aramTenacity`` multiplier (engine.py exposes it as
``scaled["aram_tenacity_mult"]`` since 1.19.0). EhpResult now surfaces
the value + ``effective_cc_duration(base_cc_s, tenacity_mult)`` helper
returns the post-tenacity CC duration (tenacity_mult < 1.0 -> shorter
CC; tenacity_mult > 1.0 -> longer CC). The helper is the seam any future
fight-sim or coach-prompt consumer reads; EHP's primary blended_ehp
math is unchanged (CC-duration vs HP-pool is a fundamentally different
axis - the consumer must pair tenacity_mult with their own CC
assumption).

ENGINE 1.28.0 (2026-05-21) - Phase 6 healing throughput. Closes the
``ehp.py:23`` deliberate Phase-6 omission "Healing throughput
(lifesteal, Spirit Visage amp)". Three contributions feed the heal
pool: (a) item-passive heals (Sundered Sky 6610 Lightshield Strike,
100% base AD melee / 50% base AD ranged per one-trigger-per-fight),
(b) lifesteal-derived heal accumulated over the 6s fight window
(``stats.lifesteal * stats.ad * stats.as * 6.0``), (c) the
multiplicative heal amp (Spirit Visage 3065 / Arena 223065 +25%).
Bloodthirster's Ichorshield (3072 / 223072) rides the Phase 1.5 shield
pipeline (full-cap steady-state assumption: 165 L1 -> 315 L18, ANY
damage type). The post-amp heal pool is value-additive at the top of
the damage stack (same place as shields), absorbing all damage types
(heals don't discriminate by damage type in League's model).

Phase 6 deliberate omissions (deferred to Phase 6.5+):
* Death's Dance Defy heal-on-takedown (75% bonus AD over 2s) -
  SHIPPED in ENGINE 1.57.0 (2026-05-25). New ``ItemHeal.takedown_gated``
  schema field + ``_TAKEDOWN_RATE_PER_FIGHT = 0.5`` operator-tunable
  module constant. Consumer-site gating: ``_collect_heals`` multiplies
  the resolved per-trigger magnitude by the takedown rate when the
  flag is set. DD 6333 / Arena 226333 are the first consumers; flipped
  from defensive_only to a real EHP heal contribution.
* Lifesteal post-mitigation accuracy - the lifesteal heal model uses
  pre-armor AD (the EHP scorer is enemy-state-agnostic). Real lifesteal
  heals on post-armor damage, so this over-credits by ~30-40% vs a
  60-90 armor target. Consistent with the rest of EHP's no-enemy-pen
  posture (Phase 1 omission still in force).
* Sundered Sky 6% missing-HP additive - SHIPPED in Phase 6.5
  (ENGINE 1.29.0, 2026-05-21). The
  ``_MISSING_HP_SHARE_FOR_HEALS = 0.5`` module constant introduces a
  single mid-fight HP-share assumption (50% missing HP) distinct from
  the full-HP steady-state convention used elsewhere in the scorer.
  Lightshield Strike fires mid-fight so this is a reasonable approx-
  imation; operator can adjust if calibration data suggests
  otherwise. The base AD piece remains the dominant contributor
  (~103 hp on Aatrox L11 vs ~62 hp from the missing-HP piece).

ENGINE 1.29.0 (2026-05-21) - Phase 6.5 closes the deliberate Phase 6
boundary "Spirit Visage amp on Phase 1.5 SHIELDS". Riot's tooltip on
Spirit Visage 3065 / Arena 223065 Boundless Vitality reads "increases
self-healing and shielding by 25%". The Phase 6 wire amped the heal
pool only; Phase 6.5 extends the SAME multiplier to the shield pool
(Sterak / Shieldbow / Maw / Hexdrinker / BT Ichorshield). The amp is
applied at the EHP-math site (top of damage stack) - the shield_any /
shield_phys / shield_mag / shield_true EhpResult fields stay PRE-amp
for transparency (matching the heal_item_total / heal_lifesteal pre-
amp convention); ``shield_amp_mult`` surfaces the multiplier alongside
``heal_amp_mult``. The two amps are SIBLINGS at the EHP-math top of
the stack, NOT nested (a build with SV + BT does NOT double-amp the
heal pool via the shield amp - heal_total is amped exactly once by
heal_amp_mult; shield_any is amped exactly once by shield_amp_mult;
the two products are added). Same multiplier value (today: only
Spirit Visage at 1.25) but conceptually independent fields so future
heal-only or shield-only amp items stay representable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

from .data_loader import DataSnapshot
from .effects import ITEM_EFFECTS
from ._effects_types import ANY, MAGICAL, PHYSICAL, TRUE
from .engine import build_champion
from ._passive_mitigation_overrides import mitigation_multipliers
from ._passive_flat_mitigation_overrides import flat_mitigation_hp
from ._passive_health_overrides import passive_health_stack_hp
from ._passive_resist_overrides import resist_grants
from ._passive_revive_overrides import revive_multiplier, revive_egg_resist
from ._champion_cc_mitigation_overrides import champion_cc_tenacity_fraction
from ._champion_spell_shield_overrides import champion_spell_shield_fraction
from ._passive_survival_window_overrides import survival_window_multiplier
from .rank import (
    DEFAULT_SLOT_COUNT,
    DEFAULT_TOP_N,
    SORT_KEYS,
    _champion_is_melee,
    _filter_candidates,
    _is_terminal,
    strip_arena_trinkets,
)
from .stats import clamp_level
from .survivability_credit import survivability_item_ids_tank
from ._hsp_amp import sum_wielder_hsp_pct


def _armor_factor(resist: float) -> float:
    """League's resist -> damage-taken multiplier. Mirrors ``dps._armor_factor``.

    Positive resist: ``100 / (100 + resist)``.
    Negative resist (shred): ``2 - 100/(100 - resist)``. Inlined here rather
    than imported from dps.py so the EHP scorer doesn't depend on the DPS
    layer's private helpers.
    """
    if resist >= 0:
        return 100.0 / (100.0 + resist)
    return 2.0 - 100.0 / (100.0 - resist)


def _clamp_pct(value: float) -> float:
    """Clamp a percent-fraction input to ``[0.0, 0.99]``.

    T1-F3 (2026-06-09): the enemy-pen pipeline caps every percent term
    (shred + general %pen) at 0.99 per the lift-doc spec
    (docs/COMPETITOR_LIFT_2026-06-08.md line 60) so a single source can
    never fully zero a resist (mirrors League's 99% shred/pen practical
    ceiling). Negative inputs floor at 0.0 (a percent term cannot heal a
    resist back upward).
    """
    if value <= 0.0:
        return 0.0
    if value >= 0.99:
        return 0.99
    return value


def _effective_resist_after_pen(
    resist: float,
    *,
    shred_pct: float = 0.0,
    pen_pct: float = 0.0,
    flat_pen: float = 0.0,
) -> float:
    """Apply the enemy-side pen pipeline to one of the tank's resists.

    T1-F3 (BACKLOG MED, docs/COMPETITOR_LIFT_2026-06-08.md lines 59-66) -
    the OPT-IN enemy-penetration seam for the EHP scorer. Mirrors the
    DPS-side ``effects.effective_target_armor`` / ``effective_target_mr``
    convention so the two scorers stay consistent, but takes the already-
    summed/composed per-axis inputs the ``compute_ehp`` kwargs expose
    rather than reading an item-effect list (the EHP target is the tank;
    the pen comes from the ENEMY build, plumbed in as scalars).

    Order (spec, ARMOR side): flat reduction -> % shred (clamped
    0..0.99) -> general %pen (multiplicative, already composed by the
    caller into a single fraction) -> lethality / flat pen (subtract
    LAST, post-%). The MR side is the same shape: %shred -> %pen -> flat
    magic pen last. There is no flat-reduction kwarg in the T1-F3 intent
    list, so the flat-reduction step is a no-op here (the seam exposes
    shred / general-%pen / flat-pen only).

    League's two-rule split (preserved from the DPS helper):
    * SHRED is a REDUCTION - it CAN drive the resist below zero, and a
      negative resist amplifies incoming damage via ``_armor_factor``'s
      ``2 - 100/(100-R)`` branch. (Within this seam shred is a single
      clamped-0.99 percent, so it never fully crosses zero on its own,
      but the negative-capable contract is kept for symmetry + a future
      flat-reduction kwarg.)
    * PENETRATION (general %pen, then flat pen / lethality) CANNOT push
      the resist below zero - on an already non-positive post-shred
      value it is a pure no-op, and the flat-pen tail floors at 0.0.

    NOTE on natural-vs-bonus armor: the lift-doc spec asks to split
    natural vs bonus armor IF the codebase already tracks bonus armor
    FOR THE TARGET (so bonus-only pen hits only the bonus portion). The
    EHP scorer's target (the tank) does NOT carry a first-class bonus-
    armor field - ``compute_ehp`` resolves total ``armor`` / ``mr`` from
    the build, and the T1-F3 kwarg list carries no bonus-only-pen input.
    Per the spec fallback, bonus-only pen is therefore APPROXIMATED
    against the total resist here; no bonus-armor field is invented. If
    a bonus-only-pen kwarg is added later, split the resist at the
    flat-reduction step (after computing total - base from
    ``build_champion``'s base_stats) before the % terms.

    ``resist`` already-negative returns unchanged (pen / shred is a
    no-op on negative resist, mirroring the DPS helper). All-zero pen
    inputs return ``resist`` unchanged (identity), so the default keeps
    ``compute_ehp`` byte-identical.
    """
    shred = _clamp_pct(shred_pct)
    pen = _clamp_pct(pen_pct)
    flat = max(0.0, flat_pen)
    if not (shred or pen or flat):
        return resist
    if resist < 0:
        return resist
    r = resist * (1.0 - shred)            # % shred (reduction) - can cross 0
    if r <= 0.0:
        # Shred alone already reached <= 0 - penetration is a no-op.
        return r
    r = r * (1.0 - pen)                   # general % penetration (multiplicative)
    r = r - flat                          # flat pen + lethality (subtract last)
    return max(0.0, r)                    # penetration cannot go below zero


_RANGED_ATTACKRANGE_THRESHOLD = 250.0


def _is_ranged(base_stats: dict) -> bool:
    """Detect ranged-champion status by base attackrange.

    ENGINE 1.27.0 (2026-05-21): used by the shield-throughput scorer to
    pick the ``ItemShield.ranged_modifier`` (Maw / Shieldbow / Hexdrinker
    have ranged shields at 75-80% of melee values per Meraki 16.10.1).
    Threshold 250 separates melee (Yasuo 175 / Aatrox 175 / Sett 125)
    from ranged (Caitlyn 650 / Ezreal 550 / Lux 550). Aphelios and
    similar shifting-form champs default to their base attackrange.
    """
    try:
        return float(base_stats.get("attackrange", 0.0)) > _RANGED_ATTACKRANGE_THRESHOLD
    except (TypeError, ValueError):
        return False


def _collect_shields(
    item_ids: Iterable[str],
    level: int,
    bonus_hp: float,
    bonus_ad: float,
    is_ranged: bool,
) -> tuple[dict[str, float], tuple[tuple[str, str, float], ...]]:
    """Resolve every ``ItemShield`` across the equipped items.

    Returns a tuple of (totals, sources) where:

    * ``totals`` is a dict keyed by shield damage type
      (``"any"``/``"physical"``/``"magical"``/``"true"``) mapping to the
      summed shield_hp; missing keys = 0.0.
    * ``sources`` is a tuple of ``(item_id, damage_type, shield_hp)``
      triples in stable iteration order; used by EhpResult.format_table
      and to_dict for surfacing per-item contributions.

    Items without a ``shield`` field (the 99% case) contribute nothing
    and are silently skipped.
    """
    totals: dict[str, float] = {ANY: 0.0, PHYSICAL: 0.0, MAGICAL: 0.0, TRUE: 0.0}
    sources: list[tuple[str, str, float]] = []
    for item_id in item_ids:
        eff = ITEM_EFFECTS.get(str(item_id))
        if eff is None or eff.shield is None:
            continue
        shield = eff.shield
        hp = shield.resolve_magnitude(
            level=level,
            bonus_hp=bonus_hp,
            bonus_ad=bonus_ad,
            is_ranged=is_ranged,
        )
        if hp <= 0:
            continue
        totals[shield.damage_type] = totals.get(shield.damage_type, 0.0) + hp
        sources.append((str(item_id), shield.damage_type, hp))
    return totals, tuple(sources)


_FIGHT_WINDOW_S = 6.0
"""Phase 6 healing throughput fight-window constant (seconds).

The lifesteal-derived heal pool accumulates over this window:
``lifesteal_pct * total_AD * attack_speed * _FIGHT_WINDOW_S``. 6.0s
matches the engine's existing sustained/burst boundary (compute_dps
weights burst against the ~3s burst window with sustained DPS taking
over after; 6s is a representative full-engagement window for EHP
throughput purposes). Item-passive heals (Sundered Sky Lightshield
Strike) use a one-trigger-per-fight convention and are NOT scaled by
this window - the per-trigger heal magnitude IS the per-fight heal.
"""


_MISSING_HP_SHARE_FOR_HEALS = 0.5
"""Phase 6.5 mid-fight HP-share assumption for items whose heal piece
scales with missing HP.

The EHP scorer's normal convention is full-HP steady-state (no missing
HP). Items like Sundered Sky 6610 carry a 6% missing-HP additive on
their heal piece; this constant introduces a single Phase-6.5 mid-fight
assumption (50% HP missing -> heal scales against 50% of total HP).
Operator can adjust if calibration data suggests a different mid-fight
share. 0.5 is a reasonable mid-fight approximation matching the heal
trigger model (Lightshield Strike fires mid-fight, not at full HP).
"""


_CC_EFFECTIVENESS_FACTOR = 0.5
"""ENGINE 1.33.0 (2026-05-22) EHP-vs-CC blended scorer coefficient.

CC pressure summed across enemy champions does not perfectly translate
into operator EHP loss - CC is interrupted by gaps between casts,
cleansed by QSS / Mercurial / Mikael's, dodged via Flash / dash, and
not perfectly chained inside a 6s fight window. This factor calibrates
the discount applied to ``blended_ehp`` per second of summed enemy
CC pressure.

Math: ``cc_blended_ehp = blended_ehp * (1.0 - cc_pressure_fraction * 0.5)``
where ``cc_pressure_fraction = min(enemy_cc_pressure_s / _FIGHT_WINDOW_S, 1.0)``.

A conservative midpoint - 1.0s of summed enemy CC pressure erodes
0.5s of operator fight-time effectiveness. Operator-tunable via a
single module constant (parallels ``_MISSING_HP_SHARE_FOR_HEALS = 0.5``
Phase 6.5 discipline). Future calibration data from live games may
warrant adjustment; do NOT vary per-enemy or per-spell - the factor
is a coarse aggregate model by design.
"""


_TAKEDOWN_RATE_PER_FIGHT = 0.5
"""ENGINE 1.57.0 (2026-05-25) takedown-gated heal trigger rate.

Death's Dance Defy heals 75% bonus AD over 2s on a champion takedown
(kill or assist within 3s of damage). The per-fight takedown rate is
inherently champion-role / game-state dependent: a carry farming sidelane
sees few takedowns, while a teamfighting bruiser may net 1-2 per skirmish.
This constant approximates the fraction of fights that yield AT LEAST
ONE Defy trigger. 0.5 (default) matches "every other fight on average"
or equivalently "one takedown every two skirmishes" - a conservative
midpoint that does NOT over-credit DD in passive sidelane play and does
NOT under-credit it in active teamfights.

Operator-tunable via a single module constant (parallels
``_MISSING_HP_SHARE_FOR_HEALS = 0.5`` Phase 6.5 discipline and
``_CC_EFFECTIVENESS_FACTOR = 0.5`` ENGINE 1.33.0 precedent).

Applied at the consumer site in ``_collect_heals``: for any ItemHeal
with ``takedown_gated=True``, the resolved per-trigger magnitude is
multiplied by this factor before contributing to the heal pool. The
dataclass ``ItemHeal`` stays convention-agnostic - it composes the
heal magnitude; the consumer applies the gating.

Calibration note: this is a coarse aggregate model by design. Future
calibration data (live rewind_history.db role-by-role takedown rate
analysis) MAY warrant per-role tuning, but the single-constant
discipline is intentional - varying per-build or per-enemy multiplies
the calibration surface area beyond what the data supports.
"""


def _collect_heals(
    item_ids: Iterable[str],
    base_ad: float,
    bonus_hp: float,
    bonus_ad: float,
    is_ranged: bool,
    missing_hp: float = 0.0,
    takedown_rate: float = _TAKEDOWN_RATE_PER_FIGHT,
) -> tuple[float, tuple[tuple[str, float], ...]]:
    """Resolve every ``ItemHeal`` across the equipped items.

    ENGINE 1.28.0 (2026-05-21): Phase 6 healing throughput.

    Returns ``(total_heal_hp, sources)`` where ``sources`` is a tuple of
    ``(item_id, heal_hp)`` pairs in stable iteration order. The total
    is the pre-amp sum (Spirit Visage's amp is applied later in
    ``compute_ehp`` via ``_total_heal_amp``). One-trigger-per-fight
    convention - the per-trigger magnitude IS the per-fight heal (no
    fight-window scaling for item-passive heals; that scaling applies
    only to the lifesteal-derived heal).

    Phase 6.5 (2026-05-21): ``missing_hp`` is the absolute missing-HP
    value (in HP units, NOT a share) that gets threaded into each
    ``ItemHeal.resolve_magnitude`` call. ``compute_ehp`` derives this
    once via ``total_hp * _MISSING_HP_SHARE_FOR_HEALS`` and passes it
    here; items whose heal carries ``missing_hp_pct=0`` (the 99%
    default case) are unaffected.

    ENGINE 1.57.0 (2026-05-25): ``takedown_rate`` (default
    ``_TAKEDOWN_RATE_PER_FIGHT`` = 0.5) gates items whose heal is
    triggered on a champion takedown (kill or assist within a short
    window). For any ``ItemHeal`` with ``takedown_gated=True``, the
    resolved per-trigger magnitude is multiplied by this rate before
    contributing to the totals. Items without the flag (the 99%
    default case) are unaffected. Death's Dance 6333 / Arena 226333
    Defy is the first consumer.

    Items without a ``heal`` field (the ~99% case) contribute nothing
    and are silently skipped.
    """
    total = 0.0
    sources: list[tuple[str, float]] = []
    for item_id in item_ids:
        eff = ITEM_EFFECTS.get(str(item_id))
        if eff is None or eff.heal is None:
            continue
        magnitude = eff.heal.resolve_magnitude(
            base_ad=base_ad,
            bonus_hp=bonus_hp,
            bonus_ad=bonus_ad,
            missing_hp=missing_hp,
            is_ranged=is_ranged,
        )
        if eff.heal.takedown_gated:
            magnitude *= max(0.0, takedown_rate)
        if magnitude <= 0:
            continue
        total += magnitude
        sources.append((str(item_id), magnitude))
    return total, tuple(sources)


def _total_heal_amp(item_ids: Iterable[str]) -> float:
    """Sum the multiplicative heal-amp factor across the equipped items.

    ENGINE 1.28.0 (2026-05-21): returns the ``(1 + heal_amp_pct)``
    product across all items with ``heal_amp_pct > 0`` (today only
    Spirit Visage 3065 / Arena 223065 at 0.25). Multiple amp items
    stack multiplicatively per League's buff-system semantics (same
    doctrine as ``damage_amp_pct`` / Phase 4 batch 14). Default ``1.0``
    when no amp items are equipped (identity multiplier).
    """
    factor = 1.0
    for item_id in item_ids:
        eff = ITEM_EFFECTS.get(str(item_id))
        if eff is None or eff.heal_amp_pct <= 0:
            continue
        factor *= (1.0 + eff.heal_amp_pct)
    return factor


# ENGINE 1.180.0 (R77, 2026-07-05): item-keyed incoming CRIT-DAMAGE REDUCTION.
# Randuin's Omen (SR 3143 / Arena 223143) Resilience "30% reduced critical
# strike damage taken" (ItemEffect.crit_damage_reduction=0.30) was a
# defensive_only NOTE only - the DS ranker gave its signature crit-DR ZERO
# effective-HP credit despite it being a proven WIN buy (rewind_history.db:
# 344 builds, 54.7% WR vs 50.0% baseline). Crit damage is PHYSICAL, so the
# reduction is multiplicative on the physical EHP denominator - the SAME layer
# as the champion percent-DR family (``mitigation_multipliers``), which is
# champion_id-keyed and structurally cannot see items.
#
# The crit-affected SHARE of incoming physical damage is the live feed we lack
# (same class as the flat-mitigation instance count / health-stack count) -
# modeled as a conservative operator-tunable midpoint. A 30% crit-DR at a 0.5
# share yields a x0.85 physical denominator (+17.6% physical EHP) when armed.
# ``assume_item_crit_dr`` defaults False -> the helper short-circuits to the
# identity 1.0 before any item is inspected -> BYTE-IDENTICAL.
_ASSUMED_INCOMING_CRIT_SHARE = 0.5


def item_crit_dr_multiplier(
    item_ids: Iterable[str],
    assume_item_crit_dr: bool = False,
) -> float:
    """Physical-denominator multiplier from item-keyed crit-damage reduction.

    Returns ``1.0`` (identity) when ``assume_item_crit_dr`` is False or no
    equipped item carries ``crit_damage_reduction`` - BYTE-IDENTICAL. When
    armed, each such item contributes ``(1 - crit_damage_reduction *
    _ASSUMED_INCOMING_CRIT_SHARE)`` multiplicatively (Randuin's is the only
    carrier today, so no unique-passive stacking question arises). A value
    ``< 1.0`` shrinks the physical denominator -> larger physical EHP, the
    correct "less crit damage taken -> survives more" direction.
    """
    if not assume_item_crit_dr:
        return 1.0
    factor = 1.0
    for item_id in item_ids:
        eff = ITEM_EFFECTS.get(str(item_id))
        if eff is None or eff.crit_damage_reduction <= 0.0:
            continue
        factor *= (1.0 - eff.crit_damage_reduction * _ASSUMED_INCOMING_CRIT_SHARE)
    return factor


# ENGINE 1.181.0 (R80, 2026-07-05): item-keyed incoming BASIC-ATTACK DAMAGE
# REDUCTION. Plated Steelcaps (SR 3047 / Arena 223047) "Plating" reduces all
# incoming basic-attack damage by 10% (Meraki 16.13.1) - a defensive_only NOTE
# with ZERO EHP credit, though the item's armor already counted. Basic-attack
# damage is PHYSICAL, so the reduction is multiplicative on the physical EHP
# denominator - the SAME layer + item-keyed lane as R77's crit-DR (the champion
# percent-DR family is champion_id-keyed and cannot see items).
#
# The basic-attack SHARE of incoming physical damage is the live feed we lack
# (same class as R77's crit-share) - a conservative operator-tunable midpoint.
# A 10% AA-DR at a 0.5 share yields a x0.95 physical denominator (+5.3% physical
# EHP) when armed. ``assume_item_aa_dr`` defaults False -> the helper short-
# circuits to the identity 1.0 before any item is inspected -> BYTE-IDENTICAL.
_ASSUMED_INCOMING_AA_SHARE = 0.5


def item_aa_dr_multiplier(
    item_ids: Iterable[str],
    assume_item_aa_dr: bool = False,
) -> float:
    """Physical-denominator multiplier from item-keyed basic-attack DR.

    Returns ``1.0`` (identity) when ``assume_item_aa_dr`` is False or no
    equipped item carries ``basic_attack_damage_reduction`` - BYTE-IDENTICAL.
    When armed, each such item contributes ``(1 - basic_attack_damage_reduction
    * _ASSUMED_INCOMING_AA_SHARE)`` multiplicatively (Plated Steelcaps is the
    only carrier today, so no unique-passive stacking question arises). A value
    ``< 1.0`` shrinks the physical denominator -> larger physical EHP, the
    correct "less basic-attack damage taken -> survives more" direction.
    """
    if not assume_item_aa_dr:
        return 1.0
    factor = 1.0
    for item_id in item_ids:
        eff = ITEM_EFFECTS.get(str(item_id))
        if eff is None or eff.basic_attack_damage_reduction <= 0.0:
            continue
        factor *= (1.0 - eff.basic_attack_damage_reduction * _ASSUMED_INCOMING_AA_SHARE)
    return factor


# ENGINE 1.182.0 (R86, 2026-07-06): item-keyed enemy ATTACK-SPEED-SLOW aura.
# Frozen Heart (SR 3110 / ARAM 323110 / Arena 223110) "Winter's Caress" reduces
# nearby enemy Attack Speed by 20% (DDragon 16.13.1) - a defensive_only NOTE with
# ZERO EHP credit though the item's armor already counted. A 20% enemy AS slow
# means nearby enemies auto-attack at 0.80x RATE, so the incoming basic-attack
# damage rate drops 20%: the SAME physical-EHP effect as R80's per-hit AA-DR, just
# sourced from attack RATE not per-hit magnitude. It folds into the physical EHP
# denominator behind the default-OFF ``assume_item_enemy_as_slow`` seam - a
# distinct item-keyed lane from R77's crit-DR and R80's per-hit AA-DR (each item
# carries only its own reduction, so the lanes never cross-credit and stack
# multiplicatively). The basic-attack SHARE of incoming physical reuses R80's
# midpoint ``_ASSUMED_INCOMING_AA_SHARE`` (the live feed we lack). Default False ->
# identity 1.0 before any item is inspected -> BYTE-IDENTICAL.
def item_enemy_as_slow_multiplier(
    item_ids: Iterable[str],
    assume_item_enemy_as_slow: bool = False,
) -> float:
    """Physical-denominator multiplier from item-keyed enemy AS-slow auras.

    Returns ``1.0`` (identity) when ``assume_item_enemy_as_slow`` is False or no
    equipped item carries ``enemy_attack_speed_slow`` - BYTE-IDENTICAL. When
    armed, each such item contributes ``(1 - enemy_attack_speed_slow *
    _ASSUMED_INCOMING_AA_SHARE)`` multiplicatively (Frozen Heart is the only
    carrier today, so no unique-passive stacking question arises). A value
    ``< 1.0`` shrinks the physical denominator -> larger physical EHP, the
    correct "enemy attacks slower -> less basic-attack damage taken -> survives
    more" direction.
    """
    if not assume_item_enemy_as_slow:
        return 1.0
    factor = 1.0
    for item_id in item_ids:
        eff = ITEM_EFFECTS.get(str(item_id))
        if eff is None or eff.enemy_attack_speed_slow <= 0.0:
            continue
        factor *= (1.0 - eff.enemy_attack_speed_slow * _ASSUMED_INCOMING_AA_SHARE)
    return factor


def _vamp_heal_pool(
    vamp_pct: float,
    ad: float,
    attack_speed: float,
    fight_window_s: float = _FIGHT_WINDOW_S,
) -> float:
    """Convert a vamp fraction (lifesteal / spellvamp / omnivamp) into a
    per-fight heal magnitude off the representative AA-damage throughput.

    ENGINE 1.28.0 (2026-05-21) shipped this for lifesteal; ENGINE 1.121.0
    (2026-06-14) generalises the SAME formula to the spellvamp / omnivamp
    stats so every vamp kind the stat schema resolves feeds the EHP sustain
    term (closes the ``test_wireable_sims_p1l3`` CONTRACT-GAP: vamp stats
    resolved but never converted to an effective-survivability output).

    Formula: ``vamp_pct * ad * attack_speed * fight_window_s`` - the AA
    damage dealt over the window times the vamp fraction returned as HP.
    PRE-mitigation approximation (vamp heals on post-armor damage in-game,
    but the EHP scorer is the wielder's EHP and does not model enemy armor;
    bounded ~30-40% over-credit vs a 60-90 armor target, consistent with the
    scorer's enemy-state-agnostic posture). Exact for lifesteal and for the
    AA share of omnivamp; a documented LOWER-BOUND proxy for spellvamp (which
    heals off ABILITY damage the enemy-agnostic EHP scorer does not model)
    and for omnivamp's ability share.

    All inputs clamped at 0; non-positive window returns 0.
    """
    if fight_window_s <= 0:
        return 0.0
    raw = (
        max(0.0, vamp_pct)
        * max(0.0, ad)
        * max(0.0, attack_speed)
        * fight_window_s
    )
    return max(0.0, raw)


def _lifesteal_heal(
    lifesteal_pct: float,
    ad: float,
    attack_speed: float,
    fight_window_s: float = _FIGHT_WINDOW_S,
) -> float:
    """Lifesteal stat -> per-fight heal magnitude (ENGINE 1.28.0).

    Thin back-compatible wrapper over the generalised ``_vamp_heal_pool``
    (ENGINE 1.121.0). Kept as a named entry point because the Phase-6 heal
    tests and the ``compute_ehp`` lifesteal site import it directly. See
    ``_vamp_heal_pool`` for the formula + the pre-mitigation-approximation
    rationale.
    """
    return _vamp_heal_pool(lifesteal_pct, ad, attack_speed, fight_window_s)


def effective_cc_duration(base_cc_s: float, tenacity_mult: float) -> float:
    """Apply ARAM tenacity multiplier to a base CC duration.

    ENGINE 1.25.0 (2026-05-21): the seam any consumer (coach prompt
    builder, future fight-sim, EHP-vs-CC blended model) reads to convert
    a base CC duration into the post-tenacity value. ``tenacity_mult``
    comes from ``EhpResult.aram_tenacity_mult`` (or directly from
    ``resolved.stats.get("aram_tenacity_mult", 1.0)``).

    Formula: ``eff_cc_s = base_cc_s * tenacity_mult``.
      * ``tenacity_mult == 1.0`` -> identity (no ARAM tenacity modifier).
      * ``tenacity_mult < 1.0`` -> shorter CC (most ARAM assassins: 0.80
        means 1.0s root becomes 0.80s).
      * ``tenacity_mult > 1.0`` -> longer CC (rare: ARAM imposes longer
        CC on a few champs as a balance lever).

    Negative or zero base_cc_s returns 0.0. Tenacity floored at 0.0 (a
    pathological future value cannot make CC negative).
    """
    if base_cc_s <= 0:
        return 0.0
    return float(base_cc_s) * max(0.0, float(tenacity_mult))


def _aram_damage_taken(snapshot: DataSnapshot, champion_id: str, mode: str) -> float:
    """Pull ``aramDamageTaken`` from the snapshot. 1.0 outside ARAM.

    ARAM applies a per-champion modifier to ALL damage taken (physical,
    magical, true). Snapshot stores it under
    ``champion.lolmath.aram_modifiers.aramDamageTaken`` - extracted by
    ``tools/daemon_slayer_extract.py`` from lolmath's data chunk.
    """
    if mode != "ARAM":
        return 1.0
    champ = snapshot.champion(champion_id)
    aram = ((champ.get("lolmath") or {}).get("aram_modifiers") or {})
    return float(aram.get("aramDamageTaken", 1.0))


@dataclass(frozen=True)
class EhpResult:
    champion_id: str
    champion_name: str
    level: int
    item_ids: tuple[str, ...]
    mode: str
    hp: float
    armor: float
    mr: float
    physical_ehp: float          # HP / (armor_factor(armor) * mode_mult)
    magical_ehp: float           # HP / (armor_factor(mr) * mode_mult)
    true_ehp: float              # HP / mode_mult
    blended_ehp: float           # weighted by enemy AD/AP/true shares
    enemy_ad_share: float
    enemy_ap_share: float
    enemy_true_share: float      # derived: 1 - ad_share - ap_share
    mode_multiplier: float       # aramDamageTaken; 1.0 outside ARAM
    # ENGINE 1.25.0 (2026-05-21): ARAM tenacity multiplier on incoming CC
    # duration. 17 ARAM champs carry non-1.0 values (assassin-shaped +20%
    # / +10% lengthening, plus a handful of shorteners). 1.0 outside ARAM
    # (engine.py only writes the scaled["aram_tenacity_mult"] key when
    # mode == "ARAM" via _apply_mode_modifiers). The blended_ehp math
    # above does NOT consume this value - CC duration vs HP pool is a
    # different axis; downstream consumers pair this with their own base
    # CC assumption via the module-level ``effective_cc_duration`` helper.
    aram_tenacity_mult: float = 1.0
    # ENGINE 1.27.0 (2026-05-21): Phase 1.5 shield throughput. Aggregated
    # shield_hp by damage type (closes ehp.py:21 deliberate omission).
    # ``shield_any`` is type-agnostic (Sterak / Shieldbow lifelines) -
    # absorbs all 3 damage components. ``shield_phys`` / ``shield_mag``
    # / ``shield_true`` are type-gated (Maw / Hexdrinker are magic-only).
    # ``shield_sources`` is the per-item breakdown for format_table and
    # to_dict transparency. The physical_ehp / magical_ehp / true_ehp /
    # blended_ehp fields above ALREADY include the shield contribution
    # (added at the top of the damage stack per League's shield-then-HP
    # absorption order); these fields surface the magnitude separately.
    shield_any: float = 0.0
    shield_phys: float = 0.0
    shield_mag: float = 0.0
    shield_true: float = 0.0
    shield_sources: tuple[tuple[str, str, float], ...] = field(default_factory=tuple)
    # ENGINE 1.29.0 (2026-05-21): Phase 6.5 shield-amp closure. Same
    # multiplier value as ``heal_amp_mult`` today (Spirit Visage 3065 /
    # Arena 223065 amps "all heal AND shielding +25%" per Riot tooltip)
    # but conceptually a sibling field so a future heal-only or shield-
    # only amp item stays representable. Applied multiplicatively at the
    # EHP-math site to ``shield_any`` / ``shield_phys`` / ``shield_mag``
    # / ``shield_true``. The shield_* fields above are PRE-amp for
    # transparency (matching ``heal_item_total`` / ``heal_lifesteal``
    # pre-amp convention); the physical_ehp / magical_ehp / true_ehp /
    # blended_ehp fields ALREADY include the post-amp shield contribution.
    shield_amp_mult: float = 1.0
    # ENGINE 1.28.0 (2026-05-21): Phase 6 healing throughput. Heal pool
    # is value-additive at the top of the damage stack (same place as
    # shields). ``heal_item_total`` = sum of item-passive heal triggers
    # (Sundered Sky one-shot per fight); ``heal_lifesteal`` = lifesteal-
    # derived heal accumulated over ``_FIGHT_WINDOW_S`` (default 6s);
    # ``heal_amp_mult`` is the multiplicative amp (Spirit Visage 1.25);
    # ``heal_total`` is the POST-amp sum that the EHP math actually
    # consumes (``(heal_item_total + heal_lifesteal) * heal_amp_mult``).
    # ``heal_sources`` is the per-item breakdown (pre-amp magnitudes
    # for transparency in format_table). The physical_ehp / magical_ehp
    # / true_ehp / blended_ehp fields above ALREADY include the heal
    # contribution. The heal pool absorbs all damage types (ANY-type
    # like a lifeline shield - heals don't discriminate by damage type
    # in League's model).
    heal_item_total: float = 0.0
    heal_lifesteal: float = 0.0
    heal_amp_mult: float = 1.0
    heal_total: float = 0.0
    heal_sources: tuple[tuple[str, float], ...] = field(default_factory=tuple)
    # ENGINE 1.33.0 (2026-05-22): EHP-vs-CC blended scorer. Second
    # engine math consumer of ``compute_cc_pressure`` (the first was
    # the coach-prompt-side ``core/enemy_cc_threat_context.py`` per
    # CLAUDE.md item 136 Slice B; this slice closes item 136 carry (a)
    # by consuming the registry inside the engine math layer).
    #
    # ``enemy_cc_pressure_s`` is the sum of ``total_cc_seconds`` from
    # ``compute_cc_pressure(enemy, mode)`` over the ``enemy_champions``
    # iterable. ``cc_pressure_fraction`` is the bounded share of the
    # ``_FIGHT_WINDOW_S`` (6.0s) consumed by enemy CC, clamped at 1.0
    # so a 20s burst of summed CC saturates to a single fight window.
    # ``cc_blended_ehp`` is the conservative-discount EHP after the
    # ``_CC_EFFECTIVENESS_FACTOR=0.5`` midpoint adjustment.
    #
    # Empty ``enemy_champions`` (default) leaves all three fields at
    # their identity defaults (0.0 / 0.0 / equal to ``blended_ehp``).
    # The existing physical_ehp / magical_ehp / true_ehp / blended_ehp
    # fields ABOVE are NOT discounted - the CC blend sits ON TOP of
    # the per-type EHP math as a sibling discount layer applied only
    # to ``cc_blended_ehp``.
    enemy_cc_pressure_s: float = 0.0
    cc_pressure_fraction: float = 0.0
    cc_blended_ehp: float = 0.0
    stats: dict[str, float] = field(default_factory=dict)
    notes: tuple[str, ...] = field(default_factory=tuple)
    # ENGINE 1.91.0 (2026-06-02): GAP-2 effects-text passive DAMAGE-REDUCTION
    # multipliers (per damage type) folded into the EHP denominator when
    # ``apply_passive_mitigation=True``. Default 1.0 (no reduction) leaves the
    # physical/magical/true/blended EHP fields above byte-identical; the values
    # < 1.0 surface the DR magnitude (mult 0.90 = 10% reduction). Same sibling
    # convention as ``shield_amp_mult`` / ``aram_tenacity_mult``.
    passive_mitigation_phys: float = 1.0
    passive_mitigation_mag: float = 1.0
    passive_mitigation_true: float = 1.0
    # ENGINE 1.93.0 (2026-06-02): GAP-2 effects-text passive RESIST-STAT grants
    # (bonus armor / MR) added to the armor/MR denominator when
    # ``apply_passive_resist=True``. Default 0.0 leaves the physical/magical/
    # blended EHP fields above byte-identical; positive values surface the grant
    # magnitude (added BEFORE _armor_factor; the reported armor/mr fields stay the
    # resolved build stats). Same sibling convention as passive_mitigation_*.
    passive_resist_armor: float = 0.0
    passive_resist_mr: float = 0.0
    # ENGINE 1.101.0 (2026-06-03): GAP-2 effects-text passive REVIVE / second-life
    # multiplier on the EHP NUMERATOR when ``apply_passive_revive=True``. Default
    # 1.0 (no revive) leaves the physical/magical/true/blended EHP fields above
    # byte-identical; > 1.0 surfaces the amortized second-life uplift (Anivia 1.40
    # = a full-HP revive at the 0.4 midpoint). Same sibling convention as
    # passive_mitigation_* / passive_resist_*.
    passive_revive_mult: float = 1.0
    # ENGINE 1.102.0 (2026-06-03): GAP-2 SIXTH survivability axis - an
    # ALLY-TARGETED grant a TEAMMATE confers on THIS champion (the
    # ``external_resist_*`` / ``external_revive_multiplier`` inputs sourced from
    # ``_passive_ally_grant_overrides``). Default 0.0 / 0.0 / 1.0 leaves the EHP
    # fields above byte-identical; positive armor/MR and a > 1.0 multiplier echo
    # the teammate-conferred resist add (Orianna E / Braum W / Taric W) and ally
    # revive (Renata W). Distinct from passive_resist_* / passive_revive_mult,
    # which stay the SELF grants. Same sibling convention as those fields.
    ally_grant_armor: float = 0.0
    ally_grant_mr: float = 0.0
    ally_grant_revive_mult: float = 1.0
    # DSP7 (2026-06-17, ENGINE 1.133.0): the THIRD ally-grant survivability axis -
    # a flat EHP-numerator HP a TEAMMATE confers (enchanter shield / heal: Janna E
    # / Lulu E / Karma E / Yuumi E / Seraphine W / Soraka W / Nami W), sourced
    # from ``_passive_ally_grant_overrides.ally_flat_hp_grant`` and passed as
    # ``external_flat_hp``. Default 0.0 leaves every EHP field above byte-
    # identical; a positive value echoes the conferred shield/heal HP. Distinct
    # from the SELF heal/shield item throughput (shield_*/heal_*) which is the
    # protected ally's OWN sustain. Same sibling convention as ally_grant_armor.
    ally_grant_flat_hp: float = 0.0
    # ENGINE 1.103.0 (2026-06-03): item 290 SEVENTH survivability axis - the
    # champion's INNATE tenacity / crowd-control-immunity ABILITY (Garen W / Olaf R
    # / Malzahar P) as a combined tenacity FRACTION sourced from
    # ``_champion_cc_mitigation_overrides`` when ``apply_champion_tenacity=True``.
    # Default 0.0 leaves enemy_cc_pressure_s / cc_blended_ehp byte-identical; a
    # positive fraction shrank the eaten CC (a larger cc_blended_ehp). Not an EHP
    # numerator/denominator term - it feeds the cc_blended discount, the clean
    # CC-survival half of the guaranteed-survival family the ally-grant + DR
    # registries excluded.
    champion_tenacity_frac: float = 0.0
    # ENGINE 1.104.0 (2026-06-03): item 292 EIGHTH survivability axis - the
    # champion's SELF SPELL-SHIELD / block-one CC ability (Sivir E / Nocturne W /
    # Fiora W / Morgana E self) as a combined block FRACTION sourced from
    # ``_champion_spell_shield_overrides`` when ``apply_spell_shield=True``. A
    # SEPARATE seam from champion_tenacity_frac: a spell-shield negates ONE CC
    # instance (availability-gated), it does not scale every CC's duration, so the
    # consumer applies it as its own multiplicative discount AFTER the tenacity
    # step. Default 0.0 leaves enemy_cc_pressure_s / cc_blended_ehp byte-identical.
    spell_shield_frac: float = 0.0
    # ENGINE 1.105.0 (2026-06-03): item 293 NINTH survivability axis + SECOND
    # EHP-NUMERATOR term (after the item-288 revive) - the champion's SELF
    # GUARANTEED-SURVIVAL WINDOW (untargetable / stasis / invulnerable: Tryndamere
    # R / Kindred R / Taric R / Kayle R self / Lissandra R self / Xayah R / Vladimir
    # W / Elise E / Fizz E / Mel W) sourced from
    # ``_passive_survival_window_overrides`` when ``apply_survival_window=True``. A
    # window voids ALL incoming damage for window_s of the fight -> the avoided
    # FRACTION multiplies the EHP numerator (1 + window_s/_FIGHT_WINDOW_S * prob).
    # Default 1.0 (no window) leaves the EHP fields byte-identical; > 1.0 surfaces
    # the amortized uplift. Same sibling convention as passive_revive_mult.
    survival_window_mult: float = 1.0
    # ENGINE 1.121.0 (2026-06-14): SUSTAIN contract-gap closure. An explicitly
    # named effective-survivability term that folds the damage-conversion VAMP
    # heal (lifesteal + spellvamp + omnivamp) into the EHP, closing the
    # test_wireable_sims_p1l3 CONTRACT-GAP (vamp stats resolved but never named
    # as an effective-EHP output). SIBLING layer (the cc_blended_ehp pattern):
    # blended_ehp / physical_ehp / magical_ehp / true_ehp above are
    # BYTE-IDENTICAL - they already include the lifesteal heal pool (heal_total)
    # since ENGINE 1.28.0; these fields NAME the sustain-inclusive quantity and
    # add the previously-unconsumed spellvamp / omnivamp share.
    #   * ``ehp_without_sustain`` - blended EHP with the VAMP heal stripped
    #     (item-passive heals + shields kept) = the "raw" EHP the contract
    #     compares against.
    #   * ``effective_ehp_with_sustain`` - blended EHP including the FULL vamp
    #     pool. == blended_ehp on every current build (no SR item resolves
    #     spellvamp / omnivamp - pinned by VampStatResolutionEdge); > blended_ehp
    #     once such an item exists.
    #   * ``sustain_ehp_delta`` = effective_ehp_with_sustain - ehp_without_sustain
    #     (the EHP the vamp sustain is worth this fight).
    #   * ``heal_spellvamp`` / ``heal_omnivamp`` - the pre-amp spellvamp /
    #     omnivamp heal magnitudes (0.0 on current builds), heal_lifesteal
    #     siblings.
    effective_ehp_with_sustain: float = 0.0
    ehp_without_sustain: float = 0.0
    sustain_ehp_delta: float = 0.0
    heal_spellvamp: float = 0.0
    heal_omnivamp: float = 0.0
    # ENGINE 1.148.0 (R9, 2026-06-21): per-instance FLAT-AMOUNT damage reduction
    # the percent mitigation registry EXCLUDED (Fizz P, Amumu E, Leona W) - the
    # prevented-damage HP (bonus-max-HP equivalent) folded into the EHP NUMERATOR
    # per damage type when ``assume_passive_flat_mitigation=True``. Default 0.0
    # leaves every EHP field above byte-identical; positive values surface the
    # prevented HP. Sourced from ``_passive_flat_mitigation_overrides``; distinct
    # from the passive_mitigation_* PERCENT multipliers (a denominator divide) and
    # ext_flat_hp (an ally grant). Same sibling convention as ally_grant_flat_hp.
    passive_flat_mit_phys: float = 0.0
    passive_flat_mit_mag: float = 0.0
    passive_flat_mit_true: float = 0.0

    def to_dict(self) -> dict:
        return {
            "champion_id": self.champion_id,
            "champion_name": self.champion_name,
            "level": self.level,
            "item_ids": list(self.item_ids),
            "mode": self.mode,
            "hp": self.hp,
            "armor": self.armor,
            "mr": self.mr,
            "physical_ehp": self.physical_ehp,
            "magical_ehp": self.magical_ehp,
            "true_ehp": self.true_ehp,
            "blended_ehp": self.blended_ehp,
            "enemy_ad_share": self.enemy_ad_share,
            "enemy_ap_share": self.enemy_ap_share,
            "enemy_true_share": self.enemy_true_share,
            "mode_multiplier": self.mode_multiplier,
            "aram_tenacity_mult": self.aram_tenacity_mult,
            "shield_any": self.shield_any,
            "shield_phys": self.shield_phys,
            "shield_mag": self.shield_mag,
            "shield_true": self.shield_true,
            "shield_sources": [
                {"item_id": iid, "damage_type": dt, "shield_hp": hp}
                for iid, dt, hp in self.shield_sources
            ],
            "shield_amp_mult": self.shield_amp_mult,
            "heal_item_total": self.heal_item_total,
            "heal_lifesteal": self.heal_lifesteal,
            "heal_amp_mult": self.heal_amp_mult,
            "heal_total": self.heal_total,
            "heal_sources": [
                {"item_id": iid, "heal_hp": hp}
                for iid, hp in self.heal_sources
            ],
            "enemy_cc_pressure_s": self.enemy_cc_pressure_s,
            "cc_pressure_fraction": self.cc_pressure_fraction,
            "cc_blended_ehp": self.cc_blended_ehp,
            "passive_mitigation_phys": self.passive_mitigation_phys,
            "passive_mitigation_mag": self.passive_mitigation_mag,
            "passive_mitigation_true": self.passive_mitigation_true,
            "passive_flat_mit_phys": self.passive_flat_mit_phys,
            "passive_flat_mit_mag": self.passive_flat_mit_mag,
            "passive_flat_mit_true": self.passive_flat_mit_true,
            "passive_resist_armor": self.passive_resist_armor,
            "passive_resist_mr": self.passive_resist_mr,
            "passive_revive_mult": self.passive_revive_mult,
            "ally_grant_armor": self.ally_grant_armor,
            "ally_grant_mr": self.ally_grant_mr,
            "ally_grant_revive_mult": self.ally_grant_revive_mult,
            "ally_grant_flat_hp": self.ally_grant_flat_hp,
            "champion_tenacity_frac": self.champion_tenacity_frac,
            "spell_shield_frac": self.spell_shield_frac,
            "survival_window_mult": self.survival_window_mult,
            "effective_ehp_with_sustain": self.effective_ehp_with_sustain,
            "ehp_without_sustain": self.ehp_without_sustain,
            "sustain_ehp_delta": self.sustain_ehp_delta,
            "heal_spellvamp": self.heal_spellvamp,
            "heal_omnivamp": self.heal_omnivamp,
            "sustain": {
                "effective_ehp_with_sustain": self.effective_ehp_with_sustain,
                "ehp_without_sustain": self.ehp_without_sustain,
                "sustain_ehp_delta": self.sustain_ehp_delta,
                "heal_lifesteal": self.heal_lifesteal,
                "heal_spellvamp": self.heal_spellvamp,
                "heal_omnivamp": self.heal_omnivamp,
            },
            "stats": dict(self.stats),
            "notes": list(self.notes),
        }

    def format_table(self) -> str:
        head = (
            f"{self.champion_name} ({self.champion_id}) - lvl {self.level} "
            f"- mode {self.mode}"
        )
        rows = [head, "-" * len(head)]
        if self.item_ids:
            rows.append(f"items: {', '.join(self.item_ids)}")
        else:
            rows.append("items: (none)")
        rows.append(
            f"caster: hp={self.hp:.0f}  armor={self.armor:.1f}  mr={self.mr:.1f}"
        )
        rows.append(
            f"enemy mix: AD={self.enemy_ad_share * 100:.0f}%  "
            f"AP={self.enemy_ap_share * 100:.0f}%  "
            f"true={self.enemy_true_share * 100:.0f}%"
        )
        rows.append("")
        rows.append(f"  blended_ehp    {self.blended_ehp:.0f}")
        rows.append(f"  physical_ehp   {self.physical_ehp:.0f}")
        rows.append(f"  magical_ehp    {self.magical_ehp:.0f}")
        rows.append(f"  true_ehp       {self.true_ehp:.0f}")
        if self.mode_multiplier != 1.0:
            rows.append(
                f"  mode_mult      {self.mode_multiplier:.3f}  (aramDamageTaken)"
            )
        if self.aram_tenacity_mult != 1.0:
            rows.append(
                f"  tenacity_mult  {self.aram_tenacity_mult:.3f}  (aramTenacity x CC duration)"
            )
        if self.shield_any or self.shield_phys or self.shield_mag or self.shield_true:
            shield_bits = []
            if self.shield_any:
                shield_bits.append(f"any={self.shield_any:.0f}")
            if self.shield_phys:
                shield_bits.append(f"phys={self.shield_phys:.0f}")
            if self.shield_mag:
                shield_bits.append(f"mag={self.shield_mag:.0f}")
            if self.shield_true:
                shield_bits.append(f"true={self.shield_true:.0f}")
            if self.shield_amp_mult != 1.0:
                shield_bits.append(f"amp=x{self.shield_amp_mult:.3f}")
            rows.append("  shield_hp     " + "  ".join(shield_bits))
        if self.heal_total > 0:
            heal_bits = []
            if self.heal_item_total > 0:
                heal_bits.append(f"item={self.heal_item_total:.0f}")
            if self.heal_lifesteal > 0:
                heal_bits.append(f"lifesteal={self.heal_lifesteal:.0f}")
            if self.heal_amp_mult != 1.0:
                heal_bits.append(f"amp=x{self.heal_amp_mult:.3f}")
            heal_bits.append(f"total={self.heal_total:.0f}")
            rows.append("  heal_hp       " + "  ".join(heal_bits))
        if self.sustain_ehp_delta > 0:
            rows.append(
                f"  sustain       effective_ehp={self.effective_ehp_with_sustain:.0f}"
                f"  raw_ehp={self.ehp_without_sustain:.0f}"
                f"  delta=+{self.sustain_ehp_delta:.0f} (vamp)"
            )
        if self.enemy_cc_pressure_s > 0:
            rows.append(
                f"  cc_pressure   total_s={self.enemy_cc_pressure_s:.1f}  "
                f"fraction={self.cc_pressure_fraction:.2f}  "
                f"blended_ehp={self.cc_blended_ehp:.0f} (after CC discount)"
            )
        if self.notes:
            rows.append("")
            for n in self.notes:
                rows.append(f"  note: {n}")
        return "\n".join(rows)


def compute_ehp(
    snapshot: DataSnapshot,
    champion_id: str,
    level: int,
    item_ids: Optional[Iterable[str | int]] = None,
    mode: str = "SR",
    enemy_ad_share: float = 0.5,
    enemy_ap_share: float = 0.5,
    augments: Optional[Iterable] = None,
    enemy_champions: Iterable[str] = (),
    include_conditional: bool = False,
    apply_mode_modifiers: bool = False,
    apply_build_tenacity: bool = False,
    apply_passive_mitigation: bool = False,
    assume_passive_flat_mitigation: bool = False,
    apply_passive_resist: bool = False,
    apply_passive_revive: bool = False,
    apply_champion_tenacity: bool = False,
    apply_spell_shield: bool = False,
    apply_survival_window: bool = False,
    external_resist_armor: float = 0.0,
    external_resist_mr: float = 0.0,
    external_revive_multiplier: float = 1.0,
    external_flat_hp: float = 0.0,
    apply_egg_resist: bool = True,
    enemy_lethality: float = 0.0,
    enemy_armor_pen_pct: float = 0.0,
    enemy_shred_pct: float = 0.0,
    enemy_magic_pen_flat: float = 0.0,
    enemy_magic_pen_pct: float = 0.0,
    caster_current_hp_pct: float = 1.0,
    assume_passive_health_stacks: bool = False,
    assume_hsp_amp: bool = False,
    # B45/B46 (operator flip 2026-07-06): default-ON so the EHP scorer credits
    # Randuin's crit-DR (~+17.6% physical EHP at the assumed crit share) and
    # Plated Steelcaps' 10% basic-attack DR (~+5.3% physical EHP at the assumed
    # 0.5 AA share). Was default-OFF pending live validation; the assumed shares
    # are conservative midpoints (no live crit/AA-share feed). Pass False at a
    # call site to opt back out.
    assume_item_crit_dr: bool = True,
    assume_item_aa_dr: bool = True,
    # R86 (1.182.0): item-keyed enemy AS-slow aura (Frozen Heart -20% enemy AS
    # ~= 20% less incoming basic-attack RATE, ~+11.1% physical EHP at the assumed
    # 0.5 AA share). Ships DEFAULT-OFF pending its own live-gated flip (unlike the
    # already-flipped R77/R80); identity multiplier when False -> BYTE-IDENTICAL.
    assume_item_enemy_as_slow: bool = False,
) -> EhpResult:
    """Compute Effective HP for the resolved build under an enemy damage profile.

    ``enemy_ad_share`` and ``enemy_ap_share`` are floats in ``[0.0, 1.0]``
    summing to <= 1.0; the remainder is true-damage share. Defaults to
    50/50 AD/AP - a reasonable "no info" baseline. Operator-facing
    callers (``core/defensive_picks.py``) derive these shares from the
    threat profile.

    Caster armor/MR come straight from the resolved stat block. Enemy-pen
    modeling is OPT-IN as of T1-F3 (2026-06-09): the five ``enemy_*``
    kwargs (``enemy_lethality`` / ``enemy_armor_pen_pct`` /
    ``enemy_shred_pct`` / ``enemy_magic_pen_flat`` / ``enemy_magic_pen_pct``)
    feed ``_effective_resist_after_pen`` BEFORE the ``_armor_factor`` curve.
    ALL FIVE default to 0.0 -> the pen step is an identity no-op ->
    BYTE-IDENTICAL to the pre-seam Phase-1 behavior (closes the long-
    standing ehp.py:30 deliberate omission). ARMOR order: % shred (clamped
    0..0.99) -> general %pen (multiplicative) -> lethality (flat, subtract
    LAST). MR order: %pen -> flat magic pen (subtract last). The reported
    ``EhpResult.armor`` / ``.mr`` stay the RESOLVED build stats; the post-
    pen value is internal to the EHP math (matching the passive-resist /
    ally-grant convention). See ``_effective_resist_after_pen`` for the
    natural-vs-bonus-armor NOTE.

    ENGINE 1.33.0 (2026-05-22): ``enemy_champions`` keyword is the
    second engine math consumer of ``compute_cc_pressure`` (closes item
    136 carry (a)). Pass an iterable of enemy champion ids (canonical
    DDragon ids like "Annie", "Morgana", "MonkeyKing") to compute
    ``enemy_cc_pressure_s`` summed across registered CC spells (89 of
    172 champs at patch 16.11.1; the registry size is computed at import). Default ``()`` leaves all 3 new fields at
    identity (0.0 / 0.0 / equal to ``blended_ehp``), preserving full
    back-compat for all existing callers. Empty / None / unknown
    entries within the iterable are silently skipped (mirrors
    ``compute_cc_pressure`` fail-soft contract).

    ENGINE 1.39.0 (2026-05-22): ``include_conditional`` (default False)
    is the SECOND authorized consumer wire of the ``cc_conditional``
    registry (the FIRST was ``compute_cc_pressure`` at ENGINE 1.38.0).
    When True, the kwarg is propagated through to the per-enemy
    ``compute_cc_pressure(enemy, mode, include_conditional=True)``
    calls so each enemy's ``total_cc_seconds`` includes the
    probability-weighted post-tenacity conditional contribution from
    the 18-entry / 18-champion conditional registry. The resulting
    ``cc_blended_ehp`` field absorbs the additional discount when
    conditional CC is present on at least one enemy. Default
    ``include_conditional=False`` preserves BYTE-IDENTICAL behavior
    for every existing caller; the conditional axis is opt-in.
    """
    level = clamp_level(level)
    if not (0.0 <= enemy_ad_share <= 1.0):
        raise ValueError(
            f"enemy_ad_share must be in [0,1], got {enemy_ad_share}"
        )
    if not (0.0 <= enemy_ap_share <= 1.0):
        raise ValueError(
            f"enemy_ap_share must be in [0,1], got {enemy_ap_share}"
        )
    total_share = enemy_ad_share + enemy_ap_share
    if total_share > 1.0001:  # 1e-4 tolerance for float arithmetic
        raise ValueError(
            f"enemy_ad_share + enemy_ap_share must be <= 1.0, got {total_share}"
        )

    resolved = build_champion(
        snapshot, champion_id, level, item_ids=item_ids, mode=mode,
        augments=augments, apply_mode_modifiers=apply_mode_modifiers,
    )
    stats = resolved.stats
    hp = float(stats.get("hp", 0.0))
    armor = float(stats.get("armor", 0.0))
    mr = float(stats.get("mr", 0.0))

    mode_mult = _aram_damage_taken(snapshot, resolved.champion_id, mode)
    if mode != "ARAM" and apply_mode_modifiers:
        # item 232: OPT-IN wiki mode_modifiers sidecar for the non-ARAM
        # modes (urf/ofa/usb/nb dmg_taken MULTIPLIERS). ARAM keeps its
        # authoritative legacy aramDamageTaken path above (the helper
        # returns 1.0 outside ARAM) - do NOT route ARAM through the wiki
        # sidecar (avoids double-count). SR + unknown + addend-only modes
        # (ARENA/swift carry no dmg_taken) leave mode_mult=1.0, so EHP
        # stays byte-identical unless the flag is True AND the mode has a
        # wiki dmg_taken entry. Mirrors item 231's gate_ammo opt-in.
        mm = snapshot.mode_modifier(resolved.champion_id, mode)
        if isinstance(mm, dict) and "dmg_taken" in mm:
            mode_mult = float(mm["dmg_taken"])
    # Division-safety: never let a future data corruption pin
    # aramDamageTaken to 0 and explode the EHP math.
    safe_mult = mode_mult if mode_mult > 0 else 1.0
    # ENGINE 1.25.0 (2026-05-21): ARAM tenacity multiplier exposed via
    # the resolved stats dict (engine._apply_mode_modifiers gates on
    # mode == "ARAM"; SR + every non-ARAM mode get 1.0 by default).
    # Forwarded to EhpResult so consumers can call
    # ``effective_cc_duration(base_s, tenacity_mult)``. Blended EHP math
    # is unchanged - CC duration is a separate axis from HP pool.
    aram_tenacity_mult = float(resolved.stats.get("aram_tenacity_mult", 1.0))

    # ENGINE 1.27.0 (2026-05-21): Phase 1.5 shield throughput. Bonus
    # stats are item-side deltas from the champion's base block (stats
    # - base_stats); shields scale off these (Sterak's 60% bonus_hp;
    # Maw 200 + 150% bonus_ad). Ranged-vs-melee picks the
    # ItemShield.ranged_modifier (Meraki: Maw/Shieldbow/Hexdrinker at
    # 75-80% for ranged).
    base = resolved.base_stats
    bonus_hp = max(0.0, hp - float(base.get("hp", 0.0)))
    bonus_ad = max(0.0, float(stats.get("ad", 0.0)) - float(base.get("ad", 0.0)))
    base_ad = float(base.get("ad", 0.0))
    is_ranged = _is_ranged(base)
    shield_totals, shield_sources = _collect_shields(
        resolved.item_ids,
        level=level,
        bonus_hp=bonus_hp,
        bonus_ad=bonus_ad,
        is_ranged=is_ranged,
    )
    shield_any = shield_totals.get(ANY, 0.0)
    shield_phys = shield_totals.get(PHYSICAL, 0.0)
    shield_mag = shield_totals.get(MAGICAL, 0.0)
    shield_true = shield_totals.get(TRUE, 0.0)

    # ENGINE 1.28.0 (2026-05-21): Phase 6 healing throughput. Heal pool
    # accumulates from (a) item-passive heals (Sundered Sky Lightshield
    # Strike, one trigger per fight) and (b) lifesteal stat over the
    # fight window. Spirit Visage's amp applies multiplicatively to the
    # combined pool. The post-amp total is value-additive to EHP at the
    # top of the damage stack - heals don't discriminate by damage type
    # in League's model, so the heal pool acts like an ANY shield.
    # Phase 6.5 (2026-05-21): missing-HP additive piece on item heals
    # (Sundered Sky 6% missing HP) is wired by deriving the mid-fight
    # missing_hp once here from the resolved total HP and threading
    # it through _collect_heals. The full-HP steady-state convention
    # used elsewhere in the scorer is preserved by gating this only
    # on items that opt in via ItemHeal.missing_hp_pct > 0.
    # ENGINE 1.57.0 (2026-05-25): takedown-gated heals (Death's Dance
    # Defy 75% bonus AD per takedown) are scaled by the
    # ``_TAKEDOWN_RATE_PER_FIGHT`` constant inside ``_collect_heals``
    # for ItemHeal entries with takedown_gated=True. Items without the
    # flag (the 99% default case including Sundered Sky) are unaffected
    # and stay at the always-on one-trigger-per-fight model.
    missing_hp = hp * _MISSING_HP_SHARE_FOR_HEALS
    heal_item_total, heal_sources = _collect_heals(
        resolved.item_ids,
        base_ad=base_ad,
        bonus_hp=bonus_hp,
        bonus_ad=bonus_ad,
        is_ranged=is_ranged,
        missing_hp=missing_hp,
    )
    heal_lifesteal = _lifesteal_heal(
        lifesteal_pct=float(stats.get("lifesteal", 0.0)),
        ad=float(stats.get("ad", 0.0)),
        attack_speed=float(stats.get("as", 0.0)),
    )
    heal_amp_mult = _total_heal_amp(resolved.item_ids)
    heal_total = (heal_item_total + heal_lifesteal) * heal_amp_mult

    # ENGINE 1.29.0 (2026-05-21): Phase 6.5 - Spirit Visage's Boundless
    # Vitality amps "all heal AND shielding +25%" per Riot's tooltip.
    # The Phase 6 wire amped only the heal pool; Phase 6.5 closes the
    # boundary by applying the SAME multiplier to the shield pool at
    # the top of the damage stack. The two amps are SIBLINGS, not
    # nested: heal_total is amped once (above); shield_any/phys/mag/true
    # are amped once (below); both products sum into the EHP math. Same
    # multiplier value (today: Spirit Visage at 1.25) but conceptually a
    # sibling field so future heal-only or shield-only amp items stay
    # representable.
    # ENGINE 1.171.0 (R60, 2026-07-02): wielder Heal/Shield Power (HSP) amp.
    # HSP (Redemption / Mikael / Ardent / Moonstone / Staff of Flowing Water -
    # the heal_shield_amp_pct stat) boosts the shields the WIELDER applies to
    # ITSELF: its own item self-shields (Sterak's Gage, Shieldbow, Maw,
    # Hexdrinker, Bloodthirster Ichorshield). Summed ADDITIVELY across the build
    # (the "(1 + hsp_pct)" model, matching real-LoL additive HSP) and folded into
    # the existing sibling shield-amp multiplier alongside Spirit Visage's
    # Boundless Vitality. Distinct from R59 (the TARGET-side Lifeline shield).
    # DEFAULT-OFF: assume_hsp_amp=False -> hsp_pct 0.0 -> shield_amp_mult ==
    # heal_amp_mult -> BYTE-IDENTICAL to 1.170.0. The heal pool (heal_total) is
    # NOT touched here: lifesteal is not HSP-amped and item heals are out of the
    # directive scope (ItemShield only). The live default-ON flip is
    # operator-gated (docs/LIVE_GAME_GATED_SYNC.md).
    hsp_pct = (
        sum_wielder_hsp_pct(resolved.item_ids) if assume_hsp_amp else 0.0
    )
    shield_amp_mult = heal_amp_mult * (1.0 + hsp_pct)
    shield_any_amped = shield_any * shield_amp_mult
    shield_phys_amped = shield_phys * shield_amp_mult
    shield_mag_amped = shield_mag * shield_amp_mult
    shield_true_amped = shield_true * shield_amp_mult

    # ENGINE 1.91.0 (2026-06-02): GAP-2 effects-text passive DAMAGE-REDUCTION.
    # A flat-% DR ("Kassadin takes 10% reduced magic damage") is multiplicative
    # on the damage TAKEN, so it folds into the EHP DENOMINATOR per damage type
    # (a smaller divisor -> larger EHP -> the correct "less damage taken ->
    # survives more" direction). ``apply_passive_mitigation`` defaults False ->
    # all three multipliers are 1.0 -> BYTE-IDENTICAL to 1.90.0. Active /
    # cooldown-gated DRs are amortized inside ``mitigation_multipliers`` by their
    # entry's operator-tunable ``conditional_probability`` midpoint.
    # ENGINE 1.153.0 (R35, 2026-06-27): the snapshot-driven percent-DR consumer.
    # Passing ``snapshot`` lets mitigation_multipliers fold the per-rank percent
    # damage-reduction blocks the R19 forward-marker accessor surfaced (Galio W,
    # Garen W, MasterYi W, ...) into the denominator alongside the hand-authored
    # registry. Still DEFAULT-OFF: apply_passive_mitigation=False returns (1,1,1)
    # before the snapshot is consulted, so live DS output is byte-identical.
    mit_phys, mit_mag, mit_true = mitigation_multipliers(
        resolved.champion_id, level, apply_passive_mitigation, snapshot
    )

    # ENGINE 1.180.0 (R77, 2026-07-05): item-keyed incoming CRIT-DAMAGE
    # REDUCTION (Randuin's Omen Resilience 30% reduced crit damage taken).
    # Crit is PHYSICAL, so this is a SEPARATE physical-only denominator factor
    # applied alongside mit_phys (NOT folded into it - mit_phys stays the pure
    # champion percent-DR value for reporting). ``assume_item_crit_dr`` defaults
    # False -> identity 1.0 -> BYTE-IDENTICAL. Item-keyed (mit_phys is
    # champion_id-keyed and cannot see the build's items).
    item_crit_dr_mult = item_crit_dr_multiplier(
        resolved.item_ids, assume_item_crit_dr
    )

    # ENGINE 1.181.0 (R80, 2026-07-05): item-keyed incoming BASIC-ATTACK DAMAGE
    # REDUCTION (Plated Steelcaps Plating 10% reduced basic-attack damage).
    # Basic-attack damage is PHYSICAL, so this is a SEPARATE physical-only
    # denominator factor applied alongside mit_phys + item_crit_dr_mult (NOT
    # folded into mit_phys - it stays the pure champion percent-DR value for
    # reporting). ``assume_item_aa_dr`` defaults False -> identity 1.0 ->
    # BYTE-IDENTICAL. Item-keyed lane distinct from R77's crit-DR (each item
    # carries only its own reduction, so the two seams never cross-credit).
    item_aa_dr_mult = item_aa_dr_multiplier(
        resolved.item_ids, assume_item_aa_dr
    )

    # ENGINE 1.182.0 (R86, 2026-07-06): item-keyed enemy ATTACK-SPEED-SLOW aura
    # (Frozen Heart Winter's Caress -20% enemy AS -> 20% less incoming basic-attack
    # RATE). Basic-attack damage is PHYSICAL, so this is a SEPARATE physical-only
    # denominator factor applied alongside item_crit_dr_mult + item_aa_dr_mult (NOT
    # folded into mit_phys - it stays the pure champion percent-DR value for
    # reporting). ``assume_item_enemy_as_slow`` defaults False -> identity 1.0 ->
    # BYTE-IDENTICAL. Distinct item-keyed lane from R77/R80 (never cross-credit;
    # stacks multiplicatively with Steelcaps' per-hit AA-DR on a build with both).
    item_enemy_as_slow_mult = item_enemy_as_slow_multiplier(
        resolved.item_ids, assume_item_enemy_as_slow
    )

    # ENGINE 1.148.0 (R9, 2026-06-21): GAP - per-instance FLAT-AMOUNT damage
    # reduction, the sibling the percent mitigation registry deliberately
    # EXCLUDED (Fizz P, Amumu E, Leona W). A flat reduction per damage instance
    # prevents ``instances * flat * prob`` of damage over a fight, behaving like
    # bonus effective-HP, so it folds into the EHP NUMERATOR exactly like
    # ``ext_flat_hp`` (the enchanter ally flat-HP grant) below - NOT the
    # denominator (unlike the percent registry). ``assume_passive_flat_mitigation``
    # defaults False -> (0.0, 0.0, 0.0) -> BYTE-IDENTICAL to 1.147.0. The
    # per-instance count is an operator-tunable conservative midpoint inside
    # ``flat_mitigation_hp`` (the live per-instance feed we lack); a cooldown-gated
    # active (Leona W) is amortized there by its conditional_probability.
    flat_mit_phys, flat_mit_mag, flat_mit_true = flat_mitigation_hp(
        resolved.champion_id, level, assume_passive_flat_mitigation
    )

    # ENGINE 1.160.0 (R46, 2026-06-30): GAP - infinitely / permanently STACKING
    # max-HP passives (Sion W Soul Furnace +4 per kill, Cho'Gath R Feast
    # +80/120/160 per stack by rank, Swain P Ravenous Flock +15 per Soul Fragment).
    # A permanent bonus max-HP grant is NOT in the resolved stat block (not
    # base-per-level, not an item), so it sits at the TOP of the damage stack
    # exactly like ``ext_flat_hp`` / ``flat_mit_*`` - it adds RAW to every per-type
    # numerator and rides the SAME armor/MR curve, lifting every damage-type EHP
    # (incl. true) uniformly. ``assume_passive_health_stacks`` defaults False ->
    # 0.0 -> BYTE-IDENTICAL. The per-stack HP is EXACT 16.13.1 Meraki; the assumed
    # stack COUNT by level is an operator-tunable conservative midpoint (the live
    # stack feed we lack), amortized inside ``passive_health_stack_hp``.
    passive_health_hp = passive_health_stack_hp(
        resolved.champion_id, level, assume_passive_health_stacks
    )

    # ENGINE 1.93.0 (2026-06-02): GAP-2 effects-text passive RESIST-STAT grants.
    # The FOURTH survivability axis - champion-passive bonus armor / MR (Garen W
    # Courage, Wukong P, Shyvana P, Sejuani P, Gwen W, Pantheon E) that is NOT in
    # the resolved stat block (not base per-level, not an item). It raises the
    # armor/MR DENOMINATOR DIRECTLY (added BEFORE _armor_factor), unlike the DR
    # registry which multiplies the post-curve denominator. ``apply_passive_resist``
    # defaults False -> both grants 0.0 -> eff_armor/eff_mr == armor/mr ->
    # BYTE-IDENTICAL to 1.92.0. Active grants are amortized inside
    # ``resist_grants`` by their entry's operator-tunable conditional_probability.
    # The reported EhpResult.armor / .mr stay the RESOLVED build stats (the grant
    # is surfaced separately via passive_resist_armor / passive_resist_mr).
    # ENGINE 1.96.0 (2026-06-02): item 268 percent-of-resist mode (Malphite W /
    # Taric W / Poppy W / Rell W / Rammus W %-half) needs the RESOLVED build
    # resists - the grant is a PERCENT of the champion's own armor / MR, not a flat
    # add. The flat-add half (item 264/267) ignores these kwargs. total_* exclude
    # the passive grants (not in base/items) so there is no self-feedback.
    # ENGINE 1.158.0 (R45): caster_current_hp_pct threads the live HP fraction so
    # the low-HP DOUBLED tier (Poppy W "24% below 40% max HP") can fire. Defaults
    # to 1.0 (full HP) -> the tier is dormant -> byte-identical to 1.96.0.
    bonus_armor, bonus_mr = resist_grants(
        resolved.champion_id, level, apply_passive_resist,
        total_armor=armor, total_mr=mr,
        base_armor=float(base.get("armor", 0.0)),
        base_mr=float(base.get("mr", 0.0)),
        caster_current_hp_pct=caster_current_hp_pct,
    )
    # ENGINE 1.102.0 (2026-06-03): GAP-2 SIXTH survivability axis - an
    # ALLY-TARGETED resist grant a TEAMMATE confers on THIS champion (Orianna E
    # ball / Braum W / Taric W tether). The value is sourced by the caller from
    # ``_passive_ally_grant_overrides.ally_resist_grant`` (the granter-side
    # registry) and passed in as ``external_resist_armor`` / ``external_resist_mr``
    # - a GENERIC external add (compute_ehp scores the PROTECTED ally; the grant
    # rides in from a teammate). Folded into the SAME armor/MR denominator as the
    # self resist grant. Default 0.0 -> byte-identical to 1.101.0.
    ext_armor = max(0.0, float(external_resist_armor))
    ext_mr = max(0.0, float(external_resist_mr))
    eff_armor = armor + bonus_armor + ext_armor
    eff_mr = mr + bonus_mr + ext_mr
    # DSP7 (2026-06-17, ENGINE 1.133.0): ally enchanter SHIELD / HEAL flat-HP
    # grant - the THIRD ally-grant EHP mode (after the resist denominator add +
    # the revive numerator multiplier). The caller sources it from
    # ``_passive_ally_grant_overrides.ally_flat_hp_grant`` (Janna E / Lulu E /
    # Karma E / Yuumi E / Seraphine W shields, Soraka W / Nami W heals) and passes
    # the conferred raw HP as ``external_flat_hp``. A flat shield / heal sits at
    # the TOP of the damage stack exactly like base HP (it is NOT amped by the
    # protected ally's own shield/heal amp - the granter's value is final), so it
    # adds RAW to every per-type numerator and rides the SAME armor/MR curve.
    # Default 0.0 -> byte-identical. Negative clamped (never lowers EHP).
    ext_flat_hp = max(0.0, float(external_flat_hp))

    # T1-F3 (2026-06-09, docs/COMPETITOR_LIFT_2026-06-08.md lines 59-66):
    # OPT-IN enemy-penetration seam. The five enemy_* kwargs default to 0.0
    # -> ``_effective_resist_after_pen`` is an identity no-op -> eff_armor /
    # eff_mr stay exactly the resist sum above -> BYTE-IDENTICAL to the
    # pre-seam EHP math (closes the ehp.py:30 deliberate Phase-1 omission
    # "Caster-side enemy pen/reduction ... needs enemy build plumbing"; the
    # plumbing now arrives as caller-supplied scalars sourced from the enemy
    # build by core/defensive_picks.py). The pen bites the FULL resolved-
    # plus-granted resist (the tank's real effective resist is what an enemy
    # penetrates), so it is applied AFTER the passive/ally resist grants and
    # BEFORE _armor_factor. ARMOR: % shred -> general %pen -> lethality (flat,
    # last). MR: %shred (none in the kwarg set) -> %pen -> flat magic pen
    # last. true_ehp ignores resists so pen never touches it. See the helper
    # docstring for the natural-vs-bonus-armor NOTE (bonus-only pen is
    # approximated against total; no bonus-armor field is invented).
    eff_armor = _effective_resist_after_pen(
        eff_armor,
        shred_pct=enemy_shred_pct,
        pen_pct=enemy_armor_pen_pct,
        flat_pen=enemy_lethality,
    )
    eff_mr = _effective_resist_after_pen(
        eff_mr,
        shred_pct=0.0,
        pen_pct=enemy_magic_pen_pct,
        flat_pen=enemy_magic_pen_flat,
    )

    # Shields + heal sit at the top of the damage stack: each damage_type
    # sees ``hp + shield_any_amped + shield_<type>_amped + heal_total``
    # effective HP before the armor/MR curve. Shields + heals are NOT
    # reduced separately by resistances in League's damage model - they
    # share the same factor as HP. The mit_* DR multiplier divides the
    # whole denominator (it composes multiplicatively with armor/MR, the way
    # League stacks a flat-% reduction on top of the resistance curve).
    # ``flat_mit_<type>`` is prevented post-mitigation damage (per-instance flat
    # DR), a bonus-max-HP equivalent that sits at the TOP of the damage stack
    # exactly like ``ext_flat_hp`` - it adds RAW to the matching per-type
    # numerator and rides the SAME armor/MR curve. 0.0 when the flag is off ->
    # byte-identical.
    physical_ehp = (hp + ext_flat_hp + passive_health_hp + flat_mit_phys + shield_any_amped + shield_phys_amped + heal_total) / (_armor_factor(eff_armor) * safe_mult * mit_phys * item_crit_dr_mult * item_aa_dr_mult * item_enemy_as_slow_mult)
    magical_ehp = (hp + ext_flat_hp + passive_health_hp + flat_mit_mag + shield_any_amped + shield_mag_amped + heal_total) / (_armor_factor(eff_mr) * safe_mult * mit_mag)
    true_ehp = (hp + ext_flat_hp + passive_health_hp + flat_mit_true + shield_any_amped + shield_true_amped + heal_total) / (safe_mult * mit_true)

    # ENGINE 1.101.0 (2026-06-03): GAP-2 effects-text passive REVIVE / second-life.
    # The FIFTH survivability axis and the FIRST EHP-NUMERATOR term: a
    # death-triggered second HP pool (Anivia P Rebirth full-HP revive, Zac P Cell
    # Division 10:50% revive) is worth (1 + revived_fraction) of the single-life
    # EHP when the passive is up. The revived HP runs through the SAME armor/MR
    # curve as the first life, so the second life's EHP is exactly
    # ``revived_fraction`` of the first's -> a NUMERATOR multiplier on the final
    # per-type EHP (unlike the DR registry which divides the denominator, or the
    # resist registry which raises the armor/MR denominator). Applied BEFORE
    # blended_ehp so the blend (and cc_blended below) inherit it.
    # ``apply_passive_revive`` defaults False -> multiplier 1.0 -> BYTE-IDENTICAL
    # to 1.100.0. The long cooldown + must-survive-the-resurrection-window gate is
    # amortized inside ``revive_multiplier`` by the entry's _REVIVE_PROB midpoint.
    revive_mult = revive_multiplier(resolved.champion_id, level, apply_passive_revive)
    # ENGINE 1.102.0 (2026-06-03): GAP-2 ALLY-TARGETED revive (Renata W Bailout) -
    # a teammate confers a death-triggered second HP pool on THIS champion. The
    # caller sources it from ``ally_revive_multiplier`` and passes the > 1.0
    # multiplier as ``external_revive_multiplier`` (composes multiplicatively with
    # any self revive - two independent second lives). Default 1.0 -> unchanged.
    ext_revive = max(1.0, float(external_revive_multiplier))
    # ENGINE 1.105.0 (item 293): GAP-2 GUARANTEED-SURVIVAL WINDOW - the SECOND
    # EHP-NUMERATOR term (sibling of the revive). A SELF untargetable / stasis /
    # invulnerable window (Tryndamere R / Kindred R / Taric R / Kayle R self /
    # Lissandra R self / Xayah R / Vladimir W / Elise E / Fizz E / Mel W) voids ALL
    # incoming damage for window_s of the fight, so it adds the avoided
    # ``window_s / _FIGHT_WINDOW_S`` damage FRACTION (capped, amortized) to the
    # numerator - the operator-chosen bounded additive model (the revive shape),
    # not a divergent uptime model. A window voids every damage type uniformly, so
    # it scales physical/magical/true by the same factor. ``apply_survival_window``
    # defaults False -> multiplier 1.0 -> BYTE-IDENTICAL to 1.104.0. The cooldown +
    # defensive-use gate is amortized inside the multiplier by the per-type midpoint.
    survival_window_mult = survival_window_multiplier(
        resolved.champion_id, level, apply_survival_window, _FIGHT_WINDOW_S
    )
    # ITEM 316 (2026-06-06): Anivia Rebirth EGG-STATE resist seam. The self-revive
    # EXTRA (``revive_mult - 1``) is the death-triggered second-life pool; for
    # Anivia that pool must survive the resurrection EGG, which fights through
    # MODIFIED resists (-40:20 by level bonus armor + MR), NOT her normal fighting
    # resists. Reshape the self-revive extra per damage type by the resist-curve
    # ratio ``_armor_factor(eff)/_armor_factor(eff+egg)``; true EHP ignores resists
    # so the egg never touches it. ITEM 321 (2026-06-06, ENGINE 1.120.0): the
    # ``apply_egg_resist`` default is now True (default-ON cutover); a caller
    # passes False to recover the prior scalar path. Non-Anivia / non-revive
    # callers are unaffected (the egg deltas are 0.0 -> ratio 1.0). ext_revive
    # (ally revive) + survival_window stay
    # multiplicative on the whole (independent second lives through normal resists).
    egg_armor, egg_mr = revive_egg_resist(
        resolved.champion_id, level, apply_egg_resist
    )
    revive_extra = max(0.0, revive_mult - 1.0)
    egg_ratio_phys = (
        _armor_factor(eff_armor) / _armor_factor(eff_armor + egg_armor)
        if egg_armor
        else 1.0
    )
    egg_ratio_mag = (
        _armor_factor(eff_mr) / _armor_factor(eff_mr + egg_mr)
        if egg_mr
        else 1.0
    )
    common_revive = ext_revive * survival_window_mult
    physical_ehp *= (1.0 + revive_extra * egg_ratio_phys) * common_revive
    magical_ehp *= (1.0 + revive_extra * egg_ratio_mag) * common_revive
    true_ehp *= (1.0 + revive_extra) * common_revive

    enemy_true_share = max(0.0, 1.0 - enemy_ad_share - enemy_ap_share)
    blended_ehp = (
        physical_ehp * enemy_ad_share
        + magical_ehp * enemy_ap_share
        + true_ehp * enemy_true_share
    )

    # ENGINE 1.121.0 (2026-06-14): SUSTAIN contract-gap closure. A SIBLING
    # effective-survivability term (the cc_blended_ehp pattern) that NAMES the
    # vamp-inclusive EHP and folds in the previously-unconsumed spellvamp /
    # omnivamp stats. blended_ehp above is UNTOUCHED (byte-identical): it
    # already carries the lifesteal heal pool (heal_total) since ENGINE 1.28.0.
    # _blend_with_heal recomputes the blend for an arbitrary heal scalar using
    # the SAME locals as the main math (shields, eff resists, mode, mit, revive
    # / egg / window numerator mults), so _blend_with_heal(heal_total) is
    # exactly blended_ehp (guard-tested). The vamp heals reuse the lifesteal
    # AA-throughput proxy (_vamp_heal_pool); spellvamp / omnivamp resolve to 0
    # on every current build (no SR item grants them - VampStatResolutionEdge),
    # so effective_ehp_with_sustain == blended_ehp today and diverges only when
    # such an item lands.
    def _blend_with_heal(heal_scalar: float) -> float:
        # Mirror the main numerators (incl flat_mit_<type>) so
        # _blend_with_heal(heal_total) stays exactly blended_ehp (guard-tested);
        # flat_mit_* is 0.0 when the flag is off -> byte-identical.
        p = (hp + ext_flat_hp + flat_mit_phys + shield_any_amped + shield_phys_amped + heal_scalar) / (
            _armor_factor(eff_armor) * safe_mult * mit_phys * item_crit_dr_mult * item_aa_dr_mult * item_enemy_as_slow_mult
        )
        m = (hp + ext_flat_hp + flat_mit_mag + shield_any_amped + shield_mag_amped + heal_scalar) / (
            _armor_factor(eff_mr) * safe_mult * mit_mag
        )
        t = (hp + ext_flat_hp + flat_mit_true + shield_any_amped + shield_true_amped + heal_scalar) / (
            safe_mult * mit_true
        )
        p *= (1.0 + revive_extra * egg_ratio_phys) * common_revive
        m *= (1.0 + revive_extra * egg_ratio_mag) * common_revive
        t *= (1.0 + revive_extra) * common_revive
        return (
            p * enemy_ad_share + m * enemy_ap_share + t * enemy_true_share
        )

    ad_stat = float(stats.get("ad", 0.0))
    as_stat = float(stats.get("as", 0.0))
    heal_spellvamp = _vamp_heal_pool(
        float(stats.get("spellvamp", 0.0)), ad_stat, as_stat
    )
    heal_omnivamp = _vamp_heal_pool(
        float(stats.get("omnivamp", 0.0)), ad_stat, as_stat
    )
    vamp_extra_amped = (heal_spellvamp + heal_omnivamp) * heal_amp_mult
    effective_ehp_with_sustain = _blend_with_heal(heal_total + vamp_extra_amped)
    ehp_without_sustain = _blend_with_heal(heal_item_total * heal_amp_mult)
    sustain_ehp_delta = effective_ehp_with_sustain - ehp_without_sustain

    # ENGINE 1.33.0 (2026-05-22): EHP-vs-CC blended scorer. Second
    # engine math consumer of ``compute_cc_pressure`` (the first was
    # the coach-prompt-side ``core/enemy_cc_threat_context.py`` per
    # item 136 Slice B). Default-empty ``enemy_champions`` leaves all
    # three new fields at identity (0.0 / 0.0 / equal to ``blended_ehp``)
    # so all existing callers stay byte-identical in their EHP math.
    #
    # Lazy import of ``compute_cc_pressure`` avoids a module-load
    # circular import: ``cc_pressure.py`` imports ``effective_cc_duration``
    # from this module, so we cannot eagerly import the reverse at the
    # top of ``ehp.py`` (Python would see a partial module). Lazy import
    # inside the function is safe - by call time both modules are fully
    # loaded.
    enemy_cc_pressure_s = 0.0
    cc_pressure_fraction = 0.0
    cc_blended_ehp = blended_ehp  # identity for the empty enemy_champions case
    # ENGINE 1.103.0 (item 290): the champion's innate tenacity fraction (0.0 when
    # the flag is off = byte-identical). Resolved once here so the EhpResult field
    # is populated even with no enemy comp; consumed in the cc block below.
    champion_tenacity_frac = (
        champion_cc_tenacity_fraction(champion_id, level, True)
        if apply_champion_tenacity else 0.0
    )
    # ENGINE 1.104.0 (item 292): the champion's SELF spell-shield block fraction
    # (0.0 when the flag is off = byte-identical). Resolved once here so the
    # EhpResult field is populated even with no enemy comp; a SEPARATE axis from
    # the tenacity fraction (a single-CC-instance block, not a duration scale) -
    # applied as its own discount AFTER the tenacity step in the cc block below.
    spell_shield_frac = (
        champion_spell_shield_fraction(champion_id, level, True)
        if apply_spell_shield else 0.0
    )
    if enemy_champions:
        from .cc_pressure import compute_cc_pressure

        cc_total = 0.0
        for enemy in enemy_champions:
            if not enemy:
                continue
            # ENGINE 1.39.0 (2026-05-22): SECOND authorized consumer
            # wire of the cc_conditional registry. The
            # ``include_conditional`` kwarg flows through to each
            # per-enemy compute_cc_pressure call so the conditional
            # post-tenacity contribution lands inside total_cc_seconds.
            # Default False preserves byte-identical 1.38.0 behavior for
            # every existing caller (the 4 cc_blended_ehp consumers stay
            # unchanged unless an explicit opt-in flows in).
            cc_total += compute_cc_pressure(
                enemy, mode, include_conditional=include_conditional
            ).total_cc_seconds
        # Item 236: OPT-IN build-tenacity credit. Tenacity shortens the CC the
        # CASTER actually eats, so it shrinks the enemy CC pressure for THIS
        # build (build-dependent -> the cc_blended ranking mode can now re-rank
        # tenacity items up vs a heavy-CC comp). Reuses the documented
        # effective_cc_duration tenacity seam (tenacity_mult = 1 - fraction).
        # Default False = the pre-item-236 build-independent discount
        # (byte-identical for every existing enemy_champions caller).
        # ENGINE 1.103.0 (2026-06-03): item 290 adds the CHAMPION-innate tenacity
        # source (Garen W / Olaf R / Malzahar P) as the third tenacity credit on
        # this same seam. League tenacity stacks MULTIPLICATIVELY, so the item and
        # champion fractions combine as (1 - item_frac) * (1 - champ_frac). Each
        # flag is independent + default-off; with only apply_build_tenacity on this
        # is byte-identical to the item-236 single-source path (champ_frac = 0.0).
        ten_remaining = 1.0
        if apply_build_tenacity:
            from ._item_tenacity import total_item_tenacity
            ten_remaining *= (1.0 - total_item_tenacity(item_ids or ()))
        if apply_champion_tenacity:
            ten_remaining *= (1.0 - champion_tenacity_frac)
        ten_frac = 1.0 - ten_remaining
        if ten_frac > 0.0:
            cc_total = effective_cc_duration(cc_total, 1.0 - ten_frac)
        # ENGINE 1.104.0 (item 292): the SELF spell-shield block-one negation - a
        # SEPARATE axis from tenacity (a probabilistic single-CC-instance block,
        # NOT a duration scale), so it is applied as its OWN multiplicative
        # discount on the post-tenacity pressure rather than on the
        # effective_cc_duration tenacity seam. Default-off (frac 0.0) = no-op.
        if apply_spell_shield and spell_shield_frac > 0.0:
            cc_total *= (1.0 - spell_shield_frac)
        enemy_cc_pressure_s = cc_total
        if enemy_cc_pressure_s > 0:
            cc_pressure_fraction = min(
                enemy_cc_pressure_s / _FIGHT_WINDOW_S, 1.0
            )
            cc_blended_ehp = blended_ehp * (
                1.0 - cc_pressure_fraction * _CC_EFFECTIVENESS_FACTOR
            )

    notes = list(resolved.notes)
    if mode == "ARAM" and mode_mult != 1.0:
        notes.append(
            f"ARAM aramDamageTaken={mode_mult:.3f} on all incoming damage "
            f"(EHP scaled by x{1.0 / safe_mult:.3f})"
        )
    if mode == "ARAM" and aram_tenacity_mult != 1.0:
        notes.append(
            f"ARAM aramTenacity={aram_tenacity_mult:.3f}x effective CC duration "
            f"(consumers via effective_cc_duration helper)"
        )
    for item_id, damage_type, sh_hp in shield_sources:
        eff = ITEM_EFFECTS.get(item_id)
        item_label = eff.name if eff is not None else item_id
        notes.append(
            f"shield: {item_label} contributes {sh_hp:.0f} hp ({damage_type})"
        )
    for item_id, heal_hp in heal_sources:
        eff = ITEM_EFFECTS.get(item_id)
        item_label = eff.name if eff is not None else item_id
        notes.append(
            f"heal: {item_label} contributes {heal_hp:.0f} hp per fight "
            f"(pre-amp)"
        )
    if heal_lifesteal > 0:
        notes.append(
            f"heal: lifesteal {heal_lifesteal:.0f} hp over "
            f"{_FIGHT_WINDOW_S:.0f}s window (pre-amp)"
        )
    if heal_amp_mult != 1.0:
        notes.append(
            f"heal: amp x{heal_amp_mult:.3f} applied multiplicatively "
            f"(Spirit Visage Boundless Vitality and similar)"
        )
    if shield_amp_mult != 1.0 and (shield_any or shield_phys or shield_mag or shield_true):
        notes.append(
            f"shield: amp x{shield_amp_mult:.3f} applied multiplicatively "
            f"to shield pool (Spirit Visage Boundless Vitality amps "
            f"heal AND shielding +25%)"
        )
    if enemy_cc_pressure_s > 0:
        notes.append(
            f"enemy_cc: {enemy_cc_pressure_s:.2f}s summed post-tenacity "
            f"(fraction={cc_pressure_fraction:.2f}) - blended_ehp "
            f"discounted by "
            f"{cc_pressure_fraction * _CC_EFFECTIVENESS_FACTOR * 100:.0f}% "
            f"via _CC_EFFECTIVENESS_FACTOR=0.5"
        )
    if apply_passive_mitigation and (mit_phys != 1.0 or mit_mag != 1.0 or mit_true != 1.0):
        notes.append(
            f"passive_mitigation: effects-text damage reduction folded into the "
            f"EHP denominator (mit_phys=x{mit_phys:.3f} mit_mag=x{mit_mag:.3f} "
            f"mit_true=x{mit_true:.3f}; active DRs amortized at their "
            f"conditional_probability midpoint)"
        )
    if assume_passive_flat_mitigation and (
        flat_mit_phys != 0.0 or flat_mit_mag != 0.0 or flat_mit_true != 0.0
    ):
        notes.append(
            f"passive_flat_mitigation: per-instance flat damage reduction folded "
            f"into the EHP numerator as prevented HP (phys=+{flat_mit_phys:.0f} "
            f"mag=+{flat_mit_mag:.0f} true=+{flat_mit_true:.0f}; "
            f"instances * flat * prob over the fight window; the percent-DR "
            f"registry's excluded flat-amount sibling - Fizz P / Amumu E / Leona W)"
        )
    if apply_passive_resist and (bonus_armor != 0.0 or bonus_mr != 0.0):
        notes.append(
            f"passive_resist: effects-text bonus resists added to the armor/MR "
            f"denominator (+{bonus_armor:.1f} armor, +{bonus_mr:.1f} MR; active "
            f"grants amortized at their conditional_probability midpoint)"
        )
    if apply_passive_revive and revive_mult != 1.0:
        notes.append(
            f"passive_revive: effects-text death-triggered second life folded "
            f"into the EHP numerator (x{revive_mult:.3f}; revived HP fraction "
            f"exact, amortized at the _REVIVE_PROB availability+survival midpoint)"
        )
    if apply_survival_window and survival_window_mult != 1.0:
        notes.append(
            f"survival_window: effects-text guaranteed-survival window (untargetable"
            f"/stasis/invuln) folded into the EHP numerator (x{survival_window_mult:.3f}"
            f"; window duration exact, avoided fraction window_s/{_FIGHT_WINDOW_S:.0f}s "
            f"amortized at the availability midpoint)"
        )
    if ext_armor != 0.0 or ext_mr != 0.0 or ext_revive != 1.0 or ext_flat_hp != 0.0:
        notes.append(
            f"ally_grant: teammate-conferred ally-targeted survivability folded in "
            f"(+{ext_armor:.1f} armor, +{ext_mr:.1f} MR into the denominator, "
            f"+{ext_flat_hp:.1f} flat HP (enchanter shield/heal) on the numerator, "
            f"x{ext_revive:.3f} revive on the numerator; sourced from "
            f"_passive_ally_grant_overrides, the sixth survivability axis)"
        )
    # T1-F3 (2026-06-09): surface the opt-in enemy-pen step when active. The
    # reported armor/mr are the resolved build stats; eff_armor / eff_mr above
    # are the post-pen values the EHP math consumed.
    if enemy_shred_pct or enemy_armor_pen_pct or enemy_lethality:
        notes.append(
            f"enemy_armor_pen: shred={_clamp_pct(enemy_shred_pct) * 100:.0f}% -> "
            f"pct_pen={_clamp_pct(enemy_armor_pen_pct) * 100:.0f}% -> "
            f"lethality={max(0.0, enemy_lethality):.0f} flat "
            f"(armor {armor + bonus_armor + ext_armor:.1f} -> {eff_armor:.1f} effective)"
        )
    if enemy_magic_pen_pct or enemy_magic_pen_flat:
        notes.append(
            f"enemy_magic_pen: pct_pen={_clamp_pct(enemy_magic_pen_pct) * 100:.0f}% -> "
            f"flat={max(0.0, enemy_magic_pen_flat):.0f} "
            f"(MR {mr + bonus_mr + ext_mr:.1f} -> {eff_mr:.1f} effective)"
        )

    return EhpResult(
        champion_id=resolved.champion_id,
        champion_name=resolved.champion_name,
        level=level,
        item_ids=resolved.item_ids,
        mode=mode,
        hp=hp,
        armor=armor,
        mr=mr,
        physical_ehp=physical_ehp,
        magical_ehp=magical_ehp,
        true_ehp=true_ehp,
        blended_ehp=blended_ehp,
        enemy_ad_share=enemy_ad_share,
        enemy_ap_share=enemy_ap_share,
        enemy_true_share=enemy_true_share,
        mode_multiplier=mode_mult,
        aram_tenacity_mult=aram_tenacity_mult,
        shield_any=shield_any,
        shield_phys=shield_phys,
        shield_mag=shield_mag,
        shield_true=shield_true,
        shield_sources=shield_sources,
        shield_amp_mult=shield_amp_mult,
        heal_item_total=heal_item_total,
        heal_lifesteal=heal_lifesteal,
        heal_amp_mult=heal_amp_mult,
        heal_total=heal_total,
        heal_sources=heal_sources,
        enemy_cc_pressure_s=enemy_cc_pressure_s,
        cc_pressure_fraction=cc_pressure_fraction,
        cc_blended_ehp=cc_blended_ehp,
        passive_mitigation_phys=mit_phys,
        passive_mitigation_mag=mit_mag,
        passive_mitigation_true=mit_true,
        passive_resist_armor=bonus_armor,
        passive_resist_mr=bonus_mr,
        passive_revive_mult=revive_mult,
        ally_grant_flat_hp=ext_flat_hp,
        ally_grant_armor=ext_armor,
        ally_grant_mr=ext_mr,
        ally_grant_revive_mult=ext_revive,
        champion_tenacity_frac=champion_tenacity_frac,
        spell_shield_frac=spell_shield_frac,
        survival_window_mult=survival_window_mult,
        effective_ehp_with_sustain=effective_ehp_with_sustain,
        ehp_without_sustain=ehp_without_sustain,
        sustain_ehp_delta=sustain_ehp_delta,
        heal_spellvamp=heal_spellvamp,
        heal_omnivamp=heal_omnivamp,
        passive_flat_mit_phys=flat_mit_phys,
        passive_flat_mit_mag=flat_mit_mag,
        passive_flat_mit_true=flat_mit_true,
        stats=dict(stats),
        notes=tuple(notes),
    )


# --------------------------------------------------- T1-F4 gold efficiency


# 16.12 standard per-point gold cost of the three pure defensive stats.
# Source: League of Legends Wiki "Gold efficiency" reference values
# (https://wiki.leagueoflegends.com/en-us/Gold_efficiency), the same
# convention the lift-doc target (seb16120 stat advisor) uses for its
# "EHP per gold" verdict (docs/COMPETITOR_LIFT_2026-06-08.md lines 68-75):
# Cloth Armor 300g / 15 armor = 20g per armor; Null-Magic Mantle 450g /
# 25 MR = 18g per MR; Ruby Crystal 400g / 150 HP = 2.6667g per HP. These
# are the canonical "raw stat" gold values RC uses ONLY for the per-unit
# stat verdict; whole-item gold efficiency stays in rank.py.
_GOLD_PER_ARMOR = 20.0
_GOLD_PER_MR = 18.0
_GOLD_PER_HP = 400.0 / 150.0  # 2.6667g per HP


def ehp_gold_efficiency(
    snapshot: DataSnapshot,
    champion_id: str,
    level: int,
    item_ids: Optional[Iterable[str | int]] = None,
    mode: str = "SR",
    enemy_ad_share: float = 0.5,
    enemy_ap_share: float = 0.5,
    augments: Optional[Iterable] = None,
    apply_mode_modifiers: bool = False,
    enemy_lethality: float = 0.0,
    enemy_armor_pen_pct: float = 0.0,
    enemy_shred_pct: float = 0.0,
    enemy_magic_pen_flat: float = 0.0,
    enemy_magic_pen_pct: float = 0.0,
) -> dict:
    """Marginal EHP gained per 1 gold for ARMOR vs MR vs HP.

    T1-F4 (BACKLOG LOW, docs/COMPETITOR_LIFT_2026-06-08.md lines 68-75) -
    the per-unit-stat gold-efficiency verdict built on the shipped T1-F3
    enemy-pen seam. Given the champion's CURRENT resolved armor / MR / HP
    context (the same build + enemy-mix structures ``compute_ehp`` already
    resolves), this returns how much blended EHP each of +1 armor, +1 MR,
    and +1 HP buys, the per-gold figure for each (dividing by the 16.12
    standard ``_GOLD_PER_*`` constants), and a "buy this stat next" verdict
    so the most gold-efficient defensive stat versus a given enemy AD/AP
    damage-mix is identifiable.

    PURE COMPUTE-ONLY / ADDITIVE: this helper is wired to NO live surface
    (a live flip is a gated follow-up - do not flip blind). It calls
    ``compute_ehp`` and does not mutate it; every existing caller of
    ``compute_ehp`` stays byte-identical.

    Method (finite-difference over the SHIPPED ``compute_ehp`` seams, so
    the marginals agree with the scorer's own math):

    * ARMOR / MR marginal - re-evaluate ``compute_ehp`` with the existing
      ``external_resist_armor`` / ``external_resist_mr`` kwarg bumped by
      +1. Those kwargs add into ``eff_armor`` / ``eff_mr`` at exactly the
      point a real +1 of the stat would (BEFORE the T1-F3 pen step), so a
      lethality-stacked enemy correctly buys you LESS armor EHP (the gap to
      the un-penned case is the whole point of riding T1-F3). The marginal
      is ``blended_ehp(stat+1) - blended_ehp(stat)``.
    * HP marginal - +1 HP scales every per-type EHP numerator
      proportionally (HP, shields, and heals share the damage-taken
      factor), so the blended-EHP gain from +1 HP is
      ``blended_ehp / hp`` (exact for a naked build where every numerator
      is HP; a faithful proportional approximation once shields/heals are
      present, consistent with the rest of the scorer's posture). There is
      no ``external_hp`` kwarg on ``compute_ehp``, so the analytic ratio is
      used rather than inventing one.

    Enemy-pen kwargs (the five T1-F3 ``enemy_*`` scalars) are forwarded to
    BOTH the base and the bumped calls so the verdict reflects the enemy's
    real penetration. All five default to 0.0 -> the un-penned verdict.

    Returns a plain dict (no new dataclass needed for a single derived
    readout):

      {
        "champion_id", "champion_name", "level", "mode",
        "armor", "mr", "hp",                 # resolved current stats
        "enemy_ad_share", "enemy_ap_share",
        "ehp_gain_armor", "ehp_gain_mr", "ehp_gain_hp",      # +1 stat -> +EHP
        "ehp_per_gold_armor", "ehp_per_gold_mr", "ehp_per_gold_hp",
        "best_stat", "best_ehp_per_gold",    # argmax verdict
        "second_best_stat", "gap_to_second", # margin over the runner-up
      }
    """
    base = compute_ehp(
        snapshot, champion_id, level, item_ids=item_ids, mode=mode,
        enemy_ad_share=enemy_ad_share, enemy_ap_share=enemy_ap_share,
        augments=augments, apply_mode_modifiers=apply_mode_modifiers,
        enemy_lethality=enemy_lethality,
        enemy_armor_pen_pct=enemy_armor_pen_pct,
        enemy_shred_pct=enemy_shred_pct,
        enemy_magic_pen_flat=enemy_magic_pen_flat,
        enemy_magic_pen_pct=enemy_magic_pen_pct,
    )

    def _blended_with(**extra) -> float:
        return compute_ehp(
            snapshot, champion_id, level, item_ids=item_ids, mode=mode,
            enemy_ad_share=enemy_ad_share, enemy_ap_share=enemy_ap_share,
            augments=augments, apply_mode_modifiers=apply_mode_modifiers,
            enemy_lethality=enemy_lethality,
            enemy_armor_pen_pct=enemy_armor_pen_pct,
            enemy_shred_pct=enemy_shred_pct,
            enemy_magic_pen_flat=enemy_magic_pen_flat,
            enemy_magic_pen_pct=enemy_magic_pen_pct,
            **extra,
        ).blended_ehp

    ehp_gain_armor = max(0.0, _blended_with(external_resist_armor=1.0) - base.blended_ehp)
    ehp_gain_mr = max(0.0, _blended_with(external_resist_mr=1.0) - base.blended_ehp)
    # +1 HP scales the numerator proportionally (see docstring). Guard a
    # pathological zero-HP build (division-safety, mirrors safe_mult).
    ehp_gain_hp = (base.blended_ehp / base.hp) if base.hp > 0 else 0.0

    per_gold = {
        "armor": ehp_gain_armor / _GOLD_PER_ARMOR,
        "mr": ehp_gain_mr / _GOLD_PER_MR,
        "hp": ehp_gain_hp / _GOLD_PER_HP,
    }
    # Stable argmax: ties resolve to the lowest-cost stat first (HP < MR <
    # armor by gold cost) by ordering the candidate list, then taking the
    # max by per-gold value.
    order = ["hp", "mr", "armor"]
    best_stat = max(order, key=lambda s: per_gold[s])
    runner = [s for s in order if s != best_stat]
    second_best_stat = max(runner, key=lambda s: per_gold[s])
    gap_to_second = per_gold[best_stat] - per_gold[second_best_stat]

    return {
        "champion_id": base.champion_id,
        "champion_name": base.champion_name,
        "level": base.level,
        "mode": base.mode,
        "armor": base.armor,
        "mr": base.mr,
        "hp": base.hp,
        "enemy_ad_share": base.enemy_ad_share,
        "enemy_ap_share": base.enemy_ap_share,
        "ehp_gain_armor": ehp_gain_armor,
        "ehp_gain_mr": ehp_gain_mr,
        "ehp_gain_hp": ehp_gain_hp,
        "ehp_per_gold_armor": per_gold["armor"],
        "ehp_per_gold_mr": per_gold["mr"],
        "ehp_per_gold_hp": per_gold["hp"],
        "best_stat": best_stat,
        "best_ehp_per_gold": per_gold[best_stat],
        "second_best_stat": second_best_stat,
        "gap_to_second": gap_to_second,
    }


# ----------------------------------------------------------------- ranker


@dataclass(frozen=True)
class EhpRankedItem:
    item_id: str
    item_name: str
    gold: int
    delta_ehp: float             # blended_ehp with item - baseline blended_ehp
    new_ehp: float
    ehp_per_1k_gold: float       # delta_ehp / (gold/1000); 0 when delta<=0
    is_terminal: bool
    tags: tuple[str, ...]
    # Phase 0 dead-unique filter mirror - see ``rank.RankedItem`` for the
    # full rationale. Same flag, same dedup semantics: a candidate whose
    # unique_passive_key collides with an item already in current_item_ids
    # is filtered by default (proc/pen would be zeroed by collect_effects).
    # For EHP this matters less than for DPS (most defensive items don't
    # share unique_passive_keys), but the lifeline family (Sterak's, Maw,
    # Shieldbow, Verdant Barrier, Hexdrinker, Protoplasm Harness, Seraph's,
    # Lifeline component) is a real conflict source.
    shares_dead_unique: bool = False
    dead_unique_key: str = ""
    # Phase 4(d): candidate's own unique-passive family key, always set
    # (collision-independent) - the positive "locks <family>" signal.
    unique_passive_key: str = ""
    # Item 236: CC-adjusted EHP surface. ``cc_blended_ehp`` is the new build's
    # blended EHP discounted by the enemy comp's CC-lockdown fraction (== new_ehp
    # when no enemy_champions are supplied, by the compute_ehp identity contract).
    # ``delta_cc_blended_ehp`` is that value's gain over the baseline build. When
    # the ranker runs ``score_by="cc_blended"`` the sort + efficiency key uses
    # ``delta_cc_blended_ehp``; the default ``score_by="blended"`` leaves both at
    # their no-enemy identity (cc == blended) so the row stays byte-identical.
    cc_blended_ehp: float = 0.0
    delta_cc_blended_ehp: float = 0.0
    # RF3 (2026-06-17, ENGINE 1.138.0): 1.0 on a WIN-anchored survivability item
    # floated by the DEFAULT-OFF ``prefer_survivability_by_win`` seam, else 0.0.
    # The EHP scorer ALREADY pools these resist/HP items - its raw-EHP-max sort
    # just buries the win-correlated mid-tier ones (KSante Thornmail/Iceborn,
    # Rell Fimbulwinter). When the seam is ON the marker prefixes the sort key so
    # the tabled rows float to the front BY MEMBERSHIP (no injection - RF1's shape,
    # not RF2's). Default 0.0 leaves the row + sort byte-identical.
    survivability_score: float = 0.0

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "item_name": self.item_name,
            "gold": self.gold,
            "delta_ehp": self.delta_ehp,
            "new_ehp": self.new_ehp,
            "ehp_per_1k_gold": self.ehp_per_1k_gold,
            "is_terminal": self.is_terminal,
            "tags": list(self.tags),
            "shares_dead_unique": self.shares_dead_unique,
            "dead_unique_key": self.dead_unique_key,
            "unique_passive_key": self.unique_passive_key,
            "cc_blended_ehp": self.cc_blended_ehp,
            "delta_cc_blended_ehp": self.delta_cc_blended_ehp,
            "survivability_score": self.survivability_score,
        }


@dataclass(frozen=True)
class EhpRankResult:
    champion_id: str
    champion_name: str
    level: int
    mode: str
    current_item_ids: tuple[str, ...]
    baseline_ehp: float
    enemy_ad_share: float
    enemy_ap_share: float
    enemy_true_share: float
    budget: Optional[int]
    slot_count: int
    sort_by: str
    candidates_considered: int
    candidates_evaluated: int
    ranked: tuple[EhpRankedItem, ...]
    notes: tuple[str, ...] = field(default_factory=tuple)
    # Item 236: which EHP metric drove the ranking - "blended" (default,
    # PRE-cc) or "cc_blended" (enemy-CC-lockdown-adjusted).
    score_by: str = "blended"

    def to_dict(self) -> dict:
        return {
            "champion_id": self.champion_id,
            "champion_name": self.champion_name,
            "level": self.level,
            "mode": self.mode,
            "current_item_ids": list(self.current_item_ids),
            "baseline_ehp": self.baseline_ehp,
            "enemy_ad_share": self.enemy_ad_share,
            "enemy_ap_share": self.enemy_ap_share,
            "enemy_true_share": self.enemy_true_share,
            "budget": self.budget,
            "slot_count": self.slot_count,
            "sort_by": self.sort_by,
            "score_by": self.score_by,
            "candidates_considered": self.candidates_considered,
            "candidates_evaluated": self.candidates_evaluated,
            "ranked": [r.to_dict() for r in self.ranked],
            "notes": list(self.notes),
        }

    def format_table(self) -> str:
        head = (
            f"{self.champion_name} ({self.champion_id}) - lvl {self.level} "
            f"- mode {self.mode}  [TANK]"
        )
        rows = [head, "-" * len(head)]
        if self.current_item_ids:
            rows.append(f"current items: {', '.join(self.current_item_ids)}")
        else:
            rows.append("current items: (none)")
        rows.append(
            f"enemy mix: AD={self.enemy_ad_share * 100:.0f}%  "
            f"AP={self.enemy_ap_share * 100:.0f}%  "
            f"true={self.enemy_true_share * 100:.0f}%"
        )
        budget_label = "unlimited" if self.budget is None else f"{self.budget}"
        rows.append(
            f"budget: {budget_label}  slots: {len(self.current_item_ids)}/{self.slot_count}"
            f"  sort: {self.sort_by}"
        )
        rows.append(
            f"baseline_ehp: {self.baseline_ehp:.0f}   "
            f"considered/evaluated: {self.candidates_considered}/{self.candidates_evaluated}"
        )
        rows.append("")
        rows.append(
            f"  {'#':>3}  {'id':>6}  {'name':<28}  "
            f"{'gold':>5}  {'+ehp':>7}  {'new':>7}  {'ehp/1k':>7}"
        )
        rows.append("  " + "-" * 78)
        for i, r in enumerate(self.ranked, 1):
            rows.append(
                f"  {i:>3}  {r.item_id:>6}  {r.item_name[:28]:<28}  "
                f"{r.gold:>5}  {r.delta_ehp:>7.1f}  {r.new_ehp:>7.0f}  "
                f"{r.ehp_per_1k_gold:>7.1f}"
            )
        if self.notes:
            rows.append("")
            for n in self.notes:
                rows.append(f"  note: {n}")
        return "\n".join(rows)


def rank_items_by_ehp(
    snapshot: DataSnapshot,
    champion_id: str,
    level: int,
    current_item_ids: Optional[Iterable[str | int]] = None,
    mode: str = "SR",
    enemy_ad_share: float = 0.5,
    enemy_ap_share: float = 0.5,
    budget: Optional[int] = None,
    slot_count: int = DEFAULT_SLOT_COUNT,
    top_n: int = DEFAULT_TOP_N,
    include_components: bool = False,
    only_item_ids: Optional[Iterable[str | int]] = None,
    sort_by: str = "delta",
    augments: Optional[Iterable] = None,
    filter_shared_uniques: bool = True,
    apply_mode_modifiers: bool = False,
    enemy_champions: Iterable[str] = (),
    include_conditional: bool = False,
    score_by: str = "blended",
    apply_build_tenacity: Optional[bool] = None,
    apply_passive_mitigation: bool = False,
    assume_passive_flat_mitigation: bool = False,
    apply_passive_resist: bool = False,
    apply_passive_revive: bool = False,
    apply_champion_tenacity: bool = False,
    apply_spell_shield: bool = False,
    apply_survival_window: bool = False,
    prefer_survivability_by_win: bool = False,
    cost_ceiling: Optional[int] = None,
) -> EhpRankResult:
    """Rank items by blended-EHP contribution when added to ``current_item_ids``.

    Mirror of ``rank.rank_items`` for the EHP scorer. Same candidate
    filtering pipeline (purchasable + mode-legal + optional whitelist +
    budget + terminal-only) - only the scoring function differs.

    Sort keys:
      * ``delta``       - absolute EHP gained (default)
      * ``efficiency``  - EHP gained per 1000 gold spent

    ``only_item_ids`` is the integration point for the s171
    ``core/defensive_picks.py`` curated catalog (Option B from the s174
    design conversation): the catalog is passed as a whitelist so the
    math-driven ranking happens within an operator-vetted pool.

    Item 236 - CC-adjusted ranking. ``score_by`` selects the EHP metric the
    sort + efficiency key rank on:
      * ``"blended"`` (default) - PRE-cc ``blended_ehp`` delta. BYTE-IDENTICAL
        to the pre-item-236 behavior (the ``cc_blended_ehp`` / ``delta_cc_blended_ehp``
        row fields still populate, but at their no-enemy identity ``cc == blended``
        so nothing about the ordering changes).
      * ``"cc_blended"`` - the enemy-CC-lockdown-adjusted ``cc_blended_ehp`` delta.
        A tank picking into a heavy-CC comp ranks by CC-adjusted effective HP.
    ``enemy_champions`` (the enemy comp) + ``include_conditional`` (fold the
    probability-weighted conditional-CC registry into the discount) are threaded
    into every ``compute_ehp`` call so the baseline + each candidate share the
    same enemy context. Both are no-ops on ``blended_ehp`` (compute_ehp computes
    ``blended_ehp`` before the enemy-CC block), so supplying them under the
    default ``score_by="blended"`` is still byte-identical to today.

    RF3 (2026-06-17, ENGINE 1.138.0): ``prefer_survivability_by_win`` (default
    False) is the OPTIONAL tank-template seam. The EHP scorer pools every terminal
    resist/HP item but sorts purely by ``delta_ehp`` (blind to win-rate), so the
    WIN-correlated mid-tier survivability items the player base wins on (KSante
    Thornmail/Iceborn, Rell Fimbulwinter - the DSP10 ehp-lane buried winners) sink
    below the raw-EHP-max stackers. When ON, the champ's WIN-anchored
    ``survivability_item_credit_tank`` set is FLOATED above the rest BY MEMBERSHIP
    (the marker prefixes the sort key, model order preserved within each tier).

    RF6 (2026-06-17, ENGINE 1.139.0): the float alone is a no-op for a tabled id
    the pool DROPS. Rell's sole tabled winner Fimbulwinter 3121 is the
    non-purchasable mana-line transform of Winter's Approach
    (``gold.purchasable``=False), so ``_filter_candidates`` excludes it and RF3 has
    nothing to lift (RF4 verified in_pool=False; RF3's "already pooled" premise
    holds for KSante's Thornmail/Iceborn but is FALSE for Rell). RF6 therefore also
    INJECTS the tabled set via ``_filter_candidates(inject_ids=...)``, force-admitting
    it past the purchasable gate so it enters the pool and floats - RF2's inject
    intent, extended to clear the ``_is_purchasable`` gate the RF2 hps ``only_ids``
    union could not. OFF (default) the output is byte-identical: ``survivability_score``
    stays 0.0, the pool is unchanged (``inject_ids`` None), and the sort is unchanged.
    A champ ABSENT from the table is a no-op even when ON. The live default-ON flip
    is EXCLUDED (docs/LIVE_GAME_GATED_SYNC.md).
    """
    if sort_by not in SORT_KEYS:
        raise ValueError(f"sort_by must be one of {SORT_KEYS}, got {sort_by!r}")
    if score_by not in ("blended", "cc_blended"):
        raise ValueError(
            f"score_by must be 'blended' or 'cc_blended', got {score_by!r}"
        )
    enemy_champions = tuple(str(e) for e in (enemy_champions or ()))
    # Item 236: tenacity-credit defaults ON for cc_blended ranking (an
    # inert build-INDEPENDENT cc_blended discount cannot re-rank, so the
    # mode is only meaningful with the build-tenacity term) and OFF for the
    # default blended mode (keeps it byte-identical). Explicit bool overrides.
    apply_tenacity = (
        apply_build_tenacity if apply_build_tenacity is not None
        else (score_by == "cc_blended")
    )
    level = clamp_level(level)

    current_ids: tuple[str, ...] = tuple(str(i) for i in (current_item_ids or ()))
    current_ids, stripped_trinkets = strip_arena_trinkets(current_ids, mode)
    current_set = set(current_ids)
    # Collect unique_passive_keys already locked in. Same logic as
    # ``rank.rank_items`` - candidates colliding here are filtered by default.
    current_unique_keys: set[str] = set()
    for iid in current_ids:
        eff = ITEM_EFFECTS.get(iid)
        if eff is not None and eff.unique_passive_key:
            current_unique_keys.add(eff.unique_passive_key)

    if len(current_ids) >= slot_count:
        raise ValueError(
            f"current_item_ids has {len(current_ids)} items; slot_count={slot_count} "
            f"leaves no room for a new item"
        )

    only_ids: Optional[set[str]] = None
    if only_item_ids is not None:
        only_ids = {str(i) for i in only_item_ids}

    # RF3/RF6 (DEFAULT-OFF): resolve the champ's WIN-anchored tank survivability
    # item set. Empty unless the seam is ON AND the champ is tabled -> byte-identical
    # no-op. Most tabled ids are already pooled (the EHP scorer pools every terminal
    # resist/HP item) and the seam only FLOATS them by membership (RF3); RF6 also
    # INJECTS the ids the pool DROPS - a non-purchasable mana-line transform like
    # Rell's Fimbulwinter 3121 (gold.purchasable=False) is force-admitted via
    # _filter_candidates(inject_ids=...) so it can float instead of being a no-op.
    champ_rec = snapshot.champions.get(str(champion_id))
    surv_ids: frozenset[str] = (
        survivability_item_ids_tank(str(champion_id), champ_rec)
        if prefer_survivability_by_win else frozenset()
    )
    surv_active = bool(surv_ids)

    baseline = compute_ehp(
        snapshot,
        champion_id=champion_id,
        level=level,
        item_ids=current_ids,
        mode=mode,
        enemy_ad_share=enemy_ad_share,
        enemy_ap_share=enemy_ap_share,
        augments=augments,
        apply_mode_modifiers=apply_mode_modifiers,
        enemy_champions=enemy_champions,
        include_conditional=include_conditional,
        apply_build_tenacity=apply_tenacity,
        apply_passive_mitigation=apply_passive_mitigation,
        assume_passive_flat_mitigation=assume_passive_flat_mitigation,
        apply_passive_resist=apply_passive_resist,
        apply_passive_revive=apply_passive_revive,
        apply_champion_tenacity=apply_champion_tenacity,
        apply_spell_shield=apply_spell_shield,
        apply_survival_window=apply_survival_window,
    )

    candidates = _filter_candidates(
        snapshot,
        mode=mode,
        current_ids=current_set,
        budget=budget,
        include_components=include_components,
        only_ids=only_ids,
        # RF6: force-admit the tabled WIN-anchored survivability ids past the
        # _is_purchasable gate so a not-pooled mana-line transform (Rell's
        # Fimbulwinter 3121, gold.purchasable=False) surfaces and can float.
        # None when the seam is OFF / champ untabled -> byte-identical pool.
        inject_ids=(set(surv_ids) if surv_active else None),
        # F2 cost-aware-top seam (DEFAULT-OFF). Drops over-cost mega-items
        # (e.g. 6000g Void Immolation 223069) the absolute-EHP delta floats to
        # rank-1. None -> byte-identical pool.
        cost_ceiling=cost_ceiling,
        # Ranged-only purchasability gate: drop Runaan's (+ alias) for a melee
        # tank - the shop blocks the purchase (2026-07-02).
        champion_is_melee=_champion_is_melee(champ_rec),
    )

    ranked: list[EhpRankedItem] = []
    for item_id, rec in candidates:
        cand_eff = ITEM_EFFECTS.get(item_id)
        cand_key = cand_eff.unique_passive_key if cand_eff is not None else ""
        shares_dead_unique = bool(cand_key and cand_key in current_unique_keys)
        if shares_dead_unique and filter_shared_uniques:
            continue
        new_build = current_ids + (item_id,)
        try:
            scored = compute_ehp(
                snapshot,
                champion_id=champion_id,
                level=level,
                item_ids=new_build,
                mode=mode,
                enemy_ad_share=enemy_ad_share,
                enemy_ap_share=enemy_ap_share,
                augments=augments,
                apply_mode_modifiers=apply_mode_modifiers,
                enemy_champions=enemy_champions,
                include_conditional=include_conditional,
                apply_build_tenacity=apply_tenacity,
                apply_passive_mitigation=apply_passive_mitigation,
                assume_passive_flat_mitigation=assume_passive_flat_mitigation,
                apply_passive_resist=apply_passive_resist,
                apply_passive_revive=apply_passive_revive,
                apply_champion_tenacity=apply_champion_tenacity,
                apply_spell_shield=apply_spell_shield,
                apply_survival_window=apply_survival_window,
            )
        except (KeyError, ValueError):
            continue
        gold = int((rec.get("gold") or {}).get("total", 0) or 0)
        delta = scored.blended_ehp - baseline.blended_ehp
        cc_delta = scored.cc_blended_ehp - baseline.cc_blended_ehp
        # Item 236: the ACTIVE metric drives efficiency + sort. Default
        # score_by="blended" ranks on the PRE-cc delta (byte-identical: cc_delta
        # == delta when no enemy_champions); "cc_blended" ranks on the
        # enemy-CC-lockdown-adjusted delta. Negative / zero deltas zero-out the
        # per-1k column - regressions, not efficiency.
        active_delta = cc_delta if score_by == "cc_blended" else delta
        eff = (active_delta / (gold / 1000.0)) if (gold > 0 and active_delta > 0) else 0.0
        # RF3 survivability credit marker: 1.0 on a WIN-anchored survivability item
        # when the seam is engaged, else 0.0. Floated BY MEMBERSHIP - these items
        # are pooled but the raw-EHP-max delta sort buries the win-correlated ones.
        survivability_score = 1.0 if (surv_active and item_id in surv_ids) else 0.0
        ranked.append(EhpRankedItem(
            item_id=item_id,
            item_name=str(rec.get("name", item_id)),
            gold=gold,
            delta_ehp=delta,
            new_ehp=scored.blended_ehp,
            ehp_per_1k_gold=eff,
            is_terminal=_is_terminal(rec),
            tags=tuple(rec.get("tags") or ()),
            shares_dead_unique=shares_dead_unique,
            dead_unique_key=cand_key if shares_dead_unique else "",
            unique_passive_key=cand_key,
            cc_blended_ehp=scored.cc_blended_ehp,
            delta_cc_blended_ehp=cc_delta,
            survivability_score=survivability_score,
        ))

    # Item 236: the sort key tracks score_by. Default "blended" sorts on
    # delta_ehp (byte-identical); "cc_blended" sorts on delta_cc_blended_ehp.
    _active = (
        (lambda r: r.delta_cc_blended_ehp)
        if score_by == "cc_blended"
        else (lambda r: r.delta_ehp)
    )

    def _base_key(r: EhpRankedItem) -> tuple:
        if sort_by == "efficiency":
            return (r.ehp_per_1k_gold, _active(r))
        return (_active(r), r.ehp_per_1k_gold)

    if surv_active:
        # RF3: float surfaced survivability items above the max-EHP ordering,
        # preserving model order within each tier. Byte-identical when off
        # (surv_active False -> the prefix term is never added).
        ranked.sort(key=lambda r: (r.survivability_score,) + _base_key(r), reverse=True)
    else:
        ranked.sort(key=_base_key, reverse=True)

    if top_n is not None and top_n > 0:
        ranked = ranked[:top_n]

    notes: list[str] = []
    notes.append(
        f"enemy mix: AD {enemy_ad_share * 100:.0f}% / "
        f"AP {enemy_ap_share * 100:.0f}% / "
        f"true {baseline.enemy_true_share * 100:.0f}%"
    )
    if stripped_trinkets:
        notes.append(
            f"mode=ARENA - stripped trinket(s) {list(stripped_trinkets)} "
            f"from current_item_ids"
        )
    if include_components:
        notes.append("include_components=True - non-terminal items in the ranking")
    if budget is not None:
        notes.append(f"budget={budget}g - items over budget filtered")
    if only_ids is not None:
        notes.append(f"only_item_ids restricted to {len(only_ids)} whitelisted ids")
    if baseline.mode_multiplier != 1.0:
        notes.append(
            f"ARAM aramDamageTaken={baseline.mode_multiplier:.3f} "
            f"folded into all EHP values"
        )
    if score_by == "cc_blended":
        notes.append(
            f"score_by=cc_blended - ranked on CC-adjusted EHP vs "
            f"{len(enemy_champions)} enemy champ(s)"
            + ("" if enemy_champions else " (no enemies supplied -> identical to blended)")
        )
    if surv_active:
        notes.append(
            f"prefer_survivability_by_win=ON - {len(surv_ids)} WIN-anchored "
            f"survivability item(s) floated above the max-EHP ordering"
        )

    return EhpRankResult(
        champion_id=baseline.champion_id,
        champion_name=baseline.champion_name,
        level=level,
        mode=mode,
        current_item_ids=current_ids,
        baseline_ehp=baseline.blended_ehp,
        enemy_ad_share=enemy_ad_share,
        enemy_ap_share=enemy_ap_share,
        enemy_true_share=baseline.enemy_true_share,
        budget=budget,
        slot_count=slot_count,
        sort_by=sort_by,
        candidates_considered=len(snapshot.items),
        candidates_evaluated=len(candidates),
        ranked=tuple(ranked),
        notes=tuple(notes),
        score_by=score_by,
    )
