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
_DAMAGE_TYPES = frozenset({PHYSICAL, MAGICAL})


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
