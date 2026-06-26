# core/ds_capability_gap.py | section=core | frozen=no
"""Multi-axis composition-gap synthesizer (L4 Phase-D consumer).

Pure read-only consumer of the existing DS capability scorers. Given the local
player's champion and the live enemy composition, it finds the single highest-
severity CAPABILITY DEFICIT the operator's pick has versus the enemy comp's
demand, and emits one prioritized coaching verdict.

This generalizes the proven single-axis ``core.ds_antitank_hint`` pattern into
the "which capability is my comp missing" synthesis the DS scorers were built
toward but no surface yet produces (the ``Phase-D consumer`` the scorer
docstrings defer - see antitank.py / threatrange.py / cc_output.py).

Design - a registry of gap DETECTORS. Each detector reads one capability axis,
pairing the operator's own score on that axis against an enemy-demand signal,
and returns either ``None`` (the axis does not qualify) or a gap dict:

    {"axis": str, "demand_count": int, "severity": float, "detail": str}

``severity`` is the cross-axis ranking key (v1: the number of enemies driving
the demand, so "more enemies forcing the issue" ranks higher). Detectors gate on
the scorers' own calibrated thresholds / boolean identity flags, so NO new
per-axis threshold needs calibrating here. Adding an axis = append a detector.

No engine math change, no ENGINE_VERSION bump, no served-path edit: this module
is inert until a caller wires it (the section-5 "default inert" contract). Every
public path is deterministic and never raises.
"""
from __future__ import annotations

import logging

_log = logging.getLogger("rc.ds_capability_gap")

# --- Tunable constants -------------------------------------------------------

# Minimum number of enemy artillery/siege threats before the poke gap fires.
# Mirrors ds_antitank_hint.HIGH_HP_ENEMY_MIN: below this the comp is not
# "poke-heavy" enough to warrant a siege-respect call-out.
POKE_ENEMY_MIN: int = 2

# Sustain gap: a heavy-sustain enemy is one whose SustainResult.total_sustain_score
# clears SUSTAIN_HIGH_SCORE, and the gap fires only when at least
# SUSTAIN_ENEMY_MIN of them are present. The score cut (1.5) is grounded against
# live compute_sustain output (probed 2026-06-26): it cleanly separates the
# drain/lifesteal bruisers + mages (Warwick 11.67 / Aatrox 6.99 / Swain 3.29 /
# Fiddlesticks 2.93 / Vladimir 1.60) from everyone else (DrMundo 0.60 and below).
SUSTAIN_ENEMY_MIN: int = 2
SUSTAIN_HIGH_SCORE: float = 1.5

# Axis priority order. Used as the stable tie-break when two gaps share the same
# severity (the earlier axis is the more itemization-direct, actionable call):
# anti-tank and anti-heal are both direct item buys, ahead of the positional
# poke call.
_AXIS_PRIORITY: tuple[str, ...] = ("anti_tank", "sustain", "poke")


# --- gap detectors -----------------------------------------------------------

def _detect_antitank_gap(my_champion: str, enemy_champions: list[str], mode: str) -> dict | None:
    """Anti-tank deficit: enemy comp is tanky AND my kit does not already shred.

    Delegates to the proven ``build_antitank_hint`` consumer rather than
    re-deriving the score/archetype logic."""
    from core.ds_antitank_hint import build_antitank_hint

    hint = build_antitank_hint(my_champion, enemy_champions, mode)
    if not hint.get("recommend_antitank_items"):
        return None
    demand = int(hint.get("tanky_enemy_count", 0))
    detail = hint.get("hint") or (
        f"Enemy comp tanky ({demand}); itemize anti-tank (%max-HP / armor pen)."
    )
    return {
        "axis": "anti_tank",
        "demand_count": demand,
        "severity": float(demand),
        "detail": detail,
    }


def _detect_poke_gap(my_champion: str, enemy_champions: list[str], mode: str) -> dict | None:
    """Poke/siege deficit: enemy fields >=POKE_ENEMY_MIN artillery threats AND I
    cannot poke back (my own kit is not artillery), so the enemy out-ranges me.

    Keys on ``ThreatRangeResult.is_artillery`` - the long-siege identity flag the
    threatrange scorer explicitly exposes for a poke consumer."""
    from agents.daemon_slayer.threatrange import compute_threatrange

    artillery = 0
    for champ in enemy_champions:
        try:
            if compute_threatrange(champ, mode).is_artillery:
                artillery += 1
        except Exception:  # noqa: BLE001 - never break the synthesis on one champ
            _log.debug("ds_capability_gap: compute_threatrange(%r) raised - skipping", champ)
    if artillery < POKE_ENEMY_MIN:
        return None
    # If my own kit is artillery I can trade poke for poke - no deficit.
    try:
        if compute_threatrange(my_champion, mode).is_artillery:
            return None
    except Exception:  # noqa: BLE001
        _log.debug("ds_capability_gap: compute_threatrange(self=%r) raised", my_champion)
        return None
    detail = (
        f"Enemy out-ranges you ({artillery} artillery); close distance, "
        "dodge poke, force the engage."
    )
    return {
        "axis": "poke",
        "demand_count": artillery,
        "severity": float(artillery),
        "detail": detail,
    }


