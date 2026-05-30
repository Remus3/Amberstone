"""Phase 4b + 4c (s178/s179, 2026-05-12) - Mage ability DPS scorer.

Sibling of ``dps.py``. ``compute_ability_dps()`` returns the caster's
per-spell ability DPS (and total) for a resolved build at a given level.
``rank_items_by_ability_dps()`` (Phase 4c, s179) drives the ``/rank-mage``
ranker - same candidate-filtering pipeline as the DPS/EHP/hybrid
scorers, but each candidate is scored by total ability-DPS gain over
the baseline rather than by auto-attack DPS or blended EHP.

For each of the four active spell keys (Q/W/E/R):

1. Resolve the rank at the given champion level using a canonical
   max-priority order (default Q > W > E; R unlocks at lvl 6/11/16).
2. Evaluate the first damage block of the canonical ability form via the
   Phase 4a ``DamageBlock`` schema - sums ``base`` plus each scaling
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
expose a single ``damage`` block per ability key - straightforward to
evaluate. A minority of champions (Aatrox Q's chain variants, Aphelios's
weapon stances, Ezreal's R splash component) ship multiple damage blocks
per form. Phase 4b uses ``block_strategy="first"`` by default - only the
first damage block of the canonical form_index=0 contributes. Phase 5.9
(s191, 2026-05-14) layered a per-(champion, key) ``block_index_overrides``
registry on top - ``champion_block_index.json`` ships defaults for
Cassiopeia E (poisoned-target enhanced), Anivia E (chilled-target
enhanced), Diana W (all-orbs total), Veigar R (executed-target maximum),
Brand W (CC'd-target increased), etc. When a key is in the resolved
override map, the engine switches to the new ``"indexed"`` strategy with
that specific block; keys without an entry honor the global strategy.

Phase 4b deliberate omissions (deferred):
* Passive (P) ability damage - needs different rank model (level-scaled
  rather than rank-locked); typically on-hit which ``compute_dps`` covers.
* Multi-form abilities (Aphelios weapons, Jayce stance, Sylas-stolen ult)
  - ``form_index=0`` only. Operator can pass ``form_index_overrides`` to
  pick a different form per key.
* On-cast triggers, ability-amp items like Liandry's ramp damage -
  modeled at the rotation level in ``dps.py``, not at per-cast level
  here. Items that pump ``ap`` flow through to ability DPS naturally
  via the resolved stat block.
* Conditional damage amps (Ahri R-into-Q, Zoe E-into-Q) - single
  per-cast scoring with no combo-multiplier. Champion-specific.

ENGINE 1.23.0 (2026-05-20) - ability-haste consumption
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Closes the half-shipped state from ENGINE 1.19.0: the engine layer
exposes ``scaled["aram_ability_haste"]`` (flat delta; default 0) and
``scaled["aram_tenacity_mult"]`` (multiplier; default 1.0) via
``engine._apply_mode_modifiers``; this module now CONSUMES the haste
delta to shorten per-spell effective cooldowns using Riot's canonical
haste formula ``eff_cd = base_cd / (1 + total_AH / 100)`` (mirrors
``core/summoner_cooldowns.py`` shipped 2026-05-20 ``58d1e87``).

The total ability-haste plumbed into the formula is the sum of:

* the per-spell ``base_ah`` caller param (defaults to 0; reserved for
  the future item-AH lane - the dataclass shape in ``_effects_types.py``
  does not yet ship an ``ability_haste_flat`` field, so item-AH source
  is currently always 0 and the only non-zero source is the ARAM delta);
* ``scaled.get("aram_ability_haste", 0.0)`` when ``mode == "ARAM"``
  (SR and other modes strip the delta defensively even if a caller
  pre-populates the key).

Per-spell ``AbilitySpellDps`` grows two new fields:

* ``base_cooldown`` - the pre-haste rank cooldown from
  ``_form_cooldown_at_rank`` (back-compat: same value as the pre-1.23
  ``cooldown`` in SR mode with no haste sources).
* ``total_ability_haste`` - the haste sum used in the formula (0.0
  outside ARAM, the aramAbilityHaste delta inside ARAM).

The ``cooldown`` field becomes the EFFECTIVE post-haste value (identity
to ``base_cooldown`` when total haste is 0, the natural case for SR
and most ARAM champions). Result top-level grows ``aram_ability_haste``
and ``aram_tenacity_mult`` for downstream consumer visibility.

TODO (future EHP-side enemy-CC consumer): ``aram_tenacity_mult`` is
plumbed forward but NOT consumed in this slice - the consumption point
is in a future EHP scorer that ingests enemy CC durations applied
against the receiving champion. The marker is in place so when that
scorer ships, the data is already on the result.
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
from .dps import _armor_factor
from .ehp import effective_cc_duration
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
from ._item_ability_haste import total_item_ability_haste
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

# Canonical 4-active-spell set. Passive (P) is intentionally excluded -
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
    # R unlocks at 6/11/16 - three ranks total.
    "ultimate":   (-1, -1, -1, -1, -1, -1, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 2, 2, 2),
}

DEFAULT_MAX_PRIORITY: tuple[str, str, str] = ("Q", "W", "E")

# Phase 4d (s185, 2026-05-13) - per-champion max_priority override registry.
# Sibling of ``hybrid._load_archetype_weights``; same lazy-cache pattern. The
# JSON file lives next to this module and is shipped with the engine - not
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
    """Clear the singleton cache - for tests that mutate the on-disk file."""
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
      * ``"override"`` - caller passed an explicit value
      * ``"champion"`` - override table had an entry for the champion
      * ``"default"`` - fell back to the table default ("Q", "W", "E")
    """
    if explicit is not None:
        keys = tuple(str(k).upper() for k in explicit)
        if len(keys) != 3 or set(keys) != {"Q", "W", "E"}:
            raise ValueError(
                f"max_priority must be a permutation of (Q, W, E), got {explicit!r}"
            )
        return (keys, "override")  # type: ignore[return-value]
    return get_max_priority_for(champion_id)


# Phase 4e (s187, 2026-05-13) - per-(champion, key) form_index registry.
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
    """Clear the singleton cache - for tests that mutate the on-disk file."""
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

      * ``"override"`` - caller passed any explicit value
      * ``"champion"`` - registry entry used, caller passed None
      * ``"default"`` - empty dict, no registry entry, no caller input
    """
    registry_map, registry_source = get_form_index_for(champion_id)
    if explicit is None:
        return (registry_map, registry_source)
    # Caller wins per-key; registry fills the gaps.
    merged: dict[str, int] = dict(registry_map)
    for k, v in explicit.items():
        merged[str(k).upper()] = int(v)
    return (merged, "override")


# Phase 5.9 (s191, 2026-05-14) - per-(champion, key) block_index registry.
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
    """Clear the singleton cache - for tests that mutate the on-disk file."""
    global _BLOCK_INDEX_CACHE
    with _BLOCK_INDEX_LOCK:
        _BLOCK_INDEX_CACHE = None


# Phase 5.9.28 (s228, 2026-05-16) - conditional-target-state schema lift
# (operator sign-off: option B, the multi-session lift; Part 1 = schema +
# validator + resolver + flagship seeds, Part 2 = live liveclient
# HP%/CC plumbing). A block_index value may now ALSO be a conditional
# dict mapping a target-state condition → int|list[int]. ``"default"`` is
# the REQUIRED operator-commits / canonical-amped branch (the ranking
# assumption - same model s191 established for "assume the amped
# condition is met"). Every other key is a positive live-target-state
# descriptor selecting a *downgrade* (never a more optimistic block than
# ``"default"``). Part 1 (s228) resolves to ``"default"``
# unconditionally; live predicate evaluation against real liveclient
# target HP%/CC is Part 2. The vocabulary is CLOSED (mirrors
# ``_BLOCK_STRATEGIES``): an unknown condition key is a registry typo and
# MUST fail loudly here, never silently no-op.
_BLOCK_INDEX_DEFAULT_KEY = "default"
# Phase 5.9.29 (s229, 2026-05-16): generalized ``target_no_cc`` →
# ``target_no_setup``. s228 scoped the non-HP condition to its CC-family
# flagships (Zoe sleep / Evelynn charm), but the seed-expansion candidates
# (Anivia E vs *Chilled*, Brand W vs *ablaze*, Cassiopeia E vs *poisoned*,
# mark-based amps) share the identical modeling semantic regardless of
# debuff *type*: the operator's own ability applied an amp-enabling target
# state; the amped block is the operator-commits/canonical assumption, the
# downgrade is when that state is absent. Naming it after "CC" was a
# false narrowing - 5+ concrete uses → the honest general term.
_BLOCK_INDEX_CONDITIONS: frozenset[str] = frozenset({
    "target_full_hp",    # live target above the execute/low-HP threshold →
                          # pick the non-execute block (Kindred E 5% vs 7.5%
                          # missing-HP, Veigar/Morgana-class HP-threshold amps)
    "target_no_setup",   # the operator's amp-enabling target state - CC /
                          # sleep / charm / chill / ablaze / poison / mark -
                          # is NOT present → pick the un-amped block (Zoe E
                          # sleep, Evelynn Q charm, Anivia E chill, Brand W
                          # ablaze). Type-agnostic by design.
})


def _normalize_block_index_value(
    v,
) -> "int | list[int] | dict[str, int | list[int]]":
    """Coerce a JSON-loaded block_index value to int, list[int], or a
    conditional dict.

    Phase 5.9.20 (s207): int (single block) or list[int] (sum-of-blocks
    - Camille W / Malphite W / Heimerdinger W / Katarina R).
    Phase 5.9.28 (s228): also a conditional ``dict`` mapping a
    target-state condition → int|list[int]. The dict MUST contain a
    ``"default"`` key; every other key MUST be in
    ``_BLOCK_INDEX_CONDITIONS``; nested values are themselves normalized
    to int|list[int] (one level only - no nested conditional dicts).
    Validates shape; raises ValueError on anything else.
    """
    if isinstance(v, bool):
        # Guard: bool is an int subtype; reject it as a registry value.
        raise ValueError(
            f"block_index value must be int, list[int], or conditional "
            f"dict, got bool {v!r}"
        )
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
    if isinstance(v, dict):
        if _BLOCK_INDEX_DEFAULT_KEY not in v:
            raise ValueError(
                f"conditional block_index must contain a "
                f"{_BLOCK_INDEX_DEFAULT_KEY!r} key, got {v!r}"
            )
        cond_out: dict[str, int | list[int]] = {}
        for ck, cv in v.items():
            cks = str(ck)
            if (
                cks != _BLOCK_INDEX_DEFAULT_KEY
                and cks not in _BLOCK_INDEX_CONDITIONS
            ):
                raise ValueError(
                    f"unknown block_index condition {cks!r}; valid: "
                    f"{sorted(_BLOCK_INDEX_CONDITIONS)} "
                    f"(plus required {_BLOCK_INDEX_DEFAULT_KEY!r})"
                )
            nv = _normalize_block_index_value(cv)
            if isinstance(nv, dict):
                raise ValueError(
                    f"nested conditional block_index not allowed: "
                    f"{cks!r} -> {cv!r}"
                )
            cond_out[cks] = nv
        return cond_out
    raise ValueError(
        f"block_index value must be int, list[int], or conditional "
        f"dict, got {v!r}"
    )


def get_block_index_for(
    champion_id: str,
) -> "tuple[dict[str, int | list[int] | dict[str, int | list[int]]], str]":
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
    explicit: "Optional[dict[str, int | list[int] | dict[str, int | list[int]]]]",
) -> "tuple[dict[str, int | list[int] | dict[str, int | list[int]]], str]":
    """Resolve block_index_overrides from caller input + registry.

    Registry provides the per-(champion, key) default; caller's dict
    (if any) is merged in with caller winning per-key. Returns
    ``(merged, source)``:

      * ``"override"`` - caller passed any explicit value
      * ``"champion"`` - registry entry used, caller passed None
      * ``"default"`` - empty dict, no registry entry, no caller input

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
# (treated as a percentage when >0 - ap_pct=50.0 means 50% of AP, so we
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
    # 2026-05-30 unit-map exhaustion: deterministic caster-stat scalings.
    ("caster_armor_pct", "caster_armor"),
    ("caster_bonus_mp_pct", "caster_bonus_mp"),
    ("caster_bonus_ms_pct", "caster_bonus_ms"),
)

