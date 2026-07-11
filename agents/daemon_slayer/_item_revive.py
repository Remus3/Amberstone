"""Per-item death-triggered self-REVIVE registry, keyed by item id.

This is the ITEM-SIDE lane of the champion ``_passive_revive_overrides``
registry. That champion registry EXPLICITLY excludes item revives (see its
docstring: "ITEM revive (Guardian Angel) is item-side, not a champion passive -
out of this registry's (champion, ability_key, form_index) scope"), and its
``revive_multiplier`` is champion-keyed, so an item can never match it. This
module fills that gap: an item-keyed revive that composes multiplicatively with
any champion self-revive (two independent second lives), the same EHP-NUMERATOR
shape ``compute_ehp`` already applies to the champion revive.

A revive is a death-triggered SECOND HP POOL: the wielder takes fatal damage,
enters a resurrection state, and is restored to a fraction of health, fighting
on. Over a fight that is an Effective-HP NUMERATOR multiplier - a build that can
come back with a second life is worth ``(1 + revived_fraction)`` times its
single-life EHP when the revive is up. Unlike Anivia's Rebirth (which fights
through an egg's modified resists), Guardian Angel has NO egg / bloblet survival
gate - its resurrection is a 4s invulnerable + untargetable channel that always
completes - so the item revive folds through the wielder's NORMAL resists (it
must NOT get the egg_ratio the champion ``revive_extra`` gets).

Source magnitude: ``data/daemon_slayer/16.13.1/items_meraki.json`` item 3026
Rebirth passive (items_meraki.json:15505): "Upon taking lethal damage, enter
resurrection for 4 seconds ... afterwards heal for {{as|50% of '''base'''
health}} ... (300 second cooldown, starts after resurrection ends)." So the
restored pool is 50% of BASE health.

Registered ids (each confirmed present in ``data/daemon_slayer/16.13.1/
items.json`` before adding):
  * 3026   - Guardian Angel (base, items.json:13560).
  * 223026 - Guardian Angel (Arena mode-mirror, items.json:6782). Carries the
    base nominal: the Arena copy shares the identical Rebirth passive text. This
    matches the ``_item_omnivamp.py`` Arena-mirror convention (same-nominal
    carry).

DROPPED / DEFERRED:
  * 323026 (ARAM mirror) - NOT present in the DS item index; intentionally
    omitted (same convention as ``_item_omnivamp.py`` dropping 324633 - an item
    id the engine never resolves would be dead weight).

DEFAULT BEHAVIOR IS BYTE-IDENTICAL: the ``assume_item_revive`` seam on
``compute_ehp`` defaults False; with it OFF the multiplier is 1.0 and the EHP
math is unchanged. The live default-ON flip is operator-gated (mirrors
``assume_max_stacks_omnivamp`` / ``apply_passive_revive``).

Keyed by string item_id to match the engine's ``resolved.item_ids`` tuple shape
(strings throughout).
"""

from __future__ import annotations

from typing import Iterable


# item_id -> revived fraction of BASE HP (Rebirth restores 50% of base health).
_ITEM_REVIVE: dict[str, float] = {
    "3026":   0.50,  # Guardian Angel - Rebirth (50% of base health)
    "223026": 0.50,  # Guardian Angel (Arena mirror; base nominal)
}


# Operator-tunable midpoint for a death-triggered ITEM REVIVE (the expected
# fraction of the modeled fight in which the revive is off-cooldown and
# available). Mirrors ``_passive_revive_overrides._REVIVE_PROB`` (0.4). GA's
# revive is GUARANTEED to complete once triggered (a 4s invulnerable +
# untargetable channel - there is NO egg / bloblet survival gate to fail, unlike
# Anivia / Zac), but its 300s cooldown is LONGER than Anivia's 240s, so the same
# conservative 0.4 "off-cooldown-and-available" midpoint applies: the shorter
# uptime from the longer cooldown offsets the guaranteed completion. Documented +
# conservative; a future (Phase D) consumer feeds a live passive-cooldown clock
# without re-authoring. The restored-health FRACTION (50% of base) is EXACT from
# the ability text; only this availability midpoint is the assumption.
_ITEM_REVIVE_PROB: float = 0.4


def item_revive_max_hp_fraction(
    item_ids: Iterable[str | int], base_hp: float, total_hp: float
) -> float:
    """Summed ADDITIVE EHP-numerator fraction from equipped item revives.

    Returns ``sum(base_frac * (base_hp/total_hp) * _ITEM_REVIVE_PROB)`` over the
    equipped registered items. The caller uses this as ``item_revive_mult - 1``:
    a numerator multiplier ``(1 + fraction)`` on the per-type Effective HP (the
    second life runs through the wielder's NORMAL resists, so its EHP is exactly
    that fraction of the first life's).

    BASE-to-MAX conversion: the revive restores a fraction of BASE HP, but the
    ``revive_extra`` numerator multiplier it feeds scales the FIRST life's EHP,
    which is proportional to TOTAL max HP. So a "50% of base health" revive is
    worth ``0.50 * (base_hp / total_hp)`` of a max-HP life, which this function
    computes before amortizing by ``_ITEM_REVIVE_PROB``. A build with lots of
    bonus HP (base_hp << total_hp) therefore credits a SMALLER numerator fraction
    than a naive max-HP reading would - correct, because GA restores base, not
    max, health.

    Items not in the registry contribute 0. ``total_hp <= 0`` returns 0.0
    (division guard). Duplicate ids stack per occurrence (the build planner
    enforces the inventory cap + unique-passive doctrine separately).
    """
    if total_hp <= 0.0:
        return 0.0
    ratio = float(base_hp) / float(total_hp)
    total = 0.0
    for iid in item_ids:
        base_frac = _ITEM_REVIVE.get(str(iid))
        if base_frac is not None:
            total += base_frac * ratio * _ITEM_REVIVE_PROB
    return total
