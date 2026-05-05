"""Phase 2 step 2 + Phase 4 thin slice — auto-attack DPS with conditionals.

Reads ``snapshot.scenarios(champion_id)`` (early/mid/late phases × rotations
with weights, durations, basic-attack counts) and convolves with the
champion's resolved AD/AS/crit at the requested level + items. Mode hook
applies ``aram_modifiers.aramDamageDealt`` for ARAM. Target armor uses
the standard League formula.

Phase 4 thin slice (2026-05-03): ``effects.ITEM_EFFECTS`` layers
per-item conditionals on top of the stat math — Infinity Edge bumps the
crit-damage multiplier, Kraken Slayer adds an every-3rd-attack physical
proc, Stormrazor adds an every-4-second magic proc. Magical procs use
target MR (not armor); physical procs share the auto-attack armor curve.

Phase 4 batch 5 (2026-05-04): ``target_max_hp`` is plumbed into
``CallContext`` so %-target-HP procs (BotRK Mist's Edge, Eclipse Ever
Rising Moon) resolve. Same caller-supplied shape as ``target_armor`` /
``target_mr`` — defaults to 0.0, lolmath scenarios don't carry HP.

Phase 4 batch 6 (2026-05-04): caster HP layer. ``caster_max_hp`` and
``caster_bonus_hp`` are derived from the resolved build (``stats["hp"]``
and ``stats["hp"] - base_stats["hp"]`` respectively) and fed into
``CallContext``. Engine-internal — no caller param — since the engine
always knows the caster's exact HP. Unlocks Titanic Hydra Cleave
(1.5% bonus HP) and Heartsteel Colossal Consumption (6% max HP).

Phase 4 batch 7 (2026-05-04): multi-target rotations. Each rotation's
``numberOfTargets`` (lolmath field, 94% of rotations = 1.0) feeds into
``CallContext.targets_in_rotation`` per rotation via ``replace``.
Cleave-to-others procs (Ravenous Hydra) read ``max(0, n-1)`` from it;
single-target procs ignore the field. AoE-incl-primary procs (Sunfire
Immolate, when added) would use ``n`` directly.

Ability damage is **not** included — spell formulas aren't in the
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
    total_conditional_as,
    total_crit_chance_bonus,
    total_crit_damage_bonus,
    total_damage_amp_multiplier,
    total_giant_slayer_multiplier,
    total_magic_amp_multiplier,
    total_stacked_ap,
    total_target_bonus_hp_amp_multiplier,
)
from .engine import build_champion
from .stats import clamp_level

# Base bonus crit damage on auto-attacks. ``effects.ITEM_EFFECTS`` adds
# per-item bumps (e.g. Infinity Edge = +0.30) on top.
DEFAULT_CRIT_BONUS = 0.75

EARLY_LEVEL_MAX = 6
MID_LEVEL_MAX = 12

PHASES: tuple[str, ...] = ("early", "mid", "late")


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
            "stats": dict(self.stats),
            "notes": list(self.notes),
        }

    def format_table(self) -> str:
        head = (
            f"{self.champion_name} ({self.champion_id}) — lvl {self.level} "
            f"— mode {self.mode} — phase {self.phase}"
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
    """League's armor → physical damage multiplier (also applies to MR/magic).

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
    ``total_magic_amp_multiplier``) is applied only to magical procs —
    models target-debuff auras (Abyssal Mask Unmake) that increase magic
    damage taken without affecting physical auto-attack damage.
    """
    if duration <= 0:
        return 0.0
    total = 0.0
    for e in effects:
        for proc in e.periodics:
            if proc.every_n_attacks > 0:
                if total_attacks <= 0:
                    continue
                procs = total_attacks / proc.every_n_attacks
            else:  # every_n_seconds > 0 enforced by PeriodicProc.__post_init__
                procs = duration / proc.every_n_seconds
            is_physical = proc.damage_type == PHYSICAL
            is_true = proc.damage_type == TRUE
            resist = 0.0 if is_true else (target_armor_for_physical if is_physical else target_mr)
            type_amp = 1.0 if (is_physical or is_true) else magic_amp
            dmg = proc.resolve_damage(call_ctx)
            total += procs * dmg * _armor_factor(resist) * mode_dmg_mult * type_amp
    return total / duration


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
) -> float:
    """DPS contribution from basic attacks during a single rotation.

    ``total_attacks = basic + basicTime * AS``. Each attack lands ``AD``
    pre-resists, scaled by crit average and the mode damage multiplier,
    then divided by full rotation duration (which includes time spent
    casting abilities — auto DPS is naturally diluted in cast-heavy
    rotations). ``target_armor_for_physical`` already has reduction +
    pen applied at the caller. Conditional procs from items add on top
    via ``_periodic_proc_dps``.

    Phase 4 batch 14 (2026-05-04): ``damage_amp`` is the build's
    multiplicative damage-amp factor (Riftmaker Void Corruption,
    future Conqueror-style amps). Applied to both base AA and proc
    DPS — in-game amps don't discriminate damage type. Default 1.0
    keeps pre-batch behavior unchanged.

    Phase 4 batch 34 (2026-05-04): ``magic_amp`` applies only to magical
    proc DPS inside ``_periodic_proc_dps`` — does NOT touch base AA
    (physical). Default 1.0 keeps pre-batch behavior unchanged.
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
        magic_amp=magic_amp,
    )
    return (base_dps + proc_dps) * damage_amp


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
            magic_amp=magic_amp,
        )
        total_weight += w
    if total_weight <= 0:
        return 0.0
    return weighted_sum / total_weight


