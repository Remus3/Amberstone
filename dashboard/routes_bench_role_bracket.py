"""GET /api/role-bracket-bench - operator role x game-time-bracket averages.

The benchmark column feed for the WP-A4 vertical "You vs benchmark" stats panel.
Returns the operator's OWN historical SR averages (level / cs / teamfight / kda)
for one role + one game-time bracket, read from the rewind match corpus via
core.role_bracket_bench (a DESCRIPTIVE personal-corpus lens, never a meta /
Riot / Claude number). The panel's "You" side is the live game; this is the
"benchmark" side. The reworked stats panel reads /api/rank-tier-bench instead
(core.role_bracket_bench is DEPRECATED-ALIVE); this route stays registered on
:8888, so it is still reachable with any query.

Request shape:
  GET /api/role-bracket-bench?role=<role>&bracket=<bracket>

  role    : top | jungle | mid | bot | support, or an alias from
            core.role_bracket_bench.ROLE_ALIASES (adc / middle / sup / ...),
            case-insensitive. Absent or blank -> DEFAULT_ROLE.
  bracket : early (games under 14:00) | mid (14:00 and over), case-insensitive.
            Absent or blank -> DEFAULT_BRACKET. The old third bracket is
            retired in the reader, so it is a 400 like any other unknown value.

  Each value has ASCII blanks (space, tab, CR, LF, FF, VT) stripped from its
  ends, never Unicode ones (str.strip() also ate U+3000 / NBSP), and must then
  be ASCII; anything else is a 400 with a fixed message that never echoes the
  value. A refusal is decided before the cache or the grid is read.

Response:
  {"ok": true, "role": <str>, "bracket": <str>, "n": <int matches in the cell>,
   "stats": {"lvl": {"avg","p50","n"}, "cs": {...}, "tf": {...}, "kda": {...}},
   "cached": <bool>, "elapsed_ms": <int>}

Every stat always carries exactly avg / p50 / n. avg and p50 are a finite
number from the grid (an int stays an int) or null; n and the top-level n are
a whole count or 0. A grid, role entry, cell or stat that is not the expected
dict reads as empty, so one junk field costs only itself and the payload never
shares a dict with the reader's grid cache. An empty cell (no matches for that
role+bracket, or the corpus is absent on a clean checkout / CI) returns ok:true,
n:0, and the four stat keys with avg:null - the panel renders an empty column
rather than erroring.

Cache: 5 min in-process keyed by (role, bracket), timed on time.monotonic (a
wall-clock step never keeps an entry fresh; an entry stamped in the future is
never served). The lock only guards the dict: no answer is sent under it.
elapsed_ms is measured on time.perf_counter.

Failure modes (a raw exception string is NEVER leaked to the client):
  - bad role / bracket -> 400 with a short fixed error
  - any other exception -> 500 {"ok": false, "error": "internal error - see
    logs"} through dashboard._errors.send_error (cause logged once with its
    type name, scrubbed, with the traceback). The 200 body is dumped with
    allow_nan=False before it is cached, so anything the shaping missed
    becomes that fixed 500 and is never cached.
"""
from __future__ import annotations

import json
import logging
import math
import threading
import time
from urllib.parse import parse_qs, urlparse

from core import role_bracket_bench as bench
from dashboard._dispatch import equals
from dashboard._errors import GENERIC_ERROR, send_error

log = logging.getLogger("rc.web_dashboard")

_CACHE_TTL_S = 300.0
# (role, bracket) -> (stamped at, on time.monotonic; payload without the
# per-request "cached" / "elapsed_ms" keys).
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

# A count above this is junk, not a match count (the corpus is one player's
# games). An int above _MAX_ABS_INT is junk too: json.dumps would write it
# exactly, but JS reads past 2**53 inexactly, and no level / CS / KP / KDA
# average comes near it.
_MAX_COUNT = 1_000_000
_MAX_ABS_INT = 10 ** 15

_ASCII_BLANKS = " \t\r\n\f\v"
_ROLE_ERROR = f"role must be one of {', '.join(VALID_ROLES)}"
_BRACKET_ERROR = f"bracket must be one of {', '.join(VALID_BRACKETS)}"
_FIXED_500_BODY = json.dumps(
    {"ok": False, "error": GENERIC_ERROR}).encode("utf-8")


def _elapsed_ms(t0: float) -> int:
    return max(0, int((time.perf_counter() - t0) * 1000))


