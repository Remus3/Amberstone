"""Scaling power-curve coach hint generator.

Pure read-only consumer of agents.daemon_slayer.scaling.compute_scaling.
Produces a deterministic dict summarising the curve mismatch between
my_champion and a set of enemies, with a human-readable coaching hint.

No imports from any other RC module; no side-effects; never raises.

Input contract (hardened S144-T true-audit cycle 157). The caller is the live
coach shadow path (``coaches/_base_coach.py`` -> ``core/ds_coach_shadow.py``),
which feeds Live Client names bridged to DDragon ids, so junk is expected:

- A champion id that is not a ``str`` reads as blank; a ``str`` id is stripped.
- ``enemy_champions`` is a list or tuple of ids; a bare ``str`` is ONE enemy
  (never iterated into its letters); any other container reads as no enemies.
  A non-``str`` or blank entry is skipped.
- ``mode`` that is not a non-blank ``str`` falls back to "SR"; it is stripped.
- ``game_time_s`` must be a finite, non-negative real number (``bool`` is not
  a number here); anything else is an unknown stage "".

Verdict contract. A champion absent from the DS scaling registry has NO curve
(compute_scaling returns empty ``sources``); that is "unknown", never "zero
scaling". So an unknown my_champion, or a comparison set with no known enemy,
is verdict "even" - never an "outscale" against nobody ("late 0.76 vs 0.00")
or a "falloff" from a registry miss ("late 0.00 vs 0.89"). Unknown enemies are
excluded from the enemy averages and counted in ``enemy_unknown``.
"""

from __future__ import annotations

import math

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

DEFAULT_MODE: str = "SR"

EVEN_HINT: str = "Even power curve; win on tempo and lane state."


def _clean_id(value: object) -> str:
    """A stripped champion id, or "" for a non-``str`` / blank value."""
    return value.strip() if isinstance(value, str) else ""


def _clean_mode(value: object) -> str:
    cleaned = value.strip() if isinstance(value, str) else ""
    return cleaned or DEFAULT_MODE


def _clean_enemies(value: object) -> list[str]:
    """Non-blank stripped ids from a list / tuple; a bare ``str`` is one id."""
    if isinstance(value, str):
        items: tuple | list = (value,)
    elif isinstance(value, (list, tuple)):
        items = value
    else:
        return []
    return [cid for cid in (_clean_id(e) for e in items) if cid]


def _stage(game_time_s: object) -> str:
    """Map raw game time in seconds to a stage label.

    Returns "" when game_time_s is None (not yet in-game or not provided) or
    is not a finite, non-negative real number.
    """
    if isinstance(game_time_s, bool) or not isinstance(game_time_s, (int, float)):
        return ""
    # Compare the value itself: float() of a huge int raises OverflowError.
    if isinstance(game_time_s, float) and not math.isfinite(game_time_s):
        return ""
    if game_time_s < 0:
        return ""
    if game_time_s < EARLY_MAX_S:
        return "EARLY"
    if game_time_s < MID_MAX_S:
        return "MID"
    return "LATE"


def build_scaling_hint(
    my_champion: str,
    enemy_champions: list[str] | None,
    mode: str = DEFAULT_MODE,
    game_time_s: float | None = None,
) -> dict:
    """Build a scaling power-curve coaching hint for one champion vs enemies.

    Parameters
    ----------
    my_champion:
        Canonical DS champion id (e.g. "Kayle", "Vayne").
        Blank, None or non-str -> all-zero, verdict "even".
    enemy_champions:
        List or tuple of canonical DS champion ids. None treated as [].
        Blank and non-str entries are skipped.
    mode:
        Game mode string forwarded to compute_scaling (e.g. "SR", "ARAM").
    game_time_s:
        Elapsed game time in seconds. None or invalid -> stage "".

    Returns
    -------
    dict with keys:
        my_champion (str), mode (str),
        my_early (float r4), my_mid (float r4), my_late (float r4),
        my_slope (float r4), scaling_score (float r4),
        enemy_count (int, enemies with a known curve),
        enemy_unknown (int, enemies absent from the scaling registry),
        enemy_avg_late (float r4), enemy_avg_slope (float r4),
        stage (str), verdict (str), hint (str).
    Never raises.
    """
    safe_mode = _clean_mode(mode)
    my_id = _clean_id(my_champion)
    enemies = _clean_enemies(enemy_champions)

    my = compute_scaling(my_id, safe_mode)

    enemy_results = [compute_scaling(e, safe_mode) for e in enemies]
    known = [r for r in enemy_results if r.sources]
    enemy_count = len(known)
    enemy_unknown = len(enemy_results) - enemy_count

    if enemy_count:
        enemy_avg_late = sum(r.late_power for r in known) / enemy_count
        enemy_avg_slope = sum(r.scaling_slope for r in known) / enemy_count
    else:
        enemy_avg_late = 0.0
        enemy_avg_slope = 0.0

    # No curve on either side (blank / unknown champion, or no known enemy)
    # means there is nothing to compare: "even", never a decisive verdict.
    if not my.sources or not enemy_count:
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
        hint = EVEN_HINT

    return {
        "my_champion": my_id,
        "mode": safe_mode,
        "my_early": round(my.early_power, 4),
        "my_mid": round(my.mid_power, 4),
        "my_late": round(my.late_power, 4),
        "my_slope": round(my.scaling_slope, 4),
        "scaling_score": round(my.scaling_score, 4),
        "enemy_count": enemy_count,
        "enemy_unknown": enemy_unknown,
        "enemy_avg_late": round(enemy_avg_late, 4),
        "enemy_avg_slope": round(enemy_avg_slope, 4),
        "stage": _stage(game_time_s),
        "verdict": verdict,
        "hint": hint,
    }
