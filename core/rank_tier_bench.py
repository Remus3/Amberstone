"""Rank-tier benchmark grid for the in-game stats panel (overlay item 8, Phase 1).

Surfaces a SELECTED rank-tier's average metrics (cs / kda / kp), mode-specific,
so the overlay stats panel can benchmark the operator against, e.g., "an average
Gold SR game" for self-improvement - instead of the operator's own history
(that personal-corpus lens is core.role_bracket_bench, left untouched here).

Data (this phase): a committed STATIC estimate seed,
`data/rank_tiers/rank_tier_averages.seed.json`, lifted from the
`_RANK_TIER_AVERAGES` reference table in web/js/panels/last_match.js. The seed
is a hand-curated ESTIMATE, tagged "estimate-not-measured" in its `source`
header - source() carries that provenance so the UI can badge it and coaching
never leans on it as ground truth.

Live-first with static fallback (mirrors core.smoothed_rates_101qq): when
RC_RANK_TIER_LIVE is enabled, per-(tier, mode) rows from core.rank_tier_source
overlay the seed and source() reports "live"; otherwise the seed is served and
source() reports "static" ("none" if the seed is missing/empty). The kill
switch defaults OFF this phase (no live endpoint exists yet). The loader is
thread-safe, idempotent, TTL-cached, and never raises.

Grid shape (nested, JSON-friendly), returned by rank_tier_grid(tier, mode):
  { <role>: { <bracket>: { <metric>: {"avg": <number>} } } }
role is "all" for laneless benchmarking; bracket is "early" (< 840s) or "mid"
(< 1500s) - both carry identical estimate values in the seed (bracket-agnostic).
An absent tier/mode (e.g. arena, which has no seed) yields {} - "no benchmark".
"""
from __future__ import annotations

import copy
import json
import os
import threading
import time
from pathlib import Path

from core import rank_tier_source

_ROOT = Path(__file__).resolve().parent.parent
_SEED_PATH = _ROOT / "data" / "rank_tiers" / "rank_tier_averages.seed.json"

# The 10-tier ladder (global, not region-scoped) - the panel's rank set.
VALID_TIERS = (
    "iron", "bronze", "silver", "gold", "platinum",
    "emerald", "diamond", "master", "grandmaster", "challenger",
)
# Modes the seed carries (arena has no seed -> "no benchmark").
VALID_MODES = ("SR", "ARAM")
# Game-time brackets: early < 840s, mid < 1500s (14/25 min). Phase 1 seed is
# bracket-agnostic (both hold the same estimate); Phase 4 owns the live split.
VALID_BRACKETS = ("early", "mid")
VALID_METRICS = ("cs", "kda", "kp")

_TTL_S = 6 * 3600.0
_clock = time.monotonic

_LOCK = threading.RLock()
_LOADED = False
_LOADED_AT: float = 0.0
_SOURCE: str = "none"               # "live" | "static" | "none" - which seed won
_GRID: dict = {}                    # tier -> mode -> role -> bracket -> metric -> {avg}


def _live_enabled() -> bool:
    """RC_RANK_TIER_LIVE kill switch. Default OFF ("0") this phase - no live
    endpoint exists yet, so the seed is authoritative."""
    return os.environ.get("RC_RANK_TIER_LIVE", "0").strip().lower() not in (
        "0", "false", "no", "off", "",
    )


def _norm_tier(tier: str) -> str | None:
    t = str(tier or "").strip().lower()
    return t if t in VALID_TIERS else None


def _norm_mode(mode: str) -> str | None:
    m = str(mode or "").strip().upper()
    return m if m in VALID_MODES else None


def _load_static_grid() -> dict:
    """Read the committed estimate seed into the tier->mode->... grid, or {}
    on any read/parse error (fail-soft - the panel renders 'no benchmark')."""
    try:
        raw = json.loads(_SEED_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}
    tiers = raw.get("tiers") if isinstance(raw, dict) else None
    return tiers if isinstance(tiers, dict) else {}


