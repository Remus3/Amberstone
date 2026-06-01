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
C1 (item 246, gap-plan Phase C1) RESOLVED two of the three STAGED entries via
block-index routing (the "Maximum ..." block already holds the ceiling, so an
amp would double-model it - route the block-index instead, never add an amp):

* Sion Q - already resolved BEFORE this seam: ``champion_block_index.json``
  ``{"Q": 2}`` selects the "Maximum Physical Damage" block by default (the s191
  block-index routing predates the Gap-1 amp analysis). No flag-gated route is
  needed; flag on/off is byte-identical. Its STAGED entry was removed.
* Hwei Q form2 - now wired via ``_STAGED_AMP_BLOCK_ROUTES`` below, GATED on
  ``apply_ability_amps`` (default byte-identical). The route points at the
  "Maximum Damage" damage block, which Meraki pre-bakes as a flat value equal to
  block0 * the "Maximum Damage Increase" % - i.e. the full missing-HP ceiling is
  ALREADY in the block, so NO separate Gap-2 missing-HP coefficient is required;
  the route IS the ceiling. Its STAGED entry was removed.

C2x (item 257) RESOLVED the last STAGED entry (AurelionSol W) via the cross-spell
self-state seam below (``_CROSS_SPELL_AMP_OVERRIDES`` + ``CrossSpellAmpEntry``).
The amp targets the Breath-of-Light Q beam while the W flight buff is active;
W f0 has no damage block, so the amp is keyed to the TARGET Q and sourced from
the W rank + W-flight buff state. It is GATED on ``apply_ability_amps`` (default
byte-identical). ``_STAGED_AMP_CANDIDATES`` is now empty.

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
_COND_W_FLIGHT = "w_flight"            # self-state buff window (AurelionSol Astral Flight active)

