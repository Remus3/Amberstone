"""2026-06-02 (GAP 2) - effects-text-only DAMAGE-REDUCTION (mitigation) registry.

The survivability-triad SIBLING of ``_passive_heal_overrides.py`` (items
250-254) and ``_passive_shield_overrides.py`` (item 260), but for the THIRD
survivability axis the engine did not yet model from effects text: a flat
PERCENT damage-reduction multiplier ("takes X% reduced magic damage", "30%
damage reduction"). Heals + shields are SURVIVABILITY THROUGHPUT (they feed
``ability_hps.compute_ability_hps``); damage reduction is the SURVIVABILITY
DENOMINATOR (it feeds ``ehp.compute_ehp`` - a % less damage taken is a strictly
multiplicative boost to Effective HP, on top of the armor/MR curve, exactly the
way League composes a flat-% reduction with resistances).

Why a NEW registry (not heal/shield): damage reduction is NOT an ability
``attribute_kind`` block at all - ``compute_ehp`` reads only ``armor`` / ``mr``
from the resolved stat block. The Meraki pipeline does parse some of these DR
percents into an ``attribute_kind == "modifier"`` block ("Damage Reduction",
"Physical Damage Reduction"), but ``compute_ehp`` never consumes modifier
blocks, so the DR is uncovered regardless of where it parses. This registry adds
the MISSING half: per-damage-type DR multipliers (mit_phys / mit_mag / mit_true)
that ``compute_ehp`` folds into the physical/magical/true EHP DENOMINATORS when
``apply_passive_mitigation=True``. ZERO synthetic block - this is a pure EHP
modifier, so there is no ``to_X_block`` here (unlike the heal/shield registries).

DEFAULT BEHAVIOR IS BYTE-IDENTICAL: ``apply_passive_mitigation`` defaults False;
with it OFF every multiplier is 1.0 and the EHP math is unchanged. No live
:8860 default scorer flips it on; it is opt-in everywhere (mirrors
``apply_passive_shield`` / ``apply_build_tenacity``).

Why HAND-AUTHORED, not parsed: identical reasoning to the heal/damage/shield
registries - a text-parser mis-extracts the endpoints and re-breaks on each
patch prose rewrite. Each entry's percent + damage type come from the verbatim
``effects_descriptions`` fragment cited in its ``note``; a patch re-extract
re-verifies the cited text.

CONDITIONAL / ACTIVE gating (the item-255 ``conditional_probability``
convention): a PERMANENT innate DR (Kassadin P) uses prob 1.0 - it always
applies. A short defensive ACTIVE (Nilah W / K'Sante W / Briar E / Irelia W) is
a cooldown-gated burst the player presses to tank a key window; the registry
ships the EXACT reduction percent but amortizes it by an operator-tunable
``conditional_probability`` midpoint = the expected fraction of a fight's
incoming damage the active is up for (0.3 here, conservative). The amortized
reduction is ``pct/100 * conditional_probability``; e.g. K'Sante W (30% any at
prob 0.3) gives an effective 9% sustained DR -> mit_any 0.91. Routing the active
trigger to a live fight clock is a future (Phase D) consumer job; the percent is
exact, only the firing midpoint is the assumption.

mit math (in ``compute_ehp``): for each entry whose key champion matches, for
each ``(pct, type)`` term, ``frac = (pct/100) * conditional_probability`` and
``mult = 1 - frac`` multiplies the matching axis (physical / magical / true; an
"any" term multiplies all three). The per-axis product is then folded into the
denominator: ``physical_ehp /= mit_phys`` (smaller divisor -> larger EHP -> more
survival, the correct DR direction). Default-OFF leaves all three at 1.0.

``level_scaled`` (default False) - set True for a DR whose percent scales "based
on level" (Irelia W phys 40:70 + magic 20:35). The per-level tuple
(``_lerp_per_level(low, high)``) is read at champion LEVEL (``level-1``). Flat
DRs leave it False.

EXHAUSTED scan (all 171 champs, forms whose effects_descriptions carry a
damage-reduction / "X% reduced ... damage" / "damage reduction" verb): the clean
flat-% MULTIPLICATIVE DR set is exactly these 5 (1 permanent + 4 active).
Documented EXCLUSIONS (scanned, deliberately NOT seeded - with the reason
class):
  - PER-INSTANCE FLAT-AMOUNT reduction (reduces a flat number per hit, OR caps at
    a % of EACH damage instance -> hit-count / instance-size dependent, not a
    clean steady-state multiplier; the same boundary as the heal registry's vamp
    class which needs a per-instance damage feed): Fizz P ("by 4 (+ 1% AP), up to
    a maximum of 50%"), Amumu E ("pre-mitigation physical, capped at 50% of the
    instance"), Leona W ("flat damage reduction of up to 50% of the instance").
  - DR PERCENT NOT IN EFFECTS TEXT (the prose says only "gains damage reduction"
    / "reduces incoming damage" with no number; the value lives ONLY in a parsed
    "Damage Reduction" modifier block - a future "read the modifier block" lift
    could seed these, but the hand-authored registry has no citable percent):
    Alistar R, Gragas W, Warwick E, Bel'Veth E, Garen W active.
  - RESIST-STAT grant (bonus armor / MR, a DIFFERENT axis than a damage
    multiplier; would mis-model as a DR percent + risk a double-count if it were
    in resolved stats): Garen W Courage (0.2 armor + 0.2 MR per stack), Leona W
    bonus armor / MR.
  - AoE-ONLY conditional (AoE is not a damage TYPE the blended EHP models - it
    blends physical / magical / true, not single-target-vs-AoE): Jax E ("25%
    reduced damage from area of effect abilities").
  - IMMUNITY-UNTIL-HIT (a one-instance negation that breaks on the first hit, not
    a sustained multiplier - amortizing 90% would wildly overstate it): Malzahar
    P Void Shift ("90% damage reduction until he takes non-minion damage").
  - PARTIAL-WINDOW + MODIFIED-VALUE-NOT-IN-TEXT (the cited percent applies only to
    a sub-window of the channel; the rest is a parsed "Modified Damage Reduction"
    block with no effects-text value): Master Yi W ("70% for the first 0.5
    seconds, then modified to a reduced amount").
  - DODGE / UNTARGETABLE / spirit-form (not a percent DR): Jax E AA-dodge, Zed R
    / Yone E / Vladimir W untargetable.
  - GREY-HEALTH / GRIT stored-damage barrier (the documented shield-registry
    exclusion class - a bespoke stored-damage mechanic, not a flat multiplier):
    Dr. Mundo W, Sett W (Grit), Mordekaiser W, Rengar W, Tahm Kench E.
  - OFFENSIVE damage-falloff (the ENEMY takes reduced damage from THIS ability -
    a damage modifier on the caster's spell, not self-DR): Ezreal R (minions /
    non-epic monsters 50% less), Xayah Q (secondary targets 50% less), Qiyana Q
    (beyond-first 75%).
  - VAMP / post-mitigation HEAL (matched the "post-mitigation damage" substring
    but is a heal, not a DR; the heal registry's documented exclusion): Aatrox E /
    P, Ambessa R, Aphelios P, Morgana P, Nilah Q, Warwick P / Q, Hecarim W.
"""
from __future__ import annotations

