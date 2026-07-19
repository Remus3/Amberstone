"""RUNE-side Heal/Shield Power (HSP) registry, keyed by rune id (R136-S2).

The RUNE-SIDE lane of the item-keyed ``_hsp_amp.sum_wielder_hsp_pct``. That
helper (``_hsp_amp.py:23``) sums ``heal_shield_amp_pct`` across EQUIPPED ITEMS
ONLY - it reads the curated ``enchanter_items.json`` field through
``hps.load_default_formulas`` and looks each contribution up BY ITEM ID. A rune
has no item id, so it can never reach that lookup no matter what it grants. 8453
Revitalize grants flat Heal and Shield Power and therefore earned ZERO, the exact
structural gap this registry fills - the same reasoning the sibling
``_rune_resist_grants`` registry carries for the resist axis.

The DDragon 16.14.1 ``runesReforged.json`` longDesc, quoted VERBATIM:

  * 8453 Revitalize: "Gain 5% Heal and Shield Power.<br><br>Heals and shields you
    cast or receive are 10% stronger on targets below 40% health."

ONLY THE FIRST SENTENCE IS MODELLED. The second sentence ("10% stronger on
targets below 40% health") was READ AND DELIBERATELY REJECTED, not overlooked: it
is a TARGET-STATE CONDITIONAL, and the DS conditional-target-state arc is
operator-CLOSED (live target-state plumbing was permanently shelved). Crediting
it would require knowing the heal target's current health fraction at scoring
time, which the engine does not carry. The flat 5% half is unconditional and
always-on, so it is exact rather than amortized - this registry needs NO firing
midpoint and NO probability field, unlike ``_rune_resist_grants``.

UNITS ARE A FRACTION, NOT A PERCENT: 5% is stored as 0.05, matching the
``heal_shield_amp_pct`` convention in ``enchanter_items.json`` (Redemption 10% ->
0.10). This is what makes the two lanes DIRECTLY ADDITIVE per the real-LoL HSP
model and the "(1 + hsp_pct)" convention documented at ``_hsp_amp.py:27-30``:
Redemption 0.10 + Mikael 0.12 + Revitalize 0.05 = 0.27, never a compounded
1.22 * 1.05. Note this deliberately differs from ``_rune_resist_grants``, which
stores percents (75.0 == 75%) because its consumers are resist magnitudes.

HSP amplifies HEALS AND SHIELDS ONLY. It does NOT amplify vamp (lifesteal /
omnivamp / spellvamp / drain) - the contract stated at ``_hsp_amp.py:5-7``. This
module returns a bare fraction and takes no position on which pools a caller
applies it to; the seam caller must keep the item lane's existing REGEN-only /
ItemShield-only scoping and must not widen it to a vamp pool.

ONE id is SEEDED. This registry is a deliberate ALLOWLIST, not a tree-wide sweep.
A sweep of all 62 current-patch runes found exactly one other mention of the
stat, and it was rejected: 8351 Glacial Augment SCALES ITS SLOW BY the wielder's
HSP ("20% (+90% per 100% Heal and Shield Power)") - it is a CONSUMER of the stat,
not a GRANTER of it, so crediting it here would invert the direction of the term.
Every other Resolve rune grants a different axis entirely (8439 Aftershock / 8429
Conditioning / 8242 Unflinching resists - the ``_rune_resist_grants`` lane; 8446
Demolish tower damage; 8451 Overgrowth max health; 8473 Bone Plating flat damage
block) or heals/shields an ALLY rather than granting the wielder HSP (8463 Font
of Life, 8465 Guardian - the ally-throughput lane ``hps.py`` already owns). Each
was read and rejected rather than overlooked.

FAIL-SOFT, mirroring ``_hsp_amp``: an empty / None rune list, a non-iterable, or
any lookup failure returns 0.0, so the orchestrator's DEFAULT-OFF seam stays
BYTE-IDENTICAL when the flag is off or the page carries no HSP rune.

Keyed by string rune_id to match the engine's id convention (strings throughout);
integer ids are coerced on lookup, and a repeated id is credited at most once
(a rune page cannot carry the same rune twice, so a duplicated or aliased id must
never double-credit - the ``_rune_resist_grants`` ``family`` rationale).
"""

from __future__ import annotations

from typing import Iterable, Optional

# 8453 Revitalize (Resolve, slot 3) - verbatim: "Gain 5% Heal and Shield Power."
# Stored as a FRACTION so it is additive with enchanter_items.json HSP.
REVITALIZE_HSP_PCT: float = 0.05

_RUNE_HSP_PCT: dict[str, float] = {
    "8453": REVITALIZE_HSP_PCT,
}


def sum_rune_hsp_pct(rune_ids: Optional[Iterable[str | int]]) -> float:
    """Sum flat Heal/Shield Power across the wielder's runes (additive, fail-soft).

    Additive with the item-side ``_hsp_amp.sum_wielder_hsp_pct`` per the real-LoL
    HSP model - the caller sums the two lanes and applies a single
    ``(1 + hsp_pct)`` factor (Redemption 0.10 + Mikael 0.12 + Revitalize 0.05 =
    0.27). Runes not in the registry contribute 0.0, so a full offensive page and
    every non-HSP Resolve rune return 0.0 by construction.

    Only the UNCONDITIONAL half of Revitalize is credited; its below-40%-health
    amplifier is target-state conditional and is deliberately not modelled (see
    the module docstring). A repeated id is credited once. Returns 0.0 on an
    empty / None / non-iterable argument or any lookup failure - the seam caller
    gates on its DEFAULT-OFF flag, so a 0.0 return is byte-identical.
    """
    if not rune_ids:
        return 0.0
    try:
        seen: set[str] = set()
        total = 0.0
        for rid in rune_ids:
            if rid is None:
                continue
            key = str(rid)
            if not key or key in seen:
                continue
            seen.add(key)
            total += _RUNE_HSP_PCT.get(key, 0.0)
        return total
    except Exception:
        return 0.0
