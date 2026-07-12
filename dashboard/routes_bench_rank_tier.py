"""GET /api/rank-tier-bench - selected rank-tier average metrics (overlay item 8).

The benchmark feed for the reworked in-game stats panel (web/js/panels/
stats_panel.js). Where the older /api/role-bracket-bench serves the operator's
OWN history (a descriptive personal-corpus lens), this serves a SELECTED
rank-tier's average metrics (cs / kda / kp), mode-specific, so the operator can
benchmark against, e.g., "an average Gold SR game" for self-improvement.

Data comes from core.rank_tier_bench (Phase 1): a committed STATIC estimate
seed, live-first when RC_RANK_TIER_LIVE is on. The estimate provenance rides
out on `source` ("live" | "static" | "none") so the overlay can badge it and
coaching never leans on it as ground truth.

Request shape:
  GET /api/rank-tier-bench?tier=<tier>&mode=<mode>&bracket=<bracket>

  tier    : iron | bronze | silver | gold | platinum | emerald | diamond |
            master | grandmaster | challenger. Empty -> the "off" state
            (ok:true, null stats). A non-empty UNKNOWN tier -> 400.
  mode    : SR | ARAM. Any other mode (arena, empty) -> "no benchmark"
            (ok:true, source echoed, null stats) - never a 400, because arena
            is a real mode that simply has no seed yet.
  bracket : early (<14m) | mid (>=14m). Empty/unknown -> mid (lenient; the
            panel derives it from the live clock).

Response:
  {"ok": true, "tier": <str>, "mode": <str>, "bracket": <str>, "role": "all",
   "source": <"live"|"static"|"none">, "n": <int metrics present>,
   "stats": {"cs": {"avg"}, "kda": {"avg"}, "kp": {"avg"}},
   "cached": <bool>, "elapsed_ms": <int>}

An empty cell (off tier, a mode with no seed such as arena, or a thin ARAM MID
cell) returns ok:true, n:0, and the three metric keys with avg:null - the panel
renders "-" / "no benchmark" rather than erroring.

Cache: 5min in-process keyed by (tier, mode, bracket) - mirrors
routes_bench_role_bracket so a re-polling panel does not re-scan the grid.

Failure modes (a raw exception string is NEVER leaked to the client):
  - non-empty unknown tier -> 400 with a short clear error
  - any other exception  -> 500 structured error; the raw text is logged.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from urllib.parse import parse_qs, urlparse

from core import rank_tier_bench as bench
from dashboard._dispatch import equals

log = logging.getLogger("rc.web_dashboard")

_CACHE_TTL_S = 300.0
_CACHE: dict[tuple, tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_MAX = 64
_CACHE_EVICT = 16

DEFAULT_BRACKET = "mid"
VALID_TIERS = bench.VALID_TIERS
VALID_MODES = bench.VALID_MODES
VALID_BRACKETS = bench.VALID_BRACKETS

# The metric rows the seed carries (each cell {avg}). An empty cell echoes these
# keys with avg:null so the client never KeyErrors a column. lvl is deliberately
# absent (the rank-tier seed has no level metric; the panel renders lvl You-only).
_METRIC_KEYS = bench.VALID_METRICS          # ("cs", "kda", "kp")
_EMPTY_STAT = {"avg": None}


def _cache_put(key: tuple, now: float, payload: dict) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = (now, payload)
        if len(_CACHE) > _CACHE_MAX:
            victims = sorted(_CACHE.items(), key=lambda kv: kv[1][0])[:_CACHE_EVICT]
            for k, _ in victims:
                _CACHE.pop(k, None)


def _parse_tier(raw: str) -> tuple[str, str | None]:
    """('', None) for the off state; (canon, None) for a valid tier; ('', err)
    for a non-empty unknown tier (the caller 400s)."""
    if not raw:
        return ("", None)
    t = raw.strip().lower()
    if t not in VALID_TIERS:
        return ("", f"tier must be one of {', '.join(VALID_TIERS)}")
    return (t, None)


def _parse_mode(raw: str) -> str:
    """Uppercased mode when the seed covers it, else '' (no benchmark). Never a
    400 - a real mode without a seed (arena) is a soft empty, not an error."""
    m = (raw or "").strip().upper()
    return m if m in VALID_MODES else ""


def _parse_bracket(raw: str) -> str:
    b = (raw or "").strip().lower()
    return b if b in VALID_BRACKETS else DEFAULT_BRACKET


def _build_payload(tier: str, mode: str, bracket: str) -> dict:
    """Assemble the metric cell for (tier, mode, bracket) from the rank-tier
    grid's laneless 'all' bucket. tier '' or mode '' -> empty (null) stats."""
    src = bench.source()
    stats = {k: dict(_EMPTY_STAT) for k in _METRIC_KEYS}
    if tier and mode:
        grid = bench.rank_tier_grid(tier, mode)      # {role: {bracket: {metric: {avg}}}}
        cell = ((grid.get("all", {}) or {}).get(bracket) or {})
        for k in _METRIC_KEYS:
            mv = cell.get(k)
            if isinstance(mv, dict) and mv.get("avg") is not None:
                stats[k] = {"avg": mv["avg"]}
    n = sum(1 for k in _METRIC_KEYS if stats[k].get("avg") is not None)
    return {
        "ok": True,
        "tier": tier,
        "mode": mode,
        "bracket": bracket,
        "role": "all",
        "source": src,
        "n": n,
        "stats": stats,
    }


def _serve_rank_tier_bench(h) -> None:
    t0 = time.time()
    try:
        qs = parse_qs(urlparse(h.path).query or "")
        tier_raw = (qs.get("tier") or [""])[0].strip()
        mode_raw = (qs.get("mode") or [""])[0].strip()
        bracket_raw = (qs.get("bracket") or [""])[0].strip()

        tier, err = _parse_tier(tier_raw)
        if err:
            h._send(400, json.dumps({"ok": False, "error": err})
                    .encode("utf-8"), "application/json")
            return
        mode = _parse_mode(mode_raw)
        bracket = _parse_bracket(bracket_raw)

        key = (tier, mode, bracket)
        now = time.time()
        with _CACHE_LOCK:
            cached = _CACHE.get(key)
            if cached and (now - cached[0]) < _CACHE_TTL_S:
                payload = dict(cached[1])
                payload["cached"] = True
                payload["elapsed_ms"] = int((time.time() - t0) * 1000)
                h._send(200, json.dumps(payload).encode("utf-8"),
                        "application/json")
                return

        payload = _build_payload(tier, mode, bracket)
        payload["cached"] = False
        payload["elapsed_ms"] = int((time.time() - t0) * 1000)

        cacheable = dict(payload)
        cacheable.pop("cached", None)
        cacheable.pop("elapsed_ms", None)
        _cache_put(key, now, cacheable)

        h._send(200, json.dumps(payload).encode("utf-8"), "application/json")
    except Exception as exc:  # noqa: BLE001
        log.warning("api/rank-tier-bench: %s", exc)
        try:
            h._send(500, json.dumps(
                {"ok": False, "error": "internal error - see logs"})
                .encode("utf-8"), "application/json")
        except Exception:  # noqa: BLE001
            pass


def _reset_caches() -> None:
    """Test-only: clear the response cache + the underlying grid cache."""
    with _CACHE_LOCK:
        _CACHE.clear()
    bench._reset_cache()


GET_ROUTES = [
    (equals("/api/rank-tier-bench"), _serve_rank_tier_bench),
]
