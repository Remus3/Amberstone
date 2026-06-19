"""core/player_gpi.py - longitudinal 8-axis player skill profile (GPI radar).

Closes competitor-lift #1 from docs/COMPETITOR_LIFT_2026-06-16.md (the
Aggregator C GPI radar, "best BACKLOG pickup"). RC already grades a SINGLE
match (Post Game Review) and labels per-champion metrics post-game
(core/benchmarks), but nothing aggregates a LONGITUDINAL multi-axis skill
profile across the operator's history. This module builds that profile from
the LOCAL rewind_history.db - no Riot API, no Claude, no DS schema lift.

Scoring is honest and self-relative: RC has no rank-cohort distributions for
arbitrary metrics, so each axis is scored against the operator's OWN history
(the same personal-percentile basis as LBAND1 / core.benchmarks), answering
"how does my recent form rank vs my own typical games". A relative axis is
the mean, over the recent window, of each game's percentile within the full
filtered history; 50 == typical, >50 == an above-baseline streak. Two axes
are window-level shape metrics scored absolutely (Versatility = champion-pool
entropy, Consistency = inverse KDA dispersion).

The 6 relative axes derive only from columns proven present + populated in
the operator participant row (the matches.tracked_kp / tracked_ttmga_t
summary columns are frequently empty strings in the live DB, so they are NOT
used - aggression and tempo come from participant damage + gold instead).

Public API:
    compute_gpi(mode="sr", window=20, champion=None) -> dict   # the contract
    list_champions(mode="sr") -> [{champion_id, n_games}, ...] # drilldown pool
The dict is the /api/player-profile + radar-panel contract; see _empty().
"""
from __future__ import annotations

import bisect
import math
import sqlite3
from typing import Callable, Optional

from core import draft_elo_db

# Rift map ids. The operator plays mostly ARAM (map 12) but SR (map 11) is the
# only mode where all 8 axes are individually meaningful (ARAM has no wards /
# lane CS / neutral objectives in the same sense), so SR is the default; the
# other modes still compute (self-relative) for callers that ask.
MODE_MAPS: dict[str, int] = {"sr": 11, "aram": 12, "arena": 30}

DEFAULT_WINDOW = 20
MIN_GAMES = 10            # below this the percentile baseline is too thin to trust
MIN_DURATION_S = 300      # drop remakes / very-early surrenders

# (key, label, unit, higher_is_better, per-game metric selector)
_RELATIVE_AXES: tuple[tuple[str, str, str, bool, Callable[[dict], float]], ...] = (
    ("aggression", "Aggression", "dmg/min", True, lambda g: g["dpm"]),
    ("farming", "Farming", "cs/min", True, lambda g: g["cspm"]),
    ("vision", "Vision", "vis/min", True, lambda g: g["vspm"]),
    ("objectives", "Objectives", "obj/game", True, lambda g: g["obj"]),
    ("survival", "Survival", "deaths/min", False, lambda g: g["deaths_pm"]),
    ("tempo", "Tempo", "gold/min", True, lambda g: g["gpm"]),
)

# Static improvement tip per relative skill axis (the Aggregator C weakest-axis
# call-out, finding 1.2). Only the 6 relative axes get tips - the two shape axes
# (versatility / consistency) are not skill deficits (a one-trick reads low on
# versatility by choice, not weakness), so they never drive the tip.
_AXIS_TIPS: dict[str, str] = {
    "aggression": "Look for more fights - your damage to champions trails your "
                  "norm; group and trade when your cooldowns are up.",
    "farming": "Farm tighter - your CS per minute is below your baseline; catch "
               "the side waves between objectives.",
    "vision": "Ward more - your vision per minute is low; carry a control ward "
              "and sweep before objectives.",
    "objectives": "Contest objectives - you take fewer dragons / towers than "
                  "usual; rotate with your team on spawns.",
    "survival": "Die less - your deaths per minute are up; respect enemy power "
                "spikes and ward your flanks.",
    "tempo": "Build a lead - your gold per minute is low; punish recalls and "
             "convert kills into plates and CS.",
}


def _empty(mode: str, window: int, n_games: int, champion: Optional[int],
           confidence: str) -> dict:
    return {
        "ok": True,
        "mode": mode,
        "champion": champion,
        "n_games": n_games,
        "window": window,
        "min_games": MIN_GAMES,
        "confidence": confidence,
        "axes": [],
        "overall": None,
        "weakest_axis": None,
        "tip": None,
    }


