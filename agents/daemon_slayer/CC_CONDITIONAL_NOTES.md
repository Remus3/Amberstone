# cc_conditional registry - authoring source + REJECT rationale (pre-A3 archive)

The conditional-CC registry data now lives in
`cc_conditional_registry.json` (loaded by `_build_per_spell_cc_conditional`
+ `_build_per_spell_cc_conditional_forms` in `cc_conditional.py`). The two
hand-authored builder functions below were relocated here VERBATIM by the
item-245 A3 externalization (zero token loss, mirrors the item-241 A1
`__init__.py` -> `CHANGELOG.md` relocation). They are the canonical record of
every entry's construction, the wave-by-wave history, and the interspersed
REJECT rationale (champions considered and NOT added per wave). This file is
documentation only - it is NOT imported or executed; the live registry is the
JSON. New entries are hand-added to the JSON (the `ConditionalCcEntry`
`__post_init__` validates them at load); record their rationale here.

## _build_per_spell_cc_conditional (primary registry, verbatim pre-A3)

```python
def _build_per_spell_cc_conditional() -> Dict[str, Dict[str, ConditionalCcEntry]]:
    """Build the conditional CC registry.

    Uses ``registry.setdefault(champion, {})[spell] = entry`` pattern
    so multi-wave additions never clobber prior entries (mirrors the
    wave-6 schema lift from item 140 in ``ability_dps.py``).

    Seed: 10 canonical examples from the wave 4/5/6 REJECT lists in
    CLAUDE.md items 138/139/140. Wave 1 expansion (item 142) added
    +8 entries / +8 champs (10/10 -> 18/18). Wave 2 (item 143) added
    +5 entries / +5 champs (18/18 -> 23/23). Wave 3 (item 144) added
    +5 entries / +5 champs (23/23 -> 28/28). Wave 4 (item 145) added
    +5 entries / +4 champs + 1 multi-wave coexistence (28/28 ->
    33/32). Wave 5 (item 146) added +2 entries / 0 net-new champs
    via multi-wave coexistence on Briar + TahmKench (33/32 -> 35/32).
    Wave 6 (this run) adds +1 entry / 0 net-new champs via multi-
    wave coexistence on Brand (35/32 -> 36/32). Future waves populate
    further as consumer logic ships and operator-calibrates
    probabilities.

    Per-entry probabilities pass through ``_p(champion, spell, default)``
    which honors any ``per_entry_probability`` override loaded from
    ``data/cc_conditional_calibration.json``. Default is the canonical
    seed value (or tag midpoint if the seed picks the midpoint).
    """
    registry: Dict[str, Dict[str, ConditionalCcEntry]] = {}

    def _p(champion: str, spell: str, default: float) -> float:
        """Resolve per-entry probability with operator override.

        Reads ``_PER_ENTRY_PROBABILITY_OVERRIDES.get((champion, spell), default)``
        so the operator's calibration JSON file flows through to every
        registered entry without per-entry boilerplate.
        """
        return _PER_ENTRY_PROBABILITY_OVERRIDES.get((champion, spell), default)

    # === seed wave 1 - canonical examples from wave 4/5/6 REJECTs ===

    # Brand R Pyroclasm: the R bounces; landing 3rd Blaze stack from
    # passive triggers a 2.0s stun. Conditional on 3 stacks of Blaze
    # accumulated within the fight window.
    registry.setdefault("Brand", {})["R"] = ConditionalCcEntry(
        champion="Brand",
        spell="R",
        cc_kind="stun",
        durations_s=(2.0,),
        condition=COND_NTH_HIT,
        probability=_p("Brand", "R", 0.7),
        notes=(
            "Brand passive Blaze stuns target at 3 stacks (2.0s); R "
            "Pyroclasm bounces multiple times so it is the most likely "
            "source of 3-stack saturation in a teamfight."
        ),
    )

    # Twisted Fate W Pick a Card: cycles Red / Yellow / Blue. Yellow
    # (Gold) Card stuns 1.5s. Probability is mid-low because TF must
    # pre-cycle to Gold before the fight.
    registry.setdefault("TwistedFate", {})["W"] = ConditionalCcEntry(
        champion="TwistedFate",
        spell="W",
        cc_kind="stun",
        durations_s=(1.5,),
        condition=COND_GOLD_CARD,
        probability=_p("TwistedFate", "W", 0.4),
        notes=(
            "Pick a Card cycles R/Y/B; Gold (Yellow) stuns 1.5s. "
            "Probability assumes TF locks Gold before engage; not all "
            "fights start with W pre-loaded."
        ),
    )

    # Jarvan IV E + Q combo: E Demacian Standard + Q Dragon Strike
    # creates a knock-up. Standalone Q is a dash + slow; the EQ combo
    # is the knock-up. Conditional on Jarvan placing his flag in line
    # with his target before pulling.
    registry.setdefault("JarvanIV", {})["E"] = ConditionalCcEntry(
        champion="JarvanIV",
        spell="E",
        cc_kind="knockup",
        durations_s=(1.0,),
        condition=COND_TERRAIN,
        probability=_p("JarvanIV", "E", 0.5),
        notes=(
            "E places flag; Q dashes to flag and knocks enemies up "
            "1.0s along the path. Conditional on flag-placement "
            "preceding Q within a teamfight setup."
        ),
    )

    # Tahm Kench R Devour: requires 3 Q stacks on the enemy first.
    # Devoured enemies are effectively suppressed (cannot act) for
    # ~1.0s. Probability is mid-low because the 3-stack precondition
    # is rare against mobile or high-range targets.
    registry.setdefault("TahmKench", {})["R"] = ConditionalCcEntry(
        champion="TahmKench",
        spell="R",
        cc_kind="suppression",
        durations_s=(1.0,),
        condition=COND_DEVOUR_TARGET,
        probability=_p("TahmKench", "R", 0.4),
        notes=(
            "Devour requires 3 stacks of Tongue Lash (Q) on the enemy. "
            "While devoured, target is effectively suppressed; can be "
            "spat or held. Probability assumes Tahm setup time."
        ),
    )

    # Volibear Q Thundering Smash: dash + slow normally; if Voli
    # collides with terrain or a wall, the enemy is knocked aside
    # ~0.75s. Requires Voli to dash toward terrain with target in
    # line.
    registry.setdefault("Volibear", {})["Q"] = ConditionalCcEntry(
        champion="Volibear",
        spell="Q",
        cc_kind="knockback",
        durations_s=(0.75,),
        condition=COND_TERRAIN,
        probability=_p("Volibear", "Q", 0.3),
        notes=(
            "Q dashes; if collision with terrain occurs while target "
            "is hit, target is knocked aside 0.75s. Standalone Q is "
            "slow only; the conditional bump requires positioning."
        ),
    )

    # Warwick R Infinite Duress: full-channel suppression on a single
    # target. Channel duration = R duration; cleanseable, can be
    # interrupted by hard CC mid-channel. Probability mid because not
    # all R casts complete the channel.
    registry.setdefault("Warwick", {})["R"] = ConditionalCcEntry(
        champion="Warwick",
        spell="R",
        cc_kind="suppression",
        durations_s=(1.5, 1.75, 2.0),
        condition=COND_CHANNEL_COMPLETION,
        probability=_p("Warwick", "R", 0.5),
        notes=(
            "R suppresses target for channel duration. Cleanseable; "
            "interruptible by hard CC on Warwick. Probability assumes "
            "average teamfight where R lands but may be interrupted."
        ),
    )

    # Viktor W Gravity Field: creates a field; enemies in the field
    # gain stacks per tick; at 3 stacks, the enemy is stunned 1.5s.
    # Conditional on the enemy remaining in the field long enough to
    # accumulate 3 stacks (about 1.5s in-field).
    registry.setdefault("Viktor", {})["W"] = ConditionalCcEntry(
        champion="Viktor",
        spell="W",
        cc_kind="stun",
        durations_s=(1.5,),
        condition=COND_NTH_HIT,
        probability=_p("Viktor", "W", 0.6),
        notes=(
            "Field deals slow + stacks; enemy at 3 stacks (~1.5s in "
            "field) is stunned 1.5s. Probability assumes Viktor zones "
            "the field correctly + enemy fails to flash out."
        ),
    )

    # Mordekaiser R Realm of Death: isolates target in a separate
    # plane for 7s (rank-independent on duration; rank scales stat-
    # steal). Banishment is not direct CC but the enemy is removed
    # from the main fight, which the EHP-vs-CC scorer should credit.
    # Conditional on the R landing (mode-gated = always-on when cast
    # in a mode that supports R cast - here just confirming the cast
    # itself lands).
    registry.setdefault("Mordekaiser", {})["R"] = ConditionalCcEntry(
        champion="Mordekaiser",
        spell="R",
        cc_kind="banishment",
        durations_s=(7.0,),
        condition=COND_MODE_GATED,
        probability=_p("Mordekaiser", "R", 1.0),
        notes=(
            "Banishes target to Death Realm 7s on cast. Once cast and "
            "landed, banishment is unconditional; probability=1.0. The "
            "operator cannot engage the rest of the team during this "
            "window which the scorer should credit."
        ),
    )

    # Sett E Facebreaker: pulls enemies on both sides toward each
    # other. If at least 2 enemies are caught and snapped together,
    # they are stunned 1.0s. Standalone E with 1 enemy is a slow only.
    registry.setdefault("Sett", {})["E"] = ConditionalCcEntry(
        champion="Sett",
        spell="E",
        cc_kind="stun",
        durations_s=(1.0,),
        condition=COND_DUAL_ENEMY,
        probability=_p("Sett", "E", 0.6),
        notes=(
            "E pulls enemies inward; stuns 1.0s only when 2+ enemies "
            "are caught and snap together. Teamfight conditional; in "
            "1v1 the E is slow only."
        ),
    )

    # Vex E Personal Space + R Shadow Surge: R marks target with
    # Doom; subsequent ally damage triggers a fear ~1.25s. Modeled
    # here on E because that is the trigger surface; Doom mark itself
    # is from R passive + R cast.
    registry.setdefault("Vex", {})["E"] = ConditionalCcEntry(
        champion="Vex",
        spell="E",
        cc_kind="fear",
        durations_s=(1.0, 1.125, 1.25, 1.375, 1.5),
        condition=COND_TARGET_DEBUFFED,
        probability=_p("Vex", "E", 0.5),
        notes=(
            "Personal Space deals damage + applies fear when target is "
            "Doom-marked (from R or passive). Standalone E is damage "
            "only; the fear requires the Doom mark."
        ),
    )

    # ============================================================
    # === wave 1 expansion (2026-05-22) - 8 entries / 8 new champs
    # === Drawn from wave 4/5/6/7 REJECT lists in CLAUDE.md items
    # === 138/139/140/141. Uses only existing condition tags - no
    # === new tag constants (operator-gated). Conservative per-entry
    # === probabilities, defaulting to tag midpoint unless mechanic
    # === justifies departure.
    # ============================================================

    # Bard Q Cosmic Binding: ranged skillshot that stuns first target
    # only if it bounces off a wall OR passes through a second enemy.
    # Single-target line-up with no wall behind = damage + slow only.
    # The wall-bounce / dual-enemy stun is positioning-conditional;
    # using COND_TERRAIN as the primary tag since wall geometry is the
    # most common bounce trigger.
    registry.setdefault("Bard", {})["Q"] = ConditionalCcEntry(
        champion="Bard",
        spell="Q",
        cc_kind="stun",
        durations_s=(1.5, 1.75, 2.0, 2.25, 2.5),
        condition=COND_TERRAIN,
        probability=_p("Bard", "Q", 0.3),
        notes=(
            "Q stuns on bounce off wall or pass-through second target. "
            "Single-target hit with no wall behind is slow-only. "
            "Terrain-positioning conditional; probability mid-low "
            "because Bard must aim into geometry."
        ),
    )

    # Karma W Focused Resolve: tether + delayed root. If the tether
    # is maintained for the full duration (Karma stays in range +
    # target does not break LoS), target is rooted for the rank
    # duration. Cleanseable by movement / dash / LoS break, so
    # mid-probability.
    registry.setdefault("Karma", {})["W"] = ConditionalCcEntry(
        champion="Karma",
        spell="W",
        cc_kind="root",
        durations_s=(1.5, 1.625, 1.75, 1.875, 2.0),
        condition=COND_CHANNEL_COMPLETION,
        probability=_p("Karma", "W", 0.4),
        notes=(
            "W tethers target; root fires only if tether persists for "
            "the full channel (~2s). Movement / dash / LoS break can "
            "cancel; probability mid-low vs full midpoint because tether "
            "is frequently cancelled in fights."
        ),
    )

    # Taliyah W Seismic Shove: places a delayed shove zone; the zone
    # fires after a short delay (~1s). Standalone W on cast is a slow.
    # The knockup direction depends on Taliyah's recast input within
    # the delay window. Recast-during-delay is the trigger surface.
    registry.setdefault("Taliyah", {})["W"] = ConditionalCcEntry(
        champion="Taliyah",
        spell="W",
        cc_kind="knockup",
        durations_s=(0.75,),
        condition=COND_CHANNEL_COMPLETION,
        probability=_p("Taliyah", "W", 0.5),
        notes=(
            "W zone fires after delay; knockup direction set by "
            "Taliyah's recast input. Single value 0.75s across all "
            "ranks. Probability midpoint - recast cadence varies."
        ),
    )

    # Kennen E Lightning Rush: damage + speed dash, applies Mark of
    # the Storm stack on each champion hit (passive). At 3 stacks the
    # target is stunned 1.25s. E is a key applicator - mark stack
    # accumulation via Q + W + E + auto-attack is the nth_hit gate.
    registry.setdefault("Kennen", {})["E"] = ConditionalCcEntry(
        champion="Kennen",
        spell="E",
        cc_kind="stun",
        durations_s=(1.25,),
        condition=COND_NTH_HIT,
        probability=_p("Kennen", "E", 0.6),
        notes=(
            "E applies Mark of the Storm. At 3 stacks (Q + W + E + AA "
            "combo or similar) target is stunned 1.25s. E is the mid-"
            "fight applicator; probability mid because Kennen needs "
            "full combo to land the third stack."
        ),
    )

    # KSante Q Ntofo Strikes: 3-cast spell where the 3rd cast roots.
    # First 2 casts are damage + slow only. The 3-cast cycle within
    # a fight window is the nth_hit trigger. KSante R already in
    # unconditional wave-5 registry - this Q coexists on same champ.
    registry.setdefault("KSante", {})["Q"] = ConditionalCcEntry(
        champion="KSante",
        spell="Q",
        cc_kind="root",
        durations_s=(0.75,),
        condition=COND_NTH_HIT,
        probability=_p("KSante", "Q", 0.7),
        notes=(
            "Q is a 3-cast cycle; 3rd cast roots for 0.75s. First 2 "
            "casts are damage + slow only. 3-cast achievability is "
            "high in a 6s fight given Q's short cooldown."
        ),
    )

    # Ornn Q Volcanic Rupture: damage + slow on direct cast.
    # Knockup-on-Brittle-stack target if Ornn has applied Brittle
    # (from auto-attack passive or W damage). Brittle pre-application
    # is the debuff prerequisite. Ornn R already in unconditional
    # wave-7 registry; Q coexists on same champ via setdefault.
    registry.setdefault("Ornn", {})["Q"] = ConditionalCcEntry(
        champion="Ornn",
        spell="Q",
        cc_kind="knockup",
        durations_s=(1.5,),
        condition=COND_TARGET_DEBUFFED,
        probability=_p("Ornn", "Q", 0.5),
        notes=(
            "Q knocks up only when target has Brittle stack from auto "
            "or W. Standalone Q is damage + slow. Probability midpoint "
            "because Brittle application is part of Ornn fight rhythm."
        ),
    )

    # Xayah E Bladecaller: recall feathers from Q / R / auto-attack;
    # feathers root if 3+ feathers hit the same target in the recall.
    # 1 or 2 feathers = damage only. Multi-feather hit requires Xayah
    # to set up the feather pattern via Q + auto-attacks first.
    registry.setdefault("Xayah", {})["E"] = ConditionalCcEntry(
        champion="Xayah",
        spell="E",
        cc_kind="root",
        durations_s=(1.25,),
        condition=COND_NTH_HIT,
        probability=_p("Xayah", "E", 0.6),
        notes=(
            "E recalls feathers; root fires only if 3+ feathers hit "
            "the same target. 1-2 feather hit is damage only. Probability "
            "mid because feather setup needs prior Q + auto chain."
        ),
    )

    # Fiora W Riposte: parries the next champion ability or auto-attack
    # within a 0.75s window. If the parry blocks an enemy ability /
    # auto, the enemy is stunned (or slowed) for 1.5s. Standalone W
    # with no enemy ability incoming is a pure spell-shield with no
    # stun on Fiora's targets. The stun fires only when the enemy is
    # actively attacking through the parry window (debuffed = enemy
    # casting state).
    registry.setdefault("Fiora", {})["W"] = ConditionalCcEntry(
        champion="Fiora",
        spell="W",
        cc_kind="stun",
        durations_s=(1.5,),
        condition=COND_TARGET_DEBUFFED,
        probability=_p("Fiora", "W", 0.4),
        notes=(
            "W parries within a 0.75s window; if it blocks an enemy "
            "champion ability or AA, target is stunned 1.5s. Parry "
            "outcome depends on enemy cast timing into Fiora's window; "
            "probability mid-low because parry timing is hard."
        ),
    )

    # ============================================================
    # === wave 2 expansion (2026-05-22) - 5 entries / 5 new champs
    # === Drawn from wave 4/5/6/7 REJECT lists across items
    # === 138/139/140/141 + the wave 1 REJECT carry-forward in
    # === item 142. Uses only existing condition tags - no new tag
    # === constants (operator-gated). Conservative per-entry
    # === probabilities, defaulting to tag midpoint unless mechanic
    # === justifies departure.
    # ============================================================

    # Maokai Q Bramble Smash: dash + knockback line. Base hit is a
    # short knockback (~0.25s); if the target is pushed into terrain,
    # the impact extends into a ~1.0s stun. Standalone hit with no
    # terrain behind the target = damage + brief knockback only.
    # Terrain-positioning conditional with low probability because
    # operator must aim into geometry.
    registry.setdefault("Maokai", {})["Q"] = ConditionalCcEntry(
        champion="Maokai",
        spell="Q",
        cc_kind="stun",
        durations_s=(1.0,),
        condition=COND_TERRAIN,
        probability=_p("Maokai", "Q", 0.3),
        notes=(
            "Q knocks back; if target collides with terrain, stun "
            "extends to ~1.0s. Standalone hit with no wall behind is "
            "brief knockback only. Terrain-positioning conditional; "
            "probability mid-low because aim is geometry-dependent."
        ),
    )

    # Pyke E Phantom Undertow: Pyke dashes leaving a knife behind; the
    # knife returns to Pyke after a delay (~1.25s) and stuns enemies it
    # passes through for the rank duration. Standalone dash with no
    # return path through enemies = damage on dash only. The stun
    # fires only when the return-path completes through a target.
    # Channel-completion conditional (the recall delay must elapse).
    registry.setdefault("Pyke", {})["E"] = ConditionalCcEntry(
        champion="Pyke",
        spell="E",
        cc_kind="stun",
        durations_s=(1.25,),
        condition=COND_CHANNEL_COMPLETION,
        probability=_p("Pyke", "E", 0.5),
        notes=(
            "E leaves a knife on dash path; knife returns ~1.25s post-"
            "cast and stuns enemies it passes through for the rank "
            "duration. Channel-completion conditional; mid probability "
            "because return path is predictable but dodgeable."
        ),
    )

    # Swain E Nevermove: launches a damage zone outward; the zone then
    # returns to Swain along the same line. Targets hit by the RETURN
    # wave are rooted for the rank duration. Outbound hit is damage
    # only. Channel-completion conditional - the return wave only fires
    # if Swain remains stationary + the wave is not cleansed mid-flight.
    registry.setdefault("Swain", {})["E"] = ConditionalCcEntry(
        champion="Swain",
        spell="E",
        cc_kind="root",
        durations_s=(1.5, 1.625, 1.75, 1.875, 2.0),
        condition=COND_CHANNEL_COMPLETION,
        probability=_p("Swain", "E", 0.5),
        notes=(
            "E damage zone returns to Swain; targets hit by RETURN "
            "wave rooted 1.5-2.0s across ranks. Outbound hit is damage "
            "only. Channel-completion conditional - return path takes "
            "~1.5s + dodgeable; probability midpoint."
        ),
    )

    # Skarner Q Shattered Earth / Upheaval: Q has 3 charges. The 3rd
    # cast in the cycle creates a terrain pillar; enemies caught
    # between Skarner's path + the pillar are knocked up ~0.75s.
    # First 2 casts are damage only. nth_hit conditional on the 3-cast
    # cycle completing within the fight window.
    registry.setdefault("Skarner", {})["Q"] = ConditionalCcEntry(
        champion="Skarner",
        spell="Q",
        cc_kind="knockup",
        durations_s=(0.75,),
        condition=COND_NTH_HIT,
        probability=_p("Skarner", "Q", 0.7),
        notes=(
            "Q is a 3-charge cycle; 3rd cast creates terrain pillar + "
            "knocks up 0.75s. First 2 casts are damage only. 3-cycle "
            "achievability is high given Q's low cooldown."
        ),
    )

    # Zilean Q Time Bomb: places delayed bomb that detonates ~3s
    # later. If 2 bombs land on the same target before either
    # detonates, both detonate immediately + stun the target 2.0s.
    # Single-bomb hit is damage only. nth_hit conditional on the
    # 2-bomb stack landing on the same enemy in sequence.
    registry.setdefault("Zilean", {})["Q"] = ConditionalCcEntry(
        champion="Zilean",
        spell="Q",
        cc_kind="stun",
        durations_s=(2.0,),
        condition=COND_NTH_HIT,
        probability=_p("Zilean", "Q", 0.7),
        notes=(
            "Q places delayed bomb (3s); if 2 bombs land on same target "
            "before either detonates, both pop + target stunned 2.0s. "
            "Single bomb is damage only. 2-stack achievability high in "
            "a 6s fight with Q cooldown reset."
        ),
    )

    # ============================================================
    # === wave 3 expansion (2026-05-22) - 5 entries / 5 new champs
    # === 4 of 5 entries are 3-cast Q-cycle terminal knockups
    # === (Aatrox / Riven / Yasuo / Yone) sourced via the durable
    # === multi-cast windup pattern at 16.10.1. The 5th is the
    # === Leblanc full-tether root (Karma W parallel). All entries
    # === re-use existing condition tags; no new tag constants.
    # === None of the wave 3 champions appear in waves 1/2 or in
    # === the unconditional ``_PER_SPELL_CC_DURATIONS`` registry
    # === for their wave-3 spell slot (Riven W is unconditional
    # === but Riven Q is the wave-3 conditional slot; Renekton W
    # === / Camille E base-stun extension paths were intentionally
    # === REJECTED to keep wave 3 entries semantically symmetric
    # === to existing entries which encode full conditional CC
    # === durations rather than over-base extensions).
    # ============================================================

    # Aatrox Q3 The Darkin Blade sweetspot knockup: Q is a 3-cast
    # cycle (line / cone / circle). The 3rd cast's inner sweetspot
    # circle deals bonus damage AND knocks up enemies inside it for
    # 0.5s. Outside the sweetspot ring on cast 3 = damage + brief
    # knockback (not first-order CC). nth_hit conditional on the
    # 3-cycle reaching cast 3 within the fight window. Aatrox has
    # no unconditional ``_PER_SPELL_CC_DURATIONS`` entry today; this
    # is the first registered Aatrox first-order CC.
    registry.setdefault("Aatrox", {})["Q"] = ConditionalCcEntry(
        champion="Aatrox",
        spell="Q",
        cc_kind="knockup",
        durations_s=(0.5,),
        condition=COND_NTH_HIT,
        probability=_p("Aatrox", "Q", 0.7),
        notes=(
            "Q is a 3-cast cycle; 3rd cast's inner sweetspot circle "
            "knocks up enemies hit for 0.5s. Outside the sweetspot is "
            "damage + brief knockback (not first-order CC). 3-cycle "
            "achievability high in a 6s fight given Q's short windup "
            "between casts."
        ),
    )

    # Riven Q3 Broken Wings third-dash terminal knockup: Q is a
    # 3-dash cycle. The 3rd dash ends with a small AOE knockup of
    # 0.75s on impact. Casts 1 + 2 are damage + dash only. nth_hit
    # conditional on the 3-cycle reaching cast 3. Riven W is the
    # unconditional stun (already in ``_PER_SPELL_CC_DURATIONS``);
    # Riven Q (this wave 3) is the conditional knockup that coexists
    # on the same champion via setdefault.
    registry.setdefault("Riven", {})["Q"] = ConditionalCcEntry(
        champion="Riven",
        spell="Q",
        cc_kind="knockup",
        durations_s=(0.75,),
        condition=COND_NTH_HIT,
        probability=_p("Riven", "Q", 0.7),
        notes=(
            "Q is a 3-dash cycle; 3rd dash impact AOE knocks up "
            "enemies 0.75s. Casts 1 + 2 are damage + dash only. "
            "3-cycle achievability high given Q's short cooldown "
            "and dash reset cadence."
        ),
    )

    # Yasuo Q3 Steel Tempest tornado knockup: Q is a 3-cast cycle
    # (line slash x2 + ranged tornado). The 3rd cast becomes a
    # ranged tornado that knocks up enemies hit for 1.0s. Casts 1
    # + 2 are damage + brief knockback (single-target dash). nth_hit
    # conditional on the 3-cycle reaching cast 3 within the fight
    # window. Yasuo R is the unconditional knockup (already in
    # ``_PER_SPELL_CC_DURATIONS``); Yasuo Q (this wave 3) is the
    # conditional knockup that coexists on the same champion via
    # setdefault.
    registry.setdefault("Yasuo", {})["Q"] = ConditionalCcEntry(
        champion="Yasuo",
        spell="Q",
        cc_kind="knockup",
        durations_s=(1.0,),
        condition=COND_NTH_HIT,
        probability=_p("Yasuo", "Q", 0.7),
        notes=(
            "Q is a 3-cast cycle; 3rd cast becomes a ranged tornado "
            "that knocks up enemies hit for 1.0s. Casts 1 + 2 are "
            "damage only (no first-order CC). 3-cycle achievability "
            "high in a 6s fight given Q is core combo + bonus AS "
            "from passive."
        ),
    )

    # Yone Q3 Mortal Steel tornado knockup: mirror of Yasuo Q
    # mechanic. Q is a 3-cast cycle; 3rd cast becomes a ranged
    # tornado that knocks up enemies hit for 0.75s (Yone's tornado
    # is slightly shorter knockup than Yasuo's). Casts 1 + 2 are
    # damage only. Yone R is the unconditional knockup (already in
    # ``_PER_SPELL_CC_DURATIONS``); Yone Q (this wave 3) is the
    # conditional knockup that coexists on the same champion via
    # setdefault.
    registry.setdefault("Yone", {})["Q"] = ConditionalCcEntry(
        champion="Yone",
        spell="Q",
        cc_kind="knockup",
        durations_s=(0.75,),
        condition=COND_NTH_HIT,
        probability=_p("Yone", "Q", 0.7),
        notes=(
            "Q is a 3-cast cycle mirror of Yasuo's; 3rd cast becomes "
            "a ranged tornado that knocks up enemies hit for 0.75s. "
            "Casts 1 + 2 are damage only (no first-order CC). 3-cycle "
            "achievability high given Q's short cooldown."
        ),
    )

    # Leblanc E Ethereal Chains full-tether root: E projectile
    # applies a tether debuff on hit. If the tether persists for
    # the full duration (~1.5s) without Leblanc breaking range or
    # the target breaking LoS, target is rooted for 1.5s. Tether-
    # breaking = damage only (no first-order CC). channel_completion
    # conditional (the tether duration is the channel). Mirrors the
    # Karma W full-tether pattern from wave 1. Leblanc has no
    # unconditional ``_PER_SPELL_CC_DURATIONS`` entry today; this is
    # the first registered Leblanc first-order CC.
    registry.setdefault("Leblanc", {})["E"] = ConditionalCcEntry(
        champion="Leblanc",
        spell="E",
        cc_kind="root",
        durations_s=(1.5,),
        condition=COND_CHANNEL_COMPLETION,
        probability=_p("Leblanc", "E", 0.5),
        notes=(
            "E applies tether on hit; root fires only if tether "
            "persists for the full duration (~1.5s) without Leblanc "
            "leaving range or target breaking LoS. Tether-breaking = "
            "damage only. Probability midpoint matches the Karma W "
            "full-tether pattern from wave 1; tether is frequently "
            "cancelled in mid-fight."
        ),
    )

    # ============================================================
    # === wave 4 expansion (2026-05-22) - 5 entries / 4 new champs
    # === + 1 multi-wave coexistence (Aatrox W chain-root coexists
    # === with Aatrox Q3 knockup from wave 3). Uses only the 10
    # === existing condition tags - no new tag constants.
    # === Conservative per-entry probabilities, defaulting to tag
    # === midpoint unless mechanic justifies departure.
    # === REJECTs documented in commit body: Senna W (already
    # === unconditional wave 1), Aurora E (mechanic-uncertain at
    # === 16.10.1), Briar W / Naafiri R / Akali R / Jhin R / Pyke R
    # === / Sett R (no first-order CC), Heimerdinger R-Q (no
    # === additional CC beyond base E already unconditional),
    # === Galio Q / Galio R (Galio W+E+R already unconditional),
    # === Lillia E + R (R already unconditional wave 6).
    # ============================================================

    # Nunu R Absolute Zero: 3s channel that on completion explodes
    # in an AOE, knocking up enemies caught in the radius for 0.5s.
    # Channel can be interrupted by hard CC OR Nunu moving out of
    # range; standalone partial-channel = damage only (no AOE
    # knockup). channel_completion conditional - the full 3s
    # channel is required for the knockup payload. Nunu has no
    # unconditional ``_PER_SPELL_CC_DURATIONS`` entry today; this
    # is the first registered Nunu first-order CC.
    registry.setdefault("Nunu", {})["R"] = ConditionalCcEntry(
        champion="Nunu",
        spell="R",
        cc_kind="knockup",
        durations_s=(0.5,),
        condition=COND_CHANNEL_COMPLETION,
        probability=_p("Nunu", "R", 0.5),
        notes=(
            "R is a 3s channel that explodes on completion + knocks "
            "up enemies in the AOE for 0.5s. Channel-interruption by "
            "hard CC or Nunu moving out of range cancels the knockup. "
            "Probability midpoint - channels are frequently cancelled "
            "in teamfights but Nunu can use terrain to break LoS."
        ),
    )

    # Yuumi Q Prowling Projectile: long-travel skillshot that roots
    # at max-distance impact. Short-range hit = damage only. The
    # root duration scales with distance traveled; at max travel the
    # root is 1.75s. channel_completion conditional - the projectile
    # must travel its full distance to apply the root. Yuumi has no
    # unconditional ``_PER_SPELL_CC_DURATIONS`` entry today; this
    # is the first registered Yuumi first-order CC.
    registry.setdefault("Yuumi", {})["Q"] = ConditionalCcEntry(
        champion="Yuumi",
        spell="Q",
        cc_kind="root",
        durations_s=(1.75,),
        condition=COND_CHANNEL_COMPLETION,
        probability=_p("Yuumi", "Q", 0.4),
        notes=(
            "Q is a long-travel skillshot; root fires only at max "
            "projectile distance for 1.75s. Short-range hit is damage "
            "only. Probability mid-low because Yuumi must aim from "
            "far back to land the max-distance root; teamfight "
            "positioning often does not allow this."
        ),
    )

    # Pantheon Q Comet Spear empowered: tap-cast Q is a short-range
    # damage spear; the long-cast (hold) empowered version becomes
    # a long-range thrown spear that stuns enemies hit for 1.0s.
    # Standalone tap-cast = damage only. channel_completion
    # conditional - the windup (charge-up to empowered cast) is the
    # channel that must complete to gain the stun payload. Pantheon
    # W is already in ``_PER_SPELL_CC_DURATIONS`` (unconditional
    # stun 1.0s); Pantheon Q (this wave 4) is the conditional
    # empowered-cast stun that coexists on the same champion via
    # setdefault on a different spell slot.
    registry.setdefault("Pantheon", {})["Q"] = ConditionalCcEntry(
        champion="Pantheon",
        spell="Q",
        cc_kind="stun",
        durations_s=(1.0,),
        condition=COND_CHANNEL_COMPLETION,
        probability=_p("Pantheon", "Q", 0.5),
        notes=(
            "Q tap-cast is a short-range damage spear; empowered "
            "long-cast (hold + release) becomes a long-range thrown "
            "spear with 1.0s stun on champion hit. channel_completion "
            "conditional - the windup-channel must complete. Coexists "
            "with Pantheon W unconditional stun on a different spell "
            "slot via setdefault."
        ),
    )

    # Aatrox W Infernal Chains: skillshot that hits + applies a
    # chain debuff on champion targets for 1.75s. If the target is
    # still inside the chain's zone when the duration expires, they
    # are rooted briefly + pulled back to the cast origin. The pull-
    # back movement IS the first-order CC; target who walks out of
    # the zone before the timer expires takes damage only. target_
    # debuffed conditional - the chain debuff must persist on the
    # target through the full 1.75s window. Aatrox Q (wave 3) is
    # the conditional knockup; Aatrox W (this wave 4) is the
    # conditional pull-back root that coexists on the same champion
    # via setdefault on a different spell slot.
    registry.setdefault("Aatrox", {})["W"] = ConditionalCcEntry(
        champion="Aatrox",
        spell="W",
        cc_kind="root",
        durations_s=(1.75,),
        condition=COND_TARGET_DEBUFFED,
        probability=_p("Aatrox", "W", 0.5),
        notes=(
            "W chain hits + applies chain debuff for 1.75s; if target "
            "is still inside the zone when timer expires, they are "
            "pulled back + briefly rooted. Walking out of the zone "
            "before expiry = damage + slow only. target_debuffed "
            "conditional - the chain debuff must persist through the "
            "full window. Coexists with Aatrox Q wave 3 conditional "
            "knockup on a different spell slot via setdefault."
        ),
    )

    # Briar Q Head Rush: dash to target dealing damage. If the
    # target is knocked into terrain at the end of the dash (or
    # Briar collides with terrain mid-dash) the target is stunned
    # for 1.0s. Standalone dash with no terrain in path = damage
    # only. terrain conditional - the terrain-positioning must
    # align with Briar's dash trajectory. Briar has no unconditional
    # ``_PER_SPELL_CC_DURATIONS`` entry today; this is the first
    # registered Briar first-order CC. (The Briar Q + R frenzy-
    # state-gated variants flagged in items 142/143 carry-forwards
    # still require a new condition tag schema lift - not landed
    # here. This entry encodes the terrain-only path.)
    registry.setdefault("Briar", {})["Q"] = ConditionalCcEntry(
        champion="Briar",
        spell="Q",
        cc_kind="stun",
        durations_s=(1.0,),
        condition=COND_TERRAIN,
        probability=_p("Briar", "Q", 0.3),
        notes=(
            "Q dash; if target is knocked into terrain at end of dash, "
            "stun 1.0s. No-terrain hit is damage only. terrain "
            "conditional. Frenzy-state-gated variants (Q+R during "
            "Frenzy) carry forward operator-gated - they need a new "
            "condition tag schema lift not in this wave."
        ),
    )

    # ============================================================
    # === wave 5 expansion (2026-05-22) - 2 entries / 2 new champs
    # === for the conditional registry (Briar gets a SECOND spell
    # === slot E coexisting with wave 4 Q; TahmKench gets a SECOND
    # === spell slot Q coexisting with wave 0 R devour). Uses only
    # === the 10 existing condition tags - no new tag constants.
    # === Drawn from carries: Briar W frenzy carry (item 144) which
    # === pointed at E as a non-frenzy-gated alternative, plus the
    # === TahmKench passive-stack chain (item 142+) re-examined as
    # === Q-application stun rather than passive-only encoding.
    # === REJECTs documented in commit body: Vayne E wall-stun
    # === (would clobber unconditional knockback on same slot;
    # === schema lift needed); Trundle E displacement (no clean
    # === tag fit since Trundle CREATES the terrain); Mel E Solar
    # === Snare (not Meraki-verified at 16.10.1; needs reverify);
    # === Annie passive Pyromania (the next-cast stun lands on Q/W/R,
    # === not a discrete spell slot - encoding ambiguous); Belveth
    # === W Above and Below (slow only, no first-order CC verified
    # === in 16.10.1 ability data); Naafiri R / Akali R / Jhin R /
    # === Pyke R / Sett R / Sett W (no CC verified per prior REJECTs);
    # === Cho'Gath W Feral Scream (unconditional silence - belongs
    # === in unconditional registry, not conditional); Singed W /
    # === Aphelios Q / Lillia Q / Akshan Q / Ekko W coexistence
    # === clobbers (E or W slot already in unconditional registry).
    # === Briar W + R frenzy variants STILL operator-gated (need
    # === new COND_FRENZY_STATE tag schema lift).
    # ============================================================

    # Briar E Chilling Scream: channeled scream that charges over
    # ~1.5s. Tap-cast at zero charge deals damage + slow only with
    # no first-order CC. Full-charge release fears enemies in a
    # cone for ~1.0s + deals heavy damage. channel_completion
    # conditional - the charge-channel must complete to gain the
    # fear payload. Briar Q (wave 4) is the terrain-conditional
    # stun; Briar E (this wave 5) is the channel-completion fear
    # that coexists on the same champion via setdefault on a
    # different spell slot. SECOND multi-wave coexistence in the
    # cc_conditional registry (after Aatrox Q3 + W from waves 3+4).
    # The Briar W + R frenzy-state-gated variants from item 144
    # carry-forward STILL require new COND_FRENZY_STATE tag schema
    # lift - not in this wave.
    registry.setdefault("Briar", {})["E"] = ConditionalCcEntry(
        champion="Briar",
        spell="E",
        cc_kind="fear",
        durations_s=(1.0,),
        condition=COND_CHANNEL_COMPLETION,
        probability=_p("Briar", "E", 0.5),
        notes=(
            "E is a charged scream; full-charge release fears "
            "enemies in cone for 1.0s. Tap-cast is damage + slow "
            "only (no first-order CC). channel_completion conditional "
            "- the charge-channel must complete to gain the fear "
            "payload. Coexists with Briar Q wave 4 terrain-stun on a "
            "different spell slot via setdefault."
        ),
    )

    # TahmKench Q Tongue Lash: applies 1 stack of passive 'An
    # Acquired Taste' on hit. At 3 stacks (from Q + AA + Q OR
    # Q + AA + AA OR similar 3-application chain) the target is
    # stunned for 1.5s. Q's own slow is the unconditional damage
    # surface; the 3rd-stack stun is the conditional first-order
    # CC. Encoding on Q because Q is the primary stack applicator
    # in the operator's typical combo (Q-AA-Q in fight = 3 stacks
    # achievable in fight window). nth_hit conditional with
    # probability 0.7 because Tahm's slow + reach makes the 3-cycle
    # achievable in a 6s window. TahmKench R (wave 0) is the
    # devour conditional; TahmKench Q (this wave 5) is the nth_hit
    # passive-stack stun that coexists on the same champion via
    # setdefault on a different spell slot.
    registry.setdefault("TahmKench", {})["Q"] = ConditionalCcEntry(
        champion="TahmKench",
        spell="Q",
        cc_kind="stun",
        durations_s=(1.5,),
        condition=COND_NTH_HIT,
        probability=_p("TahmKench", "Q", 0.7),
        notes=(
            "Q applies 1 stack of passive An Acquired Taste; at 3 "
            "stacks target is stunned 1.5s. Q's own slow is the "
            "unconditional damage surface; the 3rd-stack stun is "
            "the nth_hit conditional. Probability 0.7 because 3-cycle "
            "is achievable in 6s fight via Q + AA + Q chain. Coexists "
            "with TahmKench R wave 0 devour on different spell slot "
            "via setdefault."
        ),
    )

    # ============================================================
    # === wave 6 expansion (2026-05-22) - 1 entry / 0 new champs
    # === via multi-wave coexistence on existing champion (Brand
    # === gains Q coexisting with wave 0 R nth_hit 3-stack stun).
    # === Uses only the 10 existing condition tags - no new tag
    # === constants (operator-gated). Sourced from the wave 4
    # === REJECT carry where Brand W was rejected as not first-
    # === order CC; the canonical Brand Q stun-on-blazed-target
    # === IS first-order CC with a clean COND_TARGET_DEBUFFED fit.
    # === REJECTs documented in commit body: Lissandra E (damage +
    # === dash only, no first-order CC at 16.10.1 per Meraki);
    # === Aurora R/E/W (mechanic-uncertain or slow-only); Volibear
    # === R (turret-only); Naafiri R / Akali R / Jhin R / Pyke R /
    # === Sett R (no first-order CC verified); Vex E (mark-conditional
    # === already shipped wave 0); Heimerdinger R-Q/R-W (already
    # === unconditional E in _PER_SPELL_CC_DURATIONS); Galio Q (slow
    # === only); Brand W Pillar of Flame (passive Blaze trigger,
    # === not first-order); Lillia E (no CC); Sett W (needs new
    # === grit_meter tag); Sett E (already wave 0 dual_enemy);
    # === Tristana R terrain-stun (uncertain at 16.10.1 whether
    # === stun fires only on wall collision or always - Meraki
    # === shows Stun Duration block but mechanic interpretation
    # === unclear); Mel E (root is unconditional direct-hit per
    # === Meraki, belongs in _PER_SPELL_CC_DURATIONS not here);
    # === Annie Pyromania passive (encoding still ambiguous per
    # === item 146 wave 5 REJECT - lands across Q/W/R, rank-up by
    # === champion-level not spell-level); Bel'Veth W (slow +
    # === airborne unconditional, belongs elsewhere); Vayne E
    # === wall-stun (schema lift needed per item 146 REJECT);
    # === Trundle E (no clean tag fit); Renekton W + Camille E
    # === (extension-shape asymmetry per item 144 REJECT).
    # ============================================================

    # Brand Q Sear: skillshot damage line. Standalone hit on a non-
    # blazed target = damage only. If the target carries a Blaze
    # passive stack (applied by any prior Brand spell-hit OR auto-
    # attack landing the passive), Sear stuns the target for 1.25s.
    # The Blaze debuff is the prerequisite (target_debuffed tag).
    # Brand R is already in the cc_conditional registry as wave 0
    # nth_hit 3-stack stun (Pyroclasm bouncing 3 times); Brand Q
    # (this wave 6) is the conditional stun on a blazed target that
    # coexists on the same champion via setdefault on a different
    # spell slot. FOURTH multi-entry-within-cc_conditional champion
    # (after Aatrox Q+W waves 3+4 / Briar Q+E waves 4+5 / TahmKench
    # R+Q waves 0+5). Pantheon Q wave 4 coexists with Pantheon W in
    # the SEPARATE unconditional `_PER_SPELL_CC_DURATIONS` registry,
    # NOT in cc_conditional. Probability
    # 0.5 (tag midpoint) - in a teamfight Brand typically applies
    # Blaze early via passive auto-attack or W zone before Q follow-
    # up, but the debuff also frequently expires before Q hits (4s
    # window per stack); midpoint reflects average mid-fight setup.
    # Duration 1.25s confirmed canonical at 16.10.x via Riot wiki
    # Brand passive Blaze interaction. The Brand W Pillar of Flame
    # increased-damage-on-blazed-target was REJECTED wave 4 as "not
    # first-order"; Brand Q here is genuinely first-order CC (stun
    # is the direct effect, not a damage amplification).
    registry.setdefault("Brand", {})["Q"] = ConditionalCcEntry(
        champion="Brand",
        spell="Q",
        cc_kind="stun",
        durations_s=(1.25,),
        condition=COND_TARGET_DEBUFFED,
        probability=_p("Brand", "Q", 0.5),
        notes=(
            "Q Sear stuns 1.25s only when target carries a Blaze "
            "passive stack from prior Brand spell-hit or auto-attack. "
            "Standalone Q on a non-blazed target is damage only. "
            "target_debuffed conditional - the Blaze stack must "
            "persist on the target when Q lands (4s stack window). "
            "Coexists with Brand R wave 0 nth_hit 3-stack stun on a "
            "different spell slot via setdefault."
        ),
    )

    # ---------------- wave 8 (2026-05-22 / ENGINE 1.45.0) ----------------
    #
    # Wave 8 ships +3 entries / +3 net-new champions across 2 existing
    # condition tags (COND_CHANNEL_COMPLETION + COND_TARGET_DEBUFFED).
    # All 3 are EXPLICITLY-AUTHORIZED candidates from prior wave REJECT
    # lists where the REJECT note flagged the entry as belonging in
    # cc_conditional (parallel to Karma W) - NOT new pitches.
    #
    # Source for each:
    # 1) Morgana R Soul Shackles: wave 8 unconditional REJECT (item 146
    #    Slice B `4ab11ba`) explicitly said "REJECT - belongs in
    #    cc_conditional (parallel to Karma W)". Wave 9 REJECT (item 147
    #    Slice B `3c73c3b`) re-stated: "stun fires on tether expiry
    #    (channel-completion-conditional); belongs in cc_conditional if
    #    added later parallel to Karma W". The Meraki 16.10.1 parse-
    #    strip exposes the Stun Duration block (1.5/1.75/2.0s across 3
    #    ranks). Mechanic mirrors Karma W exactly: ult tethers all
    #    enemies in range for 3s; if Morgana maintains the tether (LoS
    #    + distance) for the full channel, all tethered targets are
    #    stunned for the rank duration. CC fires only on channel
    #    completion - channel-cancel via knockup / displacement / death
    #    nullifies. Pinned by Karma W parallel (wave 1 entry).
    #
    # 2) Seraphine E Beat Drop: wave 4 unconditional REJECT (item 138
    #    Slice B `6718445`) said "conditional on existing slow"; wave 8
    #    REJECT (item 146) said "stun OR root duration constant but
    #    which CC fires is target-state-conditional; REJECT per item
    #    138"; wave 9 REJECT (item 147) said "target-state conditional".
    #    The Meraki 16.10.1 parse-strip exposes the Disable Duration
    #    block (1.1-1.5s). At 16.10.1 the mechanic is: damages all
    #    enemies in a line; fresh targets receive damage + slow only;
    #    slowed targets are stunned; stunned targets are rooted (the
    #    CC TIER ESCALATES based on target's pre-existing debuff state).
    #    The disable duration is the same value across all CC types.
    #    Encoding the CONDITIONAL stun/root variant via debuffed_target
    #    captures the first-order CC that fires when a teammate (or
    #    Seraphine's R) has already slowed the target. Probability mid
    #    because the setup is teamfight-dependent (solo Seraphine on
    #    a fresh target gets damage + slow only).
    #
    # 3) Evelynn W Allure: wave 4 unconditional REJECT (item 138 Slice
    #    B `6718445`) said "detonation-on-Eve-attack conditional"; wave
    #    8 REJECT (item 146) explicitly said "detonation-on-Eve-attack
    #    conditional charm". The Meraki 16.10.1 parse-strip exposes
    #    the Disable Duration block (1.25-2.25s across 5 ranks).
    #    Mechanic: W applies a mark (charm-debuff) on cast that
    #    DETONATES when Evelynn's NEXT spell-hit or auto-attack lands
    #    on the marked target within the mark window. The charm fires
    #    on Evelynn's follow-up attack - channel completion of her
    #    own kit-sequence (mark + follow-up). Maps to
    #    COND_CHANNEL_COMPLETION (Evelynn must complete the mark +
    #    detonation sequence; if she dies / loses target / leaves
    #    range before the follow-up, no charm). Probability mid-low -
    #    Evelynn typically detonates her own mark in setup gank flows
    #    but the mark also expires (~2.5s) before follow-up in many
    #    fights.
    #
    # All 3 use ONLY the 12 existing condition tags. NO new tag
    # constants. NO Meraki extractor schema lift needed (the duration
    # values are in the parse-strip damage_blocks; the mechanic
    # description lives in Riot wiki / in-game tooltip + standard
    # League knowledge). The 3 entries close item 150 carry-forward
    # (the "16 consecutive run saturation" verdict was based on
    # candidates that DID need the schema lift; these 3 do NOT).
    #
    # Multi-wave coexistence count: NONE this wave (Morgana / Seraphine
    # / Evelynn are net-new champions with no prior cc_conditional
    # entries). Wave 8 grows the multi-entry-WITHIN-cc_conditional
    # champion count by ZERO (stays at 4: Aatrox Q+W / Brand Q+R /
    # Briar Q+E / TahmKench R+Q).
    #
    # REGISTRY GROWS: 36 entries -> 39 entries / 32 champions -> 35
    # champions.

    # Morgana R Soul Shackles: tethers all enemies in range for 3s;
    # if Morgana maintains LoS + range for the full channel, all
    # tethered targets are stunned for the rank duration. Channel
    # cancel via knockup / displacement / death nullifies stun.
    # Mechanic parallel to Karma W wave 1 entry (tether + full-
    # channel CC). Stun durations 1.5/1.75/2.0s across 3 ranks
    # confirmed via Meraki 16.10.1 Stun Duration block.
    registry.setdefault("Morgana", {})["R"] = ConditionalCcEntry(
        champion="Morgana",
        spell="R",
        cc_kind="stun",
        durations_s=(1.5, 1.75, 2.0),
        condition=COND_CHANNEL_COMPLETION,
        probability=_p("Morgana", "R", 0.5),
        notes=(
            "R Soul Shackles tethers all enemies in range; tethered "
            "targets are stunned for the rank duration if Morgana "
            "maintains LoS + range for the full 3s channel. Channel "
            "cancel via knockup / displacement / death nullifies the "
            "stun. Mechanic parallel to Karma W wave 1 entry. "
            "Probability midpoint - in teamfights the operator "
            "typically gets the channel off but enemies frequently "
            "interrupt or break tether. Closes wave 8 unconditional "
            "REJECT (item 146) + wave 9 REJECT (item 147) note that "
            "Morgana R belongs in cc_conditional parallel to Karma W."
        ),
    )

    # Seraphine E Beat Drop: damages all enemies in a line; CC tier
    # ESCALATES based on target's pre-existing debuff state. Fresh
    # target gets damage + slow only. Slowed target is stunned.
    # Stunned target is rooted. Disable duration is the SAME value
    # across all CC types (1.1/1.2/1.3/1.4/1.5s across 5 ranks
    # confirmed via Meraki 16.10.1 Disable Duration block). The
    # conditional stun/root variant fires when target is already
    # debuffed (slowed or stunned) - typically via teammate setup
    # or Seraphine's own R follow-up.
    registry.setdefault("Seraphine", {})["E"] = ConditionalCcEntry(
        champion="Seraphine",
        spell="E",
        cc_kind="stun",
        durations_s=(1.1, 1.2, 1.3, 1.4, 1.5),
        condition=COND_TARGET_DEBUFFED,
        probability=_p("Seraphine", "E", 0.5),
        notes=(
            "E Beat Drop CC tier escalates by target state: fresh "
            "target gets damage + slow only; slowed target stunned; "
            "stunned target rooted. The conditional stun fires when "
            "target is already slowed (teammate setup or Seraphine "
            "R). Disable duration is the same value across all CC "
            "tiers. Probability midpoint - teamfight setup-dependent. "
            "Closes wave 4 + wave 8 + wave 9 REJECT notes that beat "
            "drop conditional CC belongs in cc_conditional."
        ),
    )

    # Evelynn W Allure: applies a mark (charm-debuff) on cast that
    # DETONATES when Evelynn's next spell-hit or auto-attack lands
    # on the marked target within the mark window (~2.5s). The
    # charm fires on Evelynn's follow-up attack - channel completion
    # of her own kit-sequence (mark application + detonation
    # follow-up). Cleansable via QSS / mark-expiry. Disable
    # durations 1.25/1.5/1.75/2.0/2.25s across 5 ranks confirmed via
    # Meraki 16.10.1 Disable Duration block. Maps to
    # COND_CHANNEL_COMPLETION (Evelynn must complete the mark +
    # detonation sequence).
    registry.setdefault("Evelynn", {})["W"] = ConditionalCcEntry(
        champion="Evelynn",
        spell="W",
        cc_kind="charm",
        durations_s=(1.25, 1.5, 1.75, 2.0, 2.25),
        condition=COND_CHANNEL_COMPLETION,
        probability=_p("Evelynn", "W", 0.4),
        notes=(
            "W Allure applies a mark that detonates on Evelynn's "
            "next spell-hit or auto-attack on the marked target. "
            "Charm fires on follow-up - channel completion of her "
            "mark+detonation sequence. Mark expires ~2.5s without "
            "follow-up. Probability mid-low - Evelynn typically "
            "detonates in setup ganks but mark frequently expires "
            "in poke fights. Closes wave 4 + wave 8 REJECT notes "
            "that detonation-on-Eve-attack conditional charm belongs "
            "in cc_conditional."
        ),
    )

    # ============================================================
    # === wave 9 expansion (2026-05-23 / ENGINE 1.46.0) - +3 entries
    # === / +3 net-new champions closing 3 of the 7 schema-lift-blocked
    # === candidates from prior wave REJECTs (items 150 / 151 / 152
    # === carry-forward). The Meraki extractor schema lift shipped this
    # === wave (additive ``effects_descriptions: list[str]`` per form
    # === in ``data/daemon_slayer/16.10.1/champion_abilities.json``)
    # === enables verification of empowered / form-gated mechanics that
    # === lived in description text but were absent from the structured
    # === leveling[] blocks. The CC duration values for all 3 wave 9
    # === entries were ALREADY present in the parse-strip
    # === damage_blocks.raw_modifiers; the schema lift confirms the
    # === mechanic descriptions in-source (no re-litigation needed).
    # ===
    # === The 4 OTHER candidates from the item 152 mission spec
    # === REJECT after schema-lift verification:
    # ===
    # ===   (a) Karma W form 1 Renewal - same (Karma, W) slot already
    # ===       holds the wave 1 Focused Resolve channel-completion
    # ===       root entry. The registry is keyed (champion, spell)
    # ===       so the form 1 R-empowered variant cannot coexist on
    # ===       the same spell slot. Wave 1 entry already captures
    # ===       the core mechanic at base duration; the R-empowered
    # ===       extension is a calibration tuning, not a new mechanic.
    # ===   (b) Aatrox R World Ender - schema-lifted description
    # ===       confirms the 3s fear targets minions/monsters ONLY,
    # ===       NOT champions. No champion-facing CC. The item 150
    # ===       audit note "post-R passive empowered Q-sweetspot/W-
    # ===       pull" was speculative; Riot 16.10.1 description does
    # ===       NOT empower Q or W under R. Q3 sweetspot knockup
    # ===       0.5s is already in cc_conditional wave 3 unconditional
    # ===       on its own (NOT R-gated).
    # ===   (c) Volibear R Stormbringer - schema-lifted description
    # ===       confirms only turret-disable + 50% slow (1s decaying).
    # ===       Slow is NOT first-order CC; turret-only disable is
    # ===       not champion CC. The Stormbringer form is a self-buff
    # ===       (ghosting + bonus health + range + size) with no
    # ===       champion-facing stun/root/knockup.
    # ===   (d) Briar W Blood Frenzy - schema-lifted description
    # ===       confirms Blood Frenzy is purely self-buff (ghosting +
    # ===       attack speed + movement speed + AoE-around-target AA
    # ===       empowerment). No CC granted to other spells while
    # ===       in frenzy state. The Briar Q stun 0.85s is already
    # ===       in cc_conditional wave 4+5 unconditional on its own;
    # ===       Briar E Chilling Scream fear is wave 5 multi-wave
    # ===       coexistence.
    # ===
    # === Multi-wave coexistence count: NONE this wave (Hwei / Neeko
    # === are net-new champions to cc_conditional; Renekton is also
    # === net-new in cc_conditional - the unconditional W base-stun
    # === entry sits in `_PER_SPELL_CC_DURATIONS`, the cc_conditional
    # === wave-9 entry encodes the Fury-empowered EXTENDED stun on
    # === the same spell slot via the separate-registry coexistence
    # === pattern established by Aatrox Q3 wave 3 + Neeko E wave 9).
    # ===
    # === REGISTRY GROWS: 39 entries -> 42 entries / 35 champions
    # === -> 38 champions. cc_conditional consumer math BYTE-IDENTICAL
    # === to 1.45.0 for default include_conditional=False callers
    # === across all 5 consumer surfaces.
    # ============================================================

    # Hwei E form 1 Grim Visage (EQ): Hwei E is a 2-cast cycle where
    # E (Subject: Torment, form_index=0) is the mood selector and the
    # follow-up spell (Q / W / E) determines the form. Form 1 (EQ)
    # fires a fear projectile dealing magic damage and applying a
    # Disable Duration fear of 1.0/1.125/1.25/1.375/1.5s across 5
    # ranks (Meraki 16.10.1 Disable Duration block; schema-lifted
    # description text confirms "fears them for a duration"). The
    # CC is unconditional WITHIN form 1 but conditional on completing
    # the 2-cast cycle (E0 mood selector -> EQ form lock-in). Maps
    # to COND_CHANNEL_COMPLETION (the operator must complete the
    # 2-cast cycle before the fear lands; partial-cycle = no E1
    # fire at all). Probability mid-low because the cycle requires
    # 2 inputs in sequence + the fear projectile is dodgeable.
    registry.setdefault("Hwei", {})["E"] = ConditionalCcEntry(
        champion="Hwei",
        spell="E",
        cc_kind="fear",
        durations_s=(1.0, 1.125, 1.25, 1.375, 1.5),
        condition=COND_CHANNEL_COMPLETION,
        probability=_p("Hwei", "E", 0.4),
        notes=(
            "E form 1 Grim Visage (EQ form): fears target for "
            "1.0-1.5s across 5 ranks. Hwei E is a 2-cast cycle "
            "(E mood selector -> Q/W/E form lock). The fear fires "
            "only on the EQ form completion; partial-cycle = no "
            "fire. Maps to COND_CHANNEL_COMPLETION on the 2-cast "
            "sequence. Probability mid-low - 2-input setup + "
            "dodgeable projectile. Closes item 150 + 151 + 152 "
            "carry-forward 'Hwei E form_index=1 Grim Visage Disable "
            "1.0-1.5s; multi-form same-spell-slot constraint' via "
            "ENGINE 1.46.0 Meraki schema lift (the duration values "
            "were already in the parse-strip damage_blocks but the "
            "mechanic verification needed effects_descriptions)."
        ),
    )

    # Neeko E Tangle-Barbs (EMPOWERED root variant): Neeko E base
    # spiral roots first-hit target for 0.7/0.9/1.1/1.3/1.5s (already
    # in unconditional `_PER_SPELL_CC_DURATIONS` as Neeko E base).
    # If the spiral hits at least one enemy, the projectile grows in
    # size and SUBSEQUENT enemies hit by the grown spiral are rooted
    # for the EMPOWERED duration 1.8/2.1/2.4/2.7/3.0s across 5 ranks
    # (Meraki 16.10.1 Empowered Root Duration block; schema-lifted
    # description text confirms "If the spiral hits at least one
    # enemy, it grows in size and its speed and root duration is
    # increased"). The empowered duration applies to enemies hit
    # AFTER the first; in a 1v1 isolated hit only the base duration
    # fires. Maps to COND_DUAL_ENEMY (need 2+ enemies in spiral
    # path for the empowered duration to credit). Coexists with the
    # unconditional Neeko E base via the separate-registry pattern
    # (Aatrox Q3 wave 3 is the precedent: unconditional Q damage
    # alongside cc_conditional Q3 sweetspot knockup).
    registry.setdefault("Neeko", {})["E"] = ConditionalCcEntry(
        champion="Neeko",
        spell="E",
        cc_kind="root",
        durations_s=(1.8, 2.1, 2.4, 2.7, 3.0),
        condition=COND_DUAL_ENEMY,
        probability=_p("Neeko", "E", 0.5),
        notes=(
            "E Tangle-Barbs EMPOWERED root variant: spiral grows on "
            "first-enemy hit, subsequent enemies hit by the grown "
            "spiral are rooted 1.8-3.0s across 5 ranks. Base root "
            "(0.7-1.5s) is in unconditional _PER_SPELL_CC_DURATIONS. "
            "The empowered duration credits when 2+ enemies are "
            "caught in the spiral path. Maps to COND_DUAL_ENEMY "
            "(teamfight conditional). Probability midpoint - "
            "Neeko's E is a primary teamfight tool typically aimed "
            "into clusters. Closes item 150 + 151 + 152 carry-"
            "forward 'Neeko E Empowered Root 1.8-3.0s; multi-form "
            "same-spell-slot constraint' via ENGINE 1.46.0 schema "
            "lift. Coexists with unconditional base root on the "
            "same (Neeko, E) slot via the separate-registry "
            "pattern."
        ),
    )

    # Renekton W Ruthless Predator (REIGN OF ANGER empowered stun):
    # Renekton W base stun 0.75s is in unconditional
    # `_PER_SPELL_CC_DURATIONS` (Riot canonical). The Reign of Anger
    # Bonus (cast while at 100 Fury) increases the stun duration to
    # 1.5s flat across all ranks. The bonus is gated on Renekton
    # entering the empowered Fury state - a self-empowered champion
    # state that gates a CC variant of W with extended duration.
    # Maps to COND_FRENZY_STATE (the wave 7 forward-marker tag at
    # midpoint 0.4 - this is the FIRST consumer of the frenzy_state
    # tag in the registry, closing the forward-marker contract).
    # Probability 0.4 (tag midpoint) - Renekton typically enters
    # Fury for engages but the W cast must specifically coincide
    # with the Fury threshold. Mechanic schema-lift-verified:
    # description text effect[2] "Reign of Anger Bonus: ...
    # increasing the stun duration to 1.5 seconds" was captured by
    # the ENGINE 1.46.0 Meraki extractor schema lift (the 1.5s
    # value is NOT in the structured damage_blocks - the W form
    # damage_blocks only carry damage attributes; the empowered
    # stun duration lived exclusively in description text).
    registry.setdefault("Renekton", {})["W"] = ConditionalCcEntry(
        champion="Renekton",
        spell="W",
        cc_kind="stun",
        durations_s=(1.5,),
        condition=COND_FRENZY_STATE,
        probability=_p("Renekton", "W", 0.4),
        notes=(
            "W Ruthless Predator REIGN OF ANGER empowered stun: "
            "base stun 0.75s (unconditional) extends to 1.5s when "
            "cast while at 100 Fury. Mechanic captured by ENGINE "
            "1.46.0 Meraki schema lift (effects_descriptions[2] "
            "'Reign of Anger Bonus: ... increasing the stun "
            "duration to 1.5 seconds'). Maps to COND_FRENZY_STATE "
            "- FIRST consumer of the wave 7 forward-marker tag, "
            "closing the COND_FRENZY_STATE empty-registry contract. "
            "Probability tag midpoint 0.4. Closes item 150 + 151 "
            "+ 152 carry-forward 'Renekton W Fury empowered-Fury "
            "stun in stripped description'. Coexists with the "
            "unconditional Renekton W 0.75s base stun on the same "
            "(Renekton, W) slot via the separate-registry pattern "
            "(unconditional registry = `_PER_SPELL_CC_DURATIONS`, "
            "this is the conditional empowered variant)."
        ),
    )

    # ============================================================
    # === wave 11 expansion (2026-05-23 / ENGINE 1.48.0) - +2 entries
    # === / +2 net-new champions (Sion R primary + Gnar W form 1
    # === sidecar). Uses ONLY the 12 existing condition tags - no
    # === new tag constants. The Gnar W form 1 entry lives in the
    # === sidecar registry _PER_SPELL_CC_CONDITIONAL_FORMS (see
    # === _build_per_spell_cc_conditional_forms below); only the
    # === Sion R primary entry is registered here.
    # ===
    # === Wave 11 closes 2 explicit-duration candidates from the
    # === item 153 + 154 + 155 effects_descriptions audit that did
    # === NOT need a separate extractor schema lift. The 13 other
    # === candidates audited this wave were REJECT-confirmed:
    # ===
    # ===   (a) Aatrox R minion-only fear (confirmed not champion CC)
    # ===   (b) Volibear R turret-only disable + slow (no champion
    # ===       first-order CC; slow does not count)
    # ===   (c) Briar W self-buff frenzy state (no CC payload)
    # ===   (d) Sion E minion-only stun
    # ===   (e) Lillia W damage + center-bonus only
    # ===   (f) Ekko R self-stasis + damage only
    # ===   (g) Smolder R damage + Smolder-heal only
    # ===   (h) Karma E shield + MS only (both forms)
    # ===   (i) Vladimir R damage amp + delayed burst + Vlad-heal
    # ===   (j) Akshan Q/R damage + buffs only
    # ===   (k) Tristana E damage stacking detonation only
    # ===   (l) Kayle E/R no CC
    # ===   (m) Nidalee R is a transform, no CC; Q/W/E forms have
    # ===       no champion-facing CC duration in description text
    # ===
    # === DEFERRED (would need additional verification beyond
    # === effects_descriptions):
    # ===
    # ===   * Jayce E Thundering Blow - description confirms "roots
    # ===     the target enemy over the cast time" + 600u knockback,
    # ===     but cast time duration value is NOT in
    # ===     effects_descriptions or damage_blocks (would need wiki
    # ===     cross-reference at ~0.4s). CARRY-FORWARD for wave 12+
    # ===     if patch data adds cast_time field.
    # ===   * Singed E Fling Mega-Adhesive overlap root - duration
    # ===     described as "for a duration" only, no value. Requires
    # ===     2-spell-overlap target-debuffed encoding that the
    # ===     current schema lift does not support without further
    # ===     work. CARRY-FORWARD for wave 12+.
    # ===
    # === Multi-wave coexistence: Sion (Q wave 0 unconditional +
    # === R wave 11 cc_conditional) is the FIFTH multi-entry-cross-
    # === unconditional/conditional champion (after Aatrox / Briar /
    # === TahmKench / Brand all within cc_conditional + Pantheon
    # === Q wave 4 + W unconditional + Renekton/Karma W cross). Gnar
    # === (R wave 0 unconditional + W form 1 wave 11 sidecar) is the
    # === SIXTH via the form-explicit sidecar pattern.
    # ===
    # === REGISTRY GROWS: 42 primary entries (unchanged + Sion R = 43
    # === primary) + 2 sidecar (wave 10 Karma W form 1 + Hwei E form
    # === 2 unchanged + Gnar W form 1 = 3 sidecar) = 46 total entries
    # === across 40 champions (added Sion + Gnar to the union).
    # === cc_conditional consumer math BYTE-IDENTICAL to 1.47.0 for
    # === default include_conditional=False callers across all 5
    # === consumer surfaces.
    # ============================================================

    # Sion R Unstoppable Onslaught: Sion charges forward for up to
    # 8 seconds with displacement immunity + ghosting + ramping
    # movement speed. At end of charge (or on terrain/champion
    # collision) he slams the ground in a smaller-radius AOE.
    # Enemies in that smaller AOE are PULLED toward Sion over 0.5s
    # AND stunned after a brief delay. The stun duration scales with
    # charge channel-time: 0.25s minimum (immediate-cancel slam) up
    # to 1.75s (full 8s charge). Standalone slam-on-min-charge =
    # damage + slow only; the inner-radius stun fires only on
    # sufficient channel completion. Encoded at representative
    # midpoint 1.0s (mid-charge ~4s) for operator-conservative
    # calibration consistent with the wave 0+ single-value patterns.
    # Operator can tune via per_entry_probability ``Sion:R`` if
    # max-charge encoding is preferred (would land at 1.75s).
    # Maps to COND_CHANNEL_COMPLETION - parallel to Karma W /
    # Warwick R / Morgana R / Nunu R (channel-time-gated CC).
    # Mechanic schema-lift-verified: effects_descriptions text
    # "Enemies in a smaller radius are also pulled towards Sion
    # over 0.5 seconds and become stunned after a brief delay for
    # 0.25 : 1.75 (based on channel time) seconds" captured by
    # ENGINE 1.46.0 Meraki schema lift. The outer-radius slow 3s
    # is NOT first-order CC and is omitted. Sion Q (unconditional
    # stun 1.25-2.25s in `_PER_SPELL_CC_DURATIONS`) is on a different
    # spell slot - no collision.
    registry.setdefault("Sion", {})["R"] = ConditionalCcEntry(
        champion="Sion",
        spell="R",
        cc_kind="stun",
        durations_s=(1.0,),
        condition=COND_CHANNEL_COMPLETION,
        probability=_p("Sion", "R", 0.5),
        notes=(
            "R Unstoppable Onslaught: 8s charge with displacement "
            "immunity; on slam-impact a smaller-radius inner AOE "
            "pulls enemies toward Sion + stuns them for 0.25-1.75s "
            "based on channel time. Encoded at midpoint 1.0s "
            "(mid-charge ~4s) for operator-conservative calibration. "
            "Outer-radius slow 3s is NOT first-order CC and is "
            "omitted. Maps to COND_CHANNEL_COMPLETION - parallel "
            "to Karma W / Warwick R / Morgana R. Mechanic captured "
            "by ENGINE 1.46.0 Meraki schema lift "
            "(effects_descriptions confirms 0.25 : 1.75 channel-"
            "time-gated stun). Coexists with the unconditional "
            "Sion Q stun 1.25-2.25s in `_PER_SPELL_CC_DURATIONS` "
            "on a different spell slot. Operator can tune via "
            "per_entry_probability ``Sion:R`` if max-charge "
            "calibration (1.75s) is preferred."
        ),
    )

    # ============================================================
    # === wave 12 expansion (2026-05-24 / ENGINE 1.49.0) - +2
    # === primary entries / +2 net-new champions (Singed E Mega-
    # === Adhesive overlap root + Alistar E Trample 5-stack stun).
    # === A third wave 12 entry lives in the sidecar registry
    # === (Sylas E form_index=1 Abduct 2-cast-completion stun);
    # === see _build_per_spell_cc_conditional_forms below.
    # ===
    # === Wave 12 closes 3 schema-lift-verified candidates that
    # === were missed in waves 1-11. The Singed E Mega-Adhesive
    # === overlap root was DEFERRED at item 156 wave 11 with the
    # === note "description says 'for a duration' with no explicit
    # === value" - but the actual schema-lifted damage_blocks
    # === block exposes a per-rank Root Duration modifier [1.0,
    # === 1.25, 1.5, 1.75, 2.0] seconds that the wave 11 audit
    # === overlooked. Re-audit at item 170 confirmed the
    # === structured value in `data/daemon_slayer/16.10.1/
    # === champion_abilities.json`. The Alistar E 5-stack
    # === Trample stun + Sylas E2 Abduct 2-cast-completion stun
    # === were both named in `ability_dps.py` comments as known
    # === conditional-CC carryovers from prior-wave REJECT lists.
    # ===
    # === Wave 12 uses ONLY the 12 existing condition tags - no
    # === new tag constants. Consumer math BYTE-IDENTICAL to
    # === 1.48.0 for default include_conditional=False callers
    # === across all 5 consumer surfaces.
    # ===
    # === REJECT (still deferred):
    # ===   * Jayce E Thundering Blow cast-time root - description
    # ===     "roots the target enemy over the cast time" + "0.4
    # ===     seconds" lockout, but the 0.4s value refers to
    # ===     Jayce's Q/Q1 lockout AFTER Thundering Blow's cast,
    # ===     NOT the cast-time root duration. The cast-time
    # ===     duration is still absent from effects_descriptions
    # ===     and damage_blocks. CARRY-FORWARD wave 13+ if patch
    # ===     adds explicit cast_time field.
    # ===   * Maokai R Sapling Showcase distance-gated root
    # ===     0.75-2.25s - the unconditional Maokai R registry
    # ===     entry already encodes a mid-distance root for ranks
    # ===     1/2/3. Adding a cc_conditional COND_RANGE_GATED
    # ===     entry would double-count with the unconditional
    # ===     encoding under include_conditional=True. REJECT.
    # ============================================================

    # Singed E Fling Mega-Adhesive overlap root: Singed E base
    # mechanic flings the target 550 units over Singed dealing
    # magic damage; the displacement is captured as the
    # unconditional 1.0s knockback in `_PER_SPELL_CC_DURATIONS`
    # (Singed E base entry). The CONDITIONAL root payload fires
    # ONLY when the target's landing position falls inside the
    # area-of-effect of Singed's Mega Adhesive (W), with a
    # per-rank root duration of [1.0, 1.25, 1.5, 1.75, 2.0]
    # seconds across 5 E ranks (Meraki 16.10.1 Root Duration
    # block; effects_descriptions confirms "If the target lands
    # on Mega Adhesive's area of effect after the displacement,
    # they are rooted for a duration"). Maps to
    # COND_TARGET_DEBUFFED - the target must be inside the Mega
    # Adhesive zone when Fling resolves, which requires Singed to
    # have pre-placed W along the projected flight path. Without
    # W overlap the target receives damage + displacement only
    # (no root). Coexists with the unconditional Singed E
    # knockback on the same spell slot via the separate-registry
    # pattern (`_PER_SPELL_CC_DURATIONS` = base displacement;
    # this cc_conditional entry = overlap-root payload). The
    # combination is the canonical Singed combo (W ground-
    # adhesive then E Fling onto adhesive); RC's EHP-vs-CC
    # scorer should credit both contributions under
    # include_conditional=True. Closes item 156 + item 170
    # wave-12-audit carry-forward (the wave 11 note dismissed
    # the Mega-Adhesive root as "for a duration" but the
    # schema-lifted damage_blocks ACTUALLY exposes the per-rank
    # values; re-audit at item 170 confirmed the structured
    # block).
    registry.setdefault("Singed", {})["E"] = ConditionalCcEntry(
        champion="Singed",
        spell="E",
        cc_kind="root",
        durations_s=(1.0, 1.25, 1.5, 1.75, 2.0),
        condition=COND_TARGET_DEBUFFED,
        probability=_p("Singed", "E", 0.5),
        notes=(
            "E Fling Mega-Adhesive overlap root: when the target's "
            "landing position falls inside Singed's pre-placed W "
            "Mega Adhesive zone, target is rooted for 1.0-2.0s "
            "across 5 E ranks (Meraki 16.10.1 Root Duration block). "
            "Standalone Fling with no W overlap is damage + "
            "displacement only. Maps to COND_TARGET_DEBUFFED - "
            "target must be inside Mega Adhesive zone when Fling "
            "lands. Probability midpoint - canonical Singed combo "
            "(W then E onto W) is reliable but requires aim. "
            "Coexists with the unconditional Singed E knockback "
            "1.0s in `_PER_SPELL_CC_DURATIONS` on the same spell "
            "slot via the separate-registry pattern (unconditional "
            "= base displacement; conditional = W-overlap root "
            "payload). Closes item 156 wave 11 deferred carry "
            "via item 170 wave 12 re-audit of the schema-lifted "
            "damage_blocks."
        ),
    )

    # Alistar E Trample 5-stack stun: E channels for 5 seconds
    # tramping the ground around Alistar every 0.5s, generating
    # a stack of Trample per tick that damages at least one
    # enemy champion, up to 5 stacks. At 5 stacks, Alistar's
    # next basic attack on-hit against a champion within 6
    # seconds ends Trample's effects to deal bonus magic damage
    # AND stun the target for 1.0 second (flat across all 5 E
    # ranks per effects_descriptions). Standalone E with fewer
    # than 5 stacks (or no champion in the trample radius long
    # enough) = damage + ghosting only (no stun payload). Maps
    # to COND_NTH_HIT (5-stack accumulation conditional).
    # Probability 0.7 (tag midpoint) - in teamfights Alistar
    # reliably tramples a target for the 5s channel + lands the
    # 5-stack basic attack within the 6s window, but a chasing
    # target frequently exits the trample radius before stack
    # 5 accumulates. Coexists with Alistar Q (unconditional
    # knock-up 1.0s in `_PER_SPELL_CC_DURATIONS`) and Alistar W
    # (unconditional knock-back 0.5s in
    # `_PER_SPELL_CC_DURATIONS`) on different spell slots via
    # setdefault. Closes item 170 wave-12-audit candidate
    # (named in `ability_dps.py:1225-1228` comment as a known
    # conditional-CC carryover from prior-wave REJECT lists).
    registry.setdefault("Alistar", {})["E"] = ConditionalCcEntry(
        champion="Alistar",
        spell="E",
        cc_kind="stun",
        durations_s=(1.0,),
        condition=COND_NTH_HIT,
        probability=_p("Alistar", "E", 0.7),
        notes=(
            "E Trample 5-stack stun: 5s channel ticks every 0.5s "
            "generating a stack of Trample per champion damaged, "
            "up to 5 stacks. At 5 stacks, the next basic attack "
            "on-hit ends Trample to deal bonus damage + stun the "
            "target for 1.0s flat across all 5 E ranks. "
            "Standalone E with fewer than 5 stacks = damage + "
            "ghosting only. Maps to COND_NTH_HIT (5-stack "
            "accumulation conditional). Probability tag midpoint "
            "0.7 - reliable in teamfights but chasing targets "
            "frequently exit the trample radius. Coexists with "
            "Alistar Q unconditional knock-up + Alistar W "
            "unconditional knock-back on different spell slots. "
            "Closes item 170 wave-12-audit candidate (named in "
            "ability_dps.py comment as known conditional-CC "
            "carryover)."
        ),
    )

    # ============================================================
    # === wave 13 expansion (2026-05-24 / ENGINE 1.50.0) - +6
    # === primary entries / +5 net-new champions sourced from an
    # === all-champ effects_descriptions scan against the
    # === ENGINE 1.46.0 Meraki schema-lifted data file. Each
    # === closure uses ONE of the 12 existing condition tags; NO
    # === new tag constants. A seventh wave 13 entry lives in
    # === the sidecar registry (Aphelios Q form_index=3 Gravitum
    # === Binding Eclipse expunge root - target-debuffed); see
    # === _build_per_spell_cc_conditional_forms below.
    # ===
    # === New primary entries (6 total, 4 net-new champions +
    # === 2 multi-wave coexistence on Warwick / TahmKench):
    # ===
    # ===   * Sejuani E Permafrost (NEW champ) - COND_NTH_HIT 0.7:
    # ===     4-Frost-stack accumulator stun 1.0s flat.
    # ===   * Renata Q Handshake (NEW champ) - COND_CHANNEL_COMPLETION
    # ===     0.5: tether-recast-throw bystander stun 0.5s flat.
    # ===   * Shaco R Hallucinate (NEW champ) - COND_CHANNEL_COMPLETION
    # ===     0.5: clone-death deploy box fear 1.0s flat.
    # ===   * Fizz R Chum the Waters (NEW champ) - COND_TARGET_DEBUFFED
    # ===     0.5: lure-on-champion knockup 1.0s instead of base
    # ===     knock-back.
    # ===   * Warwick E Primal Howl (existing champ; coexists with
    # ===     wave 0 Warwick R suppression) - COND_CHANNEL_COMPLETION
    # ===     0.5: recast fear 1.0s after damage-reduction window.
    # ===   * TahmKench W Abyssal Dive (existing champ; coexists with
    # ===     wave 0 TahmKench R devour + wave 5 TahmKench Q nth_hit
    # ===     stun) - COND_CHANNEL_COMPLETION 0.5: 1.35s channel +
    # ===     0.65s recovery; emerges to stun 1.0s flat.
    # ===
    # === Wave 13 REJECT verdicts (effects_descriptions schema-
    # === lift-verified this run; CARRY-FORWARD only if new
    # === evidence surfaces):
    # ===
    # ===   * LeeSin R Dragon's Rage primary-target airborne 1.0s -
    # ===     the description "rendering them airborne for 1 second"
    # ===     is UNCONDITIONAL CC on the primary target; belongs
    # ===     in `_PER_SPELL_CC_DURATIONS` not cc_conditional. The
    # ===     bystander collision knockup IS conditional but
    # ===     adding it without the primary unconditional entry
    # ===     under-credits the spell. REJECT - defer to a future
    # ===     `_PER_SPELL_CC_DURATIONS` LeeSin R addition.
    # ===   * Poppy R Keeper's Verdict 1.0s base knockup - the
    # ===     1.0s knockup is the BASE non-charged recast; the
    # ===     charged knockback is the empowered variant.
    # ===     Knockup-on-base-recast is UNCONDITIONAL; belongs
    # ===     in `_PER_SPELL_CC_DURATIONS` not cc_conditional.
    # ===     REJECT.
    # ===   * RekSai W form 1 Unburrow knockup 1.0s - unconditional
    # ===     1.0s knockup on Unburrow form transition; belongs in
    # ===     `_PER_SPELL_CC_DURATIONS` not cc_conditional. REJECT.
    # ===   * Jayce E cast-time root - STILL schema-blocked (item
    # ===     170 wave 12 carry; cast_time field absent from
    # ===     effects_descriptions and damage_blocks).
    # ===   * Maokai R distance-gated root - STILL double-count
    # ===     with unconditional Maokai R entry (item 170 wave 12
    # ===     carry; would need that registry deleted first).
    # ============================================================

    # Sejuani E Permafrost: passive accumulates Frost stacks on
    # enemies hit by Sejuani's W + allied melee basic attacks (up
    # to 4 stacks per target over 5 seconds). Sejuani can ONLY
    # cast E against an enemy with 4 stacks - the cast itself
    # requires the nth-hit precondition. The cast deals magic
    # damage + a slight displacement + STUNS the target for 1.0
    # second flat across all 5 E ranks per effects_descriptions
    # ("which deals magic damage, displaces slightly, and stuns
    # them for 1 second"). Standalone E with no 4-stack target
    # cannot be cast at all (the input is gated). Maps to
    # COND_NTH_HIT - the canonical 4-stack accumulator
    # conditional. Probability 0.7 (tag midpoint) - in teamfights
    # Sejuani's W + ally autos reliably reach 4 stacks on a
    # priority target within the 5s Frost window. Coexists with
    # the unconditional Sejuani Q 0.75-1.25s stun + Sejuani R
    # 1.0-2.0s stun in `_PER_SPELL_CC_DURATIONS` on different
    # spell slots.
    registry.setdefault("Sejuani", {})["E"] = ConditionalCcEntry(
        champion="Sejuani",
        spell="E",
        cc_kind="stun",
        durations_s=(1.0,),
        condition=COND_NTH_HIT,
        probability=_p("Sejuani", "E", 0.7),
        notes=(
            "E Permafrost 4-Frost-stack stun: E can ONLY be cast "
            "against an enemy already carrying 4 Frost stacks "
            "(accumulated via Sejuani W + allied melee basic "
            "attacks within a 5s window). Cast deals magic damage "
            "+ slight displacement + stuns the target for 1.0s "
            "flat across all 5 E ranks. Maps to COND_NTH_HIT - "
            "input itself is gated on 4 stacks. Probability tag "
            "midpoint 0.7 - W ticks + ally auto chain reliably "
            "stacks a priority target. Coexists with Sejuani Q + "
            "R unconditional stuns in `_PER_SPELL_CC_DURATIONS` "
            "on different spell slots."
        ),
    )

    # Renata Q Handshake recast bystander stun: the FIRST cast
    # roots the primary target for 1.0s flat (unconditional CC
    # on the primary target; this primary root belongs in
    # `_PER_SPELL_CC_DURATIONS` if added later). The RECAST
    # within the tether window throws the target in the recast
    # direction; SECONDARY targets struck by the thrown enemy
    # take damage AND are stunned for 0.5 seconds. Standalone Q
    # without a recast = damage + 1.0s primary root only (no
    # secondary stun). Maps to COND_CHANNEL_COMPLETION - the
    # secondary stun fires only after the tether persists +
    # Renata initiates the recast throw. Probability 0.5 (tag
    # midpoint) - the tether persists if Renata stays in range,
    # but secondary targets must be in the throw line which
    # requires deliberate aim. Renata has NO unconditional CC
    # entry in `_PER_SPELL_CC_DURATIONS` yet (primary root would
    # need a separate addition); this cc_conditional entry
    # encodes ONLY the recast-throw bystander stun payload.
    registry.setdefault("Renata", {})["Q"] = ConditionalCcEntry(
        champion="Renata",
        spell="Q",
        cc_kind="stun",
        durations_s=(0.5,),
        condition=COND_CHANNEL_COMPLETION,
        probability=_p("Renata", "Q", 0.5),
        notes=(
            "Q Handshake recast bystander stun: first cast roots "
            "primary target 1.0s (unconditional, belongs in "
            "`_PER_SPELL_CC_DURATIONS` if added later). Recast "
            "within tether throws target; SECONDARY targets "
            "struck by the thrown body are stunned 0.5s flat. "
            "Standalone Q without recast = damage + primary "
            "root only. Maps to COND_CHANNEL_COMPLETION - "
            "secondary stun fires only after tether persists + "
            "recast throw aim lands. Probability tag midpoint "
            "0.5 - tether persists reliably but secondary "
            "throw-line aim requires teamfight setup. FIRST "
            "Renata first-order CC registration in the engine "
            "(encodes only the recast bystander payload)."
        ),
    )

    # Shaco R Hallucinate clone-death box fear: R blinks Shaco
    # while summoning a controllable clone. The clone deals
    # modified damage + can be commanded; when the clone DIES
    # or EXPIRES (after up to 18 seconds), it deploys 3 mini-
    # boxes that activate instantly + FEAR nearby enemy
    # champions for 1.0 second flat per effects_descriptions
    # ("deploy three mini-boxes that activate instantly,
    # fearing nearby enemies for 1 second, increased to 2.2
    # seconds against non-champions"). Standalone R cast with
    # the clone still alive = damage + clone-control only (no
    # fear payload). Maps to COND_CHANNEL_COMPLETION - the
    # fear fires ONLY after the clone-death/expiration event
    # completes, which is operator-controlled (Shaco can
    # detonate manually) but not guaranteed in every fight
    # window. Probability 0.5 (tag midpoint) - clone death is
    # reliable in commit fights but Shaco frequently saves the
    # clone for setup/scouting. Coexists with the unconditional
    # Shaco W 0.5-1.5s fear in `_PER_SPELL_CC_DURATIONS` on a
    # different spell slot.
    registry.setdefault("Shaco", {})["R"] = ConditionalCcEntry(
        champion="Shaco",
        spell="R",
        cc_kind="fear",
        durations_s=(1.0,),
        condition=COND_CHANNEL_COMPLETION,
        probability=_p("Shaco", "R", 0.5),
        notes=(
            "R Hallucinate clone-death box fear: clone deploys "
            "3 mini-boxes on death/expiration that fear nearby "
            "enemy champions 1.0s flat (effects_descriptions "
            "'fearing nearby enemies for 1 second'). Standalone "
            "R with clone alive = damage + control only. Maps "
            "to COND_CHANNEL_COMPLETION - fear fires only after "
            "clone death/expiration. Probability tag midpoint "
            "0.5 - operator-controlled detonation but clone "
            "frequently saved for utility. Coexists with Shaco "
            "W unconditional fear in `_PER_SPELL_CC_DURATIONS` "
            "on a different spell slot."
        ),
    )

    # Fizz R Chum the Waters lure-on-champion knockup: R throws
    # a lure that attracts a shark after a 2-second delay.
    # Standalone lure (no champion intercept) = damage + slow +
    # KNOCK BACK (not knockup) - the knockback is the BASE
    # eruption effect. Conditional on an enemy champion
    # intercepting the lure in flight (becoming the "holder"),
    # the shark emerges at the holder's position and the
    # eruption becomes a KNOCK UP for 1.0 second flat instead
    # of the knock back per effects_descriptions ("The lure's
    # holder is slowed and revealed for the duration and
    # afterwards is impacted by the eruption but is knocked up
    # for 1 second instead of knocked back"). Maps to
    # COND_TARGET_DEBUFFED - the lure must attach to a champion
    # (debuffing them with slow + reveal) for the knockup
    # variant to fire. Probability 0.5 (tag midpoint) - in
    # teamfights Fizz reliably hits a champion with the lure
    # but skilled enemies side-step it. Coexists with no
    # `_PER_SPELL_CC_DURATIONS` entry for Fizz (FIRST Fizz
    # first-order CC registration anywhere in the engine; the
    # base knockback is captured under cc_kind="knockback"
    # which sits at 0.25s effective duration so it stays out
    # of the unconditional registry per the wave 0 ship rule).
    registry.setdefault("Fizz", {})["R"] = ConditionalCcEntry(
        champion="Fizz",
        spell="R",
        cc_kind="knockup",
        durations_s=(1.0,),
        condition=COND_TARGET_DEBUFFED,
        probability=_p("Fizz", "R", 0.5),
        notes=(
            "R Chum the Waters lure-on-champion knockup: base "
            "eruption knocks BACK 0.25s; lure attached to a "
            "champion (the holder) makes the eruption knock UP "
            "for 1.0s flat instead (effects_descriptions "
            "'knocked up for 1 second instead of knocked "
            "back'). Maps to COND_TARGET_DEBUFFED - lure must "
            "attach to a champion (debuffing them with slow + "
            "reveal). Probability tag midpoint 0.5 - reliable "
            "in teamfights but lure projectile is dodgeable. "
            "FIRST Fizz first-order CC registration in the "
            "engine."
        ),
    )

    # Warwick E Primal Howl recast fear: E grants Warwick
    # damage reduction for up to 2.5 seconds. After 1 second of
    # the buff Warwick can RECAST E (automatically recasts on
    # buff expiration) to fear nearby enemies for 1.0 second
    # flat per effects_descriptions ("ending Primal Howl's
    # effects and fearing nearby enemies for 1 second, slowing
    # them by 90%"). Standalone E without recast = damage
    # reduction self-buff only (no fear payload until 2.5s
    # auto-recast). Maps to COND_CHANNEL_COMPLETION - the
    # fear fires only after the 1s recast-window opens AND
    # Warwick is in range of enemies when the recast triggers.
    # Probability 0.5 (tag midpoint) - the recast auto-fires
    # at 2.5s so the fear is reliable in commit fights, but
    # the radius is short (380 units) so frequently misses
    # mobile targets. Coexists with the wave 0 cc_conditional
    # Warwick R suppression on a different spell slot.
    registry.setdefault("Warwick", {})["E"] = ConditionalCcEntry(
        champion="Warwick",
        spell="E",
        cc_kind="fear",
        durations_s=(1.0,),
        condition=COND_CHANNEL_COMPLETION,
        probability=_p("Warwick", "E", 0.5),
        notes=(
            "E Primal Howl recast fear: E grants 2.5s damage "
            "reduction; recast (manual after 1s or auto on "
            "buff expiration) fears nearby enemies 1.0s flat "
            "(effects_descriptions 'fearing nearby enemies "
            "for 1 second'). Standalone E without recast = "
            "self-buff only. Maps to COND_CHANNEL_COMPLETION "
            "- fear fires only after recast window opens. "
            "Probability tag midpoint 0.5 - auto-recast at "
            "2.5s is reliable but 380-unit radius frequently "
            "misses mobile targets. Coexists with the wave 0 "
            "Warwick R suppression cc_conditional entry on a "
            "different spell slot."
        ),
    )

    # TahmKench W Abyssal Dive emerge stun: W channels 1.35s
    # as Tahm Kench dives, then blinks to the target location
    # after a 0.15s delay and remains unable-to-act for 0.65s
    # after the channel completes. Tahm Kench emerges to deal
    # magic damage AND knock up + stun nearby enemies for 1.0
    # second flat per effects_descriptions ("Tahm Kench
    # emerges to deal magic damage to nearby enemies, as well
    # as knock up and stun them for 1 second"). Standalone W
    # cast that is INTERRUPTED during the 1.35s channel
    # (Tahm Kench takes hard CC mid-dive) = no emerge payload
    # (cast fails). Maps to COND_CHANNEL_COMPLETION - the
    # stun fires only after the full 1.35 + 0.15 + 0.65s
    # cycle completes. Probability 0.5 (tag midpoint) - the
    # channel can be interrupted by stuns/silences but Tahm
    # Kench has displacement immunity during the dive itself,
    # so completion is reliable in most fight windows.
    # Coexists with the wave 0 cc_conditional TahmKench R
    # devour suppression + the wave 5 cc_conditional
    # TahmKench Q nth_hit stun on different spell slots.
    registry.setdefault("TahmKench", {})["W"] = ConditionalCcEntry(
        champion="TahmKench",
        spell="W",
        cc_kind="stun",
        durations_s=(1.0,),
        condition=COND_CHANNEL_COMPLETION,
        probability=_p("TahmKench", "W", 0.5),
        notes=(
            "W Abyssal Dive emerge stun: 1.35s channel + 0.15s "
            "blink delay + 0.65s recovery; on completion Tahm "
            "Kench emerges to knock up + stun nearby enemies "
            "1.0s flat (effects_descriptions 'knock up and "
            "stun them for 1 second'). Interrupted channel = "
            "no emerge payload. Maps to "
            "COND_CHANNEL_COMPLETION - stun fires only after "
            "full cycle completes. Probability tag midpoint "
            "0.5 - reliable in most fights given displacement "
            "immunity during dive. Coexists with the wave 0 "
            "TahmKench R devour suppression + wave 5 TahmKench "
            "Q nth_hit stun cc_conditional entries on "
            "different spell slots."
        ),
    )

    # ============================================================
    # === wave 15 expansion (2026-05-24 / ENGINE 1.52.0) - +2
    # === primary entries / +2 net-new champions sourced from
    # === systematic re-audit of the ENGINE 1.51.0 Meraki schema-
    # === lifted data file (cast_time + effects_descriptions
    # === cross-reference). The audit surfaced 110 forms across
    # === 171 champions where cast_time>0 + a CC-keyword appears
    # === in effects_descriptions; 57 of those collide with the
    # === unconditional _PER_SPELL_CC_DURATIONS registry (BLOCKED
    # === absent a same-spell-slot coexistence schema lift), 28
    # === are already-covered cc_conditional entries (no
    # === duplication), leaving 25 unsorted candidates. Of the
    # === 25, 2 close cleanly with no schema lift + no tag
    # === expansion + no collision (Zac Q + Ornn E); the
    # === remaining 23 either map to unconditional CC
    # === (Velkoz E / Blitzcrank R / Darius E / Ambessa R /
    # === Quinn R), minion-only CC (Aatrox R / Darius R /
    # === Sion E / Nunu Q), positional/transcendent state-
    # === tracking the schema does not cover (Fiddlesticks E /
    # === Taliyah E / Syndra E), knockback-not-stun-or-root
    # === (XinZhao R / Zyra R), or no first-order CC at all
    # === (Khazix Q / Aphelios R / Urgot R recast suppress).
    # === A third entry lives in the sidecar registry (Rell W
    # === form 0 Ferromancy: Crash Down channel-completion stun);
    # === see _build_per_spell_cc_conditional_forms below.
    # ===
    # === New primary entries (2 total, both net-new champions):
    # ===
    # ===   * Zac Q Stretching Strikes 2-hit cross-target root -
    # ===     COND_NTH_HIT 0.7: 0.5s root flat across all 5 Q
    # ===     ranks when the empowered second strike lands on a
    # ===     DIFFERENT target than the first (both then rooted).
    # ===   * Ornn E Searing Charge terrain-collision stun -
    # ===     COND_TERRAIN 0.3: 1.25s stun flat across all 5 E
    # ===     ranks when Ornn collides with terrain mid-charge.
    # ===     FIRST consumer of COND_TERRAIN tag (was forward-
    # ===     marker with zero consumers since wave 7).
    # ===
    # === Wave 15 REJECT verdicts (cast_time + effects_descriptions
    # === schema-verified this run; CARRY-FORWARD only if new
    # === evidence surfaces):
    # ===
    # ===   * Aatrox R World Ender post-R fear 3.0s - minion-
    # ===     only fear (effects_descriptions "fearing nearby
    # ===     enemy minions and monsters for 3 seconds"). NOT
    # ===     champion CC. REJECT (item 153 wave 9 carry-forward).
    # ===   * Darius R Noxian Guillotine execute fear 3.0s -
    # ===     minion-only fear after execute kill (effects_
    # ===     descriptions "fears nearby minions and monsters for
    # ===     3 seconds"). NOT champion CC. REJECT.
    # ===   * Sion E Roar of the Slayer stun 0.75s - minion-only
    # ===     stun (effects_descriptions "If the target is a
    # ===     minion or non-epic monster, they are also stunned
    # ===     for 0.75 seconds"). NOT champion CC. REJECT.
    # ===   * Nunu Q Consume stun - minion-only stun (effects_
    # ===     descriptions "stunning and pulling them towards
    # ===     him" gated on Consume killing the minion target).
    # ===     NOT champion CC. REJECT.
    # ===   * Ambessa R Public Execution 0.75s suppress + 0.4s
    # ===     stun - UNCONDITIONAL on primary champion target hit
    # ===     (effects_descriptions describes the full sequence
    # ===     once target seized; the cast-time gates Ambessa's
    # ===     own stationarity not the CC application). Belongs
    # ===     in _PER_SPELL_CC_DURATIONS not cc_conditional.
    # ===     REJECT (mirrors LeeSin R wave 13/14 REJECT).
    # ===   * Blitzcrank R Static Field silence - UNCONDITIONAL
    # ===     AoE silence on detonation. Belongs in
    # ===     _PER_SPELL_CC_DURATIONS not cc_conditional. REJECT.
    # ===   * Darius E Apprehend pull+brief-airborne -
    # ===     UNCONDITIONAL pull. Brief airborne (no explicit
    # ===     duration in description). REJECT.
    # ===   * Quinn R Behind Enemy Lines - no CC on enemies; the
    # ===     2-second channel is Quinn's self-channel and the
    # ===     ability buffs Valor (Quinn's familiar). REJECT.
    # ===   * Velkoz E Tectonic Disruption knockup+stun 0.75s -
    # ===     UNCONDITIONAL knockup+stun on direct hit (effects_
    # ===     descriptions "knocking them up and stunning them
    # ===     for 0.75 seconds"). The cast-time gates landing
    # ===     delay (0.25-0.55s), NOT the CC application. Belongs
    # ===     in _PER_SPELL_CC_DURATIONS not cc_conditional.
    # ===     REJECT.
    # ===   * Fiddlesticks E Reap center-target silence 1.25s -
    # ===     POSITIONAL gating (only center-of-area enemies
    # ===     silenced), not cast-time conditional. Schema does
    # ===     not encode positional sub-zones cleanly. REJECT.
    # ===   * Irelia R Vanguard's Edge perimeter knockaway -
    # ===     not airborne per description ("knocking all enemy
    # ===     units away from them, though not rendering them
    # ===     airborne"); displacement-only with no stun/root
    # ===     duration. REJECT.
    # ===   * Khazix Q Taste Their Fear - "fear" appears in
    # ===     SPELL NAME only; no actual fear CC on enemy. REJECT.
    # ===   * LeeSin R Dragon's Rage primary-target root - item
    # ===     171 wave 13 REJECT verdict carries (UNCONDITIONAL
    # ===     primary-target CC; belongs in
    # ===     _PER_SPELL_CC_DURATIONS not cc_conditional).
    # ===   * Aphelios R Moonlight Vigil Gravitum root - actually
    # ===     a Q form_index=3 entry (already shipped wave 13 as
    # ===     Aphelios:Q:3 sidecar entry); R itself has no
    # ===     first-order CC payload. REJECT.
    # ===   * Rell W form 1 Mount Up empowered AA stun 0.6s -
    # ===     gated on activating Mount Up state THEN landing
    # ===     the empowered next basic attack. NOT cast-time
    # ===     conditional - it is next-hit-after-form-transition
    # ===     conditional. Could theoretically register as
    # ===     COND_NTH_HIT but the empowerment is post-cast not
    # ===     during cast_time, and the AA must land on a
    # ===     champion target. Risky semantic - REJECT pending
    # ===     operator clarification on whether form-transition
    # ===     empowerments register here or live elsewhere.
    # ===   * Syndra E Scatter the Weak Transcendent stun 1.25s -
    # ===     STATE-tracking via Transcendent Bonus (80
    # ===     Splinters of Wrath passive accumulation). Schema
    # ===     does not encode passive-state accumulation. REJECT.
    # ===   * Taliyah Q Threaded Volley no CC. REJECT.
    # ===   * Taliyah E Unraveled Earth dash-detonation stun
    # ===     0.75s (champion) / 2.0s (monster) - condition is
    # ===     enemy DASHING or BEING DISPLACED across a stone,
    # ===     not target-debuffed or nth-hit. No clean tag fit
    # ===     in the 12 existing tags. REJECT (could fit a new
    # ===     COND_TRAVERSE tag in a future wave with operator
    # ===     authorization). Coexists potential with the
    # ===     existing wave 3 Taliyah W cc_conditional entry.
    # ===   * Urgot R Fear Beyond Death Mercy recast suppress -
    # ===     gated on target HP<25%; HP-threshold state-tracking
    # ===     the schema does not cover. The 1.5s channel-recast
    # ===     suppress is COND_TARGET_HP_BELOW conceptually but
    # ===     no existing consumer + Urgot R already has a complex
    # ===     primary leash payload. REJECT pending operator
    # ===     authorization to register first COND_TARGET_HP_BELOW
    # ===     consumer.
    # ===   * XinZhao R Crescent Guard knockback - knockback IS
    # ===     not a CC kind in the current cc_conditional schema
    # ===     (stun/root/charm/fear/silence/sleep/suppress/
    # ===     airborne only). The knockback is also gated on
    # ===     "non-Challenged" targets (Challenged is XinZhao's
    # ===     passive mark). REJECT (mechanic out of schema scope).
    # ===   * Zyra R Stranglethorns zone knockup 1.0s after 2s
    # ===     delay - UNCONDITIONAL zone knockup. Belongs in
    # ===     _PER_SPELL_CC_DURATIONS not cc_conditional. REJECT.
    # ============================================================

    # Zac Q Stretching Strikes 2-hit cross-target root: Zac casts
    # Q stretching his left arm to catch the first enemy hit
    # (damage + 40% slow + tether). The tether lingers 2 seconds;
    # while it persists Zac's NEXT basic attack is REPLACED by a
    # second Stretching Strike with 0.25s cast time + 25 bonus
    # attack range. The conditional payload fires when the two
    # strikes affect DIFFERENT targets: per effects_descriptions
    # "If the two Stretching Strikes affect different targets,
    # both are rooted for 0.5 seconds while the secondary target
    # is dealt the initial damage and applied the same slow."
    # Maps to COND_NTH_HIT - the root requires landing the 2nd
    # strike on a different enemy than the 1st strike.
    # Probability 0.7 (tag midpoint) - in teamfights Zac's Q
    # leads engages onto a primary target, the empowered second
    # strike then frequently hits a different enemy chasing or
    # collapsing. Standalone Q with same-target double-strike =
    # damage + slow only (no root). Coexists with the
    # unconditional Zac E + R entries in `_PER_SPELL_CC_DURATIONS`
    # on different spell slots.
    #
    # Mechanic schema-lift-verified: effects_descriptions[2] for
    # form 0 ("If the two Stretching Strikes affect different
    # targets, both are rooted for 0.5 seconds while the secondary
    # target is dealt the initial damage and applied the same
    # slow.") + Meraki cast_time=0.33 for the first strike. The
    # secondary slam (knockup + 0.25s stun on targets near each
    # other after displacement) is a deeper conditional layer not
    # registered here - this wave 15 entry encodes ONLY the
    # 2-target root payload that fires on the 0.5s flat duration.
    registry.setdefault("Zac", {})["Q"] = ConditionalCcEntry(
        champion="Zac",
        spell="Q",
        cc_kind="root",
        durations_s=(0.5,),
        condition=COND_NTH_HIT,
        probability=_p("Zac", "Q", 0.7),
        notes=(
            "Q Stretching Strikes 2-hit cross-target root: Zac's "
            "first Q strike applies tether + slow + damage; the "
            "empowered second strike (replaces next AA within 2s "
            "tether window) lands on a DIFFERENT target = both "
            "rooted for 0.5s flat across all 5 Q ranks per "
            "effects_descriptions. Same-target double-strike = "
            "damage + slow only (no root). Maps to COND_NTH_HIT "
            "- root requires landing the 2nd strike on a "
            "different enemy than the 1st. Probability tag "
            "midpoint 0.7 - teamfight collapses + chase patterns "
            "reliably hit different targets across the tether "
            "window. FIRST Zac Q first-order CC registration in "
            "the engine (unconditional Zac E + R entries cover "
            "the other spell slots). The secondary slam knockup "
            "+ 0.25s stun on targets-near-each-other is a deeper "
            "conditional layer NOT registered here - this entry "
            "encodes ONLY the 2-target root payload."
        ),
    )

    # Ornn E Searing Charge terrain-collision stun: Ornn charges
    # in the target direction (0.35s cast_time + travel) dealing
    # physical damage to enemies he passes through. If Ornn
    # COLLIDES with terrain during the charge, he creates a
    # shockwave that knocks up and STUNS nearby enemies for
    # 1.25 seconds flat (per effects_descriptions "If Ornn
    # collides with terrain during the charge, he creates a
    # shockwave that knocks up and stuns nearby enemies for
    # 1.25 seconds"). Standalone E without terrain collision =
    # damage only (no shockwave, no stun). Maps to COND_TERRAIN -
    # the canonical terrain-positional conditional tag. FIRST
    # consumer of COND_TERRAIN (was registered as a forward-
    # marker tag with zero consumers; this is its first
    # registration). Probability 0.3 (tag midpoint) - terrain
    # collision requires Ornn to aim at a wall and the enemy to
    # be near the wall; reliable in lane (close-to-wall fights)
    # but unreliable in open teamfights. Coexists with the wave 4
    # cc_conditional Ornn Q knockup entry on a different spell
    # slot.
    #
    # Mechanic schema-lift-verified: effects_descriptions[1] for
    # form 0 ("If Ornn collides with terrain during the charge,
    # he creates a shockwave that knocks up and stuns nearby
    # enemies for 1.25 seconds and deals the same damage if they
    # were not already hit by the charge.") + Meraki cast_time=
    # 0.35 for E. The knockup payload is separately captured by
    # the cc_pressure unconditional Ornn R registry (R has its
    # own knockup); this wave 15 entry encodes ONLY the
    # 1.25s stun-on-terrain conditional payload.
    registry.setdefault("Ornn", {})["E"] = ConditionalCcEntry(
        champion="Ornn",
        spell="E",
        cc_kind="stun",
        durations_s=(1.25,),
        condition=COND_TERRAIN,
        probability=_p("Ornn", "E", 0.3),
        notes=(
            "E Searing Charge terrain-collision stun: Ornn "
            "charges + deals damage to enemies passed through; "
            "if he COLLIDES with terrain mid-charge a shockwave "
            "knocks up + STUNS nearby enemies 1.25s flat across "
            "all 5 E ranks per effects_descriptions. Standalone "
            "E with no terrain hit = damage only (no shockwave, "
            "no stun). Maps to COND_TERRAIN - the canonical "
            "terrain-positional conditional tag. FIRST consumer "
            "of COND_TERRAIN (forward-marker tag since wave 7 "
            "schema lift). Probability tag midpoint 0.3 - "
            "terrain collision requires aiming at a wall + the "
            "enemy near it; reliable in lane / mid-Rift fights, "
            "unreliable in open teamfights. Coexists with the "
            "wave 4 Ornn Q debuffed-target knockup entry on a "
            "different spell slot."
        ),
    )

    # ============================================================
    # === wave 16 expansion (2026-05-24 / ENGINE 1.53.0) - +4
    # === primary entries / +3 net-new champions (Garen + Syndra
    # === + Udyr; KSante W is a multi-wave coexistence on the
    # === existing wave 1 KSante Q entry) sourced from the wave 15
    # === leftover
    # === candidate scan. The wave 15 audit walked all 110 forms
    # === across 171 champions with cast_time>0 + a CC keyword in
    # === effects_descriptions; wave 16 extends that scan to ALL
    # === 171 champions regardless of cast_time, surfacing 11
    # === uncovered slots with explicit duration values in
    # === effects_descriptions. Of those 11, 4 close cleanly with
    # === no schema lift + no tag expansion + no slot collision:
    # ===
    # ===   * Garen Q Decisive Strike empowered-AA silence 1.5s -
    # ===     COND_NTH_HIT 0.7. Garen Q cleanses slows + bonus MS
    # ===     + empowers the NEXT basic attack within 4.5s to
    # ===     silence the target 1.5s on hit. The single-hit
    # ===     empowered AA is the canonical nth_hit conditional
    # ===     pattern; standalone Q with no follow-up AA = MS
    # ===     buff only (no silence). FIRST Garen first-order CC
    # ===     registration in the engine.
    # ===   * Syndra E Scatter the Weak Dark-Sphere knockback
    # ===     stun 1.25s - COND_TARGET_DEBUFFED 0.5. Syndra E
    # ===     knocks back enemies for damage; if a Dark Sphere
    # ===     (Q residue) is in the cone, the sphere ALSO flies
    # ===     and stuns enemies it knocks back 1.25s flat.
    # ===     Standalone E without a sphere in path = knockback
    # ===     + damage only. Maps to COND_TARGET_DEBUFFED - the
    # ===     "debuff" is the sphere positioning that the target
    # ===     must overlap with. Distinct from the Transcendent
    # ===     Bonus 80-Splinter slow REJECTED wave 15. FIRST
    # ===     Syndra first-order CC registration in the engine.
    # ===   * Udyr E Blazing Stampede empowered-AA pounce stun
    # ===     0.75s - COND_NTH_HIT 0.7. Udyr enters Stampede
    # ===     Stance + the NEXT basic attack pounces and stuns
    # ===     0.75s. Mechanically parallel to Garen Q (single-
    # ===     hit AA-empower) with a once-per-target ICD that
    # ===     does not affect first-cast probability. Standalone
    # ===     Stance entry with no AA = MS buff only. FIRST Udyr
    # ===     first-order CC registration in the engine.
    # ===   * KSante W Path Maker recast channel stun
    # ===     0.5-1.75s - COND_CHANNEL_COMPLETION 0.5. KSante W
    # ===     charges 0.4-1.0s; recast dashes + carries enemies
    # ===     + stuns them 0.5-1.75s based on channel time. Mid-
    # ===     channel hard CC cancels the recast payload. Maps
    # ===     to COND_CHANNEL_COMPLETION - canonical channel-
    # ===     completion conditional pattern (parallel to
    # ===     Warwick R + Karma W + Pantheon Q). Standalone W
    # ===     with no recast = displacement immunity only.
    # ===     Coexists with KSante Q wave 1 cc_conditional
    # ===     entry on a different spell slot. The All Out
    # ===     (R-active) form REMOVES the stun (replaces with
    # ===     true damage); this entry encodes the BASE form
    # ===     payload only. Encoding choice: representative
    # ===     1.0s midpoint of the 0.5-1.75s range (operator
    # ===     can tune via per_entry_probability override).
    # ===
    # === Wave 16 REJECT verdicts (effects_descriptions schema-
    # === verified this run; CARRY-FORWARD only if new evidence
    # === surfaces):
    # ===
    # ===   * Ahri W priority targeting on Charmed - no CC
    # ===     application by W itself (charm comes from E).
    # ===     REJECT.
    # ===   * Aphelios R Moonlight Vigil - already shipped as
    # ===     Aphelios:Q:3 sidecar wave 13; R has no first-order
    # ===     CC. REJECT.
    # ===   * Darius E Apprehend - 1.0s airborne is UNCONDITIONAL
    # ===     pull-displacement; belongs in
    # ===     `_PER_SPELL_CC_DURATIONS` not cc_conditional.
    # ===     REJECT (matches wave 15 Darius E REJECT).
    # ===   * Irelia R perimeter knockaway - displacement only
    # ===     (per effects_descriptions "knocking all enemy
    # ===     units away from them, though not rendering them
    # ===     airborne"); the 1.5s slow is NOT CC. REJECT.
    # ===   * LeeSin R - item 171 wave 13 REJECT carries
    # ===     (UNCONDITIONAL primary-target root + knockback).
    # ===   * Milio R - cleanse + tenacity buff only, no CC
    # ===     application. REJECT.
    # ===   * Taliyah E dash-detonation stun 0.75s - wave 15
    # ===     REJECT verdict binding (would need new
    # ===     COND_TRAVERSE tag for clean fit; tag schema lift
    # ===     operator-gated).
    # ============================================================

    # Garen Q Decisive Strike empowered-AA silence: Garen casts Q to
    # cleanse himself of all slows + gain 35% bonus MS for a duration;
    # additionally his NEXT basic attack within 4.5 seconds gains an
    # uncancellable windup, lunges at the target, deals bonus physical
    # damage, AND silences them for 1.5 seconds flat across all 5 Q
    # ranks. The silence fires ONLY when the empowered AA lands; the
    # AA must land on a champion target within the 4.5s window. Maps
    # to COND_NTH_HIT - the empowered single-hit AA is the canonical
    # nth_hit conditional pattern (mirrors Alistar E Trample 5-stack
    # stun + Kennen E + Riven Q nth_hit knockup + Aatrox Q3 nth_hit
    # knockup). Probability 0.7 (tag midpoint) - 4.5s is a generous
    # window that reliably lands the empowered AA against most
    # targets unless Garen is hard-CC'd or the target Flashes away.
    # Standalone Q with no follow-up AA (within the 4.5s) = MS buff
    # cleanse only (no silence). FIRST Garen first-order CC
    # registration in the engine (Garen E + R have no champion CC).
    #
    # Mechanic schema-lift-verified: effects_descriptions[1] for
    # form 0 ("Additionally, Garen empowers his next basic attack
    # within 4.5 seconds to have an uncancellable windup, lunge at
    # the target, deal bonus physical damage, and silence them for
    # 1.5 seconds.") + Meraki damage_blocks Movement Speed Duration
    # block (the MS buff duration scales but the silence is flat).
    # The 4.5s window itself is not a Meraki damage_block but is
    # captured in effects_descriptions text.
    registry.setdefault("Garen", {})["Q"] = ConditionalCcEntry(
        champion="Garen",
        spell="Q",
        cc_kind="silence",
        durations_s=(1.5,),
        condition=COND_NTH_HIT,
        probability=_p("Garen", "Q", 0.7),
        notes=(
            "Q Decisive Strike empowered-AA silence: Garen Q "
            "cleanses slows + bonus MS + empowers NEXT basic "
            "attack within 4.5s to lunge + silence 1.5s flat "
            "across all 5 Q ranks per effects_descriptions. The "
            "silence fires ONLY when the empowered AA lands on a "
            "champion target. Standalone Q with no follow-up AA "
            "= MS buff cleanse only (no silence). Maps to "
            "COND_NTH_HIT - the empowered single-hit AA is the "
            "canonical nth_hit conditional pattern (parallel to "
            "Alistar E + Kennen E + Riven Q + Aatrox Q3 + Udyr E "
            "wave 16). Probability tag midpoint 0.7 - 4.5s window "
            "reliably lands the empowered AA absent hard CC on "
            "Garen or target Flash. FIRST Garen first-order CC "
            "registration in the engine (Garen E + R have no "
            "champion CC payload)."
        ),
    )

    # Syndra E Scatter the Weak Dark-Sphere knockback stun: Syndra
    # E (0.25s cast_time) propels a wave of force in a cone in the
    # target direction, knocking back enemies for damage. If a
    # Dark Sphere (Q residue placed earlier) sits in the cone, the
    # sphere ALSO flies and knocks back enemies it hits PLUS stuns
    # them for 1.25 seconds flat across all 5 E ranks. The stun
    # fires ONLY when an enemy is hit by a PUSHED Dark Sphere -
    # standalone E without a sphere in path = damage + knockback
    # only (no stun). Maps to COND_TARGET_DEBUFFED - the
    # "debuff" is the sphere positioning the target must overlap
    # with at the moment of cast. Mechanically distinct from the
    # Transcendent Bonus 80-Splinter slow (REJECTED wave 15 for
    # state-tracking). Probability 0.5 (tag midpoint) - sphere
    # positioning + cone alignment is the operator's combo
    # responsibility; reliable in lane (Q sphere telegraph) but
    # less reliable in open teamfights. FIRST Syndra first-order
    # CC registration in the engine (Syndra Q + W + R have no
    # champion CC; the R execute is damage-only).
    #
    # Mechanic schema-lift-verified: effects_descriptions[1] for
    # form 0 ("Dark Spheres can be knocked back for 950 units and
    # up to 1200 units away from Syndra based on proximity,
    # knocking back enemies they hit over 70 units, though not
    # through terrain. Targets hit are also stunned for 1.25
    # seconds, during which they are also revealed, and dealt
    # Scatter the Weak's damage if they were not damaged by the
    # initial cast.") + Meraki cast_time=0.25 for form 0.
    registry.setdefault("Syndra", {})["E"] = ConditionalCcEntry(
        champion="Syndra",
        spell="E",
        cc_kind="stun",
        durations_s=(1.25,),
        condition=COND_TARGET_DEBUFFED,
        probability=_p("Syndra", "E", 0.5),
        notes=(
            "E Scatter the Weak Dark-Sphere knockback stun: "
            "Syndra E propels a knockback cone; if a Dark "
            "Sphere (Q residue) sits in the cone path, sphere "
            "ALSO flies + STUNS targets 1.25s flat across all "
            "5 E ranks per effects_descriptions. Standalone E "
            "without sphere = damage + knockback only (no "
            "stun). Maps to COND_TARGET_DEBUFFED - the "
            "'debuff' is the sphere positioning at moment of "
            "cast (target overlap with pushed sphere path). "
            "Distinct from Transcendent 80-Splinter slow "
            "(REJECTED wave 15 for state-tracking). Probability "
            "tag midpoint 0.5 - sphere placement + cone "
            "alignment is operator combo work; reliable in lane "
            "telegraphed plays, less so in open teamfights. "
            "FIRST Syndra first-order CC registration in the "
            "engine (Q + W + R have no champion CC; R execute "
            "is damage-only)."
        ),
    )

    # Udyr E Blazing Stampede empowered-AA pounce stun: Udyr E
    # enters Stampede Stance + ghosts + bonus MS (4s decay). His
    # NEXT basic attack gains an uncancellable windup, pounces on
    # the target, deals normal AA damage, AND stuns them for 0.75
    # seconds flat across all 5 E ranks. The stun cannot affect
    # the same target more than once every few seconds (ICD that
    # does NOT affect first-cast probability). Maps to
    # COND_NTH_HIT - the empowered single-hit AA pounce is the
    # canonical nth_hit conditional pattern (parallel to Garen Q
    # silence wave 16 + Alistar E + Kennen E + Riven Q + Aatrox
    # Q3 nth_hit knockup). Probability 0.7 (tag midpoint) - 4-
    # second Stance window reliably lands the pounce-AA absent
    # hard CC on Udyr or target Flash. Standalone Stance entry
    # with no AA = MS buff + ghosting only (no stun). FIRST Udyr
    # first-order CC registration in the engine.
    #
    # Mechanic schema-lift-verified: effects_descriptions[0] for
    # form 0 ("Active - Stance: Udyr enters Stampede Stance,
    # empowering his basic attacks to have an uncancellable
    # windup and pounce on the target to stun them for 0.75
    # seconds. This cannot affect the same target more than once
    # every few seconds.") + Meraki damage_blocks confirm the
    # 4s MS buff duration scales but the stun is flat.
    registry.setdefault("Udyr", {})["E"] = ConditionalCcEntry(
        champion="Udyr",
        spell="E",
        cc_kind="stun",
        durations_s=(0.75,),
        condition=COND_NTH_HIT,
        probability=_p("Udyr", "E", 0.7),
        notes=(
            "E Blazing Stampede empowered-AA pounce stun: Udyr "
            "E enters Stampede Stance + ghosting + bonus MS; "
            "NEXT basic attack pounces + stuns 0.75s flat "
            "across all 5 E ranks per effects_descriptions. "
            "Once-per-target ICD that does NOT affect first-"
            "cast probability. Standalone Stance entry with no "
            "AA = MS buff + ghosting only (no stun). Maps to "
            "COND_NTH_HIT - the empowered single-hit AA pounce "
            "is the canonical nth_hit conditional pattern "
            "(parallel to Garen Q wave 16 silence + Alistar E + "
            "Kennen E + Riven Q + Aatrox Q3 nth_hit knockup). "
            "Probability tag midpoint 0.7 - 4-second Stance "
            "window reliably lands the pounce-AA absent hard "
            "CC on Udyr or target Flash. FIRST Udyr first-order "
            "CC registration in the engine."
        ),
    )

    # KSante W Path Maker recast channel-completion stun: KSante
    # W raises ntofos defensively + prepares to dash; charges for
    # 0.4-1.0s gaining displacement immunity + 30% damage
    # reduction. Path Maker's range, stun duration, and All Out
    # bonus true damage modifier all SCALE WITH CHANNEL TIME over
    # the first 0.9s of charge. RECAST dashes in the targeted
    # direction, deals damage to enemies passed through, carries
    # them alongside, AND stuns them for 0.5-1.75 seconds based
    # on channel time. Maps to COND_CHANNEL_COMPLETION - the
    # canonical channel-completion conditional pattern (parallel
    # to Warwick R + Karma W + Pantheon Q + Sion R + Renata Q +
    # Rell W form 0). The cast is interruptible BY CROWD CONTROL
    # ONLY mid-channel (the description explicitly notes "Path
    # Maker's charge cannot be interrupted by crowd control" so
    # standard CC effects don't cancel mid-charge; however the
    # All Out form REMOVES the stun). Probability 0.5 (tag
    # midpoint) - KSante typically holds the charge to threshold
    # for max-range stun then dashes; the conditional gate is
    # the cast itself completing rather than mid-channel
    # interruption. The All Out (R-active) form REMOVES this
    # stun (replaces with true damage); this entry encodes the
    # BASE form payload only. Encoding choice: representative
    # 1.0s midpoint of the 0.5-1.75s range; operator can tune
    # via per_entry_probability override. Coexists with KSante Q
    # wave 1 cc_conditional entry on a different spell slot.
    #
    # Mechanic schema-lift-verified: effects_descriptions[2] for
    # form 0 ("Recast: K'Sante dashes in the direction he
    # targeted at the time of cast, though not through terrain,
    # dealing physical damage to enemies he passes through,
    # carrying them alongside him, and stunning them for 0.5 :
    # 1.75 (based on channel time) seconds.").
    registry.setdefault("KSante", {})["W"] = ConditionalCcEntry(
        champion="KSante",
        spell="W",
        cc_kind="stun",
        durations_s=(1.0,),
        condition=COND_CHANNEL_COMPLETION,
        probability=_p("KSante", "W", 0.5),
        notes=(
            "W Path Maker recast channel-completion stun: "
            "KSante W charges 0.4-1.0s + recast dashes + "
            "carries enemies + STUNS them 0.5-1.75s based on "
            "channel time per effects_descriptions. Stored as "
            "representative 1.0s midpoint of the 0.5-1.75s "
            "range; operator can tune via per_entry_probability "
            "override key KSante:W. Maps to "
            "COND_CHANNEL_COMPLETION - canonical channel-"
            "completion pattern (parallel to Warwick R + "
            "Karma W + Pantheon Q + Sion R + Renata Q + Rell W "
            "form 0). Probability tag midpoint 0.5 - reliable "
            "in operator-pace engages where KSante holds the "
            "charge to threshold. The All Out (R-active) form "
            "REMOVES this stun (replaces with true damage); "
            "this entry encodes the BASE form payload only. "
            "Coexists with KSante Q wave 1 cc_conditional "
            "entry on a different spell slot. FIRST KSante W "
            "first-order CC registration in the engine."
        ),
    )

    # ============================================================
    # === wave 17 expansion (2026-05-24 / ENGINE 1.54.0) - +1
    # === entry / 0 net-new champions (Taliyah already in
    # === registry with W wave 1 channel-completion knockup) via
    # === a NEW COND_TRAVERSE condition tag schema lift. Closes
    # === item 174 carry (i) "Taliyah E needs new COND_TRAVERSE
    # === tag - operator-gated" + the wave 14 + wave 16 REJECT
    # === carries flagging the same Taliyah E mechanic as
    # === requiring a new tag for clean fit.
    # ===
    # === The Taliyah E Unraveled Earth mechanic is canonically
    # === a TRAVERSE-conditional stun: Taliyah scatters a field
    # === of stones across the ground; enemies who DASH OR ARE
    # === KNOCKED OVER a stone detonate it, taking magic damage
    # === and becoming STUNNED for 0.75 seconds (champion target;
    # === 2.0s if monster). Standalone enemy who walks AROUND
    # === the field never triggers the stun. The mechanic does
    # === not fit COND_TERRAIN (which is collision with map
    # === geometry, not a spell-placed object), does not fit
    # === COND_NTH_HIT (no stack accumulation), and does not fit
    # === COND_TARGET_DEBUFFED (no pre-applied mark - the stone
    # === is a ground zone, not a debuff). COND_TRAVERSE captures
    # === the "enemy displacement over placed object" semantic
    # === precisely.
    # ===
    # === Multi-wave coexistence count: Taliyah W (wave 1
    # === channel-completion knockup) + Taliyah E (wave 17
    # === traverse-conditional stun) becomes the 7th multi-entry-
    # === within-cc_conditional champion (after Aatrox Q+W /
    # === Brand Q+R / Briar Q+E / TahmKench R+Q / KSante Q+W /
    # === Sion R + Sion Q from prior waves - or similar count
    # === depending on rolling totals; the test guard uses
    # === assertGreaterEqual to stay forward-compatible).
    # ===
    # === REGISTRY GROWS: 64 entries -> 65 entries / 54
    # === champions -> 54 champions (Taliyah already counted
    # === via wave 1 W entry; this is multi-wave coexistence on
    # === the SAME champion via setdefault on a different spell
    # === slot). Condition tag total grows 12 -> 13 with the
    # === new COND_TRAVERSE constant.
    # ===
    # === Default include_conditional=False compute_cc_pressure
    # === is BYTE-IDENTICAL to 1.53.0 for Taliyah (base = 0.0
    # === unchanged; Taliyah has no unconditional
    # === _PER_SPELL_CC_DURATIONS entry).
    # ============================================================

    # Taliyah E Unraveled Earth dash-detonation stun: Taliyah
    # scatters a field of 22 stones across the ground in the
    # target direction. The stones remain for 4 seconds + slow
    # enemies within the area by 20% (the slow is unconditional
    # but is NOT first-order CC). Enemies that DASH OR ARE
    # KNOCKED OVER a stone DETONATE it - taking magic damage AND
    # becoming STUNNED for 0.75 seconds (2.0 seconds if monster).
    # The stun is applied once the displacement ENDS. An enemy
    # can detonate up to 4 stones per cast but the stun only
    # fires once per cast per target (Unraveled Earth can affect
    # targets only once per cast). Standalone enemy who never
    # dashes / is never displaced across a stone = damage + slow
    # only (no first-order CC). Maps to COND_TRAVERSE - the
    # FIRST consumer of the wave 17 forward-marker schema lift,
    # closing the COND_TRAVERSE empty-registry contract on ship.
    #
    # Probability 0.3 (tag midpoint) - champions typically AVOID
    # the telegraphed stone field unless forced through it by
    # ally CC / dash mechanics / need-to-pass-through pathing
    # constraints. The reliable consumer cases are (a) enemy
    # mid-dash through the field after Taliyah pre-places, and
    # (b) ally CC chains that knock enemies over stones (e.g.
    # JarvanIV EQ knockup placing the target in field path).
    # Lower than COND_NTH_HIT 0.7 (stacks accumulate naturally
    # in fights) and equal to COND_TERRAIN 0.3 (both require
    # operator positioning + target movement coincidence). FIRST
    # Taliyah E first-order CC registration in the engine
    # (Taliyah Q + W + R have no champion CC; Q+Worked Ground
    # monster stun is monster-only NOT champion).
    #
    # Mechanic schema-lift-verified: effects_descriptions[1] for
    # form 0 ("Enemies that dash or are knocked over a stone
    # will detonate it, taking magic damage and becoming stunned
    # for 0.75 seconds, increased to 2 seconds if they are a
    # monster. The stun is applied once the displacement ends.")
    # captured by the ENGINE 1.46.0 Meraki schema lift. The
    # 0.75s duration is the champion-target value; the 2.0s
    # monster value is encoded as MONSTER-ONLY in the
    # description so the registry stores the champion-facing
    # value only. Coexists with Taliyah W wave 1 cc_conditional
    # entry on a different spell slot via setdefault. Distinct
    # from Taliyah Q Worked Ground Boulder monster-stun
    # (monster-only).
    registry.setdefault("Taliyah", {})["E"] = ConditionalCcEntry(
        champion="Taliyah",
        spell="E",
        cc_kind="stun",
        durations_s=(0.75,),
        condition=COND_TRAVERSE,
        probability=_p("Taliyah", "E", 0.3),
        notes=(
            "E Unraveled Earth dash-detonation stun: Taliyah "
            "scatters 22 stones across the ground; enemies who "
            "DASH OR ARE KNOCKED OVER a stone detonate it + are "
            "STUNNED for 0.75s (champion; 2.0s monster) per "
            "effects_descriptions. Standalone enemy who walks "
            "AROUND the field = damage + 20% slow only (no "
            "first-order CC). Maps to COND_TRAVERSE - FIRST "
            "consumer of the wave 17 forward-marker tag schema "
            "lift, closing the COND_TRAVERSE empty-registry "
            "contract on ship. Probability tag midpoint 0.3 - "
            "champions typically AVOID the telegraphed stone "
            "field; reliable consumer cases are enemy mid-dash "
            "through the field after Taliyah pre-places + ally "
            "CC chains that knock enemies over stones. Coexists "
            "with Taliyah W wave 1 cc_conditional entry on a "
            "different spell slot via setdefault. FIRST Taliyah "
            "E first-order CC registration in the engine "
            "(Q + W + R have no champion CC; Q Worked Ground "
            "Boulder stun is monster-only NOT champion). Closes "
            "item 174 carry (i) Taliyah E needs new "
            "COND_TRAVERSE tag - operator-gated. Mechanic "
            "captured by ENGINE 1.46.0 Meraki schema lift."
        ),
    )

    # ============================================================
    # === wave 18 expansion (2026-05-24 / ENGINE 1.55.0) - +2
    # === primary entries / +1 net-new champion (Maokai R distance-
    # === gated root coexists with the unconditional Maokai R entry
    # === in `_PER_SPELL_CC_DURATIONS` via the NEW
    # === coexists_with_unconditional schema-lift flag; Briar R
    # === Hematomania impact fear is a clean new entry on a new
    # === Briar spell slot R - Briar already has Q wave 4 + E wave 5
    # === entries so Briar is NOT net-new, only Maokai is).
    # ===
    # === Wave 18 SCHEMA LIFT: ConditionalCcEntry gains the
    # === ``coexists_with_unconditional`` boolean field (default
    # === False). When True, the entry declares that the same
    # === (champion, spell) slot ALSO holds an unconditional CC
    # === entry in ``_PER_SPELL_CC_DURATIONS``. The consumer-side
    # === ``compute_cc_pressure(include_conditional=True)`` math
    # === credits MAX(unconditional_post_tenacity,
    # === conditional_post_tenacity) per slot - NEVER the sum.
    # === This closes the long-deferred Maokai R distance-gated
    # === root (item 170 + 172 + 173 + 174 + 175 carry forward;
    # === would have double-counted before the schema lift).
    # ===
    # === Wave 18 RE-AUDIT CONCLUSIONS for the other operator-
    # === flagged spec candidates:
    # ===
    # ===   * Renekton W Ruthless Predator Reign-of-Anger empowered
    # ===     stun 1.5s - ALREADY SHIPPED wave 9 (ENGINE 1.46.0,
    # ===     item 153) as the FIRST consumer of COND_FRENZY_STATE
    # ===     tag. The wave 7 schema-lift carry-forward referring
    # ===     to Renekton W is OBSOLETE - the mechanic is fully
    # ===     captured. No state-tracking tag (COND_FURY_50) needed
    # ===     because the existing COND_FRENZY_STATE tag with its
    # ===     0.4 midpoint already covers Fury-state-gated CC.
    # ===
    # ===   * Karma W form 1 Renewal Mantra-bonus root extension
    # ===     - ALREADY SHIPPED wave 10 (ENGINE 1.47.0, item 154)
    # ===     in the sidecar registry as the SECOND consumer of
    # ===     COND_FRENZY_STATE tag. The wave 7 carry-forward is
    # ===     OBSOLETE.
    # ===
    # ===   * Hwei E form 1 Grim Visage Disable fear 1.0-1.5s -
    # ===     ALREADY SHIPPED wave 9 (ENGINE 1.46.0, item 153) as
    # ===     the PRIMARY registry entry. The wave 7 carry-forward
    # ===     was misleading - the channel-completion mechanic was
    # ===     covered.
    # ===
    # ===   * Hwei E form 2 Gaze of the Abyss root - ALREADY
    # ===     SHIPPED wave 10 (ENGINE 1.47.0, item 154) in the
    # ===     sidecar.
    # ===
    # ===   * Neeko E Empowered Root 1.8-3.0s - ALREADY SHIPPED
    # ===     wave 9 (ENGINE 1.46.0, item 153) as the COND_DUAL_ENEMY
    # ===     primary entry. The wave 7 carry-forward is OBSOLETE.
    # ===
    # ===   * Aatrox post-R passive empowered abilities - REJECT
    # ===     re-verified (item 153 + wave 18 audit). The Meraki
    # ===     16.10.1 effects_descriptions for Aatrox R confirms
    # ===     "fearing nearby enemy MINIONS AND MONSTERS for 3
    # ===     seconds" - minion/monster ONLY, not champions. The
    # ===     post-R "passive empowered Q-sweetspot/W-pull" notion
    # ===     in items 150/151/152 audit notes was speculative;
    # ===     the schema-lifted description does NOT empower Q or
    # ===     W during R. Q3 sweetspot knockup 0.5s is already in
    # ===     cc_conditional wave 3 as Aatrox Q primary entry
    # ===     (NOT R-gated).
    # ===
    # ===   * Volibear R Stormbringer passive form - REJECT
    # ===     re-verified. effects_descriptions confirms only
    # ===     turret-disable + 50% slow (1s decaying). Slow is NOT
    # ===     first-order CC; turret-only disable is NOT champion
    # ===     CC. Stormbringer is a self-buff (ghosting + bonus
    # ===     health + range + size) with no champion-facing CC.
    # ===
    # ===   * Briar W Blood Frenzy empowered Q/E/R - REJECT
    # ===     re-verified. effects_descriptions for Briar W
    # ===     confirms self-buff frenzy state (ghosting + AS + MS
    # ===     + AoE-around-target AA empowerment) but NO CC granted
    # ===     to Q/E/R while in frenzy. Briar Q stun 0.85s is in
    # ===     unconditional `_PER_SPELL_CC_DURATIONS` separately;
    # ===     Briar W form 1 (Snack Attack) is bite + damage only.
    # ===     Briar E charge fear / knockback is already in
    # ===     cc_conditional wave 5.
    # ===
    # === Net wave 18 ship list = 2 entries:
    # ===   (1) Maokai R distance-gated max-root + coexistence flag
    # ===   (2) Briar R Hematomania impact non-marked target fear
    # ===
    # === Registry growth (primary registry):
    # ===   58 primary + 7 sidecar = 65 entries / 54 champions
    # ===   (ENGINE 1.54.0)
    # === Post wave 18:
    # ===   60 primary + 7 sidecar = 67 entries / 55 champions
    # ===   (ENGINE 1.55.0) (Maokai NEW; Briar already in registry)
    # ===
    # === Condition tag total UNCHANGED at 13 (Maokai R reuses
    # === COND_RANGE_GATED forward-marker - this is the FIRST
    # === consumer of COND_RANGE_GATED, closing the empty-registry
    # === contract; Briar R reuses COND_TARGET_DEBUFFED). No new
    # === condition tag constants this wave.
    # ============================================================

    # Maokai R Nature's Grasp: 5 thorny brambles advance in the target
    # direction; each bramble roots first-hit enemies. The actual root
    # duration scales from 0.75s minimum (close-distance impact) up to
    # 2.25s maximum (far-distance impact, full-bramble-travel). Per
    # Meraki 16.10.1 effects_descriptions: "Each bramble deals magic
    # damage to enemies hit and roots them for 0.75 : 2.25 (based on
    # distance traveled) seconds." The unconditional
    # `_PER_SPELL_CC_DURATIONS["Maokai"]["R"] = (1.2, 1.6, 2.0)` entry
    # encodes per-rank MID-distance estimates (mid-distance impact at
    # ranks 1/2/3 yields ~1.2/1.6/2.0s). The cc_conditional entry here
    # encodes the FAR-DISTANCE 2.25s payoff gated on Maokai landing
    # the brambles at maximum travel range. Maps to COND_RANGE_GATED -
    # FIRST consumer of the wave 7 forward-marker tag, closing the
    # COND_RANGE_GATED empty-registry contract that has been pending
    # since ENGINE 1.44.0.
    #
    # SCHEMA LIFT: ``coexists_with_unconditional=True`` declares that
    # the same (Maokai, R) slot ALSO holds the unconditional entry in
    # `_PER_SPELL_CC_DURATIONS`. The consumer-side
    # ``compute_cc_pressure(include_conditional=True)`` math credits
    # MAX(unconditional_post_tenacity, conditional_post_tenacity) for
    # this slot - NEVER both summed. This avoids the long-deferred
    # double-count concern (item 170 + 172 + 173 + 174 + 175 carry
    # forward) while still letting the operator opt into the far-
    # distance bonus credit when include_conditional=True.
    #
    # Probability: tag midpoint COND_RANGE_GATED 0.4 reflects the
    # fraction of Maokai R casts that land at the far-distance band
    # (Maokai must place the brambles to clip at max-travel; close-
    # range engages get the mid-distance value via the unconditional
    # entry instead).
    #
    # Probability-weighted contribution at MAX (R rank 3, far distance):
    #   2.25s * 0.4 = 0.9s post-probability.
    # vs unconditional rank 3 mid-distance:
    #   2.0s flat.
    # Consumer MAX rule selects the unconditional 2.0s for Maokai R
    # in the default calibration - the conditional only beats the
    # unconditional if the operator tunes the probability above ~0.89
    # via per_entry_probability override (Maokai:R = 0.9 lifts the
    # conditional contribution to 2.025s, JUST above unconditional
    # 2.0s). This is the intended operator-tunable behavior.
    registry.setdefault("Maokai", {})["R"] = ConditionalCcEntry(
        champion="Maokai",
        spell="R",
        cc_kind="root",
        durations_s=(2.25,),
        condition=COND_RANGE_GATED,
        probability=_p("Maokai", "R", 0.4),
        notes=(
            "R Nature's Grasp distance-gated root: brambles root "
            "0.75-2.25s scaling on distance traveled per Meraki "
            "16.10.1 effects_descriptions ('0.75 : 2.25 based on "
            "distance traveled'). Encoded at MAX-distance 2.25s "
            "with COND_RANGE_GATED tag (FIRST consumer of the "
            "wave 7 forward-marker tag - closes the empty-registry "
            "contract pending since ENGINE 1.44.0). "
            "coexists_with_unconditional=True declares same-slot "
            "coexistence with the unconditional Maokai R entry "
            "(1.2/1.6/2.0s per-rank mid-distance values in "
            "`_PER_SPELL_CC_DURATIONS`). Consumer math: at "
            "include_conditional=True the MAX rule credits the "
            "larger of the unconditional post-tenacity (2.0s rank "
            "3) or the conditional post-tenacity (2.25 * 0.4 = "
            "0.9s default) - never both summed. Operator can tune "
            "via per_entry_probability `Maokai:R` to lift the "
            "conditional above the unconditional (Maokai:R = 0.9 "
            "lifts to 2.025s vs unconditional 2.0s). Mechanic "
            "captured by ENGINE 1.46.0 Meraki schema lift. Closes "
            "items 170 + 172 + 173 + 174 + 175 carry forward "
            "(Maokai R distance-gated needs same-spell-slot "
            "coexistence schema lift)."
        ),
        coexists_with_unconditional=True,
    )

    # Briar R Certain Death (Hematomania impact non-marked fear):
    # Briar's R kicks her pillory's hemolith in the target direction,
    # marking the first enemy champion hit as prey. On hit, Briar
    # cleanses herself + dashes to the marked target with displacement
    # immunity. UPON ARRIVAL she creates an explosion that deals magic
    # damage to the marked target AND nearby enemies AND fears ALL
    # NON-MARKED targets in the explosion radius for 1.5 seconds (per
    # Meraki 16.10.1 effects_descriptions: "fears all non-marked
    # targets for 1.5 seconds, during which they are slowed by 35%").
    # The marked target itself receives damage but no fear (R is
    # single-target chase, not single-target fear). The fear is
    # genuinely first-order champion CC fired conditionally on:
    #   (1) The marked-target dash arriving (Briar must complete the
    #       channel + dash to deliver the explosion);
    #   (2) Non-marked enemies being inside the explosion radius
    #       (teamfight-conditional - 1v1 on the marked target yields
    #       no fear).
    #
    # Maps to COND_TARGET_DEBUFFED with the inverse semantic: fires on
    # NON-DEBUFFED (non-marked) targets within range when the mark
    # itself has been applied to a different enemy. This is the
    # closest existing tag fit; the tag covers "fires only when target
    # is in a specific debuff state" - here the relevant state is the
    # OTHER target's marked-state which determines which enemies in
    # the AoE receive the fear. Alternative encoding would be
    # COND_DUAL_ENEMY (requires 2+ enemies = marked + non-marked) but
    # COND_TARGET_DEBUFFED captures the mark-mechanic more precisely.
    # Probability 0.5 (tag midpoint) - typical Briar R engage has
    # 1-3 teammates near the marked target so the fear lands with
    # mid-to-high frequency. The fear duration 1.5s flat across all
    # 3 R ranks per effects_descriptions.
    #
    # Briar registry growth: existing entries Q wave 4 (terrain stun
    # 1.0s) + E wave 5 (channel-completion fear 1.0s); R wave 18 is
    # the THIRD Briar entry, making Briar the 4TH 3-slot champion in
    # cc_conditional after TahmKench (Q+W+R) and Taliyah (W+E) -
    # actually NO, Taliyah is 2-slot. Briar becomes the SECOND 3-slot
    # champion after TahmKench. No coexistence flag needed - Briar
    # has NO unconditional `_PER_SPELL_CC_DURATIONS` entry for R
    # (R is a single-target chase mark + dash + explosion mechanic
    # encoded entirely via cc_conditional).
    #
    # FIRST Briar R first-order CC registration anywhere - the
    # earlier waves only captured Q dash-terrain-stun + E charge-fear,
    # not the Hematomania impact fear which lives in the R
    # description text and was not flagged in prior REJECT carries.
    # Discovered during the wave 18 schema-lift re-audit of Briar
    # description text alongside the Briar W self-buff verification.
    registry.setdefault("Briar", {})["R"] = ConditionalCcEntry(
        champion="Briar",
        spell="R",
        cc_kind="fear",
        durations_s=(1.5,),
        condition=COND_TARGET_DEBUFFED,
        probability=_p("Briar", "R", 0.5),
        notes=(
            "R Certain Death Hematomania impact fear: on dash "
            "arrival, the explosion fears all NON-MARKED enemies in "
            "radius for 1.5s flat across all 3 R ranks per Meraki "
            "16.10.1 effects_descriptions ('fears all non-marked "
            "targets for 1.5 seconds'). Marked target receives "
            "damage but no fear (single-target chase mark). Maps "
            "to COND_TARGET_DEBUFFED with the inverse mark-state "
            "semantic: the fear gates on non-marked status of the "
            "AoE targets, which the marked-debuff-on-different-"
            "enemy condition gates. Probability midpoint - typical "
            "Briar R engage has 1-3 teammates near the marked "
            "target so the fear lands with mid-to-high frequency. "
            "No coexistence flag - Briar has no unconditional R "
            "entry in `_PER_SPELL_CC_DURATIONS`. THIRD Briar entry "
            "in cc_conditional after Q wave 4 + E wave 5; Briar "
            "becomes the SECOND 3-slot cc_conditional champion "
            "after TahmKench. FIRST Briar R first-order CC "
            "registration anywhere. Discovered during wave 18 "
            "re-audit of Briar description text. Mechanic captured "
            "by ENGINE 1.46.0 Meraki schema lift."
        ),
    )

    # ---------------- wave 20 entries (2026-05-25, ENGINE 1.58.0) ---
    # Wave 20 schema lift (Meraki `notes` field on every spell form;
    # tools/daemon_slayer_abilities_extract.py + ENGINE 1.58.0)
    # surfaces 1 ship-candidate from re-audit of the operator-brief
    # named entries (Kindred E / Diana P / Vayne P) PLUS the
    # cross-audit of Vayne E that the operator brief did NOT name
    # but matches the wave-7 forward-marker COND_TERRAIN tag cleanly.
    #
    # REJECT verdicts for the 3 brief-named carries:
    #
    #   * Kindred E Mounting Dread - effects_descriptions text:
    #     "slows them by 30% (+ 5% per 100 AP) for 1 second and
    #     marks them for 4 seconds". Slow only. The third stack
    #     directs Wolf to pounce for damage; missing-HP crit
    #     threshold. NO hard CC. The `notes` field carries only
    #     casting cancel + bug clauses, no CC duration override.
    #     REJECT.
    #   * Diana P Moonsilver Blade - effects_descriptions text:
    #     "Diana gains 15% : 35% (based on level) bonus attack
    #     speed. After casting an ability, this bonus is tripled
    #     to 45% : 105% (based on level) for 5 seconds". Pure
    #     AS bonus. NO CC mechanic at all. The `notes` field
    #     carries only structure-targeting + bug clauses.
    #     REJECT.
    #   * Vayne P Night Hunter - effects_descriptions text:
    #     "Vayne gains 30 bonus movement speed while facing a
    #     nearby visible enemy champion, increased to 90 while
    #     under the effects of Final Hour". Pure MS bonus. NO
    #     CC mechanic at all. The `notes` field carries only the
    #     2s sight-loss persistence clause. REJECT.
    #
    # Vayne E Condemn (terrain-collision stun): the cross-audit
    # surfaced this as a 4th candidate the brief did NOT name.
    # effects_descriptions text: "If the target collides with
    # terrain, they take bonus physical damage and become stunned
    # for 1.5 seconds" - terrain-collision conditional stun 1.5s
    # flat across all 5 E ranks. The `notes` field adds nuance:
    # "Condemn's stun duration starts when Vayne's target collides
    # with a wall (they can be immobilized for up to 2 seconds
    # depending on displacement duration based on distance
    # traveled)" - the 1.5s is fixed; the additional 0.5s is the
    # displacement-distance-scaled travel time AFTER the cast
    # ends. Encoded at the canonical 1.5s stun for the consumer.
    # Maps to COND_TERRAIN (prob 0.3) - SECOND consumer of the
    # wave 7 forward-marker tag after Ornn E wave 15. Vayne joins
    # the registry as a NEW cc_conditional champion (was not in
    # the registry under any prior wave).
    #
    # SCHEMA LIFT: ``coexists_with_unconditional=True`` declares
    # that the same (Vayne, E) slot ALSO holds the unconditional
    # entry in `_PER_SPELL_CC_DURATIONS["Vayne"]["E"] = (0.5,
    # 0.5, 0.5, 0.5, 0.5)` - the 0.5s knockback that always lands
    # (terrain-miss path). Consumer-side
    # ``compute_cc_pressure(include_conditional=True)`` math
    # credits MAX(unconditional_post_tenacity, conditional_post_
    # tenacity) for this slot - NEVER both summed. The unconditional
    # 0.5s knockback represents the no-wall miss path; the
    # conditional 1.5s * 0.3 = 0.45s represents the wall-hit
    # weighted expectation. Default calibration: unconditional
    # 0.5s wins. Operator can tune Vayne:E above 0.34 to flip
    # the conditional above the unconditional.
    #
    # Probability midpoint 0.3 reflects the wall-hit fraction in
    # a typical 6s fight window. Vayne is a marksman who keeps
    # distance from walls + targets in lane phase; her terrain
    # stun typically lands in skirmishes near jungle camps,
    # river entrances, or alcoves. Mid frequency.
    #
    # FIRST Vayne first-order CC registration anywhere. Discovered
    # during wave 20 schema-lift re-audit of the Vayne ability set
    # alongside the brief-named carries.
    registry.setdefault("Vayne", {})["E"] = ConditionalCcEntry(
        champion="Vayne",
        spell="E",
        cc_kind="stun",
        durations_s=(1.5, 1.5, 1.5, 1.5, 1.5),
        condition=COND_TERRAIN,
        probability=_p("Vayne", "E", 0.3),
        notes=(
            "E Condemn terrain-collision stun: knockback 475u + "
            "if target collides with terrain, bonus physical damage "
            "+ 1.5s stun flat across all 5 E ranks per Meraki "
            "16.10.1 effects_descriptions ('become stunned for "
            "1.5 seconds'). The Meraki `notes` field captures the "
            "ENGINE 1.58.0 schema lift detail: 'Condemn's stun "
            "duration starts when Vayne's target collides with a "
            "wall (they can be immobilized for up to 2 seconds "
            "depending on displacement duration based on distance "
            "traveled)' - the 1.5s is the fixed canonical stun "
            "duration; the additional 0.5s is displacement-distance"
            "-scaled travel time before the stun starts (modeled "
            "as 1.5s for the consumer). Maps to COND_TERRAIN (prob "
            "0.3) - SECOND consumer of the wave 7 forward-marker "
            "tag after Ornn E wave 15. coexists_with_unconditional"
            "=True declares same-slot coexistence with the "
            "unconditional Vayne E 0.5s knockback entry in "
            "`_PER_SPELL_CC_DURATIONS` (the no-wall miss path). "
            "Consumer math: at include_conditional=True the MAX "
            "rule credits the larger of unconditional 0.5s or "
            "conditional 1.5 * 0.3 = 0.45s default (operator can "
            "tune via per_entry_probability `Vayne:E` to lift the "
            "conditional above the unconditional). FIRST Vayne "
            "first-order CC registration anywhere. Discovered "
            "during wave 20 (ENGINE 1.58.0) re-audit of operator "
            "brief named carries Kindred E + Diana P + Vayne P "
            "(all 3 REJECT-verified at parse-strip + notes-lift "
            "level: Kindred E slow only / Diana P AS bonus only "
            "/ Vayne P MS bonus only). Vayne E was the 4th "
            "candidate the audit surfaced as a genuine winner."
        ),
        coexists_with_unconditional=True,
    )

    # ---------------- wave 21 entries (2026-05-25, ENGINE 1.59.0) ---
    # Wave 21 re-audits prior-wave REJECT carries against the new
    # ENGINE 1.58.0 ``notes`` schema-lifted field. The full-fleet
    # filter (916 forms with non-null notes; CC-verb + condition-gate
    # regex against post-boilerplate-stripped notes text;
    # registry-membership filter against `_PER_SPELL_CC_DURATIONS` +
    # cc_conditional primary + sidecar registries) surfaced 113
    # candidates from the post-strip notes text. Triage of the top
    # ~40 against full effects_descriptions + notes content yields
    # TWO valid ship candidates - both on Xin Zhao, neither of which
    # the wave 0-20 registry covered.
    #
    # Xin Zhao Q + R are BOTH first-order CC entries gated on a
    # state condition. The `notes` field for both spells confirms
    # the CC payload is real (spell-shield + displacement-immunity
    # interaction clauses reference "the knock up" and "the stun"
    # respectively, which is how Meraki documents real CC payloads
    # in their per-spell operational notes).
    #
    # SHIP candidates:
    #
    # (1) Xin Zhao Q Three Talon Strike - 3rd-hit knockup 0.75s.
    #     The COND_NTH_HIT tag in this very module's docstring
    #     EXPLICITLY names "Xin Zhao Q 3rd-attack knockup" as the
    #     canonical motivating example for the tag (line 190).
    #     Yet through waves 0-20 the entry was never added. This
    #     wave closes the gap.
    #     Mechanic: Q empowers next 3 basic attacks within 5s.
    #     3rd attack knocks up target 0.75s. Per Meraki
    #     effects_descriptions[1] "The third attack knocks up the
    #     target for 0.75 seconds". Notes field confirms "Spell
    #     shield will only block the knock up" - distinguishing
    #     the CC payload from the damage. Maps to COND_NTH_HIT
    #     (prob 0.7 tag midpoint). FIRST Xin Zhao Q first-order CC
    #     registration anywhere. Coexists with the unconditional
    #     Xin Zhao W in `_PER_SPELL_CC_DURATIONS` on a different
    #     spell slot.
    #
    # (2) Xin Zhao R Crescent Sweep - target-NOT-Challenged stun
    #     0.75s.
    #     This was a wave 15 REJECT carry ("XinZhao R knockback -
    #     not in cc_conditional CC kind schema") that misread the
    #     mechanic. The wave 15 audit caught the knockback
    #     displacement (which IS in the schema, but the wave 15
    #     verdict claimed otherwise) and missed the STUN that fires
    #     ALONGSIDE the knockback on the same target-not-Challenged
    #     gate. The wave 21 re-audit confirms the stun is real via
    #     two independent evidence sources:
    #     (a) effects_descriptions[1] "Active: Xin Zhao sweeps his
    #         spear around him ... knocking back all non-Challenged
    #         targets hit up-to 700 units over 0.75 seconds, as well
    #         as stunning them for the same duration."
    #     (b) The wave 20 schema-lifted notes field carries
    #         "Displacement immunity will also resist the application
    #         of the stun" - confirming the stun is a separate CC
    #         payload distinct from the knockback (otherwise displ-
    #         imm would never be discussed in stun context).
    #     The condition is the INVERSE target-state gate: stun
    #     fires ONLY on targets that are NOT currently marked
    #     Challenged. Challenged targets receive damage but no
    #     CC. This is the SECOND COND_TARGET_DEBUFFED entry that
    #     gates on the INVERSE of target debuff state (the first
    #     was Briar R wave 18 fearing non-marked enemies).
    #     Maps to COND_TARGET_DEBUFFED (prob 0.5 tag midpoint) -
    #     midpoint reflects that in a typical teamfight, the
    #     operator's R cast lands on 2-4 enemies of which ~1 is
    #     usually the Challenged target (skill expression: the
    #     operator targets the highest-value non-Challenged enemy
    #     before cycling). FIRST Xin Zhao R first-order CC
    #     registration anywhere. Coexists with the unconditional
    #     Xin Zhao W in `_PER_SPELL_CC_DURATIONS` on a different
    #     spell slot (Q + W + R all distinct slots).
    #
    # REJECT verdicts wave 21 (top 40 candidates after registry
    # filter; full audit report in
    # `agents/daemon_slayer/docs/WAVE_21_AUDIT_NOTES.md`):
    #   * Akshan E polymorph - notes wording is about Akshan being
    #     self-CCd cancelling his own dash, not applying CC to
    #     enemies. REJECT.
    #   * Aphelios Q form 2 taunted - notes interaction clause about
    #     Aphelios being taunted during onslaught, not applying CC.
    #     REJECT.
    #   * Aurora R collision - rift border collision applies only a
    #     30%/50% slow, no hard CC. REJECT.
    #   * Bard E grounded - corridor cast-prevention check (Bard
    #     cannot cast Magical Journey while grounded), not enemy CC.
    #     REJECT.
    #   * Bel'Veth E taunted - notes interaction clause about Bel'Veth
    #     being taunted, not applying CC. REJECT.
    #   * Blitzcrank E knockup - UNCONDITIONAL knockup 1s on empowered
    #     AA (no gating condition; the empowered state is granted by
    #     simply casting E within the 5s window). Belongs in
    #     `_PER_SPELL_CC_DURATIONS`. REJECT for conditional registry.
    #   * Briar W form 1 charmed - notes about Briar herself being
    #     charmed during Frenzy, not applying CC. REJECT.
    #   * Caitlyn E suppressed - cast-cancel clause if Caitlyn is
    #     suppressed mid-cast, not applying CC. REJECT.
    #   * Camille R silence - 0.4s nested silence during disrupt is
    #     a tech-detail "nested silence prevents silence-immunity
    #     from blocking the disrupt"; not first-order champion CC,
    #     just an engine-implementation safeguard. REJECT.
    #   * Darius E airborne - UNCONDITIONAL pull-displacement +
    #     airborne 1s. Belongs in `_PER_SPELL_CC_DURATIONS`. REJECT.
    #   * Kha'Zix Q Isolated - damage modifier only on Isolated
    #     targets; no CC payload. REJECT.
    #   * LeeSin R - UNCONDITIONAL knockback + airborne 1s primary
    #     + 1s knockup secondary. Belongs in
    #     `_PER_SPELL_CC_DURATIONS`. wave 13/14/15/16 REJECT carry.
    #     REJECT.
    #   * Olaf R - SELF crowd-control cleanse, no enemy CC. REJECT.
    #   * Poppy W knocked-up - UNCONDITIONAL knockup 0.5s on dash-
    #     interruption (the aura). Belongs in
    #     `_PER_SPELL_CC_DURATIONS` if not already. REJECT for
    #     conditional registry.
    #   * Poppy R knocked-up - UNCONDITIONAL knockup 1s on recast.
    #     Already in `_PER_SPELL_CC_DURATIONS`? No - belongs there.
    #     REJECT for conditional registry.
    #   * Pyke R execute - no CC payload, just execute + blink.
    #     REJECT.
    #   * Rammus Q recast - the stun on terminal collision is
    #     UNCONDITIONAL on collision with enemy. Belongs in
    #     `_PER_SPELL_CC_DURATIONS`. REJECT for conditional
    #     registry.
    #   * Rek'Sai E form 1 knockup - Tunnel mechanic with no CC
    #     payload mentioned in form 1 effects. The "knocked up"
    #     gate phrase is from a different mechanic context.
    #     REJECT.
    #   * Rell W form 1 grounded - notes wording is about Rell using
    #     empowered AA while grounded/rooted; not enemy CC. wave 15
    #     ship had Rell W form 0 (Crash Down channel-completion
    #     stun); wave 15 docstring explicitly noted "Form 1 (Mount
    #     Up Dismounted-state empowered-AA) is a separate mechanic
    #     REJECTED this wave pending operator clarification on
    #     form-transition empowered-AA registration." This wave 21
    #     re-audit confirms the form 1 mechanic is an empowered-AA
    #     dash+stun gated on dismounted-state + completion of the
    #     dash impact. While it COULD ship as a sidecar entry under
    #     COND_FRENZY_STATE (parallel to Gnar W form 1 + Karma W
    #     form 1), the "form-transition empowered-AA" semantic is
    #     intrinsically different from the rage-meter / mantra-
    #     charge / form-cycle patterns used by prior sidecar
    #     entries. Per item 187 don't-redo precedent, this is an
    #     operator-decision-gated entry. CARRY to wave 22+ pending
    #     operator clarification. REJECT for wave 21.
    #   * Rumble E - heat-gated harpoon empowered version applies
    #     no extra CC (only stronger slow + shred). REJECT.
    #   * Samira P stack - airborne immobilize trigger + extended
    #     melee range; no CC applied by Samira. REJECT.
    #   * Sett R suppression - UNCONDITIONAL suppression on cast
    #     (the cast IS the suppress, no gating condition). Belongs
    #     in `_PER_SPELL_CC_DURATIONS`. REJECT for conditional
    #     registry.
    #   * Skarner E terrain-collision stun - the 1.1s stun fires
    #     UNCONDITIONALLY when the attached target collides with
    #     terrain during the charge. Skarner E suppression is
    #     also UNCONDITIONAL during the charge (grab triggers
    #     suppression on collision). Both belong in
    #     `_PER_SPELL_CC_DURATIONS`. REJECT for conditional
    #     registry (the unconditional-CC schema is the proper
    #     home).
    #   * Sylas R stack - notes wording is about per-target
    #     cooldown stacking on Hijack, not CC. REJECT.
    #   * Taliyah R grounded - notes about Taliyah jumping while
    #     immobilized or silenced; not enemy CC. REJECT.
    #   * Trundle E - UNCONDITIONAL knockback on pillar spawn.
    #     Belongs in `_PER_SPELL_CC_DURATIONS`. REJECT for
    #     conditional registry.
    #   * Tryndamere E Fury - cooldown reduction on crit-strike
    #     only; no CC at all. REJECT.
    #   * TwistedFate R grounded - cast-cancel clause about TF
    #     unable to recast Destiny while grounded/rooted, not
    #     enemy CC. REJECT.
    #   * Twitch W suppressed - cast-cancel clause about Venom
    #     Cask missile failing to fire if Twitch is suppressed.
    #     REJECT.
    #   * Urgot W taunted - the empowered-AA on-immobilized trigger
    #     is captured by "taunted" but Urgot W applies no CC.
    #     REJECT.
    #   * Vel'Koz E - UNCONDITIONAL knockup + stun 0.75s; close-
    #     proximity adds knockback. Belongs in
    #     `_PER_SPELL_CC_DURATIONS`. REJECT for conditional
    #     registry.
    #   * Vex R grounded - cast-cancel clause about Vex unable to
    #     recast while grounded/rooted, not enemy CC. REJECT.
    #   * Viego R - UNCONDITIONAL knockback up to 400u + 0.99 slow
    #     0.25s on primary target. Belongs in
    #     `_PER_SPELL_CC_DURATIONS`. REJECT for conditional
    #     registry.
    #   * Yorick W knocks-aside - UNCONDITIONAL knock-aside on
    #     ring rise. Belongs in `_PER_SPELL_CC_DURATIONS`. REJECT
    #     for conditional registry.
    #
    # Wave 21 registry growth: +2 primary entries / +1 net-new
    # champion (Xin Zhao). Per-tag consumer counts: COND_NTH_HIT
    # +1 (Xin Zhao Q), COND_TARGET_DEBUFFED +1 (Xin Zhao R). Tag
    # count unchanged at 13.
    #
    # Math preservation: default
    # compute_cc_pressure(include_conditional=False) is BYTE-
    # IDENTICAL to ENGINE 1.58.0 for ALL champions (the wave 21
    # path skips when the flag is False). include_conditional=True
    # callers receive new probability-weighted contributions for
    # Xin Zhao: Q 0.75 * 0.7 = 0.525s, R 0.75 * 0.5 = 0.375s,
    # totaling +0.9s expected conditional pressure beyond the
    # existing 1.0s unconditional W knockup.

    # Xin Zhao Q Three Talon Strike 3rd-hit knockup
    registry.setdefault("XinZhao", {})["Q"] = ConditionalCcEntry(
        champion="XinZhao",
        spell="Q",
        cc_kind="knockup",
        durations_s=(0.75, 0.75, 0.75, 0.75, 0.75),
        condition=COND_NTH_HIT,
        probability=_p("XinZhao", "Q", 0.7),
        notes=(
            "Q Three Talon Strike: Xin Zhao empowers his next 3 "
            "basic attacks within 5s. The 3rd attack knocks the "
            "target up 0.75s flat across all 5 Q ranks per Meraki "
            "16.10.1 effects_descriptions[1] ('The third attack "
            "knocks up the target for 0.75 seconds'). Maps to "
            "COND_NTH_HIT (prob 0.7 tag midpoint). The notes field "
            "confirms the knockup is the CC payload separately from "
            "the damage ('Spell shield will only block the knock "
            "up'). This is the CANONICAL example of COND_NTH_HIT - "
            "the tag's own docstring at line 190 names Xin Zhao Q "
            "3rd-attack knockup as the motivating example, yet "
            "through waves 0-20 the entry was never added. Wave 21 "
            "(notes-field re-audit of prior-wave REJECT carries + "
            "fresh full-fleet filter) closes the gap. FIRST Xin "
            "Zhao Q first-order CC registration anywhere. Coexists "
            "with the unconditional Xin Zhao W 1.0s knockup in "
            "`_PER_SPELL_CC_DURATIONS` on a different spell slot. "
            "No coexists_with_unconditional flag - Xin Zhao Q has "
            "no unconditional entry. Probability 0.7 midpoint - "
            "in a teamfight, the operator typically lands 3 "
            "consecutive AAs on the highest-priority target within "
            "the 5s window; missed attacks (target untargetable / "
            "dashes / displacement) lower the success rate but "
            "Xin Zhao's empowered AA range expansion makes the "
            "3rd-hit knockup reliable. Mechanic captured by ENGINE "
            "1.46.0 Meraki schema lift (effects_descriptions); "
            "validated against ENGINE 1.58.0 notes-field lift."
        ),
    )

    # Xin Zhao R Crescent Sweep target-not-Challenged stun
    registry.setdefault("XinZhao", {})["R"] = ConditionalCcEntry(
        champion="XinZhao",
        spell="R",
        cc_kind="stun",
        durations_s=(0.75, 0.75, 0.75),
        condition=COND_TARGET_DEBUFFED,
        probability=_p("XinZhao", "R", 0.5),
        notes=(
            "R Crescent Sweep target-not-Challenged stun: Xin Zhao "
            "sweeps his spear, knocking back all NON-Challenged "
            "targets hit up to 700 units over 0.75s + stunning "
            "them 0.75s flat across all 3 R ranks per Meraki "
            "16.10.1 effects_descriptions[1] ('Active: Xin Zhao "
            "sweeps his spear around him ... knocking back all "
            "non-Challenged targets hit up-to 700 units over 0.75 "
            "seconds, as well as stunning them for the same "
            "duration'). Challenged targets (the last enemy hit by "
            "Xin Zhao's AAs or Audacious Charge, marked for 3s) "
            "receive damage but no CC - the stun is INVERSE-gated "
            "on the target's debuff state. Maps to "
            "COND_TARGET_DEBUFFED (prob 0.5 tag midpoint) with "
            "inverse semantic. SECOND COND_TARGET_DEBUFFED entry "
            "gating on inverse target-state after Briar R wave 18 "
            "(non-marked-enemy fear). The wave 20 schema-lifted "
            "notes field confirms the stun is a distinct CC "
            "payload via 'Displacement immunity will also resist "
            "the application of the stun' - if the stun were not "
            "a real payload, the notes would not document displ-"
            "imm interaction. This entry CORRECTS a wave 15 "
            "REJECT carry (the wave 15 audit caught the knockback "
            "displacement and dismissed the entry as 'not in "
            "cc_conditional CC kind schema'; that was a misread - "
            "knockback IS in the schema AND the same gate fires a "
            "stun alongside). FIRST Xin Zhao R first-order CC "
            "registration anywhere. Coexists with the unconditional "
            "Xin Zhao W 1.0s knockup in `_PER_SPELL_CC_DURATIONS` "
            "on a different spell slot. No coexists_with_"
            "unconditional flag - Xin Zhao R has no unconditional "
            "entry. Probability 0.5 midpoint - in a typical "
            "teamfight the operator's R cast lands on 2-4 enemies "
            "of which ~1 is usually the Challenged target. Skill "
            "expression: operator targets the highest-value non-"
            "Challenged enemy before cycling. Mechanic captured by "
            "ENGINE 1.46.0 Meraki schema lift; the inverse-target-"
            "state gate documented by ENGINE 1.58.0 notes-field "
            "lift. Xin Zhao becomes a 2-slot cc_conditional "
            "champion (Q wave 21 + R wave 21) entering the registry "
            "with both slots in the same wave."
        ),
    )

    # ============================================================
    # === wave 23 expansion (2026-05-26 / ENGINE 1.61.0) - +1
    # === entry / +1 net-new champion (Hecarim) via the wave 18
    # === coexists_with_unconditional same-slot-coexistence schema
    # === (Maokai R precedent). SECOND consumer of the wave 7
    # === forward-marker COND_RANGE_GATED tag.
    # ============================================================

    # Hecarim R Onslaught of Shadows distance-gated fear: Hecarim
    # dashes to the target location with displacement immunity and
    # summons 5 spectral riders in an arrow formation that charge
    # alongside him. UPON ARRIVAL he fears nearby enemies with a
    # duration scaled on the distance traveled from cast origin to
    # the dash terminus. Per Meraki 16.10.1 effects_descriptions[1]:
    # "Upon arrival, he fears nearby enemies for 0.75 : 1.5 (based
    # on distance traveled) seconds and slows them by 0% : 99%
    # (based on distance from Hecarim)."
    #
    # The 0.75-1.5s range-gated fear coexists with the unconditional
    # Hecarim R 1.0s flat entry in `_PER_SPELL_CC_DURATIONS["Hecarim"]
    # ["R"] = (1.0, 1.0, 1.0)`. The unconditional 1.0s represents the
    # mid-distance midpoint; the conditional 1.5s represents the
    # max-distance band. Maps to COND_RANGE_GATED (prob 0.4 - tag
    # midpoint matches Maokai R precedent; mid-low reflecting that
    # the operator must commit to a long-range dash to reach the
    # 1.5s far-band fear, while close-range R engages get the 1.0s
    # mid value via the unconditional entry).
    #
    # SCHEMA: coexists_with_unconditional=True declares same-slot
    # coexistence with the unconditional `_PER_SPELL_CC_DURATIONS`
    # entry. Consumer-side compute_cc_pressure(include_conditional=
    # True) math credits MAX(unconditional_post_tenacity 1.0s,
    # conditional_post_tenacity 1.5 * 0.4 = 0.6s default) - never
    # both summed. Default calibration: unconditional 1.0s wins.
    # Operator can tune Hecarim:R above 0.667 (1.0/1.5) to lift the
    # conditional above the unconditional via the per_entry_
    # probability override.
    #
    # SECOND consumer of the wave 7 forward-marker COND_RANGE_GATED
    # tag after Maokai R wave 18. Closes wave 23 audit (re-audit of
    # all prior REJECT carries against the FULL ENGINE 1.60.0 schema
    # including notes + cast_time + effects_descriptions + parent_
    # resource + damage_blocks; Hecarim R surfaced because the
    # effects_descriptions for the R fear was not previously matched
    # against the COND_RANGE_GATED tag - the audit subagent flagged
    # the "0.75 : 1.5 (based on distance traveled)" range as the
    # canonical range-gated CC payload).
    #
    # FIRST Hecarim cc_conditional entry anywhere - the existing
    # Hecarim E knockback (0.75s flat) + R fear (1.0s baseline) live
    # in the unconditional `_PER_SPELL_CC_DURATIONS` registry. This
    # wave 23 entry registers ONLY the range-gated fear bonus.
    #
    # Math preservation: default compute_cc_pressure(include_
    # conditional=False) is BYTE-IDENTICAL to ENGINE 1.60.0 for ALL
    # champions including Hecarim (the wave 23 path skips when the
    # flag is False; unconditional 1.0s flat R fear unchanged). At
    # include_conditional=True the consumer max-rule keeps the
    # unconditional 1.0s as the credited value by default; operator
    # override Hecarim:R = 0.95 lifts conditional to 1.425s which
    # then beats the unconditional via MAX.
    registry.setdefault("Hecarim", {})["R"] = ConditionalCcEntry(
        champion="Hecarim",
        spell="R",
        cc_kind="fear",
        durations_s=(1.5, 1.5, 1.5),
        condition=COND_RANGE_GATED,
        probability=_p("Hecarim", "R", 0.4),
        notes=(
            "R Onslaught of Shadows distance-gated fear: Hecarim "
            "dashes to target with displacement immunity, summons 5 "
            "spectral riders, AoE magic damage on arrival. Per "
            "Meraki 16.10.1 effects_descriptions[1] 'fears nearby "
            "enemies for 0.75 : 1.5 (based on distance traveled) "
            "seconds'. Encoded at MAX-distance 1.5s with COND_RANGE_"
            "GATED tag (SECOND consumer of the wave 7 forward-marker "
            "tag after Maokai R wave 18). coexists_with_unconditional"
            "=True declares same-slot coexistence with the "
            "unconditional Hecarim R 1.0s flat baseline entry in "
            "`_PER_SPELL_CC_DURATIONS`. Consumer math: at include_"
            "conditional=True the MAX rule credits the larger of "
            "unconditional 1.0s or conditional 1.5 * 0.4 = 0.6s "
            "default (operator can tune Hecarim:R above 0.667 to "
            "flip the conditional above the unconditional). "
            "Probability midpoint 0.4 matches Maokai R precedent - "
            "operator must commit to a long-distance ride to reach "
            "the 1.5s far band; close-range R engages get the 1.0s "
            "mid value via the unconditional entry. FIRST Hecarim "
            "cc_conditional entry anywhere (E knockback + R baseline "
            "fear already in `_PER_SPELL_CC_DURATIONS`). Discovered "
            "during wave 23 (2026-05-26 / ENGINE 1.61.0) full-schema "
            "re-audit. Mechanic captured by ENGINE 1.46.0 Meraki "
            "schema lift (effects_descriptions); range-gated payload "
            "matches the COND_RANGE_GATED tag without further "
            "schema work."
        ),
        coexists_with_unconditional=True,
    )

    return registry
