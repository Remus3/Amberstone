"""Per-item cast-triggered self-STASIS survival-window registry, keyed by item id.

This is the ITEM-SIDE lane of the champion
``_passive_survival_window_overrides`` registry. That champion registry is keyed
by ``(champion_id, ability_key, form_index)`` and its
``survival_window_multiplier`` is champion-keyed, so an ITEM can never match it
(exactly the same structural gap the ``_item_revive`` registry fills for the
champion revive registry). This module fills that gap for the survival window: an
item-keyed guaranteed-survival window that composes multiplicatively with any
champion survival window AND with any revive, the same EHP-NUMERATOR shape
``compute_ehp`` already applies to the champion survival window.

A survival window is CAST-TRIGGERED and voids ALL incoming damage for a finite
duration (the wielder is untargetable + invulnerable + in stasis - Zhonya's Time
Stop / Wooglet's Stasis: "unable to move, attack, cast spells, or use items ...
untargetable and invulnerable"). Over the modeled fight that voids a FRACTION of
the incoming damage - a build that can become un-killable for ``window_s`` of a
``fight_window_s`` fight is worth ``(1 + window_s / fight_window_s)`` times its
single-window EHP when the active is up. A NUMERATOR multiplier, capped at the
whole fight, amortized by availability - the item-288 revive shape re-used by the
champion survival window.

Why a NEW registry (not ``_item_revive``): mechanically distinct, exactly the
distinction the champion survival window draws against the champion revive. A
revive is DEATH-TRIGGERED and restores a second HP pool that runs through the
armor/MR curve again (so ``item_revive_max_hp_fraction`` needs a base/total-HP
conversion and the credit folds through NORMAL resists); a survival window is
CAST-TRIGGERED and voids damage outright for its duration (NO resist curve, NO HP
pool - it is a fraction-of-fight avoided). Both land on the EHP NUMERATOR as
``(1 + extra)`` multipliers and compose multiplicatively, but the source value (an
avoided-fight FRACTION vs a restored HP fraction) and the trigger (cast vs death)
differ, so they stay separate item registries under separate flags.

Source magnitude: ``data/daemon_slayer/16.13.1/items_meraki.json`` - Zhonya's
Hourglass (3157) + Seeker's Armguard (2420) share the "Time Stop" active ("Put
yourself in stasis for 2.5 seconds, rendering you untargetable and invulnerable
... but also unable to move, attack, cast spells, or use items"); Wooglet's
Witchcap (228002, Arena-native) carries the identical "Stasis" active. So the
window is a flat 2.5s all-damage void for every registered item.

Registered ids (each confirmed present in the DS item index + Meraki before
adding):
  * 3157   - Zhonya's Hourglass (base).
  * 223157 - Zhonya's Hourglass (Arena mode-mirror). Carries the base nominal:
    the Arena copy shares the identical Time Stop active (same-nominal carry,
    the ``_item_revive`` / ``_item_omnivamp`` Arena-mirror convention).
  * 2420   - Seeker's Armguard (the Zhonya component that keeps the 2.5s Time
    Stop active; no Arena / ARAM mirror of its own in the index).
  * 228002 - Wooglet's Witchcap (Arena-native stasis item; no own 22/32 mirror).

DROPPED / DEFERRED (NOT present in the DS item index - an item id the engine
never resolves would be dead weight, the ``_item_revive`` dropped-mirror
convention):
  * 323157   - Zhonya's ARAM mirror.
  * 222420 / 322420 - Seeker's Armguard Arena / ARAM mirrors.
  * 22228002 / 32228002 - Wooglet's Witchcap map-mirror ids.

DEFAULT BEHAVIOR IS BYTE-IDENTICAL: the ``assume_item_stasis`` seam on
``compute_ehp`` defaults False; with it OFF the multiplier is 1.0 and the EHP
math is unchanged. The live default-ON flip is operator-gated (mirrors
``assume_item_revive`` / ``apply_survival_window``).

Keyed by string item_id to match the engine's ``resolved.item_ids`` tuple shape
(strings throughout).
"""

from __future__ import annotations

from typing import Iterable


# item_id -> guaranteed-survival window duration (seconds). Every registered item
# grants the flat 2.5s Time Stop / Stasis all-damage void.
_ITEM_SURVIVAL_WINDOW: dict[str, float] = {
    "3157":   2.5,  # Zhonya's Hourglass - Time Stop (2.5s stasis)
    "223157": 2.5,  # Zhonya's Hourglass (Arena mirror; base nominal)
    "2420":   2.5,  # Seeker's Armguard - Time Stop (2.5s stasis)
    "228002": 2.5,  # Wooglet's Witchcap (Arena-native stasis; 2.5s)
}


# Operator-tunable midpoint for a CAST-TRIGGERED ITEM STASIS window (the expected
# fraction of the modeled fight in which the active is off-cooldown AND used
# defensively). Mirrors ``_passive_survival_window_overrides._SURVIVAL_WINDOW_ULT_PROB``
# (0.35): a Zhonya-class active is a ~120s-cooldown deployable defensive active -
# up rarely but spans the fight when it fires - the same posture as a long-cooldown
# defensive ULT, so it takes the ult midpoint rather than the higher short-cooldown
# BASIC midpoint. The window DURATION (2.5s) is EXACT from the ability text; only
# this firing midpoint is the assumption. Routing the trigger to a live active-
# cooldown clock is a future (Phase D) consumer job.
_ITEM_STASIS_PROB: float = 0.35


def item_survival_window_fraction(
    item_ids: Iterable[str | int], fight_window_s: float
) -> float:
    """Summed ADDITIVE EHP-numerator fraction from equipped item stasis windows.

    Returns ``sum(min(window_s / fight_window_s, 1.0) * _ITEM_STASIS_PROB)`` over
    the equipped registered items. The caller uses this as ``item_stasis_mult -
    1``: a numerator multiplier ``(1 + fraction)`` on the per-type Effective HP. A
    stasis window voids EVERY damage type uniformly (untargetable + invulnerable to
    everything), so - unlike the item revive - there is NO resist curve and NO
    base/total-HP conversion: the avoided-damage fraction is simply the share of
    the fight the window spans, capped at the whole fight and amortized by
    availability.

    Distinct from ``_item_revive.item_revive_max_hp_fraction``: that is a
    death-triggered second HP POOL folded through NORMAL resists (needs the
    ``base_hp`` / ``total_hp`` arguments); this is a cast-triggered damage-VOID
    fraction (needs only the reference ``fight_window_s``). Both land on the EHP
    numerator and compose multiplicatively.

    Items not in the registry contribute 0. ``fight_window_s <= 0`` falls back to
    the reference 6.0s window (division guard). Duplicate ids stack per occurrence
    (the build planner enforces the inventory cap + unique-passive doctrine
    separately).
    """
    fw = float(fight_window_s) if fight_window_s and fight_window_s > 0 else 6.0
    total = 0.0
    for iid in item_ids:
        window_s = _ITEM_SURVIVAL_WINDOW.get(str(iid))
        if window_s is not None:
            total += min(window_s / fw, 1.0) * _ITEM_STASIS_PROB
    return total