from dataclasses import dataclass

from ._passive_damage_overrides import _lerp_per_level

# Damage-type axis tokens for a mitigation term.
PHYS = "physical"
MAG = "magical"
TRUE = "true"
ANY = "any"
_VALID_TYPES = frozenset((PHYS, MAG, TRUE, ANY))

# Operator-tunable midpoint for a short defensive ACTIVE (the expected fraction
# of a fight's incoming damage the active is up for). Documented + conservative;
# Phase D tunes per-champ live. PERMANENT innate DR uses prob 1.0 (always on).
_ACTIVE_DR_PROB = 0.3

# The ability rank a snapshot-driven per-rank percent-DR block is read at when no
# live per-instance rank feed exists - the analog of the flat registry's
# ``_passive_flat_mitigation_overrides._ASSUMED_ABILITY_RANK`` (kept in sync). A
# rank-4 read (index 3, clamped to the tuple bounds) is the mid-late-game default
# a future live per-instance consumer replaces.
_ASSUMED_ABILITY_RANK = 4


@dataclass(frozen=True)
class PassiveMitigationEntry:
    """One hand-authored effects-text-only flat-% DAMAGE-REDUCTION formula.

    ``terms`` is a tuple of ``(pct, damage_type)`` pairs: ``pct`` is a flat
    percent (or a per-level tuple when ``level_scaled``) and ``damage_type`` is
    one of ``physical`` / ``magical`` / ``true`` / ``any`` (``any`` reduces all
    three EHP axes). Each term multiplies its axis by ``1 - (pct/100 *
    conditional_probability)`` in ``compute_ehp``.

    ``conditional_probability`` (default 1.0 = a permanent innate that always
    applies) amortizes a cooldown-gated active by its expected uptime midpoint.

    ``level_scaled`` (default False) - set True when a term's ``pct`` is a
    per-level tuple read at champion level (``level-1``), not a flat percent
    (Irelia W's level-scaled phys / magic reduction).
    """

    terms: tuple[tuple[float | tuple[float, ...], str], ...]
    conditional_probability: float = 1.0
    note: str = ""
    attribute: str = "Passive Mitigation"
    level_scaled: bool = False


