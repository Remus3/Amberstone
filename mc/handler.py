# arch: Mission Control HTTP handler (minimal, no dashboard Handler) | section=mc | frozen=no
"""The Mission Control request handler.

Deliberately minimal. It implements exactly what the two loop-route modules
consume - `_send(code, body, ctype)` and a parsed JSON POST body - plus static
file serving for web/mc/. It does NOT subclass or import the dashboard's
Handler, which carries game state, supervisor proxying and vision auth.

CSRF: the bearer requirement on POST is itself the cross-origin defence. A
browser cannot attach an Authorization header cross-origin without a CORS
preflight, and this server answers no preflight, so a hostile page cannot
drive this surface even from a machine that can reach it.

Static assets are served no-store: web/mc/ is outside the dashboard's
compute_asset_hash sweep, so there is no cache-busting hash on these URLs and
a cached mc.js would silently serve stale control-plane code.
"""
from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler
from pathlib import Path

from mc import auth, routes

log = logging.getLogger("rc.mc.handler")

WEB_DIR = Path(__file__).resolve().parent.parent / "web" / "mc"

# RC is single-operator and these bodies are tiny (an action plus an
# idempotency key). Mirrors the dashboard's 1 MiB cap.
_MAX_POST_BYTES = 1 * 1024 * 1024

_CTYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
}


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

    # -- static ------------------------------------------------------

    def _serve_static(self) -> bool:
        rel = "index.html" if self.path in ("/", "") else self.path.lstrip("/")
        rel = rel.split("?", 1)[0]
        target = (WEB_DIR / rel).resolve()
        # Path traversal guard: the resolved path must stay inside WEB_DIR.
        # is_relative_to is a real path-component check. A plain
        # str(target).startswith(str(WEB_DIR)) has a sibling-prefix bypass:
        # web/mc-evil/ starts with the same characters as web/mc/, so a
        # string prefix check lets ../mc-evil/secret.txt through even
        # though mc-evil is a sibling directory, not a subpath of mc.
        if not target.is_relative_to(WEB_DIR.resolve()):
            return False
        if not target.is_file():
            return False
        ctype = _CTYPES.get(target.suffix, "application/octet-stream")
        self._send(200, target.read_bytes(), ctype)
        return True

    # -- verbs -------------------------------------------------------

    def do_GET(self) -> None:
        try:
            for matcher, handler in routes.GET_ROUTES:
                if matcher(self.path):
                    handler(self)
                    return
            if self._serve_static():
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
