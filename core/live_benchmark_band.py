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
"""

from __future__ import annotations

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

# Minimum personal games behind a distribution before it is trustworthy to band
# against. Matches core.aftergame_summary.have_benchmarks (>= 5).
_MIN_GAMES = 5

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


def _resolve_sr_mode(champion: str, mode: str, min_games: int) -> Optional[str]:
    """Resolve a coarse live mode to the SR benchmark-mode key with enough games.

    Returns the first ``_SR_MODE_PRIORITY`` member that has ``>= min_games`` of
    the player's history on ``champion``, or None when the mode is not SR-family
    or no family member clears the gate. Fail-soft: never raises."""
    if not champion:
        return None
    if (mode or "").strip().upper() != "SR":
        return None
    for bench_mode in _SR_MODE_PRIORITY:
        try:
            if benchmarks.games_for(champion, bench_mode) >= min_games:
                return bench_mode
        except Exception:
            continue
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
    off-checkpoint game time, a missing champion, an absent / non-numeric live
    value, or a "no-data" benchmark all yield NO band for that metric. Never
    raises. The returned list is empty when nothing is bandable."""
    out: List[Dict] = []
    try:
        gts = float(game_time_s)
    except (TypeError, ValueError):
        return out
    if gts < 0:
        return out

    # Benchmarks are keyed on canonical ids (TahmKench); the live coach passes the
    # Live Client display name ("Tahm Kench"). Look up canonically, but keep the
    # readable display name for the coach line.
    lookup = canonical_champion_id(champion) if champion else ""
    bench_mode = _resolve_sr_mode(lookup, mode, min_games)
    if bench_mode is None:
        return out

    live_values: Dict[str, Optional[float]] = {"cs": cs, "level": level}

    for label, metric_keys in _active_checkpoints(gts, tolerance_s):
        for metric_key in metric_keys:
            field = _METRIC_LIVE_FIELD.get(metric_key)
            raw = live_values.get(field) if field else None
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                continue
            value = float(raw)
            try:
                band = benchmarks.rank_value(lookup, bench_mode, metric_key, value)
            except Exception:
                continue
            if band == "no-data":
                continue
            try:
                p50 = benchmarks.get(lookup, bench_mode, metric_key).get("p50")
            except Exception:
                p50 = None
            display = _METRIC_DISPLAY.get(metric_key, metric_key)
            out.append(
                {
                    "checkpoint": label,
                    "metric": metric_key,
                    "display": display,
                    "value": value,
                    "band": band,
                    "p50": p50,
                    "line": _line(display, label, band, champion),
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
        for key in keys:
            val = game_state.get(key)
            if isinstance(val, bool):
                continue
            if isinstance(val, (int, float)):
                return float(val)
        return None

    return band_metrics(
        champion,
        _num("game_time_s", "game_seconds") or 0.0,
        cs=_num("cs"),
        level=_num("level"),
        mode=mode,
    )