# (champion_id, key, form_index) -> PassiveMitigationEntry. Keyed for parity with
# the heal/shield registries + future per-form gating; ``compute_ehp`` aggregates
# ALL entries whose key champion matches (DR is champion-level for EHP). Seeded
# 2026-06-02 against verbatim effects_descriptions at patch 16.11.1.
_PASSIVE_MITIGATION_OVERRIDES: dict[tuple[str, str, int], PassiveMitigationEntry] = {
    # Kassadin P Void Stone: "Kassadin is permanently ghosted and takes 10%
    # reduced magic damage." PERMANENT flat 10% MAGIC -> prob 1.0. The cleanest
    # seed: true effects-text-only (no parsed block), always-on, build-intrinsic.
    ("Kassadin", "P", 0): PassiveMitigationEntry(
        terms=((10.0, MAG),),
        conditional_probability=1.0,
        note="Void Stone: permanent 10% reduced magic damage taken (innate, always-on)",
        attribute="Void Stone",
    ),
    # Nilah W Slipstream: "during which she becomes ghosted ... reduces all
    # incoming magic damage taken by 25%, and dodges all non-turret basic
    # attacks." 25% MAGIC, active 2.25s on a cooldown -> amortized at the active
    # midpoint. The ally-share (allies she touches gain the same for 1.5s) is not
    # a self-DR term.
    ("Nilah", "W", 0): PassiveMitigationEntry(
        terms=((25.0, MAG),),
        conditional_probability=_ACTIVE_DR_PROB,
        note="Jubilant Veil: 25% reduced magic damage during the 2.25s active; cooldown-gated active amortized at the operator-tunable midpoint",
        attribute="Jubilant Veil",
    ),
    # K'Sante W Path Maker: "During this time, he gains displacement immunity and
    # 30% damage reduction". 30% ALL types, active charge 0.4-1s -> amortized. The
    # All Out bonus (R-form raises it to 75%) is form-gated + not modeled (the
    # Kayn-R / form-gate precedent); the base non-All-Out 30% is seeded.
    ("KSante", "W", 0): PassiveMitigationEntry(
        terms=((30.0, ANY),),
        conditional_probability=_ACTIVE_DR_PROB,
        note="Path Maker: 30% damage reduction (all types) during the W charge; All Out 75% (R-form-gated) not modeled; cooldown-gated active amortized at the midpoint",
        attribute="Path Maker",
    ),
    # Briar E Chilling Scream: "charging for up to 1 second, during which she ...
    # gains 35% damage reduction and heals herself every 0.25 seconds." 35% ALL
    # types, active charge ~1s -> amortized.
    ("Briar", "E", 0): PassiveMitigationEntry(
        terms=((35.0, ANY),),
        conditional_probability=_ACTIVE_DR_PROB,
        note="Chilling Scream: 35% damage reduction (all types) during the up-to-1s charge; cooldown-gated active amortized at the midpoint",
        attribute="Chilling Scream",
    ),
    # Irelia W Defiant Dance: "reduces incoming physical damage by 40% : 70%
    # (based on level) (+ 7% per 100 AP) and incoming magic damage by 20% : 35%
    # (based on level) (+ 3.5% per 100 AP)." level-scaled PHYS + MAGIC split,
    # active channel 1.5s (immobile) -> amortized. The AP sub-terms (+7%/100AP,
    # +3.5%/100AP) are OMITTED (no AP ctx on this EHP-side mitigation seam; the
    # same boundary as the heal registry's omitted AP/AS sub-terms) - the
    # level-scaled base percents are seeded.
    ("Irelia", "W", 0): PassiveMitigationEntry(
        terms=((_lerp_per_level(40.0, 70.0), PHYS), (_lerp_per_level(20.0, 35.0), MAG)),
        conditional_probability=_ACTIVE_DR_PROB,
        note="Defiant Dance: physical 40:70 + magic 20:35 (based on level) damage reduction during the 1.5s channel; +AP sub-terms omitted; level_scaled; cooldown-gated active amortized at the midpoint",
        attribute="Defiant Dance",
        level_scaled=True,
    ),
}

