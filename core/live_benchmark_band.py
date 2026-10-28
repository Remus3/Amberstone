"""Live personal-percentile benchmark banding for in-game coaching.

Bands a player's LIVE in-game metric (current CS, current level) against that
player's OWN historical percentile distribution on the SAME champion, read from
``core.benchmarks`` (data/coach_reference/champion_benchmarks.json). Returns
short, ASCII, fail-soft coach lines like "CS at 10: top quartile on Tristana."

WHY this exists: the live macro coach (core.lead_projection) bands live CS / gold
/ level against a FLAT heuristic curve (a fixed ~8 cs/min "average solo laner"
benchmark). That is mode-agnostic and player-agnostic. RC already computes a
RICHER per-champion personal percentile distribution from the player's own match
history, but it is consumed ONLY post-game (core.aftergame_summary). This module
is the missing LIVE half: at a checkpoint moment (~10:00 / ~15:00 game time) it
asks "how does your live value compare to YOUR OWN distribution on this champion"
- a personal-percentile read, not a flat average. It is a deterministic precompute
substrate (charter 4b PRIMARY: deterministic coaching off live Haiku); a pure
generator with no live-coach consumer yet (mirrors how core.lead_projection /
core.laning_verdicts first shipped). A later wave wires it into the state builder
/ overlay. Nothing here touches the network, an LLM, or the DS engine.

SCOPE (correct-by-construction, deliberately narrow):
  - SR family ONLY. champion_benchmarks.json carries sr / sr_ranked / sr_flex
    modes only (no ARAM / Arena personal benchmarks). A non-SR mode -> no bands.
  - cs + level ONLY. These two live fields map cleanly onto the benchmark
    semantics (cumulative CS, champion level). Gold is EXCLUDED on purpose: the
    live gold signal is ON-HAND (post-buy) gold, while the gold_at_N benchmark is
    a total / at-frame figure, so banding them would compare apples to oranges
    (this is the same reason lead_projection down-weights its gold axis). XP is
    excluded because raw XP is not a reliable live field.
  - Checkpoint-gated. cs_at_10 / level_at_10 only band when game time is within a
    tolerance window of 10:00; cs_at_15 only near 15:00. Off-checkpoint -> no
    bands (a mid-window value is not comparable to an at-checkpoint distribution).
  - >= 5 games gate. Mirrors core.aftergame_summary's trust gate - a distribution
    backed by < 5 of the player's games is too thin to coach against.

INPUT VOCABULARY (s144 true-audit): every number is an int or float, never a
bool or a str, and finite. Game time is 0..10**6 s, cs 0..10**5 and level 1..30
(the sibling vocabularies of dashboard/_adaptation_latch and
core/build_planner/fed_threat); anything else is no reading for that metric. The
champion is a str, stripped, 1..64 chars. A junk tolerance_s / min_games keeps
its default, and a distribution whose p25 / p50 / p75 are not finite ordered
numbers is no band.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional

from core import benchmarks
from core.archetype_picks import canonical_champion_id

# SR benchmark-mode keys, most-specific first. A coarse "SR" live mode resolves
# to the first family member that clears the games gate (a ranked game prefers
# the ranked distribution, then normals, then flex).
_SR_MODE_PRIORITY = ("sr_ranked", "sr", "sr_flex")

# Checkpoint windows: (center_seconds, label, (metric_key, ...)). Only metrics
# whose live field matches the benchmark semantics are listed (see SCOPE).
_CHECKPOINTS = (
    (600.0, "10", ("cs_at_10", "level_at_10")),
    (900.0, "15", ("cs_at_15",)),
)

# How far from a checkpoint center a live value is still treated as "at" it.
_TOLERANCE_S = 45.0
# A caller tolerance must stay under half the 300 s gap between the checkpoint
# centers, so one clock never sits in both windows (an inf tolerance used to band
# cs at 33:20 as both cs_at_10 and cs_at_15).
_MAX_TOLERANCE_S = 150.0

# Minimum personal games behind a distribution before it is trustworthy to band
# against. Matches core.aftergame_summary.have_benchmarks (>= 5).
_MIN_GAMES = 5
_MAX_MIN_GAMES = 10 ** 6

# Plausibility bounds for the live readings (see INPUT VOCABULARY).
_MAX_GAME_TIME_S = 10 ** 6
_MAX_CHAMPION_LEN = 64
# live field -> (lo, hi) inclusive.
_LIVE_BOUNDS = {
    "cs": (0, 10 ** 5),
    "level": (1, 30),
}

# metric_key -> the live game_state field it bands.
_METRIC_LIVE_FIELD = {
    "cs_at_10": "cs",
    "cs_at_15": "cs",
    "level_at_10": "level",
}
# metric_key -> short display noun for the coach line.
_METRIC_DISPLAY = {
    "cs_at_10": "CS",
    "cs_at_15": "CS",
    "level_at_10": "Level",
}

_SOURCE_TAG = "live-bench"


def _finite(val, lo, hi) -> Optional[float]:
    """``val`` as a float when it is an int / float (not a bool) that is finite
    and inside ``lo..hi``; else None. Bounds are checked BEFORE float() so a
    >1e308 int is refused instead of raising OverflowError, and the range check
    alone refuses NaN (every comparison is False) and +-inf."""
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        return None
    if not lo <= val <= hi:
        return None
    return float(val)


def _tolerance(val) -> float:
    """A caller tolerance in 0.._MAX_TOLERANCE_S (exclusive), else the default."""
    tol = _finite(val, 0, _MAX_TOLERANCE_S)
    if tol is None or tol >= _MAX_TOLERANCE_S:
        return _TOLERANCE_S
    return tol


def _min_games(val) -> int:
    """A caller games floor that is an int (not a bool) in 1.._MAX_MIN_GAMES,
    else the default. A floor of 0 used to resolve to a mode with NO games."""
    if isinstance(val, bool) or not isinstance(val, int):
        return _MIN_GAMES
    if not 1 <= val <= _MAX_MIN_GAMES:
        return _MIN_GAMES
    return val


def _champion(val) -> str:
    """The stripped champion name, or "" for a non-str, blank or long one."""
    if not isinstance(val, str):
        return ""
    name = val.strip()
    if len(name) > _MAX_CHAMPION_LEN:
        return ""
    return name


def _percentiles(entry) -> Optional[tuple]:
    """(p25, p50, p75) from a benchmark entry when all three are finite numbers
    (not bools) in order, else None. A NaN distribution used to band every value
    "top quartile" because each comparison is False."""
    if not isinstance(entry, dict):
        return None
    out = []
    for key in ("p25", "p50", "p75"):
        val = entry.get(key)
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            return None
        if isinstance(val, float) and not math.isfinite(val):
            return None
        out.append(val)
    if not out[0] <= out[1] <= out[2]:
        return None
    return tuple(out)


def _resolve_sr_mode(champion: str, mode: str, min_games: int) -> Optional[str]:
    """Resolve a coarse live mode to the SR benchmark-mode key with enough games.

    Returns the first ``_SR_MODE_PRIORITY`` member that has ``>= min_games`` of
    the player's history on ``champion``, or None when the mode is not SR-family
    or no family member clears the gate. A games count that is not a finite
    number (a bool, a str, NaN, inf) is not trusted. Fail-soft: never raises."""
    if not champion or not isinstance(champion, str):
        return None
    if not isinstance(mode, str) or mode.strip().upper() != "SR":
        return None
    for bench_mode in _SR_MODE_PRIORITY:
        try:
            games = benchmarks.games_for(champion, bench_mode)
        except Exception:  # noqa: BLE001
            continue
        if _finite(games, 0, _MAX_MIN_GAMES) is None:
            continue
        if games >= min_games:
            return bench_mode
    return None


def _line(display: str, checkpoint: str, band: str, champion: str) -> str:
    """Short (<= 10 words) ASCII coach line for a banded metric."""
    if band == "above-p75":
        return f"{display} at {checkpoint}: top quartile on {champion}."
    if band == "p50-p75":
        return f"{display} at {checkpoint}: above your {champion} median."
    if band == "p25-p50":
        return f"{display} at {checkpoint}: below your {champion} median."
    if band == "below-p25":
        return f"{display} at {checkpoint}: bottom quartile on {champion}."
    return f"{display} at {checkpoint}: in your {champion} range."


def _active_checkpoints(game_time_s: float, tolerance_s: float):
    """Yield (label, metric_keys) for every checkpoint whose center is within
    ``tolerance_s`` of ``game_time_s``."""
    for center, label, metric_keys in _CHECKPOINTS:
        if abs(game_time_s - center) <= tolerance_s:
            yield label, metric_keys


def band_metrics(
    champion: str,
    game_time_s: float,
    *,
    cs: Optional[float] = None,
    level: Optional[float] = None,
    mode: str = "SR",
    tolerance_s: float = _TOLERANCE_S,
    min_games: int = _MIN_GAMES,
) -> List[Dict]:
    """Band live ``cs`` / ``level`` against the player's personal percentile
    distribution on ``champion`` at the active checkpoint(s).

    Returns a list of band dicts (one per banded metric), each with keys:
      checkpoint : "10" / "15"
      metric     : the benchmark metric key (e.g. "cs_at_10")
      display    : "CS" / "Level"
      value      : the live value banded
      band       : "below-p25" / "p25-p50" / "p50-p75" / "above-p75"
      p50        : the player's median for this metric (None if unavailable)
      line       : short ASCII coach line
      source_tag : always "live-bench"

    Pure + fail-soft: a non-SR mode, a thin (< min_games) distribution, an
    off-checkpoint game time, a missing champion, an absent / non-numeric /
    out-of-range live value (see INPUT VOCABULARY), a degenerate distribution or
    a "no-data" benchmark all yield NO band for that metric. Never raises. The
    returned list is empty when nothing is bandable."""
    out: List[Dict] = []
    gts = _finite(game_time_s, 0, _MAX_GAME_TIME_S)
    if gts is None:
        return out
    tolerance = _tolerance(tolerance_s)
    games_floor = _min_games(min_games)

    # Benchmarks are keyed on canonical ids (TahmKench); the live coach passes the
    # Live Client display name ("Tahm Kench"). Look up canonically, but keep the
    # readable display name for the coach line.
    name = _champion(champion)
    if not name:
        return out
    try:
        lookup = canonical_champion_id(name)
    except Exception:  # noqa: BLE001 - fail-soft resolver
        return out
    if not isinstance(lookup, str):
        return out
    bench_mode = _resolve_sr_mode(lookup, mode, games_floor)
    if bench_mode is None:
        return out

    live_values: Dict[str, Optional[float]] = {
        field: _finite(raw, lo, hi)
        for field, raw, (lo, hi) in (
            ("cs", cs, _LIVE_BOUNDS["cs"]),
            ("level", level, _LIVE_BOUNDS["level"]),
        )
    }

    for label, metric_keys in _active_checkpoints(gts, tolerance):
        for metric_key in metric_keys:
            field = _METRIC_LIVE_FIELD.get(metric_key)
            value = live_values.get(field) if field else None
            if value is None:
                continue
            try:
                band = benchmarks.rank_value(lookup, bench_mode, metric_key, value)
            except Exception:  # noqa: BLE001
                continue
            if band == "no-data":
                continue
            # A readable entry must be a sane distribution; an unreadable one
            # (get() raised or answered empty) keeps rank_value's band, no p50.
            try:
                entry = benchmarks.get(lookup, bench_mode, metric_key)
            except Exception:  # noqa: BLE001
                entry = None
            p50 = None
            if isinstance(entry, dict) and entry:
                pct = _percentiles(entry)
                if pct is None:
                    continue
                p50 = pct[1]
            display = _METRIC_DISPLAY.get(metric_key, metric_key)
            out.append(
                {
                    "checkpoint": label,
                    "metric": metric_key,
                    "display": display,
                    "value": value,
                    "band": band,
                    "p50": p50,
                    "line": _line(display, label, band, name),
                    "source_tag": _SOURCE_TAG,
                }
            )
    return out


def band_from_state(game_state: dict, *, mode: str = "SR") -> List[Dict]:
    """Adapter: pull champion / cs / level / game_time_s from a live game-state
    dict and band them. Defensive about the champion key (the live coach dict
    has carried it under a few names); fail-soft to no bands on a non-dict or a
    missing champion. Mirrors core.lead_projection.project_lead's call shape so a
    future wire-in is a drop-in."""
    if not isinstance(game_state, dict):
        return []

    champion = ""
    for key in ("champion", "champion_name", "champ", "tracked_champion_name"):
        val = game_state.get(key)
        if isinstance(val, str) and val.strip():
            champion = val.strip()
            break

    def _num(*keys: str) -> Optional[float]:
        # A junk number (bool, NaN, inf, negative, >1e308 int) is no reading,
        # so the next alias is tried; band_metrics applies the per-field bounds.
        for key in keys:
            val = _finite(game_state.get(key), 0, _MAX_GAME_TIME_S)
            if val is not None:
                return val
        return None

    return band_metrics(
        champion,
        _num("game_time_s", "game_seconds") or 0.0,
        cs=game_state.get("cs"),
        level=game_state.get("level"),
        mode=mode,
    )