def _phase_rotations(snapshot: DataSnapshot, champion_id: str) -> dict[str, list[dict]]:
    """Pull the first scenario block's per-phase rotations.

    Champions in the snapshot all expose at least one scenario record (the
    extractor's coverage check pins this). We use index 0 by convention —
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
    phase: Optional[str] = None,
    augments: Optional[Iterable] = None,
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
    behaviorally identical (the amp resolves to ×1.0 with no signal).
    """
    level = clamp_level(level)
    selected_phase = phase or _select_phase(level)
    if selected_phase not in PHASES:
        raise ValueError(
            f"phase must be one of {PHASES}, got {selected_phase!r}"
        )

    resolved = build_champion(
        snapshot, champion_id, level, item_ids=item_ids, mode=mode,
        augments=augments,
    )
    stats = resolved.stats

    champ = snapshot.champion(resolved.champion_id)
    aram = ((champ.get("lolmath") or {}).get("aram_modifiers") or {})
    mode_mult = 1.0
    if mode == "ARAM":
        mode_mult = float(aram.get("aramDamageDealt", 1.0))

    item_effects = collect_effects(resolved.item_ids)
    crit_bonus = DEFAULT_CRIT_BONUS + total_crit_damage_bonus(item_effects)
    # Phase 4 batch 14 (2026-05-04): build-wide damage amp. 1.0 when no
    # items carry an amp, so pre-batch builds pass through unchanged.
    damage_amp = total_damage_amp_multiplier(item_effects)
    # Phase 4 batch 19 (2026-05-04): target-conditional amp (LDR Giant
    # Slayer). Stacks multiplicatively with damage_amp_pct items per
    # League's buff-system pin from batch 14. ×1.0 when caller leaves
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
    # base/bonus split for HP (Phase 4 batch 6, 2026-05-04) — Titanic
    # Hydra scales off bonus HP, Heartsteel scales off max HP, so we
    # surface both. Engine-derived (unlike target_max_hp): the engine
    # always knows the caster's exact HP from the build.
    base_ad = float(resolved.base_stats.get("ad", 0.0)) if resolved.base_stats else 0.0
    total_ad = float(stats.get("ad", 0.0))
    bonus_ad = max(0.0, total_ad - base_ad)
    ap = float(stats.get("ap", 0.0))
    base_hp = float(resolved.base_stats.get("hp", 0.0)) if resolved.base_stats else 0.0
    caster_max_hp = float(stats.get("hp", 0.0))
    caster_bonus_hp = max(0.0, caster_max_hp - base_hp)
    # Phase 4 batch 38 (2026-05-04): Giant Slayer target max HP advantage amp.
    # Stacks multiplicatively with damage_amp (same buffer-system doctrine as
    # target_amp from batch 19). Resolved here because caster_max_hp is needed.
    giant_slayer_amp = total_giant_slayer_multiplier(item_effects, target_max_hp, caster_max_hp)
    damage_amp *= giant_slayer_amp
    # Phase 4 batch 27 (2026-05-04): caster max mana — needed for Manamune /
    # Muramana's Awe (already folded into ad_flat by build_champion) and
    # Muramana's Shock proc (per-attack 1.2% max mana physical). Manaless
    # champions and pre-batch-27 builds carry stats["mp"]=0 → 0 contribution.
    caster_max_mp = float(stats.get("mp", 0.0))
    # Phase 4 batch 15 (2026-05-04): cross-derived AP from caster bonus
    # HP (Riftmaker's Void Infusion). Added to ap before CallContext
    # is built so AP-scaling procs (Lich Bane, Nashor's Tooth) see the
    # converted total. Stays out of resolved.stats — /stats reflects
    # raw stat blocks; /dps reflects converted totals.
    ap_from_hp = total_bonus_ap_from_hp(item_effects, caster_bonus_hp)
    ap += ap_from_hp
    # Phase 4 batch 54 (2026-05-04): stacked AP from kill-stack passives
    # (Mejai's Glory). Inserted BEFORE ap_amp so Rabadon's Magical Opus
    # amplifies the full AP total including stacked AP — Glory AP is real
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
    # Phase 4 batch 21 (2026-05-04): crit_chance plumbed into CallContext
    # for ER Spellblade (+0.5 bonus physical per 1% crit).
    # Phase 4 batch 26 (2026-05-04): item-effect-contributed crit
    # (Yun Tal Wildarrows flat 25% + Atma's Big Hands HP-scaled). Summed
    # into the build's stats.crit and clamped at 1.0; the boosted total
    # flows through both the rotation auto-attack crit calc (via
    # ``stats_for_rotation``) and CallContext.crit_chance (read by ER
    # Spellblade's lambda + future crit-scaling procs). /stats endpoint
    # output is unchanged — same separation as batch 15's HP→AP cross-
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
    # Added to stats_for_rotation["as"] alongside crit_from_effects — both
    # are DPS-time cross-derivations that don't appear in /stats. The AS
    # value is uptime-weighted (0.08 for Yun Tal at ~27% uptime).
    cond_as = total_conditional_as(item_effects)
    if cond_as > 0:
        if stats_for_rotation is stats:
            stats_for_rotation = dict(stats)
        stats_for_rotation["as"] = stats_for_rotation.get("as", 0.0) + cond_as
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
            magic_amp=magic_amp,
        )
        for p in PHASES
    }
    weighted_dps = phase_dps[selected_phase]

    crit = crit_total
    ad = float(stats.get("ad", 0.0))
    eff_as = float(stats.get("as", 0.0))
    # Phase 4 batch 14: per-hit display value reflects the same amp the
    # rotation DPS uses, so /dps clients see consistent numbers.
    avg_attack_dmg = ad * (1 + crit * crit_bonus) * _armor_factor(target_armor_eff) * mode_mult * damage_amp
    raw_attack_dps = ad * eff_as * (1 + crit * crit_bonus)

    notes = list(resolved.notes)
    if mode == "ARAM" and mode_mult != 1.0:
        notes.append(f"ARAM aramDamageDealt={mode_mult:.2f} on per-hit damage")
    if target_armor_eff != target_armor:
        notes.append(
            f"effective target armor {target_armor:.1f} → {target_armor_eff:.1f}"
            " after reduction + pen"
        )
    if target_mr_eff != target_mr:
        notes.append(
            f"effective target MR {target_mr:.1f} → {target_mr_eff:.1f}"
            " after magic pen"
        )
    if damage_amp != 1.0:
        notes.append(
            f"build damage amp ×{damage_amp:.4f} "
            f"(+{(damage_amp - 1.0) * 100:.2f}% to all damage)"
        )
    if target_amp != 1.0:
        notes.append(
            f"target-conditional amp ×{target_amp:.4f} "
            f"(target_bonus_hp={target_bonus_hp:.0f}, "
            f"+{(target_amp - 1.0) * 100:.2f}% folded into build amp)"
        )
    if giant_slayer_amp != 1.0:
        hp_diff = max(0.0, target_max_hp - caster_max_hp)
        notes.append(
            f"Giant Slayer HP-advantage amp ×{giant_slayer_amp:.4f} "
            f"(target {target_max_hp:.0f} - caster {caster_max_hp:.0f} = {hp_diff:.0f} HP diff → "
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
    if cond_as > 0:
        notes.append(
            f"conditional AS bonus: +{cond_as:.3f} (Yun Tal Flurry ~27% uptime)"
        )
    if ap_amp != 1.0:
        notes.append(
            f"AP amplified ×{ap_amp:.4f} by Rabadon's Deathcap "
            f"(effective AP for procs: {ap:.1f})"
        )
    if magic_amp != 1.0:
        notes.append(
            f"magic damage amp ×{magic_amp:.4f} (Abyssal Mask Unmake "
            f"+{(magic_amp - 1.0) * 100:.0f}% magic damage to target)"
        )
    if crit_from_effects > 0:
        # Phase 4 batch 26 (2026-05-04): surface item-effect-contributed
        # crit so /dps clients can see when crit was lifted off raw stats
        # alone (Yun Tal pin / Atma HP-scaled). When raw + bonus > 1.0
        # the effective value is clamped at 1.0 — surface both the raw
        # contribution and the post-clamp final to make the cap visible.
        notes.append(
            f"crit chance lifted by items: +{crit_from_effects * 100:.1f}% "
            f"(raw {raw_crit * 100:.1f}% + items → effective {crit_total * 100:.1f}%)"
        )
    for e in item_effects:
        if e.note:
            notes.append(e.note)
    if not any(rotations_by_phase.values()):
        notes.append("no scenarios in snapshot for this champion — DPS=0")
    elif not rotations_by_phase[selected_phase]:
        notes.append(f"no rotations defined for phase={selected_phase!r}")

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
        stats=dict(stats),
        notes=tuple(notes),
    )