# Champions carrying a CURATED hand-authored percent-DR entry. The snapshot fold
# (below) skips these so a champ landing in BOTH the hand-authored registry and
# the ``champion_abilities.json`` defensive-block scan is never double-counted -
# the curated entry wins. Disjoint from the snapshot map today (R35); a forward
# safety guard for future overlap.
_HAND_AUTHORED_DR_CHAMPS = frozenset(c for (c, _k, _f) in _PASSIVE_MITIGATION_OVERRIDES)

# The labels the abilities-snapshot percent-DR accessor surfaces are an open set
# (16.13.1: "Damage Reduction", Braum's lowercased "Damage reduction", "Magic
# Damage Reduction", "Physical Damage Reduction", MasterYi's "Modified Damage
# Reduction"). A new champ can mint any phrasing, so classify by case-insensitive
# substring rather than an exact map: a "physical" token -> PHYS, a "magic" token
# -> MAG, anything else -> ANY (reduces all three EHP axes).
_AXIS_BY_TOKEN = ((PHYS, "physical"), (MAG, "magic"))

__all__ = [
    "PassiveMitigationEntry",
    "_PASSIVE_MITIGATION_OVERRIDES",
    "_HAND_AUTHORED_DR_CHAMPS",
    "_ASSUMED_ABILITY_RANK",
    "mitigation_multipliers",
    "PHYS",
    "MAG",
    "TRUE",
    "ANY",
]


def _classify_dr_axis(label: str) -> str:
    """Map a snapshot percent-DR attribute label to a damage axis token.

    Case-insensitive substring: a ``physical`` token -> PHYS, a ``magic`` token
    -> MAG, otherwise ANY (a generic "Damage Reduction" reduces all three axes).
    """
    low = str(label).lower()
    for axis, token in _AXIS_BY_TOKEN:
        if token in low:
            return axis
    return ANY


def _value_at_level(pct: float | tuple[float, ...], level: int, level_scaled: bool) -> float:
    """Resolve a term percent at the champion level.

    A ``level_scaled`` term carries a per-level tuple (``_lerp_per_level``) read
    at ``level-1`` (clamped to the tuple bounds); a flat term is its float.
    """
    if level_scaled and isinstance(pct, (tuple, list)):
        if not pct:
            return 0.0
        idx = max(0, min(int(level) - 1, len(pct) - 1))
        return float(pct[idx])
    if isinstance(pct, (tuple, list)):
        # Defensive: a tuple on a non-level_scaled entry resolves at its first.
        return float(pct[0]) if pct else 0.0
    return float(pct)


