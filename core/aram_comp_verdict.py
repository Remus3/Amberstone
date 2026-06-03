# arch: deterministic ARAM comp-balance verdict | section=core | frozen=no
"""Deterministic ARAM team-comp swap/variant/stay verdict (Haiku-elimination).

WHY
    coaches/aram_team_analyzer.analyze() otherwise pays a Claude Haiku call to
    answer the pre-game bench question: swap my pick, change my variant, or
    stay. The Haiku system prompt already spells out a fully DETERMINISTIC
    rubric (range mix -> damage type -> frontline -> engage -> sustain). This
    module computes that rubric from champions.json FACTS and applies the same
    ordered decision rule with no LLM call.

CORRECT-BY-CONSTRUCTION (not a prediction)
    Unlike the matchup engine - which tried to PREDICT a stochastic game
    outcome and validated as a coin-flip - this engine reports comp-balance
    FACTS (how many ranged champs, is the damage mono-type, is there a
    frontline) and a transparent fix rule over them. There is no stochastic
    outcome to be a coin-flip against, so the tests ARE the validation.

DATA (all already present, Meraki/DDragon)
    data/daemon_slayer/<patch>/champions.json ['data']:
      * stats.attackrange  -> the range-mix factor (>= 500 = ranged).
      * info.attack / info.magic (DDragon's own 0-10 ratings) -> AD/AP lean.
      * tags -> frontline (Tank, or melee Fighter).
    The engage + sustain factors use compact curated sets (champ-intrinsic,
    patch-stable) since "starts the fight" / "extends the fight" are not a
    single clean field; they only matter AFTER the data-driven top-3 factors.

FAIL-SOFT
    Every path swallows exceptions and degrades to a STAY verdict; it never
    raises. A team with < 3 resolvable champs returns ok=False so the caller
    may fall back to its Haiku path for the degenerate case.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("rc.core.aram_comp_verdict")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DS_DATA_DIR = _PROJECT_ROOT / "data" / "daemon_slayer"

# attackrange >= this is "ranged" for the range-mix factor. 500 is the standard
# ranged-carry threshold; the 8 mid-range casters (Karthus/Vladimir/Thresh/...)
# at ~425-450 have melee autos and are counted as melee here (conservative).
RANGED_MIN_RANGE = 500
# Rubric factor 1: an ARAM comp wants at least this many ranged champs.
MIN_RANGED = 2

# Curated hard-engage set (rubric factor 4 - "someone has to start fights").
# Champ-intrinsic and patch-stable; matched by normalised display name.
_ENGAGE = {
    "Malphite", "Leona", "Amumu", "Sejuani", "Nautilus", "Rell", "Ornn",
    "Hecarim", "Zac", "Vi", "Jarvan IV", "Gragas", "Alistar", "Maokai",
    "Rakan", "Pantheon", "Galio", "Wukong", "Sett", "Nunu & Willump",
    "Diana", "Shen", "Volibear", "Skarner", "Kennen", "Ashe", "Nidalee",
}
# Curated sustain set (rubric factor 5 - healing/shielding extends fights).
_SUSTAIN = {
    "Soraka", "Sona", "Yuumi", "Nami", "Janna", "Taric", "Lulu", "Karma",
    "Seraphine", "Senna", "Vladimir", "Swain", "Dr. Mundo", "Warwick",
    "Aatrox", "Sylas", "Fiddlesticks", "Renata Glasc", "Ivern",
}

# Keyword sets for detecting that a build VARIANT shifts a champ toward a
# damage-type deficit (rubric: prefer a zero-risk variant over a swap).
_AP_VARIANT_KW = ("ap", "magic", "mage", "burst", "ability power")
_AD_VARIANT_KW = ("ad", "on-hit", "on hit", "onhit", "crit", "lethality",
                   "bruiser", "attack damage")
_SUSTAIN_VARIANT_KW = ("sustain", "lifesteal", "life steal", "heal", "drain",
                       "omnivamp", "vamp", "bruiser")

_champ_index: dict[str, dict] = {}
_index_loaded = False


def _norm(name: object) -> str:
    """Lower-case, alnum-only normalisation for champ-name matching."""
    return "".join(ch for ch in str(name).lower() if ch.isalnum())


def _resolve_patch() -> Optional[str]:
    try:
        return _DS_DATA_DIR.joinpath("current.txt").read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def _load_index() -> dict[str, dict]:
    """norm(name) -> champion dict. Memoised; {} fail-soft.

    Indexes by the DISPLAY name field (c['name']) not the data key, because the
    caller passes display names ("Lee Sin", "Dr. Mundo"), while the JSON key is
    the DDragon id ("LeeSin", "DrMundo").
    """
    global _index_loaded
    if _index_loaded:
        return _champ_index
    _index_loaded = True
    patch = _resolve_patch()
    if not patch:
        return _champ_index
    path = _DS_DATA_DIR / patch / "champions.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8")).get("data") or {}
    except (OSError, ValueError):
        return _champ_index
    for champ in data.values():
        if isinstance(champ, dict) and champ.get("name"):
            _champ_index[_norm(champ["name"])] = champ
    return _champ_index


def _lookup(name: object) -> Optional[dict]:
    return _load_index().get(_norm(name)) if name else None


def _stat_range(champ: dict) -> float:
    stats = champ.get("stats") if isinstance(champ, dict) else None
    try:
        return float((stats or {}).get("attackrange") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _damage_lean(champ: dict) -> str:
    """'ad' | 'ap' | 'hybrid' from DDragon's info.attack vs info.magic."""
    info = champ.get("info") if isinstance(champ, dict) else None
    info = info or {}
    try:
        a = float(info.get("attack") or 0.0)
        m = float(info.get("magic") or 0.0)
    except (TypeError, ValueError):
        return "hybrid"
    if a > m:
        return "ad"
    if m > a:
        return "ap"
    return "hybrid"


