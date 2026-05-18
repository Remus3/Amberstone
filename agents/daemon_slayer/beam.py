"""Phase 2 step 4 - full-build beam-search ranker.

Single-slot ``rank_items`` picks the best Nth item GREEDILY against a fixed
baseline; it can't see synergies that only score well together (Trinity Force
+ Sundered Sky, IE + Stormrazor crit-on-energized). Beam search keeps the
top-K partial builds at each slot depth and expands them all in parallel,
then returns the top-N **complete** builds sorted by final weighted DPS.

Algorithm:

  1. Score the seed beam (caller's current build, or naked).
  2. Pre-filter the candidate pool once (mode legality, purchasability,
     terminal-only, ``only_item_ids`` whitelist).
  3. For each remaining slot:
       * Expand every surviving beam by every candidate not already in it.
       * Honour boots-uniqueness (only one ``"Boots"``-tagged item per build).
       * Skip expansions that exceed ``total_budget`` (when set).
       * Dedupe by ``frozenset(item_ids)`` - order-invariant; equivalent
         orderings are scored once.
       * Score each expansion via ``compute_dps`` (full Phase 4 effect chain).
       * Keep top ``beam_width`` by weighted DPS.
  4. Sort final survivors and return top ``top_n``.

Cost: ``slots × beam_width × |candidate_pool|`` compute_dps calls in the
worst case (no dedup hits). Default ``beam_width=10`` over the SR pool
(~175 candidates) lands a 6-slot search in ~10k evaluations - sub-second
on the warm snapshot. Tune ``beam_width`` for thoroughness vs. wall time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

from .data_loader import DataSnapshot
from .dps import compute_dps
from .rank import MODE_MAP_ID, _filter_candidates, _is_terminal, strip_arena_trinkets
from .stats import clamp_level

DEFAULT_BEAM_WIDTH = 10
DEFAULT_TOP_N = 10
DEFAULT_SLOT_COUNT = 6
_BOOTS_TAG = "Boots"
_CONSUMABLE_TAG = "Consumable"


@dataclass(frozen=True)
class RankedBuild:
    item_ids: tuple[str, ...]
    item_names: tuple[str, ...]
    total_gold: int
    final_dps: float
    baseline_dps: float
    delta_dps: float
    dps_per_1k_gold: float

    def to_dict(self) -> dict:
        return {
            "item_ids": list(self.item_ids),
            "item_names": list(self.item_names),
            "total_gold": self.total_gold,
            "final_dps": self.final_dps,
            "baseline_dps": self.baseline_dps,
            "delta_dps": self.delta_dps,
            "dps_per_1k_gold": self.dps_per_1k_gold,
        }


@dataclass(frozen=True)
class BeamResult:
    champion_id: str
    champion_name: str
    level: int
    mode: str
    current_item_ids: tuple[str, ...]
    target_armor: float
    target_mr: float
    target_max_hp: float
    target_bonus_hp: float
    phase: str
    baseline_dps: float
    slot_count: int
    beam_width: int
    total_budget: Optional[int]
    candidate_pool_size: int
    builds_evaluated: int
    depth_reached: int
    ranked: tuple[RankedBuild, ...]
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "champion_id": self.champion_id,
            "champion_name": self.champion_name,
            "level": self.level,
            "mode": self.mode,
            "current_item_ids": list(self.current_item_ids),
            "target_armor": self.target_armor,
            "target_mr": self.target_mr,
            "target_max_hp": self.target_max_hp,
            "target_bonus_hp": self.target_bonus_hp,
            "phase": self.phase,
            "baseline_dps": self.baseline_dps,
            "slot_count": self.slot_count,
            "beam_width": self.beam_width,
            "total_budget": self.total_budget,
            "candidate_pool_size": self.candidate_pool_size,
            "builds_evaluated": self.builds_evaluated,
            "depth_reached": self.depth_reached,
            "ranked": [r.to_dict() for r in self.ranked],
            "notes": list(self.notes),
        }

    def format_table(self) -> str:
        head = (
            f"{self.champion_name} ({self.champion_id}) - lvl {self.level} "
            f"- mode {self.mode} - phase {self.phase} - beam"
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
        budget_label = "unlimited" if self.total_budget is None else f"{self.total_budget}"
        rows.append(
            f"slots={self.slot_count}  beam_width={self.beam_width}  "
            f"depth_reached={self.depth_reached}  total_budget={budget_label}"
        )
        rows.append(
            f"baseline_dps={self.baseline_dps:.2f}  pool={self.candidate_pool_size}  "
            f"builds_evaluated={self.builds_evaluated}"
        )
        rows.append("")
        rows.append(f"  {'#':>3}  {'+dps':>7}  {'final':>7}  {'gold':>5}  "
                    f"{'g/1k':>6}  build")
        rows.append("  " + "-" * 78)
        for i, r in enumerate(self.ranked, 1):
            names = " · ".join(n[:14] for n in r.item_names)
            rows.append(
                f"  {i:>3}  {r.delta_dps:>7.2f}  {r.final_dps:>7.2f}  "
                f"{r.total_gold:>5}  {r.dps_per_1k_gold:>6.2f}  {names}"
            )
        if self.notes:
            rows.append("")
            for n in self.notes:
                rows.append(f"  note: {n}")
        return "\n".join(rows)


def _has_boots_tag(rec: dict) -> bool:
    return _BOOTS_TAG in (rec.get("tags") or ())


def _is_consumable(rec: dict) -> bool:
    """Health Potion, Control Ward, Stealth Ward, Cappa Juice etc.

    Beam search treats consumables as build-irrelevant: they have positive
    gold but contribute zero DPS, so a tight ``total_budget`` would
    otherwise fill empty slots with potions instead of leaving them open.
    Trinkets (3340/3363/3364) are already excluded - total_gold=0 fails
    the ``_is_purchasable`` filter upstream.
    """
    if rec.get("consumed") is True:
        return True
    return _CONSUMABLE_TAG in (rec.get("tags") or ())


def _build_gold(snapshot: DataSnapshot, item_ids: Iterable[str]) -> int:
    total = 0
    for iid in item_ids:
        rec = snapshot.items.get(iid)
        if rec is None:
            continue
        total += int((rec.get("gold") or {}).get("total", 0) or 0)
    return total


def _seed_has_boots(snapshot: DataSnapshot, item_ids: Iterable[str]) -> bool:
    for iid in item_ids:
        rec = snapshot.items.get(iid)
        if rec is not None and _has_boots_tag(rec):
            return True
    return False


def beam_search_build(
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
    slot_count: int = DEFAULT_SLOT_COUNT,
    beam_width: int = DEFAULT_BEAM_WIDTH,
    top_n: int = DEFAULT_TOP_N,
    total_budget: Optional[int] = None,
    include_components: bool = False,
    only_item_ids: Optional[Iterable[str | int]] = None,
    boots_unique: bool = True,
) -> BeamResult:
    """Search top ``top_n`` complete builds for ``champion_id``.

    ``current_item_ids`` are pinned in every returned build (the user already
    owns them). ``slot_count - len(current_item_ids)`` is the search depth.

    ``beam_width`` caps survivors per generation; ``top_n`` clips the final
    output. ``total_budget`` (if set) prunes any beam whose total cost
    exceeds it. ``boots_unique=True`` (default) prevents two boots items
    from coexisting in a build.

    When the seed already fills ``slot_count`` no search runs and a single
    baseline-only result is returned. When search exhausts (no candidates
    can extend any surviving beam - common with tight budgets or
    ``only_item_ids`` whitelists), the deepest layer reached is what
    ``ranked`` returns.
    """
    if beam_width < 1:
        raise ValueError(f"beam_width must be >= 1, got {beam_width}")
    if top_n < 1:
        raise ValueError(f"top_n must be >= 1, got {top_n}")
    level = clamp_level(level)

    current_ids: tuple[str, ...] = tuple(str(i) for i in (current_item_ids or ()))
    current_ids, stripped_trinkets = strip_arena_trinkets(current_ids, mode)
    if len(current_ids) > slot_count:
        raise ValueError(
            f"current_item_ids has {len(current_ids)} items; slot_count={slot_count} "
            f"can't hold them all"
        )

    only_ids: Optional[set[str]] = None
    if only_item_ids is not None:
        only_ids = {str(i) for i in only_item_ids}

    baseline = compute_dps(
        snapshot,
        champion_id=champion_id,
        level=level,
        item_ids=current_ids,
        mode=mode,
        target_armor=target_armor,
        target_mr=target_mr,
        target_max_hp=target_max_hp,
        target_bonus_hp=target_bonus_hp,
        phase=phase,
    )

    seed_gold = _build_gold(snapshot, current_ids)
    seed_beam: tuple[tuple[str, ...], float, int] = (
        current_ids, baseline.weighted_dps, seed_gold,
    )

    notes: list[str] = []
    if mode in MODE_MAP_ID:
        notes.append(f"mode={mode} → maps id {MODE_MAP_ID[mode]}")
    else:
        notes.append(f"mode={mode} not in MODE_MAP_ID - no per-mode item filter applied")
    if stripped_trinkets:
        notes.append(
            f"mode=ARENA - stripped trinket(s) {list(stripped_trinkets)} from current_item_ids"
        )
    if total_budget is not None:
        notes.append(f"total_budget={total_budget}g")
    if not boots_unique:
        notes.append("boots_unique=False - multiple boots items allowed")
    if include_components:
        notes.append("include_components=True - non-terminal items in the search")
    if baseline.mode_multiplier == 0.0:
        notes.append(
            "baseline mode_multiplier=0 - every build evaluates to 0 DPS (e.g. Yunara in ARAM)"
        )

    remaining = slot_count - len(current_ids)
    if remaining <= 0:
        # Seed already fills the build - nothing to search. Return a
        # single-row result so the consumer always sees a valid build.
        names = tuple(str((snapshot.items.get(i) or {}).get("name", i)) for i in current_ids)
        single = RankedBuild(
            item_ids=current_ids,
            item_names=names,
            total_gold=seed_gold,
            final_dps=baseline.weighted_dps,
            baseline_dps=baseline.weighted_dps,
            delta_dps=0.0,
            dps_per_1k_gold=0.0,
        )
        return BeamResult(
            champion_id=baseline.champion_id,
            champion_name=baseline.champion_name,
            level=level, mode=mode,
            current_item_ids=current_ids,
            target_armor=target_armor, target_mr=target_mr,
            target_max_hp=target_max_hp,
            target_bonus_hp=target_bonus_hp,
            phase=baseline.phase, baseline_dps=baseline.weighted_dps,
            slot_count=slot_count, beam_width=beam_width,
            total_budget=total_budget,
            candidate_pool_size=0, builds_evaluated=1, depth_reached=0,
            ranked=(single,),
            notes=tuple(notes + ["seed already fills slot_count - no search performed"]),
        )

    # Pool = all candidates regardless of beam contents. Cheaper to pre-prepare
    # gold + boots-flag once than to re-derive per beam expansion. Consumables
    # (Health Potion, Control Ward, etc.) get dropped here - they're
    # purchasable and DPS-neutral, so a tight ``total_budget`` would
    # otherwise fill empty slots with them.
    raw_pool = _filter_candidates(
        snapshot,
        mode=mode,
        current_ids=set(),  # per-beam exclusion happens below
        budget=None,
        include_components=include_components,
        only_ids=only_ids,
    )
    pool: list[tuple[str, dict, int, bool]] = [
        (iid, rec,
         int((rec.get("gold") or {}).get("total", 0) or 0),
         _has_boots_tag(rec))
        for iid, rec in raw_pool
        if not _is_consumable(rec)
    ]

    beams: list[tuple[tuple[str, ...], float, int]] = [seed_beam]
    seen: set[frozenset] = {frozenset(current_ids)}
    builds_evaluated = 1
    depth_reached = 0
    last_full_layer = beams

    for depth in range(1, remaining + 1):
        next_beams: list[tuple[tuple[str, ...], float, int]] = []
        for items, _dps, gold in beams:
            cur_set = set(items)
            beam_has_boots = boots_unique and _seed_has_boots(snapshot, items)
            for iid, rec, item_gold, item_is_boots in pool:
                if iid in cur_set:
                    continue
                if boots_unique and beam_has_boots and item_is_boots:
                    continue
                new_gold = gold + item_gold
                if total_budget is not None and new_gold > total_budget:
                    continue
                new_items = items + (iid,)
                key = frozenset(new_items)
                if key in seen:
                    continue
                seen.add(key)
                try:
                    scored = compute_dps(
                        snapshot,
                        champion_id=champion_id,
                        level=level,
                        item_ids=new_items,
                        mode=mode,
                        target_armor=target_armor,
                        target_mr=target_mr,
                        target_max_hp=target_max_hp,
                        target_bonus_hp=target_bonus_hp,
                        phase=phase,
                    )
                except (KeyError, ValueError):
                    continue
                builds_evaluated += 1
                next_beams.append((new_items, scored.weighted_dps, new_gold))
        if not next_beams:
            # No surviving expansion - search exhausted (tight budget,
            # narrow whitelist, etc). Stop and rank what we have at the
            # deepest layer that produced beams.
            break
        next_beams.sort(key=lambda b: b[1], reverse=True)
        beams = next_beams[:beam_width]
        depth_reached = depth
        last_full_layer = beams

    final = sorted(last_full_layer, key=lambda b: b[1], reverse=True)[:top_n]

    ranked: list[RankedBuild] = []
    for items, weighted, gold in final:
        delta = weighted - baseline.weighted_dps
        eff = (delta / (gold / 1000.0)) if (gold > 0 and delta > 0) else 0.0
        names = tuple(str((snapshot.items.get(i) or {}).get("name", i)) for i in items)
        ranked.append(RankedBuild(
            item_ids=items,
            item_names=names,
            total_gold=gold,
            final_dps=weighted,
            baseline_dps=baseline.weighted_dps,
            delta_dps=delta,
            dps_per_1k_gold=eff,
        ))

    if depth_reached < remaining:
        notes.append(
            f"search exhausted at depth {depth_reached}/{remaining} - no further expansions"
        )

    return BeamResult(
        champion_id=baseline.champion_id,
        champion_name=baseline.champion_name,
        level=level, mode=mode,
        current_item_ids=current_ids,
        target_armor=target_armor, target_mr=target_mr,
        target_max_hp=target_max_hp,
        target_bonus_hp=target_bonus_hp,
        phase=baseline.phase, baseline_dps=baseline.weighted_dps,
        slot_count=slot_count, beam_width=beam_width,
        total_budget=total_budget,
        candidate_pool_size=len(pool),
        builds_evaluated=builds_evaluated,
        depth_reached=depth_reached,
        ranked=tuple(ranked),
        notes=tuple(notes),
    )
