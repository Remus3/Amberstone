# arch: cdragon ability-ratio sidecar extractor (character bins -> cdragon_ability_ratios.json) + Meraki drift | section=tools | frozen=no
"""CommunityDragon character-bin ability damage RATIOS -> per-champion sidecar JSON.

WHY (2026-06-03): the engine's per-ability ratios come from a FROZEN Meraki dump
(``data/daemon_slayer/<patch>/champion_abilities.json``). Meraki goes stale between
its own refreshes; CommunityDragon mirrors the LIVE current-patch game bins. This
tool RE-SOURCES the ratios from CDragon as an ADDITIVE sidecar plus a DRIFT report
versus the current Meraki ratios. It is NOT an engine cutover: nothing here edits
the engine or any file under ``agents/``. The DS engine keeps reading the Meraki
``champion_abilities.json``; this sidecar is INERT until a consumer opts in, and
the drift report is a human-review artifact.

PROVENANCE / REUSE: the live fetch + slug + patch-segment helpers are imported (or
minimally replicated) from ``daemon_slayer_cdragon_spell_extract.py`` - the proven
2-segment patch dir (``16.11`` not ``16.11.1``), the ``<slug>.bin.json`` URL, the
fail-soft backoff fetch, and the atomic write. The character bin is a FLAT dict of
dotted-path keys; each spell record's scalars live under an ``mSpell`` sub-dict and
the slot order (Q/W/E/R) comes from ``CharacterRecords/Root.spellNames`` (passive
slot is not in spellNames so it is not emitted).

THE RESOLVER (the pure testable core; ``resolve_spell_damage_blocks``):
CDragon stores numeric per-rank arrays under a spell's data-value list. The live
bin names that list ``DataValues`` (capitalised) with entries
``{name, values:[7-rank]}``; the older Riot tooling calls it ``mDataValues``. We
read EITHER name. Damage formulas live under ``mSpell.mSpellCalculations.<CalcName>``
each carrying ``mFormulaParts[]``. We map the part ``__type`` values:

  * NamedDataValueCalculationPart  -> contributes ``base[]`` (the referenced
                                      data-value array; an absolute flat amount).
  * StatByNamedDataValueCalculationPart -> a ratio[] = the referenced data-value
                                      array; the stat comes from ``mStat``.
  * StatByCoefficientCalculationPart -> a ratio[] = the inline ``mCoefficient``
                                      broadcast to rank length; stat from ``mStat``.
  * GameCalculationModified         -> resolve ``mModifiedGameCalculation`` (a named
                                      ref into ``mSpellCalculations``) * ``mMultiplier``
                                      ONLY when the referenced calc is itself fully
                                      flat (every part flat); else the WHOLE block
                                      falls back.
  * ProductOfSubPartsCalculationPart / SumOfSubPartsCalculationPart -> resolve ONLY
                                      when every subpart is flat (a stat-ratio times
                                      a plain number yields a scaled ratio; a sum of
                                      flat parts yields a combined ratio); else the
                                      WHOLE block falls back.
  * ANY of ByCharLevelInterpolationCalculationPart,
    ByCharLevelBreakpointsCalculationPart, Breakpoint,
    BuffCounterByNamedDataValueCalculationPart, BuffCounterByCoefficient(...),
    GameCalculationConditional, StatBySubPartCalculationPart, a buff/conditional
    cross-ref via ``mSpellCalculationKey``, or an unrecognised ``__type`` -> mark the
    WHOLE block ``resolution="fallback"`` and emit NO ratios (Meraki stays
    authoritative there).

STAT ENUM -> schema field (CONSERVATIVE - only emit a ratio when the stat enum is
KNOWN; an unknown enum makes the WHOLE block fall back, never a guess):
  * absent (no ``mStat``) or the AP enum -> ``ap_pct``
  * ``mStat == 2``  -> ``total_ad_pct``
  * ``mStat == 8``  -> ``bonus_ad_pct``  (observed live: Jhin passive 0.35 bonus-AD)
  * ``mStat == 12`` (max-HP, carries ``mStatFormula``) -> ``caster_max_hp_pct`` for a
                     caster-sourced ratio, ``target_max_hp_pct`` when the referenced
                     data-value name marks it as target (``Target...`` prefix). When
                     the caster/target split is undeterminable we DEFAULT to caster
                     (the common live case: Zac Q / Garen W shield are caster max HP).
  * any other enum  -> unknown -> the WHOLE block falls back.

CDragon stores ratios as FRACTIONS (0.75); we MULTIPLY by 100 to match the Meraki
percent schema (75.0). ``base[]`` is an absolute amount, kept as-is. For a
mode-override data block (``DataValuesModeOverride`` / ``mDataValuesModeOverride``
keyed ``cherry``) we resolve the SR/default values and only NOTE cherry presence in
``cherry_override`` - never use cherry as the primary.

OUTPUT sidecar ``data/daemon_slayer/<patch>/cdragon_ability_ratios.json``:
  {patch, generated_note, champions: {<Champ>: {Q:[{name, base[], ap_pct[],
   total_ad_pct[], bonus_ad_pct[], caster_max_hp_pct[], target_max_hp_pct[],
   resolution, calc_type}], W:[...], E:[...], R:[...]}}}.
``<patch>`` resolves from ``data/daemon_slayer/current.txt`` (a 3-segment repo id
mapped to the 2-segment CDragon URL form).

DRIFT MODE (``--drift``): load the committed Meraki ``champion_abilities.json``
``damage_blocks`` + the resolved CDragon ratios; for each champ/ability/field where
BOTH have a MECHANICAL value, emit ``{champ, ability, field, meraki, cdragon,
delta}``; write ``data/daemon_slayer/<patch>/cdragon_ratio_drift.json`` with a
summary ``{n_champs, n_blocks_compared, n_changed, n_only_cdragon, n_fallback,
n_meraki_only}`` and print it.

CLI: ``--drift`` adds the drift report; ``--champions Lux,Darius,Zac`` subsets;
``--patch`` overrides; ``--out`` overrides; ``--sleep`` paces network calls;
``--limit`` smokes a subset; ``--dry-run`` skips the write; ``-v`` per-champ log.
Live fetches happen ONLY in the live path (the resolver core never touches the
network). stdlib + urllib only (the DS data-pipeline rule); ASCII-only output and
source (no em/en-dashes, no smart quotes).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DATA_DIR = PROJECT_ROOT / "data" / "daemon_slayer"

# Reuse the proven live helpers from the sibling spell extractor when importable
# (same host, same bin, same 2-segment patch contract). Fall back to a minimal
# local replication so the resolver core + tests never hard-depend on the import.
try:  # pragma: no cover - import shape varies by sys.path at runtime
    import daemon_slayer_cdragon_spell_extract as _spell
except Exception:  # noqa: BLE001 - keep the module importable standalone
    _spell = None  # type: ignore[assignment]

if _spell is not None:
    _fetch_with_retry = _spell._fetch_with_retry  # live GET with backoff
    _cdragon_patch_segment = _spell._cdragon_patch_segment  # 16.11.1 -> 16.11
    _cdragon_slug = _spell._cdragon_slug  # DDragon id -> lowercased bin slug
    _char_root_name = _spell._char_root_name  # bin <Name> w/ spellNames
    CDRAGON_CHAR_URL = _spell.CDRAGON_CHAR_URL
    _SLOT_KEYS = _spell._SLOT_KEYS
else:  # pragma: no cover - exercised only when the sibling import is unavailable
    import urllib.request

    CDRAGON_CHAR_URL = (
        "https://raw.communitydragon.org/{patch}/game/data/characters/"
        "{slug}/{slug}.bin.json"
    )
    _SLOT_KEYS = ("Q", "W", "E", "R")
    _HEADER_UA = "RiotCommander-DaemonSlayer/1.0 (offline patch-refresh extractor)"

    def _fetch_with_retry(url: str, retries: int = 3, backoff_s: float = 3.0) -> str:
        last: Optional[Exception] = None
        for attempt in range(max(1, retries)):
            try:
                req = urllib.request.Request(
                    url, headers={"User-Agent": _HEADER_UA, "Accept": "*/*"}
                )
                with urllib.request.urlopen(req, timeout=40) as resp:
                    return resp.read().decode("utf-8", "replace")
            except Exception as exc:  # noqa: BLE001 - retry transient CDN 404/5xx
                last = exc
                if attempt + 1 < retries and backoff_s > 0:
                    time.sleep(backoff_s * (attempt + 1))
        raise last if last is not None else RuntimeError("fetch failed")

    def _cdragon_patch_segment(patch: str) -> str:
        parts = patch.split(".")
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            return parts[0] + "." + parts[1]
        return patch

    def _cdragon_slug(ddragon_id: str) -> str:
        return ddragon_id.lower()

    def _char_root_name(doc: dict[str, Any], slug: str) -> Optional[str]:
        names: list[str] = []
        seen: set[str] = set()
        for key in doc:
            if isinstance(key, str) and key.startswith("Characters/"):
                parts = key.split("/")
                if len(parts) >= 2 and parts[1] and parts[1] not in seen:
                    seen.add(parts[1])
                    names.append(parts[1])
        for nm in names:
            root = doc.get("Characters/" + nm + "/CharacterRecords/Root")
            if isinstance(root, dict):
                sn = root.get("spellNames")
                if isinstance(sn, list) and sn:
                    return nm
        return names[0] if names else None


# --------------------------------------------------------------------------- stat enum map
# The schema field each KNOWN CDragon ``mStat`` enum maps to. An absent ``mStat``
# (or the explicit AP enum 0) means AP. Enum values verified live in the 16.11 bins
# (mStat 2 = total AD; mStat 8 = bonus AD; mStat 12 = max HP with mStatFormula).
# A "max-HP" enum is handled specially (caster-vs-target) so it is NOT a plain
# field here. ANY enum not in this map (e.g. 4 = attack speed) makes the block fall
# back - the conservative rule (never guess a stat).
_STAT_AP_ENUM = 0
_STAT_TOTAL_AD_ENUM = 2
_STAT_BONUS_AD_ENUM = 8
_STAT_MAX_HP_ENUM = 12

_STAT_FIELD: dict[int, str] = {
    _STAT_AP_ENUM: "ap_pct",
    _STAT_TOTAL_AD_ENUM: "total_ad_pct",
    _STAT_BONUS_AD_ENUM: "bonus_ad_pct",
}

# The ordered ratio fields a resolved block can carry (all percent-scaled).
_RATIO_FIELDS = (
    "ap_pct",
    "total_ad_pct",
    "bonus_ad_pct",
    "caster_max_hp_pct",
    "target_max_hp_pct",
)

# Part ``__type`` values that ALWAYS force the whole block to fall back (level /
# breakpoint / buff-counter / conditional / cross-ref parts that the percent schema
# cannot represent). Any unrecognised type also falls back (handled in code).
_HARD_FALLBACK_TYPES = frozenset({
    "ByCharLevelInterpolationCalculationPart",
    "ByCharLevelBreakpointsCalculationPart",
    "Breakpoint",
    "BuffCounterByNamedDataValueCalculationPart",
    "BuffCounterByCoefficientCalculationPart",
    "BuffCounterByCoefficient",
    "GameCalculationConditional",
    "StatBySubPartCalculationPart",
})

# The flat (rank-array-resolvable) part types the subpart / modified resolvers
# accept. Anything else inside a product/sum/modified part forces fallback.
_FLAT_PART_TYPES = frozenset({
    "NamedDataValueCalculationPart",
    "StatByNamedDataValueCalculationPart",
    "StatByCoefficientCalculationPart",
    "NumberCalculationPart",
})


# --------------------------------------------------------------------------- small numeric helpers
def _num(v: Any) -> Optional[float]:
    """A scalar -> float, or None for bool / non-numeric."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return None


