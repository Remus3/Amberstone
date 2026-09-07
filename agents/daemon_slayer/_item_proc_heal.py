"""Per-item PERIODIC-PROC SELF-HEAL registry, keyed by item id (RM-103).

This is the heal-side twin of an ``ItemEffect.periodics`` entry. A handful of
items deal periodic damage AND convert a multiple of that damage back into
health for the wielder. The package already models the DAMAGE half of exactly
such a proc (Unending Despair's Anguish, a ``PeriodicProc`` at
``_effects_data.py:2040-2047`` for SR 2502 and ``:3711-3716`` for Arena 222502)
but had NO carrier anywhere for the heal half - ``_effects_data.py:2050``
dismisses it as an "ally self-heal component utility-only", which is wrong on
both counts: it is a SELF heal, and a 2.5x multiplier per champion hit is not
utility. This module fills that gap.

SOURCE MAGNITUDE (vendored feed, re-derived - not inherited from the filing):
``data/daemon_slayer/16.14.1/items_meraki.json`` item 2502, passive "Anguish"
(``"unique": true``):

    "Every 4 seconds after entering combat with champions, sap all enemy
    champions around you within 650 units to deal magic damage equal to 3% of
    your bonus health to them and heal yourself equal to 250% of the
    post-mitigation damage dealt."

So, per proc, per enemy champion hit::

    heal_hp = 2.50 * 0.03 * caster_bonus_hp * (100 / (100 + victim_MR))
            = 0.075 * caster_bonus_hp   [PRE-mitigation]

There is NO level scaling in the passive text, so none is modeled.

REGISTERED IDS (each confirmed present in ``data/daemon_slayer/16.14.1/
items.json`` before adding; exactly two ids in the whole 706-item index carry
the name "Unending Despair"):
  * 2502   - Unending Despair (base). ``maps`` 11 / 12 / 21 / 35 -> this single
    id already covers SR, ARAM and the Nexus modes.
  * 222502 - Unending Despair (Arena mode-mirror, ``maps`` 30 only). Carries the
    base nominal: Meraki keys base ids only, and the Arena DDragon copy carries
    the identical Anguish text ("heal for 250% of the damage dealt"). Same
    same-nominal Arena-mirror convention as ``_item_omnivamp.py`` /
    ``_item_revive.py``.

NOT REGISTERED:
  * 322502 (ARAM mirror) - DOES NOT EXIST. Unlike Riftmaker or Archangel's,
    Unending Despair has no 32xxxx mirror; base 2502 IS the ARAM item
    (``maps["12"] == True``). Verified against the item index, not assumed.

R144 MIRROR-COVERAGE RE-MEASURE (16.14.1, slice C). Re-audited against
``core.daemon_slayer_resolver.name_to_id``, which hands the engine ``222502``
under mode="arena" where a bare-id-only registry would fall through to a silent
0.0 (the R143 / f7c49de5 defect class). COMPLETE: both ids were already
registered, and the missing ``322502`` was re-confirmed absent from the index.
The Arena mirror IS retuned in its stat block (350 HP / 10 AH vs the base
400 / 15), but its Anguish passive text is identical to the base's ("heal for
250% of the damage dealt"), so the 0.075 coefficient is carried on measured
text rather than assumed. Pinned by ``tests/test_r144_mirror_slice_c.py``.

THE ONE ASSUMPTION IN THIS LANE: ``_ASSUMED_TARGET_MR_FOR_PROC_HEAL``.
The heal is 250% of POST-mitigation damage, but the EHP consumer
(``ehp._collect_heals`` -> ``ItemHeal.resolve_magnitude``,
``_effects_types.py:457-464``) takes only base_ad / bonus_hp / bonus_ad /
missing_hp / is_ranged - it has no victim-resist input at all, and ``ehp.py``
carries ZERO executable references to ``target_mr`` (its only mention, at
``ehp.py:188``, is prose describing the DPS-side helpers). Crediting the raw
0.075 would therefore silently price the heal as if every victim had 0 MR,
over-crediting it by 60% at a typical target. Rather than impute a live value
that the EHP lane cannot supply, this module names the assumption, seeds it at
the sweep-standard TANKY target's MR of 60.0 (the ``100 / 60 / 2500 / 1200``
armor / MR / HP / bonus-HP profile used as the standard probe target - see
``tests/test_ad_axis_ability_damage_rm39.py:30`` and the 1.223.0 CHANGELOG
entry's golden-diff target pair), pins it with a test, and exposes it as an
optional per-call override so no caller inherits it silently.

At the seed, the effective coefficient is::

    0.075 * 100/(100 + 60) = 0.075 * 0.625 = 0.046875 * caster_bonus_hp

CONSERVATIVE ACTIVITY SEEDS. ``_PROC_HEAL_TRIGGERS_PER_FIGHT`` and
``_PROC_HEAL_CHAMPIONS_IN_RANGE`` are both seeded at 1.0 - the most
conservative setting available and the exact setting the RM-103 filing's own
counterfactual was measured at (ROADMAP.md:268-270: "1 champ in range, 1
trigger per fight window"). Both are identity multipliers at that seed, so they
add NO credit beyond a single proc on a single champion; a 4s proc cadence in a
6s fight window and a 650-unit AoE around a frontline tank would both support
higher numbers, and deliberately are not claimed. Both are per-call
overridable.

DEFAULT BEHAVIOR IS BYTE-IDENTICAL: ``assume_item_proc_heal`` defaults False
and the function short-circuits to 0.0 before any item is inspected. The live
default-ON flip is operator-gated (mirrors ``assume_max_stacks_omnivamp`` /
``assume_item_revive``).

Keyed by string item_id to match the engine's ``resolved.item_ids`` tuple shape
(strings throughout); int ids are coerced.
"""

