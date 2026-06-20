"""2026-06-19 (R7) - per-stack champion self-Attack-Speed passive registry.

A small class of champion INNATE passives grant the champion a per-stack bonus
ATTACK SPEED that ramps to a documented ceiling at max stacks. The DS stat
pipeline (``engine.build_champion``) resolves base + item + rune AS but has no
signal for these innate stacking self-AS buffs, so the auto-attack rotation in
``dps.compute_dps`` under-credits a champion who is at (or near) full passive
stacks in a developed fight - exactly the AA scorer's blind spot.

This module is the registry the AA scorer needed. It is the ATTACK-SPEED sibling
of ``_passive_damage_overrides`` (per-AA on-hit DAMAGE) and the item-effect
``total_conditional_as`` lane (Yun Tal Flurry, an ITEM AS buff): same idea (a
DPS-time AS cross-derivation that does not appear in /stats), but keyed on the
CHAMPION's innate per-stack passive rather than an item.

CONSUMER: ``dps.compute_dps`` ONLY when ``assume_passive_as_stacks=True`` (the
seam wired R7). The default path never imports this module, so the AA DPS stays
byte-identical. The live default-ON flip is operator-gated (see
docs/LIVE_GAME_GATED_SYNC.md; CLAUDE-Settled "per-stack assumed_stacks").

WHY HAND-AUTHORED, not parsed: identical reasoning to the sibling registries - a
text-parser mis-extracts the "X% : Y% (based on level)" endpoints and re-breaks
on each patch's prose rewrite. We author the exact per-stack low/high + max
stacks per ``champion_id`` from the verbatim ``effects_descriptions`` fragment
cited in each entry's ``note``; a future patch re-extract re-verifies the cited
text rather than re-parsing it.

GROUND TRUTH: data/daemon_slayer/16.12.1/champion_abilities.json (Meraki content
patch 25.15) effects_descriptions, verified 2026-06-19. By construction the
documented max bonus AS equals ``per_stack * max_stacks`` for every entry
(Jax 0.125*8=1.0; Irelia 0.25*4=1.0; Ezreal 0.10*5=0.50; Volibear 0.05*5=0.25),
so the full-stack assumption needs no separate clamp.
"""
from __future__ import annotations

from dataclasses import dataclass


def _lerp_by_level(low: float, high: float, level: float) -> float:
    """Linear interpolate ``low`` (level 1) to ``high`` (level 18).

    Standard League "X - Y based on level" 17-step ramp: value at level L is
    ``low + (high - low) * (L - 1) / 17``, with L clamped to 1..18. Mirrors
    ``rune_procs._lerp_by_level`` / ``summoners._lerp_by_level``; kept local so
    the registry has no DPS-path import dependency.
    """
    lvl = 1.0 if level < 1 else (18.0 if level > 18 else float(level))
    return low + (high - low) * (lvl - 1.0) / 17.0


@dataclass(frozen=True)
class PassiveAsEntry:
    """One champion's innate per-stack self-attack-speed passive.

    per_stack_low / per_stack_high: bonus AS FRACTION granted PER STACK at level
      1 / level 18 (Jax 0.05 : 0.125). A FLAT (no level scaling) passive sets
      low == high (Ezreal 0.10 : 0.10).
    max_stacks: the documented stack ceiling. ``per_stack * max_stacks`` equals
      the champion's documented max bonus AS by construction (so the full-stack
      assumption is self-clamping).
    ap_per_stack_per_100: extra bonus AS PER STACK per 100 AP, for the one
      AP-scaled passive (Volibear 0.04); 0.0 for the AP-independent passives.
    note: provenance (the verbatim effects_descriptions fragment + patch).
    """

    per_stack_low: float
    per_stack_high: float
    max_stacks: int
    ap_per_stack_per_100: float = 0.0
    note: str = ""

    def per_stack_at(self, level: float, ap: float = 0.0) -> float:
        """Bonus AS FRACTION from ONE stack at ``level`` with caster ``ap``."""
        base = _lerp_by_level(self.per_stack_low, self.per_stack_high, level)
        return base + self.ap_per_stack_per_100 * (ap / 100.0)


