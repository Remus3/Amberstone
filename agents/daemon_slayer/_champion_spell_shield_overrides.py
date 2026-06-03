"""2026-06-03 (GAP 2) - effects-text SPELL-SHIELD / block-one CC registry.

The EIGHTH survivability axis, and the SECOND that feeds the CC-blended discount
rather than an Effective-HP numerator/denominator term. Item 290 (the
champion-innate CC-mitigation registry, the SEVENTH axis) modeled a SELF
*tenacity* / crowd-control-*immunity* ABILITY (Garen W / Olaf R / Malzahar P) as a
multiplicative duration SCALE on every eaten CC, and explicitly deferred this
sibling sub-axis:

    "SPELL-SHIELD / block-one mechanics (Fiora W Riposte's timed damage+CC block,
    Morgana E Black Shield's single-CC absorb): a binary block of ONE incoming CC
    instance, not a duration scale on every CC. This is the separate spell-shield
    sub-axis (a probabilistic CC-INSTANCE negation), deliberately not folded into
    the multiplicative-tenacity seam."

This registry is that sub-axis. The mechanical distinction from item 290's
tenacity is real and is preserved in the code:

  - TENACITY (item 290) scales the DURATION of EVERY CC the caster eats
    (``effective_cc_duration(cc_total, 1 - ten_frac)``). It is a continuous,
    always-on (or window-amortized) duration multiplier.
  - A SPELL-SHIELD here negates ONE incoming CC INSTANCE entirely, gated by the
    ability's COOLDOWN availability. It does not shorten every CC; it eats one and
    is then on cooldown. The amortized contribution is therefore an
    availability-weighted "expected share of the modeled fight's CC pressure that
    a cooldown-gated single block removes", not a per-CC duration scale.

Because the engine carries exactly one CC-pressure quantity (``enemy_cc_pressure_s``
= the post-tenacity sum of enemy CC seconds), both axes ultimately reduce that
same value - but the spell-shield reduction is applied as its OWN distinct
multiplicative discount AFTER the tenacity step in ``compute_ehp``, under its OWN
``apply_spell_shield`` flag, sourced from THIS registry, echoed in its OWN
``EhpResult.spell_shield_frac`` field. The two seams stay architecturally
separable + independently flippable; only the final arithmetic target is shared
(there is no other place for "CC the caster avoids" to land).

The CONSUMER seam is the existing cc_blended path: ``compute_ehp`` gains
``apply_spell_shield`` (default False = byte-identical). When on AND an enemy comp
is supplied, the spell-shield fraction shrinks ``enemy_cc_pressure_s`` (raising
``cc_blended_ehp`` and re-ranking ``rank_items_by_ehp(score_by="cc_blended")`` - a
CC-survival item is worth marginally less to a champion who already negates a CC
instance herself). Route-reachable on ``/ehp`` / ``/rank-tank`` / ``/hybrid`` /
``/rank-bruiser``. The default-on flip stays the Phase D job (a live "saner not
different" re-rank).

DEFAULT BEHAVIOR IS BYTE-IDENTICAL: ``champion_spell_shield_fraction`` returns 0.0
when ``apply_spell_shield`` is False, and the consumer multiplies the eaten CC by
the no-op ``(1 - 0.0)``. Opt-in everywhere (mirrors ``apply_champion_tenacity`` /
``apply_passive_resist`` / ``apply_passive_revive``).

EXHAUSTIVE roster scan (all 171 champs, every ability form whose
effects_descriptions carry a SELF spell-shield / single-CC-instance block - a
mechanic that negates ONE incoming hostile effect rather than scaling CC
duration). The clean self set is:

  - Sivir E Spell Shield: "Active: Sivir gains a spell shield for 1.5 seconds.
    Upon successfully blocking a hostile effect..." The canonical block-the-next-
    ability spell shield (SELF). Reactively popped -> amortized at the reactive
    spell-shield midpoint. Flat (all E ranks block one effect; only the CD scales).
  - Nocturne W Shroud of Darkness: "Active: Nocturne gains a spell shield for 1.5
    seconds. Upon successfully blocking a hostile effect..." Same reactive spell
    shield (SELF). Flat.
  - Fiora W Riposte: "Active: Fiora enters a defensive stance for 0.75 seconds ...
    prevents all incoming non-turret damage, and gains debuff immunity and crowd
    control immunity. ... If Riposte negates at least one hostile immobilizing
    effect, Fiora stuns the target..." A sub-second timed PARRY that blocks ALL CC
    in a tiny pre-timed window (she is unable to act during it). Harder to land
    than a reactive shield -> amortized at the lower parry midpoint. Flat.
  - Morgana E Black Shield (SELF cast): "Active: Morgana grants a shield to the
    target allied champion or herself for 5 seconds, which absorbs incoming magic
    damage and grants crowd control immunity while it holds." Cast on HERSELF, the
    5s magic-damage-gated CC-immunity shield is the widest reliable single-block
    catch window -> amortized at the higher sustained-shield midpoint. Flat. (The
    ALLY cast belongs to the ``_passive_ally_grant_overrides`` ally domain, item
    289; only the self cast is THIS axis.)

Documented EXCLUSIONS (scanned, deliberately NOT seeded - with the reason class):
  - CHAMPION-INNATE TENACITY / CC-IMMUNITY (Garen W, Olaf R, Malzahar P): a
    duration SCALE / sustained immunity, NOT a single-instance block. Item 290's
    ``_champion_cc_mitigation_overrides`` axis. Malzahar P "negates" is a passive
    immunity-until-hit, not a block-one.
  - CAST-BOUND dash / channel CC-immunity (Galio R Hero's Entrance, plus the item
    290 set Sion R / Warwick R / Pantheon R / Kled R+P / Briar R): the immunity
    lasts only during the ability's OWN channel / dash and exists to land the
    engage, not to eat an incoming CC. (Galio R "crowd control immunity for the
    remaining duration, becomes untargetable" is the engage channel.)
  - AREA / PROJECTILE walls (Yasuo W Wind Wall blocks hostile PROJECTILES in a
    line; Shen W Spirit's Refuge blocks BASIC ATTACKS in a zone): an area denial of
    a damage/projectile class, not a self single-CC-instance absorb. Wind Wall also
    eats non-CC projectiles; neither is a personal block-one CC shield.
  - UNTARGETABLE / INVULNERABLE / STASIS windows (Vladimir W, Fizz E, Kayle R,
    Zhonya-class, Gwen W mist, Lissandra R self, etc.): a binary cannot-be-hit /
    cannot-die window = infinite EHP for its duration, the guaranteed-survival
    seam (option 2), a DIFFERENT unmodeled representation - NOT a finite single-CC
    block.
  - ALLY-TARGETED block (Morgana E Black Shield cast on an ALLY): rides a
    teammate, so it belongs to the ``_passive_ally_grant_overrides`` ally domain
    (a different consumer that scores the protected ally), not this SELF registry.
"""
from __future__ import annotations

