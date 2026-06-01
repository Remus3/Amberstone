"""Mage item ranker for ``/rank-mage`` (relocated from ability_dps.py, item 241 A2).

``rank_items_by_ability_dps`` plus its two result dataclasses
(``AbilityDpsRankedItem`` / ``AbilityDpsRankResult``) - the self-contained ranking
layer that scores each candidate item by total ability-DPS gain. Mirrors how
``dps.py`` keeps ``compute_dps`` separate from its rankers.

``compute_ability_dps`` is imported lazily inside the ranking function (not at
module level) so this module never forms an import cycle with ``ability_dps``;
``ability_dps`` re-exports the three public symbols below. ``from __future__
import annotations`` keeps the dataclass field annotations lazy.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence

from .abilities import AbilitiesSnapshot
from .data_loader import DataSnapshot
from .effects import ITEM_EFFECTS
from .rank import (
    DEFAULT_SLOT_COUNT,
    DEFAULT_TOP_N,
    SORT_KEYS,
    _filter_candidates,
    _is_terminal,
    strip_arena_trinkets,
)
from .stats import clamp_level

# ─── ranker (Phase 4c, s179) ─────────────────────────────────────────────────


@dataclass(frozen=True)
class AbilityDpsRankedItem:
    """Phase 4c sibling of ``RankedItem`` / ``EhpRankedItem`` /
    ``HybridRankedItem`` - one row of the mage ranker output.

    ``delta_ability_dps`` is the raw total-ability-DPS gain over the
    baseline. ``ability_dps_per_1k_gold`` zeroes out on regressions so
    the efficiency column doesn't mislead.
    """
    item_id: str
    item_name: str
    gold: int
    delta_ability_dps: float
    new_ability_dps: float
    ability_dps_per_1k_gold: float
    is_terminal: bool
    tags: tuple[str, ...]
    shares_dead_unique: bool = False
    dead_unique_key: str = ""
    # Phase 4(d): candidate's own unique-passive family key, always set
    # (collision-independent) - the positive "locks <family>" signal.
    unique_passive_key: str = ""

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "item_name": self.item_name,
            "gold": self.gold,
            "delta_ability_dps": self.delta_ability_dps,
            "new_ability_dps": self.new_ability_dps,
            "ability_dps_per_1k_gold": self.ability_dps_per_1k_gold,
            "is_terminal": self.is_terminal,
            "tags": list(self.tags),
            "shares_dead_unique": self.shares_dead_unique,
            "dead_unique_key": self.dead_unique_key,
            "unique_passive_key": self.unique_passive_key,
        }


@dataclass(frozen=True)
class AbilityDpsRankResult:
    """Phase 4c - output of ``rank_items_by_ability_dps``."""
    champion_id: str
    champion_name: str
    level: int
    mode: str
    current_item_ids: tuple[str, ...]
    baseline_ability_dps: float
    primary_scaling: str                  # "AP" | "AD" | "HP" | "MIXED"
    target_armor: float
    target_mr: float
    target_max_hp: float
    target_bonus_hp: float
    target_current_hp_pct: float
    max_priority: tuple[str, str, str]
    max_priority_source: str              # "override" | "champion" | "default"
    form_index_source: str                # "override" | "champion" | "default"
    form_index_resolved: dict[str, int]   # merged map actually used
    block_index_source: str               # "override" | "champion" | "default"
    block_index_resolved: "dict[str, int | list[int] | dict[str, int | list[int]]]"  # merged (champion, key) → block_index map
    block_strategy: str
    mode_multiplier: float                # aramDamageDealt; 1.0 outside ARAM
    budget: Optional[int]
    slot_count: int
    sort_by: str
    candidates_considered: int            # snapshot.items total
    candidates_evaluated: int             # passed filter
    ranked: tuple[AbilityDpsRankedItem, ...]
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "champion_id": self.champion_id,
            "champion_name": self.champion_name,
            "level": self.level,
            "mode": self.mode,
            "current_item_ids": list(self.current_item_ids),
            "baseline_ability_dps": self.baseline_ability_dps,
            "primary_scaling": self.primary_scaling,
            "target_armor": self.target_armor,
            "target_mr": self.target_mr,
            "target_max_hp": self.target_max_hp,
            "target_bonus_hp": self.target_bonus_hp,
            "target_current_hp_pct": self.target_current_hp_pct,
            "max_priority": list(self.max_priority),
            "max_priority_source": self.max_priority_source,
            "form_index_source": self.form_index_source,
            "form_index_resolved": dict(self.form_index_resolved),
            "block_index_source": self.block_index_source,
            "block_index_resolved": dict(self.block_index_resolved),
            "block_strategy": self.block_strategy,
            "mode_multiplier": self.mode_multiplier,
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
            f"- mode {self.mode}  [MAGE]"
        )
        rows = [head, "-" * len(head)]
        if self.current_item_ids:
            rows.append(f"current items: {', '.join(self.current_item_ids)}")
        else:
            rows.append("current items: (none)")
        rows.append(
            f"target: armor={self.target_armor:.0f}  mr={self.target_mr:.0f}"
            f"  max_hp={self.target_max_hp:.0f}  bonus_hp={self.target_bonus_hp:.0f}"
            f"  current_hp_pct={self.target_current_hp_pct * 100:.0f}%"
        )
        rows.append(
            f"priority: {'>'.join(self.max_priority)}  "
            f"block: {self.block_strategy}  primary_scaling: {self.primary_scaling}"
        )
        budget_label = "unlimited" if self.budget is None else f"{self.budget}"
        rows.append(
            f"budget: {budget_label}  slots: {len(self.current_item_ids)}/{self.slot_count}"
            f"  sort: {self.sort_by}"
        )
        rows.append(
            f"baseline_ability_dps: {self.baseline_ability_dps:.2f}   "
            f"considered/evaluated: {self.candidates_considered}/{self.candidates_evaluated}"
        )
        rows.append("")
        rows.append(
            f"  {'#':>3}  {'id':>6}  {'name':<28}  "
            f"{'gold':>5}  {'+adps':>7}  {'new':>7}  {'adps/1k':>7}"
        )
        rows.append("  " + "-" * 78)
        for i, r in enumerate(self.ranked, 1):
            rows.append(
                f"  {i:>3}  {r.item_id:>6}  {r.item_name[:28]:<28}  "
                f"{r.gold:>5}  {r.delta_ability_dps:>7.2f}  "
                f"{r.new_ability_dps:>7.2f}  {r.ability_dps_per_1k_gold:>7.2f}"
            )
        if self.notes:
            rows.append("")
            for n in self.notes:
                rows.append(f"  note: {n}")
        return "\n".join(rows)


def rank_items_by_ability_dps(
    snapshot: DataSnapshot,
    champion_id: str,
    level: int,
    current_item_ids: Optional[Iterable[str | int]] = None,
    mode: str = "SR",
    target_armor: float = 0.0,
    target_mr: float = 0.0,
    target_max_hp: float = 0.0,
    target_bonus_hp: float = 0.0,
    target_current_hp_pct: float = 1.0,
    budget: Optional[int] = None,
    slot_count: int = DEFAULT_SLOT_COUNT,
    top_n: int = DEFAULT_TOP_N,
    include_components: bool = False,
    only_item_ids: Optional[Iterable[str | int]] = None,
    sort_by: str = "delta",
    augments: Optional[Iterable] = None,
    abilities_snapshot: Optional[AbilitiesSnapshot] = None,
    max_priority: Optional[Sequence[str]] = None,
    block_strategy: str = "first",
    form_index_overrides: Optional[dict[str, int]] = None,
    block_index_overrides: "Optional[dict[str, int | list[int] | dict[str, int | list[int]]]]" = None,
    filter_shared_uniques: bool = True,
    apply_ability_amps: bool = False,
) -> AbilityDpsRankResult:
    """Rank items by total-ability-DPS gain when added to ``current_item_ids``.

    Phase 4c sibling of ``rank_items`` (DPS), ``rank_items_by_ehp`` (EHP),
    and ``rank_items_by_hybrid`` (bruiser). Same candidate-filtering
    pipeline - purchasable + mode-legal + optional whitelist + budget +
    terminal-only + dead-unique dedup. Only the scoring function changes:
    each candidate's total ability DPS via ``compute_ability_dps`` is
    compared to the baseline.

    Sort keys:
      * ``delta``       - absolute ability-DPS gain (default)
      * ``efficiency``  - ability-DPS gain per 1000 gold

    ``filter_shared_uniques=True`` drops candidates whose unique passive
    key collides with one already in ``current_item_ids`` - matches the
    other scorers' behavior so the mage ranker stays consistent with the
    rest of the engine.

    ``max_priority``, ``block_strategy``, ``form_index_overrides``,
    ``block_index_overrides``, and ``target_current_hp_pct`` flow through
    to ``compute_ability_dps`` for both the baseline and each candidate.
    """
    from .ability_dps import (
        _resolve_block_index_overrides,
        _resolve_form_index_overrides,
        _resolve_max_priority,
        compute_ability_dps,
    )

    if sort_by not in SORT_KEYS:
        raise ValueError(f"sort_by must be one of {SORT_KEYS}, got {sort_by!r}")
    level = clamp_level(level)

    # Resolve once so baseline + every candidate use the same priority +
    # form_index + block_index, and the result carries consistent source
    # labels.
    resolved_priority, priority_source = _resolve_max_priority(champion_id, max_priority)
    resolved_form_index, form_index_source = _resolve_form_index_overrides(
        champion_id, form_index_overrides,
    )
    resolved_block_index, block_index_source = _resolve_block_index_overrides(
        champion_id, block_index_overrides,
    )

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

    baseline = compute_ability_dps(
        snapshot,
        champion_id=champion_id, level=level,
        item_ids=current_ids, mode=mode,
        target_armor=target_armor, target_mr=target_mr,
        target_max_hp=target_max_hp, target_bonus_hp=target_bonus_hp,
        target_current_hp_pct=target_current_hp_pct,
        augments=augments,
        abilities_snapshot=abilities_snapshot,
        max_priority=resolved_priority,
        block_strategy=block_strategy,
        form_index_overrides=resolved_form_index,
        block_index_overrides=resolved_block_index,
        apply_ability_amps=apply_ability_amps,
    )

    candidates = _filter_candidates(
        snapshot,
        mode=mode,
        current_ids=current_set,
        budget=budget,
        include_components=include_components,
        only_ids=only_ids,
    )

    ranked: list[AbilityDpsRankedItem] = []
    for item_id, rec in candidates:
        cand_eff = ITEM_EFFECTS.get(item_id)
        cand_key = cand_eff.unique_passive_key if cand_eff is not None else ""
        shares_dead_unique = bool(cand_key and cand_key in current_unique_keys)
        if shares_dead_unique and filter_shared_uniques:
            continue
        new_build = current_ids + (item_id,)
        try:
            scored = compute_ability_dps(
                snapshot,
                champion_id=champion_id, level=level,
                item_ids=new_build, mode=mode,
                target_armor=target_armor, target_mr=target_mr,
                target_max_hp=target_max_hp, target_bonus_hp=target_bonus_hp,
                target_current_hp_pct=target_current_hp_pct,
                augments=augments,
                abilities_snapshot=abilities_snapshot,
                max_priority=resolved_priority,
                block_strategy=block_strategy,
                form_index_overrides=resolved_form_index,
                block_index_overrides=resolved_block_index,
                apply_ability_amps=apply_ability_amps,
            )
        except (KeyError, ValueError):
            continue
        gold = int((rec.get("gold") or {}).get("total", 0) or 0)
        delta = scored.total_ability_dps - baseline.total_ability_dps
        eff = (delta / (gold / 1000.0)) if (gold > 0 and delta > 0) else 0.0
        ranked.append(AbilityDpsRankedItem(
            item_id=item_id,
            item_name=str(rec.get("name", item_id)),
            gold=gold,
            delta_ability_dps=delta,
            new_ability_dps=scored.total_ability_dps,
            ability_dps_per_1k_gold=eff,
            is_terminal=_is_terminal(rec),
            tags=tuple(rec.get("tags") or ()),
            shares_dead_unique=shares_dead_unique,
            dead_unique_key=cand_key if shares_dead_unique else "",
            unique_passive_key=cand_key,
        ))

    if sort_by == "efficiency":
        ranked.sort(key=lambda r: (r.ability_dps_per_1k_gold, r.delta_ability_dps), reverse=True)
    else:
        ranked.sort(key=lambda r: (r.delta_ability_dps, r.ability_dps_per_1k_gold), reverse=True)

    if top_n is not None and top_n > 0:
        ranked = ranked[:top_n]

    notes: list[str] = []
    notes.append(
        f"max_priority={'>'.join(resolved_priority)} (source={priority_source})  "
        f"block_strategy={block_strategy}"
    )
    notes.append(f"primary_scaling={baseline.primary_scaling}")
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
    if baseline.mode_multiplier != 1.0:
        notes.append(
            f"mode_multiplier={baseline.mode_multiplier:.3f} on per-cast damage"
        )
    if baseline.total_ability_dps == 0.0:
        notes.append(
            "baseline ability DPS is 0 - champion may be missing from the "
            "abilities snapshot or have no measured cast rates"
        )

    if resolved_block_index:
        notes.append(
            f"block_index source={block_index_source}: "
            + ", ".join(f"{k}={resolved_block_index[k]}" for k in sorted(resolved_block_index))
        )

    return AbilityDpsRankResult(
        champion_id=baseline.champion_id,
        champion_name=baseline.champion_name,
        level=level,
        mode=mode,
        current_item_ids=current_ids,
        baseline_ability_dps=baseline.total_ability_dps,
        primary_scaling=baseline.primary_scaling,
        target_armor=target_armor,
        target_mr=target_mr,
        target_max_hp=target_max_hp,
        target_bonus_hp=target_bonus_hp,
        target_current_hp_pct=target_current_hp_pct,
        max_priority=tuple(resolved_priority),
        max_priority_source=priority_source,
        form_index_source=form_index_source,
        form_index_resolved=dict(resolved_form_index),
        block_index_source=block_index_source,
        block_index_resolved=dict(resolved_block_index),
        block_strategy=block_strategy,
        mode_multiplier=baseline.mode_multiplier,
        budget=budget,
        slot_count=slot_count,
        sort_by=sort_by,
        candidates_considered=len(snapshot.items),
        candidates_evaluated=len(candidates),
        ranked=tuple(ranked),
        notes=tuple(notes),
    )