# champion_id (canonical DDragon id) -> PassiveAsEntry. Verified 2026-06-19
# against data/daemon_slayer/16.12.1/champion_abilities.json effects_descriptions
# (Meraki content patch 25.15). Keys are canonical ids (Volibear, not "Volibear
# the Relentless Storm") - dps.compute_dps looks up resolved.champion_id.
_PASSIVE_AS_OVERRIDES: dict[str, PassiveAsEntry] = {
    # Irelia Ionian Fervor: "For each stack, Irelia gains 10% : 25% (based on
    # level) bonus attack speed, up to a maximum of 40% : 100% (based on level)."
    # 4 stacks (10*4=40 .. 25*4=100). The max-stack on-hit magic damage +
    # Unsteady mark are SEPARATE mechanics, not this AS buff.
    "Irelia": PassiveAsEntry(
        per_stack_low=0.10,
        per_stack_high=0.25,
        max_stacks=4,
        note="Ionian Fervor: 10% : 25% (by level) bonus AS/stack, max 4 -> 40% : 100%.",
    ),
    # Jax Relentless Assault: "For each stack, Jax gains 5% : 12.5% (based on
    # level) bonus attack speed, up to a maximum of 40% : 100% (based on level)."
    # 8 stacks (5*8=40 .. 12.5*8=100).
    "Jax": PassiveAsEntry(
        per_stack_low=0.05,
        per_stack_high=0.125,
        max_stacks=8,
        note="Relentless Assault: 5% : 12.5% (by level) bonus AS/stack, max 8 -> 40% : 100%.",
    ),
    # Ezreal Rising Spell Force: "For each stack, Ezreal gains 10% bonus attack
    # speed, up to a maximum of 50%." FLAT (no level scaling), 5 stacks.
    "Ezreal": PassiveAsEntry(
        per_stack_low=0.10,
        per_stack_high=0.10,
        max_stacks=5,
        note="Rising Spell Force: 10% bonus AS/stack (flat), max 5 -> 50%.",
    ),
    # Volibear The Relentless Storm: "For each stack, Volibear gains 5% (+ 4% per
    # 100 AP) bonus attack speed, up to 25% (+ 20% per 100 AP)." FLAT 5% base + AP
    # scaling, 5 stacks (5*5=25 base; 4*5=20 per-100-AP). Lightning Claws (5-stack
    # on-hit magic) is a SEPARATE mechanic, not this AS buff.
    "Volibear": PassiveAsEntry(
        per_stack_low=0.05,
        per_stack_high=0.05,
        max_stacks=5,
        ap_per_stack_per_100=0.04,
        note="The Relentless Storm: (5% + 4% per 100 AP) bonus AS/stack, max 5 -> 25% + 20% per 100 AP.",
    ),
}


def passive_as_entry(champion_id: str) -> PassiveAsEntry | None:
    """Return the PassiveAsEntry for ``champion_id`` or None (no registered passive)."""
    return _PASSIVE_AS_OVERRIDES.get(champion_id)


def passive_as_bonus(
    champion_id: str,
    level: float,
    ap: float = 0.0,
    stack_fraction: float = 1.0,
) -> float:
    """Bonus AS FRACTION credited from a champion's per-stack self-AS passive.

    Returns 0.0 for a champion with no registered passive (every champion the
    seam does not cover). ``stack_fraction`` is the assumed fraction of max
    stacks (1.0 = full stacks, a developed fight); it is clamped to [0, 1] so a
    caller can never assume MORE than the cap. The result is
    ``per_stack_at(level, ap) * max_stacks * stack_fraction``; at fraction 1.0 it
    equals the champion's documented max bonus AS (per_stack * max_stacks ==
    documented max by construction), so no explicit ceiling clamp is needed.

    AP-scaled passives (Volibear) read the caller-supplied ``ap`` (the resolved
    post-amp AP in ``dps.compute_dps``); AP-independent passives ignore it.
    """
    entry = _PASSIVE_AS_OVERRIDES.get(champion_id)
    if entry is None:
        return 0.0
    frac = 0.0 if stack_fraction < 0 else (1.0 if stack_fraction > 1.0 else stack_fraction)
    return entry.per_stack_at(level, ap) * entry.max_stacks * frac
