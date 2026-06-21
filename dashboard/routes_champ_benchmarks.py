"""GET /api/champ-benchmarks - per-champion stat distribution (read-only).

Surfaces core.benchmarks (data/coach_reference/champion_benchmarks.json) as a
Aggregator-B-style per-champion stat breakdown - p25/p50/p75 for a fixed column set of
early-game metrics, one row per champion, over the operator's OWN tracked
corpus. This is a DESCRIPTIVE personal-corpus lens (the player's own baselines),
NOT a global / meta / Riot / Claude winrate. The benchmark JSON is already
computed and consumed by coach prose today; this thin HTTP surface is its first
UI exposure (the Build Insights "Benchmarks" tab polls it).

Request shape:
  GET /api/champ-benchmarks[?mode=sr|aram|arena]

  mode : sr | aram | arena. Default sr (the only suffix the benchmark builder
         emits today; aram / arena are valid but resolve to zero rows).
         Anything else -> 400.

The UI mode maps to a stored key suffix (champion_benchmarks.json keys are
"<Champ>|<suffix>"). A mode whose suffix has no rows returns ok:true with n:0
(the panel shows an empty state - no error).

Response:
  {"ok": true, "mode": <str>, "n": <int rows>, "min_games": 3,
   "metrics": [<5 column metric keys>],
   "rows": [{"champion": <str>, "games": <int>,
             "stats": {<metric>: {"p50","p25","p75","avg","n"}, ...}}, ...],
   "cached": <bool>, "elapsed_ms": <int>}

Only the 5 column metrics are shaped into stats; a champion missing one has that
stat omitted. Sample-gate: only champions with games >= min_games (3) are
included (Aggregator-B-style - never show a stat without enough sample behind it).

Cache: 5min in-process keyed by (mode,) - mirrors routes_duration_winrate so a
re-polling panel does not re-scan the benchmark dict on every poll.

Failure modes (a raw exception string is NEVER leaked to the client):
  - bad mode -> 400 with a short clear error
  - any other exception -> 500 structured error; the raw text is logged.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from urllib.parse import parse_qs, urlparse

from core import benchmarks
from dashboard._dispatch import equals

log = logging.getLogger("rc.web_dashboard")

_CACHE_TTL_S = 300.0
_CACHE: dict[tuple, tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_MAX = 256
_CACHE_EVICT = 64

# UI mode -> stored champion_benchmarks.json key suffix. The corpus is keyed by
# "<Champ>|sr" today; aram / arena suffixes are valid targets that currently
# resolve to zero rows (empty state) - the map keeps the contract stable if the
# benchmark builder later starts emitting those suffixes.
DEFAULT_MODE = "sr"
VALID_MODES = ("sr", "aram", "arena")
_MODE_SUFFIX = {"sr": "sr", "aram": "aram", "arena": "arena"}

# The fixed column set surfaced as stats (the Benchmarks table columns). Keep in
# lockstep with web/js/panels/champ_benchmarks.js + the ui_mock fixture.
COLUMN_METRICS = (
    "cs_at_10",
    "gold_at_10",
    "gold_at_15",
    "kill_participation_pct",
    "level_at_10",
)
MIN_GAMES = 3

# The stat sub-fields carried per metric cell (p50 is the headline; p25/p75 the
# spread; n the per-metric sample). avg is included for completeness.
_STAT_FIELDS = ("p50", "p25", "p75", "avg", "n")


def _cache_put(key: tuple, now: float, payload: dict) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = (now, payload)
        if len(_CACHE) > _CACHE_MAX:
            victims = sorted(_CACHE.items(), key=lambda kv: kv[1][0])[:_CACHE_EVICT]
            for k, _ in victims:
                _CACHE.pop(k, None)


def _parse_mode(raw: str) -> tuple[str, str | None]:
    if not raw:
        return (DEFAULT_MODE, None)
    if raw not in VALID_MODES:
        return ("", f"mode must be one of {', '.join(VALID_MODES)}")
    return (raw, None)


def _shape_stats(metrics: dict) -> dict:
    """Pull only the COLUMN_METRICS out of a row's full metric dict, keeping the
    headline + spread sub-fields. A column metric absent from the row is simply
    not added (the cell renders empty / null client-side)."""
    out: dict[str, dict] = {}
    for col in COLUMN_METRICS:
        m = metrics.get(col)
        if not m:
            continue
        out[col] = {f: m.get(f) for f in _STAT_FIELDS if f in m}
    return out


def _build_payload(mode: str) -> dict:
    suffix = _MODE_SUFFIX.get(mode, mode)
    rows_in = benchmarks.rows_for_mode(suffix)
    rows_out = []
    for r in rows_in:
        games = int(r.get("games", 0) or 0)
        if games < MIN_GAMES:
            continue
        rows_out.append({
            "champion": r.get("champion", ""),
            "games": games,
            "stats": _shape_stats(r.get("metrics", {}) or {}),
        })
    return {
        "ok": True,
        "mode": mode,
        "n": len(rows_out),
        "min_games": MIN_GAMES,
        "metrics": list(COLUMN_METRICS),
        "rows": rows_out,
    }


def _serve_champ_benchmarks(h) -> None:
    t0 = time.time()
    try:
        qs = parse_qs(urlparse(h.path).query or "")
        mode_raw = (qs.get("mode") or [""])[0].strip()

        mode, err = _parse_mode(mode_raw)
        if err:
            h._send(400, json.dumps({"ok": False, "error": err})
                    .encode("utf-8"), "application/json")
            return

        key = (mode,)
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

        payload = _build_payload(mode)
        payload["cached"] = False
        payload["elapsed_ms"] = int((time.time() - t0) * 1000)

        cacheable = dict(payload)
        cacheable.pop("cached", None)
        cacheable.pop("elapsed_ms", None)
        _cache_put(key, now, cacheable)

        h._send(200, json.dumps(payload).encode("utf-8"), "application/json")
    except Exception as exc:  # noqa: BLE001
        log.warning("api/champ-benchmarks: %s", exc)
        try:
            h._send(500, json.dumps(
                {"ok": False, "error": "internal error - see logs"})
                .encode("utf-8"), "application/json")
        except Exception:  # noqa: BLE001
            pass


def _reset_caches() -> None:
    """Test-only: clear response cache."""
    with _CACHE_LOCK:
        _CACHE.clear()


GET_ROUTES = [
    (equals("/api/champ-benchmarks"), _serve_champ_benchmarks),
]
