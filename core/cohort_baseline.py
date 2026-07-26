"""Per-role cohort baselines from the .rofl stats corpus (T0).

The criteria doc keeps saying "vs cohort" and there was nothing to compare
against. This builds that comparison from the archived sidecars: 4070
player-rows across 407 challenger games, read off disk with zero API calls.

WHY RATES, NOT TOTALS. Corpus game length runs 70 s to 3044 s (median 1608).
A raw cs or damage total therefore measures how long the game happened to last
at least as much as how the player performed, so every metric here is
PER MINUTE of that player's own TIME_PLAYED. The two exceptions are noted in
METRICS and are ratios already.

WHY PERCENTILES, NOT MEANS. A coaching line needs "you are in the bottom
quarter of junglers for camp throughput", which is a percentile question. A
mean would also be dragged around by the long tail of stomps and 15-minute
surrenders.

FIELD-NAME TRAPS, verified against a real sidecar - these are the engine's own
names and several differ from the obvious guess:
    kills   CHAMPIONS_KILLED   (not KILLS)
    deaths  NUM_DEATHS         (not DEATHS)
    champ   SKIN               (not championName)
    cs      MINIONS_KILLED + NEUTRAL_MINIONS_KILLED
    vision  VISION_SCORE, WARD_PLACED, WARD_KILLED
Every sidecar value is a STRING, including numerics and WIN ('Win'/'Fail').

SCOPE: T0 is end-of-game only. These baselines say nothing about WHEN anything
happened - that is T1/T2. They are a yardstick for outcome metrics, not a
timeline.
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path

# metric name -> (sidecar fields to sum, per_minute?)
METRICS = {
    "cs_per_min": (("MINIONS_KILLED", "NEUTRAL_MINIONS_KILLED"), True),
    "jungle_cs_per_min": (("NEUTRAL_MINIONS_KILLED",), True),
    "gold_per_min": (("GOLD_EARNED",), True),
    "damage_to_champs_per_min": (("TOTAL_DAMAGE_DEALT_TO_CHAMPIONS",), True),
    "damage_taken_per_min": (("TOTAL_DAMAGE_TAKEN",), True),
    "vision_score_per_min": (("VISION_SCORE",), True),
    "wards_placed_per_min": (("WARD_PLACED",), True),
    "wards_killed_per_min": (("WARD_KILLED",), True),
    "cc_seconds_per_min": (("TIME_CCING_OTHERS",), True),
    "heal_on_teammates_per_min": (("TOTAL_HEAL_ON_TEAMMATES",), True),
    "turret_damage_per_min": (("TOTAL_DAMAGE_DEALT_TO_TURRETS",), True),
    # Already ratios / counts that do not scale with time in a useful way.
    "kills": (("CHAMPIONS_KILLED",), False),
    "deaths": (("NUM_DEATHS",), False),
    "assists": (("ASSISTS",), False),
}

PERCENTILES = (10, 25, 50, 75, 90)

# A player with less than this much time played is a remake or a disconnect,
# and their rates are meaningless (a 60 s row divides by ~1).
MIN_TIME_PLAYED_S = 600


def _num(value) -> float:
    """Sidecar values are STRINGS. A bad one is 0.0, never a crash."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def row_metrics(player: dict) -> dict:
    """One sidecar player row -> the metric dict, or {} if unusable."""
    time_played = _num(player.get("TIME_PLAYED"))
    if time_played < MIN_TIME_PLAYED_S:
        return {}
    minutes = time_played / 60.0
    out = {}
    for name, (fields, per_minute) in METRICS.items():
        total = sum(_num(player.get(f)) for f in fields)
        out[name] = (total / minutes) if per_minute else total
    return out


# Match-V5 participant field names for the SAME metrics. Kept separate from
# METRICS rather than mapped, because the two sources genuinely disagree on
# naming and a single table would hide that: the sidecar says CHAMPIONS_KILLED
# and MINIONS_KILLED, Match-V5 says kills and totalMinionsKilled.
MV5_METRICS = {
    "cs_per_min": (("totalMinionsKilled", "neutralMinionsKilled"), True),
    "jungle_cs_per_min": (("neutralMinionsKilled",), True),
    "gold_per_min": (("goldEarned",), True),
    "damage_to_champs_per_min": (("totalDamageDealtToChampions",), True),
    "damage_taken_per_min": (("totalDamageTaken",), True),
    "vision_score_per_min": (("visionScore",), True),
    "wards_placed_per_min": (("wardsPlaced",), True),
    "wards_killed_per_min": (("wardsKilled",), True),
    "cc_seconds_per_min": (("timeCCingOthers",), True),
    "heal_on_teammates_per_min": (("totalHealsOnTeammates",), True),
    "turret_damage_per_min": (("damageDealtToTurrets",), True),
    "kills": (("kills",), False),
    "deaths": (("deaths",), False),
    "assists": (("assists",), False),
}


def participant_metrics(participant: dict) -> dict:
    """Match-V5 participant -> the same metric dict as row_metrics().

    Lets a baseline be built from match blobs alone - one API call per match,
    no timeline and no .rofl - which is what makes an all-ranks sweep
    affordable.
    """
    time_played = _num(participant.get("timePlayed"))
    if time_played < MIN_TIME_PLAYED_S:
        return {}
    minutes = time_played / 60.0
    out = {}
    for name, (fields, per_minute) in MV5_METRICS.items():
        total = sum(_num(participant.get(f)) for f in fields)
        out[name] = (total / minutes) if per_minute else total
    return out


def build(rows) -> dict:
    """rows = iterable of (role, metric_dict) -> percentile tables per role.

    A metric needs at least 20 samples in a role before it is reported;
    percentiles over a handful of rows are noise with decimal places.
    """
    by_role: dict = {}
    for role, metrics in rows:
        if not role or not metrics:
            continue
        by_role.setdefault(role, {})
        for name, value in metrics.items():
            by_role[role].setdefault(name, []).append(value)

    out = {}
    for role, metrics in sorted(by_role.items()):
        out[role] = {}
        for name, values in sorted(metrics.items()):
            if len(values) < 20:
                continue
            values = sorted(values)
            out[role][name] = {
                "n": len(values),
                "mean": round(statistics.mean(values), 3),
                **{f"p{p}": round(_percentile(values, p), 3)
                   for p in PERCENTILES},
            }
    return out


def _percentile(sorted_values, pct: float) -> float:
    """Linear-interpolated percentile. Explicit rather than numpy-dependent."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    k = (len(sorted_values) - 1) * (pct / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = k - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac


def rank_of(baselines: dict, role: str, metric: str, value: float):
    """Where a value falls in its cohort, as a percentile band.

    Returns None when the cohort has no table for that metric - an unknown
    cohort must not be reported as an average one.
    """
    table = (baselines.get(role) or {}).get(metric)
    if not table:
        return None
    bands = [(table[f"p{p}"], p) for p in PERCENTILES if f"p{p}" in table]
    band = 0
    for threshold, pct in bands:
        if value >= threshold:
            band = pct
    return {"metric": metric, "role": role, "value": round(value, 3),
            "at_or_above_p": band, "median": table["p50"], "n": table["n"]}


def load(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8")).get("roles", {})
