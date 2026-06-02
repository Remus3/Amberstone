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
resist grant). TWO source modes:
  - effects-text value (item 264): 6 entries (4 permanent + 2 active) whose
    armor / MR number is cited directly in the prose.
  - parsed-block value (item 267, the "read the parsed block" lift): 6 entries
    whose prose says only "gains bonus armor and bonus magic resistance" with NO
    inline number, but whose value lives in a parsed Meraki ``[other]`` block
    indexed by ability rank -> seeded ``rank_scaled``: Olaf R [10/15/20] perm,
    Nasus R [40/55/70], Kennen R [20/40/60], Hecarim W [5..25], Rammus W FLAT
    [27..47] (% half omitted), Graves E [32..128] armor-only at-cap.
  - percent-of-resist value (item 268, the candidate-B base-vs-bonus split): 5
    entries whose grant is a PERCENT of the champion's own armor / MR (not a flat
    add). ``armor_pct`` / ``mr_pct`` + ``pct_base`` ("total" | "bonus") multiply
    the RESOLVED build resist threaded in from ``compute_ehp``: Malphite W
    (10..30% of TOTAL armor, ARMOR ONLY, permanent), Taric W (6..10% of TOTAL
    armor, ARMOR ONLY, permanent), Poppy W (flat 12% of TOTAL armor + MR,
    permanent), Rell W form 1 (flat 15% of BONUS armor + MR, Dismounted steady-
    state), Rammus W (30..60% of TOTAL armor + MR, the %-half extending the item
    267 flat entry, 7s active amortized).
  - unlabeled MULTI-STAT / MULTI-SERIES block (item 270, the last seedable resist
    EXCLUSION class): a parsed block bundles several stats or two value series with
    no per-stat label; HAND attribution resolves the FLAT BASE confidently. Singed
    R (ONE shared series [25,60,95] = AP == armor == MR), Braum W / Leona W / Jax R
    (a TWO-series block where series[0] varies by rank = the flat base, series[1]
    is a rank-constant percent coefficient that is OMITTED per its base - Braum
    36% of ALLY bonus / Leona 20% uncertain / Jax 40%/24% of BONUS AD). The
    rank-varying flat base armor / MR is seeded (rank_scaled); the percent
    coefficient + the AP / MS / regen / per-instance-DR / per-hit sub-terms are
    documented omissions (the item-264 omission boundary). No new schema field -
    hand-authoring resolves the per-series attribution the item-264 note imagined
    needing a generic parser for.
  - FORM-OCCUPANCY-gated value (item 271): the grant exists ONLY in one stance of
    a 2-form toggle (the other stance carries ZERO of it, so unlike K'Sante All
    Out / Kayn R the base cannot be seeded gate-independently); amortized by the
    fraction of the modeled fight spent in the granting form
    (``_FORM_OCCUPANCY_PROB`` 0.5, reusing ``conditional_probability`` - no new
    schema field). Jayce R Hammer (5/15/25/35 by level armor == MR, Hammer-stance
    only; +7.5% bonus AD omitted). EXHAUSTIVE roster scan: the SOLE form-gated
    self flat-resist grant (Cannon-stance Jayce R only shreds the TARGET; Kled
    forms are HP not resist; Elise/Nidalee/Gnar/Shyvana/Swain forms grant no flat
    resist).
  - PER-STACK UNBOUNDED value (item 272): a flat per-stack coefficient times a
    slow game-long accumulator with NO cap, so unlike the BOUNDED per-stack cases
    (Garen W cap 30 / Graves E cap 8 / Wukong P cap 5, all seeded "at the cap")
    it cannot be capped - it needs an assumed steady-state count. ``per_stack_*``
    + ``assumed_stacks`` (``_ASSUMED_SOUL_COUNT`` 25, the item-249 convention on
    the EHP seam). Thresh P (1 bonus armor per soul, ARMOR ONLY; +1 AP per soul is
    offensive). EXHAUSTIVE roster scan (per-stack + armor/MR co-occurrence): the
    SOLE per-stack-UNBOUNDED self-resist grant - every other per-stack resist is
    BOUNDED (Garen W / Graves E / Wukong P combat stacks / Jax R on-hit, already
    seeded or omitted).
