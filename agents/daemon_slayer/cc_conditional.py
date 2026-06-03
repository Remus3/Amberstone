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
champions. Wave 5 (2026-05-22 / ENGINE 1.42.0) adds +2 entries via
multi-wave coexistence on existing champions (Briar E channel-
completion fear sourced from item 144 Briar W frenzy carry-forward
+ TahmKench Q nth_hit passive-stack stun re-examined from item 142
conditional carry), bringing the registry to 35 entries across 32
champions (no net-new champions; both entries land on existing
champions via setdefault). TahmKench Q coexists with TahmKench R
wave 0 conditional devour on a different spell slot. Briar Q wave 4
+ Briar E wave 5 coexist on the same champion via setdefault (SECOND
multi-wave coexistence after Aatrox Q3+W from waves 3+4; TahmKench
R+Q is THIRD). Wave 6 (2026-05-22 / ENGINE 1.43.0) adds +1 entry via
multi-wave coexistence on an existing champion (Brand Q Sear
target_debuffed stun on Blaze-stacked target sourced from the wave 4
REJECT carry where Brand W was rejected as not first-order; the
canonical Brand Q stun-on-blazed-target IS first-order CC with a
clean COND_TARGET_DEBUFFED fit), bringing the registry to 36 entries
across 32 champions (no net-new champions; Brand Q lands via
setdefault alongside Brand R wave 0 nth_hit 3-stack stun - FOURTH
multi-entry-WITHIN-cc_conditional champion after Aatrox Q+W (waves
3+4) / Briar Q+E (waves 4+5) / TahmKench R+Q (waves 0+5); Pantheon
W+Q noted as multi-wave but Pantheon W lives in the SEPARATE
unconditional `_PER_SPELL_CC_DURATIONS` registry not cc_conditional,
so Pantheon has 1 entry in cc_conditional). The Brand Q encoding uses
COND_TARGET_DEBUFFED because the stun fires only when target carries
a Blaze passive stack (from any prior Brand spell-hit or auto-attack
applying passive); standalone Q on a non-blazed target is damage
only.
Wave 7 (2026-05-22 / ENGINE 1.44.0) closes item 147 carry (l) by
shipping the long-deferred conditional CC tag schema lift: 2 NEW tag
constants ``COND_FRENZY_STATE`` (champion enters a self-empowered
state that gates a CC variant of another spell) and ``COND_RANGE_GATED``
(CC fires only at a specific cast-range band, distinct from terrain
positioning and stack accumulation). Both tags register in
``_DEFAULT_CONDITION_PROBABILITY`` with calibrated midpoint 0.4 (mid-
low because the prerequisite empowered-state / range-band achievement
is operator-controlled but not guaranteed). NO new registry entries
this wave (registry stays at 36 entries / 32 champions); the schema
lift is a FORWARD-MARKER seam mirroring the s112 ``STAT_GRANT_CALC_KEYS``
empty-registry pattern. The item 147 carry-forward named Briar frenzy
+ Sylas range as the canonical REJECT candidates for these tags, but a
Meraki 16.10.1 re-verify during this run found: (1) Sylas E2 Abduct
stuns on hook hit regardless of cast range (the item 142 REJECT note
calling it range-conditional was incorrect); (2) Briar W has 2 forms
(Blood Frenzy + Snack Attack) but the Meraki extract is parse-stripped
to damage_blocks only - the leveling/effects detail needed to verify
a frenzy-empowered Q or R CC mechanic is absent at parse-strip level.
Future entries populate when a Meraki-verifiable mechanic surfaces.
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
from typing import Dict, List, Optional, Tuple


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

COND_FRENZY_STATE = "frenzy_state"
# Champion enters a self-empowered state (Briar W Blood Frenzy,
# Renekton Fury threshold, Volibear R passive form, Aatrox post-R
# passive) that gates an empowered variant of another spell with
# first-order CC. Probability midpoint reflects the fraction of fight
# windows in which the operator has entered the empowered state
# before the gated CC fires. Forward-marker tag added at ENGINE
# 1.44.0 (item 148 schema lift) closing item 147 carry (l); no
# registry entry consumes this tag at ship time. Future entries
# populate when a Meraki-verifiable frenzy-gated CC mechanic
# surfaces.

