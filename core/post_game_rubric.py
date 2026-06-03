"""Riot per-role grading rubric.

Calibration reference: https://www.unrankedsmurfs.com/blog/what-is-riot-algorithm-for-determining-s-and-s+-ranks
The unrankedsmurfs writeup is the single public source for the per-role weight
vectors Riot uses internally to compute end-of-game S/A/B/C/D letter grades.
The numbers reproduced below are STARTING calibration values derived from
that public rubric source.

Per-role JSON override loader
-----------------------------

Loader implementation: `_load_weights_overrides` (reads the file) +
`_apply_overrides` (composes onto defaults via dataclasses.replace).

The operator can tune the per-role weights without modifying source by
dropping a JSON file at `data/post_game_rubric_weights.json` (gitignored
as personal calibration data alongside `data/coaching/death_patterns.json`).

Schema (per-role partial overrides allowed; missing axes keep the default):

    {
      "ADC": {"kda": 2.5, "obj_participation": 0.6},
      "SUP": {"vision_score": 1.8}
    }

Fail-soft semantics:

  * Missing file -> defaults preserved (no error, no warning).
  * Empty `{}` -> defaults preserved.
  * Malformed JSON -> defaults preserved (one WARNING log at module load).
  * Unknown role keys silently ignored (forward-compatible with future roles).
  * Unknown axis keys silently ignored (forward-compatible with future axes).
  * Negative weights floored to 0.0 (a negative score weight is nonsense).
  * Non-numeric values silently ignored (default kept for that axis).
  * Non-dict role values silently ignored (a top-level role key whose value
    is not a JSON object cannot carry axis overrides).

The override file is read ONCE at module import. To re-apply after editing,
restart RC via `restart_trigger.txt` (matches the cache-discipline pattern
the coach prompts use for `data/coaching/death_patterns.json`).

Sibling module note
-------------------

This module is a SIBLING to core/post_game_score.py (PGR S2 WPA framework).
WPA scores a per-event delta given the rolling match state. The rubric here
scores a per-match per-role profile against role-specific baselines. They
compose; do NOT consolidate.

Role weight rationale (from the public rubric source):

  * ADC: 2.1 KDA weight + 0.50 obj-participation weight + 0.85 CS-per-min.
    Damage-per-minute weighted heavily (carry expectation).
  * SUP: 2.5 KDA + weighted vision (highest of any role) + 0.10 obj-
    participation + 0.00 CS-per-min (CS is intentionally NOT scored for
    support - taking CS is anti-pattern). Damage-per-min weighted low.
  * JG:  1.8 KDA + 0.70 obj-participation (highest weight - jungle is
    judged most on objective participation) + 0.40 CS-per-min.
  * MID: 2.0 KDA + 0.30 obj-participation + 0.85 CS-per-min. Damage-per-min
    weighted heavily (carry expectation but less than ADC's farm window).
  * TOP: 1.9 KDA + 0.25 obj-participation + 0.80 CS-per-min. Lowest obj
    weight (isolated lane expectation).

Vision score weight: SUP 1.5 (dominant signal for the role), all other
roles 0.30 (vision is universally tracked but not a primary role metric).

Damage-per-min weight: ADC 0.85, MID 0.80, JG 0.55, TOP 0.45, SUP 0.20.
"""
from __future__ import annotations

import dataclasses
import json
import logging
from dataclasses import dataclass
from pathlib import Path

_LOG = logging.getLogger(__name__)

# Per-role JSON override file. See module docstring for schema. Operator-tunable;
# missing/malformed file is fail-soft. Gitignored.
_OVERRIDES_PATH = Path("data") / "post_game_rubric_weights.json"


@dataclass(frozen=True)
class RoleWeights:
    """Per-role weight vector for the rubric scorer.

    All float fields default to 0.0 so a partial override (e.g. just SUP)
    does not need to spell out every axis. Construct via the registry below
    or pass a custom instance to compute_role_grade.
    """

    role: str
    kda: float = 0.0
    cs_per_min: float = 0.0
    obj_participation: float = 0.0
    vision_score: float = 0.0
    damage_per_min: float = 0.0


# Starting calibration values derived from the public rubric source. See the
# module docstring for the per-role rationale. Operator-tunable via the JSON
# override loader (see _OVERRIDES_PATH + _load_weights_overrides below); the
# defaults below are what ships when no override file is present.
_DEFAULT_WEIGHTS: dict[str, RoleWeights] = {
    "ADC": RoleWeights(
        role="ADC",
        kda=2.1,
        cs_per_min=0.85,
        obj_participation=0.50,
        vision_score=0.30,
        damage_per_min=0.85,
    ),
    "SUP": RoleWeights(
        role="SUP",
        kda=2.5,
        cs_per_min=0.00,
        obj_participation=0.10,
        vision_score=1.5,
        damage_per_min=0.20,
    ),
    "JG": RoleWeights(
        role="JG",
        kda=1.8,
        cs_per_min=0.40,
        obj_participation=0.70,
        vision_score=0.30,
        damage_per_min=0.55,
    ),
    "MID": RoleWeights(
        role="MID",
        kda=2.0,
        cs_per_min=0.85,
        obj_participation=0.30,
        vision_score=0.30,
        damage_per_min=0.80,
    ),
    "TOP": RoleWeights(
        role="TOP",
        kda=1.9,
        cs_per_min=0.80,
        obj_participation=0.25,
        vision_score=0.30,
        damage_per_min=0.45,
    ),
}


