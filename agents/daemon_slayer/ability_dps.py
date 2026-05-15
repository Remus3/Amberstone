"""Phase 4b + 4c (s178/s179, 2026-05-12) — Mage ability DPS scorer.

Sibling of ``dps.py``. ``compute_ability_dps()`` returns the caster's
per-spell ability DPS (and total) for a resolved build at a given level.
``rank_items_by_ability_dps()`` (Phase 4c, s179) drives the ``/rank-mage``
ranker — same candidate-filtering pipeline as the DPS/EHP/hybrid
scorers, but each candidate is scored by total ability-DPS gain over
the baseline rather than by auto-attack DPS or blended EHP.

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
first damage block of the canonical form_index=0 contributes. Phase 5.9
(s191, 2026-05-14) layered a per-(champion, key) ``block_index_overrides``
registry on top — ``champion_block_index.json`` ships defaults for
Cassiopeia E (poisoned-target enhanced), Anivia E (chilled-target
enhanced), Diana W (all-orbs total), Veigar R (executed-target maximum),
Brand W (CC'd-target increased), etc. When a key is in the resolved
override map, the engine switches to the new ``"indexed"`` strategy with
that specific block; keys without an entry honor the global strategy.

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

import json
import threading
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Iterable, Optional, Sequence

from .abilities import (
    AbilitiesNotFound,
    AbilitiesSnapshot,
    AbilityForm,
    DamageBlock,
)
from .data_loader import DataSnapshot
from .effects import (
    ITEM_EFFECTS,
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
from .rank import (
    DEFAULT_SLOT_COUNT,
    DEFAULT_TOP_N,
    SORT_KEYS,
    _filter_candidates,
    _is_terminal,
    strip_arena_trinkets,
)
from .stats import clamp_level
from .ult_rates import get_spell_casts_per_sec

# Canonical 4-active-spell set. Passive (P) is intentionally excluded —
# the ``compute_dps`` auto-attack scorer covers on-hit passives, and
# level-scaled passive damage doesn't fit the per-rank model.
SPELL_KEYS: tuple[str, ...] = ("Q", "W", "E", "R")

# Standard max-priority rank tables (0-indexed rank at champion level).
# Pin to the conventional "Q-first, W-second, E-third" max order; Phase 4d
# (s185) ships per-champion overrides via ``champion_max_priority.json``
# loaded by ``get_max_priority_for`` below.
_PRIORITY_TABLES: dict[str, tuple[int, ...]] = {
    # Indexed 1-18 (idx 0 unused so lookup reads naturally).
    "priority_1": (-1, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4),
    "priority_2": (-1, -1, 0, 0, 0, 0, 0, 0, 1, 1, 2, 2, 3, 4, 4, 4, 4, 4, 4),
    "priority_3": (-1, -1, -1, -1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 2, 2, 3, 4),
    # R unlocks at 6/11/16 — three ranks total.
    "ultimate":   (-1, -1, -1, -1, -1, -1, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 2, 2, 2),
}

DEFAULT_MAX_PRIORITY: tuple[str, str, str] = ("Q", "W", "E")

# Phase 4d (s185, 2026-05-13) — per-champion max_priority override registry.
# Sibling of ``hybrid._load_archetype_weights``; same lazy-cache pattern. The
# JSON file lives next to this module and is shipped with the engine — not
# patch-versioned, since the override reflects a champion's kit identity not
# a patch-time stat tweak.
_MAX_PRIORITY_PATH = Path(__file__).resolve().parent / "champion_max_priority.json"
_MAX_PRIORITY_LOCK = threading.Lock()
_MAX_PRIORITY_CACHE: Optional[dict] = None


def _load_max_priority_table() -> dict:
    """Load the per-champion max_priority override table from disk.

    Singleton cache for the process lifetime. Tests can call
    ``reset_max_priority_cache()`` to force a re-read after mutating
    the on-disk file.
    """
    global _MAX_PRIORITY_CACHE
    with _MAX_PRIORITY_LOCK:
        if _MAX_PRIORITY_CACHE is None:
            _MAX_PRIORITY_CACHE = json.loads(
                _MAX_PRIORITY_PATH.read_text(encoding="utf-8")
            )
        return _MAX_PRIORITY_CACHE


def reset_max_priority_cache() -> None:
    """Clear the singleton cache — for tests that mutate the on-disk file."""
    global _MAX_PRIORITY_CACHE
    with _MAX_PRIORITY_LOCK:
        _MAX_PRIORITY_CACHE = None


def get_max_priority_for(champion_id: str) -> tuple[tuple[str, str, str], str]:
    """Return ``(priority_tuple, source)`` for ``champion_id``.

    ``champion_id`` is the DDragon canonical id (e.g. ``"Cassiopeia"``,
    ``"TwistedFate"``). Source is ``"champion"`` for an explicit override
    or ``"default"`` for the table fallback.
    """
    table = _load_max_priority_table()
    overrides = table.get("champions") or {}
    if champion_id in overrides:
        seq = overrides[champion_id]
        if not isinstance(seq, (list, tuple)) or len(seq) != 3:
            raise ValueError(
                f"champion_max_priority.json: {champion_id!r} must map to a "
                f"3-key list, got {seq!r}"
            )
        keys = tuple(str(s).upper() for s in seq)
        if set(keys) != {"Q", "W", "E"}:
            raise ValueError(
                f"champion_max_priority.json: {champion_id!r} -> {seq!r} is "
                f"not a permutation of (Q, W, E)"
            )
        return (keys, "champion")  # type: ignore[return-value]
    default_seq = table.get("default") or list(DEFAULT_MAX_PRIORITY)
    keys = tuple(str(s).upper() for s in default_seq)
    return (keys, "default")  # type: ignore[return-value]


def _resolve_max_priority(
    champion_id: str,
    explicit: Optional[Sequence[str]],
) -> tuple[tuple[str, str, str], str]:
    """Resolve max_priority from caller input + override registry.

    Returns ``(priority_tuple, source)`` where source is:
      * ``"override"`` — caller passed an explicit value
      * ``"champion"`` — override table had an entry for the champion
      * ``"default"`` — fell back to the table default ("Q", "W", "E")
    """
    if explicit is not None:
        keys = tuple(str(k).upper() for k in explicit)
        if len(keys) != 3 or set(keys) != {"Q", "W", "E"}:
            raise ValueError(
                f"max_priority must be a permutation of (Q, W, E), got {explicit!r}"
            )
        return (keys, "override")  # type: ignore[return-value]
    return get_max_priority_for(champion_id)


# Phase 4e (s187, 2026-05-13) — per-(champion, key) form_index registry.
# Multi-form champions (Nidalee cougar, Elise spider, Jayce cannon, Hwei
# damage forms, LeeSin Q-recast) need a non-zero form_index by default
# because their form 0 either has no damage blocks (Hwei "Subject:" stance
# setups) or weaker scaling than a later form (Nidalee Takedown's 5 blocks
# vs Javelin Toss's 2). Loader pattern mirrors champion_max_priority.json.
_FORM_INDEX_PATH = Path(__file__).resolve().parent / "champion_form_index.json"
_FORM_INDEX_LOCK = threading.Lock()
_FORM_INDEX_CACHE: Optional[dict] = None


def _load_form_index_table() -> dict:
    """Load the per-champion form_index override table from disk.

    Singleton cache. Tests can call ``reset_form_index_cache()`` to force
    a re-read after mutating the on-disk file.
    """
    global _FORM_INDEX_CACHE
    with _FORM_INDEX_LOCK:
        if _FORM_INDEX_CACHE is None:
            _FORM_INDEX_CACHE = json.loads(
                _FORM_INDEX_PATH.read_text(encoding="utf-8")
            )
        return _FORM_INDEX_CACHE


def reset_form_index_cache() -> None:
    """Clear the singleton cache — for tests that mutate the on-disk file."""
    global _FORM_INDEX_CACHE
    with _FORM_INDEX_LOCK:
        _FORM_INDEX_CACHE = None


def get_form_index_for(champion_id: str) -> tuple[dict[str, int], str]:
    """Return ``(form_index_map, source)`` for ``champion_id``.

    Source is ``"champion"`` if the registry has an entry, ``"default"``
    if it fell back to an empty map (form 0 for all keys).
    """
    table = _load_form_index_table()
    overrides = table.get("champions") or {}
    if champion_id in overrides:
        raw = overrides[champion_id]
        if not isinstance(raw, dict):
            raise ValueError(
                f"champion_form_index.json: {champion_id!r} must map to a "
                f"dict, got {raw!r}"
            )
        mapping = {str(k).upper(): int(v) for k, v in raw.items()}
        return (mapping, "champion")
    return ({}, "default")


def _resolve_form_index_overrides(
    champion_id: str,
    explicit: Optional[dict[str, int]],
) -> tuple[dict[str, int], str]:
    """Resolve form_index_overrides from caller input + registry.

    Registry provides the per-champion default; caller's dict (if any) is
    merged in with caller winning per-key. Returns ``(merged, source)``:

      * ``"override"`` — caller passed any explicit value
      * ``"champion"`` — registry entry used, caller passed None
      * ``"default"`` — empty dict, no registry entry, no caller input
    """
    registry_map, registry_source = get_form_index_for(champion_id)
    if explicit is None:
        return (registry_map, registry_source)
    # Caller wins per-key; registry fills the gaps.
    merged: dict[str, int] = dict(registry_map)
    for k, v in explicit.items():
        merged[str(k).upper()] = int(v)
    return (merged, "override")


# Phase 5.9 (s191, 2026-05-14) — per-(champion, key) block_index registry.
# A minority of champions have a later damage block that represents the
# realistic burst-window value: Cassi E block1 "Total Enhanced" (vs
# poisoned), Anivia E block1 "Enhanced" (vs chilled), Diana W block2
# "Total Magic Damage" (all 3 orbs), Veigar R block1 "Maximum" (executed
# target), etc. Default block_index=0 preserves pre-s191 behavior for
# the ~95% of champions with single-block forms. Loader pattern mirrors
# champion_form_index.json.
_BLOCK_INDEX_PATH = Path(__file__).resolve().parent / "champion_block_index.json"
_BLOCK_INDEX_LOCK = threading.Lock()
_BLOCK_INDEX_CACHE: Optional[dict] = None


def _load_block_index_table() -> dict:
    """Load the per-(champion, key) block_index override table from disk.

    Singleton cache. Tests can call ``reset_block_index_cache()`` to force
    a re-read after mutating the on-disk file.
    """
    global _BLOCK_INDEX_CACHE
    with _BLOCK_INDEX_LOCK:
        if _BLOCK_INDEX_CACHE is None:
            _BLOCK_INDEX_CACHE = json.loads(
                _BLOCK_INDEX_PATH.read_text(encoding="utf-8")
            )
        return _BLOCK_INDEX_CACHE


def reset_block_index_cache() -> None:
    """Clear the singleton cache — for tests that mutate the on-disk file."""
    global _BLOCK_INDEX_CACHE
    with _BLOCK_INDEX_LOCK:
        _BLOCK_INDEX_CACHE = None


def _normalize_block_index_value(v) -> int | list[int]:
    """Coerce a JSON-loaded block_index value to int or list[int].

    Phase 5.9.20 (s207): registry values may be int (pre-s207 schema —
    single block per key) or list[int] (sum-of-blocks — Camille W /
    Malphite W / Heimerdinger W / Katarina R seed entries). Validates
    shape; raises ValueError on anything else.
    """
    if isinstance(v, bool):
        # Guard: bool is an int subtype; reject it as a registry value.
        raise ValueError(f"block_index value must be int or list[int], got bool {v!r}")
    if isinstance(v, int):
        return v
    if isinstance(v, list):
        out: list[int] = []
        for x in v:
            if isinstance(x, bool) or not isinstance(x, int):
                raise ValueError(
                    f"block_index list element must be int, got {x!r}"
                )
            out.append(x)
        return out
    raise ValueError(f"block_index value must be int or list[int], got {v!r}")


def get_block_index_for(champion_id: str) -> tuple[dict[str, int | list[int]], str]:
    """Return ``(block_index_map, source)`` for ``champion_id``.

    Source is ``"champion"`` if the registry has an entry, ``"default"``
    if it fell back to an empty map (block 0 for all keys).

    Phase 5.9.20 (s207): map values may now be int OR list[int]; lists
    express sum-of-blocks (operator-commits-to-all-components) entries.
    """
    table = _load_block_index_table()
    overrides = table.get("champions") or {}
    if champion_id in overrides:
        raw = overrides[champion_id]
        if not isinstance(raw, dict):
            raise ValueError(
                f"champion_block_index.json: {champion_id!r} must map to a "
                f"dict, got {raw!r}"
            )
        mapping: dict[str, int | list[int]] = {
            str(k).upper(): _normalize_block_index_value(v) for k, v in raw.items()
        }
        return (mapping, "champion")
    return ({}, "default")


def _resolve_block_index_overrides(
    champion_id: str,
    explicit: Optional[dict[str, int | list[int]]],
) -> tuple[dict[str, int | list[int]], str]:
    """Resolve block_index_overrides from caller input + registry.

    Registry provides the per-(champion, key) default; caller's dict
    (if any) is merged in with caller winning per-key. Returns
    ``(merged, source)``:

      * ``"override"`` — caller passed any explicit value
      * ``"champion"`` — registry entry used, caller passed None
      * ``"default"`` — empty dict, no registry entry, no caller input

    Phase 5.9.20 (s207): caller values may be int OR list[int]; both
    pass through ``_normalize_block_index_value`` for validation.
    """
    registry_map, registry_source = get_block_index_for(champion_id)
    if explicit is None:
        return (registry_map, registry_source)
    # Caller wins per-key; registry fills the gaps.
    merged: dict[str, int | list[int]] = dict(registry_map)
    for k, v in explicit.items():
        merged[str(k).upper()] = _normalize_block_index_value(v)
    return (merged, "override")


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

# Valid block-strategies. Phase 5.9 (s191) added ``"indexed"`` — pick a
# specific damage-block index per spell key via ``block_index_overrides``.
# The ``compute_*`` callers transparently switch to ``"indexed"`` for keys
# present in the resolved override map; keys without an entry fall back to
# the caller-supplied global ``block_strategy``.
_BLOCK_STRATEGIES: frozenset[str] = frozenset({"first", "sum", "max", "indexed"})


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
    block_index: int | Sequence[int] = 0,
) -> float:
    """Combine damage blocks per the configured strategy.

    ``block_index`` is consulted only when ``strategy == "indexed"`` (added
    in Phase 5.9, s191). For ``"first"`` it is ignored (block 0 always
    used); for ``"max"`` / ``"sum"`` it is also ignored (all blocks
    aggregated). Out-of-range indexes clamp to the last available damage
    block, preserving forward-compat with future patches that may add
    extra blocks to existing forms.

    Phase 5.9.20 (s207, 2026-05-14): ``block_index`` may now be an int OR
    a sequence of ints. When a sequence is supplied under ``"indexed"``
    strategy, the evaluated damage at each (clamped) index is summed —
    used to express "operator commits to landing every component" cases
    where the realistic single-target damage is the sum across multiple
    Meraki blocks (Camille W base + outer-cone, Malphite W active cast
    + first-AA bonus, Heimerdinger W initial + 4 subsequent rockets,
    Katarina R full physical + magic dagger volleys). An empty sequence
    returns 0.0. Single-int callers retain identical pre-s207 behavior.
    """
    damage_blocks = tuple(b for b in blocks if b.attribute_kind == "damage")
    if not damage_blocks:
        return 0.0
    if strategy == "first":
        return _evaluate_block(damage_blocks[0], rank, ctx)
    if strategy == "indexed":
        if isinstance(block_index, int):
            indices: tuple[int, ...] = (block_index,)
        else:
            indices = tuple(int(x) for x in block_index)
        if not indices:
            return 0.0
        total = 0.0
        for raw_idx in indices:
            idx = raw_idx
            if idx < 0:
                idx = 0
            if idx >= len(damage_blocks):
                idx = len(damage_blocks) - 1
            total += _evaluate_block(damage_blocks[idx], rank, ctx)
        return total
    evals = [_evaluate_block(b, rank, ctx) for b in damage_blocks]
    if strategy == "max":
        return max(evals) if evals else 0.0
    if strategy == "sum":
        return sum(evals)
    raise ValueError(f"unknown block_strategy: {strategy!r}")


def _form_cooldown_at_rank(
    form: AbilityForm,
    rank: int,
    fallback_form: AbilityForm | None = None,
) -> float:
    """Return the cooldown at this rank.

    Phase 5.9.19 (s206, 2026-05-14): when ``form`` has no per-rank CD data
    (Meraki snapshots set ``cooldown=None`` for every non-form-0 entry of a
    form-swap ability — Riven R / Renekton E / AurelionSol R / Qiyana Q
    etc.), inherit from ``fallback_form`` (typically form 0) which carries
    the canonical CD list. Form-swap mechanics share the actual game CD
    with their parent form, so inheritance is correct.

    Final fallback: 60s generic default (preserves pre-s206 behavior when
    no fallback is available — single-form abilities with malformed CD).
    """
    if form.cooldown:
        if rank < 0:
            rank = 0
        if rank >= len(form.cooldown):
            return float(form.cooldown[-1])
        return float(form.cooldown[rank])
    if fallback_form is not None and fallback_form.cooldown:
        if rank < 0:
            rank = 0
        if rank >= len(fallback_form.cooldown):
            return float(fallback_form.cooldown[-1])
        return float(fallback_form.cooldown[rank])
    return 60.0


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
    max_priority_source: str = "default"            # "override" | "champion" | "default"
    form_index_source: str = "default"              # "override" | "champion" | "default"
    form_index_resolved: dict[str, int] = field(default_factory=dict)
    block_index_source: str = "default"             # "override" | "champion" | "default"
    block_index_resolved: dict[str, int] = field(default_factory=dict)
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
            "max_priority_source": self.max_priority_source,
            "block_strategy": self.block_strategy,
            "form_index_source": self.form_index_source,
            "form_index_resolved": dict(self.form_index_resolved),
            "block_index_source": self.block_index_source,
            "block_index_resolved": dict(self.block_index_resolved),
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
    max_priority: Optional[Sequence[str]] = None,
    block_strategy: str = "first",
    form_index_overrides: Optional[dict[str, int]] = None,
    block_index_overrides: Optional[dict[str, int | list[int]]] = None,
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
        Optional three ability keys (e.g. ``("E", "Q", "W")``) describing
        max order — first key is maxed first, third last. When ``None``,
        the per-champion override registry (``champion_max_priority.json``)
        is consulted; falls back to Q-W-E for unmapped champions.
    block_strategy:
        Global strategy for multi-block abilities — ``"first"`` (default),
        ``"sum"``, ``"max"``, or ``"indexed"``. Per-key overrides via
        ``block_index_overrides`` switch a specific key to ``"indexed"``
        with the supplied block_index; keys without an entry fall back to
        the global strategy. See module docstring for rationale.
    form_index_overrides:
        Per-key form index overrides — e.g. ``{"Q": 2}`` to evaluate
        Aphelios's Q with the 3rd weapon stance. Default 0 for all keys.
    block_index_overrides:
        Per-key damage-block index overrides — e.g. ``{"E": 1}`` to evaluate
        Cassiopeia E's "Total Enhanced Damage" block instead of the default
        "Bonus Magic Damage" block0. When ``None``, the per-champion override
        registry (``champion_block_index.json``) is consulted; falls back
        to block 0 for unmapped (champion, key) pairs.
    """
    if block_strategy not in _BLOCK_STRATEGIES:
        raise ValueError(
            f"block_strategy must be one of {_BLOCK_STRATEGIES}, "
            f"got {block_strategy!r}"
        )
    max_priority, max_priority_source = _resolve_max_priority(champion_id, max_priority)
    form_index_overrides, form_index_source = _resolve_form_index_overrides(
        champion_id, form_index_overrides,
    )
    block_index_overrides, block_index_source = _resolve_block_index_overrides(
        champion_id, block_index_overrides,
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
                max_priority_source=max_priority_source,
                form_index_source=form_index_source,
                form_index_resolved=form_index_overrides,
                block_index_source=block_index_source,
                block_index_resolved=block_index_overrides,
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
            max_priority_source=max_priority_source,
            form_index_source=form_index_source,
            form_index_resolved=form_index_overrides,
            block_index_source=block_index_source,
            block_index_resolved=block_index_overrides,
            champion_name=resolved.champion_name,
            note=f"champion {resolved.champion_id!r} absent from abilities snapshot",
        )
    per_key_forms = abil_snap.get_abilities(resolved.champion_id)
    overrides = form_index_overrides or {}
    block_overrides = block_index_overrides or {}

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
        # Phase 5.9.19 (s206): when form_idx != 0, pass form 0 as fallback
        # so non-form-0 entries with cooldown=None inherit from the parent
        # form's CD list (Riven R / Renekton E / AurelionSol R / Qiyana Q).
        fallback = forms[0] if form_idx != 0 else None
        cooldown = _form_cooldown_at_rank(form, rank, fallback_form=fallback)
        cost = _form_cost_at_rank(form, rank)
        # Phase 5.9 (s191): if this key has a block_index override (caller
        # or per-(champion, key) registry), switch to "indexed" strategy
        # with that specific block; otherwise honor the global block_strategy.
        if key in block_overrides:
            raw_dpc = _select_blocks(
                form.damage_blocks, rank, ctx, "indexed",
                block_index=block_overrides[key],
            )
        else:
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

    if block_overrides:
        notes.append(
            "block_index overrides applied: "
            + ", ".join(f"{k}={block_overrides[k]}" for k in sorted(block_overrides))
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
        max_priority_source=max_priority_source,
        block_strategy=block_strategy,
        form_index_source=form_index_source,
        form_index_resolved=dict(form_index_overrides),
        block_index_source=block_index_source,
        block_index_resolved=dict(block_index_overrides),
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
    max_priority_source: str = "default",
    form_index_source: str = "default",
    form_index_resolved: Optional[dict[str, int]] = None,
    block_index_source: str = "default",
    block_index_resolved: Optional[dict[str, int]] = None,
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
        max_priority_source=max_priority_source,
        block_strategy=block_strategy,
        form_index_source=form_index_source,
        form_index_resolved=dict(form_index_resolved or {}),
        block_index_source=block_index_source,
        block_index_resolved=dict(block_index_resolved or {}),
        stats={},
        notes=(note,) if note else (),
    )


