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

Bonus HP amps (Cinderhulk +15% bonus HP) flow through ``build_champion`` already
via the existing stat schema - no new field needed; EHP picks them up
automatically because ``stats["hp"]/["armor"]/["mr"]`` reflect the amp. NOTE
(corrected R106, 2026-07-11): Jak'Sho's Voidborn Resilience (+30% of BONUS armor
+ MR at 5 combat stacks) and Force of Nature's Steadfast (+70 bonus MR at 8
stacks) do NOT flow through ``build_champion`` - it folds only the items' FLAT
static resists (Jak'Sho +45/+45, FoN +55 MR), not the stacked combat ramp
(live-probe R105). That ramp is credited to the armor/MR DENOMINATOR by the
default-OFF ``apply_item_resist_grants`` seam (``_item_resist_grants``), the
item-side lane of the champion resist_grants axis.

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
from .effects import ITEM_EFFECTS, collect_effects
from ._effects_types import ANY, CallContext, MAGICAL, PHYSICAL, TRUE
from .engine import build_champion
from ._passive_mitigation_overrides import mitigation_multipliers
from ._passive_flat_mitigation_overrides import flat_mitigation_hp
from ._passive_health_overrides import passive_health_stack_hp
from ._passive_resist_overrides import resist_grants
from ._passive_revive_overrides import revive_multiplier, revive_egg_resist
from ._champion_cc_mitigation_overrides import champion_cc_tenacity_fraction
from ._champion_spell_shield_overrides import champion_spell_shield_fraction
from ._melee_ranged import (
    MELEE_RANGED_ATTACKRANGE_SPLIT,
    attackrange_is_ranged,
)
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
from .kit_conversion import conversion_factor, kit_conversion
from ._resist_damage_coupling import coupled_resist_points, resist_damage_coupling
from ._health_damage_coupling import coupled_health_points, health_damage_coupling
from ._mana_damage_coupling import coupled_mana_points, mana_damage_coupling
from ._item_caster_hp_proc import (
    _MAX_CONVERTED_FRACTION,
    _REFERENCE_FIGHT_SECONDS,
    item_caster_hp_proc,
    proc_converted_points,
)
from ._hsp_amp import sum_wielder_hsp_pct
from ._item_ally_grant import ally_grant_hp, total_item_ally_grant_hp
from ._champion_ally_reach import champion_ally_reach
from ._passive_ally_grant_overrides import _ALLY_SHIELD_HEAL_PROB


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


# RM-123: the melee/ranged split is now the shared canonical constant
# (``_melee_ranged.MELEE_RANGED_ATTACKRANGE_SPLIT`` = 350.0). Alias kept for the
# back-compat symbol name imported by test_ehp_shield_phase15.
_RANGED_ATTACKRANGE_THRESHOLD = MELEE_RANGED_ATTACKRANGE_SPLIT


def _is_ranged(base_stats: dict) -> bool:
    """Detect ranged-champion status by base attackrange.

    ENGINE 1.27.0 (2026-05-21): used by the shield-throughput scorer to
    pick the ``ItemShield.ranged_modifier`` (Maw / Shieldbow / Hexdrinker
    have ranged shields at 75-80% of melee values per Meraki 16.10.1).
    RM-123 (2026-07-29): split raised 250 -> 350 to match real League - the
    250 value wrongly classified Rakan (300) and Lillia (325), both MELEE, as
    ranged. Ranged now = base attackrange >= 350 (Urgot 350 / Caitlyn 650 /
    Lux 550); melee = below 350 (Yasuo 175 / Rakan 300 / Lillia 325). Aphelios
    and similar shifting-form champs default to their base attackrange.
    """
    return attackrange_is_ranged(base_stats.get("attackrange", 0.0))


def _collect_shields(
    item_ids: Iterable[str],
    level: int,
    bonus_hp: float,
    bonus_ad: float,
    is_ranged: bool,
    max_hp: float = 0.0,
    max_mana: float = 0.0,
    assume_kaenic_shield: bool = False,
    assume_eclipse_shield: bool = False,
    assume_chainlaced_shield: bool = False,
    assume_seraphs_shield: bool = False,
    assume_fimbulwinter_shield: bool = False,
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
        # Default-off (opt-in) shields are dropped unless the caller explicitly
        # arms the specific seam for THAT item. The arming is per-shield (keyed by
        # item id) so turning one conditional shield on never leaks credit into
        # another: R92 Kaenic Rookern (2504 / Arena 222504, mirror armed by
        # RM-104) rides assume_kaenic_shield (its
        # Magebane magic shield has an anti-correlated "no magic damage for 15s"
        # uptime); R97 Eclipse (6692 / Arena 226692) rides assume_eclipse_shield
        # (a burst-window shield on a 6s/target CD); R99 Chainlaced Crushers
        # (3173) rides assume_chainlaced_shield (its Noxian Persistence magic
        # shield triggers only on taking magic damage, 15s CD). Seraph's Embrace
        # (3040 / Arena 223040 / ARAM 323040) rides assume_seraphs_shield (its
        # Lifeline 18%-max-mana generic shield fires only at <30% HP). R129
        # Fimbulwinter (3121 / Arena 223121 / ARAM 323121) rides
        # assume_fimbulwinter_shield (its Everlasting 100 +4.5%-max-mana generic
        # shield fires on immobilizing an enemy, 8s CD). None is folded into the
        # always-on lifeline pool.
        if shield.default_off:
            iid = str(item_id)
            armed = (
                (assume_kaenic_shield and iid in ("2504", "222504"))
                or (assume_eclipse_shield and iid in ("6692", "226692"))
                or (assume_chainlaced_shield and iid == "3173")
                or (assume_seraphs_shield and iid in ("3040", "223040", "323040"))
                or (assume_fimbulwinter_shield and iid in ("3121", "223121", "323121"))
            )
            if not armed:
                continue
        hp = shield.resolve_magnitude(
            level=level,
            bonus_hp=bonus_hp,
            bonus_ad=bonus_ad,
            is_ranged=is_ranged,
            max_hp=max_hp,
            max_mana=max_mana,
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
# CURRENT DEFAULT (corrected 2026-07-25): ARMED. The helper below still defaults
# ``assume_item_crit_dr`` False, but every real caller overrides that -
# ``compute_ehp`` and ``rank_items_by_ehp`` both default it TRUE (the B45/B46
# operator flip, 2026-07-06), so the shipped tank ranking DOES carry this credit
# and Randuin's Omen leads the SR tank order partly because of it. The earlier
# "defaults False -> BYTE-IDENTICAL" note described the pre-flip posture and is
# no longer true of anything a caller can reach. Pass False explicitly (route key
# ``assume_item_crit_dr``, or the ``rank_tank_for`` kwarg) to opt back out.
_ASSUMED_INCOMING_CRIT_SHARE = 0.5


def item_crit_dr_multiplier(
    item_ids: Iterable[str],
    assume_item_crit_dr: bool = False,
) -> float:
    """Physical-denominator multiplier from item-keyed crit-damage reduction.

    Returns ``1.0`` (identity) when ``assume_item_crit_dr`` is False or no
    equipped item carries ``crit_damage_reduction``. NOTE the parameter default
    here is False but is NOT the shipped posture: ``compute_ehp`` /
    ``rank_items_by_ehp`` both pass True by default, so the live scorer runs this
    ARMED. When armed, each such item contributes ``(1 - crit_damage_reduction *
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
# EHP) when armed. CURRENT DEFAULT (corrected 2026-07-25): ARMED - the helper
# below still defaults ``assume_item_aa_dr`` False, but ``compute_ehp`` and
# ``rank_items_by_ehp`` both default it TRUE (the B45/B46 operator flip,
# 2026-07-06), so the shipped ranking carries this credit. The earlier "defaults
# False -> BYTE-IDENTICAL" note described the pre-flip posture. Pass False
# explicitly (route key ``assume_item_aa_dr``, or the ``rank_tank_for`` kwarg) to
# opt back out.
_ASSUMED_INCOMING_AA_SHARE = 0.5


def item_aa_dr_multiplier(
    item_ids: Iterable[str],
    assume_item_aa_dr: bool = False,
) -> float:
    """Physical-denominator multiplier from item-keyed basic-attack DR.

    Returns ``1.0`` (identity) when ``assume_item_aa_dr`` is False or no
    equipped item carries ``basic_attack_damage_reduction``. NOTE the parameter
    default here is False but is NOT the shipped posture: ``compute_ehp`` /
    ``rank_items_by_ehp`` both pass True by default, so the live scorer runs this
    ARMED. When armed, each such item contributes ``(1 - basic_attack_damage_reduction
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
# midpoint ``_ASSUMED_INCOMING_AA_SHARE`` (the live feed we lack). CURRENT
# DEFAULT (corrected 2026-07-25): ARMED. The helper below still defaults
# ``assume_item_enemy_as_slow`` False, but ``compute_ehp`` and
# ``rank_items_by_ehp`` both default it TRUE, so the shipped ranking carries this
# credit (Frozen Heart's dEHP is ~56 pct higher armed than forced off on a mid
# tank build). The earlier "Default False -> BYTE-IDENTICAL" note described a
# posture no reachable caller uses. Pass False explicitly (route key
# ``assume_item_enemy_as_slow``, or the ``rank_tank_for`` kwarg) to opt back out.
def item_enemy_as_slow_multiplier(
    item_ids: Iterable[str],
    assume_item_enemy_as_slow: bool = False,
) -> float:
    """Physical-denominator multiplier from item-keyed enemy AS-slow auras.

    Returns ``1.0`` (identity) when ``assume_item_enemy_as_slow`` is False or no
    equipped item carries ``enemy_attack_speed_slow``. NOTE the parameter default
    here is False but is NOT the shipped posture: ``compute_ehp`` /
    ``rank_items_by_ehp`` both pass True by default, so the live scorer runs this
    ARMED. When armed, each such item contributes ``(1 - enemy_attack_speed_slow *
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


def _crit_weighted_vamp_multiplier(
    item_ids: Iterable[str | int],
    crit_chance: float,
    caster_bonus_hp: float = 0.0,
    assume_crit_weighted_vamp: bool = False,
) -> float:
    """R193 (slice B): crit-weight factor for the vamp heal pool.

    Returns ``1.0`` (identity) when ``assume_crit_weighted_vamp`` is False - the
    shipped default, so every existing EHP number is byte-identical - and
    ``1 + crit_total * crit_damage_bonus_total`` when armed.

    WHY this seam exists: ``_vamp_heal_pool`` prices vamp off ``AD * AS *
    window``, the UNCRIT auto-attack throughput. An auto-attack actually lands
    ``AD * (1 + crit * crit_damage_bonus)`` (the expression DS already ships at
    dps.py:1283) and lifesteal heals off that crit-inflated hit, so a crit
    carry's sustain is under-credited by the whole crit factor (measured 306.18
    -> 547.30, x1.788, on a 5-item L16 Jinx). Crit is a WIELDER-side stat the
    EHP scorer already fully resolves - ``stats["crit"]`` plus the item-effect
    crit-chance lane (Yun Tal / Atma's) that dps.py:1083 folds in - so unlike an
    enemy-state term there is nothing to assume here.

    WHY it is nonetheless DEFAULT-OFF and operator-gated: the pool's
    pre-mitigation over-credit (vamp priced off PRE-armor damage) is a
    DELIBERATE enemy-agnostic posture of this scorer, not an oversight - see the
    ``_vamp_heal_pool`` docstring. Arming this seam multiplies the crit factor
    straight into that same unmitigated number, so it WIDENS the pre-mitigation
    over-credit on exactly the crit builds where it is already largest. Getting
    the crit half right and the armor half wrong is a net posture change, which
    is why the live flip stays with the operator. This seam does NOT touch the
    pre-mitigation posture in either direction.

    No formula is invented here: the crit-chance stack (sum then clamp at 1.0,
    honouring the engine's crit cap at engine.py:185) and the crit-damage bonus
    (``DEFAULT_CRIT_BONUS`` plus ``total_crit_damage_bonus``) are lifted from
    dps.py:1083 / dps.py:1283 verbatim so the two sides cannot drift. The dps
    import is lazy + flag-gated so the OFF path pays no import cost.
    """
    if not assume_crit_weighted_vamp:
        return 1.0
    from .effects import total_crit_chance_bonus, total_crit_damage_bonus
    from .dps import DEFAULT_CRIT_BONUS

    effects = []
    for item_id in item_ids:
        eff = ITEM_EFFECTS.get(str(item_id))
        if eff is not None:
            effects.append(eff)
    crit_from_effects = total_crit_chance_bonus(effects, max(0.0, caster_bonus_hp))
    crit_total = min(max(0.0, crit_chance) + max(0.0, crit_from_effects), 1.0)
    crit_bonus = max(0.0, DEFAULT_CRIT_BONUS + total_crit_damage_bonus(effects))
    return 1.0 + crit_total * crit_bonus


# R194 slice C (RM-116c): the base item ids whose AoE damage Meraki 16.14.1
# explicitly labels lifesteal-eligible. Ravenous Hydra is the ONLY member of the
# hydra_cleave family that carries the clause - its Cleave reads "This damage
# benefits from life steal at 100% effectiveness" and its Ravenous Crescent
# active repeats it verbatim, while Tiamat 3077, Titanic 3748, Profane 6698 and
# Stridebreaker 6631 carry the same Cleave shape with NO such sentence. Start
# tight; widen only when a patch adds the clause somewhere else.
_VAMP_ELIGIBLE_CLEAVE_BASE_IDS: frozenset[str] = frozenset({"3074"})

# Mode-mirror id prefixes. DDragon ships one item under several ids (Arena 22*,
# ARAM 32*, plus the rarer 12* copies), so the credited set is resolved by ID
# SUFFIX against ITEM_EFFECTS rather than by NAME - a name sweep silently misses
# a renamed mirror, and a bare-base-id registry silently returns 0.0 for the
# mirror id the Arena resolver actually hands the engine (the R143 defect class).
_MODE_MIRROR_ID_PREFIXES: tuple[str, ...] = ("", "12", "22", "32")


def _resolve_vamp_eligible_cleave_ids() -> frozenset[str]:
    """Expand the base ids to every mode-mirror id the engine can resolve."""
    out: set[str] = set()
    for base in _VAMP_ELIGIBLE_CLEAVE_BASE_IDS:
        for prefix in _MODE_MIRROR_ID_PREFIXES:
            candidate = prefix + base
            if candidate in ITEM_EFFECTS:
                out.add(candidate)
    return frozenset(out)


# 16.14.1 resolves to {"3074", "223074"} - pinned by the R194 suffix-sweep test.
VAMP_ELIGIBLE_CLEAVE_ITEM_IDS: frozenset[str] = _resolve_vamp_eligible_cleave_ids()


def _cleave_vamp_damage(
    item_ids: Iterable[str | int],
    base_ad: float,
    bonus_ad: float,
    attack_speed: float,
    targets_in_rotation: float = 1.0,
    fight_window_s: float = _FIGHT_WINDOW_S,
    assume_cleave_lifesteal: bool = False,
) -> float:
    """R194 (slice C, RM-116c): lifesteal-eligible AoE damage over the fight window.

    Returns the PRE-mitigation physical damage that Meraki labels
    lifesteal-eligible but that ``_vamp_heal_pool`` cannot see, so the caller can
    price it at the build's lifesteal fraction. Returns ``0.0`` (identity) when
    ``assume_cleave_lifesteal`` is False - the shipped default, so every existing
    EHP number is byte-identical.

    WHY this seam exists: ``_vamp_heal_pool`` prices vamp off ``AD * AS *
    window``, the AUTO-ATTACK throughput and nothing else. Ravenous Hydra adds
    two damage sources that its own tooltip says lifesteal heals off at FULL
    effectiveness - the Cleave rider on every basic and the Ravenous Crescent
    active - and neither is auto-attack damage, so neither reaches the pool. The
    miss grows with the fight: a melee bruiser swinging into three enemies reads
    the sustain of a single-target duel.

    No coefficient is invented here. The Cleave magnitude is read back out of
    ``ITEM_EFFECTS`` by evaluating the item's OWN ``PeriodicProc.bonus_damage``
    against a ``CallContext`` carrying ``targets_in_rotation``, so this lane and
    the DPS lane cannot drift apart - the same no-second-source discipline
    ``_crit_weighted_vamp_multiplier`` uses. The Crescent magnitude is the item's
    OWN ``physical_burst_total_ad_ratio`` (0.80 total AD), the field the DSV8
    burst scorer already reads.

    WHY the item set is narrow: only the base ids in
    ``_VAMP_ELIGIBLE_CLEAVE_BASE_IDS`` (expanded to their mode mirrors) carry the
    Meraki lifesteal clause. The four structurally identical hydra siblings do
    not, so they contribute nothing here even though they proc the same shape.

    WHY it is DEFAULT-OFF rather than simply keyed on ``targets_in_rotation``:
    the Cleave term is genuinely 0.0 at ``targets_in_rotation=1.0``
    (``max(0, n - 1)``), but the Crescent term is NOT - a single-target fight
    still lands one Crescent. So the flag, not the target count, is what
    guarantees byte-identity. Two assumptions also ride here and both deserve an
    operator gate: the enemy-agnostic scorer has no live enemy count, and the
    Crescent is modelled as ONE cast per fight window (Meraki carries no cooldown
    for it, so this reuses the DSV8 one-cast burst-window convention - an upper
    bound in a 6s window).

    The ``hydra_cleave`` unique-passive family is honoured by routing through
    ``collect_effects``: a build whose family winner is a lifesteal-silent hydra
    procs no Ravenous Cleave in game and is credited nothing here. Duplicate ids
    collapse the same way.

    RM-187 (1.277.0): the local ``ctx`` is handed to ``collect_effects`` so this
    site resolves groups strongest-at-context like every other lane. It is the
    one site with no circularity - the context is built from this function's own
    arguments, above, before anything is collected. ``hydra_cleave`` members are
    every_n_ATTACKS only, so they expose no per-second comparable magnitude and
    this family still resolves FIRST-SEEN in practice; that is the documented
    fallback, not an oversight (an attack-keyed proc needs an attack-rate signal
    ``collect_effects`` does not carry). Pinned by
    ``test_unique_passive_dedup_flip_rm187.NoComparableMagnitudeStaysFirstSeenTests``.

    Damage is PRE-mitigation and carries no mode multiplier, matching
    ``_vamp_heal_pool``'s deliberate enemy-agnostic posture rather than
    introducing a second convention.
    """
    if not assume_cleave_lifesteal or fight_window_s <= 0:
        return 0.0
    safe_base_ad = max(0.0, base_ad)
    safe_bonus_ad = max(0.0, bonus_ad)
    attacks = max(0.0, attack_speed) * fight_window_s
    ctx = CallContext(
        base_ad=safe_base_ad,
        bonus_ad=safe_bonus_ad,
        level=1,
        targets_in_rotation=max(0.0, targets_in_rotation),
    )
    total_ad = safe_base_ad + safe_bonus_ad
    total = 0.0
    for eff in collect_effects(item_ids, ctx):
        if eff.item_id not in VAMP_ELIGIBLE_CLEAVE_ITEM_IDS:
            continue
        for proc in eff.periodics:
            if proc.damage_type != PHYSICAL or proc.every_n_attacks <= 0:
                continue
            total += (attacks / proc.every_n_attacks) * max(
                0.0, proc.resolve_damage(ctx)
            )
        total += max(0.0, eff.physical_burst_total_ad_ratio) * total_ad
    return max(0.0, total)


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
    # ENGINE 1.197.0 (R104, 2026-07-10): item-side SPELL-SHIELD block FRACTION - the
    # ITEM lane of the champion spell-shield axis (Banshee's Veil 3102 / Edge of
    # Night 3814 / Verdant Barrier 4632 "Annul" = block the next enemy ability).
    # Sourced from ``_item_spell_shield_overrides`` when ``apply_item_spell_shield``
    # is True; feeds the SAME cc_blended discount as spell_shield_frac, combining
    # MULTIPLICATIVELY with it AFTER the tenacity step. Default 0.0 leaves
    # enemy_cc_pressure_s / cc_blended_ehp byte-identical. Appended at END per the
    # dataclass field-append convention. NOT an EHP-numerator term.
    item_spell_shield_frac: float = 0.0
    # ENGINE 1.198.0 (R105, 2026-07-10): item-side MANA -> MAX-HP "Awe" credit - the
    # bonus max HEALTH (15% of BONUS mana; Winter's Approach 3119 / Fimbulwinter 3121
    # + Arena/ARAM mirrors) folded into the EHP NUMERATOR when
    # ``apply_item_mana_health`` is True. Default 0.0 leaves every EHP field
    # byte-identical. A genuine flat max-HP pool add (sibling of ext_flat_hp /
    # ally_grant_flat_hp), NOT a cc-only term. Appended at END per the dataclass
    # field-append convention.
    item_mana_health_hp: float = 0.0
    # ENGINE 1.199.0 (R106, 2026-07-11): item-side conditional RESIST-GRANT (Jak'Sho
    # 6665 Voidborn +30% bonus armor+MR at 5 stacks / Force of Nature 4401 Steadfast
    # +70 bonus MR at 8 stacks + Arena mirrors) folded into the armor/MR DENOMINATOR
    # (eff_armor / eff_mr) when ``apply_item_resist_grants`` is True. Default 0.0
    # leaves every EHP field byte-identical. Surfaced (like passive_resist_armor/mr)
    # for observability; amortized by the at-max-stacks midpoint. Appended at END per
    # the dataclass field-append convention.
    item_resist_armor: float = 0.0
    item_resist_mr: float = 0.0
    # ENGINE 1.200.0 (R107, 2026-07-11): item-side BONUS-HP-AMP "Warmog's Vitality"
    # (Warmog's Armor 3083 + Arena mirror 443083 = +12% of bonus-health-from-items as
    # bonus max health) folded into the EHP NUMERATOR when ``apply_item_bonus_hp_amp``
    # is True. Default 0.0 leaves every EHP field byte-identical. A genuine flat max-HP
    # pool add (sibling of ext_flat_hp / item_mana_health_hp), EXACT (no midpoint).
    # Appended at END per the dataclass field-append convention.
    item_bonus_hp_amp_hp: float = 0.0
    # ENGINE 1.201.0 (R108, 2026-07-11): item-side GENERAL %DR ("Blessing" /
    # "Safeguard") ALL-damage-type denominator multiplier - Celestial Opposition
    # 3869 (35/25%) + Crown of the Shattered Queen 664644 (40%) reduce incoming
    # champion damage across phys/mag/TRUE. 1.0 (identity) unless
    # ``assume_item_general_dr`` and a carrier is equipped, so OFF is byte-identical.
    # Appended at END per the dataclass field-append convention.
    item_general_dr_mult: float = 1.0
    # ENGINE 1.224.0 (R132, 2026-07-19): rune-side RESOLVE resist grant (Aftershock
    # 8439 capped 45 + 75% bonus resists / Conditioning 8429 +8 flat and +3% total /
    # Unflinching 8242 +10 flat) folded into the armor/MR DENOMINATOR (eff_armor /
    # eff_mr) when ``apply_rune_resist_grants`` is True. Default 0.0 leaves every EHP
    # field byte-identical. Surfaced (like passive_resist_armor/mr and
    # item_resist_armor/mr) for observability; amortized by a firing midpoint except
    # Conditioning, which is EXACT once online. Appended at END per the dataclass
    # field-append convention.
    rune_resist_armor: float = 0.0
    rune_resist_mr: float = 0.0
    # ENGINE 1.226.0 (RM-99 / R137, 2026-07-19): item-side PERMANENT-HP-PER-PROC
    # stack (Heartsteel 3084 + Arena mirror 223084 = 10% of the Colossal Consumption
    # proc damage granted as permanent bonus max health) folded into the EHP
    # NUMERATOR when ``assume_item_health_stacks`` is True. Default 0.0 leaves every
    # EHP field byte-identical. A genuine flat max-HP pool add and a member of the
    # PERMANENT-HP family (sibling of passive_health_hp / rune_perm_hp), so - unlike
    # the exact R105 / R107 stat conversions - it is a PROXY, amortized by an assumed
    # cumulative proc count by level. Appended at END per the dataclass field-append
    # convention.
    item_health_stack_hp: float = 0.0
    # R194 slice C (RM-116c): the lifesteal HP credited off Ravenous Hydra's
    # Cleave + Ravenous Crescent when ``assume_cleave_lifesteal`` is armed,
    # reported apart from ``heal_lifesteal`` (which it is INCLUDED in) so the
    # AA-throughput half and the AoE half stay separable. 0.0 at the default
    # flag -> every existing field byte-identical. Appended at END per the
    # dataclass field-append convention.
    heal_cleave_lifesteal: float = 0.0
    # RM-118 (2026-08-02): the resolved build's TOTAL maximum mana, the pool the
    # champion MANA -> DAMAGE coupling credit normalizes against. Already computed
    # inside ``compute_ehp`` for the Seraph's Embrace Lifeline shield
    # (``ehp.py:1725``, ``float(stats.get("mp", 0.0))``) and merely forwarded here
    # rather than recomputed. OBSERVABILITY ONLY - no EHP field reads it, so the
    # value is byte-identical whatever the mana lever does. Appended at END per the
    # dataclass field-append convention.
    max_mana: float = 0.0

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
            "item_spell_shield_frac": self.item_spell_shield_frac,
            "item_mana_health_hp": self.item_mana_health_hp,
            "item_resist_armor": self.item_resist_armor,
            "item_resist_mr": self.item_resist_mr,
            "rune_resist_armor": self.rune_resist_armor,
            "rune_resist_mr": self.rune_resist_mr,
            "item_bonus_hp_amp_hp": self.item_bonus_hp_amp_hp,
            "item_health_stack_hp": self.item_health_stack_hp,
            "item_general_dr_mult": self.item_general_dr_mult,
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
    # R92 (2026-07-10): default-OFF opt-in for Kaenic Rookern (2504) Magebane's
    # 15%-max-HP magic shield. Byte-identical OFF (2504's default_off shield is
    # dropped from the pool); live default-ON flip is operator-gated.
    assume_kaenic_shield: bool = False,
    # R97 (2026-07-10): default-OFF opt-in for Eclipse (6692 / Arena 226692) Ever
    # Rising Moon's shield half - 160 (+40% bonus AD) generic shield, 0.5x ranged.
    # Byte-identical OFF (the default_off shield is dropped from the pool); live
    # default-ON flip is operator-gated. Armed per-shield so it never credits Kaenic.
    assume_eclipse_shield: bool = False,
    # R99 (2026-07-10): default-OFF opt-in for Chainlaced Crushers (3173) Noxian
    # Persistence magic shield - 100 (L1)->200 (L18) +8% bonus HP, magic-only.
    # Byte-identical OFF (the default_off shield is dropped from the pool); live
    # default-ON flip is operator-gated. Armed per-shield so it never credits
    # Kaenic/Eclipse.
    assume_chainlaced_shield: bool = False,
    # Seraph's Embrace (2026-07-10): default-OFF opt-in for Seraph's Embrace
    # (3040 / Arena 223040 / ARAM 323040) Lifeline - 18% max mana ANY (generic)
    # shield at <30% HP. Byte-identical OFF (the default_off shield is dropped
    # from the pool); live default-ON flip is operator-gated. Armed per-shield so
    # it never credits Kaenic/Eclipse/Chainlaced.
    assume_seraphs_shield: bool = False,
    # R129 (2026-07-14): default-OFF opt-in for Fimbulwinter (3121 / Arena 223121
    # / ARAM 323121) Everlasting - 100 (+4.5% max mana) ANY (generic) shield on
    # immobilizing an enemy, 8s CD. Byte-identical OFF (the default_off shield is
    # dropped from the pool); live default-ON flip is operator-gated. Armed
    # per-shield so it never credits Kaenic/Eclipse/Chainlaced/Seraphs.
    assume_fimbulwinter_shield: bool = False,
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
    # 0.5 AA share). Corrected 2026-07-25: this ships DEFAULT-ON like R77/R80 -
    # the "DEFAULT-OFF pending its own live-gated flip" note contradicted the
    # literal below. Pass False for the identity multiplier.
    assume_item_enemy_as_slow: bool = True,
    # Riftmaker (2026-07-10): default-OFF opt-in to credit item-passive omnivamp
    # (Void Corruption 10% melee / 6% ranged AT MAX Void Corruption stacks) to the
    # EHP SUSTAIN axis. Byte-identical OFF (stats["omnivamp"] stays absent ->
    # heal_omnivamp == 0.0 -> effective_ehp_with_sustain == blended_ehp). ON injects
    # the build's summed omnivamp FRACTION so the existing _vamp_heal_pool credit
    # lands on effective_ehp_with_sustain / sustain_ehp_delta ONLY; blended_ehp is
    # NOT moved (same posture as lifesteal / spellvamp). Live default-ON flip is
    # operator-gated.
    assume_max_stacks_omnivamp: bool = False,
    # ENGINE 1.195.0 (2026-07-10): default-OFF opt-in to credit an item-side
    # death-triggered REVIVE (Guardian Angel Rebirth = 50% of BASE health) to the
    # EHP NUMERATOR. The item-side lane of the champion revive (which is
    # champion-keyed, so an item can never match ``revive_multiplier``). Folds into
    # ``common_revive`` through NORMAL resists (GA has no egg, unlike Anivia) and
    # composes multiplicatively with any champion self-revive. Byte-identical OFF
    # (item_revive_mult == 1.0). ON RAISES blended_ehp (a numerator term, NOT a
    # sustain-only credit like omnivamp). Live default-ON flip is operator-gated.
    assume_item_revive: bool = False,
    # ENGINE 1.196.0 (2026-07-10): default-OFF opt-in to credit an item-side
    # cast-triggered self-STASIS survival window (Zhonya's Hourglass 3157 / Seeker's
    # Armguard 2420 / Wooglet's Witchcap 228002 = a 2.5s untargetable+invulnerable
    # all-damage void) to the EHP NUMERATOR. The item-side lane of the champion
    # survival window (which is champion-keyed, so an item can never match
    # ``survival_window_multiplier``). Folds into ``common_revive`` as an
    # avoided-fight FRACTION (NO resist curve, NO HP pool - unlike the item revive)
    # and composes multiplicatively with any champion survival window / revive.
    # Byte-identical OFF (item_stasis_mult == 1.0). ON RAISES blended_ehp (a
    # numerator term, NOT a sustain-only credit like omnivamp). Live default-ON flip
    # is operator-gated.
    assume_item_stasis: bool = False,
    # ENGINE 1.197.0 (R104, 2026-07-10): default-OFF opt-in to credit an item-side
    # SPELL-SHIELD / block-next-ability passive (Banshee's Veil 3102 / Edge of Night
    # 3814 / Verdant Barrier 4632 "Annul") to the cc_blended CC-pressure discount.
    # The item-side lane of the champion spell-shield axis (champion-keyed, so an
    # item can never match ``champion_spell_shield_fraction``). Negates ONE incoming
    # CC instance -> shrinks enemy_cc_pressure_s (raising cc_blended_ehp), combining
    # MULTIPLICATIVELY with the champion spell_shield_frac AFTER the tenacity step.
    # A block-one CC negation, NOT an EHP-numerator term (that is the item-stasis
    # lane). Byte-identical OFF (item_spell_shield_frac == 0.0). Live default-ON flip
    # is operator-gated.
    apply_item_spell_shield: bool = False,
    # ENGINE 1.198.0 (R105, 2026-07-10): default-OFF opt-in to credit an item-side
    # MANA -> MAX-HP "Awe" passive (Winter's Approach 3119 / Fimbulwinter 3121 +
    # Arena/ARAM mirrors = bonus health equal to 15% of BONUS mana) to the EHP
    # NUMERATOR. The item-side lane of the R46 stacking-HP axis (champion-keyed, so
    # an item can never match ``passive_health_stack_hp``); build_champion folds
    # mana->AD (Manamune) / mana->AP (Archangel/Seraph) but has NO mana->HP walk, so
    # the mana-derived HP is uncredited. Folds ``0.15 * bonus_mana`` into every
    # per-type numerator next to ``ext_flat_hp`` (a genuine flat max-HP pool add),
    # EXACT (no amortization midpoint). Byte-identical OFF (item_mana_health_hp ==
    # 0.0). Live default-ON flip is operator-gated.
    apply_item_mana_health: bool = False,
    # ENGINE 1.199.0 (R106, 2026-07-11): credit the item-side conditional / ramping
    # RESIST GRANT (Jak'Sho 6665 Voidborn +30% bonus armor+MR at 5 combat stacks /
    # Force of Nature 4401 Steadfast +70 flat bonus MR at 8 magic-damage stacks +
    # Arena mirrors 226665 / 224401) to the armor/MR DENOMINATOR. The item-side lane
    # of the champion resist_grants (champion-keyed, so an item can never match it);
    # build_champion folds only the items' FLAT static resists, NOT the stacked ramp.
    # Amortized by the at-max-stacks midpoint. Byte-identical OFF (item_resist_* ==
    # 0.0). Live default-ON flip is operator-gated.
    apply_item_resist_grants: bool = False,
    # ENGINE 1.200.0 (R107, 2026-07-11): credit the item-side BONUS-HP-AMP "Warmog's
    # Vitality" (Warmog's Armor 3083 + Arena mirror 443083 = bonus health equal to 12%
    # of bonus-health-from-items) to the EHP NUMERATOR. The item twin of the champion
    # stacking-HP passive (champion-keyed, so an item can never match
    # passive_health_stack_hp); build_champion folds each item's FLAT health stat but
    # has NO bonus-HP -> bonus-HP self-amp walk, so the +12% is uncredited. Folds
    # ``0.12 * bonus_hp_from_items`` (total_hp - base_hp) into every per-type numerator
    # next to ``item_mana_health_hp``. EXACT (no amortization midpoint). Byte-identical
    # OFF (item_bonus_hp_amp_hp == 0.0). Live default-ON flip is operator-gated.
    apply_item_bonus_hp_amp: bool = False,
    # ENGINE 1.201.0 (R108, 2026-07-11): credit the item-side GENERAL %DR
    # ("Blessing" / "Safeguard") - an UNTARGETED, all-damage-type percent damage
    # reduction - to ALL THREE per-type EHP denominators. The item-keyed lane of
    # the champion-only R35 percent-mitigation (mit_*, champion_id-keyed so an item
    # can never match it); genuinely distinct from the physical-ONLY R77 crit-DR /
    # R80 AA-DR / R86 AS-slow lanes because general DR also reduces TRUE damage.
    # Multiplies a ``1 - dr * uptime`` factor into every per-type denominator (main
    # + the _blend_with_heal mirror). Byte-identical OFF (item_general_dr_mult ==
    # 1.0). AMORTIZED-MIDPOINT (uptime-gated). Live default-ON flip operator-gated.
    assume_item_general_dr: bool = False,
    # ENGINE 1.224.0 (R132, 2026-07-19): credit the DEFENSIVE RESOLVE-RUNE resist
    # grant (Aftershock 8439 = 45 + 75% bonus resists, capped 80-150 by level /
    # Conditioning 8429 = +8 flat and +3% total, permanent after 12 min /
    # Unflinching 8242 = +10 flat while crowd controlled) to the armor/MR
    # DENOMINATOR. The RUNE-side lane of the champion resist_grants (champion-keyed)
    # and the item item_resist_grants (item-keyed), neither of which a rune id can
    # ever match; before this seam the engine modelled runes as OFFENSE ONLY (zero
    # rune/perk/keystone references in this module, and rune_procs.py registers
    # Aftershock's explosion alone - "resist-bonus side not modeled"). Amortized by
    # a firing midpoint except Conditioning, which is EXACT once online.
    # Byte-identical OFF (rune_resist_* == 0.0), even when rune_ids is supplied.
    # Live default-ON flip is operator-gated. Appended at END of the signature per
    # the no-mid-signature-insert convention.
    apply_rune_resist_grants: bool = False,
    rune_ids: Iterable[str | int] = (),
    # ENGINE 1.225.0 (R136, 2026-07-19): the RM-101 defensive-rune remainder - the
    # half R132 deliberately did not build. R132 shipped the resist DENOMINATOR
    # feed only; these two seams are both NUMERATOR-side and reuse the SAME
    # ``rune_ids`` transport R132 already plumbed, so no new ids parameter lands.
    #   * apply_rune_health_grants - Overgrowth 8451 permanent max-HP + Grasp 8437
    #     self-side heal/permanent-HP (rune_procs.py:606 scores Grasp's DAMAGE and
    #     admits verbatim "(heal + permanent-HP sides not modeled)").
    #   * apply_rune_hsp_amp - Revitalize 8453's flat 5% Heal/Shield Power.
    # ENGINE 1.229.0 (R142) adds the RM-101 residual pair on the same transport,
    # each independently gated so every rune lane stays separately flippable:
    #   * apply_rune_self_heal - Second Wind 8444's 4%-of-missing-health heal.
    #   * apply_rune_shield_grants - Guardian 8465's SELF shield, with the ally
    #     half and the ability-power term deliberately omitted (this module holds
    #     no wielder AP, so that term is unrepresentable and its absence is a
    #     deliberate undercount, which is the safe direction).
    # Font of Life 8463 stays unbuilt: its DDragon longDesc carries an unresolved
    # ``@BaseHeal@`` template var in all four vendored snapshots, so there is no
    # magnitude to model.
    #     _hsp_amp.sum_wielder_hsp_pct sums heal_shield_amp_pct across EQUIPPED
    #     ITEMS ONLY, so a rune could never reach it.
    # Both default False -> 0.0 contributions -> BYTE-IDENTICAL to 1.224.0, and
    # passing rune_ids alone does NOT arm either. Live default-ON flip is
    # operator-gated. Appended at END per the no-mid-signature-insert convention.
    apply_rune_health_grants: bool = False,
    apply_rune_hsp_amp: bool = False,
    # R137 (ENGINE 1.226.0, RM-99): default-OFF opt-in for the item-side
    # PERMANENT-HP-PER-PROC stack - Heartsteel 3084 (+ Arena mirror 223084) grants
    # permanent bonus max health equal to 10% of its Colossal Consumption proc
    # damage, and only the damage half is modelled today. A PROXY lane (assumed
    # cumulative proc count by level), hence ``assume_`` rather than ``apply_``,
    # matching its nearest sibling ``assume_passive_health_stacks``. Default False
    # -> 0.0 -> BYTE-IDENTICAL to 1.225.0, and equipping Heartsteel alone does NOT
    # arm it. Live default-ON flip is operator-gated. Appended at END per the
    # no-mid-signature-insert convention.
    assume_item_health_stacks: bool = False,
    apply_rune_flat_mitigation: bool = False,
    assume_item_proc_heal: bool = False,
    # R142 (ENGINE 1.229.0): the RM-101 residual defensive-rune pair, appended at
    # END per the no-mid-signature-insert convention. Both ride the existing
    # ``rune_ids`` transport and are independently gated, so passing rune_ids
    # alone arms neither and the operator can flip each apart from the R132 /
    # R136 lanes.
    apply_rune_self_heal: bool = False,
    apply_rune_shield_grants: bool = False,
    # RM-87 / row A-18 (2026-07-25): the champion RESIST -> DAMAGE coupling seam,
    # appended at END per the no-mid-signature-insert convention. This pair is a
    # RANKING-ONLY lever: it is consumed by ``rank_items_by_ehp``'s sort key (the
    # ``_conv_key`` precedent - never a row value), so on THIS function it is
    # accepted for signature parity + forward-compat and validated only. Nothing
    # in the EHP math below reads it, which is why compute_ehp stays provably
    # byte-identical whatever is passed. See ``_resist_damage_coupling`` for the
    # registry and the refutation of the original "resists pay twice" filing.
    apply_resist_damage_coupling: bool = False,
    resist_coupling_strength: float = 0.0,
    # R193 slice B: default-OFF opt-in to CRIT-WEIGHT the vamp heal pool
    # (lifesteal / spellvamp / omnivamp). The pool prices vamp off the UNCRIT
    # ``AD * AS * window`` throughput even though the wielder's crit is already
    # resolved in ``stats``; an auto-attack lands ``AD * (1 + crit *
    # crit_damage_bonus)`` (dps.py:1283) and lifesteal heals off that hit, so a
    # crit carry's sustain is under-credited by the whole crit factor (x1.788
    # measured on a 5-item L16 Jinx; a zero-crit build is an exact no-op).
    # Byte-identical OFF (``_crit_weighted_vamp_multiplier`` returns 1.0).
    # Live default-ON flip is operator-gated BECAUSE arming it widens the
    # deliberate pre-mitigation over-credit on crit builds - see
    # ``_crit_weighted_vamp_multiplier`` for that rationale. Appended at END per
    # the no-mid-signature-insert convention.
    assume_crit_weighted_vamp: bool = False,
    # R194 slice C (RM-116c): default-OFF opt-in to credit the build's lifesteal
    # on Ravenous Hydra's Cleave and Ravenous Crescent - two damage sources
    # Meraki 16.14.1 states benefit from life steal at 100% effectiveness and
    # that ``_vamp_heal_pool`` (AA throughput only) cannot see. ``targets_in_
    # rotation`` is the enemy count the AoE lands on, the same field name the
    # DPS side's ``CallContext`` carries (dps.py:40) so the two halves of the
    # engine name the quantity identically. Passing ``targets_in_rotation``
    # ALONE does NOT arm the credit: the Cleave term is already 0.0 at 1.0, but
    # the Crescent term is not, so the FLAG is what guarantees byte-identity.
    # Live default-ON flip is operator-gated - see ``_cleave_vamp_damage`` for
    # the two assumptions (no live enemy count on an enemy-agnostic scorer; one
    # Crescent cast per fight window). Appended at END per the
    # no-mid-signature-insert convention.
    targets_in_rotation: float = 1.0,
    assume_cleave_lifesteal: bool = False,
    *,
    # RM-201: the guaranteed-minimum CC band. ``compute_cc_pressure`` has shipped
    # this seam since ENGINE 1.150.0 and none of its five production callers
    # forwarded it, so the ``durations_floor_s`` half of the conditional registry
    # could not be armed from any route. KEYWORD-ONLY and appended at END so no
    # existing positional call site shifts. It is an AND-gate with
    # ``include_conditional`` above - the floor lives on the CONDITIONAL registry,
    # so this flag alone is arithmetically inert and the two travel together.
    apply_cc_floor: bool = False,
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
    # RM-87: the coupling lever is ranking-only (see the signature note), but its
    # magnitude is validated HERE so an invalid value fails at the same boundary
    # as the enemy-share floats rather than silently inverting a sort key.
    if resist_coupling_strength < 0.0:
        raise ValueError(
            f"resist_coupling_strength must be >= 0.0, got {resist_coupling_strength}"
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
    # Seraph's Embrace Lifeline scales off TOTAL max mana (stats["mp"] = champion
    # base mana at level + item flat mp; 0.0 for manaless champs).
    max_mana = float(stats.get("mp", 0.0))
    is_ranged = _is_ranged(base)
    # Riftmaker (2026-07-10): default-OFF opt-in item-passive omnivamp credit.
    # OFF (default) leaves stats["omnivamp"] absent -> the _vamp_heal_pool call
    # below resolves heal_omnivamp == 0.0 (byte-identical). ON injects the build's
    # summed omnivamp FRACTION (melee/ranged-picked) so the sustain axis credits
    # it; blended_ehp is computed downstream WITHOUT this term (sustain-only).
    # ``stats`` is the fresh per-call dict from build_champion (mutating it is
    # call-local); the gated lazy import keeps OFF import-cost-free.
    if assume_max_stacks_omnivamp:
        from ._item_omnivamp import item_omnivamp_fraction
        omnivamp_frac = item_omnivamp_fraction(resolved.item_ids, is_ranged)
        if omnivamp_frac > 0.0:
            stats["omnivamp"] = stats.get("omnivamp", 0.0) + omnivamp_frac
    shield_totals, shield_sources = _collect_shields(
        resolved.item_ids,
        level=level,
        bonus_hp=bonus_hp,
        bonus_ad=bonus_ad,
        is_ranged=is_ranged,
        max_hp=hp,
        max_mana=max_mana,
        assume_kaenic_shield=assume_kaenic_shield,
        assume_eclipse_shield=assume_eclipse_shield,
        assume_chainlaced_shield=assume_chainlaced_shield,
        assume_seraphs_shield=assume_seraphs_shield,
        assume_fimbulwinter_shield=assume_fimbulwinter_shield,
    )
    shield_any = shield_totals.get(ANY, 0.0)
    # ENGINE 1.229.0 (R142): Guardian 8465's SELF shield - level-lerped 40-150 plus
    # 6% of bonus health (DDragon 16.14.1). It joins the ANY pool because a rune
    # shield absorbs any damage type, and it lands BEFORE shield_amp_mult so the
    # Heal/Shield Power lanes amplify it exactly as they do in game. TWO TERMS ARE
    # DELIBERATELY OMITTED, not overlooked: the ally half (throughput to a second
    # unit this frame does not model) and the "+20% ability power" term (this
    # module holds no wielder AP - every ``ap`` token here is enemy_ap_share, an
    # incoming-damage-type share - so the term is unrepresentable and omitting it
    # undercounts, which is the safe direction). OFF -> 0.0 -> byte-identical.
    if apply_rune_shield_grants:
        from ._rune_shield_grants import rune_shield_grants as _rune_shield_fn
        shield_any += _rune_shield_fn(
            rune_ids,
            level=level,
            total_hp=hp,
            base_hp=float(base.get("hp", 0.0)),
            apply_rune_shield_grants=True,
        )
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

    # RM-103: Unending Despair 2502 / Arena mirror 222502 "Anguish" SELF-heal -
    # 250% of the post-mitigation 3%-bonus-HP proc damage, per champion hit.
    # _effects_data called this an "ally self-heal component utility-only",
    # which was wrong three ways: it is a SELF heal, it is a 2.5x multiplier
    # rather than utility, and there is no ally component at all (the proc is
    # an enemy AoE within 650 units).
    #
    # ITEM_EFFECTS['2502'].heal and ['222502'].heal are BOTH None, so
    # _collect_heals skips these ids entirely - there is no double-credit path.
    # Joins the pool BEFORE heal_amp_mult: Anguish's heal is an ordinary heal
    # and is amplified by Heal/Shield Power in game, same posture as
    # rune_heal_hp. OFF -> 0.0 -> byte-identical.
    if assume_item_proc_heal:
        from ._item_proc_heal import item_proc_heal_hp as _item_proc_heal_fn
        heal_item_total += _item_proc_heal_fn(
            resolved.item_ids,
            bonus_hp,
            assume_item_proc_heal=True,
        )

    # R193 slice B: the crit-weight factor for every vamp lane (lifesteal here,
    # spellvamp / omnivamp at the sustain blend below) is resolved ONCE so the
    # three lanes cannot drift apart. 1.0 when the seam is OFF -> byte-identical.
    crit_vamp_mult = _crit_weighted_vamp_multiplier(
        resolved.item_ids,
        float(stats.get("crit", 0.0)),
        caster_bonus_hp=bonus_hp,
        assume_crit_weighted_vamp=assume_crit_weighted_vamp,
    )
    lifesteal_pct = float(stats.get("lifesteal", 0.0))
    heal_lifesteal = _lifesteal_heal(
        lifesteal_pct=lifesteal_pct,
        ad=float(stats.get("ad", 0.0)),
        attack_speed=float(stats.get("as", 0.0)),
    ) * crit_vamp_mult
    # R194 slice C (RM-116c): the AoE half of the same lifesteal stat. Priced at
    # the SAME fraction as the AA half above and folded INTO heal_lifesteal, so
    # it inherits that lane's placement (before heal_amp_mult) with no new
    # posture. It deliberately does NOT take ``crit_vamp_mult``: no source says
    # Cleave or Crescent can crit, and inventing a crit weight for them would be
    # a second unsourced assumption on top of the two the seam already carries.
    # 0.0 at the default flag -> byte-identical.
    heal_cleave_lifesteal = lifesteal_pct * _cleave_vamp_damage(
        resolved.item_ids,
        base_ad=base_ad,
        bonus_ad=bonus_ad,
        attack_speed=float(stats.get("as", 0.0)),
        targets_in_rotation=targets_in_rotation,
        assume_cleave_lifesteal=assume_cleave_lifesteal,
    )
    heal_lifesteal += heal_cleave_lifesteal
    heal_amp_mult = _total_heal_amp(resolved.item_ids)
    # ENGINE 1.225.0 (R136): RM-101 rune HEALTH grants - Overgrowth 8451's
    # permanent max-HP (3 per 8 absorbed, plus a DISCRETE 3.5% max-HP threshold at
    # 120 absorbed) and Grasp 8437's self-side (1.3% max-HP heal + 5 permanent HP,
    # both 40% effective on ranged). Grasp's coefficients are NOT re-derived here -
    # they are the same DDragon-cited magnitudes already carried on the ENEMY side
    # at enemy_runes.py:213/:215/:216, restated so the two sides cannot drift.
    # permanent HP joins the per-type NUMERATORS next to passive_health_hp; the
    # heal joins the heal pool BEFORE heal_amp_mult (Grasp's heal is amplifiable
    # in game). OFF -> (0.0, 0.0) -> byte-identical; the gated lazy import keeps
    # OFF import-free, matching the R132 rune_resist precedent.
    rune_perm_hp = 0.0
    rune_heal_hp = 0.0
    if apply_rune_health_grants:
        from ._rune_health_grants import rune_health_grants as _rune_health_fn
        rune_perm_hp, rune_heal_hp = _rune_health_fn(
            rune_ids,
            level=level,
            max_hp=hp,
            is_ranged=is_ranged,
            apply_rune_health_grants=True,
        )
    # ENGINE 1.229.0 (R142): Second Wind 8444 - "heal for 4% of your missing health
    # over 10s" (DDragon 16.14.1, verbatim). Joins the heal pool BEFORE
    # heal_amp_mult because a rune heal is amplifiable in game, the same placement
    # Grasp's rune_heal_hp already uses. It reuses this scorer's OWN
    # _MISSING_HP_SHARE_FOR_HEALS convention rather than inventing a second
    # missing-health reading, and is discounted by the ratio of the modeled
    # engagement window to the rune's own 10s heal duration - the magnitude is
    # exact DDragon and only that uptime ratio is an assumption. OFF -> 0.0 ->
    # byte-identical; the gated lazy import keeps OFF import-free.
    rune_self_heal_hp = 0.0
    if apply_rune_self_heal:
        from ._rune_self_heal import sum_rune_self_heal as _rune_self_heal_fn
        rune_self_heal_hp = _rune_self_heal_fn(
            rune_ids,
            max_health=hp,
            missing_hp_share=_MISSING_HP_SHARE_FOR_HEALS,
            is_ranged=is_ranged,
        )
    heal_total = (
        heal_item_total + heal_lifesteal + rune_heal_hp + rune_self_heal_hp
    ) * heal_amp_mult

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
    # ENGINE 1.225.0 (R136): the RUNE lane of the same additive HSP model.
    # Revitalize 8453 grants a flat 5% Heal and Shield Power that the ITEM-keyed
    # sum_wielder_hsp_pct can never see. Additive with the item sum per the real-LoL
    # model the "(1 + hsp_pct)" convention already encodes (Redemption 0.10 +
    # Mikael 0.12 = 0.22; + Revitalize 0.05 = 0.27). Its second clause ("10%
    # stronger on targets below 40% health") is a TARGET-STATE conditional and is
    # deliberately NOT modelled - that arc is operator-CLOSED. Independently gated
    # from assume_hsp_amp so the operator can flip the item and rune lanes apart.
    hsp_pct = (
        sum_wielder_hsp_pct(resolved.item_ids) if assume_hsp_amp else 0.0
    )
    if apply_rune_hsp_amp:
        from ._rune_hsp_amp import sum_rune_hsp_pct as _rune_hsp_fn
        hsp_pct += _rune_hsp_fn(rune_ids)
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
    # TRUE here (B45/B46 flip) -> ARMED on the shipped path; pass False for the
    # identity 1.0. Item-keyed (mit_phys is
    # champion_id-keyed and cannot see the build's items).
    item_crit_dr_mult = item_crit_dr_multiplier(
        resolved.item_ids, assume_item_crit_dr
    )

    # ENGINE 1.181.0 (R80, 2026-07-05): item-keyed incoming BASIC-ATTACK DAMAGE
    # REDUCTION (Plated Steelcaps Plating 10% reduced basic-attack damage).
    # Basic-attack damage is PHYSICAL, so this is a SEPARATE physical-only
    # denominator factor applied alongside mit_phys + item_crit_dr_mult (NOT
    # folded into mit_phys - it stays the pure champion percent-DR value for
    # reporting). ``assume_item_aa_dr`` defaults TRUE here (B45/B46 flip) ->
    # ARMED on the shipped path; pass False for the identity 1.0.
    # Item-keyed lane distinct from R77's crit-DR (each item
    # carries only its own reduction, so the two seams never cross-credit).
    item_aa_dr_mult = item_aa_dr_multiplier(
        resolved.item_ids, assume_item_aa_dr
    )

    # ENGINE 1.182.0 (R86, 2026-07-06): item-keyed enemy ATTACK-SPEED-SLOW aura
    # (Frozen Heart Winter's Caress -20% enemy AS -> 20% less incoming basic-attack
    # RATE). Basic-attack damage is PHYSICAL, so this is a SEPARATE physical-only
    # denominator factor applied alongside item_crit_dr_mult + item_aa_dr_mult (NOT
    # folded into mit_phys - it stays the pure champion percent-DR value for
    # reporting). ``assume_item_enemy_as_slow`` defaults TRUE here -> ARMED on the
    # shipped path; pass False for the identity 1.0.
    # Distinct item-keyed lane from R77/R80 (never cross-credit;
    # stacks multiplicatively with Steelcaps' per-hit AA-DR on a build with both).
    item_enemy_as_slow_mult = item_enemy_as_slow_multiplier(
        resolved.item_ids, assume_item_enemy_as_slow
    )

    # ENGINE 1.201.0 (R108, 2026-07-11): item-keyed UNTARGETED GENERAL %DR
    # (Celestial Opposition 3869 "Blessing" 35/25% + Crown of the Shattered Queen
    # 664644 "Safeguard" 40%). UNLIKE the physical-only R77/R80/R86 lanes above,
    # general DR reduces ALL damage types incl TRUE, so this multiplier folds into
    # every per-type denominator below (the true-damage credit no R77/R80/R86 fold
    # performs). Applied ALONGSIDE the champion mit_* (item-keyed, never aliased
    # into the champion percent-DR value). ``assume_item_general_dr`` defaults
    # False -> identity 1.0 -> BYTE-IDENTICAL. AMORTIZED-MIDPOINT (uptime-gated).
    # The gated lazy import keeps OFF import-free.
    item_general_dr_mult = 1.0
    if assume_item_general_dr:
        from ._item_general_dr import item_general_dr_multiplier as _item_general_dr_fn
        item_general_dr_mult = _item_general_dr_fn(
            resolved.item_ids, not is_ranged, assume_item_general_dr
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

    # RM-101: the RUNE-side lane of the SAME flat per-instance damage-block
    # mechanic. _passive_flat_mitigation_overrides is keyed by champion_id, so
    # rune 8473 Bone Plating could never match it - the identical structural
    # gap R132's _rune_resist_grants filled on the resist axis.
    #
    # Folded into the SAME flat_mit_* locals, so none of the six numerator
    # expressions below change at all. apply_rune_flat_mitigation defaults
    # False -> (0.0, 0.0, 0.0) -> byte-identical, and passing rune_ids alone
    # does NOT arm it. Gated lazy import keeps OFF import-free (R132 precedent).
    rune_flat_mit_phys = rune_flat_mit_mag = rune_flat_mit_true = 0.0
    if apply_rune_flat_mitigation:
        from ._rune_flat_mitigation import rune_flat_mitigation_hp as _rune_flat_mit_fn
        rune_flat_mit_phys, rune_flat_mit_mag, rune_flat_mit_true = _rune_flat_mit_fn(
            rune_ids,
            level=level,
            apply_rune_flat_mitigation=True,
        )
        flat_mit_phys += rune_flat_mit_phys
        flat_mit_mag += rune_flat_mit_mag
        flat_mit_true += rune_flat_mit_true

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

    # ENGINE 1.198.0 (R105, 2026-07-10): item-side MANA -> MAX-HP "Awe" credit - the
    # item analog of passive_health_hp above (a clean EHP-NUMERATOR flat max-HP
    # term), sourced from an ITEM passive. Winter's Approach 3119 / Fimbulwinter 3121
    # (+ Arena/ARAM mirrors) grant bonus MAX HEALTH = 15% of BONUS mana via "Awe"
    # (Meraki 16.13.1), which is NOT in the resolved stat block: build_champion folds
    # mana->AD (Manamune) / mana->AP (Archangel/Seraph) but has NO mana->HP walk.
    # bonus_mana = item-contributed max mana (max_mana - base max mana; the
    # champion's own base mana is EXCLUDED, matching the "15% bonus mana" tooltip and
    # the Awe-AP base). ``apply_item_mana_health`` defaults False -> 0.0 ->
    # BYTE-IDENTICAL. EXACT (deterministic, no midpoint). Folded next to ext_flat_hp
    # in every per-type numerator (main + the _blend_with_heal mirror) below. The
    # gated lazy import keeps OFF import-free.
    item_mana_health_hp = 0.0
    if apply_item_mana_health:
        from ._item_mana_health import item_mana_health_hp as _item_mana_health_fn
        bonus_mana = max(0.0, max_mana - float(base.get("mp", 0.0)))
        item_mana_health_hp = _item_mana_health_fn(resolved.item_ids, bonus_mana)

    # ENGINE 1.200.0 (R107, 2026-07-11): item-side BONUS-HP-AMP "Warmog's Vitality"
    # credit - the item HP -> HP self-amplifier twin of item_mana_health_hp above (a
    # clean EHP-NUMERATOR flat max-HP term). Warmog's Armor 3083 (+ Arena mirror
    # 443083) grants bonus max health = 12% of BONUS health from items (Meraki 16.13.1,
    # passive "Warmog's Vitality"), which is NOT in the resolved stat block:
    # build_champion folds each item's FLAT health stat and walks bonus-HP -> bonus-AD
    # (Tyranny) but has NO bonus-HP -> bonus-HP self-amp walk. bonus_hp_from_items =
    # item-contributed max HP (hp - base hp; the champion's own base health is EXCLUDED,
    # matching "bonus health from items" and the engine's own bonus_hp_from_items).
    # ``apply_item_bonus_hp_amp`` defaults False -> 0.0 -> BYTE-IDENTICAL. EXACT
    # (deterministic, no midpoint). Folded next to item_mana_health_hp in every per-type
    # numerator (main + the _blend_with_heal mirror) below. The gated lazy import keeps
    # OFF import-free.
    item_bonus_hp_amp_hp = 0.0
    if apply_item_bonus_hp_amp:
        from ._item_bonus_hp_amp import item_bonus_hp_amp_hp as _item_bonus_hp_amp_fn
        bonus_hp_from_items = max(0.0, hp - float(base.get("hp", 0.0)))
        item_bonus_hp_amp_hp = _item_bonus_hp_amp_fn(
            resolved.item_ids, bonus_hp_from_items
        )

    # ENGINE 1.226.0 (R137 / RM-99, 2026-07-19): item-side PERMANENT-HP-PER-PROC
    # stack credit - Heartsteel 3084 (+ Arena mirror 223084) grants permanent bonus
    # max health equal to 10% of its Colossal Consumption proc damage (70 + 6% max
    # HP). ``_effects_data`` models the DAMAGE half only and disclaims this half
    # in-line; no registry credits it, and the champion twin
    # (_passive_health_overrides, R46) is champion-keyed so an item can never match.
    # Unlike the two exact item HP lanes above (R105 mana->HP, R107 item-HP->HP)
    # this is ``procs x hp_per_proc``, so it needs BOTH the resolved max HP and the
    # level - and it is a PROXY (assumed cumulative proc count), hence ``assume_``.
    # NO SELF-FEEDBACK: the proc scales with max HP and the credit IS max HP, so the
    # formula is fed the RESOLVED ``hp`` and the credit is never added back before it
    # runs. ``assume_item_health_stacks`` defaults False -> 0.0 -> BYTE-IDENTICAL.
    # Folded next to passive_health_hp / rune_perm_hp (the PERMANENT-HP family) in
    # the main per-type numerators only - deliberately NOT in the _blend_with_heal
    # mirror, which carries the exact R105/R107 conversions but not this family. The
    # gated lazy import keeps OFF import-free.
    item_health_stack_hp = 0.0
    if assume_item_health_stacks:
        from ._item_health_stack import item_health_stack_hp as _item_health_stack_fn
        item_health_stack_hp = _item_health_stack_fn(resolved.item_ids, hp, level)

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
    # ENGINE 1.199.0 (R106, 2026-07-11): item-side conditional RESIST-GRANT credit -
    # the ITEM analog of resist_grants above (a clean EHP-DENOMINATOR bonus armor/MR
    # add). Jak'Sho 6665 Voidborn (+30% BONUS armor+MR at 5 combat stacks) + Force of
    # Nature 4401 Steadfast (+70 flat BONUS MR at 8 magic-damage stacks) [+ Arena
    # mirrors 226665 / 224401] RAMP to max stacks in combat and are absent from the
    # resolved stat block: build_champion folds only their FLAT static resists
    # (Jak'Sho +45/+45, FoN +55 MR), NOT the stacked ramp (live-probe R105). The
    # champion resist registry is champion-keyed so an item can never match
    # resist_grants - the structural gap the item-side registries fill. Added to
    # eff_armor / eff_mr next to bonus_armor / ext_armor (DENOMINATOR, BEFORE the pen
    # step + the _armor_factor curve), so it flows into every per-type EHP AND the
    # _blend_with_heal sustain mirror via the eff_* closure - no numerator touch.
    # ``apply_item_resist_grants`` defaults False -> (0.0, 0.0) -> BYTE-IDENTICAL.
    # CONDITIONAL (unlike R105's exact mana->HP): each grant is amortized by the
    # at-max-stacks midpoint inside the registry. The gated lazy import keeps OFF
    # import-free.
    item_resist_armor = 0.0
    item_resist_mr = 0.0
    if apply_item_resist_grants:
        from ._item_resist_grants import item_resist_grants as _item_resist_fn
        item_resist_armor, item_resist_mr = _item_resist_fn(
            resolved.item_ids,
            total_armor=armor, total_mr=mr,
            base_armor=float(base.get("armor", 0.0)),
            base_mr=float(base.get("mr", 0.0)),
            level=level,
        )
    # ENGINE 1.224.0 (R132, 2026-07-19): rune-side RESIST-GRANT credit - the RUNE
    # analog of resist_grants / item_resist_grants above (a clean EHP-DENOMINATOR
    # bonus armor/MR add). Aftershock 8439 (45 + 75% of BONUS resists for 2.5s on a
    # 20s cooldown, CAPPED at 80-150 by level - the cap BINDS on the high-bonus tank
    # cohort that actually runs it, so it is modelled explicitly), Conditioning 8429
    # (+8 flat and +3% of TOTAL, permanent past the 12-minute mark) and Unflinching
    # 8242 (+10 flat while crowd controlled and 2s after). The champion registry is
    # champion-keyed and the item registry is item-keyed, so a rune can never match
    # either - the structural gap this lane fills. Added to eff_armor / eff_mr next
    # to bonus_armor / ext_armor / item_resist_armor (DENOMINATOR, BEFORE the pen
    # step + the _armor_factor curve), so it flows into every per-type EHP AND the
    # _blend_with_heal sustain mirror via the eff_* closure - no numerator touch.
    # ``apply_rune_resist_grants`` defaults False -> (0.0, 0.0) -> BYTE-IDENTICAL,
    # and passing rune_ids alone does NOT arm it. The gated lazy import keeps OFF
    # import-free.
    rune_resist_armor = 0.0
    rune_resist_mr = 0.0
    if apply_rune_resist_grants:
        from ._rune_resist_grants import rune_resist_grants as _rune_resist_fn
        rune_resist_armor, rune_resist_mr = _rune_resist_fn(
            rune_ids,
            level=level,
            total_armor=armor, total_mr=mr,
            base_armor=float(base.get("armor", 0.0)),
            base_mr=float(base.get("mr", 0.0)),
        )
    eff_armor = armor + bonus_armor + ext_armor + item_resist_armor + rune_resist_armor
    eff_mr = mr + bonus_mr + ext_mr + item_resist_mr + rune_resist_mr
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
    # ``rune_perm_hp`` (R136) is permanent max HP earned over the game - it rides
    # the SAME armor/MR curve as base HP, so it adds RAW to each per-type
    # numerator exactly like its nearest sibling ``passive_health_hp``. 0.0 when
    # apply_rune_health_grants is off -> byte-identical.
    physical_ehp = (hp + ext_flat_hp + item_mana_health_hp + item_bonus_hp_amp_hp + passive_health_hp + rune_perm_hp + item_health_stack_hp + flat_mit_phys + shield_any_amped + shield_phys_amped + heal_total) / (_armor_factor(eff_armor) * safe_mult * mit_phys * item_crit_dr_mult * item_aa_dr_mult * item_enemy_as_slow_mult * item_general_dr_mult)
    magical_ehp = (hp + ext_flat_hp + item_mana_health_hp + item_bonus_hp_amp_hp + passive_health_hp + rune_perm_hp + item_health_stack_hp + flat_mit_mag + shield_any_amped + shield_mag_amped + heal_total) / (_armor_factor(eff_mr) * safe_mult * mit_mag * item_general_dr_mult)
    true_ehp = (hp + ext_flat_hp + item_mana_health_hp + item_bonus_hp_amp_hp + passive_health_hp + rune_perm_hp + item_health_stack_hp + flat_mit_true + shield_any_amped + shield_true_amped + heal_total) / (safe_mult * mit_true * item_general_dr_mult)

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
    # ENGINE 1.195.0 (2026-07-10): item-revive (Guardian Angel) EHP-numerator
    # credit. The item-side lane of the champion revive (revive_extra above is
    # champion-keyed; an item can never match it). GA's Rebirth restores 50% of
    # BASE health after lethal damage on a 300s cooldown - a death-triggered second
    # life, the SAME EHP-numerator shape as the champion revive. Folded into
    # common_revive so it runs through NORMAL resists: GA has NO egg (its 4s
    # invulnerable channel always completes), unlike Anivia, so it must NOT get the
    # egg_ratio that revive_extra gets. It composes MULTIPLICATIVELY with any
    # champion self-revive (independent second lives). item_revive_max_hp_fraction
    # converts the 50%-of-base pool to a max-HP numerator fraction (the multiplier
    # scales the first life's EHP, proportional to TOTAL max HP). Default False ->
    # item_revive_mult 1.0 -> BYTE-IDENTICAL. This credit RAISES blended_ehp when ON
    # (correct - an EHP-numerator term, same as the champion revive), NOT a
    # sustain-only credit like omnivamp. The gated lazy import keeps OFF import-free.
    item_revive_mult = 1.0
    if assume_item_revive:
        from ._item_revive import item_revive_max_hp_fraction
        item_revive_frac = item_revive_max_hp_fraction(
            resolved.item_ids, base_hp=float(base.get("hp", 0.0)), total_hp=hp
        )
        item_revive_mult = 1.0 + item_revive_frac
    # ENGINE 1.196.0 (2026-07-10): item-stasis (Zhonya's Hourglass / Seeker's
    # Armguard / Wooglet's Witchcap) EHP-numerator credit. The item-side lane of
    # the champion survival window (survival_window_mult above is champion-keyed; an
    # item can never match it). A 2.5s Time Stop / Stasis active voids ALL incoming
    # damage while up - a cast-triggered guaranteed-survival window, the SAME
    # EHP-numerator shape as the champion survival window. Folded into common_revive
    # as an avoided-fight FRACTION: unlike the item revive it runs through NO resist
    # curve and needs NO base/total-HP conversion (it voids damage outright, not a
    # second HP pool). It composes MULTIPLICATIVELY with any champion survival
    # window / revive (independent damage-void windows). item_survival_window_fraction
    # returns min(2.5/fight_window, 1.0) * prob per registered item. Default False ->
    # item_stasis_mult 1.0 -> BYTE-IDENTICAL. This credit RAISES blended_ehp when ON
    # (correct - an EHP-numerator term, same as the champion survival window), NOT a
    # sustain-only credit like omnivamp. The gated lazy import keeps OFF import-free.
    item_stasis_mult = 1.0
    if assume_item_stasis:
        from ._item_survival_window import item_survival_window_fraction
        item_stasis_mult = 1.0 + item_survival_window_fraction(
            resolved.item_ids, _FIGHT_WINDOW_S
        )
    common_revive = ext_revive * survival_window_mult * item_revive_mult * item_stasis_mult
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
        # Mirror the main numerators EXACTLY (see physical_ehp / magical_ehp /
        # true_ehp above) so _blend_with_heal(heal_total) stays exactly
        # blended_ehp (guard-tested). Every optional term is 0.0 when its flag
        # is off -> byte-identical at defaults.
        #
        # RM-105: the PERMANENT-HP family (passive_health_hp R46, rune_perm_hp
        # R136, item_health_stack_hp R137) was missing here. The omission was
        # invisible because the contract test asserted the equality only AT
        # DEFAULT FLAGS, where every one of those terms is 0.0 - so the two
        # fields diverged by exactly the omitted HP the moment a seam was armed
        # (measured 618.33 EHP on Sion L13 with apply_rune_health_grants ON,
        # about 10 percent), and every one of those seams is queued for a
        # default-ON flip. If you add a term to the main numerators, ADD IT
        # HERE TOO - the contract test now arms each seam and will catch you.
        p = (hp + ext_flat_hp + item_mana_health_hp + item_bonus_hp_amp_hp + passive_health_hp + rune_perm_hp + item_health_stack_hp + flat_mit_phys + shield_any_amped + shield_phys_amped + heal_scalar) / (
            _armor_factor(eff_armor) * safe_mult * mit_phys * item_crit_dr_mult * item_aa_dr_mult * item_enemy_as_slow_mult * item_general_dr_mult
        )
        m = (hp + ext_flat_hp + item_mana_health_hp + item_bonus_hp_amp_hp + passive_health_hp + rune_perm_hp + item_health_stack_hp + flat_mit_mag + shield_any_amped + shield_mag_amped + heal_scalar) / (
            _armor_factor(eff_mr) * safe_mult * mit_mag * item_general_dr_mult
        )
        t = (hp + ext_flat_hp + item_mana_health_hp + item_bonus_hp_amp_hp + passive_health_hp + rune_perm_hp + item_health_stack_hp + flat_mit_true + shield_any_amped + shield_true_amped + heal_scalar) / (
            safe_mult * mit_true * item_general_dr_mult
        )
        p *= (1.0 + revive_extra * egg_ratio_phys) * common_revive
        m *= (1.0 + revive_extra * egg_ratio_mag) * common_revive
        t *= (1.0 + revive_extra) * common_revive
        return (
            p * enemy_ad_share + m * enemy_ap_share + t * enemy_true_share
        )

    ad_stat = float(stats.get("ad", 0.0))
    as_stat = float(stats.get("as", 0.0))
    # R193 slice B: the same ``crit_vamp_mult`` the lifesteal lane took above -
    # these two lanes share the AA-throughput proxy, so they share its crit
    # weighting. 1.0 when the seam is OFF -> byte-identical.
    heal_spellvamp = _vamp_heal_pool(
        float(stats.get("spellvamp", 0.0)), ad_stat, as_stat
    ) * crit_vamp_mult
    heal_omnivamp = _vamp_heal_pool(
        float(stats.get("omnivamp", 0.0)), ad_stat, as_stat
    ) * crit_vamp_mult
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
    # ENGINE 1.197.0 (R104): the ITEM-side spell-shield block fraction (0.0 when the
    # flag is off = byte-identical). The item lane of the champion axis above -
    # keyed by resolved.item_ids, folded into the SAME cc discount below. Lazy import
    # mirrors the item-stasis / item-revive item-side lanes.
    item_spell_shield_frac = 0.0
    if apply_item_spell_shield:
        from ._item_spell_shield_overrides import item_spell_shield_fraction
        item_spell_shield_frac = item_spell_shield_fraction(resolved.item_ids)
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
            # RM-201: ``apply_cc_floor`` rides the SAME per-enemy call. It is
            # read only inside the conditional branch of
            # ``_conditional_credit_seconds``, so arming it with
            # ``include_conditional`` False is a measured no-op rather than a
            # convention.
            cc_total += compute_cc_pressure(
                enemy, mode,
                include_conditional=include_conditional,
                apply_cc_floor=apply_cc_floor,
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
        # ENGINE 1.197.0 (R104): the ITEM-side spell-shield block (Banshee / EoN /
        # Verdant "Annul"), the item lane of the champion block above. A second
        # block-one negation on the SAME running cc_total product, so it composes
        # MULTIPLICATIVELY with the champion frac. Default-off (frac 0.0) = no-op.
        if apply_item_spell_shield and item_spell_shield_frac > 0.0:
            cc_total *= (1.0 - item_spell_shield_frac)
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
    if assume_item_stasis and item_stasis_mult != 1.0:
        notes.append(
            f"item_stasis: item-side cast-triggered self-stasis window (Zhonya/Seeker"
            f"/Wooglet 2.5s untargetable+invuln) folded into the EHP numerator "
            f"(x{item_stasis_mult:.3f}; window duration exact, avoided fraction "
            f"window_s/{_FIGHT_WINDOW_S:.0f}s amortized at the _ITEM_STASIS_PROB "
            f"availability midpoint; the item-side lane of the champion survival window)"
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
        heal_cleave_lifesteal=heal_cleave_lifesteal,
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
        item_spell_shield_frac=item_spell_shield_frac,
        item_mana_health_hp=item_mana_health_hp,
        item_bonus_hp_amp_hp=item_bonus_hp_amp_hp,
        item_health_stack_hp=item_health_stack_hp,
        item_general_dr_mult=item_general_dr_mult,
        item_resist_armor=item_resist_armor,
        item_resist_mr=item_resist_mr,
        rune_resist_armor=rune_resist_armor,
        rune_resist_mr=rune_resist_mr,
        survival_window_mult=survival_window_mult,
        effective_ehp_with_sustain=effective_ehp_with_sustain,
        ehp_without_sustain=ehp_without_sustain,
        sustain_ehp_delta=sustain_ehp_delta,
        heal_spellvamp=heal_spellvamp,
        heal_omnivamp=heal_omnivamp,
        passive_flat_mit_phys=flat_mit_phys,
        passive_flat_mit_mag=flat_mit_mag,
        passive_flat_mit_true=flat_mit_true,
        max_mana=max_mana,
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
    # Term A (2026-07-18, ENGINE 1.220.0): ally-granted EHP surface.
    # ``team_blended_ehp`` is the new build's blended EHP plus the flat HP the
    # build's items confer on TEAMMATES (``_item_ally_grant``), amortized by the
    # shipped ``_ALLY_SHIELD_HEAL_PROB`` uptime midpoint and gated on the
    # champion's ally-reach signal. ``delta_team_blended_ehp`` is that value's
    # gain over the baseline build; because the CURRENT build's ally grant is
    # identical on both sides it cancels, so the delta reduces exactly to
    # ``delta_ehp + candidate_ally_grant * prob``. When the ranker runs
    # ``score_by="team_blended"`` the sort + efficiency key uses
    # ``delta_team_blended_ehp``; every other score_by leaves both at their
    # no-grant identity (team == blended) so the row stays byte-identical.
    team_blended_ehp: float = 0.0
    delta_team_blended_ehp: float = 0.0
    # RM-87 / row A-18 (2026-07-25): OBSERVABILITY ONLY - the candidate's armor /
    # MR gain over the baseline build, which is the quantity the resist -> damage
    # coupling credit reads. Appended at END with defaults per the Python
    # dataclass convention (a mid-class required field breaks every positional
    # construction). Populated ONLY when the coupling lever is engaged; 0.0
    # otherwise, so the default row stays at identity and the OFF path is
    # byte-identical. They explain a reorder (Thornmail's armor delta pays a
    # second time on Ornn; Warmog's 0.0 is why it does not) - the ranker's sort
    # key is the only consumer.
    delta_armor: float = 0.0
    delta_mr: float = 0.0
    # R194 slice A (RM-116 part a): the SUSTAIN axis surface. ``sustain_ehp`` is
    # the new build's ``effective_ehp_with_sustain`` - blended EHP with the vamp
    # heal pool (lifesteal + spellvamp + omnivamp) folded into the numerator -
    # and ``delta_sustain_ehp`` is its gain over the baseline build. The vamp
    # extra is an ADDEND, not a multiplier, and only a candidate that actually
    # carries vamp earns one, which is why ranking on it reorders where a
    # uniform numerator multiplier provably cannot.
    #
    # Appended at END with defaults per the Python dataclass convention. No
    # shipped item resolves a spellvamp or omnivamp STAT, so both fields sit at
    # their blended identity (sustain == blended) until
    # ``assume_max_stacks_omnivamp`` arms the Riftmaker credit - the default row
    # is unmoved.
    sustain_ehp: float = 0.0
    delta_sustain_ehp: float = 0.0
    # RM-91 T1 (2026-07-26): OBSERVABILITY ONLY - the candidate's MAXIMUM HEALTH
    # gain over the baseline build, which is the quantity the health -> damage
    # coupling credit reads. Appended at the VERY END with a default per the
    # Python dataclass convention (a mid-class required field breaks every
    # positional construction). Populated ONLY when the health coupling lever is
    # engaged; 0.0 otherwise, so the default row stays at identity and the OFF
    # path is byte-identical.
    #
    # ONE field, not two, and the omission is deliberate rather than lazy: the
    # entry's ``pct_base`` may read the BONUS pool, but for an ITEM delta the
    # bonus-health gain and the maximum-health gain are the SAME number - both
    # builds resolve at the same level, so the champion's base block is identical
    # on both sides and cancels out of the subtraction. A second
    # ``delta_bonus_hp`` field would therefore be an exact duplicate column on
    # every row the ranker can ever produce. The ranker passes this one value for
    # both arguments of ``coupled_health_points``, whose two-argument shape is
    # kept so a future non-item caller (a rune / augment lane that grants base
    # health) can distinguish them without a signature change.
    delta_max_hp: float = 0.0
    # RM-118 (2026-08-02): OBSERVABILITY ONLY - the candidate's MAXIMUM MANA gain
    # over the baseline build, which is the quantity the mana -> damage coupling
    # credit reads. Appended at the VERY END with a default per the Python
    # dataclass convention (a mid-class required field breaks every positional
    # construction). Populated ONLY when the mana coupling lever is engaged; 0.0
    # otherwise, so the default row stays at identity and the OFF path is
    # byte-identical.
    #
    # ONE field, not two, for the identical reason ``delta_max_hp`` above is one
    # field: for an ITEM delta the bonus-mana gain and the maximum-mana gain are
    # the SAME number - both builds resolve at the same level, so the champion's
    # base mana block is identical on both sides and cancels out of the
    # subtraction. The ranker passes this one value for both arguments of
    # ``coupled_mana_points``, whose two-argument shape is kept so a future
    # non-item caller (a rune / augment lane granting base mana) can distinguish
    # them without a signature change.
    delta_max_mp: float = 0.0

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
            "team_blended_ehp": self.team_blended_ehp,
            "delta_team_blended_ehp": self.delta_team_blended_ehp,
            "delta_armor": self.delta_armor,
            "delta_mr": self.delta_mr,
            "sustain_ehp": self.sustain_ehp,
            "delta_sustain_ehp": self.delta_sustain_ehp,
            "delta_max_hp": self.delta_max_hp,
            "delta_max_mp": self.delta_max_mp,
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
    # PRE-cc), "cc_blended" (enemy-CC-lockdown-adjusted), "team_blended"
    # (self + ally-granted) or "sustain" (vamp-inclusive, R194 slice A).
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
    apply_item_spell_shield: bool = False,
    apply_item_mana_health: bool = False,
    apply_item_resist_grants: bool = False,
    apply_item_bonus_hp_amp: bool = False,
    assume_item_general_dr: bool = False,
    apply_survival_window: bool = False,
    prefer_survivability_by_win: bool = False,
    cost_ceiling: Optional[int] = None,
    kit_conversion_strength: float = 0.0,
    # ENGINE 1.224.0 (R132) seam, forwarded verbatim to ``compute_ehp``. Appended at
    # the END per compute_ehp's stated convention - a mid-signature insert shifts the
    # positional index of every later parameter. Guarded by
    # tests/test_rune_resist_signature_convention_r134.py.
    apply_rune_resist_grants: bool = False,
    rune_ids: Iterable[str | int] = (),
    # R136 (ENGINE 1.225.0): the RM-101 numerator pair, appended AFTER the R132
    # tail per the same convention. Both reuse the existing ``rune_ids`` transport.
    apply_rune_health_grants: bool = False,
    apply_rune_hsp_amp: bool = False,
    # R137 (ENGINE 1.226.0, RM-99): the item permanent-HP-stack seam, appended AFTER
    # the R136 pair per the same convention.
    assume_item_health_stacks: bool = False,
    apply_rune_flat_mitigation: bool = False,
    assume_item_proc_heal: bool = False,
    # R142 (ENGINE 1.229.0): the RM-101 residual defensive-rune pair, appended at
    # END per the no-mid-signature-insert convention. Both ride the existing
    # ``rune_ids`` transport and are independently gated, so passing rune_ids
    # alone arms neither and the operator can flip each apart from the R132 /
    # R136 lanes.
    apply_rune_self_heal: bool = False,
    apply_rune_shield_grants: bool = False,
    # RM-87 / row A-18 (2026-07-25): the champion RESIST -> DAMAGE coupling lever,
    # appended at END per the no-mid-signature-insert convention. THIS is the
    # function that consumes it: a sort-ONLY credit folded into ``_base_key``
    # (the ``_conv_key`` precedent), never into a row value. Inert unless the flag
    # is True AND the strength is > 0.0 AND the champion is seeded in
    # ``_resist_damage_coupling`` - any one of those failing is an exact no-op.
    apply_resist_damage_coupling: bool = False,
    resist_coupling_strength: float = 0.0,
    # 2026-07-25: the three ASSUMED-INCOMING-SHARE seams, appended at END per the
    # no-mid-signature-insert convention. ``compute_ehp`` arms all three
    # DEFAULT-ON (B45/B46 operator flip for crit-DR + aa-DR, R86 for the enemy
    # AS-slow aura) off a champion-blind 0.5 share constant, but this ranker did
    # not expose them, so no HTTP or client caller could opt back out. Defaults
    # mirror ``compute_ehp`` exactly (True), so an unchanged call site is
    # byte-identical; passing False forwards the opt-out to BOTH the baseline and
    # every candidate call, which is the only way the OFF comparison stays a
    # like-for-like delta.
    assume_item_crit_dr: bool = True,
    assume_item_aa_dr: bool = True,
    assume_item_enemy_as_slow: bool = True,
    # R194 slice A (RM-116 part a): the item-passive omnivamp credit (Riftmaker
    # 4633 / 224633 Void Corruption at MAX stacks), forwarded verbatim to BOTH
    # the baseline and every candidate ``compute_ehp`` call. Appended at END per
    # the no-mid-signature-insert convention. ``compute_ehp`` has carried it
    # since 2026-07-10 and R193 slice C exposed it on the /ehp SCALAR lane only;
    # this is the RANKER lane. DEFAULT-OFF and byte-identical OFF - and even ON
    # the credit lands on the SUSTAIN metric alone, so it moves the ordering
    # only under ``score_by="sustain"``.
    assume_max_stacks_omnivamp: bool = False,
    # RM-91 T1 (2026-07-26): the champion HEALTH -> DAMAGE coupling lever, the
    # HEALTH-axis twin of the RM-87 resist pair above, appended at END per the
    # no-mid-signature-insert convention. A sort-ONLY credit folded into
    # ``_base_key`` (the ``_conv_key`` precedent), never into a row value. Inert
    # unless the flag is True AND the strength is > 0.0 AND the champion is seeded
    # in ``_health_damage_coupling`` - any one of those failing is an exact no-op.
    # DELIBERATELY a SEPARATE flag from the RM-87 pair: the two registries are
    # disjoint (zero champion overlap), so one merged flag would arm a health
    # credit on a resist converter and vice versa.
    apply_health_damage_coupling: bool = False,
    health_coupling_strength: float = 0.0,
    # RM-91 T2 (2026-07-26): the ITEM caster-HP proc credit, appended at END per
    # the no-mid-signature-insert convention. T1 above credits the CHAMPION's kit
    # for re-spending the health DELTA a candidate grants, which is monotone in
    # that delta and so cannot reorder two health items. THIS pair credits the
    # candidate ITEM's OWN caster-HP-scaling proc (Titanic Hydra Cleave 1 percent
    # of max health per basic attack, Heartsteel 6 percent, Unending Despair 3
    # percent of bonus health every 4s) - keyed by ITEM ID, so it is independent
    # of the health delta and a zero-proc item (Randuin's Omen 3143) earns
    # nothing however much health it grants. That independence is the whole point:
    # it is what lets a real core item overtake Randuin's.
    #
    # NOT a double-count with T1: different payers out of different pools (the
    # champion's kit spends the delta, the item spends the existing pool), so the
    # two may be armed together. Separate flags for the same reason RM-87 and
    # RM-91 T1 are separate - arming one must never silently arm the other.
    #
    # Sort-ONLY, folded into ``_base_key``, never into a row value. Inert unless
    # the flag is True AND the strength is > 0.0 - either failing is an exact
    # no-op.
    apply_item_caster_hp_proc: bool = False,
    item_caster_hp_proc_strength: float = 0.0,
    # RM-118 (2026-07-29): the wielder Heal-and-Shield-Power ITEM amp, forwarded
    # verbatim to BOTH the baseline and every candidate ``compute_ehp`` call.
    # Appended at END per the no-mid-signature-insert convention. ``compute_ehp``
    # has carried it since ENGINE 1.171.0 (R60) and R197 wired it onto the SCALAR
    # /ehp + /sustain lanes; this is the RANKER lane, where item choice is
    # actually decided. DEFAULT-OFF and byte-identical OFF. Even ON it is INERT
    # unless a self-shield item (Sterak's / Shieldbow / Maw) is in the baseline or
    # a candidate build - the amp multiplies the ItemShield POOL, which is empty
    # on the HSP pair alone (the honest R197 finding). So it moves ordering only
    # for a candidate that carries its own shield, which is the R194 per-candidate
    # shape, not the RM-115 uniform-multiplier inert shape.
    assume_hsp_amp: bool = False,
    # RM-118 (2026-08-02): the champion MANA -> DAMAGE coupling lever, the
    # MANA-axis twin of the RM-87 resist pair and the RM-91 T1 health pair above,
    # appended at END per the no-mid-signature-insert convention. A sort-ONLY
    # credit folded into ``_base_key`` (the ``_conv_key`` precedent), never into a
    # row value. Inert unless the flag is True AND the strength is > 0.0 AND the
    # champion is seeded in ``_mana_damage_coupling`` - any one of those failing
    # is an exact no-op.
    #
    # DELIBERATELY a SEPARATE flag from BOTH the RM-87 pair and the RM-91 T1 pair:
    # the three registries are disjoint (zero champion overlap at 16.15.1), so a
    # merged flag would arm a mana credit on a resist converter (Rammus, who
    # converts resists and carries no mana term) and a resist credit on the mana
    # converter (Blitzcrank). Arming one lever must never silently arm another.
    apply_mana_damage_coupling: bool = False,
    mana_coupling_strength: float = 0.0,
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
      * ``"sustain"`` - R194 slice A (RM-116 part a). The vamp-inclusive
        ``effective_ehp_with_sustain`` delta: blended EHP with the lifesteal /
        spellvamp / omnivamp heal pool folded into the numerator. The vamp extra
        is an ADDEND earned per CANDIDATE, so unlike a uniform numerator
        multiplier it genuinely reorders. No shipped item resolves a spellvamp
        or omnivamp STAT, so this mode is the byte-identical blended order until
        ``assume_max_stacks_omnivamp`` arms the Riftmaker credit - the same
        arms-when-fed shape as ``cc_blended`` with no ``enemy_champions``.
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
    if score_by not in ("blended", "cc_blended", "team_blended", "sustain"):
        raise ValueError(
            "score_by must be 'blended', 'cc_blended', 'team_blended' or "
            f"'sustain', got {score_by!r}"
        )
    # RM-91: the health-coupling magnitude is validated at the same boundary as
    # the other scalars rather than silently inverting a sort key. The RM-87
    # sibling gets this for free by forwarding its pair to ``compute_ehp``; this
    # lever is ranker-ONLY (nothing in the EHP math reads it), so it is not
    # forwarded anywhere and is checked here instead.
    if health_coupling_strength < 0.0:
        raise ValueError(
            f"health_coupling_strength must be >= 0.0, got {health_coupling_strength}"
        )
    # RM-118: same boundary, same reason - a negative strength would invert the
    # sort key rather than disarm the lever. Ranker-ONLY like its RM-91 sibling
    # (nothing in the EHP math reads it), so it is checked here and forwarded
    # nowhere.
    if mana_coupling_strength < 0.0:
        raise ValueError(
            f"mana_coupling_strength must be >= 0.0, got {mana_coupling_strength}"
        )
    # RM-91 T2: same boundary, same reason - a negative strength would invert the
    # sort key rather than disarm the lever.
    if item_caster_hp_proc_strength < 0.0:
        raise ValueError(
            "item_caster_hp_proc_strength must be >= 0.0, got "
            f"{item_caster_hp_proc_strength}"
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

    # Term A (2026-07-18, ENGINE 1.220.0, DEFAULT-OFF): resolve the ally-grant
    # amortizer ONCE. Non-zero only when score_by == "team_blended" AND the
    # champion's kit actually reaches allies, so on every other path the
    # multiplier is 0.0, the new row fields collapse to their blended identity
    # (team_blended_ehp == blended_ehp, delta_team_blended_ehp == delta_ehp) and
    # neither active_delta nor the sort key ever reads them - byte-identical.
    #
    # The coefficient is the SHIPPED _ALLY_SHIELD_HEAL_PROB (0.5) - "the
    # expected fraction of the modeled fight in which the granted shield / heal
    # HP is PRESENT on the protected ally". Term A introduces ZERO new
    # constants; it reuses the amortizer the champion-side ally registry
    # already uses for exactly this quantity.
    #
    # Both sides of the sum are EHP: a flat shield / heal sits at the TOP of the
    # protected ally's damage stack exactly like base HP, so it rides the same
    # armor/MR curve and adds RAW to the numerator - the contract this module
    # already documents for the self-shield pool. No cross-unit conversion is
    # introduced (deliberately unlike hybrid.py, which needed a whole
    # normalization layer to paper over one mixed-unit addition).
    _ally_grant_mult = (
        _ALLY_SHIELD_HEAL_PROB
        if (score_by == "team_blended" and champion_ally_reach(champion_id))
        else 0.0
    )
    _baseline_ally_ehp = (
        total_item_ally_grant_hp(current_ids, level) * _ally_grant_mult
        if _ally_grant_mult else 0.0
    )

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
        apply_item_spell_shield=apply_item_spell_shield,
        apply_item_mana_health=apply_item_mana_health,
        apply_item_resist_grants=apply_item_resist_grants,
        apply_rune_resist_grants=apply_rune_resist_grants,
        rune_ids=rune_ids,
        apply_rune_health_grants=apply_rune_health_grants,
        apply_rune_hsp_amp=apply_rune_hsp_amp,
        apply_rune_self_heal=apply_rune_self_heal,
        apply_rune_shield_grants=apply_rune_shield_grants,
        assume_item_health_stacks=assume_item_health_stacks,
        apply_rune_flat_mitigation=apply_rune_flat_mitigation,
        assume_item_proc_heal=assume_item_proc_heal,
        apply_item_bonus_hp_amp=apply_item_bonus_hp_amp,
        assume_item_general_dr=assume_item_general_dr,
        apply_survival_window=apply_survival_window,
        # RM-87: forwarded to the BASELINE call only, and only so the strength is
        # validated at the same boundary as the enemy-share floats. The pair is
        # inert inside compute_ehp by construction (nothing in the EHP math reads
        # it), so this forward cannot perturb a single baseline value; the
        # per-candidate calls below deliberately do NOT forward it, because a
        # sort-only lever has no business being re-validated once per candidate.
        apply_resist_damage_coupling=apply_resist_damage_coupling,
        resist_coupling_strength=resist_coupling_strength,
        # Assumed-incoming-share seams: forwarded to the BASELINE call so the
        # prefix build's own carriers (Plated Steelcaps' aa-DR is a common early
        # tank buy) are treated the same way as the candidates'. Forwarding only
        # one side would compare an armed baseline against a disarmed candidate.
        assume_item_crit_dr=assume_item_crit_dr,
        assume_item_aa_dr=assume_item_aa_dr,
        assume_item_enemy_as_slow=assume_item_enemy_as_slow,
        # R194 slice A: forwarded to the BASELINE call so a prefix build that
        # already owns Riftmaker is credited the same way a candidate is.
        # Forwarding only the candidate side would compare an armed candidate
        # against a disarmed baseline and manufacture the whole delta.
        assume_max_stacks_omnivamp=assume_max_stacks_omnivamp,
        assume_hsp_amp=assume_hsp_amp,
    )

    # RM-87 / row A-18 (2026-07-25): resolve the resist -> damage coupling ONCE.
    # Consulted ONLY when the flag is engaged AND the strength is positive, so a
    # default call never touches the registry (the ``_conv`` gating shape).
    # ``_coupling_pool`` is the BASELINE build's RAW resist pool (armor + MR on the
    # basis the entry names, percent-FREE) - the denominator that turns a
    # candidate's coupled resist points into a dimensionless percent-delta,
    # exactly how ``hybrid._hybrid_delta_pct`` normalizes ``delta_dps /
    # baseline_dps`` and ``delta_ehp / baseline_ehp`` before weighting two
    # different units. Percent-FREE on purpose: normalizing by the percent-
    # weighted baseline would cancel the percents and hand a 5-percent converter
    # the same credit as a 40-percent one. A non-positive pool (a level-1
    # no-item bonus-basis build) disarms the lane rather than dividing by zero.
    _coupling = (
        resist_damage_coupling(str(champion_id))
        if (apply_resist_damage_coupling and resist_coupling_strength > 0.0)
        else None
    )
    _coupling_pool = 0.0
    if _coupling is not None:
        if _coupling.pct_base == "bonus":
            # BONUS basis: subtract the champion's own base block, exactly how
            # compute_ehp derives its bonus_hp / bonus_ad (``stats`` minus
            # ``base_stats`` off the SAME resolved build).
            _cpl_resolved = build_champion(
                snapshot, champion_id, level, item_ids=current_ids, mode=mode,
                augments=augments, apply_mode_modifiers=apply_mode_modifiers,
            )
            _cpl_base = _cpl_resolved.base_stats
            _basis_armor = max(
                0.0, baseline.armor - float(_cpl_base.get("armor", 0.0))
            )
            _basis_mr = max(0.0, baseline.mr - float(_cpl_base.get("mr", 0.0)))
        else:
            _basis_armor, _basis_mr = baseline.armor, baseline.mr
        _coupling_pool = _basis_armor + _basis_mr
        if _coupling_pool <= 0.0:
            _coupling = None

    # RM-91 T1 (2026-07-26): resolve the HEALTH -> damage coupling ONCE, the exact
    # mirror of the RM-87 block above on the health axis. Consulted ONLY when the
    # flag is engaged AND the strength is positive, so a default call never
    # touches the registry.
    #
    # ``_health_pool`` is the BASELINE build's RAW health on the basis the entry
    # names, percent-FREE - the denominator that turns a candidate's coupled
    # health points into a dimensionless percent-delta. Percent-FREE is
    # load-bearing for the same reason it is on the resist lever: normalizing by
    # a percent-weighted pool would cancel the percents and hand a 2.5-percent
    # converter (Braum) the same credit as an 11-percent one (Shen). A
    # non-positive pool (a level-1 no-item bonus-basis build) disarms the lane
    # rather than dividing by zero.
    _health_coupling = (
        health_damage_coupling(str(champion_id))
        if (apply_health_damage_coupling and health_coupling_strength > 0.0)
        else None
    )
    _health_pool = 0.0
    # RM-91 T2 shares this resolve with T1 rather than building the champion
    # twice when both levers are armed. None until some lane actually needs the
    # base-stat block, so a default call still resolves nothing.
    _hcpl_resolved = None
    if _health_coupling is not None:
        if _health_coupling.pct_base == "bonus":
            # BONUS basis: subtract the champion's own base block at THIS level,
            # exactly how compute_ehp derives its bonus_hp (``stats`` minus
            # ``base_stats`` off the SAME resolved build). ``base_stats`` is the
            # level-scaled no-item block, so this is item-granted health.
            _hcpl_resolved = build_champion(
                snapshot, champion_id, level, item_ids=current_ids, mode=mode,
                augments=augments, apply_mode_modifiers=apply_mode_modifiers,
            )
            _health_pool = max(
                0.0, baseline.hp - float(_hcpl_resolved.base_stats.get("hp", 0.0))
            )
        else:
            _health_pool = baseline.hp
        if _health_pool <= 0.0:
            _health_coupling = None

    # RM-118 (2026-08-02): resolve the MANA -> damage coupling ONCE, the exact
    # mirror of the RM-87 and RM-91 T1 blocks above on the mana axis. Consulted
    # ONLY when the flag is engaged AND the strength is positive, so a default
    # call never touches the registry.
    #
    # ``_mana_pool`` is the BASELINE build's RAW mana on the basis the entry
    # names, percent-FREE - the denominator that turns a candidate's coupled mana
    # points into a dimensionless percent-delta. Percent-FREE is load-bearing for
    # the same reason it is on the resist and health levers: normalizing by a
    # percent-weighted pool would cancel the percents and hand a 2-percent
    # converter the same credit as a 6-percent one. A non-positive pool (a
    # manaless champion resolves ``mp`` to 0.0) disarms the lane rather than
    # dividing by zero.
    _mana_coupling = (
        mana_damage_coupling(str(champion_id))
        if (apply_mana_damage_coupling and mana_coupling_strength > 0.0)
        else None
    )
    _mana_pool = 0.0
    if _mana_coupling is not None:
        if _mana_coupling.pct_base == "bonus":
            # BONUS basis: subtract the champion's own base mana block at THIS
            # level off the SAME resolved build, exactly how the health lane
            # derives its bonus pool. Reuse the RM-91 resolve when some earlier
            # lane already built it rather than resolving the champion twice.
            if _hcpl_resolved is None:
                _hcpl_resolved = build_champion(
                    snapshot, champion_id, level, item_ids=current_ids, mode=mode,
                    augments=augments, apply_mode_modifiers=apply_mode_modifiers,
                )
            _mana_pool = max(
                0.0, baseline.max_mana - float(_hcpl_resolved.base_stats.get("mp", 0.0))
            )
        else:
            _mana_pool = baseline.max_mana
        if _mana_pool <= 0.0:
            _mana_coupling = None

    # RM-91 T2 (2026-07-26): resolve the ITEM-proc pools ONCE. Unlike T1 this
    # lever is CHAMPION-BLIND - an item's proc pays out for whoever wields it -
    # so there is no registry lookup here, only the two health pools every
    # candidate's credit normalizes against.
    #
    # BOTH pools are needed, not one: a max-basis proc (Titanic 1 percent) reads
    # the total pool while a bonus-basis proc (Unending Despair 3 percent of BONUS
    # health) reads the much smaller item-granted pool, and collapsing them would
    # over-price every bonus-basis item by the ratio between them.
    _hp_proc_armed = bool(
        apply_item_caster_hp_proc and item_caster_hp_proc_strength > 0.0
    )
    _hp_proc_pool_total = 0.0
    _hp_proc_pool_bonus = 0.0
    if _hp_proc_armed:
        if _hcpl_resolved is None:
            _hcpl_resolved = build_champion(
                snapshot, champion_id, level, item_ids=current_ids, mode=mode,
                augments=augments, apply_mode_modifiers=apply_mode_modifiers,
            )
        _hp_proc_pool_total = max(0.0, baseline.hp)
        _hp_proc_pool_bonus = max(
            0.0, baseline.hp - float(_hcpl_resolved.base_stats.get("hp", 0.0))
        )
        # A non-positive TOTAL pool would divide by zero. The bonus pool may
        # legitimately be zero (a no-health build) and simply zeroes the
        # bonus-basis half of the numerator, so it is not a disarm condition.
        if _hp_proc_pool_total <= 0.0:
            _hp_proc_armed = False

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
        champion_is_melee=_champion_is_melee(champ_rec, augments),
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
                apply_item_spell_shield=apply_item_spell_shield,
                apply_item_mana_health=apply_item_mana_health,
                apply_item_resist_grants=apply_item_resist_grants,
                apply_rune_resist_grants=apply_rune_resist_grants,
                rune_ids=rune_ids,
                apply_rune_health_grants=apply_rune_health_grants,
                apply_rune_hsp_amp=apply_rune_hsp_amp,
                apply_rune_self_heal=apply_rune_self_heal,
                apply_rune_shield_grants=apply_rune_shield_grants,
                assume_item_health_stacks=assume_item_health_stacks,
                apply_rune_flat_mitigation=apply_rune_flat_mitigation,
                assume_item_proc_heal=assume_item_proc_heal,
                apply_item_bonus_hp_amp=apply_item_bonus_hp_amp,
                assume_item_general_dr=assume_item_general_dr,
                apply_survival_window=apply_survival_window,
                # Same seams as the baseline call - see the note there.
                assume_item_crit_dr=assume_item_crit_dr,
                assume_item_aa_dr=assume_item_aa_dr,
                assume_item_enemy_as_slow=assume_item_enemy_as_slow,
                assume_max_stacks_omnivamp=assume_max_stacks_omnivamp,
                assume_hsp_amp=assume_hsp_amp,
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
        # Term A: the candidate's own ally grant, amortized. The CURRENT build's
        # grant is identical on both sides of the subtraction and cancels, so
        # the team delta is exactly ``delta + candidate_grant * prob``. The
        # multiplier is 0.0 unless score_by == "team_blended" AND the champion
        # reaches allies, so this is byte-identical on every other path.
        cand_ally_grant = (
            ally_grant_hp(item_id, level) * _ally_grant_mult
            if _ally_grant_mult else 0.0
        )
        team_delta = delta + cand_ally_grant
        team_ehp = scored.blended_ehp + _baseline_ally_ehp + cand_ally_grant
        # R194 slice A: the vamp-inclusive delta. ``compute_ehp`` already
        # computes both sides, so this costs one subtraction and no extra call.
        # Equals ``delta`` exactly whenever neither build resolves a spellvamp
        # or omnivamp stat, which is every build until the omnivamp seam is
        # armed - the row identity the default path relies on.
        sustain_delta = (
            scored.effective_ehp_with_sustain - baseline.effective_ehp_with_sustain
        )
        active_delta = (
            cc_delta if score_by == "cc_blended"
            else team_delta if score_by == "team_blended"
            else sustain_delta if score_by == "sustain"
            else delta
        )
        eff = (active_delta / (gold / 1000.0)) if (gold > 0 and active_delta > 0) else 0.0
        # RF3 survivability credit marker: 1.0 on a WIN-anchored survivability item
        # when the seam is engaged, else 0.0. Floated BY MEMBERSHIP - these items
        # are pooled but the raw-EHP-max delta sort buries the win-correlated ones.
        survivability_score = 1.0 if (surv_active and item_id in surv_ids) else 0.0
        # RM-87 observability: the candidate's resist gain, which is the quantity
        # the coupling credit reads. 0.0 unless the lane is armed -> the default
        # row (and to_dict) stays at identity.
        if _coupling is not None:
            cpl_d_armor = scored.armor - baseline.armor
            cpl_d_mr = scored.mr - baseline.mr
        else:
            cpl_d_armor = 0.0
            cpl_d_mr = 0.0
        # RM-91 observability: the candidate's maximum-health gain, which is the
        # quantity the health-coupling credit reads. Both builds resolve at the
        # same level, so the champion's base block cancels and this ALSO equals
        # the bonus-health gain - which is why one field covers both bases.
        # 0.0 unless the lane is armed -> the default row (and to_dict) stays at
        # identity.
        hcpl_d_hp = (scored.hp - baseline.hp) if _health_coupling is not None else 0.0
        # RM-118 observability: the candidate's maximum-mana gain, which is the
        # quantity the mana-coupling credit reads. Both builds resolve at the same
        # level, so the champion's base mana block cancels and this ALSO equals the
        # bonus-mana gain - which is why one field covers both bases. 0.0 unless
        # the lane is armed -> the default row (and to_dict) stays at identity.
        mcpl_d_mp = (
            (scored.max_mana - baseline.max_mana) if _mana_coupling is not None else 0.0
        )
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
            team_blended_ehp=team_ehp,
            delta_team_blended_ehp=team_delta,
            delta_armor=cpl_d_armor,
            delta_mr=cpl_d_mr,
            sustain_ehp=scored.effective_ehp_with_sustain,
            delta_sustain_ehp=sustain_delta,
            delta_max_hp=hcpl_d_hp,
            delta_max_mp=mcpl_d_mp,
        ))

    # Item 236: the sort key tracks score_by. Default "blended" sorts on
    # delta_ehp (byte-identical); "cc_blended" sorts on delta_cc_blended_ehp.
    # Term A: "team_blended" sorts on delta_team_blended_ehp.
    # R194 slice A: "sustain" sorts on delta_sustain_ehp.
    _active = (
        (lambda r: r.delta_cc_blended_ehp)
        if score_by == "cc_blended"
        else (lambda r: r.delta_team_blended_ehp)
        if score_by == "team_blended"
        else (lambda r: r.delta_sustain_ehp)
        if score_by == "sustain"
        else (lambda r: r.delta_ehp)
    )

    # RM-86 L1 kit-conversion gate (DEFAULT-OFF). Objective is "ehp", not the
    # damage axis: for a tank, health and resists ARE the output, so only raw
    # damage stats are off-axis. Registry consulted ONLY when the lever is
    # engaged -> 0.0 is provably byte-identical (onhit_dps.py:494-496).
    _conv = (
        kit_conversion(str(champion_id), champ_rec)
        if kit_conversion_strength > 0.0 else None
    )
    _conv_memo: dict[str, float] = {}

    def _conv_key(value: float, item_id: str) -> float:
        """Sort-only view of ``value`` - never mutates the row itself.

        Only ever LOWERS: a non-positive value is returned unchanged, because
        scaling a negative number toward zero would RAISE its rank
        (the onhit_dps.py:501-504 rule).
        """
        if _conv is None or value <= 0.0:
            return value
        factor = _conv_memo.get(item_id)
        if factor is None:
            factor = conversion_factor(
                _conv, item_id, snapshot.items.get(item_id) or {},
                kit_conversion_strength, "ehp",
            )
            _conv_memo[item_id] = factor
        return value * factor

    def _coupling_key(value: float, r: EhpRankedItem) -> float:
        """RM-87 sort-only view of ``value`` - never mutates the row itself.

        The champion's kit re-spends a fraction of its resists as damage
        (``_resist_damage_coupling``), and this module credits that payment
        nowhere: ``ehp.py`` reads zero damage_blocks. The credit is a
        NORMALIZED percent-delta, the ``hybrid._hybrid_delta_pct`` idiom:

            points = armor_pct/100 * delta_armor + mr_pct/100 * delta_mr
            credit = strength * conditional_probability * points / pool

        where ``pool`` is the BASELINE build's RAW resist total on the basis the
        entry names (total or bonus per ``pct_base``), percent-FREE. Both halves
        are resist points, so ``points / pool`` is dimensionless and the lever
        stays unit-free - no EHP-vs-damage unit mixing enters the sort key - and
        because the pool carries no percents the credit scales with the
        conversion MAGNITUDE (Ornn's 40 percent earns 8x Rell's 5 percent).

        Only ever RAISES, and only for a candidate that actually grants resists.
        A non-positive value is returned unchanged (the ``_conv_key`` guard,
        mirrored: scaling a negative delta UP would push a regression further
        down, which is a behavior change this seam has no business making).
        """
        if _coupling is None or value <= 0.0:
            return value
        points = coupled_resist_points(_coupling, r.delta_armor, r.delta_mr)
        if points <= 0.0:
            return value
        credit = (
            resist_coupling_strength
            * _coupling.conditional_probability
            * (points / _coupling_pool)
        )
        return value * (1.0 + credit)

    def _health_key(value: float, r: EhpRankedItem) -> float:
        """RM-91 sort-only view of ``value`` - never mutates the row itself.

        The champion's kit re-spends a fraction of its HEALTH as damage
        (``_health_damage_coupling``), and this module credits that payment
        nowhere: ``ehp.py`` reads zero damage_blocks. Same shape as
        ``_coupling_key``, one axis over:

            points = max_hp_pct/100 * delta_max_hp + bonus_hp_pct/100 * delta_bonus_hp
            credit = strength * conditional_probability * points / pool

        where ``pool`` is the BASELINE build's RAW health on the basis the entry
        names (total or bonus per ``pct_base``), percent-FREE. Both halves are
        health points, so ``points / pool`` is dimensionless and the lever stays
        unit-free, and because the pool carries no percents the credit scales
        with the conversion MAGNITUDE (Shen's 11 percent earns 2.75x Tahm
        Kench's 4 percent).

        For an ITEM delta the maximum-health and bonus-health gains are the same
        number (the base block cancels), so ``r.delta_max_hp`` is passed for
        both - see the field's note on ``EhpRankedItem``.

        Only ever RAISES, and only for a candidate that actually grants health.
        A non-positive value is returned unchanged (the ``_conv_key`` guard,
        mirrored).

        KNOWN LIMIT, deliberate and out of scope for T1: this factor is MONOTONE
        in ``delta_max_hp``, so it can raise health-granting candidates above
        resist-only ones but can never re-order WITHIN the health axis - a
        600-HP item cannot overtake a 1000-HP one. Crediting an ITEM's own
        caster-HP-scaling proc is the follow-on (T2).
        """
        if _health_coupling is None or value <= 0.0:
            return value
        points = coupled_health_points(
            _health_coupling, r.delta_max_hp, r.delta_max_hp
        )
        if points <= 0.0:
            return value
        credit = (
            health_coupling_strength
            * _health_coupling.conditional_probability
            * (points / _health_pool)
        )
        return value * (1.0 + credit)

    def _mana_key(value: float, r: EhpRankedItem) -> float:
        """RM-118 sort-only view of ``value`` - never mutates the row itself.

        The champion's kit re-spends a fraction of its MANA as damage
        (``_mana_damage_coupling``), and this module credits that payment
        nowhere: ``ehp.py`` reads zero damage_blocks. Same shape as
        ``_coupling_key`` / ``_health_key``, one axis over:

            points = max_mp_pct/100 * delta_max_mp + bonus_mp_pct/100 * delta_bonus_mp
            credit = strength * conditional_probability * points / pool

        where ``pool`` is the BASELINE build's RAW mana on the basis the entry
        names (total or bonus per ``pct_base``), percent-FREE. Both halves are
        mana points, so ``points / pool`` is dimensionless and the lever stays
        unit-free - no EHP-vs-damage unit mixing enters the sort key - and
        because the pool carries no percents the credit scales with the
        conversion MAGNITUDE.

        For an ITEM delta the maximum-mana and bonus-mana gains are the same
        number (the base block cancels), so ``r.delta_max_mp`` is passed for
        both - see the field's note on ``EhpRankedItem``.

        Only ever RAISES, and only for a candidate that actually grants mana.
        A non-positive value is returned unchanged (the ``_conv_key`` guard,
        mirrored).

        KNOWN LIMIT, inherited from the RM-91 T1 sibling: this factor is MONOTONE
        in ``delta_max_mp``, so it can raise mana-granting candidates above
        mana-free ones but can never re-order WITHIN the mana axis.
        """
        if _mana_coupling is None or value <= 0.0:
            return value
        points = coupled_mana_points(
            _mana_coupling, r.delta_max_mp, r.delta_max_mp
        )
        if points <= 0.0:
            return value
        credit = (
            mana_coupling_strength
            * _mana_coupling.conditional_probability
            * (points / _mana_pool)
        )
        return value * (1.0 + credit)

    def _hp_proc_key(value: float, r: EhpRankedItem) -> float:
        """RM-91 T2 sort-only view of ``value`` - never mutates the row itself.

        The candidate ITEM's own proc re-spends a fraction of the WIELDER's
        health pool as damage, and ``ehp.py`` prices it nowhere (it reads zero
        damage). Same normalized-percent shape as ``_coupling_key`` /
        ``_health_key``, one payer over:

            points = max_hp_pct/100 * pool_total + bonus_hp_pct/100 * pool_bonus
            credit = strength * min(cap, fires_per_fight * points / pool_total)

        The decisive difference from T1: ``points`` reads the EXISTING pool, not
        the candidate's health delta, so the factor is INDEPENDENT of how much
        health the candidate grants. A candidate with no caster-HP proc gets
        exactly nothing (Randuin's Omen 3143, Frozen Heart 3110), which is what
        allows a smaller-EHP core item to overtake a bigger-EHP one - the
        reordering T1 provably could not perform.

        Dimensionless throughout: both halves of ``points / pool_total`` are
        health points, so no EHP-vs-damage unit mixing enters the sort key.

        Only ever RAISES, and only for a candidate whose own proc converts caster
        health. A non-positive value is returned unchanged (the ``_conv_key``
        guard, mirrored: scaling a negative delta up would push a regression
        further down).
        """
        if not _hp_proc_armed or value <= 0.0:
            return value
        entry = item_caster_hp_proc(r.item_id)
        if entry is None:
            return value
        points = proc_converted_points(
            entry, _hp_proc_pool_total, _hp_proc_pool_bonus
        )
        if points <= 0.0:
            return value
        fraction = min(
            _MAX_CONVERTED_FRACTION,
            entry.fires_per_fight * (points / _hp_proc_pool_total),
        )
        return value * (1.0 + item_caster_hp_proc_strength * fraction)

    def _base_key(r: EhpRankedItem) -> tuple:
        if sort_by == "efficiency":
            return (
                _mana_key(_hp_proc_key(_health_key(_coupling_key(_conv_key(r.ehp_per_1k_gold, r.item_id), r), r), r), r),
                _mana_key(_hp_proc_key(_health_key(_coupling_key(_conv_key(_active(r), r.item_id), r), r), r), r),
            )
        return (
            _mana_key(_hp_proc_key(_health_key(_coupling_key(_conv_key(_active(r), r.item_id), r), r), r), r),
            _mana_key(_hp_proc_key(_health_key(_coupling_key(_conv_key(r.ehp_per_1k_gold, r.item_id), r), r), r), r),
        )

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
    if score_by == "team_blended":
        notes.append(
            "score_by=team_blended - ranked on self EHP + ally-granted EHP"
            + (
                f" (ally reach ON, grant amortized at {_ally_grant_mult:.2f})"
                if _ally_grant_mult
                else " (champion has no ally-facing ability -> identical to blended)"
            )
        )
    if score_by == "sustain":
        notes.append(
            "score_by=sustain - ranked on vamp-inclusive effective EHP"
            + (
                " (assume_max_stacks_omnivamp ON - item omnivamp credited)"
                if assume_max_stacks_omnivamp
                else " (no vamp source armed -> identical to blended)"
            )
        )
    if surv_active:
        notes.append(
            f"prefer_survivability_by_win=ON - {len(surv_ids)} WIN-anchored "
            f"survivability item(s) floated above the max-EHP ordering"
        )
    if _coupling is not None:
        notes.append(
            f"apply_resist_damage_coupling=ON ({_coupling.attribute}) - sort-only "
            f"credit for {_coupling.armor_pct:.0f}% {_coupling.pct_base} armor + "
            f"{_coupling.mr_pct:.0f}% {_coupling.pct_base} MR re-spent as damage, "
            f"strength={resist_coupling_strength:.2f}, amortized at "
            f"{_coupling.conditional_probability:.2f}, normalized against a "
            f"{_coupling_pool:.1f}-point baseline {_coupling.pct_base} resist pool"
        )
    elif apply_resist_damage_coupling and resist_coupling_strength > 0.0:
        notes.append(
            "apply_resist_damage_coupling=ON but inert - champion has no seeded "
            "resist->damage conversion (or a zero baseline resist pool)"
        )
    if _health_coupling is not None:
        _hc_pct = _health_coupling.max_hp_pct + _health_coupling.bonus_hp_pct
        notes.append(
            f"apply_health_damage_coupling=ON ({_health_coupling.attribute}) - "
            f"sort-only credit for {_hc_pct:.1f}% {_health_coupling.pct_base} "
            f"health re-spent as damage, strength={health_coupling_strength:.2f}, "
            f"amortized at {_health_coupling.conditional_probability:.2f}, "
            f"normalized against a {_health_pool:.1f}-point baseline "
            f"{_health_coupling.pct_base} health pool"
        )
    elif apply_health_damage_coupling and health_coupling_strength > 0.0:
        notes.append(
            "apply_health_damage_coupling=ON but inert - champion has no seeded "
            "health->damage conversion (or a zero baseline health pool)"
        )
    if _mana_coupling is not None:
        _mc_pct = _mana_coupling.max_mp_pct + _mana_coupling.bonus_mp_pct
        notes.append(
            f"apply_mana_damage_coupling=ON ({_mana_coupling.attribute}) - "
            f"sort-only credit for {_mc_pct:.1f}% {_mana_coupling.pct_base} "
            f"mana re-spent as damage, strength={mana_coupling_strength:.2f}, "
            f"amortized at {_mana_coupling.conditional_probability:.2f}, "
            f"normalized against a {_mana_pool:.1f}-point baseline "
            f"{_mana_coupling.pct_base} mana pool"
        )
    elif apply_mana_damage_coupling and mana_coupling_strength > 0.0:
        notes.append(
            "apply_mana_damage_coupling=ON but inert - champion has no seeded "
            "mana->damage conversion (or a zero baseline mana pool)"
        )
    if _hp_proc_armed:
        # Count the credited candidates from the POOL, not from the census: what
        # the operator needs to know is how many of the items actually on offer
        # earned the credit, which is the number that explains the reorder.
        _hp_proc_hits = sum(
            1 for r in ranked if item_caster_hp_proc(r.item_id) is not None
        )
        notes.append(
            f"apply_item_caster_hp_proc=ON - sort-only credit for a candidate's "
            f"OWN caster-health proc on {_hp_proc_hits} of {len(ranked)} ranked "
            f"item(s), strength={item_caster_hp_proc_strength:.2f}, cadence "
            f"amortized over a {_REFERENCE_FIGHT_SECONDS:.0f}s reference fight, "
            f"normalized against a {_hp_proc_pool_total:.1f}-point total / "
            f"{_hp_proc_pool_bonus:.1f}-point bonus health pool"
        )
    elif apply_item_caster_hp_proc and item_caster_hp_proc_strength > 0.0:
        notes.append(
            "apply_item_caster_hp_proc=ON but inert - zero baseline health pool"
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
