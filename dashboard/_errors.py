# arch: shared JSON error envelope for the :8888 dashboard + :8895 Mission Control | section=dashboard | frozen=no
"""Scrubbed JSON error envelope shared by every dashboard/MC route module.

RM-134. This helper is the last-resort error path for BOTH surfaces: `:8888`
serves the dashboard route modules directly, and `mc/routes.py` splices the
`routes_loop_status` / `routes_loop_control` tables into `:8895`. CORRECTED
2026-09-18 (RM-239 / RM-242 adjudication): the superseded wording read "`:8888`
serves these route modules directly" of ALL of them, which is FALSE at HEAD for
BOTH spliced modules - `routes_loop_control` AND `routes_loop_status` are
MC-ONLY. Settled by executing the matchers, not by grep: the dashboard dispatch
source carries no reference to either, `/api/loop-control` and `/api/loop-status`
each match zero routes in both the `:8888` POST and GET tables, the MC route
table's sole POST entry resolves to `_serve_loop_control`, and the auth-tuple
entry in the dashboard handler is vestigial (auth runs, then 404). Each module's
own header records the same de-registration. Do NOT infer from the splice clause
above that either module is dual-surfaced - the splice is how they are served AT
ALL, not a second surface.
The splice half above is the TRUE half and is kept. It used to
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

from core.log_scrub import scrub_log

log = logging.getLogger("rc.web_dashboard")

# The wording already used by dashboard/builders_last_match.py for the same class
# of failure - keep one phrase so the UI never shows two dialects of "it broke".
GENERIC_ERROR = "internal error - see logs"


def send_error(h, exc: Exception, status: int = 500, *,
               public_msg: str | None = None, fields: dict | None = None,
               log_traceback: bool = False) -> None:
    """Send a user-safe JSON error envelope and log the raw cause.

    ``exc`` never reaches the response body. Pass ``public_msg`` for a curated
    degraded-mode line; omit it for the generic one.

    RM-835: ``fields`` are a route's own envelope keys, placed before
    ``error`` (``{"ok": False}`` keeps a route's ``{ok, error}`` shape), so a
    route can adopt this path without changing the keys its client reads.
    They are server-authored constants - never put the exception in them -
    and an ``error`` key among them is overwritten by the fixed line.
    ``log_traceback=True`` adds the traceback to the one log line (the
    logger's RM-811 scrub filter renders it).
    """
    msg = public_msg or GENERIC_ERROR
    # RM-811 residuals: the raw cause is scrubbed (RM-321) - this is the
    # last-resort path of every route, Mission Control's two included, and an
    # exception's text can carry the client's own characters.
    log.warning("%s: %s: %s", msg, type(exc).__name__, scrub_log(str(exc)),
                exc_info=exc if log_traceback else None)
    body = dict(fields or {})
    body["error"] = msg
    payload = json.dumps(body).encode("utf-8")
    h._send(status, payload, "application/json")


# RM-838: the fixed line a :8888 proxy sends in place of an upstream's non-2xx
# body. The proxies used to forward that body (and the supervisor proxy its
# Content-Type) verbatim, so any upstream that put exception text in an error
# reply leaked it through :8888. Decision: scrub here, at the trust boundary,
# rather than rely on every upstream staying clean - the live consumers branch
# on the STATUS (kept), never on the error body.
_UPSTREAM_ERROR_LINES = {
    400: "bad request",
    401: "unauthorized",
    403: "forbidden",
    404: "not found",
}
UPSTREAM_ERROR = "upstream error - see logs"
_UPSTREAM_LOG_CAP = 200


def forward_upstream_error(h, status: int, body: bytes, where: str, *,
                           lines: dict[int, str] | None = None) -> None:
    """Send an upstream's non-2xx status with a fixed JSON line, never its body.

    ``lines`` lets a route keep a status word its client knows (the
    ``/api/lcu-cmd-result`` pollers' 404 ``pending``). The upstream body is
    logged once at debug (a polled 404 must not flood the log), capped and
    scrubbed, with the status.
    """
    snippet = (body or b"")[:_UPSTREAM_LOG_CAP].decode("utf-8", "replace")
    log.debug("%s: upstream HTTPError %s: %s", scrub_log(where), status,
              scrub_log(snippet))
    line = ((lines or {}).get(status) or _UPSTREAM_ERROR_LINES.get(status)
            or UPSTREAM_ERROR)
    h._send(status, json.dumps({"error": line}).encode("utf-8"),
            "application/json")
