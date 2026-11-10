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
import math
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
    """Sidecar values are STRINGS. A bad one is 0.0, never a crash.

    "Bad" includes what float() happily accepts: "nan" / "inf" / "1e999"
    (a NaN rate sorts nowhere and poisons every percentile; json.dumps then
    writes a bare NaN no JSON reader accepts), a negative (every metric here
    is a count or a total, so a negative is corruption, not a value), a bool
    (JSON true is not a stat) and an int too large for a float (OverflowError,
    which the old except did not catch).
    """
    if isinstance(value, bool):
        return 0.0
    try:
        out = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    if not math.isfinite(out) or out < 0:
        return 0.0
    return out


def _rates(row, time_field: str, table: dict) -> dict:
    """Shared body of row_metrics / participant_metrics.

    A row that is not a dict is unusable ({}), like a short one, rather than
    an AttributeError that ends a whole corpus build on one junk sidecar.
    """
    if not isinstance(row, dict):
        return {}
    time_played = _num(row.get(time_field))
    if time_played < MIN_TIME_PLAYED_S:
        return {}
    minutes = time_played / 60.0
    out = {}
    for name, (fields, per_minute) in table.items():
        total = sum(_num(row.get(f)) for f in fields)
        out[name] = (total / minutes) if per_minute else total
    return out


def row_metrics(player: dict) -> dict:
    """One sidecar player row -> the metric dict, or {} if unusable."""
    return _rates(player, "TIME_PLAYED", METRICS)


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
    return _rates(participant, "timePlayed", MV5_METRICS)


def _finite(value) -> bool:
    """A real, finite number - never a bool, a string or NaN / inf."""
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def build(rows) -> dict:
    """rows = iterable of (role, metric_dict) -> percentile tables per role.

    A metric needs at least 20 samples in a role before it is reported;
    percentiles over a handful of rows are noise with decimal places.

    A malformed entry (not a pair, a role that is not a non-empty string, a
    metric dict that is not a dict) is skipped, and so is a value that is not
    a finite real number: one NaN would otherwise leave sorted() in an
    arbitrary order and every percentile of that metric wrong, and a mixed
    str / int role set would fail the final sort for every role.
    """
    by_role: dict = {}
    for entry in rows:
        if not isinstance(entry, (tuple, list)) or len(entry) != 2:
            continue
        role, metrics = entry
        if not isinstance(role, str) or not role:
            continue
        if not isinstance(metrics, dict) or not metrics:
            continue
        for name, value in metrics.items():
            if not isinstance(name, str) or not _finite(value):
                continue
            by_role.setdefault(role, {}).setdefault(name, []).append(value)

    out = {}
    for role, metrics in sorted(by_role.items()):
        out[role] = {}
        for name, raw_values in sorted(metrics.items()):
            if len(raw_values) < 20:
                continue
            values = sorted(raw_values)
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
    cohort must not be reported as an average one. A table that is not one
    build() could have written (a percentile missing or not a finite number,
    `n` not a positive int) is treated the same way, as is a value that is
    not a finite real number: a NaN fails every comparison and would read as
    the bottom band.
    """
    if not _finite(value) or not isinstance(role, str):
        return None
    if not isinstance(baselines, dict):
        return None
    by_metric = baselines.get(role)
    if not isinstance(by_metric, dict):
        return None
    table = by_metric.get(metric)
    if not _valid_table(table):
        return None
    bands = [(table[f"p{p}"], p) for p in PERCENTILES]
    band, matched = 0, None
    for threshold, pct in bands:
        if value >= threshold:
            band, matched = pct, threshold

    # Tie plateau. A metric most of the cohort scores 0.0 on has every
    # percentile sitting at 0.0, so a 0.0 clears them all and the loop above
    # keeps the HIGHEST - telling a player who healed nobody they are 90th
    # percentile. When the value merely TIES the threshold, credit the lowest
    # percentile sharing it: that band is still literally true, and `tied`
    # tells the renderer the comparison carries little information.
    tied = False
    if matched is not None and value == matched:
        sharing = [pct for threshold, pct in bands if threshold == matched]
        band, tied = min(sharing), len(sharing) > 1

    return {"metric": metric, "role": role, "value": round(value, 3),
            "at_or_above_p": band, "median": table["p50"], "n": table["n"],
            "tied": tied}


def _valid_table(table) -> bool:
    """True for a percentile table of the shape build() writes."""
    if not isinstance(table, dict):
        return False
    n = table.get("n")
    if not isinstance(n, int) or isinstance(n, bool) or n < 1:
        return False
    return all(_finite(table.get(f"p{p}")) for p in PERCENTILES)


def load(path, cohort: str | None = None) -> dict:
    """Per-role tables from either baseline file shape.

    `tools/build_cohort_baseline.py` writes one cohort as {"roles": ...}.
    `tools/build_rank_baselines.py` writes many as {"tiers": {NAME: {"roles":
    ...}}} and needs `cohort` to say which one to compare against.

    A tiers-shaped file with no cohort named RAISES rather than reading empty.
    Returning {} there is indistinguishable from "this cohort has no table",
    so every band is silently omitted and the report looks merely sparse.

    Every refusal is a ValueError - the one exception the caller
    (tools/pgr_event_report.py) catches and reports. That covers bad JSON
    (JSONDecodeError is a ValueError) and a file of the wrong SHAPE: a top
    level, `tiers`, a cohort entry or `roles` that is not an object. A UTF-8
    BOM (a hand edit in a Windows editor) is accepted.
    """
    blob = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(blob, dict):
        raise ValueError(f"{path} is not a JSON object")
    tiers = blob.get("tiers")
    if not tiers:
        return _roles_of(blob, path)
    if not isinstance(tiers, dict):
        raise ValueError(f"{path} 'tiers' is not an object")
    available = ", ".join(sorted(str(k) for k in tiers))
    if not cohort:
        raise ValueError(
            f"{path} holds {len(tiers)} cohorts and none was named - "
            f"pass one of: {available}")
    if cohort not in tiers:
        raise ValueError(f"no cohort {cohort} in {path} - have: {available}")
    entry = tiers[cohort]
    if entry is None:
        return {}
    if not isinstance(entry, dict):
        raise ValueError(f"{path} cohort {cohort} is not an object")
    return _roles_of(entry, f"{path} cohort {cohort}")


def _roles_of(holder: dict, where) -> dict:
    """The `roles` object of a cohort holder; absent or null reads as {}."""
    roles = holder.get("roles")
    if roles is None:
        return {}
    if not isinstance(roles, dict):
        raise ValueError(f"{where} 'roles' is not an object")
    return roles