def _round6(v: Optional[float]) -> Optional[float]:
    return None if v is None else round(float(v), 6)


def _data_values_index(mspell: dict[str, Any]) -> dict[str, list[float]]:
    """Map a spell's data-value ``name`` -> its per-rank float array.

    The live bin names this list ``DataValues``; older Riot tooling uses
    ``mDataValues``. We read either (DataValues wins when both present). Each
    entry is ``{name, values:[...]}``; a non-numeric / empty values list is
    skipped (so a referencing part that needs it will fall back).
    """
    out: dict[str, list[float]] = {}
    for key in ("DataValues", "mDataValues"):
        block = mspell.get(key)
        if not isinstance(block, list):
            continue
        for entry in block:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            vals = entry.get("values")
            if not isinstance(name, str) or not isinstance(vals, list) or not vals:
                continue
            arr: list[float] = []
            ok = True
            for x in vals:
                n = _num(x)
                if n is None:
                    ok = False
                    break
                arr.append(n)
            if ok and name not in out:
                out[name] = arr
    return out


def _broadcast(value: float, length: int) -> list[float]:
    """An inline coefficient broadcast to ``length`` ranks (>=1)."""
    return [value] * max(1, length)


def _stat_field_for(mstat: Any, data_value_name: Optional[str]) -> Optional[str]:
    """Resolve a part's stat enum -> schema field name, or None if unknown.

    ``mstat`` absent (None) means AP. A known scalar enum maps via ``_STAT_FIELD``.
    The max-HP enum resolves caster-vs-target by the referenced data-value name (a
    ``Target...`` prefix -> target; otherwise caster, the common live case).
    Anything else -> None (the caller falls the whole block back).
    """
    if mstat is None:
        return "ap_pct"
    si = _num(mstat)
    if si is None:
        return None
    enum = int(round(si))
    if enum in _STAT_FIELD:
        return _STAT_FIELD[enum]
    if enum == _STAT_MAX_HP_ENUM:
        name = data_value_name or ""
        if name.lower().startswith("target"):
            return "target_max_hp_pct"
        return "caster_max_hp_pct"
    return None


