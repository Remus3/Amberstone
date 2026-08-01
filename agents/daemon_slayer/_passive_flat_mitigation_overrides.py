"""R9 (2026-06-21) - effects-text-only PER-INSTANCE FLAT-AMOUNT damage-reduction.

The MISSING SIBLING of ``_passive_mitigation_overrides.py``. That percent
registry deliberately EXCLUDED (its docstring lines 64-69) the survivability
class that reduces a FLAT NUMBER per damage instance (optionally capped at a
fraction of EACH instance), naming Fizz P, Amumu E, Leona W. R9 adds exactly
that excluded class as a NEW registry - it does NOT re-open or modify the
percent registry (a distinct, separately-keyed sibling).

WHY A SEPARATE REGISTRY (not a new term-type in the percent one): a flat-amount
reduction is hit-count / instance-size dependent, NOT a clean steady-state
multiplier on the damage axis. The percent registry multiplies the EHP
DENOMINATOR (``physical_ehp /= mit_phys``); a flat per-instance reduction
instead prevents a flat block of post-mitigation damage over a fight window,
behaving like bonus effective-HP. So R9 folds into the EHP NUMERATOR, exactly
the way ``ext_flat_hp`` (the enchanter ally flat-HP grant) does at
``ehp.py`` - adding prevented HP at the top of the damage stack, then divided
by the SAME armor/MR curve. This is the correct max-HP-equivalent of prevented
post-mitigation damage.

THE INSTANCE-COUNT PROXY (the data we lack live): per-instance flat DR prevents
``_ASSUMED_FLAT_DR_INSTANCES * flat_per_instance * conditional_probability`` of
damage over a fight. We have no live per-instance damage feed (the same
boundary the percent registry's active amortization and the heal registry's
vamp class hit), so the instance count is an operator-tunable conservative
midpoint - the analog of the percent registry's ``_ACTIVE_DR_PROB``.

PRE-VS-POST-MITIGATION SIMPLIFICATION: Amumu E reduces PRE-mitigation physical;
Fizz P / Leona W reduce the incoming instance (post-source, pre-resist in
League's stack). We fold the prevented amount into the EHP numerator as if it
were prevented POST-mitigation HP (bonus max-HP equivalent). This slightly
OVER-credits a pre-mitigation reducer on a high-resist target (the same flat
block is worth more raw HP after the armor curve already shrank the instance) -
a documented, bounded simplification kept for engine simplicity; the magnitudes
are small (flat 4-50 prevented HP per instance) relative to the EHP pool.

CAP IS NON-BINDING AT REPRESENTATIVE INSTANCE SIZES: each seed caps the flat
reduction at ``cap_frac`` (0.5 = "up to 50% of the instance"). At representative
champion-combat instance sizes (a 100-300 final-damage instance), the flat block
(4-50) is FAR below 50% of the instance, so the cap never binds and is not
modeled in the prevented-HP arithmetic (it would only clip a flat block against
a sub-100-damage instance, which the conservative instance count already
under-weights). The cap is recorded per entry for provenance + a future
instance-size-aware consumer.

DEFAULT BEHAVIOR IS BYTE-IDENTICAL: ``assume_passive_flat_mitigation`` defaults
False; with it OFF ``flat_mitigation_hp`` returns ``(0.0, 0.0, 0.0)`` and every
EHP numerator is unchanged. No live :8860 default scorer flips it on; it is
opt-in everywhere (mirrors ``apply_passive_mitigation`` /
``apply_passive_shield``).

WHY HAND-AUTHORED, not parsed: identical reasoning to the percent / heal /
shield registries - a text-parser mis-extracts and re-breaks on each patch prose
rewrite. Each entry's flat amount + axis + cap come from the verbatim
``effects_descriptions`` (and, for the rank-scaled flat, the parsed
``damage_blocks`` modifier values) cited in its ``note``; a patch re-extract
re-verifies the cited text.

DATA-DRIVEN PER-RANK NOTE (followed the data, not memory): the prompt's
assumption was a flat per-level amount, but the 16.12.1 ground truth shows
Amumu E and Leona W carry a per-RANK flat block (5 ability ranks), not a
per-level (18) curve - the value lives in a ``damage_blocks`` modifier:
  - Amumu E "Physical Damage Reduction" values [5, 7, 9, 11, 13] (ranks 1-5);
    the +3% bonus-armor + +3% bonus-MR sub-terms are OMITTED (no resist ctx on
    this EHP-numerator seam - the same boundary as the percent registry's
    omitted +AP sub-terms).
  - Leona W "Flat Damage Reduction" values [8, 12, 16, 20, 24] (ranks 1-5).
So those two seeds use ``rank_scaled=True`` with a 5-tuple read at the assumed
ability rank (``_ASSUMED_ABILITY_RANK``). Fizz P is a flat innate 4 (the +1% AP
sub-term omitted, same boundary).
"""
from __future__ import annotations

from dataclasses import dataclass

# Damage-type axis tokens for a flat-mitigation term (mirrors the percent
# registry's tokens so the two siblings share the axis vocabulary).
PHYS = "physical"
MAG = "magical"
TRUE = "true"
ANY = "any"
_VALID_TYPES = frozenset((PHYS, MAG, TRUE, ANY))

