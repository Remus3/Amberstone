# arch: closed-axis comp coverage + shared-vulnerability facts | section=core | frozen=no
"""Closed-axis team-comp coverage and shared-vulnerability scorer (Y-09 / RM-533).

Provenance: method from external reference S (behaviour only, clean-room).

WHAT
    Each champion carries two fixed sets over CLOSED axis lists: what it COVERS
    (COVER_AXES) and what it is WEAK to (VULN_AXES). For a team:
      * coverage_pct = |union of cover sets| / |cover axes defined for the mode|
      * shared_vulns = the vuln axes that hit 2+ members, with those members.
    Both teams are scored; the enemy run also carries the legacy
    composition_advisor.enemy_damage_profile (AD/AP split) it extends.

COMP FACTS, NOT A PREDICTION
    Nothing here estimates who wins. Every bit is a kit / stat fact read from
    data RC already holds, with the thresholds pinned below. There is no
    stochastic outcome to calibrate against, so the tests ARE the validation.
    No badge / "good coverage" threshold ships: one would have to be calibrated
    per mode and team size from stored comps, and core/match_db.py stores only
    the operator's own champion per row (no 10-player comp), so that
    calibration is not cheap today (left as a residual).

DATA SOURCES (read-only; no engine math change)
    core/aram_comp_verdict.py helpers (imported, never edited):
      _lookup (:117), _stat_range (:121), _damage_lean (:129),
      _is_frontline (:145), RANGED_MIN_RANGE (:48), _resolve_patch (:84),
      _DS_DATA_DIR (:43); curated _ENGAGE (:54) / _SUSTAIN (:61) are a
      FALLBACK only, used when a champion has no DS / ability data at all.
    agents/daemon_slayer (public compute_* functions, data-only modules):
      cc_output.compute_cc_output (:684) + _CC_KIND_WEIGHT (:56)
      mobility.compute_mobility (:651) + _FLASH_UNITS (:71)
      threatrange.compute_threatrange (:1139) + _THREATRANGE_BAND_WEIGHT (:69)
      waveclear.compute_waveclear (:783) + _WAVECLEAR_KIND_WEIGHT (:66)
      sustain.compute_sustain (:343)
      antitank.compute_antitank (:730)
    data/daemon_slayer/<patch>/champion_abilities.json ['data'][id][slot][form]:
      damage_type (TRUE), damage_blocks[].attribute / attribute_kind (heal),
      is_aoe, effects_descriptions (Grievous Wounds wording).

FAIL-SOFT
    An unknown / junk name ('' , '__class__', None, ints) is skipped and listed
    in ``unresolved``. Every public entry point swallows exceptions;
    coverage_from_team_context returns None on any failure.
"""
from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from typing import Any, Optional

from core.aram_comp_verdict import (
    _DS_DATA_DIR,
    _ENGAGE,
    _SUSTAIN,
    RANGED_MIN_RANGE,
    _damage_lean,
    _is_frontline,
    _lookup,
    _norm,
    _resolve_patch,
    _stat_range,
)

logger = logging.getLogger("rc.core.comp_coverage")

# -- Closed axis lists (order is the canonical output order) ------------------

COVER_AXES: tuple[str, ...] = (
    "ad", "ap", "true", "hard_cc", "aoe_cc", "engage", "disengage",
    "frontline", "waveclear", "poke", "sustain", "anti_heal", "tank_shred",
)
VULN_AXES: tuple[str, ...] = (
    "weak_to_poke", "weak_to_dive", "weak_to_cc_chain", "weak_to_burst",
    "weak_to_grievous", "weak_to_kite",
)

# Axes NOT defined for a mode key (removed from the denominator). Arena has no
# minion waves, so waveclear is undefined there. TFT has no champion comp in
# this sense: every axis is undefined and the scorer returns None.
_UNDEFINED_COVER_BY_MODE: dict[str, frozenset[str]] = {
    "arena": frozenset({"waveclear"}),
    "tft": frozenset(COVER_AXES),
}

# -- Pinned thresholds --------------------------------------------------------
# Each threshold is anchored on a tier the DS module itself defines (read at
# import, never copied), so a DS re-tier moves these with it.


def _ds():
    """Deferred DS imports (keeps core import light; fail-soft to None)."""
    from agents.daemon_slayer import (  # noqa: PLC0415
        antitank,
        cc_output,
        mobility,
        sustain,
        threatrange,
        waveclear,
    )
    return cc_output, mobility, threatrange, waveclear, sustain, antitank