Documented EXCLUSIONS (scanned, deliberately NOT seeded - with the reason class):
  - RESURRECTION / non-combat STATE (the grant applies only while the champion
    cannot act - a revive-egg, not a stat she fights with): Anivia P
    (-40:20 by level while under resurrection).
  - BALL-ATTACHED / ally-targeted grant (the grant rides a unit that is usually
    NOT the caster): Orianna E (the Ball grants resists to its attached unit).
  - ARMOR-PEN / SIZE / ATTACK-SPEED-only (not a resist grant): Darius E /
    Pantheon R / Ambessa R (armor pen), Malphite P (size), Galio P / Rell W AS.
"""
from __future__ import annotations

from dataclasses import dataclass

from ._passive_damage_overrides import _lerp_per_level, _step_per_level

# Operator-tunable midpoint for a short defensive ACTIVE resist grant (the
# expected fraction of a fight's duration the active is up). Documented +
# conservative; Phase D tunes per-champ live. A PERMANENT innate / in-combat
# grant uses prob 1.0 (always up in the fight the EHP frame models). Parallel to
# ``_passive_mitigation_overrides._ACTIVE_DR_PROB``.
_ACTIVE_RESIST_PROB = 0.3

# Operator-tunable midpoint for a FORM-OCCUPANCY-gated resist grant (item 271):
# the resist exists ONLY while the champion is in one stance of a 2-form toggle
# (the OTHER stance carries ZERO of the grant, so the base cannot be seeded
# gate-independently the way K'Sante All Out / Kayn R are). The grant is
# amortized by the expected fraction of the modeled fight spent in the
# granting form. 0.5 = a roughly even split of a 2-form toggle (Jayce mains
# weave Cannon poke + Hammer brawl). Documented + conservative; Phase D tunes
# per-champ live. Reuses the existing ``conditional_probability`` amortization
# field (no new schema field - hand-authoring resolves the form gate, the
# item-270 convention). Parallel to ``_ACTIVE_RESIST_PROB``.
_FORM_OCCUPANCY_PROB = 0.5

# Operator-tunable midpoint for a PER-STACK UNBOUNDED resist grant (item 272):
# the resist scales LINEARLY with a slow game-long accumulator that has NO cap
# (Thresh souls), so unlike the BOUNDED per-stack cases (Garen W cap 30 / Graves
# E cap 8 / Wukong P cap 5) it cannot be "seeded at the cap" - it needs an
# assumed steady-state stack count. 25 souls = a typical mid-to-late-game count
# for a support Thresh (souls never reset; Thresh's innate ARMOR DOES NOT GROW
# per level, so souls ARE his armor scaling). The per-soul coefficient is EXACT;
# only the count is the assumption (the item-249 ``assumed_stacks`` convention).
# Documented + conservative; Phase D feeds the real live soul count from the
# scoreboard / Live Client without re-authoring. Parallel to
# ``_ACTIVE_RESIST_PROB`` / ``_FORM_OCCUPANCY_PROB``.
_ASSUMED_SOUL_COUNT = 25.0


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

    ``rank_scaled`` (default False, item 267) - set True when ``armor`` / ``mr``
    is a per-ABILITY-RANK tuple sourced from a parsed Meraki ``[other]`` block,
    resolved via ``ability_dps.rank_at_level(key, level)`` (deterministic for
    ults, engine-default Q>W>E priority for basics; an unlearned ability grants
    0.0). Mutually exclusive with ``level_scaled``.
    """

    armor: float | tuple[float, ...] = 0.0
    mr: float | tuple[float, ...] = 0.0
    # item 268 (percent-of-resist mode): bonus armor / MR equal to a PERCENT of
    # the champion's OWN resist STAT (e.g. Malphite W 20% of his armor), NOT a
    # flat add. ``armor_pct`` / ``mr_pct`` carry the percent (12.0 == 12%), flat
    # or a per-rank / per-level tuple resolved the same way as ``armor`` / ``mr``.
    # ``pct_base`` selects which resist the percent multiplies: "total" (base +
    # build) or "bonus" (build delta = total - base per-level). An entry may carry
    # BOTH the flat-add fields (item 264/267) AND the percent fields (Rammus W);
    # they sum. Default 0.0 percent -> the flat-only entries are unchanged.
    armor_pct: float | tuple[float, ...] = 0.0
    mr_pct: float | tuple[float, ...] = 0.0
    pct_base: str = "total"
    conditional_probability: float = 1.0
    note: str = ""
    attribute: str = "Passive Resist"
    level_scaled: bool = False
    rank_scaled: bool = False
    # item 272 (per-stack UNBOUNDED mode): bonus armor / MR equal to a flat
    # per-stack coefficient times ``assumed_stacks`` (a slow game-long accumulator
    # with no cap, e.g. Thresh souls). The coefficient is EXACT; only the count is
    # the steady-state assumption (the item-249 ``assumed_stacks`` convention,
    # mirrored on the EHP seam). Resolves as ``per_stack_* * assumed_stacks``,
    # summed alongside the flat-add + percent halves. Default 0.0 -> a flat /
    # percent / bounded-at-cap entry contributes nothing here.
    per_stack_armor: float = 0.0
    per_stack_mr: float = 0.0
    assumed_stacks: float = 0.0


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
    # ----- item 267: rank-scaled grants whose VALUE lives in a parsed [other]
    # block (the effects_descriptions prose says only "gains bonus armor and
    # bonus magic resistance" with NO inline number). armor/mr are per-ABILITY-
    # RANK tuples resolved via ability_dps.rank_at_level(key, level) -
    # deterministic for ults (R 6/11/16), engine-default Q>W>E priority for
    # basics. Each value cited from the patch-16.11.1 [other] block.
    #
    # Olaf R Ragnarok: "Passive: Olaf gains bonus armor and bonus magic
    # resistance." [other] block [10,15,20] by R rank. PERMANENT passive (the
    # R's passive half is always on once R is learned), prob 1.0.
    ("Olaf", "R", 0): PassiveResistEntry(
        armor=(10.0, 15.0, 20.0),
        mr=(10.0, 15.0, 20.0),
        conditional_probability=1.0,
        note="Ragnarok passive: 10/15/20 armor + MR by R rank ([other] block); permanent once R learned; rank_scaled",
        attribute="Ragnarok",
        rank_scaled=True,
    ),
    # Nasus R Fury of the Sands: "gaining bonus health, bonus armor, bonus magic
    # resistance, increased size ...". [other] block [40,55,70] by R rank = the
    # armor + MR (the [heal] 300/450/600 bonus HP + the % block are separate +
    # not modeled here). 15s active steroid, cooldown-gated -> amortized.
    ("Nasus", "R", 0): PassiveResistEntry(
        armor=(40.0, 55.0, 70.0),
        mr=(40.0, 55.0, 70.0),
        conditional_probability=_ACTIVE_RESIST_PROB,
        note="Fury of the Sands: 40/55/70 armor + MR by R rank ([other] block); 15s active amortized at the midpoint; bonus HP + size omitted; rank_scaled",
        attribute="Fury of the Sands",
        rank_scaled=True,
    ),
    # Kennen R Slicing Maelstrom: "gaining bonus armor and bonus magic
    # resistance for the duration." [other] block [20,40,60] by R rank. 3s
    # active burst, cooldown-gated -> amortized.
    ("Kennen", "R", 0): PassiveResistEntry(
        armor=(20.0, 40.0, 60.0),
        mr=(20.0, 40.0, 60.0),
        conditional_probability=_ACTIVE_RESIST_PROB,
        note="Slicing Maelstrom: 20/40/60 armor + MR by R rank ([other] block); 3s active amortized at the midpoint; rank_scaled",
        attribute="Slicing Maelstrom",
        rank_scaled=True,
    ),
    # Hecarim W Spirit of Dread: "gains bonus armor and bonus magic resistance
    # and is healed ...". [other] block [5,10,15,20,25] by W rank = the resists
    # (the [heal] 120:240 is separate). ~4s active, cooldown-gated -> amortized.
    # W rank resolved at the engine-default Q>W>E priority (W = priority_2).
    ("Hecarim", "W", 0): PassiveResistEntry(
        armor=(5.0, 10.0, 15.0, 20.0, 25.0),
        mr=(5.0, 10.0, 15.0, 20.0, 25.0),
        conditional_probability=_ACTIVE_RESIST_PROB,
        note="Spirit of Dread: 5/10/15/20/25 armor + MR by W rank ([other] block); 4s active amortized at the midpoint; heal omitted; rank_scaled (W priority_2)",
        attribute="Spirit of Dread",
        rank_scaled=True,
    ),
    # Rammus W Defensive Ball Curl: "gaining bonus armor and bonus magic
    # resistance." TWO [other] series - FLAT [27,32,37,42,47] + a % TOTAL armor/MR
    # [30:60]. The FLAT half (by W rank) is seeded; the %-of-total half is OMITTED
    # (a percent-of-resist mode the flat-add seam does not pass - the candidate-B
    # base-vs-bonus split). 7s active, cooldown-gated -> amortized.
    # item 268: the %-of-total half ITEM 267 OMITTED is now seeded alongside the
    # flat half on the SAME entry. "Bonus Armor" [30,37.5,45,52.5,60] % total armor
    # + "Bonus Magic Resistance" [30,37.5,45,52.5,60] % total MR by W rank. The
    # flat half (27..47) + percent half SUM (League stacks both). 7s active
    # amortized at the same _ACTIVE_RESIST_PROB midpoint; rank_scaled (W priority_2)
    # governs BOTH the flat tuple and the percent tuple.
    ("Rammus", "W", 0): PassiveResistEntry(
        armor=(27.0, 32.0, 37.0, 42.0, 47.0),
        mr=(27.0, 32.0, 37.0, 42.0, 47.0),
        armor_pct=(30.0, 37.5, 45.0, 52.5, 60.0),
        mr_pct=(30.0, 37.5, 45.0, 52.5, 60.0),
        pct_base="total",
        conditional_probability=_ACTIVE_RESIST_PROB,
        note="Defensive Ball Curl: 27/32/37/42/47 FLAT + 30/37.5/45/52.5/60% of TOTAL armor + MR by W rank ([other] blocks, both sum); 7s active amortized; rank_scaled (W priority_2)",
        attribute="Defensive Ball Curl",
        rank_scaled=True,
    ),
    # ----- item 268: PERCENT-OF-RESIST mode (the candidate-B base-vs-bonus split
    # named as the percent-mode EXCLUSION in items 264/267). The grant is a PERCENT
    # of the champion's own resist STAT (resolved against the build), not a flat
    # add - so armor_pct / mr_pct carry the percent + pct_base selects total | bonus.
    #
    # Malphite W Thunderclap: "Bonus Armor" [10,15,20,25,30] % of his armor (% of
    # TOTAL armor, ARMOR ONLY). The Granite-Shield "Increased Bonus Armor"
    # [30..90]% tier is OMITTED (shield-gated; the base is seeded). PERMANENT
    # passive (always on while W learned) -> prob 1.0; rank_scaled (W priority_2).
    ("Malphite", "W", 0): PassiveResistEntry(
        armor_pct=(10.0, 15.0, 20.0, 25.0, 30.0),
        mr_pct=0.0,
        pct_base="total",
        conditional_probability=1.0,
        note="Thunderclap: 10/15/20/25/30% of TOTAL armor as bonus armor by W rank (ARMOR ONLY); Granite-Shield Increased tier omitted; permanent; rank_scaled (W priority_2)",
        attribute="Thunderclap",
        rank_scaled=True,
    ),
    # Taric W Bastion: "Bonus Armor" [6,7,8,9,10] % of Taric's armor (% of TOTAL
    # armor, ARMOR ONLY). The ally-tethered copy is omitted (self portion seeded).
    # PERMANENT (the self-bonus is present whenever W is learned) -> prob 1.0;
    # rank_scaled (W priority_2).
    ("Taric", "W", 0): PassiveResistEntry(
        armor_pct=(6.0, 7.0, 8.0, 9.0, 10.0),
        mr_pct=0.0,
        pct_base="total",
        conditional_probability=1.0,
        note="Bastion: 6/7/8/9/10% of TOTAL armor as bonus armor by W rank (ARMOR ONLY, self portion); ally copy omitted; permanent; rank_scaled (W priority_2)",
        attribute="Bastion",
        rank_scaled=True,
    ),
    # Poppy W Steadfast Presence passive (Stubborn to a Fault): "increases her
    # total armor and total magic resistance by 12%, doubled to 24% while below 40%
    # maximum health." FLAT 12% of TOTAL armor + MR (NOT rank-scaled). The
    # doubled-to-24%-below-40%-HP conditional is OMITTED (the steady-state
    # above-40%-HP value is seeded; same boundary as Sejuani's +75% sub-terms).
    # PERMANENT passive (the Garen-W / Shyvana-P flat-permanent convention,
    # level-invariant) -> prob 1.0.
    ("Poppy", "W", 0): PassiveResistEntry(
        armor_pct=12.0,
        mr_pct=12.0,
        pct_base="total",
        conditional_probability=1.0,
        note="Stubborn to a Fault: +12% of TOTAL armor + MR (flat, level-invariant); doubled-to-24%-below-40%-HP conditional omitted; permanent",
        attribute="Stubborn to a Fault",
    ),
    # Rell W form 1 (Mount Up / Dismounted passive): "While Rell is Dismounted, she
    # gains 15% bonus armor, 15% bonus magic resistance". FLAT 15% of BONUS armor +
    # MR (the build delta, NOT total) -> 0 itemless, surfaces only when she builds
    # resists. Dismounted is her STEADY-STATE combat stance after the R/W engage
    # (the EHP frame models the post-engage fight), so prob 1.0 (the Sejuani
    # Frost-Armor in-combat-permanent convention). form_index 1 = the Mount Up form
    # where the Dismounted passive lives in the parsed data.
    ("Rell", "W", 1): PassiveResistEntry(
        armor_pct=15.0,
        mr_pct=15.0,
        pct_base="bonus",
        conditional_probability=1.0,
        note="Ferromancy (Dismounted): +15% of BONUS armor + MR (build delta, 0 itemless) while Dismounted; Dismounted = steady-state combat stance, prob 1.0",
        attribute="Ferromancy",
    ),
    # Graves E True Grit: "For each stack, Graves gains bonus armor." ARMOR ONLY
    # (no MR). [other] per-stack [4,7,10,13,16] + the at-cap (8 stacks)
    # [32,56,80,104,128] by E rank. Seeded at the CAP (the in-fight steady state,
    # refreshed by Quickdraw casts + attacks; the Garen-W-at-cap convention),
    # prob 1.0. E rank resolved at the engine-default priority (E = priority_3).
    ("Graves", "E", 0): PassiveResistEntry(
        armor=(32.0, 56.0, 80.0, 104.0, 128.0),
        mr=0.0,
        conditional_probability=1.0,
        note="True Grit: 32/56/80/104/128 ARMOR-ONLY by E rank at the 8-stack cap ([other] block); seeded at the in-fight steady-state cap; rank_scaled (E priority_3)",
        attribute="True Grit",
        rank_scaled=True,
    ),
    # ----- item 270: UNLABELED MULTI-STAT / MULTI-SERIES block resist set (the
    # last seedable resist-grant EXCLUSION class from items 264/267/268). These
    # forms carry a parsed Meraki block that bundles several stats or two value
    # series with no per-stat label, so item 264 deferred them as "value cannot be
    # confidently attributed". HAND attribution resolves them cleanly:
    #   - Singed R "Bonus Stats" is ONE series [25,60,95] shared by AP / armor / MR
    #     (the canonical Insanity Potion - the same flat number to all three; the
    #     % MS + the two regen blocks are separate). armor == MR == that series.
    #   - Braum W / Leona W / Jax R carry a TWO-series block: series[0] VARIES by
    #     ability rank (the flat base armor / MR) and series[1] is CONSTANT across
    #     ranks (a percent coefficient). The rank-varying series is seeded as the
    #     flat base; the constant percent coefficient is OMITTED per its (different)
    #     base: Braum 36% of the ALLY's bonus resist (cross-champion, no ally seam),
    #     Leona 20% (attribution uncertain - own-bonus not confirmed), Jax 40%/24%
    #     of BONUS AD (no bonus-AD ctx on the EHP seam - the item-264 omission
    #     boundary). The flat base is exact + correct lower-bound.
    #
    # Singed R Insanity Potion: armor == MR == [25,60,95] by R rank ("Bonus Stats"
    # block). 25s active on a 100s cooldown -> amortized at the active midpoint
    # (uptime ~0.25, the 0.3 convention midpoint). AP + % MS + HP/mana regen
    # omitted (not resist). rank_scaled (R 6/11/16).
    ("Singed", "R", 0): PassiveResistEntry(
        armor=(25.0, 60.0, 95.0),
        mr=(25.0, 60.0, 95.0),
        conditional_probability=_ACTIVE_RESIST_PROB,
        note="Insanity Potion: 25/60/95 armor + MR by R rank (shared Bonus Stats series, == the AP value); 25s active amortized at the midpoint; AP/MS/regen omitted; rank_scaled",
        attribute="Insanity Potion",
        rank_scaled=True,
    ),
    # Braum W Stand Behind Me: self base armor + MR [20,25,30,35,40] by W rank
    # ("Self Bonus Armor" / "Self Bonus Magic Resistance" series[0]). The +36% of
    # the ALLY's bonus resists (series[1], constant 36) is OMITTED (cross-champion,
    # no ally resist on the EHP seam). Short active grant -> amortized. rank_scaled
    # (W priority_2).
    ("Braum", "W", 0): PassiveResistEntry(
        armor=(20.0, 25.0, 30.0, 35.0, 40.0),
        mr=(20.0, 25.0, 30.0, 35.0, 40.0),
        conditional_probability=_ACTIVE_RESIST_PROB,
        note="Stand Behind Me: 20/25/30/35/40 self armor + MR by W rank (series[0]); +36% of ALLY bonus resist omitted (cross-champion); active amortized at the midpoint; rank_scaled (W priority_2)",
        attribute="Stand Behind Me",
        rank_scaled=True,
    ),
    # Leona W Eclipse: base armor + MR [20,27.5,35,42.5,50] by W rank ("Bonus
    # Armor" / "Bonus Magic Resistance" series[0]). The +20% (series[1], constant
    # 20) is OMITTED (attribution uncertain - own-bonus not confirmed), as is the
    # separate "Flat Damage Reduction" [8..24] (a per-INSTANCE flat-AMOUNT
    # reduction, NOT a flat-% DR; the item-261 per-instance exclusion). 3s active
    # (+3s if it hits) -> amortized. rank_scaled (W priority_2).
    ("Leona", "W", 0): PassiveResistEntry(
        armor=(20.0, 27.5, 35.0, 42.5, 50.0),
        mr=(20.0, 27.5, 35.0, 42.5, 50.0),
        conditional_probability=_ACTIVE_RESIST_PROB,
        note="Eclipse: 20/27.5/35/42.5/50 armor + MR by W rank (series[0]); +20% second series + the per-instance flat damage reduction omitted; 3s active amortized at the midpoint; rank_scaled (W priority_2)",
        attribute="Eclipse",
        rank_scaled=True,
    ),
    # Jax R Grandmaster-at-Arms: base armor [25,50,75] + MR [15,30,45] by R rank
    # ("Bonus Armor" / "Bonus Magic Resistance" series[0], granted when the active
    # lantern swing hits a champion). The +40% / +24% of BONUS AD (series[1],
    # constant) is OMITTED (no bonus-AD ctx on the EHP seam; the item-264 boundary),
    # as is the "per Champion Hit" extra [20/25/30 armor, 12/15/18 MR] (additional
    # per-extra-champ). On-hit active -> amortized. rank_scaled (R 6/11/16).
    ("Jax", "R", 0): PassiveResistEntry(
        armor=(25.0, 50.0, 75.0),
        mr=(15.0, 30.0, 45.0),
        conditional_probability=_ACTIVE_RESIST_PROB,
        note="Grandmaster-at-Arms: 25/50/75 armor + 15/30/45 MR by R rank (series[0], on active champ-hit); +40%/24% bonus-AD + per-champ-hit extra omitted; active amortized at the midpoint; rank_scaled",
        attribute="Grandmaster-at-Arms",
        rank_scaled=True,
    ),
    # Jayce R Transform Mercury Hammer (form_index 1, item 271): "Active: Jayce
    # transforms into Hammer Stance ... gaining 5 / 15 / 25 / 35 (based on level)
    # (+ 7.5% bonus AD) bonus armor and bonus magic resistance". FORM-GATED: this
    # grant exists ONLY in Hammer stance; Cannon stance (form_index 0) carries
    # ZERO of it (its R only shreds the TARGET's resists 10..25% on-hit, an
    # offensive debuff not a self-grant), so unlike K'Sante All Out / Kayn R the
    # base cannot be seeded gate-independently. Amortized by the form-occupancy
    # midpoint (_FORM_OCCUPANCY_PROB 0.5 = a roughly even Cannon/Hammer split).
    # armor == MR == 5/15/25/35 "based on level" = slash-notation discrete level
    # TIER step -> _step_per_level (even-quarters v1 estimate, the item-247
    # convention; level boundaries not in the 16.11.1 effects text). The +7.5%
    # bonus-AD sub-term is OMITTED (no bonus-AD ctx on this EHP seam; the item
    # 270 Jax-R / item 264 omission boundary).
    ("Jayce", "R", 1): PassiveResistEntry(
        armor=_step_per_level((5.0, 15.0, 25.0, 35.0)),
        mr=_step_per_level((5.0, 15.0, 25.0, 35.0)),
        conditional_probability=_FORM_OCCUPANCY_PROB,
        note="Transform Mercury Hammer: 5/15/25/35 (based on level) armor == MR, Hammer-stance only; +7.5% bonus AD omitted; form-occupancy amortized at the midpoint; level_scaled",
        attribute="Transform Mercury Hammer",
        level_scaled=True,
    ),
    # Thresh P Damnation (form_index 0, item 272): "Soul: For each stack, Thresh
    # gains 1 ability power and 1 bonus armor." PER-STACK UNBOUNDED - the soul
    # count is a slow game-long accumulator with NO cap, so unlike the BOUNDED
    # per-stack cases (Garen W cap 30/30, Graves E cap 8 stacks, Wukong P cap 5)
    # this cannot be seeded "at the cap" - it needs an assumed steady-state soul
    # count (_ASSUMED_SOUL_COUNT 25, the item-249 assumed_stacks convention on the
    # EHP seam). ARMOR ONLY (the +1 AP per soul is offensive, not a resist; no MR).
    # PERMANENT (souls are never lost), prob 1.0. Thresh's innate "armor does not
    # increase through growth (per level)" makes souls his ONLY armor scaling, so
    # the grant is load-bearing for his EHP. per_stack_armor 1.0 * assumed_stacks
    # 25 = 25 bonus armor at the midpoint (Phase D feeds the live soul count).
    ("Thresh", "P", 0): PassiveResistEntry(
        per_stack_armor=1.0,
        per_stack_mr=0.0,
        assumed_stacks=_ASSUMED_SOUL_COUNT,
        conditional_probability=1.0,
        note="Damnation: 1 bonus armor per soul (ARMOR ONLY, +1 AP per soul is offensive); UNBOUNDED accumulator seeded at the assumed steady-state soul count (25); permanent; per_stack",
        attribute="Damnation",
    ),
}