# --------------------------------------------------------------------------- flat-part evaluation
class _Fallback(Exception):
    """Raised internally when a part cannot be represented in the percent schema."""


def _flat_part_value(part: dict[str, Any], data_vals: dict[str, list[float]],
                     rank_len: int) -> tuple[Optional[str], list[float]]:
    """Evaluate ONE LEAF flat part -> (field_or_None_for_base, per-rank array).

    A ``NamedDataValueCalculationPart`` / ``NumberCalculationPart`` is a flat
    (non-ratio) amount: field is None (it is a base/multiplier magnitude). A
    ``StatBy...`` part is a ratio: field is the resolved schema field and the array
    is the FRACTION (caller scales to percent). Raises ``_Fallback`` for any
    unrepresentable shape (unknown stat, missing data value, unknown type).
    """
    ptype = part.get("__type")
    if ptype == "NamedDataValueCalculationPart":
        dv = part.get("mDataValue")
        arr = data_vals.get(dv) if isinstance(dv, str) else None
        if arr is None:
            raise _Fallback(f"missing data value {dv!r}")
        return None, list(arr)
    if ptype == "NumberCalculationPart":
        n = _num(part.get("mNumber"))
        if n is None:
            raise _Fallback("non-numeric mNumber")
        return None, _broadcast(n, rank_len)
    if ptype == "StatByNamedDataValueCalculationPart":
        dv = part.get("mDataValue")
        arr = data_vals.get(dv) if isinstance(dv, str) else None
        if arr is None:
            raise _Fallback(f"missing stat data value {dv!r}")
        field = _stat_field_for(part.get("mStat"), dv if isinstance(dv, str) else None)
        if field is None:
            raise _Fallback("unknown stat enum")
        return field, list(arr)
    if ptype == "StatByCoefficientCalculationPart":
        coef = _num(part.get("mCoefficient"))
        if coef is None:
            raise _Fallback("non-numeric mCoefficient")
        field = _stat_field_for(part.get("mStat"), None)
        if field is None:
            raise _Fallback("unknown stat enum")
        return field, _broadcast(coef, rank_len)
    raise _Fallback(f"non-flat part type {ptype!r}")


