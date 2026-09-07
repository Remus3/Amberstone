"""Per-item PASSIVE omnivamp registry (max-stacks best-case).

DDragon's structured ``items.json.data[id].stats`` block does NOT carry a
usable omnivamp value - the numeric percent lives inside a tooltip variable
(``<omnivamp>...</omnivamp>``) that the description strips, and Meraki's per-item
``stats.omnivamp`` block is flat ``0.0`` because the omnivamp is a conditional
PASSIVE, not a base stat. So this registry is the canonical engine-side source
for build-time item omnivamp, keyed by item id - the same situation as
``_item_tenacity.py`` / ``_item_ability_haste.py`` (both stats-stripped +
description/effect-text only), and this module mirrors their shape.

Riftmaker (2026-07-10): consumed by ``ehp.compute_ehp`` behind the OPT-IN
``assume_max_stacks_omnivamp`` flag so the EHP SUSTAIN axis credits the build's
omnivamp (``_vamp_heal_pool`` converts the fraction to a per-fight heal that
feeds ``effective_ehp_with_sustain`` / ``sustain_ehp_delta``). This surfaces the
sustain axis ONLY; ``blended_ehp`` is left byte-identical, matching the existing
lifesteal / spellvamp posture. The flag ships DEFAULT-OFF (byte-identical when
False - ``stats["omnivamp"]`` stays absent); the live default-ON flip is
operator-gated.

Values are the MELEE / RANGED omnivamp FRACTIONS at MAXIMUM stacks, the
best-case sustained-DPS convention Riftmaker's ``damage_amp_pct=0.08`` already
uses (its Void Corruption ramps to full over 4s in combat; the omnivamp is
granted only at that max-stack strength). Source magnitude:
``data/daemon_slayer/16.13.1/items_meraki.json`` item 4633 "Void Corruption":
"At maximum stacks, gain {{as|{{rd|10%|6%}} omnivamp}}" -> 10% melee / 6%
ranged. The ``(melee_frac, ranged_frac)`` tuple lets the consumer pick the
branch by the wielder's ``is_ranged`` (base attackrange >= 350, per
``ehp._is_ranged`` / ``_melee_ranged``; RM-123).

Registered ids (each confirmed present in ``data/daemon_slayer/16.13.1/
items.json`` before adding):
  * 4633   - Riftmaker (base).
  * 224633 - Riftmaker (Arena mode-mirror, items.json:9980). Carries the base
    nominal: Meraki keys base ids only (no separate Arena magnitude), and the
    Arena copy shares the identical Void Corruption passive text. This matches
    the ``_item_tenacity.py`` Arena-mirror convention (same-nominal carry).

DROPPED / DEFERRED:
  * 324633 (ARAM mirror) - NOT present in the DS item index; intentionally
    omitted (an item id the engine never resolves would be dead weight).
  * 124633 - not in the item index either; omitted.
  * 2517 Endless Hunger (Feast) - 15% omnivamp is TAKEDOWN-gated for an 8s
    window (transient, kill-conditional), NOT an always-on max-stacks passive.
    DEFERRED (start tight, widen on evidence).
  * 3156 Maw of Malmortius (Lifeline) - 10% omnivamp fires only on a Lifeline
    magic-damage-below-30%-HP proc (conditional burst window). DEFERRED.
  * 447103 Hemomancer's Helm (Scarlet Allegiance) - a threshold CONSUMER of
    omnivamp (grants bonus HP IF lifesteal + omnivamp >= 30%), NOT an omnivamp
    grant. Excluded by definition.

R144 MIRROR-COVERAGE RE-MEASURE (16.14.1, slice C). Re-audited against
``core.daemon_slayer_resolver.name_to_id``, which hands the engine mirror ids
(``224633`` under mode="arena") where a bare-id-only registry would fall
through to a silent 0.0 - the R143 / f7c49de5 defect class. COMPLETE: the
16.14.1 index carries exactly two ids named "Riftmaker" (``4633`` and
``224633``) and both were already registered. The DROPPED ids below were
re-confirmed genuinely ABSENT from the index, so their absence is correct
rather than a gap (compare R143's Forbidden Idol 3114, which likewise has no
mirror and correctly gained none). Both facts are pinned by
``tests/test_r144_mirror_slice_c.py``.

Regeneration on a patch bump: re-scan ``items_meraki.json`` effect text for
``omnivamp}}`` grants that are clean always-on / max-stacks passives (drop the
takedown / proc-gated / consumer entries above), map each to its ``is_ranged``
split, and confirm each id (plus mode mirrors) exists in ``items.json`` before
adding.

Keyed by string item_id to match the engine's ``resolved.item_ids`` tuple
shape (strings throughout).
"""

from __future__ import annotations

from typing import Iterable


# item_id -> (melee_frac, ranged_frac). Fractions in [0.0, 1.0).
_ITEM_OMNIVAMP: dict[str, tuple[float, float]] = {
    "4633":   (0.10, 0.06),  # Riftmaker - Void Corruption (max stacks)
    "224633": (0.10, 0.06),  # Riftmaker (Arena mirror; base nominal)
}


def item_omnivamp_fraction(item_ids: Iterable[str | int], is_ranged: bool) -> float:
    """Summed item PASSIVE omnivamp FRACTION for the build, melee/ranged-picked.

    Returns the total omnivamp fraction (e.g. ``0.10`` for a single melee
    Riftmaker) contributed by the equipped items, selecting each item's melee
    or ranged branch by ``is_ranged``. Items not in the registry contribute 0.
    Duplicate ids stack per occurrence (League stat-stack rules; the build
    planner enforces the inventory cap + unique-passive doctrine separately).
    """
    idx = 1 if is_ranged else 0
    total = 0.0
    for iid in item_ids:
        pair = _ITEM_OMNIVAMP.get(str(iid))
        if pair is not None:
            total += pair[idx]
    return total