def _fold_rows(rows: list) -> dict:
    """Fold a live source's flat metric rows into a role->bracket->metric grid.

    Each row: {"role","bracket","metric","avg"}. Unknown brackets/metrics and
    non-numeric averages are dropped. role defaults to "all"."""
    out: dict = {}
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        role = str(r.get("role") or "all")
        bracket = r.get("bracket")
        metric = r.get("metric")
        if bracket not in VALID_BRACKETS or metric not in VALID_METRICS:
            continue
        try:
            avg = float(r.get("avg"))
        except (TypeError, ValueError):
            continue
        out.setdefault(role, {}).setdefault(bracket, {})[metric] = {"avg": avg}
    return out


def _try_live_grid() -> dict:
    """Assemble a live grid by asking core.rank_tier_source for each
    (tier, mode). Empty {} when nothing is live (unconfigured/unreachable);
    the caller then keeps the static seed. Fail-soft per cell."""
    grid: dict = {}
    for tier in VALID_TIERS:
        for mode in VALID_MODES:
            try:
                rows = rank_tier_source.fetch_rows(tier, mode)
            except Exception:  # noqa: BLE001 - live path must never raise into the loader
                rows = None
            if not rows:
                continue
            mode_grid = _fold_rows(rows)
            if mode_grid:
                grid.setdefault(tier, {})[mode] = mode_grid
    return grid


def _overlay(base: dict, live: dict) -> None:
    """Overlay live cells onto the static base in place, at metric granularity
    (a live cs does not wipe the static kda/kp for the same cell)."""
    for tier, modes in live.items():
        for mode, mode_grid in modes.items():
            dst_mode = base.setdefault(tier, {}).setdefault(mode, {})
            for role, brackets in mode_grid.items():
                dst_role = dst_mode.setdefault(role, {})
                for bracket, metrics in brackets.items():
                    dst_bracket = dst_role.setdefault(bracket, {})
                    for metric, val in metrics.items():
                        dst_bracket[metric] = val


def _load_once() -> None:
    """Load + cache the grid. Thread-safe, idempotent, TTL-bounded. Static
    seed is the base; live rows overlay it when the kill switch is on."""
    global _LOADED, _LOADED_AT, _SOURCE, _GRID
    with _LOCK:
        if _LOADED and (_clock() - _LOADED_AT) < _TTL_S:
            return
        grid = _load_static_grid()
        src = "static" if grid else "none"
        if _live_enabled():
            live = _try_live_grid()
            if live:
                _overlay(grid, live)
                src = "live"
        _GRID = grid
        _SOURCE = src
        _LOADED = True
        _LOADED_AT = _clock()


def source() -> str:
    """Which seed the cache is serving: 'live' | 'static' | 'none'."""
    _load_once()
    return _SOURCE


def rank_tier_grid(tier: str, mode: str) -> dict:
    """Return the {role: {bracket: {metric: {"avg": n}}}} grid for a tier +
    mode, or {} when the tier/mode has no benchmark (unknown tier, or a mode
    the seed does not cover such as arena). Never raises; a deep copy so
    callers cannot mutate the cache."""
    _load_once()
    t = _norm_tier(tier)
    m = _norm_mode(mode)
    if not t or not m:
        return {}
    with _LOCK:
        tier_block = _GRID.get(t)
        if not isinstance(tier_block, dict):
            return {}
        mode_block = tier_block.get(m)
        if not isinstance(mode_block, dict):
            return {}
        return copy.deepcopy(mode_block)


def _reset_cache() -> None:
    """Test-only: clear the cache so the next call re-reads from disk/live."""
    global _LOADED, _LOADED_AT, _SOURCE, _GRID
    with _LOCK:
        _LOADED = False
        _LOADED_AT = 0.0
        _SOURCE = "none"
        _GRID = {}
