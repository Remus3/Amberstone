"""Phase 4b (s178, 2026-05-12) — Mage ability DPS evaluator.

Sibling of ``dps.py``. ``compute_ability_dps()`` returns the caster's
per-spell ability DPS (and total) for a resolved build at a given level.
``rank_items_by_ability_dps()`` ships in Phase 4c (next session).

For each of the four active spell keys (Q/W/E/R):

1. Resolve the rank at the given champion level using a canonical
   max-priority order (default Q > W > E; R unlocks at lvl 6/11/16).
2. Evaluate the first damage block of the canonical ability form via the
   Phase 4a ``DamageBlock`` schema — sums ``base`` plus each scaling
   field times its corresponding caster/target stat from the resolved
   build / caller-supplied context.
3. Apply mode damage multiplier (``aramDamageDealt`` for ARAM).
4. Apply mitigation factor per damage type: PHYSICAL→target_armor,
   MAGIC→target_mr, TRUE→none, MIXED→half-half.
5. Multiply per-cast damage by measured casts/sec from
   ``cast_rates.get_spell_casts_per_sec``. If the dataset has no entry
   for this champion × mode, fall back to ``1 / cooldown × mana_uptime``.
6. Sum per-spell DPS into ``total_ability_dps``.

Block-strategy notes
~~~~~~~~~~~~~~~~~~~~

Most damage-dealing mages (Veigar, Lux, Annie, Brand, Syndra, Xerath)
expose a single ``damage`` block per ability key — straightforward to
evaluate. A minority of champions (Aatrox Q's chain variants, Aphelios's
weapon stances, Ezreal's R splash component) ship multiple damage blocks
per form. Phase 4b uses ``block_strategy="first"`` by default — only the
first damage block of the canonical form_index=0 contributes. This
under-scores chain-cast and weapon-swap mechanics (the typical fighter
patterns) but evaluates mage abilities accurately, which is the Phase 4b
target. Phase 5 (assassin burst) revisits with per-champion strategies.

Phase 4b deliberate omissions (deferred):
* Passive (P) ability damage — needs different rank model (level-scaled
  rather than rank-locked); typically on-hit which ``compute_dps`` covers.
* Multi-form abilities (Aphelios weapons, Jayce stance, Sylas-stolen ult)
  — ``form_index=0`` only. Operator can pass ``form_index_overrides`` to
  pick a different form per key.
* Item-level ability haste, on-cast triggers, ability-amp items like
  Liandry's ramp damage — modeled at the rotation level in ``dps.py``,
  not at per-cast level here. Items that pump ``ap`` flow through to
  ability DPS naturally via the resolved stat block.
* Conditional damage amps (Ahri R-into-Q, Zoe E-into-Q) — single
  per-cast scoring with no combo-multiplier. Champion-specific.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Iterable, Optional, Sequence

from .abilities import (
    AbilitiesNotFound,
    AbilitiesSnapshot,
    AbilityForm,
    DamageBlock,
)
from .data_loader import DataSnapshot
from .effects import (
    collect_effects,
    effective_target_armor,
    effective_target_mr,
    total_ap_amp_multiplier,
    total_bonus_ap_from_hp,
    total_caster_hp_scaled_ap_amp,
    total_damage_amp_multiplier,
    total_giant_slayer_multiplier,
    total_magic_amp_multiplier,
    total_stacked_ap,
    total_target_bonus_hp_amp_multiplier,
)
from .engine import build_champion
from .stats import clamp_level
from .ult_rates import get_spell_casts_per_sec

# Canonical 4-active-spell set. Passive (P) is intentionally excluded —
# the ``compute_dps`` auto-attack scorer covers on-hit passives, and
# level-scaled passive damage doesn't fit the per-rank model.
SPELL_KEYS: tuple[str, ...] = ("Q", "W", "E", "R")

# Standard max-priority rank tables (0-indexed rank at champion level).
# Pin to the conventional "Q-first, W-second, E-third" max order; per-champ
# overrides can ship in a future patch via a JSON next to archetype_weights.
_PRIORITY_TABLES: dict[str, tuple[int, ...]] = {
    # Indexed 1-18 (idx 0 unused so lookup reads naturally).
    "priority_1": (-1, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4),
    "priority_2": (-1, -1, 0, 0, 0, 0, 0, 0, 1, 1, 2, 2, 3, 4, 4, 4, 4, 4, 4),
    "priority_3": (-1, -1, -1, -1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 2, 2, 3, 4),
    # R unlocks at 6/11/16 — three ranks total.
    "ultimate":   (-1, -1, -1, -1, -1, -1, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 2, 2, 2),
}

# Damage-block scaling fields and the CallContext-style attribute they
# multiply against. ``factor`` is the value stored in the damage block
# (treated as a percentage when >0 — ap_pct=50.0 means 50% of AP, so we
# divide by 100 before multiplying).
#
# Maps to ``DamageBlock`` field names (Phase 4a snapshot schema).
_SCALING_TARGETS: tuple[tuple[str, str], ...] = (
    ("total_ad_pct", "total_ad"),
    ("bonus_ad_pct", "bonus_ad"),
    ("ap_pct", "ap"),
    ("caster_max_hp_pct", "caster_max_hp"),
    ("caster_bonus_hp_pct", "caster_bonus_hp"),
    ("target_max_hp_pct", "target_max_hp"),
    ("target_missing_hp_pct", "target_missing_hp"),
    ("target_current_hp_pct", "target_current_hp"),
    ("target_bonus_hp_pct", "target_bonus_hp"),
    ("target_armor_pct", "target_armor"),
    ("bonus_armor_pct", "caster_bonus_armor"),
    ("bonus_mr_pct", "caster_bonus_mr"),
    ("caster_max_mp_pct", "caster_max_mp"),
)

# Valid block-strategies.
_BLOCK_STRATEGIES: frozenset[str] = frozenset({"first", "sum", "max"})


@dataclass(frozen=True)
class AbilityContext:
    """Resolved caster/target stats fed into the per-cast damage formula.

    Mirrors ``effects.CallContext`` but with a name + shape tuned for
    ability evaluation. Decoupled from the auto-attack scorer's
    ``CallContext`` so future Phase 4b/4c changes don't ripple back.
    """
    base_ad: float
    total_ad: float        # base + bonus
    bonus_ad: float
    ap: float
    caster_max_hp: float
    caster_bonus_hp: float
    caster_bonus_armor: float
    caster_bonus_mr: float
    caster_max_mp: float
    caster_mp_regen_per_5: float
    target_armor: float
    target_mr: float
    target_max_hp: float
    target_current_hp: float
    target_missing_hp: float
    target_bonus_hp: float

    @staticmethod
    def from_build(
        stats: dict[str, float],
        base_stats: dict[str, float] | None,
        target_armor: float,
        target_mr: float,
        target_max_hp: float,
        target_bonus_hp: float,
        target_current_hp_pct: float = 1.0,
    ) -> "AbilityContext":
        """Build a context from a resolved champion's ``stats`` dict.

        ``target_current_hp_pct`` is the assumed fraction of target's max
        HP they're sitting at — defaults to 1.0 (full HP). Operators can
        override for ``target_missing_hp_pct`` / ``target_current_hp_pct``
        damage blocks (Eve's R is full at low HP, etc.).
        """
        base = base_stats or {}
        base_ad = float(base.get("ad", 0.0))
        total_ad = float(stats.get("ad", 0.0))
        bonus_ad = max(0.0, total_ad - base_ad)
        caster_max_hp = float(stats.get("hp", 0.0))
        caster_base_hp = float(base.get("hp", 0.0))
        caster_bonus_hp = max(0.0, caster_max_hp - caster_base_hp)
        caster_base_armor = float(base.get("armor", 0.0))
        caster_bonus_armor = max(0.0, float(stats.get("armor", 0.0)) - caster_base_armor)
        caster_base_mr = float(base.get("mr", 0.0))
        caster_bonus_mr = max(0.0, float(stats.get("mr", 0.0)) - caster_base_mr)

        current_pct = max(0.0, min(1.0, target_current_hp_pct))
        target_current_hp = target_max_hp * current_pct
        target_missing_hp = target_max_hp * (1.0 - current_pct)

        return AbilityContext(
            base_ad=base_ad,
            total_ad=total_ad,
            bonus_ad=bonus_ad,
            ap=float(stats.get("ap", 0.0)),
            caster_max_hp=caster_max_hp,
            caster_bonus_hp=caster_bonus_hp,
            caster_bonus_armor=caster_bonus_armor,
            caster_bonus_mr=caster_bonus_mr,
            caster_max_mp=float(stats.get("mp", 0.0)),
            caster_mp_regen_per_5=float(stats.get("mpregen", 0.0)),
            target_armor=float(target_armor),
            target_mr=float(target_mr),
            target_max_hp=float(target_max_hp),
            target_current_hp=target_current_hp,
            target_missing_hp=target_missing_hp,
            target_bonus_hp=float(target_bonus_hp),
        )


def rank_at_level(
    key: str,
    level: int,
    max_priority: Sequence[str] = ("Q", "W", "E"),
) -> int:
    """Return the rank (0-indexed) the spell would have at champion level.

    Uses the canonical "1 ability point per level" distribution with
    priorities: first key in ``max_priority`` is maxed first, second
    is maxed second, third is maxed third. ``R`` is always treated as
    the ultimate and unlocks at lvl 6/11/16.

    Returns ``-1`` when the spell is not yet unlocked at that level —
    consumers treat as zero damage.

    ``key='P'`` is treated as level-scaled passive: returns ``level - 1``
    clamped to [0, 17]. ``DamageBlock.value_at`` clamps further to the
    block's actual length.
    """
    level = clamp_level(level)
    if key == "P":
        return max(0, min(17, level - 1))
    if key == "R":
        return _PRIORITY_TABLES["ultimate"][level]
    if key not in {"Q", "W", "E"}:
        raise ValueError(f"unknown ability key: {key!r}")
    if key not in max_priority:
        # Operator passed an unusual priority list — fall back to a
        # safe rank-0 unlock at lvl 1 (treat as priority_3).
        return _PRIORITY_TABLES["priority_3"][level]
    idx = list(max_priority).index(key)
    table = _PRIORITY_TABLES[f"priority_{idx + 1}"]
    return table[level]


def _mitigation_factor(damage_type: str | None, target_armor: float, target_mr: float) -> float:
    """League's mitigation factor for a damage block.

    Mirrors ``dps._armor_factor`` for both resists. MIXED splits 50/50
    armor/MR (rare; mostly utility abilities). TRUE bypasses all resists.
    Unknown / None defaults to MAGIC routing — most multi-block abilities
    without a form-level damage_type are magical.
    """
    def _resist_factor(resist: float) -> float:
        if resist >= 0:
            return 100.0 / (100.0 + resist)
        return 2.0 - 100.0 / (100.0 - resist)

    dt = (damage_type or "MAGIC").upper()
    if dt == "TRUE":
        return 1.0
    if dt == "PHYSICAL":
        return _resist_factor(target_armor)
    if dt == "MIXED":
        return 0.5 * _resist_factor(target_armor) + 0.5 * _resist_factor(target_mr)
    return _resist_factor(target_mr)  # MAGIC + fallback


def _evaluate_block(
    block: DamageBlock,
    rank: int,
    ctx: AbilityContext,
) -> float:
    """Sum a damage block's contribution at the given rank.

    Base damage is taken directly. Each scaling field is multiplied by
    its corresponding context attribute, divided by 100 (Meraki stores
    percentages as floats, e.g. 50.0 = 50%). Missing fields contribute 0
    via ``DamageBlock.value_at``'s default.
    """
    if rank < 0:
        return 0.0
    total = block.value_at("base", rank)
    for field_name, ctx_attr in _SCALING_TARGETS:
        scaling_pct = block.value_at(field_name, rank)
        if scaling_pct == 0.0:
            continue
        ctx_val = getattr(ctx, ctx_attr, 0.0)
        total += (scaling_pct / 100.0) * ctx_val
    return total


def _select_blocks(
    blocks: tuple[DamageBlock, ...],
    rank: int,
    ctx: AbilityContext,
    strategy: str,
) -> float:
    """Combine damage blocks per the configured strategy."""
    damage_blocks = tuple(b for b in blocks if b.attribute_kind == "damage")
    if not damage_blocks:
        return 0.0
    if strategy == "first":
        return _evaluate_block(damage_blocks[0], rank, ctx)
    evals = [_evaluate_block(b, rank, ctx) for b in damage_blocks]
    if strategy == "max":
        return max(evals) if evals else 0.0
    if strategy == "sum":
        return sum(evals)
    raise ValueError(f"unknown block_strategy: {strategy!r}")


def _form_cooldown_at_rank(form: AbilityForm, rank: int) -> float:
    """Return the cooldown at this rank, or a generous fallback (60s)
    when the form has no per-rank CD data."""
    if form.cooldown is None or not form.cooldown:
        return 60.0
    if rank < 0:
        rank = 0
    if rank >= len(form.cooldown):
        return float(form.cooldown[-1])
    return float(form.cooldown[rank])


def _form_cost_at_rank(form: AbilityForm, rank: int) -> float:
    """Return mana/resource cost at rank, or 0.0 when None / empty."""
    if form.cost is None or not form.cost:
        return 0.0
    if rank < 0:
        rank = 0
    if rank >= len(form.cost):
        return float(form.cost[-1])
    return float(form.cost[rank])


def _mana_uptime_factor(
    cost_per_cast: float,
    cooldown: float,
    ctx: AbilityContext,
    resource: str | None,
) -> float:
    """Fraction of theoretical 1/cooldown rate sustainable by mana regen.

    Only meaningful when the resource is MANA AND the champion has a
    non-zero mana pool AND the cost is non-zero. Energy / manaless /
    HP-cost users return 1.0 (no economy constraint).

    Returns a value in (0, 1]. Used only by the fallback path that
    doesn't have measured rewind data — measured casts/sec already
    encodes mana downtime.
    """
    if resource != "MANA":
        return 1.0
    if cost_per_cast <= 0:
        return 1.0
    if ctx.caster_max_mp <= 0:
        return 1.0
    if cooldown <= 0:
        return 1.0
    # Regen per second from per-5 value.
    regen_per_sec = ctx.caster_mp_regen_per_5 / 5.0
    cost_per_sec_theoretical = cost_per_cast / cooldown
    if cost_per_sec_theoretical <= regen_per_sec:
        return 1.0
    return max(0.05, regen_per_sec / cost_per_sec_theoretical)


# ─── per-spell evaluation ────────────────────────────────────────────────────


@dataclass(frozen=True)
class AbilitySpellDps:
    """Per-spell-key breakdown returned by ``compute_ability_dps``."""
    key: str
    form_name: str
    form_index: int
    rank: int
    cooldown: float
    cost: float
    damage_type: str | None
    resource: str | None
    raw_damage_per_cast: float          # base + all scaling, pre-mode, pre-mitigation
    post_mode_damage_per_cast: float    # × mode_multiplier
    post_mitigation_damage_per_cast: float
    casts_per_sec: float                # measured (if available) or theoretical
    casts_per_sec_source: str           # "measured" | "theoretical_with_mana_uptime" | "missing"
    mana_uptime_factor: float
    dps: float
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "form_name": self.form_name,
            "form_index": self.form_index,
            "rank": self.rank,
            "cooldown": self.cooldown,
            "cost": self.cost,
            "damage_type": self.damage_type,
            "resource": self.resource,
            "raw_damage_per_cast": self.raw_damage_per_cast,
            "post_mode_damage_per_cast": self.post_mode_damage_per_cast,
            "post_mitigation_damage_per_cast": self.post_mitigation_damage_per_cast,
            "casts_per_sec": self.casts_per_sec,
            "casts_per_sec_source": self.casts_per_sec_source,
            "mana_uptime_factor": self.mana_uptime_factor,
            "dps": self.dps,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class AbilityDpsResult:
    """Top-level result from ``compute_ability_dps``."""
    champion_id: str
    champion_name: str
    level: int
    item_ids: tuple[str, ...]
    mode: str
    target_armor: float
    target_mr: float
    target_max_hp: float
    target_bonus_hp: float
    mode_multiplier: float                          # aramDamageDealt; 1.0 outside ARAM
    per_spell: tuple[AbilitySpellDps, ...]
    total_ability_dps: float
    primary_scaling: str                            # "AP" | "AD" | "HP" | "MIXED" | "TRUE"
    max_priority: tuple[str, str, str]
    block_strategy: str
    stats: dict[str, float] = field(default_factory=dict)
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "champion_id": self.champion_id,
            "champion_name": self.champion_name,
            "level": self.level,
            "item_ids": list(self.item_ids),
            "mode": self.mode,
            "target_armor": self.target_armor,
            "target_mr": self.target_mr,
            "target_max_hp": self.target_max_hp,
            "target_bonus_hp": self.target_bonus_hp,
            "mode_multiplier": self.mode_multiplier,
            "per_spell": [s.to_dict() for s in self.per_spell],
            "total_ability_dps": self.total_ability_dps,
            "primary_scaling": self.primary_scaling,
            "max_priority": list(self.max_priority),
            "block_strategy": self.block_strategy,
            "stats": dict(self.stats),
            "notes": list(self.notes),
        }

    def format_table(self) -> str:
        head = (
            f"{self.champion_name} ({self.champion_id}) — lvl {self.level} "
            f"— mode {self.mode}  [MAGE]"
        )
        rows = [head, "-" * len(head)]
        if self.item_ids:
            rows.append(f"items: {', '.join(self.item_ids)}")
        else:
            rows.append("items: (none)")
        rows.append(
            f"target: armor={self.target_armor:.0f}  mr={self.target_mr:.0f}"
            f"  max_hp={self.target_max_hp:.0f}"
        )
        rows.append(
            f"priority: {'>'.join(self.max_priority)}  "
            f"block: {self.block_strategy}  primary_scaling: {self.primary_scaling}"
        )
        rows.append("")
        rows.append(
            f"  {'spell':<6}  {'rank':>4}  {'cd':>5}  {'dpc':>7}  "
            f"{'cps':>6}  {'dps':>7}"
        )
        rows.append("  " + "-" * 60)
        for s in self.per_spell:
            rows.append(
                f"  {s.key + ' ' + s.form_name[:4]:<6}  {s.rank:>4}  "
                f"{s.cooldown:>5.1f}  {s.post_mitigation_damage_per_cast:>7.1f}  "
                f"{s.casts_per_sec:>6.3f}  {s.dps:>7.2f}"
            )
        rows.append("")
        rows.append(f"  total_ability_dps    {self.total_ability_dps:.2f}")
        if self.notes:
            rows.append("")
            for n in self.notes:
                rows.append(f"  note: {n}")
        return "\n".join(rows)


# ─── primary-scaling classifier ──────────────────────────────────────────────


def _classify_primary_scaling(per_spell: Sequence[AbilitySpellDps],
                              forms: Sequence[AbilityForm]) -> str:
    """Identify which stat the champion's abilities mainly scale off.

    Inspects the un-evaluated damage blocks rather than the post-build
    DPS so the classification is stable across builds. Used by Phase 4c
    to route between the mage / bruiser / carry ranker.
    """
    ap_score = 0.0
    ad_score = 0.0
    hp_score = 0.0
    true_score = 0.0
    for form in forms:
        for block in form.damage_blocks:
            if block.attribute_kind != "damage":
                continue
            if block.ap_pct:
                ap_score += sum(block.ap_pct)
            if block.total_ad_pct:
                ad_score += sum(block.total_ad_pct)
            if block.bonus_ad_pct:
                ad_score += sum(block.bonus_ad_pct)
            if block.caster_max_hp_pct:
                hp_score += sum(block.caster_max_hp_pct)
            if block.caster_bonus_hp_pct:
                hp_score += sum(block.caster_bonus_hp_pct)
    # Heuristic: pick the dominant signal.
    scores = {"AP": ap_score, "AD": ad_score, "HP": hp_score}
    top = max(scores, key=lambda k: scores[k])
    if scores[top] <= 0:
        # No scaling found — could be all-base or unparsed.
        return "MIXED"
    if scores[top] < 1.5 * sum(v for k, v in scores.items() if k != top):
        return "MIXED"
    return top


# ─── top-level compute ───────────────────────────────────────────────────────


def compute_ability_dps(
    snapshot: DataSnapshot,
    champion_id: str,
    level: int,
    item_ids: Optional[Iterable[str | int]] = None,
    mode: str = "SR",
    target_armor: float = 0.0,
    target_mr: float = 0.0,
    target_max_hp: float = 0.0,
    target_bonus_hp: float = 0.0,
    target_current_hp_pct: float = 1.0,
    augments: Optional[Iterable] = None,
    abilities_snapshot: Optional[AbilitiesSnapshot] = None,
    max_priority: tuple[str, str, str] = ("Q", "W", "E"),
    block_strategy: str = "first",
    form_index_overrides: Optional[dict[str, int]] = None,
) -> AbilityDpsResult:
    """Compute total ability DPS for the resolved build.

    Mirror of ``compute_dps``'s contract — same ``snapshot``, ``mode``,
    ``target_*``, and ``augments`` plumbing — but the result decomposes by
    spell key instead of by rotation phase.

    Parameters
    ----------
    target_current_hp_pct:
        Assumed fraction of max HP the target sits at when the cast lands
        (default 1.0 = full HP). Affects ``target_missing_hp_pct`` /
        ``target_current_hp_pct`` blocks only.
    abilities_snapshot:
        Optional override — defaults to the lazy-cached snapshot from
        ``abilities.load_default()``. Test fixtures pass synthetic ones.
    max_priority:
        Tuple of three ability keys (e.g. ``("Q", "W", "E")``) describing
        max order — first key is maxed first, third last. Default Q-W-E.
    block_strategy:
        How to combine multi-block abilities — ``"first"`` (default),
        ``"sum"``, or ``"max"``. See module docstring for rationale.
    form_index_overrides:
        Per-key form index overrides — e.g. ``{"Q": 2}`` to evaluate
        Aphelios's Q with the 3rd weapon stance. Default 0 for all keys.
    """
    if block_strategy not in _BLOCK_STRATEGIES:
        raise ValueError(
            f"block_strategy must be one of {_BLOCK_STRATEGIES}, "
            f"got {block_strategy!r}"
        )
    if set(max_priority) != {"Q", "W", "E"}:
        raise ValueError(
            f"max_priority must be a permutation of (Q, W, E), got {max_priority!r}"
        )
    if not 0.0 <= target_current_hp_pct <= 1.0:
        raise ValueError(
            f"target_current_hp_pct must be in [0,1], got {target_current_hp_pct}"
        )

    level = clamp_level(level)

    # Load ability data; defer the import-time cost to the first call.
    abil_snap = abilities_snapshot
    if abil_snap is None:
        from .abilities import load_default  # local import keeps test fixtures cheap
        try:
            abil_snap = load_default()
        except AbilitiesNotFound as e:
            # Surface a structured 0-result with a single note rather than
            # crashing — the server can return a body explaining the missing
            # snapshot.
            return _empty_result(
                snapshot, champion_id, level, item_ids, mode,
                target_armor, target_mr, target_max_hp, target_bonus_hp,
                max_priority, block_strategy,
                note=f"abilities snapshot missing: {e}",
            )

    # Resolve build stats. Reuses the same engine pipeline as compute_dps.
    resolved = build_champion(
        snapshot, champion_id, level, item_ids=item_ids, mode=mode,
        augments=augments,
    )

    # Mode damage multiplier (ARAM aramDamageDealt only — EHP scorer uses
    # aramDamageTaken on the receiving side).
    champ_rec = snapshot.champion(resolved.champion_id)
    aram = ((champ_rec.get("lolmath") or {}).get("aram_modifiers") or {})
    mode_mult = 1.0
    if mode == "ARAM":
        mode_mult = float(aram.get("aramDamageDealt", 1.0))

    # Build ability context.
    ctx = AbilityContext.from_build(
        stats=resolved.stats,
        base_stats=resolved.base_stats,
        target_armor=target_armor,
        target_mr=target_mr,
        target_max_hp=target_max_hp,
        target_bonus_hp=target_bonus_hp,
        target_current_hp_pct=target_current_hp_pct,
    )

    # Mirror the AP cross-derivations + damage amps that ``compute_dps``
    # applies (Phase 4 batches 14/15/19/32/34/38/54/56). Without this,
    # Rabadon's 30% AP amp / Liandry's 6% damage amp / Abyssal Mask
    # magic amp would be invisible to the ability scorer — making item
    # rankings disagree with the auto-attack DPS scorer for no good
    # reason. All amps preserve the same precedence as compute_dps:
    #   ap += ap_from_hp + stacked_ap
    #   ap *= ap_amp (Rabadon's)
    #   ap *= hp_ap_amp (Demonic Embrace HP-scaled)
    # then per-cast damage flows through:
    #   damage *= damage_amp (Riftmaker/Liandry's)
    #   damage *= target_bonus_hp_amp (LDR Giant Slayer @ bonus HP)
    #   damage *= giant_slayer_amp (Perplexity @ max HP diff)
    # plus magic-only damage gets an extra ``magic_amp`` (Abyssal Mask)
    # applied inside the per-spell loop based on the form's damage_type.
    item_effects = collect_effects(resolved.item_ids)
    ap_from_hp = total_bonus_ap_from_hp(item_effects, ctx.caster_bonus_hp)
    stacked_ap = total_stacked_ap(item_effects)
    ap_total = ctx.ap + ap_from_hp + stacked_ap
    ap_amp = total_ap_amp_multiplier(item_effects)
    if ap_amp != 1.0:
        ap_total *= ap_amp
    hp_ap_amp = total_caster_hp_scaled_ap_amp(item_effects, ctx.caster_max_hp)
    if hp_ap_amp != 1.0:
        ap_total *= hp_ap_amp
    # Replace ctx with a copy carrying the boosted AP. AbilityContext is
    # frozen — use dataclasses.replace.
    ctx = replace(ctx, ap=ap_total)

    # Build-wide damage amps applied at per-cast level (not per-spell —
    # amps don't discriminate between Q and W). Folded into ``damage_amp``
    # which multiplies the post-mitigation per-cast damage.
    damage_amp = total_damage_amp_multiplier(item_effects)
    damage_amp *= total_target_bonus_hp_amp_multiplier(item_effects, target_bonus_hp)
    damage_amp *= total_giant_slayer_multiplier(
        item_effects, target_max_hp, ctx.caster_max_hp,
    )
    magic_amp = total_magic_amp_multiplier(item_effects)

    # Effective resists: pre-reduction-and-pen pipeline mirrors compute_dps
    # (armor reduction → flat pen → % pen). Lethality flows through
    # ``effective_target_armor`` via per-item ``lethality`` fields. Magic
    # has the symmetric pipeline (Void Staff %, Sorcerer's Shoes flat).
    target_armor_eff = effective_target_armor(target_armor, item_effects, level)
    target_mr_eff = effective_target_mr(target_mr, item_effects)

    # Resolve forms for Q/W/E/R. Champions may lack a key in the snapshot
    # — surface a zero spell rather than raising so partial coverage is
    # tolerated.
    if not abil_snap.has_champion(resolved.champion_id):
        return _empty_result(
            snapshot, resolved.champion_id, level, item_ids, mode,
            target_armor, target_mr, target_max_hp, target_bonus_hp,
            max_priority, block_strategy,
            champion_name=resolved.champion_name,
            note=f"champion {resolved.champion_id!r} absent from abilities snapshot",
        )
    per_key_forms = abil_snap.get_abilities(resolved.champion_id)
    overrides = form_index_overrides or {}

    per_spell: list[AbilitySpellDps] = []
    forms_for_classification: list[AbilityForm] = []
    for key in SPELL_KEYS:
        forms = per_key_forms.get(key, ())
        if not forms:
            per_spell.append(_zero_spell(key, "missing", -1, notes=(
                f"no {key} ability recorded for {resolved.champion_id} — skipped",
            )))
            continue
        form_idx = overrides.get(key, 0)
        if form_idx < 0 or form_idx >= len(forms):
            form_idx = 0
        form = forms[form_idx]
        forms_for_classification.append(form)
        rank = rank_at_level(key, level, max_priority=max_priority)
        if rank < 0:
            per_spell.append(_zero_spell(
                key, form.name, form_idx,
                notes=(f"{key} locked at level {level}",),
            ))
            continue
        cooldown = _form_cooldown_at_rank(form, rank)
        cost = _form_cost_at_rank(form, rank)
        raw_dpc = _select_blocks(form.damage_blocks, rank, ctx, block_strategy)
        post_mode = raw_dpc * mode_mult
        # Per-spell magic_amp only applies to magic damage (Abyssal Mask
        # Unmake doesn't touch physical Garen Q or true Talon E).
        dt = (form.damage_type or "MAGIC").upper()
        spell_magic_amp = magic_amp if dt == "MAGIC" else 1.0
        # Build-wide damage_amp + spell-magic_amp scale per-cast pre-mit.
        post_amps = post_mode * damage_amp * spell_magic_amp
        mit_factor = _mitigation_factor(form.damage_type, target_armor_eff, target_mr_eff)
        post_mit = post_amps * mit_factor

        measured = get_spell_casts_per_sec(resolved.champion_name, key, mode)
        cps_source = "measured"
        mana_uptime = 1.0
        if measured <= 0:
            theoretical = (1.0 / cooldown) if cooldown > 0 else 0.0
            mana_uptime = _mana_uptime_factor(cost, cooldown, ctx, form.resource)
            measured = theoretical * mana_uptime
            cps_source = "theoretical_with_mana_uptime" if theoretical > 0 else "missing"

        dps = post_mit * measured
        per_spell.append(AbilitySpellDps(
            key=key,
            form_name=form.name,
            form_index=form_idx,
            rank=rank,
            cooldown=cooldown,
            cost=cost,
            damage_type=form.damage_type,
            resource=form.resource,
            raw_damage_per_cast=raw_dpc,
            post_mode_damage_per_cast=post_mode,
            post_mitigation_damage_per_cast=post_mit,
            casts_per_sec=measured,
            casts_per_sec_source=cps_source,
            mana_uptime_factor=mana_uptime,
            dps=dps,
        ))

    total_dps = sum(s.dps for s in per_spell)
    primary = _classify_primary_scaling(per_spell, forms_for_classification)

    notes: list[str] = list(resolved.notes)
    if mode == "ARAM" and mode_mult != 1.0:
        notes.append(f"ARAM aramDamageDealt={mode_mult:.3f} on per-cast damage")
    n_missing = sum(1 for s in per_spell if s.casts_per_sec_source == "missing")
    if n_missing:
        notes.append(
            f"{n_missing}/4 spells had no measured cast rate AND no cooldown "
            "fallback — DPS contribution is 0"
        )
    n_theoretical = sum(1 for s in per_spell if s.casts_per_sec_source == "theoretical_with_mana_uptime")
    if n_theoretical:
        notes.append(
            f"{n_theoretical}/4 spells used theoretical 1/cooldown × mana_uptime "
            f"(no measured rewind data for {resolved.champion_name} × {mode})"
        )
    if ap_amp != 1.0:
        notes.append(
            f"AP amplified ×{ap_amp:.3f} by item amp (effective AP for ability "
            f"scaling: {ap_total:.1f})"
        )
    if hp_ap_amp != 1.0:
        notes.append(
            f"AP HP-scaled amp ×{hp_ap_amp:.3f} (Demonic Embrace at "
            f"{ctx.caster_max_hp:.0f} HP)"
        )
    if ap_from_hp > 0:
        notes.append(
            f"AP cross-derived from bonus HP: +{ap_from_hp:.1f} "
            "(Riftmaker Void Infusion)"
        )
    if stacked_ap > 0:
        notes.append(f"Mejai's stacked AP: +{stacked_ap:.0f}")
    if damage_amp != 1.0:
        notes.append(
            f"build damage amp ×{damage_amp:.3f} "
            f"(+{(damage_amp - 1.0) * 100:.1f}% to all ability damage)"
        )
    if magic_amp != 1.0:
        notes.append(
            f"magic damage amp ×{magic_amp:.3f} on magic-typed spells "
            "(Abyssal Mask Unmake)"
        )
    if target_armor_eff != target_armor:
        notes.append(
            f"effective target armor {target_armor:.1f} → {target_armor_eff:.1f} "
            "after reduction + lethality + % pen"
        )
    if target_mr_eff != target_mr:
        notes.append(
            f"effective target MR {target_mr:.1f} → {target_mr_eff:.1f} "
            "after flat + % magic pen"
        )

    return AbilityDpsResult(
        champion_id=resolved.champion_id,
        champion_name=resolved.champion_name,
        level=level,
        item_ids=resolved.item_ids,
        mode=mode,
        target_armor=target_armor,
        target_mr=target_mr,
        target_max_hp=target_max_hp,
        target_bonus_hp=target_bonus_hp,
        mode_multiplier=mode_mult,
        per_spell=tuple(per_spell),
        total_ability_dps=total_dps,
        primary_scaling=primary,
        max_priority=tuple(max_priority),
        block_strategy=block_strategy,
        stats=dict(resolved.stats),
        notes=tuple(notes),
    )


# ─── helpers for partial / empty results ──────────────────────────────────────


def _zero_spell(key: str, form_name: str, form_index: int,
                notes: tuple[str, ...] = ()) -> AbilitySpellDps:
    return AbilitySpellDps(
        key=key, form_name=form_name, form_index=form_index, rank=-1,
        cooldown=0.0, cost=0.0, damage_type=None, resource=None,
        raw_damage_per_cast=0.0, post_mode_damage_per_cast=0.0,
        post_mitigation_damage_per_cast=0.0,
        casts_per_sec=0.0, casts_per_sec_source="missing",
        mana_uptime_factor=1.0, dps=0.0, notes=notes,
    )


def _empty_result(
    snapshot: DataSnapshot,
    champion_id: str,
    level: int,
    item_ids: Optional[Iterable[str | int]],
    mode: str,
    target_armor: float,
    target_mr: float,
    target_max_hp: float,
    target_bonus_hp: float,
    max_priority: tuple[str, str, str],
    block_strategy: str,
    *,
    champion_name: str | None = None,
    note: str = "",
) -> AbilityDpsResult:
    """Build a structured zero-DPS result when ability data is missing.

    Surfaces the cause via ``notes`` so consumers can disambiguate
    "no data" from "0 DPS". Used by ``compute_ability_dps`` when the
    snapshot can't be loaded or the champion is absent.
    """
    name = champion_name or champion_id
    items = tuple(str(i) for i in (item_ids or ()))
    per_spell = tuple(
        _zero_spell(k, "missing", -1, notes=("ability data unavailable",))
        for k in SPELL_KEYS
    )
    return AbilityDpsResult(
        champion_id=champion_id, champion_name=name, level=level,
        item_ids=items, mode=mode,
        target_armor=target_armor, target_mr=target_mr,
        target_max_hp=target_max_hp, target_bonus_hp=target_bonus_hp,
        mode_multiplier=1.0, per_spell=per_spell, total_ability_dps=0.0,
        primary_scaling="MIXED",
        max_priority=tuple(max_priority),
        block_strategy=block_strategy,
        stats={},
        notes=(note,) if note else (),
    )