__all__ = [
    "PassiveResistEntry",
    "_PASSIVE_RESIST_OVERRIDES",
    "resist_grants",
    "_ACTIVE_RESIST_PROB",
    "_FORM_OCCUPANCY_PROB",
    "_ASSUMED_SOUL_COUNT",
]


def _value_at_level(
    val: float | tuple[float, ...],
    level: int,
    level_scaled: bool,
    *,
    key: str | None = None,
    rank_scaled: bool = False,
) -> float:
    """Resolve a grant value at the champion level.

    ``rank_scaled`` (item 267): ``val`` is a per-ABILITY-RANK tuple (the grant
    value lives in a parsed Meraki ``[other]`` block indexed by ability rank,
    NOT by champion level). The ability rank is resolved from the champion level
    via ``ability_dps.rank_at_level(key, level)`` - deterministic for ults
    (R unlocks 6/11/16), engine-default skill priority (Q>W>E) for basics. An
    unlearned ability (rank ``-1``) grants 0.0.

    ``level_scaled`` value carries a per-CHAMPION-LEVEL tuple (``_lerp_per_level``)
    read at ``level-1`` (clamped). A flat value is its float. (``rank_scaled`` and
    ``level_scaled`` are mutually exclusive; rank is checked first.)
    """
    if rank_scaled and isinstance(val, (tuple, list)):
        if not val:
            return 0.0
        # Function-level import to dodge the ability_dps <-> ehp module cycle
        # (same break pattern as items 235/257).
        from .ability_dps import rank_at_level
        rank = rank_at_level(str(key or ""), int(level))
        if rank < 0:
            return 0.0  # ability not yet learned at this level
        idx = max(0, min(rank, len(val) - 1))
        return float(val[idx])
    if level_scaled and isinstance(val, (tuple, list)):
        if not val:
            return 0.0
        idx = max(0, min(int(level) - 1, len(val) - 1))
        return float(val[idx])
    if isinstance(val, (tuple, list)):
        # Defensive: a tuple on a non-scaled entry resolves at its first.
        return float(val[0]) if val else 0.0
    return float(val)