def _thresholds() -> dict:
    cc_output, mobility, threatrange, waveclear, _s, _a = _ds()
    kw = cc_output._CC_KIND_WEIGHT
    return {
        # hard_cc: an unconditional CC of the hard-disable tier (stun, knock-up,
        # charm, suppression ...): the top weight in cc_output's own table.
        "hard_cc_w": max(kw.values()),
        # aoe_cc: an unconditional CC at or above the action-restricting tier
        # (root / silence weight) delivered by an is_aoe ability.
        "aoe_cc_w": kw["ROOT"],
        # mobility floor: one Flash of unconditional self-repositioning
        # (mobility.py defines 1.0 unit == _FLASH_UNITS of displacement).
        "mobile_units": 1.0,
        # poke: an unconditional non-CC threat mechanism at LONG reach or more.
        "poke_band_w": threatrange._THREATRANGE_BAND_WEIGHT["LONG"],
        # weak_to_poke: no unconditional threat mechanism at MEDIUM reach or more.
        "reach_band_w": threatrange._THREATRANGE_BAND_WEIGHT["MEDIUM"],
        # waveclear: an unconditional AoE clear mechanism (AOE_DOT tier or above).
        "wave_kind_w": waveclear._WAVECLEAR_KIND_WEIGHT["AOE_DOT"],
    }


# weak_to_burst: DDragon info.defense (0-10 rating) at or below this, and not
# frontline. Measured on 16.18.1 champions.json: 0-3 holds 58 of 173 champions
# (the bottom third of the defense rating distribution).
BURST_DEFENSE_MAX = 3

_DISPLACE_KINDS = frozenset({"DASH", "LEAP", "BLINK"})
_DISENGAGE_CC_KINDS = frozenset({"KNOCKBACK", "POLYMORPH"})
# "inflicts / applies ... Grievous Wounds" in an ability's effect text. The
# notes field is excluded on purpose: it mentions Grievous Wounds only to say a
# heal is NOT affected by it (measured on 16.18.1: Gnar P, Nasus R, Pyke P,
# Renekton Q/R).
_GW_RE = re.compile(r"(inflict|appl)\w*\b[^.]{0,40}Grievous Wounds")


# -- Ability data (champion_abilities.json) -----------------------------------

@lru_cache(maxsize=1)
def _abilities() -> dict:
    patch = _resolve_patch()
    if not patch:
        return {}
    try:
        path = _DS_DATA_DIR / patch / "champion_abilities.json"
        data = json.loads(path.read_text(encoding="utf-8")).get("data") or {}
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, AttributeError):
        return {}


def _forms(champ_id: str):
    spells = _abilities().get(champ_id)
    if not isinstance(spells, dict):
        return
    for slot, forms in spells.items():
        if not isinstance(forms, list):
            continue
        for f in forms:
            if isinstance(f, dict):
                yield slot, f


def _ability_facts(champ_id: str) -> dict:
    true_dmg = heal = anti_heal = False
    aoe_slots: set[str] = set()
    seen = False
    for slot, f in _forms(champ_id):
        seen = True
        if f.get("damage_type") == "TRUE":
            true_dmg = True
        if f.get("is_aoe") is True:
            aoe_slots.add(slot)
        for b in f.get("damage_blocks") or []:
            if not isinstance(b, dict):
                continue
            if "true damage" in str(b.get("attribute") or "").lower():
                true_dmg = True
            if b.get("attribute_kind") == "heal":
                heal = True
        text = " ".join(str(x) for x in (f.get("effects_descriptions") or []))
        if _GW_RE.search(text):
            anti_heal = True
    return {"seen": seen, "true": true_dmg, "heal": heal,
            "anti_heal": anti_heal, "aoe_slots": aoe_slots}


# -- Per-champion profile ------------------------------------------------------

# champion id -> (cover, vuln). Kit facts are patch-static within a process.
_PROFILE_CACHE: dict[str, tuple[frozenset, frozenset]] = {}


def _profile_for(champ: dict) -> tuple[frozenset, frozenset]:
    cid = str(champ.get("id") or "")
    hit = _PROFILE_CACHE.get(cid)
    if hit is None:
        hit = _derive(champ)
        _PROFILE_CACHE[cid] = hit
    return hit