def _detect_sustain_gap(my_champion: str, enemy_champions: list[str], mode: str) -> dict | None:
    """Sustain deficit: enemy comp fields >=SUSTAIN_ENEMY_MIN heavy-sustain
    threats AND my own kit does not out-sustain in kind, so they out-heal my
    trades and I need anti-heal (Grievous Wounds).

    Keys on ``SustainResult.total_sustain_score`` against ``SUSTAIN_HIGH_SCORE``
    - the calibrated cut the sustain scorer's total exposes for a consumer."""
    from agents.daemon_slayer.sustain import compute_sustain

    heavy = 0
    for champ in enemy_champions:
        try:
            if compute_sustain(champ, mode).total_sustain_score >= SUSTAIN_HIGH_SCORE:
                heavy += 1
        except Exception:  # noqa: BLE001 - never break the synthesis on one champ
            _log.debug("ds_capability_gap: compute_sustain(%r) raised - skipping", champ)
    if heavy < SUSTAIN_ENEMY_MIN:
        return None
    # If my own kit out-sustains in kind I can trade heal-for-heal - no deficit.
    try:
        if compute_sustain(my_champion, mode).total_sustain_score >= SUSTAIN_HIGH_SCORE:
            return None
    except Exception:  # noqa: BLE001
        _log.debug("ds_capability_gap: compute_sustain(self=%r) raised", my_champion)
        return None
    detail = (
        f"Enemy comp out-sustains you ({heavy} heavy-sustain); itemize anti-heal "
        "(Grievous Wounds)."
    )
    return {
        "axis": "sustain",
        "demand_count": heavy,
        "severity": float(heavy),
        "detail": detail,
    }


# Registry of detectors, in _AXIS_PRIORITY order. Append a detector to extend
# the synthesis to another capability axis.
_DETECTORS = (_detect_antitank_gap, _detect_sustain_gap, _detect_poke_gap)


# --- ranking -----------------------------------------------------------------

def _rank_gaps(gaps: list[dict]) -> list[dict]:
    """Sort gaps by severity desc, tie-broken by _AXIS_PRIORITY order."""
    def _key(g: dict):
        axis = g.get("axis", "")
        try:
            prio = _AXIS_PRIORITY.index(axis)
        except ValueError:
            prio = len(_AXIS_PRIORITY)
        return (-float(g.get("severity", 0.0)), prio)

    return sorted(gaps, key=_key)


# --- public API --------------------------------------------------------------

def build_capability_gap(
    my_champion: str,
    enemy_champions: list[str] | None,
    mode: str = "SR",
) -> dict:
    """Return the prioritized capability-gap verdict for a match-up.

    Parameters
    ----------
    my_champion:
        DDragon champion id for the local player. Blank/None -> applies=False.
    enemy_champions:
        DDragon champion ids for the enemies. None -> []. Blank entries skipped.
    mode:
        Game mode string passed through to the scorers (default "SR").

    Returns
    -------
    dict with keys:
        applies (bool)      - True when at least one gap fired.
        my_champion (str)
        mode (str)
        top_gap (str)       - axis key of the highest-severity gap ("" if none).
        verdict (str)       - coaching string for the top gap (ASCII, "" if none).
        gaps (list[dict])   - all fired gaps, sorted by severity desc. Each:
                              {axis, demand_count, severity, detail}.
    """
    safe_champion = (my_champion or "").strip()
    safe_mode = mode if mode else "SR"
    if not safe_champion:
        return _zero_result("", safe_mode)

    if enemy_champions is None:
        enemy_champions = []
    safe_enemies = [(c or "").strip() for c in enemy_champions if (c or "").strip()]

    gaps: list[dict] = []
    for detector in _DETECTORS:
        try:
            gap = detector(safe_champion, safe_enemies, safe_mode)
        except Exception:  # noqa: BLE001 - one bad axis never breaks the rest
            _log.debug("ds_capability_gap: detector %s raised", getattr(detector, "__name__", "?"))
            gap = None
        if gap is not None:
            gaps.append(gap)

    if not gaps:
        return _zero_result(safe_champion, safe_mode)

    ranked = _rank_gaps(gaps)
    top = ranked[0]
    return {
        "applies": True,
        "my_champion": safe_champion,
        "mode": safe_mode,
        "top_gap": top["axis"],
        "verdict": top["detail"],
        "gaps": ranked,
    }


def _zero_result(champion: str, mode: str) -> dict:
    """All-empty result for a blank champion or a no-gap match-up."""
    return {
        "applies": False,
        "my_champion": champion,
        "mode": mode if mode else "SR",
        "top_gap": "",
        "verdict": "",
        "gaps": [],
    }


__all__ = [
    "build_capability_gap",
    "POKE_ENEMY_MIN",
    "SUSTAIN_ENEMY_MIN",
    "SUSTAIN_HIGH_SCORE",
]
