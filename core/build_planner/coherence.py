"""core.build_planner.coherence - carry build-coherence re-rank (Step 1).

The AD/carry ds.dps scorer ranks by pure delta_dps over the full catalog with no
coherence term, so cross-archetype artifacts surface on crit ADCs: Essence Reaver
(3508) floats to the top (its Spellblade proc is modeled at an ability-cast tempo
a pure auto-attacker lacks, and its AH + mana are DPS-invisible but unpenalized),
Eclipse (6692) rides lethality, and the crit AMPLIFIER core (Infinity Edge 3031)
is buried (greedy single-item delta_dps cannot see accumulated-crit synergy). See
ops/audit/DS_BUILD_RECO_OVERLAY_QA.md +
docs/specs/2026-07-13-ds-build-coherence-refactor.md.

coherence_rerank applies a METRIC (not win-rate, not a hand-blacklist) soft
re-rank at the carry chokepoint: dock off-axis / wasted-stat items and nudge
on-axis kit fit, both from core.build_planner.kit_synergy PRIMITIVES -
stat_fit = dot(item_vector, kit_weights) with the spellblade proc artifact
corrected, wasted_stat_penalty = anti_synergy_penalty (which now folds the
spellblade-on-non-user proc-tempo artifact). The adjustment is delta-dominated:
a coherent item (penalty ~0) only receives the uniform on-axis nudge, so a clean
build barely re-orders while the artifacts sink and the buried crit core lifts.

Metric-only + carry-scoped by control flow: a non-carry archetype early-returns
rows[:top] UNCHANGED (byte-identical), so the clean mage / tank / enchanter
builds never move.

ASCII only - use " - " for a clause break (repo hard rule).
"""
from __future__ import annotations

import math
from typing import Optional

from core.build_planner.champ_kit_data import (
    _AP_HYBRID_ITEM_IDS,
    is_ap_hybrid_marksman,
    is_caster_marksman,
)
from core.build_planner.kit_synergy import (
    anti_synergy_penalty,
    champ_kit_traits,
    stat_fit,
)

# DPS-equivalent tuning weights (delta-dominated). MU scales the wasted-stat dock
# (anti_synergy_penalty, which folds the spellblade-proc-artifact term); W scales
# the on-axis kit-fit nudge. Chosen so a coherent item (penalty ~0) only gets the
# uniform +W*fit lift while an artifact (Essence Reaver / Eclipse) is docked below
# the crit core - verified against the live 16.13.1 rank_items rows for
# Twitch / Jinx / Caitlyn / Ashe (ARAM cell). Values live in DPS units: the ER
# dock is MU*(0.5 AH-waste + 2.0 spellblade-artifact) ~= 25 DPS, enough to clear
# its raw delta lead on the tightest champ (Jinx) without perturbing the crit
# core's internal order (those rows carry penalty 0). This _MU/_W pair applies
# ONLY to the raw-delta_dps BASE (fight_length None/<=0 - every non-mapped champ);
# that branch must stay byte-identical, so DO NOT retune these two constants.
_MU = 10.0
_W = 6.0

# Eff-branch dock (L4 crit-burst fix, 2026-07-13, docs/specs/2026-07-13-ds-crit-
# burst-fix.md). When fight_length is engaged the BASE is the burst-inclusive
# effective_score (= burst_gain + delta_dps * fight_length, agents.daemon_slayer.
# rank), which is BURST-dominated: burst_gain is a total-rotation-damage delta in
# the HUNDREDS, ~8-10x the delta_dps magnitude the _MU/_W pair above was tuned
# for. Reusing _MU=10 there makes the artifact dock negligible against the base,
# so Essence Reaver (3508, anti_synergy_penalty 2.5) and Eclipse (6692, penalty
# 0.5) resurface ABOVE the crit core (Infinity Edge 3031 / The Collector 6676 /
# Yun Tal 3032). _MU_EFF is sized to the effective_score magnitude: the ER dock
# (_MU_EFF * 2.5 ~= 200) clears its MEASURED ~20-100 effective_score lead over
# IE / Collector with margin - live 16.13.1 (engine 1.208.0) at the squishy-carry
# target, ER + Eclipse fall out of the top-8 for all five crit ADCs (Twitch /
# Caitlyn / Jinx / Draven / Samira). _W_EFF stays at the _W magnitude ON PURPOSE:
# the on-axis nudge must remain a LIGHT tiebreak so the crit core's
# effective_score-driven internal order is preserved, not scrambled (a large
# _W_EFF would flip IE above Collector, overriding the burst score). These apply
# ONLY to the effective_score BASE; the delta branch keeps _MU/_W exactly.
_MU_EFF = 80.0
_W_EFF = 6.0

# The carry / marksman archetype whose ds.dps ranking this re-rank corrects. Every
# other archetype early-returns unchanged (tank / bruiser / mage / assassin /
# enchanter are clean - see the QA).
_CARRY_ARCHETYPE = "carry"