def _fetch_operator_games(conn: sqlite3.Connection, mode: str,
                          champion: Optional[int]) -> list[dict]:
    """Return the operator's per-game rows newest-first for ``mode``.

    The operator participant row is the one whose (champion_id, team_id)
    matches the match's tracked_* keys. A handful of rows in the live DB
    multi-match that join (sentinel tracked ids), so we dedupe to one row per
    match_id keeping the first (newest) seen.
    """
    map_id = MODE_MAPS.get(mode)
    params: list = []
    where = ["m.has_stats = 1", "m.game_duration_s >= ?"]
    params.append(MIN_DURATION_S)
    if map_id is not None:
        where.append("m.map_id = ?")
        params.append(map_id)
    if champion is not None:
        where.append("p.champion_id = ?")
        params.append(champion)
    sql = (
        "SELECT m.match_id, m.game_duration_s, p.champion_id, "
        "p.total_minions_killed, p.neutral_minions_killed, p.vision_score, "
        "p.gold_earned, p.total_damage_dealt_to_champs, p.deaths, p.kills, "
        "p.assists, p.dragon_kills, p.baron_kills, p.turret_takedowns, "
        "p.inhibitor_takedowns "
        "FROM matches m JOIN participants p ON p.match_id = m.match_id "
        "AND p.champion_id = m.tracked_champion_id "
        "AND p.team_id = m.tracked_team_id "
        "WHERE " + " AND ".join(where) + " "
        "ORDER BY m.game_creation_ts DESC"
    )
    seen: set[str] = set()
    games: list[dict] = []
    for row in conn.execute(sql, params):
        (mid, dur_s, champ, minions, neutral, vis, gold, dmg, deaths, kills,
         assists, drag, baron, turret, inhib) = row
        if mid in seen:
            continue
        seen.add(mid)
        dur_min = max(float(dur_s or 0), 1.0) / 60.0
        games.append({
            "match_id": mid,
            "champion_id": champ,
            "dpm": float(dmg or 0) / dur_min,
            "cspm": float((minions or 0) + (neutral or 0)) / dur_min,
            "vspm": float(vis or 0) / dur_min,
            "obj": float((drag or 0) + (baron or 0) + (turret or 0)
                         + (inhib or 0)),
            "deaths_pm": float(deaths or 0) / dur_min,
            "gpm": float(gold or 0) / dur_min,
            "kda": (float(kills or 0) + float(assists or 0)) / max(1.0,
                                                                   float(deaths or 0)),
        })
    return games


def _percentile(sorted_vals: list[float], x: float) -> float:
    """Midrank percentile of ``x`` within ``sorted_vals`` -> 0..1.

    Averages the strictly-below and at-or-below ranks so a value equal to the
    whole baseline lands at 0.5, not 1.0 (ties do not over-credit).
    """
    n = len(sorted_vals)
    if n == 0:
        return 0.5
    lo = bisect.bisect_left(sorted_vals, x)
    hi = bisect.bisect_right(sorted_vals, x)
    return (lo + hi) / (2.0 * n)


def _median(vals: list[float]) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    n = len(s)
    mid = n // 2
    if n % 2:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2.0


def _relative_axis(spec, games: list[dict], window: int) -> dict:
    key, label, unit, higher, sel = spec
    sign = 1.0 if higher else -1.0
    # Directional baseline (negated for lower-is-better) drives the percentile;
    # the human-readable value + median stay in raw units.
    baseline = sorted(sign * sel(g) for g in games)
    recent = games[:window]
    pcts = [_percentile(baseline, sign * sel(g)) for g in recent]
    score = 100.0 * sum(pcts) / len(pcts) if pcts else 50.0
    recent_raw = [sel(g) for g in recent]
    return {
        "key": key,
        "label": label,
        "unit": unit,
        "scoring": "relative",
        "higher_is_better": higher,
        "score": round(score, 1),
        "recent_value": round(sum(recent_raw) / len(recent_raw), 2) if recent_raw else 0.0,
        "baseline_p50": round(_median([sel(g) for g in games]), 2),
        "sample_n": len(recent),
    }


def _versatility_axis(games: list[dict], window: int) -> dict:
    """Champion-pool diversity over the recent window via normalized Shannon
    entropy. 1 champion -> 0; an even spread across N distinct champs over N
    games -> 100. A one-trick reads low, a flex-everything player reads high.
    """
    recent = games[:window]
    n = len(recent)
    counts: dict[int, int] = {}
    for g in recent:
        counts[g["champion_id"]] = counts.get(g["champion_id"], 0) + 1
    if n <= 1:
        score = 0.0
    else:
        ent = -sum((c / n) * math.log(c / n) for c in counts.values())
        score = 100.0 * ent / math.log(n)   # log(n) == max entropy (all distinct)
    return {
        "key": "versatility",
        "label": "Versatility",
        "unit": "champ pool",
        "scoring": "absolute",
        "higher_is_better": True,
        "score": round(min(100.0, max(0.0, score)), 1),
        "recent_value": len(counts),
        "baseline_p50": None,
        "sample_n": n,
    }


