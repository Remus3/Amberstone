"""Per-item PERMANENT-HP-PER-PROC registry (Heartsteel "Colossal Consumption").

The ITEM-SIDE lane of the R46 stacking-HP passive axis
(``_passive_health_overrides.passive_health_stack_hp``): a permanent max-HP pool
that ACCRUES OVER THE GAME, expressed as ``procs x hp_per_proc``. Heartsteel
(3084 + Arena mirror 223084) grants permanent bonus health equal to a percent of
its empowered proc damage, and that health earns ZERO EHP credit today -
``_effects_data`` models the damage half only and disclaims the rest in-line.

Why a NEW registry / seam:
  * The champion registry ``_passive_health_overrides`` is EXACTLY this axis but is
    keyed by ``(champion_id, ability_key, form_index)``, so an ITEM can never match
    it - the same structural gap the ``_item_revive`` / ``_item_mana_health`` /
    ``_item_bonus_hp_amp`` registries fill for their axes.
  * The two item-side HP-numerator lanes that DO exist are both EXACT conversions
    of an ALREADY-RESOLVED stat (R105 mana -> HP, R107 item-HP -> HP). Neither can
    express ``procs x hp_per_proc``, because neither takes a level or a proc count.

SOURCING - the coefficient is 10%, and the obvious in-repo source is STALE.
``data/daemon_slayer/16.14.1/items_meraki.json`` says 8%. It is wrong for this
patch: the Meraki body is BYTE-IDENTICAL across all five vendored patch dirs
(16.10.1 .. 16.14.1) despite five separate fetches, i.e. the ``latest`` endpoint is
frozen at content patch 25.15 - the item-side instance of the RM-81 defect. Three
independent live sources read 10% (DDragon ``items.json`` for this same patch dir,
CommunityDragon 16.14, and the LoL wiki), and the wiki's dated ``V26.11`` entry
("conversion to permanent bonus health increased to 10% from 8%") PREDICTS the
exact 8 -> 10 flip observed between the vendored 16.10.1 and 16.11.1 dirs. Meraki's
8% was correct for V25.04 .. V26.10 and is ~11 patches stale. Meraki's 30-second
per-target cooldown is still correct - only the coefficient moved.

Mechanic (verbatim, wiki + DDragon 16.14.1 agreeing): within 700 units of an enemy
champion, generate a stack on them each second, up to 3; your next basic attack
against a 3-stack target consumes them to deal 70 (+6% maximum health) bonus
physical damage on-hit and grants permanent bonus health equal to 10% of that
amount (30 second cooldown PER TARGET).

THE PROC-COUNT PROXY (the data we lack live), mirroring the R46 rationale: the
value of a permanent-HP-per-proc item is ``hp_per_proc * proc_count``, but there is
no live stack feed. The per-proc HP is EXACT (10% of a damage formula both feeds
agree on); the PROC COUNT by champion level is an operator-tunable CONSERVATIVE
curve. ``_ASSUMED_PROCS_BY_LEVEL`` is deliberately LOW and monotonic-non-decreasing
so a flipped-on scorer never OVER-states the pool - the RM-94 Mejai's failure mode
(pinned at MAX stacks, so it ranks #6 for every mage at 2-5% real presence) is the
thing this curve exists to avoid. It is zero below level 7 because a 3000g item is
not realistically completed earlier, and it lands at 8 procs at level 13 - above
the ~5.2 that RM-99 measured as passing Warmog's, well below the ~16.5 that would
take #1 on a tank.

CADENCE DISAGREEMENT - deliberate, and NOT resolved here. The damage half in
``_effects_data`` carries ``every_n_seconds=3.5``, which is neither the 3-second
charge nor the 30-second per-target cooldown; on a single-target rotation it
implies ~8.57x the real proc count. This curve is derived from the REAL 30s
cadence, so the two halves of the Heartsteel model disagree about firing rate.
Correcting ``every_n_seconds`` is a DEFAULT-ON change to already-shipped damage
scoring that would reorder live build orders, so it is deliberately NOT bundled
into this default-OFF numerator add - it is filed as its own operator-gated slice.
Matching a known-wrong cadence to look self-consistent would make this lane wrong
on purpose.

NO SELF-FEEDBACK: the proc damage scales with the caster's max HP, and the credit
IS max HP, so a naive implementation would feed its own output back into its input.
It does not - ``caster_max_hp`` is the RESOLVED build max HP passed by the caller
and the credited HP is never added back before the formula runs (the same
no-self-feedback contract ``_rune_resist_grants`` states and ``ehp.py`` carries as
an invariant in code).

DEFAULT BEHAVIOR IS BYTE-IDENTICAL: the ``assume_item_health_stacks`` seam on
``compute_ehp`` defaults False; with it OFF the credited HP is 0.0 and every EHP
numerator is unchanged. The live default-ON flip is operator-gated. The ``assume_``
prefix (rather than ``apply_``) matches its nearest sibling
``assume_passive_health_stacks`` and marks that the lane rests on a PROXY quantity,
unlike the exact ``apply_item_mana_health`` / ``apply_item_bonus_hp_amp``
conversions. Prefix and PLUMBING are orthogonal: this seam is route-exposed like
the R107 / R136 lanes, deliberately NOT like R46, whose flag never reaches
``rank_items_by_ehp`` or any server route and is therefore unreachable from the
scorer.

Keyed by string item_id to match the engine's ``resolved.item_ids`` tuple shape.
"""

