"""Phase 2 step 3 - item ranker.

Score every purchasable, mode-legal item in the snapshot by the DPS it
would add to a champion's current build. Filter via ``maps`` (mode
validity), ``gold.total`` (must be a real purchase), and ``into`` (skip
non-terminal components by default - ranking Long Sword above Bloodthirster
is rarely useful). Sort by absolute ``delta_dps`` (default) or by
``dps_per_gold``.

This is pure Python on top of ``compute_dps`` - N×DPS where N is the
filtered candidate count (≈125-175 in 16.9.1 for the common modes).
Sub-second on a warm snapshot. No conditional effects (passives,
on-hit) - those live in Phase 4 alongside ability damage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

from .data_loader import DataSnapshot
from .dps import compute_dps
from .effects import ITEM_EFFECTS
from .stats import clamp_level

# Mode → DDragon map id. Items whose ``maps[map_id]`` is False are unbuyable
# in that mode (e.g. ARAM bans non-completed components like Phage). Modes
# without a wired map id pass through with no validity filter.
#
# BRAWL is DDragon map 35. coaches/brawl_coach.py._ds_engine_mode("BRAWL")
# returns the literal "BRAWL" (URF/NexusBlitz/etc ride the SR identity;
# only true Brawl is map 35 - see tests/test_cross_mode_ds_p1l6.py
# CrossModeBrawlRoutingTests), so rank_items genuinely receives
# mode="BRAWL" for real Brawl games. Without this entry _is_legal_in_mode
# was a silent no-op for the entire mode, admitting ~281 map-35-illegal
# items (Doran's, jungle companions, the 22-prefixed Arena-mirror set)
# into Brawl recommendations (audit P1-L23).
MODE_MAP_ID: dict[str, str] = {
    "SR": "11",
    "ARAM": "12",
    "ARENA": "30",
    "BRAWL": "35",
}

DEFAULT_SLOT_COUNT = 6
DEFAULT_TOP_N = 20
SORT_KEYS: tuple[str, ...] = ("delta", "efficiency")

# Arena gives every player Arcane Sweeper as a trinket - it occupies the
# trinket slot, not an item slot, but the live game's inventory polling
# returns it alongside the 6 build slots. Strip these from current_item_ids
# when mode=ARENA so the slot-count check passes and the baseline DPS
# isn't padded with a zero-stat record. The candidate pool already
# excludes them via _is_purchasable (gold.purchasable=False).
ARENA_TRINKET_IDS: frozenset[str] = frozenset({"3348"})


def strip_arena_trinkets(
    current_ids: tuple[str, ...], mode: str
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return (kept_ids, stripped_ids). No-op outside ARENA."""
    if mode != "ARENA" or not current_ids:
        return current_ids, ()
    kept: list[str] = []
    stripped: list[str] = []
    for i in current_ids:
        if i in ARENA_TRINKET_IDS:
            stripped.append(i)
        else:
            kept.append(i)
    return tuple(kept), tuple(stripped)


@dataclass(frozen=True)
class RankedItem:
    item_id: str
    item_name: str
    gold: int
    delta_dps: float            # weighted_dps with item - baseline
    new_dps: float              # weighted_dps with item
    dps_per_1k_gold: float      # delta_dps / (gold/1000); 0 when delta<=0
    is_terminal: bool           # `into` is empty - final-tier item
    tags: tuple[str, ...]
    # Phase 6 step 8 (2026-05-12): candidate's unique passive collides with an
    # item already in current_item_ids - the proc/pen contribution would be
    # zeroed by collect_effects() dedup. Stat block still contributes (the
    # delta_dps reflects this honestly) but the operator gets no value from
    # the unique itself. Default-filter is on in ``rank_items``; consumers
    # can opt out via ``filter_shared_uniques=False`` to surface the flag.
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
            "delta_dps": self.delta_dps,
            "new_dps": self.new_dps,
            "dps_per_1k_gold": self.dps_per_1k_gold,
            "is_terminal": self.is_terminal,
            "tags": list(self.tags),
            "shares_dead_unique": self.shares_dead_unique,
            "dead_unique_key": self.dead_unique_key,
            "unique_passive_key": self.unique_passive_key,
        }


