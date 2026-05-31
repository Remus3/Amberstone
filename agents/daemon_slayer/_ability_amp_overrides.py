"""2026-05-31 (item 239 / GAP 1) - ability self-damage-amp override registry.

Context: ``modifier_blocks.py`` classifies 180 Meraki ``attribute_kind ==
"modifier"`` blocks at 16.11.1 into a heterogeneous taxonomy. One bucket -
``damage_amp_self`` - is a self-amp on the caster's OWN outgoing damage
(Illaoi Q tentacle bonus, Mordekaiser Q isolation, Hwei/Sion max-charge).
The ability-DPS evaluator drops every modifier block from the damage sum
(it sums only ``attribute_kind == "damage"`` blocks), so these self-amps
were INVISIBLE. ``modifier_blocks.py`` foreshadowed this exact seam (its
docstring calls the ``damage_amp_self`` blocks "the conditional-block
schema's job ... OR auto-attack empowerments that belong in the AA
scorer").

This module is that seam, as an OPT-IN registry. It is consumed by
``ability_dps.compute_ability_dps`` ONLY when ``apply_ability_amps=True``;
the default path is byte-identical. No DPS-path module imports
``modifier_blocks`` (it is behavior-neutral) and no conditional-CC entry
covers these spells (the CC roots Mord R / Sion R / Hwei E are different
spells), so there is NO double-count with any existing consumer.

Inclusion principle - ACTIVE (``_ABILITY_AMP_OVERRIDES``, consumed) vs STAGED
(``_STAGED_AMP_CANDIDATES``, documentation-only):
An ability-amp is ACTIVE only when the keyed form carries a same-form
``attribute_kind=="damage"`` block the amp can scale AND that amplified value
is not ALREADY a separate damage block on the same form (no redundant
double-model). At 16.11.1 the clean case is Mordekaiser Q - the isolation
bonus lives only in the modifier, with no separate "isolated" damage block, so
the amp is the only way to surface it. Illaoi Q is kept as the always_on
reference even though its Q form is modifier-only (no same-form damage block,
so the amp is LIVE-INERT - a forward-marker that applies the instant a
same-form damage block ever appears).
The STAGED entries each need a different seam before they can apply correctly:
AurelionSol W (the amp targets the Breath-of-Light Q beam while in flight - a
cross-spell self-state the per-form key cannot express; W f0 has no damage
block); Sion Q and Hwei Q f2 (each form already carries a "Maximum ..." damage
block that represents the charged / isolated ceiling, so an amp on the base
block would double-model the same value - reconcile via block-index routing,
and Hwei's bonus is missing-HP-scaled which needs Gap-2-style coefficient
modeling). They are registered for the handoff record but never consumed.

Two amp bases:

* ``"ability"`` - multiplies THIS spell's own ability damage and IS
  applied inside ``ability_dps``. The amp factor multiplies the
  post-mode / post-build-amp per-cast damage.
* ``"aa"`` - an auto-attack empowerment (Caitlyn W, Fiora E, Jayce W,
  Sivir W, Nidalee Q). Registered for documentation, but INERT in
  ``ability_dps`` - it belongs in the AA scorer (``compute_dps``), a
  separate future seam. ``compute_ability_dps`` skips any ``base != "ability"``
  entry.

Two amp gatings (via ``_amp_multiplier``):

* ``always_on=True`` - the amp is unconditional; factor = 1.0 + addend.
* conditional (``always_on=False``) - the amp gates on an in-game
  condition; factor = 1.0 + probability * addend, where probability is
  the per-condition midpoint from ``_DEFAULT_AMP_PROBABILITY`` (mirrors
  ``cc_conditional._DEFAULT_CONDITION_PROBABILITY`` values verbatim where
  a COND_* tag fits; ``isolation`` has no COND_* tag so it takes the
  shared ~0.5 midpoint).

``amp_per_rank`` is the multiplier ADDEND per spell rank (0-based index by
the spell's current rank, matching ``ability_dps``'s ``rank_at_level``
0-based contract). Values verified against the form's ``raw_modifiers``
and ``effects_descriptions`` at patch 16.11.1.
"""
from __future__ import annotations

from dataclasses import dataclass

