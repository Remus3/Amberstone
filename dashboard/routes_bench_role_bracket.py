"""GET /api/role-bracket-bench - operator role x game-time-bracket averages.

The benchmark column feed for the WP-A4 vertical "You vs benchmark" stats panel.
Returns the operator's OWN historical SR averages (level / cs / teamfight / kda)
for one role + one game-time bracket, read from the rewind match corpus via
core.role_bracket_bench (a DESCRIPTIVE personal-corpus lens, never a meta /
Riot / Claude number). The panel's "You" side is the live game; this is the
"benchmark" side.

Request shape:
  GET /api/role-bracket-bench?role=<role>&bracket=<bracket>

  role    : top | jungle | mid | bot | support (UI aliases adc/middle/sup/... are
            normalized). Empty -> DEFAULT_ROLE. Unrecognized -> 400.
  bracket : early (<25m) | mid (25-35m) | late (>=35m). Empty -> DEFAULT_BRACKET.
            Unrecognized -> 400.

Response:
  {"ok": true, "role": <str>, "bracket": <str>, "n": <int matches in the cell>,
   "stats": {"lvl": {"avg","p50","n"}, "cs": {...}, "tf": {...}, "kda": {...}},
   "cached": <bool>, "elapsed_ms": <int>}

An empty cell (no matches for that role+bracket, or the corpus is absent on a
clean checkout / CI) returns ok:true, n:0, and the four stat keys with avg:null
- the panel renders an empty column rather than erroring.

Cache: 5min in-process keyed by (role, bracket) - mirrors routes_champ_benchmarks
so a re-polling panel does not re-scan the grid on every poll.

Failure modes (a raw exception string is NEVER leaked to the client):
  - bad role / bracket -> 400 with a short clear error
  - any other exception -> 500 structured error; the raw text is logged.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from urllib.parse import parse_qs, urlparse

from core import role_bracket_bench as bench
from dashboard._dispatch import equals

log = logging.getLogger("rc.web_dashboard")

_CACHE_TTL_S = 300.0
_CACHE: dict[tuple, tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_MAX = 64
_CACHE_EVICT = 16

DEFAULT_ROLE = "mid"
DEFAULT_BRACKET = "mid"
VALID_ROLES = bench.VALID_ROLES
VALID_BRACKETS = bench.VALID_BRACKETS

# The stat rows the panel renders (each cell carries avg/p50/n). An empty cell
# echoes these keys with avg:null so the client never KeyErrors a column.
_STAT_KEYS = ("lvl", "cs", "tf", "kda")
_EMPTY_STAT = {"avg": None, "p50": None, "n": 0}


def _cache_put(key: tuple, now: float, payload: dict) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = (now, payload)
        if len(_CACHE) > _CACHE_MAX:
            victims = sorted(_CACHE.items(), key=lambda kv: kv[1][0])[:_CACHE_EVICT]
            for k, _ in victims:
                _CACHE.pop(k, None)


def _parse_role(raw: str) -> tuple[str, str | None]:
    if not raw:
        return (DEFAULT_ROLE, None)
    canon = bench.normalize_role(raw)
    if canon is None:
        return ("", f"role must be one of {', '.join(VALID_ROLES)}")
    return (canon, None)


def _parse_bracket(raw: str) -> tuple[str, str | None]:
    if not raw:
        return (DEFAULT_BRACKET, None)
    b = raw.strip().lower()
    if b not in VALID_BRACKETS:
        return ("", f"bracket must be one of {', '.join(VALID_BRACKETS)}")
    return (b, None)


def _build_payload(role: str, bracket: str) -> dict:
    grid = bench.role_bracket_grid()
    cell = (grid.get(role, {}) or {}).get(bracket) or {}
    stats = {k: (cell.get(k) or dict(_EMPTY_STAT)) for k in _STAT_KEYS}
    return {
        "ok": True,
        "role": role,
        "bracket": bracket,
        "n": int(cell.get("n", 0) or 0),
        "stats": stats,
    }


def _serve_role_bracket_bench(h) -> None:
    t0 = time.time()
    try:
        qs = parse_qs(urlparse(h.path).query or "")
        role_raw = (qs.get("role") or [""])[0].strip()
        bracket_raw = (qs.get("bracket") or [""])[0].strip()

        role, err = _parse_role(role_raw)
        if err:
            h._send(400, json.dumps({"ok": False, "error": err})
                    .encode("utf-8"), "application/json")
            return
        bracket, err = _parse_bracket(bracket_raw)
        if err:
            h._send(400, json.dumps({"ok": False, "error": err})
                    .encode("utf-8"), "application/json")
            return

        key = (role, bracket)
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

        payload = _build_payload(role, bracket)
        payload["cached"] = False
        payload["elapsed_ms"] = int((time.time() - t0) * 1000)

        cacheable = dict(payload)
        cacheable.pop("cached", None)
        cacheable.pop("elapsed_ms", None)
        _cache_put(key, now, cacheable)

        h._send(200, json.dumps(payload).encode("utf-8"), "application/json")
    except Exception as exc:  # noqa: BLE001
        log.warning("api/role-bracket-bench: %s", exc)
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
    (equals("/api/role-bracket-bench"), _serve_role_bracket_bench),
]
