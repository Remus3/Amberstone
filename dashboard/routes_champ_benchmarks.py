"""GET /api/champ-benchmarks - per-champion stat distribution (read-only).

Surfaces core.benchmarks (data/coach_reference/champion_benchmarks.json) as a
Aggregator-B-style per-champion stat breakdown - p25/p50/p75 for a fixed column set of
early-game metrics, one row per champion, over the operator's OWN tracked
corpus. This is a DESCRIPTIVE personal-corpus lens (the player's own baselines),
NOT a global / meta / Riot / Claude winrate. The benchmark JSON is already
computed and consumed by coach prose today; this thin HTTP surface is its first
UI exposure (the Build Insights "Benchmarks" tab polls it).
Live client: web/js/panels/champ_benchmarks.js (mode=sr|aram|arena).

Request shape:
  GET /api/champ-benchmarks[?mode=sr|aram|arena]

  mode : sr | aram | arena. Default sr (the only suffix the benchmark builder
         emits today; aram / arena are valid but resolve to zero rows).
         ASCII blanks (space, tab, CR, LF, FF, VT) are stripped from both
         ends, never Unicode ones (S144-T-629: str.strip() also ate U+3000).
         Anything else -> 400 with a fixed message that never echoes it.

The UI mode maps to a stored key suffix (champion_benchmarks.json keys are
"<Champ>|<suffix>"). A mode whose suffix has no rows returns ok:true with n:0
(the panel shows an empty state - no error).

Response:
  {"ok": true, "mode": <str>, "n": <int rows>, "min_games": 3,
   "metrics": [<5 column metric keys>],
   "rows": [{"champion": <str>, "games": <int>,
             "stats": {<metric>: {"p50","p25","p75","avg","n"}, ...}}, ...],
   "cached": <bool>, "elapsed_ms": <int, never negative>}

Only the 5 column metrics are shaped into stats; a champion missing one has that
stat omitted. Sample-gate: only champions with games >= min_games (3) are
included (Aggregator-B-style - never show a stat without enough sample behind it).

Row validation (S144-T-629). The JSON file is RC-written, but a hand edit, a
builder change or a half-merged file can put any JSON value in it, and one bad
value used to cost the whole table (a 500) or the whole panel (a NaN token the
browser's JSON.parse rejects). Now a bad value costs only itself:
  - a row that is not a dict, or whose champion is not a non-empty str, is
    dropped;
  - games is a whole count 0..1000000 (an int, or an integral float served
    as an int; never a bool or a str); anything else drops that row, as a
    count under the gate does (null / absent games still read as 0);
  - a metrics block or metric cell that is not a dict is treated as absent
    (the row stays, the cell renders "-");
  - p50 / p25 / p75 / avg are finite real numbers (never a bool, a str or a
    nested value; an int past 10**15 is not served) and n is a whole count
    0..1000000; a present sub-field that fails is served as null, an absent
    one stays absent.
A clean corpus serialises exactly as before (order, types and values).

Cache: 5min in-process keyed by (mode,) - mirrors routes_duration_winrate so a
re-polling panel does not re-scan the benchmark dict on every poll. Timed on
time.monotonic (a wall-clock step never keeps an entry fresh; an entry stamped
in the future is never served). A response is written to the socket after the
cache lock is released, so a client that stops reading never holds other
requests behind the lock.

Failure modes (a raw exception string is NEVER leaked to the client):
  - bad mode -> 400 with a short clear error
  - any other exception -> the fixed 500 {"ok": false, "error": "internal
    error - see logs"} through dashboard._errors.send_error (cause logged once
    with its type name, scrubbed, with the traceback); not cached. The body
    is dumped with allow_nan=False, so anything the row validation missed
    that is not strict JSON lands here too, never on the wire.
"""
from __future__ import annotations

import json
import logging
import math
import threading
import time
from urllib.parse import parse_qs, urlparse

from core import benchmarks
from dashboard._dispatch import equals
from dashboard._errors import GENERIC_ERROR, send_error

log = logging.getLogger("rc.web_dashboard")

