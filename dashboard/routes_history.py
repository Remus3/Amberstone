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
from urllib.parse import parse_qs, urlparse

from dashboard.builders import (
    _build_history,
    _build_home_summary,
    _build_loadouts_all,
    _build_session_summary,
)
from dashboard._dispatch import equals, prefix

log = logging.getLogger("rc.web_dashboard")

# Raw exception text can leak file paths - log it, never render it
# (same policy as dashboard/_handler.do_POST; audit cycle 8 slice E).
_GENERIC_ERR = "internal error - see logs"


def _serve_session_summary(h) -> None:
    try:
        h._send(200, json.dumps(_build_session_summary()).encode(),
                "application/json")
    except Exception as exc:
        log.warning("api/session/summary: %s", exc)
        h._send(500, json.dumps({"error": _GENERIC_ERR}).encode(),
                "application/json")


def _serve_history(h) -> None:
    try:
        qs = parse_qs(urlparse(h.path).query)
        scope = (qs.get("scope") or ["14d"])[0]
        h._send(200, json.dumps(_build_history(scope)).encode(),
                "application/json")
    except Exception as exc:
        log.warning("api/history: %s", exc)
        h._send(500, json.dumps({"error": _GENERIC_ERR}).encode(),
                "application/json")


def _serve_loadouts_all(h) -> None:
    try:
        qs = parse_qs(urlparse(h.path).query)
        mode = (qs.get("mode") or ["aram"])[0]
        h._send(200, json.dumps(_build_loadouts_all(mode)).encode(),
                "application/json")
    except Exception as exc:
        log.warning("api/loadouts/all: %s", exc)
        h._send(500, json.dumps({"error": _GENERIC_ERR}).encode(),
                "application/json")


def _serve_home_summary(h) -> None:
    # Read-only aggregate for the dashboard's home/lobby view.
    # Pulls from data/match_history.db (the freshest source -
    # rewind_history.db is stale).
    try:
        h._send(200, json.dumps(_build_home_summary()).encode("utf-8"),
                "application/json")
    except Exception as exc:
        log.warning("api/home/summary: %s", exc)
        h._send(500, json.dumps({"error": _GENERIC_ERR}).encode(),
                "application/json")


# -- route table ------------------------------------------------------

# /api/history and /api/loadouts/all use prefix() because the legacy
# do_GET used `startswith`. /api/session/summary and /api/home/summary
# are exact matches.
GET_ROUTES = [
    (equals("/api/session/summary"),  _serve_session_summary),
    (prefix("/api/history"),          _serve_history),
    (prefix("/api/loadouts/all"),     _serve_loadouts_all),
    (equals("/api/home/summary"),     _serve_home_summary),
]

POST_ROUTES: list = []
