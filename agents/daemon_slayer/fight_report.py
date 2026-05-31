"""Unified V2 fight-report: compose the 5 substrate modules into one report.

DS V2 plan section 3 (S2 deliverable): V1 stays the fast steady-state ranking
path; V2 is the bounded combat-simulator / correctness path. This module is the
COMPOSE layer - it does NOT rewrite any scorer. It calls the 5 additive V2
substrate modules and stitches their results into a single ``FightReport``:

  * mana_sim.compute_mana_bounded_combo  -> finite-mana bounded rotation
  * rune_procs.compute_rune_proc_damage  -> keystone/proc rune damage layer
  * ability_hps.compute_ability_hps      -> active+passive heal/shield throughput
  * self_shred.compute_self_shred_uplift -> target-shred own-DPS uplift
  * scenario_matrix.sweep_scenarios       -> cross-interaction sweep + invariants

Fail-soft: ``compute_fight_report`` NEVER raises. Each section runs in its own
try/except; on failure that section is zeroed and a note is appended, the rest
of the report continues. ASCII only (no em/en dash, no smart quotes).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

from .ability_dps import AbilityContext, compute_ability_dps
from .ability_hps import compute_ability_hps
from .data_loader import DataSnapshot
from .dps import compute_dps
from .engine import build_champion
from .mana_sim import compute_mana_bounded_combo
from .rune_procs import RUNE_PROCS, compute_rune_proc_damage, keystone_amp
from .scenario_matrix import check_invariants, sweep_scenarios
from .self_shred import compute_self_shred_uplift

# Default rotation when the caller does not supply one. Matches the spirit of
# the burst/combo default (Q-W-E-AA-R) but interleaves an AA after R so the
# auto-attack channel is exercised both early and late.
_DEFAULT_SEQUENCE: Tuple[str, ...] = ("Q", "W", "E", "AA", "R", "AA")

# Rune proc_types that contribute a per-proc DAMAGE figure to the burst total.
# "adaptive" (Conqueror) returns a per-stack stat value, not damage, so it is
# excluded from the burst sum (it carries a 0.0 amp_mult and a stat meaning).
_BURST_PROC_TYPES = frozenset({"on_proc_burst", "per_attack", "stacking_amp"})


@dataclass(frozen=True)
class FightReport:
    """Composed V2 fight report stitching the 5 substrate modules.

    Every numeric section is fail-soft: a section that raised is zeroed and the
    reason is recorded in ``notes``. ``invariant_violations`` is empty for a
    well-behaved build (physical DPS non-increasing in armor, etc.).
    """

    champion: str
    champion_name: str
    level: int
    mode: str
    item_ids: Tuple[str, ...]
    runes: Tuple[int, ...]
    sequence: Tuple[str, ...]
    target_armor: float
    target_mr: float
    target_max_hp: float
    target_bonus_hp: float

    # mana_sim section
    resource_type: str = ""
    mana_pool: float = 0.0
    mana_regen_per_s: float = 0.0
    casts_allowed: int = 0
    casts_requested: int = 0
    oom_at_t: Optional[float] = None
    bounded_dps: float = 0.0
    unbounded_dps: float = 0.0

    # rune_procs section
    rune_entries: Tuple[dict, ...] = field(default_factory=tuple)
    rune_burst_total: float = 0.0
    keystone_amp_mult: float = 1.0

    # ability_hps section
    ability_heal_hps: float = 0.0
    ability_shield_hps: float = 0.0
    ability_hps_total: float = 0.0

    # self_shred section
    shred_ability: str = ""
    shred_uplift_pct: float = 0.0
    shred_dps_gain: float = 0.0

    # scenario_matrix section
    scenario_cells: int = 0
    invariant_violations: Tuple[dict, ...] = field(default_factory=tuple)

    notes: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "champion": self.champion,
            "champion_name": self.champion_name,
            "level": self.level,
            "mode": self.mode,
            "item_ids": list(self.item_ids),
            "runes": list(self.runes),
            "sequence": list(self.sequence),
            "target_armor": self.target_armor,
            "target_mr": self.target_mr,
            "target_max_hp": self.target_max_hp,
            "target_bonus_hp": self.target_bonus_hp,
            "resource_type": self.resource_type,
            "mana_pool": self.mana_pool,
            "mana_regen_per_s": self.mana_regen_per_s,
            "casts_allowed": self.casts_allowed,
            "casts_requested": self.casts_requested,
            "oom_at_t": self.oom_at_t,
            "bounded_dps": self.bounded_dps,
            "unbounded_dps": self.unbounded_dps,
            "rune_entries": [dict(e) for e in self.rune_entries],
            "rune_burst_total": self.rune_burst_total,
            "keystone_amp_mult": self.keystone_amp_mult,
            "ability_heal_hps": self.ability_heal_hps,
            "ability_shield_hps": self.ability_shield_hps,
            "ability_hps_total": self.ability_hps_total,
            "shred_ability": self.shred_ability,
            "shred_uplift_pct": self.shred_uplift_pct,
            "shred_dps_gain": self.shred_dps_gain,
            "scenario_cells": self.scenario_cells,
            "invariant_violations": [
                {"invariant": v["invariant"], "detail": v["detail"]}
                for v in self.invariant_violations
            ],
            "notes": list(self.notes),
        }


def _short(exc: Exception) -> str:
    """One-line, length-capped exception summary for a section note."""
    return f"{type(exc).__name__}: {str(exc)[:120]}"


def compute_fight_report(
    champion: str,
    level: int = 1,
    item_ids: Optional[Sequence[str | int]] = None,
    sequence: Optional[Sequence[str]] = None,
    runes: Optional[Sequence[int | str]] = None,
    target_armor: float = 0.0,
    target_mr: float = 0.0,
    target_max_hp: float = 0.0,
    target_bonus_hp: float = 0.0,
    mode: str = "SR",
    snapshot: Optional[DataSnapshot] = None,
    caster_hp_pct: float = 1.0,
    game_time_s: float = 0.0,
) -> FightReport:
    """Compose a unified V2 fight report for ``champion``.

    Calls each of the 5 substrate modules in its own try/except. NEVER raises -
    a section that fails is zeroed and a note is appended. ``snapshot`` is a
    DataSnapshot (loaded when None). ``runes`` is an iterable of Riot perk ids
    (int or str). ``sequence`` defaults to ``_DEFAULT_SEQUENCE`` when None.
    """
    snap = snapshot if snapshot is not None else DataSnapshot.load()
    items: List[str] = [str(i) for i in (item_ids or [])]
    runes_list: List[int] = []
    for r in (runes or []):
        try:
            runes_list.append(int(r))
        except (TypeError, ValueError):
            continue
    seq: Tuple[str, ...] = (
        tuple(str(s) for s in sequence) if sequence else _DEFAULT_SEQUENCE
    )
    try:
        lvl = int(level)
    except (TypeError, ValueError):
        lvl = 1
    if lvl < 1:
        lvl = 1

    champ = str(champion or "").strip()
    notes: List[str] = []

    champion_name = champ
    # ----- MANA section -------------------------------------------------
    resource_type = ""
    mana_pool = 0.0
    mana_regen_per_s = 0.0
    casts_allowed = 0
    casts_requested = 0
    oom_at_t: Optional[float] = None
    bounded_dps = 0.0
    unbounded_dps = 0.0
    try:
        mr = compute_mana_bounded_combo(
            champ, lvl, item_ids=items, sequence=list(seq),
            target_armor=target_armor, target_mr=target_mr,
            target_max_hp=target_max_hp, target_bonus_hp=target_bonus_hp,
            mode=mode, snapshot=snap,
        )
        resource_type = mr.resource_type
        mana_pool = mr.mana_pool
        mana_regen_per_s = mr.mana_regen_per_s
        casts_allowed = mr.casts_allowed
        casts_requested = mr.casts_requested
        oom_at_t = mr.oom_at_t
        bounded_dps = mr.bounded_dps
        unbounded_dps = mr.unbounded_dps
        if mr.champion_name:
            champion_name = mr.champion_name
        for n in (mr.notes or ()):
            notes.append(f"mana: {n}")
    except Exception as exc:  # fail-soft
        notes.append(f"mana section failed: {_short(exc)}")

    # ----- ABILITY-HPS section -----------------------------------------
    ability_heal_hps = 0.0
    ability_shield_hps = 0.0
    ability_hps_total = 0.0
    try:
        hps = compute_ability_hps(snap, champ, lvl, items, mode)
        ability_heal_hps = hps.total_heal_per_sec
        ability_shield_hps = hps.total_shield_per_sec
        ability_hps_total = hps.total_ability_hps
        if champion_name == champ and hps.champion_name:
            champion_name = hps.champion_name
    except Exception as exc:  # fail-soft
        notes.append(f"ability_hps section failed: {_short(exc)}")

    # ----- SELF-SHRED section ------------------------------------------
    shred_ability = ""
    shred_uplift_pct = 0.0
    shred_dps_gain = 0.0
    phys_dps = 0.0
    magic_dps = 0.0
    try:
        phys_dps = compute_dps(
            snap, champ, lvl, item_ids=items, mode=mode,
            target_armor=target_armor, target_mr=target_mr,
            target_max_hp=target_max_hp, target_bonus_hp=target_bonus_hp,
        ).weighted_dps
    except Exception:
        phys_dps = 0.0
    try:
        magic_dps = compute_ability_dps(
            snap, champion_id=champ, level=lvl, item_ids=items, mode=mode,
            target_armor=target_armor, target_mr=target_mr,
            target_max_hp=target_max_hp, target_bonus_hp=target_bonus_hp,
        ).dps
    except Exception:
        magic_dps = 0.0
    try:
        shred = compute_self_shred_uplift(
            champ, lvl, target_armor, target_mr,
            champion_physical_dps=phys_dps, champion_magic_dps=magic_dps,
            snapshot=None,
        )
        shred_ability = shred.shred_source
        shred_uplift_pct = shred.dps_uplift_pct
        shred_dps_gain = shred.dps_uplift_abs
    except Exception as exc:  # fail-soft
        notes.append(f"self_shred section failed: {_short(exc)}")

    # ----- RUNE section -------------------------------------------------
    rune_entries: List[dict] = []
    rune_burst_total = 0.0
    keystone_amp_mult = 1.0
    try:
        resolved = build_champion(snap, champ, lvl, item_ids=items, mode=mode)
        if resolved.champion_name and champion_name == champ:
            champion_name = resolved.champion_name
        ctx = AbilityContext.from_build(
            stats=resolved.stats,
            base_stats=resolved.base_stats,
            target_armor=target_armor,
            target_mr=target_mr,
            target_max_hp=target_max_hp,
            target_bonus_hp=target_bonus_hp,
        )
        for rid in runes_list:
            proc = RUNE_PROCS.get(rid)
            val = compute_rune_proc_damage(
                rid, lvl, ad=ctx.bonus_ad, ap=ctx.ap,
                bonus_hp=ctx.caster_bonus_hp, target_max_hp=target_max_hp,
                mode=mode, caster_max_hp=ctx.caster_max_hp,
                caster_hp_pct=caster_hp_pct, game_time_s=game_time_s,
            )
            # item 232 - gated stacking-amp runes (Last Stand 8299) report the
            # CONTEXT-GATED amp via keystone_amp, not the static amp_mult field
            # (which is 1.0 for gated runes). For unconditional amps (PtA/Coup/
            # Cut/First Strike) keystone_amp(rid, 1.0, default ctx) == amp_mult,
            # so this is byte-identical at the full-HP / time-0 default.
            eff_amp = (
                keystone_amp(
                    rid, 1.0,
                    caster_hp_pct=caster_hp_pct, game_time_s=game_time_s,
                )
                if proc is not None and proc.proc_type == "stacking_amp"
                else (proc.amp_mult if proc else 1.0)
            )
            entry = {
                "rune_id": rid,
                "name": proc.name if proc else "unknown",
                "tree": proc.tree if proc else "",
                "proc_type": proc.proc_type if proc else "",
                "value": val,
                "amp_mult": eff_amp,
            }
            rune_entries.append(entry)
            if entry["proc_type"] in _BURST_PROC_TYPES:
                rune_burst_total += val
            if entry["proc_type"] == "stacking_amp":
                keystone_amp_mult *= float(entry["amp_mult"])
    except Exception as exc:  # fail-soft
        notes.append(f"rune section failed: {_short(exc)}")
        rune_entries = []
        rune_burst_total = 0.0
        keystone_amp_mult = 1.0

    # ----- SCENARIO section --------------------------------------------
    scenario_cells = 0
    invariant_violations: List[dict] = []
    try:
        sweep_levels = [max(1, lvl - 3), lvl]
        item_sets = [items]
        target_profiles = [
            (0.0, target_mr, target_max_hp, target_bonus_hp),
            (100.0, target_mr, target_max_hp, target_bonus_hp),
            (200.0, target_mr, target_max_hp, target_bonus_hp),
        ]
        cells = sweep_scenarios(
            champ, sweep_levels, item_sets, target_profiles,
            modes=(mode,), metric="dps", snapshot=snap,
        )
        scenario_cells = len(cells)
        violations = check_invariants(cells)
        invariant_violations = [
            {"invariant": v.invariant, "detail": v.detail} for v in violations
        ]
    except Exception as exc:  # fail-soft
        notes.append(f"scenario section failed: {_short(exc)}")
        scenario_cells = 0
        invariant_violations = []

    return FightReport(
        champion=champ,
        champion_name=champion_name,
        level=lvl,
        mode=mode,
        item_ids=tuple(items),
        runes=tuple(runes_list),
        sequence=seq,
        target_armor=float(target_armor),
        target_mr=float(target_mr),
        target_max_hp=float(target_max_hp),
        target_bonus_hp=float(target_bonus_hp),
        resource_type=resource_type,
        mana_pool=mana_pool,
        mana_regen_per_s=mana_regen_per_s,
        casts_allowed=casts_allowed,
        casts_requested=casts_requested,
        oom_at_t=oom_at_t,
        bounded_dps=bounded_dps,
        unbounded_dps=unbounded_dps,
        rune_entries=tuple(rune_entries),
        rune_burst_total=rune_burst_total,
        keystone_amp_mult=keystone_amp_mult,
        ability_heal_hps=ability_heal_hps,
        ability_shield_hps=ability_shield_hps,
        ability_hps_total=ability_hps_total,
        shred_ability=shred_ability,
        shred_uplift_pct=shred_uplift_pct,
        shred_dps_gain=shred_dps_gain,
        scenario_cells=scenario_cells,
        invariant_violations=tuple(invariant_violations),
        notes=tuple(notes),
    )


__all__ = ["FightReport", "compute_fight_report"]
