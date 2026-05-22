"""Conditional CC entries that cannot fit the unconditional first-order schema.

A conditional CC fires only when a specific in-game condition is met
(e.g. 3rd-hit stack, terrain element nearby, channel completion). The
fight-window EHP-vs-CC scorer would over- or under-credit these if
they were modeled as unconditional, so they live in a separate registry
with explicit probability + condition tags.

JSON override loader
--------------------

Loader implementation: ``_load_overrides`` (reads the file) +
``_apply_default_probability_overrides`` (composes onto the per-tag
midpoints) + ``_apply_per_entry_overrides`` (returns the lookup map
threaded into each ConditionalCcEntry at builder time).

The operator can tune the 10 per-tag probability midpoints AND the 28
per-entry probabilities without modifying source by dropping a JSON
file at ``data/cc_conditional_calibration.json`` (gitignored as
personal calibration data alongside ``data/post_game_rubric_weights.json``
and ``data/coaching/death_patterns.json``).

Schema (both top-level keys optional; missing keys keep the defaults):

    {
      "default_condition_probability": {
        "nth_hit": 0.65,
        "channel_completion": 0.55
      },
      "per_entry_probability": {
        "Brand:R": 0.75,
        "Maokai:Q": 0.35
      }
    }

Fail-soft semantics:

  * Missing file -> defaults preserved (no error, no warning).
  * Empty file / whitespace-only -> defaults preserved.
  * Malformed JSON -> defaults preserved (one WARNING log at module load).
  * Non-dict top-level -> defaults preserved.
  * Unknown condition tag keys silently dropped (forward-compatible
    with future tag constants).
  * Unknown ``<champion>:<spell>`` keys silently dropped (forward-
    compatible with future registry entries).
  * Malformed entry keys without exactly one colon silently dropped.
  * Out-of-range [0.0, 1.0] values silently DROPPED (NOT clamped) so a
    nonsense override does not subtly distort the ConditionalCcEntry
    construction; the default value stays in force for that key.
  * Bool values dropped (Python bool is int subclass; True/False MUST
    NOT silently become 1.0/0.0).
  * Non-numeric values dropped (str / null / list / dict ignored).

The override file is read ONCE at module import. To re-apply after
editing, restart RC via ``restart_trigger.txt`` (matches the cache-
discipline pattern the coach prompts use for
``data/coaching/death_patterns.json``).

This module ships at ENGINE 1.37.0 (2026-05-22) as a FORWARD-MARKER seam
with the schema + machinery + a seed of 10 canonical examples drawn
from the wave 4/5/6 REJECT lists in CLAUDE.md items 138/139/140 plus
wave 1 expansion of +8 entries across +8 new champions drawn from the
same REJECT lists (CLAUDE.md items 138/139/140/141), bringing the
registry to 18 entries across 18 champions. Wave 2 (2026-05-22 / ENGINE
1.39.0) adds +5 entries across +5 new champions sourced from the wave
4-7 REJECT lists + the wave 1 REJECT carry-forward, bringing the
registry to 23 entries across 23 champions. Wave 3 (2026-05-22 / ENGINE
1.40.0) adds +5 entries across +5 new champions, all 3-cast-cycle
knock-up sweetspot triggers + Leblanc full-tether snare, bringing the
registry to 28 entries across 28 champions. Wave 4 (2026-05-22 /
ENGINE 1.41.0) adds +5 entries across +4 new champions + 1 multi-
wave coexistence (Aatrox W chain-root coexists with Aatrox Q3
knockup from wave 3), bringing the registry to 33 entries across 32
champions.
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

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Tuple


_LOG = logging.getLogger(__name__)


# Per-tag + per-entry probability override file. See module docstring
# for schema. Operator-tunable; missing/malformed file is fail-soft.
# Gitignored as personal calibration data.
_OVERRIDES_PATH = Path("data") / "cc_conditional_calibration.json"


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


# ---------------- JSON override loader ----------------


def _load_overrides() -> dict:
    """Read per-tag + per-entry overrides from _OVERRIDES_PATH.

    Returns an empty dict when the file is missing or malformed. Never
    raises; a single WARNING is logged on malformed JSON so the
    operator gets a hint without the dashboard crashing.

    Schema is documented in the module docstring. Top-level dict with
    optional ``default_condition_probability`` (tag -> float) and
    ``per_entry_probability`` (``<champion>:<spell>`` -> float) keys.
    Anything else at top-level returns ``{}`` so the apply functions
    only see well-shaped input.
    """
    try:
        raw = _OVERRIDES_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError:
        # Permission errors, parent-not-a-directory, etc. - fail-soft.
        return {}
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        _LOG.warning(
            "cc_conditional: malformed JSON at %s; defaults preserved",
            _OVERRIDES_PATH,
        )
        return {}
    if not isinstance(data, dict):
        # Top-level must be a JSON object.
        return {}
    return data


def _apply_default_probability_overrides(
    defaults: Dict[str, float],
    overrides: dict,
) -> Dict[str, float]:
    """Compose per-tag probability overrides onto the default midpoints.

    Unknown tag keys are silently dropped (forward-compatible with
    future condition tag constants). Non-float values are silently
    dropped (the default tag midpoint is kept). Out-of-range values
    (negative or > 1.0) are silently DROPPED (not clamped) so a
    nonsense override does not subtly distort downstream construction.

    Returns a NEW dict; the input ``defaults`` mapping is not mutated.
    """
    if not overrides:
        return dict(defaults)
    section = overrides.get("default_condition_probability")
    if not isinstance(section, dict):
        return dict(defaults)
    result: Dict[str, float] = dict(defaults)
    for tag, value in section.items():
        if not isinstance(tag, str):
            continue
        if tag not in defaults:
            # Unknown tag - forward-compatible silent drop.
            continue
        # bool is a subclass of int in Python; reject so True/False do
        # not silently become 1.0/0.0.
        if isinstance(value, bool):
            continue
        if not isinstance(value, (int, float)):
            continue
        numeric = float(value)
        # Out-of-range values DROPPED (not clamped). The defaults stay
        # in force. Pinned by ApplyDefaultProbabilityOverridesTests.
        if numeric < 0.0 or numeric > 1.0:
            continue
        result[tag] = numeric
    return result


def _apply_per_entry_overrides(overrides: dict) -> Dict[Tuple[str, str], float]:
    """Build the per-entry probability override lookup map.

    Reads the ``per_entry_probability`` block of the overrides dict.
    Returns a dict keyed by ``(champion, spell)`` tuples (matching the
    builder's setdefault key shape). Non-conformant entries are
    silently dropped:

      * Key without exactly one colon (cannot split into champ:spell).
      * Empty champion or spell after split.
      * Non-float value.
      * Bool value.
      * Out-of-range [0.0, 1.0] value.

    The builder reads this lookup via ``.get((champion, spell), tag_default)``
    when constructing each ConditionalCcEntry. Unknown
    ``<champion>:<spell>`` keys are not validated against the seed
    here - they are silently dropped at builder lookup time when
    ``.get()`` returns the tag default.
    """
    if not overrides:
        return {}
    section = overrides.get("per_entry_probability")
    if not isinstance(section, dict):
        return {}
    result: Dict[Tuple[str, str], float] = {}
    for key, value in section.items():
        if not isinstance(key, str):
            continue
        # Key shape: ``<champion>:<spell>`` (exactly one colon).
        parts = key.split(":")
        if len(parts) != 2:
            continue
        champion, spell = parts[0].strip(), parts[1].strip()
        if not champion or not spell:
            continue
        # bool defense (must come before int/float check).
        if isinstance(value, bool):
            continue
        if not isinstance(value, (int, float)):
            continue
        numeric = float(value)
        if numeric < 0.0 or numeric > 1.0:
            continue
        result[(champion, spell)] = numeric
    return result


# Apply overrides at module load. The builder reads the post-override
# _DEFAULT_CONDITION_PROBABILITY for tag-default lookups and the per-
# entry map for per-(champion, spell) override lookups. Both default
# to no-op when the override file is absent or malformed.
_OVERRIDES_RAW = _load_overrides()
_DEFAULT_CONDITION_PROBABILITY = _apply_default_probability_overrides(
    _DEFAULT_CONDITION_PROBABILITY, _OVERRIDES_RAW
)
_PER_ENTRY_PROBABILITY_OVERRIDES: Dict[Tuple[str, str], float] = (
    _apply_per_entry_overrides(_OVERRIDES_RAW)
)


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
        probability=0.5,
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
        probability=0.4,
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
        probability=0.5,
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
        probability=0.5,
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
        probability=0.3,
        notes=(
            "Q dash; if target is knocked into terrain at end of dash, "
            "stun 1.0s. No-terrain hit is damage only. terrain "
            "conditional. Frenzy-state-gated variants (Q+R during "
            "Frenzy) carry forward operator-gated - they need a new "
            "condition tag schema lift not in this wave."
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
    "_OVERRIDES_PATH",
    "_PER_ENTRY_PROBABILITY_OVERRIDES",
    "_PER_SPELL_CC_CONDITIONAL",
    "_apply_default_probability_overrides",
    "_apply_per_entry_overrides",
    "_build_per_spell_cc_conditional",
    "_load_overrides",
    "get_conditional_entries",
    "get_total_conditional_cc_seconds",
]