from __future__ import annotations

from typing import Iterable

# item_id -> fraction of the empowered proc's damage granted as PERMANENT bonus
# max health.
_ITEM_HEALTH_STACK_PCT: dict[str, float] = {
    # Heartsteel - "grant you permanent bonus health equal to 10% of that amount"
    # (DDragon 16.14.1 + CommunityDragon 16.14 + wiki; NOT Meraki, which is frozen
    # at 8% - see the SOURCING note above).
    "3084": 0.10,
    # Heartsteel (Arena mirror). PROVENANCE: INHERITED, UNSOURCED. No feed states a
    # coefficient for 223084 - it is absent from Meraki entirely (which carries no
    # Arena mirrors) and its DDragon description omits the percentage. Riot
    # demonstrably retuned this mirror on other axes (700 Health vs 900, 2500g vs
    # 3000g), so if they also retuned the conversion, no available data can detect
    # it. Carries the base nominal per the _item_mana_health / _item_bonus_hp_amp
    # Arena-mirror convention; re-source before any map-30 default-ON flip.
    "223084": 0.10,
}

# Assumed CUMULATIVE proc count by champion level (index 0 = level 1). Deliberately
# LOW and monotonic-non-decreasing; zero below level 7 (a 3000g item is not
# realistically completed earlier). Operator-tunable - this is the single number in
# the lane that is a judgement rather than a source.
_ASSUMED_PROCS_BY_LEVEL: tuple[float, ...] = (
    0, 0, 0, 0, 0, 0, 1, 2, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13,
)


def _proc_damage(caster_max_hp: float) -> float:
    """Empowered Colossal Consumption damage: 70 + 6% of the caster's max health.

    A LOCAL copy of the ``_effects_data`` 3084 ``PeriodicProc.bonus_damage`` lambda,
    deliberately not imported from it (this registry must not depend on the effects
    facade). The two are pinned together by
    ``test_item_health_stack_credit_r137.ProcDamageAgreesWithEffectsDataTests`` so a
    patch that re-sources one and not the other fails loudly rather than silently
    mispricing the stack half.
    """
    return 70.0 + 0.06 * max(0.0, float(caster_max_hp))


def item_health_stack_hp(
    item_ids: Iterable[str | int], caster_max_hp: float, level: int
) -> float:
    """Return the permanent bonus MAX HP accrued from item proc-stack passives.

    ``caster_max_hp`` is the RESOLVED build max health (the proc scales with it);
    ``level`` selects the assumed cumulative proc count and is clamped to 1..18.
    The credit is ``max_registered_pct * assumed_procs * proc_damage(caster_max_hp)``.

    The MAX (not the sum) over the equipped registered items reflects a UNIQUE
    passive over a shared accrual - a synthetic build listing the base plus its
    Arena mirror cannot double-count. In a real DS build at most one Heartsteel is
    ever equipped, so the MAX equals the single match.

    Items not in the registry contribute 0. This is a clean EHP-NUMERATOR flat
    max-HP term (a real pool increase, folded next to ``passive_health_hp`` /
    ``rune_perm_hp`` - the permanent-HP family - NOT next to the exact R105 / R107
    stat conversions). Non-positive ``caster_max_hp`` yields 0.0. The default-OFF
    gating lives in ``compute_ehp`` (this function is only called when
    ``assume_item_health_stacks`` is True).
    """
    hp = max(0.0, float(caster_max_hp))
    if hp <= 0.0:
        return 0.0
    max_pct = 0.0
    for iid in item_ids:
        pct = _ITEM_HEALTH_STACK_PCT.get(str(iid))
        if pct is not None and pct > max_pct:
            max_pct = pct
    if max_pct <= 0.0:
        return 0.0
    idx = min(max(int(level), 1), len(_ASSUMED_PROCS_BY_LEVEL)) - 1
    procs = _ASSUMED_PROCS_BY_LEVEL[idx]
    if procs <= 0.0:
        return 0.0
    return max_pct * procs * _proc_damage(hp)
