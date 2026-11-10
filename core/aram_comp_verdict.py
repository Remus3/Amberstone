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
    raises. A team with < 3 RESOLVABLE champs (not merely < 3 names) returns
    ok=False so the caller may fall back to its Haiku path for the degenerate
    case.

TRUST BOUNDARY (lane 8 s144 cycle 117)
    comp_verdict's ``state`` is the POST /api/aram-comp-verdict body verbatim
    (dashboard/routes_coach.py), so every list is read only when it is a real
    list / tuple, entries only when they are strings no longer than
    _MAX_NAME, and the team / bench / variant lists are capped. champions.json
    and current.txt are read fail-soft: a junk shape, a BOM, a path-segment
    patch token or a transient read failure never raises, and a failed load is
    NOT cached (core/failed_load_gate.py backoff, warned once per streak).
"""
from __future__ import annotations

import json
import logging
import math
import threading
from pathlib import Path
from typing import Optional

from core.failed_load_gate import FailedLoadGate

logger = logging.getLogger("rc.core.aram_comp_verdict")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DS_DATA_DIR = _PROJECT_ROOT / "data" / "daemon_slayer"

# A current.txt token holding any of these would leave the DS data dir.
_PATCH_FORBIDDEN = ("/", "\\", ":", "..")

# Request-body bounds. An ARAM team is 5 and the bench at most 10; the caps
# leave room for that and stop a hostile body from buying unbounded lookups
# (the bench search re-scores a trial team per candidate). The longest
# champion display name is 14 characters ("Nunu & Willump").
_MAX_TEAM = 10
_MAX_BENCH = 20
_MAX_VARIANTS = 20
_MAX_NAME = 64
_MAX_LABEL = 48
_LIST_KINDS = (list, tuple)
# compute_factors is also called with sets by internal callers; order is
# irrelevant to a count.
_TEAM_KINDS = (list, tuple, set, frozenset)

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

_ENGAGE_NORM = frozenset("".join(ch for ch in e.lower() if ch.isalnum())
                         for e in _ENGAGE)
_SUSTAIN_NORM = frozenset("".join(ch for ch in s.lower() if ch.isalnum())
                          for s in _SUSTAIN)

# Champion index. Published whole under _lock (a concurrent caller never sees
# a half-built index) and cached only on success: a failed load returns {}
# and _GATE keeps the loader off the disk for its backoff window.
_lock = threading.Lock()
_GATE = FailedLoadGate()
_champ_index: dict[str, dict] = {}
# norm(DDragon id / data key) -> champion, only for ids that differ from every
# display name ("MonkeyKing" -> Wukong, "Nunu", "Renata"). Kept apart from
# _champ_index so its values stay one entry per champion.
_alias_index: dict[str, dict] = {}
_index_loaded = False


def _norm(name: object) -> str:
    """Lower-case, alnum-only normalisation for champ-name matching."""
    return "".join(ch for ch in str(name).lower() if ch.isalnum())


def _reset_cache() -> None:
    """Test seam: drop the cached index and the failure backoff."""
    global _champ_index, _alias_index, _index_loaded
    with _lock:
        _champ_index = {}
        _alias_index = {}
        _index_loaded = False
        _GATE.reset()


def _resolve_patch() -> Optional[str]:
    """The current DS patch token, or None.

    utf-8-sig: a PowerShell 5.1 ``-Encoding UTF8`` write leaves a BOM that a
    plain utf-8 read keeps inside the token, so champions.json went "missing".
    A token carrying a path separator, a drive colon or ``..`` is refused: it
    would read a champions.json outside the DS data dir.
    """
    try:
        patch = _DS_DATA_DIR.joinpath("current.txt").read_text(
            encoding="utf-8-sig").strip()
    # RM-291A: UnicodeDecodeError is a ValueError, not an OSError.
    except (OSError, UnicodeDecodeError):
        return None
    if not patch or any(bad in patch for bad in _PATCH_FORBIDDEN):
        return None
    return patch


def _read_champions(path: Path) -> dict:
    """champions.json ['data'] as a dict; raises ValueError on a junk shape."""
    doc = json.loads(path.read_text(encoding="utf-8-sig"))
    data = doc.get("data") if isinstance(doc, dict) else None
    if not isinstance(data, dict):
        raise ValueError("champions.json carries no 'data' object")
    return data


def _build_index(data: dict) -> tuple[dict, dict]:
    names: dict[str, dict] = {}
    for champ in data.values():
        if isinstance(champ, dict):
            name = champ.get("name")
            key = _norm(name) if isinstance(name, str) else ""
            if key:
                names.setdefault(key, champ)
    aliases: dict[str, dict] = {}
    for data_key, champ in data.items():
        if not isinstance(champ, dict) or not isinstance(champ.get("name"), str):
            continue
        for form in (data_key, champ.get("id")):
            key = _norm(form) if isinstance(form, str) else ""
            # A display name always wins over a colliding id.
            if key and key not in names:
                aliases.setdefault(key, champ)
    return names, aliases


def _load_index() -> dict[str, dict]:
    """norm(name) -> champion dict. Cached on success; {} fail-soft.

    Indexes by the DISPLAY name field (c['name']) not the data key, because the
    caller passes display names ("Lee Sin", "Dr. Mundo"), while the JSON key is
    the DDragon id ("LeeSin", "DrMundo"); ids that differ from every name are
    resolved through _alias_index by _lookup.
    """
    global _champ_index, _alias_index, _index_loaded
    if _index_loaded:
        return _champ_index
    with _lock:
        if _index_loaded:
            return _champ_index
        if not _GATE.should_attempt():
            return {}
        try:
            patch = _resolve_patch()
            if not patch:
                raise ValueError("current.txt missing, empty, unreadable or refused")
            names, aliases = _build_index(
                _read_champions(_DS_DATA_DIR / patch / "champions.json"))
            if not names:
                raise ValueError("champions.json names no champion")
        # RecursionError: json.loads on a too-deep document.
        except (OSError, ValueError, RecursionError) as exc:
            if _GATE.record_failure():
                logger.warning("aram_comp_verdict: champion index load failed "
                               "(%s): %s", type(exc).__name__, exc)
            return {}
        _GATE.record_success()
        _champ_index, _alias_index = names, aliases
        _index_loaded = True
        return names


def _clean_name(name: object) -> str:
    """A stripped champion-name string, or "" for a non-str / over-long one."""
    if not isinstance(name, str):
        return ""
    name = name.strip()
    return name if len(name) <= _MAX_NAME else ""


def _lookup(name: object) -> Optional[dict]:
    key = _norm(_clean_name(name))
    if not key:
        return None
    return _load_index().get(key) or _alias_index.get(key)


def _num(value: object) -> Optional[float]:
    """A finite float, or None (bool, junk, NaN and inf are not numbers)."""
    if isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return out if math.isfinite(out) else None


def _stat_range(champ: dict) -> float:
    stats = champ.get("stats") if isinstance(champ, dict) else None
    if not isinstance(stats, dict):
        return 0.0
    rng = _num(stats.get("attackrange"))
    return rng if rng is not None and rng > 0.0 else 0.0


def _damage_lean(champ: dict) -> str:
    """'ad' | 'ap' | 'hybrid' from DDragon's info.attack vs info.magic.

    A missing rating reads 0; a present but junk or non-finite one makes the
    lean undecidable, so 'hybrid'."""
    info = champ.get("info") if isinstance(champ, dict) else None
    if not isinstance(info, dict):
        return "hybrid"
    ratings = []
    for field in ("attack", "magic"):
        raw = info.get(field)
        val = 0.0 if raw is None else _num(raw)
        if val is None:
            return "hybrid"
        ratings.append(val)
    a, m = ratings
    if a > m:
        return "ad"
    if m > a:
        return "ap"
    return "hybrid"


def _is_frontline(champ: dict) -> bool:
    tags = champ.get("tags") if isinstance(champ, dict) else None
    if not isinstance(tags, _LIST_KINDS):
        return False  # a str would match "Tank" as a substring
    if "Tank" in tags:
        return True
    return "Fighter" in tags and _stat_range(champ) < RANGED_MIN_RANGE


def _names(seq: object, kinds: tuple = _LIST_KINDS,
           cap: Optional[int] = None) -> list:
    """Cleaned non-empty name strings from a real list (a str, a dict or any
    other junk reads as empty), optionally capped."""
    if not isinstance(seq, kinds):
        return []
    out = []
    for raw in seq:
        name = _clean_name(raw)
        if name:
            out.append(name)
            if cap is not None and len(out) >= cap:
                break
    return out


def compute_factors(team: list) -> dict:
    """Comp-balance facts over a list of champion display names.

    Unknown names are skipped (not counted), so a partially-resolved team still
    yields honest counts over what resolved. A DDragon id ("MonkeyKing")
    resolves too. Anything but a list / tuple / set of strings reads as empty.
    """
    resolved = [(n, _lookup(n)) for n in _names(team, _TEAM_KINDS)]
    champs = [c for _, c in resolved if c]
    leans = [_damage_lean(c) for c in champs]
    ad = sum(1 for lean in leans if lean == "ad")
    ap = sum(1 for lean in leans if lean == "ap")
    hybrid = sum(1 for lean in leans if lean == "hybrid")
    ranged = sum(1 for c in champs if _stat_range(c) >= RANGED_MIN_RANGE)
    # Curated sets match the resolved DISPLAY name, so an id alias counts.
    names_norm = {_norm(c.get("name")) if c else _norm(n) for n, c in resolved}
    return {
        "n": len(champs),
        "ranged_count": ranged,
        "melee_count": len(champs) - ranged,
        "ad_count": ad,
        "ap_count": ap,
        "hybrid_count": hybrid,
        "frontline_count": sum(1 for c in champs if _is_frontline(c)),
        "engage_count": len(_ENGAGE_NORM & names_norm),
        "sustain_count": len(_SUSTAIN_NORM & names_norm),
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
    # The resolved display name, so a bench id alias still matches.
    if gap == "engage":
        return _norm(c.get("name")) in _ENGAGE_NORM
    if gap == "sustain":
        return _norm(c.get("name")) in _SUSTAIN_NORM
    return False


# Y-05 net-benefit gate (external reference S, method only). A gap a swap
# NEWLY INTRODUCES weighs this much against the gaps it fixes; anything not
# listed weighs 1. Range and frontline weigh 2 because they are the two factors
# comp_verdict already reports at "high" confidence: swapping out the only
# frontline to gain range must not read as an even trade.
_INTRODUCED_WEIGHT = {"range": 2, "frontline": 2}


def _gap_keys(gaps: list) -> list:
    """Ordered gap list -> JSON-plain keys ("range", "damage:ap", ...)."""
    return [f"{g}:{d}" if d else g for g, d in gaps]


def _introduced_weight(keys) -> int:
    return sum(_INTRODUCED_WEIGHT.get(str(k).split(":", 1)[0], 1) for k in keys)


def _trial_team(team: list, my_champ: str, candidate: str) -> Optional[list]:
    """A NEW list with my champion's slot replaced by `candidate`; None when my
    champion is not in `team` (no slot to model). Never mutates `team`."""
    mine = _norm(my_champ)
    if not mine:
        return None
    for i, name in enumerate(team):
        if _norm(name) == mine:
            return [*team[:i], candidate, *team[i + 1:]]
    return None


def _best_bench(bench: list, gap: str, detail, f: dict, gaps: list,
                team: Optional[list] = None, my_champ: str = "") -> dict:
    """Pick the bench champ fixing `gap`, judged on the TRIAL team.

    Each candidate that addresses `gap` is re-scored on the team with MY
    champion replaced: compute_factors + _ordered_gaps on that trial team.
    It is accepted only when gaps fixed >= weighted gaps newly introduced
    (_INTRODUCED_WEIGHT). Ranking: net gaps removed, then keeps every factor
    already satisfied, then the legacy score (fixes `gap` + covers the most
    other gaps). Returns {"pick", "gaps_after", "caveat"}; pick None when no
    candidate passes, with the caveat naming the best rejected one.

    When my champion is not in `team` the trial cannot be built: the legacy
    pick is kept and the caveat says it was not net-checked.
    """
    before = _gap_keys(gaps)
    before_set = set(before)
    others = [(g, d) for g, d in gaps if g != gap]
    best, best_rank, rejected = None, None, None
    for name in bench:
        if not _bench_addresses(name, gap, detail, f):
            continue
        score = 1 + sum(1 for g, d in others if _bench_addresses(name, g, d, f))
        trial = _trial_team(team or [], my_champ, name)
        if trial is None:
            rank = (0, 1, score)
            cand = {"pick": name, "gaps_after": list(before),
                    "caveat": f"{name}: swap not net-checked "
                              f"({my_champ or 'my champion'} not in my team)."}
        else:
            after = _gap_keys(_ordered_gaps(compute_factors(trial)))
            fixed = [k for k in before if k not in set(after)]
            introduced = [k for k in after if k not in before_set]
            net = len(fixed) - _introduced_weight(introduced)
            if net < 0:
                if rejected is None or net > rejected[0]:
                    rejected = (net, name, fixed, introduced)
                continue
            rank = (net, 0 if introduced else 1, score)
            caveat = ""
            if introduced:
                caveat = (f"Swap to {name} breaks "
                          f"{', '.join(_key_phrase(k) for k in introduced)}.")
            cand = {"pick": name, "gaps_after": after, "caveat": caveat}
        if best_rank is None or rank > best_rank:
            best, best_rank = cand, rank
    if best is not None:
        return best
    caveat = ""
    if rejected is not None:
        net, name, fixed, introduced = rejected
        fixes = ", ".join(_key_phrase(k) for k in fixed) or "no gap"
        caveat = (f"{name} rejected: fixes {fixes} but breaks "
                  f"{', '.join(_key_phrase(k) for k in introduced)} "
                  f"(net {net}).")
    return {"pick": None, "gaps_after": list(before), "caveat": caveat}


def _key_phrase(key: str) -> str:
    gap, _, detail = str(key).partition(":")
    if gap == "damage" and detail:
        return f"damage mix (no {detail.upper()})"
    return gap


def _variant_addresses(variant: dict, keywords: tuple) -> bool:
    text = " ".join(str(variant.get(k) or "")[:256]
                    for k in ("key", "label", "summary")).lower()
    return any(kw in text for kw in keywords)


def _variant_label(variant: dict) -> str:
    """The label echoed into a reason: a bounded string, else the key."""
    label = variant.get("label")
    label = label.strip() if isinstance(label, str) else ""
    if not label:
        return variant["key"]
    return label if len(label) <= _MAX_LABEL else label[:_MAX_LABEL - 3] + "..."


def _variants(raw: object) -> list:
    """Variant dicts with a bounded non-empty str key; junk reads as none."""
    if not isinstance(raw, _LIST_KINDS):
        return []
    out = []
    for v in raw:
        if isinstance(v, dict) and _clean_name(v.get("key")):
            out.append({**v, "key": v["key"].strip()})
            if len(out) >= _MAX_VARIANTS:
                break
    return out


def _find_variant(variants: list, current: str, keywords: tuple) -> Optional[dict]:
    cur = _norm(current)
    for v in variants:
        if _norm(v.get("key")) == cur:
            continue  # can't "switch" to the variant already active
        if _variant_addresses(v, keywords):
            return v
    return None


def _result(ok, rec, swap_to, variant_to, reason, conf, f,
            gaps_before=None, gaps_after=None, caveat=""):
    # Y-05: gaps_before / gaps_after are the ordered gap keys of the current
    # team and of the team the verdict leads to (a variant or a stay leaves the
    # composition, so the gaps, unchanged). caveat names what a swap breaks or
    # why a candidate was rejected; "" when there is nothing to say. A caveat
    # is also appended to `reason` so text-only renderers still show it.
    if caveat:
        reason = f"{reason} {caveat}"
    before = list(gaps_before or [])
    return {
        "ok": ok, "recommendation": rec, "swap_to": swap_to or "",
        "variant_to": variant_to or "", "reason": reason,
        "confidence": conf, "factors": f,
        "gaps_before": before,
        "gaps_after": list(before if gaps_after is None else gaps_after),
        "caveat": caveat or "",
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
        # state is the POST body verbatim: real lists of bounded strings only.
        team = _names(state.get("my_team"), cap=_MAX_TEAM)
        if len(team) < 3:
            return _stay_unknown()
        my_champ = _clean_name(state.get("my_champion"))
        bench = _names(state.get("bench"), cap=_MAX_BENCH)
        variants = _variants(state.get("variants"))
        current_variant = _clean_name(state.get("current_variant"))

        f = compute_factors(team)
        if f["n"] < 3:
            # Docstring contract: judged only over >= 3 RESOLVABLE champs.
            return _stay_unknown()
        gaps = _ordered_gaps(f)
        before = _gap_keys(gaps)
        if not gaps:
            reason = (f"Comp is balanced ({f['ranged_count']} ranged, mixed "
                      f"damage, frontline present) - stay.")
            return _result(True, "stay", "", "", reason, "high", f, before)

        rejected_caveat = ""
        for gap, detail in gaps:
            # Build-addressable gaps (damage / sustain): prefer a variant.
            if gap == "damage":
                kw = _AP_VARIANT_KW if detail == "ap" else _AD_VARIANT_KW
                v = _find_variant(variants, current_variant, kw)
                if v:
                    # `detail` is the MISSING type; the comp's excess (mono) type
                    # is its opposite. Label the comp by the excess it has, not
                    # the type it lacks (LGS2/OQ22 inverted-label fix).
                    excess = "AD" if detail == "ap" else "AP"
                    reason = (f"All-{excess} comp - the {_variant_label(v)} "
                              f"variant adds {'magic' if detail == 'ap' else 'physical'} damage.")
                    return _result(True, "variant", "", v["key"], reason, "medium",
                                   f, before)
            if gap == "sustain":
                v = _find_variant(variants, current_variant, _SUSTAIN_VARIANT_KW)
                if v:
                    reason = (f"Comp lacks sustain - the {_variant_label(v)} "
                              f"variant adds healing/lifesteal.")
                    return _result(True, "variant", "", v["key"], reason, "medium",
                                   f, before)

            choice = _best_bench(bench, gap, detail, f, gaps, team, my_champ)
            pick = choice["pick"]
            if pick:
                reason = _swap_reason(gap, detail, pick, f)
                conf = "high" if gap in ("range", "frontline") else "medium"
                return _result(True, "swap", pick, "", reason, conf, f, before,
                               choice["gaps_after"], choice["caveat"])
            rejected_caveat = rejected_caveat or choice["caveat"]

        top = gaps[0][0]
        if rejected_caveat:
            reason = (f"{_gap_phrase(top)}, but no bench swap fixes more gaps "
                      f"than it opens - stay.")
        else:
            reason = f"{_gap_phrase(top)}, but no bench champ or variant fixes it - stay."
        return _result(True, "stay", "", "", reason, "low", f, before,
                       None, rejected_caveat)
    except Exception as exc:  # never raise into the coach path  # noqa: BLE001
        # WARNING, not DEBUG: with the inputs validated above this backstop is
        # a real bug, and a DEBUG line never reaches logs/.
        logger.warning("comp_verdict failed (%s): %s", type(exc).__name__, exc)
        return _stay_unknown()


def _swap_reason(gap: str, detail, pick: str, f: dict) -> str:
    if gap == "range":
        return (f"Only {f['ranged_count']}/{f['n']} ranged - swap to {pick} "
                f"for poke and disengage range.")
    if gap == "damage":
        # `detail` is the MISSING type; label the comp by its excess (mono) type,
        # which is the opposite (LGS2/OQ22 inverted-label fix).
        excess = "AD" if detail == "ap" else "AP"
        return f"All-{excess} comp - swap to {pick} to mix the damage type."
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
