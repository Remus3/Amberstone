"""Conditional CC entries that cannot fit the unconditional first-order schema.

A conditional CC fires only when a specific in-game condition is met
(e.g. 3rd-hit stack, terrain element nearby, channel completion). The
fight-window EHP-vs-CC scorer would over- or under-credit these if
they were modeled as unconditional, so they live in a separate registry
with explicit probability + condition tags.

This module ships at ENGINE 1.37.0 (2026-05-22) as a FORWARD-MARKER seam
with the schema + machinery + a seed of 10 canonical examples drawn
from the wave 4/5/6 REJECT lists in CLAUDE.md items 138/139/140 plus
wave 1 expansion of +8 entries across +8 new champions drawn from the
same REJECT lists (CLAUDE.md items 138/139/140/141), bringing the
registry to 18 entries across 18 champions. Wave 2 (2026-05-22 / ENGINE
1.39.0) adds +5 entries across +5 new champions sourced from the wave
4-7 REJECT lists + the wave 1 REJECT carry-forward, bringing the
registry to 23 entries across 23 champions.
At initial ship (ENGINE 1.37.0) no consumer wires were attached and the
module was a strict forward marker. The first consumer wire ships via
``compute_cc_pressure(include_conditional=False)`` (item 142 / ENGINE
1.38.0); the kwarg defaults to False so the 4 prior consumers
(compute_ehp / enemy_cc_threat_line / compute_hybrid /
routes_cc_blended_ehp_threat) are byte-identical. Future consumers
opt in by passing include_conditional=True to credit (probability *
duration) per conditional entry alongside the unconditional first-
order entries already in ``_PER_SPELL_CC_DURATIONS``.

Mirrors the empty-seam pattern shipped at:
  * ENGINE 1.22.0 - ``STAT_GRANT_CALC_KEYS`` empty registry in
    ``agents/daemon_slayer/augments.py`` (item 112 / `21657eb`).
  * ENGINE 1.30.0 - ``_PER_SPELL_CC_DURATIONS`` registry was a forward
    marker before seed waves at items 134/135/137/138/139/140 broke it
    to 95 entries across 82 champions.

Closes item 140 carry (h) - the conditional CC axis schema lift was
operator-gated through prior waves; this ships the schema + initial
seed without any consumer wire, so the registry can be populated
incrementally as future consumer logic ships.

Schema:
  * ``ConditionalCcEntry`` frozen dataclass per spell entry with
    champion / spell / cc_kind / per-rank durations / condition tag /
    probability midpoint / notes.
  * ``_DEFAULT_CONDITION_PROBABILITY`` map from condition-tag strings
    to operator-tunable conservative midpoints. The midpoints are the
    starting calibration; future operator tuning via real-game match
    data can replace any value without changing the schema.
  * ``_build_per_spell_cc_conditional`` builder function with
    setdefault pattern (mirrors the wave-6 schema lift from item 140
    so future multi-wave augmentation does not clobber).
  * ``get_conditional_entries(champion)`` returns the ordered Q/W/E/R
    entries for a champion (empty tuple if absent).
  * ``get_total_conditional_cc_seconds(champion, ...)`` returns the
    probability-weighted (or raw) total of max-rank durations for the
    champion. This is the seam shape future consumers read.

The condition-tag constants (``COND_NTH_HIT``, ``COND_GOLD_CARD``,
etc.) are the public taxonomy; future entries should pick from this
set or extend ``_DEFAULT_CONDITION_PROBABILITY`` with a new tag and
its calibrated midpoint.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple


# ---------------- condition tag taxonomy ----------------


# Each condition tag is a string constant. Future entries must use one
# of these or extend ``_DEFAULT_CONDITION_PROBABILITY`` with a new tag.
COND_NTH_HIT = "nth_hit"
# Brand passive 3-stack Blaze stun, Xin Zhao Q 3rd-attack knockup,
# Yasuo Q 3rd-cast knock-up. Probability that a 6s fight window
# accumulates enough hits to trigger.

COND_GOLD_CARD = "gold_card"
# Twisted Fate W Pick a Card landing on Gold. TF cycles R/Y/B; Gold
# requires the operator to pre-set the card before the fight.

COND_TERRAIN = "terrain"
# Volibear Q wall-knockaside, Jarvan IV EQ flag-knockup, Ornn Q
# post-Brittle stun. Requires specific positioning vs map geometry.

COND_CHANNEL_COMPLETION = "channel"
# Karma W full-channel root, Warwick R full-channel suppression,
# Lucian R full-channel. CC duration = channel time; cleanseable +
# interruptible mid-channel.

COND_DREAM_STACK = "dream_stack"
# Lillia E mark + R sleep on marked enemies. Dream stacks accumulate
# slowly across the fight; not all stacked enemies survive to R cast.

COND_DEVOUR_TARGET = "devour"
# Tahm Kench R devour-on-enemy (requires 3 Q stacks to enable, then
# the enemy must be in range when R is cast).

COND_TARGET_HP_BELOW = "low_hp_target"
# Reserved for future execute-like CC entries (no current example).
# Probability depends on fight progression; the target must be below
# the execute threshold when the CC fires.

COND_TARGET_DEBUFFED = "debuffed_target"
# Vex E mark-detonation fear, Lissandra E shard root. Requires a
# pre-applied debuff or mark on the target.

COND_DUAL_ENEMY = "dual_enemy"
# Sett E Facebreaker stun (requires 2+ enemies pulled together),
# Zac Q. Team-fight conditional.

COND_MODE_GATED = "mode_gated"
# Mode-specific (Arena / ARAM only). Probability is 1.0 in the
# matching mode and 0.0 elsewhere; consumers gate by mode separately
# but the tag exists for documentation completeness.


# ---------------- default-probability midpoints ----------------


# Conservative operator-tunable midpoints for each condition tag.
# These are STARTING calibration values; future tuning via real-game
# match data can replace any value without changing the schema. The
# midpoints are intentionally biased toward the average 6s fight
# window where stacks-accumulation / terrain-positioning / channel-
# completion all are plausible but not guaranteed.
_DEFAULT_CONDITION_PROBABILITY: Dict[str, float] = {
    COND_NTH_HIT: 0.7,
    COND_GOLD_CARD: 0.4,
    COND_TERRAIN: 0.3,
    COND_CHANNEL_COMPLETION: 0.5,
    COND_DREAM_STACK: 0.3,
    COND_DEVOUR_TARGET: 0.4,
    COND_TARGET_HP_BELOW: 0.5,
    COND_TARGET_DEBUFFED: 0.5,
    COND_DUAL_ENEMY: 0.6,
    COND_MODE_GATED: 1.0,
}


# ---------------- ConditionalCcEntry schema ----------------


@dataclass(frozen=True)
class ConditionalCcEntry:
    """One conditional CC spell entry.

    Fields:
      * ``champion``: canonical DDragon id (e.g. ``"Brand"``,
        ``"TwistedFate"``, ``"JarvanIV"``).
      * ``spell``: one of ``"Q"``, ``"W"``, ``"E"``, ``"R"``.
      * ``cc_kind``: stun / root / fear / suppression / charm / sleep /
        knockup / knockback / banishment / stasis. Free-form for now
        (matches the cc_kind tags used in ``core/enemy_cc_threat_context``).
      * ``durations_s``: per-rank durations tuple. Length 1 means same
        value all ranks (shorthand). Length 5 for Q/W/E and length 3
        for R is canonical.
      * ``condition``: one of the ``COND_*`` constants. Must exist as a
        key in ``_DEFAULT_CONDITION_PROBABILITY``.
      * ``probability``: 0.0-1.0 probability that the condition is met
        in a 6s fight window. Defaults to the value in
        ``_DEFAULT_CONDITION_PROBABILITY`` for the tag. Per-entry
        override is allowed (some entries are intrinsically more
        reliable than the tag-default midpoint).
      * ``notes``: free-form documentation. Should explain the
        condition + the calibration choice if non-default.
    """

    champion: str
    spell: str
    cc_kind: str
    durations_s: Tuple[float, ...]
    condition: str
    probability: float = 0.5
    notes: str = ""

    def __post_init__(self) -> None:
        if self.spell not in ("Q", "W", "E", "R"):
            raise ValueError(
                f"spell must be Q/W/E/R, got {self.spell!r}"
            )
        if not (0.0 <= self.probability <= 1.0):
            raise ValueError(
                f"probability must be in [0.0, 1.0], got {self.probability}"
            )
        if not self.durations_s:
            raise ValueError("durations_s tuple must be non-empty")
        if any(d < 0 for d in self.durations_s):
            raise ValueError(
                f"durations_s must all be non-negative, got {self.durations_s}"
            )
        expected_ranks = 3 if self.spell == "R" else 5
        if len(self.durations_s) not in (1, expected_ranks):
            raise ValueError(
                f"durations_s tuple length must be 1 (same all ranks) or "
                f"{expected_ranks} for {self.spell}, got {len(self.durations_s)}"
            )
        if self.condition not in _DEFAULT_CONDITION_PROBABILITY:
            raise ValueError(
                f"condition {self.condition!r} not in _DEFAULT_CONDITION_PROBABILITY"
            )


# ---------------- registry builder ----------------


def _build_per_spell_cc_conditional() -> Dict[str, Dict[str, ConditionalCcEntry]]:
    """Build the conditional CC registry.

    Uses ``registry.setdefault(champion, {})[spell] = entry`` pattern
    so multi-wave additions never clobber prior entries (mirrors the
    wave-6 schema lift from item 140 in ``ability_dps.py``).

    Seed: 10 canonical examples from the wave 4/5/6 REJECT lists in
    CLAUDE.md items 138/139/140. Future waves populate further as
    consumer logic ships and operator-calibrates probabilities.
    """
    registry: Dict[str, Dict[str, ConditionalCcEntry]] = {}

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
        probability=0.7,
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
        probability=0.4,
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
        probability=0.5,
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
        probability=0.4,
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
        probability=0.3,
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
        probability=0.5,
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
        probability=0.6,
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
        probability=1.0,
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
        probability=0.6,
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
        probability=0.5,
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
        probability=0.3,
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
        probability=0.4,
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
        probability=0.5,
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
        probability=0.6,
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
        probability=0.7,
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
        probability=0.5,
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
        probability=0.6,
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
        probability=0.4,
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
        probability=0.3,
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
        probability=0.5,
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
        probability=0.5,
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
        probability=0.7,
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
        probability=0.7,
        notes=(
            "Q places delayed bomb (3s); if 2 bombs land on same target "
            "before either detonates, both pop + target stunned 2.0s. "
            "Single bomb is damage only. 2-stack achievability high in "
            "a 6s fight with Q cooldown reset."
        ),
    )

    return registry


# Module-load: build registry once. Callers can re-invoke the builder
# for fresh dict instances (used by tests to verify multi-wave-friendly
# construction).
_PER_SPELL_CC_CONDITIONAL: Dict[str, Dict[str, ConditionalCcEntry]] = (
    _build_per_spell_cc_conditional()
)


# ---------------- public lookup helpers ----------------


_SPELL_ORDER = ("Q", "W", "E", "R")


def get_conditional_entries(champion: str) -> Tuple[ConditionalCcEntry, ...]:
    """Return all conditional CC entries for a champion in Q/W/E/R order.

    Returns the empty tuple for unknown champions, blank / None
    champion, or champions with no conditional entries.

    The returned tuple is sorted in canonical Q-W-E-R order over the
    subset of spells the champion has registered (matches the
    ``compute_cc_pressure`` ordering convention).
    """
    if not champion:
        return ()
    spells_dict = _PER_SPELL_CC_CONDITIONAL.get(champion, {})
    if not spells_dict:
        return ()
    ordered = []
    for slot in _SPELL_ORDER:
        if slot in spells_dict:
            ordered.append(spells_dict[slot])
    return tuple(ordered)


def get_total_conditional_cc_seconds(
    champion: str,
    *,
    apply_probability: bool = True,
    rank_index: int = -1,
) -> float:
    """Sum conditional CC seconds for a champion, optionally weighted.

    Forward-marker contract for future consumers (cc_pressure / fight-
    sim / EHP-vs-CC blended scorer):

      * ``apply_probability=True`` (default): each entry contributes
        ``duration * entry.probability`` to the sum. This is the
        probability-weighted contribution that the operator expects
        the EHP scorer to credit.
      * ``apply_probability=False``: each entry contributes raw
        ``duration`` (max-rank or rank-indexed). Used for diagnostic
        / test fixtures.
      * ``rank_index = -1`` (default): max rank (last element of the
        per-rank tuple).
      * ``rank_index 0..n-1``: select a specific rank.

    Returns 0.0 for unknown champions / no conditional entries / blank
    champion. Never raises.
    """
    entries = get_conditional_entries(champion)
    if not entries:
        return 0.0
    total = 0.0
    for e in entries:
        n = len(e.durations_s)
        if 0 <= rank_index < n:
            idx = rank_index
        else:
            idx = n - 1
        duration = e.durations_s[idx]
        if apply_probability:
            duration *= e.probability
        total += duration
    return total


# ---------------- public introspection ----------------


REGISTRY_TOTAL_CHAMPIONS: int = len(_PER_SPELL_CC_CONDITIONAL)
REGISTRY_TOTAL_ENTRIES: int = sum(
    len(spells) for spells in _PER_SPELL_CC_CONDITIONAL.values()
)


__all__ = [
    "COND_CHANNEL_COMPLETION",
    "COND_DEVOUR_TARGET",
    "COND_DREAM_STACK",
    "COND_DUAL_ENEMY",
    "COND_GOLD_CARD",
    "COND_MODE_GATED",
    "COND_NTH_HIT",
    "COND_TARGET_DEBUFFED",
    "COND_TARGET_HP_BELOW",
    "COND_TERRAIN",
    "ConditionalCcEntry",
    "REGISTRY_TOTAL_CHAMPIONS",
    "REGISTRY_TOTAL_ENTRIES",
    "_DEFAULT_CONDITION_PROBABILITY",
    "_PER_SPELL_CC_CONDITIONAL",
    "_build_per_spell_cc_conditional",
    "get_conditional_entries",
    "get_total_conditional_cc_seconds",
]