def _derive(champ: dict) -> tuple[frozenset, frozenset]:
    cc_output, mobility, threatrange, waveclear, sustain, antitank = _ds()
    t = _thresholds()
    cid = str(champ.get("id") or "")
    name = str(champ.get("name") or "")
    ab = _ability_facts(cid)

    ccr = cc_output.compute_cc_output(cid)
    mob = mobility.compute_mobility(cid)
    thr = threatrange.compute_threatrange(cid)
    wav = waveclear.compute_waveclear(cid)
    sus = sustain.compute_sustain(cid)
    atk = antitank.compute_antitank(cid)
    has_ds = bool(ccr.spells or mob.spells or thr.sources or wav.sources)

    cc_unc = [s for s in ccr.spells if not s.conditional]
    mob_unc = [s for s in mob.spells if not s.conditional]
    displace_slots = {s.spell_key for s in mob_unc if s.kind in _DISPLACE_KINDS}
    ranged = _stat_range(champ) >= RANGED_MIN_RANGE
    frontline = _is_frontline(champ)
    lean = _damage_lean(champ)

    cover: set[str] = set()
    if lean in ("ad", "hybrid"):
        cover.add("ad")
    if lean in ("ap", "hybrid"):
        cover.add("ap")
    if ab["true"]:
        cover.add("true")
    if any(s.kind_weight >= t["hard_cc_w"] for s in cc_unc):
        cover.add("hard_cc")
    if any(s.kind_weight >= t["aoe_cc_w"] and s.spell_key in ab["aoe_slots"]
           for s in cc_unc):
        cover.add("aoe_cc")
    # engage = a gap-closer (any dash/leap/blink row, gated ones included:
    # target-anchored dashes are gated on "needs a target" by design) plus an
    # unconditional hard CC, on a melee or frontline body. Measured on 16.18.1:
    # 45 champions, recalling 20 of the 27 curated _ENGAGE names.
    gap_closer = any(s.kind in _DISPLACE_KINDS for s in mob.spells)
    if gap_closer and "hard_cc" in cover and (frontline or not ranged):
        cover.add("engage")
    elif not has_ds and name in _ENGAGE:
        cover.add("engage")  # curated fallback: no DS rows at all
    if any(s.cc_kind in _DISENGAGE_CC_KINDS for s in cc_unc) or (
            ranged and displace_slots):
        cover.add("disengage")
    if frontline:
        cover.add("frontline")
    if any(s.kind_weight >= t["wave_kind_w"] for s in wav.sources
           if not s.conditional):
        cover.add("waveclear")
    if any(s.band_weight >= t["poke_band_w"] and s.kind != "CC"
           for s in thr.sources if not s.conditional):
        cover.add("poke")
    if sus.sustain_score > 0.0 or ab["heal"]:
        cover.add("sustain")
    elif not ab["seen"] and not sus.spells and name in _SUSTAIN:
        cover.add("sustain")  # curated fallback: no ability / DS sustain data
    if ab["anti_heal"]:
        cover.add("anti_heal")
    if any(not s.conditional and s.value > 0.0 for s in atk.sources):
        cover.add("tank_shred")

    mobile = mob.mobility_score >= t["mobile_units"]
    reach = any(s.band_weight >= t["reach_band_w"]
                for s in thr.sources if not s.conditional)
    try:
        defense = float((champ.get("info") or {}).get("defense") or 0.0)
    except (TypeError, ValueError):
        defense = 0.0

    vuln: set[str] = set()
    if has_ds and not reach and "sustain" not in cover:
        vuln.add("weak_to_poke")
    if ranged and not frontline and not mobile:
        vuln.add("weak_to_dive")
    # cc_chain / kite key on ANY displacement row (gated target-anchored dashes
    # included - Yasuo E, Zed R, Leona E): a champion with none cannot leave a
    # lockdown chain or close on a kiter.
    if not frontline and not gap_closer:
        vuln.add("weak_to_cc_chain")
    if not frontline and defense <= BURST_DEFENSE_MAX:
        vuln.add("weak_to_burst")
    if "sustain" in cover:
        vuln.add("weak_to_grievous")
    if not ranged and not gap_closer:
        vuln.add("weak_to_kite")
    return frozenset(cover), frozenset(vuln)


def _resolve(name: Any) -> Optional[dict]:
    if not isinstance(name, str) or not _norm(name):
        return None
    champ = _lookup(name)
    return champ if isinstance(champ, dict) and champ.get("id") else None


def champion_profile(name: Any) -> Optional[dict]:
    """{'id', 'cover': [...], 'vuln': [...]} in canonical axis order, or None."""
    try:
        champ = _resolve(name)
        if champ is None:
            return None
        cover, vuln = _profile_for(champ)
        return {
            "id": champ["id"],
            "cover": [a for a in COVER_AXES if a in cover],
            "vuln": [a for a in VULN_AXES if a in vuln],
        }
    except Exception:  # noqa: BLE001 - fail-soft
        logger.debug("champion_profile failed for %r", name, exc_info=True)
        return None


