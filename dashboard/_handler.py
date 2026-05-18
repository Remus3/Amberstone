"""Dashboard HTTP request handler.

Tier 2 helper-shake (2026-05-01): extracted from web_dashboard.py.

`Handler` is the `BaseHTTPRequestHandler` subclass driving every
:8888 request. It owns:

  * `do_GET`  - delegates to `dashboard._dispatch.dispatch_get`,
                falls through to the agents-supervisor proxy for
                paths only :8890 implements, else 404
  * `do_POST` - same-origin CSRF guard, 1-MiB body cap, JSON
                decode, then delegates to `dashboard._dispatch.
                dispatch_post`, else 404
  * `_send`   - TLS-aware response writer; sets HSTS only when
                the connection itself is wrapped (matches the
                2026-04-29 audit)
  * `_csrf_ok` - same-origin guard rejecting cross-origin POSTs
                with browser-side Origin/Referer mismatches; script
                callers without those headers pass cleanly
  * `_proxy_to_supervisor` - forwards the active GET to
                127.0.0.1:8890 and streams the response back so the
                dashboard's side panels (adaptation, activity,
                minimap-crop, etc.) populate over the :8888 origin

`SUPERVISOR_PROXY_PATHS` is the curated set of GET prefixes that
only the agents supervisor implements. `SUPERVISOR_ORIGIN` is the
fixed loopback URL.

The shared logger name `rc.web_dashboard` is preserved so existing
log-filter rules keep matching.
"""
from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler

from dashboard import _dispatch

log = logging.getLogger("rc.web_dashboard")


# Paths that only the agents supervisor (:8890) implements. :8888 proxies
# GETs for these so the new dashboard, when accessed via :8888, gets full
# side-panel data without having to know about port 8890.
SUPERVISOR_PROXY_PATHS = (
    "/api/activity",
    "/api/adaptation",
    "/api/advisories",
    "/api/day-of-week",
    "/api/digest",
    "/api/duration",
    "/api/env",
    "/api/insight-card",
    "/api/locked-champion",
    "/api/minimap-crop",
    "/api/queue",
    "/api/session",
    "/api/session-games",
    "/api/task",          # /api/task/<id>
    "/api/time-of-day",
    "/api/trending",
)
SUPERVISOR_ORIGIN = "http://127.0.0.1:8890"

