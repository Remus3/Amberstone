# arch: shared JSON error envelope for the :8888 dashboard + :8895 Mission Control | section=dashboard | frozen=no
"""Scrubbed JSON error envelope shared by every dashboard/MC route module.

RM-134. This helper is the last-resort error path for BOTH surfaces: `:8888`
serves these route modules directly, and `mc/routes.py` splices the very same
`routes_loop_status` / `routes_loop_control` tables into `:8895`. It used to
serialize ``str(exc)[:200]`` verbatim, so a filesystem path, a module name or a
secret-shaped traceback fragment reached the wire on any unhandled route error.

CLAUDE.md Error Handling: render a friendly degraded-mode message to the client
and log the raw error. `agents/_supervisor_http._send_error` already worked this
way; this is the same contract for the dashboard/MC envelope. Callers that have
a better user-facing wording pass ``public_msg``; everyone else gets the generic
line. The raw cause is logged here as well as at the call site, so a future
route that forgets its own ``log.warning`` still leaves a trail.

Pinned by tests/test_dashboard_error_scrub_rm134.py.
"""
from __future__ import annotations

import json
import logging

log = logging.getLogger("rc.web_dashboard")

# The wording already used by dashboard/builders_last_match.py for the same class
# of failure - keep one phrase so the UI never shows two dialects of "it broke".
GENERIC_ERROR = "internal error - see logs"


def send_error(h, exc: Exception, status: int = 500, *,
               public_msg: str | None = None) -> None:
    """Send a user-safe JSON error envelope and log the raw cause.

    ``exc`` never reaches the response body. Pass ``public_msg`` for a curated
    degraded-mode line; omit it for the generic one.
    """
    msg = public_msg or GENERIC_ERROR
    log.warning("%s: %s: %s", msg, type(exc).__name__, exc)
    payload = json.dumps({"error": msg}).encode("utf-8")
    h._send(status, payload, "application/json")