from dataclasses import dataclass

from ._passive_resist_overrides import _value_at_level

# Operator-tunable amortization midpoints: the expected SHARE of the modeled
# fight's incoming CC pressure that a cooldown-gated single-instance block
# negates. Conservative + documented; Phase D feeds a live availability without
# re-authoring. Parallel to the item-290 CC-immunity midpoints, but these are
# block-AVAILABILITY (one block per cooldown), not duration-uptime.
_SPELL_SHIELD_REACTIVE_PROB = 0.2   # a reactively popped 1.5s spell shield (Sivir E / Nocturne W)
_SPELL_SHIELD_DURATION_PROB = 0.25  # a 5s sustained CC-immunity shield, widest catch (Morgana E self)
_SPELL_SHIELD_PARRY_PROB = 0.12     # a sub-second pre-timed parry, hardest to land (Fiora W)


@dataclass(frozen=True)
class SpellShieldEntry:
    """One hand-authored effects-text SELF spell-shield / block-one CC grant.

    ``block_pct`` is the NOMINAL share of the ONE blocked CC instance the shield
    negates (a flat float, or a per-ABILITY-RANK tuple when ``rank_scaled``). A
    spell shield negates the next hostile effect ENTIRELY, so every seed is 100.0;
    the field exists for schema parity + a future partial block. The EFFECTIVE
    contribution is ``(block_pct / 100) * conditional_probability`` - the amortized
    expected fraction of the fight's CC pressure the cooldown-gated block removes.

    ``conditional_probability`` amortizes the single block by its
    availability+success midpoint (one block per cooldown, weighted by how reliably
    it eats a meaningful CC in the modeled fight).

    ``rank_scaled`` (item 267 convention): ``block_pct`` is a per-ABILITY-RANK
    tuple resolved from champion level via engine-default skill priority.
    ``level_scaled``: a per-CHAMPION-LEVEL tuple read at ``level-1``. Mutually
    exclusive; rank is checked first. (Both seeds are flat at the active patch.)
    """

    block_pct: float | tuple[float, ...] = 100.0
    conditional_probability: float = 1.0
    rank_scaled: bool = False
    level_scaled: bool = False
    attribute: str = "Spell Shield"
    note: str = ""