# Condition string values. Reuse cc_conditional COND_* tag VALUES verbatim
# where a tag fits; "isolation" has no COND_* analogue so it is a literal.
_COND_ISOLATION = "isolation"          # no cc_conditional COND_* tag; ~0.5 midpoint
_COND_CHANNEL = "channel"              # == cc_conditional.COND_CHANNEL_COMPLETION
_COND_FRENZY_STATE = "frenzy_state"    # == cc_conditional.COND_FRENZY_STATE

# Condition -> probability midpoint. Mirrors cc_conditional values:
#   channel == COND_CHANNEL_COMPLETION (0.5)
#   frenzy_state == COND_FRENZY_STATE (0.4)
#   isolation has no COND_* tag - takes the shared ~0.5 single-condition midpoint.
_DEFAULT_AMP_PROBABILITY: dict[str, float] = {
    _COND_ISOLATION: 0.5,
    _COND_CHANNEL: 0.5,
    _COND_FRENZY_STATE: 0.4,
}


@dataclass(frozen=True)
class AmpEntry:
    """A self-damage-amp on one spell form.

    amp_per_rank: multiplier ADDEND per 0-based spell rank (0.10 -> x1.10).
    base: "ability" (applied in ability_dps) | "aa" (AA scorer; inert here).
    condition: a key in ``_DEFAULT_AMP_PROBABILITY`` (ignored if always_on).
    always_on: True -> unconditional (factor 1+addend); False -> prob-gated.
    note: one-line provenance / uncertainty.
    """

    amp_per_rank: tuple[float, ...]
    base: str
    condition: str = ""
    always_on: bool = False
    note: str = ""


# (champion_id, key, form_index) -> AmpEntry.
# Verified 2026-05-31 against raw_modifiers + effects_descriptions at 16.11.1.
_ABILITY_AMP_OVERRIDES: dict[tuple[str, str, int], AmpEntry] = {
    # Illaoi Q Tentacle Smash: ed[0] "Passive: Tentacle damage is increased"
    # (unconditional). raw_modifiers "Damage Increase" [10,15,20,25,30]%.
    # LIVE-INERT at 16.11.1: the Q form holds only a modifier block (no
    # same-form "damage" block), so there is nothing for the amp to scale on
    # the real form. Retained as the canonical always_on reference + a
    # forward-marker (the amp applies the instant a same-form damage block
    # exists). Illaoi's amplified tentacle damage is a separate P-driven
    # mechanic, not this Q form.
    ("Illaoi", "Q", 0): AmpEntry(
        amp_per_rank=(0.10, 0.15, 0.20, 0.25, 0.30),
        base="ability",
        always_on=True,
        note="Tentacle damage increase, unconditional passive (ed[0]).",
    ),
    # Mordekaiser Q Obliterate: ed[0] "increased if only one enemy is hit".
    # raw_modifiers "Damage Increase" [30,35,40,45,50]%. Isolation-gated.
    ("Mordekaiser", "Q", 0): AmpEntry(
        amp_per_rank=(0.30, 0.35, 0.40, 0.45, 0.50),
        base="ability",
        condition=_COND_ISOLATION,
        note="Q damage increase when only one enemy is hit (ed[0]).",
    ),
    # --- AA-empowerment entries: base="aa" -> DOCUMENTED but INERT in
    # ability_dps (they belong in the AA scorer compute_dps). amp_per_rank is
    # a placeholder shape; it is never read because ability_dps skips base!="ability".
    # Caitlyn W Yordle Snap Trap: the headshot empowerment is on her passive;
    # registered per spec for documentation. AA-empowerment family.
    ("Caitlyn", "W", 0): AmpEntry(
        amp_per_rank=(0.0,),
        base="aa",
        note="AA empowerment family (headshot); AA scorer seam, inert here.",
    ),
    # Fiora E Bladework: ed[0] "empowers her next two basic attacks".
    ("Fiora", "E", 0): AmpEntry(
        amp_per_rank=(0.0,),
        base="aa",
        note="empowers next two basic attacks (ed[0]); AA scorer seam, inert here.",
    ),
    # Jayce W (Hammer) Lightning Field form: ed[0] "empowers his next 3 basic attacks".
    ("Jayce", "W", 1): AmpEntry(
        amp_per_rank=(0.0,),
        base="aa",
        note="empowers next 3 basic attacks (ed[0]); AA scorer seam, inert here.",
    ),
    # Sivir W Ricochet: ed[0] "empowers her crossblade ... her basic attacks".
    ("Sivir", "W", 0): AmpEntry(
        amp_per_rank=(0.0,),
        base="aa",
        note="empowers basic attacks / crossblade bounce (ed[0]); AA scorer seam, inert here.",
    ),
    # Nidalee Q form1 (Human Javelin Toss empowered AA - Takedown): ed[0]
    # "empowers her next basic attack".
    ("Nidalee", "Q", 1): AmpEntry(
        amp_per_rank=(0.0,),
        base="aa",
        note="empowers next basic attack Takedown (ed[0]); AA scorer seam, inert here.",
    ),
}


