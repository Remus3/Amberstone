"""Per-champion override-registry loaders (relocated from ability_dps.py,
item 241 A2).

The three lazy-singleton loaders - max_priority / form_index / block_index - share
an identical cache + lock + reset-hook shape. Extracted here as one focused module;
``ability_dps`` re-exports every public symbol (the ``get_*_for`` resolvers, the
``reset_*_cache`` test hooks, ``DEFAULT_MAX_PRIORITY``, and the block-index helpers)
so all consumer imports and the cache-reset test seams keep working unchanged.

Self-contained: depends only on the stdlib plus ``DamageBlock`` from ``abilities``;
it does NOT import ``ability_dps`` (preserving the load-order / no-cycle invariant).
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Optional, Sequence

from .abilities import DamageBlock

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
# dict mapping a target-state condition -> int|list[int]. ``"default"`` is
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
# Phase 5.9.29 (s229, 2026-05-16): generalized ``target_no_cc`` ->
# ``target_no_setup``. s228 scoped the non-HP condition to its CC-family
# flagships (Zoe sleep / Evelynn charm), but the seed-expansion candidates
# (Anivia E vs *Chilled*, Brand W vs *ablaze*, Cassiopeia E vs *poisoned*,
# mark-based amps) share the identical modeling semantic regardless of
# debuff *type*: the operator's own ability applied an amp-enabling target
# state; the amped block is the operator-commits/canonical assumption, the
# downgrade is when that state is absent. Naming it after "CC" was a
# false narrowing - 5+ concrete uses -> the honest general term.
_BLOCK_INDEX_CONDITIONS: frozenset[str] = frozenset({
    "target_full_hp",    # live target above the execute/low-HP threshold ->
                          # pick the non-execute block (Kindred E 5% vs 7.5%
                          # missing-HP, Veigar/Morgana-class HP-threshold amps)
    "target_no_setup",   # the operator's amp-enabling target state - CC /
                          # sleep / charm / chill / ablaze / poison / mark -
                          # is NOT present -> pick the un-amped block (Zoe E
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
    target-state condition -> int|list[int]. The dict MUST contain a
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
