"""Phase 4 — per-item conditional effects (thin slice + first expansion).

DDragon item ``stats`` blocks only carry the flat/percent stat lines
(AD, AS, crit, hp, ...). The DPS-relevant text — IE's crit-damage bump,
Kraken's every-3rd-attack proc, Stormrazor's Energized, Trinity Force's
Spellblade — lives in the description prose with the numbers stripped.
This module pins those numbers per-patch as Python constants so ``dps.py``
can layer them onto the rotation math.

Schema layers
~~~~~~~~~~~~~

* ``crit_damage_bonus`` — flat add to ``DEFAULT_CRIT_BONUS`` (IE).
* ``periodic`` — single ``PeriodicProc`` per item (every-N-attacks or
  every-N-seconds). ``bonus_damage`` is either a constant float OR a
  callable ``(CallContext) -> float`` for stat-scaling procs (TriForce
  spellblade off ``base_ad``, Wit's End off ``level``, etc.).
* ``armor_pen_pct`` / ``armor_pen_flat`` — physical penetration applied
  multiplicatively / additively after armor reduction.
* ``armor_reduction_pct`` — Black-Cleaver-style reduction applied BEFORE
  pen. Modeled at sustained-DPS values (full stacks); burst rotations
  see less.
* ``defensive_only`` — documents items whose effect is non-DPS (lifeline
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
    2026-05-04, Phase 4 batch 3) is total Ability Power — pure
    item-contributed, since champion records carry no base AP — and
    enables Lich Bane / Nashor's Tooth-style spellblade and AP-on-hit
    scaling.

    ``target_max_hp`` (added 2026-05-04, Phase 4 batch 5) is the
    caller-supplied target max HP — same shape as ``target_armor`` /
    ``target_mr``, default 0.0 means "caller didn't say so contributions
    floor at zero". Unlocks BotRK / Eclipse %-target-HP procs. lolmath
    scenarios carry no HP signal, so callers (arena_coach, sr_draft,
    /dps clients) decide a realistic value from game context. ``%-current-HP``
    procs use the steady-state assumption ``current = max``; explicit
    chunking simulation (e.g. "target at 30%") is a future field.

    ``caster_max_hp`` / ``caster_bonus_hp`` (added 2026-05-04, Phase 4
    batch 6) are engine-derived (``resolved.stats["hp"]`` and
    ``stats["hp"] - base_stats["hp"]`` respectively). Unlike
    ``target_max_hp``, these aren't caller-supplied — the engine knows
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
    resolved crit chance as a fraction (0.0–1.0), engine-derived from
    ``stats.get("crit")`` and clamped at 1.0. Required for crit-scaling
    procs (Essence Reaver Spellblade scales linearly: +0.5 bonus
    physical per 1% crit, capped at +50 at 100%). Default 0.0 means
    "build has no crit" — pre-batch-21 callers don't pass it and procs
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
    # Phase 4 batch 19 (2026-05-04): caller-supplied target bonus HP —
    # same shape as target_max_hp (default 0.0 = "caller didn't say").
    # Required for target-conditional amp items (LDR Giant Slayer scales
    # with the enemy's bonus HP only). Distinct from target_max_hp
    # because base HP varies per-target (Aatrox lvl 11 base ≈ 1790, but
    # an enemy Cho'Gath mid-game may have 1500 base HP); the engine
    # can't infer it without naming the target. Procs that key on this
    # field gracefully no-op when the caller leaves it at 0.
    target_bonus_hp: float = 0.0
    # Phase 4 batch 27 (2026-05-04): caster max mana — engine-derived from
    # ``stats["mp"]`` (champion base mp + per-level scaling + item flat mp
    # contributions). Sibling of caster_max_hp from batch 6. Required for
    # Manamune / Muramana's Awe (2% max mana → bonus AD) and Muramana's
    # Shock (1.2% max mana per-attack proc). Default 0.0 means "build has
    # no mana" — manaless champions (energy users like Lee Sin, Akali)
    # and pre-batch-27 callers gracefully no-op any mana-scaling proc.
    caster_max_mp: float = 0.0


# Scaling-damage callable type. Float still works as a constant.
DamageFn = Union[float, Callable[[CallContext], float]]


@dataclass(frozen=True)
class PeriodicProc:
    """A periodic on-hit / on-timer damage proc.

    Either ``every_n_attacks`` (Kraken-style) OR ``every_n_seconds``
    (Stormrazor-style) is set; the other stays at the default zero.
    Both being set is a config error caught at construction.

    ``bonus_damage`` may be a float (constant) or a callable that takes
    a ``CallContext`` and returns a float — used for stat-scaling procs
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
    # Phase 4 batch 8 (2026-05-04): tuple instead of single Optional —
    # an item can carry multiple periodic procs (Titanic Hydra has both
    # a primary on-hit AND a cleave-to-others piece). ``()`` means "no
    # periodic procs"; single-proc entries write ``(PeriodicProc(...),)``.
    periodics: tuple[PeriodicProc, ...] = ()
    # Physical-damage modifiers — applied to ``target_armor`` in dps.py
    # before the armor curve. Reduction (Black Cleaver) lands first,
    # then % pen (LDR / MR), then flat pen (lethality items).
    armor_reduction_pct: float = 0.0   # Black Cleaver: 0.30 sustained
    armor_pen_pct: float = 0.0         # LDR: 0.35; MR: 0.30
    armor_pen_flat: float = 0.0        # lethality flat (rare standalone)
    # Magic-damage modifiers (Phase 4 batch 4, 2026-05-04) — applied to
    # ``target_mr`` symmetrically. No MR-reduction layer in current
    # League patch (no magic-side Black Cleaver), so % pen lands first
    # and flat pen subtracts after. Add ``mr_reduction_pct`` here when
    # the first item demands it — same layering rules.
    magic_pen_pct: float = 0.0         # Void Staff: 0.40; Cryptbloom: 0.30
    magic_pen_flat: float = 0.0        # Sorc's Shoes: 12; Shadowflame: 15
    # Phase 4 batch 14 (2026-05-04): combat-state damage amplifier.
    # League stacks damage amps multiplicatively via the buff system
    # (two 8% amps = 1.08 * 1.08 = 1.1664x, not 1.16x), so the engine
    # applies them as a product-of-(1+amp) factor, not a sum. Sustained-
    # DPS approximation pins the full-ramp value (e.g. Riftmaker's 8%
    # after 4s in combat — same shape as Black Cleaver's "30% at 5
    # stacks sustained"). Applied to both base AA and proc damage in
    # ``dps._rotation_attack_dps``: in-game amps don't discriminate
    # physical vs magical, just "damage to champions while in combat".
    damage_amp_pct: float = 0.0
    # Phase 4 batch 15 (2026-05-04): stat cross-derivation — caster bonus
    # HP converts into AP at this rate (Riftmaker's Void Infusion: 0.02
    # per bonus HP). Always-on passive, no ramp gate. Applied dps-side
    # via CallContext.ap so AP-scaling procs (Lich Bane spellblade,
    # Nashor's Tooth on-hit) see the converted total. Engine-internal:
    # the resolved stats output from /stats reflects raw stat blocks
    # only; the cross-derivation is computed at DPS time and surfaced
    # in DpsResult.notes when non-zero.
    ap_per_bonus_hp_pct: float = 0.0
    # Phase 4 batch 19 (2026-05-04): target-conditional damage amp —
    # scales linearly from 0 to ``target_bonus_hp_amp_max_pct`` as the
    # caller-supplied ``target_bonus_hp`` rises from 0 to
    # ``target_bonus_hp_amp_cap``, then caps. LDR Giant Slayer:
    # max_pct=0.15, cap=1500 (DDragon: "up to 15% bonus damage,
    # maximum reached at 1500 bonus Health"). Stacks multiplicatively
    # with damage_amp_pct (League's buff system pin from batch 14).
    # Both fields default 0.0 — items without target-conditional amps
    # contribute nothing to the multiplier. Caller leaves
    # CallContext.target_bonus_hp at 0 → amp resolves to 0 (back-compat).
    target_bonus_hp_amp_max_pct: float = 0.0
    target_bonus_hp_amp_cap: float = 0.0
    # Phase 4 batch 20 (2026-05-04): item-passive bonus AD as a percentage of
    # the wielder's leveled base AD. Sterak's Gage "The Claws that Catch"
    # grants "bonus attack damage equal to 45% base AD" — a stat layer, not
    # a proc. Engine resolves this in ``build_champion`` by walking item ids
    # after stat aggregation, summing ``effect.bonus_ad_pct_base_ad *
    # raw_base["ad"]`` per item, and folding the total into ``ad_flat``
    # before ``_combine_items`` runs. Default 0.0 → no contribution.
    # NOT a unique passive in current League (multiple Sterak's-shape items
    # could in principle stack), but currently only 3053 carries this — if
    # a second item appears, ``unique_passive_key`` is the right gate.
    bonus_ad_pct_base_ad: float = 0.0
    # Phase 4 batch 27 (2026-05-04): item-passive bonus AD as a percentage of
    # the wielder's total max mana. Manamune / Muramana's "Awe" grants
    # bonus AD equal to 2% of maximum mana — a stat layer, not a proc.
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
    # the wielder's BONUS mana (item-contributed only — NOT champion base).
    # Archangel's Staff (3003) "Awe" grants 1% bonus mana → AP; Seraph's
    # Embrace (3040) "Awe" grants 2%. Note the divergence from
    # ``bonus_ad_pct_max_mp`` (Manamune/Muramana) — Manamune's Awe is keyed
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
    # Phase 4 batch 30 (2026-05-04): lethality — level-scaled flat armor
    # pen. Distinct from ``armor_pen_flat`` (a raw constant) because real
    # League scales lethality by caster level: actual flat pen =
    # ``lethality × (0.6 + 0.4 × level / 18)``. At lvl 1: 60% effective;
    # at lvl 18: 100%. The pipeline-position is the same as
    # ``armor_pen_flat`` (last in line: reduction → % pen → flat pen);
    # the level scaling is the only difference. ``effective_target_armor``
    # accepts an optional ``level`` parameter and folds the scaled
    # lethality into the pen_flat sum when provided. Pre-batch-30 callers
    # that omit level get the existing armor_pen_flat-only behavior.
    # Default 0.0 → no contribution. NOT a unique passive at the
    # effect-layer (multiple lethality items stack their flat pen
    # additively in current League — same call as the % pen layer).
    lethality: float = 0.0
    # Phase 4 batch 26 (2026-05-04): item-effect-contributed crit chance.
    # Two flavors composing additively into a single per-build sum that
    # adds to ``stats["crit"]`` at compute_dps construction time:
    # - ``crit_chance_bonus_flat`` — a build-time constant (Yun Tal
    #   Wildarrows "Practice Makes Lethal" pinned at full 25% stacks; same
    #   pattern as a Sundered Sky lambda-as-constant).
    # - ``crit_chance_bonus_max_pct`` + ``crit_chance_bonus_per_bonus_hp_cap``
    #   — linear ramp with caster_bonus_hp, max at cap (Atma's Reckoning
    #   "Big Hands" 0–30% over 0–3000 bonus HP). Same shape as
    #   target_bonus_hp_amp from batch 19, just on the caster side.
    # The summed contribution is added to the build's stats.crit and
    # clamped at 1.0 in compute_dps; CallContext.crit_chance and the
    # rotation auto-attack crit calc both see the boosted total. Display
    # values (avg_attack_dmg / raw_attack_dps) reflect the same boosted
    # crit. /stats endpoint output is unchanged — same separation as
    # batch 15's ap_per_bonus_hp_pct (cross-derivation surfaces only via
    # /dps + DpsResult.notes).
    crit_chance_bonus_flat: float = 0.0
    crit_chance_bonus_max_pct: float = 0.0
    crit_chance_bonus_per_bonus_hp_cap: float = 0.0
    # Phase 4 batch 32 (2026-05-04): multiplicative AP amplifier.
    # Rabadon's Deathcap "Magical Opus" multiplies the wielder's total AP
    # by (1 + ap_amp_pct). Applied at DPS time — ``compute_dps`` multiplies
    # the effective AP used by proc scaling and pen formulas by
    # ``total_ap_amp_multiplier(effects)`` AFTER other AP cross-derivation
    # (HP→AP, mana→AP). Raw stat block unchanged — same separation as
    # ``ap_per_bonus_hp_pct`` (batch 15). Stacks multiplicatively per
    # League's buff-system semantics; current patch has one item
    # (Rabadon's 30%). Default 0.0 → no contribution.
    ap_amp_pct: float = 0.0
    # Phase 4 batch 32 (2026-05-04): bonus AD as a percentage of bonus HP.
    # Overlord's Bloodmail "Tyranny" grants bonus AD = 2.5% bonus HP.
    # Bonus HP = HP from items only (not base HP from leveling). Engine
    # resolves this in ``build_champion`` using ``item_totals["hp_flat"]``
    # as the bonus HP proxy — correct because champion leveling contributes
    # base HP, not bonus HP. Walked AFTER ``aggregate_item_stats`` so
    # items' own HP (Overlord's 550) is included. One-way, no feedback.
    # Default 0.0 → no contribution.
    bonus_ad_pct_bonus_hp: float = 0.0
    # Phase 4 batch 34 (2026-05-04): target-debuff magic damage amplifier.
    # Abyssal Mask's "Unmake" aura causes nearby enemies to take X% more
    # magic damage from ALL sources. Modeled as a multiplier on magic-type
    # proc DPS only — does NOT affect physical AA damage (unlike the
    # general ``damage_amp_pct`` field which amplifies everything).
    # ``total_magic_amp_multiplier`` returns the product of
    # (1 + magic_amp_pct) across all effects; applied inside
    # ``_periodic_proc_dps`` per-proc when damage_type != PHYSICAL.
    # Default 0.0 → no contribution.
    magic_amp_pct: float = 0.0
    defensive_only: bool = False     # documents "no DPS effect" entries
    note: str = ""                   # one-line summary surfaced in DpsResult.notes
    # Phase 4 batch 10 (2026-05-04): unique-passive de-duplication.
    # Items that share the same in-game unique passive (Sunfire's Immolate
    # + Hollow Radiance's Immolate, hypothetically multiple Spellblades)
    # don't stack their procs in League — Riot enforces "Unique Passive"
    # explicitly. Engine respects this when ``collect_effects`` sees the
    # same non-empty key twice — first-seen wins, later items contribute
    # only their stat block (which is item-side, not effect-side).
    # Default ``""`` means "no dedup" — every existing entry passes through
    # unchanged. Add a key only when stacking the same effect across
    # multiple items would over-count.
    unique_passive_key: str = ""


