"""2026-06-02 (GAP 2) - effects-text-only RESIST-STAT grant registry.

The FOURTH survivability axis, sibling of the item-261
``_passive_mitigation_overrides.py`` (flat-% DAMAGE REDUCTION) and the item-260
``_passive_shield_overrides.py`` / item-250..254 ``_passive_heal_overrides.py``
(throughput). Heals + shields are SURVIVABILITY THROUGHPUT; a flat-% DR is the
SURVIVABILITY DENOMINATOR MULTIPLIER; a RESIST-STAT grant raises the armor / MR
DENOMINATOR DIRECTLY (it is bonus armor / bonus magic resistance the champion
gains from an ability or innate passive, NOT a flat-% multiplier on damage
taken). Item 261 documented resist-stat grants as a DELIBERATE EXCLUSION from
the DR registry ("a DIFFERENT axis than a damage multiplier; would mis-model as
a DR percent") - this registry is that excluded axis, modeled cleanly.

Why a NEW registry (not the DR registry): a resist grant adds to ``armor`` /
``mr`` BEFORE ``_armor_factor`` (the League resist curve ``100/(100+resist)``),
whereas the DR registry multiplies the post-curve denominator. The two compose
the way League stacks bonus resists then a flat-% reduction. ``compute_ehp``
already reads ``armor`` / ``mr`` from the resolved stat block; this registry adds
the MISSING half - champion-passive / ability bonus resists that are NOT in the
base per-level stat block and NOT an item (so the resolved stats never carry
them). ZERO synthetic block - this is a pure EHP-denominator addend, so there is
no ``to_X_block`` here (mirrors the DR registry).

DEFAULT BEHAVIOR IS BYTE-IDENTICAL: ``apply_passive_resist`` defaults False; with
it OFF both grants are 0.0 and the EHP math is unchanged. No live :8893 default
scorer flips it on; it is opt-in everywhere (mirrors ``apply_passive_mitigation``
/ ``apply_passive_shield`` / ``apply_build_tenacity``).

RE-RANK note (HONEST framing - DIFFERS from the DR registry): a flat resist add
goes through the NON-LINEAR ``_armor_factor`` curve, so unlike item 261's DR
(a uniform multiplicative EHP scale that is rank-INVARIANT) a resist grant is NOT
a uniform EHP scale. Added to BOTH the baseline AND every ranked candidate (it is
a CHAMPION passive, build-independent), it shifts the per-row ``delta_ehp`` with
diminishing returns -> ``rank_items_by_ehp`` / ``rank_items_by_hybrid`` CAN
re-rank flag-on (an armor item is worth marginally less EHP to a champ that
already carries +30 innate armor; HP / MR items shift the other way). This is a
CORRECT re-rank, not a bug. The DEFAULT (flag-OFF) stays byte-identical.

Why HAND-AUTHORED, not parsed: identical reasoning to the heal/damage/shield/DR
registries - a text-parser mis-extracts the endpoints and re-breaks on each patch
prose rewrite. Each entry's armor / MR value comes from the verbatim
``effects_descriptions`` fragment cited in its ``note``; a patch re-extract
re-verifies the cited text.

CONDITIONAL / ACTIVE gating (the item-255 ``conditional_probability``
convention): a PERMANENT innate grant (Garen W cap / Wukong P / Shyvana P /
Sejuani P in-combat) uses prob 1.0 - it is up whenever the champion is in the
fight the EHP frame models. A short cooldown-gated ACTIVE (Gwen W mist / Pantheon
E 4s window) is amortized by the operator-tunable ``_ACTIVE_RESIST_PROB`` midpoint
(the expected fraction of a fight the active is up). The amortized grant is
``value * conditional_probability``; the resist value is EXACT, only the firing
midpoint is the assumption. Routing the active trigger to a live fight clock is a
future (Phase D) consumer job.

``level_scaled`` (default False) - set True for a grant whose value scales "based
on level" (Wukong P 6:10, Pantheon E 5:30). The per-level tuple
(``_lerp_per_level(low, high)``) is read at champion LEVEL (``level-1``). Flat
grants leave it False.

EXHAUSTED scan (all 171 champs, forms whose effects_descriptions carry a SELF
"gains/grants/bonus ... armor / magic resistance" grant): the clean flat /
level-scaled SELF resist-grant set with a CITABLE value in effects text is
exactly these 6 (4 permanent + 2 active). Documented EXCLUSIONS (scanned,
deliberately NOT seeded - with the reason class):
  - VALUE-NOT-IN-EFFECTS-TEXT (the prose says only "gains bonus armor and bonus
    magic resistance" with NO number; the value lives ONLY in a parsed leveling /
    modifier block - a future "read the block" lift could seed these, but the
    hand-authored registry has no citable value): Olaf R, Rammus W, Kennen R,
    Nasus R, Hecarim W, Malphite W (also "tripled while Granite Shield active"),
    Singed R, Taric W (% of his armor), Graves E ("for each stack ... bonus
    armor").
  - PERCENT-OF-RESIST multiplier (a multiplier on the resist STAT, not a flat
    add; needs a base-vs-bonus resist split this flat-add seam does not pass - a
    future percent-mode lift): Poppy W (+12% TOTAL armor + MR, doubled <40% HP),
    Rell W (15% BONUS armor + MR while Dismounted).
  - FORM-GATED with a GATE-DEPENDENT magnitude (the resist exists ONLY in one
    form; unlike K'Sante All Out / Kayn R where the base is gate-INDEPENDENT, here
    Cannon stance has ZERO of this grant so the base cannot be cleanly seeded -
    needs a form-state midpoint, Phase D): Jayce R Hammer (5/15/25/35 by level).
  - RESURRECTION / non-combat STATE (the grant applies only while the champion
    cannot act - a revive-egg, not a stat she fights with): Anivia P
    (-40:20 by level while under resurrection).
  - PER-STACK UNBOUNDED slow-accumulator (souls / similar - needs an
    assumed-stack-count midpoint that swings wildly by game length, less clean
    than the item-249 combat-stack convention): Thresh P (1 bonus armor per soul).
  - BALL-ATTACHED / ally-targeted grant (the grant rides a unit that is usually
    NOT the caster): Orianna E (the Ball grants resists to its attached unit).
  - ARMOR-PEN / SIZE / ATTACK-SPEED-only (not a resist grant): Darius E /
    Pantheon R / Ambessa R (armor pen), Malphite P (size), Galio P / Rell W AS.
"""
from __future__ import annotations

