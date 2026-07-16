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
from .effects import ITEM_EFFECTS
from .rank import (
    DEFAULT_SLOT_COUNT,
    DEFAULT_TOP_N,
    SORT_KEYS,
    _champion_is_melee,
    _filter_candidates,
    _is_terminal,
    strip_arena_trinkets,
)
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


# --------------------------------------------------------------- ranker


@dataclass(frozen=True)
class OnhitDpsRankedItem:
    """One row of the on-hit AP ranker output - sibling of ``RankedItem``
    (dps.py), ``AbilityDpsRankedItem`` (mage), and ``HybridRankedItem``
    (bruiser).

    ``delta_dps`` / ``new_dps`` describe the COMBINED ``onhit_dps`` (plain
    sum of ability + auto), matching ``OnhitDpsResult.onhit_dps``.
    ``ability_dps`` / ``auto_dps`` are the two halves of ``new_dps`` for
    this candidate build, so ``new_dps == ability_dps + auto_dps`` holds
    per row (the composed-scorer invariant the caller relies on).
    """
    item_id: str
    item_name: str
    gold: int
    delta_dps: float           # onhit_dps gain over baseline (ability+auto sum)
    new_dps: float              # onhit_dps with item == ability_dps + auto_dps
    ability_dps: float          # compute_ability_dps().total_ability_dps half
    auto_dps: float             # compute_dps().weighted_dps half (incl. on-hit procs)
    dps_per_1k_gold: float      # delta_dps / (gold/1000); 0 when delta<=0
    is_terminal: bool           # `into` is empty - final-tier item
    tags: tuple[str, ...]
    # Mirrors the dead-unique dedup flag on RankedItem / AbilityDpsRankedItem /
    # HybridRankedItem - candidate's unique passive collides with one already
    # in current_item_ids.
    shares_dead_unique: bool = False
    dead_unique_key: str = ""
    # Candidate's own unique-passive family key, always set
    # (collision-independent) - the positive "locks <family>" signal.
    unique_passive_key: str = ""

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "item_name": self.item_name,
            "gold": self.gold,
            "delta_dps": self.delta_dps,
            "new_dps": self.new_dps,
            "ability_dps": self.ability_dps,
            "auto_dps": self.auto_dps,
            "dps_per_1k_gold": self.dps_per_1k_gold,
            "is_terminal": self.is_terminal,
            "tags": list(self.tags),
            "shares_dead_unique": self.shares_dead_unique,
            "dead_unique_key": self.dead_unique_key,
            "unique_passive_key": self.unique_passive_key,
        }


@dataclass(frozen=True)
class OnhitDpsRankResult:
    champion_id: str
    champion_name: str
    level: int
    mode: str
    current_item_ids: tuple[str, ...]
    baseline_ability_dps: float
    baseline_auto_dps: float
    baseline_onhit_dps: float
    target_armor: float
    target_mr: float
    target_max_hp: float
    target_bonus_hp: float
    phase: str
    budget: Optional[int]
    slot_count: int
    sort_by: str
    candidates_considered: int      # snapshot.items total
    candidates_evaluated: int       # passed filter
    ranked: tuple[OnhitDpsRankedItem, ...]
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "champion_id": self.champion_id,
            "champion_name": self.champion_name,
            "level": self.level,
            "mode": self.mode,
            "current_item_ids": list(self.current_item_ids),
            "baseline_ability_dps": self.baseline_ability_dps,
            "baseline_auto_dps": self.baseline_auto_dps,
            "baseline_onhit_dps": self.baseline_onhit_dps,
            "target_armor": self.target_armor,
            "target_mr": self.target_mr,
            "target_max_hp": self.target_max_hp,
            "target_bonus_hp": self.target_bonus_hp,
            "phase": self.phase,
            "budget": self.budget,
            "slot_count": self.slot_count,
            "sort_by": self.sort_by,
            "candidates_considered": self.candidates_considered,
            "candidates_evaluated": self.candidates_evaluated,
            "ranked": [r.to_dict() for r in self.ranked],
            "notes": list(self.notes),
        }

    def format_table(self) -> str:
        head = (
            f"{self.champion_name} ({self.champion_id}) - lvl {self.level} "
            f"- mode {self.mode} - phase {self.phase}  [ON-HIT AP]"
        )
        rows = [head, "-" * len(head)]
        if self.current_item_ids:
            rows.append(f"current items: {', '.join(self.current_item_ids)}")
        else:
            rows.append("current items: (none)")
        rows.append(
            f"target: armor={self.target_armor:.0f}  mr={self.target_mr:.0f}"
            f"  max_hp={self.target_max_hp:.0f}  bonus_hp={self.target_bonus_hp:.0f}"
        )
        budget_label = "unlimited" if self.budget is None else f"{self.budget}"
        rows.append(
            f"budget: {budget_label}  slots: {len(self.current_item_ids)}/{self.slot_count}"
            f"  sort: {self.sort_by}"
        )
        rows.append(
            f"baseline_onhit_dps: {self.baseline_onhit_dps:.2f}  "
            f"(ability {self.baseline_ability_dps:.2f} + auto {self.baseline_auto_dps:.2f})   "
            f"considered/evaluated: {self.candidates_considered}/{self.candidates_evaluated}"
        )
        rows.append("")
        rows.append(
            f"  {'#':>3}  {'id':>6}  {'name':<28}  "
            f"{'gold':>5}  {'+dps':>7}  {'new':>7}  {'dps/1k':>7}"
        )
        rows.append("  " + "-" * 78)
        for i, r in enumerate(self.ranked, 1):
            rows.append(
                f"  {i:>3}  {r.item_id:>6}  {r.item_name[:28]:<28}  "
                f"{r.gold:>5}  {r.delta_dps:>7.2f}  {r.new_dps:>7.2f}  {r.dps_per_1k_gold:>7.2f}"
            )
        if self.notes:
            rows.append("")
            for n in self.notes:
                rows.append(f"  note: {n}")
        return "\n".join(rows)


