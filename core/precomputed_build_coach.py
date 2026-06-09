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
    the A3 anti-tank provenance. PURE static table read - no Haiku, no :8893
    network.

    v1 is SHADOW ONLY (charter 4b "do not flip blind"): recorded alongside live
    Haiku (``core.hz_build_shadow``) for offline validation; NO coach flip.

DURABILITY CLASSIFIER (live enemy comp -> recommended variant)
    ``core.aram_comp_verdict.compute_factors`` over the enemy champion names
    yields a ``frontline_count`` (Tank tag, or melee Fighter) - deterministic
    over champions.json facts, correct-by-construction (NOT prediction). A wall
    of ``>= _ANTI_TANK_FRONTLINE`` frontliners leans ``anti_tank``; otherwise
    ``anti_squishy``.

FAIL-SOFT
    No resolved enemy / missing table / uncovered champ -> ``[]`` (the caller
    keeps its existing path). Never raises.
"""
from __future__ import annotations

from typing import Optional, Sequence, Tuple

from core.aram_comp_verdict import compute_factors
from core.build_order_variants import load_build_order_variants, lookup
from core.coach_choices import CoachChoice

# A frontline wall of this many tanks / melee-fighters leans the recommendation
# to anti_tank; below it, the squishy extreme.
_ANTI_TANK_FRONTLINE: int = 2

SOURCE_TAG: str = "ds-precompute-build"

_VARIANTS: Tuple[str, str] = ("anti_tank", "anti_squishy")
_VARIANT_LABELS: dict[str, str] = {
    "anti_tank": "Build anti-tank",
    "anti_squishy": "Build anti-squishy",
}


def _other(variant: str) -> str:
    return "anti_squishy" if variant == "anti_tank" else "anti_tank"


def comp_lean(enemy_comp: Sequence[str]) -> Optional[Tuple[str, str]]:
    """Recommended variant + confidence for a live enemy comp, or None.

    Returns ``(variant, confidence)``. ``anti_tank`` when the resolved comp
    carries ``>= _ANTI_TANK_FRONTLINE`` frontliners, else ``anti_squishy``.
    Confidence reflects how decisive the wall (or its absence) is. None when no
    enemy name resolves against champions.json (cannot classify)."""
    factors = compute_factors(list(enemy_comp or []))
    n = int(factors.get("n") or 0)
    if n <= 0:
        return None
    front = int(factors.get("frontline_count") or 0)
    if front >= _ANTI_TANK_FRONTLINE:
        conf = "high" if front >= 3 else "mid"
        return "anti_tank", conf
    conf = "high" if (front == 0 and n >= 3) else "mid"
    return "anti_squishy", conf


def _next_item_str(
    order: Sequence[object],
    owned_count: int,
    item_costs: Optional[dict],
) -> Optional[str]:
    """``"Name (Ng)"`` (or ``"item <id>"``) for the next un-bought core item,
    or None when the build order is finished / empty. ``item_costs`` maps
    ``item_id_str -> (display_name, total_gold)``."""
    try:
        oc = int(owned_count)
    except (TypeError, ValueError):
        oc = 0
    if not order or not (0 <= oc < len(order)):
        return None
    iid = str(order[oc])
    if item_costs and iid in item_costs:
        name, cost = item_costs[iid]
        if name:
            try:
                return f"{name} ({int(cost)}g)"
            except (TypeError, ValueError):
                return str(name)
    return f"item {iid}"


def _variant_outcome(
    cell: dict,
    owned_count: int,
    item_costs: Optional[dict],
) -> str:
    """DS-backed expected-outcome line for one variant choice: the next item +
    the A3 anti-tank provenance note."""
    order = cell.get("order") if isinstance(cell.get("order"), list) else []
    nxt = _next_item_str(order, owned_count, item_costs)
    at = cell.get("antitank") if isinstance(cell.get("antitank"), dict) else {}
    variant = str(cell.get("variant") or "")
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


def build_choices(
    my_champion: str,
    enemy_comp: Sequence[str],
    mode: str = "sr",
    *,
    payload: Optional[dict] = None,
    item_costs: Optional[dict] = None,
    owned_count: int = 0,
) -> list[CoachChoice]:
    """Two BUILD A/B choices for the live (champ vs comp) state, or ``[]``.

    A = the durability-lean-matched variant (the recommendation, confidence from
    the classifier margin); B = the other extreme. ``payload`` overrides the
    loaded HZ-B2 table (test seam). Fail-soft to ``[]`` on an unresolvable comp,
    a missing table, or an uncovered champion."""
    try:
        if not my_champion:
            return []
        lean = comp_lean(enemy_comp)
        if lean is None:
            return []
        variant, conf = lean
        data = payload if payload is not None else load_build_order_variants(mode)
        rec = lookup(data, str(my_champion), variant)
        if not rec:
            return []
        a = CoachChoice(
            key="A",
            label=_VARIANT_LABELS[variant],
            expected_outcome=_variant_outcome(rec, owned_count, item_costs),
            confidence=conf,
            source_tag=SOURCE_TAG,
        )
        other = _other(variant)
        other_cell = lookup(data, str(my_champion), other)
        b_outcome = (
            _variant_outcome(other_cell, owned_count, item_costs)
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
    except Exception:  # noqa: BLE001 - the coach hot path must never raise
        return []


__all__ = ["SOURCE_TAG", "comp_lean", "build_choices"]
