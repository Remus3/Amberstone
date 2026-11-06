"""core.build_planner.champ_kit_data - per-champion kit-weight derivation (WP-B4+).

WP-C1 shipped a 6-axis-archetype kit-weight model with only ~6 hand-curated
champions; every other champion fell back to a FLAT per-archetype vector, so all
54 mages (etc.) scored identically. This module derives a genuinely PER-CHAMPION
kit-weight vector from champions.json ground truth, so the C2 scorer distinguishes
each of the 173 champions, not just each archetype.

Ground truth (read-only, NEVER the DS engine - the split-brain guard
``test_routes_state_has_no_in_process_engine_import`` in
tests/test_ds_preview_e2e_p1l21.py; we load the same DATA files DS reads):
  * data/daemon_slayer/<patch>/champions.json - per champ:
      lolmath.damage_distribution {physical, magical, trued}  (the AD/AP/true axis)
      lolmath.roles                                            (MARKSMAN/MAGE/...)
      lolmath.ratings {healing, shielding}                     (enchanter signal)
      tags                                                     (Marksman/Mage/...)
      stats.attackrange                                        (ranged vs melee)
      stats.attackspeedperlevel                                (AS reliance)
  * data/daemon_slayer/<patch>/cdragon_ability_ratios.json - per champ per spell:
      ap_pct / total_ad_pct                                    (ability scaling confirm)

The derivation is a transparent heuristic blend of these signals onto the SAME
10-axis space kit_synergy.AXES uses, tuned against the empirically-observed
signal table (the crit-marksman vs on-hit-marksman split keys on magical share -
Miss Fortune 0.05 magical = crit, Kog'Maw 0.58 magical = on-hit). Per-champ
distinctness comes from the continuous inputs (damage_distribution floats,
attackrange, attackspeedperlevel) - two carries with different magical share or
attack-range get different vectors.

Input hardening (s144 true-audit cycle 161): both JSON files are DS-extracted
third-party data, so every field is shape-checked where it is read. A NaN /
inf / bool / junk number reads as 0.0 (as a missing field always did) and is
coerced per field, so one bad value never zeroes its siblings; a non-object
section or a non-list tag set is read as absent; a shape-drifted file is a
load FAILURE (retried after the gate's backoff), never a cached success; a
champion name also resolves through a case-insensitive alphanumeric fold, so
"ezreal" resolves like "Ezreal"; current.txt is read BOM-tolerant and a
path-segment token is refused. Well-formed data gives byte-identical output.

ASCII only - use " - " for a clause break (repo hard rule).
"""
from __future__ import annotations

import json
import logging
import math
import threading
from pathlib import Path
from typing import Any, Optional

from core.failed_load_gate import FailedLoadGate

_log = logging.getLogger("rc.build_planner.champ_kit_data")

_DS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "daemon_slayer"

# Canonical axis order - MUST equal kit_synergy.AXES (a guard test pins this).
# Duplicated here so this leaf module never imports kit_synergy (no import cycle).
_AXES: tuple[str, ...] = (
    "AD", "bonusAD", "AP", "AS", "crit",
    "on-hit", "AH", "HP-scaling", "%maxHP", "true",
)

# --------------------------------------------------------------------------- #
# Data loaders - mirror ``_resolve_ds_patch`` / ``_load_items`` in
# core/build_planner/kit_synergy.py.
# --------------------------------------------------------------------------- #
_CHAMP_CACHE: Optional[dict[str, dict]] = None
_RATIO_CACHE: Optional[dict[str, dict]] = None
_LOCK = threading.Lock()
# RM-439: a failed load is NOT cached - retried after the gate's backoff and
# warned once per failure streak (core/failed_load_gate.py).
_CHAMP_GATE = FailedLoadGate()
_RATIO_GATE = FailedLoadGate()

# Case-fold lookup built lazily from (and tied to) one champion index object,
# so a rebuilt or swapped index never serves a stale fold. (index, fold) pair.
_FOLD: tuple[Optional[dict], dict[str, dict]] = (None, {})

