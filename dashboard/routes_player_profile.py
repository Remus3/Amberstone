"""GET /api/player-profile - longitudinal 8-axis GPI radar (read-only).

Serves the already-shipped ``core.player_gpi.compute_gpi`` over the LOCAL
rewind_history.db. The compute is the Aggregator-C-profile-style longitudinal
skill profile (8 axes, self-relative scoring); this route is the thin
read-only HTTP surface the radar panel polls.

Request shape:
  GET /api/player-profile[?mode=sr|aram|arena][&window=20][&champion=64]

  mode     : sr | aram | arena. Default sr. Anything else -> 400.
  window   : recent-game window, 1..100. Default 20.
  champion : optional champion id (Riot integer ``key``) to filter the
             history to one champion, 1..2147483647. Omitted -> null.
  An integer is an optional ``-`` then ASCII digits: a ``+``, an ``_``, a
  decimal point or a non-ASCII digit (all of which ``int()`` accepts) is the
  "must be an integer" 400; an integer out of range is the "must be lo..hi"
  400 (a huge champion id never reaches the DB bind as a 503).

Response is ``compute_gpi(...)``'s dict plus ``champions`` (the operator's
played-champion pool for ``mode`` as ``[{champion_id, n_games}, ...]`` newest
first - powers the per-champion drilldown selector), ``cached`` (bool) and
``elapsed_ms`` (int, never negative). See ``core.player_gpi._empty`` for the
axis shape. The compute dict includes ``this_match`` (newest filtered game
scored per axis vs the full history; null when insufficient) - it passes
through here untouched, cache included. A non-finite float anywhere in the
payload (an ``inf`` REAL in the DB poisons every mean built on it) is served
as ``null``: the body is always strict JSON, which the panel's ``r.json()``
needs.

Cache: 5min in-process LRU keyed by (mode, window, champion). The compute
is a full scan + percentile pass over the rewind db; a panel that re-polls
on a timer would otherwise turn that into a DB hot loop. The TTL runs on the
monotonic clock (a wall-clock step neither extends nor cuts it short), the
entry is stamped when the compute finishes, and the response is written
after ``_CACHE_LOCK`` is released, so a slow client never stalls the route.

Failure modes (a raw exception string is NEVER leaked to the client):
  - bad mode / window / champion -> 400 with a short clear error
  - compute raised a DB / OS error (db missing, locked, corrupt) -> 503
  - any other exception (a bug) -> 500 structured error; the raw text and
    the traceback are logged.
A failure is never cached.
"""
from __future__ import annotations

import json
import logging
import math
import re
import sqlite3
import threading
import time
from urllib.parse import parse_qs, urlparse

from core import draft_elo_db, player_gpi
from dashboard._dispatch import equals

log = logging.getLogger("rc.web_dashboard")

_VALID_MODES = ("sr", "aram", "arena")
_WINDOW_MIN = 1
_WINDOW_MAX = 100
# Riot champion keys are small positive ints; the cap is the 32-bit signed
# max, which every real key fits and every SQLite INTEGER bind accepts.
_CHAMPION_MIN = 1
_CHAMPION_MAX = 2**31 - 1

# An integer is an optional minus then ASCII digits. str patterns: ``\d``
# would match any Unicode digit, so the class is spelled out.
_INT_RE = re.compile(r"-?[0-9]+")

# Exact texts are pinned by tests/test_routes_int_param_no_echo_s144q51.py;
# a 400 names the parameter and the shape, never the caller's value.
_ERR_WINDOW_INT = "window must be an integer"
_ERR_WINDOW_RANGE = f"window must be {_WINDOW_MIN}..{_WINDOW_MAX}"
_ERR_CHAMPION_INT = "champion must be an integer"
_ERR_CHAMPION_RANGE = f"champion must be {_CHAMPION_MIN}..{_CHAMPION_MAX}"

