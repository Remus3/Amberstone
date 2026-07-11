"""Per-item SPELL-SHIELD / block-next-ability registry, keyed by item id.

This is the ITEM-SIDE lane of the champion
``_champion_spell_shield_overrides`` registry (the EIGHTH survivability axis).
That champion registry is keyed by ``(champion_id, ability_key, form_index)`` and
its ``champion_spell_shield_fraction`` is champion-keyed, so an ITEM can never
match it - the exact structural gap the ``_item_revive`` / ``_item_survival_window``
registries fill for the champion revive / survival-window axes. This module fills
that gap for the spell-shield sub-axis: an item-keyed block-next-ability shield
that feeds the SAME cc_blended discount the champion spell-shield feeds
(``cc_total *= (1 - frac)`` in ``compute_ehp``), NOT the EHP numerator.

Mechanic: the "Annul" passive (Banshee's Veil / Edge of Night / Verdant Barrier)
grants a SPELL SHIELD that BLOCKS THE NEXT enemy ABILITY, then goes on a ~40s
cooldown (Banshee regenerates its shield after leaving combat; Edge of Night /
Verdant Barrier restart the cooldown on taking champion damage). This is the
item analog of Sivir E / Nocturne W: a single-instance negation of one incoming
hostile effect, gated to one block per cooldown. So - like the champion reactive
spell shield - it lands on the cc_blended CC-pressure discount, amortized by the
reactive block-availability midpoint, NOT on the guaranteed-survival EHP numerator
(that is the ``_item_survival_window`` stasis lane, a cast-triggered all-damage
void, a mechanically different axis).

Why a NEW registry (not ``_item_survival_window``): a spell shield negates ONE
incoming CC INSTANCE (a probabilistic block that shrinks ``enemy_cc_pressure_s``);
a stasis window voids ALL damage of every type for a finite duration (an
avoided-fight FRACTION on the EHP NUMERATOR). Different mechanic, different
consumer, different flag - exactly the distinction the champion registries draw
between ``_champion_spell_shield_overrides`` and ``_passive_survival_window_overrides``.

Source magnitude: ``data/daemon_slayer/16.13.1/items_meraki.json`` (passive name
"Annul", unique) cross-checked against DDragon item text
"Annul - Grants a Spell Shield that blocks the next enemy Ability." A spell shield
blocks the next effect ENTIRELY, so every registered item is a flat 100.0% block
of the one blocked instance; only the amortization midpoint scales it.

Registered ids (each confirmed present in the DS item index + Meraki/DDragon
before adding; adversarial 4th-item hunt returned none missed):
  * 3102   - Banshee's Veil (base).
  * 223102 - Banshee's Veil (Arena mode-mirror; same-nominal carry, the
    ``_item_revive`` / ``_item_survival_window`` Arena-mirror convention).
  * 3814   - Edge of Night (base).
  * 223814 - Edge of Night (Arena mode-mirror; same nominal).
  * 4632   - Verdant Barrier (the Banshee's / Edge of Night component that keeps
    the Annul spell shield; no Arena / ARAM mirror of its own in the index).

DROPPED (NOT present in the DS item index - an item id the engine never resolves
would be dead weight, the ``_item_revive`` dropped-mirror convention):
  * 323102 / 323814 - Banshee's / Edge of Night ARAM mirrors.
  * 224632 / 324632 - Verdant Barrier Arena / ARAM mirrors.

DOCUMENTED EXCLUSIONS (scanned, deliberately NOT seeded - with the reason class,
mirroring the champion registry's exclusion discipline):
  * CLEANSE / CC-REMOVAL actives (Quicksilver Sash 3140, Mercurial Scimitar 3139
    + Arena 223139, Silvermere Dawn 6035 + Arena 226035, Mikael's Blessing 3222 +
    mirrors): "Remove all crowd control debuffs" REMOVES EXISTING CC, it does not
    pre-emptively BLOCK the next instance. A different mechanic (a duration-scale /
    removal, not a single-instance block). The champion registry draws the same
    line against tenacity / immunity.
  * FLAT PER-INSTANCE DAMAGE BLOCK (Guardian's Horn 2051 Undaunted "blocks 15
    damage from attacks and spells"): a flat damage shave every instance, not a
    block of a whole ability.
  * BELOW-HP MAGIC SHIELD (Maw of Malmortius 3156 / Hexdrinker 3155 Lifeline):
    a magic-damage shield triggered under 30% HP, not a pre-emptive ability block.

DEFAULT BEHAVIOR IS BYTE-IDENTICAL: the ``apply_item_spell_shield`` seam on
``compute_ehp`` defaults False; with it OFF the fraction is 0.0 and the CC math is
unchanged. The live default-ON flip is operator-gated (mirrors ``apply_spell_shield``
/ ``assume_item_stasis`` / ``assume_item_revive``).

Keyed by string item_id to match the engine's ``resolved.item_ids`` tuple shape
(strings throughout).
"""