# Valid block-strategies. Phase 5.9 (s191) added ``"indexed"`` - pick a
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
    # 2026-05-30 unit-map exhaustion: deterministic caster-stat scalings.
    # Defaulted so existing manual AbilityContext(...) constructions (test
    # helpers) stay valid; from_build sets real values by keyword.
    caster_armor: float = 0.0
    caster_bonus_mp: float = 0.0
    caster_bonus_ms: float = 0.0

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
        HP they're sitting at - defaults to 1.0 (full HP). Operators can
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
        caster_armor = float(stats.get("armor", 0.0))
        caster_max_mp = float(stats.get("mp", 0.0))
        caster_bonus_mp = max(0.0, caster_max_mp - float(base.get("mp", 0.0)))
        caster_bonus_ms = max(0.0, float(stats.get("ms", 0.0)) - float(base.get("ms", 0.0)))

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
            caster_armor=caster_armor,
            caster_max_mp=caster_max_mp,
            caster_bonus_mp=caster_bonus_mp,
            caster_bonus_ms=caster_bonus_ms,
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

    Returns ``-1`` when the spell is not yet unlocked at that level -
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
        # Operator passed an unusual priority list - fall back to a
        # safe rank-0 unlock at lvl 1 (treat as priority_3).
        return _PRIORITY_TABLES["priority_3"][level]
    idx = list(max_priority).index(key)
    table = _PRIORITY_TABLES[f"priority_{idx + 1}"]
    return table[level]


