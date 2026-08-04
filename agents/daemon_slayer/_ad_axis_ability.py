"""AD-axis ability-damage term - the RM-39 / RM-43 credited-type per-spell sum.

RELOCATED here from ``hybrid.py`` by RM-36 / RM-38 (2026-08-04) so the CARRY
ranker (``rank.rank_items``) can consume the SAME term the bruiser scorer
already uses. It could not simply import ``hybrid``: ``hybrid`` imports
``rank`` (hybrid.py:50), so the dependency only runs one way.

There is exactly ONE definition of this term in the engine. ``hybrid`` binds
``_physical_ability_damage`` to ``physical_ability_damage`` below, so its
behaviour is unchanged and no private copy exists to drift.

``ability_dps`` imports ``rank`` at module level, so ``rank`` must import THIS
module lazily inside the function that needs it - the same deferred-import idiom
``dps.py:911`` already uses. ``hybrid`` imports it at module level, which is
safe because ``hybrid`` already imports ``ability_dps`` that way.
"""

from __future__ import annotations

from .ability_dps import compute_ability_dps
from .cast_propensity import propensity_adjusted_dps_delta
from .data_loader import DataSnapshot


# Damage types the AD-axis ability term credits (RM-39 / RM-43). PHYSICAL is
# the L1 set; TRUE was added at L2 on measured evidence. MAGIC and MIXED are
# deliberately absent - see _physical_ability_damage below for the rationale
# on each.
AD_AXIS_CREDITED_DAMAGE_TYPES = frozenset({"PHYSICAL", "TRUE"})