def mitigation_multipliers(
    champion_id: str,
    level: int,
    apply_passive_mitigation: bool,
    snapshot=None,
) -> tuple[float, float, float]:
    """Return ``(mit_phys, mit_mag, mit_true)`` damage-reduction multipliers.

    Each multiplier is ``prod(1 - pct/100 * conditional_probability)`` over every
    registered mitigation term matching ``champion_id`` for its damage axis (an
    ``any`` term contributes to all three). When ``apply_passive_mitigation`` is
    False (the default) all three are 1.0 - the EHP math is byte-identical and
    ``snapshot`` is never consulted.

    Two sources fold in when the flag is on:

    1. The hand-authored ``_PASSIVE_MITIGATION_OVERRIDES`` registry (effects-text
       formulas the abilities snapshot cannot express - level-scaled / form-gated
       / innate-always-on terms).
    2. R35 - when ``snapshot`` is a ``DataSnapshot``, the per-rank PERCENT
       damage-reduction blocks the R19 accessor
       ``snapshot.spell_damage_reduction_pct(champ, slot)`` surfaces from
       ``champion_abilities.json``. Each block's magnitude is read at
       ``_ASSUMED_ABILITY_RANK`` (clamped to the tuple bounds), amortized by
       ``_ACTIVE_DR_PROB`` (the active-uptime midpoint, since these are
       cooldown-gated self-buffs), classified to a damage axis by
       ``_classify_dr_axis``, and folded identically. A champ already carrying a
       hand-authored entry is SKIPPED (``_HAND_AUTHORED_DR_CHAMPS``) so the
       curated formula wins and nothing is double-counted.

    The caller folds each multiplier into the matching EHP denominator
    (``physical_ehp /= mit_phys``); a multiplier < 1.0 = a smaller divisor =
    larger EHP = the correct "less damage taken -> survives more" direction.
    """
    mit_phys = mit_mag = mit_true = 1.0
    if not apply_passive_mitigation:
        return mit_phys, mit_mag, mit_true
    cid = str(champion_id)
    lvl = int(level)
    for (entry_cid, _key, _form), entry in _PASSIVE_MITIGATION_OVERRIDES.items():
        if entry_cid != cid:
            continue
        prob = float(entry.conditional_probability)
        for (pct_raw, dtype) in entry.terms:
            if dtype not in _VALID_TYPES:
                continue
            pct = _value_at_level(pct_raw, lvl, entry.level_scaled)
            frac = max(0.0, min(1.0, (pct / 100.0) * prob))
            mult = 1.0 - frac
            if dtype in (PHYS, ANY):
                mit_phys *= mult
            if dtype in (MAG, ANY):
                mit_mag *= mult
            if dtype in (TRUE, ANY):
                mit_true *= mult

    # R35 snapshot-driven percent-DR fold (skip hand-authored champs to avoid a
    # double count). The per-rank tuple is read at the assumed ability rank and
    # amortized at the active-uptime midpoint - the same denominator treatment as
    # a hand-authored active entry.
    if snapshot is not None and cid not in _HAND_AUTHORED_DR_CHAMPS:
        idx = _ASSUMED_ABILITY_RANK - 1
        for slot in ("Q", "W", "E", "R"):
            labels = snapshot.spell_damage_reduction_pct(cid, slot)
            if not labels:
                continue
            for label, per_rank in labels.items():
                if not per_rank:
                    continue
                rank_idx = max(0, min(idx, len(per_rank) - 1))
                pct = float(per_rank[rank_idx])
                frac = max(0.0, min(1.0, (pct / 100.0) * _ACTIVE_DR_PROB))
                mult = 1.0 - frac
                axis = _classify_dr_axis(label)
                if axis in (PHYS, ANY):
                    mit_phys *= mult
                if axis in (MAG, ANY):
                    mit_mag *= mult
                if axis in (TRUE, ANY):
                    mit_true *= mult
    return mit_phys, mit_mag, mit_true