# A patch token names ONE directory under _DS_DIR. A separator, a drive colon
# or a parent reference would point the read elsewhere, so it is refused
# (same set as core/aram_balance_context.py and core/aram_comp_verdict.py).
_PATCH_FORBIDDEN = ("/", "\\", ":", "..")


def _resolve_ds_patch() -> Optional[str]:
    """The current DS patch token, or None when unreadable, blank or refused.

    utf-8-sig: a PowerShell 5.1 ``-Encoding UTF8`` write leaves a BOM that a
    plain utf-8 read keeps inside the token, so champions.json went "missing".
    """
    try:
        txt = (_DS_DIR / "current.txt").read_text(encoding="utf-8-sig").strip()
    # UnicodeDecodeError is a ValueError, not an OSError (RM-291A).
    except (OSError, ValueError):
        return None
    if not txt or any(bad in txt for bad in _PATCH_FORBIDDEN):
        return None
    return txt


def _key_variants(name: str):
    """Champ-name variants matching core/archetype_picks resolution."""
    if not name:
        return
    yield name
    yield name.replace("'", "")
    yield name.replace(" ", "")
    yield name.replace("'", "").replace(" ", "")


def _num(value: Any) -> float:
    """A finite float from a JSON number or numeric string, else 0.0.

    0.0 is what a missing field always read as. A NaN / inf (json.loads takes
    the bare literals) or a bool is junk, not a share: ``_clamp`` keeps its
    UPPER bound when handed NaN, so NaN used to read as the maximum weight.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return 0.0
    try:
        out = float(value)
    except (ValueError, OverflowError):
        return 0.0
    return out if math.isfinite(out) else 0.0


def _obj(value: Any) -> dict:
    """``value`` when it is a dict, else an empty dict (absent section)."""
    return value if isinstance(value, dict) else {}


def _str_set(value: Any) -> frozenset[str]:
    """The str members of a JSON list, else empty.

    A bare string is NOT iterated by character, and a nested list or object
    member (unhashable) is dropped rather than raising TypeError.
    """
    if not isinstance(value, (list, tuple)):
        return frozenset()
    return frozenset(v for v in value if isinstance(v, str))


def _load_champions() -> dict[str, dict]:
    """champions.json 'data' map, indexed by id + display name + stripped variants.

    Fail-soft to {} on any read/parse error (same contract as kit_synergy). A
    file that parses but holds no champion object (a non-object top level or
    'data', or no object entry) is a FAILURE too - never cached as a success.
    Only str keys with at least one alphanumeric character are indexed.
    """
    global _CHAMP_CACHE
    with _LOCK:
        if _CHAMP_CACHE is not None:
            return _CHAMP_CACHE
        if not _CHAMP_GATE.should_attempt():
            return {}
        index: dict[str, dict] = {}
        patch = _resolve_ds_patch()
        if not patch:
            if _CHAMP_GATE.record_failure():
                _log.warning("champ_kit_data: %s unreadable - no champ data",
                             _DS_DIR / "current.txt")
            return {}
        path = _DS_DIR / patch / "champions.json"
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            if _CHAMP_GATE.record_failure():
                _log.warning("champ_kit_data: %s missing - no champ data", path)
            return {}
        except (OSError, ValueError, RecursionError) as exc:
            if _CHAMP_GATE.record_failure():
                _log.warning("champ_kit_data: champ load failed: %s", exc)
            return {}
        data = raw.get("data", raw) if isinstance(raw, dict) else None
        if isinstance(data, dict):
            for cid, entry in data.items():
                if not isinstance(entry, dict):
                    continue
                for k in (cid, entry.get("id"), entry.get("name")):
                    # _key_variants only drops apostrophes and spaces, so every
                    # variant of a key with an alphanumeric keeps one.
                    if isinstance(k, str) and _norm(k):
                        for v in _key_variants(k):
                            index.setdefault(v, entry)
        if not index:
            if _CHAMP_GATE.record_failure():
                _log.warning("champ_kit_data: %s holds no champion rows - "
                             "no champ data", path)
            return {}
        _CHAMP_GATE.record_success()
        _CHAMP_CACHE = index
        return index


def _load_ability_ratios() -> dict[str, dict]:
    """cdragon_ability_ratios.json 'champions' map, keyed by champ id. Fail-soft.

    A file whose top level is not an object, or whose 'champions' is missing
    or not an object, is a FAILURE (never a cached success); an empty
    'champions' object is a legitimate empty map and is cached.
    """
    global _RATIO_CACHE
    with _LOCK:
        if _RATIO_CACHE is not None:
            return _RATIO_CACHE
        if not _RATIO_GATE.should_attempt():
            return {}
        patch = _resolve_ds_patch()
        if not patch:
            if _RATIO_GATE.record_failure():
                _log.warning("champ_kit_data: %s unreadable - ability ratios skipped",
                             _DS_DIR / "current.txt")
            return {}
        path = _DS_DIR / patch / "cdragon_ability_ratios.json"
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            if _RATIO_GATE.record_failure():
                _log.info("champ_kit_data: %s missing - ability ratios skipped", path)
            return {}
        except (OSError, ValueError, RecursionError) as exc:
            if _RATIO_GATE.record_failure():
                _log.warning("champ_kit_data: ratio load failed: %s", exc)
            return {}
        champs = raw.get("champions") if isinstance(raw, dict) else None
        if not isinstance(champs, dict):
            if _RATIO_GATE.record_failure():
                _log.warning("champ_kit_data: %s has no 'champions' object - "
                             "ability ratios skipped", path)
            return {}
        out = {str(k): v for k, v in champs.items() if isinstance(v, dict)}
        _RATIO_GATE.record_success()
        _RATIO_CACHE = out
        return out


def invalidate_cache() -> None:
    """Drop caches so the next read re-pulls (patch refresh / tests)."""
    global _CHAMP_CACHE, _RATIO_CACHE, _FOLD
    with _LOCK:
        _CHAMP_CACHE = None
        _RATIO_CACHE = None
        _FOLD = (None, {})
        _CHAMP_GATE.reset()
        _RATIO_GATE.reset()


def _fold_index(index: dict[str, dict]) -> dict[str, dict]:
    """``_norm``-keyed view of ``index`` (first entry wins), cached per index."""
    global _FOLD
    built_for, fold = _FOLD
    if built_for is index:
        return fold
    fold = {}
    for k, entry in index.items():
        fold.setdefault(_norm(k), entry)
    _FOLD = (index, fold)
    return fold


def _resolve_champ(champ) -> dict:
    """The champions.json entry for ``champ``, or {} when unresolved.

    Exact name variants are tried first (byte-identical to the pre-fold
    lookup), then a case-insensitive alphanumeric fold, so a lower-cased or
    upper-cased name resolves like the canonical one - the coherence re-rank
    resolves the archetype case-insensitively, so a fold miss here docked a
    caster marksman's real core. A name with no alphanumeric never resolves.
    """
    name = str(champ) if champ is not None else ""
    key = _norm(name)
    if not key:
        return {}
    index = _load_champions()
    if not index:
        return {}
    for v in _key_variants(name.strip()):
        if v in index:
            return index[v]
    return _fold_index(index).get(key, {})


# Ability-AP-scaling floor separating a genuine hybrid ability-caster from a crit
# / on-hit auto-attacker that merely carries an incidental secondary Mage tag.
# Measured against the live 16.13.1 cdragon_ability_ratios (_ability_agg "ap" =
# summed top-rank AP scaling across the kit): genuine casters Ezreal 4.25 /
# Corki 2.50 / Smolder 2.55 sit well above crit/on-hit ADCs Jhin 1.60 /
# Kai'Sa 1.40 / Varus 1.25 / Miss Fortune 1.20, a clean 1.60 -> 2.50 gap; 2.0
# cuts it with margin on both sides. (Mage-archetype Marksman+Mage champs -
# Azir / Kog'Maw / Twisted Fate - are exempt from the coherence dock anyway via
# its archetype early-return, so their side of this cut is immaterial.)
_CASTER_MKS_ABIL_AP_FLOOR = 2.0


def is_caster_marksman(champ) -> bool:
    """True when ``champ`` is a genuine caster / spellblade marksman - a Marksman
    that ALSO carries the Mage secondary tag AND scales heavily off ability AP
    (Ezreal, Corki, Smolder).

    These kits genuinely charge Sheen-line spellblade procs and build mana / AH
    on an ability-cast tempo (Ezreal Essence Reaver / Trinity / Manamune), so the
    carry-coherence spellblade dock must NOT strip their real core - the coherence
    re-rank excludes them (byte-identical).

    The Marksman + Mage TAG alone is NOT enough: many crit / on-hit ADCs carry an
    incidental secondary Mage tag (Jhin, Kai'Sa, Varus, Miss Fortune, Teemo) yet
    build no spellblade / mana core, so the broad tag-only gate wrongly spared
    their Essence Reaver / Eclipse artifact from the dock (live-confirmed
    2026-07-13, docs/specs/2026-07-13-ds-build-coherence-refactor.md KNOWN GAP).
    The ability-AP-scaling floor (_ability_agg "ap" >= _CASTER_MKS_ABIL_AP_FLOOR)
    distinguishes the genuine hybrid ability-caster (heavy AP scaling on its
    spells) from a crit auto-attacker (little to none). The pure crit / on-hit
    ADCs with no Mage tag (Jinx / Caitlyn / Ashe / Twitch / Draven / Lucian) were
    already docked. Metric-derived (DDragon tags + cdragon ability ratios), NOT a
    hand-blacklist. Fail-soft to False when the champ is unresolved.
    """
    entry = _resolve_champ(champ)
    if not entry:
        return False
    tags = _str_set(entry.get("tags"))
    if not (("Marksman" in tags) and ("Mage" in tags)):
        return False
    return _ability_agg(entry).get("ap", 0.0) >= _CASTER_MKS_ABIL_AP_FLOOR


# --------------------------------------------------------------------------- #
# LEAP-07 DD1 - the AP-on-AD-marksman coherence class (the "Zeri class").
# docs/specs/leap/LEAP-07-build-coherence-calibration-r2.md, section DD1.
# --------------------------------------------------------------------------- #
# The AP-hybrid item set: heavy flat-AP items that are ON-AXIS only for a
# marksman whose kit genuinely converts ability AP into sim DPS. Lich Bane 3100
# and Liandry's Torment 6653, each with its Arena mirror id. Deliberately NOT
# extended to Dusk and Dawn 2510 (a legit on-hit hybrid - OnHit + AS + AP -
# coherent for ANY on-hit marksman; spec GHOST LIST, do not dock it).
_AP_HYBRID_ITEM_IDS: frozenset[str] = frozenset({"3100", "223100", "6653", "226653"})

# Per-champion allow-map, EMPTY at ship. A champion earns membership ONLY when a
# RED test proves the DS engine credits its ability-AP for _AP_HYBRID_ITEM_IDS
# ABOVE a pure-AD-marksman control (Caitlyn / Jinx) at a fixed target.
# MEASURED at engine 1.245.0 / patch 16.14.1 (SR level 13, target armor 100 /
# MR 50 / max HP 2000 / bonus HP 800, empty build):
#   Lich Bane 3100 delta - Zeri 21.87 vs Caitlyn 26.16 / Jinx 24.65
#   Liandry's 6653 delta - Zeri 28.81 vs Caitlyn 29.98 / Jinx 29.29
# Zeri sits BELOW both controls on both items, so the engine does NOT credit her
# Q ability-AP above a pure-AD baseline - she does NOT qualify and the map ships
# empty (byte-identical behavior; the R77/Stormrazor precedent - build the seam
# and the guard, ship no behavior flip). Pinned by
# tests/test_carry_coherence_rerank.py::test_measured_membership_rule_keeps_zeri_out.
_AP_HYBRID_MARKSMAN: frozenset[str] = frozenset()


def _norm(champ) -> str:
    """Case/format-insensitive champion key - lowercase alphanumerics only.

    Mirrors core.ds_champion_fight_length._norm so a coach-supplied display id,
    a DDragon id, or a lower-cased name all resolve identically ("Kog'Maw" ->
    "kogmaw"). Duplicated rather than imported so this leaf module keeps zero
    intra-package imports (the split-brain guard).
    """
    return "".join(ch for ch in (str(champ) if champ is not None else "").lower()
                   if ch.isalnum())


def is_ap_hybrid_marksman(champ) -> bool:
    """A carry-archetype Marksman whose kit genuinely converts AP into sim DPS
    through an ability the DS engine credits - so Lich Bane / Liandry's are
    ON-AXIS for it, not wasted stat.

    A DISTINCT class from ``is_caster_marksman``: that gate protects a
    spellblade / mana ability-caster (Ezreal, Corki, Smolder) from the coherence
    dock wholesale; this one marks a marksman for whom a specific flat-AP item
    set is coherent while the rest of the standard carry dock still applies.

    Explicit per-champion allow-map, mirroring ``_CHAMPION_FIGHT_LENGTH`` and
    ``is_caster_marksman`` - a champion earns membership ONLY when the RED test
    proves the engine credits its ability-AP for ``_AP_HYBRID_ITEM_IDS`` above a
    pure-AD-marksman baseline (see the ``_AP_HYBRID_MARKSMAN`` measurement note).
    Fail-soft False when unresolved.
    """
    return _norm(champ) in _AP_HYBRID_MARKSMAN


def _ability_agg(entry: dict) -> dict[str, float]:
    """Sum ap_pct + total_ad_pct across all spell blocks (top-rank value),
    normalized to fractions. Used only as a secondary AD/AP confirmation.

    A spell entry that is not a list of objects is skipped (a bare number used
    to raise TypeError), and a ratio that is not a finite number - NaN, inf,
    bool - adds nothing: an inf made an auto-attacker a caster marksman and a
    NaN erased every real ratio summed with it."""
    out = {"ap": 0.0, "total_ad": 0.0}
    cid = entry.get("id")
    if not cid:
        return out
    blocks = _obj(_load_ability_ratios().get(str(cid)))
    for arr in blocks.values():
        if not isinstance(arr, list):
            continue
        for b in arr:
            if not isinstance(b, dict):
                continue
            for src, key in (("ap", "ap_pct"), ("total_ad", "total_ad_pct")):
                v = b.get(key)
                if isinstance(v, list):
                    v = v[-1] if v else None
                out[src] += _num(v) / 100.0
    return out


def _clamp(x: float, lo: float = 0.0, hi: float = 1.5) -> float:
    return max(lo, min(hi, x))


# --------------------------------------------------------------------------- #
# The derivation.
# --------------------------------------------------------------------------- #
def derive_kit_weights(champ) -> Optional[dict[str, float]]:
    """Per-champion kit-weight vector over _AXES, or None when ``champ`` is blank
    or absent from champions.json (the caller then falls back to the archetype
    base). Pure - reads cached static data, no I/O after first load.
    """
    entry = _resolve_champ(champ)
    if not entry:
        return None

    # Every section is shape-checked and every number coerced on its own: a
    # non-object section reads as absent, and a junk / non-finite number reads
    # as 0.0 without zeroing its siblings (one shared try block used to).
    lm = _obj(entry.get("lolmath"))
    dd = _obj(lm.get("damage_distribution"))
    phys = _num(dd.get("physical"))
    mag = _num(dd.get("magical"))
    true_s = _num(dd.get("trued"))

    tags = _str_set(entry.get("tags"))
    roles = _str_set(lm.get("roles"))
    stats = _obj(entry.get("stats"))
    rng = _num(stats.get("attackrange"))
    as_pl = _num(stats.get("attackspeedperlevel"))
    ratings = _obj(lm.get("ratings"))
    util = max(_num(ratings.get("healing")), _num(ratings.get("shielding")))

    ranged = rng >= 300.0
    is_mks = ("Marksman" in tags) or ("MARKSMAN" in roles)
    is_mage = "Mage" in tags
    is_asn = "Assassin" in tags
    is_ftr = "Fighter" in tags
    is_tank = "Tank" in tags
    is_sup = ("Support" in tags) or ("SUPPORT" in roles)
    is_ench = is_sup and util >= 4.0 and not is_mks
    # A PRIMARY mage - many marksmen carry a secondary "Mage" tag (Miss Fortune,
    # Kog'Maw, Varus); they are NOT AH/AP mages, so the mage treatment gates on
    # "Mage tag AND not a marksman".
    is_mage_primary = is_mage and not is_mks
    # Marksman damage-type split: physical-dominant ranged = crit-marksman;
    # a meaningful magical share (on-hit magic damage) = on-hit-marksman.
    crit_mks = is_mks and ranged and mag < 0.22 and phys >= 0.55
    onhit_mks = is_mks and mag >= 0.22

    w: dict[str, float] = {}
    # AD - physical-damage reliance.
    w["AD"] = _clamp(phys * 1.25)
    # AP - magical reliance; a marksman's magic is auto/on-hit (not AP scaling),
    # so discount it heavily for any marksman. EXCEPT an AP-hybrid-marksman
    # class member (LEAP-07 DD1): its magic IS ability-AP the engine credits, so
    # it is scored on its own kit weights, NOT the generic marksman AP discount.
    # The allow-map is empty at ship, so this is byte-identical today.
    ap_discounted = is_mks and not is_ap_hybrid_marksman(champ)
    w["AP"] = _clamp(mag * (0.3 if ap_discounted else 1.35))
    # bonusAD - archetype-shaped (the cdragon ratios carry no bonus_ad split).
    # Marksman identity wins over a SECONDARY Assassin/Fighter tag: a crit / on-
    # hit marksman (Twitch/Quinn/Akshan/Lucian carry a dual Assassin tag) is a
    # ranged auto-attacker, not a bonusAD-lethality assassin, so it takes the
    # marksman bonusAD weight - else the secondary tag inflates it to 0.8 and the
    # kit-synergy fit over-credits lethality stat-sticks (Essence Reaver/Eclipse).
    w["bonusAD"] = 0.3 if is_mks else (0.8 if is_asn else (0.5 if is_ftr else 0.1))
    # AS - marksmen value attack speed; floor + attackspeedperlevel bonus.
    if is_mks:
        w["AS"] = _clamp(0.6 + as_pl / 7.5)
    else:
        w["AS"] = _clamp(0.2 + as_pl / 18.0)
    # crit - crit-marksmen only; other marksmen a little, everyone else none.
    w["crit"] = 1.1 if crit_mks else (0.2 if is_mks else 0.0)
    # on-hit - on-hit-marksmen highest; marksmen + fighters moderate.
    w["on-hit"] = 1.0 if onhit_mks else (0.6 if is_mks else (0.4 if is_ftr else 0.15))
    # AH - ability reliance. Marksman identity precedes a SECONDARY Assassin /
    # Fighter tag (see bonusAD above): a marksman auto-attacker does not stack
    # ability haste like an assassin, so a dual-tagged crit marksman
    # (Twitch/Quinn/Akshan/Lucian) takes the low marksman AH weight - the 0.6
    # assassin value mis-derived it and let ability-haste stat-sticks (Essence
    # Reaver 15 AH) dodge the kit-synergy AH-waste penalty + spellblade-user flag.
    if is_ench or is_mage_primary:
        w["AH"] = 0.9
    elif is_mks:
        w["AH"] = 0.05 if crit_mks else 0.2
    elif is_asn or is_ftr:
        w["AH"] = 0.6
    else:
        w["AH"] = 0.4
    # HP-scaling - frontline durability as offense (tanks/fighters).
    w["HP-scaling"] = 1.1 if is_tank else (0.4 if is_ftr else (0.15 if is_sup else 0.0))
    # %maxHP - anti-tank / sustain mix.
    w["%maxHP"] = 0.7 if is_tank else (0.55 if is_ftr else (0.35 if is_mks else 0.25))
    # true - small, scales with the realized true-damage share.
    w["true"] = _clamp(0.2 + true_s * 2.0, 0.0, 0.9)

    return {a: float(w.get(a, 0.0)) for a in _AXES}