# (champion_id, key, form_index) -> AmpEntry. DOCUMENTATION ONLY - NOT consumed
# by ``_ability_amp_for`` / the seam. Each needs a different mechanism before it
# can apply without a redundant double-model or a wrong target. Kept here as the
# handoff record of the analyzed-but-deferred ``damage_amp_self`` blocks.
_STAGED_AMP_CANDIDATES: dict[tuple[str, str, int], AmpEntry] = {
    # AurelionSol W Astral Flight: the "Breath of Light Flat Damage Modifier"
    # [108..112]% (x1.08..1.12) amplifies the Q beam (Breath of Light) WHILE in
    # flight - a cross-spell self-state. W f0 itself has no damage block, so the
    # amp cannot be keyed to W. Needs a cross-spell / self-state seam that
    # applies a Q-side multiplier gated on the W (flight) buff being active.
    ("AurelionSol", "W", 0): AmpEntry(
        amp_per_rank=(0.08, 0.09, 0.10, 0.11, 0.12),
        base="ability",
        condition=_COND_FRENZY_STATE,
        note="STAGED: cross-spell - amplifies Q beam during W flight, not W itself.",
    ),
    # Sion Q Decimating Smash: the form already carries a "Maximum Physical
    # Damage" damage block representing the full-charge value; an amp on the
    # "Minimum Physical Damage" block would double-model the same charged
    # ceiling. Reconcile via a block-index / charge-fraction route, not an amp.
    ("Sion", "Q", 0): AmpEntry(
        amp_per_rank=(0.25, 0.5833, 0.75, 0.85, 0.9167),
        base="ability",
        condition=_COND_CHANNEL,
        note="STAGED: 'Maximum Physical Damage' block already models full charge.",
    ),
    # Hwei Q form2 Severing Bolt: the form already carries a "Maximum Damage"
    # block (the isolated / immobilized ceiling) AND the bonus is missing-HP
    # scaled. An amp on the base "Magic Damage" block double-models the ceiling;
    # the missing-HP term needs Gap-2-style coefficient modeling. Reconcile via
    # block-index routing + a missing-HP coefficient, not an amp.
    ("Hwei", "Q", 2): AmpEntry(
        amp_per_rank=(2.00, 2.375, 2.75, 3.125, 3.50),
        base="ability",
        condition=_COND_ISOLATION,
        note="STAGED: 'Maximum Damage' block + missing-HP scaling; reconcile via routing.",
    ),
}


def _ability_amp_for(cid: str, key: str, form_index: int) -> AmpEntry | None:
    """Return the AmpEntry for ``(cid, key, form_index)`` or None.

    Reads only ``_ABILITY_AMP_OVERRIDES`` (the active registry).
    ``_STAGED_AMP_CANDIDATES`` is intentionally NOT consulted.
    """
    return _ABILITY_AMP_OVERRIDES.get((cid, key, form_index))


def _amp_multiplier(
    entry: AmpEntry,
    rank: int,
    prob_map: dict[str, float],
) -> float:
    """Return the per-cast amp factor for ``entry`` at 0-based ``rank``.

    ``always_on`` -> 1.0 + addend. Conditional -> 1.0 + probability * addend
    where probability is ``prob_map[entry.condition]`` (0.0 if the condition
    is unknown, so an unmapped condition is inert rather than a crash).
    The rank index is clamped to the ``amp_per_rank`` tuple bounds.
    """
    ranks = entry.amp_per_rank
    if not ranks:
        return 1.0
    idx = rank if rank >= 0 else 0
    if idx >= len(ranks):
        idx = len(ranks) - 1
    addend = ranks[idx]
    if entry.always_on:
        return 1.0 + addend
    prob = prob_map.get(entry.condition, 0.0)
    return 1.0 + prob * addend