from __future__ import annotations

from typing import Iterable


# item_id -> PRE-mitigation self-heal as a fraction of caster BONUS HP, per
# proc, per enemy champion hit. 2.50 (heal multiplier) * 0.03 (bonus-HP damage
# ratio) = 0.075. Both ids share the coefficient - the Arena mirror's passive
# text is identical to the base item's.
_ITEM_PROC_HEAL_BONUS_HP_SCALING: dict[str, float] = {
    "2502":   0.075,  # Unending Despair - Anguish (250% of 3% bonus HP)
    "222502": 0.075,  # Unending Despair (Arena mirror; base nominal)
}


# Assumed victim MAGIC RESIST for converting the proc's PRE-mitigation damage
# into the POST-mitigation value the 250% heal actually keys off. Seeded at the
# sweep-standard tanky target (armor 100 / MR 60 / HP 2500 / bonus HP 1200).
# This is the single modeling assumption in this module; every other number
# here is read straight off the Meraki passive text. Pinned by
# ``AssumedTargetMrPinTests`` so a later pass cannot move it silently, and
# overridable per call via ``item_proc_heal_hp(..., target_mr=...)``.
_ASSUMED_TARGET_MR_FOR_PROC_HEAL: float = 60.0

# Conservative activity seeds - both identity at 1.0. See the module docstring.
_PROC_HEAL_TRIGGERS_PER_FIGHT: float = 1.0
_PROC_HEAL_CHAMPIONS_IN_RANGE: float = 1.0


def _magic_mitigation_factor(target_mr: float) -> float:
    """League's resist -> damage-taken multiplier for the victim's MR.

    Positive resist: ``100 / (100 + mr)``. Negative resist (shred):
    ``2 - 100 / (100 - mr)``. Inlined rather than imported from
    ``ehp._armor_factor`` (``ehp.py:147-157``) because ``ehp`` is this module's
    CONSUMER - importing back into it would be circular. The two must stay in
    agreement; ``TargetMrOverrideTests`` pins the negative-resist branch.
    """
    if target_mr >= 0:
        return 100.0 / (100.0 + target_mr)
    return 2.0 - 100.0 / (100.0 - target_mr)


def item_proc_heal_hp(
    item_ids: Iterable[str | int],
    bonus_hp: float,
    *,
    assume_item_proc_heal: bool = False,
    target_mr: float | None = None,
    triggers_per_fight: float | None = None,
    champions_in_range: float | None = None,
) -> float:
    """Per-fight SELF-heal HP from equipped periodic-proc heal items.

    Returns ``0.0`` - the inert default - whenever ``assume_item_proc_heal`` is
    False, no registered item is equipped, or any input drives the product to
    zero. The caller folds a positive return into ``heal_item_total`` BEFORE
    ``heal_amp_mult`` (Anguish's heal is an ordinary heal and IS amplified by
    Spirit Visage in game), matching the ``rune_heal_hp`` precedent at
    ``ehp.py:1534``.

    UNIQUE-PASSIVE DEDUP: Anguish is flagged ``"unique": true`` in the Meraki
    feed, so the heal is credited exactly ONCE no matter how many registered
    ids appear in ``item_ids`` (a duplicate 2502, or a 2502 + 222502 pair). The
    largest registered coefficient present wins; today both are 0.075, so the
    rule is currently order- and choice-independent.

    Args:
        item_ids: equipped item ids (str or int; coerced to str).
        bonus_hp: caster BONUS health. Clamped at 0 - a malformed champion
            record cannot drive the heal negative.
        assume_item_proc_heal: DEFAULT-OFF master flag. False -> exactly 0.0.
        target_mr: victim magic resist for the post-mitigation step. ``None``
            uses ``_ASSUMED_TARGET_MR_FOR_PROC_HEAL`` (60.0).
        triggers_per_fight: proc count in the modeled fight window. ``None``
            uses ``_PROC_HEAL_TRIGGERS_PER_FIGHT`` (1.0). Clamped at 0.
        champions_in_range: enemy champions inside the 650-unit sap radius per
            proc. ``None`` uses ``_PROC_HEAL_CHAMPIONS_IN_RANGE`` (1.0).
            Clamped at 0.

    Returns:
        Total self-heal HP over the modeled fight window, floored at 0.0.
    """
    if not assume_item_proc_heal:
        return 0.0

    coefficient = 0.0
    for item_id in item_ids:
        scaling = _ITEM_PROC_HEAL_BONUS_HP_SCALING.get(str(item_id))
        if scaling is not None and scaling > coefficient:
            coefficient = scaling
    if coefficient <= 0.0:
        return 0.0

    hp = max(0.0, float(bonus_hp))
    mr = (
        _ASSUMED_TARGET_MR_FOR_PROC_HEAL
        if target_mr is None
        else float(target_mr)
    )
    triggers = max(
        0.0,
        _PROC_HEAL_TRIGGERS_PER_FIGHT
        if triggers_per_fight is None
        else float(triggers_per_fight),
    )
    targets = max(
        0.0,
        _PROC_HEAL_CHAMPIONS_IN_RANGE
        if champions_in_range is None
        else float(champions_in_range),
    )

    per_proc_per_target = coefficient * hp * _magic_mitigation_factor(mr)
    return max(0.0, per_proc_per_target * triggers * targets)
