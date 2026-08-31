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

Concurrency contract (this module is read from dashboard server threads via
dashboard/routes_bench_rank_tier.py, so a blocked reader is a blocked request):
  - `_LOCK` guards the published cache fields ONLY and is NEVER held across
    network I/O. A live sweep is VALID_TIERS x VALID_MODES = 20 cells, each a
    fresh HTTP GET at rank_tier_source._TIMEOUT_S = 6.0s, so holding `_LOCK`
    over one would stall every accessor for ~120s in the worst case.
  - `_REFRESH_LOCK` serialises refreshers and IS held across the sweep, but the
    only caller that ever WAITS on it is a cold start with nothing to serve.
  - Once a grid exists, an expired TTL kicks a BACKGROUND refresh and the stale
    grid is returned immediately (stale-while-revalidate).
  - `_LIVE_BUDGET_S` bounds one sweep's wall clock so a half-dead endpoint
    yields a partial live overlay instead of a two-minute refresh.

Grid shape (nested, JSON-friendly), returned by rank_tier_grid(tier, mode):
  { <role>: { <bracket>: { <metric>: {"avg": <number>} } } }
role is "all" for laneless benchmarking; bracket is "early" (< 840s) or "mid"
(< 1500s) - both carry identical estimate values in the seed (bracket-agnostic).
An absent tier/mode (e.g. arena, which has no seed) yields {} - "no benchmark".
"""
from __future__ import annotations

import copy
import json
import logging
import math
import os
import threading
import time
from pathlib import Path

from core import rank_tier_source

log = logging.getLogger("rc.web_dashboard")

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
# Wall-clock ceiling for ONE live sweep. 20 cells x a 6.0s socket timeout is a
# ~120s floor on the unbounded worst case; the budget is checked between cells,
# so a slow endpoint yields a PARTIAL live overlay (already fail-soft per cell)
# instead of a two-minute refresh.
_LIVE_BUDGET_S = 30.0
_clock = time.monotonic

# _LOCK guards the published fields below and is NEVER held across network I/O.
# _REFRESH_LOCK serialises refreshers and IS held across the sweep; only a cold
# start ever waits on it. Never take _LOCK and then block on _REFRESH_LOCK.
_LOCK = threading.RLock()
_REFRESH_LOCK = threading.Lock()
_LOADED = False
_LOADED_AT: float = 0.0
_GENERATION = 0                     # bumped by _reset_cache; a build from an
                                    # older generation is discarded at publish
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
    non-numeric averages are dropped. role defaults to "all".

    Two value rules, both load-bearing:
      - NON-FINITE avgs are dropped. json.loads accepts NaN / Infinity /
        -Infinity by default, a nan passes isinstance(x, float) AND survives
        float() (raising neither TypeError nor ValueError), and json.dumps then
        re-emits a bare `NaN` token that a browser JSON.parse rejects - which
        breaks the ENTIRE /api/rank-tier-bench body, not one row.
        core.rank_tier_source already rejects these at its parse boundary; this
        is the belt to that braces, and it also covers a caller-supplied row.
      - BOOLS are dropped. bool subclasses int and float(True) is 1.0, so a
        `"avg": true` would silently become the average 1.0. A boolean is not a
        measured average, so this is treated as a type error, not a value."""
    out: dict = {}
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        role = str(r.get("role") or "all")
        bracket = r.get("bracket")
        metric = r.get("metric")
        if bracket not in VALID_BRACKETS or metric not in VALID_METRICS:
            continue
        raw_avg = r.get("avg")
        if isinstance(raw_avg, bool):
            continue
        try:
            avg = float(raw_avg)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(avg):
            continue
        out.setdefault(role, {}).setdefault(bracket, {})[metric] = {"avg": avg}
    return out


