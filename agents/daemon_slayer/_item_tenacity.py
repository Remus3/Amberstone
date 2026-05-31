"""Per-item flat Tenacity registry.

DDragon's structured ``items.json.data[id].stats`` block does NOT carry a
tenacity stat key (verified at 16.11.1: every tenacity-granting item has an
EMPTY stats-tenacity key); the numeric value lives inside the localized
description text as ``<attention>N%</attention> Tenacity``. Meraki bulk strips
per-item stats too. So this registry is the canonical engine-side source for
build tenacity - the exact same situation as ``_item_ability_haste.py`` (AH is
also stats-stripped + description-only), and this module mirrors its shape.

Item 236 (ENGINE 1.71.0 -> 1.72.0): consumed by ``ehp.compute_ehp`` behind the
OPT-IN ``apply_build_tenacity`` flag so the ``cc_blended_ehp`` CC-lockdown
discount credits the build's tenacity (tenacity shortens the enemy CC the
caster eats -> larger CC-adjusted EHP). This is what makes the
``rank_items_by_ehp(score_by="cc_blended")`` mode genuinely build-DEPENDENT (a
Mercury's Treads / Sterak's candidate rises vs a heavy-CC comp); without it the
discount is a uniform per-enemy-comp scale that cannot re-rank items.

Values are the NOMINAL flat passive tenacity from each item's 16.11.1
description (parse-verified, not hand-typed). EXCLUDED on purpose:
  * Silvermere Dawn (6035) - the tenacity is a temporary buff from the
    Quicksilver ACTIVE (a CC cleanse), not a passive stat; modeling it as flat
    would overstate.
  * Anathema's Chains (8001) - "reduced Tenacity" is a DEBUFF dealt to the
    marked Nemesis, NOT a self-grant.
  * Elixir of Iron (2138) - a consumable, never a build slot.
Conditional caveats (Wit's End / Sterak's tenacity has melee/near-enemy gates
in-game) are treated as the nominal best-case, matching the AH registry's
"carry the base stat" convention - the gate is a second-order refinement.

Regeneration on a patch bump: re-run the description scan that seeded this
(parse ``<attention>N%</attention>`` adjacent to "Tenacity" in
``items.json.data[id].description``, drop the 3 excluded ids) and diff.

Keyed by string item_id to match the engine's ``resolved.item_ids`` tuple
shape (strings throughout). The 22.../66...-prefixed ids are the Arena
mode-mirror copies (same item, different map id).
"""

from __future__ import annotations

from typing import Iterable


_ITEM_TENACITY: dict[str, float] = {
    "1111": 30.0,    # Jarvan I's (Arena starter)
    "2517": 20.0,    # Endless Hunger (Arena)
    "2525": 25.0,    # Protoplasm Harness (Arena)
    "3053": 20.0,    # Sterak's Gage
    "3091": 20.0,    # Wit's End
    "3111": 30.0,    # Mercury's Treads
    "3173": 30.0,    # Chainlaced Crushers (boots)
    "4012": 30.0,    # Sin Eater (Arena)
    "4013": 30.0,    # Lightning Braid (Arena)
    "222517": 20.0,  # Endless Hunger (Arena mirror)
    "222525": 25.0,  # Protoplasm Harness (Arena mirror)
    "223053": 20.0,  # Sterak's Gage (Arena mirror)
    "223091": 20.0,  # Wit's End (Arena mirror)
    "223111": 30.0,  # Mercury's Treads (Arena mirror)
    "223172": 20.0,  # Zephyr (Arena)
    "447110": 30.0,  # Moonflair Spellblade (Arena)
    "663172": 20.0,  # Zephyr (Arena mirror)
}


def item_tenacity(item_id: str | int) -> float:
    """Return the flat nominal tenacity PERCENT for a single item id, else 0.0."""
    return _ITEM_TENACITY.get(str(item_id), 0.0)


def total_item_tenacity(item_ids: Iterable[str | int]) -> float:
    """Combined tenacity FRACTION in ``[0.0, 1.0)`` for the build.

    League tenacity stacks MULTIPLICATIVELY (each source reduces the REMAINING
    CC duration), not additively: two 30% sources give
    ``1 - 0.7 * 0.7 = 0.51`` (51%), never 60%. Returns the combined fraction
    (e.g. ``0.51``) so a consumer can scale a CC duration by ``(1 - fraction)``.
    Items not in the registry contribute 0 (no reduction). Duplicate ids stack
    per occurrence per League's stat-stack rules (the build planner enforces the
    inventory cap + unique-passive doctrine separately).
    """
    remaining = 1.0
    for iid in item_ids:
        pct = _ITEM_TENACITY.get(str(iid), 0.0)
        if pct:
            remaining *= (1.0 - pct / 100.0)
    return 1.0 - remaining