def physical_ability_damage(
    snapshot: DataSnapshot,
    champion_id: str,
    level: int,
    item_ids,
    mode: str,
    target_armor: float,
    target_mr: float,
    target_max_hp: float,
    target_bonus_hp: float,
    augments,
    target_current_hp_pct: float = 1.0,
    apply_cast_rate_propensity_prior: bool = False,
) -> float:
    """Credited-type ability-DPS scalar - the AD-axis analogue of
    ``_ability_damage`` (RM-39 / RM-43, DEFAULT-OFF seam).

    Same call as ``_ability_damage``; the ONLY difference is that it SUMS A
    FILTERED SET OF PER-SPELL ROWS instead of returning ``total_ability_dps``.
    A row is credited when BOTH gates pass:

    * its ``damage_type`` normalizes into ``AD_AXIS_CREDITED_DAMAGE_TYPES``,
      and
    * its ``ap_pct_sum`` is zero - the row does not scale with AP AT ALL.

    The second gate is the AP-SCALING EXCLUSION and it is independent of damage
    type on purpose. This is the AD-axis term; an AP-scaling row never belongs
    in it, whatever its damage type says.

    THE SUM IS NOT DIMENSIONALLY ADDITIVE WITH ``weighted_dps`` (RM-98,
    corrected 2026-07-24). This docstring previously asserted that rows being
    "post-mitigation and post-cast-rate (``ability_dps.py:1261``)" made the sum
    "directly additive". Post-cast-rate is precisely what BREAKS additivity:
    the cast rate is a WHOLE-GAME rate
    (``data/daemon_slayer/spell_cast_rates.json`` - casts divided by
    ``matches.game_duration_s``) while ``weighted_dps`` is a combat-window
    per-second figure. ``docs/specs/SPEC_rm98_cast_rate_time_base.md:76-89``
    adjudicates this and sizes the characteristic distortion at ~7x per spell.
    The term is still LOAD-BEARING and must not be dropped - measured at 30.5
    pct of Renekton's ON damage term, 29.2 pct cohort mean, 65.9 pct for Riven
    (SPEC:91-99). ``apply_cast_rate_propensity_prior`` (below) is the
    adjudicated repair; it is DEFAULT-OFF, so the sum this function returns at
    the default is still the mixed-basis one.

    ``apply_cast_rate_propensity_prior`` (RM-98, DEFAULT-OFF) re-bases the
    measured rows onto ``availability * propensity_prior`` before summing - see
    ``cast_propensity``. The delta is computed over the ALREADY-FILTERED row
    list, not over ``result.per_spell``, so BOTH gates apply to it and it can
    never re-admit a row the sum excluded. Default False never calls the helper
    (byte-identical).

    The filter reuses the canonical normalization idiom from
    ``ability_dps.py:371`` verbatim - ``(damage_type or "MAGIC").upper()`` - so
    a None damage_type falls back to MAGIC and is EXCLUDED, never treated as
    physical. That fallback is load-bearing: Aatrox E / R and Darius E all
    carry ``damage_type=None``.

    WHY THE PER-SPELL SUM - this is the real guard, and it is NOT the
    damage-type filter. Returning ``total_ability_dps`` promotes Liandry's
    Torment to #1 for Aatrox, importing AP burn items onto an AD bruiser. The
    filter does not prevent that and never did: Aatrox has ZERO nonzero
    non-PHYSICAL rows (Q 16.2499 / W 2.6193 PHYSICAL, E and R 0.0), so every
    filter arm - PHYSICAL, +TRUE, +MIXED, unfiltered - returns the identical
    number for him. The mechanism is ``item_proc_dps``
    (``ability_dps.py:1376-1381``), which folds item burn / DoT into
    ``total_ability_dps`` and appears in NO per_spell row. Measured residue
    (total minus the per_spell sum) for Aatrox: 0.0000 on an empty build,
    exactly 31.2500 with Liandry's (6653). Pinned by
    ``test_ad_axis_term_is_per_spell_sum_not_total_ability_dps``.

    WHY TRUE IS CREDITED (the L2 widen): ``_mitigation_factor`` returns a flat
    1.0 for TRUE (``ability_dps.py:372-373``), so a TRUE row carries no resist
    derivative onto the AD axis. All 5 in-cohort TRUE rows - Olaf E Reckless
    Swing, Vayne W Silver Bolts, Darius R Noxian Guillotine, MasterYi E Wuju
    Style, Garen R Demacian Justice - measured dAP 0.0000 and dVoid 0.0000, so
    crediting them imports neither AP nor magic-pen valuation. It is flat
    post-mitigation damage the AD branch was simply dropping.

    THE AP-SCALING EXCLUSION IS WHAT MAKES THAT SAFE, NOT THE DAMAGE TYPE.
    Roster-wide there are 7 TRUE rows and 2 of them DO scale with AP: Belveth R
    Endless Banquet (dAP +1.2153, ``ap_pct_sum`` 300.0) and Chogath R Feast
    (dAP +0.6076, ``ap_pct_sum`` 150.0). Nothing in the damage-type filter
    stops them. Until the kit-axis fix they were out of reach only ACCIDENTALLY,
    because ``_damage_axis`` read the DDragon ratings and routed both to "ap"
    (Belveth attack 4 / magic 7, Chogath attack 3 / magic 7) - which was wrong
    about Belveth for every OTHER purpose, since her kit is 0.698 physical.
    ``_damage_axis`` now reads the kit distribution and routes Belveth to "ad",
    so this term meets her R directly and the ``ap_pct_sum`` gate is what keeps
    it out. Do NOT widen on the assumption that TRUE is AP-inert roster-wide -
    it is not, and the axis split no longer covers for that.

    MEASURED COLLATERAL of the exclusion, recorded so it reads as a decision:
    Vayne Q Tumble is PHYSICAL and carries BOTH ``total_ad_pct`` (75..115) and
    a nonzero ``ap_pct`` (50.0 per rank), so the gate drops a genuinely
    dual-scaling row. That is the stated contract - an AD-axis term must not
    become an AP-pricing channel - and her TRUE W Silver Bolts row, the one the
    L2 widen exists for, is unaffected.

    WHY MIXED IS STILL HELD (a decision, not an oversight): the whole
    in-cohort MIXED population is Yone (W Spirit Cleave, R Fate Sealed).
    Unlike TRUE, MIXED does import magic-pen valuation - ``_mitigation_factor``
    splits it 50/50 across armor and MR (``ability_dps.py:377``), and a full
    credit moves Yone's Void Staff from 129 to 111. Yone's W / R genuinely are
    half-physical, so the honest treatment is a 50 pct credit mirroring that
    same split - a separate design, not a filter widen. MAGIC stays excluded
    permanently: crediting it climbs Udyr's Rabadon's 55 places (126 -> 71).
    """
    result = compute_ability_dps(
        snapshot,
        champion_id=champion_id,
        level=level,
        item_ids=item_ids,
        mode=mode,
        target_armor=target_armor,
        target_mr=target_mr,
        target_max_hp=target_max_hp,
        target_bonus_hp=target_bonus_hp,
        target_current_hp_pct=target_current_hp_pct,
        augments=augments,
    )
    credited_rows = [
        row
        for row in result.per_spell
        if (row.damage_type or "MAGIC").upper() in AD_AXIS_CREDITED_DAMAGE_TYPES
        and float(getattr(row, "ap_pct_sum", 0.0) or 0.0) <= 0.0
    ]
    credited = sum(row.dps for row in credited_rows)
    if not apply_cast_rate_propensity_prior:
        return credited
    # The propensity DELTA rides the SAME filtered rows, not ``per_spell`` -
    # otherwise the RM-98 path would re-admit exactly what the sum excluded.
    return credited + propensity_adjusted_dps_delta(
        credited_rows,
        credited_damage_types=AD_AXIS_CREDITED_DAMAGE_TYPES,
    )
