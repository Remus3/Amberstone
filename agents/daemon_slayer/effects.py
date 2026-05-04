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
        # Deduped against Lich Bane (3100). Sundered Sky (6610) uses its
        # own "Lightshield Strike" label, not Spellblade — distinct
        # mechanic, no dedup. Essence Reaver (3508) has the Spellblade
        # label too but is currently defensive_only (proc not modeled);
        # tagging it would create order-dependence (LB or TF would get
        # deduped if Essence Reaver appeared first), so it stays untagged
        # until promoted out of defensive_only.
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
        note="Voltaic Cyclosword: Energized release ~100 + 25% bonus AD physical every ~4s",
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
        note="Lord Dominik's Regards: 35% armor pen (physical)",
    ),
    "3033": ItemEffect(
        item_id="3033",
        name="Mortal Reminder",
        armor_pen_pct=0.30,
        note="Mortal Reminder: 30% armor pen + Grievous Wounds (heal-cut not modeled)",
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
        defensive_only=True,
        note="Youmuu's Ghostblade: active speed; no on-hit DPS",
    ),
    "3814": ItemEffect(
        item_id="3814",
        name="Edge of Night",
        defensive_only=True,
        note="Edge of Night: Spellshield; no DPS contribution",
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
        defensive_only=True,
        note="Opportunity: bonus lethality on takedown (conditional, not modeled)",
    ),
    "3053": ItemEffect(
        item_id="3053",
        name="Sterak's Gage",
        defensive_only=True,
        unique_passive_key="lifeline",
        note="Sterak's Gage: Lifeline shield + bonus AD on takedown; no DPS contribution",
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
        defensive_only=True,
        note="Hullbreaker: solo-lane bonus stats + tower siege; situational",
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
        note="Spear of Shojin: Veteran's Resolve stacks reduce ability CDs (CDR not DPS-modeled)",
    ),
    "3508": ItemEffect(
        item_id="3508",
        name="Essence Reaver",
        defensive_only=True,
        note="Essence Reaver: mana refund + CDR after ability use; no on-hit DPS proc",
    ),
    "3084": ItemEffect(
        item_id="3084",
        name="Heartsteel",
        periodics=(PeriodicProc(
            name="Colossal Consumption",
            # 70-160 (linear by level) + 6% caster max HP physical, every
            # 3.5s of in-combat-with-champion charge time. Approximation:
            # in DPS rotations the champion is always near the target,
            # so the 3.5s cadence is the binding constraint. The HP-on-
            # damage permanent stack is not modeled — that's stat-side,
            # not proc-side.
            bonus_damage=lambda c: (
                70.0 + 90.0 * (c.level - 1) / 17.0
                + 0.06 * c.caster_max_hp
            ),
            damage_type=PHYSICAL,
            every_n_seconds=3.5,
        ),),
        note=(
            "Heartsteel: Colossal Consumption ~70-160 (by level) + 6% caster "
            "max HP physical every ~3.5s in combat"
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
    "6631": ItemEffect(
        item_id="6631",
        name="Stridebreaker",
        defensive_only=True,
        note="Stridebreaker: Halting Slash active dash + slow; no on-hit DPS proc",
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
        defensive_only=True,
        note="Hextech Gunblade: Lightning Bolt active (targeted nuke + slow); no on-hit DPS proc",
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
        defensive_only=True,
        note="Riftmaker: combat-state damage amp (up to 8% bonus dmg after 4s); not modeled in Phase 4",
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


def effective_target_armor(target_armor: float, effects: Iterable[ItemEffect]) -> float:
    """Apply armor reduction → % pen → flat pen pipeline.

    Mirrors League's order: ``armor_reduction_pct`` (Black Cleaver
    stacks) reduces target armor first; then ``armor_pen_pct`` (LDR /
    Mortal Reminder) reduces what's left; then ``armor_pen_flat``
    (lethality) subtracts. Result floors at zero — physical damage
    against zero-armor uses the ``armor=0`` factor (1.0).

    Effects without armor modifiers contribute nothing here. Order
    among items in ``effects`` doesn't matter — sums commute, and
    the multiplicative layers are applied in fixed order.
    """
    eff_list = list(effects)
    red_pct = sum(e.armor_reduction_pct for e in eff_list)
    pen_pct = sum(e.armor_pen_pct for e in eff_list)
    pen_flat = sum(e.armor_pen_flat for e in eff_list)
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