# Operator-tunable representative count of mitigated damage instances over a
# fight window - the per-instance feed proxy we lack live. A conservative
# documented midpoint: a champion in a multi-second fight eats well more than 6
# damaging instances (basic attacks + spell ticks), but a flat per-instance
# reducer only meaningfully bites the SMALL instances (it is a tiny fraction of a
# big nuke), so 6 under-counts the raw instance volume on purpose to keep the
# prevented-HP credit conservative. The analog of the percent registry's
# ``_ACTIVE_DR_PROB`` midpoint; a future live per-instance consumer replaces it.
_ASSUMED_FLAT_DR_INSTANCES = 6.0

# The ability rank at which a rank-scaled flat block is read (Amumu E / Leona W
# carry a per-rank flat tuple). Mid-game representative: a core defensive spell
# is typically rank 3-5 by a teamfight; rank 4 (index 3) is the conservative
# representative pick (NOT max rank). Clamped to the tuple bounds in
# ``_value_at_level``. Flat (non-rank-scaled) entries ignore it.
_ASSUMED_ABILITY_RANK = 4


@dataclass(frozen=True)
class PassiveFlatMitigationEntry:
    """One hand-authored effects-text-only PER-INSTANCE FLAT-AMOUNT reduction.

    ``terms`` is a tuple of ``(flat_or_per_rank_tuple, damage_type)`` pairs:
    the first element is a flat amount reduced per damage instance (or a
    per-rank tuple when ``rank_scaled``) and ``damage_type`` is one of
    ``physical`` / ``magical`` / ``true`` / ``any`` (``any`` reduces all three
    EHP axes). The prevented HP contributed by a term is
    ``_ASSUMED_FLAT_DR_INSTANCES * flat * conditional_probability`` (added to the
    matching EHP numerator).

    ``cap_frac`` (default 0.5) - the per-instance cap fraction from the effects
    text ("up to 50% of the instance"). Recorded for provenance; NON-BINDING at
    representative instance sizes (see the module docstring) so it is not applied
    in the prevented-HP arithmetic.

    ``conditional_probability`` (default 1.0 = a permanent innate that always
    applies) amortizes a cooldown-gated active by its expected uptime midpoint.

    ``rank_scaled`` (default False) - set True when a term's flat is a per-rank
    tuple read at ``_ASSUMED_ABILITY_RANK`` (Amumu E / Leona W), not a flat
    amount.
    """

    terms: tuple[tuple[float | tuple[float, ...], str], ...]
    cap_frac: float = 0.5
    conditional_probability: float = 1.0
    note: str = ""
    attribute: str = "Passive Flat Mitigation"
    rank_scaled: bool = False


# (champion_id, key, form_index) -> PassiveFlatMitigationEntry. Keyed (champion,
# key, form) for parity with the percent / heal / shield registries;
# ``flat_mitigation_hp`` aggregates ALL entries whose key champion matches.
# Seeded 2026-06-21 against verbatim effects_descriptions (+ the parsed
# damage_blocks flat modifier for the rank-scaled pair) at patch 16.12.1.
_PASSIVE_FLAT_MITIGATION_OVERRIDES: dict[
    tuple[str, str, int], PassiveFlatMitigationEntry
] = {
    # Fizz P Nimble Fighter: "Innate: Fizz is permanently ghosted and reduces
    # every instance of incoming damage by 4 (+ 1% AP), up to a maximum of 50%
    # reduction." FLAT 4 on ANY incoming damage type, permanent innate -> prob
    # 1.0, cap 0.5. The +1% AP sub-term is OMITTED (no AP ctx on this
    # EHP-numerator seam, the same boundary as the percent registry's omitted AP
    # sub-terms). The cleanest flat seed: always-on, build-intrinsic, all types.
    ("Fizz", "P", 0): PassiveFlatMitigationEntry(
        terms=((4.0, ANY),),
        cap_frac=0.5,
        conditional_probability=1.0,
        note=(
            "Nimble Fighter: 'reduces every instance of incoming damage by 4 "
            "(+ 1% AP), up to a maximum of 50% reduction' (flat 4 ANY, innate "
            "always-on; +1% AP omitted; cap 50% of the instance non-binding at "
            "representative instance sizes)"
        ),
        attribute="Nimble Fighter",
    ),
    # Amumu E Tantrum (passive): "Passive: Amumu reduces every instance of
    # pre-mitigation physical damage taken, capped at 50% of the damage
    # instance." The flat amount is the parsed 'Physical Damage Reduction'
    # modifier values [5, 7, 9, 11, 13] (ability ranks 1-5). FLAT per-rank on
    # PHYSICAL, permanent passive -> prob 1.0, cap 0.5. The +3% bonus-armor +3%
    # bonus-MR sub-terms are OMITTED (no resist ctx on this numerator seam). The
    # pre-mitigation->post-mitigation numerator simplification is documented in
    # the module docstring.
    ("Amumu", "E", 0): PassiveFlatMitigationEntry(
        terms=(((5.0, 7.0, 9.0, 11.0, 13.0), PHYS),),
        cap_frac=0.5,
        conditional_probability=1.0,
        note=(
            "Tantrum passive: 'reduces every instance of pre-mitigation physical "
            "damage taken, capped at 50% of the damage instance'; flat per-rank "
            "[5,7,9,11,13] PHYS from the 'Physical Damage Reduction' modifier; "
            "+3% bonus-armor/+3% bonus-MR sub-terms omitted; rank_scaled; cap 50% "
            "non-binding at representative instance sizes"
        ),
        attribute="Tantrum",
        rank_scaled=True,
    ),
    # Leona W Eclipse (active): "Active: Leona raises her guard for 3 seconds,
    # gaining flat damage reduction of up to 50% of the damage instance and bonus
    # armor and bonus magic resistance." The flat amount is the parsed 'Flat
    # Damage Reduction' modifier values [8, 12, 16, 20, 24] (ability ranks 1-5).
    # FLAT per-rank on ANY incoming damage type, active 3s on a 10-14s cooldown ->
    # amortized at the active midpoint, cap 0.5. The bonus-armor / bonus-MR
    # (a RESIST-STAT grant, a different axis) is NOT a flat-DR term - it belongs
    # to the resist registry, not here (the percent registry's Leona-W resist
    # exclusion).
    ("Leona", "W", 0): PassiveFlatMitigationEntry(
        terms=(((8.0, 12.0, 16.0, 20.0, 24.0), ANY),),
        cap_frac=0.5,
        conditional_probability=0.3,
        note=(
            "Eclipse active: 'gaining flat damage reduction of up to 50% of the "
            "damage instance'; flat per-rank [8,12,16,20,24] ANY from the 'Flat "
            "Damage Reduction' modifier; 3s active on a 10-14s cooldown amortized "
            "at the 0.3 midpoint; bonus-armor/MR is a resist-grant axis (not a "
            "flat-DR term); rank_scaled; cap 50% non-binding"
        ),
        attribute="Eclipse",
        rank_scaled=True,
    ),
}

