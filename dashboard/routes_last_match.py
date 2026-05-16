"""Last Match view route.

Serves /api/last-match — operator's most-recent non-TFT match plus the
Quick Review (what went right / wrong as a team / chronic patterns).
Source of truth: data/match_history.db. rewind_history.db enrichment
is deferred to the v2 Refresh-from-Riot flow (button in the Last Match
page header).
"""
import json
import logging

from dashboard.builders import _build_last_match
from dashboard._dispatch import equals

log = logging.getLogger("rc.web_dashboard")


def _serve_last_match(h) -> None:
    try:
        h._send(200, json.dumps(_build_last_match()).encode("utf-8"),
                "application/json")
    except Exception as exc:
        log.warning("api/last-match: %s", exc)
        h._send(500, json.dumps({"error": str(exc)}).encode(),
                "application/json")


GET_ROUTES = [
    (equals("/api/last-match"), _serve_last_match),
]

POST_ROUTES: list = []