_MAX_POST_BYTES = 1 << 20


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *a):
        log.debug("HTTP " + fmt, *a)

    def _proxy_to_supervisor(self):
        """Forward the current GET to 127.0.0.1:8890 and stream the
        response back. Body is read in full first so we can set a proper
        Content-Length; requests here return <100KB (minimap PNG is the
        biggest) so memory cost is negligible."""
        import urllib.request as _ur
        import urllib.error as _ue
        url = SUPERVISOR_ORIGIN + self.path
        try:
            req = _ur.Request(url, method=self.command)
            # Pass through conditional headers the dashboard might send.
            for h in ("If-None-Match", "If-Modified-Since", "Accept"):
                v = self.headers.get(h)
                if v:
                    req.add_header(h, v)
            with _ur.urlopen(req, timeout=4) as r:
                body = r.read()
                ctype = r.headers.get("Content-Type", "application/octet-stream")
                self._send(r.status, body, ctype)
        except _ue.HTTPError as e:
            # Forward the non-2xx response - 404 from supervisor should
            # still look like 404 to the dashboard, not 500 here.
            try:
                body = e.read() or b""
            except Exception:
                body = b""
            ctype = e.headers.get("Content-Type", "application/json") if e.headers else "application/json"
            self._send(e.code, body, ctype)
        except Exception as exc:
            log.debug("proxy %s: %s", self.path, exc)
            self._send(502, b'{"error":"supervisor_unreachable"}', "application/json")

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        # AUDIT 2026-04-29: Strict-Transport-Security so any browser that
        # touches the dashboard once over HTTPS never falls back to plain
        # HTTP for this origin again - eliminates the original Game-PC
        # "http://… not connecting" symptom permanently. 1-year max-age is
        # standard. We don't include preload / includeSubDomains because
        # this is LAN-only and we don't own the rest of the IP space.
        # Only set when the connection itself is TLS - when wrap_socket
        # is in play, the underlying request socket has an .cipher() attr.
        try:
            sock = self.connection
            if hasattr(sock, "cipher") and callable(sock.cipher):
                self.send_header("Strict-Transport-Security", "max-age=31536000")
        except Exception:
            pass
        self.end_headers()
        try: self.wfile.write(body)
        except Exception: pass

    def do_GET(self):
        # Slice 2C (2026-05-01): all GET routes live in dashboard/routes_*.
        # Anything that doesn't match a registered route either falls
        # through to the agents-supervisor proxy (:8890) for routes that
        # only exist there, or returns 404.
        if _dispatch.dispatch_get(self):
            return
        if any(self.path == p or self.path.startswith(p + "?") or self.path.startswith(p + "/")
               for p in SUPERVISOR_PROXY_PATHS):
            # 2026-04-23: forward routes that only exist on the agents
            # supervisor (:8890) through :8888 so the new dashboard's
            # side panels (adaptation, activity, env, minimap-crop,
            # locked-champion, etc.) populate when accessed via 8888.
            self._proxy_to_supervisor()
        else:
            self._send(404, b"not found", "text/plain")

    def _csrf_ok(self) -> bool:
        """AUDIT 2026-04-28 (deferred-low-value): same-origin guard for
        POST endpoints. RC is LAN-only so cross-site CSRF is mitigated by
        threat model, but a misbehaving / compromised tab on Legion could
        still cross-origin-POST into 8888. Browsers send Origin (and
        Referer) on cross-origin POSTs; non-browser clients (curl, our
        own scripts) typically send neither and are allowed.

        Rule: if Origin or Referer is present, its hostname must match
        the request's Host header - OR the origin must itself be a local
        loopback address (127.0.0.1 / localhost) coming from a script on
        the same machine. Absent both headers → allow (script caller).
        """
        try:
            origin  = self.headers.get("Origin", "") or ""
            referer = self.headers.get("Referer", "") or ""
            if not origin and not referer:
                return True
            host = (self.headers.get("Host", "") or "").strip().lower()
            if not host:
                return False
            host_h, _, _ = host.partition(":")
            from urllib.parse import urlparse
            local_aliases = {"127.0.0.1", "localhost", "::1"}
            for src in (origin, referer):
                if not src:
                    continue
                # "null" Origin is what some sandboxed iframes / file://
                # contexts send. Treat as cross-origin.
                if src == "null":
                    return False
                p = urlparse(src)
                src_hp = (p.hostname or "").lower()
                if not src_hp:
                    return False
                # Same hostname is fine (port may differ - e.g. dashboard
                # opened via localhost vs LAN IP from same machine).
                if src_hp == host_h:
                    continue
                # Origin from local loopback when request host is the LAN
                # bind is also fine - script callers, dev probes.
                if src_hp in local_aliases and host_h not in local_aliases:
                    continue
                if host_h in local_aliases and src_hp in local_aliases:
                    continue
                # Anything else: reject.
                return False
            return True
        except Exception:
            # Don't block POSTs on parse errors - fail open with a log.
            log.debug("csrf_ok parse failed; allowing")
            return True

    def do_POST(self):
        # 2026-04-27 audit: cap POST body at 1 MiB. RC is LAN-only and the
        # legitimate inputs (chat text, /api/bridge messages) are tiny -
        # an unbounded read on Content-Length: 999999999 would let a LAN
        # attacker (or a misbehaving tab) allocate a multi-GB buffer per
        # request. Also: don't echo the exception message back to the
        # client, since urllib/json error strings can leak file paths or
        # unrelated headers.
        # AUDIT 2026-04-28 (deferred-low-value): same-origin CSRF guard.
        # Browser-driven cross-origin POSTs (Origin/Referer mismatch) are
        # rejected with 403; script callers without those headers pass.
        if not self._csrf_ok():
            log.warning("do_POST CSRF reject path=%s origin=%r referer=%r host=%r",
                        self.path,
                        self.headers.get("Origin"),
                        self.headers.get("Referer"),
                        self.headers.get("Host"))
            self._send(403, b'{"error":"cross_origin"}', "application/json")
            return
        try:
            n = int(self.headers.get("Content-Length", "0"))
            if n > _MAX_POST_BYTES:
                self._send(413, b'{"error":"payload_too_large"}', "application/json")
                return
            body = self.rfile.read(n) if n else b""
            payload = json.loads(body.decode("utf-8", errors="replace")) if body else {}
        except Exception as exc:
            log.debug("do_POST bad_body: %s", exc)
            self._send(400, b'{"error":"bad_body"}', "application/json")
            return

        # Slice 2C-7d (2026-05-01): every POST route lives in
        # dashboard/routes_*. Dispatcher handled or it's a 404.
        if _dispatch.dispatch_post(self, payload):
            return
        self._send(404, b"not found", "text/plain")