# Patch 16.9.1 — refresh on patch bump (extractor manifest is the trigger).
ITEM_EFFECTS: dict[str, ItemEffect] = {
    # ─────────────────────────────────────────────── crit / DPS-positive
    "3031": ItemEffect(
        item_id="3031",
        name="Infinity Edge",
        crit_damage_bonus=0.30,
        note="Infinity Edge: +30% bonus crit damage",
    ),
    "3072": ItemEffect(
        item_id="3072",
        name="Bloodthirster",
        defensive_only=True,
        note="Bloodthirster: Ichorshield (excess lifesteal → shield); no DPS contribution",
    ),
    "3097": ItemEffect(
        item_id="3097",
        name="Stormrazor",
        periodics=(PeriodicProc(
            name="Energized Bolt",
            bonus_damage=120.0,
            damage_type=MAGICAL,
            every_n_seconds=4.0,
        ),),
        note="Stormrazor: Energized ~120 magic dmg every ~4s",
    ),
    "6672": ItemEffect(
        item_id="6672",
        name="Kraken Slayer",
        periodics=(PeriodicProc(
            name="Bring It Down",
            bonus_damage=100.0,
            damage_type=PHYSICAL,
            every_n_attacks=3,
        ),),
        note="Kraken Slayer: Bring It Down ~100 physical dmg every 3rd attack",
    ),
    "6673": ItemEffect(
        item_id="6673",
        name="Immortal Shieldbow",
        defensive_only=True,
        # Phase 4 batch 12 (2026-05-04): Lifeline is unique-passive in
        # current League — only one Lifeline shield triggers per low-HP
        # threshold. Deduped against Sterak's Gage (3053) + Maw of
        # Malmortius (3156). All 3 are defensive_only so dedup only
        # affects DpsResult.notes (no proc to drop). When/if any
        # Lifeline item gets a DPS proc later, the order-dependence
        # gating from batch 11 (Essence Reaver) applies — re-evaluate.
        unique_passive_key="lifeline",
        note="Immortal Shieldbow: Lifeline (low-HP shield); no DPS contribution",
    ),

    # ── Phase 4 expansion 2026-05-03: energized family + scaling procs ──

    "3087": ItemEffect(
        item_id="3087",
        name="Statikk Shiv",
        periodics=(PeriodicProc(
            name="Electroshock",
            bonus_damage=110.0,
            damage_type=MAGICAL,
            every_n_seconds=3.0,
        ),),
        note="Statikk Shiv: Energized chain lightning ~110 magic dmg every ~3s",
    ),
    "3094": ItemEffect(
        item_id="3094",
        name="Rapid Firecannon",
        periodics=(PeriodicProc(
            name="Sharpshooter",
            bonus_damage=120.0,
            damage_type=MAGICAL,
            every_n_seconds=3.0,
        ),),
        note="Rapid Firecannon: Energized critical strike ~120 magic dmg every ~3s",
    ),
    "3091": ItemEffect(
        item_id="3091",
        name="Wit's End",
        periodics=(PeriodicProc(
            name="Fray",
            # 15 magic at lvl 1 → 80 at lvl 18, linear by level.
            bonus_damage=lambda c: 15.0 + (c.level - 1) * (65.0 / 17.0),
            damage_type=MAGICAL,
            every_n_attacks=1,
        ),),
        note="Wit's End: Fray on-hit magic dmg scales 15→80 by level",
    ),
    "3085": ItemEffect(
        item_id="3085",
        name="Runaan's Hurricane",
        periodics=(PeriodicProc(
            name="Wind's Fury",
            # Two extra bolts at 30% bonus AD each = 60% bonus AD per shot.
            # Approximation: assumes both bolts find a target.
            bonus_damage=lambda c: 0.60 * c.bonus_ad,
            damage_type=PHYSICAL,
            every_n_attacks=1,
        ),),
        note="Runaan's Hurricane: 2 extra bolts on-hit, ~60% bonus AD per shot",
    ),
    "3078": ItemEffect(
        item_id="3078",
        name="Trinity Force",
        periodics=(PeriodicProc(
            name="Spellblade",
            # Spellblade: next basic after spell deals 200% base AD bonus
            # physical. Approximation: fires ~once per 3s in active rotations
            # (real CD is 1.5s after spell cast, gated by ability cadence).
            bonus_damage=lambda c: 2.0 * c.base_ad,
            damage_type=PHYSICAL,
            every_n_seconds=3.0,
        ),),
        # Phase 4 batch 11 (2026-05-04): Spellblade is unique-passive in
        # current League — only one Spellblade proc fires per attack.
        # Deduped against Lich Bane (3100) and, as of Phase 4 batch 21
        # (2026-05-04), Essence Reaver (3508). Sundered Sky (6610) uses
        # its own "Lightshield Strike" label, not Spellblade — distinct
        # mechanic, no dedup.
        unique_passive_key="spellblade",
        note="Trinity Force: Spellblade ~200% base AD on-hit, ~once per 3s in rotation",
    ),
    "6699": ItemEffect(
        item_id="6699",
        name="Voltaic Cyclosword",
        periodics=(PeriodicProc(
            name="Firmament",
            # Energized release: 100 + 25% bonus AD physical (slow utility
            # not modeled). Charges over 4s of moving / attacking.
            bonus_damage=lambda c: 100.0 + 0.25 * c.bonus_ad,
            damage_type=PHYSICAL,
            every_n_seconds=4.0,
        ),),
        # Phase 4 batch 30 (2026-05-04): 10 Lethality piece added via the
        # lethality plumbing schema. Was unmodeled prior — Voltaic's stat
        # block in DDragon doesn't carry the lethality value; description
        # lists it. Pipeline now accounts for the level-scaled flat pen
        # alongside the existing Energized periodic proc.
        lethality=10.0,
        note="Voltaic Cyclosword: Energized release ~100 + 25% bonus AD physical every ~4s + 10 Lethality (level-scaled flat pen)",
    ),
    "6610": ItemEffect(
        item_id="6610",
        name="Sundered Sky",
        periodics=(PeriodicProc(
            name="Lightshield Strike",
            # Every 8s, next basic deals (20 + 200% base AD) bonus physical.
            # Long CD makes this rare in DPS terms but a big single hit.
            bonus_damage=lambda c: 20.0 + 2.0 * c.base_ad,
            damage_type=PHYSICAL,
            every_n_seconds=8.0,
        ),),
        note="Sundered Sky: Lightshield Strike ~200% base AD bonus on guaranteed crit, every ~8s",
    ),
    "3124": ItemEffect(
        item_id="3124",
        name="Guinsoo's Rageblade",
        periodics=(PeriodicProc(
            name="Phantom Hit",
            # Every 3rd attack triggers an extra on-hit. Approximated as
            # 50% bonus AD physical — under-counts on-hit stacking with
            # other items (BotRK, Wit's End) but those self-stack via
            # their own periodic entries.
            bonus_damage=lambda c: 0.50 * c.bonus_ad,
            damage_type=PHYSICAL,
            every_n_attacks=3,
        ),),
        note="Guinsoo's Rageblade: Phantom Hit every 3rd attack, ~50% bonus AD physical",
    ),

    # ── Phase 4 expansion: armor pen / reduction ──

    "3036": ItemEffect(
        item_id="3036",
        name="Lord Dominik's Regards",
        armor_pen_pct=0.35,
        # Phase 4 batch 19 (2026-05-04): Giant Slayer promoted via the
        # target-conditional amp schema. DDragon: "Deal up to 15% bonus
        # damage against champions based on their bonus Health. Maximum
        # damage bonus reached at 1500 bonus Health." Caller supplies
        # target_bonus_hp; engine scales linearly to 15% at 1500, then
        # caps. Stacks multiplicatively with damage_amp_pct items
        # (Riftmaker, future Conqueror-style amps).
        target_bonus_hp_amp_max_pct=0.15,
        target_bonus_hp_amp_cap=1500.0,
        note="Lord Dominik's Regards: 35% armor pen (physical) + Giant Slayer up to 15% damage scaling with target_bonus_hp (capped at 1500)",
    ),
    "3033": ItemEffect(
        item_id="3033",
        name="Mortal Reminder",
        armor_pen_pct=0.30,
        note="Mortal Reminder: 30% armor pen + Grievous Wounds (heal-cut not modeled)",
    ),
    # Phase 4 batch 25 (2026-05-04): Serylda's Grudge added to ITEM_EFFECTS
    # as a new entry (was unmodeled — stats-only via item aggregation prior).
    # DDragon snapshot 16.9.1: "+45 Attack Damage / 35% Armor Penetration /
    # 15 Ability Haste". Same shape as LDR (3036) — % armor pen sits in the
    # same pipeline layer (reduction → % pen → flat pen). Coefficient 0.35
    # matches LDR; LDR additionally carries Giant Slayer (target_bonus_hp
    # amp); Serylda has Bitter Cold instead, which is a 30% slow on
    # damaging-ability hits to enemies below 50% HP — pure utility, not
    # damage. Stays unmodeled per the s77/s78 utility-without-damage rule
    # (same call as Stridebreaker's Halting Slash and Iceborn's frost field).
    # No unique_passive_key — the % pen layer sums across items in current
    # League (LDR + Serylda would stack to 70% pen if a build carried both;
    # the build-legality "only one of these archetypes" decision is
    # ranker-owned, not effect-layer).
    "6694": ItemEffect(
        item_id="6694",
        name="Serylda's Grudge",
        armor_pen_pct=0.35,
        note="Serylda's Grudge: 35% armor pen (physical) + Bitter Cold ability slow on <50% HP targets (utility, not modeled)",
    ),
    "3071": ItemEffect(
        item_id="3071",
        name="Black Cleaver",
        # 6% armor reduction per stack, max 5 stacks = 30%. Modeled at
        # sustained DPS (full stacks); burst rotations see less.
        armor_reduction_pct=0.30,
        note="Black Cleaver: 30% armor reduction at full 5 stacks (sustained DPS assumption)",
    ),

    # ── Phase 4 expansion: defensive_only entries (proof of coverage) ──

    "3046": ItemEffect(
        item_id="3046",
        name="Phantom Dancer",
        defensive_only=True,
        # NOT tagged "lifeline" — DDragon's actual passive label is
        # "Spectral Waltz" (Ghost effect, not a shield). Older RC notes
        # called this Lifeline by mistake. Different mechanic, no shared
        # unique-passive with Shieldbow / Sterak's / Maw.
        note="Phantom Dancer: Spectral Waltz (Ghost on low HP); no DPS contribution",
    ),
    "6676": ItemEffect(
        item_id="6676",
        name="The Collector",
        defensive_only=True,
        note="The Collector: Execute below 5% HP — fires once at low HP, not a per-rotation DPS proc",
    ),
    "6675": ItemEffect(
        item_id="6675",
        name="Navori Flickerblade",
        defensive_only=True,
        note="Navori Flickerblade: Crits CDR basic abilities (CDR not DPS-modeled)",
    ),
    "3142": ItemEffect(
        item_id="3142",
        name="Youmuu's Ghostblade",
        # Phase 4 batch 30 (2026-05-04): promoted from defensive_only via
        # the lethality plumbing schema. Stat block carries 18 Lethality
        # in description (NOT in DDragon's stats keys); the active MS
        # boost stays utility-only — not modeled (same rule as Stridebreaker's
        # Halting Slash, Iceborn's frost field).
        lethality=18.0,
        note="Youmuu's Ghostblade: 18 Lethality (level-scaled flat pen) + active MS bonus (utility, not modeled)",
    ),
    "3814": ItemEffect(
        item_id="3814",
        name="Edge of Night",
        # Phase 4 batch 30 (2026-05-04): promoted from defensive_only via
        # the lethality plumbing schema. 15 Lethality in description; the
        # Spellshield piece stays non-DPS (deduped against Banshee's Veil
        # could be a future call, but Spellshield is shield-style mechanic
        # and Banshee's is also separate — different proc shapes).
        lethality=15.0,
        note="Edge of Night: 15 Lethality (level-scaled flat pen) + Spellshield (defensive, not modeled)",
    ),
    "6695": ItemEffect(
        item_id="6695",
        name="Serpent's Fang",
        defensive_only=True,
        note="Serpent's Fang: anti-shield; situational, not DPS-modeled",
    ),
    "6701": ItemEffect(
        item_id="6701",
        name="Opportunity",
        # Phase 4 batch 30 (2026-05-04): promoted from defensive_only via
        # the lethality plumbing schema. 18 base Lethality in description;
        # the takedown-bonus-lethality piece is event-bound and stays
        # not-modeled (same rule as Hubris's Eminence). The 18 base
        # alone is a steady-state DPS contribution.
        lethality=18.0,
        note="Opportunity: 18 base Lethality (level-scaled flat pen) + takedown-bonus-lethality (conditional, not modeled)",
    ),
    "3053": ItemEffect(
        item_id="3053",
        name="Sterak's Gage",
        unique_passive_key="lifeline",
        # Phase 4 batch 20 (2026-05-04): "The Claws that Catch" promoted
        # from unmodeled. Meraki bulk items snapshot resolves the
        # numeric scaling DDragon stripped: "Gain bonus attack damage
        # equal to 45% base AD". This is a stat layer (not a proc) —
        # always-on flat AD added at build time, scales with the
        # leveled champion base AD (e.g. Sett base AD ~76 at lvl 11 →
        # +34 bonus AD from Sterak's). Engine wires this in
        # ``build_champion`` via the ``bonus_ad_pct_base_ad`` field.
        # The Lifeline shield piece (unique_passive_key="lifeline")
        # remains non-DPS — deduped against Shieldbow / Maw / Sterak.
        # Engine still treats the item as having a non-DPS lifeline
        # piece + a DPS-positive Claws piece, both modeled correctly.
        bonus_ad_pct_base_ad=0.45,
        note=(
            "Sterak's Gage: The Claws that Catch +45% base AD as bonus AD "
            "(stat layer) + Lifeline (low-HP shield, deduped)"
        ),
    ),
    "3156": ItemEffect(
        item_id="3156",
        name="Maw of Malmortius",
        defensive_only=True,
        unique_passive_key="lifeline",
        note="Maw of Malmortius: Lifeline magic shield; no DPS contribution",
    ),
    "3181": ItemEffect(
        item_id="3181",
        name="Hullbreaker",
        # Phase 4 batch 20 (2026-05-04): promoted from defensive_only.
        # Meraki bulk items snapshot (items_meraki.json) carries the
        # numeric formula DDragon strips:
        #   "Basic attacks on-hit grant a stack for 10s, stacking up to
        #    5 times. At maximum stacks, your next basic attack consumes
        #    all stacks to deal 120% base AD + 5% maximum health bonus
        #    physical damage."
        # Engine modeling:
        # - every_n_attacks=5 (4 build stacks + 5th attack consumes; same
        #   shape as Kraken Slayer's 3rd-attack proc, just at 5).
        # - bonus_damage = 1.20 * base_ad + 0.05 * caster_max_hp.
        # - "maximum health" is unqualified in Meraki's text → caster's
        #   max HP (League convention; Hullbreaker is a side-laner HP-
        #   stacker item, design intent is wielder's HP). Same shape as
        #   Heartsteel's `0.06 * c.caster_max_hp`.
        # Approximations:
        # - Real proc only fires vs champions/epic monsters/structures.
        #   Engine has no champion-only target gate today (same trade-off
        #   as Kraken Slayer); over-counts vs minion-only rotations,
        #   noise band <DPS error of every other approximation.
        # - Increased structure damage (300% base AD + 10% max HP) not
        #   modeled — engine targets are champions, not structures.
        # - Boarding Party (ally-side siege minion buff) is non-DPS.
        periodics=(PeriodicProc(
            name="Skipper",
            bonus_damage=lambda c: 1.20 * c.base_ad + 0.05 * c.caster_max_hp,
            damage_type=PHYSICAL,
            every_n_attacks=5,
        ),),
        note=(
            "Hullbreaker: Skipper every-5th-attack 120% base AD + 5% caster "
            "max HP bonus physical (champ/epic/structure-gated; engine over-"
            "counts vs minion rotations) + Boarding Party (ally-side, no DPS)"
        ),
    ),
    "3110": ItemEffect(
        item_id="3110",
        name="Frozen Heart",
        defensive_only=True,
        note="Frozen Heart: AS-slow aura + armor; no DPS contribution",
    ),
    "3011": ItemEffect(
        item_id="3011",
        name="Chemtech Putrifier",
        defensive_only=True,
        note="Chemtech Putrifier: Grievous Wounds on damage (AP support, no DPS)",
    ),
    "3153": ItemEffect(
        item_id="3153",
        name="Blade of The Ruined King",
        periodics=(PeriodicProc(
            name="Mist's Edge",
            # 8% target current HP on-hit (melee value; ranged is 5%).
            # Steady-state DPS approximation: current_hp ≈ max_hp at the
            # start of a fight, so we model with target_max_hp. Slight
            # over-count as the target gets chunked through the rotation;
            # an explicit current_hp_pct field is a future batch.
            bonus_damage=lambda c: 0.08 * c.target_max_hp,
            damage_type=PHYSICAL,
            every_n_attacks=1,
        ),),
        note="Blade of the Ruined King: Mist's Edge ~8% target HP on-hit (melee, steady-state approx)",
    ),
    "3302": ItemEffect(
        item_id="3302",
        name="Terminus",
        # Phase 4 batch 13 (2026-05-04): promoted from defensive_only.
        # The "alternating physical/magical" wording in the prior note
        # was incorrect — DDragon shows Shadow is a constant on-hit
        # (30 magic, every basic), and Juxtaposition is the alternating
        # part (Light buff = caster resists, defensive; Dark buff = pen).
        # In sustained DPS rotations both Light and Dark buffs are up
        # most of the time (each refreshes every 2 attacks at AS=1.0,
        # both last 5s). Light's resists are caster-side, ignored;
        # Dark's pen is modeled at full uptime (10% armor pen + 10%
        # magic pen) — same sustained-DPS approximation as Black
        # Cleaver's stacking.
        periodics=(PeriodicProc(
            name="Shadow",
            bonus_damage=30.0,
            damage_type=MAGICAL,
            every_n_attacks=1,
        ),),
        armor_pen_pct=0.10,
        magic_pen_pct=0.10,
        note=(
            "Terminus: Shadow on-hit ~30 magic damage per attack + "
            "Juxtaposition Dark sustained 10% armor pen + 10% magic pen"
        ),
    ),
    "6692": ItemEffect(
        item_id="6692",
        name="Eclipse",
        periodics=(PeriodicProc(
            name="Ever Rising Moon",
            # 6% target max HP physical, gated on hitting the same target
            # with two damage instances within 1.5s. In an active basic-
            # attack rotation the 2-attack gate is the binding constraint,
            # so every_n_attacks=2 is the right shape. Note: real proc
            # has a 6s CD per target — under-counts when sustained, but
            # most rotations don't fire 2 procs within 6s anyway.
            bonus_damage=lambda c: 0.06 * c.target_max_hp,
            damage_type=PHYSICAL,
            every_n_attacks=2,
        ),),
        note="Eclipse: Ever Rising Moon ~6% target max HP every 2 attacks (physical)",
    ),

    # ── Phase 4 expansion 2026-05-04: high-pickrate SR legendaries ──
    # All defensive_only — passives are non-DPS (active utilities, lifeline
    # shields, sustain, damage-storage, ability-CDR stacks). Promote to
    # periodic / armor-pen / amp entries when the relevant Phase 4+ hooks
    # land (target HP, magic pen layer, ability scaling).

    "6333": ItemEffect(
        item_id="6333",
        name="Death's Dance",
        defensive_only=True,
        note="Death's Dance: bleed (stores damage to release over time); no DPS proc",
    ),
    "3161": ItemEffect(
        item_id="3161",
        name="Spear of Shojin",
        defensive_only=True,
        # Phase 4 batch 16 (2026-05-04): note corrected against DDragon
        # snapshot. Prior note named "Veteran's Resolve stacks reduce
        # ability CDs" which is from an older patch — current passives
        # are "Dragonforce" (25 basic ability haste, stat-side) and
        # "Focused Will" (3% damage amp per stack to abilities/passives,
        # max 4 stacks = 12%). The amp is ABILITY-only, not auto-attack
        # — engine doesn't model ability damage, so this stays
        # defensive_only. Generic damage_amp_pct (batch 14) intentionally
        # not used since it would amp AAs too.
        note="Spear of Shojin: Dragonforce (25 basic AH, stat) + Focused Will (3% per stack ability/passive amp, max 4 stacks; ability damage not DPS-modeled)",
    ),
    # Phase 4 batch 21 (2026-05-04): ER promoted from defensive_only via
    # the new CallContext.crit_chance schema. Per Meraki bulk text:
    #   "Spellblade — After using an Ability, your next basic attack
    #    within 10s deals 125% base AD (+ 0 to 50 based on critical
    #    strike chance, scaling 0.5 damage per 1% crit) bonus physical
    #    damage on-hit and restores mana equal to half that amount."
    # Crit-chance scaling: 0.5 damage per 1% crit → 50 * crit_chance
    # (where crit_chance is 0.0–1.0). At 0% crit ER procs for 1.25 *
    # base_ad; at 100% crit, +50 flat on top. Cooldown 1.5s real, but
    # rotation cadence is ability-cast-frequency-bound — match the
    # ~3s assumption already pinned for Trinity Force / Lich Bane (see
    # batch 11 commentary on Spellblade dedup).
    "3508": ItemEffect(
        item_id="3508",
        name="Essence Reaver",
        periodics=(PeriodicProc(
            name="Spellblade",
            bonus_damage=lambda c: 1.25 * c.base_ad + 50.0 * c.crit_chance,
            damage_type=PHYSICAL,
            every_n_seconds=3.0,
        ),),
        # Spellblade unique-passive — same key as Trinity Force (3078)
        # and Lich Bane (3100). First-seen-wins ordering: a build with
        # [TF, ER] keeps TF's spellblade; [ER, TF] keeps ER's. The pre-
        # promotion comment on TF flagged this exact dedup question;
        # batch 21 closes it by joining the family.
        unique_passive_key="spellblade",
        note="Essence Reaver: Spellblade 125% base AD + 0.5/crit% bonus physical on-hit, ~once per 3s in rotation",
    ),
    "3084": ItemEffect(
        item_id="3084",
        name="Heartsteel",
        periodics=(PeriodicProc(
            name="Colossal Consumption",
            # Flat 70 + 6% caster max HP physical, every 3.5s of in-
            # combat-with-champion charge time. DDragon 16.9.1 description:
            # "70 plus 6% of your max Health". The level-scaling lerp
            # (70 + 90*(level-1)/17 = 70-160) carried here through batch 16
            # was from a prior patch and was wrong on current data. The
            # HP-on-damage permanent stack (8% of damage as max HP) is not
            # modeled — that's stat-side, not proc-side.
            bonus_damage=lambda c: 70.0 + 0.06 * c.caster_max_hp,
            damage_type=PHYSICAL,
            every_n_seconds=3.5,
        ),),
        note=(
            "Heartsteel: Colossal Consumption flat 70 + 6% caster max HP "
            "physical every ~3.5s in combat"
        ),
    ),
    "3083": ItemEffect(
        item_id="3083",
        name="Warmog's Armor",
        defensive_only=True,
        note="Warmog's Armor: out-of-combat HP regen; no DPS contribution",
    ),
    "3139": ItemEffect(
        item_id="3139",
        name="Mercurial Scimitar",
        defensive_only=True,
        note="Mercurial Scimitar: active cleanse + bonus MS; no DPS contribution",
    ),
    "3026": ItemEffect(
        item_id="3026",
        name="Guardian Angel",
        defensive_only=True,
        note="Guardian Angel: revive after lethal damage; no DPS contribution",
    ),
    "3102": ItemEffect(
        item_id="3102",
        name="Banshee's Veil",
        defensive_only=True,
        note="Banshee's Veil: spellshield blocks next ability; no DPS contribution",
    ),
    "3157": ItemEffect(
        item_id="3157",
        name="Zhonya's Hourglass",
        defensive_only=True,
        note="Zhonya's Hourglass: active stasis (untargetable for 2.5s); no DPS contribution",
    ),
    # Phase 4 batch 21 (2026-05-04): Stridebreaker promoted from
    # defensive_only via the same multi-target rotation layer Ravenous
    # Hydra (3074) uses. Per Meraki bulk, Cleave deals "40% AD (melee) /
    # 20% AD (ranged) physical damage to other enemies in a 350 radius
    # centered around the target" on every basic on-hit. Same shape and
    # per-rotation isolation as Ravenous; coefficient is 40% vs Ravenous's
    # 35%. Halting Slash active (dash + slow) stays utility — not modeled.
    # Melee values pinned; ranged variant under-counts (same trade-off as
    # Ravenous and Titanic).
    "6631": ItemEffect(
        item_id="6631",
        name="Stridebreaker",
        periodics=(PeriodicProc(
            name="Cleave",
            # Melee: 40% total AD physical to other enemies (primary
            # already lands via the basic attack itself). At
            # targets_in_rotation=1.0 the cleave hits 0 enemies and adds
            # zero DPS — preserves the historic single-target shape for
            # all-n=1 rotations.
            bonus_damage=lambda c: max(0.0, c.targets_in_rotation - 1.0)
                * 0.40 * (c.base_ad + c.bonus_ad),
            damage_type=PHYSICAL,
            every_n_attacks=1,
        ),),
        note="Stridebreaker: Cleave ~40% AD physical to other enemies in 350 radius (melee, scales with rotation targets)",
    ),
    # Phase 4 batch 24 (2026-05-04): Profane Hydra (6698) added to
    # ITEM_EFFECTS as a new entry (was stats-only via item aggregation
    # prior — assassin-tagged Tiamat upgrade). Per Meraki bulk, Cleave
    # deals "40% AD (melee) / 20% AD (ranged) physical damage to other
    # enemies in a 350 radius centered around the target" on every
    # damaging basic on-hit. Same shape and per-rotation isolation as
    # Stridebreaker / Ravenous; coefficient pinned at 40% (melee value)
    # to match Stridebreaker's call. Heretical Cleave active (~80% AD
    # AoE) stays not-modeled — Meraki bulk has its cooldown null and
    # actives-without-CD-pin are deferred per the s77/s78 hand-off rule.
    # Tiamat-tree exclusivity (only one of Strider/Ravenous/Profane/
    # Titanic owned at once) is enforced by the ranker's build legality
    # checks, not by unique_passive_key here — same pattern as the
    # other hydras.
    "6698": ItemEffect(
        item_id="6698",
        name="Profane Hydra",
        periodics=(PeriodicProc(
            name="Cleave",
            # Melee: 40% total AD physical to other enemies (primary
            # already lands via the basic attack itself). At
            # targets_in_rotation=1.0 the cleave hits 0 enemies and adds
            # zero DPS — preserves the historic single-target shape for
            # all-n=1 rotations.
            bonus_damage=lambda c: max(0.0, c.targets_in_rotation - 1.0)
                * 0.40 * (c.base_ad + c.bonus_ad),
            damage_type=PHYSICAL,
            every_n_attacks=1,
        ),),
        note="Profane Hydra: Cleave ~40% AD physical to other enemies in 350 radius (melee, scales with rotation targets)",
    ),

    # ── Phase 4 batch 3 (2026-05-04): AP-aware CallContext + spellblade ──
    # CallContext.ap (added this batch) lets spellblade and AP-on-hit procs
    # promote out of defensive_only. Two items unlock; five AP-stat siblings
    # land here as documented defensive_only because their effects don't
    # fit the periodic / on-hit shape (active utility, ability-bound,
    # combat-state amp, %-current-HP magic crit).

    "3100": ItemEffect(
        item_id="3100",
        name="Lich Bane",
        periodics=(PeriodicProc(
            name="Spellblade",
            # 75% base AD + 50% AP bonus magic on next basic after ability.
            # Real CD 1.5s; rotation cadence approx ~3s same as Trinity Force
            # spellblade (gated by ability cast frequency, not item CD).
            bonus_damage=lambda c: 0.75 * c.base_ad + 0.50 * c.ap,
            damage_type=MAGICAL,
            every_n_seconds=3.0,
        ),),
        # Phase 4 batch 11 (2026-05-04): Spellblade unique-passive — see
        # the note on Trinity Force (3078) for the full reasoning. First-
        # seen-wins ordering: building [TF, LB] keeps TF's spellblade,
        # building [LB, TF] keeps LB's. Both are reasonable approximations
        # of a single in-game spellblade firing.
        unique_passive_key="spellblade",
        note="Lich Bane: Spellblade ~75% base AD + 50% AP magic, ~once per 3s in rotation",
    ),
    "6662": ItemEffect(
        item_id="6662",
        name="Iceborn Gauntlet",
        # Phase 4 batch 23 (2026-05-04): added to ITEM_EFFECTS as a new
        # entry (was not in the table at all — stats-only via item
        # aggregation prior to this batch). Iceborn's Spellblade variant
        # deals 150% base AD bonus physical on the next basic after an
        # ability. Real CD is 1.5s post-empowered-attack; rotation
        # cadence approx ~3s same as Trinity Force / Lich Bane / Essence
        # Reaver (gated by ability cast frequency, not item CD). The
        # frost field's 25% slow is utility, not damage — not modeled.
        # Joins the spellblade unique-passive dedup family.
        periodics=(PeriodicProc(
            name="Spellblade",
            bonus_damage=lambda c: 1.50 * c.base_ad,
            damage_type=PHYSICAL,
            every_n_seconds=3.0,
        ),),
        # Spellblade unique-passive — same key as Trinity Force (3078),
        # Lich Bane (3100), and Essence Reaver (3508). First-seen-wins
        # ordering: [TF, IBG] keeps TF (200% > 150%, but order rules);
        # [IBG, TF] keeps IBG. Same caveat as the rest of the family —
        # the engine doesn't pick "best", it picks "first" — and that
        # behavior is documented and intentional.
        unique_passive_key="spellblade",
        note="Iceborn Gauntlet: Spellblade ~150% base AD on-hit, ~once per 3s in rotation",
    ),
    "3115": ItemEffect(
        item_id="3115",
        name="Nashor's Tooth",
        periodics=(PeriodicProc(
            name="Icathian Bite",
            # 15 + 20% AP bonus magic per basic. Per-attack proc (every_n=1).
            bonus_damage=lambda c: 15.0 + 0.20 * c.ap,
            damage_type=MAGICAL,
            every_n_attacks=1,
        ),),
        note="Nashor's Tooth: Icathian Bite on-hit ~15 + 20% AP magic per attack",
    ),

    "3146": ItemEffect(
        item_id="3146",
        name="Hextech Gunblade",
        # Phase 4 batch 22 (2026-05-04): promoted from defensive_only.
        # Lightning Bolt active deals 175→253 (level 1→18, linear) +
        # 30% AP magic damage, 40s cooldown. Meraki text:
        #   "175 + (253-175)/17*(x-1) for 20" + 30% AP magic damage.
        # Cooldown sourced from in-game / wiki (Meraki bulk has the
        # cooldown field null on this item); 40s pins the in-game value.
        # Modeled as a long-CD periodic proc — same shape as Sundered
        # Sky's Lightshield Strike (8s) just with a far longer cadence.
        # Slow (25% / 1.5s) is utility, not damage — not modeled. Per the
        # batch 21 stat-property pattern, c.ap is build-derived and lives
        # on CallContext at compute_dps construction time; pre-batch
        # callers that don't pass it get the 0.0 default and the lambda
        # gracefully falls back to flat level-scaled damage.
        periodics=(PeriodicProc(
            name="Lightning Bolt",
            bonus_damage=lambda c: 175.0 + (253.0 - 175.0) / 17.0 * (c.level - 1) + 0.30 * c.ap,
            damage_type=MAGICAL,
            every_n_seconds=40.0,
        ),),
        note="Hextech Gunblade: Lightning Bolt 175→253 + 30% AP magic, 40s CD (slow not modeled)",
    ),
    "6655": ItemEffect(
        item_id="6655",
        name="Luden's Echo",
        defensive_only=True,
        note="Luden's Echo: ability-bound echo bolts (not on-hit / not in auto rotation)",
    ),
    "4633": ItemEffect(
        item_id="4633",
        name="Riftmaker",
        # Phase 4 batch 14 (2026-05-04): promoted via damage_amp_pct.
        # Void Corruption ramps to 8% bonus damage after 4s in combat
        # (sustained-DPS approximation pins the full-ramp value).
        # Phase 4 batch 15 (2026-05-04): Void Infusion HP→AP wired via
        # ap_per_bonus_hp_pct = 0.02 (always-on passive, not gated by
        # combat — DDragon: "Gain 2% of your bonus Health as Ability
        # Power"). Compounds with Heartsteel / Titanic Hydra HP stacks
        # to lift Lich Bane / Nashor's Tooth proc damage. The omnivamp
        # at full Void Corruption stacks is intentionally not modeled
        # (DPS engine doesn't track healing).
        damage_amp_pct=0.08,
        ap_per_bonus_hp_pct=0.02,
        note="Riftmaker: Void Corruption ~8% damage amp at full ramp + Void Infusion 2% bonus HP → AP (always on)",
    ),
    "3128": ItemEffect(
        item_id="3128",
        name="Deathfire Grasp",
        defensive_only=True,
        note="Deathfire Grasp: active 15% target max HP — active item, not in auto rotation",
    ),

    # ── Phase 4 batch 4 (2026-05-04): magic pen layer ──
    # Symmetric to the armor pen pipeline. Void Staff / Cryptbloom carry
    # % pen; Sorcerer's Shoes / Shadowflame carry flat pen. Shadowflame
    # also has a magic-crit-on-low-HP effect (target HP not modeled in
    # Phase 4); the 15 flat pen IS modeled here, so it's no longer
    # defensive_only — the pen contribution alone is real DPS uplift.

    "3135": ItemEffect(
        item_id="3135",
        name="Void Staff",
        magic_pen_pct=0.40,
        note="Void Staff: 40% magic pen (magical)",
    ),
    "3137": ItemEffect(
        item_id="3137",
        name="Cryptbloom",
        magic_pen_pct=0.30,
        note="Cryptbloom: 30% magic pen + Life from Death heal-on-takedown (heal not DPS-modeled)",
    ),
    "3020": ItemEffect(
        item_id="3020",
        name="Sorcerer's Shoes",
        magic_pen_flat=12.0,
        note="Sorcerer's Shoes: 12 flat magic pen",
    ),
    "4645": ItemEffect(
        item_id="4645",
        name="Shadowflame",
        magic_pen_flat=15.0,
        note="Shadowflame: 15 flat magic pen + Cinderbloom magic crit <40% HP (low-HP gate not modeled)",
    ),

    # ── Phase 4 batch 6 (2026-05-04): caster HP layer ──
    # CallContext.caster_max_hp / caster_bonus_hp (engine-derived from
    # resolved stats) lets caster-HP-scaling procs land. Heartsteel
    # promotes from defensive_only above. Titanic Hydra is a new add.
    # Ravenous Hydra deferred — current-patch Cleave is nearby-enemies-
    # only (no primary-target bonus); contributes 0 in single-target DPS.

    "3748": ItemEffect(
        item_id="3748",
        name="Titanic Hydra",
        periodics=(
            PeriodicProc(
                name="Cleave (primary)",
                # Melee: 5 + 1.5% caster bonus HP physical to primary on
                # every basic. Ranged variant (3 + 0.75%) under-counted —
                # Titanic is almost exclusively a melee item.
                bonus_damage=lambda c: 5.0 + 0.015 * c.caster_bonus_hp,
                damage_type=PHYSICAL,
                every_n_attacks=1,
            ),
            # Phase 4 batch 8 (2026-05-04): cleave-to-others piece —
            # 40% of total AD physical to enemies behind the target. The
            # multi-proc-per-item schema lets this co-exist with the
            # primary on-hit proc. Multiplier max(0, n-1) — same shape
            # as Ravenous Hydra in batch 7.
            PeriodicProc(
                name="Cleave (to nearby)",
                bonus_damage=lambda c: max(0.0, c.targets_in_rotation - 1.0)
                    * 0.40 * (c.base_ad + c.bonus_ad),
                damage_type=PHYSICAL,
                every_n_attacks=1,
            ),
        ),
        note="Titanic Hydra: Cleave ~5 + 1.5% bonus HP on-hit primary + ~40% AD to nearby (melee values)",
    ),

    # ── Phase 4 batch 7 (2026-05-04): multi-target rotations ──
    # CallContext.targets_in_rotation (engine-derived from each rotation's
    # numberOfTargets) lets cleave-to-others procs land. ~6% of lolmath
    # rotations carry n>1; the other 94% pass n=1.0 unchanged.

    "3074": ItemEffect(
        item_id="3074",
        name="Ravenous Hydra",
        periodics=(PeriodicProc(
            name="Cleave",
            # Melee: 35% total AD physical to nearby enemies only (no
            # damage to primary target — that already lands via the basic
            # attack). With targets_in_rotation=1.0 the cleave hits 0 enemies
            # and contributes zero, exactly the historic single-target shape.
            # Ranged variant 21% under-counted — same call as Titanic.
            bonus_damage=lambda c: max(0.0, c.targets_in_rotation - 1.0)
                * 0.35 * (c.base_ad + c.bonus_ad),
            damage_type=PHYSICAL,
            every_n_attacks=1,
        ),),
        note="Ravenous Hydra: Cleave ~35% AD physical to nearby enemies (melee, scales with rotation targets)",
    ),

    # ── Phase 4 batch 9 (2026-05-04): Immolate items ──
    # Sunfire Aegis (3068) and Hollow Radiance (6664) share the same
    # Immolate aura passive: after taking or dealing damage, deal
    # ~12 + 1.5% bonus HP magic damage per second to nearby enemies for 3s.
    # In any DPS rotation (basic attacks every ~1s, all rotations >=2s),
    # the 1s charge + 3s active window are continuously refreshed — modeled
    # as a per-second tick over the full rotation duration. The
    # AoE-incl-primary multiplier is c.targets_in_rotation (Sunfire's aura
    # damages every nearby enemy, primary included). Caster bonus HP
    # scaling reuses the batch-6 caster-HP layer.
    #
    # NOTE: Riot enforces unique-passive on Immolate (stacking Sunfire +
    # Hollow Radiance does NOT double the proc). The engine currently
    # treats all procs independently, so a build with both items will
    # double-count this contribution. Unique-passive enforcement is its
    # own architectural change — out of scope for this batch.
    #
    # Both items pass-through CallContext.targets_in_rotation: at n=1 the
    # Immolate still ticks for 1× damage (the primary target IS counted).
    # At n=3 it ticks for 3× damage. This is the AoE-incl-primary idiom
    # pinned in batch 7's tests.

    "3068": ItemEffect(
        item_id="3068",
        name="Sunfire Aegis",
        periodics=(PeriodicProc(
            name="Immolate",
            bonus_damage=lambda c: c.targets_in_rotation
                * (12.0 + 0.015 * c.caster_bonus_hp),
            damage_type=MAGICAL,
            every_n_seconds=1.0,
        ),),
        unique_passive_key="immolate",
        note="Sunfire Aegis: Immolate ~12 + 1.5% bonus HP magic per second to nearby (melee values)",
    ),
    "6664": ItemEffect(
        item_id="6664",
        name="Hollow Radiance",
        periodics=(PeriodicProc(
            name="Immolate",
            bonus_damage=lambda c: c.targets_in_rotation
                * (12.0 + 0.015 * c.caster_bonus_hp),
            damage_type=MAGICAL,
            every_n_seconds=1.0,
        ),),
        unique_passive_key="immolate",
        note=(
            "Hollow Radiance: Immolate ~12 + 1.5% bonus HP magic per second "
            "to nearby (Desolate execute-on-kill not modeled — conditional)"
        ),
    ),

    # ── Phase 4 batch 26 (2026-05-04): item-effect-contributed crit chance ──
    # CallContext.crit_chance was added in batch 21 for Essence Reaver. This
    # batch adds the *production* path — items that themselves contribute to
    # the build's crit chance (Yun Tal at full Wildarrows stacks; Atma's
    # Big Hands scaling with caster bonus HP). Engine sums each effect's
    # contribution into the resolved crit at compute_dps time and clamps at
    # 1.0; auto-attack crit + ER spellblade scaling + future crit-readers
    # all see the boosted total. /stats output is unchanged — same
    # cross-derivation pattern as Riftmaker's HP→AP from batch 15.

    "3032": ItemEffect(
        item_id="3032",
        name="Yun Tal Wildarrows",
        # Practice Makes Lethal: gain crit on-attack permanently, capped at
        # 25%. Pinned at full stacks (the steady-state assumption — same
        # call as Black Cleaver's "30% reduction at 5 stacks sustained" and
        # Riftmaker's "8% at full ramp"). DDragon stat block carries 0%
        # base crit; Wildarrows is the entire crit story for this item.
        # Flurry (30% AS for 6s on champion-attack, 30s CD with attack-driven
        # CD reduction) is intentionally not modeled — it would need a
        # conditional AS-bonus schema and the steady-state uptime is
        # near-100% which over-counts in shorter rotations. Stays utility-
        # adjacent (real DPS impact, but blocked on schema). The item's
        # 50 AD + 40% AS land via item aggregation.
        crit_chance_bonus_flat=0.25,
        # No unique_passive_key — Practice Makes Lethal is one of one in
        # the current item set. Adding a key now would be premature.
        note="Yun Tal Wildarrows: Practice Makes Lethal +25% crit at full Wildarrows stacks (steady-state pin; Flurry AS bonus not modeled)",
    ),

    "3039": ItemEffect(
        item_id="3039",
        name="Atma's Reckoning",
        # Big Hands: 1% crit per 100 bonus HP, capped at 30% at 3000 bonus
        # HP (LoL wiki, V25.21 — Meraki bulk has the passive list null,
        # external source pinned 2026-05-04). Linear ramp; same shape as
        # batch 19's target_bonus_hp_amp (LDR Giant Slayer) on the caster
        # side. The 700 HP / 20% crit / 10 AH stat block lands via item
        # aggregation; Atma's stats alone don't reach the 3000 cap (700
        # bonus HP from Atma itself ≈ 0.07 ramp = 7% Big Hands), so
        # multi-HP-item builds (Heartsteel, Titanic Hydra, Warmog's,
        # Sterak's HP) drive most of the contribution.
        crit_chance_bonus_max_pct=0.30,
        crit_chance_bonus_per_bonus_hp_cap=3000.0,
        note="Atma's Reckoning: Big Hands +1% crit per 100 bonus HP, max 30% at 3000 bonus HP",
    ),

    # ── Phase 4 batch 27 (2026-05-04): Manamune / Muramana family ──
    # Mana-scaling damage. Awe (2% max mana → bonus AD) is a stat layer
    # mirroring batch 20's Sterak's bonus_ad_pct_base_ad wiring; Shock
    # (Muramana only — 1.2% max mana per-attack physical) uses the
    # existing periodic schema with a new caster_max_mp CallContext field.
    # Manamune transforms into Muramana at +360 max-mana-stacks in real
    # League — engine doesn't model the transformation, so the two items
    # are independent ITEM_EFFECTS entries. Manaflow (the stacking
    # mana-on-attack mechanism that drives the transformation) is
    # intentionally not modeled; same call as Yun Tal's Practice Makes
    # Lethal stack-up — pin the steady-state assumption (the item's own
    # listed max-mana stat) and let build_champion handle the mana
    # block. Muramana's ability damage piece (3-4% max mana on damaging
    # abilities) stays not-modeled per the ability-bound rule.

    "3004": ItemEffect(
        item_id="3004",
        name="Manamune",
        # Awe: 2% max mana as bonus AD. Stat block: 35 AD / 500 mana / 15 AH
        # (DDragon 16.9.1, mirrors Meraki bulk passive text). The 500 mana
        # contribution lands via item aggregation; Awe converts the build's
        # total max mana (champion base + items + Manamune's own 500) into
        # +AD at engine resolution time.
        # Manaflow stack-up not modeled — caller's build represents either
        # "post-transformation Muramana" (use 3042) or "pre-transformation
        # Manamune" (use 3004), not the in-flight stacking state. Engine's
        # build is steady-state; Manaflow stays utility-adjacent.
        bonus_ad_pct_max_mp=0.02,
        note="Manamune: Awe +2% max mana as bonus AD (Manaflow stack-up not modeled — steady-state)",
    ),

    "3042": ItemEffect(
        item_id="3042",
        name="Muramana",
        # Awe: 2% max mana as bonus AD (same coefficient as Manamune).
        # Shock: 1.2% max mana bonus physical per-attack vs champions.
        # Engine has no champion-only target gate (same trade-off as
        # Kraken Slayer, Hullbreaker) — over-counts vs minion-only
        # rotations; noise band <DPS error of every other approximation.
        # Ability damage piece (3-4% max mana on damaging abilities)
        # stays not-modeled per the ability-bound rule (same as Liandry).
        # Stat block: 35 AD / 1000 mana / 15 AH (Muramana's mana pool is
        # 2x Manamune's — the entire point of the transformation in real
        # League). Awe + Shock both scale linearly with the larger mana
        # pool, so Muramana's DPS uplift on the same caster is roughly
        # 2x Manamune's at the same mana baseline.
        bonus_ad_pct_max_mp=0.02,
        periodics=(PeriodicProc(
            name="Shock",
            bonus_damage=lambda c: 0.012 * c.caster_max_mp,
            damage_type=PHYSICAL,
            every_n_attacks=1,
        ),),
        note=(
            "Muramana: Awe +2% max mana as bonus AD + Shock 1.2% max mana "
            "per-attack physical (champ-only gate not enforced; ability "
            "damage piece not modeled)"
        ),
    ),

    # ── Phase 4 batch 28 (2026-05-04): Archangel's Staff / Seraph's Embrace ──
    # AP-side Awe twins of the Manamune family (batch 27). Same "Awe" name,
    # but different math — Archangel/Seraph's are keyed off BONUS mana
    # (item-contributed only), while Manamune/Muramana are keyed off MAX
    # mana (champion base + items). The new
    # ``bonus_ap_pct_bonus_mp`` field captures the AP-side variant; engine.py
    # walks it after the existing Awe-AD walk, targeting ap_flat instead of
    # ad_flat, sourced from ``item_totals.get("mp_flat", 0.0)`` (which is
    # the build's bonus mana sum). Manaflow stack-up + Archangel's
    # transformation into Seraph's at +360 max mana stacks intentionally
    # not modeled — same call as Manamune (steady-state assumption).

    "3003": ItemEffect(
        item_id="3003",
        name="Archangel's Staff",
        # Awe: 1% bonus mana as Ability Power. Stat block: 70 AP / 600 mana
        # / 25 AH (DDragon 16.9.1; Meraki passive text confirms 1% bonus
        # mana). Ezreal lvl 11 + Archangel: champion base mp ≈ 1075 not
        # counted; bonus mana = 600 → Awe AP = 0.01 * 600 = 6 AP. Stack
        # mana items to lift further (Manamune adds 500 bonus mana → +5
        # AP from Archangel's Awe; Tear of the Goddess builds from this
        # baseline).
        bonus_ap_pct_bonus_mp=0.01,
        # No unique_passive_key — Archangel/Seraph's are one-of-two, but
        # build-legality (transformation gate prevents owning both) is
        # ranker-owned per the s81 pattern.
        note="Archangel's Staff: Awe +1% bonus mana as AP (Manaflow stack-up not modeled — steady-state)",
    ),

    "3040": ItemEffect(
        item_id="3040",
        name="Seraph's Embrace",
        # Awe: 2% bonus mana as AP (post-transformation form, double the
        # Archangel coefficient). Stat block: 70 AP / 1000 mana / 25 AH
        # — Seraph's adds 1000 bonus mana baseline, so its Awe alone
        # contributes 0.02 * 1000 = 20 AP from the item's own mana, lifting
        # further with each additional mana item in the build.
        # Lifeline shield (350 + max-mana% shield at <30% HP) is non-DPS;
        # tagged ``unique_passive_key="lifeline"`` so collect_effects
        # dedups against Shieldbow / Sterak's / Maw / Phantom Dancer
        # (which uses Spectral Waltz, NOT lifeline — see batch 12). The
        # Awe walk lives in engine.py and bypasses collect_effects, so
        # the AP contribution survives any lifeline dedup.
        bonus_ap_pct_bonus_mp=0.02,
        unique_passive_key="lifeline",
        note=(
            "Seraph's Embrace: Awe +2% bonus mana as AP + Lifeline "
            "(low-HP mana shield, deduped — no DPS contribution from "
            "the shield piece)"
        ),
    ),
    # ── Phase 4 batch 29 (2026-05-04): coverage batch — defensive_only +
    # 2 partial promotions (Liandry's Suffering damage amp, Stormsurge
    # flat magic pen). Coverage-completeness; no new schema fields. The
    # 4 defensive_only entries surface "we considered this and decided
    # no DPS contribution applies" with one-line notes — same template
    # as the existing high-pickrate defensive_only entries from batches
    # 1-3. The 2 partial promotions reuse existing schema (damage_amp_pct
    # from batch 14, magic_pen_flat from batch 4).

    "6697": ItemEffect(
        item_id="6697",
        name="Hubris",
        # Phase 4 batch 30 (2026-05-04): promoted from defensive_only via
        # the lethality plumbing schema. 18 Lethality is now level-scaled
        # via effective_target_armor's level parameter. Eminence remains
        # defensive — takedown-bound bonus AD stack stays not-modeled
        # (would need an event-driven AD-bonus schema; same family as
        # Hubris-shape items: Opportunity's takedown lethality bonus,
        # Stormsurge's Stormraider applies-on-burst, etc.).
        lethality=18.0,
        note=(
            "Hubris: 18 Lethality (level-scaled flat pen) + Eminence "
            "takedown-bound bonus AD stack (90s, not modeled)"
        ),
    ),

    "3065": ItemEffect(
        item_id="3065",
        name="Spirit Visage",
        # 400 HP + 50 MR + 10 AH + 100% base regen. Boundless Vitality
        # (heal/shield amp 25%) is non-DPS — engine doesn't model healing
        # output. Pure defensive.
        defensive_only=True,
        note="Spirit Visage: Boundless Vitality (heal/shield +25%); no DPS contribution",
    ),

    "2504": ItemEffect(
        item_id="2504",
        name="Kaenic Rookern",
        # 400 HP + 80 MR + 100% regen. Magebane: gain magic shield after
        # 15s of not taking magic damage. Pure defensive — no DPS path.
        defensive_only=True,
        note="Kaenic Rookern: Magebane (low-MR-uptime magic shield); no DPS contribution",
    ),

    "6653": ItemEffect(
        item_id="6653",
        name="Liandry's Torment",
        # 60 AP + 300 HP stat block. Two passives:
        # - Torment: ability damage burn — ~6% target max HP magic over
        #   3s. Ability-bound, NOT in basic auto rotation. Same rule as
        #   Spear of Shojin (batch 16) — engine doesn't model ability
        #   damage.
        # - Suffering: 2% bonus damage per second in combat, max 3
        #   stacks = 6%. Generic damage amp, not ability-restricted —
        #   applies to autos + procs same as Riftmaker's Void Corruption
        #   (batch 14). Steady-state DPS pin = 6% (full ramp after 3s
        #   in combat). Promoted via the existing damage_amp_pct schema.
        damage_amp_pct=0.06,
        note=(
            "Liandry's Torment: Suffering ~6% damage amp at full ramp "
            "(3s in champ combat; sustained-DPS approximation) + "
            "Torment burn (ability-bound, not modeled)"
        ),
    ),

    "4629": ItemEffect(
        item_id="4629",
        name="Cosmic Drive",
        # 70 AP + 350 HP + 25 AH + 4% MS stat block. Spelldance: 20 bonus
        # MS for 4s on dealing magic/true damage to champions. Pure
        # utility (movement speed); no DPS contribution.
        defensive_only=True,
        note="Cosmic Drive: Spelldance (MS bonus on magic/true damage); no DPS contribution",
    ),

    "4646": ItemEffect(
        item_id="4646",
        name="Stormsurge",
        # 90 AP + 15 flat magic pen + 6% MS stat block (the 15 magic pen
        # is in the description text, NOT in DDragon's stat block keys).
        # Two ability-bound passives:
        # - Stormraider: 25% max-HP-in-2.5s gate to apply Squall.
        # - Squall: 2s after Stormraider, deal 125 + 10% AP magic.
        # Both are ability-bound and conditional — NOT modeled (same
        # rule as Hextech Rocketbelt, Luden's, etc.). The 15 flat magic
        # pen IS modeled here via magic_pen_flat — joins Sorcerer's
        # Shoes (12) and Shadowflame (15) in the magic pen layer.
        # Magic-pen contribution alone is real DPS uplift, so this
        # entry is NOT defensive_only.
        magic_pen_flat=15.0,
        note=(
            "Stormsurge: 15 flat magic pen (magical) + Stormraider/Squall "
            "ability-bound burst (not modeled; same rule as Rocketbelt)"
        ),
    ),

    # ── Phase 4 batch 30 (2026-05-04): lethality plumbing — new entries ──
    # Axiom Arc and Umbral Glaive were unmodeled prior; now land via the
    # lethality schema alongside the 5 in-place updates above (Hubris,
    # Voltaic, Edge of Night, Youmuu's, Opportunity). All 7 lethality items
    # in current League now carry the level-scaled flat pen contribution.

    "6696": ItemEffect(
        item_id="6696",
        name="Axiom Arc",
        # 55 AD + 18 Lethality + 20 AH stat block (lethality in description,
        # NOT in DDragon's stats keys). Flux passive: takedown within 3s of
        # damage refunds Ultimate Ability cooldown. Pure utility (CDR is
        # not modeled; no DPS proc). Defensive_only=False because the 18
        # Lethality alone is real DPS contribution.
        lethality=18.0,
        note=(
            "Axiom Arc: 18 Lethality (level-scaled flat pen) + Flux ult-CDR "
            "on takedown (utility, not modeled)"
        ),
    ),

    "3179": ItemEffect(
        item_id="3179",
        name="Umbral Glaive",
        # 60 AD + 18 Lethality + 15 AH stat block. Two passives:
        # - Nightstalker: after-stealth next attack vs champion deals
        #   bonus true damage. Stealth-conditional + after-event — same
        #   "ability-bound burst" rule that defers Stormsurge's Squall.
        # - Blackout: reveal stealth wards / bonus damage to wards. Pure
        #   utility / target-type-restricted (engine targets champions).
        # Lethality alone is the modeled DPS piece.
        lethality=18.0,
        note=(
            "Umbral Glaive: 18 Lethality (level-scaled flat pen) + "
            "Nightstalker after-stealth true damage (conditional, not "
            "modeled) + Blackout ward damage (utility, not modeled)"
        ),
    ),


    # ── Phase 4 batch 31 (2026-05-04): support / ramp item coverage sweep ──
    # 21 items. 2 partial promotions (Dead Man's Plate Shipwrecker physical proc;
    # Spectral Cutlass ARAM-only lethality — same schema as batch 30). 19
    # defensive_only entries: support-role items, sustain amplifiers, conditional-
    # or-ability-bound passives that don't fit the basic-auto DPS model.
    # Defensive_only count: 21 → 40.

    # ─── Dead Man's Plate — Shipwrecker partial promotion ───────────────────
    # 350 HP + 55 armor + 4% MS stat block. Two passives:
    # - Shipwrecker: while moving, build Momentum stacks (7/0.25s = 28/s,
    #   cap 100 stacks in ~3.57s). Next attack consumes all stacks to deal
    #   100 + 45% of built-up bonus MS (max 20 bonus MS at 100 stacks)
    #   bonus physical damage. Damage at full Momentum = 100 + 0.45×20 = 109.
    #   Approximated as every_n_attacks=4 (3.57s build-up at 1.0 AS melee
    #   cadence; assumes continuous movement in combat).
    # - Unsinkable: 15% slow resistance — utility, not modeled.
    # Approximation caveats: ignores other sources of bonus MS (champions with
    # high MS or MS-stacking builds get more damage); assumes full stacks on
    # discharge (fair for standard melee rotations where movement is continuous).
    "3742": ItemEffect(
        item_id="3742",
        name="Dead Man's Plate",
        periodics=(PeriodicProc(
            name="Shipwrecker",
            bonus_damage=109.0,  # 100 + 0.45 × 20 bonus MS at full Momentum stacks
            damage_type=PHYSICAL,
            every_n_attacks=4,
        ),),
        note=(
            "Dead Man's Plate: Shipwrecker ~109 physical (100 + 45% max Momentum "
            "bonus MS) every ~4 attacks (assumes full stacks at discharge; "
            "Unsinkable slow resist not modeled)"
        ),
    ),

    # ─── Spectral Cutlass — ARAM-only lethality promotion ───────────────────
    # 50 AD + 15 Lethality + 4% MS stat block (ARAM-only, map 12 only).
    # Soul Anchor active (0s listed CD in DDragon): marks current location;
    # returns you there after 4s or on recast. Pure repositioning utility —
    # not modeled (same rule as all other utility actives in this batch).
    # Lethality modeled via the batch-30 level-scaled schema (same 15 Lethality
    # coefficient as Edge of Night). Item available on map 12 (ARAM) only;
    # aram_coach's resolver uses mode='aram' and DDragon map 12 index.
    "4004": ItemEffect(
        item_id="4004",
        name="Spectral Cutlass",
        lethality=15.0,
        note=(
            "Spectral Cutlass: 15 Lethality (level-scaled flat pen, ARAM-only) "
            "+ Soul Anchor repositioning active (utility, not modeled)"
        ),
    ),

    # ─── Support / enchanter items — defensive_only ──────────────────────────
    # All entries below have effects that are non-DPS (ally healing/shielding
    # triggers, ally-proc-bound damage, enemy-on-champion-only burst gated by
    # ability casts, MS/AS conditional on ally link, etc.). No direct
    # basic-auto DPS contribution from any passive here.

    "3109": ItemEffect(
        item_id="3109",
        name="Knight's Vow",
        defensive_only=True,
        note="Knight's Vow: Worthy tether (damage redirect + ally tankiness); no DPS contribution",
    ),
    "3222": ItemEffect(
        item_id="3222",
        name="Mikael's Blessing",
        defensive_only=True,
        note="Mikael's Blessing: active CC cleanse + heal; no DPS contribution",
    ),
    "3107": ItemEffect(
        item_id="3107",
        name="Redemption",
        defensive_only=True,
        # Active calls a heal beam after 2.5s — the healing dominates the
        # use-case; the incidental magic damage to enemies is negligible
        # (10% target max HP, CD null in Meraki, per-heal-not-per-auto).
        note="Redemption: active AoE heal beam (incidental enemy damage; ability-bound); no sustained DPS contribution",
    ),
    "3190": ItemEffect(
        item_id="3190",
        name="Locket of the Iron Solari",
        defensive_only=True,
        note="Locket of the Iron Solari: active AoE shield; no DPS contribution",
    ),
    "3504": ItemEffect(
        item_id="3504",
        name="Ardent Censer",
        defensive_only=True,
        # Healer-triggered AS/on-hit buff to allies. Caster's own AS +
        # on-hit magic buff applies only after healing/shielding an ally —
        # not a sustained per-auto DPS proc.
        note="Ardent Censer: Sanctified (heal/shield triggers AS + on-hit AP buff); no standalone DPS contribution",
    ),
    "6616": ItemEffect(
        item_id="6616",
        name="Staff of Flowing Water",
        defensive_only=True,
        note="Staff of Flowing Water: heal/shield grants Rapids (AP + AH) to allies; no DPS contribution",
    ),
    "6620": ItemEffect(
        item_id="6620",
        name="Echoes of Helia",
        defensive_only=True,
        # Soul Siphon: damage dealt generates Soul Charges used for target
        # healing pulses. Converts DPS into sustain — not a damage amplifier.
        note="Echoes of Helia: Soul Siphon (damage → Soul Charges → heal pulses); no DPS contribution",
    ),
    "6617": ItemEffect(
        item_id="6617",
        name="Moonstone Renewer",
        defensive_only=True,
        note="Moonstone Renewer: Starlit Grace (heal chains to nearby allies in combat); no DPS contribution",
    ),
    "6621": ItemEffect(
        item_id="6621",
        name="Dawncore",
        defensive_only=True,
        note="Dawncore: support scaling (AP scales with heal/shield power); no DPS contribution",
    ),
    "4005": ItemEffect(
        item_id="4005",
        name="Imperial Mandate",
        defensive_only=True,
        # Coordinated Fire: ability-CC marks target; ALLIED champion attack
        # on marked target deals bonus damage. Requires ally proc — not a
        # self-basic-auto DPS contribution.
        note="Imperial Mandate: Coordinated Fire (ally proc on CC'd target); no solo DPS contribution",
    ),
    "6657": ItemEffect(
        item_id="6657",
        name="Rod of Ages",
        defensive_only=True,
        # Eternity converts damage taken → mana; mana used → HP. Stacked
        # passive HP/MP/AP ramping (30 stacks over 6 min). Sustain and
        # scaling, not a DPS proc.
        note="Rod of Ages: Eternity (damage→mana, mana→HP sustain ramp); no DPS contribution",
    ),
    "3119": ItemEffect(
        item_id="3119",
        name="Winter's Approach",
        defensive_only=True,
        # 400 HP + 500 mana + 15 AH. Awe (same name as Manamune family):
        # gain HP = 8% of max mana. HP-conversion, not AD or AP.
        # Same transformation mechanic as the Manamune family (transforms
        # into Fimbulwinter at +700 stacked mana); stays defensive_only
        # because the HP contribution doesn't affect DPS.
        note="Winter's Approach: Awe (8% max mana as bonus HP); no DPS contribution",
    ),
    "3121": ItemEffect(
        item_id="3121",
        name="Fimbulwinter",
        defensive_only=True,
        # 400 HP + 1000 mana + 15 AH. Post-transformation form of Winter's
        # Approach. Everfrost passive: first ability hit in combat freezes
        # target briefly. CC utility, ability-bound — not a per-auto DPS proc.
        note="Fimbulwinter: Awe (8% max mana as HP) + Everfrost CC on first ability hit (ability-bound utility); no DPS contribution",
    ),
    "4401": ItemEffect(
        item_id="4401",
        name="Force of Nature",
        defensive_only=True,
        # Steadfast: taking magic damage generates stacks (up to 8, +6 MR
        # each). Resistor: 30 bonus MR at 8 stacks. Pure defensive stacking.
        note="Force of Nature: Steadfast (MR stacks on magic-damage-taken); no DPS contribution",
    ),
    "3116": ItemEffect(
        item_id="3116",
        name="Rylai's Crystal Scepter",
        defensive_only=True,
        # Rimefrost: ability damage slows by 30% for 1s. CC utility —
        # not a damage proc (same rule as Stridebreaker's Halting Slash,
        # Serylda's Bitter Cold).
        note="Rylai's Crystal Scepter: Rimefrost (ability damage slow); no DPS contribution",
    ),
    "6665": ItemEffect(
        item_id="6665",
        name="Jak'Sho, The Protean",
        defensive_only=True,
        # Voidborn Resilience: gain stacks in combat each second, each granting
        # 2 armor + 2 MR (up to 8 stacks = 16 armor + 16 MR). Pure defensive.
        note="Jak'Sho, The Protean: Voidborn Resilience (stacking resists in combat); no DPS contribution",
    ),
    "3152": ItemEffect(
        item_id="3152",
        name="Hextech Rocketbelt",
        defensive_only=True,
        # Active: dash + arc of 7 rockets, each dealing magic damage.
        # Cooldown null in Meraki bulk (same blocker as other null-CD actives).
        # Multi-rocket formula doesn't fit the single-proc periodic model
        # cleanly; the empowered-ability bonus is ability-cast-bound.
        note="Hextech Rocketbelt: multi-rocket active (null CD in Meraki, multi-projectile formula; ability-cast empowerment not modeled)",
    ),
    "3073": ItemEffect(
        item_id="3073",
        name="Experimental Hexplate",
        defensive_only=True,
        # Overdrive: ult cast triggers 50% bonus AS + 20% bonus MS for 8s
        # (30s CD). Conditional on ult usage — ability-cast schema blocker,
        # same rule as Spear of Shojin (batch 16). 30 ult haste is stat-side
        # only.
        note="Experimental Hexplate: Overdrive (ult-cast-triggered AS + MS burst); ability-cast schema blocker; no sustained DPS contribution",
    ),
    "8020": ItemEffect(
        item_id="8020",
        name="Abyssal Mask",
        magic_amp_pct=0.12,
        note=(
            "Abyssal Mask: Unmake 12% more magic damage taken by nearby enemies "
            "(700-unit aura; sustained-DPS assumption = always active; "
            "applies to magical proc DPS only via magic_amp_pct schema)"
        ),
    ),

    # ── Phase 4 batch 32 (2026-05-04): AP amplification + lethality + new schema ──
    # 7 active promotions (2 new schema fields + 5 reuse existing):
    # Rabadon's Deathcap (ap_amp_pct=0.30), Dusk and Dawn (spellblade),
    # The Collector + Prowler's Claw + Bastionbreaker (lethality),
    # Overlord's Bloodmail (bonus_ad_pct_bonus_hp), Demonic Embrace
    # (ap_per_bonus_hp_pct). 8 defensive_only entries.

    "3089": ItemEffect(
        item_id="3089",
        name="Rabadon's Deathcap",
        ap_amp_pct=0.30,
        note=(
            "Rabadon's Deathcap: Magical Opus +30% total AP (multiplicative; "
            "amplifies all AP-scaling procs and pen formulas via CallContext.ap)"
        ),
    ),
    "2510": ItemEffect(
        item_id="2510",
        name="Dusk and Dawn",
        periodics=(PeriodicProc(
            name="Spellblade",
            bonus_damage=lambda c: 0.75 * c.base_ad + 0.10 * c.ap,
            damage_type=MAGICAL,
            every_n_seconds=1.5,
        ),),
        unique_passive_key="spellblade",
        note=(
            "Dusk and Dawn: Spellblade 75% base AD + 10% AP bonus magic "
            "damage every ~1.5s; joins Trinity Force / Lich Bane / ER / "
            "Iceborn Gauntlet spellblade dedup family; on-hit echo not modeled"
        ),
    ),
    "667666": ItemEffect(
        item_id="667666",
        name="The Collector",
        lethality=10.0,
        note=(
            "The Collector: 10 Lethality (level-scaled flat pen). "
            "Death execute (<5% HP) is utility, not modeled"
        ),
    ),
    "6693": ItemEffect(
        item_id="6693",
        name="Prowler's Claw",
        lethality=22.0,
        note=(
            "Prowler's Claw: 22 Lethality (level-scaled flat pen). "
            "Ambush Predator active is utility, not modeled"
        ),
    ),
    "2520": ItemEffect(
        item_id="2520",
        name="Bastionbreaker",
        lethality=22.0,
        note=(
            "Bastionbreaker: 22 Lethality (level-scaled flat pen). "
            "Shaped Charge ability-damage passive deferred (ability-cast schema gap)"
        ),
    ),
    "2501": ItemEffect(
        item_id="2501",
        name="Overlord's Bloodmail",
        bonus_ad_pct_bonus_hp=0.025,
        note=(
            "Overlord's Bloodmail: Tyranny 2.5% bonus HP as bonus AD "
            "(engine resolves at stat-build time via item_totals[hp_flat]). "
            "Retribution missing-HP-scaled AD not modeled (combat ramp)"
        ),
    ),
    "4637": ItemEffect(
        item_id="4637",
        name="Demonic Embrace",
        ap_per_bonus_hp_pct=0.02,
        periodics=(
            PeriodicProc(
                name="Azakana's Gaze",
                every_n_seconds=1.0,
                bonus_damage=lambda c: 0.01 * c.target_max_hp,
                damage_type=MAGICAL,
            ),
        ),
        note=(
            "Demonic Embrace: Dark Pact 2% bonus HP as AP (stat walk). "
            "Azakana's Gaze: 1% target max HP/s magic burn (ranged value; "
            "melee is 2%/s — conservative under sustained-DPS assumption; "
            "ability-trigger modeled as sustained per the always-active convention)"
        ),
    ),
    # ── defensive_only (8) ──
    "3165": ItemEffect(
        item_id="3165",
        name="Morellonomicon",
        defensive_only=True,
        note="Morellonomicon: Grievous Wounds (anti-heal utility); no DPS contribution",
    ),
    "4628": ItemEffect(
        item_id="4628",
        name="Horizon Focus",
        defensive_only=True,
        note=(
            "Horizon Focus: Hypershot 15% damage amp requires range 600+ and ability "
            "hit (range conditional + ability-cast schema gap); no sustained DPS contribution"
        ),
    ),
    "3118": ItemEffect(
        item_id="3118",
        name="Malignance",
        defensive_only=True,
        note=(
            "Malignance: Hatefog 15% damage amp requires ultimate hit "
            "(ultimate-cast schema gap); Scorn 20 ult haste is utility"
        ),
    ),
    "2503": ItemEffect(
        item_id="2503",
        name="Blackfire Torch",
        periodics=(
            PeriodicProc(
                name="Baleful Blaze",
                every_n_seconds=0.5,
                bonus_damage=lambda c: 6.0 + 0.06 * c.ap,
                damage_type=MAGICAL,
            ),
        ),
        note=(
            "Blackfire Torch: Baleful Blaze 6 + 6% AP magic damage every 0.5s "
            "(ranged value per Meraki {{ap|60/6}} melee/ranged split at 1/s cadence; "
            "ability-trigger modeled as sustained per the always-active convention; "
            "Blackfire AP stacking ramp utility-only)"
        ),
    ),
    "2517": ItemEffect(
        item_id="2517",
        name="Endless Hunger",
        defensive_only=True,
        note=(
            "Endless Hunger: Famine (bonus AD ability haste scaling) and "
            "Feast (takedown omnivamp) are utility; no DPS contribution"
        ),
    ),
    "6609": ItemEffect(
        item_id="6609",
        name="Chempunk Chainsword",
        defensive_only=True,
        note="Chempunk Chainsword: Hackshorn (Grievous Wounds from physical damage); no DPS contribution",
    ),
    "2523": ItemEffect(
        item_id="2523",
        name="Hexoptics C44",
        defensive_only=True,
        note=(
            "Hexoptics C44: Magnification up to 10% increased attack damage at 600 range "
            "(range-conditional, fight distance unknown); Arcane Aim takedown bonus is utility"
        ),
    ),
    "8010": ItemEffect(
        item_id="8010",
        name="Bloodletter's Curse",
        defensive_only=True,
        note=(
            "Bloodletter's Curse: Vile Decay ability-stacking 40% magic pen "
            "(ability-cast schema gap; sustained pen requires 3+ applications); "
            "deferred pending ability-cast schema"
        ),
    ),
    # ── Phase 4 batch 33 (2026-05-04): ability-burn promos + dual-pen + caster-HP burn ──
    # Gambler's Blade (667101): 15 lethality + 15 magic pen flat (dual-pen item).
    # Adaptive Force (55) has a DDragon stats-block gap — not carried as AD or AP in
    # aggregate_item_stats. Contribution modeled via pen only.
    "667101": ItemEffect(
        item_id="667101",
        name="Gambler's Blade",
        lethality=15.0,
        magic_pen_flat=15.0,
        note=(
            "Gambler's Blade: 15 lethality + 15 magic pen flat (dual-pen). "
            "Adaptive Force 55 has DDragon stats-block gap — not in aggregate_item_stats; "
            "pen contribution only"
        ),
    ),
    # Unending Despair (2502): Agony — 3% caster bonus HP magic damage every 4s.
    # Meraki: 3% bonus HP to self and nearest ally as magic. Using self-damage value only
    # (the ally component is utility). Caster-bonus-HP-scaled proc via caster_bonus_hp.
    "2502": ItemEffect(
        item_id="2502",
        name="Unending Despair",
        periodics=(
            PeriodicProc(
                name="Agony",
                every_n_seconds=4.0,
                bonus_damage=lambda c: 0.03 * c.caster_bonus_hp,
                damage_type=MAGICAL,
            ),
        ),
        note=(
            "Unending Despair: Agony 3% caster bonus HP magic damage every 4s "
            "(proc AoE to enemy; ally self-heal component utility-only; "
            "caster_bonus_hp = item_totals[hp_flat] proxy same as Titanic/Heartsteel)"
        ),
    ),
    # ── defensive_only (7) ──
    "4636": ItemEffect(
        item_id="4636",
        name="Night Harvester",
        defensive_only=True,
        note=(
            "Night Harvester: Soulrend 30s CD mythic proc — damage value not in "
            "DDragon/Meraki description and varies by level; deferred pending "
            "periodic-with-level-scale schema or explicit formula lookup"
        ),
    ),
    "2512": ItemEffect(
        item_id="2512",
        name="Fiendhunter Bolts",
        defensive_only=True,
        note=(
            "Fiendhunter Bolts: Bolt Detonation periodic proc value not confirmed "
            "from DDragon/Meraki; deferred pending formula verification"
        ),
    ),
    "663060": ItemEffect(
        item_id="663060",
        name="Sword of the Divine",
        defensive_only=True,
        note=(
            "Sword of the Divine: Pact of the Blade conditional 100% crit guarantee "
            "on ability (ability-cast schema gap); stat block AS bonus only"
        ),
    ),
    "667112": ItemEffect(
        item_id="667112",
        name="Flesheater",
        defensive_only=True,
        note=(
            "Flesheater: Consume flat armor reduction requires ability hit "
            "(armor_reduction_flat schema gap; flat shred not yet modeled); "
            "Adaptive Force has DDragon stats-block gap"
        ),
    ),
    "664011": ItemEffect(
        item_id="664011",
        name="Sword of Blossoming Dawn",
        defensive_only=True,
        note=(
            "Sword of Blossoming Dawn: Bloom passive is heal/shield (utility); "
            "no DPS contribution"
        ),
    ),
    "2522": ItemEffect(
        item_id="2522",
        name="Actualizer",
        defensive_only=True,
        note=(
            "Actualizer: Actualize damage amp requires ally within 1000 range "
            "(ally-proximity conditional not modelable without fight geometry)"
        ),
    ),
    "667109": ItemEffect(
        item_id="667109",
        name="Cruelty",
        defensive_only=True,
        note=(
            "Cruelty: Execute damage amp below 50% HP (missing-HP conditional "
            "not modelable under sustained-DPS assumption)"
        ),
    ),
    # ── Phase 4 batch 35 (2026-05-04): missed-lethality + dual-pen + spellblade + on-hit ──
    # Duskblade of Draktharr (6691): missed from batch-30 lethality sweep.
    # Nightstalker unique-proc (large burst on first attack after stealth) is
    # conditional on vision/stealth mechanics — not sustained, not modeled.
    "6691": ItemEffect(
        item_id="6691",
        name="Duskblade of Draktharr",
        lethality=18.0,
        note=(
            "Duskblade of Draktharr: 18 lethality (missed from batch 30 sweep). "
            "Nightstalker proc requires post-stealth first attack (stealth conditional, "
            "not sustained-DPS modelable)"
        ),
    ),
    # Perplexity (4015): 22% armor pen + 30% magic pen dual-pen item (Arena/special pool).
    # Giant Slayer passive deals up to 15% more damage against targets with greater
    # max HP than caster (0.6% per 100 HP difference, based on MAX HP difference NOT
    # bonus HP) — requires new schema (target_max_hp vs caster_max_hp); deferred.
    "4015": ItemEffect(
        item_id="4015",
        name="Perplexity",
        armor_pen_pct=0.22,
        magic_pen_pct=0.30,
        note=(
            "Perplexity: 22% armor pen + 30% magic pen (dual-pen; both pen fields "
            "wire into existing effective_target_armor + effective_target_mr helpers). "
            "Giant Slayer (0-15% based on target-vs-caster max HP difference) deferred "
            "— needs separate max_hp_diff_amp schema distinct from bonus-HP-keyed LDR"
        ),
    ),
    # Divine Sunderer (6632): Spellblade physical variant — 125% base AD + 6% target max
    # HP bonus physical on next attack after ability cast, ~3s cadence. Joins the
    # "spellblade" unique-passive family (Trinity Force / Lich Bane / ER / Iceborn /
    # Dusk+Dawn). Heal component (Sandforce: same damage distributed across nearby
    # allies as HP) is utility-only. Patch 16.9.1 values.
    "6632": ItemEffect(
        item_id="6632",
        name="Divine Sunderer",
        periodics=(
            PeriodicProc(
                name="Spellblade",
                every_n_seconds=3.0,
                bonus_damage=lambda c: 1.25 * c.base_ad + 0.06 * c.target_max_hp,
                damage_type=PHYSICAL,
            ),
        ),
        unique_passive_key="spellblade",
        note=(
            "Divine Sunderer: Spellblade 125% base AD + 6% target max HP physical "
            "every ~3s (joins spellblade dedup family; Sandforce heal utility-only)"
        ),
    ),
    # Navori Flickerblade (6672): Bring It Down — every 3rd basic attack deals bonus
    # physical damage on-hit, scaling 120→168 (ranged) over levels 1→13.
    # Quicken (CDR on crit) is utility-only.
    "6672": ItemEffect(
        item_id="6672",
        name="Navori Flickerblade",
        periodics=(
            PeriodicProc(
                name="Bring It Down",
                every_n_attacks=3,
                bonus_damage=lambda c: min(168.0, 120.0 + 4.0 * (c.level - 1)),
                damage_type=PHYSICAL,
            ),
        ),
        note=(
            "Navori Flickerblade: Bring It Down 120→168 bonus physical every 3rd attack "
            "(ranged scaling 120 + 4 × (level-1), capped at 168 at level 13+; "
            "Quicken CDR-on-crit utility-only)"
        ),
    ),
    # Hellfire Hatchet (4017): 12 lethality. Char proc is ability-triggered burn
    # scaling off target max HP AND lethality — requires ability-cast + new
    # lethality-in-formula schema; deferred.
    "4017": ItemEffect(
        item_id="4017",
        name="Hellfire Hatchet",
        lethality=12.0,
        note=(
            "Hellfire Hatchet: 12 lethality (pen contribution modeled). "
            "Char ability-triggered burn scales target max HP × lethality "
            "(ability-cast schema gap + lethality-in-formula gap; deferred)"
        ),
    ),
    # ── defensive_only (6) ──
    "6630": ItemEffect(
        item_id="6630",
        name="Goredrinker",
        defensive_only=True,
        note=(
            "Goredrinker: Thirsting Slash is an active ability (no passive DPS proc); "
            "Resolve 8% omnivamp is lifesteal (utility); no DPS contribution"
        ),
    ),
    "6671": ItemEffect(
        item_id="6671",
        name="Galeforce",
        defensive_only=True,
        note=(
            "Galeforce: Cloudburst is an active ability (no passive proc); "
            "Courage speed-boost is utility; no DPS contribution"
        ),
    ),
    "3050": ItemEffect(
        item_id="3050",
        name="Zeke's Convergence",
        defensive_only=True,
        note=(
            "Zeke's Convergence: Frostfire Tempest + Cryocombustion require "
            "tether-ally proximity (support aura; no caster-DPS contribution)"
        ),
    ),
    "4016": ItemEffect(
        item_id="4016",
        name="Wordless Promise",
        defensive_only=True,
        note=(
            "Wordless Promise: Promise heal/shield passive (utility); no DPS contribution"
        ),
    ),
    "4014": ItemEffect(
        item_id="4014",
        name="Frozen Mallet",
        defensive_only=True,
        note=(
            "Frozen Mallet: Icy slow on basic attacks (utility); no DPS contribution"
        ),
    ),
    "4013": ItemEffect(
        item_id="4013",
        name="Lightning Braid",
        defensive_only=True,
        note=(
            "Lightning Braid: Chain Lightning fires on ability hit (ability-cast schema gap); "
            "also applies -20% ability damage reduction (DPS-negative) so net contribution "
            "for casters is unclear; deferred"
        ),
    ),
    # ── Phase 4 batch 36 (2026-05-04): Arena item sweep + Rite of Ruin crit ──
    # Detonation Orb (447113): 12 flat magic pen (Detonation Orb stat block).
    # The Bomb stored-damage passive requires ability damage tracking (deferred).
    "447113": ItemEffect(
        item_id="447113",
        name="Detonation Orb",
        magic_pen_flat=12.0,
        note=(
            "Detonation Orb: 12 flat magic pen (existing schema). "
            "The Bomb stored 20% ability damage release deferred (ability-cast schema gap)"
        ),
    ),
    # Reverberation (447114): Resonate on-hit — 10 + 2% caster bonus HP magic per attack.
    # Reverberate HP-at-combat-start and Rumble immobilize-stacks are utility/conditional.
    "447114": ItemEffect(
        item_id="447114",
        name="Reverberation",
        periodics=(
            PeriodicProc(
                name="Resonate",
                every_n_attacks=1,
                bonus_damage=lambda c: 10.0 + 0.02 * c.caster_bonus_hp,
                damage_type=MAGICAL,
            ),
        ),
        note=(
            "Reverberation: Resonate 10 + 2% caster bonus HP magic on-hit (same schema as "
            "Titanic Hydra Cleave, keyed off caster_bonus_hp). "
            "Reverberate HP-per-AS and Rumble stacks utility-only"
        ),
    ),
    # Pyromancer's Cloak (447118): Spark (5s CD) — attack or ability hit burns target
    # for 100→350 magic over 3s (total burn; Meraki melee value). Modeled as
    # every_n_seconds=5.0 with total_damage as bonus_damage (same convention as
    # Hextech Gunblade's Lightning Bolt). Cleansing Flame fireball AoE deferred.
    "447118": ItemEffect(
        item_id="447118",
        name="Pyromancer's Cloak",
        periodics=(
            PeriodicProc(
                name="Spark",
                every_n_seconds=5.0,
                bonus_damage=lambda c: 100.0 + 250.0 / 17.0 * (c.level - 1),
                damage_type=MAGICAL,
            ),
        ),
        note=(
            "Pyromancer's Cloak: Spark 100→350 magic burn over 3s every 5s "
            "(melee Meraki value; total burn modeled as single proc per event; "
            "Cleansing Flame fireball AoE deferred)"
        ),
    ),
    # Lightning Rod (447119): Call Lightning — autocast every 16s: 135→230 magic
    # + 30% bonus AD + 50% AP + 10% target max HP. Fully Automated reduces CD via
    # AH (not modeled; pins at 16s base). Uses level + bonus_ad + ap + target_max_hp —
    # all existing CallContext fields.
    "447119": ItemEffect(
        item_id="447119",
        name="Lightning Rod",
        periodics=(
            PeriodicProc(
                name="Call Lightning",
                every_n_seconds=16.0,
                bonus_damage=lambda c: (
                    (135.0 + 95.0 / 17.0 * (c.level - 1))
                    + 0.30 * c.bonus_ad
                    + 0.50 * c.ap
                    + 0.10 * c.target_max_hp
                ),
                damage_type=MAGICAL,
            ),
        ),
        note=(
            "Lightning Rod: Call Lightning 135→230 + 30% bonus AD + 50% AP + 10% target max HP "
            "magic every 16s (base CD; Fully Automated AH reduction not modeled, "
            "pins at 16s conservative value)"
        ),
    ),
    # Regicide (447115): 15 lethality. End the Line takedown-conditional bonus deferred.
    "447115": ItemEffect(
        item_id="447115",
        name="Regicide",
        lethality=15.0,
        note=(
            "Regicide: 15 lethality (existing schema). "
            "End the Line takedown-vs-Regent bonus deferred (takedown conditional)"
        ),
    ),
    # Rite of Ruin (3430): Wrath and Ruin — 2.5% crit per ability cast, up to 8 stacks
    # = 20% crit. Pinned at max stacks per sustained-DPS convention (same as Yun Tal
    # Wildarrows' flat-stacks pin). Salvage the Wreckage shield is utility-only.
    "3430": ItemEffect(
        item_id="3430",
        name="Rite Of Ruin",
        crit_chance_bonus_flat=0.20,
        note=(
            "Rite Of Ruin: Wrath and Ruin max 8 stacks = 20% bonus crit chance "
            "(pinned at full stacks per sustained-DPS convention; same schema as Yun Tal). "
            "Salvage the Wreckage ability-chance shield utility-only"
        ),
    ),
    # ── defensive_only (6) ──
    "447108": ItemEffect(
        item_id="447108",
        name="Runecarver",
        defensive_only=True,
        note=(
            "Runecarver: Spiral Out fires missiles per Rune stack on Energized proc — "
            "Rune-stack layer on top of Energized mechanic is too complex for sustained model; "
            "deferred"
        ),
    ),
    "447116": ItemEffect(
        item_id="447116",
        name="Kinkou Jitte",
        defensive_only=True,
        note=(
            "Kinkou Jitte: Between the Ribs deals extra damage through positional weakpoint "
            "(directional conditional not modelable without fight geometry)"
        ),
    ),
    "447120": ItemEffect(
        item_id="447120",
        name="Diamond-Tipped Spear",
        defensive_only=True,
        note=(
            "Diamond-Tipped Spear: Sweet Spot 0-30% damage amp scales with fight distance "
            "(range conditional not modelable); Reach Weapon +75 range utility-only"
        ),
    ),
    "447121": ItemEffect(
        item_id="447121",
        name="Twilight's Edge",
        defensive_only=True,
        note=(
            "Twilight's Edge: The Path Between requires 130 bonus AD AND 180 AP threshold; "
            "randomly assigns Material/Spirit World effect — threshold + RNG not modelable"
        ),
    ),
    "447107": ItemEffect(
        item_id="447107",
        name="Decapitator",
        defensive_only=True,
        note=(
            "Decapitator: Anticipation stacks boost ultimate damage "
            "(ultimate-cast schema gap; no basic attack DPS proc)"
        ),
    ),
    "447100": ItemEffect(
        item_id="447100",
        name="Mirage Blade",
        defensive_only=True,
        note=(
            "Mirage Blade: Blur grants bonus MS and a brief untargetable dash illusion "
            "(movement utility + dodge mechanic; no DPS contribution)"
        ),
    ),
    # ── Phase 4 batch 37 (2026-05-04): TRUE damage type + Arena item sweep ──
    # TRUE damage bypasses both armor and MR (resist=0.0 in _periodic_proc_dps).
    # Three active promotions; 14 defensive_only entries completing the Arena pool sweep.

    # Darksteel Talons (443054): Gash — every basic attack deals 10→20 true damage
    # (level-scaled, ranged Meraki value). 25%/20% caster bonus armor scaling deferred
    # (no caster_bonus_armor field in CallContext).
    "443054": ItemEffect(
        item_id="443054",
        name="Darksteel Talons",
        periodics=(
            PeriodicProc(
                name="Gash",
                every_n_attacks=1,
                bonus_damage=lambda c: 10.0 + 10.0 / 17.0 * (c.level - 1),
                damage_type=TRUE,
            ),
        ),
        note=(
            "Darksteel Talons: Gash every basic attack 10→20 true damage (ranged value, level-scaled). "
            "25%/20% caster bonus armor component deferred (caster_bonus_armor not in CallContext)"
        ),
    ),
    # Fulmination (443055): Dynamo — every 100th attack 13% CURRENT target HP magic damage.
    # target_max_hp used as upper-bound approximation (current HP unavailable in CallContext).
    # Polarity Energized mechanic (stacks via movement + attacks) deferred — same complexity
    # class as Stormrazor; not modeled at sustained-DPS level.
    "443055": ItemEffect(
        item_id="443055",
        name="Fulmination",
        periodics=(
            PeriodicProc(
                name="Dynamo",
                every_n_attacks=100,
                bonus_damage=lambda c: 0.13 * c.target_max_hp,
                damage_type=MAGICAL,
            ),
        ),
        note=(
            "Fulmination: Dynamo every 100th attack 13% CURRENT target HP magic "
            "(target_max_hp used as upper-bound; current HP unavailable). "
            "Polarity Energized mechanic deferred (movement-stack complexity)"
        ),
    ),
    # Reaper's Toll (443090): Reap — every basic attack 0.7% target max HP true damage
    # at base 0 stacks. Stacks infinitely per target (no cap) — pinned at base (0 stacks)
    # per conservative sustained-DPS convention. Sow on-kill heal utility-only.
    "443090": ItemEffect(
        item_id="443090",
        name="Reaper's Toll",
        periodics=(
            PeriodicProc(
                name="Reap",
                every_n_attacks=1,
                bonus_damage=lambda c: 0.007 * c.target_max_hp,
                damage_type=TRUE,
            ),
        ),
        note=(
            "Reaper's Toll: Reap every basic attack 0.7% target max HP true damage "
            "(pinned at 0 stacks — infinite per-target stacking deferred). "
            "Sow on-kill heal utility-only"
        ),
    ),
    # ── defensive_only (14) ──
    "447101": ItemEffect(
        item_id="447101",
        name="Gambler's Blade",
        defensive_only=True,
        note=(
            "Gambler's Blade (447101): Money In The Bank 12% chance to store 30–240g on attack/ability — "
            "gold-economy mechanic, not a DPS proc; variable payout not modelable in sustained DPS"
        ),
    ),
    "447102": ItemEffect(
        item_id="447102",
        name="Reality Fracture",
        defensive_only=True,
        note=(
            "Reality Fracture: ZZ'Rot summons 8 Voidmites on attack/ability — "
            "summoned-unit DPS requires AI/positioning modeling; deferred"
        ),
    ),
    "447103": ItemEffect(
        item_id="447103",
        name="Hemomancer's Helm",
        defensive_only=True,
        note=(
            "Hemomancer's Helm: Scarlet Allegiance conditional on lifesteal + omnivamp >= 30% "
            "grants 500 bonus HP and healing — HP/sustain gain, no DPS proc"
        ),
    ),
    "447104": ItemEffect(
        item_id="447104",
        name="Innervating Locket",
        defensive_only=True,
        note=(
            "Innervating Locket: Fill the Soul charges from ability casts (up to 30), "
            "triggers at max charge — ability-cast schema gap; deferred"
        ),
    ),
    "447105": ItemEffect(
        item_id="447105",
        name="Empyrean Promise",
        defensive_only=True,
        note=(
            "Empyrean Promise: no passive effects in Meraki 16.9.1 — stat block only; "
            "defensive_only per zero-proc policy"
        ),
    ),
    "447106": ItemEffect(
        item_id="447106",
        name="Dragonheart",
        defensive_only=True,
        note=(
            "Dragonheart: Inner Flame grants random Dragon Soul every 2 Arena rounds + "
            "total stat scaling — Arena-round mechanic, not a basic-attack DPS proc"
        ),
    ),
    "447109": ItemEffect(
        item_id="447109",
        name="Cruelty",
        defensive_only=True,
        note=(
            "Cruelty: Watch Them Fall summons comet on immobilize/ground — "
            "CC-conditional proc, no sustained per-attack DPS contribution"
        ),
    ),
    "447110": ItemEffect(
        item_id="447110",
        name="Moonflair Spellblade",
        defensive_only=True,
        note=(
            "Moonflair Spellblade: Relentless resets basic attack timer and empowers "
            "next 2 attacks after ability cast — attack-reset/haste mechanic, "
            "not a simple damage proc (ability-cast schema gap)"
        ),
    ),
    "447112": ItemEffect(
        item_id="447112",
        name="Flesheater",
        defensive_only=True,
        note=(
            "Flesheater: Hack the Meat 3 armor/MR reduction per hit (10 stacks) — "
            "flat shred needs armor_reduction_flat schema (not yet implemented); "
            "Cannibalize on-kill heal utility-only"
        ),
    ),
    "447122": ItemEffect(
        item_id="447122",
        name="Black Hole Gauntlet",
        defensive_only=True,
        note=(
            "Black Hole Gauntlet: Accretion stacks from on-hit + immobilize effects — "
            "stack-conditional with CC dependency; not a simple per-attack DPS proc"
        ),
    ),
    "447123": ItemEffect(
        item_id="447123",
        name="Puppeteer",
        defensive_only=True,
        note=(
            "Puppeteer: Pull Their Strings 4-stack on-hit conditional + ally buff utility passive — "
            "stack ramp + conditional trigger not modelable in sustained flat DPS"
        ),
    ),
    "443056": ItemEffect(
        item_id="443056",
        name="Demon King's Crown",
        defensive_only=True,
        note=(
            "Demon King's Crown: Supremacy percentage increase to total AD/AP/AS/max HP — "
            "Arena-round progression mechanic; not a simple stat add (multiplier interacts "
            "with full stat build; deferred)"
        ),
    ),
    "443060": ItemEffect(
        item_id="443060",
        name="Sword of the Divine",
        defensive_only=True,
        note=(
            "Sword of the Divine: Excoriate grants random bonus crit damage up to 50% — "
            "random distribution not pinnable to a single sustained value; "
            "crit_damage_bonus promotion deferred pending design decision on RNG items"
        ),
    ),
    "443069": ItemEffect(
        item_id="443069",
        name="Hamstringer",
        defensive_only=True,
        note=(
            "Hamstringer: Scour critical strikes inflict 2s physical bleed — "
            "crit-conditional proc rate + exact bleed formula unavailable in Meraki 16.9.1; "
            "deferred pending schema for crit-gated procs"
        ),
    ),

}