def _rank_length(parts: list[dict[str, Any]], data_vals: dict[str, list[float]]) -> int:
    """Infer the per-rank array length from any referenced data value (else 7)."""
    for arr in data_vals.values():
        if arr:
            return len(arr)
    return 7


def _resolve_subpart_product(part: dict[str, Any], data_vals: dict[str, list[float]],
                             rank_len: int) -> tuple[Optional[str], list[float]]:
    """A ProductOfSubParts (mPart1 * mPart2) -> (field, per-rank array) if flat.

    The product of a stat-ratio and a plain number is a scaled ratio; the product
    of two plain numbers is a scaled base (field None). Each subpart must reduce to
    a SINGLE contribution (a multi-term subpart, two ratios, or any non-flat
    subpart) raise ``_Fallback``.
    """
    p1 = part.get("mPart1")
    p2 = part.get("mPart2")
    if not isinstance(p1, dict) or not isinstance(p2, dict):
        raise _Fallback("product missing mPart1/mPart2")
    c1 = _resolve_flat_any(p1, data_vals, rank_len)
    c2 = _resolve_flat_any(p2, data_vals, rank_len)
    if len(c1) != 1 or len(c2) != 1:
        raise _Fallback("product subpart is multi-term")
    (f1, a1), (f2, a2) = c1[0], c2[0]
    fields = [f for f in (f1, f2) if f is not None]
    if len(fields) > 1:
        raise _Fallback("product of two ratios is not a single schema field")
    field = fields[0] if fields else None
    n = max(len(a1), len(a2), rank_len)
    out = [
        (a1[i] if i < len(a1) else a1[-1]) * (a2[i] if i < len(a2) else a2[-1])
        for i in range(n)
    ]
    return field, out


def _resolve_subpart_sum(part: dict[str, Any], data_vals: dict[str, list[float]],
                         rank_len: int) -> tuple[Optional[str], list[float]]:
    """A SumOfSubParts -> (field, per-rank array) if every subpart is flat AND they
    share at most one ratio field (a sum of like terms). Mixed ratio fields, a
    multi-term subpart, or a non-flat subpart raise ``_Fallback``."""
    subs = part.get("mSubparts")
    if not isinstance(subs, list) or not subs:
        raise _Fallback("sum missing mSubparts")
    resolved: list[tuple[Optional[str], list[float]]] = []
    for sp in subs:
        if not isinstance(sp, dict):
            raise _Fallback("non-dict subpart")
        c = _resolve_flat_any(sp, data_vals, rank_len)
        if len(c) != 1:
            raise _Fallback("sum subpart is multi-term")
        resolved.append(c[0])
    fields = {f for f, _ in resolved if f is not None}
    if len(fields) > 1:
        raise _Fallback("sum mixes multiple schema fields")
    field = next(iter(fields)) if fields else None
    n = max([len(a) for _, a in resolved] + [rank_len])
    out = [0.0] * n
    for _, arr in resolved:
        for i in range(n):
            out[i] += arr[i] if i < len(arr) else arr[-1]
    return field, out


def _resolve_flat_any(part: dict[str, Any], data_vals: dict[str, list[float]],
                      rank_len: int) -> list[tuple[Optional[str], list[float]]]:
    """Resolve any FLAT part (leaf or a product/sum of flat parts) -> a list of
    (field, array) contributions. A leaf or a product/sum collapses to a single
    contribution; the list shape lets a modified-ref carry multiple. Non-flat /
    unknown shapes raise ``_Fallback``."""
    ptype = part.get("__type")
    if ptype == "ProductOfSubPartsCalculationPart":
        return [_resolve_subpart_product(part, data_vals, rank_len)]
    if ptype == "SumOfSubPartsCalculationPart":
        return [_resolve_subpart_sum(part, data_vals, rank_len)]
    if ptype in _HARD_FALLBACK_TYPES or ptype not in _FLAT_PART_TYPES:
        raise _Fallback(f"non-flat nested part {ptype!r}")
    return [_flat_part_value(part, data_vals, rank_len)]


def _calc_is_flat(calc: dict[str, Any], data_vals: dict[str, list[float]]) -> bool:
    """True when every part of a named calc is flat-resolvable (for the modified
    ref). A part referencing a missing data value or an unknown type makes it not
    flat."""
    parts = calc.get("mFormulaParts")
    if not isinstance(parts, list) or not parts:
        return False
    rank_len = _rank_length(parts, data_vals)
    for p in parts:
        if not isinstance(p, dict):
            return False
        try:
            _resolve_flat_any(p, data_vals, rank_len)
        except _Fallback:
            return False
    return True