# (champion_id, key, form_index) -> SpellShieldEntry. Keyed for parity with the
# self heal/shield/DR/resist/revive + ally-grant + cc-mitigation registries.
# Seeded 2026-06-03 against verbatim effects_descriptions at patch 16.11.1.
_CHAMPION_SPELL_SHIELD_OVERRIDES: dict[tuple[str, str, int], SpellShieldEntry] = {
    # Sivir E Spell Shield: "Active: Sivir gains a spell shield for 1.5 seconds.
    # Upon successfully blocking a hostile effect, she heals herself..." Blocks the
    # next hostile effect entirely (SELF) -> amortized at the reactive midpoint.
    ("Sivir", "E", 0): SpellShieldEntry(
        block_pct=100.0,
        conditional_probability=_SPELL_SHIELD_REACTIVE_PROB,
        note="Spell Shield: reactive 1.5s block of the next hostile effect (SELF); amortized at the reactive spell-shield midpoint",
        attribute="Spell Shield",
    ),
    # Nocturne W Shroud of Darkness: "Active: Nocturne gains a spell shield for 1.5
    # seconds. Upon successfully blocking a hostile effect, Shroud of Darkness'
    # bonus attack speed is doubled..." Same reactive single-effect block (SELF).
    ("Nocturne", "W", 0): SpellShieldEntry(
        block_pct=100.0,
        conditional_probability=_SPELL_SHIELD_REACTIVE_PROB,
        note="Shroud of Darkness: reactive 1.5s block of the next hostile effect (SELF); amortized at the reactive spell-shield midpoint",
        attribute="Shroud of Darkness",
    ),
    # Fiora W Riposte: "Active: Fiora enters a defensive stance for 0.75 seconds ...
    # prevents all incoming non-turret damage, and gains ... crowd control immunity.
    # ... If Riposte negates at least one hostile immobilizing effect, Fiora stuns
    # the target..." A sub-second PRE-TIMED parry blocking all CC in a tiny window
    # -> amortized at the lower parry midpoint (harder to land than a reactive pop).
    ("Fiora", "W", 0): SpellShieldEntry(
        block_pct=100.0,
        conditional_probability=_SPELL_SHIELD_PARRY_PROB,
        note="Riposte: 0.75s pre-timed parry blocking all incoming CC+damage (SELF); amortized at the lower parry midpoint",
        attribute="Riposte",
    ),
    # Morgana E Black Shield (SELF cast): "Active: Morgana grants a shield to the
    # target allied champion or herself for 5 seconds, which absorbs incoming magic
    # damage and grants crowd control immunity while it holds." The self cast is a
    # 5s magic-gated CC-immunity shield -> widest single-block catch window,
    # amortized at the higher sustained-shield midpoint. The ALLY cast is the
    # _passive_ally_grant_overrides domain (item 289).
    ("Morgana", "E", 0): SpellShieldEntry(
        block_pct=100.0,
        conditional_probability=_SPELL_SHIELD_DURATION_PROB,
        note="Black Shield (self cast): 5s magic-gated CC-immunity shield; amortized at the sustained-shield midpoint; the ally cast is the ally-grant domain",
        attribute="Black Shield",
    ),
}

__all__ = [
    "SpellShieldEntry",
    "_CHAMPION_SPELL_SHIELD_OVERRIDES",
    "champion_spell_shield_fraction",
    "_SPELL_SHIELD_REACTIVE_PROB",
    "_SPELL_SHIELD_DURATION_PROB",
    "_SPELL_SHIELD_PARRY_PROB",
]


def champion_spell_shield_fraction(
    champion_id: str, level: int, apply_spell_shield: bool
) -> float:
    """Return the combined SPELL-SHIELD block FRACTION in ``[0.0, 1.0)`` for a champ.

    Sums, over every registered self spell-shield matching ``champion_id``, the
    effective per-entry block ``(block_pct(level) / 100) * prob``, and STACKS them
    MULTIPLICATIVELY (each independent block negates a share of the REMAINING CC
    pressure): ``1 - prod(1 - eff_frac_i)``. The result is the combined fraction
    the consumer scales the post-tenacity eaten CC by ``(1 - fraction)``. Each
    seeded champion has exactly one spell-shield, so this is just that entry's
    effective block; the general product form is kept for parity with the tenacity
    registry + a future multi-shield champion.

    NOTE this is a SEPARATE axis from ``champion_cc_tenacity_fraction`` (item 290):
    a spell-shield negates one CC INSTANCE (availability-gated), it does not scale
    every CC's duration. The consumer applies it as its own multiplicative discount
    AFTER the tenacity step, not on the ``effective_cc_duration`` tenacity seam.

    When ``apply_spell_shield`` is False (the default) the fraction is 0.0 -
    byte-identical.
    """
    if not apply_spell_shield:
        return 0.0
    cid = str(champion_id)
    lvl = int(level)
    remaining = 1.0
    for (entry_cid, _key, _form), entry in _CHAMPION_SPELL_SHIELD_OVERRIDES.items():
        if entry_cid != cid:
            continue
        pct = _value_at_level(
            entry.block_pct, lvl, entry.level_scaled,
            key=_key, rank_scaled=entry.rank_scaled,
        )
        eff = max(0.0, min(1.0, (pct / 100.0) * float(entry.conditional_probability)))
        if eff:
            remaining *= (1.0 - eff)
    return 1.0 - remaining
