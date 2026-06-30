"""Phase 2 step 2 + Phase 4 thin slice - auto-attack DPS with conditionals.

Reads ``snapshot.scenarios(champion_id)`` (early/mid/late phases x rotations
with weights, durations, basic-attack counts) and convolves with the
champion's resolved AD/AS/crit at the requested level + items. Mode hook
applies ``aram_modifiers.aramDamageDealt`` for ARAM. Target armor uses
the standard League formula.

Phase 4 thin slice (2026-05-03): ``effects.ITEM_EFFECTS`` layers
per-item conditionals on top of the stat math - Infinity Edge bumps the
crit-damage multiplier, Kraken Slayer adds an every-3rd-attack physical
proc, Stormrazor adds an every-4-second magic proc. Magical procs use
target MR (not armor); physical procs share the auto-attack armor curve.

Phase 4 batch 5 (2026-05-04): ``target_max_hp`` is plumbed into
``CallContext`` so %-target-HP procs (BotRK Mist's Edge, Eclipse Ever
Rising Moon) resolve. Same caller-supplied shape as ``target_armor`` /
``target_mr`` - defaults to 0.0, lolmath scenarios don't carry HP.

Phase 4 batch 6 (2026-05-04): caster HP layer. ``caster_max_hp`` and
``caster_bonus_hp`` are derived from the resolved build (``stats["hp"]``
and ``stats["hp"] - base_stats["hp"]`` respectively) and fed into
``CallContext``. Engine-internal - no caller param - since the engine
always knows the caster's exact HP. Unlocks Titanic Hydra Cleave
(1.5% bonus HP) and Heartsteel Colossal Consumption (6% max HP).

Phase 4 batch 7 (2026-05-04): multi-target rotations. Each rotation's
``numberOfTargets`` (lolmath field, 94% of rotations = 1.0) feeds into
``CallContext.targets_in_rotation`` per rotation via ``replace``.
Cleave-to-others procs (Ravenous Hydra) read ``max(0, n-1)`` from it;
single-target procs ignore the field. AoE-incl-primary procs (Sunfire
Immolate, when added) would use ``n`` directly.

Ability damage is **not** included - spell formulas aren't in the
snapshot. Only the basic-attack portion of each rotation is scored;
rotation duration includes the time spent casting abilities, so longer
rotations naturally dilute auto-attack DPS.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Iterable, Optional

from .data_loader import DataSnapshot
from .effects import (
    CallContext,
    ItemEffect,
    PHYSICAL,
    TRUE,
    collect_effects,
    effective_target_armor,
    effective_target_mr,
    total_ap_amp_multiplier,
    total_bonus_ap_from_hp,
    total_caster_hp_scaled_ap_amp,
    total_conditional_as,
    total_crit_chance_bonus,
    total_crit_damage_bonus,
    total_damage_amp_multiplier,
    total_giant_slayer_multiplier,
    total_magic_amp_multiplier,
    total_stacked_ap,
    total_takedown_bonus_ad,
    total_target_bonus_hp_amp_multiplier,
)
from .engine import build_champion
from .stats import clamp_level
from .ult_rates import get_ult_casts_per_sec

# Base bonus crit damage on auto-attacks. ``effects.ITEM_EFFECTS`` adds
# per-item bumps (e.g. Infinity Edge = +0.30) on top.
DEFAULT_CRIT_BONUS = 0.75

# B1 melee-applicability gate (DS Tier-2 cross-eval nomination B, 1.141.0):
# a champion is melee when its base attackrange is below this ceiling. The big
# data gap sits between the longest short-melee (Nilah 225) and the shortest
# ranged carry (Xayah 525), so 350 separates them with no champion in between.
# Consumed only when compute_dps(apply_melee_aa_gate=True); default-OFF the
# value is never read. See ops/audit/ds_cross_eval/TIER2_REPORT.md (B1).
MELEE_RANGE_CEILING = 350

EARLY_LEVEL_MAX = 6
MID_LEVEL_MAX = 12

PHASES: tuple[str, ...] = ("early", "mid", "late")

# DSV2 (1.125.0): takedown / kill-state OFFENSE seam assumption. When
# ``compute_dps`` / ``compute_burst_damage`` is called with
# ``assume_takedown=True`` the wielder is assumed to hold this many Hubris
# Eminence stacks worth of bonus AD (15 + 2*stacks). One stack -> 17 bonus AD,
# the value the moment after a single takedown (Eminence grants the first stack
# on the takedown that triggers it). Operator-tunable, mirroring ehp.py's
# ``_TAKEDOWN_RATE_PER_FIGHT`` doctrine; bumping it models a snowballing carry
# that has banked several takedowns. The seam is inert at the default flag
# (assume_takedown=False) regardless of this value.
_ASSUMED_TAKEDOWN_STACKS = 1

# DSV4 (1.127.0): Spear of Shojin Focused Will stacks assumed when the ability
# scorers' ``assume_ability_amp`` seam is ON. 4 = the item's max stacks (a
# developed fight at full Focused Will), so the steady-state ability scorers
# value the full 12% amp. Operator-tunable like ``_ASSUMED_TAKEDOWN_STACKS``;
# the seam is inert at the default flag (assume_ability_amp=False) regardless of
# this value. Consumed by ``ability_dps.compute_ability_dps`` +
# ``burst.compute_burst_damage`` via ``effects.total_ability_damage_amp``.
_ASSUMED_ABILITY_AMP_STACKS = 4

# R7 (1.147.0): per-stack champion self-Attack-Speed passive seam. When
# ``compute_dps(assume_passive_as_stacks=True)`` the wielder is assumed to hold
# this fraction of the champion's max passive stacks (1.0 = full stacks, a
# developed fight at steady state). Operator-tunable like
# ``_ASSUMED_TAKEDOWN_STACKS`` / ``_ASSUMED_ABILITY_AMP_STACKS``; the seam is
# inert at the default flag (assume_passive_as_stacks=False) regardless of this
# value. Consumed via ``_passive_as_overrides.passive_as_bonus`` - only the 4
# registered innate per-stack self-AS passives (Irelia Ionian Fervor / Jax
# Relentless Assault / Ezreal Rising Spell Force / Volibear The Relentless
# Storm) contribute; every other champion is byte-identical even with the flag on.
_ASSUMED_PASSIVE_AS_STACK_FRACTION = 1.0


@dataclass(frozen=True)
class DpsResult:
    champion_id: str
    champion_name: str
    level: int
    item_ids: tuple[str, ...]
    mode: str
    target_armor: float
    target_mr: float
    target_max_hp: float           # caller-supplied; 0.0 zeros out %HP procs
    target_bonus_hp: float         # caller-supplied; 0.0 zeros out target-bonus-HP amps (Giant Slayer)
    phase: str
    weighted_dps: float            # selected phase, weighted across rotations
    phase_dps: dict[str, float]    # all 3 phases for context
    avg_attack_dmg: float          # per-attack avg post-armor + mode
    raw_attack_dps: float          # AD * AS * crit avg, no scenario / no resists
    mode_multiplier: float         # aramDamageDealt or 1.0
    # Phase 5.6 (s188, 2026-05-13): per-attack on-hit proc damage -
    # amortized sum of every-n-attacks procs (Wit's End magic damage,
    # BotRK Mist's Edge HP%, Statikk Shiv stacks etc.), post-mit + post-mode
    # + post-amps. Used by burst.py to give each AA token in a combo a
    # richer per-hit total than raw AD-on-armor. Empty builds yield 0.0;
    # builds with non-attack-cadence procs only also 0.0. Note: Spellblade
    # items (Trinity Force / Lich Bane / ER / Iceborn / Dusk+Dawn / Divine
    # Sunderer / Sheen / Bloodsong) are time-based (every_n_seconds) so
    # they DON'T contribute here - they live in ``spellblade_per_proc_damage``
    # below, which burst.py arms per-spell-cast.
    per_attack_on_hit_damage: float = 0.0
    # Phase 5.7 (s189, 2026-05-13): Spellblade per-proc damage. Spellblade
    # is the canonical "next basic after spell cast" mechanic shared by
    # eight items via ``unique_passive_key="spellblade"``: Trinity Force,
    # Lich Bane, Essence Reaver, Iceborn Gauntlet, Dusk and Dawn, Divine
    # Sunderer, Sheen, Bloodsong (+ Arena mirrors). ``collect_effects``
    # already dedups via the unique-passive key, so at most one Spellblade
    # survives into ``item_effects``. The per-proc damage value here is
    # the post-mit / post-mode / post-amp damage from ONE proc - burst.py
    # walks the combo with a spellblade_armed flag and adds this value to
    # each AA that consumes an armed Spellblade. Empty for builds without
    # a Spellblade-family item.
    spellblade_per_proc_damage: float = 0.0
    spellblade_item_name: str = ""        # informational; "" when no spellblade
    # Phase 5.8 (s190, 2026-05-13): Lightshield Strike per-proc damage.
    # Sundered Sky (6610 + Arena mirror 226610) carries the only
    # "Lightshield Strike" proc in the engine - explicitly distinct from
    # spellblade (different label, 8s vs 1.5s CD, no dedup family). Same
    # arm-consume model as Spellblade in burst.py, but capped at 1 proc
    # per combo because the 8s CD greatly exceeds typical burst window.
    lightshield_strike_per_proc_damage: float = 0.0
    lightshield_strike_item_name: str = ""
    stats: dict[str, float] = field(default_factory=dict)
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
            "phase": self.phase,
            "weighted_dps": self.weighted_dps,
            "phase_dps": dict(self.phase_dps),
            "avg_attack_dmg": self.avg_attack_dmg,
            "raw_attack_dps": self.raw_attack_dps,
            "mode_multiplier": self.mode_multiplier,
            "per_attack_on_hit_damage": self.per_attack_on_hit_damage,
            "spellblade_per_proc_damage": self.spellblade_per_proc_damage,
            "spellblade_item_name": self.spellblade_item_name,
            "lightshield_strike_per_proc_damage": self.lightshield_strike_per_proc_damage,
            "lightshield_strike_item_name": self.lightshield_strike_item_name,
            "stats": dict(self.stats),
            "notes": list(self.notes),
        }

    def format_table(self) -> str:
        head = (
            f"{self.champion_name} ({self.champion_id}) - lvl {self.level} "
            f"- mode {self.mode} - phase {self.phase}"
        )
        rows = [head, "-" * len(head)]
        if self.item_ids:
            rows.append(f"items: {', '.join(self.item_ids)}")
        else:
            rows.append("items: (none)")
        rows.append(
            f"target: armor={self.target_armor:.0f}  mr={self.target_mr:.0f}"
            f"  max_hp={self.target_max_hp:.0f}  bonus_hp={self.target_bonus_hp:.0f}"
        )
        rows.append("")
        rows.append(f"  weighted_dps   {self.weighted_dps:.2f}")
        for p in PHASES:
            marker = " *" if p == self.phase else "  "
            rows.append(f"  {p:<5} dps     {self.phase_dps.get(p, 0.0):.2f}{marker}")
        rows.append("")
        rows.append(f"  raw_attack_dps {self.raw_attack_dps:.2f}  (AD * AS * crit avg)")
        rows.append(f"  avg_attack_dmg {self.avg_attack_dmg:.2f}  (per-hit, post-armor + mode)")
        rows.append(f"  mode_mult      {self.mode_multiplier:.2f}")
        if self.notes:
            rows.append("")
            for n in self.notes:
                rows.append(f"  note: {n}")
        return "\n".join(rows)


def _select_phase(level: int) -> str:
    if level <= EARLY_LEVEL_MAX:
        return "early"
    if level <= MID_LEVEL_MAX:
        return "mid"
    return "late"


def _armor_factor(armor: float) -> float:
    """League's armor -> physical damage multiplier (also applies to MR/magic).

    Positive armor: 100 / (100 + armor). Negative: 2 - 100/(100 - armor).
    """
    if armor >= 0:
        return 100.0 / (100.0 + armor)
    return 2.0 - 100.0 / (100.0 - armor)


def _periodic_proc_dps(
    effects: list[ItemEffect],
    total_attacks: float,
    duration: float,
    target_armor_for_physical: float,
    target_mr: float,
    mode_dmg_mult: float,
    call_ctx: CallContext,
    magic_amp: float = 1.0,
    ability_dot_only: bool = False,
    apply_melee_aa_gate: bool = False,
) -> float:
    """Sum DPS contribution from every conditional proc in the build.

    Each proc fires on either an attack count (``every_n_attacks``) or
    a time interval (``every_n_seconds``). Physical procs use the
    target's *effective* armor (post-reduction-and-pen); magical procs
    use MR. Mode damage multiplier applies (ARAM ``aramDamageDealt``
    reduces proc damage too). Rotation duration divides the per-rotation
    proc total so the contribution is in DPS units.

    Scaling procs (TriForce off ``base_ad``, Wit's End by ``level``,
    Runaan's by ``bonus_ad``) resolve through ``proc.resolve_damage``
    against ``call_ctx``; constants pass through unchanged.

    Phase 4 batch 34 (2026-05-04): ``magic_amp`` (from
    ``total_magic_amp_multiplier``) is applied only to magical procs -
    models target-debuff auras (Abyssal Mask Unmake) that increase magic
    damage taken without affecting physical auto-attack damage.
    """
    if duration <= 0:
        return 0.0
    total = 0.0
    for e in effects:
        for proc in e.periodics:
            # B1 (1.141.0): a ranged-only proc (Runaan's bolts) contributes
            # nothing on a melee auto. Default-OFF -> never skips (byte-identical).
            if apply_melee_aa_gate and call_ctx.is_melee and proc.ranged_only:
                continue
            if proc.every_n_attacks > 0:
                if total_attacks <= 0:
                    continue
                # ENGINE 1.26.0 (2026-05-21): stack-ramp-gated procs (Dead
                # Man's Plate Shipwrecker, future stack-discharge items).
                # When stack_ramp_seconds > 0, the effective period is
                # gated by the LATER of the attack-counted period and the
                # ramp. Each rotation tick: one stack-ramp + one attack
                # to discharge. Default stack_ramp_seconds=0.0 leaves
                # existing every_n_attacks procs unchanged (max(a, 0)=a).
                if proc.stack_ramp_seconds > 0:
                    attack_period_s = duration / total_attacks
                    eff_period_s = max(
                        proc.stack_ramp_seconds,
                        attack_period_s * proc.every_n_attacks,
                    )
                    procs = duration / eff_period_s
                else:
                    procs = total_attacks / proc.every_n_attacks
            else:  # every_n_seconds > 0 enforced by PeriodicProc.__post_init__
                procs = duration / proc.every_n_seconds
            # DSV1: the ability/AP scorer (compute_ability_dps) passes
            # ability_dot_only=True so it folds ONLY the ability-triggered AP
            # damage-over-time burns explicitly tagged ability_dot (Liandry
            # Torment, Blackfire Baleful Blaze, Demonic Azakana's Gaze). Every
            # other every_n_seconds proc - tank Immolate auras (Sunfire),
            # physical spellblades (Iceborn / Trinity Force), on-cast nukes
            # (Luden's) - is skipped so it cannot pollute the AP item ranking.
            # compute_dps keeps the default ability_dot_only=False (counts
            # every proc - byte-identical).
            if ability_dot_only and not proc.ability_dot:
                continue
            is_physical = proc.damage_type == PHYSICAL
            is_true = proc.damage_type == TRUE
            resist = 0.0 if is_true else (target_armor_for_physical if is_physical else target_mr)
            type_amp = 1.0 if (is_physical or is_true) else magic_amp
            dmg = proc.resolve_damage(call_ctx)
            total += procs * dmg * _armor_factor(resist) * mode_dmg_mult * type_amp
    return total / duration


SPELLBLADE_UNIQUE_KEY = "spellblade"
LIGHTSHIELD_STRIKE_PROC_NAME = "Lightshield Strike"


def _lightshield_strike_per_proc_damage(
    effects: list[ItemEffect],
    target_armor_for_physical: float,
    target_mr: float,
    mode_dmg_mult: float,
    call_ctx: CallContext,
    magic_amp: float = 1.0,
    damage_amp: float = 1.0,
) -> tuple[float, str]:
    """Per-proc damage from Sundered Sky's Lightshield Strike (if any).

    Identified by ``PeriodicProc.name == "Lightshield Strike"`` - the
    schema explicitly keeps Lightshield Strike OUT of the spellblade
    unique-passive family (different in-game label, 8s CD vs 1.5s, no
    dedup). Currently only Sundered Sky (6610) + its Arena mirror
    (226610) carry this proc.

    Returns ``(per_proc_damage, item_name)`` - first match wins (Arena
    mirror dedup is informational only; no game mode lets you stack two
    Sundered Skys). Damage applies the standard pipeline:
    ``resolve_damage(call_ctx)`` -> ``_armor_factor`` against the
    appropriate resist -> mode multiplier -> type-selective ``magic_amp``
    (only for MAGIC) -> build-wide ``damage_amp``. Empty builds yield
    ``(0.0, "")``.

    Phase 5.8 (s190, 2026-05-13): consumed by ``burst.py``'s combo
    walker on the AA following the first ability cast - same arm-consume
    pattern as Spellblade, but capped at 1 proc per combo because the
    real CD (8s) far exceeds a typical burst window (2-3s). Different
    state variable (``lightshield_strike_armed``) so a build with both
    Sundered Sky + a Spellblade item (e.g. Trinity Force) gets BOTH
    procs on the same AA.
    """
    for e in effects:
        for proc in e.periodics:
            if proc.name != LIGHTSHIELD_STRIKE_PROC_NAME:
                continue
            is_physical = proc.damage_type == PHYSICAL
            is_true = proc.damage_type == TRUE
            resist = 0.0 if is_true else (
                target_armor_for_physical if is_physical else target_mr
            )
            type_amp = 1.0 if (is_physical or is_true) else magic_amp
            dmg = proc.resolve_damage(call_ctx)
            per_proc = dmg * _armor_factor(resist) * mode_dmg_mult * type_amp * damage_amp
            return (per_proc, e.name)
    return (0.0, "")


def _spellblade_per_proc_damage(
    effects: list[ItemEffect],
    target_armor_for_physical: float,
    target_mr: float,
    mode_dmg_mult: float,
    call_ctx: CallContext,
    magic_amp: float = 1.0,
    damage_amp: float = 1.0,
) -> tuple[float, str]:
    """Per-proc damage from the build's active Spellblade (if any).

    Identifies Spellblade-family items by ``unique_passive_key="spellblade"``
    - Trinity Force / Lich Bane / Essence Reaver / Iceborn Gauntlet /
    Dusk+Dawn / Divine Sunderer / Sheen / Bloodsong (+ Arena mirrors).
    ``collect_effects`` enforces the unique-passive dedup upstream (first-
    seen-wins), so iterating ``effects`` yields at most one Spellblade
    item.

    Returns ``(per_proc_damage, item_name)``. The damage value applies
    the standard pipeline: ``resolve_damage(call_ctx)`` for the per-proc
    base, ``_armor_factor`` against the appropriate resist (armor for
    PHYSICAL, MR for MAGIC, bypass for TRUE), mode multiplier, type-
    selective ``magic_amp`` (only for MAGIC), and build-wide
    ``damage_amp``. Empty builds yield ``(0.0, "")``.

    Used by ``burst.compute_burst_damage`` (Phase 5.7, s189): the combo
    walker arms Spellblade on each ability cast and consumes it on the
    next AA, attributing this per-proc damage to that ComboCast row.
    Differs from ``_per_attack_proc_damage`` (which handles every-AA
    on-hit) in that Spellblade fires once per ability-then-AA transition
    rather than once per AA - the model matches in-game behavior in a
    single-combo window where the 1.5s internal CD is irrelevant.
    """
    for e in effects:
        if e.unique_passive_key != SPELLBLADE_UNIQUE_KEY:
            continue
        for proc in e.periodics:
            is_physical = proc.damage_type == PHYSICAL
            is_true = proc.damage_type == TRUE
            resist = 0.0 if is_true else (
                target_armor_for_physical if is_physical else target_mr
            )
            type_amp = 1.0 if (is_physical or is_true) else magic_amp
            dmg = proc.resolve_damage(call_ctx)
            per_proc = dmg * _armor_factor(resist) * mode_dmg_mult * type_amp * damage_amp
            return (per_proc, e.name)
    return (0.0, "")


def _per_attack_proc_damage(
    effects: list[ItemEffect],
    target_armor_for_physical: float,
    target_mr: float,
    mode_dmg_mult: float,
    call_ctx: CallContext,
    magic_amp: float = 1.0,
    damage_amp: float = 1.0,
    apply_melee_aa_gate: bool = False,
) -> float:
    """Per-attack on-hit proc damage (post-mit, post-mode, post-amps).

    Sister function to ``_periodic_proc_dps`` but with a per-attack
    semantic instead of per-second: each ``every_n_attacks`` proc
    contributes ``1 / every_n_attacks`` of its damage per AA, amortized
    across the burst window. Time-based procs (``every_n_seconds``) are
    skipped - they don't fit a single-attack window cleanly and are
    already captured at the rotation level in ``_periodic_proc_dps``.

    Used by ``burst.compute_burst_damage`` (Phase 5.6, s188) so each AA
    token in an assassin's combo gets the on-hit contribution from items
    like Wit's End (+15-80 magic damage on attack), BotRK Mist's Edge
    (5% target current HP), Statikk Shiv (4-stack proc), Triforce
    Spellblade (off base_ad), Lich Bane (AP-scaling spellblade), etc.

    Returns the total on-hit damage a single AA contributes - already
    armor/MR-mitigated, mode-multiplied, magic-amp-applied for magical
    procs, and wrapped in ``damage_amp`` to match the rotation pipeline.
    """
    total = 0.0
    for e in effects:
        for proc in e.periodics:
            # B1 (1.141.0): ranged-only proc contributes nothing on a melee
            # auto. Default-OFF -> never skips (byte-identical to pre-B1 burst).
            if apply_melee_aa_gate and call_ctx.is_melee and proc.ranged_only:
                continue
            if proc.every_n_attacks <= 0:
                continue
            # ENGINE 1.26.0 (2026-05-21): stack-ramp-gated procs (Dead
            # Man's Plate Shipwrecker; future stack-discharge items) do
            # NOT contribute meaningfully to a burst-window per-attack
            # tally - the ramp typically exceeds the burst window (2-3s
            # vs 3.57s ramp for Dead Man's), and these are tank items
            # whose DPS contribution is sustained-only. Skip in burst
            # to avoid over-attributing per-AA on items whose proc
            # cannot have accumulated by attack #1. Sustained DPS still
            # captures the contribution via _periodic_proc_dps.
            if proc.stack_ramp_seconds > 0:
                continue
            procs_per_aa = 1.0 / proc.every_n_attacks
            is_physical = proc.damage_type == PHYSICAL
            is_true = proc.damage_type == TRUE
            resist = 0.0 if is_true else (target_armor_for_physical if is_physical else target_mr)
            type_amp = 1.0 if (is_physical or is_true) else magic_amp
            dmg = proc.resolve_damage(call_ctx)
            total += procs_per_aa * dmg * _armor_factor(resist) * mode_dmg_mult * type_amp
    return total * damage_amp


def _rotation_attack_dps(
    stats: dict[str, float],
    rotation: dict,
    target_armor_for_physical: float,
    target_mr: float,
    mode_dmg_mult: float,
    crit_bonus: float,
    effects: list[ItemEffect],
    call_ctx: CallContext,
    damage_amp: float = 1.0,
    magic_amp: float = 1.0,
    aa_empower_amp: float = 1.0,
    apply_melee_aa_gate: bool = False,
) -> float:
    """DPS contribution from basic attacks during a single rotation.

    ``total_attacks = basic + basicTime * AS``. Each attack lands ``AD``
    pre-resists, scaled by crit average and the mode damage multiplier,
    then divided by full rotation duration (which includes time spent
    casting abilities - auto DPS is naturally diluted in cast-heavy
    rotations). ``target_armor_for_physical`` already has reduction +
    pen applied at the caller. Conditional procs from items add on top
    via ``_periodic_proc_dps``.

    Phase 4 batch 14 (2026-05-04): ``damage_amp`` is the build's
    multiplicative damage-amp factor (Riftmaker Void Corruption,
    future Conqueror-style amps). Applied to both base AA and proc
    DPS - in-game amps don't discriminate damage type. Default 1.0
    keeps pre-batch behavior unchanged.

    Phase 4 batch 34 (2026-05-04): ``magic_amp`` applies only to magical
    proc DPS inside ``_periodic_proc_dps`` - does NOT touch base AA
    (physical). Default 1.0 keeps pre-batch behavior unchanged.

    Item 247 (gap-plan Phase C2): ``aa_empower_amp`` scales ONLY the base AA
    component (not item proc DPS) - it is the AA-empowerment amp seam for the
    5 ``base="aa"`` AmpEntry champs (Caitlyn W / Fiora E / Jayce W f1 / Sivir W
    / Nidalee Q). Default 1.0 = byte-identical; the seam is gated on
    ``compute_dps(apply_ability_amps=True)`` and currently inert (placeholder
    entries, Phase D authors the real per-champ value).
    """
    duration = float(rotation.get("duration", 0) or 0)
    if duration <= 0:
        return 0.0
    basic = float(rotation.get("basic", 0) or 0)
    basic_time = float(rotation.get("basicTime", 0) or 0)
    eff_as = float(stats.get("as", 0.0))
    total_attacks = basic + basic_time * eff_as
    if total_attacks <= 0:
        return 0.0
    ad = float(stats.get("ad", 0.0))
    crit = min(float(stats.get("crit", 0.0)), 1.0)
    armor_factor = _armor_factor(target_armor_for_physical)
    avg_dmg = ad * (1 + crit * crit_bonus) * armor_factor * mode_dmg_mult
    base_dps = total_attacks * avg_dmg / duration
    # Phase 4 batch 7 (2026-05-04): rebind call_ctx with this rotation's
    # numberOfTargets. Cleave-to-others procs (Ravenous Hydra) reference
    # targets_in_rotation; default 1.0 keeps every other proc unchanged.
    rotation_targets = float(rotation.get("numberOfTargets", 1.0) or 1.0)
    rotation_ctx = replace(call_ctx, targets_in_rotation=rotation_targets)
    proc_dps = _periodic_proc_dps(
        effects, total_attacks, duration,
        target_armor_for_physical, target_mr, mode_dmg_mult, rotation_ctx,
        magic_amp=magic_amp, apply_melee_aa_gate=apply_melee_aa_gate,
    )
    return (base_dps * aa_empower_amp + proc_dps) * damage_amp


def _phase_weighted_dps(
    stats: dict[str, float],
    rotations: list[dict],
    target_armor_for_physical: float,
    target_mr: float,
    mode_dmg_mult: float,
    crit_bonus: float,
    effects: list[ItemEffect],
    call_ctx: CallContext,
    damage_amp: float = 1.0,
    magic_amp: float = 1.0,
    aa_empower_amp: float = 1.0,
    apply_melee_aa_gate: bool = False,
) -> float:
    """Weighted average of rotation DPS within a phase (weights from lolmath)."""
    if not rotations:
        return 0.0
    total_weight = 0.0
    weighted_sum = 0.0
    for r in rotations:
        w = float(r.get("weight", 0) or 0)
        if w <= 0:
            continue
        weighted_sum += w * _rotation_attack_dps(
            stats, r, target_armor_for_physical, target_mr,
            mode_dmg_mult, crit_bonus, effects, call_ctx, damage_amp,
            magic_amp=magic_amp, aa_empower_amp=aa_empower_amp,
            apply_melee_aa_gate=apply_melee_aa_gate,
        )
        total_weight += w
    if total_weight <= 0:
        return 0.0
    return weighted_sum / total_weight


def _phase_rotations(snapshot: DataSnapshot, champion_id: str) -> dict[str, list[dict]]:
    """Pull the first scenario block's per-phase rotations.

    Champions in the snapshot all expose at least one scenario record (the
    extractor's coverage check pins this). We use index 0 by convention -
    matches lolmath's UI default. Future revisions may add named scenario
    variants; pick by name then.
    """
    out: dict[str, list[dict]] = {p: [] for p in PHASES}
    scens = snapshot.scenarios(champion_id)
    if not scens:
        return out
    sc = (scens[0].get("settings", {}) or {}).get("scenario", {}) or {}
    for p in PHASES:
        rotations = sc.get(p, [])
        if isinstance(rotations, list):
            out[p] = rotations
    return out


def compute_dps(
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
    phase: Optional[str] = None,
    augments: Optional[Iterable] = None,
    apply_mode_modifiers: bool = False,
    apply_ability_amps: bool = False,
    apply_passive_damage: bool = False,
    assume_takedown: bool = False,
    apply_melee_aa_gate: bool = False,
    assume_passive_as_stacks: bool = False,
    apply_target_vuln: bool = False,
    assume_ally_detonation: bool = False,
) -> DpsResult:
    """Resolve auto-attack DPS for ``champion_id`` at ``level`` with items.

    ``mode='ARAM'`` applies ``aramAttackSpeed`` to bonus AS (in
    ``build_champion``) and ``aramDamageDealt`` to per-hit damage (here).
    ``phase`` overrides level-based selection; valid values:
    ``"early"|"mid"|"late"``.

    ``augments`` is an optional Arena augment list (apiName / id / record /
    Augment instance); the registered overlays add to stats before DPS
    resolution. Unknown augments are silently zero-overlay (see
    ``compute_augment_stats``).

    ``target_bonus_hp`` (Phase 4 batch 19, 2026-05-04): caller-supplied
    target bonus HP. Activates Giant Slayer-style target-conditional
    amps (LDR id 3036). Default 0.0 keeps pre-batch-19 calls
    behaviorally identical (the amp resolves to x1.0 with no signal).

    ``target_current_hp_pct`` (DS target-current-HP% lever, BACKLOG item):
    caller-supplied fraction (0.0-1.0) of the target's current HP vs its
    max HP. Scales ONLY the three genuine %-current-HP item procs (BotRK
    3153, Hellfire Hatchet 4017, Fulmination 443055) so a caller can model
    a chunked target; %-max-HP procs (Eclipse, Titanic Hydra, ...) are
    unaffected. Default 1.0 is an identity multiply - byte-identical to
    pre-lever output.

    ``assume_takedown`` (DSV2, 2026-06-15): the takedown / kill-state OFFENSE
    seam. Default False -> byte-identical. When True, Hubris Eminence's bonus
    AD (15 + 2 * ``_ASSUMED_TAKEDOWN_STACKS``) is folded into the wielder's
    bonus AD, raising AA + bonus-AD-scaling-proc DPS. The Collector execute is
    deliberately NOT valued here (a one-shot finisher is not sustained DPS - it
    is credited by ``compute_burst_damage`` instead).

    ``apply_melee_aa_gate`` (B1, 1.141.0): the melee-applicability gate. Default
    False -> byte-identical. When True and the champion is melee (attackrange <
    ``MELEE_RANGE_CEILING``), ``PeriodicProc.ranged_only`` procs (Runaan's
    Hurricane bolts - a ranged-basic-only on-hit) contribute 0 DPS, so a melee
    champion is no longer credited the two extra bolts. Ranged champions are
    unaffected even when the seam is on. The live rank.py flip stays
    validation-gated (do-not-flip-blind); see docs/LIVE_GAME_GATED_SYNC.md.

    ``assume_passive_as_stacks`` (R7, 1.147.0): the per-stack champion self-AS
    passive seam. Default False -> byte-identical (no stats copy). When True, the
    champion's registered innate per-stack bonus attack speed (Irelia Ionian
    Fervor / Jax Relentless Assault / Ezreal Rising Spell Force / Volibear The
    Relentless Storm) at ``_ASSUMED_PASSIVE_AS_STACK_FRACTION`` of max stacks is
    folded into the rotation AS (same 2.5 hard-cap re-clamp as the Yun Tal
    conditional-AS path). The AP-scaled passive (Volibear) reads the resolved
    post-amp AP. A champion with no registered passive contributes 0 even with
    the flag on. The live default-ON flip stays validation-gated (do-not-flip-
    blind); see docs/LIVE_GAME_GATED_SYNC.md.
    """
    level = clamp_level(level)
    selected_phase = phase or _select_phase(level)
    if selected_phase not in PHASES:
        raise ValueError(
            f"phase must be one of {PHASES}, got {selected_phase!r}"
        )

    resolved = build_champion(
        snapshot, champion_id, level, item_ids=item_ids, mode=mode,
        augments=augments, apply_mode_modifiers=apply_mode_modifiers,
    )
    stats = resolved.stats

    champ = snapshot.champion(resolved.champion_id)
    aram = ((champ.get("lolmath") or {}).get("aram_modifiers") or {})
    mode_mult = 1.0
    if mode == "ARAM":
        mode_mult = float(aram.get("aramDamageDealt", 1.0))
    elif apply_mode_modifiers:
        # item 232: OPT-IN wiki mode_modifiers sidecar for the non-ARAM
        # modes (urf/ofa/usb/nb dmg_dealt MULTIPLIERS). ARAM keeps its
        # authoritative legacy lolmath path above - do NOT route ARAM
        # through the wiki sidecar (avoids double-count). SR + unknown +
        # addend-only modes (ARENA/swift carry no dmg_dealt) leave
        # mode_mult=1.0, so output stays byte-identical unless the flag is
        # True AND the mode has a wiki dmg_dealt entry. Mirrors item 231's
        # gate_ammo opt-in precedent: default False = byte-identical.
        mm = snapshot.mode_modifier(resolved.champion_id, mode)
        if isinstance(mm, dict) and "dmg_dealt" in mm:
            mode_mult = float(mm["dmg_dealt"])

    # Item 247 (gap-plan Phase C2): AA-empowerment amp seam. OPT-IN
    # (apply_ability_amps default False = byte-identical). When True, the 5
    # base="aa" AmpEntry champs (Caitlyn W / Fiora E / Jayce W f1 / Sivir W /
    # Nidalee Q) scale ONLY the base-AA component (not item procs) by their
    # amortized empowerment factor. The rank lookup uses the canonical
    # 1-point-per-level distribution; rank_at_level is imported function-level
    # to avoid the dps <-> ability_dps module cycle. FORWARD-MARKER: the
    # entries are placeholder (0.0,) today, so the factor is 1.0 - the seam is
    # route-reachable + inert until Phase D authors the real per-champ value.
    aa_empower_amp = 1.0
    if apply_ability_amps:
        from ._ability_amp_overrides import _aa_amp_multiplier
        from .ability_dps import rank_at_level

        aa_empower_amp = _aa_amp_multiplier(
            resolved.champion_id, lambda k: rank_at_level(k, level)
        )

    item_effects = collect_effects(resolved.item_ids)
    crit_bonus = DEFAULT_CRIT_BONUS + total_crit_damage_bonus(item_effects)
    # Phase 4 batch 14 (2026-05-04): build-wide damage amp. 1.0 when no
    # items carry an amp, so pre-batch builds pass through unchanged.
    damage_amp = total_damage_amp_multiplier(item_effects)
    # Phase 4 batch 19 (2026-05-04): target-conditional amp (LDR Giant
    # Slayer). Stacks multiplicatively with damage_amp_pct items per
    # League's buff-system pin from batch 14. x1.0 when caller leaves
    # target_bonus_hp at 0 OR when no item carries the schema field.
    target_amp = total_target_bonus_hp_amp_multiplier(item_effects, target_bonus_hp)
    damage_amp *= target_amp

    # Phase 4 expansion: armor reduction + pen pipeline. Phase 4 batch 4
    # (2026-05-04) added the symmetric magic pen pipeline (Void Staff,
    # Cryptbloom, Sorcerer's Shoes, Shadowflame).
    target_armor_eff = effective_target_armor(target_armor, item_effects, level)
    target_mr_eff = effective_target_mr(target_mr, item_effects)

    # Build call context once per compute_dps. base_ad comes from the
    # leveled champion base (pre-items); bonus_ad is total - base. Same
    # base/bonus split for HP (Phase 4 batch 6, 2026-05-04) - Titanic
    # Hydra scales off bonus HP, Heartsteel scales off max HP, so we
    # surface both. Engine-derived (unlike target_max_hp): the engine
    # always knows the caster's exact HP from the build.
    base_ad = float(resolved.base_stats.get("ad", 0.0)) if resolved.base_stats else 0.0
    total_ad = float(stats.get("ad", 0.0))
    bonus_ad = max(0.0, total_ad - base_ad)
    # DSV2 (1.125.0): takedown / kill-state OFFENSE seam. assume_takedown=False
    # (the default) -> takedown_bonus_ad stays 0.0 and every line below is
    # byte-identical. When True, Hubris Eminence's bonus AD (15 + 2*stacks at
    # _ASSUMED_TAKEDOWN_STACKS) folds into the wielder's bonus AD so it raises
    # both the AA rotation (via stats_for_rotation["ad"]) and bonus_ad-scaling
    # procs (via CallContext.bonus_ad). The Collector execute is NOT credited
    # here - a one-shot finisher is not sustained DPS; the burst scorer values
    # it. A build without a takedown-AD item contributes 0 even when the flag
    # is set (total_takedown_bonus_ad returns 0.0).
    takedown_bonus_ad = 0.0
    if assume_takedown:
        takedown_bonus_ad = total_takedown_bonus_ad(
            item_effects, _ASSUMED_TAKEDOWN_STACKS
        )
        bonus_ad += takedown_bonus_ad
    ap = float(stats.get("ap", 0.0))
    base_hp = float(resolved.base_stats.get("hp", 0.0)) if resolved.base_stats else 0.0
    caster_max_hp = float(stats.get("hp", 0.0))
    caster_bonus_hp = max(0.0, caster_max_hp - base_hp)
    # Phase 4 batch 58 (2026-05-04): caster bonus armor - item-contributed
    # armor above the champion's leveled base. Same base/bonus split as
    # caster_bonus_hp. Required for Darksteel Talons' Gash (+ 20% bonus armor).
    base_armor = float(resolved.base_stats.get("armor", 0.0)) if resolved.base_stats else 0.0
    caster_bonus_armor = max(0.0, float(stats.get("armor", 0.0)) - base_armor)
    # Phase 4 batch 59 (2026-05-04): caster raw lethality - sum of all items'
    # lethality values (un-scaled, before level conversion). Required for
    # Bastionbreaker's Shaped Charge (15 + 0.75 x lethality true damage / 45s).
    caster_lethality = sum(e.lethality for e in item_effects)
    # Phase 4 batch 38 (2026-05-04): Giant Slayer target max HP advantage amp.
    # Stacks multiplicatively with damage_amp (same buffer-system doctrine as
    # target_amp from batch 19). Resolved here because caster_max_hp is needed.
    giant_slayer_amp = total_giant_slayer_multiplier(item_effects, target_max_hp, caster_max_hp)
    damage_amp *= giant_slayer_amp
    # Phase 4 batch 27 (2026-05-04): caster max mana - needed for Manamune /
    # Muramana's Awe (already folded into ad_flat by build_champion) and
    # Muramana's Shock proc (per-attack 1.2% max mana physical). Manaless
    # champions and pre-batch-27 builds carry stats["mp"]=0 -> 0 contribution.
    caster_max_mp = float(stats.get("mp", 0.0))
    # Phase 4 batch 15 (2026-05-04): cross-derived AP from caster bonus
    # HP (Riftmaker's Void Infusion). Added to ap before CallContext
    # is built so AP-scaling procs (Lich Bane, Nashor's Tooth) see the
    # converted total. Stays out of resolved.stats - /stats reflects
    # raw stat blocks; /dps reflects converted totals.
    ap_from_hp = total_bonus_ap_from_hp(item_effects, caster_bonus_hp)
    ap += ap_from_hp
    # Phase 4 batch 54 (2026-05-04): stacked AP from kill-stack passives
    # (Mejai's Glory). Inserted BEFORE ap_amp so Rabadon's Magical Opus
    # amplifies the full AP total including stacked AP - Glory AP is real
    # AP. Raw stat blocks (/stats) unchanged; only CallContext.ap sees it.
    stacked_ap = total_stacked_ap(item_effects)
    ap += stacked_ap
    # Phase 4 batch 32 (2026-05-04): multiplicative AP amplifier. Applied
    # after ap_from_hp + stacked_ap so Rabadon's Magical Opus boosts ALL
    # AP, including the HP-converted and kill-stacked contributions.
    # Raw stat blocks (/stats) unchanged; only CallContext.ap sees it.
    ap_amp = total_ap_amp_multiplier(item_effects)
    if ap_amp != 1.0:
        ap *= ap_amp
    # Phase 4 batch 56 (2026-05-04): caster HP-scaled multiplicative AP amp.
    # Demonic Embrace (444637 Arena) Sinister Pact: +1.5% AP per 100 HP,
    # capped at 45%. Applied AFTER Rabadon's (ap_amp) so the amplified AP
    # feeds into this second multiplicative layer - consistent with League's
    # buff-system stacking: each multiplier applies to the running total.
    hp_ap_amp = total_caster_hp_scaled_ap_amp(item_effects, caster_max_hp)
    if hp_ap_amp != 1.0:
        ap *= hp_ap_amp
    # Phase 4 batch 21 (2026-05-04): crit_chance plumbed into CallContext
    # for ER Spellblade (+0.5 bonus physical per 1% crit).
    # Phase 4 batch 26 (2026-05-04): item-effect-contributed crit
    # (Yun Tal Wildarrows flat 25% + Atma's Big Hands HP-scaled). Summed
    # into the build's stats.crit and clamped at 1.0; the boosted total
    # flows through both the rotation auto-attack crit calc (via
    # ``stats_for_rotation``) and CallContext.crit_chance (read by ER
    # Spellblade's lambda + future crit-scaling procs). /stats endpoint
    # output is unchanged - same separation as batch 15's HP->AP cross-
    # derivation. ``crit_from_effects`` is 0.0 when no item carries
    # either crit_chance_bonus field, so pre-batch-26 builds pass
    # through behaviorally identical.
    crit_from_effects = total_crit_chance_bonus(item_effects, caster_bonus_hp)
    raw_crit = float(stats.get("crit", 0.0))
    crit_total = min(raw_crit + crit_from_effects, 1.0)
    if crit_from_effects > 0:
        stats_for_rotation: dict[str, float] = dict(stats)
        stats_for_rotation["crit"] = crit_total
    else:
        stats_for_rotation = stats
    crit_chance_ctx = crit_total
    # Phase 4 batch 54 (2026-05-04): conditional bonus AS (Yun Tal Flurry).
    # Added to stats_for_rotation["as"] alongside crit_from_effects - both
    # are DPS-time cross-derivations that don't appear in /stats. The AS
    # value is uptime-weighted (0.08 for Yun Tal at ~27% uptime).
    cond_as = total_conditional_as(item_effects)
    if cond_as > 0:
        if stats_for_rotation is stats:
            stats_for_rotation = dict(stats)
        # R42 (1.157.0): cond_as is a bonus-AS FRACTION (Yun Tal Flurry,
        # uptime-weighted ~0.08 = +8% bonus AS), but stats["as"] is FINAL
        # attacks/sec (engine resolves it as base_as * (1 + bonus_pct)). League
        # folds bonus AS onto the INNATE base AS, so scale the fraction by
        # base_as before adding to the final AS - adding the raw fraction
        # over-credits by 1/base_as. Mirrors the R7 passive_as fold directly
        # below. The 2.5 League hard-cap re-clamp still applies after the fold.
        innate_base_as = float(
            (champ.get("stats") or {}).get("attackspeed", 0.0) or 0.0
        )
        stats_for_rotation["as"] = min(
            2.5, stats_for_rotation.get("as", 0.0) + innate_base_as * cond_as
        )
    # DSV2 (1.125.0): fold the takedown bonus AD into the rotation AD so the
    # AA damage reflects Hubris Eminence. Gated on > 0 so the OFF path (and any
    # non-Hubris build) never copies stats - byte-identical to pre-DSV2.
    if takedown_bonus_ad > 0:
        if stats_for_rotation is stats:
            stats_for_rotation = dict(stats)
        stats_for_rotation["ad"] = (
            stats_for_rotation.get("ad", 0.0) + takedown_bonus_ad
        )
    # R7 (1.147.0): per-stack champion self-Attack-Speed passive seam.
    # assume_passive_as_stacks=False (the default) -> passive_as stays 0.0, no
    # stats copy, no note - byte-identical. When True, the champion's registered
    # innate per-stack bonus AS (Irelia/Jax/Ezreal/Volibear) at
    # _ASSUMED_PASSIVE_AS_STACK_FRACTION of max stacks folds into the rotation AS
    # with the same 2.5 League hard-cap re-clamp as the Yun Tal conditional-AS
    # path above. The AP-scaled passive (Volibear) reads the resolved post-amp
    # `ap`. A champion with no registered passive contributes 0.
    passive_as = 0.0
    if assume_passive_as_stacks:
        from ._passive_as_overrides import passive_as_bonus

        passive_as = passive_as_bonus(
            resolved.champion_id, level, ap=ap,
            stack_fraction=_ASSUMED_PASSIVE_AS_STACK_FRACTION,
        )
        if passive_as > 0:
            if stats_for_rotation is stats:
                stats_for_rotation = dict(stats)
            # passive_as is a bonus-AS FRACTION (Irelia full stacks L18 = 1.0 =
            # +100%), but stats["as"] is FINAL attacks/sec (engine resolves it as
            # base_as * (1 + bonus_pct)). League folds bonus AS onto the INNATE
            # base AS, so scale the fraction by base_as before adding to the
            # final AS - adding the raw fraction over-credits by 1/base_as. The
            # 2.5 League hard-cap re-clamp still applies after the fold.
            innate_base_as = float(
                (champ.get("stats") or {}).get("attackspeed", 0.0) or 0.0
            )
            stats_for_rotation["as"] = min(
                2.5, stats_for_rotation.get("as", 0.0) + innate_base_as * passive_as
            )
    # Phase 4 batch 63 (2026-05-05): per-champion ult cast rate for
    # ability-triggered items (Malignance Hatefog). Looked up from
    # ult_cast_rates.json derived from rewind_history.db spell4_casts.
    ult_casts_per_sec = get_ult_casts_per_sec(resolved.champion_name, mode)
    call_ctx = CallContext(
        base_ad=base_ad,
        bonus_ad=bonus_ad,
        level=level,
        target_armor=target_armor_eff,
        target_mr=target_mr_eff,
        ap=ap,
        target_max_hp=target_max_hp,
        caster_max_hp=caster_max_hp,
        caster_bonus_hp=caster_bonus_hp,
        target_bonus_hp=target_bonus_hp,
        crit_chance=crit_chance_ctx,
        caster_max_mp=caster_max_mp,
        caster_bonus_armor=caster_bonus_armor,
        caster_lethality=caster_lethality,
        ult_casts_per_sec=ult_casts_per_sec,
        target_current_hp_pct=target_current_hp_pct,
        is_melee=float((champ.get("stats") or {}).get("attackrange", 0) or 0) < MELEE_RANGE_CEILING,
    )

    # Phase 4 batch 34 (2026-05-04): magic-only target-debuff amp.
    # Abyssal Mask Unmake: 12% more magic damage taken by nearby enemies.
    # Applied inside _periodic_proc_dps per-proc (magical only), not to
    # physical auto-attack damage. 1.0 when no item carries magic_amp_pct.
    magic_amp = total_magic_amp_multiplier(item_effects)

    rotations_by_phase = _phase_rotations(snapshot, resolved.champion_id)
    phase_dps = {
        p: _phase_weighted_dps(
            stats_for_rotation, rotations_by_phase[p], target_armor_eff, target_mr_eff,
            mode_mult, crit_bonus, item_effects, call_ctx, damage_amp,
            magic_amp=magic_amp, aa_empower_amp=aa_empower_amp,
            apply_melee_aa_gate=apply_melee_aa_gate,
        )
        for p in PHASES
    }
    weighted_dps = phase_dps[selected_phase]

    crit = crit_total
    # DSV2 (1.125.0): the per-hit display AD (avg_attack_dmg / raw_attack_dps,
    # read by burst.compute_burst_damage as the AA per-hit) includes the
    # takedown bonus AD. 0.0 when the seam is OFF -> byte-identical.
    ad = float(stats.get("ad", 0.0)) + takedown_bonus_ad
    eff_as = float(stats.get("as", 0.0))
    # Phase 4 batch 14: per-hit display value reflects the same amp the
    # rotation DPS uses, so /dps clients see consistent numbers. Item 247:
    # the AA-empower amp is a pure-AA factor, so the per-hit displays carry it
    # too (1.0 default -> byte-identical).
    avg_attack_dmg = ad * (1 + crit * crit_bonus) * _armor_factor(target_armor_eff) * mode_mult * damage_amp * aa_empower_amp
    raw_attack_dps = ad * eff_as * (1 + crit * crit_bonus) * aa_empower_amp
    # Phase 5.6 (s188, 2026-05-13): per-attack on-hit proc damage. Used
    # by burst.compute_burst_damage to score AA tokens richer than raw
    # AD-on-armor - captures Wit's End / BotRK / Statikk contributions
    # to a single AA hit. Falls out of compute_dps so the AA scorer in
    # burst.py doesn't need to re-derive call_ctx / effects. Spellblade
    # is NOT included here (it's time-based, not attack-based) - see
    # ``spellblade_per_proc_damage`` below.
    per_attack_on_hit_damage = _per_attack_proc_damage(
        item_effects, target_armor_eff, target_mr_eff, mode_mult,
        call_ctx, magic_amp=magic_amp, damage_amp=damage_amp,
        apply_melee_aa_gate=apply_melee_aa_gate,
    )
    # Phase 5.7 (s189, 2026-05-13): Spellblade per-proc damage. Returned
    # to burst.py separately from per_attack_on_hit_damage because
    # Spellblade fires once per ability-then-AA transition (not once per
    # AA). collect_effects dedups the spellblade family via
    # unique_passive_key - at most one Spellblade item survives, so the
    # helper returns one (damage, name) tuple.
    spellblade_per_proc, spellblade_name = _spellblade_per_proc_damage(
        item_effects, target_armor_eff, target_mr_eff, mode_mult,
        call_ctx, magic_amp=magic_amp, damage_amp=damage_amp,
    )
    # Phase 5.8 (s190, 2026-05-13): Lightshield Strike per-proc damage -
    # Sundered Sky's distinct mechanic (different name, 8s CD, no dedup
    # with the spellblade family). Tracked separately so a build with
    # both Sundered Sky + Trinity Force fires BOTH on the same AA.
    lightshield_strike_per_proc, lightshield_strike_name = (
        _lightshield_strike_per_proc_damage(
            item_effects, target_armor_eff, target_mr_eff, mode_mult,
            call_ctx, magic_amp=magic_amp, damage_amp=damage_amp,
        )
    )

    notes = list(resolved.notes)

    # Degenerate-scenario fallback (Aphelios dps zero-output, found in the
    # per-champion cross-eval - ops/audit/ds_cross_eval/SYSTEMIC_FINDINGS.md
    # Cluster C). When the champion's laning-scenario rotations encode zero
    # basic attacks in EVERY phase (Aphelios weapon-swap kit, whose upstream
    # lolmath rotations are modeled as pure casts with basic=0), the basic-
    # attack-portion weighted_dps collapses to 0.0 - every item delta becomes
    # 0 and the ranker degenerates to starter items. Fall back to the mode-
    # adjusted raw attack DPS (AD * AS * crit * mode_mult, fully item-
    # responsive) so item ranking stays meaningful.
    #
    # The ``mode_mult > 0`` gate is load-bearing: a champion ARAM-DISABLED at
    # the snapshot patch (aramDamageDealt=0, e.g. Yunara pre-16.11.1) has
    # mode_mult=0 and MUST stay weighted_dps=0 - that is a real "deals no
    # damage in this mode" zero, not a scenario gap. raw_attack_dps is mode-
    # independent so it is >0 even for a disabled champ; multiplying by
    # mode_mult keeps a disabled champ at 0 AND scales an enabled champ's
    # fallback by the ARAM modifier, consistent with avg_attack_dmg. Guarded
    # on ALL phases == 0, so the champs with real basic-attack rotations are
    # byte-identical.
    if raw_attack_dps > 0.0 and mode_mult > 0.0 and not any(phase_dps.values()):
        fallback_dps = raw_attack_dps * mode_mult
        weighted_dps = fallback_dps
        phase_dps = {p: fallback_dps for p in PHASES}
        notes.append(
            "weighted_dps fell back to raw_attack_dps*mode_mult (scenario "
            "rotations encode zero basic attacks for this champion)"
        )

    if takedown_bonus_ad > 0:
        notes.append(
            f"takedown bonus AD +{takedown_bonus_ad:.0f} "
            f"(Hubris Eminence at {_ASSUMED_TAKEDOWN_STACKS} assumed stack(s); "
            "assume_takedown kill-state seam)"
        )

    # Section-2 cadence routing (04_GAPS_AND_ROADMAP): route an on_hit
    # passive's damage onto the AUTO-ATTACK cadence. OPT-IN -
    # apply_passive_damage default False = byte-identical (the seam adds
    # nothing). When True, the allowlisted every-AA on_hit passive (Warwick
    # Eternal Hunger / Orianna Clockwork Winding) evaluates its per-hit bonus
    # through the canonical passive-block path, mitigates it by the entry's
    # damage type (same resistance curve the AA uses), and adds it to the
    # per-hit display AND the steady DPS (per_hit * eff_as) across every
    # phase. This is the consumer the passive-damage registry needed: the
    # injected P-form block is inert in every other scorer (compute_ability_dps
    # skips the P slot). The default-on FLIP + the non-every-AA on_hit entries
    # (mark-consume / internal-CD / empowered-first-hit) stay gated.
    passive_aa_per_hit = 0.0
    if apply_passive_damage:
        from ._passive_damage_overrides import (
            aa_routed_on_hit_entry,
            to_damage_block,
        )
        from .ability_dps import AbilityContext, _evaluate_block
        from .ability_dps import rank_at_level as _rank_at_level

        _routed = aa_routed_on_hit_entry(resolved.champion_id)
        if _routed is not None:
            _pkey, _pentry = _routed
            _pblock = to_damage_block(_pentry)
            _pctx = AbilityContext.from_build(
                stats=stats,
                base_stats=resolved.base_stats or {},
                target_armor=target_armor,
                target_mr=target_mr,
                target_max_hp=target_max_hp,
                target_bonus_hp=target_bonus_hp,
            )
            _praw = _evaluate_block(_pblock, _rank_at_level("P", level), _pctx)
            if _praw > 0.0:
                if _pentry.damage_type == "PHYSICAL":
                    _pmit = _armor_factor(target_armor_eff)
                elif _pentry.damage_type == "TRUE":
                    _pmit = 1.0
                else:  # MAGIC - same resistance curve, plus magic-debuff amp
                    _pmit = _armor_factor(target_mr_eff) * magic_amp
                passive_aa_per_hit = _praw * _pmit * mode_mult * damage_amp
                _passive_dps = passive_aa_per_hit * eff_as
                weighted_dps += _passive_dps
                phase_dps = {p: v + _passive_dps for p, v in phase_dps.items()}
                per_attack_on_hit_damage += passive_aa_per_hit
                notes.append(
                    f"on_hit passive {_pentry.attribute} routed to AA cadence: "
                    f"+{passive_aa_per_hit:.1f}/hit ({_pentry.damage_type}), "
                    f"+{_passive_dps:.1f} DPS (apply_passive_damage)"
                )

    # R12 (1.149.0): all-source target-vulnerability mark seam. A vulnerability
    # mark (Vladimir R Hemoplague, Evenshroud Coruscation) makes the marked
    # target take +X% damage FROM ALL SOURCES, so it scales the wielder's whole
    # DPS output - AAs, item procs, AND the routed on-hit passive above. OPT-IN:
    # default apply_target_vuln=False never resolves the multiplier, so the
    # AA-DPS path is byte-identical. When True the marked-target scenario is
    # assumed live (the assume_takedown / assume_ability_amp developed-fight
    # doctrine); the multiplier is the product of every mark the wielder owns
    # (her champion ability + each registered build item), multiplicative per
    # independent amp source. Live default-ON flip EXCLUDED -> docs/LIVE_GAME_GATED_SYNC.md.
    if apply_target_vuln:
        from ._target_vulnerability_overrides import target_vuln_multiplier

        _vuln_mult = target_vuln_multiplier(resolved.champion_id, resolved.item_ids)
        if _vuln_mult != 1.0:
            weighted_dps *= _vuln_mult
            phase_dps = {p: v * _vuln_mult for p, v in phase_dps.items()}
            notes.append(
                f"all-source target-vulnerability mark x{_vuln_mult:.4f} "
                f"(+{(_vuln_mult - 1.0) * 100:.2f}% to all damage on the marked "
                "target; apply_target_vuln seam)"
            )

    if mode == "ARAM" and mode_mult != 1.0:
        notes.append(f"ARAM aramDamageDealt={mode_mult:.2f} on per-hit damage")
    if target_armor_eff != target_armor:
        notes.append(
            f"effective target armor {target_armor:.1f} -> {target_armor_eff:.1f}"
            " after reduction + pen"
        )
    if target_mr_eff != target_mr:
        notes.append(
            f"effective target MR {target_mr:.1f} -> {target_mr_eff:.1f}"
            " after magic pen"
        )
    if damage_amp != 1.0:
        notes.append(
            f"build damage amp x{damage_amp:.4f} "
            f"(+{(damage_amp - 1.0) * 100:.2f}% to all damage)"
        )
    if target_amp != 1.0:
        notes.append(
            f"target-conditional amp x{target_amp:.4f} "
            f"(target_bonus_hp={target_bonus_hp:.0f}, "
            f"+{(target_amp - 1.0) * 100:.2f}% folded into build amp)"
        )
    if giant_slayer_amp != 1.0:
        hp_diff = max(0.0, target_max_hp - caster_max_hp)
        notes.append(
            f"Giant Slayer HP-advantage amp x{giant_slayer_amp:.4f} "
            f"(target {target_max_hp:.0f} - caster {caster_max_hp:.0f} = {hp_diff:.0f} HP diff -> "
            f"+{(giant_slayer_amp - 1.0) * 100:.2f}% all damage)"
        )
    if ap_from_hp > 0:
        notes.append(
            f"caster AP cross-derived from bonus HP: +{ap_from_hp:.1f} AP "
            f"(total AP for procs: {ap:.1f})"
        )
    if stacked_ap > 0:
        notes.append(
            f"Mejai's stacked AP: +{stacked_ap:.0f} AP (full-stacks pin; "
            f"total AP for procs: {ap:.1f})"
        )
    if hp_ap_amp != 1.0:
        notes.append(
            f"caster HP-scaled AP amp x{hp_ap_amp:.4f} "
            f"(Demonic Embrace Sinister Pact at {caster_max_hp:.0f} HP; "
            f"total AP for procs: {ap:.1f})"
        )
    if cond_as > 0:
        notes.append(
            f"conditional AS bonus: +{cond_as * 100:.1f}% bonus AS "
            "(Yun Tal Flurry ~27% uptime, folded onto base AS)"
        )
    if passive_as > 0:
        notes.append(
            f"per-stack self-AS passive: +{passive_as * 100:.1f}% bonus AS "
            f"({resolved.champion_name} at {_ASSUMED_PASSIVE_AS_STACK_FRACTION:.0%} "
            "of max stacks; assume_passive_as_stacks seam, folded onto base AS)"
        )
    if ap_amp != 1.0:
        notes.append(
            f"AP amplified x{ap_amp:.4f} by Rabadon's Deathcap "
            f"(effective AP for procs: {ap:.1f})"
        )
    if magic_amp != 1.0:
        notes.append(
            f"magic damage amp x{magic_amp:.4f} (Abyssal Mask Unmake "
            f"+{(magic_amp - 1.0) * 100:.0f}% magic damage to target)"
        )
    if crit_from_effects > 0:
        # Phase 4 batch 26 (2026-05-04): surface item-effect-contributed
        # crit so /dps clients can see when crit was lifted off raw stats
        # alone (Yun Tal pin / Atma HP-scaled). When raw + bonus > 1.0
        # the effective value is clamped at 1.0 - surface both the raw
        # contribution and the post-clamp final to make the cap visible.
        notes.append(
            f"crit chance lifted by items: +{crit_from_effects * 100:.1f}% "
            f"(raw {raw_crit * 100:.1f}% + items -> effective {crit_total * 100:.1f}%)"
        )
    if spellblade_per_proc > 0:
        notes.append(
            f"Spellblade ({spellblade_name}) per-proc {spellblade_per_proc:.1f} "
            "(consumed by next AA after spell cast; burst.py models the "
            "ability-then-AA transition)"
        )
    if lightshield_strike_per_proc > 0:
        notes.append(
            f"Lightshield Strike ({lightshield_strike_name}) per-proc "
            f"{lightshield_strike_per_proc:.1f} (Sundered Sky 8s CD - fires once per "
            "burst combo on the AA after first spell cast; distinct from spellblade)"
        )
    for e in item_effects:
        if e.note:
            notes.append(e.note)
    if not any(rotations_by_phase.values()):
        notes.append("no scenarios in snapshot for this champion - DPS=0")
    elif not rotations_by_phase[selected_phase]:
        notes.append(f"no rotations defined for phase={selected_phase!r}")

    # R41 (1.156.0): ally mark-detonation seam. assume_ally_detonation=False (the
    # default) -> ally_detonation_dps stays 0.0 and weighted_dps / phase_dps are
    # byte-identical. When True, a champion whose mark an ALLY consumes for bonus
    # damage (Leona P Sunlight) is credited the amortized team-damage her mark
    # enables: the pre-mit per-event magic / its re-proc cadence (ally_detonation_
    # dps_raw), MR-mitigated (magic routing via _armor_factor), x mode_mult x
    # magic_amp, x the assumed ally proc rate. An unmarked champion contributes 0
    # even with the flag on. The live default-ON flip is operator-gated
    # (docs/LIVE_GAME_GATED_SYNC.md) - do not flip blind.
    ally_detonation_dps = 0.0
    if assume_ally_detonation:
        from ._ally_detonation_overrides import (
            _ASSUMED_ALLY_DETONATION_PROB,
            ally_detonation_dps_raw,
        )

        det_target_current_hp = target_max_hp * target_current_hp_pct
        det_raw = ally_detonation_dps_raw(
            resolved.champion_id, level, resolved.item_ids, det_target_current_hp
        )
        if det_raw > 0.0:
            ally_detonation_dps = (
                det_raw * _armor_factor(target_mr_eff) * mode_mult
                * magic_amp * _ASSUMED_ALLY_DETONATION_PROB
            )
            weighted_dps += ally_detonation_dps
            phase_dps = {p: v + ally_detonation_dps for p, v in phase_dps.items()}
            notes.append(
                f"ally-detonation +{ally_detonation_dps:.1f} DPS "
                f"({resolved.champion_name} mark consumed by allies at "
                f"{_ASSUMED_ALLY_DETONATION_PROB:.0%} assumed proc rate; "
                "assume_ally_detonation seam)"
            )

    return DpsResult(
        champion_id=resolved.champion_id,
        champion_name=resolved.champion_name,
        level=level,
        item_ids=resolved.item_ids,
        mode=mode,
        target_armor=target_armor,
        target_mr=target_mr,
        target_max_hp=target_max_hp,
        target_bonus_hp=target_bonus_hp,
        phase=selected_phase,
        weighted_dps=weighted_dps,
        phase_dps=phase_dps,
        avg_attack_dmg=avg_attack_dmg,
        raw_attack_dps=raw_attack_dps,
        mode_multiplier=mode_mult,
        per_attack_on_hit_damage=per_attack_on_hit_damage,
        spellblade_per_proc_damage=spellblade_per_proc,
        spellblade_item_name=spellblade_name,
        lightshield_strike_per_proc_damage=lightshield_strike_per_proc,
        lightshield_strike_item_name=lightshield_strike_name,
        stats=dict(stats),
        notes=tuple(notes),
    )


# Phase 6 step 7 (2026-05-10): per-level DPS curve helper. Coaches read this
# to hint power-spike levels - "Lulu peaks at lvl 6, falls off at 11" style.
# Default sample levels chosen for power-spike granularity: level 1 (lane
# start), 6 (ult unlock), 11 (mid-game spike), 16 (full kit), 18 (cap).
DPS_CURVE_LEVELS: tuple[int, ...] = (1, 6, 11, 16, 18)


@dataclass(frozen=True)
class DpsCurvePoint:
    """One sample on a champion's level-DPS curve.

    ``weighted_dps`` is the same number ``compute_dps()`` returns at that
    level; ``phase`` is the auto-selected rotation phase; ``stats`` is a
    compact subset of the resolved block (the four numbers a coach is
    most likely to surface). Full stat block is still available via the
    per-level ``compute_dps`` call if a caller needs it.
    """
    level: int
    weighted_dps: float
    phase: str
    stats: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "weighted_dps": self.weighted_dps,
            "phase": self.phase,
            "stats": dict(self.stats),
        }


def compute_dps_curve(
    snapshot: DataSnapshot,
    champion_id: str,
    item_ids: Optional[Iterable[str | int]] = None,
    mode: str = "SR",
    target_armor: float = 0.0,
    target_mr: float = 0.0,
    target_max_hp: float = 0.0,
    target_bonus_hp: float = 0.0,
    levels: Optional[Iterable[int]] = None,
    augments: Optional[Iterable] = None,
    apply_mode_modifiers: bool = False,
) -> list[DpsCurvePoint]:
    """Return a per-level DPS curve for ``champion_id`` with the given build.

    Calls :func:`compute_dps` at each level in ``levels`` (default
    :data:`DPS_CURVE_LEVELS` = 1/6/11/16/18) and returns the points in
    input order. All build parameters (items, mode, target resists,
    augments) are threaded through unchanged so the curve reflects the
    SAME build at each level - useful for "when does this build come
    online" coaching prompts.

    Levels outside ``[1, 18]`` raise via the underlying ``clamp_level``
    in ``compute_dps``. Duplicate levels in the input list are honored
    (no dedup) - caller can request a denser sample around a phase
    boundary by repeating a level.
    """
    target_levels = tuple(levels) if levels is not None else DPS_CURVE_LEVELS
    pts: list[DpsCurvePoint] = []
    for lv in target_levels:
        r = compute_dps(
            snapshot, champion_id, level=lv,
            item_ids=item_ids, mode=mode,
            target_armor=target_armor, target_mr=target_mr,
            target_max_hp=target_max_hp, target_bonus_hp=target_bonus_hp,
            augments=augments,
            apply_mode_modifiers=apply_mode_modifiers,
        )
        pts.append(DpsCurvePoint(
            level=lv,
            weighted_dps=r.weighted_dps,
            phase=r.phase,
            stats={
                "ad": r.stats.get("ad", 0.0),
                "ap": r.stats.get("ap", 0.0),
                "as": r.stats.get("as", 0.0),
                "crit": r.stats.get("crit", 0.0),
            },
        ))
    return pts