def _resolve_modified(part: dict[str, Any], calcs: dict[str, Any],
                      data_vals: dict[str, list[float]], rank_len: int,
                      ) -> list[tuple[Optional[str], list[float]]]:
    """A GameCalculationModified -> a LIST of (field, per-rank array) contributions
    ONLY if the referenced calc is fully flat, each scaled by the multiplier.

    The multiplier is a flat NumberCalculationPart (or a bare number). A modified
    ref preserves EVERY contribution of the referenced calc (a base magnitude AND
    any ratio fields), each multiplied through - so ``BladeDamage * 0.35`` keeps
    both the scaled base and the scaled total-AD ratio. Non-flat ref, missing ref,
    or a non-flat multiplier raise ``_Fallback``.
    """
    ref_name = part.get("mModifiedGameCalculation")
    ref = calcs.get(ref_name) if isinstance(ref_name, str) else None
    if not isinstance(ref, dict) or not _calc_is_flat(ref, data_vals):
        raise _Fallback("modified ref missing or not flat")
    # resolve the multiplier (a NumberCalculationPart wrapper or a bare number)
    mult_part = part.get("mMultiplier")
    if isinstance(mult_part, dict):
        mn = _num(mult_part.get("mNumber"))
        if mn is None:
            raise _Fallback("non-flat multiplier")
        mult = mn
    else:
        mn = _num(mult_part)
        if mn is None:
            raise _Fallback("missing multiplier")
        mult = mn
    # accumulate the referenced calc's contributions (keyed by field) then scale.
    ref_parts = ref.get("mFormulaParts") or []
    ref_rank = _rank_length(ref_parts, data_vals)
    acc: dict[Optional[str], list[float]] = {}
    for p in ref_parts:
        for field, arr in _resolve_flat_any(p, data_vals, ref_rank):
            prev = acc.get(field)
            if prev is None:
                acc[field] = list(arr)
            else:
                n = max(len(prev), len(arr))
                acc[field] = [
                    (prev[i] if i < len(prev) else prev[-1])
                    + (arr[i] if i < len(arr) else arr[-1])
                    for i in range(n)
                ]
    return [
        (field, [x * mult for x in arr])
        for field, arr in acc.items()
    ]


# --------------------------------------------------------------------------- block resolver (the testable core)
def _empty_ratio_fields() -> dict[str, Optional[list[float]]]:
    return {f: None for f in _RATIO_FIELDS}


def resolve_calc_block(calc_name: str, calc: dict[str, Any],
                       mspell: dict[str, Any]) -> dict[str, Any]:
    """Resolve ONE named ``mSpellCalculations`` entry -> a damage block dict.

    Returns ``{name, base[], <ratio fields...>, resolution, calc_type}``. On any
    unrepresentable part (level/breakpoint/buff/conditional/unknown stat/missing
    data value) the whole block is ``resolution="fallback"`` with NO base/ratios.
    Ratios are scaled to PERCENT (fraction * 100). ``base[]`` stays absolute.
    """
    block: dict[str, Any] = {
        "name": calc_name,
        "base": None,
        **_empty_ratio_fields(),
        "resolution": "fallback",
        "calc_type": calc.get("__type") if isinstance(calc, dict) else None,
    }
    if not isinstance(calc, dict):
        return block
    parts = calc.get("mFormulaParts")
    if not isinstance(parts, list) or not parts:
        return block

    data_vals = _data_values_index(mspell)
    calcs = mspell.get("mSpellCalculations") or {}
    rank_len = _rank_length(parts, data_vals)

    base_acc: Optional[list[float]] = None
    ratio_acc: dict[str, list[float]] = {}

    def _add_base(arr: list[float]) -> None:
        nonlocal base_acc
        if base_acc is None:
            base_acc = list(arr)
        else:
            n = max(len(base_acc), len(arr))
            base_acc = [
                (base_acc[i] if i < len(base_acc) else base_acc[-1])
                + (arr[i] if i < len(arr) else arr[-1])
                for i in range(n)
            ]

    def _add_ratio(field: str, arr: list[float]) -> None:
        prev = ratio_acc.get(field)
        if prev is None:
            ratio_acc[field] = list(arr)
        else:
            n = max(len(prev), len(arr))
            ratio_acc[field] = [
                (prev[i] if i < len(prev) else prev[-1])
                + (arr[i] if i < len(arr) else arr[-1])
                for i in range(n)
            ]

    try:
        for part in parts:
            if not isinstance(part, dict):
                raise _Fallback("non-dict part")
            ptype = part.get("__type")
            # cross-ref into a conditional/buff calc -> hard fallback
            if "mSpellCalculationKey" in part:
                raise _Fallback("cross-ref mSpellCalculationKey")
            if ptype in _HARD_FALLBACK_TYPES:
                raise _Fallback(f"hard-fallback type {ptype!r}")
            if ptype == "GameCalculationModified":
                contribs = _resolve_modified(part, calcs, data_vals, rank_len)
            elif ptype == "ProductOfSubPartsCalculationPart":
                contribs = [_resolve_subpart_product(part, data_vals, rank_len)]
            elif ptype == "SumOfSubPartsCalculationPart":
                contribs = [_resolve_subpart_sum(part, data_vals, rank_len)]
            elif ptype in _FLAT_PART_TYPES:
                contribs = [_flat_part_value(part, data_vals, rank_len)]
            else:
                raise _Fallback(f"unknown part type {ptype!r}")
            for field, arr in contribs:
                if field is None:
                    _add_base(arr)
                else:
                    _add_ratio(field, arr)
    except _Fallback:
        return block  # resolution stays "fallback", no partial emission

    # success: emit base + percent-scaled ratios
    block["resolution"] = "mechanical"
    if base_acc is not None:
        block["base"] = [_round6(x) for x in base_acc]
    for field, arr in ratio_acc.items():
        block[field] = [_round6(x * 100.0) for x in arr]
    return block