def collect_effects(item_ids: Iterable[str | int]) -> list[ItemEffect]:
    """Return the ItemEffect entries that match the build's items, in order.

    Items without an entry in ``ITEM_EFFECTS`` are silently skipped — they
    contribute their stat-block to the engine via ``stats.aggregate_item_stats``
    but no conditional layer applies. Duplicate item IDs (e.g. two IEs)
    are kept so the engine's existing item-stack semantics carry through;
    the engine does not enforce per-item uniqueness.

    Phase 4 batch 10 (2026-05-04): items that share a non-empty
    ``unique_passive_key`` are de-duplicated first-seen-wins. The duplicate
    item still contributes its stat block via ``aggregate_item_stats``
    (which lives outside this function), so the AD/HP/etc. from the
    duplicate item is unaffected — only the proc / armor-pen effects
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
    Riftmaker's Void Infusion (2% bonus HP → AP) is the first user;
    additive across multiple cross-derivation items if any land later
    (sums commute, no buff-system multiplicative subtlety here — each
    item's contribution is its own independent stat add).

    Returns 0.0 when no item carries the field — pre-batch-15 callers
    pass through unchanged. Negative ``caster_bonus_hp`` (defensive
    paranoia: shouldn't happen — engine floors at zero) is clamped at
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

    Two flavors compose additively, returning a single fraction (0.0–N)
    intended to be added to the build's ``stats["crit"]`` and clamped at
    1.0 by the caller (compute_dps). The clamp lives at the call site so
    intermediate sums are exposed faithfully — a build with 60% Yun Tal
    flat + 50% Atma scaled would *want* 1.10 here so the caller can
    decide what to do with it (currently: cap at 100% — League's ceiling).

    - ``crit_chance_bonus_flat`` contributes unconditionally.
    - HP-scaled contributes only when both ``crit_chance_bonus_max_pct``
      AND ``crit_chance_bonus_per_bonus_hp_cap`` are positive AND
      ``caster_bonus_hp`` is positive. Otherwise the linear ramp would
      either divide by zero or contribute negative values — defensive.
      Atma's Reckoning is the canonical example: max=0.30, cap=3000 →
      ramp = min(1.0, caster_bonus_hp / 3000) → 0.0 at 0 bonus HP, 0.15
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

    League stacks combat-state damage amplifiers via the buff system —
    Riftmaker's 8% × Conqueror's 8% = 1.08 * 1.08 = 1.1664x, not 1.16x.
    Returns 1.0 when no item carries an amp (pre-batch-14 baseline) so
    every existing rotation calculation passes through unchanged.

    The 1.0 floor matters even when items are present — only items with
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
    ``CallContext``. Raw stat block is unchanged — same separation as
    ``ap_per_bonus_hp_pct`` (batch 15).

    Returns 1.0 when no item carries the field (pre-batch-32 builds pass
    through unchanged). Stacks multiplicatively per League's buff-system
    semantics — current patch has only Rabadon's, so the product is
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
    magic-type proc DPS only — does NOT amplify physical auto-attack
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
    ``cap``. LDR Giant Slayer is the canonical example — 0% at 0 bonus
    HP, 7.5% at 750, 15% at 1500, 15% past 1500.

    Stacks multiplicatively with ``total_damage_amp_multiplier`` per
    League's buff-system semantics (batch 14 doctrine). Returns 1.0
    when ``target_bonus_hp <= 0`` OR when no item carries the field —
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


def effective_target_armor(
    target_armor: float,
    effects: Iterable[ItemEffect],
    level: int | None = None,
) -> float:
    """Apply armor reduction → % pen → flat pen pipeline.

    Mirrors League's order: ``armor_reduction_pct`` (Black Cleaver
    stacks) reduces target armor first; then ``armor_pen_pct`` (LDR /
    Mortal Reminder / Serylda's) reduces what's left; then flat pen
    (``armor_pen_flat`` raw + ``lethality`` level-scaled) subtracts.
    Result floors at zero — physical damage against zero-armor uses
    the ``armor=0`` factor (1.0).

    Phase 4 batch 30 (2026-05-04): ``level`` is the caster's champion
    level. When provided, lethality contributions are folded into the
    flat-pen sum at their level-scaled value: ``lethality × (0.6 + 0.4
    × level / 18)``. Pre-batch-30 callers (tests + any direct caller
    that doesn't have a level) omit ``level`` and lethality contributes
    nothing — preserves backward-compatibility for the non-DPS path.
    Production caller (compute_dps) always passes the resolved level.

    Effects without armor modifiers contribute nothing here. Order
    among items in ``effects`` doesn't matter — sums commute, and
    the multiplicative layers are applied in fixed order.
    """
    eff_list = list(effects)
    red_pct = sum(e.armor_reduction_pct for e in eff_list)
    pen_pct = sum(e.armor_pen_pct for e in eff_list)
    pen_flat = sum(e.armor_pen_flat for e in eff_list)
    if level is not None:
        lethality_total = sum(e.lethality for e in eff_list)
        if lethality_total > 0:
            # 60% effective at lvl 1, 100% at lvl 18 (linear).
            scale = 0.6 + 0.4 * level / 18.0
            pen_flat += lethality_total * scale
    if not (red_pct or pen_pct or pen_flat):
        # Passthrough — preserves negative armor inputs (external shred,
        # tests of the armor curve itself).
        return target_armor
    if target_armor < 0:
        # Pen / reduction is a no-op on already-negative armor — items
        # don't amplify beyond what the shred already gave.
        return target_armor
    armor = target_armor * (1.0 - red_pct)
    armor = armor * (1.0 - pen_pct)
    armor = armor - pen_flat
    return max(0.0, armor)


def effective_target_mr(target_mr: float, effects: Iterable[ItemEffect]) -> float:
    """Apply % magic pen → flat magic pen pipeline.

    Mirrors League's order on the magic side: ``magic_pen_pct`` (Void
    Staff, Cryptbloom) reduces MR first, then ``magic_pen_flat``
    (Sorcerer's Shoes, Shadowflame) subtracts. No MR-reduction layer
    in the current patch (no magic-side Black Cleaver); add when the
    first item demands it. Result floors at zero — magic damage
    against zero-MR uses the same ``armor=0`` factor (1.0) via
    ``_armor_factor`` (which is shared between damage types).

    Effects without magic-pen modifiers contribute nothing here.
    Negative MR (external shred, MR-curve tests) passes through —
    pen items don't amplify beyond what the shred already gave.
    """
    eff_list = list(effects)
    pen_pct = sum(e.magic_pen_pct for e in eff_list)
    pen_flat = sum(e.magic_pen_flat for e in eff_list)
    if not (pen_pct or pen_flat):
        return target_mr
    if target_mr < 0:
        return target_mr
    mr = target_mr * (1.0 - pen_pct)
    mr = mr - pen_flat
    return max(0.0, mr)