def rank_items_by_onhit(
    snapshot: DataSnapshot,
    champion_id: str,
    level: int,
    current_item_ids: Optional[Iterable[str | int]] = None,
    mode: str = "SR",
    target_armor: float = 0.0,
    target_mr: float = 0.0,
    target_max_hp: float = 0.0,
    target_bonus_hp: float = 0.0,
    phase: Optional[str] = None,
    budget: Optional[int] = None,
    slot_count: int = DEFAULT_SLOT_COUNT,
    top_n: int = DEFAULT_TOP_N,
    include_components: bool = False,
    only_item_ids: Optional[Iterable[str | int]] = None,
    sort_by: str = "delta",
    augments: Optional[Iterable] = None,
    apply_mode_modifiers: bool = False,
    filter_shared_uniques: bool = True,
) -> OnhitDpsRankResult:
    """Rank items by combined on-hit AP DPS gain (``compute_onhit_dps``).

    Sibling of ``rank_items`` (DPS), ``rank_items_by_ehp`` (EHP), and
    ``rank_items_by_ability_dps`` (mage) - same candidate-filtering pipeline
    (already-equipped skip + non-coachable/masterwork/ranged-only denies +
    optional whitelist + purchasable + mode-legal + terminal-only + budget +
    dead-unique dedup). Only the scoring function changes: each candidate is
    scored by ``compute_onhit_dps(build).onhit_dps`` (ability + auto, plain
    sum - both halves are in the same DPS units, so no alpha/beta weighting
    is needed, unlike the bruiser hybrid scorer) compared to the baseline.

    Sort keys:
      * ``delta``       - absolute onhit-DPS gain (default)
      * ``efficiency``  - onhit-DPS gain per 1000 gold

    ``filter_shared_uniques=True`` (default) drops candidates whose
    ``unique_passive_key`` matches a unique already in ``current_item_ids`` -
    matches the other scorers' behavior so this ranker stays consistent with
    the rest of the engine.
    """
    if sort_by not in SORT_KEYS:
        raise ValueError(f"sort_by must be one of {SORT_KEYS}, got {sort_by!r}")
    level = clamp_level(level)

    current_ids: tuple[str, ...] = tuple(str(i) for i in (current_item_ids or ()))
    current_ids, stripped_trinkets = strip_arena_trinkets(current_ids, mode)
    current_set = set(current_ids)
    current_unique_keys: set[str] = set()
    for iid in current_ids:
        eff = ITEM_EFFECTS.get(iid)
        if eff is not None and eff.unique_passive_key:
            current_unique_keys.add(eff.unique_passive_key)

    if len(current_ids) >= slot_count:
        raise ValueError(
            f"current_item_ids has {len(current_ids)} items; slot_count={slot_count} "
            f"leaves no room for a new item"
        )

    only_ids: Optional[set[str]] = None
    if only_item_ids is not None:
        only_ids = {str(i) for i in only_item_ids}

    baseline = compute_onhit_dps(
        snapshot,
        champion_id=champion_id, level=level,
        item_ids=current_ids, mode=mode,
        target_armor=target_armor, target_mr=target_mr,
        target_max_hp=target_max_hp, target_bonus_hp=target_bonus_hp,
        phase=phase, augments=augments,
        apply_mode_modifiers=apply_mode_modifiers,
    )

    champ_rec = snapshot.champions.get(str(champion_id))
    candidates = _filter_candidates(
        snapshot,
        mode=mode,
        current_ids=current_set,
        budget=budget,
        include_components=include_components,
        only_ids=only_ids,
        # Ranged-only purchasability gate: drop Runaan's (+ alias) for a melee
        # on-hit AP champion (e.g. Gwen) - the shop blocks the purchase
        # (2026-07-02).
        champion_is_melee=_champion_is_melee(champ_rec, augments),
    )

    ranked: list[OnhitDpsRankedItem] = []
    for item_id, rec in candidates:
        cand_eff = ITEM_EFFECTS.get(item_id)
        cand_key = cand_eff.unique_passive_key if cand_eff is not None else ""
        shares_dead_unique = bool(cand_key and cand_key in current_unique_keys)
        if shares_dead_unique and filter_shared_uniques:
            continue
        new_build = current_ids + (item_id,)
        try:
            scored = compute_onhit_dps(
                snapshot,
                champion_id=champion_id, level=level,
                item_ids=new_build, mode=mode,
                target_armor=target_armor, target_mr=target_mr,
                target_max_hp=target_max_hp, target_bonus_hp=target_bonus_hp,
                phase=phase, augments=augments,
                apply_mode_modifiers=apply_mode_modifiers,
            )
        except (KeyError, ValueError):
            continue
        gold = int((rec.get("gold") or {}).get("total", 0) or 0)
        delta = scored.onhit_dps - baseline.onhit_dps
        eff = (delta / (gold / 1000.0)) if (gold > 0 and delta > 0) else 0.0
        ranked.append(OnhitDpsRankedItem(
            item_id=item_id,
            item_name=str(rec.get("name", item_id)),
            gold=gold,
            delta_dps=delta,
            new_dps=scored.onhit_dps,
            ability_dps=scored.ability_dps,
            auto_dps=scored.auto_dps,
            dps_per_1k_gold=eff,
            is_terminal=_is_terminal(rec),
            tags=tuple(rec.get("tags") or ()),
            shares_dead_unique=shares_dead_unique,
            dead_unique_key=cand_key if shares_dead_unique else "",
            unique_passive_key=cand_key,
        ))

    if sort_by == "efficiency":
        ranked.sort(key=lambda r: (r.dps_per_1k_gold, r.delta_dps), reverse=True)
    else:
        ranked.sort(key=lambda r: (r.delta_dps, r.dps_per_1k_gold), reverse=True)

    if top_n is not None and top_n > 0:
        ranked = ranked[:top_n]

    notes: list[str] = []
    if stripped_trinkets:
        notes.append(
            f"mode=ARENA - stripped trinket(s) {list(stripped_trinkets)} "
            f"from current_item_ids"
        )
    if include_components:
        notes.append("include_components=True - non-terminal items in the ranking")
    if budget is not None:
        notes.append(f"budget={budget}g - items over budget filtered")
    if only_ids is not None:
        notes.append(f"only_item_ids restricted to {len(only_ids)} whitelisted ids")
    if baseline.onhit_dps == 0.0:
        notes.append(
            "baseline onhit DPS is 0 - champion may be missing from the "
            "abilities snapshot or have no measured cast rates"
        )

    return OnhitDpsRankResult(
        champion_id=baseline.champion_id,
        champion_name=baseline.champion_name,
        level=level,
        mode=mode,
        current_item_ids=current_ids,
        baseline_ability_dps=baseline.ability_dps,
        baseline_auto_dps=baseline.auto_dps,
        baseline_onhit_dps=baseline.onhit_dps,
        target_armor=target_armor,
        target_mr=target_mr,
        target_max_hp=target_max_hp,
        target_bonus_hp=target_bonus_hp,
        phase=baseline.phase,
        budget=budget,
        slot_count=slot_count,
        sort_by=sort_by,
        candidates_considered=len(snapshot.items),
        candidates_evaluated=len(candidates),
        ranked=tuple(ranked),
        notes=tuple(notes),
    )