def _cache_get(key: tuple, now: float) -> dict | None:
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
    if cached is not None and 0.0 <= now - cached[0] < _CACHE_TTL_S:
        return cached[1]
    return None


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
    # ASCII first: lower() maps KELVIN SIGN to "k", so "mar<U+212A>sman"
    # would otherwise read as "marksman". The alias map is read directly
    # (not via bench.normalize_role, whose str.strip() would also eat the
    # ASCII separators U+001C-U+001F).
    canon = bench.ROLE_ALIASES.get(raw.lower()) if raw.isascii() else None
    if canon is None:
        return ("", _ROLE_ERROR)
    return (canon, None)


def _parse_bracket(raw: str) -> tuple[str, str | None]:
    if not raw:
        return (DEFAULT_BRACKET, None)
    b = raw.lower() if raw.isascii() else ""
    if b not in VALID_BRACKETS:
        return ("", _BRACKET_ERROR)
    return (b, None)


def _count(value) -> int | None:
    """A whole count 0.._MAX_COUNT as an int, else None.

    An int or an integral finite float; never a bool (an int subclass) or a
    str (the reader builds counts with len()).
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 0 <= value <= _MAX_COUNT else None
    if isinstance(value, float) and math.isfinite(value) \
            and value.is_integer() and 0 <= value <= _MAX_COUNT:
        return int(value)
    return None


def _number(value) -> int | float | None:
    """A finite real number, returned unchanged (an int stays an int), else
    None. Never a bool; an int past _MAX_ABS_INT is None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if -_MAX_ABS_INT <= value <= _MAX_ABS_INT else None
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return None


def _shape_stat(s) -> dict:
    """A fresh {avg, p50, n} for one grid stat; a non-dict reads as empty."""
    if not isinstance(s, dict):
        return dict(_EMPTY_STAT)
    return {
        "avg": _number(s.get("avg")),
        "p50": _number(s.get("p50")),
        "n": _count(s.get("n")) or 0,
    }


def _lookup_cell(grid, role: str, bracket: str) -> dict:
    """The grid's cell for (role, bracket), or {} for any wrong-shaped level."""
    if not isinstance(grid, dict):
        return {}
    by_bracket = grid.get(role)
    if not isinstance(by_bracket, dict):
        return {}
    cell = by_bracket.get(bracket)
    return cell if isinstance(cell, dict) else {}


def _build_payload(role: str, bracket: str) -> dict:
    cell = _lookup_cell(bench.role_bracket_grid(), role, bracket)
    return {
        "ok": True,
        "role": role,
        "bracket": bracket,
        "n": _count(cell.get("n")) or 0,
        "stats": {k: _shape_stat(cell.get(k)) for k in _STAT_KEYS},
    }


def _dump(payload: dict) -> bytes:
    return json.dumps(payload, allow_nan=False).encode("utf-8")


def _serve_role_bracket_bench(h) -> None:
    t0 = time.perf_counter()
    try:
        qs = parse_qs(urlparse(h.path).query or "")
        role_raw = (qs.get("role") or [""])[0].strip(_ASCII_BLANKS)
        bracket_raw = (qs.get("bracket") or [""])[0].strip(_ASCII_BLANKS)

        role, err = _parse_role(role_raw)
        if err:
            h._send(400, _dump({"ok": False, "error": err}),
                    "application/json")
            return
        bracket, err = _parse_bracket(bracket_raw)
        if err:
            h._send(400, _dump({"ok": False, "error": err}),
                    "application/json")
            return

        key = (role, bracket)
        now = time.monotonic()
        cached = _cache_get(key, now)
        if cached is not None:
            payload = dict(cached)
            payload["cached"] = True
            payload["elapsed_ms"] = _elapsed_ms(t0)
            h._send(200, _dump(payload), "application/json")
            return

        payload = _build_payload(role, bracket)
        cacheable = dict(payload)
        payload["cached"] = False
        payload["elapsed_ms"] = _elapsed_ms(t0)
        # Dumped before anything is cached: a body that is not strict JSON
        # goes to the fixed 500 below and is never stored.
        body = _dump(payload)
        _cache_put(key, now, cacheable)
        h._send(200, body, "application/json")
    except Exception as exc:  # noqa: BLE001 - last resort: fixed 500, cause logged
        try:
            send_error(h, exc, fields={"ok": False}, log_traceback=True)
        except OSError:
            # The client went away while the error was being sent.
            pass
        except Exception:  # noqa: BLE001 - send_error failed before sending
            # (an exception whose str() raises): same fixed 500 body.
            log.warning("api/role-bracket-bench: error envelope failed")
            try:
                h._send(500, _FIXED_500_BODY, "application/json")
            except OSError:
                pass


def _reset_caches() -> None:
    """Test-only: clear the response cache + the underlying grid cache."""
    with _CACHE_LOCK:
        _CACHE.clear()
    bench._reset_cache()


GET_ROUTES = [
    (equals("/api/role-bracket-bench"), _serve_role_bracket_bench),
]
