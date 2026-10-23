# arch: Mission Control HTTP handler (HEADLESS - JSON only, no static assets) | section=mc | frozen=no
"""The Mission Control request handler.

Deliberately minimal. It implements exactly what the two loop-route modules
consume - `_send(code, body, ctype)` and a parsed JSON POST body. It does NOT
subclass or import the dashboard's Handler, which carries game state,
supervisor proxying and vision auth.

HEADLESS SINCE THE MC WEB UI WAS RETIRED. This server used to also serve
`web/mc/` (index.html, mc.js, mc.css, arm_confirm.js) as a phone-friendly page.
That page and its static-serving branch are gone: the surviving consumers are
curl, scripts and the loop itself, and every one of them speaks JSON. The
control plane - the bearer perimeter, `/api/loop-status` and all nine
`/api/loop-control` actions - is unchanged, which is the whole point of
retiring the VIEW half rather than the process.

The one thing the page carried that was NOT view-only was the arm-then-confirm
gate in `web/mc/arm_confirm.js`. That was ported to the SERVER before this
removal, not deleted with it - see `dashboard/_arm_confirm.py` and
`tests/test_arm_confirm_server_gate.py`. Deleting a client cannot make a server
safer, so a UI-only guard was never a guard at all.

CSRF: the bearer requirement on POST is itself the cross-origin defence. A
browser cannot attach an Authorization header cross-origin without a CORS
preflight, and this server answers no preflight, so a hostile page cannot
drive this surface even from a machine that can reach it. With the static tree
gone there is also no same-origin page left to host such an attempt.
"""
from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler

from core.http_head_deadline import HeadDeadlineMixin
from core.http_host_gate import HostAllowlistMixin
from core.log_scrub import scrub_log
from mc import auth, routes

log = logging.getLogger("rc.mc.handler")

# RC is single-operator and these bodies are tiny (an action plus an
# idempotency key). Mirrors the dashboard's 1 MiB cap.
_MAX_POST_BYTES = 1 * 1024 * 1024


def _peer(h) -> str:
    """The client address for a log line, or '?' when ``h`` has none (the
    fake-request tests drive ``do_POST`` on a bare object)."""
    try:
        return h.address_string()
    except (AttributeError, IndexError, TypeError):
        return "?"