from dataclasses import dataclass

from ._passive_damage_overrides import _lerp_per_level

# Operator-tunable midpoint for a short defensive ACTIVE resist grant (the
# expected fraction of a fight's duration the active is up). Documented +
# conservative; Phase D tunes per-champ live. A PERMANENT innate / in-combat
# grant uses prob 1.0 (always up in the fight the EHP frame models). Parallel to
# ``_passive_mitigation_overrides._ACTIVE_DR_PROB``.
_ACTIVE_RESIST_PROB = 0.3


@dataclass(frozen=True)
class PassiveResistEntry:
    """One hand-authored effects-text-only bonus armor / magic-resistance grant.

    ``armor`` / ``mr`` are flat bonus values (or a per-level tuple when
    ``level_scaled``). Each is added to the resolved armor / MR in
    ``compute_ehp`` (before the ``_armor_factor`` curve), scaled by
    ``conditional_probability``.

    ``conditional_probability`` (default 1.0 = a permanent / in-combat grant that
    always applies in the modeled fight) amortizes a cooldown-gated active by its
    expected uptime midpoint.

    ``level_scaled`` (default False) - set True when ``armor`` / ``mr`` is a
    per-level tuple read at champion level (``level-1``), not a flat value.
    """

    armor: float | tuple[float, ...] = 0.0
    mr: float | tuple[float, ...] = 0.0
    conditional_probability: float = 1.0
    note: str = ""
    attribute: str = "Passive Resist"
    level_scaled: bool = False