# The documented default ``top`` - also the fallback for a junk ``top``.
_DEFAULT_TOP = 6


def _finite(value) -> Optional[float]:
    """``value`` as a finite float, or None for anything else.

    A bool is rejected (``True`` is not a DPS figure); an int / float / numeric
    str is accepted the way ``float()`` already accepted it; NaN, +-inf, a
    non-numeric str, bytes, a container or any other object is None.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return out if math.isfinite(out) else None


def _engaged(fight_length) -> bool:
    """True only for a real (non-bool) finite fight_length above zero."""
    if isinstance(fight_length, bool) or not isinstance(fight_length, (int, float)):
        return False
    return math.isfinite(fight_length) and fight_length > 0


def _norm_top(top) -> int:
    """A slice length: a non-negative int, never a raise.

    An int (or an integral finite float) is clamped at 0, so a negative never
    reads as "all rows but the last"; None, a bool, a str, a fractional or a
    non-finite float is the documented default.
    """
    if isinstance(top, bool):
        return _DEFAULT_TOP
    if isinstance(top, int):
        return max(0, top)
    if isinstance(top, float) and math.isfinite(top) and top.is_integer():
        return max(0, int(top))
    return _DEFAULT_TOP


def _as_row_list(rows) -> list:
    """``rows`` as a list, or [] when it is not a row sequence.

    None, a non-iterable, and a str / bytes / dict (iterating one yields
    characters, ints or keys, never ranker rows) are all [].
    """
    if rows is None or isinstance(rows, (str, bytes, bytearray, dict)):
        return []
    try:
        return list(rows)
    except TypeError:
        return []


def _coherence_adj(row, champion: str, fight_length: Optional[float] = None,
                   ap_hybrid: Optional[bool] = None) -> Optional[float]:
    """A BASE score docked by the wasted-stat penalty and nudged by kit fit.

    The BASE is the burst-inclusive ``effective_score`` when ``fight_length`` is
    engaged (a positive finite real number) - the rank_for / rank_items reweight
    ``burst_gain + delta_dps * fight_length`` - so the fight-length reweight
    survives the coherence sort. When ``fight_length`` is None, <= 0 or junk (a
    bool, a str, NaN, inf), the BASE is the raw ``delta_dps`` and the behavior
    is byte-identical to the pre-L1 re-rank.

    The artifact dock (- mu * pen) and on-axis kit nudge (+ w * fit) use a
    branch-matched (mu, w) pair: (_MU_EFF, _W_EFF) on the effective_score BASE
    (burst-dominated, ~hundreds) and (_MU, _W) on the raw delta_dps BASE
    (~tens). This keeps the delta branch BYTE-IDENTICAL while scaling the
    penalty dock to the effective_score magnitude so the Essence Reaver / Eclipse
    artifacts stay docked below the crit core on the engaged path (L4).

    ``ap_hybrid`` (LEAP-07 DD1) is the precomputed
    ``is_ap_hybrid_marksman(champion)`` verdict, resolved lazily when None. For
    a CLASS MEMBER an ``_AP_HYBRID_ITEM_IDS`` row (Lich Bane / Liandry's + Arena
    mirrors) is ON-AXIS: its wasted-stat dock is waived and it keeps the full
    ``+ w * fit`` nudge. Every OTHER item keeps its dock even for a member, and
    a NON-member (every champion today - the allow-map ships empty) is
    byte-identical to the pre-DD1 path.

    Resolves the item by ``row.item_id`` through the kit_synergy resolver; an
    unresolvable id, any metric error, or a metric (or adjusted score) that is
    not a finite number falls back to the chosen BASE so the row keeps its
    engine score and the re-rank can never crash.

    Returns None when the BASE itself is unusable - NaN, +-inf, a bool, a
    non-numeric str or any non-number (a drifted DS payload). A missing or
    falsy base still reads as 0.0, as before. A None row SINKS below every
    scorable row in coherence_rerank: a non-finite key is unordered, so before
    this guard an inf row took the top slot and a NaN row scrambled the rows
    around it.
    """
    if _engaged(fight_length):
        raw = getattr(row, "effective_score", 0.0)
        mu, w = _MU_EFF, _W_EFF
    else:
        raw = getattr(row, "delta_dps", 0.0)
        mu, w = _MU, _W
    # A falsy base (None, 0, "") reads as 0.0 exactly as the pre-guard
    # ``float(raw or 0.0)`` did; only a truthy non-finite / non-number is junk.
    base = 0.0 if not raw else _finite(raw)
    if base is None:
        return None
    iid = getattr(row, "item_id", None)
    if iid is None:
        return base
    try:
        fit = stat_fit(str(iid), champion)
        pen = anti_synergy_penalty(str(iid), champion)
    except Exception:  # noqa: BLE001 - missing kit data -> raw base, no crash
        return base
    fit, pen = _finite(fit), _finite(pen)
    if fit is None or pen is None:
        return base
    if pen and str(iid) in _AP_HYBRID_ITEM_IDS:
        if ap_hybrid is None:
            try:
                ap_hybrid = is_ap_hybrid_marksman(champion)
            except Exception:  # noqa: BLE001 - unknown champ -> not a member
                ap_hybrid = False
        if ap_hybrid:
            # Class member: this item is ON-AXIS, waive the wasted-stat dock.
            pen = 0.0
    adj = base - mu * pen + w * fit
    return adj if math.isfinite(adj) else base


def coherence_rerank(rows, champion, top: int = _DEFAULT_TOP,
                     fight_length: Optional[float] = None):
    """Return the top ``top`` rows re-ranked for carry build coherence.

    ``rows`` is a list of ranker rows (rank_items ItemScore or the client's
    rank_for rows), each exposing ``.item_id`` / ``.item_name`` / ``.delta_dps``.
    The SAME row objects are returned (a re-sorted sub-list) - nothing is
    reconstructed, so the caller's row type is preserved. ``rows`` that is not
    a row sequence (None, a str, bytes, a dict, a non-iterable) gives [].

    ``top`` goes through _norm_top: a negative is 0 (never "every row but the
    last"); None, a bool, a str or a fractional / non-finite float is the
    default 6.

    Two byte-identical early-returns leave a build UNCHANGED (``rows[:top]``):
      * a non-carry archetype (champ_kit_traits archetype) - the clean mage /
        tank / enchanter scorers never move (Kog'Maw is arch=mage and lands here);
      * a genuine caster / spellblade marksman (is_caster_marksman - a Marksman
        with the Mage tag AND heavy ability-AP scaling: Ezreal, Corki, Smolder).
        Those kits genuinely charge Sheen-line spellblade procs + mana on an
        ability tempo, so the spellblade dock must not strip their real core.
        Narrowed per the "narrow the fold, widen on test evidence" rule.

    The pure crit / on-hit ADCs (Jinx / Caitlyn / Ashe / Twitch / Draven /
    Lucian / ...) carry no Mage tag and DO get the dock. So do the crit / on-hit
    ADCs that carry an INCIDENTAL secondary Mage tag but no ability-caster core
    (Jhin / Kai'Sa / Varus / Miss Fortune) - the ability-AP floor in
    is_caster_marksman stops the tag alone from sparing their Essence Reaver /
    Eclipse artifact (gate tightened 2026-07-13). The AP-on-AD-marksman class
    (Lich Bane / Liandry's - the "Zeri class", LEAP-07 DD1) is now a THIRD gate,
    resolved by is_ap_hybrid_marksman: a class MEMBER keeps those items on-axis
    (dock waived), a NON-member takes the standard dock. The allow-map ships
    EMPTY (Zeri measured BELOW the pure-AD control at engine 1.245.0), so no
    champion is a member today and this branch is byte-identical. The live
    client only calls this on the carry branch anyway; the gates are a
    belt-and-suspenders guarantee.

    ``fight_length`` (L1 crit-burst fix, 2026-07-13) is the OPTIONAL
    fight-length-reweight knob mirrored from the engine. When engaged (a positive
    finite real number; a bool or a str never engages), the re-rank BASE is each
    row's burst-inclusive ``effective_score`` (``burst_delta + delta_dps *
    fight_length``, set by rank_for / rank_items) so the reweight survives the
    coherence sort instead of being neutralized by a raw-delta_dps re-sort (root
    cause #1). When None or <= 0 (the default), the BASE stays raw ``delta_dps``
    and the output is byte-identical to the pre-L1 re-rank. The artifact dock +
    kit nudge and the early-returns are unchanged in both cases.

    A row whose BASE is not a finite number (_coherence_adj returns None) sinks
    below every scorable row, in its original relative order, so a corrupt row
    can neither take a top slot nor reorder the real rows.
    """
    rows = _as_row_list(rows)
    top = _norm_top(top)
    try:
        arch = champ_kit_traits(champion).get("archetype")
        caster_mks = is_caster_marksman(champion)
    except Exception:  # noqa: BLE001 - unknown champ -> leave untouched
        arch, caster_mks = None, False
    if arch != _CARRY_ARCHETYPE or caster_mks:
        return rows[:top]
    # LEAP-07 DD1 - resolved ONCE per re-rank, after the early-returns, so the
    # class predicate is consulted on exactly the carry path it governs.
    try:
        ap_hybrid = is_ap_hybrid_marksman(champion)
    except Exception:  # noqa: BLE001 - unknown champ -> not a member
        ap_hybrid = False

    def _key(r):
        adj = _coherence_adj(r, champion, fight_length, ap_hybrid)
        # (1, adj) for a scorable row, (0, 0.0) for an unusable one: every
        # sinker sorts below every real row and keeps its relative order.
        return (0, 0.0) if adj is None else (1, adj)

    # Stable sort: equal-key rows keep their original engine order (Python's
    # sorted is stable and reverse=True does not reorder equal keys).
    ranked = sorted(rows, key=_key, reverse=True)
    return ranked[:top]