class Handler(HostAllowlistMixin, HeadDeadlineMixin, BaseHTTPRequestHandler):
    server_version = "RCMissionControl/1.0"
    # RM-819: the shared RM-759 Host gate (core/http_host_gate.py - core,
    # never dashboard/), FIRST so it runs on the parsed head: a Host this
    # machine does not answer to is 421 before any route (DNS rebinding);
    # a head whose parse lost lines (RM-773) or a target that is not
    # origin-form (RM-774) is 400; HTTP/0.9 is closed. The bearer still
    # gates every POST; this closes the unauthenticated GETs to a rebound
    # page.
    host_refusal_log = log
    # RM-747: one TOTAL deadline for the request line + headers
    # (``head_read_timeout_s``, core/http_head_deadline.py, shared with the
    # :8888 dashboard, RM-744), removed once the head is parsed. mc/server.py
    # puts the socket back to no timeout after its TLS handshake (RM-739),
    # so without it an idle handshaken client held its thread indefinitely.
    # Never a class-level ``timeout``: it is per receive and lasts the whole
    # connection (RM-152).

    # -- response helper the route modules call ----------------------

    def _send(self, code: int, body: bytes, ctype: str,
              cache_control: str | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache_control or "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass  # client hung up; nothing to do and nothing to log loudly

    def _send_json(self, code: int, payload: dict) -> None:
        self._send(code, json.dumps(payload).encode("utf-8"), "application/json")

    def log_message(self, fmt: str, *args) -> None:
        """Route access logs into RC logging instead of stderr.

        RM-321: overriding this drops the stdlib's control-character
        escaping, and :8895 listens on the tailnet address at INFO, so the
        message is scrubbed via core.log_scrub (never dashboard/ - mc/ is
        deliberately decoupled from it).
        """
        log.info("%s %s", self.address_string(), scrub_log(fmt % args))

    # -- verbs -------------------------------------------------------

    def do_GET(self) -> None:
        """Route table only. Nothing on this port reads the filesystem.

        There is no static branch and no document root, so the whole class of
        path-traversal question this handler used to have to answer - a
        resolved path escaping WEB_DIR, a sibling-prefix bypass on
        `web/mc-evil/` - is now structurally absent rather than guarded. Any
        unmatched path, traversal-shaped or not, is a JSON 404.
        """
        try:
            for matcher, handler in routes.GET_ROUTES:
                if matcher(self.path):
                    handler(self)
                    return
            self._send_json(404, {"ok": False, "error": "not found"})
        except Exception as exc:  # noqa: BLE001 - never take the server down
            # RM-811: the request target and the exception text are the
            # client's (RM-321 class), so both are scrubbed.
            log.warning("do_GET %s: %s", scrub_log(self.path),
                        scrub_log(str(exc)))
            self._send_json(500, {"ok": False, "error": "internal error"})

    def do_POST(self) -> None:
        try:
            ok, status, body = auth.check(self.headers.get("Authorization"))
            if not ok:
                self._send_json(status, body)
                return
            try:
                n = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                # Malformed header (e.g. "not-a-number") - a 400, not the
                # generic 500 the bare int() used to fall through to.
                self._send_json(400, {"ok": False, "error": "invalid content-length"})
                return
            if n < 0:
                # A negative Content-Length is malformed, not "too large" -
                # `n > _MAX_POST_BYTES` is never true for a negative n, so
                # without this check rfile.read(n) runs with n unmodified,
                # and on a real socket-backed rfile a negative size reads
                # until EOF: unbounded, defeating the cap below entirely.
                self._send_json(400, {"ok": False, "error": "invalid content-length"})
                return
            if n > _MAX_POST_BYTES:
                self._send_json(413, {"ok": False, "error": "payload too large"})
                return
            raw = self.rfile.read(n) if n else b""
            # RM-760b: deep nesting raises RecursionError and an over-long
            # integer raises ValueError (int max-str-digits), neither a
            # JSONDecodeError, so both used to fall through to the 500 below.
            # Only the parse is wrapped: a route raising either stays a 500.
            try:
                payload = (json.loads(raw.decode("utf-8", errors="replace"))
                           if raw else {})
            except (ValueError, RecursionError) as exc:
                # RM-811: this 400 used to log nothing, so a client sending
                # garbage to the control plane left no trace. Only a caller
                # past the bearer check reaches it, so one line per request
                # cannot be driven by a stranger. The reply stays fixed.
                log.warning("do_POST %s from %s: invalid JSON body (%s: %s) "
                            "refused (400)", scrub_log(self.path), _peer(self),
                            type(exc).__name__, scrub_log(str(exc)))
                self._send_json(400, {"ok": False, "error": "invalid json"})
                return
            for matcher, handler in routes.POST_ROUTES:
                if matcher(self.path):
                    handler(self, payload)
                    return
            self._send_json(404, {"ok": False, "error": "not found"})
        except json.JSONDecodeError as exc:
            # A route's own JSON parse; logged like the body parse (RM-811).
            log.warning("do_POST %s from %s: invalid JSON in a route (%s) "
                        "refused (400)", scrub_log(self.path), _peer(self),
                        scrub_log(str(exc)))
            self._send_json(400, {"ok": False, "error": "invalid json"})
        except Exception as exc:  # noqa: BLE001 - never take the server down
            # RM-811: the request target and the exception text are the
            # client's (RM-321 class), so both are scrubbed.
            log.warning("do_POST %s: %s", scrub_log(self.path),
                        scrub_log(str(exc)))
            self._send_json(500, {"ok": False, "error": "internal error"})