__all__ = [
    "PassiveFlatMitigationEntry",
    "_PASSIVE_FLAT_MITIGATION_OVERRIDES",
    "flat_mitigation_hp",
    "PHYS",
    "MAG",
    "TRUE",
    "ANY",
]


def _value_at_level(
    flat: float | tuple[float, ...], level: int, rank_scaled: bool
) -> float:
    """Resolve a term's flat amount.

    A ``rank_scaled`` term carries a per-rank tuple read at
    ``_ASSUMED_ABILITY_RANK`` (clamped to the tuple bounds) - ``level`` is
    accepted for signature parity with the percent registry's ``_value_at_level``
    but a rank-scaled flat block reads the assumed ABILITY RANK, not champion
    level (an ability rank tops out at 5, distinct from the 1-18 level curve). A
    flat term is its float.
    """
    if rank_scaled and isinstance(flat, (tuple, list)):
        if not flat:
            return 0.0
        idx = max(0, min(int(_ASSUMED_ABILITY_RANK) - 1, len(flat) - 1))
        return float(flat[idx])
    if isinstance(flat, (tuple, list)):
        # Defensive: a tuple on a non-rank_scaled entry resolves at its first.
        return float(flat[0]) if flat else 0.0
    return float(flat)


def flat_mitigation_hp(
    champion_id: str, level: int, assume_passive_flat_mitigation: bool
) -> tuple[float, float, float]:
    """Return ``(phys, mag, true)`` prevented-damage HP from flat per-instance DR.

    For each registered entry matching ``champion_id`` and each ``(flat, type)``
    term, the prevented HP is ``_ASSUMED_FLAT_DR_INSTANCES * flat *
    conditional_probability`` added to the matching axis (an ``any`` term adds to
    all three). When ``assume_passive_flat_mitigation`` is False (the default)
    all three are 0.0 - the EHP numerators are byte-identical.

    The caller adds each value to the matching EHP NUMERATOR (mirrors
    ``ext_flat_hp``): more prevented damage = a larger numerator = larger EHP =
    the correct "less damage taken -> survives more" direction.
    """
    phys = mag = true = 0.0
    if not assume_passive_flat_mitigation:
        return phys, mag, true
    cid = str(champion_id)
    lvl = int(level)
    for (entry_cid, _key, _form), entry in _PASSIVE_FLAT_MITIGATION_OVERRIDES.items():
        if entry_cid != cid:
            continue
        prob = float(entry.conditional_probability)
        for (flat_raw, dtype) in entry.terms:
            if dtype not in _VALID_TYPES:
                continue
            flat = _value_at_level(flat_raw, lvl, entry.rank_scaled)
            prevented = _ASSUMED_FLAT_DR_INSTANCES * flat * prob
            if prevented <= 0.0:
                continue
            if dtype in (PHYS, ANY):
                phys += prevented
            if dtype in (MAG, ANY):
                mag += prevented
            if dtype in (TRUE, ANY):
                true += prevented
    return phys, mag, true