from __future__ import annotations

from typing import Iterable

from ._champion_spell_shield_overrides import _SPELL_SHIELD_REACTIVE_PROB


# item_id -> NOMINAL block share (%) of the ONE blocked ability instance. A spell
# shield negates the next hostile effect ENTIRELY, so every seed is 100.0; the
# field exists for parity with the champion SpellShieldEntry.block_pct + a future
# partial block. The EFFECTIVE contribution is (block_pct / 100) * midpoint.
_ITEM_SPELL_SHIELD: dict[str, float] = {
    "3102":   100.0,  # Banshee's Veil - Annul (block the next enemy ability)
    "223102": 100.0,  # Banshee's Veil (Arena mirror; base nominal)
    "3814":   100.0,  # Edge of Night - Annul (block the next enemy ability)
    "223814": 100.0,  # Edge of Night (Arena mirror; base nominal)
    "4632":   100.0,  # Verdant Barrier (Banshee's / EoN component; Annul)
}


# Operator-tunable amortization midpoint for an ITEM passive Annul spell shield -
# the expected SHARE of the modeled fight's CC pressure the cooldown-gated single
# block removes. Sourced from the CHAMPION reactive spell-shield midpoint
# (``_SPELL_SHIELD_REACTIVE_PROB`` = 0.2): the item Annul is the same block-one
# mechanic as Sivir E / Nocturne W (a reactive negation of the next hostile
# effect, one block per ~40s cooldown). It is aliased (not re-declared) so the
# mapping is explicit, yet the item lane stays INDEPENDENTLY tunable - Phase D can
# decouple it on a live re-rank without touching the champion midpoint. Starting
# at the reactive floor is the conservative posture: an item passive auto-triggers
# on the FIRST hostile ability (CC or not) rather than being aimed at the key
# engage CC, so it cannot systematically exceed a value already accepted as
# non-over-crediting for the better-aimed reactive cast.
_ITEM_SPELL_SHIELD_PROB: float = _SPELL_SHIELD_REACTIVE_PROB


def item_spell_shield_fraction(item_ids: Iterable[str | int]) -> float:
    """Return the combined ITEM spell-shield block FRACTION in ``[0.0, 1.0)``.

    Sums, over every equipped registered item, the effective per-item block
    ``(block_pct / 100) * _ITEM_SPELL_SHIELD_PROB``, and STACKS them
    MULTIPLICATIVELY (each independent block negates a share of the REMAINING CC
    pressure): ``1 - prod(1 - eff_i)``. The caller scales the post-tenacity eaten
    CC by ``(1 - fraction)`` - the SAME cc_blended seam the champion spell-shield
    fraction feeds, so a champion self-shield and an item Annul combine
    multiplicatively (two sequential ``cc_total *=`` products) rather than
    double-counting. The multiplicative form mirrors
    ``champion_spell_shield_fraction``; in practice the Annul unique passive caps a
    real build at one such item, but the general product is kept for parity.

    Items not in the registry contribute 0. This is a CC-pressure discount (a
    block-one negation), NOT an EHP-numerator term - distinct from
    ``_item_survival_window.item_survival_window_fraction`` (a cast-triggered
    all-damage void on the numerator). The default-OFF gating lives in
    ``compute_ehp`` (this function is only called when ``apply_item_spell_shield``
    is True), mirroring ``_item_survival_window``.
    """
    remaining = 1.0
    for iid in item_ids:
        block_pct = _ITEM_SPELL_SHIELD.get(str(iid))
        if block_pct is None:
            continue
        eff = max(0.0, min(1.0, (block_pct / 100.0) * float(_ITEM_SPELL_SHIELD_PROB)))
        if eff:
            remaining *= (1.0 - eff)
    return 1.0 - remaining