def resolve_spell_damage_blocks(mspell: dict[str, Any]) -> list[dict[str, Any]]:
    """Resolve EVERY ``mSpellCalculations`` entry of one mSpell -> a list of blocks.

    The pure testable core: takes a parsed mSpell dict, returns resolved damage
    blocks (mechanical or fallback), one per named calc, in a stable name order.
    Records whose calc names are pure tooltip/duration helpers still resolve (they
    simply fall back when they reference level/buff parts). A ``cherry`` mode
    override is noted per block but never used as the primary.
    """
    calcs = mspell.get("mSpellCalculations")
    if not isinstance(calcs, dict) or not calcs:
        return []
    has_cherry = _has_cherry_override(mspell)
    out: list[dict[str, Any]] = []
    for calc_name in sorted(calcs.keys()):
        calc = calcs[calc_name]
        block = resolve_calc_block(calc_name, calc, mspell)
        if has_cherry:
            block["cherry_override"] = True
        out.append(block)
    return out


def _has_cherry_override(mspell: dict[str, Any]) -> bool:
    """True when the spell carries a cherry (Arena) data-value mode override.

    We only NOTE its presence - the resolver always uses the SR/default values.
    """
    for key in ("DataValuesModeOverride", "mDataValuesModeOverride"):
        block = mspell.get(key)
        if isinstance(block, dict) and "cherry" in block:
            return True
        if isinstance(block, list):
            for entry in block:
                if isinstance(entry, dict) and entry.get("mMode") == "cherry":
                    return True
    return False


