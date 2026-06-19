"""GET /api/lessons/status - cross-Claude lesson sync surface (Phase 4).

Reads the sender ledger + receiver ledger, refreshes any newly-arrived
acks (the ack-watcher does the HTTPS shuttle to /api/bridge with
fail-soft on outage), and returns the merged status as JSON. Read-only;
no POST handler.

The same shape `tools/lessons_status.py` prints. Useful both as a
machine-readable surface and a snapshot the dashboard can render
without spawning a subprocess.
"""
from __future__ import annotations

import json
from dashboard._errors import send_error
import logging
import time
from urllib.parse import parse_qs, urlparse

from dashboard._dispatch import equals

log = logging.getLogger("rc.web_dashboard")


def _serve_lessons_status(h) -> None:
    """GET ?refresh=0|1 - default 1 (poll bridge for new acks).

    Refresh is best-effort; if the bridge is down the watcher returns
    a zero-work report and the summary/confidence still render from
    whatever the ledgers currently hold.
    """
    try:
        qs = parse_qs(urlparse(h.path).query)
        refresh_raw = (qs.get("refresh") or ["1"])[0].strip().lower()
        refresh = refresh_raw not in ("0", "false", "no")
        # Lazy import so a malformed ledger / watcher import doesn't
        # blow up the rest of the routes module on dashboard boot.
        from tools.lessons_status import build_report
        report = build_report(refresh=refresh)
        payload = {"now": time.time(), **report}
        h._send(200, json.dumps(payload).encode(), "application/json")
    except Exception as exc:  # noqa: BLE001
        log.warning("lessons/status failed: %s", exc)
        send_error(h, exc)


GET_ROUTES = [
    (equals("/api/lessons/status"), _serve_lessons_status),
]

POST_ROUTES: list = []
