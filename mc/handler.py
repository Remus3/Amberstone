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

from mc import auth, routes

log = logging.getLogger("rc.mc.handler")

# RC is single-operator and these bodies are tiny (an action plus an
# idempotency key). Mirrors the dashboard's 1 MiB cap.
_MAX_POST_BYTES = 1 * 1024 * 1024


class Handler(BaseHTTPRequestHandler):
    server_version = "RCMissionControl/1.0"

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
        """Route access logs into RC logging instead of stderr."""
        log.info("%s %s", self.address_string(), fmt % args)

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
            log.warning("do_GET %s: %s", self.path, exc)
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
            payload = json.loads(raw.decode("utf-8", errors="replace")) if raw else {}
            for matcher, handler in routes.POST_ROUTES:
                if matcher(self.path):
                    handler(self, payload)
                    return
            self._send_json(404, {"ok": False, "error": "not found"})
        except json.JSONDecodeError:
            self._send_json(400, {"ok": False, "error": "invalid json"})
        except Exception as exc:  # noqa: BLE001 - never take the server down
            log.warning("do_POST %s: %s", self.path, exc)
            self._send_json(500, {"ok": False, "error": "internal error"})
