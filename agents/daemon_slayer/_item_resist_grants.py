"""Per-item conditional / ramping RESIST-GRANT registry, keyed by item id.

The ITEM-SIDE lane of the champion
``_passive_resist_overrides.resist_grants`` - the FOURTH survivability axis: a
bonus armor / magic-resistance grant that raises the EHP DENOMINATOR DIRECTLY
(added to ``eff_armor`` / ``eff_mr`` BEFORE the ``_armor_factor`` curve), NOT the
numerator. That champion registry is keyed by ``champion_id``, so an ITEM can
never match it - the exact structural gap the ``_item_revive`` /
``_item_survival_window`` / ``_item_spell_shield_overrides`` / ``_item_mana_health``
registries fill for the champion revive / survival-window / spell-shield / mana-HP
axes.

Mechanic: two current-patch (16.13.1 Meraki) item COMBAT passives grant bonus
resists that RAMP to max stacks in combat and are ABSENT from the resolved stat
block. ``build_champion`` folds only the items' FLAT static resists (Jak'Sho
+45/+45, Force of Nature +55 magic resist), NOT the stacked ramp - a live probe
(R105 / LEDGER 850) confirmed the flat statics fold and the ramp earns ZERO EHP,
and corrected the stale ``ehp.py`` header note that claimed "Voidborn ... flows
through build_champion already ... EHP picks them up automatically":

  * Jak'Sho, The Protean (6665 + Arena mirror 226665) "Voidborn Resilience"
    (verbatim ``items_meraki.json`` 16.13.1): "Gain a stack for each second in
    combat with enemy champions, stacking up to 5 times. At maximum stacks,
    increase your bonus armor and bonus magic resistance by 30% until the end of
    combat." -> a PERCENT-of-BONUS resist grant (``armor_pct`` / ``mr_pct`` with
    ``pct_base="bonus"``, the item-268 champion mode). "Bonus" resist = the
    champion's resist ABOVE base-per-level (items + runes + other passives),
    INCLUDING Jak'Sho's own +45/+45 static stat, matching the tooltip.
  * Force of Nature (4401 + Arena mirror 224401) "Steadfast" (verbatim Meraki
    16.13.1): "Taking magic damage from champions generates a stack ... stacking
    up to 8 times ... At maximum stacks, gain 70 bonus magic resistance and 6%
    bonus movement speed." -> a FLAT +70 magic-resistance add (the item-264 mode).
    MAGIC RESIST ONLY (no armor); the move-speed half is not a survivability
    resist. The "Dissipate" magic damage reduction was removed in patch V14.1, so
    there is NO percent magic DR to credit (that would be the separate
    ``_passive_mitigation_overrides`` axis anyway).

Only base + Arena (22xxxx) mirrors resolve in the DS item index
(``data/daemon_slayer/16.13.1/items.json``, 706 items) - no ARAM (32xxxx) mirror
of either exists, so ARAM uses the base id. Each of the four ids was confirmed
present in the index before adding.

Why a NEW registry (not the champion ``_passive_resist_overrides``): that registry
is champion-keyed and ``resist_grants`` iterates ``champion_id``, so an item id can
never match it - the same reasoning the sibling item-side registries carry.

Why NOT ``build_champion`` (unlike the always-on flat static resists): the ramp is
CONDITIONAL - it only reaches full value after ramping to max stacks IN COMBAT
(Jak'Sho 5 seconds in combat, FoN 8 stacks of taking magic damage), so it is not a
static stat the resolved block can carry. This lane credits it as a DEFAULT-OFF
opt-in EHP-DENOMINATOR term, amortized by an at-max-stacks midpoint, keeping the
default EHP math BYTE-IDENTICAL and leaving a future live-flip / a ``build_champion``
promotion a separate operator-gated decision (mirrors the sibling item registries).

Amortization (CONDITIONAL, unlike R105's EXACT deterministic mana -> HP): each grant
realizes its full value only AT MAX STACKS, so it is scaled by
``_ITEM_RESIST_STACK_PROB`` - the expected fraction of the modeled fight spent at
max stacks. The resist MAGNITUDE is EXACT Meraki; only the firing midpoint is the
assumption (the champion ``_ACTIVE_RESIST_PROB`` convention). See that constant's
note for the value rationale.

Unique-passive / family semantics: "Voidborn Resilience" and "Steadfast" are UNIQUE
passives, and in a real build a family's base and its Arena mirror are mutually
exclusive (you never hold 6665 AND 226665). A ``family`` tag dedups within a family
so a synthetic build listing both a base and its mirror credits the grant ONCE
(critical for the percent-of-bonus half, where a naive double-add would inflate);
DIFFERENT families (Jak'Sho vs FoN) are distinct unique passives and correctly sum.

DEFAULT BEHAVIOR IS BYTE-IDENTICAL: the ``apply_item_resist_grants`` seam on
``compute_ehp`` defaults False; with it OFF both grants are 0.0 and every EHP field
is unchanged. The live default-ON flip is operator-gated (mirrors
``apply_item_spell_shield`` / ``apply_item_mana_health`` / ``apply_passive_resist``).

Keyed by string item_id to match the engine's ``resolved.item_ids`` tuple shape
(strings throughout).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

# Operator-tunable amortization midpoint for a ramping item resist grant - the
# expected fraction of the modeled sustained fight spent AT MAX STACKS. Both
# grants realize their full value only after ramping (Jak'Sho: 5 seconds in
# combat; FoN: 8 stacks of taking magic damage from champions), so the first
# seconds of a fight are sub-max; but once reached they HOLD (Jak'Sho "until the
# end of combat"; FoN refreshes on continued magic damage). That makes them MORE
# reliably up than a cooldown-gated active (the champion ``_ACTIVE_RESIST_PROB``
# 0.3) yet not always-on like a permanent innate grant (prob 1.0), so 0.5 - the
# midpoint the form-occupancy grant ``_FORM_OCCUPANCY_PROB`` also uses - is the
# conservative default: the ramp-up is offset by the hold-through-the-fight once
# reached. Documented + conservative; Phase D tunes per-item live (each entry
# carries its own ``conditional_probability`` so the two can decouple).
_ITEM_RESIST_STACK_PROB: float = 0.5


@dataclass(frozen=True)
class ItemResistEntry:
    """One item-keyed conditional bonus armor / magic-resistance grant.

    ``armor`` / ``mr`` are flat bonus values (FoN +70 MR). ``armor_pct`` /
    ``mr_pct`` carry a PERCENT (30.0 == 30%) of the champion's resist selected by
    ``pct_base`` ("total" = base + build, or "bonus" = build delta = total - base)
    - Jak'Sho +30% of BONUS armor + MR. An entry may carry both the flat and the
    percent fields; they sum. ``conditional_probability`` amortizes the ramp by the
    expected at-max-stacks uptime. ``family`` dedups a base + its Arena mirror
    (mutually exclusive in a real build) so the grant is credited once.
    """

    armor: float = 0.0
    mr: float = 0.0
    armor_pct: float = 0.0
    mr_pct: float = 0.0
    pct_base: str = "total"
    conditional_probability: float = _ITEM_RESIST_STACK_PROB
    family: str = ""
    note: str = ""


_ITEM_RESIST_GRANTS: dict[str, ItemResistEntry] = {
    # Jak'Sho, The Protean - Voidborn Resilience: +30% of BONUS armor + BONUS MR
    # at 5 combat stacks, until end of combat (percent-of-bonus mode).
    "6665": ItemResistEntry(
        armor_pct=30.0, mr_pct=30.0, pct_base="bonus", family="jaksho",
        note="Voidborn Resilience: +30% bonus armor + bonus MR at max (5) stacks",
    ),
    "226665": ItemResistEntry(
        armor_pct=30.0, mr_pct=30.0, pct_base="bonus", family="jaksho",
        note="Jak'Sho (Arena mirror; base nominal)",
    ),
    # Force of Nature - Steadfast: +70 flat bonus MR at 8 stacks (MR only).
    "4401": ItemResistEntry(
        mr=70.0, family="fon",
        note="Steadfast: +70 flat bonus MR at max (8) stacks; MR only",
    ),
    "224401": ItemResistEntry(
        mr=70.0, family="fon",
        note="Force of Nature (Arena mirror; base nominal)",
    ),
}


def item_resist_grants(
    item_ids: Iterable[str | int],
    *,
    total_armor: float,
    total_mr: float,
    base_armor: float,
    base_mr: float,
) -> tuple[float, float]:
    """Return the ``(bonus_armor, bonus_mr)`` item-side conditional resist grant.

    ``total_armor`` / ``total_mr`` are the champion's RESOLVED build resists (base
    per-level + items); ``base_armor`` / ``base_mr`` are the base per-level resists
    - the caller passes both from ``compute_ehp`` (the same values the champion
    ``resist_grants`` receives). The percent-of-bonus grant multiplies
    ``max(0.0, total - base)`` (the bonus resist, clamped so a below-base build
    never yields a negative grant); the percent-of-total grant multiplies the
    resolved total. Each grant is scaled by its entry's
    ``conditional_probability`` (the at-max-stacks midpoint).

    A ``family`` tag is credited at most once (a base + its Arena mirror are
    mutually exclusive; crediting both would double-count the percent half).
    Different families sum. Items not in the registry contribute 0. The returned
    values are added to ``eff_armor`` / ``eff_mr`` (the DENOMINATOR) next to the
    champion ``bonus_armor`` / ``bonus_mr``. The default-OFF gating lives in
    ``compute_ehp`` (this function is only called when ``apply_item_resist_grants``
    is True).
    """
    bonus_armor = 0.0
    bonus_mr = 0.0
    seen_families: set[str] = set()
    for iid in item_ids:
        entry = _ITEM_RESIST_GRANTS.get(str(iid))
        if entry is None:
            continue
        if entry.family and entry.family in seen_families:
            continue
        seen_families.add(entry.family)
        prob = entry.conditional_probability
        # Flat add (item-264 mode).
        bonus_armor += entry.armor * prob
        bonus_mr += entry.mr * prob
        # Percent-of-resist add (item-268 mode).
        if entry.armor_pct or entry.mr_pct:
            if entry.pct_base == "bonus":
                res_a = max(0.0, total_armor - base_armor)
                res_m = max(0.0, total_mr - base_mr)
            else:
                res_a = max(0.0, total_armor)
                res_m = max(0.0, total_mr)
            bonus_armor += res_a * (entry.armor_pct / 100.0) * prob
            bonus_mr += res_m * (entry.mr_pct / 100.0) * prob
    return bonus_armor, bonus_mr
