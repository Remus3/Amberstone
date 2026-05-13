"""Phase 6 (s181, 2026-05-13) — Enchanter healing throughput scorer.

Sibling of ``dps.py`` / ``ehp.py`` / ``ability_dps.py`` / ``burst.py``.
``compute_hps()`` returns the caster's total healing + shielding + ally-
buff throughput per second for a given build under a "mid-game team-fight"
ally model. ``rank_items_by_hps()`` scores every purchasable mode-legal
item by how much total throughput it adds (same candidate-filtering
pipeline as the DPS / EHP / hybrid / ability / burst scorers).

Phase 6 is the lowest-fidelity tier in the archetype expansion plan — by
design. The DS engine has zero ally-state plumbing (no positions, no
current HP, no buff-uptime tracking). The "average teammate" model is:

* 4 allies present in team-fight radius
* AoE actives hit 3 allies on average (operator-overridable)
* Single-target heals/shields hit 1 ally (the bonded ally for Knight's
  Vow, the lowest-HP ally for Mikael)
* Proc rate for actives = 1/CD (Redemption 120s, Mikael 120s, Locket 90s)
* Proc rate for passives = curated per-item (Helia Soul Siphon ≈ 0.4/s;
  Moonstone chain rides whatever the caster heals/shields)

Formulas live in ``data/daemon_slayer/<patch>/enchanter_items.json`` — a
hand-curated registry of 9 enchanter items. The engine reads it via
:class:`EnchanterFormulasSnapshot` (singleton, mirroring ``abilities.py``).

The total throughput score is::

    direct_throughput = sum_over_items(
        (heal_per_proc + shield_per_proc) * targets * procs_per_second
    )
    amp_multiplier = product(1 + heal_shield_amp_pct)
    buff_credit = sum_over_items(ally_buff_credit_per_second)
    total_throughput = direct_throughput * amp_multiplier + buff_credit

``heal_per_proc`` scales linearly with caster level and additively with
caster AP. ``ally_buff_credit`` is a calibrated, dimensionless number
(10 ≈ 10 HPS-equivalent) to make Ardent / Staff of Flowing Water / Knight's
Vow rankable next to direct-heal items. Phase 6.5 may overhaul this with
real ally-state plumbing, but it's not blocking.

Phase 6 deliberate omissions (Phase 6.5+):
* Real ally-state plumbing (positions, HP, ability casts) — by design
* Champion-spell healing throughput (Soraka W, Lulu E shield, Janna E
  shield) — only ITEM throughput is scored; champion abilities are out
  of scope for v1
* Heal/shield-power scaling on champion abilities — the amp_multiplier
  applies only to item throughput here (a Soraka with Redemption sees
  her R amp via the in-game system, not this scorer)
* ARAM aramShieldsHealing modifier — applied if present on the champion
  but not all enchanter champions have it; default mode_mult=1.0

Phase 6 ALSO models per-target multiplier overrides via
``targets_per_proc_override`` on the API, so callers can tune the
"average teammate" assumption per scenario (e.g. 2v2 Arena → 1 ally).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
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

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_ROOT = _REPO_ROOT / "data" / "daemon_slayer"


class EnchanterFormulasNotFound(FileNotFoundError):
    """Raised when the requested enchanter_items.json snapshot is missing."""


# ─── Curated formula loader ─────────────────────────────────────────────


@dataclass(frozen=True)
class EnchanterItemFormula:
    """Per-item curated healing/shielding/buff formula.

    Schema mirrors ``data/daemon_slayer/<patch>/enchanter_items.json``.
    """

    item_id: str
    name: str
    heal_per_proc_base: float
    heal_per_proc_per_level: float
    heal_per_proc_ap_scaling: float
    heal_procs_per_second: float
    heal_targets_per_proc: float
    shield_per_proc_base: float
    shield_per_proc_per_level: float
    shield_per_proc_ap_scaling: float
    shield_procs_per_second: float
    shield_targets_per_proc: float
    heal_shield_amp_pct: float
    ally_buff_credit_per_second: float
    notes: str

    @classmethod
    def from_dict(cls, item_id: str, d: dict) -> "EnchanterItemFormula":
        return cls(
            item_id=str(item_id),
            name=str(d.get("name", item_id)),
            heal_per_proc_base=float(d.get("heal_per_proc_base", 0.0)),
            heal_per_proc_per_level=float(d.get("heal_per_proc_per_level", 0.0)),
            heal_per_proc_ap_scaling=float(d.get("heal_per_proc_ap_scaling", 0.0)),
            heal_procs_per_second=float(d.get("heal_procs_per_second", 0.0)),
            heal_targets_per_proc=float(d.get("heal_targets_per_proc", 0.0)),
            shield_per_proc_base=float(d.get("shield_per_proc_base", 0.0)),
            shield_per_proc_per_level=float(d.get("shield_per_proc_per_level", 0.0)),
            shield_per_proc_ap_scaling=float(d.get("shield_per_proc_ap_scaling", 0.0)),
            shield_procs_per_second=float(d.get("shield_procs_per_second", 0.0)),
            shield_targets_per_proc=float(d.get("shield_targets_per_proc", 0.0)),
            heal_shield_amp_pct=float(d.get("heal_shield_amp_pct", 0.0)),
            ally_buff_credit_per_second=float(d.get("ally_buff_credit_per_second", 0.0)),
            notes=str(d.get("notes", "")),
        )

    def heal_per_proc_at(self, level: int, ap: float) -> float:
        """Compute the per-proc heal amount at given level + AP."""
        return (
            self.heal_per_proc_base
            + self.heal_per_proc_per_level * max(0, level - 1)
            + self.heal_per_proc_ap_scaling * max(0.0, ap)
        )

    def shield_per_proc_at(self, level: int, ap: float) -> float:
        """Compute the per-proc shield amount at given level + AP."""
        return (
            self.shield_per_proc_base
            + self.shield_per_proc_per_level * max(0, level - 1)
            + self.shield_per_proc_ap_scaling * max(0.0, ap)
        )


@dataclass(frozen=True)
class EnchanterFormulasSnapshot:
    """Versioned snapshot of the curated enchanter item formulas."""

    patch: str
    formulas: dict[str, EnchanterItemFormula]
    data_root: Path = field(repr=False, default=_DEFAULT_DATA_ROOT)

    @classmethod
    def load(
        cls,
        patch: str | None = None,
        data_root: Path | None = None,
    ) -> "EnchanterFormulasSnapshot":
        root = Path(data_root) if data_root else _DEFAULT_DATA_ROOT
        if patch is None:
            pointer = root / "current.txt"
            if not pointer.exists():
                raise EnchanterFormulasNotFound(f"Pointer file missing: {pointer}")
            patch = pointer.read_text(encoding="utf-8").strip()
            if not patch:
                raise EnchanterFormulasNotFound(f"Pointer file empty: {pointer}")

        path = root / patch / "enchanter_items.json"
        if not path.exists():
            raise EnchanterFormulasNotFound(
                f"Enchanter formulas snapshot missing: {path}"
            )
        doc = json.loads(path.read_text(encoding="utf-8"))
        items = doc.get("items") or {}
        formulas: dict[str, EnchanterItemFormula] = {}
        for iid, payload in items.items():
            if not isinstance(payload, dict):
                continue
            formulas[str(iid)] = EnchanterItemFormula.from_dict(str(iid), payload)
        return cls(patch=patch, formulas=formulas, data_root=root)

    def has_item(self, item_id: str) -> bool:
        return str(item_id) in self.formulas

    def get_formula(self, item_id: str) -> EnchanterItemFormula:
        rec = self.formulas.get(str(item_id))
        if rec is None:
            raise KeyError(
                f"No enchanter formula for item_id={item_id!r} "
                f"(snapshot {self.patch})"
            )
        return rec

    def item_ids(self) -> tuple[str, ...]:
        """Return all known enchanter item IDs, sorted."""
        return tuple(sorted(self.formulas.keys()))


_formulas_cache: EnchanterFormulasSnapshot | None = None


def load_default_formulas() -> EnchanterFormulasSnapshot:
    """Load the current-patch enchanter formulas, caching process-wide."""
    global _formulas_cache
    if _formulas_cache is None:
        _formulas_cache = EnchanterFormulasSnapshot.load()
    return _formulas_cache


def reset_formulas_cache() -> None:
    """Drop the cached snapshot. Test fixtures call this between patches."""
    global _formulas_cache
    _formulas_cache = None


# ─── ARAM modifier helper ───────────────────────────────────────────────


def _aram_healing_modifier(
    snapshot: DataSnapshot, champion_id: str, mode: str
) -> float:
    """Pull ``aramShieldsHealing`` from the snapshot. 1.0 outside ARAM.

    Not all champions have an ``aramShieldsHealing`` modifier (most don't).
    Returns 1.0 when missing — the multiplicative identity. Operator can
    override by setting ``mode_mult`` on the API call.
    """
    if mode != "ARAM":
        return 1.0
    champ = snapshot.champion(champion_id)
    aram = ((champ.get("lolmath") or {}).get("aram_modifiers") or {})
    return float(aram.get("aramShieldsHealing", aram.get("aramHealing", 1.0)))


# ─── Result types ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class HpsItemContribution:
    """Per-item healing/shielding/buff breakdown."""

    item_id: str
    item_name: str
    heal_per_proc: float           # post-level + AP scaling
    heal_procs_per_second: float
    heal_targets_per_proc: float
    healing_hps_raw: float         # heal_per_proc × procs × targets (pre-amp)
    shield_per_proc: float
    shield_procs_per_second: float
    shield_targets_per_proc: float
    shielding_hps_raw: float       # pre-amp
    heal_shield_amp_pct: float     # contribution to compound amp
    ally_buff_credit_per_second: float  # additive credit
    notes: str

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "item_name": self.item_name,
            "heal_per_proc": self.heal_per_proc,
            "heal_procs_per_second": self.heal_procs_per_second,
            "heal_targets_per_proc": self.heal_targets_per_proc,
            "healing_hps_raw": self.healing_hps_raw,
            "shield_per_proc": self.shield_per_proc,
            "shield_procs_per_second": self.shield_procs_per_second,
            "shield_targets_per_proc": self.shield_targets_per_proc,
            "shielding_hps_raw": self.shielding_hps_raw,
            "heal_shield_amp_pct": self.heal_shield_amp_pct,
            "ally_buff_credit_per_second": self.ally_buff_credit_per_second,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class HpsResult:
    """Total healing/shielding throughput for the resolved build."""

    champion_id: str
    champion_name: str
    level: int
    item_ids: tuple[str, ...]
    mode: str
    ap: float
    # Aggregate components (pre-amp, summed across items):
    healing_hps_raw: float         # sum of per-item heal × proc × targets
    shielding_hps_raw: float       # sum of per-item shield × proc × targets
    # Multipliers:
    amp_multiplier: float          # product(1 + heal_shield_amp_pct)
    mode_multiplier: float         # aramShieldsHealing; 1.0 outside ARAM
    # Final score components:
    healing_hps: float             # healing_hps_raw × amp × mode_mult
    shielding_hps: float           # shielding_hps_raw × amp × mode_mult
    direct_throughput: float       # healing_hps + shielding_hps
    ally_buff_credit: float        # sum of ally_buff_credit_per_second
    total_throughput: float        # direct_throughput + ally_buff_credit
    # Per-item breakdown:
    items: tuple[HpsItemContribution, ...]
    notes: tuple[str, ...] = field(default_factory=tuple)
    targets_per_proc_override: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "champion_id": self.champion_id,
            "champion_name": self.champion_name,
            "level": self.level,
            "item_ids": list(self.item_ids),
            "mode": self.mode,
            "ap": self.ap,
            "healing_hps_raw": self.healing_hps_raw,
            "shielding_hps_raw": self.shielding_hps_raw,
            "amp_multiplier": self.amp_multiplier,
            "mode_multiplier": self.mode_multiplier,
            "healing_hps": self.healing_hps,
            "shielding_hps": self.shielding_hps,
            "direct_throughput": self.direct_throughput,
            "ally_buff_credit": self.ally_buff_credit,
            "total_throughput": self.total_throughput,
            "items": [i.to_dict() for i in self.items],
            "notes": list(self.notes),
            "targets_per_proc_override": self.targets_per_proc_override,
        }

    def format_table(self) -> str:
        head = (
            f"{self.champion_name} ({self.champion_id}) — lvl {self.level} "
            f"— mode {self.mode}  [ENCHANTER]"
        )
        rows = [head, "-" * len(head)]
        if self.item_ids:
            rows.append(f"items: {', '.join(self.item_ids)}")
        else:
            rows.append("items: (none)")
        rows.append(f"caster ap: {self.ap:.0f}")
        rows.append("")
        rows.append(f"  healing_hps_raw     {self.healing_hps_raw:7.2f}")
        rows.append(f"  shielding_hps_raw   {self.shielding_hps_raw:7.2f}")
        rows.append(f"  amp_multiplier      ×{self.amp_multiplier:.3f}")
        if self.mode_multiplier != 1.0:
            rows.append(
                f"  mode_multiplier     ×{self.mode_multiplier:.3f}  "
                f"(aramShieldsHealing)"
            )
        rows.append("")
        rows.append(f"  healing_hps         {self.healing_hps:7.2f}")
        rows.append(f"  shielding_hps       {self.shielding_hps:7.2f}")
        rows.append(f"  direct_throughput   {self.direct_throughput:7.2f}")
        rows.append(f"  ally_buff_credit    {self.ally_buff_credit:7.2f}")
        rows.append(f"  total_throughput    {self.total_throughput:7.2f}")
        if self.items:
            rows.append("")
            rows.append(
                f"  {'id':>6}  {'name':<28}  {'heal':>6}  {'shld':>6}  "
                f"{'amp':>5}  {'buff':>5}"
            )
            rows.append("  " + "-" * 70)
            for c in self.items:
                rows.append(
                    f"  {c.item_id:>6}  {c.item_name[:28]:<28}  "
                    f"{c.healing_hps_raw:>6.2f}  {c.shielding_hps_raw:>6.2f}  "
                    f"{c.heal_shield_amp_pct * 100:>4.0f}%  "
                    f"{c.ally_buff_credit_per_second:>5.1f}"
                )
        if self.notes:
            rows.append("")
            for n in self.notes:
                rows.append(f"  note: {n}")
        return "\n".join(rows)


# ─── Core scorer ────────────────────────────────────────────────────────


def _empty_result(
    champion_id: str,
    champion_name: str,
    level: int,
    item_ids: tuple[str, ...],
    mode: str,
    ap: float,
    mode_mult: float,
    notes: tuple[str, ...],
) -> HpsResult:
    return HpsResult(
        champion_id=champion_id,
        champion_name=champion_name,
        level=level,
        item_ids=item_ids,
        mode=mode,
        ap=ap,
        healing_hps_raw=0.0,
        shielding_hps_raw=0.0,
        amp_multiplier=1.0,
        mode_multiplier=mode_mult,
        healing_hps=0.0,
        shielding_hps=0.0,
        direct_throughput=0.0,
        ally_buff_credit=0.0,
        total_throughput=0.0,
        items=(),
        notes=notes,
    )


def compute_hps(
    snapshot: DataSnapshot,
    champion_id: str,
    level: int,
    item_ids: Optional[Iterable[str | int]] = None,
    mode: str = "SR",
    augments: Optional[Iterable] = None,
    targets_per_proc_override: Optional[float] = None,
    formulas: Optional[EnchanterFormulasSnapshot] = None,
) -> HpsResult:
    """Compute total healing+shielding+buff throughput for the resolved build.

    Items not in the curated enchanter formulas registry contribute zero
    (they're treated as non-enchanter items). Items in the registry but
    with zero formulas (e.g. Moonstone has no direct heal — it only amps)
    contribute zero direct throughput but participate in the amp product.

    ``targets_per_proc_override`` replaces the curated per-item
    ``heal_targets_per_proc`` / ``shield_targets_per_proc`` values for ALL
    items in the build — useful for Arena (2v2 → override=1) or solo-lane
    pre-grouping scenarios. None preserves the per-item curated defaults.
    """
    level = clamp_level(level)

    resolved = build_champion(
        snapshot, champion_id, level, item_ids=item_ids, mode=mode,
        augments=augments,
    )
    stats = resolved.stats
    ap = float(stats.get("ap", 0.0))

    mode_mult = _aram_healing_modifier(snapshot, resolved.champion_id, mode)
    safe_mode_mult = mode_mult if mode_mult > 0 else 1.0

    snap_formulas = formulas if formulas is not None else load_default_formulas()

    contributions: list[HpsItemContribution] = []
    amp_factor = 1.0
    healing_raw = 0.0
    shielding_raw = 0.0
    buff_credit = 0.0
    matched_count = 0

    for iid in resolved.item_ids:
        if not snap_formulas.has_item(iid):
            continue
        formula = snap_formulas.get_formula(iid)
        matched_count += 1

        heal_per_proc = formula.heal_per_proc_at(level, ap)
        shield_per_proc = formula.shield_per_proc_at(level, ap)
        heal_targets = (
            targets_per_proc_override
            if targets_per_proc_override is not None
            else formula.heal_targets_per_proc
        )
        shield_targets = (
            targets_per_proc_override
            if targets_per_proc_override is not None
            else formula.shield_targets_per_proc
        )

        heal_hps = (
            heal_per_proc
            * formula.heal_procs_per_second
            * heal_targets
        )
        shield_hps = (
            shield_per_proc
            * formula.shield_procs_per_second
            * shield_targets
        )
        healing_raw += heal_hps
        shielding_raw += shield_hps
        amp_factor *= 1.0 + formula.heal_shield_amp_pct
        buff_credit += formula.ally_buff_credit_per_second

        contributions.append(HpsItemContribution(
            item_id=formula.item_id,
            item_name=formula.name,
            heal_per_proc=heal_per_proc,
            heal_procs_per_second=formula.heal_procs_per_second,
            heal_targets_per_proc=heal_targets,
            healing_hps_raw=heal_hps,
            shield_per_proc=shield_per_proc,
            shield_procs_per_second=formula.shield_procs_per_second,
            shield_targets_per_proc=shield_targets,
            shielding_hps_raw=shield_hps,
            heal_shield_amp_pct=formula.heal_shield_amp_pct,
            ally_buff_credit_per_second=formula.ally_buff_credit_per_second,
            notes=formula.notes,
        ))

    healing_hps = healing_raw * amp_factor * safe_mode_mult
    shielding_hps = shielding_raw * amp_factor * safe_mode_mult
    direct = healing_hps + shielding_hps
    total = direct + buff_credit

    notes_out: list[str] = []
    if matched_count == 0:
        notes_out.append(
            "no enchanter formulas matched current items — total throughput is 0"
        )
    if mode == "ARAM" and mode_mult != 1.0:
        notes_out.append(
            f"ARAM aramShieldsHealing={mode_mult:.3f} applied to healing+shielding"
        )
    if targets_per_proc_override is not None:
        notes_out.append(
            f"targets_per_proc_override={targets_per_proc_override} "
            f"applied to all items (curated defaults overridden)"
        )

    return HpsResult(
        champion_id=resolved.champion_id,
        champion_name=resolved.champion_name,
        level=level,
        item_ids=resolved.item_ids,
        mode=mode,
        ap=ap,
        healing_hps_raw=healing_raw,
        shielding_hps_raw=shielding_raw,
        amp_multiplier=amp_factor,
        mode_multiplier=mode_mult,
        healing_hps=healing_hps,
        shielding_hps=shielding_hps,
        direct_throughput=direct,
        ally_buff_credit=buff_credit,
        total_throughput=total,
        items=tuple(contributions),
        notes=tuple(notes_out),
        targets_per_proc_override=targets_per_proc_override,
    )


# ─── Ranker ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class HpsRankedItem:
    item_id: str
    item_name: str
    gold: int
    delta_hps: float               # total_throughput with item - baseline
    new_hps: float
    hps_per_1k_gold: float
    is_terminal: bool
    tags: tuple[str, ...]
    # Dead-unique filter mirror (matches RankedItem). Most enchanter items
    # don't share unique_passive_keys with each other but the lifeline
    # family + heal_shield_power crowd could collide in mixed builds.
    shares_dead_unique: bool = False
    dead_unique_key: str = ""

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "item_name": self.item_name,
            "gold": self.gold,
            "delta_hps": self.delta_hps,
            "new_hps": self.new_hps,
            "hps_per_1k_gold": self.hps_per_1k_gold,
            "is_terminal": self.is_terminal,
            "tags": list(self.tags),
            "shares_dead_unique": self.shares_dead_unique,
            "dead_unique_key": self.dead_unique_key,
        }


@dataclass(frozen=True)
class HpsRankResult:
    champion_id: str
    champion_name: str
    level: int
    mode: str
    current_item_ids: tuple[str, ...]
    baseline_hps: float
    budget: Optional[int]
    slot_count: int
    sort_by: str
    candidates_considered: int
    candidates_evaluated: int
    ranked: tuple[HpsRankedItem, ...]
    notes: tuple[str, ...] = field(default_factory=tuple)
    targets_per_proc_override: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "champion_id": self.champion_id,
            "champion_name": self.champion_name,
            "level": self.level,
            "mode": self.mode,
            "current_item_ids": list(self.current_item_ids),
            "baseline_hps": self.baseline_hps,
            "budget": self.budget,
            "slot_count": self.slot_count,
            "sort_by": self.sort_by,
            "candidates_considered": self.candidates_considered,
            "candidates_evaluated": self.candidates_evaluated,
            "ranked": [r.to_dict() for r in self.ranked],
            "notes": list(self.notes),
            "targets_per_proc_override": self.targets_per_proc_override,
        }

    def format_table(self) -> str:
        head = (
            f"{self.champion_name} ({self.champion_id}) — lvl {self.level} "
            f"— mode {self.mode}  [ENCHANTER]"
        )
        rows = [head, "-" * len(head)]
        if self.current_item_ids:
            rows.append(f"current items: {', '.join(self.current_item_ids)}")
        else:
            rows.append("current items: (none)")
        budget_label = "unlimited" if self.budget is None else f"{self.budget}"
        rows.append(
            f"budget: {budget_label}  slots: {len(self.current_item_ids)}/{self.slot_count}"
            f"  sort: {self.sort_by}"
        )
        rows.append(
            f"baseline_hps: {self.baseline_hps:.2f}   "
            f"considered/evaluated: {self.candidates_considered}/{self.candidates_evaluated}"
        )
        rows.append("")
        rows.append(
            f"  {'#':>3}  {'id':>6}  {'name':<28}  "
            f"{'gold':>5}  {'+hps':>6}  {'new':>6}  {'hps/1k':>7}"
        )
        rows.append("  " + "-" * 76)
        for i, r in enumerate(self.ranked, 1):
            rows.append(
                f"  {i:>3}  {r.item_id:>6}  {r.item_name[:28]:<28}  "
                f"{r.gold:>5}  {r.delta_hps:>6.2f}  {r.new_hps:>6.2f}  "
                f"{r.hps_per_1k_gold:>7.2f}"
            )
        if self.notes:
            rows.append("")
            for n in self.notes:
                rows.append(f"  note: {n}")
        return "\n".join(rows)


def rank_items_by_hps(
    snapshot: DataSnapshot,
    champion_id: str,
    level: int,
    current_item_ids: Optional[Iterable[str | int]] = None,
    mode: str = "SR",
    budget: Optional[int] = None,
    slot_count: int = DEFAULT_SLOT_COUNT,
    top_n: int = DEFAULT_TOP_N,
    include_components: bool = False,
    only_item_ids: Optional[Iterable[str | int]] = None,
    sort_by: str = "delta",
    augments: Optional[Iterable] = None,
    filter_shared_uniques: bool = True,
    targets_per_proc_override: Optional[float] = None,
    enchanter_only: bool = True,
    formulas: Optional[EnchanterFormulasSnapshot] = None,
) -> HpsRankResult:
    """Rank items by total-throughput contribution when added to current build.

    Mirror of ``rank.rank_items`` for the HPS scorer. Same candidate-filter
    pipeline (purchasable + mode-legal + optional whitelist + budget +
    terminal-only) — only the scoring function differs.

    ``enchanter_only=True`` (default) restricts the candidate pool to items
    in the curated enchanter formulas registry — there's no point evaluating
    every item in the snapshot when 95% contribute zero HPS. Set False to
    score every candidate (most will rank delta=0 and tie at the bottom).

    Sort keys:
      * ``delta``       — absolute throughput gained (default)
      * ``efficiency``  — throughput gained per 1000 gold

    Same dead-unique dedup logic as ``rank.rank_items``.
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

    snap_formulas = formulas if formulas is not None else load_default_formulas()

    only_ids: Optional[set[str]] = None
    if only_item_ids is not None:
        only_ids = {str(i) for i in only_item_ids}
    elif enchanter_only:
        # Restrict the candidate pool to the curated enchanter item registry.
        # Mode-legal mirrors of the SR ids (Arena 22xxxx / ARAM 32xxxx) are
        # included by joining against ITEM_EFFECTS name match for the same name.
        registry_ids = set(snap_formulas.item_ids())
        # Also accept Arena/ARAM mirrors by item name match (effects.py uses
        # the same name across mode variants).
        names_in_registry = {snap_formulas.get_formula(i).name for i in registry_ids}
        for iid, eff in ITEM_EFFECTS.items():
            if eff.name in names_in_registry:
                registry_ids.add(iid)
        only_ids = registry_ids

    baseline = compute_hps(
        snapshot,
        champion_id=champion_id,
        level=level,
        item_ids=current_ids,
        mode=mode,
        augments=augments,
        targets_per_proc_override=targets_per_proc_override,
        formulas=snap_formulas,
    )

    candidates = _filter_candidates(
        snapshot,
        mode=mode,
        current_ids=current_set,
        budget=budget,
        include_components=include_components,
        only_ids=only_ids,
    )

    ranked: list[HpsRankedItem] = []
    for item_id, rec in candidates:
        cand_eff = ITEM_EFFECTS.get(item_id)
        cand_key = cand_eff.unique_passive_key if cand_eff is not None else ""
        shares_dead_unique = bool(cand_key and cand_key in current_unique_keys)
        if shares_dead_unique and filter_shared_uniques:
            continue
        new_build = current_ids + (item_id,)
        # For Arena/ARAM mirror items, resolve through the formula registry
        # only if the mirror id itself is registered; otherwise the
        # contribution will be 0 and the candidate ranks at the bottom.
        try:
            scored = compute_hps(
                snapshot,
                champion_id=champion_id,
                level=level,
                item_ids=new_build,
                mode=mode,
                augments=augments,
                targets_per_proc_override=targets_per_proc_override,
                formulas=snap_formulas,
            )
        except (KeyError, ValueError):
            continue
        gold = int((rec.get("gold") or {}).get("total", 0) or 0)
        delta = scored.total_throughput - baseline.total_throughput
        eff = (delta / (gold / 1000.0)) if (gold > 0 and delta > 0) else 0.0
        ranked.append(HpsRankedItem(
            item_id=item_id,
            item_name=str(rec.get("name", item_id)),
            gold=gold,
            delta_hps=delta,
            new_hps=scored.total_throughput,
            hps_per_1k_gold=eff,
            is_terminal=_is_terminal(rec),
            tags=tuple(rec.get("tags") or ()),
            shares_dead_unique=shares_dead_unique,
            dead_unique_key=cand_key if shares_dead_unique else "",
        ))

    if sort_by == "efficiency":
        ranked.sort(key=lambda r: (r.hps_per_1k_gold, r.delta_hps), reverse=True)
    else:
        ranked.sort(key=lambda r: (r.delta_hps, r.hps_per_1k_gold), reverse=True)

    if top_n is not None and top_n > 0:
        ranked = ranked[:top_n]

    notes: list[str] = []
    if stripped_trinkets:
        notes.append(
            f"mode=ARENA — stripped trinket(s) {list(stripped_trinkets)} "
            f"from current_item_ids"
        )
    if include_components:
        notes.append("include_components=True — non-terminal items in the ranking")
    if budget is not None:
        notes.append(f"budget={budget}g — items over budget filtered")
    if only_item_ids is not None:
        notes.append(
            f"only_item_ids restricted to {len(only_ids or ())} whitelisted ids"
        )
    elif enchanter_only:
        notes.append(
            f"enchanter_only=True — candidate pool restricted to "
            f"{len(only_ids or ())} curated enchanter items + mode mirrors"
        )
    if targets_per_proc_override is not None:
        notes.append(
            f"targets_per_proc_override={targets_per_proc_override} applied "
            f"to all items"
        )
    if baseline.mode_multiplier != 1.0:
        notes.append(
            f"ARAM aramShieldsHealing={baseline.mode_multiplier:.3f} folded "
            f"into all HPS values"
        )

    return HpsRankResult(
        champion_id=baseline.champion_id,
        champion_name=baseline.champion_name,
        level=level,
        mode=mode,
        current_item_ids=current_ids,
        baseline_hps=baseline.total_throughput,
        budget=budget,
        slot_count=slot_count,
        sort_by=sort_by,
        candidates_considered=len(snapshot.items),
        candidates_evaluated=len(candidates),
        ranked=tuple(ranked),
        notes=tuple(notes),
        targets_per_proc_override=targets_per_proc_override,
    )