def _mitigation_factor(damage_type: str | None, target_armor: float, target_mr: float) -> float:
    """League's mitigation factor for a damage block.

    Delegates to the single source of truth ``dps._armor_factor`` for
    both resists (League's resist->multiplier curve is identical for
    armor and MR). MIXED splits 50/50 armor/MR (rare; mostly utility
    abilities). TRUE bypasses all resists. Unknown / None defaults to
    MAGIC routing - most multi-block abilities without a form-level
    damage_type are magical. Was a local copy of the formula until the
    2026-05-18 audit folded it onto _armor_factor to kill the drift
    risk (a one-sided edit would silently desync the DPS / ability-DPS
    / burst scorers).
    """
    dt = (damage_type or "MAGIC").upper()
    if dt == "TRUE":
        return 1.0
    if dt == "PHYSICAL":
        return _armor_factor(target_armor)
    if dt == "MIXED":
        return 0.5 * _armor_factor(target_armor) + 0.5 * _armor_factor(target_mr)
    return _armor_factor(target_mr)  # MAGIC + fallback


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
    block_index: "int | Sequence[int] | dict[str, int | Sequence[int]]" = 0,
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
    strategy, the evaluated damage at each (clamped) index is summed -
    used to express "operator commits to landing every component" cases
    where the realistic single-target damage is the sum across multiple
    Meraki blocks (Camille W base + outer-cone, Malphite W active cast
    + first-AA bonus, Heimerdinger W initial + 4 subsequent rockets,
    Katarina R full physical + magic dagger volleys). An empty sequence
    returns 0.0. Single-int callers retain identical pre-s207 behavior.

    Phase 5.9.28 (s228, 2026-05-16): ``block_index`` may now also be a
    conditional ``dict`` (target-state schema lift, operator-signed-off
    option B). Part 1 resolves it to its ``"default"`` branch
    unconditionally - the operator-commits/canonical block, byte-identical
    to an equivalent unconditional int/list entry. Live target-state
    predicate evaluation (selecting a downgrade branch from real
    liveclient HP%/CC) is Part 2 (B-2 plumbing); the int/list paths stay
    byte-identical to pre-s228.
    """
    damage_blocks = tuple(b for b in blocks if b.attribute_kind == "damage")
    if not damage_blocks:
        return 0.0
    if strategy == "first":
        return _evaluate_block(damage_blocks[0], rank, ctx)
    if strategy == "indexed":
        bi = block_index
        if isinstance(bi, dict):
            # Phase 5.9.28 (s228): conditional schema. Part 1 resolves to
            # the operator-commits / canonical "default" branch
            # unconditionally - live target-state predicate evaluation
            # (Part 2 / B-2) selects downgrade branches from real
            # liveclient HP%/CC. ``"default"`` is guaranteed present by
            # ``_normalize_block_index_value``; the ``.get(..., 0)``
            # fallback only guards a caller dict that bypassed it.
            bi = bi.get(_BLOCK_INDEX_DEFAULT_KEY, 0)
        if isinstance(bi, int):
            indices: tuple[int, ...] = (bi,)
        else:
            indices = tuple(int(x) for x in bi)
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
    form-swap ability - Riven R / Renekton E / AurelionSol R / Qiyana Q
    etc.), inherit from ``fallback_form`` (typically form 0) which carries
    the canonical CD list. Form-swap mechanics share the actual game CD
    with their parent form, so inheritance is correct.

    Final fallback: 60s generic default (preserves pre-s206 behavior when
    no fallback is available - single-form abilities with malformed CD).
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


def _effective_ability_cd(base_cd: float, total_haste: float) -> float:
    """Apply Riot's canonical haste formula to an ability base cooldown.

    ENGINE 1.23.0 (2026-05-20): mirrors ``core.summoner_cooldowns._effective_cd``
    so the engine + summoner-CD ledger use the same math (the summoner
    module landed 2026-05-20 ``58d1e87``; this helper is the ability-side
    sibling).

    Formula: ``eff_cd = base_cd / (1 + total_haste / 100)``.
      * ``total_haste = 0`` -> identity (eff_cd == base_cd).
      * ``total_haste > 0`` -> shorter eff_cd.
      * ``total_haste < 0`` (event-mode penalties; Seraphine -20, Teemo
        -15, Ziggs -20 etc) -> longer eff_cd via the same formula.

    Defensive floor on the denominator: a hypothetical
    ``total_haste <= -100`` would otherwise divide by zero / invert. The
    helper clamps the denominator to a 0.01 floor so result stays
    finite + monotone-increasing as haste approaches -100 from above.
    Real engine values never approach this edge but the floor keeps the
    helper robust against caller-supplied test extremes.

    A ``base_cd`` of 0 returns 0 regardless of haste (locked spells,
    pre-rank states).
    """
    if base_cd <= 0:
        return 0.0
    denom = 1.0 + float(total_haste) / 100.0
    if denom < 0.01:
        denom = 0.01
    return float(base_cd) / denom


def _total_ability_haste(
    scaled_stats: dict[str, float],
    mode: str,
    base_ah: float = 0.0,
) -> float:
    """Sum the total ability-haste applied to per-spell cooldowns.

    ENGINE 1.23.0 (2026-05-20): mode-gated read of the engine-exposed
    ``aram_ability_haste`` delta (engine.py line ~210). SR + every
    non-ARAM mode strip the delta defensively even if a caller
    pre-populates the key (the engine's _apply_mode_modifiers gates
    on mode == "ARAM"; this helper double-gates so a malformed
    scaled-dict can't leak ARAM haste into SR rankings).

    ``base_ah`` is the caller-supplied baseline (defaults 0). ENGINE
    1.24.0 (2026-05-21) wired the item-AH lane via
    ``_item_ability_haste.total_item_ability_haste(item_ids)`` -
    ``compute_ability_dps`` now passes the sum of per-item flat AH
    here. The registry covers patch 16.10.1's 220 AH-carrying items
    (parsed from DDragon items.json description text). Test/CLI
    callers passing builds with no AH items see the floor case
    (base_ah=0.0, identity).

    Negative deltas (Seraphine -20, Teemo -15, etc) pass through; the
    haste formula handles them via ``_effective_ability_cd``.
    """
    if mode != "ARAM":
        return float(base_ah)
    aram_ah = float(scaled_stats.get("aram_ability_haste", 0.0))
    return float(base_ah) + aram_ah


# ENGINE 1.30.0 (2026-05-21) - per-spell CC duration registry seeded.
# Closes the item 130 carry-forward (b): this is the 2nd consumer of the
# ``effective_cc_duration`` helper shipped 1.25.0 (item 122). The helper
# itself lives in ``ehp.py`` (free function imported above); this slice
# exposes the downstream-consumer surface at the per-spell AbilityDps
# layer so a future EHP-vs-CC blended scorer (or fight-sim) can read
# per-rank base CC durations + the matching post-tenacity values without
# re-resolving the champion.
#
# ENGINE 1.29.0 shipped the seam EMPTY (forward-marker pattern mirroring
# item 112's ``STAT_GRANT_CALC_KEYS``). ENGINE 1.30.0 seeded a starter set
# of high-impact CC abilities at patch 16.10.1 (30 entries / 24 champs).
# ENGINE 1.31.0 (2026-05-21) extends the seed with wave 2: 23 additional
# entries across 20 additional champions, same first-order CC scope.
# ENGINE 1.33.0 (2026-05-22) extends the seed with wave 3: 14 additional
# entries across 14 additional champions of first-order CC at patch
# 16.10.1, same selection rules.
# ENGINE 1.34.0 (2026-05-22) extends the seed with wave 4: 15 additional
# entries across 15 additional champions, same selection rules.
# ENGINE 1.35.0 (2026-05-22) extends the seed with wave 5: 8 additional
# entries across 7 additional champions, same selection rules.
# ENGINE 1.36.0 (2026-05-22) schema lift to dict.setdefault builder
# pattern + wave 6: 5 additional entries (3 multi-wave augmentations of
# existing champion spell maps + 2 new champions). Total: 95 entries
# across 82 champions.
# All values from official Riot tooltips for FIRST-ORDER CC (stuns /
# roots / suspensions / knock-ups / knock-backs / charms / suppressions
# / polymorphs / sleeps / fear / taunts). Slows are NOT encoded
# (different math). Conditional CC (3rd-stack stuns like Brand R, Bard Q
# wall-bounce variant, Tahm Kench Q 3rd-stack stun) are skipped where
# the base semantic is unclear without a fight-sim observer.
#
# Engine math consumption is STILL FUTURE: today the values flow through
# AbilitySpellDps.cc_duration_s + .cc_duration_post_tenacity for API
# inspection (to_dict serialization) + future composition by a downstream
# fight-sim or EHP-vs-CC blended scorer. compute_ability_dps does not
# branch on the values; production DPS math is byte-identical to 1.29.0
# for every population case.
#
# Schema:
#   _PER_SPELL_CC_DURATIONS[champion_id][spell_key] = (cc_s_r1, ..., cc_s_r5)
# where ``champion_id`` is the DDragon id (e.g. ``"Annie"``, ``"MonkeyKing"``
# for Wukong), ``spell_key`` is one of ``{"Q","W","E","R"}``, and the
# tuple is per-rank base CC duration in seconds. Per-rank tuples are
# length 5 for Q/W/E and length 3 for R; some abilities have a single
# value across all ranks (e.g. Annie R 1.5s all 3 ranks). Single-value
# tuples like (1.5,) are also accepted - the engine reads the rank slot
# defensively (consumer behavior pinned by tests).
#
# ENGINE 1.36.0 SCHEMA LIFT: the registry is now constructed via a
# module-level builder function ``_build_per_spell_cc_durations`` which
# uses ``dict.setdefault(champ, {})[spell] = tuple`` to allow multi-wave
# augmentation of a single champion's spell map without dict-literal
# collision. Prior to 1.36.0 the registry was a single dict literal
# which clobbered prior-wave entries when a later wave added a new
# spell to the same champion. This blocked Lulu R + Sejuani Q + Thresh
# E (all rejected from wave 5 due to clobber). The builder runs ONCE
# at module import and assigns the result to _PER_SPELL_CC_DURATIONS
# below; consumer code reads the dict transparently.
def _build_per_spell_cc_durations() -> dict[str, dict[str, tuple[float, ...]]]:
    """Build the per-spell CC duration registry via setdefault.

    Returns a fresh dict of champion_id -> spell_key -> per-rank tuple.

    Uses ``setdefault(champ, {})[spell] = tuple`` so multiple waves can
    contribute spells to the same champion without clobbering prior-wave
    entries. The builder pattern replaces the single dict literal used
    1.30.0 through 1.35.0; production behavior of all 90 pre-1.36.0
    entries is byte-identical (value pins preserved).
    """
    registry: dict[str, dict[str, tuple[float, ...]]] = {}
    # ----- ENGINE 1.30.0 wave 1 (2026-05-21) -----
    # Initial seed: 30 entries across 24 champions of first-order CC at
    # patch 16.10. All values from Riot wiki + cdragon tooltips.
    # Ahri E - Charm: charm 1.0/1.25/1.5/1.75/2.0
    registry.setdefault("Ahri", {})["E"] = (1.0, 1.25, 1.5, 1.75, 2.0)
    # Annie R - Summon: Tibbers: stun on summon 1.5s all ranks
    registry.setdefault("Annie", {})["R"] = (1.5, 1.5, 1.5)
    # Ashe R - Enchanted Crystal Arrow: stun 1.5-3.5s based on travel
    # distance; use 1.5s as the minimum guaranteed floor across all ranks
    registry.setdefault("Ashe", {})["R"] = (1.5, 1.5, 1.5)
    # Blitzcrank Q - Rocket Grab: pull then 1.0s stun on connect all ranks
    registry.setdefault("Blitzcrank", {})["Q"] = (1.0, 1.0, 1.0, 1.0, 1.0)
    # Cassiopeia R - Petrifying Gaze: stun 2.0s if facing (slow otherwise)
    # all ranks
    registry.setdefault("Cassiopeia", {})["R"] = (2.0, 2.0, 2.0)
    # Galio W - Shield of Durand: taunt 1.0s base on cast all ranks
    registry.setdefault("Galio", {})["W"] = (1.0, 1.0, 1.0, 1.0, 1.0)
    # Galio E - Justice Punch: knock-up 0.5s
    registry.setdefault("Galio", {})["E"] = (0.5, 0.5, 0.5, 0.5, 0.5)
    # Galio R - Hero's Entrance: knock-up 0.75s on landing
    registry.setdefault("Galio", {})["R"] = (0.75, 0.75, 0.75)
    # Leona Q - Shield of Daybreak: stun 1.25s all ranks
    registry.setdefault("Leona", {})["Q"] = (1.25, 1.25, 1.25, 1.25, 1.25)
    # Leona E - Zenith Blade: root 0.5s on connect
    registry.setdefault("Leona", {})["E"] = (0.5, 0.5, 0.5, 0.5, 0.5)
    # Leona R - Solar Flare: stun 1.5s in center
    registry.setdefault("Leona", {})["R"] = (1.5, 1.5, 1.5)
    # Lissandra R - Frozen Tomb: stun 1.5s on enemy-target cast all ranks
    registry.setdefault("Lissandra", {})["R"] = (1.5, 1.5, 1.5)
    # Lulu W - Whimsy: polymorph 1.25/1.5/1.75/2.0/2.25
    registry.setdefault("Lulu", {})["W"] = (1.25, 1.5, 1.75, 2.0, 2.25)
    # Malzahar R - Nether Grasp: suppression 2.5s all ranks
    registry.setdefault("Malzahar", {})["R"] = (2.5, 2.5, 2.5)
    # Maokai R - Nature's Grasp: root 1.2/1.6/2.0
    registry.setdefault("Maokai", {})["R"] = (1.2, 1.6, 2.0)
    # MonkeyKing (Wukong) R - Cyclone: knock-up 1.0s on first hit
    registry.setdefault("MonkeyKing", {})["R"] = (1.0, 1.0, 1.0)
    # Morgana Q - Dark Binding: root 2.0/2.25/2.5/2.75/3.0
    registry.setdefault("Morgana", {})["Q"] = (2.0, 2.25, 2.5, 2.75, 3.0)
    # Nautilus Q - Dredge Line: root+pull 1.0/1.15/1.3/1.45/1.6
    registry.setdefault("Nautilus", {})["Q"] = (1.0, 1.15, 1.3, 1.45, 1.6)
    # Nautilus R - Depth Charge: knock-up 1.0/1.5/2.0 on final target
    registry.setdefault("Nautilus", {})["R"] = (1.0, 1.5, 2.0)
    # Pantheon W - Shield Vault: stun 1.0s all ranks
    registry.setdefault("Pantheon", {})["W"] = (1.0, 1.0, 1.0, 1.0, 1.0)
    # Rakan W - Grand Entrance: knock-up 1.0s all ranks
    registry.setdefault("Rakan", {})["W"] = (1.0, 1.0, 1.0, 1.0, 1.0)
    # Renekton W - Ruthless Predator: stun 0.75s base all ranks
    registry.setdefault("Renekton", {})["W"] = (0.75, 0.75, 0.75, 0.75, 0.75)
    # Sejuani R - Glacial Prison: stun on travel-line 1.0/1.5/2.0
    registry.setdefault("Sejuani", {})["R"] = (1.0, 1.5, 2.0)
    # Sona R - Crescendo: stun 1.5s all ranks
    registry.setdefault("Sona", {})["R"] = (1.5, 1.5, 1.5)
    # Thresh Q - Death Sentence: stun 1.5s on connect all ranks
    registry.setdefault("Thresh", {})["Q"] = (1.5, 1.5, 1.5, 1.5, 1.5)
    # Veigar E - Event Horizon: stun on edge cross 1.5s all ranks
    registry.setdefault("Veigar", {})["E"] = (1.5, 1.5, 1.5, 1.5, 1.5)
    # Vi Q - Vault Breaker: knock-up 0.75s all ranks
    registry.setdefault("Vi", {})["Q"] = (0.75, 0.75, 0.75, 0.75, 0.75)
    # Vi R - Cease and Desist: knock-up 1.0s on initial target
    registry.setdefault("Vi", {})["R"] = (1.0, 1.0, 1.0)
    # Yasuo R - Last Breath: knock-up 1.0s on cast (then airborne held
    # until end - approximate base trigger as 1.0)
    registry.setdefault("Yasuo", {})["R"] = (1.0, 1.0, 1.0)
    # Zoe E - Sleepy Trouble Bubble: drowsy then 2.0s sleep on contact
    registry.setdefault("Zoe", {})["E"] = (2.0, 2.0, 2.0, 2.0, 2.0)
    # ----- ENGINE 1.31.0 wave 2 (2026-05-21) -----
    # +23 entries across 20 new champions of first-order CC at patch 16.10.
    # Selection rules unchanged from wave 1 (stuns / roots / suspensions
    # / knock-ups / knock-backs / charms / sleeps / fear / suppressions);
    # no slows; no conditional CC (e.g. Tahm Kench Q 3rd-stack, Bard Q
    # wall-bounce variant). Values sourced from Riot wiki + cdragon
    # champion JSONs for patch 16.10.
    # Alistar Q - Pulverize: knock-up 1.0s all ranks
    registry.setdefault("Alistar", {})["Q"] = (1.0, 1.0, 1.0, 1.0, 1.0)
    # Alistar W - Headbutt: knock-back 0.5s on contact all ranks
    registry.setdefault("Alistar", {})["W"] = (0.5, 0.5, 0.5, 0.5, 0.5)
    # Amumu Q - Bandage Toss: stun 1.0/1.1/1.2/1.3/1.4 on pull
    registry.setdefault("Amumu", {})["Q"] = (1.0, 1.1, 1.2, 1.3, 1.4)
    # Amumu R - Curse of the Sad Mummy: stun 1.5/1.75/2.0 AOE
    registry.setdefault("Amumu", {})["R"] = (1.5, 1.75, 2.0)
    # Anivia Q - Flash Frost: stun 1.25s on detonation all ranks
    registry.setdefault("Anivia", {})["Q"] = (1.25, 1.25, 1.25, 1.25, 1.25)
    # Braum R - Glacial Fissure: knock-up 1.0s at center line all ranks
    registry.setdefault("Braum", {})["R"] = (1.0, 1.0, 1.0)
    # Chogath Q - Rupture: knock-up 1.0s on detonation all ranks
    registry.setdefault("Chogath", {})["Q"] = (1.0, 1.0, 1.0, 1.0, 1.0)
    # Fiddlesticks Q - Terrify: fear 1.25/1.5/1.75/2.0/2.25
    registry.setdefault("Fiddlesticks", {})["Q"] = (1.25, 1.5, 1.75, 2.0, 2.25)
    # Gnar R - GNAR!: knock-back 0.75s base displacement all ranks
    registry.setdefault("Gnar", {})["R"] = (0.75, 0.75, 0.75)
    # Gragas E - Body Slam: stun 1.0s on contact all ranks
    registry.setdefault("Gragas", {})["E"] = (1.0, 1.0, 1.0, 1.0, 1.0)
    # Jhin W - Deadly Flourish: root 0.75/1.0/1.25/1.5/1.75 on marked
    registry.setdefault("Jhin", {})["W"] = (0.75, 1.0, 1.25, 1.5, 1.75)
    # Lux Q - Light Binding: root 2.0/2.25/2.5/2.75/3.0 first target
    registry.setdefault("Lux", {})["Q"] = (2.0, 2.25, 2.5, 2.75, 3.0)
    # Nami Q - Aqua Prison: stun 1.5s all ranks
    registry.setdefault("Nami", {})["Q"] = (1.5, 1.5, 1.5, 1.5, 1.5)
    # Neeko E - Tangle-Barbs: root 0.75/1.0/1.25/1.5/1.75
    registry.setdefault("Neeko", {})["E"] = (0.75, 1.0, 1.25, 1.5, 1.75)
    # Neeko R - Pop Blossom: stun 1.25s on activation all ranks
    registry.setdefault("Neeko", {})["R"] = (1.25, 1.25, 1.25)
    # Orianna R - Command: Shockwave: knock-up 1.0s all ranks
    registry.setdefault("Orianna", {})["R"] = (1.0, 1.0, 1.0)
    # Poppy E - Heroic Charge: stun 0.5s base on contact (wall stun
    # 1.5s is conditional on terrain - base 0.5s always fires)
    registry.setdefault("Poppy", {})["E"] = (0.5, 0.5, 0.5, 0.5, 0.5)
    # Rell W (Ferromancy: Crash Down) intentionally NOT modeled here -
    # the W toggle has a non-standard rank progression (split mount /
    # dismount semantics; knock-up duration scales with dash distance).
    # Riven W - Ki Burst: stun 0.75s AOE all ranks
    registry.setdefault("Riven", {})["W"] = (0.75, 0.75, 0.75, 0.75, 0.75)
    # Singed E - Fling: knock-back 1.0s displacement all ranks
    registry.setdefault("Singed", {})["E"] = (1.0, 1.0, 1.0, 1.0, 1.0)
    # Skarner R - Impale: suppression 1.75/2.0/2.25 on grabbed target
    registry.setdefault("Skarner", {})["R"] = (1.75, 2.0, 2.25)
    # Varus R - Chain of Corruption: root 2.0s on root spread all ranks
    registry.setdefault("Varus", {})["R"] = (2.0, 2.0, 2.0)
    # Xerath E - Shocking Orb: stun 1.0/1.25/1.5/1.75/2.0 at min range
    # (longer with distance; floor pin for closest-target hit)
    registry.setdefault("Xerath", {})["E"] = (1.0, 1.25, 1.5, 1.75, 2.0)
    # Zac E - Elastic Slingshot: knock-up 1.0s on landing all ranks
    registry.setdefault("Zac", {})["E"] = (1.0, 1.0, 1.0, 1.0, 1.0)
    # ----- ENGINE 1.33.0 wave 3 (2026-05-22) -----
    # +14 entries across 14 additional champions of first-order CC at
    # patch 16.10. Selection rules unchanged from wave 1 + wave 2
    # (stuns / roots / suspensions / knock-ups / knock-backs / charms
    # / sleeps / fear / suppressions / polymorphs / taunts); no slows;
    # no conditional CC (Brand R 3rd-hit / TF W Gold Card / Tahm Q
    # 3rd-stack / Lillia R dream-stack / Volibear Q terrain / Urgot R
    # fear / Rell W mount/dismount toggle / Warwick R channel-gated);
    # no self-CC. Values sourced from Riot wiki + cdragon champion
    # JSONs for patch 16.10. Canonical DDragon ids ("Chogath" /
    # "MonkeyKing" / "AurelionSol" / "XinZhao" - punctuation-stripped
    # per _portraitUrl convention).
    # AurelionSol R - The Skies Descend / Falling Star: knock-up on
    # impact + stun in center (the center stun is the canonical
    # first-order CC value; knockup on first contact is wider but
    # shorter); pin the center stun 1.25/1.5/1.75 at ranks 1/2/3.
    registry.setdefault("AurelionSol", {})["R"] = (1.25, 1.5, 1.75)
    # Caitlyn W - Yordle Snap Trap: root 1.5s all ranks on triggered
    # trap (single value across all 5 ranks; trap duration scales with
    # rank but root duration is constant per the 16.10 tooltip).
    registry.setdefault("Caitlyn", {})["W"] = (1.5, 1.5, 1.5, 1.5, 1.5)
    # Camille E - Hookshot / Wall Dive: stun 0.75s on second-cast
    # wall-dive contact all ranks (single value across 5 ranks).
    registry.setdefault("Camille", {})["E"] = (0.75, 0.75, 0.75, 0.75, 0.75)
    # Diana R - Moonfall: knock-up 0.75s on pull (single value all
    # 3 ranks; rank scales damage + cooldown, not the CC duration).
    registry.setdefault("Diana", {})["R"] = (0.75, 0.75, 0.75)
    # Elise E (human form) - Cocoon: stun 1.1/1.4/1.7/2.0/2.3 across
    # 5 ranks (one of the longest single-target stuns at min rank).
    registry.setdefault("Elise", {})["E"] = (1.1, 1.4, 1.7, 2.0, 2.3)
    # Heimerdinger E - CH-2 Electron Storm Grenade: stun 1.25s on
    # primary target all 4 ranks (E maxes at rank 4 not 5; engine
    # canonical 5-rank shape, pin rank-5 slot to rank-4 value).
    registry.setdefault("Heimerdinger", {})["E"] = (
        1.25, 1.25, 1.25, 1.25, 1.25,
    )
    # Ivern Q - Rootcaller: root 1.0/1.25/1.5/1.75/2.0 across 5 ranks
    # (ally dash after root not modeled - it is an ally interaction,
    # not enemy CC).
    registry.setdefault("Ivern", {})["Q"] = (1.0, 1.25, 1.5, 1.75, 2.0)
    # Malphite R - Unstoppable Force: knock-up 1.5/1.75/2.0 across
    # 3 ranks (Malphite's signature ult CC value).
    registry.setdefault("Malphite", {})["R"] = (1.5, 1.75, 2.0)
    # Pyke Q - Bone Skewer: stun 1.25s on the pulled/skewered target
    # all 5 ranks (the ranged-Q-on-cast charge stuns; pin the
    # constant value).
    registry.setdefault("Pyke", {})["Q"] = (1.25, 1.25, 1.25, 1.25, 1.25)
    # Rell Q - Shattering Strike: root 1.0s on hit all 5 ranks
    # (single value; Rell W is intentionally NOT modeled per the
    # mount/dismount toggle skip rule).
    registry.setdefault("Rell", {})["Q"] = (1.0, 1.0, 1.0, 1.0, 1.0)
    # Ryze W - Rune Prison: root 0.75/1.0/1.25/1.5/1.75 across
    # 5 ranks (Ryze's signature W root).
    registry.setdefault("Ryze", {})["W"] = (0.75, 1.0, 1.25, 1.5, 1.75)
    # Sion Q - Decimating Smash: stun 1.25/1.5/1.75/2.0/2.25 at full
    # charge across 5 ranks (the minimum charge stuns shorter but the
    # full-charge value is the canonical max-rank pin).
    registry.setdefault("Sion", {})["Q"] = (1.25, 1.5, 1.75, 2.0, 2.25)
    # Tristana R - Buster Shot: knock-back 1.0s on hit all 3 ranks
    # (the displacement is brief; pin the constant value).
    registry.setdefault("Tristana", {})["R"] = (1.0, 1.0, 1.0)
    # XinZhao W - Wind Becomes Lightning: knock-up 1.0s on the
    # 3rd-strike attack at end of pull-line all 5 ranks (canonical
    # value; the pull setup scales damage not the CC duration).
    registry.setdefault("XinZhao", {})["W"] = (1.0, 1.0, 1.0, 1.0, 1.0)
    # ----- ENGINE 1.34.0 wave 4 (2026-05-22) -----
    # +15 entries across 15 additional champions of first-order CC at
    # patch 16.10. Selection rules unchanged from waves 1 + 2 + 3
    # (stuns / roots / suspensions / knock-ups / knock-backs / charms
    # / sleeps / fear / suppressions / polymorphs / taunts); no slows;
    # no conditional CC (Bard Q wall-bounce / TF W Gold Card / Evelynn W
    # detonation-on-Eve-attack / Karma W channel-completion / Syndra E
    # via Dark Sphere / Swain E return-wave / Seraphine E slowed-target /
    # Zilean Q double-bomb / Hwei E compound-cast); no self-CC. Values
    # sourced from data/daemon_slayer/16.10.1/champion_abilities.json
    # for the explicit per-rank duration entries; the knock-up / knock-back
    # / direct-stun single-value entries follow the wave 1+2+3 convention
    # for displacements not encoded as duration blocks.
    # Draven E - Stand Aside: knock-back 0.5s on contact all 5 ranks
    # (brief displacement followed by slow; pin canonical knockback
    # value following the Singed E / Tristana R pattern from wave 2+3).
    registry.setdefault("Draven", {})["E"] = (0.5, 0.5, 0.5, 0.5, 0.5)
    # Ekko W - Parallel Convergence: stun 2.25s on enemies inside the
    # anomaly when it expires after delay (single value across 5 ranks;
    # rank scales shield strength, not CC duration). Universal-zone
    # pattern (enemies inside at expiry get the CC) mirrors Soraka E
    # Equinox + Anivia Q from wave 2.
    registry.setdefault("Ekko", {})["W"] = (2.25, 2.25, 2.25, 2.25, 2.25)
    # Janna Q - Howling Gale: knock-up 1.0s at full charge across all
    # 5 ranks (rank scales damage; knock-up duration scales with the
    # tornado's charge time NOT with rank; pin canonical full-charge
    # value per the wave-1 Vi Q / wave-3 Tristana R single-value
    # convention).
    registry.setdefault("Janna", {})["Q"] = (1.0, 1.0, 1.0, 1.0, 1.0)
    # Jax E - Counter Strike: stun 1.0s AOE on dodge counterattack at
    # all 5 ranks (rank scales damage not CC duration).
    registry.setdefault("Jax", {})["E"] = (1.0, 1.0, 1.0, 1.0, 1.0)
    # Jinx E - Flame Chompers: root 1.5s on triggered chomper at all
    # 5 ranks (rank scales damage + cooldown, not CC duration).
    registry.setdefault("Jinx", {})["E"] = (1.5, 1.5, 1.5, 1.5, 1.5)
    # Mel E - Solar Snare: root 1.25/1.5/1.75/2.0/2.25 on orb expiry
    # across 5 ranks (Orb Root Duration block from champion_abilities
    # data at 16.10.1).
    registry.setdefault("Mel", {})["E"] = (1.25, 1.5, 1.75, 2.0, 2.25)
    # Nocturne E - Unspeakable Horror: fear 1.25/1.5/1.75/2.0/2.25
    # across 5 ranks (Disable Duration block from data; the channel
    # is the application timer not a conditional gate - the fear
    # applies as soon as the channel completes which is universal).
    registry.setdefault("Nocturne", {})["E"] = (1.25, 1.5, 1.75, 2.0, 2.25)
    # Quinn E - Vault: knock-back 0.75s on dash hit at all 5 ranks
    # (brief displacement following Singed E / Tristana R pattern).
    registry.setdefault("Quinn", {})["E"] = (0.75, 0.75, 0.75, 0.75, 0.75)
    # Rammus E - Frenzying Taunt: taunt 1.2/1.4/1.6/1.8/2.0 across
    # 5 ranks (Taunt Duration block from data).
    registry.setdefault("Rammus", {})["E"] = (1.2, 1.4, 1.6, 1.8, 2.0)
    # Senna W - Last Embrace: root 1.25/1.5/1.75/2.0/2.25 across 5
    # ranks (Root Duration block from data; delayed root after the
    # ~1s travel delay - the timer is universal not conditional,
    # mirrors the Nautilus Q / Caitlyn W expiry-root pattern).
    registry.setdefault("Senna", {})["W"] = (1.25, 1.5, 1.75, 2.0, 2.25)
    # Seraphine R - Encore: stun 1.25/1.5/1.75 across 3 ranks
    # (Disable Duration block from data; primary AOE wave stuns
    # enemies hit; bounce-back extension is universal).
    registry.setdefault("Seraphine", {})["R"] = (1.25, 1.5, 1.75)
    # Shaco W - Jack in the Box: fear 0.5/0.75/1.0/1.25/1.5 across
    # 5 ranks (Fear Duration block from data; box trigger fires the
    # fear on enemies in radius unconditionally).
    registry.setdefault("Shaco", {})["W"] = (0.5, 0.75, 1.0, 1.25, 1.5)
    # Shen E - Shadow Dash: taunt 1.5s on dash hit at all 5 ranks
    # (canonical post-rework value; rank scales damage + energy
    # restore, not CC duration; description "dashing in a direction,
    # taunting enemies in his path" from cdragon).
    registry.setdefault("Shen", {})["E"] = (1.5, 1.5, 1.5, 1.5, 1.5)
    # Soraka E - Equinox: root 1.0/1.25/1.5/1.75/2.0 on enemies inside
    # at zone expiry across 5 ranks (Root Duration block from data;
    # universal-zone pattern mirroring Ekko W + Anivia Q).
    registry.setdefault("Soraka", {})["E"] = (1.0, 1.25, 1.5, 1.75, 2.0)
    # Zyra E - Grasping Roots: root 1.0/1.25/1.5/1.75/2.0 on line hit
    # across 5 ranks (Root Duration block from data).
    registry.setdefault("Zyra", {})["E"] = (1.0, 1.25, 1.5, 1.75, 2.0)
    # ----- ENGINE 1.35.0 wave 5 (2026-05-22) -----
    # +14 entries across 14 additional champions of first-order CC at
    # patch 16.10. Selection rules unchanged from waves 1+2+3+4
    # (stuns / roots / suspensions / knock-ups / knock-backs / charms /
    # sleeps / fear / suppressions / polymorphs / taunts / pulls); no
    # slows; no conditional CC; no self-CC. champion_abilities.json
    # at 16.10.1 does not carry explicit Disable/Stun/Root/Fear/Taunt
    # duration blocks for these spells (only damage_blocks); values
    # sourced from Riot wiki + canonical patch 16.10.1 tooltips and
    # follow the single-value-all-ranks pattern established by waves
    # 1+2+3+4 (Sona R / Galio W / Yasuo R / Pantheon W / Vi Q / Singed
    # E / Tristana R / Caitlyn W / Camille E / Pyke Q / Rell Q / Jax E
    # etc.). REJECTED candidates with reason recorded (do NOT re-
    # research): Aurora R (conditional knock-up only on cast start),
    # Mordekaiser R Realm of Death (banishment conditional - items 137
    # REJECT list), Briar R Certain Death (charm+knockback compound -
    # charm piece conditional), Bard Q (wall-bounce conditional - items
    # 138 REJECT list), Sett W (direct-damage-only - items 137 REJECT),
    # Taliyah W (displacement-only not knock-up - items 137 REJECT),
    # Volibear Q (terrain conditional - items 135+ REJECT), JarvanIV
    # EQ combo (flag-throw conditional), Trundle R (slow+damage steal),
    # Kennen E (3rd Mark of the Storm stack conditional), KSante Q
    # (3rd stack conditional), Sett E Facebreaker (both-sides pull
    # conditional), Vayne E Condemn (wall-pin conditional), Sylas E2
    # Abscond/Abduct (second-cast conditional), Xayah E (3+ feathers
    # conditional), Aphelios Q variants (varies by chamber), Aurora E
    # Drawn In (slow+pull displacement), Briar Q (charge conditional),
    # Renata R (damage-applied conditional). Sejuani Q (Arctic Assault
    # stun) NOT included since Sejuani R was seeded wave 1 (would
    # combine into one Sejuani entry; deferred for sweep simplicity).
    # Shen E + Jax E + Jinx E NOT included - all 3 already seeded
    # wave 4. Thresh E (Flay knockback) NOT included - Thresh Q was
    # seeded wave 1; multi-spell Thresh extension deferred.
    # Hecarim E - Devastating Charge: knockback 0.75s on charge contact
    # all 5 ranks (brief displacement; rank scales damage + slow, not
    # CC duration); canonical knockback pattern following Singed E /
    # Tristana R from prior waves.
    registry.setdefault("Hecarim", {})["E"] = (0.75, 0.75, 0.75, 0.75, 0.75)
    # Hecarim R - Onslaught of Shadows: fear 1.0s on Hecarim phasing
    # through enemies all 3 ranks (canonical fear duration; rank scales
    # damage + travel range, not CC duration).
    registry.setdefault("Hecarim", {})["R"] = (1.0, 1.0, 1.0)
    # KSante R - All Out: knock-up 0.75s on first impact across all
    # 3 ranks (knock-aside displacement; rank scales damage + bonus
    # stats, not CC duration). Canonical first-impact-only CC piece;
    # the All Out form-change is a self-buff not first-order CC.
    registry.setdefault("KSante", {})["R"] = (0.75, 0.75, 0.75)
    # Mordekaiser E - Death's Grasp: pull 0.25s displacement at all 5
    # ranks (brief inward pull; canonical post-rework value following
    # the Singed E displacement family. Rank scales magic-pen + damage,
    # not CC duration).
    registry.setdefault("Mordekaiser", {})["E"] = (
        0.25, 0.25, 0.25, 0.25, 0.25,
    )
    # Urgot E - Disdain: knockback 0.5s on hit at all 5 ranks (brief
    # displacement; rank scales damage + executes low-HP targets, not
    # CC duration; canonical knockback value following the Draven E /
    # Singed E displacement family).
    registry.setdefault("Urgot", {})["E"] = (0.5, 0.5, 0.5, 0.5, 0.5)
    # Viego W - Spectral Maw: stun 1.5s at full charge all 5 ranks
    # (single value across 5 ranks; rank scales damage + dash range,
    # not CC duration; minimum-charge stuns shorter but full-charge
    # value is the canonical max pin following the Sion Q + Pantheon W
    # pattern).
    registry.setdefault("Viego", {})["W"] = (1.5, 1.5, 1.5, 1.5, 1.5)
    # Yone R - Fate Sealed: knock-up 0.75s on hit all 3 ranks (brief
    # lift; rank scales damage not CC duration; canonical knock-up
    # value matching Diana R / Gnar R / Tristana R pattern).
    registry.setdefault("Yone", {})["R"] = (0.75, 0.75, 0.75)
    # Ziggs W - Satchel Charge: knockback 0.5s on explosion all 5
    # ranks (brief displacement; rank scales damage, not CC duration;
    # canonical knockback value following Draven E pattern).
    registry.setdefault("Ziggs", {})["W"] = (0.5, 0.5, 0.5, 0.5, 0.5)
    # Wave 5 deferrals (now unblocked via schema lift, addressed in
    # wave 6 below): Lulu R / Sejuani Q / Thresh E were rejected
    # from wave 5 due to dict-literal collision with prior-wave
    # entries (Lulu W wave 1 / Sejuani R wave 1 / Thresh Q wave 1).
    # The 1.36.0 schema lift to setdefault enables multi-wave
    # augmentation of the same champion's spell map.
    # Tahm Kench W - Devour ally: knock-up 0.0s NOT first-order CC
    # (allied target swallow; intentionally skipped, on items 137
    # REJECT list).
    # Briar W Blood Frenzy - SKIPPED (no CC, just damage steal).
    # Heimerdinger Q turret - NOT first-order champion CC (turret
    # piece; H-28G's stun-mine piece is conditional on enemy stepping
    # in trap and the duration is rank 5 only; Heimerdinger E already
    # seeded wave 3 covers his canonical CC).
    # ----- ENGINE 1.36.0 wave 6 (2026-05-22) -----
    # SCHEMA LIFT + 5 additional entries. The 1.36.0 schema lift to
    # the setdefault builder pattern (above) unblocks 3 wave-5
    # deferrals (multi-wave augmentation of existing champion spell
    # maps): Lulu R (Lulu W in wave 1), Sejuani Q (Sejuani R in
    # wave 1), Thresh E (Thresh Q in wave 1). 2 new champions also
    # ship: Bard R + Lillia R. Total wave 6 net: 5 spell entries
    # across 5 distinct champions (Lulu / Sejuani / Thresh / Bard /
    # Lillia; the first 3 augment existing entries, the last 2
    # introduce new champions).
    # Selection rules unchanged from waves 1-5: first-order CC only
    # (stuns / roots / suspensions / knock-ups / knock-backs / charms
    # / sleeps / fear / suppressions / polymorphs / taunts / pulls
    # / stasis); no slows; no conditional CC; no self-CC; canonical
    # DDragon ids. Stasis (Bard R Tempered Fate) added to the first-
    # order CC scope as a hard-disable type alongside stun / root /
    # suspension / suppression.
    # Lulu R - Wild Growth: knock-up 1.0s on ally landing all 3
    # ranks (allied target launched into air; the knock-up affects
    # enemies under the landing zone unconditionally; canonical
    # 16.10.1 value; rank scales bonus HP + radius + duration of
    # the giant-form, not the initial knock-up duration). Multi-
    # wave augmentation: Lulu W polymorph was seeded wave 1; the
    # setdefault builder allows Lulu R to coexist.
    registry.setdefault("Lulu", {})["R"] = (1.0, 1.0, 1.0)
    # Sejuani Q - Arctic Assault: stun 0.75/0.875/1.0/1.125/1.25 across
    # 5 ranks (canonical post-rework value at 16.10.1; brief knockup-
    # stun on first enemy hit by the dash). Multi-wave augmentation:
    # Sejuani R was seeded wave 1; the setdefault builder allows
    # Sejuani Q to coexist.
    registry.setdefault("Sejuani", {})["Q"] = (0.75, 0.875, 1.0, 1.125, 1.25)
    # Thresh E - Flay: knockback 0.4s displacement all 5 ranks
    # (brief swat displacement; rank scales damage + slow not CC
    # duration; canonical knockback value following Singed E /
    # Tristana R / Draven E pattern). Multi-wave augmentation:
    # Thresh Q death-sentence stun was seeded wave 1; the setdefault
    # builder allows Thresh E to coexist.
    registry.setdefault("Thresh", {})["E"] = (0.4, 0.4, 0.4, 0.4, 0.4)
    # Bard R - Tempered Fate: stasis 2.5s on enemies hit by the
    # tomb-wave all 3 ranks (canonical Bard R duration; rank scales
    # cooldown not CC duration; the area-of-effect stasis is a hard
    # disable on enemies hit). Stasis is first-order CC (target is
    # untargetable + cannot act); aligns with the existing scope.
    # Bard Q wall-bounce stun stays REJECTED (conditional on terrain).
    registry.setdefault("Bard", {})["R"] = (2.5, 2.5, 2.5)
    # Lillia R - Lilting Lullaby: sleep 2.0s on enemies marked with
    # Dream Dust when she puts them to sleep all 3 ranks (canonical
    # 16.10.1 base sleep duration on the application; rank scales
    # damage + cooldown not CC duration). The Dream Dust mark from
    # her other abilities is the activation pattern (mirrors Zoe E
    # drowsy-then-sleep pattern wave 1); the sleep itself is the
    # first-order CC.
    registry.setdefault("Lillia", {})["R"] = (2.0, 2.0, 2.0)
    # Wave 6 REJECTED candidates (with reason recorded so future
    # audits do NOT re-research):
    # * Rell R Magnet Storm: primarily a force-pull / drag mechanic
    #   while channeling (continuous slow pull of enemies inward);
    #   the 1.0s "initial pull" is a damage tick + slow not a hard
    #   first-order CC. The Magnet Storm field IS impactful but does
    #   not displace targets to a discrete pull-stun like Sion R or
    #   Skarner R. REJECT consistent with wave-5 deferral.
    # * Bard Q Cosmic Binding: wall-bounce conditional stun
    #   (REJECT carryover from waves 4+5).
    # * TF W Pick a Card Gold Card: card-selection conditional stun
    #   (REJECT carryover from waves 4+5).
    # * Lillia E Swirlseed: ranged slow (NOT a sleep; sleep is on R only).
    # * Tristana W Rocket Jump landing: knockback was REJECTED-by-
    #   tooltip-search at 16.10.1 (landing applies a small slow not
    #   a discrete knockback). Tristana R buster-shot knockback was
    #   already seeded wave 3.
    # * Akshan E Heroic Swing: no first-order CC (just dash + slow).
    # * Karthus Q Lay Waste: no first-order CC.
    # * Naafiri R The Hunt Calls: no first-order CC.
    # * Yuumi Q Prowling Projectile fully-charged root: REJECT due to
    #   conditional charge time semantics (operator-gated schema lift
    #   to a conditional axis would unblock).
    # * Brand Q / Tahm Q / Volibear Q / Mordekaiser R / Aurora R /
    #   Briar R / Sett W / Sett E / Taliyah W / Trundle R / Kennen E /
    #   KSante Q / Vayne E / Sylas E2 / Xayah E / Aphelios Q /
    #   Aurora E / Briar Q / Renata R / Viktor W / Warwick R / Bard Q /
    #   TF W: all conditional-CC carryovers from prior-wave REJECT
    #   lists (operator-gated schema lift for the conditional axis).
    # FINAL wave 6 net: 5 spell entries across 5 distinct champions
    # (Lulu R / Sejuani Q / Thresh E / Bard R / Lillia R).
    # ----- ENGINE 1.37.0 wave 7 (2026-05-22) -----
    # +8 entries across +7 new champions + 1 multi-wave augmentation
    # (Zac R; Zac E was wave 2) of first-order CC at patch 16.10.1.
    # Selection rules unchanged from waves 1-6: first-order CC only
    # (stuns / roots / suspensions / knock-ups / knock-backs / charms /
    # sleeps / fear / suppressions / polymorphs / taunts / pulls /
    # stasis); no slows; no conditional CC; no self-CC; canonical DDragon
    # ids. Values sourced from Riot wiki + canonical patch 16.10.1
    # tooltips (Meraki bulk + champion_abilities.json damage_blocks do
    # NOT carry per-spell CC duration data; same sourcing convention as
    # waves 1-6 for the wiki-tooltip lookups). Wave 7 picks broaden
    # remaining first-order-CC coverage across champions NOT yet seeded.
    # Irelia E - Flawless Duet: stun 0.75/0.85/0.95/1.05/1.15 across
    # 5 ranks (canonical post-rework value at 16.10.1; rank scales the
    # stun duration). The 2 daggers must connect for the stun to fire,
    # but the stun itself is unconditional once both connect.
    registry.setdefault("Irelia", {})["E"] = (0.75, 0.85, 0.95, 1.05, 1.15)
    # Kalista R - Fate's Call: knock-up 1.0s on enemies hit by the
    # ally-cannonball at all 3 ranks (rank scales bonus dash range +
    # damage, not CC duration; canonical value following the Sona R /
    # Diana R / Yone R single-value-all-ranks pattern from prior waves).
    registry.setdefault("Kalista", {})["R"] = (1.0, 1.0, 1.0)
    # Ornn R - Call of the Forge God: knock-up 0.5s on first-impact of
    # the elemental ram all 3 ranks (canonical primary first-hit knockup;
    # rank scales damage + ram range, not CC duration; the second-cast
    # knockup with Brittle is conditional on the target carrying a
    # Brittle stack from other Ornn abilities, intentionally skipped).
    registry.setdefault("Ornn", {})["R"] = (0.5, 0.5, 0.5)
    # Shyvana R - Dragon's Descent: knock-back 1.0s on dragon-form
    # contact with first enemy all 3 ranks (canonical post-rework
    # displacement; rank scales bonus stats + damage, not CC duration).
    registry.setdefault("Shyvana", {})["R"] = (1.0, 1.0, 1.0)
    # Smolder R - Mountain Breaker: knock-up 1.25s on enemies hit by
    # the dive landing all 3 ranks (canonical first-order knockup; rank
    # scales damage + slow piece, the slow is intentionally skipped as
    # a separate axis per the no-slows wave convention).
    registry.setdefault("Smolder", {})["R"] = (1.25, 1.25, 1.25)
    # Vayne E - Condemn: knock-back 0.5s on hit at all 5 ranks (the
    # universal knockback displacement; rank scales damage, not CC
    # duration; the wall-pin stun is conditional on terrain contact
    # and is intentionally REJECTED per the no-conditional-CC rule).
    # Canonical knockback following the Singed E / Tristana R / Draven E
    # / Thresh E displacement family.
    registry.setdefault("Vayne", {})["E"] = (0.5, 0.5, 0.5, 0.5, 0.5)
    # Volibear E - Sky Splitter: airborne 0.25s on enemies under the
    # landing zone at all 5 ranks (brief lift-up on the lightning strike
    # landing; rank scales damage + bonus MR shred, not CC duration;
    # this is the brief disable component, distinct from the conditional
    # Volibear Q terrain-stun which stays REJECTED).
    registry.setdefault("Volibear", {})["E"] = (0.25, 0.25, 0.25, 0.25, 0.25)
    # Zac R - Let's Bounce: knock-up 1.0s on enemies hit by Zac's bounce
    # contact all 3 ranks (canonical knockup; rank scales bounce count +
    # damage, not CC duration; the slow piece on bounces is intentionally
    # skipped per the no-slows wave convention).
    registry.setdefault("Zac", {})["R"] = (1.0, 1.0, 1.0)
    # Wave 7 REJECTED candidates (with reason recorded so future audits
    # do NOT re-research):
    # * Darius E Apprehend: pure pull + slow (no first-order stun).
    # * Draven E Stand Aside: already wave 4.
    # * Ekko W Parallel Convergence: already wave 4.
    # * Yorick R Eulogy of the Isles: no first-order CC (Mist Walker
    #   summons; Yorick W Dark Procession is a wall summon, not champ-CC).
    # * AurelionSol Q / Q': no CC (Breath of Light beam damage).
    # * Aurora W Across the Veil: no CC (dash + invisibility).
    # * Aurora E The Weirding: pull + slow conditional (REJECT - matches
    #   wave 6 Aurora E carryover).
    # * Ambessa Q / W / E / R: no first-order CC at 16.10.1 (cunning
    #   weave / dash / line damage / executes); all stays inert until
    #   a future audit surfaces a canonical CC value.
    # * Pyke E Phantom Undertow: damage on path-return only (no CC);
    #   Pyke Q stun was already wave 3.
    # * Veigar E Event Horizon: already wave 1.
    # * Fiora W Riposte: parry/stun on parry is conditional on enemy
    #   targeted-damage timing (REJECT - conditional axis).
    # * Vex E Looming Darkness: fear conditional on Vex E-passive mark
    #   (REJECT - conditional axis).
    # * Ornn Q Volcanic Rupture: knockup conditional on Brittle second-
    #   cast Q (REJECT - conditional axis).
    # * Renata R Hostile Takeover: berserk effect (forces enemies to
    #   attack each other) but no first-order CC duration in the wiki
    #   tooltip in the canonical-disable sense (REJECT - berserk is a
    #   different mechanic axis, queued for a future schema lift).
    # * Volibear Q Thundering Smash: terrain-conditional stun (REJECT
    #   carryover from waves 5+6).
    # * TahmKench R Devour: ally-target swallow (REJECT carryover).
    # * Aurora R Between Worlds: zone effect, no first-order CC.
    # FINAL wave 7 net: 8 spell entries across 8 distinct champions
    # (Irelia E / Kalista R / Ornn R / Shyvana R / Smolder R / Vayne E /
    # Volibear E / Zac R). 7 of the 8 are NEW champions; Zac R is a
    # multi-wave augmentation (Zac E was seeded wave 2). Total registry:
    # 103 entries across 89 champs.
    # ----- ENGINE 1.42.0 wave 8 (2026-05-22) -----
    # +3 entries / 0 new champions / 3 multi-wave augmentations. The
    # unconditional first-order CC at patch 16.10.1 is approaching
    # saturation - per item 145 don't-redo: "most remaining champions
    # either have no first-order CC OR carry conditional-only CC". The
    # wave 8 audit walked every champion+spell duration block in
    # data/daemon_slayer/16.10.1/champion_abilities.json + cross-checked
    # against the wave-1-through-7 entries + the cc_conditional 33-entry
    # registry. Net new unconditional candidates: 3 (all multi-wave
    # augmentations of champions already partially seeded).
    # Selection rules unchanged from waves 1-7: first-order CC only
    # (stuns / roots / suspensions / knock-ups / knock-backs / charms /
    # sleeps / fear / suppressions / polymorphs / taunts / pulls /
    # stasis); no slows; no conditional CC; no self-CC; canonical
    # DDragon ids.
    # Lissandra W - Ring of Frost: root 1.25/1.35/1.45/1.55/1.65 across
    # 5 ranks (canonical 16.10.1 Meraki value via Root Duration block in
    # champion_abilities.json). AOE-on-cast around Lissandra; enemies
    # in radius are rooted unconditionally. Multi-wave augmentation:
    # Lissandra R stun was seeded wave 1; the setdefault builder allows
    # Lissandra W to coexist on the same champion's spell map.
    registry.setdefault("Lissandra", {})["W"] = (1.25, 1.35, 1.45, 1.55, 1.65)
    # Maokai W - Twisted Advance: root 1.0/1.1/1.2/1.3/1.4 across 5
    # ranks (canonical 16.10.1 Meraki value via Root Duration block).
    # Targeted dash + root on enemy hit; the root applies on contact
    # unconditionally once W is cast. Multi-wave augmentation: Maokai R
    # Nature's Grasp was seeded wave 1; setdefault allows W to coexist.
    # NOTE: Maokai Q Bramble Smash terrain-stun is conditional (already
    # cc_conditional wave 2 entry) and stays REJECTED here per the
    # no-conditional-CC selection rule.
    registry.setdefault("Maokai", {})["W"] = (1.0, 1.1, 1.2, 1.3, 1.4)
    # Rakan R - The Quickness: charm 1.0/1.25/1.5 across 3 ranks
    # (canonical 16.10.1 Meraki value via Disable Duration block).
    # Rakan dashes around an area for up to 4s; enemies he touches
    # during the dash are charmed. The charm-on-touch is unconditional
    # once R is cast (the dash IS the cast). Multi-wave augmentation:
    # Rakan W Grand Entrance knock-up was seeded wave 1; setdefault
    # allows R to coexist.
    registry.setdefault("Rakan", {})["R"] = (1.0, 1.25, 1.5)
    # Wave 8 REJECTED candidates (with reason recorded so future audits
    # do NOT re-research):
    # * Bard Q Cosmic Binding: already in cc_conditional wave 1 entry
    #   (terrain-bounce double-stun conditional axis).
    # * Evelynn W Allure: charm/stun is detonation-on-Eve-attack
    #   conditional (target must be auto-attacked by Eve to apply the
    #   charm); REJECT - belongs in cc_conditional if added later.
    # * Karma W Focused Resolve: already in cc_conditional wave 1
    #   (channel-completion full-tether root).
    # * Morgana R Soul Shackles: stun fires on tether expiry which
    #   requires target staying in range for 3s OR dying mid-tether;
    #   channel-completion-conditional axis; REJECT - belongs in
    #   cc_conditional if added later (parallel to Karma W).
    # * Seraphine E Beat Drop: stun OR root duration is the same value
    #   but which CC fires is conditional on target state (still target
    #   gets root, moving/slowed target gets stun); REJECT per item 138
    #   conditional-CC rule (target state is a conditional axis).
    # * TwistedFate W Pick a Card: already in cc_conditional wave 1
    #   (gold-card selection conditional stun).
    # * Volibear R Stormbringer: 2/3/4s Turret Disable Duration - the
    #   disable is on STRUCTURES (turrets), not on champion CC; carryover
    #   from items 138 REJECT list.
    # * Zilean Q Time Bomb: already in cc_conditional wave 2 (double-
    #   bomb stack conditional stun).
    # * Senna W Last Embrace: ALREADY in wave 4 (item 145's REJECT-list
    #   note "Senna W (unconditional)" matched the existing wave-4 entry;
    #   verified via grep on ability_dps.py - line 1182 has Senna W
    #   root 1.25/1.5/1.75/2.0/2.25 seeded item 138 wave 4).
    # * Tristana W Rocket Jump landing: REJECT per item 140 wave 6 list
    #   (the landing applies a small slow not a discrete knockback at
    #   16.10.1; only the Tristana R buster-shot knockback is canonical
    #   and was seeded wave 3).
    # * Aatrox W Infernal Chains: already in cc_conditional wave 4
    #   (debuffed-target persistence pull-back root).
    # * Skarner Q Shattered Earth + Upheaval: already in cc_conditional
    #   wave 2 (nth-hit knockup).
    # FINAL wave 8 net: 3 spell entries / 0 NEW champions / 3 multi-
    # wave augmentations (Lissandra W + Maokai W + Rakan R). Total
    # registry: 106 entries across 89 champs (unchanged champ count
    # because all 3 augmentations are on existing champions).
    # ----- ENGINE wave 9 (2026-05-22) -----
    # +2 entries / 0 new champions / 2 multi-wave augmentations. Per
    # item 146 carry (j): "wave 9+ likely thin pool (saturation for
    # net-new champions). The unconditional first-order CC at 16.10.1
    # is genuinely saturated for net-new champions, future waves either
    # coexist on already-registered champs OR need new schema." Wave 9
    # delivers exactly that - all wave 9 candidates are multi-wave
    # coexistence on already-registered champions. The wave 9 audit
    # walked every UNREGISTERED spell of every already-registered
    # champion in data/daemon_slayer/16.10.1/champion_abilities.json
    # for explicit Stun/Root/Silence/Charm/Fear/Taunt/Sleep/Suppression/
    # Knockup/Knockback/Airborne/Stasis Duration blocks. Result: 6
    # candidates surfaced from the abilities-data grep, of which 2 are
    # genuine unconditional first-order CC (Chogath W silence + Malzahar
    # Q silence) and 4 are already-known conditional / out-of-scope
    # rejects (see REJECT block below).
    # Selection rules unchanged from waves 1-8: first-order CC only
    # (stuns / roots / suspensions / knock-ups / knock-backs / charms /
    # sleeps / fear / suppressions / polymorphs / taunts / pulls /
    # stasis / silence / banishment); no slows; no conditional CC; no
    # self-CC; canonical DDragon ids.
    # Chogath W - Feral Scream: silence 1.6/1.7/1.8/1.9/2.0 across 5
    # ranks (canonical 16.10.1 Meraki value via Silence Duration block
    # in champion_abilities.json). Cone-shaped magic damage + silence
    # on cast; enemies in the cone are silenced unconditionally once W
    # is cast. Multi-wave augmentation: Chogath Q Rupture knockup was
    # seeded wave 2; the setdefault builder allows Chogath W to coexist
    # on the same champion's spell map. Silence is first-order CC per
    # the wave 9 scope expansion (matches the Mordekaiser E pull family
    # admission from wave 5 - hard-disable types that fit cleanly
    # alongside stun / root / suspension / suppression).
    registry.setdefault("Chogath", {})["W"] = (1.6, 1.7, 1.8, 1.9, 2.0)
    # Malzahar Q - Call of the Void: silence 1.0/1.25/1.5/1.75/2.0
    # across 5 ranks (canonical 16.10.1 Meraki value via Silence
    # Duration block in champion_abilities.json). Two void zones AOE
    # location-cast; enemies caught in the path between zones are
    # silenced unconditionally on contact. Multi-wave augmentation:
    # Malzahar R Nether Grasp suppression was seeded wave 1; the
    # setdefault builder allows Malzahar Q to coexist on the same
    # champion's spell map. This is a SECOND silence-family entry in
    # wave 9 alongside Chogath W; both share the same silence CC kind
    # which is added to the first-order CC scope in this wave per the
    # same precedent as wave 6 stasis (Bard R Tempered Fate).
    registry.setdefault("Malzahar", {})["Q"] = (1.0, 1.25, 1.5, 1.75, 2.0)
    # Wave 9 REJECTED candidates (with reason recorded so future audits
    # do NOT re-research):
    # * Bard Q Cosmic Binding: already in cc_conditional wave 1 entry
    #   (terrain-bounce double-stun conditional axis); the unconditional
    #   first-stun-on-direct-hit piece is fired on every cast but the
    #   double-stun-on-bounce semantics are conditional. REJECT per
    #   carryover from waves 4-8 + cc_conditional schema-lift.
    # * Morgana R Soul Shackles: stun 1.5/1.75/2.0 across 3 ranks IS
    #   in the Stun Duration block - BUT the stun fires only on tether
    #   expiry which requires target staying in range for ~3s OR dying
    #   mid-tether. This is channel-completion-conditional and was
    #   explicitly REJECTED in item 146 wave 8 - belongs in
    #   cc_conditional if added later (parallel to Karma W).
    # * Seraphine E Beat Drop: stun OR root duration 1.1/1.2/1.3/1.4/1.5
    #   across 5 ranks. Already REJECTED in waves 4 + 8 - target state
    #   determines which CC fires (still target gets root, moving/slowed
    #   target gets stun). Conditional axis per item 138 rule.
    # * Volibear R Stormbringer: 2/3/4s Turret Disable Duration - the
    #   disable is on STRUCTURES (turrets), not on champion CC.
    #   Carryover REJECT from items 138 + 142 + 146.
    # * Janna R Monsoon: initial knockup on cast + heal channel; the
    #   initial knockup is the cast-portion CC but its duration is not
    #   exposed in the damage_blocks (only Heal Per Tick + Total Heal).
    #   The knockup duration is brief (~0.5s tooltip-stated) and the
    #   channel itself is a slow-pulse-with-heal not a hard CC. REJECT
    #   per the unwillingness to encode a value not present in the
    #   Meraki bulk - operator-tunable channel-knockup is best deferred
    #   to cc_conditional with a channel-completion gate.
    # * Lulu E Help, Pix!: shield/damage only, no CC.
    # * 226 other UNREGISTERED spells of the 89 registered champions:
    #   all have NO Stun/Root/Silence/Charm/Fear/Taunt/Sleep/Suppression/
    #   Knockup/Knockback/Airborne/Stasis Duration block in
    #   champion_abilities.json. The data lane is genuinely saturated.
    # FINAL wave 9 net: 2 spell entries / 0 NEW champions / 2 multi-
    # wave augmentations (Chogath W silence + Malzahar Q silence).
    # Total registry: 108 entries across 89 champs (unchanged champ
    # count because all augmentations are on existing champions). Per
    # item 146 carry (j) prediction, wave 9 surfaces only thin
    # multi-wave coexistence and the unconditional first-order CC pool
    # at 16.10.1 remains saturated for net-new champions.
    return registry


_PER_SPELL_CC_DURATIONS: dict[str, dict[str, tuple[float, ...]]] = (
    _build_per_spell_cc_durations()
)


def _per_spell_cc_for(champion_id: str, spell_key: str) -> tuple[float, ...]:
    """Read a champion+spell base CC duration tuple from the registry.

    Returns ``()`` when the champion is absent, the spell is absent, or
    the registry entry is empty. Forward-marker: the registry is empty
    at 1.29.0 by design so all calls return ``()``; tests inject a
    monkey-patched entry to exercise consumer math.
    """
    champ_entry = _PER_SPELL_CC_DURATIONS.get(champion_id, {})
    return tuple(champ_entry.get(spell_key, ()))


def _apply_tenacity_to_cc_tuple(
    base_cc: tuple[float, ...], tenacity_mult: float,
) -> tuple[float, ...]:
    """Apply ``effective_cc_duration`` element-wise to a base-CC tuple.

    Free-function wrapper around ``ehp.effective_cc_duration`` (the
    helper shipped 1.25.0). Routed through this module-local helper so
    the call site is grep-able and the engine layer stays read-only
    against ``ehp.py``. Returns an empty tuple when the input is empty.

    Floors at 0.0 per-element via the underlying helper. SR + non-ARAM
    modes with ``tenacity_mult == 1.0`` return identity values (the
    tuple is byte-equal to the input modulo float casting).
    """
    if not base_cc:
        return ()
    return tuple(
        effective_cc_duration(float(s), float(tenacity_mult)) for s in base_cc
    )


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
    doesn't have measured rewind data - measured casts/sec already
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
    """Per-spell-key breakdown returned by ``compute_ability_dps``.

    ENGINE 1.23.0 (2026-05-20): added ``base_cooldown`` + ``total_ability_haste``
    fields. The existing ``cooldown`` field now stores the EFFECTIVE
    post-haste cooldown (``base_cooldown / (1 + total_ability_haste / 100)``).
    SR mode + most ARAM champions (those with aramAbilityHaste=0) see
    identity: ``cooldown == base_cooldown``.

    ENGINE 1.29.0 (2026-05-21): added ``cc_duration_s`` +
    ``cc_duration_post_tenacity`` per-spell tuples (2nd consumer of the
    ``effective_cc_duration`` helper shipped 1.25.0). Both default to
    ``()`` empty tuple because the ``_PER_SPELL_CC_DURATIONS`` registry
    is empty at 1.29.0 by design (forward-marker; future patches
    populate it when a downstream EHP-vs-CC blended scorer / fight-sim
    consumer ships). When populated, ``cc_duration_s`` is the per-rank
    base (length 5 for Q/W/E, length 3 for R) and
    ``cc_duration_post_tenacity`` is the same shape after element-wise
    ``effective_cc_duration(base, aram_tenacity_mult)`` - identity in
    SR + non-ARAM modes; lengthened in ARAM for the 15 champs with
    aramTenacity > 1.0.
    """
    key: str
    form_name: str
    form_index: int
    rank: int
    cooldown: float                     # effective post-haste cooldown
    cost: float
    damage_type: str | None
    resource: str | None
    raw_damage_per_cast: float          # base + all scaling, pre-mode, pre-mitigation
    post_mode_damage_per_cast: float    # x mode_multiplier
    post_mitigation_damage_per_cast: float
    casts_per_sec: float                # measured (if available) or theoretical
    casts_per_sec_source: str           # "measured" | "theoretical_with_mana_uptime" | "missing"
    mana_uptime_factor: float
    dps: float
    base_cooldown: float = 0.0          # pre-haste rank cooldown (ENGINE 1.23.0)
    total_ability_haste: float = 0.0    # haste sum used in haste formula (ENGINE 1.23.0)
    cc_duration_s: tuple[float, ...] = ()                # per-rank base CC duration (ENGINE 1.29.0)
    cc_duration_post_tenacity: tuple[float, ...] = ()    # cc_duration_s x aram_tenacity_mult (ENGINE 1.29.0)
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
            "base_cooldown": self.base_cooldown,
            "total_ability_haste": self.total_ability_haste,
            "cc_duration_s": list(self.cc_duration_s),
            "cc_duration_post_tenacity": list(self.cc_duration_post_tenacity),
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class AbilityDpsResult:
    """Top-level result from ``compute_ability_dps``.

    ENGINE 1.23.0 (2026-05-20): added ``aram_ability_haste`` (consumed
    by the per-spell cooldown haste formula) and ``aram_tenacity_mult``
    (forwarded for a future EHP-side enemy-CC consumer; not consumed in
    this slice - see module-level TODO).
    """
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
    block_index_resolved: "dict[str, int | list[int] | dict[str, int | list[int]]]" = field(default_factory=dict)
    stats: dict[str, float] = field(default_factory=dict)
    aram_ability_haste: float = 0.0                 # consumed haste delta (ENGINE 1.23.0)
    aram_tenacity_mult: float = 1.0                 # forwarded for future EHP consumer (ENGINE 1.23.0)
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
            "aram_ability_haste": self.aram_ability_haste,
            "aram_tenacity_mult": self.aram_tenacity_mult,
            "notes": list(self.notes),
        }

    def format_table(self) -> str:
        head = (
            f"{self.champion_name} ({self.champion_id}) - lvl {self.level} "
            f"- mode {self.mode}  [MAGE]"
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
        # No scaling found - could be all-base or unparsed.
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
    block_index_overrides: "Optional[dict[str, int | list[int] | dict[str, int | list[int]]]]" = None,
) -> AbilityDpsResult:
    """Compute total ability DPS for the resolved build.

    Mirror of ``compute_dps``'s contract - same ``snapshot``, ``mode``,
    ``target_*``, and ``augments`` plumbing - but the result decomposes by
    spell key instead of by rotation phase.

    Parameters
    ----------
    target_current_hp_pct:
        Assumed fraction of max HP the target sits at when the cast lands
        (default 1.0 = full HP). Affects ``target_missing_hp_pct`` /
        ``target_current_hp_pct`` blocks only.
    abilities_snapshot:
        Optional override - defaults to the lazy-cached snapshot from
        ``abilities.load_default()``. Test fixtures pass synthetic ones.
    max_priority:
        Optional three ability keys (e.g. ``("E", "Q", "W")``) describing
        max order - first key is maxed first, third last. When ``None``,
        the per-champion override registry (``champion_max_priority.json``)
        is consulted; falls back to Q-W-E for unmapped champions.
    block_strategy:
        Global strategy for multi-block abilities - ``"first"`` (default),
        ``"sum"``, ``"max"``, or ``"indexed"``. Per-key overrides via
        ``block_index_overrides`` switch a specific key to ``"indexed"``
        with the supplied block_index; keys without an entry fall back to
        the global strategy. See module docstring for rationale.
    form_index_overrides:
        Per-key form index overrides - e.g. ``{"Q": 2}`` to evaluate
        Aphelios's Q with the 3rd weapon stance. Default 0 for all keys.
    block_index_overrides:
        Per-key damage-block index overrides - e.g. ``{"E": 1}`` to evaluate
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
            # crashing - the server can return a body explaining the missing
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

    # Mode damage multiplier (ARAM aramDamageDealt only - EHP scorer uses
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
    # magic amp would be invisible to the ability scorer - making item
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
    # frozen - use dataclasses.replace.
    ctx = replace(ctx, ap=ap_total)

    # Build-wide damage amps applied at per-cast level (not per-spell -
    # amps don't discriminate between Q and W). Folded into ``damage_amp``
    # which multiplies the post-mitigation per-cast damage.
    damage_amp = total_damage_amp_multiplier(item_effects)
    damage_amp *= total_target_bonus_hp_amp_multiplier(item_effects, target_bonus_hp)
    damage_amp *= total_giant_slayer_multiplier(
        item_effects, target_max_hp, ctx.caster_max_hp,
    )
    magic_amp = total_magic_amp_multiplier(item_effects)

    # Effective resists: armor pipeline mirrors compute_dps via
    # ``effective_target_armor`` - flat reduction -> % reduction -> %
    # pen -> flat pen (lethality is level-scaled into the flat-pen
    # term). Magic has the symmetric pipeline (Void Staff %,
    # Sorcerer's Shoes flat).
    target_armor_eff = effective_target_armor(target_armor, item_effects, level)
    target_mr_eff = effective_target_mr(target_mr, item_effects)

    # ENGINE 1.23.0 (2026-05-20) - ability-haste consumption.
    # Read the engine-exposed aramAbilityHaste delta (stripped to 0
    # outside ARAM mode by ``_total_ability_haste``).
    # ENGINE 1.24.0 (2026-05-21) - item-AH lane wired via
    # ``_item_ability_haste`` registry. ``base_ah`` is the sum of flat
    # AH across the build's item ids (DDragon items.json strips AH from
    # the structured ``stats`` block, so the registry carries the
    # parsed-from-description values). SR Black Cleaver + Cosmic Drive
    # = 20 + 25 = 45 AH -> 7s base CD -> 4.83s effective. Single
    # haste-total applies uniformly to all 4 spell keys (Q/W/E/R) at
    # the engine layer - per-spell amplifiers are out of scope.
    base_ah = total_item_ability_haste(resolved.item_ids)
    total_ah = _total_ability_haste(resolved.stats, mode, base_ah=base_ah)
    # Forward the tenacity multiplier for downstream EHP consumers.
    # NOT consumed in this slice - see module-level TODO.
    aram_tenacity_mult = float(resolved.stats.get("aram_tenacity_mult", 1.0))

    # Resolve forms for Q/W/E/R. Champions may lack a key in the snapshot
    # - surface a zero spell rather than raising so partial coverage is
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
                f"no {key} ability recorded for {resolved.champion_id} - skipped",
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
        base_cooldown = _form_cooldown_at_rank(form, rank, fallback_form=fallback)
        # ENGINE 1.23.0 - apply haste formula to the rank cooldown so
        # the theoretical fallback rate + the surfaced .cooldown field
        # reflect the operator's true rotation cadence. Identity for
        # total_ah == 0 (SR mode + most ARAM champions).
        cooldown = _effective_ability_cd(base_cooldown, total_ah)
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
        # ENGINE 1.29.0 (2026-05-21) - per-spell CC duration extractor.
        # Reads ``_PER_SPELL_CC_DURATIONS`` (empty at 1.29.0, forward-marker
        # for a future EHP-vs-CC blended scorer / fight-sim consumer). The
        # post-tenacity tuple is the same shape with each element passed
        # through ``effective_cc_duration(base, aram_tenacity_mult)``;
        # identity in SR + non-ARAM modes; lengthened in ARAM for 15
        # champs with aramTenacity > 1.0.
        cc_base = _per_spell_cc_for(resolved.champion_id, key)
        cc_post_ten = _apply_tenacity_to_cc_tuple(cc_base, aram_tenacity_mult)
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
            base_cooldown=base_cooldown,
            total_ability_haste=total_ah,
            cc_duration_s=cc_base,
            cc_duration_post_tenacity=cc_post_ten,
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
            "fallback - DPS contribution is 0"
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

    # ENGINE 1.23.0: surface a note when haste actually shortened or
    # lengthened the rotation so consumers can see the consumed delta.
    if total_ah != 0.0:
        notes.append(
            f"ARAM aramAbilityHaste={total_ah:+.0f} on per-spell cooldowns "
            f"(eff_cd = base / (1 + AH/100))"
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
        aram_ability_haste=total_ah,
        aram_tenacity_mult=aram_tenacity_mult,
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
    block_index_resolved: "Optional[dict[str, int | list[int] | dict[str, int | list[int]]]]" = None,
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