def _try_live_grid() -> dict:
    """Assemble a live grid by asking core.rank_tier_source for each
    (tier, mode). Empty {} when nothing is live (unconfigured/unreachable);
    the caller then keeps the static seed. Fail-soft per cell.

    Performs NETWORK I/O - callers must not hold _LOCK. Bounded by
    _LIVE_BUDGET_S, checked between cells: a partial grid is a valid result
    because the overlay is per-cell and the static seed backs every miss."""
    grid: dict = {}
    started = _clock()
    for tier in VALID_TIERS:
        for mode in VALID_MODES:
            if (_clock() - started) >= _LIVE_BUDGET_S:
                return grid
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


def _refresh_now() -> None:
    """Build a fresh grid and publish it. Caller MUST hold _REFRESH_LOCK.

    The build - a disk read plus, when live is on, up to 20 HTTP GETs - runs
    with NO lock held. Only the publish takes _LOCK, and only for the handful of
    assignments. That is the whole fix for the ~120s lock hold."""
    global _LOADED, _LOADED_AT, _SOURCE, _GRID
    with _LOCK:
        gen = _GENERATION
    grid = _load_static_grid()
    src = "static" if grid else "none"
    if _live_enabled():
        live = _try_live_grid()          # network I/O - deliberately lock-free
        if live:
            _overlay(grid, live)
            src = "live"
    with _LOCK:
        if gen != _GENERATION:
            return                       # a _reset_cache landed mid-build
        if not grid and _GRID:
            # Lane 8 (2026-08-31), sibling of the core/smoothed_rates_101qq
            # fix: _load_static_grid is fail-soft and hands back {} on a
            # transient read failure, so a refresh that read NOTHING used to
            # overwrite a perfectly good grid and blank the overlay stats
            # panel for a full TTL. Keep what we have; re-stamp so the retry
            # lands one TTL later rather than on every read.
            log.warning(
                "rank-tier bench: refresh yielded an empty grid; keeping the "
                "previous %s grid", _SOURCE)
            _LOADED_AT = _clock()
            return
        _GRID = grid
        _SOURCE = src
        _LOADED = True
        _LOADED_AT = _clock()


def _refresh_in_background() -> None:
    """Kick a refresh onto a daemon thread, or do nothing when one is already in
    flight. Callers keep serving the stale grid meanwhile."""
    if not _REFRESH_LOCK.acquire(blocking=False):
        return                           # a refresh is already running

    def _run() -> None:
        try:
            _refresh_now()
        finally:
            _REFRESH_LOCK.release()

    try:
        threading.Thread(target=_run, name="rank-tier-bench-refresh",
                         daemon=True).start()
    except RuntimeError:
        # Interpreter shutting down, or the thread limit is hit. Release rather
        # than leak the lock; the stale grid keeps serving and the next call
        # retries.
        _REFRESH_LOCK.release()


def _load_once() -> None:
    """Ensure a grid is published, refreshing when the TTL has lapsed.

    A COLD start (nothing cached) blocks the caller, and only one thread does
    that work. Once a grid exists, an expired TTL kicks a background refresh and
    the stale grid is served immediately - a reader never waits on network I/O,
    and never waits on _LOCK behind a fetch because _LOCK is not held over one.
    """
    with _LOCK:
        loaded = _LOADED
        fresh = loaded and (_clock() - _LOADED_AT) < _TTL_S
    if fresh:
        return
    if loaded:
        _refresh_in_background()         # stale-while-revalidate
        return
    with _REFRESH_LOCK:
        with _LOCK:
            if _LOADED:
                return                   # another thread did the cold load
        _refresh_now()


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
    """Test-only: clear the cache so the next call re-reads from disk/live.
    Bumps the generation so an in-flight background build cannot publish over
    the reset."""
    global _LOADED, _LOADED_AT, _SOURCE, _GRID, _GENERATION
    with _LOCK:
        _LOADED = False
        _LOADED_AT = 0.0
        _SOURCE = "none"
        _GRID = {}
        _GENERATION += 1


def _await_refresh_for_tests(timeout_s: float = 15.0) -> bool:
    """Test-only: block until no background refresh is in flight. True when the
    refresher is idle, False on timeout."""
    if not _REFRESH_LOCK.acquire(timeout=timeout_s):
        return False
    _REFRESH_LOCK.release()
    return True
