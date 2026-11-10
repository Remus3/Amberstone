# arch: HZ-C2 precomputed BUILD A/B choice-coach over the HZ-B2 variants table | section=core | frozen=no
"""HZ-C2 - deterministic BUILD A/B choice-coach over the precomputed HZ-B2
anti-tank / anti-squishy build-order VARIANTS. PRIMARY north star: drive live
Haiku usage to ZERO.

PURPOSE
    The live coach pays a Claude Haiku call to answer "do I pivot anti-tank into
    this enemy comp, and what do I buy". HZ-B2 (``core.build_order_variants``)
    already PRECOMPUTES an ``anti_tank`` vs ``anti_squishy`` ordered-build PAIR
    per ``(my_champ x mode)``. This module is the request-time READER that
    classifies the LIVE enemy comp's durability and turns the recommended
    variant into two grounded BUILD A/B ``CoachChoice`` objects (A = the
    lean-matched variant, B = the other extreme), each carrying the next item +
    the A3 anti-tank provenance. PURE static table read - no Haiku, no :8860
    network.

    v1 is SHADOW ONLY (charter 4b "do not flip blind"): recorded alongside live
    Haiku (``core.hz_build_shadow``) for offline validation; NO coach flip.

DURABILITY CLASSIFIER (live enemy comp -> recommended variant)
    ``core.aram_comp_verdict.compute_factors`` over the enemy champion names
    yields a ``frontline_count`` (Tank tag, or melee Fighter) - deterministic
    over champions.json facts, correct-by-construction (NOT prediction). A wall
    of ``>= _ANTI_TANK_FRONTLINE`` frontliners leans ``anti_tank``; otherwise
    ``anti_squishy``.

FAIL-SOFT (S144-T-673)
    No resolved enemy / missing table / uncovered champ / unknown mode -> ``[]``
    (the caller keeps its existing path). Neither public function raises. Junk
    in ONE input degrades only that input: a malformed item-cost row renders the
    bare item id, a non-finite cost renders the name alone, a junk owned count
    reads as 0 and a junk owned-id set falls back to the owned-count index - none
    of them sinks the whole A/B pair. An unexpected failure that does reach the
    catch-all is logged once per exception type, never swallowed silently.
"""
from __future__ import annotations

import logging
import math
from collections.abc import Iterable, Mapping, Sequence
from numbers import Real
from typing import Optional, Tuple

from core.archetype_picks import canonical_champion_id
from core.aram_comp_verdict import compute_factors
from core.build_order_variants import (
    DS_MODE_KEYS,
    load_build_order_variants,
    lookup,
)
from core.coach_choices import CoachChoice

_log = logging.getLogger(__name__)

# A frontline wall of this many tanks / melee-fighters leans the recommendation
# to anti_tank; below it, the squishy extreme.
_ANTI_TANK_FRONTLINE: int = 2

SOURCE_TAG: str = "ds-precompute-build"

_VARIANT_LABELS: dict[str, str] = {
    "anti_tank": "Build anti-tank",
    "anti_squishy": "Build anti-squishy",
}

# The only modes the HZ-B2 table is generated for. A caller mode reaches the
# loader's FILE NAME, so anything else is refused before the load.
_KNOWN_MODES: frozenset[str] = frozenset(DS_MODE_KEYS)

# Exception type names already logged by build_choices' catch-all, so a failure
# that repeats on every coach tick logs once per process, not once per tick.
_LOGGED_FAILURES: set[str] = set()

# A bare string / bytes / mapping is never a list of names or ids: iterating it
# would yield characters or keys.
_NOT_A_COLLECTION = (str, bytes, bytearray, Mapping)


def _other(variant: str) -> str:
    return "anti_squishy" if variant == "anti_tank" else "anti_tank"


def _as_list(value: object) -> Optional[list]:
    """``value`` materialised as a list, or None when it is not a collection
    of entries (a bare string, bytes, a mapping, or a non-iterable)."""
    if value is None or isinstance(value, _NOT_A_COLLECTION):
        return None
    try:
        return list(value)  # type: ignore[call-overload]
    except TypeError:
        return None