# ─── ranker (Phase 4c, s179) ─────────────────────────────────────────────────


@dataclass(frozen=True)
class AbilityDpsRankedItem:
    """Phase 4c sibling of ``RankedItem`` / ``EhpRankedItem`` /
    ``HybridRankedItem`` — one row of the mage ranker output.

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
        }


@dataclass(frozen=True)
class AbilityDpsRankResult:
    """Phase 4c — output of ``rank_items_by_ability_dps``."""
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
    block_index_resolved: dict[str, int]  # merged (champion, key) → block_index map
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
            f"{self.champion_name} ({self.champion_id}) — lvl {self.level} "
            f"— mode {self.mode}  [MAGE]"
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
    block_index_overrides: Optional[dict[str, int | list[int]]] = None,
    filter_shared_uniques: bool = True,
) -> AbilityDpsRankResult:
    """Rank items by total-ability-DPS gain when added to ``current_item_ids``.

    Phase 4c sibling of ``rank_items`` (DPS), ``rank_items_by_ehp`` (EHP),
    and ``rank_items_by_hybrid`` (bruiser). Same candidate-filtering
    pipeline — purchasable + mode-legal + optional whitelist + budget +
    terminal-only + dead-unique dedup. Only the scoring function changes:
    each candidate's total ability DPS via ``compute_ability_dps`` is
    compared to the baseline.

    Sort keys:
      * ``delta``       — absolute ability-DPS gain (default)
      * ``efficiency``  — ability-DPS gain per 1000 gold

    ``filter_shared_uniques=True`` drops candidates whose unique passive
    key collides with one already in ``current_item_ids`` — matches the
    other scorers' behavior so the mage ranker stays consistent with the
    rest of the engine.

    ``max_priority``, ``block_strategy``, ``form_index_overrides``,
    ``block_index_overrides``, and ``target_current_hp_pct`` flow through
    to ``compute_ability_dps`` for both the baseline and each candidate.
    """
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
            f"mode=ARENA — stripped trinket(s) {list(stripped_trinkets)} "
            f"from current_item_ids"
        )
    if include_components:
        notes.append("include_components=True — non-terminal items in the ranking")
    if budget is not None:
        notes.append(f"budget={budget}g — items over budget filtered")
    if only_ids is not None:
        notes.append(f"only_item_ids restricted to {len(only_ids)} whitelisted ids")
    if baseline.mode_multiplier != 1.0:
        notes.append(
            f"mode_multiplier={baseline.mode_multiplier:.3f} on per-cast damage"
        )
    if baseline.total_ability_dps == 0.0:
        notes.append(
            "baseline ability DPS is 0 — champion may be missing from the "
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