# (champion_id, key, form_index) -> PassiveResistEntry. Keyed for parity with the
# heal/shield/DR registries + future per-form gating; ``resist_grants`` aggregates
# ALL entries whose key champion matches (a resist grant is champion-level for
# EHP). Seeded 2026-06-02 against verbatim effects_descriptions at patch 16.11.1.
_PASSIVE_RESIST_OVERRIDES: dict[tuple[str, str, int], PassiveResistEntry] = {
    # Garen W Courage: "For each stack, Garen gains 0.2 bonus armor and 0.2 bonus
    # magic resistance, up to a maximum of 30 bonus resistances each." PERMANENT
    # stacking (never lost) to a 30/30 cap; seeded at the cap = the steady-state
    # late-game value (the item-249 assumed-steady-state convention; early-game is
    # under-stacked). prob 1.0 (permanent).
    ("Garen", "W", 0): PassiveResistEntry(
        armor=30.0,
        mr=30.0,
        conditional_probability=1.0,
        note="Courage: 0.2 armor + 0.2 MR per permanent stack, cap 30/30; seeded at the steady-state cap",
        attribute="Courage",
    ),
    # Wukong P Stone Skin: "Wukong gains 6 : 10 (based on level) bonus armor".
    # PERMANENT innate, ARMOR ONLY (no MR). The Strength of Stone combat stacks
    # (up to 36:60 with 5 stacks) are OMITTED (per-stack combat ramp; the same
    # boundary as the per-stack omissions elsewhere) - the innate base is seeded.
    ("MonkeyKing", "P", 0): PassiveResistEntry(
        armor=_lerp_per_level(6.0, 10.0),
        mr=0.0,
        conditional_probability=1.0,
        note="Stone Skin: 6:10 (based on level) innate bonus armor (armor-only); Strength of Stone combat stacks omitted; level_scaled",
        attribute="Stone Skin",
        level_scaled=True,
    ),
    # Shyvana P Fury of the Dragonborn: "Shyvana gains 5 bonus armor and 5 bonus
    # magic resistance, which are each increased by 5 for every elemental drake
    # and Elder Dragon her team slays." PERMANENT innate base 5/5; the drake
    # stacks are OMITTED (game-state-dependent, like the per-stack omissions) -
    # the base is seeded. prob 1.0.
    ("Shyvana", "P", 0): PassiveResistEntry(
        armor=5.0,
        mr=5.0,
        conditional_probability=1.0,
        note="Fury of the Dragonborn: 5 armor + 5 MR innate base; per-drake +5 stacks omitted",
        attribute="Fury of the Dragonborn",
    ),
    # Sejuani P Frost Armor: "Sejuani gains ... 10 (+ 75% bonus armor) bonus
    # armor, and 10 (+ 75% bonus magic resistance) bonus magic resistance." Frost
    # Armor lingers 3s after taking champion/turret/monster damage -> up whenever
    # she is in the fight the EHP frame models, so prob 1.0 (in-combat near-
    # permanent, not a cooldown-gated burst). The +75% bonus-resist sub-terms are
    # OMITTED (stat-scaling with no resolved-bonus ctx on this seam; the same
    # boundary as the DR registry's omitted AP/AS sub-terms) - the flat 10/10 base
    # is seeded.
    ("Sejuani", "P", 0): PassiveResistEntry(
        armor=10.0,
        mr=10.0,
        conditional_probability=1.0,
        note="Frost Armor: 10 armor + 10 MR (in-combat, lingers 3s after taking damage); +75% bonus-resist sub-terms omitted",
        attribute="Frost Armor",
    ),
    # Gwen W Hallowed Mist: "While inside the mist ... gains 22 (+ 7% AP) bonus
    # armor and bonus magic resistance". ACTIVE mist zone she steps in/out of ->
    # amortized at the active midpoint. The +7% AP sub-term is OMITTED (no AP ctx
    # on this EHP-side seam; the DR-registry boundary) - the flat 22/22 base is
    # seeded.
    ("Gwen", "W", 0): PassiveResistEntry(
        armor=22.0,
        mr=22.0,
        conditional_probability=_ACTIVE_RESIST_PROB,
        note="Hallowed Mist: 22 armor + 22 MR while inside the mist; +7% AP omitted; cooldown-gated active amortized at the midpoint",
        attribute="Hallowed Mist",
    ),
    # Pantheon E Aegis Assault: "After recasting, Pantheon gains 5 : 30 (based on
    # level) (+ 2.5% bonus health) bonus armor and bonus magic resistance for 4
    # seconds". level-scaled ACTIVE (4s after the E recast) -> amortized. The
    # +2.5% bonus-HP sub-term is OMITTED (no bonus-HP ctx on this seam) - the
    # level-scaled base is seeded.
    ("Pantheon", "E", 0): PassiveResistEntry(
        armor=_lerp_per_level(5.0, 30.0),
        mr=_lerp_per_level(5.0, 30.0),
        conditional_probability=_ACTIVE_RESIST_PROB,
        note="Aegis Assault: 5:30 (based on level) armor + MR for 4s after recast; +2.5% bonus HP omitted; level_scaled; cooldown-gated active amortized at the midpoint",
        attribute="Aegis Assault",
        level_scaled=True,
    ),
}

__all__ = [
    "PassiveResistEntry",
    "_PASSIVE_RESIST_OVERRIDES",
    "resist_grants",
    "_ACTIVE_RESIST_PROB",
]


def _value_at_level(val: float | tuple[float, ...], level: int, level_scaled: bool) -> float:
    """Resolve a grant value at the champion level.

    A ``level_scaled`` value carries a per-level tuple (``_lerp_per_level``) read
    at ``level-1`` (clamped to the tuple bounds); a flat value is its float.
    """
    if level_scaled and isinstance(val, (tuple, list)):
        if not val:
            return 0.0
        idx = max(0, min(int(level) - 1, len(val) - 1))
        return float(val[idx])
    if isinstance(val, (tuple, list)):
        # Defensive: a tuple on a non-level_scaled entry resolves at its first.
        return float(val[0]) if val else 0.0
    return float(val)


def resist_grants(
    champion_id: str, level: int, apply_passive_resist: bool
) -> tuple[float, float]:
    """Return ``(bonus_armor, bonus_mr)`` from effects-text resist grants.

    Each is ``sum(value(level) * conditional_probability)`` over every registered
    resist grant matching ``champion_id``. When ``apply_passive_resist`` is False
    (the default) both are 0.0 - the EHP math is byte-identical.

    The caller adds each to the matching resolved resist BEFORE ``_armor_factor``
    (``eff_armor = armor + bonus_armor``); a positive grant lowers the resist
    curve's damage-taken multiplier = larger EHP = the correct "more resist ->
    survives more" direction.
    """
    bonus_armor = bonus_mr = 0.0
    if not apply_passive_resist:
        return bonus_armor, bonus_mr
    cid = str(champion_id)
    lvl = int(level)
    for (entry_cid, _key, _form), entry in _PASSIVE_RESIST_OVERRIDES.items():
        if entry_cid != cid:
            continue
        prob = float(entry.conditional_probability)
        a = _value_at_level(entry.armor, lvl, entry.level_scaled)
        m = _value_at_level(entry.mr, lvl, entry.level_scaled)
        bonus_armor += a * prob
        bonus_mr += m * prob
    return bonus_armor, bonus_mr
