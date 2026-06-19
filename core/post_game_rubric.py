"""Riot per-role grading rubric.

Calibration reference: https://www.unrankedsmurfs.com/blog/what-is-riot-algorithm-for-determining-s-and-s+-ranks
The public rubric writeup is the source for the per-role EMPHASIS ORDERING of
the weight vectors (Riot itself publishes NO exact weights: "The specifics of
how your grade after a game is calculated are not public"). The writeup states,
per role, which stats matter most - CS-led for TOP/MID, KP/objective-heaviest
for JG, vision + strict-KDA + CC for SUP, carry-damage + strict-KDA for ADC.

Two-axis calibration (item 335, 2026-06-06)
-------------------------------------------

  * WEIGHTS encode the public-source emphasis ordering and each role's vector
    sums to 5.0, so a median-of-role performance (every axis at baseline ->
    normalized 1.0) maps to raw_total 5.0, x10 == 50.0, the floor of the B
    band ("a median game is a B").
  * BASELINES are the EMPIRICAL real per-role medians from 5957 ranked-SR
    participant rows in data/rewind_history.db (map 11, CLASSIC, >=15 min):
    they make "normalized 1.0" mean "the median player for this role". The
    pre-335 baselines were hand-estimates that scored the median real game a
    D/C (damage baselines ran 40-80% low, KDA baselines ran high), violating
    the module's own "median -> ~50 B" intent; the re-anchor fixes that.

The weights remain operator-tunable via the JSON override loader below.

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

Role weight rationale (emphasis ordering from the public rubric source;
every vector sums to 5.0):

  * ADC: kda 1.5 + dpm 1.5 co-dominant (carry: strict KDA + highest damage
    expectation of any role) + cs 1.1 (important but below TOP/MID) + obj 0.6
    + vision 0.3.
  * SUP: vision 1.8 (dominant signal, highest single weight of any
    role/axis) + kda 1.6 (strictest-KDA role) + obj 1.0 (KP tied-highest
    with JG) + dpm 0.6 + cs 0.0 (CS intentionally NOT scored - taking CS is
    a support anti-pattern). CC score is a source-cited SUP signal not yet
    modeled (no axis) - a documented gap, not an omission.
  * JG:  obj 1.5 (heaviest weight in the vector - "KP heaviest for junglers")
    + kda 1.4 + dpm 1.1 + vision 0.6 + cs 0.4 (minimal - jungle farm is not
    the grade signal).
  * MID: cs 1.5 (highest emphasis, tied with TOP) + kda 1.4 + dpm 1.2 (carry)
    + obj 0.5 + vision 0.4.
  * TOP: cs 1.5 (highest emphasis) + kda 1.4 + dpm 1.0 + obj 0.7 + vision 0.4.

Vision score weight: SUP 1.8 (dominant signal for the role), JG 0.6, TOP/MID
0.4, ADC 0.3 (vision is universally tracked but a secondary lane metric).

Damage-per-min weight: ADC 1.5 (primary carry), MID 1.2, JG 1.1, TOP 1.0,
SUP 0.6.
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


# Source-ordered weight vectors (item 335). Each role's vector sums to 5.0 so
# a median-of-role performance maps to total_score 50.0 (the B floor). See the
# module docstring for the per-role emphasis rationale. Operator-tunable via the
# JSON override loader (see _OVERRIDES_PATH + _load_weights_overrides below);
# the defaults below are what ships when no override file is present.
_DEFAULT_WEIGHTS: dict[str, RoleWeights] = {
    "ADC": RoleWeights(
        role="ADC",
        kda=1.5,
        cs_per_min=1.1,
        obj_participation=0.6,
        vision_score=0.3,
        damage_per_min=1.5,
    ),
    "SUP": RoleWeights(
        role="SUP",
        kda=1.6,
        cs_per_min=0.0,
        obj_participation=1.0,
        vision_score=1.8,
        damage_per_min=0.6,
    ),
    "JG": RoleWeights(
        role="JG",
        kda=1.4,
        cs_per_min=0.4,
        obj_participation=1.5,
        vision_score=0.6,
        damage_per_min=1.1,
    ),
    "MID": RoleWeights(
        role="MID",
        kda=1.4,
        cs_per_min=1.5,
        obj_participation=0.5,
        vision_score=0.4,
        damage_per_min=1.2,
    ),
    "TOP": RoleWeights(
        role="TOP",
        kda=1.4,
        cs_per_min=1.5,
        obj_participation=0.7,
        vision_score=0.4,
        damage_per_min=1.0,
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


# Per-role baselines = EMPIRICAL real per-role medians (item 335) from 5957
# ranked-SR participant rows in data/rewind_history.db (map 11, CLASSIC,
# >=15 min). A 1.0-normalized profile (every axis at the role median) maps to
# total_score 50.0 (mid-table B grade); a +2x outlier saturates at ~100 (S+).
# Re-anchored from the pre-335 hand-estimates that scored the median game a
# D/C (dpm baselines ran 40-80% low; KDA baselines ran high).
_ROLE_BASELINES: dict[str, dict[str, float]] = {
    "ADC": {
        "kda": 2.3,
        "cs_per_min": 7.15,
        "obj_participation": 0.15,
        "vision_score": 15.0,
        "damage_per_min": 731.0,
    },
    "SUP": {
        "kda": 2.85,
        "cs_per_min": 1.0,
        "obj_participation": 0.125,
        "vision_score": 58.0,
        "damage_per_min": 330.0,
    },
    "JG": {
        "kda": 2.8,
        "cs_per_min": 6.4,
        "obj_participation": 0.375,
        "vision_score": 20.0,
        "damage_per_min": 602.0,
    },
    "MID": {
        "kda": 2.2,
        "cs_per_min": 6.9,
        "obj_participation": 0.13,
        "vision_score": 15.0,
        "damage_per_min": 756.0,
    },
    "TOP": {
        "kda": 1.8,
        "cs_per_min": 6.75,
        "obj_participation": 0.15,
        "vision_score": 15.0,
        "damage_per_min": 717.0,
    },
}


# Optional aggregator-B-style carry-efficiency axis (BACKLOG.md residual 1; folds the
# DISPLAY-only gold_share from item 505 + the existing kill-participation into
# the grade behind a DEFAULT-OFF switch). This is an ADDITIVE bonus axis - when
# enabled it can only RAISE raw_total (never lower it), so a higher gold_share
# or KP yields a non-worse grade (monotonic by construction). When the switch
# is off (the default) the component is never computed and the grade is
# byte-identical to the pre-fold calibration.
#
# The two sub-axes are normalized against neutral baselines:
#   * gold_share_pct: 100/team_size is the even-split baseline. The operator's
#     own roster size is not known here so we use the canonical 5-player SR even
#     split (20.0). _component_score clamps the ratio to [0, 2], so a carry
#     pulling 40% (2x the even split) saturates the gold-share sub-term.
#   * kp_pct: 50.0 is a neutral KP baseline (half the team's kills); a 100% KP
#     game saturates at 2x.
# Each sub-axis carries half the carry-efficiency weight so the combined
# contribution at "even split + neutral KP" equals _CARRY_EFFICIENCY_WEIGHT
# (a median carry profile adds exactly _CARRY_EFFICIENCY_WEIGHT to raw_total ->
# _CARRY_EFFICIENCY_WEIGHT * 10 points). The weight is deliberately modest (0.5)
# so the additive axis is a nudge, not a re-baseline; the full grade re-anchor
# remains a gated product call. Both sub-axes accept a 0-100 percent in `stats`
# (gold_share_pct, kp_pct) and fail-soft to 0.0 when absent.
_CARRY_EFFICIENCY_WEIGHT: float = 0.5
_GOLD_SHARE_EVEN_BASELINE: float = 20.0  # 100 / 5-player SR team
_KP_NEUTRAL_BASELINE: float = 50.0  # half the team's kills


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
    carry_efficiency: bool = False,
) -> dict:
    """Score a per-match per-role profile.

    Args:
        stats: dict carrying kills, deaths, assists, cs, game_time_s,
            obj_participation_pct (0.0-1.0), vision_score,
            damage_dealt_to_champions. Missing keys are treated as 0
            (fail-soft, never raise). When carry_efficiency is True, also
            reads gold_share_pct (0-100, from core.carry_share.gold_share_pct)
            and kp_pct (0-100 kill-participation); both fail-soft to 0.0.
        role: TeamPosition / role string. Canonicalized via
            _normalize_role; unknown -> MID.
        weights: optional RoleWeights override. Defaults to the
            calibration registry for the canonicalized role.
        carry_efficiency: optional aggregator-B-style carry-efficiency fold
            (BACKLOG.md residual 1). DEFAULT-OFF: when False the grade is
            byte-identical to the pre-fold calibration - no carry component is
            computed and `components` does not gain a `carry_efficiency` key.
            When True an ADDITIVE bonus axis (gold_share + KP) contributes to
            raw_total monotonically (a higher gold_share or KP can only raise,
            never lower, the grade). Enabling it is a grade re-baseline and a
            gated product call; the default-off path is what ships live.

    Returns:
        dict with keys: role, total_score, components (dict), and
        percentile_grade ("S+", "S", "A", "B", "C", or "D"). The components
        dict gains a `carry_efficiency` entry ONLY when carry_efficiency=True.
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

    # Optional aggregator-B-style carry-efficiency fold (DEFAULT-OFF). Additive bonus
    # axis: a gold-share sub-term + a kill-participation sub-term, each carrying
    # half the carry-efficiency weight and clamped to [0, 2] by _component_score.
    # Because it only ADDS to raw_total, a higher gold_share or KP yields a
    # non-worse grade (monotonic). When the flag is off this block is skipped
    # entirely, so the grade is byte-identical to the pre-fold calibration.
    if carry_efficiency:
        gold_share = float(stats.get("gold_share_pct", 0) or 0)
        kp = float(stats.get("kp_pct", 0) or 0)
        half_weight = _CARRY_EFFICIENCY_WEIGHT / 2.0
        components["carry_efficiency"] = _component_score(
            half_weight, gold_share, _GOLD_SHARE_EVEN_BASELINE
        ) + _component_score(half_weight, kp, _KP_NEUTRAL_BASELINE)

    raw_total = sum(components.values())
    # Linear scaling: a 1.0-normalized profile across every axis maps to
    # exactly 50.0 (the B floor); 2x saturation across every axis reaches 100
    # (S+). Multiplier of 10 is the calibration knob - see module docstring.
    # Every role's default weight vector sums to 5.0, so the median game
    # (each axis at its empirical baseline) lands at raw_total 5.0 -> 50.0.
    total_score = min(100.0, max(0.0, raw_total * 10.0))

    return {
        "role": canonical_role,
        "total_score": total_score,
        "components": components,
        "percentile_grade": _grade_bucket(total_score),
    }