def _consistency_axis(games: list[dict], window: int) -> dict:
    """Inverse KDA dispersion over the recent window. Steady KDA game to game
    reads high; boom-or-bust reads low. score = 100*(1 - clamp(cv,0,1)) where
    cv = stdev(kda)/mean(kda).
    """
    recent = games[:window]
    kdas = [g["kda"] for g in recent]
    n = len(kdas)
    if n <= 1:
        score = 50.0
        cv = 0.0
    else:
        mean = sum(kdas) / n
        if mean <= 0:
            cv = 1.0
        else:
            var = sum((k - mean) ** 2 for k in kdas) / n
            cv = math.sqrt(var) / mean
        score = 100.0 * (1.0 - min(1.0, max(0.0, cv)))
    return {
        "key": "consistency",
        "label": "Consistency",
        "unit": "KDA cv",
        "scoring": "absolute",
        "higher_is_better": True,
        "score": round(score, 1),
        "recent_value": round(cv, 2),
        "baseline_p50": None,
        "sample_n": n,
    }


def compute_gpi(mode: str = "sr", window: int = DEFAULT_WINDOW,
                champion: Optional[int] = None,
                conn: Optional[sqlite3.Connection] = None) -> dict:
    """Build the 8-axis GPI profile. The returned dict is the API/panel
    contract. Never raises on empty/thin history - returns an ok payload with
    ``confidence`` in {high, low, insufficient} and an empty ``axes`` when
    below MIN_GAMES.
    """
    if mode not in MODE_MAPS:
        mode = "sr"
    window = max(1, int(window))
    own = conn is None
    if own:
        conn = draft_elo_db.open_ro()
    try:
        games = _fetch_operator_games(conn, mode, champion)
    finally:
        if own:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass

    n_games = len(games)
    if n_games < MIN_GAMES:
        return _empty(mode, window, n_games, champion, "insufficient")

    axes = [_relative_axis(spec, games, window) for spec in _RELATIVE_AXES]
    axes.append(_versatility_axis(games, window))
    axes.append(_consistency_axis(games, window))

    overall = round(sum(a["score"] for a in axes) / len(axes), 1)
    eff_window = min(window, n_games)
    confidence = "high" if eff_window >= 10 else "low"
    out = _empty(mode, window, n_games, champion, confidence)
    out["axes"] = axes
    out["overall"] = overall

    # Weakest-axis call-out drives the single improvement tip. Only the relative
    # skill axes are eligible (see _AXIS_TIPS); ties break on axis order.
    tip_axes = [a for a in axes if a["key"] in _AXIS_TIPS]
    weakest = min(tip_axes, key=lambda a: a["score"]) if tip_axes else None
    out["weakest_axis"] = weakest["key"] if weakest else None
    out["tip"] = _AXIS_TIPS.get(weakest["key"]) if weakest else None
    return out


def list_champions(mode: str = "sr",
                   conn: Optional[sqlite3.Connection] = None) -> list[dict]:
    """Return the operator's played champions for ``mode`` as
    ``[{"champion_id": int, "n_games": int}, ...]`` ordered by games desc.

    Powers the GPI per-champion drilldown selector. Reuses the SAME operator-row
    JOIN + has_stats / MIN_DURATION_S / map_id filter as ``_fetch_operator_games``
    grouped by champion; COUNT(DISTINCT match_id) mirrors that function's
    per-match dedupe (sentinel tracked ids can multi-match). Never raises on
    empty/missing history - returns ``[]``.
    """
    if mode not in MODE_MAPS:
        mode = "sr"
    map_id = MODE_MAPS.get(mode)
    where = ["m.has_stats = 1", "m.game_duration_s >= ?"]
    params: list = [MIN_DURATION_S]
    if map_id is not None:
        where.append("m.map_id = ?")
        params.append(map_id)
    sql = (
        "SELECT p.champion_id, COUNT(DISTINCT m.match_id) AS n "
        "FROM matches m JOIN participants p ON p.match_id = m.match_id "
        "AND p.champion_id = m.tracked_champion_id "
        "AND p.team_id = m.tracked_team_id "
        "WHERE " + " AND ".join(where) + " "
        "GROUP BY p.champion_id ORDER BY n DESC, p.champion_id ASC"
    )
    own = conn is None
    if own:
        conn = draft_elo_db.open_ro()
    try:
        rows = list(conn.execute(sql, params))
    finally:
        if own:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
    return [{"champion_id": int(cid), "n_games": int(n)}
            for cid, n in rows if cid is not None]
