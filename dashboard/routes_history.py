"""History / home / session-summary / loadouts routes.

Slice 2C (2026-05-01): handlers carved out of web_dashboard._Handler.
Group 3 - read-only aggregates over data/match_history.db, all
backed by builders already extracted into `dashboard.builders`.

Each route receives the BaseHTTPRequestHandler (`h`) as its sole
argument and uses `h._send(code, body, ctype)` to write the response.
Module-level GET_ROUTES is consumed by `dashboard._dispatch`.
"""
import json
import logging
import threading
import time
from urllib.parse import parse_qs, urlparse

from dashboard.builders import (
    _build_history,
    _build_home_summary,
    _build_loadouts_all,
    _build_session_summary,
)
from dashboard._dispatch import equals

log = logging.getLogger("rc.web_dashboard")

# Raw exception text can leak file paths - log it, never render it
# (same policy as dashboard/_handler.do_POST; audit cycle 8 slice E).
_GENERIC_ERR = "internal error - see logs"
_ERR_BODY = json.dumps({"error": _GENERIC_ERR}).encode("utf-8")

# The ?scope= values dashboard/builders.py _build_history honours. That
# builder has no else branch, so any other string used to mean "the whole
# DB" while the response echoed the bogus scope as if it had been applied
# (s144 true-audit F1). Absent / empty still means the 14d default.
_HISTORY_SCOPES = frozenset({"14d", "season", "prior_season", "all"})
_DEFAULT_SCOPE = "14d"
_BAD_SCOPE_BODY = json.dumps({"error": "bad_scope"}).encode("utf-8")


def _encode(obj) -> bytes:
    """STRICT JSON. allow_nan=False turns a NaN / Infinity in a builder
    result into a ValueError (a logged 500) instead of a bare NaN token the
    browser's JSON.parse rejects on a 200 (s144 true-audit F3)."""
    return json.dumps(obj, allow_nan=False).encode("utf-8")


def _reply(h, code: int, body: bytes, route: str) -> None:
    """The ONE send per request. An OSError here means the client went
    away mid-response (the header flush hit a reset socket); answering it
    again would write a second status line onto the same dead connection,
    so it is logged and dropped (s144 true-audit F4)."""
    try:
        h._send(code, body, "application/json")
    except OSError as exc:
        log.debug("%s: client gone before %d was sent: %s", route, code, exc)


def _serve_built(h, route: str, build) -> None:
    """Build, encode, then send - the send stays OUTSIDE the try so a
    failed 200 can never fall into the 500 branch."""
    try:
        body = _encode(build())
    except Exception as exc:  # noqa: BLE001 - route boundary: log, never render
        log.warning("%s: %s: %s", route, type(exc).__name__, exc)
        _reply(h, 500, _ERR_BODY, route)
        return
    _reply(h, 200, body, route)


def _query_first(path: str, key: str) -> str:
    qs = parse_qs(urlparse(path).query or "")
    return (qs.get(key) or [""])[0]


def _serve_session_summary(h) -> None:
    _serve_built(h, "api/session/summary", _build_session_summary)


def _serve_history(h) -> None:
    route = "api/history"
    try:
        scope = _query_first(h.path, "scope").strip().lower() or _DEFAULT_SCOPE
    except Exception as exc:  # noqa: BLE001 - route boundary: log, never render
        log.warning("%s: %s: %s", route, type(exc).__name__, exc)
        _reply(h, 500, _ERR_BODY, route)
        return
    if scope not in _HISTORY_SCOPES:
        _reply(h, 400, _BAD_SCOPE_BODY, route)
        return
    _serve_built(h, route, lambda: _build_history(scope))


def _serve_loadouts_all(h) -> None:
    def _build():
        # loadout_resolver._normalize_mode maps any string onto
        # aram / arena / tft / sr, so ?mode= needs no whitelist here.
        return _build_loadouts_all(_query_first(h.path, "mode") or "aram")
    _serve_built(h, "api/loadouts/all", _build)


# HOME mode tabs (BE half): the ?mode= values /api/home/summary honors.
# Mirrors builders_home._HOME_MODE_FILTERS - TFT is deliberately absent
# (TFT rows are excluded from the home view at the read layer).
_HOME_MODES = frozenset({"SR", "ARAM", "ARENA"})


def _parse_home_mode(path: str) -> str | None:
    """Whitelist-parse the ?mode= query for /api/home/summary.

    Case-insensitive ("aram" -> "ARAM"). Anything outside the whitelist
    (tft, garbage, empty, absent) returns None so the summary silently
    falls back to unfiltered ALL - never a 4xx. Pure helper so tests can
    exercise the parsing without a live handler.
    """
    qs = parse_qs(urlparse(path).query or "")
    mode = (qs.get("mode") or [""])[0].strip().upper()
    return mode if mode in _HOME_MODES else None


# Route TTL cache - the established _CACHE / _CACHE_TTL_S / _CACHE_LOCK
# triple used by 44 sibling route modules (see routes_op_score.py).
#
# 25s sits just above the 20s client poll (web/js/main.js `_HOME`
# intervalMs) so a tab's consecutive polls coalesce onto one build instead
# of straddling the window, and every extra open tab or reload becomes free.
# Fidelity-neutral: match_history.db only changes when a game completes, and
# the home view is hidden during ChampSelect / InProgress anyway.
#
# No eviction policy - unlike the champion-keyed sibling caches, the key
# space here is bounded by construction at len(_HOME_MODES) + 1 (the
# unfiltered ALL entry keys on None), so the dict cannot grow.
_CACHE_TTL_S = 25.0
_CACHE: dict[str | None, tuple[float, bytes]] = {}
_CACHE_LOCK = threading.Lock()


def _serve_home_summary(h) -> None:
    # Read-only aggregate for the dashboard's home/lobby view.
    # Pulls from data/match_history.db (the freshest source -
    # rewind_history.db is stale). Optional ?mode=SR|ARAM|ARENA scopes
    # the stats sections to one mode (home mode tabs, HOME QA round 1).
    route = "api/home/summary"
    try:
        mode = _parse_home_mode(h.path)
        now = time.time()
        with _CACHE_LOCK:
            cached = _CACHE.get(mode)
        if cached and (now - cached[0]) < _CACHE_TTL_S:
            body = cached[1]
        else:
            body = _encode(_build_home_summary(mode))
            # Stored only on success (a non-finite payload raises in
            # _encode first), so one transient DB error cannot pin a
            # failure for the whole TTL window.
            with _CACHE_LOCK:
                _CACHE[mode] = (now, body)
    except Exception as exc:  # noqa: BLE001 - route boundary: log, never render
        log.warning("%s: %s: %s", route, type(exc).__name__, exc)
        _reply(h, 500, _ERR_BODY, route)
        return
    # Sent with the lock RELEASED: holding it across the socket write let
    # one slow reader serialise every other tab's poll (s144 true-audit F5).
    _reply(h, 200, body, route)


# -- route table ------------------------------------------------------

# All four are exact matches (path or path?query). /api/history and
# /api/loadouts/all used prefix() because the legacy do_GET used
# `startswith`, which answered 200 with real data for non-routes such as
# /api/historyX and would shadow any later route on that stem (s144
# true-audit F2). The only callers send the bare path plus a query.
GET_ROUTES = [
    (equals("/api/session/summary"),  _serve_session_summary),
    (equals("/api/history"),          _serve_history),
    (equals("/api/loadouts/all"),     _serve_loadouts_all),
    (equals("/api/home/summary"),     _serve_home_summary),
]

POST_ROUTES: list = []
