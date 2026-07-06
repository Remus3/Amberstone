# arch: archetype capability-weight multiplier for ZOI influence bubbles | section=core | frozen=no
"""Archetype capability weight for the ZOI influence layer (spec F, wave 3b).

``capability_weight(champion, level, game_time_s)`` returns a pure float
multiplier in a documented band that scales an influence bubble's radius by how
much on-map presence that champion's archetype actually converts into map
pressure at the current game state. It is the capability source Phase-3 folds
into ``core.zoi_influence.compute_zoi`` per-dot radius when a roster is provided.

WHY archetype-relative scaling:
  The Live Client API exposes only MY level / gold / game_time (mirror
  core/zoi_influence.py:15-23) - never enemy power. So bubble strength cannot
  be grounded in real gold. What we DO know per champion is its archetype (from
  core.archetype_picks.get_archetype_for), and archetypes have well-understood
  power curves: an assassin or hyper-carry is weak early and snowballs late; a
  tank or enchanter is comparatively strong early (frontloaded utility / peel)
  and flattens as carries out-scale it. Weighting presence by that curve makes
  the DMZ frontier lean toward the team whose composition actually owns the map
  at this minute, which is a better macro read than raw presence.

DESIGN:
  - 100% PURE + stateless: no I/O beyond the archetype lookup (which is cached
    per-process in core.archetype_picks). NEVER raises - any bad input
    (unknown / None / non-string champ, NaN/inf/bool level or time) fails soft
    to the NEUTRAL 1.0 (or a clamped in-band value), never an exception.
  - Output band: [CAP_MIN, CAP_MAX] = [0.6, 1.6]. Documented + test-enforced.
  - Unknown champ / None / garbage -> exactly 1.0 (neutral).

CURVE TABLE (documented constants below):
  Each archetype has a (base, time_gain, level_gain) triple. The weight is:
      w = base + time_gain * T + level_gain * L
  where T in [0,1] is game_time saturated at _TIME_FULL_S (20 min) and L in
  [0,1] is level saturated at _LEVEL_FULL (18). A negative gain frontloads
  (tanks / enchanters lose relative weight over time); a positive gain scales up
  (assassins / carries gain). The final value is clamped to the band.

ASCII only (repo hard rule). No em-dashes.
"""
from __future__ import annotations

from core.archetype_picks import (
    _load_champion_tags,
    get_archetype_for,
)

# --- band (documented, test-enforced) -------------------------------------
CAP_MIN = 0.6
CAP_MAX = 1.6
CAP_NEUTRAL = 1.0

# --- saturation points ----------------------------------------------------
_TIME_FULL_S = 1200.0   # game_time at which the time term saturates to 1.0
_LEVEL_FULL = 18.0      # champion level at which the level term saturates

# --- archetype curve table -------------------------------------------------
# (base, time_gain, level_gain). Interpreted at T=0,L=0 the weight == base;
# at full time + full level it == base + time_gain + level_gain (then clamped).
#
#   assassin / carry  -> low base, POSITIVE gains (snowball / hyper-scale)
#   mage              -> mild positive (scales, but less explosively)
#   bruiser           -> near-flat, slight positive (steady curve)
#   tank / enchanter  -> high base, NEGATIVE gains (frontloaded, flatten late)
#
# Chosen so every archetype stays inside [0.6, 1.6] across the full T,L sweep.
_ARCHETYPE_CURVE: dict[str, tuple[float, float, float]] = {
    "assassin":  (0.78, 0.34, 0.14),
    "carry":     (0.80, 0.32, 0.12),
    "mage":      (0.90, 0.18, 0.08),
    "bruiser":   (0.98, 0.08, 0.06),
    "tank":      (1.24, -0.26, -0.06),
    "enchanter": (1.20, -0.24, -0.06),
}


def _num(v):
    """Coerce to a finite float, or None if not a real number (bools rejected)."""
    if isinstance(v, bool):
        return None
    if not isinstance(v, (int, float)):
        return None
    f = float(v)
    if f != f or f in (float("inf"), float("-inf")):  # NaN / inf
        return None
    return f


def _clamp(v, lo, hi):
    if v < lo:
        return lo
    if v > hi:
        return hi
    return v


def _time_scalar(game_time_s) -> float:
    """game_time normalized to [0,1], saturating at _TIME_FULL_S. 0.0 on bad."""
    t = _num(game_time_s)
    if t is None or t <= 0.0:
        return 0.0
    return _clamp(t / _TIME_FULL_S, 0.0, 1.0)


def _level_scalar(level) -> float:
    """champion level normalized to [0,1], saturating at _LEVEL_FULL. 0.0 on bad."""
    lv = _num(level)
    if lv is None or lv <= 1.0:
        return 0.0
    return _clamp((lv - 1.0) / (_LEVEL_FULL - 1.0), 0.0, 1.0)


def _is_known_champion(champion: str) -> bool:
    """True only when `champion` is a REAL champion (has DDragon tags).

    get_archetype_for defaults an UNKNOWN champion to carry, so it cannot tell a
    real champ from a typo. The DDragon tags map (keyed by every champion
    name-form) is the oracle: a name absent from it is not a champion, so its
    capability is neutral 1.0, not a spurious carry curve."""
    try:
        tags = _load_champion_tags()
    except Exception:  # noqa: BLE001 - pure fail-soft
        return False
    if not isinstance(tags, dict):
        return False
    return bool(tags.get(champion))


def archetype_of(champion) -> str | None:
    """Resolve a champion's primary archetype, or None when it cannot be known.

    Fail-soft: only a non-empty string that names a REAL champion is resolved.
    A None / empty / non-string / unknown name -> None -> neutral weight
    upstream (spec: unknown champ -> 1.0)."""
    if not isinstance(champion, str) or not champion.strip():
        return None
    if not _is_known_champion(champion):
        return None
    try:
        info = get_archetype_for(champion)
    except Exception:  # noqa: BLE001 - pure fail-soft
        return None
    if not isinstance(info, dict):
        return None
    primary = info.get("primary")
    if primary in _ARCHETYPE_CURVE:
        return primary
    return None


def capability_weight(champion, level=None, game_time_s=None) -> float:
    """Capability multiplier for one champion at the current game state.

    Returns a finite float in [CAP_MIN, CAP_MAX]. Unknown / None / garbage
    champion -> exactly 1.0 (neutral). Never raises.
    """
    arch = archetype_of(champion)
    if arch is None:
        return CAP_NEUTRAL
    base, time_gain, level_gain = _ARCHETYPE_CURVE[arch]
    T = _time_scalar(game_time_s)
    L = _level_scalar(level)
    w = base + time_gain * T + level_gain * L
    return float(_clamp(w, CAP_MIN, CAP_MAX))


def team_mean_weight(roster, level=None, game_time_s=None) -> float:
    """Mean capability weight over a roster of champion names.

    Used when per-dot identity is unavailable (dot_champions=False): the whole
    team's dots share the roster-mean capability. Fail-soft: garbage / empty
    roster -> 1.0 (neutral). Only entries that resolve to a known archetype
    contribute; if none resolve, returns 1.0.
    """
    if not roster or not isinstance(roster, (list, tuple)):
        return CAP_NEUTRAL
    weights = []
    for champ in roster:
        arch = archetype_of(champ)
        if arch is not None:
            weights.append(capability_weight(champ, level=level, game_time_s=game_time_s))
    if not weights:
        return CAP_NEUTRAL
    return float(sum(weights) / len(weights))
