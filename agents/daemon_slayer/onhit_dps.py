"""Slice B (2026-07-16) - on-hit AP combined-DPS scorer.

Composes compute_ability_dps().total_ability_dps (Q/W/E/R) with
compute_dps().weighted_dps (autos + on-hit item procs, incl. Nashor's
Icathian Bite) into ONE combined-DPS score by PLAIN SUM. The two are
non-overlapping by design: the passive (P) on-hit lives in compute_dps, the
four active spells live in compute_ability_dps. Neither half alone surfaces
Nashor's. Sibling of hybrid.py (which composes dps + EHP with alpha/beta) -
here no weights are needed.

THE TWO HALVES ARE NOT IN THE SAME DPS UNITS (RM-98, corrected 2026-07-24).
This docstring previously asserted that they were, and that the sum was
therefore "the champion's true total sustained DPS". Both claims are false.
``weighted_dps`` is a combat-window per-second figure; every spell row inside
``total_ability_dps`` is multiplied by a WHOLE-GAME cast rate
(``data/daemon_slayer/spell_cast_rates.json`` - casts divided by
``matches.game_duration_s``, ``ability_dps.py:1261``), so the ability half is
systematically under-weighted against the auto half.
``docs/specs/SPEC_rm98_cast_rate_time_base.md:76-83`` adjudicates this and
names THIS line as the shipped, DEFAULT-ON instance of the defect; the
characteristic per-spell distortion is ~7x (SPEC:100-107).

Neither denominator replacement RM-39 named is available at the required
fidelity (SPEC:116-133) - do not re-attempt either. The adjudicated repair is
the cast-propensity prior in ``cast_propensity.py``; it is wired into
``hybrid.py`` behind DEFAULT-OFF ``apply_cast_rate_propensity_prior`` and is
deliberately NOT wired here yet (SPEC:109-114 - narrow first, widen on test
evidence). This scorer's arithmetic is UNCHANGED; only the claim about it is
corrected.

ASCII only - use " - " for a clause break (repo hard rule).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

from .ability_dps import compute_ability_dps
from .data_loader import DataSnapshot
from .dps import compute_dps
from .effects import ITEM_EFFECTS
from .hybrid import _damage_axis
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
    apply_passive_damage: bool = False,
) -> OnhitDpsResult:
    """Combined ability + on-hit-auto DPS for the resolved build (plain sum).

    ``compute_ability_dps`` has no ``phase``, ``apply_mode_modifiers``, or
    ``apply_passive_damage`` parameter (it is spell-keyed, not rotation-
    phase-keyed, has no ARAM dmg_dealt hook of its own, and skips the P slot)
    - those kwargs are forwarded ONLY to ``compute_dps``. ``apply_passive_damage``
    defaults False here (preserves the exact-sum invariant test, which relies
    on the default), routing an allowlisted kit on-hit passive (e.g. Gwen's A
    Thousand Cuts) onto the AUTO-ATTACK cadence when True - see
    ``_AA_ROUTED_ON_HIT_KEYS`` / ``dps.py``'s cadence-routing seam. Both
    composed calls share the same snapshot / champion / level / item_ids /
    mode / target_* / augments so the two halves describe the identical
    resolved build.
    """
    level = clamp_level(level)
    item_list = tuple(str(i) for i in (item_ids or ()))

    auto = compute_dps(
        snapshot, champion_id=champion_id, level=level, item_ids=item_list,
        mode=mode, target_armor=target_armor, target_mr=target_mr,
        target_max_hp=target_max_hp, target_bonus_hp=target_bonus_hp,
        phase=phase, augments=augments, apply_mode_modifiers=apply_mode_modifiers,
        apply_passive_damage=apply_passive_damage,
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


# --- AP-axis check for the coherence gate (Slice B Task 5) -----------------
#
# Starts from hybrid.py's _damage_axis (DDragon info.attack/info.magic "class
# flavor" split - magic > attack -> "ap"). Verified live against the 16.14.1
# snapshot: that split misclassifies 2 of Slice B's 3 on-hit-AP champions as
# AD-axis (Gwen 7atk/5mag, KogMaw 8atk/5mag) even though Tasks 3-4 registered
# their on-hit passive as AP-scaling magic damage - the split reflects base
# stat GROWTH, not build reality, and was authored/validated for the bruiser
# scorer's AD-vs-AP bruiser split (Darius vs Mordekaiser), never for on-hit-AP
# hybrids. Tuning ap_ad_coherence cannot fix this (it is not a strength
# problem): axis stays "ad" at any strength, so the gate never fires.
#
# Fallback: a champion whose AA-routed on-hit passive (_AA_ROUTED_ON_HIT_KEYS
# / _passive_damage_overrides.py) carries a BILINEAR ap-per-100 term (the item
# 248 "X% (+ Y% per 100 AP) of target max HP" schema - a proportional,
# itemization-relevant AP scaling, not a minor flat-ratio kicker) is AP-axis
# by construction of that registry, regardless of the coarse stat split. This
# cleanly separates Gwen/KogMaw (bilinear ap term, zero flat ap_pct) from
# Warwick/Orianna (flat ap_pct kicker only - 10.0/15.0 - empty bilinear_terms;
# the pre-Slice-B v1 entries, not on-hit-AP champions) - no numeric threshold,
# no champion-name list. Kayle does not need the fallback: her flat 20% ap_pct
# E ratio already resolves "ap" via _damage_axis (7 magic > 6 attack).
def _onhit_ap_axis(snapshot: DataSnapshot, champion_id: str) -> str:
    """Return ``"ap"`` when the champion is AP-axis for on-hit-AP purposes."""
    if _damage_axis(snapshot, champion_id) == "ap":
        return "ap"
    from ._passive_damage_overrides import aa_routed_on_hit_entry

    routed = aa_routed_on_hit_entry(str(champion_id))
    if routed is not None:
        _key, entry = routed
        if entry.damage_type == "MAGIC" and any(
            term[1] == "ap" for term in entry.bilinear_terms
        ):
            return "ap"
    return "ad"


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
    apply_passive_damage: bool = True,
    ap_ad_coherence: float = 0.0,
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

    ``apply_passive_damage=True`` (default - opposite of ``compute_onhit_dps``'s
    own False default) - this IS the on-hit scorer, so an allowlisted kit
    on-hit passive (e.g. Gwen's A Thousand Cuts, ``_AA_ROUTED_ON_HIT_KEYS``)
    should be credited by default in both the baseline and every candidate
    score. Threaded unchanged into every ``compute_onhit_dps`` call below.

    ``ap_ad_coherence`` (default 0.0 - OFF, byte-identical sort) is an
    AP/AD axis-coherence penalty. Pure-AD items (Blade of the Ruined King,
    Trinity Force, Kraken Slayer - no ``SpellDamage`` tag) add raw AD the
    marginal ranker cannot see is wasted on an AP-axis champion's kit
    scaling, so they swamp the AP on-hit field (Nashor's Tooth) even after
    Tasks 3-4 credit the kit on-hit passive. For an AP-axis champion
    (``_onhit_ap_axis`` - hybrid.py's ``_damage_axis`` DDragon attack/magic
    split, falling back to the champion's own AA-routed on-hit passive
    registry when that split says "ad"; see the comment above
    ``_onhit_ap_axis`` for why the fallback exists), a pure-AD candidate's
    SORT score is scaled down by ``(1 - ap_ad_coherence)``; at
    ``ap_ad_coherence >= 1.0`` a positive sort delta is zeroed, effectively
    dropping it to the bottom of the ranking. Only ever LOWERS a pure-AD
    candidate's rank - a non-positive delta is left untouched (scaling a
    negative number toward zero would raise, not lower, its rank).
    Non-AP-axis (AD) champions are unaffected at any strength - the axis
    lookup itself only runs when ``ap_ad_coherence > 0.0``, so 0.0 has zero
    effect on the axis path (byte-identical sort). The raw ``delta_dps`` /
    ``dps_per_1k_gold`` stored on each returned row are never penalized
    (transparency) - only the in-function sort key is.
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
        apply_passive_damage=apply_passive_damage,
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
                apply_passive_damage=apply_passive_damage,
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

    # AP/AD axis-coherence gate (Slice B Task 5). Only touches the SORT key -
    # each row's own delta_dps / dps_per_1k_gold fields stay raw (transparency).
    # Axis is looked up ONLY when the gate is active so ap_ad_coherence=0.0
    # is provably byte-identical to the pre-Task-5 sort (no axis-lookup effect).
    axis: Optional[str] = None
    if ap_ad_coherence > 0.0:
        axis = _onhit_ap_axis(snapshot, champion_id)

    def _coherence_key(value: float, tags: tuple[str, ...]) -> float:
        """Sort-only view of ``value`` - never mutates the row itself.

        Only ever lowers a pure-AD candidate's rank for an AP-axis champion:
        a non-positive value is returned unchanged (scaling a negative
        number toward zero would raise, not lower, its rank).
        """
        if axis != "ap" or "SpellDamage" in tags or value <= 0.0:
            return value
        if ap_ad_coherence >= 1.0:
            return 0.0
        return value * (1.0 - ap_ad_coherence)

    if sort_by == "efficiency":
        ranked.sort(
            key=lambda r: (
                _coherence_key(r.dps_per_1k_gold, r.tags),
                _coherence_key(r.delta_dps, r.tags),
            ),
            reverse=True,
        )
    else:
        ranked.sort(
            key=lambda r: (
                _coherence_key(r.delta_dps, r.tags),
                _coherence_key(r.dps_per_1k_gold, r.tags),
            ),
            reverse=True,
        )

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
