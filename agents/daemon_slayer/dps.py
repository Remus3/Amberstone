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

Ability damage is **not** included — spell formulas aren't in the
snapshot. Only the basic-attack portion of each rotation is scored;
rotation duration includes the time spent casting abilities, so longer
rotations naturally dilute auto-attack DPS.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

from .data_loader import DataSnapshot
from .effects import (
    ItemEffect,
    PHYSICAL,
    collect_effects,
    total_crit_damage_bonus,
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
    target_armor: float,
    target_mr: float,
    mode_dmg_mult: float,
) -> float:
    """Sum DPS contribution from every conditional proc in the build.

    Each proc fires on either an attack count (``every_n_attacks``) or
    a time interval (``every_n_seconds``). Physical procs use the
    target's armor; magical procs use MR. Mode damage multiplier
    applies (ARAM ``aramDamageDealt`` reduces proc damage too).
    Rotation duration divides the per-rotation proc total so the
    contribution is in DPS units.
    """
    if duration <= 0:
        return 0.0
    total = 0.0
    for e in effects:
        proc = e.periodic
        if proc is None:
            continue
        if proc.every_n_attacks > 0:
            if total_attacks <= 0:
                continue
            procs = total_attacks / proc.every_n_attacks
        else:  # every_n_seconds > 0 enforced by PeriodicProc.__post_init__
            procs = duration / proc.every_n_seconds
        resist = target_armor if proc.damage_type == PHYSICAL else target_mr
        total += procs * proc.bonus_damage * _armor_factor(resist) * mode_dmg_mult
    return total / duration


def _rotation_attack_dps(
    stats: dict[str, float],
    rotation: dict,
    target_armor: float,
    target_mr: float,
    mode_dmg_mult: float,
    crit_bonus: float,
    effects: list[ItemEffect],
) -> float:
    """DPS contribution from basic attacks during a single rotation.

    ``total_attacks = basic + basicTime * AS``. Each attack lands ``AD``
    pre-resists, scaled by crit average and the mode damage multiplier,
    then divided by full rotation duration (which includes time spent
    casting abilities — auto DPS is naturally diluted in cast-heavy
    rotations). Conditional procs from items add on top via
    ``_periodic_proc_dps``.
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
    avg_dmg = ad * (1 + crit * crit_bonus) * _armor_factor(target_armor) * mode_dmg_mult
    base_dps = total_attacks * avg_dmg / duration
    proc_dps = _periodic_proc_dps(
        effects, total_attacks, duration, target_armor, target_mr, mode_dmg_mult,
    )
    return base_dps + proc_dps


def _phase_weighted_dps(
    stats: dict[str, float],
    rotations: list[dict],
    target_armor: float,
    target_mr: float,
    mode_dmg_mult: float,
    crit_bonus: float,
    effects: list[ItemEffect],
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
            stats, r, target_armor, target_mr, mode_dmg_mult, crit_bonus, effects,
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
    phase: Optional[str] = None,
) -> DpsResult:
    """Resolve auto-attack DPS for ``champion_id`` at ``level`` with items.

    ``mode='ARAM'`` applies ``aramAttackSpeed`` to bonus AS (in
    ``build_champion``) and ``aramDamageDealt`` to per-hit damage (here).
    ``phase`` overrides level-based selection; valid values:
    ``"early"|"mid"|"late"``.
    """
    level = clamp_level(level)
    selected_phase = phase or _select_phase(level)
    if selected_phase not in PHASES:
        raise ValueError(
            f"phase must be one of {PHASES}, got {selected_phase!r}"
        )

    resolved = build_champion(
        snapshot, champion_id, level, item_ids=item_ids, mode=mode,
    )
    stats = resolved.stats

    champ = snapshot.champion(resolved.champion_id)
    aram = ((champ.get("lolmath") or {}).get("aram_modifiers") or {})
    mode_mult = 1.0
    if mode == "ARAM":
        mode_mult = float(aram.get("aramDamageDealt", 1.0))

    item_effects = collect_effects(resolved.item_ids)
    crit_bonus = DEFAULT_CRIT_BONUS + total_crit_damage_bonus(item_effects)

    rotations_by_phase = _phase_rotations(snapshot, resolved.champion_id)
    phase_dps = {
        p: _phase_weighted_dps(
            stats, rotations_by_phase[p], target_armor, target_mr,
            mode_mult, crit_bonus, item_effects,
        )
        for p in PHASES
    }
    weighted_dps = phase_dps[selected_phase]

    crit = min(float(stats.get("crit", 0.0)), 1.0)
    ad = float(stats.get("ad", 0.0))
    eff_as = float(stats.get("as", 0.0))
    avg_attack_dmg = ad * (1 + crit * crit_bonus) * _armor_factor(target_armor) * mode_mult
    raw_attack_dps = ad * eff_as * (1 + crit * crit_bonus)

    notes = list(resolved.notes)
    if mode == "ARAM" and mode_mult != 1.0:
        notes.append(f"ARAM aramDamageDealt={mode_mult:.2f} on per-hit damage")
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
        phase=selected_phase,
        weighted_dps=weighted_dps,
        phase_dps=phase_dps,
        avg_attack_dmg=avg_attack_dmg,
        raw_attack_dps=raw_attack_dps,
        mode_multiplier=mode_mult,
        stats=dict(stats),
        notes=tuple(notes),
    )