def _id_key(value: object) -> Optional[str]:
    """Canonical string key for an item id, or None for a junk entry.

    ``3135``, ``"3135"``, ``" 3135 "`` and ``3135.0`` all map to ``"3135"`` so
    a live int id matches a table string id. A bool, a non-integral or
    non-finite float, None and a blank string are not ids."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if math.isfinite(value) and value.is_integer():
            return str(int(value))
        return None
    if isinstance(value, str):
        return value.strip() or None
    return None


def comp_lean(enemy_comp: Sequence[str]) -> Optional[Tuple[str, str]]:
    """Recommended variant + confidence for a live enemy comp, or None.

    Returns ``(variant, confidence)``. ``anti_tank`` when the resolved comp
    carries ``>= _ANTI_TANK_FRONTLINE`` frontliners, else ``anti_squishy``.
    Confidence reflects how decisive the wall (or its absence) is. None when no
    enemy name resolves against champions.json (cannot classify), and None for
    an ``enemy_comp`` that is not a collection of names (a bare string, a
    mapping, a non-iterable) - never a raise."""
    names = _as_list(enemy_comp)
    if not names:
        return None
    factors = compute_factors(names)
    n = int(factors.get("n") or 0)
    if n <= 0:
        return None
    front = int(factors.get("frontline_count") or 0)
    if front >= _ANTI_TANK_FRONTLINE:
        conf = "high" if front >= 3 else "mid"
        return "anti_tank", conf
    conf = "high" if (front == 0 and n >= 3) else "mid"
    return "anti_squishy", conf


def _fmt_item(iid: object, item_costs: Optional[Mapping]) -> str:
    """``"Name (Ng)"`` for a known id, else ``"item <id>"``.

    ``item_costs`` maps ``item_id_str -> (display_name, total_gold)``. A row
    that is not a ``(non-blank str, cost)`` pair renders ``"item <id>"``; a
    cost that is not a finite non-negative number (a bool included) renders the
    name alone. A bad row never raises."""
    key = _id_key(iid)
    iid_s = key if key is not None else str(iid)
    row = item_costs.get(iid_s) if isinstance(item_costs, Mapping) else None
    if not isinstance(row, (tuple, list)) or len(row) != 2:
        return f"item {iid_s}"
    name, cost = row
    if not isinstance(name, str) or not name.strip():
        return f"item {iid_s}"
    name = name.strip()
    if (isinstance(cost, bool) or not isinstance(cost, Real)
            or not math.isfinite(cost) or cost < 0):
        return name
    return f"{name} ({int(cost)}g)"


def _owned_count(value: object) -> int:
    """The owned-item count as an int; a bool, a non-number or a non-finite
    value reads as 0."""
    if isinstance(value, bool) or not isinstance(value, Real):
        return 0
    if not math.isfinite(value):
        return 0
    return int(value)


def _next_item_str(
    order: Sequence[object],
    owned_count: int,
    item_costs: Optional[Mapping],
    owned_ids: Optional[Iterable[object]] = None,
) -> Optional[str]:
    """``"Name (Ng)"`` (or ``"item <id>"``) for the next un-bought core item,
    or None when the build order is finished / empty. ``item_costs`` maps
    ``item_id_str -> (display_name, total_gold)``. Junk order entries (None,
    a bool, a blank string) are skipped.

    When ``owned_ids`` (the live owned completed-item id set) is supplied, the
    next item is the first order entry whose id is NOT owned - deviation-robust,
    so the chip never recommends an item the player already holds even when they
    built off the canonical sequence (the live 'recommends an item you already
    own / conflicts with your build' bug). With ``owned_ids`` None, empty (an
    exhausted iterator included) or junk (a bare string, a mapping, a
    non-iterable) it falls back to the legacy ``order[owned_count]`` index."""
    entries = _as_list(order) or []
    keys = [k for k in (_id_key(e) for e in entries) if k is not None]
    if not keys:
        return None
    owned_list = _as_list(owned_ids)
    owned_set = {k for k in (_id_key(x) for x in owned_list or []) if k is not None}
    if owned_set:
        for key in keys:
            if key not in owned_set:
                return _fmt_item(key, item_costs)
        return None  # every core item in the order is already owned
    oc = _owned_count(owned_count)
    if not (0 <= oc < len(keys)):
        return None
    return _fmt_item(keys[oc], item_costs)


def _variant_outcome(
    cell: dict,
    variant: str,
    owned_count: int,
    item_costs: Optional[Mapping],
    owned_ids: Optional[Iterable[object]] = None,
) -> str:
    """DS-backed expected-outcome line for one variant choice: the next item +
    the A3 anti-tank provenance note. The note follows ``variant`` - the
    variant the cell was LOOKED UP under, which is also the choice's label -
    never the cell's own ``variant`` field, which an older or hand-edited
    table may lack."""
    order = cell.get("order") if isinstance(cell.get("order"), list) else []
    nxt = _next_item_str(order, owned_count, item_costs, owned_ids)
    at = cell.get("antitank") if isinstance(cell.get("antitank"), dict) else {}
    if variant == "anti_tank":
        if at.get("lean_in"):
            note = "kit already shreds; light pen"
        elif at.get("recommend_antitank_items"):
            note = "front-load pen / %max-HP"
        else:
            note = "pen vs the wall"
    else:
        note = "raw early power vs squishies"
    return f"next {nxt}; {note}" if nxt else note


def _log_failure_once(exc: BaseException) -> None:
    name = type(exc).__name__
    if name in _LOGGED_FAILURES:
        return
    _LOGGED_FAILURES.add(name)
    _log.warning("precomputed build coach: build_choices failed (%s: %s); "
                 "returning no choices (logged once per exception type)",
                 name, exc)


def build_choices(
    my_champion: str,
    enemy_comp: Sequence[str],
    mode: str = "sr",
    *,
    payload: Optional[dict] = None,
    item_costs: Optional[Mapping] = None,
    owned_count: int = 0,
    owned_ids: Optional[Iterable[object]] = None,
) -> list[CoachChoice]:
    """Two BUILD A/B choices for the live (champ vs comp) state, or ``[]``.

    A = the durability-lean-matched variant (the recommendation, confidence from
    the classifier margin); B = the other extreme. ``payload`` overrides the
    loaded HZ-B2 table (test seam). Without it, ``mode`` must name a generated
    table (``sr`` / ``aram`` / ``arena``, any case, surrounding space ignored);
    any other mode returns ``[]`` without touching the loader. Fail-soft to
    ``[]`` on an unresolvable comp, a missing table, or an uncovered champion;
    never raises."""
    try:
        if not my_champion:
            return []
        lean = comp_lean(enemy_comp)
        if lean is None:
            return []
        variant, conf = lean
        if payload is not None:
            data = payload
        else:
            mode_key = mode.strip().lower() if isinstance(mode, str) else ""
            if mode_key not in _KNOWN_MODES:
                return []
            data = load_build_order_variants(mode_key)
        my_id = canonical_champion_id(str(my_champion))
        rec = lookup(data, my_id, variant)
        if not rec:
            return []
        a = CoachChoice(
            key="A",
            label=_VARIANT_LABELS[variant],
            expected_outcome=_variant_outcome(
                rec, variant, owned_count, item_costs, owned_ids),
            confidence=conf,
            source_tag=SOURCE_TAG,
        )
        other = _other(variant)
        other_cell = lookup(data, my_id, other)
        b_outcome = (
            _variant_outcome(other_cell, other, owned_count, item_costs, owned_ids)
            if other_cell else "alternative durability build"
        )
        b = CoachChoice(
            key="B",
            label=_VARIANT_LABELS[other],
            expected_outcome=b_outcome,
            confidence="low",
            source_tag=SOURCE_TAG,
        )
        return [a, b]
    except Exception as exc:  # noqa: BLE001 - the coach hot path must never raise
        _log_failure_once(exc)
        return []


__all__ = ["SOURCE_TAG", "build_choices", "comp_lean"]