# --------------------------------------------------------------------------- bin -> per-slot resolution
def _spells_index(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Map ``<Ability>/<Spell>`` (and bare ``<Spell>``) -> mSpell, like the sibling
    extractor (single-champion bin, so no cross-champ contamination)."""
    marker = "/Spells/"
    out: dict[str, dict[str, Any]] = {}
    for key, rec in doc.items():
        if not isinstance(key, str) or not key.startswith("Characters/"):
            continue
        idx = key.find(marker)
        if idx < 0 or not isinstance(rec, dict):
            continue
        mspell = rec.get("mSpell")
        if not isinstance(mspell, dict):
            continue
        suffix = key[idx + len(marker):]
        out[suffix] = mspell
        out.setdefault(suffix.split("/")[-1], mspell)
    return out


def resolve_bin_ratios(doc: dict[str, Any], slug: str) -> dict[str, list[dict[str, Any]]]:
    """Walk a CDragon character bin -> {slot: [resolved blocks]} for Q/W/E/R.

    Slot order comes from ``CharacterRecords/Root.spellNames`` (the passive is not
    in that list, so it is not emitted). A slot with no calcs yields an empty list.
    """
    char_name = _char_root_name(doc, slug)
    if not char_name:
        return {}
    root = doc.get("Characters/" + char_name + "/CharacterRecords/Root")
    spell_names = root.get("spellNames") if isinstance(root, dict) else None
    if not isinstance(spell_names, list) or not spell_names:
        return {}
    spells = _spells_index(doc)
    out: dict[str, list[dict[str, Any]]] = {}
    for idx, slot in enumerate(_SLOT_KEYS):
        if idx >= len(spell_names):
            break
        entry = spell_names[idx]
        if not isinstance(entry, str) or not entry:
            continue
        primary = spells.get(entry) or spells.get(entry.split("/")[-1])
        if not isinstance(primary, dict):
            continue
        out[slot] = resolve_spell_damage_blocks(primary)
    return out


# --------------------------------------------------------------------------- live extract path
def _resolve_patch(patch: Optional[str]) -> str:
    if patch:
        return patch
    cur = (DATA_DIR / "current.txt").read_text(encoding="utf-8").strip()
    if not cur:
        raise SystemExit("current.txt empty; pass --patch")
    return cur


def _load_champion_ids(patch: str) -> list[str]:
    abil = DATA_DIR / patch / "champion_abilities.json"
    if not abil.exists():
        raise SystemExit(
            f"abilities file missing: {abil} (run the abilities extractor first)"
        )
    raw = json.loads(abil.read_text(encoding="utf-8"))
    champs = raw.get("data") or raw.get("champions") or {}
    if not champs:
        raise SystemExit(f"abilities file {abil} has no 'data' champion container")
    return sorted(champs.keys())


def _champ_blocks(ddragon_id: str, patch_segment: str) -> dict[str, list[dict[str, Any]]]:
    slug = _cdragon_slug(ddragon_id)
    url = CDRAGON_CHAR_URL.format(patch=patch_segment, slug=slug)
    raw = _fetch_with_retry(url)
    return resolve_bin_ratios(json.loads(raw), slug)


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=True, indent=1, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(tmp, path)


_GENERATED_NOTE = (
    "ADDITIVE CDragon-sourced ability damage ratios (re-sourced from the LIVE "
    "current-patch game bins to counter frozen-Meraki staleness). NOT an engine "
    "cutover - the DS engine keeps reading champion_abilities.json (Meraki); this "
    "sidecar is inert until a consumer opts in. resolution=mechanical blocks are "
    "fully represented in the percent schema; resolution=fallback blocks reference "
    "level/breakpoint/buff/conditional/unknown-stat parts and Meraki stays "
    "authoritative there. ratios are percent (fraction*100); base is absolute. A "
    "run with 0 mechanical blocks means the host could not reach CDragon - do NOT "
    "commit."
)


def extract(patch: str, sleep_s: float, limit: Optional[int],
            champions: Optional[list[str]], verbose: bool) -> dict[str, Any]:
    """Extract the per-champion CDragon ratio sidecar payload (does NOT write)."""
    patch_segment = _cdragon_patch_segment(patch)
    ids = _load_champion_ids(patch)
    if champions:
        wanted = {c.strip() for c in champions if c.strip()}
        ids = [i for i in ids if i in wanted]
    if limit:
        ids = ids[:limit]

    champ_out: dict[str, dict[str, list[dict[str, Any]]]] = {}
    n_mechanical = 0
    n_fallback = 0
    errs: list[str] = []
    for n, ddragon_id in enumerate(ids):
        blocks: dict[str, list[dict[str, Any]]] = {}
        err_here = False
        try:
            blocks = _champ_blocks(ddragon_id, patch_segment)
            if not blocks:
                errs.append(f"{ddragon_id}: no spellNames / Characters root in bin")
                err_here = True
        except Exception as exc:  # noqa: BLE001 - fail-soft per champ
            errs.append(f"{ddragon_id} cdragon: {type(exc).__name__}: {str(exc)[:120]}")
            err_here = True
        champ_out[ddragon_id] = blocks
        mech = sum(
            1 for bl in blocks.values() for b in bl
            if b.get("resolution") == "mechanical"
        )
        fb = sum(
            1 for bl in blocks.values() for b in bl
            if b.get("resolution") == "fallback"
        )
        n_mechanical += mech
        n_fallback += fb
        if verbose:
            tag = "ERR" if err_here else "ok"
            print(
                f"[{n+1}/{len(ids)}] {ddragon_id}: slots={sorted(blocks.keys())} "
                f"mechanical={mech} fallback={fb} {tag}"
            )
        if sleep_s > 0 and n + 1 < len(ids):
            time.sleep(sleep_s)

    return {
        "patch": patch,
        "patch_segment": patch_segment,
        "generated_note": _GENERATED_NOTE,
        "_source": (
            "CommunityDragon game/data/characters/<slug>/<slug>.bin.json "
            "(2-segment patch; mSpellCalculations + DataValues)"
        ),
        "_champ_count": len(champ_out),
        "_n_mechanical_blocks": n_mechanical,
        "_n_fallback_blocks": n_fallback,
        "_errors": errs,
        "champions": champ_out,
    }


# --------------------------------------------------------------------------- drift mode
def _meraki_blocks(patch: str) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Load Meraki ``champion_abilities.json`` -> {champ: {slot: [damage_blocks]}}.

    Flattens every ability under each P/Q/W/E/R slot into one block list per slot
    (matching the CDragon side which emits per-calc blocks under each slot).
    """
    abil = DATA_DIR / patch / "champion_abilities.json"
    raw = json.loads(abil.read_text(encoding="utf-8"))
    champs = raw.get("data") or raw.get("champions") or {}
    out: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for cid, rec in champs.items():
        if not isinstance(rec, dict):
            continue
        slots: dict[str, list[dict[str, Any]]] = {}
        for slot in _SLOT_KEYS:
            sl = rec.get(slot)
            if not isinstance(sl, list):
                continue
            blocks: list[dict[str, Any]] = []
            for ability in sl:
                if isinstance(ability, dict):
                    for b in (ability.get("damage_blocks") or []):
                        if isinstance(b, dict):
                            blocks.append(b)
            if blocks:
                slots[slot] = blocks
        if slots:
            out[cid] = slots
    return out


def _meraki_field_values(blocks: list[dict[str, Any]], field: str) -> list[list[float]]:
    """Every Meraki per-rank array present for ``field`` across a slot's blocks."""
    vals: list[list[float]] = []
    for b in blocks:
        arr = b.get(field)
        if isinstance(arr, list) and arr and all(_num(x) is not None for x in arr):
            vals.append([float(x) for x in arr])
    return vals


def _max_abs_delta(a: list[float], b: list[float]) -> float:
    n = min(len(a), len(b))
    if n == 0:
        return 0.0
    return max(abs(a[i] - b[i]) for i in range(n))


def build_drift(patch: str, cdragon: dict[str, Any]) -> dict[str, Any]:
    """Compare the resolved CDragon ratios against the Meraki damage_blocks.

    For each champ/slot/field where BOTH sides carry a MECHANICAL value, emit a
    row ``{champ, ability, field, meraki, cdragon, delta}``. ``delta`` is the
    max abs per-rank difference. The CDragon side picks, per field, the mechanical
    block whose first-rank value is closest to the Meraki value (so a multi-block
    slot pairs the corresponding term rather than mismatching).
    """
    meraki = _meraki_blocks(patch)
    cd_champs = cdragon.get("champions") or {}
    rows: list[dict[str, Any]] = []
    n_changed = 0
    n_only_cdragon = 0
    n_blocks_compared = 0
    n_meraki_only = 0
    n_fallback = cdragon.get("_n_fallback_blocks", 0)
    champs_seen: set[str] = set()

    for champ, cd_slots in sorted(cd_champs.items()):
        mk_slots = meraki.get(champ, {})
        for slot, cd_blocks in sorted(cd_slots.items()):
            mk_blocks = mk_slots.get(slot, [])
            for field in _RATIO_FIELDS:
                cd_mech = [
                    (b.get("name"), [float(x) for x in b[field]])
                    for b in cd_blocks
                    if b.get("resolution") == "mechanical"
                    and isinstance(b.get(field), list) and b.get(field)
                ]
                mk_vals = _meraki_field_values(mk_blocks, field)
                if not cd_mech:
                    continue
                if not mk_vals:
                    # CDragon resolved a ratio Meraki has no value for
                    for name, cd_arr in cd_mech:
                        rows.append({
                            "champ": champ, "ability": slot, "field": field,
                            "meraki": None, "cdragon": cd_arr,
                            "delta": None, "calc": name, "kind": "only_cdragon",
                        })
                        n_only_cdragon += 1
                        champs_seen.add(champ)
                    continue
                # pair each Meraki value with the closest CDragon mechanical block
                for mk_arr in mk_vals:
                    best = min(
                        cd_mech,
                        key=lambda nc: abs(nc[1][0] - mk_arr[0]),
                    )
                    name, cd_arr = best
                    delta = _max_abs_delta(mk_arr, cd_arr)
                    rows.append({
                        "champ": champ, "ability": slot, "field": field,
                        "meraki": mk_arr, "cdragon": cd_arr,
                        "delta": _round6(delta), "calc": name,
                        "kind": "changed" if delta > 1e-6 else "match",
                    })
                    n_blocks_compared += 1
                    if delta > 1e-6:
                        n_changed += 1
                    champs_seen.add(champ)

    # count Meraki ratio fields with no CDragon mechanical counterpart at all
    for champ, mk_slots in meraki.items():
        cd_slots = cd_champs.get(champ, {})
        for slot, mk_blocks in mk_slots.items():
            cd_blocks = cd_slots.get(slot, [])
            cd_fields = {
                f for b in cd_blocks if b.get("resolution") == "mechanical"
                for f in _RATIO_FIELDS
                if isinstance(b.get(f), list) and b.get(f)
            }
            for field in _RATIO_FIELDS:
                if _meraki_field_values(mk_blocks, field) and field not in cd_fields:
                    n_meraki_only += 1

    summary = {
        "n_champs": len(champs_seen),
        "n_blocks_compared": n_blocks_compared,
        "n_changed": n_changed,
        "n_only_cdragon": n_only_cdragon,
        "n_fallback": n_fallback,
        "n_meraki_only": n_meraki_only,
    }
    return {
        "patch": patch,
        "generated_note": (
            "DRIFT report: resolved CDragon ratios vs the committed Meraki "
            "damage_blocks. A row exists per champ/ability/field where BOTH carry a "
            "mechanical value (delta = max abs per-rank diff). kind=only_cdragon "
            "means CDragon resolved a ratio Meraki lacks; n_meraki_only counts "
            "Meraki ratio fields with no CDragon mechanical counterpart (often a "
            "fallback block). This is a human-review artifact, not an engine input."
        ),
        "summary": summary,
        "rows": rows,
    }


# --------------------------------------------------------------------------- CLI
def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--patch", help="patch id, e.g. 16.11.1; default current.txt")
    ap.add_argument(
        "--out",
        help="sidecar output path; default "
        "data/daemon_slayer/<patch>/cdragon_ability_ratios.json",
    )
    ap.add_argument(
        "--drift", action="store_true",
        help="also write the Meraki-vs-CDragon drift report",
    )
    ap.add_argument(
        "--champions",
        help="comma-separated DDragon ids to subset (e.g. Lux,Darius,Zac)",
    )
    ap.add_argument(
        "--sleep", type=float, default=0.5,
        help="seconds between per-champ network calls (default 0.5)",
    )
    ap.add_argument(
        "--limit", type=int, default=0,
        help="extract only the first N champs (smoke test)",
    )
    ap.add_argument("--dry-run", action="store_true", help="extract but do not write")
    ap.add_argument("-v", "--verbose", action="store_true", help="per-champ progress")
    args = ap.parse_args(argv)

    patch = _resolve_patch(args.patch)
    champions = args.champions.split(",") if args.champions else None
    out_path = (
        Path(args.out) if args.out
        else (DATA_DIR / patch / "cdragon_ability_ratios.json")
    )

    payload = extract(patch, args.sleep, args.limit or None, champions, args.verbose)
    print(
        f"patch={patch} (cdragon={payload['patch_segment']}) "
        f"champs={payload['_champ_count']} "
        f"mechanical={payload['_n_mechanical_blocks']} "
        f"fallback={payload['_n_fallback_blocks']} "
        f"errors={len(payload['_errors'])}"
    )
    if payload["_errors"]:
        for e in payload["_errors"][:10]:
            print("  ERR", e)
    if payload["_n_mechanical_blocks"] == 0:
        print(
            "WARNING: 0 mechanical blocks resolved - host likely cannot reach "
            "CommunityDragon (edge block); NOT a committable sidecar."
        )

    if not args.dry_run:
        _atomic_write_json(out_path, payload)
        print(f"wrote {out_path}")

    if args.drift:
        drift = build_drift(patch, payload)
        s = drift["summary"]
        print(
            "drift: "
            f"n_champs={s['n_champs']} n_blocks_compared={s['n_blocks_compared']} "
            f"n_changed={s['n_changed']} n_only_cdragon={s['n_only_cdragon']} "
            f"n_fallback={s['n_fallback']} n_meraki_only={s['n_meraki_only']}"
        )
        if not args.dry_run:
            drift_path = out_path.parent / "cdragon_ratio_drift.json"
            _atomic_write_json(drift_path, drift)
            print(f"wrote {drift_path}")

    if args.dry_run:
        print("(dry-run; not written)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
