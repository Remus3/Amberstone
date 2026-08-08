"""Phase 6 (s181, 2026-05-13) - Enchanter healing throughput scorer.

Sibling of ``dps.py`` / ``ehp.py`` / ``ability_dps.py`` / ``burst.py``.
``compute_hps()`` returns the caster's total healing + shielding + ally-
buff throughput per second for a given build under a "mid-game team-fight"
ally model. ``rank_items_by_hps()`` scores every purchasable mode-legal
item by how much total throughput it adds (same candidate-filtering
pipeline as the DPS / EHP / hybrid / ability / burst scorers).

Phase 6 is the lowest-fidelity tier in the archetype expansion plan - by
design. The DS engine has zero ally-state plumbing (no positions, no
current HP, no buff-uptime tracking). The "average teammate" model is:

* 4 allies present in team-fight radius
* AoE actives hit 3 allies on average (operator-overridable)
* Single-target heals/shields hit 1 ally (the bonded ally for Knight's
  Vow, the lowest-HP ally for Mikael)
* Proc rate for actives = 1/CD (Redemption 120s, Mikael 120s, Locket 90s)
* Proc rate for passives = curated per-item (Helia Soul Siphon ~ 0.4/s;
  Moonstone chain rides whatever the caster heals/shields)

Formulas live in ``data/daemon_slayer/<patch>/enchanter_items.json`` - a
hand-curated registry of 10 enchanter items. The engine reads it via
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
(10 ~ 10 HPS-equivalent) to make Ardent / Staff of Flowing Water / Knight's
Vow rankable next to direct-heal items. Phase 6.5 may overhaul this with
real ally-state plumbing, but it's not blocking.

Phase 6 deliberate omissions (Phase 6.5+):
* Real ally-state plumbing (positions, HP, ability casts) - by design
* Champion-spell healing throughput (Soraka W, Lulu E shield, Janna E
  shield) - only ITEM throughput is scored; champion abilities are out
  of scope for v1
* Heal/shield-power scaling on champion abilities - the amp_multiplier
  applies only to item throughput here (a Soraka with Redemption sees
  her R amp via the in-game system, not this scorer)
* ARAM aramShieldsHealing modifier - applied if present on the champion
  but not all enchanter champions have it; default mode_mult=1.0

Phase 6 ALSO models per-target multiplier overrides via
``targets_per_proc_override`` on the API, so callers can tune the
"average teammate" assumption per scenario (e.g. 2v2 Arena -> 1 ally).
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
    _champion_is_melee,
    _filter_candidates,
    _is_terminal,
    strip_arena_trinkets,
)
from .stats import clamp_level
from .survivability_credit import survivability_item_ids_enchanter

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_ROOT = _REPO_ROOT / "data" / "daemon_slayer"


class EnchanterFormulasNotFound(FileNotFoundError):
    """Raised when the requested enchanter_items.json snapshot is missing."""


# --- Curated formula loader ---------------------------------------------


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
    # R143: True when heal_shield_amp_pct is an ALLY-CHAIN ratio rather than a
    # wielder Heal-and-Shield-Power stat (Moonstone Renewer's Starlit Grace
    # explicitly excludes the wielder). RM-177: the ally-throughput path in this
    # module still COMPOUNDS it - a chain ratio genuinely multiplies - while the
    # printed-HSP rows sum; ``_hsp_amp.sum_wielder_hsp_pct`` skips it entirely.
    # Appended at the END with a default per CLAUDE.md "Python Conventions".
    ally_chain_only: bool = False

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
            ally_chain_only=bool(d.get("ally_chain_only", False)),
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
        # Integrity gate (mirrors data_loader): valid JSON with a
        # missing/empty 'items' container is a corrupt or partially
        # written snapshot. Fail LOUDLY rather than returning a
        # formula-less snapshot that would silently drop every
        # enchanter-item HPS contribution to 0.
        items = doc.get("items") if isinstance(doc, dict) else None
        if not isinstance(items, dict) or not items:
            raise EnchanterFormulasNotFound(
                f"Enchanter formulas snapshot {path} missing/empty 'items' "
                f"container (snapshot {patch}) - corrupt or partially written"
            )
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


# --- ARAM modifier helper -----------------------------------------------


def _aram_heal_shield_modifiers(
    snapshot: DataSnapshot, champion_id: str, mode: str
) -> tuple[float, float]:
    """Pull ARAM heal + shield modifiers from the snapshot.

    Returns ``(heal_mult, shield_mult)``. Outside ARAM both are 1.0.

    Meraki bulk carries TWO independent keys on the champion blob:
      * ``aramHealing``   - applied to outgoing healing only
      * ``aramShielding`` - applied to outgoing shields only

    24 champions in the 16.10.1 snapshot carry different values for the
    two keys (e.g. Camille 1.20 / 1.10, LeeSin 1.10 / 1.20, Milio 0.95 /
    0.90, Nunu 1.10 / 1.20, Ahri 0.90 / 1.00...). Collapsing them into
    a single ``aramShieldsHealing`` (the legacy field this engine used)
    under-models all 24. Pre-2026-05-20 the engine read
    ``aramShieldsHealing`` with a fallback to ``aramHealing``, so the
    shield half was wrong for every split champ.

    Legacy fallback: if only the singular ``aramShieldsHealing`` is
    present (old snapshots before the bulk schema split), use it for
    both halves so the older data still scores.
    """
    if mode != "ARAM":
        return (1.0, 1.0)
    champ = snapshot.champion(champion_id)
    aram = ((champ.get("lolmath") or {}).get("aram_modifiers") or {})
    if "aramHealing" in aram and "aramShielding" in aram:
        return (float(aram["aramHealing"]), float(aram["aramShielding"]))
    if "aramShieldsHealing" in aram:
        v = float(aram["aramShieldsHealing"])
        return (v, v)
    # Either key alone (the snapshot can carry just one when the other
    # defaults to 1.0).
    heal = float(aram.get("aramHealing", 1.0))
    shield = float(aram.get("aramShielding", 1.0))
    return (heal, shield)


def _aram_healing_modifier(
    snapshot: DataSnapshot, champion_id: str, mode: str
) -> float:
    """Backward-compat single-value modifier. Returns the heal half.

    Deprecated for new call sites - prefer
    ``_aram_heal_shield_modifiers`` so the shield half isn't lost.
    """
    return _aram_heal_shield_modifiers(snapshot, champion_id, mode)[0]


# --- Result types -------------------------------------------------------


@dataclass(frozen=True)
class HpsItemContribution:
    """Per-item healing/shielding/buff breakdown."""

    item_id: str
    item_name: str
    heal_per_proc: float           # post-level + AP scaling
    heal_procs_per_second: float
    heal_targets_per_proc: float
    healing_hps_raw: float         # heal_per_proc x procs x targets (pre-amp)
    shield_per_proc: float
    shield_procs_per_second: float
    shield_targets_per_proc: float
    shielding_hps_raw: float       # pre-amp
    heal_shield_amp_pct: float     # additive HSP, or a chain ratio if ally_chain_only
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
    healing_hps_raw: float         # sum of per-item heal x proc x targets
    shielding_hps_raw: float       # sum of per-item shield x proc x targets
    # Multipliers:
    amp_multiplier: float          # product(1 + heal_shield_amp_pct)
    heal_mult: float               # aramHealing; 1.0 outside ARAM
    shield_mult: float             # aramShielding; 1.0 outside ARAM
    # Final score components:
    healing_hps: float             # healing_hps_raw x amp x heal_mult
    shielding_hps: float           # shielding_hps_raw x amp x shield_mult
    direct_throughput: float       # healing_hps + shielding_hps (item-only)
    ally_buff_credit: float        # sum of ally_buff_credit_per_second
    total_throughput: float        # direct + buff + ability_hps_total
    # Per-item breakdown:
    items: tuple[HpsItemContribution, ...]
    notes: tuple[str, ...] = field(default_factory=tuple)
    targets_per_proc_override: Optional[float] = None
    # --- V2: champion-ability heal/shield throughput (ability_hps.py) ---
    # Folded into total_throughput so an enchanter's own kit counts (Soraka
    # W, Lulu E shield, Janna E shield, ...). 0.0 for champions with no
    # ability heal/shield blocks (most of the roster) -> total_throughput
    # stays byte-identical to the pre-V2 direct+buff value. New defaulted
    # fields go at the END of the dataclass so _empty_result + the main
    # return keep their existing positional/keyword construction.
    ability_heal_hps: float = 0.0
    ability_shield_hps: float = 0.0
    ability_hps_total: float = 0.0
    # ENGINE 1.202.0 (2026-07-11): the multiplier applied to the folded
    # champion-ability heal/shield throughput (``ability_hps_total``) inside
    # ``total_throughput``. 1.0 by default (the ability fold is added RAW,
    # byte-identical to <= 1.201.0); == ``amp_multiplier`` when the DEFAULT-OFF
    # ``apply_ability_hsp_amp`` seam is on and a Heal/Shield-Power item is
    # equipped. ``ability_hps_total`` itself stays PRE-amp for transparency
    # (matching the item ``healing_hps_raw`` pre-amp convention). New defaulted
    # field appended at the END so _empty_result + the main return keep their
    # existing keyword construction.
    ability_hps_amp_mult: float = 1.0

    @property
    def mode_multiplier(self) -> float:
        """Backward-compat alias: returns ``heal_mult``.

        Pre-split this field was the single combined ARAM healing/shield
        modifier (``aramShieldsHealing``). The 2026-05-20 fix splits
        the heal and shield halves; this alias preserves callers that
        only inspect the heal-side ratio (e.g.
        ``healing_hps(ARAM) / healing_hps(SR) == mode_multiplier``).
        """
        return self.heal_mult

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
            "heal_mult": self.heal_mult,
            "shield_mult": self.shield_mult,
            "mode_multiplier": self.mode_multiplier,
            "healing_hps": self.healing_hps,
            "shielding_hps": self.shielding_hps,
            "direct_throughput": self.direct_throughput,
            "ally_buff_credit": self.ally_buff_credit,
            "ability_heal_hps": self.ability_heal_hps,
            "ability_shield_hps": self.ability_shield_hps,
            "ability_hps_total": self.ability_hps_total,
            "ability_hps_amp_mult": self.ability_hps_amp_mult,
            "total_throughput": self.total_throughput,
            "items": [i.to_dict() for i in self.items],
            "notes": list(self.notes),
            "targets_per_proc_override": self.targets_per_proc_override,
        }

    def format_table(self) -> str:
        head = (
            f"{self.champion_name} ({self.champion_id}) - lvl {self.level} "
            f"- mode {self.mode}  [ENCHANTER]"
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
        rows.append(f"  amp_multiplier      x{self.amp_multiplier:.3f}")
        if self.heal_mult != 1.0 or self.shield_mult != 1.0:
            rows.append(
                f"  heal_mult           x{self.heal_mult:.3f}  "
                f"shield_mult         x{self.shield_mult:.3f}  "
                f"(aramHealing / aramShielding)"
            )
        rows.append("")
        rows.append(f"  healing_hps         {self.healing_hps:7.2f}")
        rows.append(f"  shielding_hps       {self.shielding_hps:7.2f}")
        rows.append(f"  direct_throughput   {self.direct_throughput:7.2f}")
        rows.append(f"  ally_buff_credit    {self.ally_buff_credit:7.2f}")
        if self.ability_hps_total > 0:
            rows.append(f"  ability_heal_hps    {self.ability_heal_hps:7.2f}")
            rows.append(f"  ability_shield_hps  {self.ability_shield_hps:7.2f}")
            rows.append(f"  ability_hps_total   {self.ability_hps_total:7.2f}")
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


# --- Core scorer --------------------------------------------------------


def _empty_result(
    champion_id: str,
    champion_name: str,
    level: int,
    item_ids: tuple[str, ...],
    mode: str,
    ap: float,
    heal_mult: float,
    shield_mult: float,
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
        heal_mult=heal_mult,
        shield_mult=shield_mult,
        healing_hps=0.0,
        shielding_hps=0.0,
        direct_throughput=0.0,
        ally_buff_credit=0.0,
        total_throughput=0.0,
        items=(),
        notes=notes,
        ability_heal_hps=0.0,
        ability_shield_hps=0.0,
        ability_hps_total=0.0,
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
    assume_missing_hp_heal_amp: bool = False,
    caster_missing_hp_pct: float = 0.0,
    apply_ability_hsp_amp: bool = False,
    apply_mode_modifiers: bool = False,
) -> HpsResult:
    """Compute total healing+shielding+buff throughput for the resolved build.

    Items not in the curated enchanter formulas registry contribute zero
    (they're treated as non-enchanter items). Items in the registry but
    with zero formulas (e.g. Moonstone has no direct heal - it only amps)
    contribute zero direct throughput but still feed the amp term.

    ``targets_per_proc_override`` replaces the curated per-item
    ``heal_targets_per_proc`` / ``shield_targets_per_proc`` values for ALL
    items in the build - useful for Arena (2v2 -> override=1) or solo-lane
    pre-grouping scenarios. None preserves the per-item curated defaults.

    ``assume_missing_hp_heal_amp`` / ``caster_missing_hp_pct`` (R5 seam,
    DEFAULT-OFF/0.0) are threaded straight into the champion-ability heal scorer
    (``compute_ability_hps``). When OFF (default) the missing-HP comeback heal-amp
    (MasterYi W / Sylas W / Lissandra R / Briar P) is never applied -> the ability
    heal throughput, and therefore ``total_throughput``, is byte-identical to
    today. When ON with a positive ``caster_missing_hp_pct`` the registered
    ability heals are multiplied by ``1 + max_bonus * caster_missing_hp_pct``.

    ENGINE 1.202.0 (2026-07-11): ``apply_ability_hsp_amp`` (DEFAULT-OFF) closes
    the item-HSP-vs-ability-throughput gap. The item heal/shield throughput is
    already Heal/Shield-Power amped (``healing_hps = healing_raw * amp_factor``),
    but the folded champion-ability throughput (``ability_hps_total``) was added
    RAW at the grand total, so an enchanter's Ardent Censer / Staff of Flowing
    Water / Redemption / Mikael HSP amped her ITEM heals but NOT her ABILITY heals
    (Soraka Q/W, Janna E, Lulu E shield, ...). In League, HSP amplifies every
    heal/shield the wielder outputs, incl. abilities. When OFF (default) the
    ability fold stays RAW -> ``total_throughput`` is byte-identical to 1.201.0.
    When ON the ability fold is multiplied by the SAME ``amp_multiplier`` the item
    heals use (the product ``prod(1 + heal_shield_amp_pct)`` for the one wielder),
    so an enchanter with no HSP item (amp_multiplier == 1.0) or no ability heal
    block (ability_hps_total == 0.0) stays byte-identical even ON. The live
    default-ON flip is operator-gated (mirrors the ehp.py item-side seams).
    """
    level = clamp_level(level)

    # RM-172: apply_mode_modifiers (DEFAULT-OFF) opts into the ARENA/Swiftplay
    # stat-growth ADDEND lane. Forwarded to compute_ability_hps below too, so
    # both halves of total_throughput share one stat line.
    resolved = build_champion(
        snapshot, champion_id, level, item_ids=item_ids, mode=mode,
        augments=augments, apply_mode_modifiers=apply_mode_modifiers,
    )
    stats = resolved.stats
    ap = float(stats.get("ap", 0.0))

    heal_mult, shield_mult = _aram_heal_shield_modifiers(
        snapshot, resolved.champion_id, mode,
    )
    safe_heal_mult = heal_mult if heal_mult > 0 else 1.0
    safe_shield_mult = shield_mult if shield_mult > 0 else 1.0

    snap_formulas = formulas if formulas is not None else load_default_formulas()

    contributions: list[HpsItemContribution] = []
    # RM-177: Heal-and-Shield-Power is ADDITIVE in League, so the printed-stat
    # rows accumulate into a sum and are folded once, below. Only the
    # ``ally_chain_only`` rows are a genuine multiplier - their field carries an
    # ally-CHAIN ratio, not the printed HSP stat, which is why ``_hsp_amp``
    # skips them for the wielder entirely.
    hsp_pct_sum = 0.0
    chain_factor = 1.0
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
        if formula.ally_chain_only:
            chain_factor *= 1.0 + formula.heal_shield_amp_pct
        else:
            hsp_pct_sum += formula.heal_shield_amp_pct
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

    amp_factor = chain_factor * (1.0 + hsp_pct_sum)

    healing_hps = healing_raw * amp_factor * safe_heal_mult
    shielding_hps = shielding_raw * amp_factor * safe_shield_mult
    direct = healing_hps + shielding_hps

    # V2 (2026-05-30): fold champion-ability heal/shield throughput into the
    # grand total so an enchanter's own kit counts (Soraka W, Lulu E shield,
    # Janna E shield, ...). FUNCTION-LEVEL import: ability_hps.py imports
    # `from .hps import _aram_heal_shield_modifiers` at module load, so a
    # module-level import here would be a circular import. We pass the SAME
    # snapshot / champion / level / resolved item_ids / mode / augments.
    # include_passive=True is the default (no-op on the 16.11.1 snapshot - no
    # P-slot heal/shield blocks). resolve_target_relative=False is the
    # conservative lower bound for the live scorer: target-relative shields
    # (Taric W % target max HP) stay at their 0 lower bound rather than
    # over-counting against an assumed enemy HP. ability_hps_total is
    # ADDITIVE to the grand total; for champions with NO ability heal/shield
    # blocks (most of the roster) it is 0.0 and total_throughput is
    # byte-identical to the pre-V2 direct+buff value. Fail-soft: a raise in
    # the heal-scorer must never crash the item scorer.
    ability_heal_hps = 0.0
    ability_shield_hps = 0.0
    ability_hps_total = 0.0
    ability_hps_failed = False
    try:
        from .ability_hps import compute_ability_hps

        a = compute_ability_hps(
            snapshot,
            resolved.champion_id,
            level,
            item_ids=resolved.item_ids,
            mode=mode,
            augments=augments,
            include_passive=True,
            resolve_target_relative=False,
            assume_missing_hp_heal_amp=assume_missing_hp_heal_amp,
            caster_missing_hp_pct=caster_missing_hp_pct,
            apply_mode_modifiers=apply_mode_modifiers,
        )
        ability_heal_hps = a.total_heal_per_sec
        ability_shield_hps = a.total_shield_per_sec
        ability_hps_total = a.total_ability_hps
    except Exception:
        ability_hps_failed = True

    # ENGINE 1.202.0 (2026-07-11): item HSP amp of the CHAMPION-ABILITY heal/shield
    # fold. ``direct`` (item throughput) is already amped by ``amp_factor``
    # (healing_hps = healing_raw * amp_factor, above); ``ability_hps_total`` was
    # folded RAW here, so the wielder's HSP items amped her item heals but NOT her
    # ability heals. ``apply_ability_hsp_amp`` defaults False -> the ability fold
    # stays RAW -> total_throughput byte-identical. ON multiplies it by the SAME
    # ``amp_factor`` (RM-177 additive-HSP convention, one wielder), applied at THIS single
    # consumer boundary only (compute_ability_hps stays the pre-amp substrate, so
    # no double-count). amp_factor == 1.0 (no HSP item) or ability_hps_total == 0.0
    # (no ability heal block) -> byte-identical even when ON.
    ability_hps_amp_mult = amp_factor if apply_ability_hsp_amp else 1.0
    total = direct + buff_credit + ability_hps_total * ability_hps_amp_mult

    notes_out: list[str] = []
    if matched_count == 0:
        notes_out.append(
            "no enchanter formulas matched current items - item throughput is 0"
        )
    if ability_hps_total > 0:
        notes_out.append(
            f"includes champion-ability heal/shield throughput "
            f"({ability_hps_total:.2f} HPS) - target-relative shields at "
            f"their lower bound"
        )
        if apply_ability_hsp_amp and ability_hps_amp_mult != 1.0:
            notes_out.append(
                f"ability heal/shield throughput HSP-amped x"
                f"{ability_hps_amp_mult:.3f} (Ardent / Staff / Redemption / "
                f"Mikael and similar)"
            )
    if ability_hps_failed:
        notes_out.append(
            "ability heal/shield throughput unavailable (scorer error) - "
            "counted as 0"
        )
    if mode == "ARAM" and (heal_mult != 1.0 or shield_mult != 1.0):
        notes_out.append(
            f"ARAM aramHealing={heal_mult:.3f} aramShielding={shield_mult:.3f} "
            f"applied per-side"
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
        heal_mult=heal_mult,
        shield_mult=shield_mult,
        healing_hps=healing_hps,
        shielding_hps=shielding_hps,
        direct_throughput=direct,
        ally_buff_credit=buff_credit,
        total_throughput=total,
        items=tuple(contributions),
        notes=tuple(notes_out),
        targets_per_proc_override=targets_per_proc_override,
        ability_heal_hps=ability_heal_hps,
        ability_shield_hps=ability_shield_hps,
        ability_hps_total=ability_hps_total,
        ability_hps_amp_mult=ability_hps_amp_mult,
    )


# --- Ranker -------------------------------------------------------------


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
    # Phase 4(d): candidate's own unique-passive family key, always set
    # (collision-independent) - the positive "locks <family>" signal.
    unique_passive_key: str = ""
    # RF2 enchanter survivability credit marker: 1.0 on a WIN-anchored survivability
    # item injected + floated by the prefer_survivability_by_win seam, else 0.0.
    survivability_score: float = 0.0

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
            "unique_passive_key": self.unique_passive_key,
            "survivability_score": self.survivability_score,
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
            f"{self.champion_name} ({self.champion_id}) - lvl {self.level} "
            f"- mode {self.mode}  [ENCHANTER]"
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
    prefer_survivability_by_win: bool = False,
    assume_missing_hp_heal_amp: bool = False,
    caster_missing_hp_pct: float = 0.0,
    apply_mode_modifiers: bool = False,
) -> HpsRankResult:
    """Rank items by total-throughput contribution when added to current build.

    Mirror of ``rank.rank_items`` for the HPS scorer. Same candidate-filter
    pipeline (purchasable + mode-legal + optional whitelist + budget +
    terminal-only) - only the scoring function differs.

    ``enchanter_only=True`` (default) restricts the candidate pool to items
    in the curated enchanter formulas registry - there's no point evaluating
    every item in the snapshot when 95% contribute zero HPS. Set False to
    score every candidate (most will rank delta=0 and tie at the bottom).

    Sort keys:
      * ``delta``       - absolute throughput gained (default)
      * ``efficiency``  - throughput gained per 1000 gold

    Same dead-unique dedup logic as ``rank.rank_items``.

    ``prefer_survivability_by_win`` is the OPTIONAL RF2 enchanter-template seam
    (DEFAULT-OFF). For an enchanter played front-to-back as a tank-support, the HP /
    tank survivability items the player base wins ARAM on (Guardian's Horn / Warmog's
    Armor / Heartsteel / Fimbulwinter; the DSP10 hps-lane buried winners) are EXCLUDED
    from the ``enchanter_only`` pool entirely - they add zero HPS throughput, so the
    throughput scorer never sees them and the generic enchanter template (Helia /
    Ardent / Staff / Locket / Knight's Vow / Redemption) tops the list. When ``False``
    (default) the output is byte-identical - ``survivability_score`` stays 0.0 and the
    sort is unchanged. When ``True`` and the champ has a WIN-anchored
    ``survivability_item_credit_enchanter`` entry, those tabled ids are INJECTED into
    the candidate pool and floated above the generic template BY TABLE MEMBERSHIP
    (model order preserved within each tier). UNLIKE the RF1 hybrid seam (which only
    floats - the bruiser scorer already pools survivability items), RF2 must inject
    first because ``enchanter_only`` drops them. Champs absent from the table are a
    no-op. The live default-ON flip is EXCLUDED -> docs/LIVE_GAME_GATED_SYNC.md.

    ``assume_missing_hp_heal_amp`` / ``caster_missing_hp_pct`` (R5 seam,
    DEFAULT-OFF/0.0) are forwarded into BOTH the baseline and per-candidate
    ``compute_hps`` calls so the missing-HP comeback heal-amp shifts the throughput
    of every build consistently. When OFF (default) the output is byte-identical -
    no ability heal is amplified. When ON with a positive ``caster_missing_hp_pct``
    a champ with a registered missing-HP heal (MasterYi W / Sylas W / Lissandra R /
    Briar P) sees its ability-heal throughput, and therefore its delta, rise.
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

    # RF2 (DEFAULT-OFF): resolve the champ's WIN-anchored enchanter survivability set
    # and INJECT it into the candidate pool. The enchanter_only pool above EXCLUDES
    # these HP/tank items (zero HPS throughput), so unlike the RF1 hybrid lane they
    # must be added to the pool before they can be floated. Empty (-> byte-identical
    # no-op) unless the seam is ON AND the champ is tabled.
    champ_rec = snapshot.champions.get(str(champion_id))
    surv_ids: frozenset[str] = (
        survivability_item_ids_enchanter(str(champion_id), champ_rec)
        if prefer_survivability_by_win else frozenset()
    )
    surv_active = bool(surv_ids)
    if surv_active and only_ids is not None:
        only_ids = set(only_ids) | set(surv_ids)

    baseline = compute_hps(
        snapshot,
        champion_id=champion_id,
        level=level,
        item_ids=current_ids,
        mode=mode,
        augments=augments,
        targets_per_proc_override=targets_per_proc_override,
        formulas=snap_formulas,
        assume_missing_hp_heal_amp=assume_missing_hp_heal_amp,
        caster_missing_hp_pct=caster_missing_hp_pct,
        apply_mode_modifiers=apply_mode_modifiers,
    )

    candidates = _filter_candidates(
        snapshot,
        mode=mode,
        current_ids=current_set,
        budget=budget,
        include_components=include_components,
        only_ids=only_ids,
        # Ranged-only purchasability gate: drop Runaan's (+ alias) for a melee
        # enchanter - the shop blocks the purchase (2026-07-02).
        champion_is_melee=_champion_is_melee(champ_rec, augments),
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
                assume_missing_hp_heal_amp=assume_missing_hp_heal_amp,
                caster_missing_hp_pct=caster_missing_hp_pct,
                apply_mode_modifiers=apply_mode_modifiers,
            )
        except (KeyError, ValueError):
            continue
        gold = int((rec.get("gold") or {}).get("total", 0) or 0)
        delta = scored.total_throughput - baseline.total_throughput
        eff = (delta / (gold / 1000.0)) if (gold > 0 and delta > 0) else 0.0
        # RF2: 1.0 on a WIN-anchored survivability item when the seam is engaged
        # (floated by MEMBERSHIP - these items add EHP/HP not HPS, so their delta is
        # ~0 and a throughput sort would never surface them), else 0.0.
        survivability_score = 1.0 if (surv_active and item_id in surv_ids) else 0.0
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
            unique_passive_key=cand_key,
            survivability_score=survivability_score,
        ))

    def _base_key(r: HpsRankedItem) -> tuple:
        if sort_by == "efficiency":
            return (r.hps_per_1k_gold, r.delta_hps)
        return (r.delta_hps, r.hps_per_1k_gold)

    if surv_active:
        # RF2: float injected survivability items above the generic enchanter
        # template, preserving model order within each tier. Byte-identical when off
        # (surv_active False -> the prefix term is never added).
        ranked.sort(key=lambda r: (r.survivability_score,) + _base_key(r), reverse=True)
    else:
        ranked.sort(key=_base_key, reverse=True)

    if top_n is not None and top_n > 0:
        ranked = ranked[:top_n]

    notes: list[str] = []
    if surv_active:
        notes.append(
            f"prefer_survivability_by_win=ON - {len(surv_ids)} WIN-anchored "
            f"survivability item(s) injected + floated above the enchanter template"
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
    if only_item_ids is not None:
        notes.append(
            f"only_item_ids restricted to {len(only_ids or ())} whitelisted ids"
        )
    elif enchanter_only:
        notes.append(
            f"enchanter_only=True - candidate pool restricted to "
            f"{len(only_ids or ())} curated enchanter items + mode mirrors"
        )
    if targets_per_proc_override is not None:
        notes.append(
            f"targets_per_proc_override={targets_per_proc_override} applied "
            f"to all items"
        )
    if baseline.heal_mult != 1.0 or baseline.shield_mult != 1.0:
        notes.append(
            f"ARAM aramHealing={baseline.heal_mult:.3f} "
            f"aramShielding={baseline.shield_mult:.3f} folded into HPS values"
        )
    if baseline.ability_hps_total > 0:
        notes.append(
            "includes champion-ability heal/shield throughput "
            f"({baseline.ability_hps_total:.2f} HPS in baseline; recomputed "
            "per candidate as AP-scaling heals grow with each item)"
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
