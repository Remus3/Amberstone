"""Phase 1 (s174, 2026-05-12) - Tank EHP scorer.

Sibling of ``dps.py``. ``compute_ehp()`` returns the caster's Effective HP
under a given enemy damage profile; ``rank_items_by_ehp()`` scores every
purchasable mode-legal item by how much EHP it adds (mirroring ``rank.py``
shape).

EHP = HP / damage_taken_factor. For physical damage,
``damage_taken_factor = armor_factor(armor) = 100/(100+armor)``
(or the inverted form when armor is negative). For magical, same formula
applied to MR. For true, ``damage_taken_factor = 1.0``. ARAM's
``aramDamageTaken`` modifier multiplies every damage_taken_factor - a
champion with ``aramDamageTaken=0.95`` takes 5% less damage so effective
HP scales by ``1/0.95`` for ALL damage types (including true).

``blended_ehp`` weights physical/magical/true components by caller-supplied
enemy damage shares. ``enemy_ad_share + enemy_ap_share <= 1.0``; remainder
is true-damage share.

Phase 1 deliberate omissions (deferred to Phase 1.5):
* Shield throughput (Sterak's lifeline, Doran's Shield, Bloodthirster) -
  needs uptime modeling
* Healing throughput (lifesteal, Spirit Visage amp) - fits Phase 6
* Caster-side enemy pen/reduction (Black Cleaver shred ON the tank,
  Void Staff %MR pen ON the tank) - needs enemy build plumbing

Bonus HP amps (Jak'Sho's Voidborne Resilience +6% bonus resists fully
stacked, Cinderhulk +15% bonus HP) flow through ``build_champion`` already
via the existing stat schema - no new field needed; EHP picks them up
automatically because ``stats["hp"]/["armor"]/["mr"]`` reflect the amp.

ENGINE 1.25.0 (2026-05-21) - aram_tenacity_mult consumer wired (closes the
BACKLOG "Future EHP enemy-CC model" carry from item 113). 17 ARAM champs
carry a non-1.0 ``aramTenacity`` multiplier (engine.py exposes it as
``scaled["aram_tenacity_mult"]`` since 1.19.0). EhpResult now surfaces
the value + ``effective_cc_duration(base_cc_s, tenacity_mult)`` helper
returns the post-tenacity CC duration (tenacity_mult < 1.0 -> shorter
CC; tenacity_mult > 1.0 -> longer CC). The helper is the seam any future
fight-sim or coach-prompt consumer reads; EHP's primary blended_ehp
math is unchanged (CC-duration vs HP-pool is a fundamentally different
axis - the consumer must pair tenacity_mult with their own CC
assumption).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

from .data_loader import DataSnapshot
from .effects import ITEM_EFFECTS
from .engine import build_champion
from .rank import (
    DEFAULT_SLOT_COUNT,
    DEFAULT_TOP_N,
    SORT_KEYS,
    _filter_candidates,
    _is_terminal,
    strip_arena_trinkets,
)
from .stats import clamp_level


def _armor_factor(resist: float) -> float:
    """League's resist → damage-taken multiplier. Mirrors ``dps._armor_factor``.

    Positive resist: ``100 / (100 + resist)``.
    Negative resist (shred): ``2 - 100/(100 - resist)``. Inlined here rather
    than imported from dps.py so the EHP scorer doesn't depend on the DPS
    layer's private helpers.
    """
    if resist >= 0:
        return 100.0 / (100.0 + resist)
    return 2.0 - 100.0 / (100.0 - resist)


def effective_cc_duration(base_cc_s: float, tenacity_mult: float) -> float:
    """Apply ARAM tenacity multiplier to a base CC duration.

    ENGINE 1.25.0 (2026-05-21): the seam any consumer (coach prompt
    builder, future fight-sim, EHP-vs-CC blended model) reads to convert
    a base CC duration into the post-tenacity value. ``tenacity_mult``
    comes from ``EhpResult.aram_tenacity_mult`` (or directly from
    ``resolved.stats.get("aram_tenacity_mult", 1.0)``).

    Formula: ``eff_cc_s = base_cc_s * tenacity_mult``.
      * ``tenacity_mult == 1.0`` -> identity (no ARAM tenacity modifier).
      * ``tenacity_mult < 1.0`` -> shorter CC (most ARAM assassins: 0.80
        means 1.0s root becomes 0.80s).
      * ``tenacity_mult > 1.0`` -> longer CC (rare: ARAM imposes longer
        CC on a few champs as a balance lever).

    Negative or zero base_cc_s returns 0.0. Tenacity floored at 0.0 (a
    pathological future value cannot make CC negative).
    """
    if base_cc_s <= 0:
        return 0.0
    return float(base_cc_s) * max(0.0, float(tenacity_mult))


def _aram_damage_taken(snapshot: DataSnapshot, champion_id: str, mode: str) -> float:
    """Pull ``aramDamageTaken`` from the snapshot. 1.0 outside ARAM.

    ARAM applies a per-champion modifier to ALL damage taken (physical,
    magical, true). Snapshot stores it under
    ``champion.lolmath.aram_modifiers.aramDamageTaken`` - extracted by
    ``tools/daemon_slayer_extract.py`` from lolmath's data chunk.
    """
    if mode != "ARAM":
        return 1.0
    champ = snapshot.champion(champion_id)
    aram = ((champ.get("lolmath") or {}).get("aram_modifiers") or {})
    return float(aram.get("aramDamageTaken", 1.0))


@dataclass(frozen=True)
class EhpResult:
    champion_id: str
    champion_name: str
    level: int
    item_ids: tuple[str, ...]
    mode: str
    hp: float
    armor: float
    mr: float
    physical_ehp: float          # HP / (armor_factor(armor) * mode_mult)
    magical_ehp: float           # HP / (armor_factor(mr) * mode_mult)
    true_ehp: float              # HP / mode_mult
    blended_ehp: float           # weighted by enemy AD/AP/true shares
    enemy_ad_share: float
    enemy_ap_share: float
    enemy_true_share: float      # derived: 1 - ad_share - ap_share
    mode_multiplier: float       # aramDamageTaken; 1.0 outside ARAM
    # ENGINE 1.25.0 (2026-05-21): ARAM tenacity multiplier on incoming CC
    # duration. 17 ARAM champs carry non-1.0 values (assassin-shaped +20%
    # / +10% lengthening, plus a handful of shorteners). 1.0 outside ARAM
    # (engine.py only writes the scaled["aram_tenacity_mult"] key when
    # mode == "ARAM" via _apply_mode_modifiers). The blended_ehp math
    # above does NOT consume this value - CC duration vs HP pool is a
    # different axis; downstream consumers pair this with their own base
    # CC assumption via the module-level ``effective_cc_duration`` helper.
    aram_tenacity_mult: float = 1.0
    stats: dict[str, float] = field(default_factory=dict)
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "champion_id": self.champion_id,
            "champion_name": self.champion_name,
            "level": self.level,
            "item_ids": list(self.item_ids),
            "mode": self.mode,
            "hp": self.hp,
            "armor": self.armor,
            "mr": self.mr,
            "physical_ehp": self.physical_ehp,
            "magical_ehp": self.magical_ehp,
            "true_ehp": self.true_ehp,
            "blended_ehp": self.blended_ehp,
            "enemy_ad_share": self.enemy_ad_share,
            "enemy_ap_share": self.enemy_ap_share,
            "enemy_true_share": self.enemy_true_share,
            "mode_multiplier": self.mode_multiplier,
            "aram_tenacity_mult": self.aram_tenacity_mult,
            "stats": dict(self.stats),
            "notes": list(self.notes),
        }

    def format_table(self) -> str:
        head = (
            f"{self.champion_name} ({self.champion_id}) - lvl {self.level} "
            f"- mode {self.mode}"
        )
        rows = [head, "-" * len(head)]
        if self.item_ids:
            rows.append(f"items: {', '.join(self.item_ids)}")
        else:
            rows.append("items: (none)")
        rows.append(
            f"caster: hp={self.hp:.0f}  armor={self.armor:.1f}  mr={self.mr:.1f}"
        )
        rows.append(
            f"enemy mix: AD={self.enemy_ad_share * 100:.0f}%  "
            f"AP={self.enemy_ap_share * 100:.0f}%  "
            f"true={self.enemy_true_share * 100:.0f}%"
        )
        rows.append("")
        rows.append(f"  blended_ehp    {self.blended_ehp:.0f}")
        rows.append(f"  physical_ehp   {self.physical_ehp:.0f}")
        rows.append(f"  magical_ehp    {self.magical_ehp:.0f}")
        rows.append(f"  true_ehp       {self.true_ehp:.0f}")
        if self.mode_multiplier != 1.0:
            rows.append(
                f"  mode_mult      {self.mode_multiplier:.3f}  (aramDamageTaken)"
            )
        if self.aram_tenacity_mult != 1.0:
            rows.append(
                f"  tenacity_mult  {self.aram_tenacity_mult:.3f}  (aramTenacity x CC duration)"
            )
        if self.notes:
            rows.append("")
            for n in self.notes:
                rows.append(f"  note: {n}")
        return "\n".join(rows)


def compute_ehp(
    snapshot: DataSnapshot,
    champion_id: str,
    level: int,
    item_ids: Optional[Iterable[str | int]] = None,
    mode: str = "SR",
    enemy_ad_share: float = 0.5,
    enemy_ap_share: float = 0.5,
    augments: Optional[Iterable] = None,
) -> EhpResult:
    """Compute Effective HP for the resolved build under an enemy damage profile.

    ``enemy_ad_share`` and ``enemy_ap_share`` are floats in ``[0.0, 1.0]``
    summing to ≤ 1.0; the remainder is true-damage share. Defaults to
    50/50 AD/AP - a reasonable "no info" baseline. Operator-facing
    callers (``core/defensive_picks.py``) derive these shares from the
    threat profile.

    Caster armor/MR come straight from the resolved stat block; no
    enemy-pen modeling in Phase 1.
    """
    level = clamp_level(level)
    if not (0.0 <= enemy_ad_share <= 1.0):
        raise ValueError(
            f"enemy_ad_share must be in [0,1], got {enemy_ad_share}"
        )
    if not (0.0 <= enemy_ap_share <= 1.0):
        raise ValueError(
            f"enemy_ap_share must be in [0,1], got {enemy_ap_share}"
        )
    total_share = enemy_ad_share + enemy_ap_share
    if total_share > 1.0001:  # 1e-4 tolerance for float arithmetic
        raise ValueError(
            f"enemy_ad_share + enemy_ap_share must be ≤ 1.0, got {total_share}"
        )

    resolved = build_champion(
        snapshot, champion_id, level, item_ids=item_ids, mode=mode,
        augments=augments,
    )
    stats = resolved.stats
    hp = float(stats.get("hp", 0.0))
    armor = float(stats.get("armor", 0.0))
    mr = float(stats.get("mr", 0.0))

    mode_mult = _aram_damage_taken(snapshot, resolved.champion_id, mode)
    # Division-safety: never let a future data corruption pin
    # aramDamageTaken to 0 and explode the EHP math.
    safe_mult = mode_mult if mode_mult > 0 else 1.0
    # ENGINE 1.25.0 (2026-05-21): ARAM tenacity multiplier exposed via
    # the resolved stats dict (engine._apply_mode_modifiers gates on
    # mode == "ARAM"; SR + every non-ARAM mode get 1.0 by default).
    # Forwarded to EhpResult so consumers can call
    # ``effective_cc_duration(base_s, tenacity_mult)``. Blended EHP math
    # is unchanged - CC duration is a separate axis from HP pool.
    aram_tenacity_mult = float(resolved.stats.get("aram_tenacity_mult", 1.0))

    physical_ehp = hp / (_armor_factor(armor) * safe_mult)
    magical_ehp = hp / (_armor_factor(mr) * safe_mult)
    true_ehp = hp / safe_mult

    enemy_true_share = max(0.0, 1.0 - enemy_ad_share - enemy_ap_share)
    blended_ehp = (
        physical_ehp * enemy_ad_share
        + magical_ehp * enemy_ap_share
        + true_ehp * enemy_true_share
    )

    notes = list(resolved.notes)
    if mode == "ARAM" and mode_mult != 1.0:
        notes.append(
            f"ARAM aramDamageTaken={mode_mult:.3f} on all incoming damage "
            f"(EHP scaled by x{1.0 / safe_mult:.3f})"
        )
    if mode == "ARAM" and aram_tenacity_mult != 1.0:
        notes.append(
            f"ARAM aramTenacity={aram_tenacity_mult:.3f}x effective CC duration "
            f"(consumers via effective_cc_duration helper)"
        )

    return EhpResult(
        champion_id=resolved.champion_id,
        champion_name=resolved.champion_name,
        level=level,
        item_ids=resolved.item_ids,
        mode=mode,
        hp=hp,
        armor=armor,
        mr=mr,
        physical_ehp=physical_ehp,
        magical_ehp=magical_ehp,
        true_ehp=true_ehp,
        blended_ehp=blended_ehp,
        enemy_ad_share=enemy_ad_share,
        enemy_ap_share=enemy_ap_share,
        enemy_true_share=enemy_true_share,
        mode_multiplier=mode_mult,
        aram_tenacity_mult=aram_tenacity_mult,
        stats=dict(stats),
        notes=tuple(notes),
    )


# ----------------------------------------------------------------- ranker


@dataclass(frozen=True)
class EhpRankedItem:
    item_id: str
    item_name: str
    gold: int
    delta_ehp: float             # blended_ehp with item - baseline blended_ehp
    new_ehp: float
    ehp_per_1k_gold: float       # delta_ehp / (gold/1000); 0 when delta<=0
    is_terminal: bool
    tags: tuple[str, ...]
    # Phase 0 dead-unique filter mirror - see ``rank.RankedItem`` for the
    # full rationale. Same flag, same dedup semantics: a candidate whose
    # unique_passive_key collides with an item already in current_item_ids
    # is filtered by default (proc/pen would be zeroed by collect_effects).
    # For EHP this matters less than for DPS (most defensive items don't
    # share unique_passive_keys), but the lifeline family (Sterak's, Maw,
    # Shieldbow, Verdant Barrier, Hexdrinker, Protoplasm Harness, Seraph's,
    # Lifeline component) is a real conflict source.
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
            "delta_ehp": self.delta_ehp,
            "new_ehp": self.new_ehp,
            "ehp_per_1k_gold": self.ehp_per_1k_gold,
            "is_terminal": self.is_terminal,
            "tags": list(self.tags),
            "shares_dead_unique": self.shares_dead_unique,
            "dead_unique_key": self.dead_unique_key,
            "unique_passive_key": self.unique_passive_key,
        }


@dataclass(frozen=True)
class EhpRankResult:
    champion_id: str
    champion_name: str
    level: int
    mode: str
    current_item_ids: tuple[str, ...]
    baseline_ehp: float
    enemy_ad_share: float
    enemy_ap_share: float
    enemy_true_share: float
    budget: Optional[int]
    slot_count: int
    sort_by: str
    candidates_considered: int
    candidates_evaluated: int
    ranked: tuple[EhpRankedItem, ...]
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "champion_id": self.champion_id,
            "champion_name": self.champion_name,
            "level": self.level,
            "mode": self.mode,
            "current_item_ids": list(self.current_item_ids),
            "baseline_ehp": self.baseline_ehp,
            "enemy_ad_share": self.enemy_ad_share,
            "enemy_ap_share": self.enemy_ap_share,
            "enemy_true_share": self.enemy_true_share,
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
            f"- mode {self.mode}  [TANK]"
        )
        rows = [head, "-" * len(head)]
        if self.current_item_ids:
            rows.append(f"current items: {', '.join(self.current_item_ids)}")
        else:
            rows.append("current items: (none)")
        rows.append(
            f"enemy mix: AD={self.enemy_ad_share * 100:.0f}%  "
            f"AP={self.enemy_ap_share * 100:.0f}%  "
            f"true={self.enemy_true_share * 100:.0f}%"
        )
        budget_label = "unlimited" if self.budget is None else f"{self.budget}"
        rows.append(
            f"budget: {budget_label}  slots: {len(self.current_item_ids)}/{self.slot_count}"
            f"  sort: {self.sort_by}"
        )
        rows.append(
            f"baseline_ehp: {self.baseline_ehp:.0f}   "
            f"considered/evaluated: {self.candidates_considered}/{self.candidates_evaluated}"
        )
        rows.append("")
        rows.append(
            f"  {'#':>3}  {'id':>6}  {'name':<28}  "
            f"{'gold':>5}  {'+ehp':>7}  {'new':>7}  {'ehp/1k':>7}"
        )
        rows.append("  " + "-" * 78)
        for i, r in enumerate(self.ranked, 1):
            rows.append(
                f"  {i:>3}  {r.item_id:>6}  {r.item_name[:28]:<28}  "
                f"{r.gold:>5}  {r.delta_ehp:>7.1f}  {r.new_ehp:>7.0f}  "
                f"{r.ehp_per_1k_gold:>7.1f}"
            )
        if self.notes:
            rows.append("")
            for n in self.notes:
                rows.append(f"  note: {n}")
        return "\n".join(rows)


def rank_items_by_ehp(
    snapshot: DataSnapshot,
    champion_id: str,
    level: int,
    current_item_ids: Optional[Iterable[str | int]] = None,
    mode: str = "SR",
    enemy_ad_share: float = 0.5,
    enemy_ap_share: float = 0.5,
    budget: Optional[int] = None,
    slot_count: int = DEFAULT_SLOT_COUNT,
    top_n: int = DEFAULT_TOP_N,
    include_components: bool = False,
    only_item_ids: Optional[Iterable[str | int]] = None,
    sort_by: str = "delta",
    augments: Optional[Iterable] = None,
    filter_shared_uniques: bool = True,
) -> EhpRankResult:
    """Rank items by blended-EHP contribution when added to ``current_item_ids``.

    Mirror of ``rank.rank_items`` for the EHP scorer. Same candidate
    filtering pipeline (purchasable + mode-legal + optional whitelist +
    budget + terminal-only) - only the scoring function differs.

    Sort keys:
      * ``delta``       - absolute EHP gained (default)
      * ``efficiency``  - EHP gained per 1000 gold spent

    ``only_item_ids`` is the integration point for the s171
    ``core/defensive_picks.py`` curated catalog (Option B from the s174
    design conversation): the catalog is passed as a whitelist so the
    math-driven ranking happens within an operator-vetted pool.
    """
    if sort_by not in SORT_KEYS:
        raise ValueError(f"sort_by must be one of {SORT_KEYS}, got {sort_by!r}")
    level = clamp_level(level)

    current_ids: tuple[str, ...] = tuple(str(i) for i in (current_item_ids or ()))
    current_ids, stripped_trinkets = strip_arena_trinkets(current_ids, mode)
    current_set = set(current_ids)
    # Collect unique_passive_keys already locked in. Same logic as
    # ``rank.rank_items`` - candidates colliding here are filtered by default.
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

    baseline = compute_ehp(
        snapshot,
        champion_id=champion_id,
        level=level,
        item_ids=current_ids,
        mode=mode,
        enemy_ad_share=enemy_ad_share,
        enemy_ap_share=enemy_ap_share,
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

    ranked: list[EhpRankedItem] = []
    for item_id, rec in candidates:
        cand_eff = ITEM_EFFECTS.get(item_id)
        cand_key = cand_eff.unique_passive_key if cand_eff is not None else ""
        shares_dead_unique = bool(cand_key and cand_key in current_unique_keys)
        if shares_dead_unique and filter_shared_uniques:
            continue
        new_build = current_ids + (item_id,)
        try:
            scored = compute_ehp(
                snapshot,
                champion_id=champion_id,
                level=level,
                item_ids=new_build,
                mode=mode,
                enemy_ad_share=enemy_ad_share,
                enemy_ap_share=enemy_ap_share,
                augments=augments,
            )
        except (KeyError, ValueError):
            continue
        gold = int((rec.get("gold") or {}).get("total", 0) or 0)
        delta = scored.blended_ehp - baseline.blended_ehp
        # Efficiency in EHP per 1000 gold so the column stays readable.
        # Negative or zero deltas zero-out - they're regressions, not efficient.
        eff = (delta / (gold / 1000.0)) if (gold > 0 and delta > 0) else 0.0
        ranked.append(EhpRankedItem(
            item_id=item_id,
            item_name=str(rec.get("name", item_id)),
            gold=gold,
            delta_ehp=delta,
            new_ehp=scored.blended_ehp,
            ehp_per_1k_gold=eff,
            is_terminal=_is_terminal(rec),
            tags=tuple(rec.get("tags") or ()),
            shares_dead_unique=shares_dead_unique,
            dead_unique_key=cand_key if shares_dead_unique else "",
            unique_passive_key=cand_key,
        ))

    if sort_by == "efficiency":
        ranked.sort(key=lambda r: (r.ehp_per_1k_gold, r.delta_ehp), reverse=True)
    else:
        ranked.sort(key=lambda r: (r.delta_ehp, r.ehp_per_1k_gold), reverse=True)

    if top_n is not None and top_n > 0:
        ranked = ranked[:top_n]

    notes: list[str] = []
    notes.append(
        f"enemy mix: AD {enemy_ad_share * 100:.0f}% / "
        f"AP {enemy_ap_share * 100:.0f}% / "
        f"true {baseline.enemy_true_share * 100:.0f}%"
    )
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
            f"ARAM aramDamageTaken={baseline.mode_multiplier:.3f} "
            f"folded into all EHP values"
        )

    return EhpRankResult(
        champion_id=baseline.champion_id,
        champion_name=baseline.champion_name,
        level=level,
        mode=mode,
        current_item_ids=current_ids,
        baseline_ehp=baseline.blended_ehp,
        enemy_ad_share=enemy_ad_share,
        enemy_ap_share=enemy_ap_share,
        enemy_true_share=baseline.enemy_true_share,
        budget=budget,
        slot_count=slot_count,
        sort_by=sort_by,
        candidates_considered=len(snapshot.items),
        candidates_evaluated=len(candidates),
        ranked=tuple(ranked),
        notes=tuple(notes),
    )
