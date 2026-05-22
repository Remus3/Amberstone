"""Conditional CC entries that cannot fit the unconditional first-order schema.

A conditional CC fires only when a specific in-game condition is met
(e.g. 3rd-hit stack, terrain element nearby, channel completion). The
fight-window EHP-vs-CC scorer would over- or under-credit these if
they were modeled as unconditional, so they live in a separate registry
with explicit probability + condition tags.

This module ships at ENGINE 1.37.0 (2026-05-22) as a FORWARD-MARKER seam
with the schema + machinery + a seed of 10 canonical examples drawn
from the wave 4/5/6 REJECT lists in CLAUDE.md items 138/139/140.
No consumer wires to it yet. Future consumers populate via
probability-weighted aggregation in ``compute_cc_pressure`` or a
sibling fight-sim that wants to credit (probability * duration) per
conditional entry alongside the unconditional first-order entries
already in ``_PER_SPELL_CC_DURATIONS``.

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