# -- Team scoring --------------------------------------------------------------

def cover_axes_for_mode(mode_key: Any) -> tuple[str, ...]:
    """Cover axes DEFINED for a mode key (the coverage denominator)."""
    undefined = _UNDEFINED_COVER_BY_MODE.get(str(mode_key or "").lower(), frozenset())
    return tuple(a for a in COVER_AXES if a not in undefined)


def compute_team_coverage(team: Any, mode_key: Any = "sr") -> dict:
    """Coverage facts for one team of champion names.

    Returns {n, coverage_pct, covered[], missing[], shared_vulns[{axis,
    members[]}], vulns[{axis, members[]}], unresolved[]}. ``coverage_pct`` is
    None when nothing resolved (unknown is not zero). Members are sorted, so
    the result does not depend on pick order.
    """
    axes = cover_axes_for_mode(mode_key)
    names = team if isinstance(team, (list, tuple)) else []
    covered: set[str] = set()
    weak: dict[str, set[str]] = {a: set() for a in VULN_AXES}
    unresolved: list[str] = []
    n = 0
    seen_ids: set[str] = set()
    for raw in names:
        prof = champion_profile(raw)
        if prof is None:
            if isinstance(raw, str) and raw:
                unresolved.append(raw)
            continue
        if prof["id"] in seen_ids:
            continue
        seen_ids.add(prof["id"])
        n += 1
        covered.update(a for a in prof["cover"] if a in axes)
        for a in prof["vuln"]:
            weak[a].add(raw)
    vulns = [{"axis": a, "members": sorted(weak[a])} for a in VULN_AXES if weak[a]]
    return {
        "n": n,
        "coverage_pct": (round(100.0 * len(covered) / len(axes), 1)
                         if n and axes else None),
        "covered": [a for a in axes if a in covered],
        "missing": [a for a in axes if a not in covered],
        "shared_vulns": [v for v in vulns if len(v["members"]) >= 2],
        "vulns": vulns,
        "unresolved": sorted(unresolved),
    }


def compute_enemy_coverage(team: Any, mode_key: Any = "sr") -> dict:
    """compute_team_coverage plus the legacy AD/AP enemy_damage_profile."""
    res = compute_team_coverage(team, mode_key)
    profile = None
    try:
        from composition_advisor import enemy_damage_profile  # noqa: PLC0415
        names = [x for x in (team if isinstance(team, (list, tuple)) else [])
                 if isinstance(x, str) and x]
        profile = enemy_damage_profile(names) if names else None
    except Exception:  # noqa: BLE001 - fail-soft
        profile = None
    res["damage_profile"] = profile
    return res


def compute_coverage(ours: Any, enemy: Any, mode_key: Any = "sr") -> Optional[dict]:
    """Both teams. None when the mode defines no cover axes (TFT)."""
    axes = cover_axes_for_mode(mode_key)
    if not axes:
        return None
    return {
        "mode_key": str(mode_key or "sr").lower(),
        "axes": {"cover": list(axes), "vuln": list(VULN_AXES)},
        "ours": compute_team_coverage(ours, mode_key),
        "enemy": compute_enemy_coverage(enemy, mode_key),
    }


def _locked(entries: Any) -> list[str]:
    if not isinstance(entries, list):
        return []
    out = []
    for e in entries:
        if isinstance(e, dict):
            name = e.get("locked_champion")
            if isinstance(name, str) and name:
                out.append(name)
    return out


def coverage_from_team_context(tc: Any) -> Optional[dict]:
    """Coverage over a coach.team_context payload; None on any failure."""
    try:
        if not isinstance(tc, dict):
            return None
        from core.queue_modes import mode_key_from_queue_id  # noqa: PLC0415
        mode_key = mode_key_from_queue_id(tc.get("queue_id")) or "sr"
        return compute_coverage(_locked(tc.get("allies")),
                                _locked(tc.get("enemies")), mode_key)
    except Exception:  # noqa: BLE001 - fail-soft, never raises into state build
        logger.debug("coverage_from_team_context failed", exc_info=True)
        return None


__all__ = [
    "BURST_DEFENSE_MAX",
    "COVER_AXES",
    "VULN_AXES",
    "champion_profile",
    "compute_coverage",
    "compute_enemy_coverage",
    "compute_team_coverage",
    "cover_axes_for_mode",
    "coverage_from_team_context",
]