def _is_frontline(champ: dict) -> bool:
    tags = champ.get("tags") if isinstance(champ, dict) else None
    tags = tags or []
    if "Tank" in tags:
        return True
    return "Fighter" in tags and _stat_range(champ) < RANGED_MIN_RANGE


def compute_factors(team: list) -> dict:
    """Comp-balance facts over a list of champion display names.

    Unknown names are skipped (not counted), so a partially-resolved team still
    yields honest counts over what resolved.
    """
    champs = [c for c in (_lookup(n) for n in (team or [])) if c]
    leans = [_damage_lean(c) for c in champs]
    ad = sum(1 for l in leans if l == "ad")
    ap = sum(1 for l in leans if l == "ap")
    hybrid = sum(1 for l in leans if l == "hybrid")
    ranged = sum(1 for c in champs if _stat_range(c) >= RANGED_MIN_RANGE)
    names_norm = {_norm(n) for n in (team or []) if n}
    return {
        "n": len(champs),
        "ranged_count": ranged,
        "melee_count": len(champs) - ranged,
        "ad_count": ad,
        "ap_count": ap,
        "hybrid_count": hybrid,
        "frontline_count": sum(1 for c in champs if _is_frontline(c)),
        "engage_count": sum(1 for e in _ENGAGE if _norm(e) in names_norm),
        "sustain_count": sum(1 for s in _SUSTAIN if _norm(s) in names_norm),
    }


def _damage_deficit(f: dict) -> Optional[str]:
    """'ap' or 'ad' when the comp lacks a PRIMARY source of that damage type,
    else None.

    Presence keys on the primary-lean count, NOT hybrids: a 7/7 hybrid (Jax)
    gives no reliable magic damage, so an all-AD+hybrid comp still lets the
    enemy stack armor - that is the mono-AD gap the rubric warns about. An
    all-hybrid comp (both counts 0) reads as mixed-enough (no deficit)."""
    ap_present = f["ap_count"] > 0
    ad_present = f["ad_count"] > 0
    if ap_present == ad_present:  # both present, or both absent (all hybrid)
        return None
    return "ap" if not ap_present else "ad"


def _ordered_gaps(f: dict) -> list:
    """Unmet rubric factors in priority order: (gap_name, detail)."""
    gaps = []
    if f["ranged_count"] < MIN_RANGED and f["melee_count"] > 0:
        gaps.append(("range", None))
    deficit = _damage_deficit(f)
    if deficit:
        gaps.append(("damage", deficit))
    if f["frontline_count"] == 0:
        gaps.append(("frontline", None))
    if f["engage_count"] == 0:
        gaps.append(("engage", None))
    if f["sustain_count"] == 0:
        gaps.append(("sustain", None))
    return gaps


def _gap_set(gaps: list) -> set:
    return {g for g, _ in gaps}


def _bench_addresses(champ_name: str, gap: str, detail, f: dict) -> bool:
    c = _lookup(champ_name)
    if not c:
        return False
    if gap == "range":
        return _stat_range(c) >= RANGED_MIN_RANGE
    if gap == "damage":
        # Strict: only a PRIMARY-lean champ of the deficit type fixes a mono
        # comp (consistent with _damage_deficit ignoring hybrids for presence).
        return _damage_lean(c) == detail
    if gap == "frontline":
        return _is_frontline(c)
    if gap == "engage":
        return _norm(champ_name) in {_norm(e) for e in _ENGAGE}
    if gap == "sustain":
        return _norm(champ_name) in {_norm(s) for s in _SUSTAIN}
    return False


