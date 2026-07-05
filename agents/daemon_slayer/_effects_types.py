"""Daemon Slayer item-effects schema types + damage-type constants.

Split out of effects.py (s246, behavior-preserving) so the large
static ITEM_EFFECTS data table (now _effects_data.py) and these
schema types are separate import units. Pure types - zero engine
dependency. effects.py re-exports every public name here, so all
existing `from .effects import ...` callers stay unchanged.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Iterable, Union


PHYSICAL = "physical"
MAGICAL = "magical"
TRUE = "true"
_DAMAGE_TYPES = frozenset({PHYSICAL, MAGICAL, TRUE})

# ENGINE 1.27.0 (2026-05-21): shield damage-type set. Mirrors the proc
# damage-type values but adds ``ANY`` for type-agnostic shields (Sterak's
# Lifeline, Immortal Shieldbow). Kept separate from _DAMAGE_TYPES so
# PeriodicProc.damage_type cannot accidentally become "any" (proc damage
# always has a real type; "any" only applies to shield absorption).
ANY = "any"
_SHIELD_TYPES = frozenset({PHYSICAL, MAGICAL, TRUE, ANY})


@dataclass(frozen=True)
class CallContext:
    """Inputs available to a scaling ``bonus_damage`` callable.

    ``base_ad`` is the leveled champion-base AD (pre-items), needed for
    spellblade-style scaling. ``bonus_ad`` is the item-contributed AD.
    ``level`` enables Wit's End-style level scaling. ``ap`` (added
    2026-05-04, Phase 4 batch 3) is total Ability Power - pure
    item-contributed, since champion records carry no base AP - and
    enables Lich Bane / Nashor's Tooth-style spellblade and AP-on-hit
    scaling.

    ``target_max_hp`` (added 2026-05-04, Phase 4 batch 5) is the
    caller-supplied target max HP - same shape as ``target_armor`` /
    ``target_mr``, default 0.0 means "caller didn't say so contributions
    floor at zero". Unlocks BotRK / Eclipse %-target-HP procs. lolmath
    scenarios carry no HP signal, so callers (arena_coach, sr_draft,
    /dps clients) decide a realistic value from game context. ``%-current-HP``
    procs use the steady-state assumption ``current = max``; explicit
    chunking simulation (e.g. "target at 30%") is a future field.

    ``caster_max_hp`` / ``caster_bonus_hp`` (added 2026-05-04, Phase 4
    batch 6) are engine-derived (``resolved.stats["hp"]`` and
    ``stats["hp"] - base_stats["hp"]`` respectively). Unlike
    ``target_max_hp``, these aren't caller-supplied - the engine knows
    the caster's exact HP from the build. Unlocks Titanic Hydra Cleave
    (1.5% bonus HP) + Heartsteel Colossal Consumption (6% max HP).

    ``targets_in_rotation`` (added 2026-05-04, Phase 4 batch 7) is the
    rotation's ``numberOfTargets`` (lolmath field). Default 1.0 means
    "single-target rotation"; lambdas that don't reference it stay
    single-target. AoE-incl-primary procs use ``c.targets_in_rotation``
    directly; cleave-to-others procs use
    ``max(0, c.targets_in_rotation - 1)``. Engine sets it per rotation
    via ``dataclasses.replace`` in ``_rotation_attack_dps``.

    ``crit_chance`` (added 2026-05-04, Phase 4 batch 21) is the build's
    resolved crit chance as a fraction (0.0-1.0), engine-derived from
    ``stats.get("crit")`` and clamped at 1.0. Required for crit-scaling
    procs (Essence Reaver Spellblade scales linearly: +0.5 bonus
    physical per 1% crit, capped at +50 at 100%). Default 0.0 means
    "build has no crit" - pre-batch-21 callers don't pass it and procs
    that reference it gracefully no-op.
    """
    base_ad: float
    bonus_ad: float
    level: int
    target_armor: float = 0.0
    target_mr: float = 0.0
    ap: float = 0.0
    target_max_hp: float = 0.0
    caster_max_hp: float = 0.0
    caster_bonus_hp: float = 0.0
    targets_in_rotation: float = 1.0
    crit_chance: float = 0.0
    # Phase 4 batch 19 (2026-05-04): caller-supplied target bonus HP -
    # same shape as target_max_hp (default 0.0 = "caller didn't say").
    # Required for target-conditional amp items (LDR Giant Slayer scales
    # with the enemy's bonus HP only). Distinct from target_max_hp
    # because base HP varies per-target (Aatrox lvl 11 base ~ 1790, but
    # an enemy Cho'Gath mid-game may have 1500 base HP); the engine
    # can't infer it without naming the target. Procs that key on this
    # field gracefully no-op when the caller leaves it at 0.
    target_bonus_hp: float = 0.0
    # Phase 4 batch 27 (2026-05-04): caster max mana - engine-derived from
    # ``stats["mp"]`` (champion base mp + per-level scaling + item flat mp
    # contributions). Sibling of caster_max_hp from batch 6. Required for
    # Manamune / Muramana's Awe (2% max mana -> bonus AD) and Muramana's
    # Shock (1.2% max mana per-attack proc). Default 0.0 means "build has
    # no mana" - manaless champions (energy users like Lee Sin, Akali)
    # and pre-batch-27 callers gracefully no-op any mana-scaling proc.
    caster_max_mp: float = 0.0
    # Phase 4 batch 58 (2026-05-04): caster bonus armor - engine-derived as
    # ``stats["armor"] - base_armor`` (item-contributed armor only). Same
    # base/bonus split pattern as caster_bonus_hp from batch 6. Required for
    # Darksteel Talons' Gash (+ 20% bonus armor ranged) scaling. Default
    # 0.0 -> pre-batch-58 builds no-op gracefully.
    caster_bonus_armor: float = 0.0
    # Phase 4 batch 59 (2026-05-04): caster raw lethality - engine-derived
    # as ``sum(e.lethality for e in item_effects)`` (raw, before level-
    # scaling to flat pen). Required for Bastionbreaker Shaped Charge
    # (15 + 0.75 x lethality ranged). Distinct from flat pen: the formula
    # uses the un-scaled lethality value, not the effective flat armor pen.
    # Default 0.0 -> builds without lethality no-op gracefully.
    caster_lethality: float = 0.0
    # Phase 4 batch 63 (2026-05-05): per-champion ult cast rate in casts/sec,
    # looked up from ``data/daemon_slayer/ult_cast_rates.json`` (derived from
    # rewind_history.db spell4_casts / game_duration_s). Engine-supplied via
    # ``ult_rates.get_ult_casts_per_sec(champion_name, mode)`` in compute_dps.
    # Required for Malignance Hatefog: the PeriodicProc uses every_n_seconds=1.0
    # and bonus_damage = (180 + 0.15 * ap) * ult_casts_per_sec so the proc
    # rate is champion-aware without changing the PeriodicProc schema. Default
    # 0.0 -> Malignance contributes 0 DPS when champion data is absent (safe).
    ult_casts_per_sec: float = 0.0
    # DS target-current-HP% scenario lever (BACKLOG item): caller-supplied
    # fraction (0.0-1.0) of the target's CURRENT HP relative to its max HP.
    # The three genuine %-current-HP item procs - BotRK 3153 Mist's Edge,
    # Hellfire Hatchet 4017 Char, Fulmination 443055 Dynamo - multiply their
    # current-HP magnitude by this factor so a caller can model "target at
    # 50% HP" instead of the steady-state current==max assumption. Genuine
    # %-MAX-HP procs (Eclipse 6692, Titanic Hydra 3748, Hullbreaker,
    # Azakana's Gaze, Reaper's Toll 443090) deliberately do NOT reference
    # this field - they key off target_max_hp / caster_max_hp. Default 1.0
    # is an identity multiply: every pre-lever caller and proc stays
    # byte-identical. Appended at the END per the repo dataclass convention
    # (a mid-class insert breaks positional construction).
    target_current_hp_pct: float = 1.0
    # B1 (1.141.0): the wielder's auto-attack is MELEE (attackrange <
    # dps.MELEE_RANGE_CEILING). Engine-derived in compute_dps from the champion
    # record's attackrange. Consumed by ``_periodic_proc_dps`` /
    # ``_per_attack_proc_damage`` ONLY when ``apply_melee_aa_gate=True`` to skip
    # a ``PeriodicProc.ranged_only`` proc (Runaan's bolts fire on ranged basics
    # only). Default False -> the gate is a no-op and every existing caller is
    # byte-identical. Appended at the END per the repo dataclass convention.
    is_melee: bool = False


# Scaling-damage callable type. Float still works as a constant.
DamageFn = Union[float, Callable[[CallContext], float]]


@dataclass(frozen=True)
class PeriodicProc:
    """A periodic on-hit / on-timer damage proc.

    Either ``every_n_attacks`` (Kraken-style) OR ``every_n_seconds``
    (Stormrazor-style) is set; the other stays at the default zero.
    Both being set is a config error caught at construction.

    ``bonus_damage`` may be a float (constant) or a callable that takes
    a ``CallContext`` and returns a float - used for stat-scaling procs
    where the constant approximation would be too lossy.

    ENGINE 1.26.0 (2026-05-21) added ``stack_ramp_seconds`` - the family
    extension for the stack-accumulation -> discharge schema lift queued
    by BACKLOG (Dead Man's Plate Momentum, iter 16 deferral). Set this
    field > 0 ALONGSIDE ``every_n_attacks > 0`` to model an item passive
    that needs ``stack_ramp_seconds`` to fully accumulate stacks and then
    discharges on the next basic attack. Sustained-DPS effective period
    in ``_periodic_proc_dps``:
    ``max(stack_ramp_seconds, every_n_attacks * attack_period_s)``.
    The ``bonus_damage`` value (or callable) is the FULL-STACK discharge
    magnitude (the engine's sustained model assumes the discharge fires
    at full ramp). Default 0.0 -> no ramp gate (today's behavior).
    Mutually exclusive with ``every_n_seconds`` (the seconds-based path
    has no ramp semantics; ramp is implicit in the period).
    """
    name: str
    bonus_damage: DamageFn
    damage_type: str
    every_n_attacks: int = 0
    every_n_seconds: float = 0.0
    # ENGINE 1.26.0 (2026-05-21): stack-accumulation ramp gate. See class
    # docstring above. Default 0.0 = no ramp (backward-compat). Only
    # meaningful when every_n_attacks > 0 (XOR with every_n_seconds).
    stack_ramp_seconds: float = 0.0
    # DSV1 (1.124.0): marks an ability-triggered AP damage-over-time burn
    # (Liandry's Torment, Blackfire's Baleful Blaze, Demonic's Azakana's
    # Gaze) that belongs in the AP / ability scorer as well as the auto
    # scorer. ``compute_ability_dps`` folds ONLY ability_dot procs (via
    # ``_periodic_proc_dps(ability_dot_only=True)``) so tank Immolate auras
    # (Sunfire), physical spellblades (Iceborn / Trinity Force), and on-cast
    # nukes (Luden's) - all every_n_seconds procs too - do NOT pollute the
    # AP item ranking. compute_dps ignores the flag (counts every proc).
    # Default False = byte-identical for every existing proc.
    ability_dot: bool = False
    # B1 (1.141.0): this proc only applies on a RANGED basic attack (Runaan's
    # Hurricane Wind's Fury - the two extra bolts fire on ranged autos only).
    # The DPS consumers (``_periodic_proc_dps`` / ``_per_attack_proc_damage``)
    # skip a ranged_only proc when ``apply_melee_aa_gate=True`` AND the wielder
    # is melee (``CallContext.is_melee``). Default False -> the proc applies
    # unconditionally (byte-identical to pre-B1 for every existing proc).
    ranged_only: bool = False

    def __post_init__(self) -> None:
        if self.damage_type not in _DAMAGE_TYPES:
            raise ValueError(
                f"PeriodicProc.damage_type must be one of {sorted(_DAMAGE_TYPES)}, "
                f"got {self.damage_type!r}"
            )
        attacks_set = self.every_n_attacks > 0
        seconds_set = self.every_n_seconds > 0
        if attacks_set == seconds_set:
            raise ValueError(
                "PeriodicProc must set exactly one of every_n_attacks "
                "(>0) or every_n_seconds (>0)"
            )
        if self.stack_ramp_seconds < 0:
            raise ValueError(
                f"PeriodicProc.stack_ramp_seconds must be >= 0, got "
                f"{self.stack_ramp_seconds!r}"
            )
        if self.stack_ramp_seconds > 0 and seconds_set:
            raise ValueError(
                "PeriodicProc.stack_ramp_seconds only valid with "
                "every_n_attacks > 0 (the seconds-based path has no "
                "ramp semantics; ramp is implicit in the period)"
            )

    def resolve_damage(self, ctx: CallContext) -> float:
        """Resolve ``bonus_damage`` against the call context.

        Constants pass through; callables evaluate. Engine consumers
        should always go through this method rather than poking at
        ``bonus_damage`` directly so the float / callable distinction
        stays invisible.
        """
        if callable(self.bonus_damage):
            out = float(self.bonus_damage(ctx))
        else:
            out = float(self.bonus_damage)
        # A proc lambda fed a non-finite CallContext field (e.g.
        # target_max_hp=inf from a caller / sweep axis through a
        # %-target-HP proc) would otherwise return inf/nan straight into
        # _periodic_proc_dps -> DpsResult.weighted_dps -> json.dumps
        # (default allow_nan=True) -> a bare Infinity/NaN token that
        # breaks downstream JSON.parse. Drop to 0.0 ("contributes nothing
        # on degenerate input") - finite values pass through byte-identical.
        if not math.isfinite(out):
            return 0.0
        return out


@dataclass(frozen=True)
class ItemShield:
    """A shield contribution to EHP (ENGINE 1.27.0, Phase 1.5).

    Closes the ``ehp.py:21`` Phase-1.5 omission "Shield throughput
    (Sterak's lifeline, Doran's Shield, Bloodthirster) - needs uptime
    modeling". Phase 1.5 ships the four LIFELINE-style shields (single
    trigger per fight, value-additive to the effective-HP pool at top of
    the damage stack): Sterak's Gage 3053, Immortal Shieldbow 6673, Maw
    of Malmortius 3156, Hexdrinker 3155. Bloodthirster's ichor-shield is
    intentionally DEFERRED to Phase 6 (with lifesteal modeling) - it
    requires overheal accrual rather than a single-trigger threshold.

    Magnitude resolves as ``flat + bonus_hp_scaling * bonus_hp +
    bonus_ad_scaling * bonus_ad`` then multiplied by ``ranged_modifier``
    when the wielder is ranged. The ``flat`` value lerps linearly with
    level when ``level_lerp_high_value`` differs from ``flat`` (or
    equivalently when ``level_lerp_low != level_lerp_high``); the lerp
    is between ``level_lerp_low`` (value = ``flat``) and
    ``level_lerp_high`` (value = ``level_lerp_high_value``). Level
    clamps OUTSIDE the lerp window: below ``level_lerp_low`` use
    ``flat``; at/above ``level_lerp_high`` use
    ``level_lerp_high_value``.

    ``damage_type`` controls which EHP component absorbs:
      * ``"any"`` - all 3 components benefit (Sterak, Shieldbow)
      * ``"magical"`` - only magical_ehp benefits (Maw, Hexdrinker)
      * ``"physical"`` - only physical_ehp (no current items)
      * ``"true"`` - only true_ehp (no current items)
    """
    damage_type: str = ANY
    flat: float = 0.0
    bonus_hp_scaling: float = 0.0
    bonus_ad_scaling: float = 0.0
    level_lerp_low: int = 1
    level_lerp_high: int = 1
    level_lerp_high_value: float = 0.0
    ranged_modifier: float = 1.0
    note: str = ""

    def __post_init__(self) -> None:
        if self.damage_type not in _SHIELD_TYPES:
            raise ValueError(
                f"ItemShield.damage_type must be one of "
                f"{sorted(_SHIELD_TYPES)}, got {self.damage_type!r}"
            )
        if self.level_lerp_low < 1 or self.level_lerp_high < 1:
            raise ValueError(
                f"ItemShield level_lerp_low/high must be >= 1, got "
                f"low={self.level_lerp_low}, high={self.level_lerp_high}"
            )
        if self.level_lerp_high < self.level_lerp_low:
            raise ValueError(
                f"ItemShield.level_lerp_high must be >= level_lerp_low, "
                f"got high={self.level_lerp_high} < low={self.level_lerp_low}"
            )
        if self.ranged_modifier < 0:
            raise ValueError(
                f"ItemShield.ranged_modifier must be >= 0, got "
                f"{self.ranged_modifier!r}"
            )

    def resolve_magnitude(
        self,
        level: int,
        bonus_hp: float = 0.0,
        bonus_ad: float = 0.0,
        is_ranged: bool = False,
    ) -> float:
        """Resolve the shield value at the given context.

        ``level`` is clamped to ``[1, 18]`` implicitly by the lerp's
        outside-window logic. Negative result is floored at 0.
        """
        if self.level_lerp_low == self.level_lerp_high:
            level_value = self.flat
        elif level <= self.level_lerp_low:
            level_value = self.flat
        elif level >= self.level_lerp_high:
            level_value = self.level_lerp_high_value
        else:
            span = self.level_lerp_high - self.level_lerp_low
            t = (level - self.level_lerp_low) / span
            level_value = self.flat + (self.level_lerp_high_value - self.flat) * t
        total = (
            level_value
            + self.bonus_hp_scaling * max(0.0, bonus_hp)
            + self.bonus_ad_scaling * max(0.0, bonus_ad)
        )
        if is_ranged and self.ranged_modifier != 1.0:
            total *= self.ranged_modifier
        # max(0.0, nan) floors to 0.0 by CPython evaluation order, but
        # max(0.0, inf) == inf would leak a bare Infinity token through
        # ehp.compute_ehp -> json.dumps. Drop any non-finite magnitude.
        if not math.isfinite(total):
            return 0.0
        return max(0.0, float(total))


@dataclass(frozen=True)
class ItemHeal:
    """An item-passive heal contribution to EHP throughput (ENGINE 1.28.0,
    Phase 6).

    Closes the ``ehp.py:23`` Phase-6 deliberate omission "Healing
    throughput (lifesteal, Spirit Visage amp) - fits Phase 6". Phase 6
    ships the item-passive heal sources that fit a one-trigger-per-fight
    model:
      * Sundered Sky 6610 Lightshield Strike (100% base AD melee /
        50% base AD ranged per empowered AA, 10s CD per target -> 1
        trigger per typical fight)

    ENGINE 1.29.0 (Phase 6.5, 2026-05-21): ``missing_hp_pct`` extends
    the dataclass to support item heal pieces that scale with the
    wielder's missing HP. Sundered Sky's heal carries a 6% missing-HP
    additive on top of the base AD scaling per Meraki 16.10.1. The
    consumer (``ehp.py``) supplies the missing_hp value derived from
    the mid-fight HP-share convention (see
    ``_MISSING_HP_SHARE_FOR_HEALS``); this dataclass stays
    convention-agnostic - it just composes the additive piece into the
    pre-ranged-modifier total. The EHP scorer's normal full-HP
    steady-state convention sits at the consumer site, not here.

    Lifesteal-derived heals are NOT modeled via ItemHeal - they're
    stat-driven (``stats["lifesteal"] * stats["ad"] * stats["as"] *
    _FIGHT_WINDOW_S``) and computed inline in ``compute_ehp``.

    ENGINE 1.57.0 (2026-05-25): ``takedown_gated`` extends the dataclass
    to support item heal pieces that fire conditional on a champion
    takedown (kill or assist credit within a short window). Death's
    Dance Defy is the first consumer: 75% bonus AD over 2s heal on
    takedown. When ``takedown_gated=True``, the consumer (``ehp.py``)
    multiplies the resolved per-trigger magnitude by the operator-
    tunable ``_TAKEDOWN_RATE_PER_FIGHT`` constant (default 0.5 ->
    "carry nets one takedown every other fight" / "support gets assist
    credit roughly half the time"). The dataclass stays convention-
    agnostic: the gating multiplier lands at the consumer site, not
    here, mirroring the ``missing_hp_pct`` precedent. Bloodthirster
    ichor-shield ships as an ``ItemShield`` (Phase 1.5 pipeline) using
    the full-cap steady-state assumption (overheal builds the shield
    between fights at base/walking).

    Magnitude resolves as ``flat + base_ad_scaling * base_ad +
    bonus_hp_scaling * bonus_hp + bonus_ad_scaling * bonus_ad +
    missing_hp_pct * missing_hp`` then multiplied by ``ranged_modifier``
    when the wielder is ranged. NO level lerp (Phase 6 heal items in
    scope are all stat-scaled directly; the level-scaling magnitudes
    today belong to the shield pipeline).

    The fight-window assumption (6.0s default) gates lifesteal
    accumulation only; item-passive heals use the one-trigger-per-fight
    convention and are NOT scaled by the fight window. ``takedown_gated``
    items get an additional consumer-side multiplier on top of the
    one-trigger model (resolved magnitude * ``_TAKEDOWN_RATE_PER_FIGHT``).
    """
    flat: float = 0.0
    base_ad_scaling: float = 0.0
    bonus_hp_scaling: float = 0.0
    bonus_ad_scaling: float = 0.0
    missing_hp_pct: float = 0.0
    ranged_modifier: float = 1.0
    # ENGINE 1.57.0 (2026-05-25): takedown-gated trigger flag. When True,
    # the consumer (``ehp._collect_heals``) multiplies the resolved
    # per-trigger magnitude by ``_TAKEDOWN_RATE_PER_FIGHT`` (default 0.5)
    # to approximate the fraction of fights that yield a takedown
    # (kill / assist within 3s of damage). Default False preserves
    # ENGINE 1.29.0 byte-identical resolve_magnitude behavior for
    # Sundered Sky and any other always-on heal entry. Death's Dance
    # 6333 / Arena 226333 Defy is the first consumer.
    takedown_gated: bool = False
    note: str = ""

    def __post_init__(self) -> None:
        if self.ranged_modifier < 0:
            raise ValueError(
                f"ItemHeal.ranged_modifier must be >= 0, got "
                f"{self.ranged_modifier!r}"
            )
        if self.missing_hp_pct < 0:
            raise ValueError(
                f"ItemHeal.missing_hp_pct must be >= 0, got "
                f"{self.missing_hp_pct!r}"
            )

    def resolve_magnitude(
        self,
        base_ad: float = 0.0,
        bonus_hp: float = 0.0,
        bonus_ad: float = 0.0,
        missing_hp: float = 0.0,
        is_ranged: bool = False,
    ) -> float:
        """Resolve the per-trigger heal value at the given context.

        Negative result is floored at 0. Stat inputs are clamped at 0 -
        a malformed champion record cannot drive heal magnitudes below
        zero via negative bonus AD or HP. ``missing_hp`` is the absolute
        missing-HP value in HP units (NOT a share); the dataclass is
        consumer-convention-agnostic.
        """
        total = (
            self.flat
            + self.base_ad_scaling * max(0.0, base_ad)
            + self.bonus_hp_scaling * max(0.0, bonus_hp)
            + self.bonus_ad_scaling * max(0.0, bonus_ad)
            + self.missing_hp_pct * max(0.0, missing_hp)
        )
        if is_ranged and self.ranged_modifier != 1.0:
            total *= self.ranged_modifier
        # max(0.0, nan) floors to 0.0 by CPython evaluation order, but
        # max(0.0, inf) == inf would leak a bare Infinity token through
        # ehp.compute_ehp -> json.dumps. Drop any non-finite magnitude.
        if not math.isfinite(total):
            return 0.0
        return max(0.0, float(total))


@dataclass(frozen=True)
class ItemEffect:
    item_id: str
    name: str
    crit_damage_bonus: float = 0.0   # added to dps.DEFAULT_CRIT_BONUS
    # Phase 4 batch 8 (2026-05-04): tuple instead of single Optional -
    # an item can carry multiple periodic procs (Titanic Hydra has both
    # a primary on-hit AND a cleave-to-others piece). ``()`` means "no
    # periodic procs"; single-proc entries write ``(PeriodicProc(...),)``.
    periodics: tuple[PeriodicProc, ...] = ()
    # Physical-damage modifiers - applied to ``target_armor`` in dps.py
    # before the armor curve. Reduction (Black Cleaver) lands first,
    # then % pen (LDR / MR), then flat pen (lethality items).
    armor_reduction_pct: float = 0.0   # Black Cleaver: 0.30 sustained
    armor_pen_pct: float = 0.0         # LDR: 0.35; MR: 0.30
    armor_pen_flat: float = 0.0        # lethality flat (rare standalone)
    # Magic-damage modifiers (Phase 4 batch 4, 2026-05-04) - applied to
    # ``target_mr`` symmetrically. Phase 4 batch 39 (2026-05-04) adds the
    # MR-reduction layer (magic-side Black Cleaver analogue): reduction
    # first, then % pen, then flat pen - same layering order as armor side.
    mr_reduction_pct: float = 0.0      # Bloodletter's Curse: 0.30 (4x7.5%)
    magic_pen_pct: float = 0.0         # Void Staff: 0.40; Cryptbloom: 0.30
    magic_pen_flat: float = 0.0        # Sorc's Shoes: 12; Shadowflame: 15
    # Phase 4 batch 14 (2026-05-04): combat-state damage amplifier.
    # League stacks damage amps multiplicatively via the buff system
    # (two 8% amps = 1.08 * 1.08 = 1.1664x, not 1.16x), so the engine
    # applies them as a product-of-(1+amp) factor, not a sum. Sustained-
    # DPS approximation pins the full-ramp value (e.g. Riftmaker's 8%
    # after 4s in combat - same shape as Black Cleaver's "30% at 5
    # stacks sustained"). Applied to both base AA and proc damage in
    # ``dps._rotation_attack_dps``: in-game amps don't discriminate
    # physical vs magical, just "damage to champions while in combat".
    damage_amp_pct: float = 0.0
    # Phase 4 batch 15 (2026-05-04): stat cross-derivation - caster bonus
    # HP converts into AP at this rate (Riftmaker's Void Infusion: 0.02
    # per bonus HP). Always-on passive, no ramp gate. Applied dps-side
    # via CallContext.ap so AP-scaling procs (Lich Bane spellblade,
    # Nashor's Tooth on-hit) see the converted total. Engine-internal:
    # the resolved stats output from /stats reflects raw stat blocks
    # only; the cross-derivation is computed at DPS time and surfaced
    # in DpsResult.notes when non-zero.
    ap_per_bonus_hp_pct: float = 0.0
    # Phase 4 batch 19 (2026-05-04): target-conditional damage amp -
    # scales linearly from 0 to ``target_bonus_hp_amp_max_pct`` as the
    # caller-supplied ``target_bonus_hp`` rises from 0 to
    # ``target_bonus_hp_amp_cap``, then caps. LDR Giant Slayer:
    # max_pct=0.15, cap=1500 (DDragon: "up to 15% bonus damage,
    # maximum reached at 1500 bonus Health"). Stacks multiplicatively
    # with damage_amp_pct (League's buff system pin from batch 14).
    # Both fields default 0.0 - items without target-conditional amps
    # contribute nothing to the multiplier. Caller leaves
    # CallContext.target_bonus_hp at 0 -> amp resolves to 0 (back-compat).
    target_bonus_hp_amp_max_pct: float = 0.0
    target_bonus_hp_amp_cap: float = 0.0
    # Phase 4 batch 20 (2026-05-04): item-passive bonus AD as a percentage of
    # the wielder's leveled base AD. Sterak's Gage "The Claws that Catch"
    # grants "bonus attack damage equal to 45% base AD" - a stat layer, not
    # a proc. Engine resolves this in ``build_champion`` by walking item ids
    # after stat aggregation, summing ``effect.bonus_ad_pct_base_ad *
    # raw_base["ad"]`` per item, and folding the total into ``ad_flat``
    # before ``_combine_items`` runs. Default 0.0 -> no contribution.
    # NOT a unique passive in current League (multiple Sterak's-shape items
    # could in principle stack), but currently only 3053 carries this - if
    # a second item appears, ``unique_passive_key`` is the right gate.
    bonus_ad_pct_base_ad: float = 0.0
    # Phase 4 batch 27 (2026-05-04): item-passive bonus AD as a percentage of
    # the wielder's total max mana. Manamune / Muramana's "Awe" grants
    # bonus AD equal to 2% of maximum mana - a stat layer, not a proc.
    # Same wiring shape as ``bonus_ad_pct_base_ad`` (batch 20): engine
    # resolves this in ``build_champion`` AFTER ``_scale_champion_base``
    # (which gives leveled base mana) and AFTER ``aggregate_item_stats``
    # (which sums item flat mana), but BEFORE ``_combine_items`` folds
    # totals into the final stat block. Self-referential check: Awe is
    # mana -> AD, one-way; the items' own mana is already in item_totals
    # at the point of the walk, so total_max_mp reflects the build's
    # finished mana pool. Default 0.0 -> no contribution.
    # NOT a unique passive at the effect-layer in the current engine
    # (multiple Awe-shape items could in principle stack); in real
    # League Manamune transforms INTO Muramana so you can't own both.
    # Build-legality is ranker-owned per the s81/s82 pattern.
    bonus_ad_pct_max_mp: float = 0.0
    # Phase 4 batch 28 (2026-05-04): item-passive bonus AP as a percentage of
    # the wielder's BONUS mana (item-contributed only - NOT champion base).
    # Archangel's Staff (3003) "Awe" grants 1% bonus mana -> AP; Seraph's
    # Embrace (3040) "Awe" grants 2%. Note the divergence from
    # ``bonus_ad_pct_max_mp`` (Manamune/Muramana) - Manamune's Awe is keyed
    # off MAX mana (champion base + items), Archangel/Seraph's Awe is
    # keyed off BONUS mana (items only). Different math even though both
    # carry the "Awe" name; pinning the asymmetry here so the engine
    # walks the right value. Walked in ``build_champion`` AFTER
    # ``aggregate_item_stats`` produces ``item_totals["mp_flat"]`` (which
    # IS the bonus mana sum). Walks ``item_totals["ap_flat"]`` rather
    # than ad_flat. Default 0.0 -> no contribution. NOT a unique passive
    # at the effect-layer (Archangel transforms INTO Seraph's in real
    # League; build-legality is ranker-owned per the s81 pattern).
    bonus_ap_pct_bonus_mp: float = 0.0
    # Phase 4 batch 30 (2026-05-04) introduced this field; ENGINE 1.10.0
    # (2026-05-19, audit-lethality) corrects the conversion to the
    # post-V14.1 (Riot 2024-01) rule: lethality grants flat armor pen
    # 1:1 at EVERY caster level. The historical pre-V14.1 scaling
    # ``lethality * (0.6 + 0.4 * level / 18)`` was REMOVED in V14.1 and
    # is OBSOLETE - do NOT re-introduce it (it under-applied lethality
    # at every level except 18, max 37.78 pp at L1). Pipeline-position
    # is the same as ``armor_pen_flat`` (last in line: reduction ->
    # % pen -> flat pen). ``effective_target_armor`` accepts an
    # optional ``level`` parameter; on the modern engine it is only
    # the "lethality contributes nothing" sentinel for non-DPS
    # callers (level=None). Pre-batch-30 callers that omit level get
    # the existing armor_pen_flat-only behavior. Default 0.0 -> no
    # contribution. NOT a unique passive at the effect-layer (multiple
    # lethality items stack their flat pen additively in current League
    # - same call as the % pen layer).
    lethality: float = 0.0
    # Phase 4 batch 26 (2026-05-04): item-effect-contributed crit chance.
    # Two flavors composing additively into a single per-build sum that
    # adds to ``stats["crit"]`` at compute_dps construction time:
    # - ``crit_chance_bonus_flat`` - a build-time constant (Yun Tal
    #   Wildarrows "Practice Makes Lethal" pinned at full 25% stacks; same
    #   pattern as a Sundered Sky lambda-as-constant).
    # - ``crit_chance_bonus_max_pct`` + ``crit_chance_bonus_per_bonus_hp_cap``
    #   - linear ramp with caster_bonus_hp, max at cap (Atma's Reckoning
    #   "Big Hands" 0-30% over 0-3000 bonus HP). Same shape as
    #   target_bonus_hp_amp from batch 19, just on the caster side.
    # The summed contribution is added to the build's stats.crit and
    # clamped at 1.0 in compute_dps; CallContext.crit_chance and the
    # rotation auto-attack crit calc both see the boosted total. Display
    # values (avg_attack_dmg / raw_attack_dps) reflect the same boosted
    # crit. /stats endpoint output is unchanged - same separation as
    # batch 15's ap_per_bonus_hp_pct (cross-derivation surfaces only via
    # /dps + DpsResult.notes).
    crit_chance_bonus_flat: float = 0.0
    crit_chance_bonus_max_pct: float = 0.0
    crit_chance_bonus_per_bonus_hp_cap: float = 0.0
    # Phase 4 batch 32 (2026-05-04): multiplicative AP amplifier.
    # Rabadon's Deathcap "Magical Opus" multiplies the wielder's total AP
    # by (1 + ap_amp_pct). Applied at DPS time - ``compute_dps`` multiplies
    # the effective AP used by proc scaling and pen formulas by
    # ``total_ap_amp_multiplier(effects)`` AFTER other AP cross-derivation
    # (HP->AP, mana->AP). Raw stat block unchanged - same separation as
    # ``ap_per_bonus_hp_pct`` (batch 15). Stacks multiplicatively per
    # League's buff-system semantics; current patch has one item
    # (Rabadon's 30%). Default 0.0 -> no contribution.
    ap_amp_pct: float = 0.0
    # Phase 4 batch 32 (2026-05-04): bonus AD as a percentage of bonus HP.
    # Overlord's Bloodmail "Tyranny" grants bonus AD = 2.5% bonus HP.
    # Bonus HP = HP from items only (not base HP from leveling). Engine
    # resolves this in ``build_champion`` using ``item_totals["hp_flat"]``
    # as the bonus HP proxy - correct because champion leveling contributes
    # base HP, not bonus HP. Walked AFTER ``aggregate_item_stats`` so
    # items' own HP (Overlord's 550) is included. One-way, no feedback.
    # Default 0.0 -> no contribution.
    bonus_ad_pct_bonus_hp: float = 0.0
    # Phase 4 batch 34 (2026-05-04): target-debuff magic damage amplifier.
    # Abyssal Mask's "Unmake" aura causes nearby enemies to take X% more
    # magic damage from ALL sources. Modeled as a multiplier on magic-type
    # proc DPS only - does NOT affect physical AA damage (unlike the
    # general ``damage_amp_pct`` field which amplifies everything).
    # ``total_magic_amp_multiplier`` returns the product of
    # (1 + magic_amp_pct) across all effects; applied inside
    # ``_periodic_proc_dps`` per-proc when damage_type != PHYSICAL.
    # Default 0.0 -> no contribution.
    magic_amp_pct: float = 0.0
    # Phase 4 batch 38 (2026-05-04): Giant Slayer target max HP advantage amp.
    # Distinct from ``target_bonus_hp_amp_max_pct`` (LDR - keyed off target
    # BONUS HP) because Perplexity's Giant Slayer is keyed off the DIFFERENCE
    # between target MAX HP and caster MAX HP (i.e. who's tankier). Formula:
    #   amp = min(giant_slayer_max_pct,
    #             max(0, (target_max_hp - caster_max_hp) / 100
    #                    * giant_slayer_pct_per_100hp))
    # Returns 0 when caster out-HPs the target. Stacks multiplicatively with
    # other amp layers per League's buff-system semantics (batch 14 doctrine).
    # ``total_giant_slayer_multiplier`` computes the factor and wires it into
    # ``compute_dps`` AFTER ``caster_max_hp`` is derived from the build.
    giant_slayer_pct_per_100hp: float = 0.0   # Perplexity: 0.006 (0.6% per 100 HP)
    giant_slayer_max_pct: float = 0.0          # Perplexity: 0.15 (15% cap at 2500 HP diff)
    # Phase 4 batch 50 (2026-05-04): flat armor / MR shred - applied to the
    # target's raw stat BEFORE % reduction, % pen, and flat pen. Mirrors
    # League's pipeline order: flat shred -> % shred (BC) -> % pen (LDR) ->
    # flat pen (lethality). Flesheater "Hack the Meat" reduces target armor
    # AND MR by 3 per damage application, stacking 10x -> 30 flat at full
    # stacks. Sustained-DPS approximation pins full-stack value (same
    # doctrine as Black Cleaver's armor_reduction_pct at full stacks).
    # Distinct from armor_reduction_pct: flat shred can push armor below
    # zero (uncommon in practice but the pipeline allows it for consistency
    # with very low-armor targets). Result is clamped at 0 by
    # effective_target_armor; negative armor -> factor > 1 is NOT modeled
    # (League makes armor-strip DPS a hard floor, not a bonus multiplier).
    armor_reduction_flat: float = 0.0   # Flesheater Hack the Meat: 30 at full stacks
    mr_reduction_flat: float = 0.0      # Flesheater Hack the Meat: 30 at full stacks
    # Phase 4 batch 56 (2026-05-04): caster max-HP-scaled multiplicative AP amplifier.
    # Demonic Embrace (444637 Arena) "Sinister Pact": +1.5% AP per 100 current HP,
    # capped at 45% (reaches cap at 3000 HP). Modeled using caster max HP as a
    # sustained-combat approximation (same convention as BotRK current-HP procs).
    # Applied as a multiplicative amp AFTER ap_per_bonus_hp_pct and ap_amp_pct:
    # Rabadon's boosts everything first, then this HP-scaling amp stacks on top.
    # Default 0.0 -> no contribution.
    ap_amp_pct_per_100_caster_hp: float = 0.0     # 0.015 for 444637 (1.5% per 100 HP)
    ap_amp_pct_per_100_caster_hp_cap: float = 0.0 # 0.45 for 444637 (45% cap at 3000 HP)
    # Phase 4 batch 54 (2026-05-04): kill-stacking AP not captured in DDragon.
    # Mejai's Soulstealer "Glory" grants 5 AP per stack (max 25 stacks = 125 AP);
    # DDragon's FlatMagicDamageMod only carries the base 20 AP. Engine pins at
    # full stacks (same sustained-peak convention as Black Cleaver full-stack
    # armor reduction). Added to effective AP before CallContext - AP-scaling
    # procs (Lich Bane, Nashor's) see the stacked total, and Rabadon's
    # ap_amp multiplies it. Default 0.0 -> no contribution.
    bonus_ap_stacked: float = 0.0
    # Phase 4 batch 54 (2026-05-04): conditional bonus AS not modeled as a stat.
    # Yun Tal Wildarrows "Flurry": on-attacking an enemy champion, gain 30%
    # bonus AS for 6s (30s CD; attacks reduce CD by 1s, crits by 2s).
    # Sustained uptime at ~1.3 attacks/s with 25% crit: cycle = 6s active +
    # 16.2s cooldown (20.25s remaining after active, 1.25s/s reduction rate
    # from attack CD drain) = 22.2s. Uptime = 6/22.2 ~ 27%.
    # Effective sustained AS bonus = 0.30 x 0.27 ~ 0.08. Added to
    # stats_for_rotation["as"] in compute_dps alongside crit_from_effects.
    # Default 0.0 -> no contribution.
    bonus_as_conditional: float = 0.0
    defensive_only: bool = False     # documents "no DPS effect" entries
    note: str = ""                   # one-line summary surfaced in DpsResult.notes
    # Phase 4 batch 10 (2026-05-04): unique-passive de-duplication.
    # Items that share the same in-game unique passive (Sunfire's Immolate
    # + Hollow Radiance's Immolate, hypothetically multiple Spellblades)
    # don't stack their procs in League - Riot enforces "Unique Passive"
    # explicitly. Engine respects this when ``collect_effects`` sees the
    # same non-empty key twice - first-seen wins, later items contribute
    # only their stat block (which is item-side, not effect-side).
    # Default ``""`` means "no dedup" - every existing entry passes through
    # unchanged. Add a key only when stacking the same effect across
    # multiple items would over-count.
    unique_passive_key: str = ""
    # ENGINE 1.27.0 (2026-05-21): Phase 1.5 shield throughput (closes the
    # ehp.py:21 deliberate omission). Single ``ItemShield`` per item;
    # ``None`` = no shield contribution (today's behavior for every item
    # except the 4 wired lifelines). The EHP scorer reads this field via
    # ``ehp.compute_ehp -> _collect_shields`` and folds it into
    # ``physical_ehp`` / ``magical_ehp`` / ``true_ehp`` at the top of the
    # damage stack. Lifeline-shield items share
    # ``unique_passive_key="lifeline_shield"`` so build planner picks at
    # most one (the rank.py dead-unique filter; see EhpRankedItem docs).
    shield: "ItemShield | None" = None
    # ENGINE 1.28.0 (2026-05-21): Phase 6 healing throughput - item-passive
    # heal contribution (closes the ehp.py:23 deliberate omission). Single
    # ``ItemHeal`` per item; ``None`` = no item-passive heal contribution
    # (today's behavior for every item except Sundered Sky in the initial
    # Phase 6 wire). The EHP scorer reads this field via
    # ``ehp.compute_ehp -> _collect_heals`` and folds the total into the
    # heal pool at the top of the damage stack (same place as shields,
    # post-amp via ``heal_amp_pct``). Death's Dance Defy heal is DEFERRED
    # to Phase 6.5 (takedown-rate uncertain); Bloodthirster's Ichorshield
    # ships in the ``shield`` field (Phase 1.5 pipeline with full-cap
    # steady-state assumption); lifesteal-derived heals are stat-driven
    # and computed inline in ``compute_ehp``, NOT via ItemHeal.
    heal: "ItemHeal | None" = None
    # ENGINE 1.28.0 (2026-05-21): Phase 6 self-heal/regen amplifier.
    # Spirit Visage 3065 "Boundless Vitality" carries 0.25 (+25% to all
    # self-heal/regen). Applied multiplicatively to the heal pool in
    # ``compute_ehp`` via ``_total_heal_amp(item_ids)`` -> product of
    # (1 + heal_amp_pct). NOT applied to the Phase 1.5 shield pipeline
    # in this engine - Riot's tooltip "increases all heal AND shielding"
    # would apply to Sterak/Shieldbow/Maw/Hexdrinker/BT shields too, but
    # amping Phase 1.5 magnitudes retroactively is deferred to Phase 6.5
    # (the deliberate scope boundary: Phase 6 ships heal-pipeline amp
    # only, shield-pipeline amp comes later when a real player build
    # pairs Spirit Visage with a lifeline item). Default 0.0 -> no
    # contribution.
    heal_amp_pct: float = 0.0
    # DSV2 (1.125.0): takedown / kill-state OFFENSE seam (P6-G5 residual 2).
    # The auto / burst scorers had no way to value the on-takedown item
    # passives, so three lethality-adjacent items were under-ranked. These
    # fields are read ONLY when the consumer (compute_dps / compute_burst_damage)
    # is called with ``assume_takedown=True`` - the kill-state assumption.
    # Default 0.0 keeps every existing item + caller byte-identical (the seam
    # is inert until both the data field AND the flag are set). Appended at the
    # END per the repo dataclass convention (a mid-class insert breaks positional
    # construction + every existing test).
    #
    # Hubris 6697 Eminence: a champion takedown grants bonus AD = base +
    # per_stack * stacks, lasting 90s (Meraki 16.12.1: "15 (+2 per stack)").
    # The consumer assumes ``dps._ASSUMED_TAKEDOWN_STACKS`` (= 1) stack worth
    # when the seam is ON -> 15 + 2*1 = 17 bonus AD folded into the wielder's
    # bonus AD for both the AA rotation and the ability scaling.
    takedown_bonus_ad_base: float = 0.0
    takedown_bonus_ad_per_stack: float = 0.0
    # The Collector 6676 Death: post-mitigation damage that would leave a
    # champion below this fraction of their MAXIMUM health executes them
    # (Meraki 16.12.1: "below 5% of their maximum health"). On the offense
    # axis the burst scorer credits this as a kill-state finisher of
    # ``execute_max_hp_pct * target_max_hp`` TRUE damage (the execute's worth
    # in its trigger window) when ``assume_takedown`` is set and a target max
    # HP is supplied. compute_dps deliberately does NOT credit it - a one-shot
    # execute is not sustained DPS. Death's Dance carries NEITHER field: its
    # takedown payoff is the Defy HEAL, already valued on the survivability
    # axis via ItemHeal.takedown_gated (ENGINE 1.57.0) - crediting it offense
    # here would double-count phantom damage.
    execute_max_hp_pct: float = 0.0
    # DSV4 (1.127.0): Spear of Shojin 3161 Focused Will - a stacking
    # ability/passive damage amp (Meraki 16.12.1: "3% per stack ... max 4
    # stacks" = 12%). NOT an auto-attack amp (the generic ``damage_amp_pct``
    # stays unused on Shojin since it would amp AAs too). Valued only on the
    # ABILITY damage paths (``compute_ability_dps`` spell sum + burst
    # ``ability_total``) when the ``assume_ability_amp`` seam is ON; the consumer
    # assumes ``dps._ASSUMED_ABILITY_AMP_STACKS`` (= 4, a developed fight at max
    # stacks). Default 0.0 / 0 keeps every existing item + caller byte-identical;
    # appended at the END per the dataclass convention.
    ability_damage_amp_per_stack: float = 0.0
    ability_damage_amp_max_stacks: int = 0
    # DSV6 (1.152.0): magic on-cast burst valuation seam. The per-cast burst
    # combo loop (compute_burst_damage) sums only ability casts + AA hits, so
    # item on-cast magic procs (Luden's Echo, Stormsurge Squall, Malignance
    # Hatefog) were never credited in a burst window - AP/magic builds scored
    # too low on the offense-burst axis. These fields carry the single-proc
    # burst-window magnitude: magic damage = ``magic_burst_base +
    # magic_burst_ap_ratio * caster_ap``, MR-mitigated by the consumer. Read
    # ONLY when the consumer is called with ``assume_magic_burst=True``; default
    # 0.0 keeps every existing item + caller byte-identical (the seam is inert
    # until both the data field AND the flag are set). Read ONLY by the BURST
    # scorer (compute_burst_damage): the same proc is modeled as a PeriodicProc
    # for the sustained-DPS scorer (compute_dps values it at its periodic rate),
    # so there is no double-count - the one-shot magnitude lives only in the
    # burst window. compute_ability_dps (single ability rotation) intentionally
    # leaves this one-shot magnitude out of its per-second metric. Appended at
    # the END per the dataclass convention (a mid-class insert breaks positional
    # construction + every existing test).
    magic_burst_base: float = 0.0
    magic_burst_ap_ratio: float = 0.0
    # R70 (2026-07-03): Hollow Radiance "Desolate" champion-takedown eruption
    # on the DSV2 takedown / kill-state seam. Meraki 16.13.1 item 6664:
    # "Scoring a takedown against an enemy champion within 3 seconds of
    # damaging them causes a larger eruption that deals [hollow_ibase*4 = 60]
    # (+ [hollow_ihp*4 = 4]% bonus health) magic damage ... within 500 units"
    # (= 400% of Immolate, whose base is 15 + 1% bonus HP). These fields
    # carry that one-trigger eruption magnitude: magic damage =
    # ``takedown_eruption_base + takedown_eruption_bonus_hp_ratio *
    # caster_bonus_hp``, MR-mitigated by the consumer. Read ONLY when the
    # consumer runs with ``assume_takedown=True`` - default 0.0 keeps every
    # existing item + caller byte-identical (the seam is inert until both the
    # data field AND the flag are set). Read ONLY by the BURST scorer
    # (compute_burst_damage) per the R59 doctrine: a one-trigger takedown
    # payoff does NOT map to a sustained-DPS rate, so compute_dps
    # deliberately does not credit it. No double-count with the Immolate
    # PeriodicProc: that models HR's sustained aura tick; the eruption is a
    # separate on-takedown event valued once in the burst window. The
    # smaller 200% NON-champion eruption (minion/monster kill) stays
    # unmodeled - farm math, not fight math. Appended at the END per the
    # dataclass convention (a mid-class insert breaks positional
    # construction + every existing test).
    takedown_eruption_base: float = 0.0
    takedown_eruption_bonus_hp_ratio: float = 0.0
    # DSV8 (1.178.0): physical item-active burst valuation seam - the PHYSICAL
    # analogue of the DSV6 magic-burst seam above. The per-cast burst combo
    # loop (compute_burst_damage) sums only ability casts + AA hits, so an
    # item ACTIVE that leads with physical damage (Goredrinker 226630
    # Thirsting Slash: "175% base AD physical damage" in a 450 radius, Meraki
    # 16.13.1) was never credited in a burst window. These fields carry the
    # single-cast burst-window magnitude: physical damage =
    # ``physical_burst_base + physical_burst_base_ad_ratio * caster BASE AD``
    # (BASE AD, not total - Thirsting Slash scales off base AD only),
    # armor-mitigated by the consumer. Read ONLY when the consumer is called
    # with ``assume_physical_burst=True``; default 0.0 keeps every existing
    # item + caller byte-identical (the seam is inert until both the data
    # field AND the flag are set). Read ONLY by the BURST scorer
    # (compute_burst_damage): unlike the DSV6 procs there is no PeriodicProc
    # for these long-CD actives, so compute_dps deliberately sees nothing -
    # the one-shot magnitude lives only in the burst window (no
    # double-count). compute_ability_dps accepts the flag as a
    # documented-inert kwarg for API symmetry only. Caster-state only (no
    # target-state conditional - the s232 closure holds). The Goredrinker
    # heal side (20% AD + 8% missing HP per champion hit) stays UNMODELED.
    # Appended at the END per the dataclass convention (a mid-class insert
    # breaks positional construction + every existing test).
    physical_burst_base: float = 0.0
    physical_burst_base_ad_ratio: float = 0.0
    # DSV9 (1.179.0): anti-shield (Shield Reaver) valuation seam. Serpent's
    # Fang's Shield Reaver (6695 / Arena 226695, Meraki 16.13.1) inflicts a
    # 3-second venom that, on first affliction, reduces all of the target's
    # ACTIVE shields by {{rd|50%|35%}} - melee 50% / ranged 35%; these two
    # fields carry the rd arms and the CASTER's melee/ranged split picks
    # which pct applies. The consumer (compute_burst_damage) credits ONE
    # active-shield cut event in the burst window under
    # ``assume_shielded_target=True`` when a ``target_max_hp`` is supplied
    # (assumed pool = _ASSUMED_TARGET_SHIELD_PCT_OF_MAX_HP x target max HP);
    # the sustained "shields gained within the duration" reduction stays
    # UNMODELED (utility over time, not burst math). Shield HP absorbs
    # POST-mitigation damage, so removing X shield HP is worth X
    # post-mitigation-equivalent damage - therefore NO armor/MR routing, NO
    # mode_mult, NO amp layer (stricter than the DSV8 seam above: a shield
    # cut is not damage dealt at all). Default 0.0 keeps every existing
    # item + caller byte-identical (the seam is inert until both the data
    # field AND the flag are set). Read ONLY by compute_burst_damage: no
    # PeriodicProc, so compute_dps sees nothing (no double-count);
    # compute_ability_dps accepts the flag as a documented-inert kwarg for
    # API symmetry only. Appended at the END per the dataclass convention
    # (a mid-class insert breaks positional construction + every existing
    # test).
    shield_cut_melee_pct: float = 0.0
    shield_cut_ranged_pct: float = 0.0
    # R77 (1.180.0): item-keyed incoming CRIT-DAMAGE REDUCTION (defensive EHP).
    # Randuin's Omen (SR 3143 / Arena 223143) Resilience "30% reduced critical
    # strike damage taken" was a defensive_only NOTE with no structured value,
    # so the EHP scorer gave its signature crit-DR ZERO credit. Crit damage is
    # PHYSICAL: the reduction folds into the physical EHP denominator via
    # ``ehp.item_crit_dr_multiplier`` behind the default-OFF ``assume_item_crit_dr``
    # seam (same layer as the champion percent-DR family, which is champion_id-
    # keyed and cannot see items). The crit-affected SHARE of incoming physical
    # is a conservative operator-tunable midpoint in the consumer (the live feed
    # we lack). Default 0.0 keeps every existing item + caller byte-identical
    # (the field AND the flag must both be set); appended at the END per the
    # dataclass convention (a mid-class insert breaks positional construction).
    crit_damage_reduction: float = 0.0
    # R80 (1.181.0): item-keyed incoming BASIC-ATTACK damage reduction (defensive
    # EHP). Plated Steelcaps (SR 3047 / Arena 223047) "Plating" reduces all
    # incoming basic-attack damage by 10% (Meraki 16.13.1) but was a
    # defensive_only NOTE with no structured value, so the EHP scorer gave its
    # signature anti-AA plating ZERO credit though the item's armor already
    # counted. Basic-attack damage is PHYSICAL: the reduction folds into the
    # physical EHP denominator via ``ehp.item_aa_dr_multiplier`` behind the
    # default-OFF ``assume_item_aa_dr`` seam (same layer + item-keyed lane as
    # R77's ``crit_damage_reduction``, which the champion percent-DR family
    # cannot see). The basic-attack SHARE of incoming physical is a conservative
    # operator-tunable midpoint in the consumer (the live feed we lack). Default
    # 0.0 keeps every existing item + caller byte-identical (the field AND the
    # flag must both be set); appended at the END per the dataclass convention.
    basic_attack_damage_reduction: float = 0.0
