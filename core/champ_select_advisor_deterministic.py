# arch: deterministic champ-select pick-advisor | section=core | frozen=no
"""core/champ_select_advisor_deterministic.py - deterministic champ-select pick-advisor (NO Haiku).

PRIMARY north-star Haiku-elimination Tier-2. The pick-advisor surface
(coaches/champ_select_coach.coach_pick -> /api/champ-select-coach) is the last
champ-select Haiku call: the champ-select BRIEF was flipped off Haiku 2026-06-06
(items 273/276/280/283) but the pick-advisor has no deterministic substrate.
This composes a v1 candidate from surfaces RC already trusts - core.aram_comp_verdict
(the ARAM bench swap + comp-balance factors, itself a Haiku-elimination module)
and the archetype-tag map - so the precompute path can be shadow-validated against
the live Haiku output (core.champ_select_shadow) before any flip. Do-not-flip-blind:
this module changes NO live output.

advise_pick(state) mirrors the advice fields of coach_pick:
    {"advice": str, "swap": str, "summoners": str, "watchout": str}
Empty shape on any error - same fail-soft contract as the Haiku path so callers
need not guard. Pure import-only reuse; NO Anthropic call, NO new dependency.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("rc.core.champ_select_advisor")

_EMPTY: dict = {"advice": "", "swap": "", "summoners": "", "watchout": ""}

# Threat rank for the "watchout" call: the enemy whose PRIMARY archetype is the
# one to track at pick time. Assassin / burst-mage > sustained marksman > bruiser
# dive > tank / enchanter. Lower index = higher threat.
_THREAT_ORDER = ("assassin", "mage", "carry", "bruiser", "tank", "enchanter")

# Friendly label for the archetype name in the watchout string (RC's "carry"
# scorer is the marksman class - say "marksman" to the player).
_ARCH_LABEL = {
    "carry": "marksman", "mage": "mage", "assassin": "assassin",
    "bruiser": "bruiser", "tank": "tank", "enchanter": "enchanter",
}

# Summoner default per primary archetype. Conservative mode-agnostic v1; the
# shadow lane validates this against Haiku before any flip is considered.
_SUMMONER_BY_ARCH = {
    "carry": "Flash + Heal",
    "enchanter": "Flash + Heal",
    "mage": "Flash + Barrier",
    "assassin": "Flash + Ignite",
    "bruiser": "Flash + Ignite",
    "tank": "Flash + Ignite",
}


def _primary_archetype(champ: str) -> str:
    """First-tag archetype for a champion display name, or "" when unresolved."""
    try:
        from core.archetype_picks import _load_champion_tags, tag_to_archetype
        tags = _load_champion_tags().get(champ) or []
        if tags:
            return tag_to_archetype(tags[0])
    except Exception as exc:  # best-effort; never breaks the advisor
        logger.debug("primary_archetype(%s): %s", champ, exc)
    return ""


def _summoners(champ: str) -> str:
    return _SUMMONER_BY_ARCH.get(_primary_archetype(champ), "Flash + Heal")


def _watchout(enemies: list) -> str:
    """Name the highest-threat enemy by primary archetype. Falls back to the
    first named enemy when no tag resolves; "" when there is no enemy at all."""
    best, best_rank, best_arch = "", len(_THREAT_ORDER), ""
    for name in enemies:
        arch = _primary_archetype(name)
        if not arch:
            continue
        try:
            rank = _THREAT_ORDER.index(arch)
        except ValueError:
            continue
        if rank < best_rank:
            best, best_rank, best_arch = name, rank, arch
    if not best:
        first = next((e for e in enemies if e), "")
        return f"Watch {first}." if first else ""
    return f"Watch {best} ({_ARCH_LABEL.get(best_arch, best_arch)})."


def _enemy_lean(enemies: list) -> str:
    """Armor-vs-MR clause from the enemy damage-type distribution. Fires only
    with >= 3 resolvable enemies AND a clear mono lean; "" otherwise."""
    try:
        from core.aram_comp_verdict import compute_factors
        f = compute_factors(enemies or [])
        if f.get("n", 0) >= 3:
            ad, ap = f.get("ad_count", 0), f.get("ap_count", 0)
            if ad and not ap:
                return "enemy AD-heavy, prioritize armor"
            if ap and not ad:
                return "enemy AP-heavy, prioritize MR"
    except Exception as exc:  # best-effort
        logger.debug("enemy_lean: %s", exc)
    return ""


def _stay(my: str, lean: str) -> str:
    return f"Stay {my} - {lean}." if lean else f"Stay {my} - solid into this comp."


def _trim(s) -> str:
    return str(s or "").rstrip(". ").strip()


def _clip(s: str) -> str:
    return s[:100]


def advise_pick(state: dict) -> dict:
    """Deterministic pick advice mirroring coach_pick's advice fields. Returns
    the EMPTY shape on bad input or any error (fail-soft, never raises)."""
    if not isinstance(state, dict) or not state.get("my_champion"):
        return dict(_EMPTY)
    try:
        my = str(state["my_champion"]).strip()
        is_aram = bool(state.get("is_aram"))
        enemies = [str(c).strip() for c in (state.get("their_team") or [])
                   if c and str(c).strip()]
        out = {
            "advice": "", "swap": "",
            "summoners": _summoners(my),
            "watchout": _watchout(enemies),
        }
        lean = _enemy_lean(enemies)
        if is_aram:
            from core.aram_comp_verdict import comp_verdict
            v = comp_verdict(state)
            rec = v.get("recommendation")
            if rec == "swap" and v.get("swap_to"):
                out["swap"] = v["swap_to"]
                out["advice"] = _clip(f"Swap to {v['swap_to']} - {_trim(v.get('reason'))}")
            elif rec == "variant" and v.get("variant_to"):
                out["advice"] = _clip(f"Stay {my}, shift build - {_trim(v.get('reason'))}")
            else:
                out["advice"] = _clip(_stay(my, lean))
        else:
            out["advice"] = _clip(_stay(my, lean))
        return out
    except Exception as exc:  # fail-soft: never raise into the route
        logger.warning("advise_pick(%s): %s", state.get("my_champion"), exc)
        return dict(_EMPTY)
