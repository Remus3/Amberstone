"""RM-101 (2026-07-19) - RUNE-keyed flat per-instance damage-block registry.

The RUNE-SIDE lane of ``_passive_flat_mitigation_overrides.flat_mitigation_hp``.
That registry is keyed by ``champion_id`` and its shape covers exactly this
mechanic - a FLAT NUMBER removed from each incoming damage instance - but a RUNE
can never match a champion key, so Bone Plating earned ZERO EHP. This is the same
structural gap the R132 ``_rune_resist_grants`` registry filled for the resist
axis, and ``_rune_resist_grants.py:55-57`` names 8473 explicitly as REJECTED from
that registry because it is "a flat per-instance damage BLOCK" rather than a
resist add. That rejection note points at the PERCENT registry
(``_passive_mitigation_overrides``); the correct lane is the FLAT sibling
``_passive_flat_mitigation_overrides``, which is what this module extends. The
rejection itself is right - only the lane name in that comment is imprecise.

Ground truth, quoted VERBATIM from ``data/meta_build/ddragon/16.14.1/
runesReforged.json`` (id 8473, longDesc; the shortDesc is byte-identical and
``data/meta/ddragon_runes.json`` carries the same text):

  "After taking damage from an enemy champion, the next 3 spells or attacks you
   receive from them deal 30-60 (based on level) less damage.<br><br>Duration:
   1.5s<br>Cooldown: 55s"

WHY THIS RUNE IS DIFFERENT FROM EVERY CHAMPION SEED - it REPLACES an assumption
instead of adding one. The champion sibling's largest single assumption is
``_ASSUMED_FLAT_DR_INSTANCES = 6.0`` (``_passive_flat_mitigation_overrides.py:92``),
an operator-tunable proxy for the per-instance damage feed the engine does not
have; every champion seed multiplies its flat block by that guess. Bone Plating
STATES its instance count in the rune text - "the next 3 spells or attacks" - so
``_BONE_PLATING_INSTANCES`` is EXACT DDragon, not a midpoint. The count is carried
per entry (``RuneFlatMitigationEntry.instances``) rather than as a module-wide
constant precisely so a stated count can never be conflated with an assumed one.

THE ONE ASSUMPTION THAT REMAINS is ``conditional_probability``, and it is seeded
CONSERVATIVELY at 0.25 - strictly BELOW the engine-wide 0.3 "short defensive
ACTIVE" midpoint (``_passive_resist_overrides._ACTIVE_RESIST_PROB``, adopted
unchanged by ``_rune_resist_grants._RUNE_ACTIVE_RESIST_PROB`` and by the champion
sibling's Leona W seed). The reasoning, in both directions:

  * ABOVE its raw duty cycle (1.5s uptime on a 55s cooldown = 0.027). Bone Plating
    is ENGAGEMENT-SYNCHRONIZED, not uniformly distributed: it arms on the FIRST
    damage taken from an enemy champion, which is the opening instant of the very
    engagement the EHP frame models. Pricing it at its raw duty cycle would credit
    almost nothing for a rune that is, in practice, up at the start of a fight.
    This is the identical argument ``_rune_resist_grants.py:86-97`` makes for
    Aftershock and Unflinching.
  * BELOW the 0.3 short-active midpoint, for three compounding reasons that the
    champion sibling's Leona W seed does NOT carry:
      1. 55s cooldown - at most ONE proc per modeled fight. Leona W re-fires on a
         10-14s cooldown and can land several times in the same window.
      2. "from them" scopes the block to a SINGLE attacker. In the multi-attacker
         teamfight frame the EHP scorers evaluate, most incoming damage is from
         someone else entirely and is not blocked at all. Leona W's ANY term has
         no such attacker scoping.
      3. All 3 instances land only if that one attacker delivers 3 separate
         spells or attacks inside the 1.5s window - the upper end of realistic,
         not the expectation. The stated count 3 is a CAP on realization.
    The instance count stays EXACT at 3.0 (never impute, never shade a stated
    number); the realization shortfall belongs in this probability, which is what
    the field is for in the sibling ("amortizes a cooldown-gated active by its
    expected uptime midpoint", ``_passive_flat_mitigation_overrides.py:119-120``).

0.25 is therefore a documented conservative midpoint, not a guess, and it is
pinned by ``tests/test_rune_flat_mitigation_rm101.py`` with a strict
``< 0.3`` ratchet so a later pass cannot quietly raise it.

AXIS IS ``ANY``: "spells or attacks" is untyped in the rune text, so the block
applies to physical, magical and true damage alike and credits all three EHP
numerators.

NO CAP FIELD: unlike every champion seed in the flat sibling (each carries a
``cap_frac`` for an "up to 50% of the instance" clause), the 16.14.1 Bone Plating
text states NO per-instance cap. The field is therefore ABSENT rather than
defaulted to the sibling's 0.5 - an unstated number stays unstated.

DEFAULT BEHAVIOR IS BYTE-IDENTICAL: ``apply_rune_flat_mitigation`` defaults False
ON THIS FUNCTION, so an un-opted caller - including one that supplies a full rune
page containing 8473 - receives ``(0.0, 0.0, 0.0)`` and every EHP numerator is
unchanged. The flag lives here as well as at the eventual ``compute_ehp`` seam
deliberately, mirroring ``_rune_health_grants.rune_health_grants``
(``_rune_health_grants.py:441-445``): a caller that forgets the outer check still
gets inert output rather than silently live numbers.

The prevented HP folds into the EHP NUMERATOR next to the champion lane's
``flat_mit_*`` terms (``ehp.py:1659-1661``), NOT the denominator - a flat
per-instance block prevents a fixed quantity of post-mitigation damage over a
fight, which behaves like bonus effective HP. The pre-vs-post-mitigation
simplification documented in the champion sibling's module docstring (lines 28-35)
applies here unchanged.

Keyed by string rune_id to match the engine's item-id convention (strings
throughout); integer ids are coerced on lookup.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from ._passive_damage_overrides import _lerp_per_level

# Damage-type axis tokens. Identical strings to the champion sibling's
# (``_passive_flat_mitigation_overrides.py:78-81``) so the two lanes fold into the
# same three EHP numerators through a shared vocabulary; a test pins the parity.
PHYS = "physical"
MAG = "magical"
TRUE = "true"
ANY = "any"
_VALID_TYPES = frozenset((PHYS, MAG, TRUE, ANY))

# Bone Plating's per-level magnitude: "30-60 (based on level)". Built by the
# ENGINE PRIMITIVE rather than transcribed, so the authored values can never drift
# from the convention every other per-level registry uses. ``_lerp_per_level``
# ROUNDS TO 6 PLACES (``_passive_damage_overrides.py:215-220``), so element 12
# (level 13) is 51.176471, NOT the raw 30 + 30*12/17 = 51.17647058823529. Any
# assertion against this magnitude must go through the primitive or the rounded
# literal; a hand-recomputed float will not compare equal.
_BONE_PLATING_FLAT_BY_LEVEL: tuple[float, ...] = _lerp_per_level(30.0, 60.0)

# EXACT, from the rune text ("the next 3 spells or attacks"). NOT an assumption -
# this is the number that lets this registry replace the champion sibling's
# ``_ASSUMED_FLAT_DR_INSTANCES = 6.0`` guess rather than inherit it.
_BONE_PLATING_INSTANCES: float = 3.0

# THE ONE JUDGEMENT CALL. Conservative documented midpoint, strictly below the
# engine-wide 0.3 short-defensive-active value. Full reasoning in the module
# docstring; ratcheted by a ``< 0.3`` assertion in the test file.
_BONE_PLATING_PROB: float = 0.25


@dataclass(frozen=True)
class RuneFlatMitigationEntry:
    """One rune-keyed PER-INSTANCE FLAT-AMOUNT damage block.

    ``terms`` is a tuple of ``(flat_or_per_level_tuple, damage_type)`` pairs -
    the same shape as the champion sibling's ``PassiveFlatMitigationEntry.terms``.
    The first element is a flat amount removed from each damage instance, or a
    per-LEVEL tuple when ``level_scaled``; ``damage_type`` is one of
    ``physical`` / ``magical`` / ``true`` / ``any`` (``any`` credits all three EHP
    axes). The prevented HP contributed by a term is
    ``instances * flat * conditional_probability``.

    ``instances`` is the count of damage instances the block applies to. Unlike
    the champion lane's module-wide ``_ASSUMED_FLAT_DR_INSTANCES`` midpoint, this
    is a PER-ENTRY field so a STATED count (Bone Plating's 3) is never conflated
    with an assumed one. An entry may only carry a stated count here.

    ``level_scaled`` (default False) - set True when a term's flat is an
    18-element per-LEVEL tuple read at ``level - 1`` (clamped), the
    ``_lerp_per_level`` convention. Distinct from the champion sibling's
    ``rank_scaled`` (a 5-element per-ABILITY-RANK tuple): Bone Plating is a rune
    and has no ability rank, only champion level.

    ``conditional_probability`` amortizes a cooldown-gated proc by its expected
    realization over the modeled fight. 1.0 would mean a permanent always-on
    block; no rune in this registry qualifies.

    ``family`` dedups mutually exclusive ids, mirroring the item and rune resist
    registries. Runes have no mirror ids today, so each entry gets its own family;
    the field exists so a future alias cannot silently double-credit.

    NOTE the deliberate ABSENCE of a ``cap_frac`` field: the champion sibling
    carries one for its "up to 50% of the instance" clauses, but the 16.14.1 Bone
    Plating text states no cap, and an unstated number stays unstated.
    """

    terms: tuple[tuple[float | tuple[float, ...], str], ...]
    instances: float
    conditional_probability: float
    level_scaled: bool = False
    family: str = ""
    note: str = ""
    attribute: str = "Rune Flat Mitigation"


_RUNE_FLAT_MITIGATION: dict[str, RuneFlatMitigationEntry] = {
    # 8473 Bone Plating (Resolve, slot 2) - verbatim 16.14.1 longDesc: "After
    # taking damage from an enemy champion, the next 3 spells or attacks you
    # receive from them deal 30-60 (based on level) less damage. Duration: 1.5s
    # Cooldown: 55s". Per-level flat 30->60 on ANY damage type, an EXACT stated 3
    # instances, amortized at the conservative 0.25 single-attacker /
    # once-per-fight midpoint. No cap clause exists in the text, so no cap is
    # modelled.
    "8473": RuneFlatMitigationEntry(
        terms=((_BONE_PLATING_FLAT_BY_LEVEL, ANY),),
        instances=_BONE_PLATING_INSTANCES,
        conditional_probability=_BONE_PLATING_PROB,
        level_scaled=True,
        family="bone_plating",
        note=(
            "Bone Plating: 'After taking damage from an enemy champion, the next "
            "3 spells or attacks you receive from them deal 30-60 (based on "
            "level) less damage. Duration: 1.5s Cooldown: 55s'; per-level flat "
            "30-60 ANY via _lerp_per_level; instances 3 STATED (not the champion "
            "lane's assumed 6); 55s cooldown + single-attacker 'from them' "
            "scoping amortized at the conservative 0.25 midpoint; no cap clause "
            "in the text so none modelled"
        ),
        attribute="Bone Plating",
    ),
}

__all__ = [
    "RuneFlatMitigationEntry",
    "_RUNE_FLAT_MITIGATION",
    "rune_flat_mitigation_hp",
    "PHYS",
    "MAG",
    "TRUE",
    "ANY",
]


def _value_at_level(
    flat: float | tuple[float, ...], level: int, level_scaled: bool
) -> float:
    """Resolve a term's flat amount at a champion level.

    A ``level_scaled`` term carries an 18-element per-LEVEL tuple read at
    ``level - 1``, CLAMPED to the tuple bounds so an out-of-range caller yields
    the nearest endpoint rather than raising or extrapolating - the
    ``rank_at_level('P', level)`` convention ``_lerp_per_level`` is built for
    (``_passive_damage_overrides.py:202-220``) and the same clamping semantics as
    ``_rune_health_grants.stacks_at_level`` (``_rune_health_grants.py:312-324``).
    A non-level-scaled term is its float.
    """
    if level_scaled and isinstance(flat, (tuple, list)):
        if not flat:
            return 0.0
        idx = max(0, min(int(level) - 1, len(flat) - 1))
        return float(flat[idx])
    if isinstance(flat, (tuple, list)):
        # Defensive: a tuple on a non-level_scaled entry resolves at its first.
        return float(flat[0]) if flat else 0.0
    return float(flat)


def rune_flat_mitigation_hp(
    rune_ids: Iterable[str | int],
    *,
    level: int,
    apply_rune_flat_mitigation: bool = False,
) -> tuple[float, float, float]:
    """Return ``(phys, mag, true)`` prevented-damage HP from rune flat DR.

    The RUNE twin of ``_passive_flat_mitigation_overrides.flat_mitigation_hp``,
    with the identical return contract: each value is an EHP NUMERATOR term
    measured in prevented post-mitigation HP, which the caller ADDS to the
    matching per-type numerator next to the champion lane's ``flat_mit_*``
    (``ehp.py:1884-1886``). More prevented damage = a larger numerator = larger
    EHP = the correct "less damage taken -> survives more" direction. Nothing here
    touches the denominator - this registry grants no resists.

    For each registered rune id and each ``(flat, type)`` term the prevented HP is
    ``entry.instances * flat * entry.conditional_probability``, added to the
    matching axis (an ``any`` term adds to all three). ``level`` indexes the
    per-level magnitude tuple and is clamped to ``[1, 18]`` in effect.

    ``apply_rune_flat_mitigation`` is the DEFAULT-OFF seam gate: False (the
    default) returns ``(0.0, 0.0, 0.0)`` for ANY rune page, so an un-opted caller
    - including one that supplies a page containing 8473 - is byte-identical. The
    flag lives on this function as well as at the eventual ``compute_ehp`` seam
    deliberately, mirroring ``_rune_health_grants.rune_health_grants``: a caller
    that forgets the outer check still gets inert output.

    A ``family`` tag is credited at most once, so a duplicated or aliased id
    cannot double-credit; different families sum. Runes outside the seeded
    allowlist contribute 0.0 by construction, so every offensive keystone and
    every non-blocking Resolve rune returns zero.
    """
    phys = mag = true = 0.0
    if not apply_rune_flat_mitigation:
        return phys, mag, true
    lvl = int(level)
    seen_families: set[str] = set()
    for rid in rune_ids:
        entry = _RUNE_FLAT_MITIGATION.get(str(rid))
        if entry is None:
            continue
        if entry.family and entry.family in seen_families:
            continue
        seen_families.add(entry.family)
        instances = float(entry.instances)
        prob = float(entry.conditional_probability)
        for (flat_raw, dtype) in entry.terms:
            if dtype not in _VALID_TYPES:
                continue
            flat = _value_at_level(flat_raw, lvl, entry.level_scaled)
            prevented = instances * flat * prob
            if prevented <= 0.0:
                continue
            if dtype in (PHYS, ANY):
                phys += prevented
            if dtype in (MAG, ANY):
                mag += prevented
            if dtype in (TRUE, ANY):
                true += prevented
    return phys, mag, true