# Numeric axes that the override loader is allowed to set. Unknown axes are
# silently dropped at apply time (forward-compatible with future RoleWeights
# fields - a future axis only needs to be listed here to be operator-tunable).
_OVERRIDE_AXES: frozenset[str] = frozenset(
    {"kda", "cs_per_min", "obj_participation", "vision_score", "damage_per_min"}
)


def _load_weights_overrides() -> dict[str, dict]:
    """Read per-role weight overrides from _OVERRIDES_PATH.

    Returns an empty dict when the file is missing or malformed. Never raises;
    a single WARNING is logged on malformed JSON so the operator gets a hint
    without the dashboard crashing.

    Schema is documented in the module docstring. Top-level keys are role
    names (ADC/SUP/JG/MID/TOP); values are dicts of axis -> numeric weight.
    Non-dict role values are silently dropped at the loader layer so the
    apply function only sees well-shaped {role: {axis: float}} input.
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
            "post_game_rubric: malformed JSON at %s; defaults preserved",
            _OVERRIDES_PATH,
        )
        return {}
    if not isinstance(data, dict):
        # Top-level must be a JSON object.
        return {}
    cleaned: dict[str, dict] = {}
    for role, axes in data.items():
        if not isinstance(role, str):
            continue
        if not isinstance(axes, dict):
            continue
        cleaned[role] = axes
    return cleaned


def _apply_overrides(
    defaults: dict[str, RoleWeights],
    overrides: dict[str, dict],
) -> dict[str, RoleWeights]:
    """Compose overrides onto defaults via dataclasses.replace.

    Unknown role keys are silently dropped (forward-compatible with future
    roles). Unknown axis keys are silently dropped (forward-compatible with
    future axes). Negative weights are floored to 0.0. Non-numeric values are
    silently dropped (the default axis weight is kept for that role).

    Returns a NEW dict; the input `defaults` mapping is not mutated.
    """
    if not overrides:
        return dict(defaults)
    result: dict[str, RoleWeights] = dict(defaults)
    for role, axes in overrides.items():
        base = defaults.get(role)
        if base is None:
            # Unknown role - forward-compatible silent drop.
            continue
        fields: dict[str, float] = {}
        for axis, value in axes.items():
            if axis not in _OVERRIDE_AXES:
                # Unknown axis - forward-compatible silent drop.
                continue
            # bool is a subclass of int in Python; reject so True/False do
            # not silently become 1.0/0.0.
            if isinstance(value, bool):
                continue
            if not isinstance(value, (int, float)):
                continue
            numeric = float(value)
            if numeric < 0.0:
                numeric = 0.0
            fields[axis] = numeric
        if fields:
            result[role] = dataclasses.replace(base, **fields)
    return result


# Apply overrides at module load. compute_role_grade and any consumer that
# reads _DEFAULT_WEIGHTS see the post-override values without further work.
_DEFAULT_WEIGHTS = _apply_overrides(_DEFAULT_WEIGHTS, _load_weights_overrides())


# Per-role baselines (per-game medians at ~32 min). A 1.0-normalized
# profile maps to a total_score of ~50 (mid-table B grade). A +2x outlier
# saturates at ~100 (S+). Sourced from public per-role median tables.
_ROLE_BASELINES: dict[str, dict[str, float]] = {
    "ADC": {
        "kda": 2.5,
        "cs_per_min": 7.5,
        "obj_participation": 0.55,
        "vision_score": 15.0,
        "damage_per_min": 600.0,
    },
    "SUP": {
        "kda": 3.0,
        "cs_per_min": 1.0,
        "obj_participation": 0.50,
        "vision_score": 55.0,
        "damage_per_min": 180.0,
    },
    "JG": {
        "kda": 3.0,
        "cs_per_min": 5.5,
        "obj_participation": 0.70,
        "vision_score": 25.0,
        "damage_per_min": 420.0,
    },
    "MID": {
        "kda": 2.8,
        "cs_per_min": 7.0,
        "obj_participation": 0.40,
        "vision_score": 18.0,
        "damage_per_min": 620.0,
    },
    "TOP": {
        "kda": 2.5,
        "cs_per_min": 6.5,
        "obj_participation": 0.35,
        "vision_score": 14.0,
        "damage_per_min": 480.0,
    },
}


# Common Riot role aliases. Match-V5 carries TeamPosition strings like
# "BOTTOM"/"UTILITY"/"JUNGLE"/"MIDDLE"/"TOP"; the rubric canonicalizes them.
_ROLE_ALIASES: dict[str, str] = {
    "BOTTOM": "ADC",
    "BOT": "ADC",
    "ADC": "ADC",
    "SUPPORT": "SUP",
    "UTILITY": "SUP",
    "SUP": "SUP",
    "JUNGLE": "JG",
    "JG": "JG",
    "MIDDLE": "MID",
    "MID": "MID",
    "TOP": "TOP",
    "TOPLANE": "TOP",
}


def _normalize_role(role: str | None) -> str:
    """Canonicalize a role string to one of ADC/SUP/JG/MID/TOP.

    Falls back to MID for unknown / blank / None inputs (MID has the
    most-balanced baseline of the five and is the safest default for a
    partial scorer).
    """
    if not role:
        return "MID"
    upper = str(role).strip().upper()
    if not upper:
        return "MID"
    return _ROLE_ALIASES.get(upper, "MID")


def _component_score(weight: float, raw: float, baseline: float) -> float:
    """Compute one component contribution to total_score.

    weight * clamp(raw / baseline, 0, 2). A 1.0 normalized profile (raw
    matches baseline exactly) contributes weight * 1.0; a 2x outlier
    saturates at weight * 2.0.
    """
    if baseline <= 0:
        return 0.0
    normalized = raw / baseline
    if normalized < 0:
        normalized = 0.0
    elif normalized > 2.0:
        normalized = 2.0
    return weight * normalized


def _grade_bucket(score: float) -> str:
    """Bucket a total_score [0, 100] to S+/S/A/B/C/D."""
    if score >= 85:
        return "S+"
    if score >= 75:
        return "S"
    if score >= 65:
        return "A"
    if score >= 50:
        return "B"
    if score >= 35:
        return "C"
    return "D"


def compute_role_grade(
    stats: dict,
    role: str,
    weights: RoleWeights | None = None,
) -> dict:
    """Score a per-match per-role profile.

    Args:
        stats: dict carrying kills, deaths, assists, cs, game_time_s,
            obj_participation_pct (0.0-1.0), vision_score,
            damage_dealt_to_champions. Missing keys are treated as 0
            (fail-soft, never raise).
        role: TeamPosition / role string. Canonicalized via
            _normalize_role; unknown -> MID.
        weights: optional RoleWeights override. Defaults to the
            calibration registry for the canonicalized role.

    Returns:
        dict with keys: role, total_score, components (dict), and
        percentile_grade ("S+", "S", "A", "B", "C", or "D").
    """
    canonical_role = _normalize_role(role)
    role_weights = weights if weights is not None else _DEFAULT_WEIGHTS[canonical_role]
    baselines = _ROLE_BASELINES[canonical_role]

    kills = float(stats.get("kills", 0) or 0)
    deaths = float(stats.get("deaths", 0) or 0)
    assists = float(stats.get("assists", 0) or 0)
    cs = float(stats.get("cs", 0) or 0)
    game_time_s = float(stats.get("game_time_s", 0) or 0)
    obj_pct = float(stats.get("obj_participation_pct", 0) or 0)
    vision = float(stats.get("vision_score", 0) or 0)
    damage = float(stats.get("damage_dealt_to_champions", 0) or 0)

    kda_value = (kills + assists) / max(1.0, deaths)
    minutes = game_time_s / 60.0
    # Divide by the true minutes (not a 1.0 floor) so a sub-60s game reports an
    # honest per-minute rate; minutes <= 0 still short-circuits to 0.0 to avoid
    # a zero-division. _component_score clamps the normalized value, so a tiny
    # denominator cannot blow the score up. Identical to the old floor for every
    # real game (minutes > 1).
    cs_per_min = cs / minutes if minutes > 0 else 0.0
    damage_per_min = damage / minutes if minutes > 0 else 0.0

    components = {
        "kda": _component_score(role_weights.kda, kda_value, baselines["kda"]),
        "cs_per_min": _component_score(
            role_weights.cs_per_min, cs_per_min, baselines["cs_per_min"]
        ),
        "obj_participation": _component_score(
            role_weights.obj_participation, obj_pct, baselines["obj_participation"]
        ),
        "vision": _component_score(
            role_weights.vision_score, vision, baselines["vision_score"]
        ),
        "dpm": _component_score(
            role_weights.damage_per_min, damage_per_min, baselines["damage_per_min"]
        ),
    }

    raw_total = sum(components.values())
    # Linear scaling: a 1.0-normalized profile across every axis maps to
    # ~46-50 (mid B); 2x saturation across every axis approaches 100 (S+).
    # Multiplier of 10 is the calibration knob - see module docstring.
    # The sum of default weights per role lands in [4.05, 4.80]; multiplying
    # by 10 puts a fully-saturated outlier at ~90-96 before the 100 clamp.
    total_score = min(100.0, max(0.0, raw_total * 10.0))

    return {
        "role": canonical_role,
        "total_score": total_score,
        "components": components,
        "percentile_grade": _grade_bucket(total_score),
    }