COND_RANGE_GATED = "range_gated"
# CC fires only when the cast lands within a specific range band
# (close-range or max-range). Distinct from COND_TERRAIN (positioning
# vs map geometry) and COND_NTH_HIT (stack accumulation). Probability
# midpoint reflects the fraction of fights where the operator
# achieves the required range band. Forward-marker tag added at
# ENGINE 1.44.0 (item 148 schema lift) closing item 147 carry (l);
# no registry entry consumes this tag at ship time. The item 142
# REJECT note attaching this tag to Sylas E2 Abduct was incorrect
# (the Abduct stun fires on hook hit regardless of cast range per
# 16.10.1 Riot spec). Future entries populate when a Meraki-
# verifiable range-gated CC mechanic surfaces.

COND_TRAVERSE = "traverse"
# CC fires only when an enemy champion DASHES through or IS DISPLACED
# OVER a placed object (typically a ground-zone marker placed by the
# spell itself). Distinct from COND_TERRAIN (collision with map
# geometry / wall slam), COND_NTH_HIT (stack accumulation), and
# COND_TARGET_DEBUFFED (pre-applied mark on the target).
# Probability midpoint 0.3 reflects that champions typically AVOID a
# telegraphed traverse-zone unless forced through it by displacement
# or a need-to-pass-through pathing constraint. Schema lift shipped at
# ENGINE 1.54.0 (wave 17) closing item 174 carry (i) "Taliyah E needs
# new COND_TRAVERSE tag". First consumer is Taliyah E Unraveled Earth
# dash-detonation stun 0.75s, captured by ENGINE 1.46.0 Meraki schema
# lift (effects_descriptions[1] "Enemies that dash or are knocked over
# a stone will detonate it, taking magic damage and becoming stunned
# for 0.75 seconds ... The stun is applied once the displacement
# ends"). Future entries populate when other Meraki-verifiable
# traverse-gated CC mechanics surface.


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
    COND_FRENZY_STATE: 0.4,
    COND_RANGE_GATED: 0.4,
    COND_TRAVERSE: 0.3,
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
      * ``form_index``: optional Meraki form_index pin. ``None`` (the
        default) means the entry encodes the DEFAULT / aggregate form
        of the spell (legacy wave 0-9 entries; one entry per
        (champion, spell) slot in the primary
        ``_PER_SPELL_CC_CONDITIONAL`` registry). An integer means the
        entry encodes a SPECIFIC Meraki ``form_index`` of the spell
        (multi-form same-spell-slot entries; lives in the parallel
        ``_PER_SPELL_CC_CONDITIONAL_FORMS`` sidecar registry). Added
        at ENGINE 1.47.0 (wave 10 schema lift, 2026-05-23) to support
        spells where multiple forms on the same Q/W/E/R slot each
        carry a distinct first-order CC mechanic (Karma W Renewal
        Mantra-bonus root extension; Hwei E Gaze of the Abyss EW
        form root). Backward-compat: all wave 0-9 entries omit the
        field and default to ``form_index=None``.
      * ``coexists_with_unconditional``: ENGINE 1.55.0 (wave 18 schema
        lift, 2026-05-24) flag. ``False`` (the default) for all wave
        0-17 entries means the entry stands ALONE on its (champion,
        spell) slot: the consumer credits the conditional contribution
        directly via ``include_conditional=True``. ``True`` declares
        that the same (champion, spell) slot ALSO has an unconditional
        entry in ``_PER_SPELL_CC_DURATIONS`` and the consumer MUST
        avoid double-crediting. When ``True``, the consumer treats the
        ``durations_s`` here as the FULL conditional-window duration
        (typically the MAX-condition payoff, e.g. Maokai R max-distance
        root 2.25s) and SUBTRACTS the unconditional contribution from
        the same spell slot via ``_PER_SPELL_CC_DURATIONS``. Net effect
        at ``include_conditional=True``: max(unconditional rank, prob *
        conditional duration) credited per spell - never both summed.
        Wave 18 lands a single consumer: Maokai R (unconditional rank-
        based mid-distance root 1.2/1.6/2.0s in the legacy registry
        coexists with the cc_conditional COND_RANGE_GATED max-distance
        2.25s entry). Backward-compat: all wave 0-17 entries omit the
        field and default to ``False``.
    """

    champion: str
    spell: str
    cc_kind: str
    durations_s: Tuple[float, ...]
    condition: str
    probability: float = 0.5
    notes: str = ""
    form_index: Optional[int] = None
    coexists_with_unconditional: bool = False

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


_REGISTRY_DATA_PATH = Path(__file__).with_name("cc_conditional_registry.json")


def _load_registry_data() -> dict:
    """Load + validate the externalized conditional-CC registry JSON.

    The data file (``cc_conditional_registry.json``, co-located with this
    module) IS the registry source after the item-245 A3 externalization
    (the ~3300-line Python builders were relocated to
    ``CC_CONDITIONAL_NOTES.md`` and replaced by the two JSON loaders
    below). Unlike the OPTIONAL calibration override file
    (``data/cc_conditional_calibration.json``), this data file is
    REQUIRED: a missing / malformed file raises so a packaging error
    fails loud rather than silently producing an empty registry.
    """
    raw = _REGISTRY_DATA_PATH.read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict) or "primary" not in data or "forms" not in data:
        raise ValueError(
            "cc_conditional_registry.json malformed (need primary + forms): "
            f"{_REGISTRY_DATA_PATH}"
        )
    return data


def _build_per_spell_cc_conditional() -> Dict[str, Dict[str, ConditionalCcEntry]]:
    """Build the primary conditional CC registry from the data file.

    Reconstructs one ``ConditionalCcEntry`` per ``primary`` record in
    ``cc_conditional_registry.json``. The stored ``probability`` is the
    SEED midpoint; ``_p(champion, spell, seed)`` re-applies any operator
    ``per_entry_probability`` override from
    ``data/cc_conditional_calibration.json`` so the calibration layer is
    preserved (byte-identical to the pre-A3 hardcoded builder when the
    override file is absent / empty).

    Returns a FRESH ``Dict[champion, Dict[spell, entry]]`` each call (the
    setdefault accumulation semantic of the legacy builder is preserved:
    each (champion, spell) slot holds exactly one default-form entry).
    Wave history + per-entry / REJECT rationale: ``CC_CONDITIONAL_NOTES.md``.
    """

    def _p(champion: str, spell: str, default: float) -> float:
        return _PER_ENTRY_PROBABILITY_OVERRIDES.get((champion, spell), default)

    registry: Dict[str, Dict[str, ConditionalCcEntry]] = {}
    for rec in _load_registry_data()["primary"]:
        champ = rec["champion"]
        spell = rec["spell"]
        registry.setdefault(champ, {})[spell] = ConditionalCcEntry(
            champion=champ,
            spell=spell,
            cc_kind=rec["cc_kind"],
            durations_s=tuple(rec["durations_s"]),
            condition=rec["condition"],
            probability=_p(champ, spell, rec["probability"]),
            notes=rec["notes"],
            form_index=rec["form_index"],
            coexists_with_unconditional=rec["coexists_with_unconditional"],
        )
    return registry


# Module-load: build registry once. Callers can re-invoke the builder
# for fresh dict instances (used by tests to verify multi-wave-friendly
# construction).
_PER_SPELL_CC_CONDITIONAL: Dict[str, Dict[str, ConditionalCcEntry]] = (
    _build_per_spell_cc_conditional()
)


# ---------------- wave 10 form-explicit sidecar registry ----------------
#
# ENGINE 1.47.0 (2026-05-23) introduces the same-spell-slot schema lift
# to support spells where multiple Meraki ``form_index`` records on the
# SAME Q/W/E/R slot each carry a distinct first-order CC mechanic.
#
# Examples surfaced via the ENGINE 1.46.0 ``effects_descriptions`` schema
# lift in ``data/daemon_slayer/16.10.1/champion_abilities.json``:
#
#   * Karma W: form_index=0 Focused Resolve (channel-completion root,
#     wave 1 default-form entry) coexists with form_index=1 Renewal
#     (Mantra-bonus root extension; gated on Karma reaching a Mantra
#     rank and casting empowered W via R).
#   * Hwei E: form_index=1 Grim Visage (EQ form, channel-completion
#     fear, wave 9 default-form entry) coexists with form_index=2
#     Gaze of the Abyss (EW form, channel-completion root).
#
# Schema design:
#
#   * The PRIMARY ``_PER_SPELL_CC_CONDITIONAL`` registry is unchanged
#     ``Dict[str, Dict[str, ConditionalCcEntry]]`` to preserve backward
#     compatibility with ~244 test access lines pinning the
#     ``["Champion"]["Slot"]`` lookup pattern. All wave 0-9 entries
#     stay in this registry with ``form_index=None`` (default form
#     semantic).
#   * The PARALLEL ``_PER_SPELL_CC_CONDITIONAL_FORMS`` sidecar
#     registry is ``Dict[str, Dict[Tuple[str, int], ConditionalCcEntry]]``
#     keyed by ``(spell, form_index)``. Wave 10 form-explicit entries
#     live here with their ``form_index`` field set to the integer
#     Meraki form_index. This avoids the same-slot collision in the
#     primary registry (e.g. (Karma, W) primary holds form_index=None
#     Focused Resolve; sidecar holds (W, 1) Renewal).
#   * ``get_conditional_entries(champion)`` merges entries from both
#     registries, returning a flat Q/W/E/R-ordered tuple with multi-
#     form entries on the same slot ordered by form_index ASC.
#   * ``REGISTRY_TOTAL_ENTRIES`` counts the union (legacy +
#     form-explicit). ``REGISTRY_TOTAL_CHAMPIONS`` counts unique
#     champions across both registries.
#
# Math preservation: byte-identical for default include_conditional=False
# callers (the consumer path skips conditional entirely). For
# include_conditional=True callers, the new form-explicit entries
# contribute to ``compute_cc_pressure`` for their champions ON TOP of
# the legacy default-form entries. This is the INTENDED schema-lift
# growth: Karma W and Hwei E gain a SECOND conditional CC contribution
# per cast (when the form is selected) instead of being capped at one
# entry per slot.


def _build_per_spell_cc_conditional_forms() -> (
    Dict[str, Dict[Tuple[str, int], ConditionalCcEntry]]
):
    """Build the form-explicit conditional CC sidecar registry from the data file.

    Reconstructs one ``ConditionalCcEntry`` per ``forms`` record in
    ``cc_conditional_registry.json``, keyed by ``(spell, form_index)``.
    ``_p_form(champion, spell, form_index, seed)`` re-applies any operator
    per-form override (3-segment ``<champion>:<spell>:<form_index>`` key) -
    byte-identical to the pre-A3 builder when the override file is absent /
    empty. Returns a FRESH dict each call. Wave history + per-entry rationale:
    ``CC_CONDITIONAL_NOTES.md``.
    """

    def _p_form(
        champion: str, spell: str, form_index: int, default: float
    ) -> float:
        return _PER_FORM_ENTRY_PROBABILITY_OVERRIDES.get(
            (champion, spell, form_index), default
        )

    registry: Dict[str, Dict[Tuple[str, int], ConditionalCcEntry]] = {}
    for rec in _load_registry_data()["forms"]:
        champ = rec["champion"]
        spell = rec["spell"]
        fi = rec["form_index"]
        registry.setdefault(champ, {})[(spell, fi)] = ConditionalCcEntry(
            champion=champ,
            spell=spell,
            cc_kind=rec["cc_kind"],
            durations_s=tuple(rec["durations_s"]),
            condition=rec["condition"],
            probability=_p_form(champ, spell, fi, rec["probability"]),
            notes=rec["notes"],
            form_index=fi,
            coexists_with_unconditional=rec["coexists_with_unconditional"],
        )
    return registry


# ---------------- public lookup helpers ----------------


_SPELL_ORDER = ("Q", "W", "E", "R")


# Apply per-form per-entry overrides at module load. The form-builder
# reads this map for (champion, spell, form_index) -> probability
# overrides. Defaults to no-op when the override file is absent or
# malformed. Extends the wave 1 ``_PER_ENTRY_PROBABILITY_OVERRIDES``
# pattern with a 3-tuple key shape.
def _apply_per_form_entry_overrides(
    overrides: dict,
) -> Dict[Tuple[str, str, int], float]:
    """Build the per-form per-entry probability override lookup map.

    Reads the ``per_entry_probability`` block of the overrides dict.
    Returns a dict keyed by ``(champion, spell, form_index)`` tuples
    matching the form-builder's lookup key shape. Non-conformant
    entries are silently dropped:

      * Key without exactly two colons (cannot split into
        champ:spell:form).
      * Empty champion or spell after split.
      * Non-integer form_index segment.
      * Non-float value.
      * Bool value.
      * Out-of-range [0.0, 1.0] value.

    The form-builder reads this lookup via
    ``.get((champion, spell, form_index), tag_default)`` when
    constructing each form-explicit ConditionalCcEntry. Unknown
    ``<champion>:<spell>:<form>`` keys are not validated against the
    seed here - they are silently dropped at builder lookup time when
    ``.get()`` returns the form-builder's hardcoded default.

    Same-key collision: if the override JSON has BOTH a 2-segment
    ``<champion>:<spell>`` key (wave 1+ shape) AND a 3-segment
    ``<champion>:<spell>:<form>`` key, the 2-segment lookup feeds the
    primary registry default-form entries and the 3-segment lookup
    feeds the sidecar registry form-explicit entries; both coexist
    without ambiguity.
    """
    if not overrides:
        return {}
    section = overrides.get("per_entry_probability")
    if not isinstance(section, dict):
        return {}
    result: Dict[Tuple[str, str, int], float] = {}
    for key, value in section.items():
        if not isinstance(key, str):
            continue
        # Key shape: ``<champion>:<spell>:<form_index>`` (exactly two
        # colons; the 2-segment shape is handled by the wave 1
        # ``_apply_per_entry_overrides`` helper and silently skipped
        # here).
        parts = key.split(":")
        if len(parts) != 3:
            continue
        champion, spell, form_str = (
            parts[0].strip(), parts[1].strip(), parts[2].strip()
        )
        if not champion or not spell or not form_str:
            continue
        # form_index must parse as an integer >= 0.
        try:
            form_index = int(form_str)
        except (TypeError, ValueError):
            continue
        if form_index < 0:
            continue
        # bool defense (must come before int/float check).
        if isinstance(value, bool):
            continue
        if not isinstance(value, (int, float)):
            continue
        numeric = float(value)
        if numeric < 0.0 or numeric > 1.0:
            continue
        result[(champion, spell, form_index)] = numeric
    return result


_PER_FORM_ENTRY_PROBABILITY_OVERRIDES: Dict[Tuple[str, str, int], float] = (
    _apply_per_form_entry_overrides(_OVERRIDES_RAW)
)


# Module-load: build sidecar registry once. Callers can re-invoke the
# builder for fresh dict instances (used by tests to verify multi-wave-
# friendly construction).
_PER_SPELL_CC_CONDITIONAL_FORMS: Dict[
    str, Dict[Tuple[str, int], ConditionalCcEntry]
] = _build_per_spell_cc_conditional_forms()


def get_conditional_entries(champion: str) -> Tuple[ConditionalCcEntry, ...]:
    """Return all conditional CC entries for a champion in Q/W/E/R order.

    Returns the empty tuple for unknown champions, blank / None
    champion, or champions with no conditional entries.

    The returned tuple is sorted in canonical Q-W-E-R order over the
    subset of spells the champion has registered (matches the
    ``compute_cc_pressure`` ordering convention). For spells with
    multi-form schema-lift entries (Karma W / Hwei E since ENGINE
    1.47.0), the primary default-form entry comes FIRST, followed by
    each form-explicit sidecar entry in form_index ASC order.
    """
    if not champion:
        return ()
    spells_dict = _PER_SPELL_CC_CONDITIONAL.get(champion, {})
    forms_dict = _PER_SPELL_CC_CONDITIONAL_FORMS.get(champion, {})
    if not spells_dict and not forms_dict:
        return ()
    ordered: List[ConditionalCcEntry] = []
    for slot in _SPELL_ORDER:
        # Primary default-form entry (wave 0-9 legacy + setdefault
        # pattern) lands first.
        if slot in spells_dict:
            ordered.append(spells_dict[slot])
        # Form-explicit sidecar entries (wave 10+) land next, sorted
        # by form_index ASC for deterministic iteration order.
        slot_forms = [
            (form_idx, entry)
            for (spell, form_idx), entry in forms_dict.items()
            if spell == slot
        ]
        for _, entry in sorted(slot_forms, key=lambda pair: pair[0]):
            ordered.append(entry)
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

    RAW BY DESIGN - does NOT apply the coexistence MAX-rule. This
    helper is a context-free probability-weighted sum over the
    CONDITIONAL registry alone. It deliberately does NOT know about
    game mode, does NOT apply build / ARAM tenacity, and does NOT
    consult the unconditional ``_PER_SPELL_CC_DURATIONS`` registry. So
    for an entry with ``coexists_with_unconditional=True`` (Hecarim R /
    Maokai R / Vayne E at the active patch) it still credits the
    conditional contribution in full, whereas the live consumer credits
    MAX(same-slot unconditional, conditional) for that slot and never
    sums both (see ``compute_cc_pressure`` ENGINE 1.55.0 wave-18 MAX
    rule). The two therefore DIVERGE on coexisting slots by
    construction: this helper returns the larger (raw conditional)
    value, and that divergence is intentional, not a bug. A consumer
    that needs the coexistence-correct, tenacity-aware, mode-aware total
    must read ``compute_cc_pressure(champion, mode,
    include_conditional=True).conditional_cc_seconds`` (the
    authoritative MAX-applied consumer), NOT this helper. This helper
    stays raw so diagnostic / test fixtures and any future consumer that
    wants the un-MAX'd conditional ceiling have one context-free
    primitive. See ``test_cc_conditional_consumer_parity`` for the
    pinned divergence.

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


# REGISTRY_TOTAL_CHAMPIONS counts the union of champions across the
# primary registry (wave 0-9 default-form entries) and the sidecar
# registry (wave 10+ form-explicit same-spell-slot entries). Since the
# wave 10 schema-lift candidates (Karma W form 1, Hwei E form 2) both
# already have wave 0-9 entries in the primary registry, this stays at
# the pre-wave-10 champion count for wave 10. Future waves that add
# form-explicit entries on NEW champions would grow this count.
REGISTRY_TOTAL_CHAMPIONS: int = len(
    set(_PER_SPELL_CC_CONDITIONAL.keys())
    | set(_PER_SPELL_CC_CONDITIONAL_FORMS.keys())
)
# REGISTRY_TOTAL_ENTRIES sums entries across BOTH registries. The
# primary registry contains one entry per (champion, spell) default-form
# slot; the sidecar contains one entry per (champion, spell, form_index)
# form-explicit slot. The two never collide by construction (legacy
# entries use form_index=None semantic; sidecar entries use explicit
# integer form_index).
REGISTRY_TOTAL_ENTRIES: int = sum(
    len(spells) for spells in _PER_SPELL_CC_CONDITIONAL.values()
) + sum(
    len(forms) for forms in _PER_SPELL_CC_CONDITIONAL_FORMS.values()
)


__all__ = [
    "COND_CHANNEL_COMPLETION",
    "COND_DEVOUR_TARGET",
    "COND_DREAM_STACK",
    "COND_DUAL_ENEMY",
    "COND_FRENZY_STATE",
    "COND_GOLD_CARD",
    "COND_MODE_GATED",
    "COND_NTH_HIT",
    "COND_RANGE_GATED",
    "COND_TARGET_DEBUFFED",
    "COND_TARGET_HP_BELOW",
    "COND_TERRAIN",
    "COND_TRAVERSE",
    "ConditionalCcEntry",
    "REGISTRY_TOTAL_CHAMPIONS",
    "REGISTRY_TOTAL_ENTRIES",
    "_DEFAULT_CONDITION_PROBABILITY",
    "_OVERRIDES_PATH",
    "_PER_ENTRY_PROBABILITY_OVERRIDES",
    "_PER_FORM_ENTRY_PROBABILITY_OVERRIDES",
    "_PER_SPELL_CC_CONDITIONAL",
    "_PER_SPELL_CC_CONDITIONAL_FORMS",
    "_apply_default_probability_overrides",
    "_apply_per_entry_overrides",
    "_apply_per_form_entry_overrides",
    "_build_per_spell_cc_conditional",
    "_build_per_spell_cc_conditional_forms",
    "_load_overrides",
    "get_conditional_entries",
    "get_total_conditional_cc_seconds",
]