_CACHE_TTL_S = 300.0
# key -> (monotonic stamp, payload without cached / elapsed_ms)
_CACHE: dict[tuple, tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()
# Mirror routes_draft_elo: TTL only gates serving, so cap + drop-oldest
# keeps the dict bounded across long uptimes.
_CACHE_MAX = 256
_CACHE_EVICT = 64

# What "the rewind history is unavailable" looks like from the compute:
# open_ro on a missing file, a locked / corrupt db, a vanished drive.
_UNAVAILABLE_ERRORS = (sqlite3.Error, OSError)


def _cache_put(key: tuple, stamp: float, payload: dict) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = (stamp, payload)
        if len(_CACHE) > _CACHE_MAX:
            victims = sorted(_CACHE.items(),
                             key=lambda kv: kv[1][0])[:_CACHE_EVICT]
            for k, _ in victims:
                _CACHE.pop(k, None)


def _cache_get(key: tuple, now: float) -> dict | None:
    """A shallow copy of the fresh entry for ``key``, or None."""
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached is None:
            return None
        age = now - cached[0]
        if 0.0 <= age < _CACHE_TTL_S:
            return dict(cached[1])
        return None


def _parse_bounded_int(raw: str, lo: int, hi: int,
                       err_int: str, err_range: str) -> tuple[int, str | None]:
    """(value, None) for an integer in lo..hi, else (0, error text).

    The integer shape is an optional ``-`` then ASCII digits. ``int()`` alone
    also takes ``+``, ``_`` separators, surrounding whitespace and every
    Unicode digit, so those are the not-an-integer error. A long digit string
    is the range error before ``int()`` runs, so its conversion cost (and
    the ``int_max_str_digits`` ValueError) is never paid.
    """
    if not _INT_RE.fullmatch(raw):
        return (0, err_int)
    digits = raw.lstrip("-").lstrip("0") or "0"
    if raw.startswith("-") or len(digits) > len(str(hi)):
        return (0, err_range)
    val = int(digits)
    if val < lo or val > hi:
        return (0, err_range)
    return (val, None)


def _parse_mode(raw: str) -> tuple[str, str | None]:
    if not raw:
        return ("sr", None)
    if raw not in _VALID_MODES:
        return ("", f"mode must be one of {', '.join(_VALID_MODES)}")
    return (raw, None)


def _parse_window(raw: str) -> tuple[int, str | None]:
    if not raw:
        return (player_gpi.DEFAULT_WINDOW, None)
    return _parse_bounded_int(raw, _WINDOW_MIN, _WINDOW_MAX,
                              _ERR_WINDOW_INT, _ERR_WINDOW_RANGE)


def _parse_champion(raw: str) -> tuple[int | None, str | None]:
    if not raw:
        return (None, None)
    val, err = _parse_bounded_int(raw, _CHAMPION_MIN, _CHAMPION_MAX,
                                  _ERR_CHAMPION_INT, _ERR_CHAMPION_RANGE)
    return (None, err) if err else (val, None)


def _scrub(value):
    """A copy of ``value`` with every non-finite float replaced by None."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_scrub(v) for v in value]
    return value


def _json_body(payload: dict) -> bytes:
    return json.dumps(payload, allow_nan=False).encode("utf-8")


def _send_json(h, status: int, payload: dict) -> None:
    h._send(status, _json_body(payload), "application/json")


def _elapsed_ms(t0: float) -> int:
    return max(0, int((time.perf_counter() - t0) * 1000))


def _compute(mode: str, window: int, champion: int | None) -> dict:
    # One RO connection shared by the GPI compute + the champion-pool list so a
    # single uncached request opens the db once. compute_gpi/list_champions both
    # leave a caller-supplied conn open (own=False); the route owns the close.
    conn = draft_elo_db.open_ro()
    try:
        payload = player_gpi.compute_gpi(
            mode=mode, window=window, champion=champion, conn=conn)
        payload["champions"] = player_gpi.list_champions(mode, conn=conn)
    finally:
        try:
            conn.close()
        except sqlite3.Error:
            pass
    return payload


def _serve_player_profile(h) -> None:
    t0 = time.perf_counter()
    try:
        qs = parse_qs(urlparse(h.path).query or "")
        mode_raw = (qs.get("mode") or [""])[0].strip()
        window_raw = (qs.get("window") or [""])[0].strip()
        champ_raw = (qs.get("champion") or [""])[0].strip()

        mode, err = _parse_mode(mode_raw)
        if err:
            _send_json(h, 400, {"ok": False, "error": err})
            return
        window, err = _parse_window(window_raw)
        if err:
            _send_json(h, 400, {"ok": False, "error": err})
            return
        champion, err = _parse_champion(champ_raw)
        if err:
            _send_json(h, 400, {"ok": False, "error": err})
            return

        key = (mode, window, champion)
        hit = _cache_get(key, time.monotonic())
        if hit is not None:
            # The lock is released before the write: a slow client must not
            # stall every other request on this route.
            hit["cached"] = True
            hit["elapsed_ms"] = _elapsed_ms(t0)
            _send_json(h, 200, hit)
            return

        try:
            payload = _scrub(_compute(mode, window, champion))
        except _UNAVAILABLE_ERRORS as exc:
            log.warning("api/player-profile compute: %s: %s",
                        type(exc).__name__, exc)
            _send_json(h, 503, {"ok": False,
                                "error": "rewind history unavailable"})
            return

        _cache_put(key, time.monotonic(), dict(payload))

        payload["cached"] = False
        payload["elapsed_ms"] = _elapsed_ms(t0)
        _send_json(h, 200, payload)
    except Exception:  # last-resort 500, traceback logged
        log.warning("api/player-profile failed", exc_info=True)
        try:
            # Raw exception text stays in the log only.
            _send_json(h, 500, {"ok": False,
                                "error": "internal error - see logs"})
        except Exception:  # noqa: BLE001 - a dead socket (OSError) or a
            # closed wfile (ValueError); the route must never raise.
            pass


def _reset_caches() -> None:
    """Test-only: clear response cache."""
    with _CACHE_LOCK:
        _CACHE.clear()


GET_ROUTES = [
    (equals("/api/player-profile"), _serve_player_profile),
]