_CACHE_TTL_S = 300.0
# (mode,) -> (stamped at, on time.monotonic; payload without the per-request
# cached / elapsed_ms fields). Never mutated after insert, so a reader may use
# an entry after releasing the lock.
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
_COUNT_FIELDS = frozenset({"n"})

# S144-T-629: the panel renders games with `| 0`, which wraps past 2**31; a
# personal corpus is nowhere near this bound.
_MAX_COUNT = 1_000_000
# An int past this is not served as a stat value: math.isfinite() raises
# OverflowError on an int past the float range, and JS reads past 2**53
# inexactly. Every real metric (gold, CS, KP percent, level) is far below.
_MAX_ABS_INT = 10 ** 15

_ASCII_BLANKS = " \t\r\n\f\v"
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


def _parse_mode(raw: str) -> tuple[str, str | None]:
    if not raw:
        return (DEFAULT_MODE, None)
    if raw not in VALID_MODES:
        return ("", f"mode must be one of {', '.join(VALID_MODES)}")
    return (raw, None)


def _count(value) -> int | None:
    """A whole count 0.._MAX_COUNT as an int, else None.

    An int or an integral finite float; never a bool (an int subclass) or a
    str (the builder writes JSON numbers).
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


def _shape_stats(metrics) -> dict:
    """Pull only the COLUMN_METRICS out of a row's full metric dict, keeping the
    headline + spread sub-fields. A column metric absent from the row, or one
    that is not a non-empty dict, is simply not added (the cell renders empty /
    null client-side). A present sub-field with a bad value is served as None."""
    out: dict[str, dict] = {}
    if not isinstance(metrics, dict):
        return out
    for col in COLUMN_METRICS:
        m = metrics.get(col)
        if not m or not isinstance(m, dict):
            continue
        out[col] = {f: (_count(m[f]) if f in _COUNT_FIELDS else _number(m[f]))
                    for f in _STAT_FIELDS if f in m}
    return out


def _shape_row(r) -> dict | None:
    """The wire row for one rows_for_mode entry, or None when it is dropped
    (not a dict, no champion name, games junk or under the gate)."""
    if not isinstance(r, dict):
        return None
    champion = r.get("champion")
    if not isinstance(champion, str) or not champion:
        return None
    raw_games = r.get("games")
    # null / absent games read as 0 (under the gate), as before.
    games = 0 if raw_games is None else _count(raw_games)
    if games is None or games < MIN_GAMES:
        return None
    return {
        "champion": champion,
        "games": games,
        "stats": _shape_stats(r.get("metrics")),
    }


def _build_payload(mode: str) -> dict:
    suffix = _MODE_SUFFIX.get(mode, mode)
    rows_out = []
    for r in benchmarks.rows_for_mode(suffix):
        row = _shape_row(r)
        if row is not None:
            rows_out.append(row)
    return {
        "ok": True,
        "mode": mode,
        "n": len(rows_out),
        "min_games": MIN_GAMES,
        "metrics": list(COLUMN_METRICS),
        "rows": rows_out,
    }


def _dump(payload: dict) -> bytes:
    return json.dumps(payload, allow_nan=False).encode("utf-8")


def _serve_champ_benchmarks(h) -> None:
    t0 = time.perf_counter()
    try:
        qs = parse_qs(urlparse(h.path).query or "")
        mode_raw = (qs.get("mode") or [""])[0].strip(_ASCII_BLANKS)

        mode, err = _parse_mode(mode_raw)
        if err:
            h._send(400, _dump({"ok": False, "error": err}),
                    "application/json")
            return

        key = (mode,)
        now = time.monotonic()
        cached = _cache_get(key, now)
        if cached is not None:
            payload = dict(cached)
            payload["cached"] = True
            payload["elapsed_ms"] = _elapsed_ms(t0)
            h._send(200, _dump(payload), "application/json")
            return

        payload = _build_payload(mode)
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
            log.warning("api/champ-benchmarks: error envelope failed")
            try:
                h._send(500, _FIXED_500_BODY, "application/json")
            except OSError:
                pass


def _reset_caches() -> None:
    """Test-only: clear response cache."""
    with _CACHE_LOCK:
        _CACHE.clear()


GET_ROUTES = [
    (equals("/api/champ-benchmarks"), _serve_champ_benchmarks),
]
