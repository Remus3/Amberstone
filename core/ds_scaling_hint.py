"""Scaling power-curve coach hint generator.

Pure read-only consumer of agents.daemon_slayer.scaling.compute_scaling.
Produces a deterministic dict summarising the curve mismatch between
my_champion and a set of enemies, with a human-readable coaching hint.

No imports from any other RC module; no side-effects; never raises.
"""

from __future__ import annotations

from agents.daemon_slayer.scaling import compute_scaling

# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------

# Games are typically considered "early" up to roughly 14 minutes (840 s).
EARLY_MAX_S: float = 840.0

# "Mid game" transition ends around 25 minutes (1500 s); beyond = late.
MID_MAX_S: float = 1500.0

# Minimum late-power delta to call a decisive curve mismatch rather than "even".
# Smaller gaps are noise given the hand-authored magnitude model.
SCALING_MARGIN: float = 0.4


def _stage(game_time_s: float | None) -> str:
    """Map raw game time in seconds to a stage label.

    Returns "" when game_time_s is None (not yet in-game or not provided).
    """
    if game_time_s is None:
        return ""
    if game_time_s < EARLY_MAX_S:
        return "EARLY"
    if game_time_s < MID_MAX_S:
        return "MID"
    return "LATE"


def build_scaling_hint(
    my_champion: str,
    enemy_champions: list[str] | None,
    mode: str = "SR",
    game_time_s: float | None = None,
) -> dict:
    """Build a scaling power-curve coaching hint for one champion vs enemies.

    Parameters
    ----------
    my_champion:
        Canonical DS champion id (e.g. "Kayle", "Vayne").
        Blank or None -> all-zero, verdict "even".
    enemy_champions:
        List of canonical DS champion ids. None treated as [].
        Blank entries are skipped.
    mode:
        Game mode string forwarded to compute_scaling (e.g. "SR", "ARAM").
    game_time_s:
        Elapsed game time in seconds. None -> stage "".

    Returns
    -------
    dict with keys:
        my_champion (str), mode (str),
        my_early (float r4), my_mid (float r4), my_late (float r4),
        my_slope (float r4), scaling_score (float r4),
        enemy_count (int), enemy_avg_late (float r4), enemy_avg_slope (float r4),
        stage (str), verdict (str), hint (str).
    Never raises.
    """
    safe_mode = mode if mode else "SR"
    enemies: list[str] = [e for e in (enemy_champions or []) if e and e.strip()]

    # my champion curve
    my = compute_scaling(my_champion or "", safe_mode)

    # enemy curves - filter to non-blank entries only
    enemy_results = [compute_scaling(e, safe_mode) for e in enemies]
    enemy_count = len(enemy_results)

    if enemy_count:
        enemy_avg_late = sum(r.late_power for r in enemy_results) / enemy_count
        enemy_avg_slope = sum(r.scaling_slope for r in enemy_results) / enemy_count
    else:
        enemy_avg_late = 0.0
        enemy_avg_slope = 0.0

    # verdict - blank champion has all-zero curve, force "even" per spec
    if not (my_champion or "").strip():
        verdict = "even"
    elif (
        (my.late_power - enemy_avg_late) > SCALING_MARGIN
        and my.scaling_slope >= enemy_avg_slope
    ):
        verdict = "outscale"
    elif (
        (enemy_avg_late - my.late_power) > SCALING_MARGIN
        and my.scaling_slope <= enemy_avg_slope
    ):
        verdict = "falloff"
    else:
        verdict = "even"

    # hint (ASCII only)
    if verdict == "outscale":
        hint = (
            f"You outscale (late {my.late_power:.2f} vs {enemy_avg_late:.2f});"
            " play safe, scale, fight late."
        )
    elif verdict == "falloff":
        hint = (
            f"You fall off late ({my.late_power:.2f} vs {enemy_avg_late:.2f});"
            " force tempo/objectives early, avoid late 5v5."
        )
    else:
        hint = "Even power curve; win on tempo and lane state."

    return {
        "my_champion": my_champion or "",
        "mode": safe_mode,
        "my_early": round(my.early_power, 4),
        "my_mid": round(my.mid_power, 4),
        "my_late": round(my.late_power, 4),
        "my_slope": round(my.scaling_slope, 4),
        "scaling_score": round(my.scaling_score, 4),
        "enemy_count": enemy_count,
        "enemy_avg_late": round(enemy_avg_late, 4),
        "enemy_avg_slope": round(enemy_avg_slope, 4),
        "stage": _stage(game_time_s),
        "verdict": verdict,
        "hint": hint,
    }
