"""Daemon Slayer item-effects schema types + damage-type constants.

Split out of effects.py (s246, behavior-preserving) so the large
static ITEM_EFFECTS data table (now _effects_data.py) and these
schema types are separate import units. Pure types - zero engine
dependency. effects.py re-exports every public name here, so all
existing `from .effects import ...` callers stay unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Union


PHYSICAL = "physical"
MAGICAL = "magical"
TRUE = "true"
_DAMAGE_TYPES = frozenset({PHYSICAL, MAGICAL, TRUE})


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
    # because base HP varies per-target (Aatrox lvl 11 base ≈ 1790, but
    # an enemy Cho'Gath mid-game may have 1500 base HP); the engine
    # can't infer it without naming the target. Procs that key on this
    # field gracefully no-op when the caller leaves it at 0.
    target_bonus_hp: float = 0.0
    # Phase 4 batch 27 (2026-05-04): caster max mana - engine-derived from
    # ``stats["mp"]`` (champion base mp + per-level scaling + item flat mp
    # contributions). Sibling of caster_max_hp from batch 6. Required for
    # Manamune / Muramana's Awe (2% max mana → bonus AD) and Muramana's
    # Shock (1.2% max mana per-attack proc). Default 0.0 means "build has
    # no mana" - manaless champions (energy users like Lee Sin, Akali)
    # and pre-batch-27 callers gracefully no-op any mana-scaling proc.
    caster_max_mp: float = 0.0
    # Phase 4 batch 58 (2026-05-04): caster bonus armor - engine-derived as
    # ``stats["armor"] - base_armor`` (item-contributed armor only). Same
    # base/bonus split pattern as caster_bonus_hp from batch 6. Required for
    # Darksteel Talons' Gash (+ 20% bonus armor ranged) scaling. Default
    # 0.0 → pre-batch-58 builds no-op gracefully.
    caster_bonus_armor: float = 0.0
    # Phase 4 batch 59 (2026-05-04): caster raw lethality - engine-derived
    # as ``sum(e.lethality for e in item_effects)`` (raw, before level-
    # scaling to flat pen). Required for Bastionbreaker Shaped Charge
    # (15 + 0.75 × lethality ranged). Distinct from flat pen: the formula
    # uses the un-scaled lethality value, not the effective flat armor pen.
    # Default 0.0 → builds without lethality no-op gracefully.
    caster_lethality: float = 0.0
    # Phase 4 batch 63 (2026-05-05): per-champion ult cast rate in casts/sec,
    # looked up from ``data/daemon_slayer/ult_cast_rates.json`` (derived from
    # rewind_history.db spell4_casts / game_duration_s). Engine-supplied via
    # ``ult_rates.get_ult_casts_per_sec(champion_name, mode)`` in compute_dps.
    # Required for Malignance Hatefog: the PeriodicProc uses every_n_seconds=1.0
    # and bonus_damage = (180 + 0.15 * ap) * ult_casts_per_sec so the proc
    # rate is champion-aware without changing the PeriodicProc schema. Default
    # 0.0 → Malignance contributes 0 DPS when champion data is absent (safe).
    ult_casts_per_sec: float = 0.0


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
    """
    name: str
    bonus_damage: DamageFn
    damage_type: str
    every_n_attacks: int = 0
    every_n_seconds: float = 0.0

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

    def resolve_damage(self, ctx: CallContext) -> float:
        """Resolve ``bonus_damage`` against the call context.

        Constants pass through; callables evaluate. Engine consumers
        should always go through this method rather than poking at
        ``bonus_damage`` directly so the float / callable distinction
        stays invisible.
        """
        if callable(self.bonus_damage):
            return float(self.bonus_damage(ctx))
        return float(self.bonus_damage)


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
    mr_reduction_pct: float = 0.0      # Bloodletter's Curse: 0.30 (4×7.5%)
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
    # CallContext.target_bonus_hp at 0 → amp resolves to 0 (back-compat).
    target_bonus_hp_amp_max_pct: float = 0.0
    target_bonus_hp_amp_cap: float = 0.0
    # Phase 4 batch 20 (2026-05-04): item-passive bonus AD as a percentage of
    # the wielder's leveled base AD. Sterak's Gage "The Claws that Catch"
    # grants "bonus attack damage equal to 45% base AD" - a stat layer, not
    # a proc. Engine resolves this in ``build_champion`` by walking item ids
    # after stat aggregation, summing ``effect.bonus_ad_pct_base_ad *
    # raw_base["ad"]`` per item, and folding the total into ``ad_flat``
    # before ``_combine_items`` runs. Default 0.0 → no contribution.
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
    # mana → AD, one-way; the items' own mana is already in item_totals
    # at the point of the walk, so total_max_mp reflects the build's
    # finished mana pool. Default 0.0 → no contribution.
    # NOT a unique passive at the effect-layer in the current engine
    # (multiple Awe-shape items could in principle stack); in real
    # League Manamune transforms INTO Muramana so you can't own both.
    # Build-legality is ranker-owned per the s81/s82 pattern.
    bonus_ad_pct_max_mp: float = 0.0
    # Phase 4 batch 28 (2026-05-04): item-passive bonus AP as a percentage of
    # the wielder's BONUS mana (item-contributed only - NOT champion base).
    # Archangel's Staff (3003) "Awe" grants 1% bonus mana → AP; Seraph's
    # Embrace (3040) "Awe" grants 2%. Note the divergence from
    # ``bonus_ad_pct_max_mp`` (Manamune/Muramana) - Manamune's Awe is keyed
    # off MAX mana (champion base + items), Archangel/Seraph's Awe is
    # keyed off BONUS mana (items only). Different math even though both
    # carry the "Awe" name; pinning the asymmetry here so the engine
    # walks the right value. Walked in ``build_champion`` AFTER
    # ``aggregate_item_stats`` produces ``item_totals["mp_flat"]`` (which
    # IS the bonus mana sum). Walks ``item_totals["ap_flat"]`` rather
    # than ad_flat. Default 0.0 → no contribution. NOT a unique passive
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
    # (HP→AP, mana→AP). Raw stat block unchanged - same separation as
    # ``ap_per_bonus_hp_pct`` (batch 15). Stacks multiplicatively per
    # League's buff-system semantics; current patch has one item
    # (Rabadon's 30%). Default 0.0 → no contribution.
    ap_amp_pct: float = 0.0
    # Phase 4 batch 32 (2026-05-04): bonus AD as a percentage of bonus HP.
    # Overlord's Bloodmail "Tyranny" grants bonus AD = 2.5% bonus HP.
    # Bonus HP = HP from items only (not base HP from leveling). Engine
    # resolves this in ``build_champion`` using ``item_totals["hp_flat"]``
    # as the bonus HP proxy - correct because champion leveling contributes
    # base HP, not bonus HP. Walked AFTER ``aggregate_item_stats`` so
    # items' own HP (Overlord's 550) is included. One-way, no feedback.
    # Default 0.0 → no contribution.
    bonus_ad_pct_bonus_hp: float = 0.0
    # Phase 4 batch 34 (2026-05-04): target-debuff magic damage amplifier.
    # Abyssal Mask's "Unmake" aura causes nearby enemies to take X% more
    # magic damage from ALL sources. Modeled as a multiplier on magic-type
    # proc DPS only - does NOT affect physical AA damage (unlike the
    # general ``damage_amp_pct`` field which amplifies everything).
    # ``total_magic_amp_multiplier`` returns the product of
    # (1 + magic_amp_pct) across all effects; applied inside
    # ``_periodic_proc_dps`` per-proc when damage_type != PHYSICAL.
    # Default 0.0 → no contribution.
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
    # League's pipeline order: flat shred → % shred (BC) → % pen (LDR) →
    # flat pen (lethality). Flesheater "Hack the Meat" reduces target armor
    # AND MR by 3 per damage application, stacking 10× → 30 flat at full
    # stacks. Sustained-DPS approximation pins full-stack value (same
    # doctrine as Black Cleaver's armor_reduction_pct at full stacks).
    # Distinct from armor_reduction_pct: flat shred can push armor below
    # zero (uncommon in practice but the pipeline allows it for consistency
    # with very low-armor targets). Result is clamped at 0 by
    # effective_target_armor; negative armor → factor > 1 is NOT modeled
    # (League makes armor-strip DPS a hard floor, not a bonus multiplier).
    armor_reduction_flat: float = 0.0   # Flesheater Hack the Meat: 30 at full stacks
    mr_reduction_flat: float = 0.0      # Flesheater Hack the Meat: 30 at full stacks
    # Phase 4 batch 56 (2026-05-04): caster max-HP-scaled multiplicative AP amplifier.
    # Demonic Embrace (444637 Arena) "Sinister Pact": +1.5% AP per 100 current HP,
    # capped at 45% (reaches cap at 3000 HP). Modeled using caster max HP as a
    # sustained-combat approximation (same convention as BotRK current-HP procs).
    # Applied as a multiplicative amp AFTER ap_per_bonus_hp_pct and ap_amp_pct:
    # Rabadon's boosts everything first, then this HP-scaling amp stacks on top.
    # Default 0.0 → no contribution.
    ap_amp_pct_per_100_caster_hp: float = 0.0     # 0.015 for 444637 (1.5% per 100 HP)
    ap_amp_pct_per_100_caster_hp_cap: float = 0.0 # 0.45 for 444637 (45% cap at 3000 HP)
    # Phase 4 batch 54 (2026-05-04): kill-stacking AP not captured in DDragon.
    # Mejai's Soulstealer "Glory" grants 5 AP per stack (max 25 stacks = 125 AP);
    # DDragon's FlatMagicDamageMod only carries the base 20 AP. Engine pins at
    # full stacks (same sustained-peak convention as Black Cleaver full-stack
    # armor reduction). Added to effective AP before CallContext - AP-scaling
    # procs (Lich Bane, Nashor's) see the stacked total, and Rabadon's
    # ap_amp multiplies it. Default 0.0 → no contribution.
    bonus_ap_stacked: float = 0.0
    # Phase 4 batch 54 (2026-05-04): conditional bonus AS not modeled as a stat.
    # Yun Tal Wildarrows "Flurry": on-attacking an enemy champion, gain 30%
    # bonus AS for 6s (30s CD; attacks reduce CD by 1s, crits by 2s).
    # Sustained uptime at ~1.3 attacks/s with 25% crit: cycle = 6s active +
    # 16.2s cooldown (20.25s remaining after active, 1.25s/s reduction rate
    # from attack CD drain) = 22.2s. Uptime = 6/22.2 ≈ 27%.
    # Effective sustained AS bonus = 0.30 × 0.27 ≈ 0.08. Added to
    # stats_for_rotation["as"] in compute_dps alongside crit_from_effects.
    # Default 0.0 → no contribution.
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