def resist_grants(
    champion_id: str,
    level: int,
    apply_passive_resist: bool,
    *,
    total_armor: float = 0.0,
    total_mr: float = 0.0,
    base_armor: float = 0.0,
    base_mr: float = 0.0,
) -> tuple[float, float]:
    """Return ``(bonus_armor, bonus_mr)`` from effects-text resist grants.

    Sums, over every registered grant matching ``champion_id``:
      - the FLAT-ADD half (item 264/267): ``value(level) * prob``.
      - the PERCENT-OF-RESIST half (item 268): ``(pct(level)/100) * resist * prob``
        where ``resist`` is ``total_armor`` / ``total_mr`` for ``pct_base="total"``
        or the build BONUS (``max(0, total - base)``) for ``pct_base="bonus"``.
      - the PER-STACK UNBOUNDED half (item 272): ``per_stack_* * assumed_stacks *
        prob`` (Thresh souls - a flat coefficient times the assumed steady-state
        count; default 0.0 leaves flat/percent entries unchanged).

    The resolved build resists (``total_*`` / ``base_*``) are keyword-only with
    0.0 defaults so a legacy positional call (the item 264/267 tests) returns the
    flat-add half unchanged and any percent entry contributes 0.0 (percent * 0).
    Only ``compute_ehp`` passes the build resists, so the percent half fires only
    on the live EHP path. When ``apply_passive_resist`` is False (the default) both
    are 0.0 - the EHP math is byte-identical.

    The percent multiplies the RESOLVED build resist (which excludes these passive
    grants - they are not in base/items), so there is NO self-feedback loop.

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
    build_bonus_armor = max(0.0, float(total_armor) - float(base_armor))
    build_bonus_mr = max(0.0, float(total_mr) - float(base_mr))
    for (entry_cid, _key, _form), entry in _PASSIVE_RESIST_OVERRIDES.items():
        if entry_cid != cid:
            continue
        prob = float(entry.conditional_probability)
        a = _value_at_level(
            entry.armor, lvl, entry.level_scaled,
            key=_key, rank_scaled=entry.rank_scaled,
        )
        m = _value_at_level(
            entry.mr, lvl, entry.level_scaled,
            key=_key, rank_scaled=entry.rank_scaled,
        )
        bonus_armor += a * prob
        bonus_mr += m * prob
        # item 268: percent-of-resist half (multiplies the resolved build resist).
        if entry.armor_pct or entry.mr_pct:
            res_a = float(total_armor) if entry.pct_base == "total" else build_bonus_armor
            res_m = float(total_mr) if entry.pct_base == "total" else build_bonus_mr
            pa = _value_at_level(
                entry.armor_pct, lvl, entry.level_scaled,
                key=_key, rank_scaled=entry.rank_scaled,
            )
            pm = _value_at_level(
                entry.mr_pct, lvl, entry.level_scaled,
                key=_key, rank_scaled=entry.rank_scaled,
            )
            bonus_armor += (pa / 100.0) * res_a * prob
            bonus_mr += (pm / 100.0) * res_m * prob
        # item 272: per-stack UNBOUNDED half (flat coefficient * assumed count).
        if entry.per_stack_armor or entry.per_stack_mr:
            n = float(entry.assumed_stacks)
            bonus_armor += float(entry.per_stack_armor) * n * prob
            bonus_mr += float(entry.per_stack_mr) * n * prob
    return bonus_armor, bonus_mr