```

## _build_per_spell_cc_conditional_forms (sidecar registry, verbatim pre-A3)

```python
def _build_per_spell_cc_conditional_forms() -> (
    Dict[str, Dict[Tuple[str, int], ConditionalCcEntry]]
):
    """Build the form-explicit conditional CC sidecar registry.

    Uses ``registry.setdefault(champion, {})[(spell, form_index)] = entry``
    pattern so multi-wave + multi-form additions never clobber. Seed:
    2 wave-10 entries closing the (a)-class REJECT carry from item 153
    wave 9 (Karma W form 1 + Hwei E form 2 same-spell-slot constraint).

    Per-entry probabilities pass through ``_p_form(champion, spell,
    form_index, default)`` which honors any ``per_entry_probability``
    override loaded from ``data/cc_conditional_calibration.json`` under
    the extended key shape ``<champion>:<spell>:<form_index>``.
    """
    registry: Dict[str, Dict[Tuple[str, int], ConditionalCcEntry]] = {}

    def _p_form(
        champion: str, spell: str, form_index: int, default: float
    ) -> float:
        """Resolve per-form per-entry probability with operator override.

        Reads ``_PER_FORM_ENTRY_PROBABILITY_OVERRIDES.get((champion,
        spell, form_index), default)`` so the operator's calibration
        JSON file flows through to every registered form-explicit
        entry without per-entry boilerplate.
        """
        return _PER_FORM_ENTRY_PROBABILITY_OVERRIDES.get(
            (champion, spell, form_index), default
        )

    # ============================================================
    # === wave 10 expansion (2026-05-23 / ENGINE 1.47.0) - +2
    # === entries / 0 net-new champions via same-spell-slot schema
    # === lift on (Karma, W) and (Hwei, E). Both slots already hold
    # === a wave 0-9 default-form entry in the primary registry;
    # === these form-explicit entries land in the sidecar registry
    # === without clobbering the legacy entries.
    # ============================================================

    # Karma W form_index=1 Renewal (Mantra-bonus root extension):
    # The base Karma W Focused Resolve (form 0) is the wave 1
    # channel-completion root entry in the primary registry (1.5-2.0s
    # across 5 W ranks per Meraki Root Duration block). When Karma
    # spends a Mantra charge (R) to empower W, the form becomes
    # Renewal with TWO additional effects: (1) Karma heals for 17%
    # of missing health on-cast plus again on tether expiry / target
    # death; (2) the root duration is EXTENDED by a bonus per Mantra
    # rank.
    #
    # Per Meraki 16.10.1 schema-lifted block, the Renewal form
    # carries:
    #   * ``Root Duration Increase`` modifier:
    #       [0.5, 0.75, 1.0, 1.25] across 4 Mantra ranks.
    #   * ``Total Root Duration`` modifier:
    #       base [1.6, 1.7, 1.8, 1.9, 2.0] across 5 W ranks
    #     PLUS bonus [0.5, 0.75, 1.0, 1.25] across 4 Mantra ranks.
    #
    # Encoding choice: a single per-W-rank tuple at the MID Mantra
    # rank (rank 2 -> +0.75 bonus) gives operator-conservative
    # midpoint duration values consistent with the wave 1
    # calibration pattern. At max Mantra (rank 4 -> +1.25) the
    # actual Total Root reaches (2.85, 2.95, 3.05, 3.15, 3.25) but
    # the registry stores the mid-Mantra estimate; operator can tune
    # via ``per_entry_probability`` (form-explicit key shape
    # ``Karma:W:1``).
    #
    # Condition tag: COND_FRENZY_STATE - Karma must be in the
    # Mantra-charged self-empowered state to cast Renewal. Parallel
    # to Renekton W Fury (wave 9 first COND_FRENZY_STATE consumer);
    # this is the SECOND consumer.
    #
    # Mechanic schema-lift-verified: the form 1 effects_descriptions
    # text "Mantra Bonus: Focused Resolve's root duration is
    # increased. Karma heals for 17% (+ 1% per 100 AP) of her missing
    # health once on-cast, and again once the tether lasts its full
    # duration or the target dies while tethered. Renewal scales with
    # Mantra's rank." confirms the mechanic (the bonus root values
    # are NOT in the structured leveling[] but the duration EXTENSION
    # values ARE in the Meraki damage_blocks Root Duration Increase
    # modifier; the schema lift confirms the mechanic in-source).
    #
    # Coexists with the primary registry wave 1 Karma W entry
    # (form_index=None default form Focused Resolve channel-completion
    # root). Both contribute to compute_cc_pressure(Karma,
    # include_conditional=True): the base form 0 fires unconditional
    # (within W's own conditional gate of full-channel tether), and
    # the form 1 Mantra-bonus extension adds extra duration when
    # Mantra is active.
    base_w = (1.6, 1.7, 1.8, 1.9, 2.0)
    mid_mantra_bonus = 0.75  # Mantra rank 2 / 4 (operator-conservative)
    karma_w_form1 = tuple(round(b + mid_mantra_bonus, 4) for b in base_w)
    registry.setdefault("Karma", {})[("W", 1)] = ConditionalCcEntry(
        champion="Karma",
        spell="W",
        cc_kind="root",
        durations_s=karma_w_form1,
        condition=COND_FRENZY_STATE,
        probability=_p_form("Karma", "W", 1, 0.4),
        notes=(
            "W form 1 Renewal (Mantra-empowered Focused Resolve): "
            "Karma's base W root (1.6-2.0s across 5 W ranks) is "
            "EXTENDED by a Mantra-rank bonus (+0.5/+0.75/+1.0/+1.25 "
            "across 4 Mantra ranks). Encoded at mid Mantra rank 2 "
            "(+0.75 bonus) for operator-conservative calibration: "
            "(2.35, 2.45, 2.55, 2.65, 2.75) seconds across 5 W ranks. "
            "At max Mantra rank 4 the actual durations reach (2.85, "
            "2.95, 3.05, 3.15, 3.25). Maps to COND_FRENZY_STATE - "
            "Karma must be in a Mantra-charged self-empowered state "
            "(R) to cast the Renewal form variant. SECOND consumer "
            "of COND_FRENZY_STATE after Renekton W wave 9. Mechanic "
            "captured by ENGINE 1.46.0 Meraki schema lift "
            "(effects_descriptions[0] 'Mantra Bonus: Focused "
            "Resolve's root duration is increased ... Renewal "
            "scales with Mantra's rank'). Coexists with the primary "
            "registry wave 1 Karma W default-form entry; this is "
            "the FIRST same-spell-slot schema-lift entry in the "
            "sidecar registry. Form-explicit override key shape: "
            "Karma:W:1."
        ),
        form_index=1,
    )

    # Hwei E form_index=2 Gaze of the Abyss (EW form root): Hwei E
    # is a 2-cast cycle. Form 0 (Subject: Torment) is the mood
    # selector; form 1 (Grim Visage, EQ follow-up) is the channel-
    # completion FEAR already in the primary registry as the wave 9
    # default-form entry; form 2 (Gaze of the Abyss, EW follow-up)
    # is the channel-completion ROOT that this wave 10 entry adds;
    # form 3 (Crushing Maw, EE follow-up) has no first-order CC
    # (slow + pull only).
    #
    # Per Meraki 16.10.1 schema-lifted block, form 2 carries:
    #   * ``Root Duration`` block: [1.2, 1.4, 1.6, 1.8, 2.0] across
    #     5 ranks. NOTE: Hwei E levels per E spell rank (5 ranks),
    #     not separately per form - all 3 EQ/EW/EE forms scale on
    #     the same E rank index.
    #
    # Mechanic schema-lift-verified: the form 2 effects_descriptions
    # text "Active - EW: Hwei tosses an eyeball to the target
    # location. Upon arrival, it expands over 0.2 seconds into a
    # dark gaze lasting 3 seconds ... Once locked on, the eye
    # launches itself at the target after 0.3 seconds and collides
    # with the first enemy hit to deal magic damage, reveal them
    # for 2.5 seconds, and root them for a duration." confirms the
    # mechanic.
    #
    # Condition tag: COND_CHANNEL_COMPLETION - parallel to form 1
    # Grim Visage (wave 9 entry). The 2-cast cycle (E mood selector
    # then EW form lock) is the channel; partial-cycle does not
    # fire any payload. Additionally the eye has a placement-lock-
    # launch sequence (0.7s + 0.3s = ~1s extra delay before the
    # projectile lands) that adds dodgeable channel time.
    #
    # Probability mid-low (0.4 tag midpoint) - matches form 1 Hwei
    # E calibration since both forms share the same 2-cast cycle
    # gating mechanic. The form 2 root has additional placement +
    # lock-on delay which is offset by the 5s root duration on a
    # rooted target making it harder to escape.
    #
    # Coexists with the primary registry wave 9 Hwei E entry
    # (form_index=None default form Grim Visage channel-completion
    # fear). Both contribute to compute_cc_pressure(Hwei,
    # include_conditional=True) when the operator picks the
    # respective form mid-cycle. Form-explicit override key shape:
    # Hwei:E:2.
    registry.setdefault("Hwei", {})[("E", 2)] = ConditionalCcEntry(
        champion="Hwei",
        spell="E",
        cc_kind="root",
        durations_s=(1.2, 1.4, 1.6, 1.8, 2.0),
        condition=COND_CHANNEL_COMPLETION,
        probability=_p_form("Hwei", "E", 2, 0.4),
        notes=(
            "E form 2 Gaze of the Abyss (EW form): roots target "
            "for 1.2-2.0s across 5 E ranks. Hwei E is a 2-cast "
            "cycle (E mood selector -> Q/W/E form lock). The root "
            "fires only on the EW form completion plus a placement-"
            "lock-launch sequence (~1s additional delay). Partial-"
            "cycle = no fire. Maps to COND_CHANNEL_COMPLETION on "
            "the 2-cast sequence + eye lock-on channel. Probability "
            "mid-low - 2-input setup + dodgeable projectile. "
            "Coexists with the primary registry wave 9 Hwei E "
            "form 1 Grim Visage fear entry; this is the SECOND "
            "same-spell-slot schema-lift entry in the sidecar "
            "registry. Mechanic captured by ENGINE 1.46.0 Meraki "
            "schema lift (effects_descriptions confirms root "
            "payload on EW form). Form-explicit override key "
            "shape: Hwei:E:2."
        ),
        form_index=2,
    )

    # ============================================================
    # === wave 11 expansion (2026-05-23 / ENGINE 1.48.0) - +1
    # === sidecar entry / +1 net-new champion via Mega-rage-
    # === transformation-form-gated CC on Gnar W slot. Gnar W
    # === form_index=0 (Mini form, Hyper) is a passive on-hit
    # === stack with no first-order CC; form_index=1 (Mega form,
    # === Wallop) is the form-gated active stun. The form-explicit
    # === sidecar registry is the canonical home for this entry
    # === since Gnar has no wave 0-10 W primary registry entry to
    # === collide with - but the sidecar pattern is preferred over
    # === a primary entry because the CC is intrinsically form-
    # === gated (Mega transform requires accumulated rage stacks
    # === driven by combat activity / time-in-fight), so the
    # === form_index field carries semantic meaning rather than
    # === collision-avoidance.
    # ============================================================

    # Gnar W form_index=1 Wallop (Mega-form stun): When Gnar is in
    # his Mega form (post-rage-meter transform), W becomes Wallop
    # which slams the arm down dealing physical damage to all
    # enemies struck within the area AND stunning them for 1.25s
    # flat across all 5 W ranks. Mini-form W (form_index=0, Hyper)
    # is a passive on-hit stack mechanic with NO first-order CC -
    # only the Mega form gates the stun payload. Maps to
    # COND_FRENZY_STATE - Gnar must be in the rage-meter-driven
    # Mega transform state to cast Wallop. THIRD consumer of the
    # COND_FRENZY_STATE tag after Renekton W wave 9 (first) +
    # Karma W form 1 wave 10 (second). Probability tag midpoint
    # 0.4 - Gnar reliably enters Mega form mid-fight via passive
    # rage accumulation, but Wallop's cast timing must coincide
    # with the Mega window before reverting to Mini.
    #
    # Mechanic schema-lift-verified: effects_descriptions[0] for
    # form_index=1 ("Active: Gnar slams his arm down in the target
    # direction, dealing physical damage to all enemies struck
    # within the area and stunning them for 1.25 seconds") captured
    # by ENGINE 1.46.0 Meraki schema lift. The duration value 1.25s
    # is explicit in the description; no rank scaling on the stun
    # duration itself (the W damage scales but the stun is flat).
    #
    # Coexists with the unconditional Gnar R GNAR! terrain-collision
    # stun 0.75s in `_PER_SPELL_CC_DURATIONS` on a different spell
    # slot. Gnar has no primary registry W entry (the sidecar entry
    # is the FIRST W slot registration for Gnar). Form-explicit
    # override key shape: Gnar:W:1.
    registry.setdefault("Gnar", {})[("W", 1)] = ConditionalCcEntry(
        champion="Gnar",
        spell="W",
        cc_kind="stun",
        durations_s=(1.25,),
        condition=COND_FRENZY_STATE,
        probability=_p_form("Gnar", "W", 1, 0.4),
        notes=(
            "W form 1 Wallop (Mega-form-gated stun): when Gnar is "
            "in Mega form (rage-meter transform), W slams the arm "
            "down + stuns enemies hit for 1.25s flat across all 5 "
            "W ranks. Mini-form W (form_index=0, Hyper) is a "
            "passive on-hit stack with NO first-order CC. Maps "
            "to COND_FRENZY_STATE - Gnar must be in the rage-"
            "meter-driven Mega transform. THIRD consumer of "
            "COND_FRENZY_STATE after Renekton W wave 9 + Karma W "
            "form 1 wave 10. Probability tag midpoint 0.4. "
            "Mechanic captured by ENGINE 1.46.0 Meraki schema "
            "lift (form 1 effects_descriptions confirms the 1.25s "
            "stun is explicit + flat-duration). Coexists with "
            "Gnar R unconditional terrain-collision stun 0.75s "
            "in `_PER_SPELL_CC_DURATIONS` on a different spell "
            "slot. Form-explicit override key shape: Gnar:W:1."
        ),
        form_index=1,
    )

    # ============================================================
    # === wave 12 expansion (2026-05-24 / ENGINE 1.49.0) - +1
    # === sidecar entry / +1 net-new champion via Sylas E form 1
    # === Abduct 2-cast-completion stun. Sylas E form_index=0
    # === (Abscond) is the FIRST cast - a dash with NO first-
    # === order CC; form_index=1 (Abduct) is the FOLLOW-UP cast
    # === fired within 3.5s of Abscond that hits the first
    # === enemy in the chain's path and stuns them for 0.5s +
    # === knocks them up for 0.5s on Sylas's arrival. The
    # === stun fires unconditionally WITHIN form 1 (just like
    # === Hwei E form 1+2), but conditional on completing the
    # === 2-cast cycle (Abscond -> Abduct within the 3.5s
    # === window). Sidecar pattern parallel to Hwei E form 1+2
    # === entries from wave 9/10 - the form_index distinguishes
    # === the FIRST cast (no CC payload) from the SECOND cast
    # === (stun + knockup CC payload). Encodes the stun
    # === component only; the 0.5s knockup is a chained
    # === airborne payload that fires AFTER the stun and is
    # === captured under the same channel-completion gate.
    # ============================================================

    # Sylas E form_index=1 Abduct (2-cast-completion stun): Sylas
    # E is a 2-cast cycle. Form 0 (Abscond) is a dash to the
    # target location with NO first-order CC. Within 3.5 seconds
    # of casting Abscond, Sylas can recast E (form 1, Abduct)
    # which whips out his chains in the target direction. The
    # chain deals magic damage to the first enemy hit and reveals
    # + stuns them for 0.5 seconds flat across all 5 E ranks.
    # Sylas then dashes to the target's location and knocks them
    # up for 0.5 seconds upon arrival (chained airborne payload
    # captured under the same channel-completion gate). Maps to
    # COND_CHANNEL_COMPLETION on the 2-cast sequence - if Sylas
    # does NOT recast within 3.5s, no Abduct stun fires (just the
    # initial dash). Probability 0.4 (mid-low matching Hwei E
    # parallel) - 2-input setup within a 3.5s window is reliable
    # in Sylas's typical combo cadence, but the chain projectile
    # is dodgeable + the recast is sometimes skipped in favor of
    # other combo paths (W + R + Q without E recast). Coexists
    # with the wave 0+ Sylas absence in `_PER_SPELL_CC_DURATIONS`
    # (Sylas has NO unconditional CC entries - this is the FIRST
    # Sylas first-order CC registration anywhere in the engine).
    # Sidecar pattern preferred because the form_index carries
    # semantic meaning (form 0 = setup dash with no CC; form 1 =
    # 2nd-cast payload with stun + knockup). Closes the wave 0+
    # carry-forward in `ability_dps.py:1225-1228` ("Sylas E2 -
    # second-cast conditional") + the item 148 wave 7 schema-
    # lift docstring REJECT note ("Sylas E2 Abduct stuns on hook
    # hit regardless of cast range" - the wave 7 note was
    # correct that range is NOT the conditional axis; channel-
    # completion of the 2-cast cycle IS the axis).
    #
    # Mechanic schema-lift-verified: effects_descriptions[0] for
    # form_index=1 ("Active: Sylas whips out his chains in the
    # target direction that deal magic damage to the first
    # enemy hit and reveal and stun them for 0.5 seconds. Upon
    # hitting the target, Sylas dashes to their location and
    # knocks them up for 0.5 seconds upon arrival") captured by
    # ENGINE 1.46.0 Meraki schema lift. The duration value 0.5s
    # is explicit in the description; no rank scaling on the
    # stun duration itself. Form-explicit override key shape:
    # Sylas:E:1.
    registry.setdefault("Sylas", {})[("E", 1)] = ConditionalCcEntry(
        champion="Sylas",
        spell="E",
        cc_kind="stun",
        durations_s=(0.5,),
        condition=COND_CHANNEL_COMPLETION,
        probability=_p_form("Sylas", "E", 1, 0.4),
        notes=(
            "E form 1 Abduct (2-cast-completion stun): Sylas E is "
            "a 2-cast cycle. Form 0 (Abscond) dashes with no CC; "
            "form 1 (Abduct, recast within 3.5s) whips chains "
            "that stun the first enemy hit for 0.5s flat across "
            "all 5 E ranks. Maps to COND_CHANNEL_COMPLETION on "
            "the 2-cast sequence. Probability mid-low matching "
            "Hwei E parallel - 2-input setup within 3.5s is "
            "reliable in Sylas combo cadence but projectile is "
            "dodgeable. Coexists with absence in "
            "`_PER_SPELL_CC_DURATIONS` (FIRST Sylas first-order "
            "CC registration anywhere in the engine). Sidecar "
            "pattern preferred - form_index carries semantic "
            "meaning (form 0 = no CC setup dash; form 1 = "
            "2nd-cast stun payload). Closes item 170 wave-12-"
            "audit candidate + ability_dps.py:1225-1228 "
            "carry-forward + item 148 wave 7 schema-lift "
            "REJECT note (the wave 7 reject was correct that "
            "range is NOT the axis; channel-completion IS). "
            "Mechanic captured by ENGINE 1.46.0 Meraki schema "
            "lift (form 1 effects_descriptions confirms the "
            "0.5s stun is explicit + flat-duration). Form-"
            "explicit override key shape: Sylas:E:1."
        ),
        form_index=1,
    )

    # ============================================================
    # === wave 13 expansion (2026-05-24 / ENGINE 1.50.0) - +1
    # === sidecar entry / +1 net-new champion via Aphelios Q
    # === form_index=3 Gravitum Binding Eclipse expunge root.
    # === Aphelios Q is a weapon-cycle ability where the form
    # === index corresponds to one of his 5 weapons (Calibrum,
    # === Severum, Gravitum, Infernum, Crescendum). Each form
    # === has a different active effect; form_index=3
    # === (Gravitum, "Binding Eclipse") is the ONLY form with
    # === a first-order CC payload: it expunges all enemies
    # === already carrying Gravitum's slow debuff, dealing
    # === magic damage AND rooting them for 1.0 second flat
    # === per effects_descriptions. The conditional axis is
    # === COND_TARGET_DEBUFFED - the root fires ONLY when a
    # === target carries Gravitum's slow first (applied via
    # === Aphelios's auto-attacks while Gravitum is the main
    # === weapon). Sidecar registry preferred because
    # === form_index carries semantic meaning (form 0/1/2/4/5
    # === have NO CC; form 3 carries the CC payload). Sidecar
    # === pattern parallel to Hwei E form 1+2 + Sylas E form
    # === 1 + Karma W form 1 + Gnar W form 1.
    # ============================================================

    # Aphelios Q form_index=3 Gravitum Binding Eclipse expunge
    # root: Aphelios's Q rotates through 5 weapons (forms 0/1/
    # 2/3/4 = Calibrum/Severum/Gravitum/Infernum/Crescendum;
    # form 5 = Sentry secondary). When Gravitum is the active
    # main weapon (form 3), Q EXPUNGES every enemy already
    # carrying Gravitum's slow debuff, dealing magic damage AND
    # rooting them for 1.0 second flat per effects_descriptions
    # ("Aphelios expunges all enemies with Gravitum's slow
    # debuff, dealing 50 : 140 ... magic damage and rooting
    # them for 1 second"). Standalone Q cast in any other
    # weapon-form has NO root payload (Calibrum is a damage
    # line-shot mark, Severum is a heal-AA empower, Infernum is
    # a cone AoE, Crescendum is a chakram shower). Maps to
    # COND_TARGET_DEBUFFED - the root requires Aphelios's auto-
    # attacks to FIRST apply Gravitum's slow debuff to the
    # target during the Gravitum-as-main-weapon window. Without
    # the pre-applied slow, the expunge has no targets to root.
    # Probability 0.5 (tag midpoint) - in teamfights Aphelios's
    # high-attack-speed Gravitum auto-chain reliably slows
    # multiple targets, but the operator must time the
    # weapon-cycle to Gravitum AND have already auto-attacked
    # priority targets. Sidecar pattern preferred (form 3
    # carries CC; other forms do not) - parallel to Hwei E
    # form 1+2 + Sylas E form 1 + Karma W form 1 + Gnar W
    # form 1. Coexists with absence in
    # `_PER_SPELL_CC_DURATIONS` (FIRST Aphelios first-order
    # CC registration anywhere in the engine). Form-explicit
    # override key shape: Aphelios:Q:3.
    registry.setdefault("Aphelios", {})[("Q", 3)] = ConditionalCcEntry(
        champion="Aphelios",
        spell="Q",
        cc_kind="root",
        durations_s=(1.0,),
        condition=COND_TARGET_DEBUFFED,
        probability=_p_form("Aphelios", "Q", 3, 0.5),
        notes=(
            "Q form 3 Gravitum Binding Eclipse expunge root: "
            "when Gravitum is active main weapon (form 3), Q "
            "expunges enemies carrying Gravitum's slow debuff "
            "(applied via Aphelios autos during the Gravitum "
            "window) for damage + 1.0s root flat across all "
            "Q ranks (effects_descriptions 'rooting them for "
            "1 second'). Other weapon-forms (Calibrum/Severum/"
            "Infernum/Crescendum) have NO root payload. Maps "
            "to COND_TARGET_DEBUFFED - root requires pre-"
            "applied Gravitum slow. Probability tag midpoint "
            "0.5 - reliable Gravitum-window auto-chain but "
            "requires weapon-cycle timing + prior autos. "
            "FIRST Aphelios first-order CC registration in "
            "the engine. Sidecar pattern parallel to Hwei E "
            "form 1+2 + Sylas E form 1 + Karma W form 1 + "
            "Gnar W form 1 - form_index carries semantic "
            "meaning (only form 3 carries CC payload). Form-"
            "explicit override key shape: Aphelios:Q:3."
        ),
        form_index=3,
    )

    # ============================================================
    # === wave 14 expansion (2026-05-24 / ENGINE 1.51.0) - +1
    # === sidecar entry / +1 net-new champion via cast_time
    # === schema lift on Jayce E form 0 Thundering Blow root.
    # === Jayce E has 2 forms (Hammer-form Thundering Blow at
    # === form_index=0 + Cannon-form Acceleration Gate at
    # === form_index=1); the cast-time-gated root payload fires
    # === ONLY on form 0. Sidecar pattern preferred because the
    # === form_index distinguishes the CC-payload form from the
    # === utility-only form. Closes item 170 wave-12 carry +
    # === item 171 wave-13 carry (Jayce E cast-time root STILL
    # === schema-blocked).
    # ===
    # === Wave 14 introduces the ``cast_time`` extractor schema
    # === lift (ENGINE 1.51.0): the ``tools/daemon_slayer_abilities_extract.py``
    # === extractor now captures the Meraki ``castTime`` field
    # === per form (None for instant casts; float seconds
    # === otherwise). The schema lift unlocks the long-deferred
    # === "roots target over the cast time" mechanic for Jayce
    # === E (0.25s) and reveals the same pattern is broadly
    # === available across the fleet (LeeSin R 0.25s + KSante R
    # === 0.4s as identified prior-wave REJECTs, but those land
    # === in the SEPARATE _PER_SPELL_CC_DURATIONS unconditional
    # === registry per item 171 wave 13 REJECT verdict - both
    # === root the primary target unconditionally rather than
    # === requiring a precondition).
    # ===
    # === Wave 14 REJECT verdicts:
    # ===
    # ===   * Maokai R distance-gated root - STILL double-counts
    # ===     with unconditional Maokai R registry entry. No
    # ===     change from wave 13. REJECT.
    # ===   * Multi-form same-spell-slot Renekton W / Aatrox R /
    # ===     Volibear R / Briar W - STILL self-buff or minion-
    # ===     only or turret-only per item 153 wave 9 schema-lift
    # ===     verification. REJECT (no new evidence this run).
    # ===   * KSante R cast-time displacement immunity 0.4s -
    # ===     the displacement immunity is a SELF buff (Sante
    # ===     gains immunity); the target is unconditionally
    # ===     rooted for an explicit 0.5s during the cast
    # ===     (matches the unconditional path NOT cast_time
    # ===     gated). REJECT.
    # ============================================================

    # Jayce E form_index=0 Thundering Blow cast-time root:
    # Jayce's E in Hammer form (form 0, Thundering Blow) roots
    # the target enemy over the cast time, then swings the
    # hammer to deal magic damage + knock the target back 600
    # units. The CC duration EQUALS the Meraki castTime field
    # (0.25 seconds, captured via the ENGINE 1.51.0 schema lift
    # of ``tools/daemon_slayer_abilities_extract.py``). The
    # post-cast knockback is a separate displacement that lives
    # in the unconditional `_PER_SPELL_CC_DURATIONS` registry
    # (Jayce E form 0 knockback) - the wave 14 entry captures
    # ONLY the cast-time root payload that fires before the
    # knockback. Form 1 (Cannon-form Acceleration Gate) has
    # cast_time=None (instant cast) and NO first-order CC -
    # purely an ally-MS-buff gate placement. Maps to
    # COND_CHANNEL_COMPLETION on the brief 0.25s cast lockout -
    # if Jayce is interrupted mid-cast (silenced / stunned /
    # CC'd within the 0.25s), no root or knockback fires.
    # Probability 0.5 (tag midpoint) - short 0.25s cast window
    # is generally completed but Jayce E is targeted with no
    # stealth + slowed-targets-only sweetspot, so the operator
    # frequently lands E only on damaged or already-CC'd
    # targets making interruption-mid-cast rare in practice.
    #
    # Mechanic schema-lift-verified: effects_descriptions[0] for
    # form_index=0 ("Active: Jayce roots the target enemy over
    # the cast time, then swings his hammer at them to deal
    # magic damage, capped against monsters, and knock them
    # back 600 units") + Meraki source castTime=0.25 for form
    # 0 confirmed via the ENGINE 1.51.0 re-extract of
    # ``data/daemon_slayer/16.10.1/champion_abilities.json``.
    # The 0.4 seconds carry in the description ("Jayce is
    # unable to cast To the Skies! or Shock Blast for 0.4
    # seconds after Thundering Blow's cast time") refers to
    # the Q/Q1 lockout AFTER cast, NOT the cast-time root
    # duration - this was the item 170+171 schema-block
    # diagnosis ("0.4s is Q lockout, not root").
    #
    # Coexists with absence in `_PER_SPELL_CC_DURATIONS` for
    # Jayce E ROOT payload (the unconditional registry holds
    # the post-cast knockback as a separate entry; this is
    # the FIRST Jayce E root-payload registration). Sidecar
    # pattern preferred - form_index carries semantic meaning
    # (form 0 = Hammer-form root payload; form 1 = Cannon-
    # form utility no CC). Closes item 170 wave 12 carry +
    # item 171 wave 13 carry "Jayce E cast-time root STILL
    # schema-blocked" - the schema lift this wave delivers
    # the missing cast_time field. Form-explicit override key
    # shape: Jayce:E:0.
    registry.setdefault("Jayce", {})[("E", 0)] = ConditionalCcEntry(
        champion="Jayce",
        spell="E",
        cc_kind="root",
        durations_s=(0.25,),
        condition=COND_CHANNEL_COMPLETION,
        probability=_p_form("Jayce", "E", 0, 0.5),
        notes=(
            "E form 0 Thundering Blow cast-time root: Jayce's "
            "Hammer-form E roots the target enemy for 0.25s "
            "over the cast time before dealing damage + "
            "knocking them back 600 units. The CC duration "
            "equals the Meraki castTime field (0.25s flat - "
            "no rank scaling on the cast lockout). Form 1 "
            "(Cannon Acceleration Gate) is instant-cast "
            "(cast_time=None) and has NO first-order CC. "
            "Maps to COND_CHANNEL_COMPLETION on the brief "
            "0.25s cast lockout - interruption mid-cast "
            "cancels root + knockback. Probability tag "
            "midpoint 0.5 - 0.25s cast window completes in "
            "most fights, but Jayce E is targeted + reliable "
            "only on slowed or already-CC'd enemies. FIRST "
            "Jayce first-order CC registration (the "
            "unconditional knockback lives in "
            "`_PER_SPELL_CC_DURATIONS` separately). Sidecar "
            "pattern - form_index carries semantic meaning "
            "(form 0 carries CC, form 1 does not). "
            "Mechanic captured by ENGINE 1.51.0 schema lift "
            "(``tools/daemon_slayer_abilities_extract.py`` "
            "now extracts the Meraki castTime field per "
            "form). Closes item 170 wave 12 + item 171 "
            "wave 13 deferred carry-forward 'Jayce E cast-"
            "time root STILL schema-blocked' - the cast_time "
            "field is now available in extracted data. "
            "The item 170+171 ledger note '0.4 seconds is "
            "Q lockout not root' was correct - the 0.25s "
            "cast time is the actual root duration. Form-"
            "explicit override key shape: Jayce:E:0."
        ),
        form_index=0,
    )

    # ============================================================
    # === wave 15 expansion (2026-05-24 / ENGINE 1.52.0) - +1
    # === sidecar entry / +1 net-new champion via cast_time
    # === Meraki schema lift on Rell W form 0 Ferromancy: Crash
    # === Down channel-completion stun. Rell W has 2 forms
    # === toggled by her mount state:
    # ===
    # ===   * form_index=0 Ferromancy: Crash Down (Mounted state)
    # ===     - 0.625s cast_time leap + on-arrival 0.8s stun + 0.4s
    # ===     knockup AoE. Channel-completion conditional.
    # ===   * form_index=1 Ferromancy: Mount Up (Dismounted state)
    # ===     - 0.25s cast_time + 0.6s stun on EMPOWERED-AA-after-
    # ===     transition (next-hit-after-form-transition). Not
    # ===     cleanly cast-time conditional; REJECTED separately
    # ===     pending operator clarification.
    # ===
    # === This wave 15 entry registers ONLY form 0 in the sidecar
    # === registry. Sidecar pattern parallel to Hwei E form 1+2 +
    # === Sylas E form 1 + Karma W form 1 + Gnar W form 1 +
    # === Aphelios Q form 3 + Jayce E form 0 - form_index carries
    # === semantic meaning (form 0 = Mounted-state CC payload;
    # === form 1 = Dismounted-state empowered-AA payload registered
    # === elsewhere or REJECTED this wave).
    # ============================================================

    # Rell W form_index=0 Ferromancy: Crash Down channel-completion
    # stun: Rell's W in Mounted form (Ferromancy: Crash Down) is a
    # 0.625s cast_time leap to a target location. Upon arrival she
    # deals magic damage + STUNS nearby enemies for 0.8s flat +
    # KNOCKS UP for 0.4s + slides another 320 units over 0.5s.
    # The CC payload fires ONLY when the cast-time leap COMPLETES;
    # if Rell is hard-CC'd mid-cast (silenced / stunned / CC'd
    # within the 0.625s), no arrival + no stun/knockup fires.
    # Maps to COND_CHANNEL_COMPLETION - the 0.625s cast lockout
    # is the channel window. Probability 0.5 (tag midpoint) -
    # Rell W is a leap-engage with momentum; interrupting it
    # requires Rell's target to have already-active ranged CC.
    # Standalone W cast that is INTERRUPTED = no arrival payload
    # (cast fails). Form 1 (Mount Up Dismounted-state empowered-
    # AA) is a separate spell with different mechanics + a
    # different conditional layer; that form is REJECTED this
    # wave pending operator clarification. Coexists with the
    # unconditional Rell Q stun entry in `_PER_SPELL_CC_DURATIONS`
    # on a different spell slot (FIRST Rell W first-order CC
    # registration anywhere in the engine).
    #
    # Mechanic schema-lift-verified: effects_descriptions[1] for
    # form_index=0 ("Active: Rell becomes Dismounted and leaps to
    # the target location over the cast time, granting herself a
    # shield that lasts until destroyed or casting Ferromancy:
    # Mount Up. Upon arrival, she deals magic damage to nearby
    # enemies, stuns them for 0.8 seconds, and knocks them up for
    # 0.4 seconds.") + Meraki cast_time=0.625 for form 0. The
    # 0.4s knockup is a separate displacement payload not
    # registered here - this entry encodes ONLY the 0.8s stun
    # payload. Form-explicit override key shape: Rell:W:0.
    registry.setdefault("Rell", {})[("W", 0)] = ConditionalCcEntry(
        champion="Rell",
        spell="W",
        cc_kind="stun",
        durations_s=(0.8,),
        condition=COND_CHANNEL_COMPLETION,
        probability=_p_form("Rell", "W", 0, 0.5),
        notes=(
            "W form 0 Ferromancy: Crash Down channel-completion "
            "stun: Rell's Mounted-state W leaps over 0.625s "
            "cast_time + on arrival deals magic damage + STUNS "
            "nearby enemies 0.8s flat across all 5 W ranks + "
            "knocks up 0.4s + slides 320 units. CC payload fires "
            "ONLY on cast completion; mid-cast hard CC cancels "
            "arrival + stun/knockup. Maps to "
            "COND_CHANNEL_COMPLETION - 0.625s cast lockout is "
            "the channel window. Probability tag midpoint 0.5 - "
            "leap-engage with momentum; interruption requires "
            "ranged CC already active on target's team. Form 1 "
            "(Mount Up Dismounted-state empowered-AA) shipped "
            "wave 22 (ENGINE 1.60.0) as a separate sidecar entry "
            "below. FIRST Rell W first-order CC registration in "
            "the engine. Coexists with the unconditional Rell Q "
            "stun entry in `_PER_SPELL_CC_DURATIONS` on a "
            "different spell slot. The 0.4s knockup is a separate "
            "displacement payload not registered here - this entry "
            "encodes ONLY the 0.8s stun. Mechanic captured by "
            "ENGINE 1.51.0 schema lift (Meraki cast_time field "
            "for form 0 = 0.625s). Form-explicit override key "
            "shape: Rell:W:0."
        ),
        form_index=0,
    )

    # ============================================================
    # === wave 22 expansion (2026-05-25 / ENGINE 1.60.0) - +1
    # === entry / 0 net-new champions via same-spell-slot schema
    # === lift on (Rell, W). Closes item 198 carry (i) Rell W form 1
    # === operator-gated since wave 15 REJECT pending operator
    # === clarification on form-transition empowered-AA semantics.
    # === Operator authority granted item 199 Slice B.
    # ============================================================

    # Rell W form_index=1 Ferromancy: Mount Up empowered-AA stun:
    # The base Rell W has TWO forms - form 0 Crash Down (Dismounted
    # leap, wave 15 ship) and form 1 Mount Up (Dismounted -> Mounted
    # transform). Form 1 is the Mount Up recast within 3.5s of form
    # 0 cast. Form 1 grants Mounted state + buffs Rell's next basic
    # attack within 3.5s to charge the target at 100 bonus range +
    # 40% bonus AS, with 0.2s cast_time. Upon CHARGE-ARRIVAL or
    # collision, the empowered AA deals bonus magic damage + STUNS
    # the target 0.6s flat + flings them 150 units over Rell over
    # 0.4s.
    #
    # Mechanic per Meraki effects_descriptions[0] for form_index=1:
    # "Active: Rell becomes Mounted, gaining 30% bonus movement
    # speed decaying over 2 seconds and empowering her next basic
    # attack within 3.5 seconds to have a 0.2-second cast time, gain
    # 100 bonus attack range and cause her to charge at the target's
    # location, during which she also gains 40% bonus attack speed.
    # Upon arrival or collision, she deals bonus magic damage, stuns
    # the target for 0.6 seconds, and flings them 150 units over
    # herself, though not through terrain, over 0.4 seconds."
    # Meraki cast_time=0.25 for form 1 (the form 1 cast itself; the
    # empowered AA charge is a separate 0.2s cast on AA delivery).
    #
    # Encoding choice: cc_kind=stun (the 0.6s stun is the primary
    # locked-CC payload; the 0.4s fling is a separate displacement
    # not registered here - mirrors form 0's exclusion of its own
    # 0.4s knockup). Single-element duration tuple - 0.6s is flat
    # across all 5 W ranks (the stun does NOT scale with W rank;
    # only the cast cooldown + Mount Up shield-conversion scale).
    #
    # Condition tag: COND_CHANNEL_COMPLETION - the 2-cast cycle
    # (form 0 -> form 1 within 3.5s) + the empowered-AA charge
    # delivery sequence is functionally a multi-step channel. The
    # stun fires ONLY on charge-arrival completion; if Rell is
    # interrupted between form 1 cast + AA delivery (silenced /
    # CC'd / killed) the stun does NOT fire. Pattern parallel to
    # Sylas E form 1 Abduct (2-cast cycle, wave 12) + Hwei E form
    # 1 Grim Visage (2-cast cycle, wave 9). Probability midpoint
    # 0.4 (mid-low, mirroring Sylas E + Hwei E form 1 - 2-input
    # setup is reliable in Rell combo cadence but the charged AA
    # is dodgeable within the 100-unit-extended range; the 3.5s
    # form 1 + 3.5s AA window is generous but operator-gated since
    # the empowered AA can be denied by knockup / dash / hard CC
    # on Rell mid-charge).
    #
    # Coexists with the wave 15 Rell W form 0 sidecar entry on the
    # same (Rell, W) slot via the form_index discriminator. This is
    # the FOURTH same-spell-slot multi-form-coexistence in the
    # sidecar registry (after Karma W form 0+1, Hwei E form 0+1+2,
    # Sylas E form 0+1). Default
    # compute_cc_pressure(include_conditional=False) is BYTE-
    # IDENTICAL to ENGINE 1.59.0 for Rell - the conditional path
    # skips when the flag is False. include_conditional=True
    # callers receive +0.24s (0.6 * 0.4) NEW conditional pressure
    # on top of the wave 15 form 0 0.4s (0.8 * 0.5) = total
    # conditional 0.64s for Rell W.
    #
    # Form-explicit override key shape: Rell:W:1.
    registry.setdefault("Rell", {})[("W", 1)] = ConditionalCcEntry(
        champion="Rell",
        spell="W",
        cc_kind="stun",
        durations_s=(0.6,),
        condition=COND_CHANNEL_COMPLETION,
        probability=_p_form("Rell", "W", 1, 0.4),
        notes=(
            "W form 1 Ferromancy: Mount Up empowered-AA stun: "
            "Rell's Dismounted-state W (recast within 3.5s of "
            "form 0 Crash Down) transforms her to Mounted state "
            "AND empowers her next basic attack within 3.5s. The "
            "empowered AA charges the target at 100 bonus range + "
            "40% bonus AS with 0.2s cast_time. Upon charge-"
            "arrival or collision, the AA deals bonus magic "
            "damage + STUNS the target 0.6s flat across all 5 W "
            "ranks + flings them 150 units over Rell over 0.4s. "
            "Maps to COND_CHANNEL_COMPLETION on the 2-cast cycle "
            "(form 0 -> form 1 within 3.5s) + empowered-AA "
            "charge-delivery sequence. Stun fires ONLY on charge-"
            "arrival completion; interruption between form 1 cast "
            "+ AA delivery (silenced / CC'd / killed) cancels the "
            "stun. Probability tag midpoint 0.4 - mid-low matching "
            "Sylas E form 1 + Hwei E form 1 parallel 2-input "
            "setup pattern; the 3.5s form 1 + 3.5s AA window is "
            "generous but the empowered AA can be denied by hard "
            "CC on Rell mid-charge. Coexists with the wave 15 "
            "Rell W form 0 sidecar entry on the same (Rell, W) "
            "slot via the form_index discriminator (FOURTH same-"
            "spell-slot multi-form-coexistence in the sidecar "
            "registry after Karma W 0+1 / Hwei E 0+1+2 / Sylas E "
            "0+1). The 0.4s fling is a separate displacement "
            "payload not registered here - this entry encodes "
            "ONLY the 0.6s stun. Mechanic captured by ENGINE "
            "1.51.0 schema lift (Meraki cast_time + "
            "effects_descriptions for form 1; both already "
            "available since wave 14 cast_time lift). Closes item "
            "198 carry (i) Rell W form 1 operator-gated since "
            "wave 15 REJECT carry. Form-explicit override key "
            "shape: Rell:W:1."
        ),
        form_index=1,
    )

    return registry
```
