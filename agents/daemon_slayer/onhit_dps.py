"""Slice B (2026-07-16) - on-hit AP combined-DPS scorer.

Composes compute_ability_dps().total_ability_dps (Q/W/E/R) with
compute_dps().weighted_dps (autos + on-hit item procs, incl. Nashor's
Icathian Bite) into ONE combined-DPS score by PLAIN SUM - both halves are
in the same DPS units. The two are non-overlapping by design: the passive
(P) on-hit lives in compute_dps, the four active spells live in
compute_ability_dps. Neither half alone surfaces Nashor's; their sum is the
champion's true total sustained DPS. Sibling of hybrid.py (which composes
dps + EHP with alpha/beta) - here no weights are needed.

ASCII only - use " - " for a clause break (repo hard rule).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

from .ability_dps import compute_ability_dps
from .data_loader import DataSnapshot
from .dps import compute_dps
from .stats import clamp_level


@dataclass(frozen=True)
class OnhitDpsResult:
    champion_id: str
    champion_name: str
    level: int
    item_ids: tuple[str, ...]
    mode: str
    ability_dps: float          # compute_ability_dps().total_ability_dps
    auto_dps: float             # compute_dps().weighted_dps (incl. on-hit procs)
    onhit_dps: float            # ability_dps + auto_dps (plain sum, same units)
    phase: str
    target_armor: float
    target_mr: float
    target_max_hp: float
    target_bonus_hp: float
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "champion_id": self.champion_id,
            "champion_name": self.champion_name,
            "level": self.level,
            "item_ids": list(self.item_ids),
            "mode": self.mode,
            "ability_dps": self.ability_dps,
            "auto_dps": self.auto_dps,
            "onhit_dps": self.onhit_dps,
            "phase": self.phase,
            "target_armor": self.target_armor,
            "target_mr": self.target_mr,
            "target_max_hp": self.target_max_hp,
            "target_bonus_hp": self.target_bonus_hp,
            "notes": list(self.notes),
        }

    def format_table(self) -> str:
        head = (
            f"{self.champion_name} ({self.champion_id}) - lvl {self.level} "
            f"- mode {self.mode}  [ON-HIT AP]"
        )
        rows = [head, "-" * len(head)]
        rows.append(f"items: {', '.join(self.item_ids) if self.item_ids else '(none)'}")
        rows.append(
            f"  ability_dps  {self.ability_dps:.2f}\n"
            f"  auto_dps     {self.auto_dps:.2f}\n"
            f"  onhit_dps    {self.onhit_dps:.2f}  (sum)"
        )
        for n in self.notes:
            rows.append(f"  note: {n}")
        return "\n".join(rows)


def compute_onhit_dps(
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
    apply_mode_modifiers: bool = False,
) -> OnhitDpsResult:
    """Combined ability + on-hit-auto DPS for the resolved build (plain sum).

    ``compute_ability_dps`` has no ``phase`` or ``apply_mode_modifiers``
    parameter (it is spell-keyed, not rotation-phase-keyed, and has no ARAM
    dmg_dealt hook of its own) - those two kwargs are forwarded ONLY to
    ``compute_dps``. Both composed calls share the same snapshot / champion /
    level / item_ids / mode / target_* / augments so the two halves describe
    the identical resolved build.
    """
    level = clamp_level(level)
    item_list = tuple(str(i) for i in (item_ids or ()))

    auto = compute_dps(
        snapshot, champion_id=champion_id, level=level, item_ids=item_list,
        mode=mode, target_armor=target_armor, target_mr=target_mr,
        target_max_hp=target_max_hp, target_bonus_hp=target_bonus_hp,
        phase=phase, augments=augments, apply_mode_modifiers=apply_mode_modifiers,
    )
    ability = compute_ability_dps(
        snapshot, champion_id=champion_id, level=level, item_ids=item_list,
        mode=mode, target_armor=target_armor, target_mr=target_mr,
        target_max_hp=target_max_hp, target_bonus_hp=target_bonus_hp,
        augments=augments,
    )
    ability_dps = float(ability.total_ability_dps)
    auto_dps = float(auto.weighted_dps)
    return OnhitDpsResult(
        champion_id=auto.champion_id,
        champion_name=auto.champion_name,
        level=level,
        item_ids=item_list,
        mode=mode,
        ability_dps=ability_dps,
        auto_dps=auto_dps,
        onhit_dps=ability_dps + auto_dps,
        phase=auto.phase,
        target_armor=target_armor,
        target_mr=target_mr,
        target_max_hp=target_max_hp,
        target_bonus_hp=target_bonus_hp,
        notes=(f"onhit_dps = ability {ability_dps:.1f} + auto {auto_dps:.1f}",),
    )
