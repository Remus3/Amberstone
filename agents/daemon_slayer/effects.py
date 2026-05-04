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
from typing import Callable, Iterable, Optional, Union


PHYSICAL = "physical"
MAGICAL = "magical"
_DAMAGE_TYPES = frozenset({PHYSICAL, MAGICAL})


@dataclass(frozen=True)
class CallContext:
    """Inputs available to a scaling ``bonus_damage`` callable.

    ``base_ad`` is the leveled champion-base AD (pre-items), needed for
    spellblade-style scaling. ``bonus_ad`` is the item-contributed AD.
    ``level`` enables Wit's End-style level scaling.

    Phase 4 doesn't model target HP, so callables that want
    ``%-current-HP`` math should be marked ``defensive_only`` until
    Phase 4+ adds the hook.
    """
    base_ad: float
    bonus_ad: float
    level: int
    target_armor: float = 0.0
    target_mr: float = 0.0


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
    periodic: Optional[PeriodicProc] = None
    # Physical-damage modifiers — applied to ``target_armor`` in dps.py
    # before the armor curve. Reduction (Black Cleaver) lands first,
    # then % pen (LDR / MR), then flat pen (lethality items).
    armor_reduction_pct: float = 0.0   # Black Cleaver: 0.30 sustained
    armor_pen_pct: float = 0.0         # LDR: 0.35; MR: 0.30
    armor_pen_flat: float = 0.0        # lethality flat (rare standalone)
    defensive_only: bool = False     # documents "no DPS effect" entries
    note: str = ""                   # one-line summary surfaced in DpsResult.notes


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
        periodic=PeriodicProc(
            name="Energized Bolt",
            bonus_damage=120.0,
            damage_type=MAGICAL,
            every_n_seconds=4.0,
        ),
        note="Stormrazor: Energized ~120 magic dmg every ~4s",
    ),
    "6672": ItemEffect(
        item_id="6672",
        name="Kraken Slayer",
        periodic=PeriodicProc(
            name="Bring It Down",
            bonus_damage=100.0,
            damage_type=PHYSICAL,
            every_n_attacks=3,
        ),
        note="Kraken Slayer: Bring It Down ~100 physical dmg every 3rd attack",
    ),
    "6673": ItemEffect(
        item_id="6673",
        name="Immortal Shieldbow",
        defensive_only=True,
        note="Immortal Shieldbow: Lifeline (low-HP shield); no DPS contribution",
    ),

    # ── Phase 4 expansion 2026-05-03: energized family + scaling procs ──

    "3087": ItemEffect(
        item_id="3087",
        name="Statikk Shiv",
        periodic=PeriodicProc(
            name="Electroshock",
            bonus_damage=110.0,
            damage_type=MAGICAL,
            every_n_seconds=3.0,
        ),
        note="Statikk Shiv: Energized chain lightning ~110 magic dmg every ~3s",
    ),
    "3094": ItemEffect(
        item_id="3094",
        name="Rapid Firecannon",
        periodic=PeriodicProc(
            name="Sharpshooter",
            bonus_damage=120.0,
            damage_type=MAGICAL,
            every_n_seconds=3.0,
        ),
        note="Rapid Firecannon: Energized critical strike ~120 magic dmg every ~3s",
    ),
    "3091": ItemEffect(
        item_id="3091",
        name="Wit's End",
        periodic=PeriodicProc(
            name="Fray",
            # 15 magic at lvl 1 → 80 at lvl 18, linear by level.
            bonus_damage=lambda c: 15.0 + (c.level - 1) * (65.0 / 17.0),
            damage_type=MAGICAL,
            every_n_attacks=1,
        ),
        note="Wit's End: Fray on-hit magic dmg scales 15→80 by level",
    ),
    "3085": ItemEffect(
        item_id="3085",
        name="Runaan's Hurricane",
        periodic=PeriodicProc(
            name="Wind's Fury",
            # Two extra bolts at 30% bonus AD each = 60% bonus AD per shot.
            # Approximation: assumes both bolts find a target.
            bonus_damage=lambda c: 0.60 * c.bonus_ad,
            damage_type=PHYSICAL,
            every_n_attacks=1,
        ),
        note="Runaan's Hurricane: 2 extra bolts on-hit, ~60% bonus AD per shot",
    ),
    "3078": ItemEffect(
        item_id="3078",
        name="Trinity Force",
        periodic=PeriodicProc(
            name="Spellblade",
            # Spellblade: next basic after spell deals 200% base AD bonus
            # physical. Approximation: fires ~once per 3s in active rotations
            # (real CD is 1.5s after spell cast, gated by ability cadence).
            bonus_damage=lambda c: 2.0 * c.base_ad,
            damage_type=PHYSICAL,
            every_n_seconds=3.0,
        ),
        note="Trinity Force: Spellblade ~200% base AD on-hit, ~once per 3s in rotation",
    ),
    "6699": ItemEffect(
        item_id="6699",
        name="Voltaic Cyclosword",
        periodic=PeriodicProc(
            name="Firmament",
            # Energized release: 100 + 25% bonus AD physical (slow utility
            # not modeled). Charges over 4s of moving / attacking.
            bonus_damage=lambda c: 100.0 + 0.25 * c.bonus_ad,
            damage_type=PHYSICAL,
            every_n_seconds=4.0,
        ),
        note="Voltaic Cyclosword: Energized release ~100 + 25% bonus AD physical every ~4s",
    ),
    "6610": ItemEffect(
        item_id="6610",
        name="Sundered Sky",
        periodic=PeriodicProc(
            name="Lightshield Strike",
            # Every 8s, next basic deals (20 + 200% base AD) bonus physical.
            # Long CD makes this rare in DPS terms but a big single hit.
            bonus_damage=lambda c: 20.0 + 2.0 * c.base_ad,
            damage_type=PHYSICAL,
            every_n_seconds=8.0,
        ),
        note="Sundered Sky: Lightshield Strike ~200% base AD bonus on guaranteed crit, every ~8s",
    ),
    "3124": ItemEffect(
        item_id="3124",
        name="Guinsoo's Rageblade",
        periodic=PeriodicProc(
            name="Phantom Hit",
            # Every 3rd attack triggers an extra on-hit. Approximated as
            # 50% bonus AD physical — under-counts on-hit stacking with
            # other items (BotRK, Wit's End) but those self-stack via
            # their own periodic entries.
            bonus_damage=lambda c: 0.50 * c.bonus_ad,
            damage_type=PHYSICAL,
            every_n_attacks=3,
        ),
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
        note="Phantom Dancer: Lifeline shield + ghosting on low HP; no DPS contribution",
    ),
    "6676": ItemEffect(
        item_id="6676",
        name="The Collector",
        defensive_only=True,
        note="The Collector: Execute below 5% HP (target HP not modeled in Phase 4)",
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
        note="Sterak's Gage: Lifeline shield + bonus AD on takedown; no DPS contribution",
    ),
    "3156": ItemEffect(
        item_id="3156",
        name="Maw of Malmortius",
        defensive_only=True,
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
        defensive_only=True,
        note="Blade of the Ruined King: 8% target current HP on-hit (target HP not modeled in Phase 4)",
    ),
    "3302": ItemEffect(
        item_id="3302",
        name="Terminus",
        defensive_only=True,
        note="Terminus: alternating physical/magical on-hit + pen stacks (not yet modeled)",
    ),
    "6692": ItemEffect(
        item_id="6692",
        name="Eclipse",
        defensive_only=True,
        note="Eclipse: 6% target max HP every 2nd attack (target HP not modeled in Phase 4)",
    ),
}


def collect_effects(item_ids: Iterable[str | int]) -> list[ItemEffect]:
    """Return the ItemEffect entries that match the build's items, in order.

    Items without an entry in ``ITEM_EFFECTS`` are silently skipped — they
    contribute their stat-block to the engine via ``stats.aggregate_item_stats``
    but no conditional layer applies. Duplicates (e.g. two IEs) are kept
    so the engine's existing item-stack semantics carry through; the engine
    does not enforce per-item uniqueness.
    """
    out: list[ItemEffect] = []
    for iid in item_ids:
        eff = ITEM_EFFECTS.get(str(iid))
        if eff is not None:
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
