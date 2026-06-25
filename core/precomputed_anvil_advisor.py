# arch: arena item-anvil deterministic substrate | section=core | frozen=no
"""core/precomputed_anvil_advisor.py - deterministic arena item-anvil substrate.

The do-not-flip-blind precompute twin of the Tier-1 arena item-anvil Haiku call
(coaches/arena_coach.py purpose="arena_anvil"). The live coach still answers via
Haiku; this module ranks each OFFERED anvil choice against the rule-based ideal
build path (coaches._arena_item_advisor.recompute_arena_build) so the precompute
path can be validated against real games offline before any flip. It serves
nothing live - core.anvil_shadow records its output alongside the Haiku take.

We rank by position in the ideal path (earliest = best) rather than re-scoring,
because recompute_arena_build already encodes the anti-tank / anti-heal pivots
and the curated per-champion ordering; the anvil decision is "which offered item
is furthest up my real build", which is exactly that position.

Name matching is normalized (lower-case, strip non-alphanumerics) so a vision /
display variant of an item name still binds to the canonical build-path entry
without an id-resolution dependency. The helpers are copied locally rather than
imported from core.anvil_shadow: sharing private names across modules couples
two fail-soft surfaces that must stay independently editable.
"""
from __future__ import annotations

import re
from typing import Iterable

from coaches._arena_item_advisor import recompute_arena_build

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _norm(name: object) -> str:
    return _NON_ALNUM.sub("", str(name or "").lower())


def _names_match(a: str, b: str) -> bool:
    # Equal-or-substring tolerates display variants without id resolution.
    if not a or not b:
        return False
    return a == b or a in b or b in a


def _rank_in_path(name: object, norm_path: list[str]) -> int | None:
    """1-based rank of an offered item inside the normalized ideal path, or
    None when it does not appear (offered an off-build anvil item)."""
    nn = _norm(name)
    if not nn:
        return None
    for i, np in enumerate(norm_path):
        if _names_match(nn, np):
            return i + 1
    return None


def _low_conf(anvil_choices: Iterable[str]) -> dict:
    """The fail-soft shape: every offered choice present, no rank, ideal empty.
    Used when recompute_arena_build yields nothing or raises - a no-match result
    is still a real validation signal, never an exception on the live path."""
    offered = [c for c in (anvil_choices or []) if c]
    return {
        "take": None,
        "take_rank": None,
        "n_matches": 0,
        "conf": "low",
        "ranked": [
            {"name": c, "rank": None, "in_ideal_path": False} for c in offered
        ],
        "ideal_path": [],
    }


def compute_anvil_pick(
    champion: str,
    current_items: Iterable[str],
    anvil_choices: Iterable[str],
    alive_opponents: Iterable[str],
    hp_pct: int,
    gold: int = 0,
) -> dict:
    """Rank the offered anvil choices against the ideal arena build path.

    Returns a dict: take (offered name with the earliest rank in the ideal path,
    or None), take_rank (int|None), n_matches (offered items found in the path),
    conf ("ok" when n_matches>=1 else "low"), ranked (per-offered name/rank/
    in_ideal_path), ideal_path. Fail-soft: an empty or raising recompute, or no
    offered choice, yields a low-conf dict and never raises."""
    try:
        ideal_path = recompute_arena_build(
            champion,
            current_items,
            gold,
            alive_opponents,
            hp_pct,
        )
    except Exception:  # noqa: BLE001
        return _low_conf(anvil_choices)

    offered = [c for c in (anvil_choices or []) if c]
    if not ideal_path or not offered:
        return _low_conf(anvil_choices)

    norm_path = [_norm(p) for p in ideal_path]

    ranked: list[dict] = []
    best_name = None
    best_rank: int | None = None
    n_matches = 0
    for choice in offered:
        rank = _rank_in_path(choice, norm_path)
        ranked.append({
            "name": choice,
            "rank": rank,
            "in_ideal_path": rank is not None,
        })
        if rank is not None:
            n_matches += 1
            if best_rank is None or rank < best_rank:
                best_rank = rank
                best_name = choice

    return {
        "take": best_name,
        "take_rank": best_rank,
        "n_matches": n_matches,
        "conf": "ok" if n_matches >= 1 else "low",
        "ranked": ranked,
        "ideal_path": list(ideal_path),
    }