def _best_bench(bench: list, gap: str, detail, f: dict, gaps: list) -> Optional[str]:
    """Pick the bench champ fixing `gap` that ALSO covers the most other gaps."""
    others = [(g, d) for g, d in gaps if g != gap]
    best, best_score = None, -1
    for name in bench:
        if not _bench_addresses(name, gap, detail, f):
            continue
        score = 1 + sum(1 for g, d in others if _bench_addresses(name, g, d, f))
        if score > best_score:
            best, best_score = name, score
    return best


def _variant_addresses(variant: dict, keywords: tuple) -> bool:
    text = " ".join(str(variant.get(k) or "") for k in ("key", "label", "summary")).lower()
    return any(kw in text for kw in keywords)


def _find_variant(variants: list, current: str, keywords: tuple) -> Optional[dict]:
    cur = _norm(current)
    for v in variants:
        if _norm(v.get("key")) == cur:
            continue  # can't "switch" to the variant already active
        if _variant_addresses(v, keywords):
            return v
    return None


def _result(ok, rec, swap_to, variant_to, reason, conf, f):
    return {
        "ok": ok, "recommendation": rec, "swap_to": swap_to or "",
        "variant_to": variant_to or "", "reason": reason,
        "confidence": conf, "factors": f,
    }


def _stay_unknown():
    return _result(False, "stay", "", "", "(insufficient team data)", "low", {})


def comp_verdict(state: dict) -> dict:
    """Deterministic swap/variant/stay verdict. analyze()-shape output.

    Returns ok=True with a verdict when my_team has >= 3 resolvable champs;
    ok=False (caller may fall back) when team data is too thin to judge.
    """
    try:
        if not isinstance(state, dict):
            return _stay_unknown()
        team = [str(c).strip() for c in (state.get("my_team") or []) if c and str(c).strip()]
        if len(team) < 3:
            return _stay_unknown()
        my_champ = str(state.get("my_champion") or "").strip()
        bench = [str(c).strip() for c in (state.get("bench") or []) if c and str(c).strip()]
        variants = [v for v in (state.get("variants") or [])
                    if isinstance(v, dict) and v.get("key")]
        current_variant = str(state.get("current_variant") or "").strip()

        f = compute_factors(team)
        gaps = _ordered_gaps(f)
        if not gaps:
            reason = (f"Comp is balanced ({f['ranged_count']} ranged, mixed "
                      f"damage, frontline present) - stay.")
            return _result(True, "stay", "", "", reason, "high", f)

        for gap, detail in gaps:
            # Build-addressable gaps (damage / sustain): prefer a variant.
            if gap == "damage":
                kw = _AP_VARIANT_KW if detail == "ap" else _AD_VARIANT_KW
                v = _find_variant(variants, current_variant, kw)
                if v:
                    reason = (f"All-{detail.upper()} comp - the {v.get('label') or v['key']} "
                              f"variant adds {'magic' if detail == 'ap' else 'physical'} damage.")
                    return _result(True, "variant", "", v["key"], reason, "medium", f)
            if gap == "sustain":
                v = _find_variant(variants, current_variant, _SUSTAIN_VARIANT_KW)
                if v:
                    reason = (f"Comp lacks sustain - the {v.get('label') or v['key']} "
                              f"variant adds healing/lifesteal.")
                    return _result(True, "variant", "", v["key"], reason, "medium", f)

            pick = _best_bench(bench, gap, detail, f, gaps)
            if pick:
                reason = _swap_reason(gap, detail, pick, f)
                conf = "high" if gap in ("range", "frontline") else "medium"
                return _result(True, "swap", pick, "", reason, conf, f)

        top = gaps[0][0]
        reason = f"{_gap_phrase(top)}, but no bench champ or variant fixes it - stay."
        return _result(True, "stay", "", "", reason, "low", f)
    except Exception as exc:  # never raise into the coach path
        logger.debug("comp_verdict failed: %s", exc)
        return _stay_unknown()


def _swap_reason(gap: str, detail, pick: str, f: dict) -> str:
    if gap == "range":
        return (f"Only {f['ranged_count']}/{f['n']} ranged - swap to {pick} "
                f"for poke and disengage range.")
    if gap == "damage":
        return f"All-{str(detail).upper()} comp - swap to {pick} to mix the damage type."
    if gap == "frontline":
        return f"No frontline - swap to {pick} to soak and engage."
    if gap == "engage":
        return f"No hard engage - swap to {pick} to start fights."
    if gap == "sustain":
        return f"No sustain - swap to {pick} to extend fights."
    return f"Swap to {pick}."


def _gap_phrase(gap: str) -> str:
    return {
        "range": "Comp is too melee-heavy",
        "damage": "Comp is mono damage-type",
        "frontline": "Comp has no frontline",
        "engage": "Comp has no hard engage",
        "sustain": "Comp has no sustain",
    }.get(gap, "Comp has a gap")