@dataclass(frozen=True)
class RankResult:
    champion_id: str
    champion_name: str
    level: int
    mode: str
    current_item_ids: tuple[str, ...]
    baseline_dps: float
    target_armor: float
    target_mr: float
    target_max_hp: float
    target_bonus_hp: float
    phase: str
    budget: Optional[int]
    slot_count: int
    sort_by: str
    candidates_considered: int      # all items in snapshot
    candidates_evaluated: int       # passed filter
    ranked: tuple[RankedItem, ...]
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "champion_id": self.champion_id,
            "champion_name": self.champion_name,
            "level": self.level,
            "mode": self.mode,
            "current_item_ids": list(self.current_item_ids),
            "baseline_dps": self.baseline_dps,
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
            f"- mode {self.mode} - phase {self.phase}"
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
            f"baseline_dps: {self.baseline_dps:.2f}   "
            f"considered/evaluated: {self.candidates_considered}/{self.candidates_evaluated}"
        )
        rows.append("")
        rows.append(f"  {'#':>3}  {'id':>6}  {'name':<28}  "
                    f"{'gold':>5}  {'+dps':>7}  {'new':>7}  {'dps/1k':>7}")
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


def _is_purchasable(item: dict) -> bool:
    gold = item.get("gold") or {}
    return bool(gold.get("purchasable")) and int(gold.get("total", 0) or 0) > 0


def _is_terminal(item: dict) -> bool:
    """Final-tier item - has no ``into`` upgrade path.

    DDragon represents an empty/missing ``into`` as ``None`` or ``[]``.
    """
    into = item.get("into")
    return not into


def _is_legal_in_mode(item: dict, mode: str) -> bool:
    """Items list per-map availability. If we don't recognise the mode, allow."""
    map_id = MODE_MAP_ID.get(mode)
    if map_id is None:
        return True
    maps = item.get("maps") or {}
    return bool(maps.get(map_id))


def _filter_candidates(
    snapshot: DataSnapshot,
    mode: str,
    current_ids: set[str],
    budget: Optional[int],
    include_components: bool,
    only_ids: Optional[set[str]],
) -> list[tuple[str, dict]]:
    """Return ``[(item_id, item_record), ...]`` passing all filters.

    Filters applied (in order):
      * already-equipped items skipped (``current_ids``)
      * ``only_ids`` whitelist - restrict to caller-selected ids when set
      * purchasable + ``gold.total`` > 0
      * mode validity via ``maps`` (only when mode is known)
      * terminal-only (``into`` empty) unless ``include_components``
      * gold ≤ ``budget`` when budget is set
    """
    out: list[tuple[str, dict]] = []
    for item_id, rec in snapshot.items.items():
        if item_id in current_ids:
            continue
        if only_ids is not None and item_id not in only_ids:
            continue
        if not _is_purchasable(rec):
            continue
        if not _is_legal_in_mode(rec, mode):
            continue
        if not include_components and not _is_terminal(rec):
            continue
        gold = int((rec.get("gold") or {}).get("total", 0) or 0)
        if budget is not None and gold > budget:
            continue
        out.append((item_id, rec))
    return out