# Condition -> probability midpoint. Mirrors cc_conditional values:
#   channel == COND_CHANNEL_COMPLETION (0.5)
#   frenzy_state == COND_FRENZY_STATE (0.4)
#   isolation has no COND_* tag - takes the shared ~0.5 single-condition midpoint.
#   w_flight has no COND_* tag - a short self-state dash/flight window; takes the
#     0.4 midpoint (the magnitude the AurelionSol W staged entry always documented).
_DEFAULT_AMP_PROBABILITY: dict[str, float] = {
    _COND_ISOLATION: 0.5,
    _COND_CHANNEL: 0.5,
    _COND_FRENZY_STATE: 0.4,
    _COND_W_FLIGHT: 0.4,
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


@dataclass(frozen=True)
class CrossSpellAmpEntry:
    """A self-state amp where one spell's RANK + active buff scale a DIFFERENT spell.

    The single staged ``damage_amp_self`` block that the per-form ``AmpEntry``
    key cannot express: the amp magnitude lives on a SOURCE spell (its modifier
    block + rank) but it multiplies a TARGET spell's damage, gated on the source
    spell's self-state buff being active. AurelionSol W (Astral Flight) carries a
    "Breath of Light Flat Damage Modifier" [108..112]% that amplifies the Q beam
    while W flight is active; W f0 itself has no damage block, so the amp cannot
    be keyed to W (item 239 STAGED it for this exact reason).

    Keyed by the TARGET spell ``(cid, target_key, target_form_index)``. The
    magnitude is indexed by the SOURCE spell's 0-based rank (resolved at the
    current champion level), and gated on ``condition`` (a self-state buff
    window) via the same ``_DEFAULT_AMP_PROBABILITY`` midpoint machinery as
    ``AmpEntry``. ``always_on`` / ``condition`` / ``amp_per_rank`` are read by
    the shared ``_amp_multiplier``; ``source_key`` is read by the consumer
    (``ability_dps``) to resolve the source rank via ``rank_at_level``.
    """

    source_key: str
    amp_per_rank: tuple[float, ...]
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
# by ``_ability_amp_for`` / the seam. EMPTY at item 257: all three analyzed-but-
# deferred ``damage_amp_self`` candidates have now been resolved -
#   * Sion Q + Hwei Q f2 (item 246 C1) via block-index routing
#     (_STAGED_AMP_BLOCK_ROUTES below) - the "Maximum ..." block already holds
#     the ceiling, so an amp would double-model it.
#   * AurelionSol W (item 257) via the cross-spell self-state seam
#     (_CROSS_SPELL_AMP_OVERRIDES below) - the amp is keyed to the TARGET Q,
#     sourced from the W rank + W-flight buff state.
# Kept as the (now empty) handoff record; a future staged candidate would re-seed it.
_STAGED_AMP_CANDIDATES: dict[tuple[str, str, int], AmpEntry] = {}


# (target_cid, target_key, target_form_index) -> CrossSpellAmpEntry. Consumed by
# ``ability_dps.compute_ability_dps`` ONLY when ``apply_ability_amps=True`` (so
# the default path is byte-identical). item 257 (gap-plan: "AurelionSol W cross-
# spell amp seam, its own session"): a ``damage_amp_self`` block whose magnitude
# lives on a SOURCE spell but multiplies a TARGET spell, gated on the source's
# self-state buff. The amp is keyed by the TARGET spell; the consumer resolves
# the SOURCE rank via ``rank_at_level(source_key, level, ...)`` and applies the
# midpoint-gated multiplier on top of the target spell's per-cast damage. No
# double-count: the source spell (W f0) has no damage block of its own, and the
# target spell (Q) has no ``_ABILITY_AMP_OVERRIDES`` entry.
_CROSS_SPELL_AMP_OVERRIDES: dict[tuple[str, str, int], CrossSpellAmpEntry] = {
    # AurelionSol Q Breath of Light: amplified by W (Astral Flight) while W
    # flight is active. W's "Breath of Light Flat Damage Modifier" raw_modifiers
    # are [108,109,110,111,112]% by W rank (x1.08..1.12 -> addend 0.08..0.12).
    # Source rank = W; gated on the W-flight self-state midpoint (0.4). Verified
    # against AurelionSol W raw_modifiers + effects_descriptions at 16.11.1.
    ("AurelionSol", "Q", 0): CrossSpellAmpEntry(
        source_key="W",
        amp_per_rank=(0.08, 0.09, 0.10, 0.11, 0.12),
        condition=_COND_W_FLIGHT,
        note="W (Astral Flight) flat-damage modifier x1.08..1.12 amplifies the Q "
             "beam while W flight is active; magnitude indexed by W rank.",
    ),
}


# (champion_id, key, form_index) -> damage-block index to ROUTE to, consumed by
# ``ability_dps.compute_ability_dps`` ONLY when ``apply_ability_amps=True`` (so
# the default path is byte-identical). C1 (item 246): a staged candidate whose
# "Maximum ..." damage block already models the charged / isolated ceiling is
# reconciled by routing the block-index (vs the un-amped "first" block), NOT by
# adding an amp that would double-count. The value is a DAMAGE-block index (the
# index into the form's ``attribute_kind=="damage"`` blocks, matching
# ``_select_blocks`` "indexed" semantics), out-of-range clamps to the last.
#
# Sion Q is intentionally ABSENT: champion_block_index.json {Q:2} already routes
# it to the Maximum block by default (flag on/off byte-identical), so no gated
# entry is needed.
_STAGED_AMP_BLOCK_ROUTES: dict[tuple[str, str, int], int] = {
    # Hwei Q form2 Severing Bolt: damage-block 0 "Magic Damage" is the un-amped
    # base; damage-block 1 "Maximum Damage" is the isolated / immobilized + full
    # missing-HP ceiling (Meraki pre-bakes it flat == block0 * "Maximum Damage
    # Increase" %, so no separate missing-HP coefficient is needed).
    ("Hwei", "Q", 2): 1,
}


def _ability_amp_for(cid: str, key: str, form_index: int) -> AmpEntry | None:
    """Return the AmpEntry for ``(cid, key, form_index)`` or None.

    Reads only ``_ABILITY_AMP_OVERRIDES`` (the active registry).
    ``_STAGED_AMP_CANDIDATES`` is intentionally NOT consulted.
    """
    return _ABILITY_AMP_OVERRIDES.get((cid, key, form_index))


def _staged_amp_block_route_for(cid: str, key: str, form_index: int) -> int | None:
    """Return the staged-amp DAMAGE-block route for ``(cid, key, form_index)``.

    Reads only ``_STAGED_AMP_BLOCK_ROUTES``. The caller
    (``ability_dps.compute_ability_dps``) consults this ONLY under
    ``apply_ability_amps=True``; the default path never sees it, keeping the
    default ranking byte-identical. ``None`` means no staged route - honor the
    normal block-strategy / block_index_overrides resolution.
    """
    return _STAGED_AMP_BLOCK_ROUTES.get((cid, key, form_index))


def _cross_spell_amp_for(
    cid: str, target_key: str, target_form_index: int
) -> CrossSpellAmpEntry | None:
    """Return the CrossSpellAmpEntry for the TARGET ``(cid, target_key, form)`` or None.

    Reads only ``_CROSS_SPELL_AMP_OVERRIDES``. The caller
    (``ability_dps.compute_ability_dps``) consults this ONLY under
    ``apply_ability_amps=True``; the default path never sees it, keeping the
    default ranking byte-identical. The caller resolves ``entry.source_key``'s
    rank via ``rank_at_level`` and multiplies ``_amp_multiplier(entry, src_rank,
    ...)`` into the target spell's per-cast amp factor.
    """
    return _CROSS_SPELL_AMP_OVERRIDES.get((cid, target_key, target_form_index))


def _aa_amp_multiplier(
    cid: str,
    rank_for_key,
    prob_map: dict[str, float] = _DEFAULT_AMP_PROBABILITY,
) -> float:
    """Combined AA-empowerment amp factor for champion ``cid``.

    Multiplies the ``_amp_multiplier`` of every ``base == "aa"`` entry keyed to
    ``cid`` (each champion has at most one - Caitlyn W / Fiora E / Jayce W f1 /
    Sivir W / Nidalee Q). ``rank_for_key(key)`` returns the spell's 0-based
    rank. Consumed by ``dps.compute_dps`` ONLY when ``apply_ability_amps=True``
    (the AA-empowerment seam, GAP-1 / gap-plan Phase C2); the default path
    never calls this, so the AA DPS stays byte-identical.

    FORWARD-MARKER: the 5 ``base="aa"`` entries currently carry placeholder
    ``amp_per_rank=(0.0,)`` (the amortized per-champ empowerment magnitude +
    cadence are live-validation work, gap-plan Phase D). So this returns 1.0
    for every champion today - the seam is wired + route-reachable + inert
    until Phase D authors a real value (mirrors the Illaoi Q always_on
    LIVE-INERT reference on the ability side).
    """
    factor = 1.0
    for (c, key, _form), entry in _ABILITY_AMP_OVERRIDES.items():
        if c != cid or entry.base != "aa":
            continue
        factor *= _amp_multiplier(entry, rank_for_key(key), prob_map)
    return factor


def _amp_multiplier(
    entry: AmpEntry | CrossSpellAmpEntry,
    rank: int,
    prob_map: dict[str, float],
) -> float:
    """Return the per-cast amp factor for ``entry`` at 0-based ``rank``.

    Accepts ``AmpEntry`` or ``CrossSpellAmpEntry`` (both carry ``amp_per_rank``
    / ``always_on`` / ``condition``); for the cross-spell entry ``rank`` is the
    SOURCE spell's rank.

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
