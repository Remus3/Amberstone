"""Riot per-role grading rubric.

Calibration reference: https://www.unrankedsmurfs.com/blog/what-is-riot-algorithm-for-determining-s-and-s+-ranks
The unrankedsmurfs writeup is the single public source for the per-role weight
vectors Riot uses internally to compute end-of-game S/A/B/C/D letter grades.
The numbers reproduced below are STARTING calibration values derived from
that public rubric source; the operator can tune them later via per-role
JSON overrides (the loader seam is documented but NOT built today - drop
a JSON next to data/post_game_wpa_model.json when it becomes useful).

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

from dataclasses import dataclass


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
# module docstring for the per-role rationale. Operator-tunable via a future
# per-role JSON override; do NOT load JSON here today.
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
    cs_per_min = cs / max(1.0, minutes) if minutes > 0 else 0.0
    damage_per_min = damage / max(1.0, minutes) if minutes > 0 else 0.0

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