def rank_items(
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
    filter_shared_uniques: bool = True,
) -> RankResult:
    """Rank items by DPS contribution when added to ``current_item_ids``.

    Caller supplies the build-so-far in ``current_item_ids`` (or omits for
    naked baseline). Each remaining slot is scored by re-running
    ``compute_dps`` with the candidate appended and subtracting the
    baseline. Results are clipped to ``top_n`` after sorting.

    Sort keys:
      * ``delta``       - absolute DPS gained (default)
      * ``efficiency``  - DPS gained per 1000 gold spent

    ``include_components=True`` keeps non-terminal items in the ranking
    (useful when the player is mid-recipe and just bought a Long Sword).
    ``only_item_ids`` restricts to a caller-provided whitelist (e.g. UI
    pre-filtered by tag).

    ``filter_shared_uniques=True`` (default) drops candidates whose
    ``unique_passive_key`` matches a unique already in
    ``current_item_ids`` - operator gets no value from the second proc
    even though stat-only delta_dps would be positive (Trinity → ER,
    Sterak's → Maw, Sunfire → Hollow Radiance). Pass ``False`` to surface
    them with ``shares_dead_unique=True`` set on the result.
    """
    if sort_by not in SORT_KEYS:
        raise ValueError(f"sort_by must be one of {SORT_KEYS}, got {sort_by!r}")
    level = clamp_level(level)

    current_ids: tuple[str, ...] = tuple(str(i) for i in (current_item_ids or ()))
    current_ids, stripped_trinkets = strip_arena_trinkets(current_ids, mode)
    current_set = set(current_ids)
    # Collect every unique_passive_key already locked in by the current build.
    # Candidates sharing one of these keys would have their proc/pen effect
    # zeroed by ``collect_effects`` - surface that to consumers via the flag
    # on RankedItem, and filter by default.
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
        augments=augments,
    )

    candidates = _filter_candidates(
        snapshot,
        mode=mode,
        current_ids=current_set,
        budget=budget,
        include_components=include_components,
        only_ids=only_ids,
    )

    ranked: list[RankedItem] = []
    for item_id, rec in candidates:
        # Compute the dead-unique flag BEFORE the expensive compute_dps call
        # so the default-filter path saves the work entirely.
        cand_eff = ITEM_EFFECTS.get(item_id)
        cand_key = cand_eff.unique_passive_key if cand_eff is not None else ""
        shares_dead_unique = bool(cand_key and cand_key in current_unique_keys)
        if shares_dead_unique and filter_shared_uniques:
            continue
        new_build = current_ids + (item_id,)
        try:
            scored = compute_dps(
                snapshot,
                champion_id=champion_id,
                level=level,
                item_ids=new_build,
                mode=mode,
                target_armor=target_armor,
                target_mr=target_mr,
                target_max_hp=target_max_hp,
                target_bonus_hp=target_bonus_hp,
                phase=phase,
                augments=augments,
            )
        except (KeyError, ValueError):
            continue
        gold = int((rec.get("gold") or {}).get("total", 0) or 0)
        delta = scored.weighted_dps - baseline.weighted_dps
        # Efficiency in DPS per 1000 gold so the column stays in a readable range.
        # Negative or zero deltas zero-out - they're not "efficient", they're regressions.
        eff = (delta / (gold / 1000.0)) if (gold > 0 and delta > 0) else 0.0
        ranked.append(
            RankedItem(
                item_id=item_id,
                item_name=str(rec.get("name", item_id)),
                gold=gold,
                delta_dps=delta,
                new_dps=scored.weighted_dps,
                dps_per_1k_gold=eff,
                is_terminal=_is_terminal(rec),
                tags=tuple(rec.get("tags") or ()),
                shares_dead_unique=shares_dead_unique,
                dead_unique_key=cand_key if shares_dead_unique else "",
                unique_passive_key=cand_key,
            )
        )

    if sort_by == "efficiency":
        ranked.sort(key=lambda r: (r.dps_per_1k_gold, r.delta_dps), reverse=True)
    else:
        ranked.sort(key=lambda r: (r.delta_dps, r.dps_per_1k_gold), reverse=True)

    if top_n is not None and top_n > 0:
        ranked = ranked[:top_n]

    notes: list[str] = []
    if mode in MODE_MAP_ID:
        notes.append(f"mode={mode} → maps id {MODE_MAP_ID[mode]}")
    else:
        notes.append(f"mode={mode} not in MODE_MAP_ID - no per-mode item filter applied")
    if stripped_trinkets:
        notes.append(
            f"mode=ARENA - stripped trinket(s) {list(stripped_trinkets)} from current_item_ids"
        )
    if include_components:
        notes.append("include_components=True - non-terminal items in the ranking")
    if budget is not None:
        notes.append(f"budget={budget}g - items over budget filtered")
    if baseline.mode_multiplier == 0.0:
        notes.append(
            "baseline mode_multiplier=0 - all DPS deltas will be 0 (e.g. Yunara in ARAM)"
        )

    return RankResult(
        champion_id=baseline.champion_id,
        champion_name=baseline.champion_name,
        level=level,
        mode=mode,
        current_item_ids=current_ids,
        baseline_dps=baseline.weighted_dps,
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
