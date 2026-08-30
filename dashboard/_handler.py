"""Dashboard HTTP request handler.

Tier 2 helper-shake (2026-05-01): extracted from web_dashboard.py.

`Handler` is the `BaseHTTPRequestHandler` subclass driving every
:8888 request. It owns:

  * `do_GET`  - delegates to `dashboard._dispatch.dispatch_get`,
                falls through to the agents-supervisor proxy for
                paths only :8890 implements, else 404
  * `do_POST` - same-origin CSRF guard, 411 on a chunked body (no
                Content-Length means no cap, no deadline and no shape
                check apply; the guard reads EVERY Transfer-Encoding
                header, not just the first). A body sent with neither
                Content-Length nor Transfer-Encoding is still read as
                empty - that is correct HTTP, not a second bypass.
                Then 1-MiB body cap, read deadline, JSON decode,
                dict-or-400, then delegates to
                `dashboard._dispatch.dispatch_post`, else 404
  * `log_message` / `_peer` - restore the two properties the stdlib
                gives every handler and an override silently drops:
                control characters escaped (`_scrub_log`) so a request
                target cannot inject into `logs/`, and the client
                address prefixed so a rejection is attributable
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

import hmac
import json
import logging
import os
import time
from http.server import BaseHTTPRequestHandler

from dashboard import _dispatch

log = logging.getLogger("rc.web_dashboard")

# Lane 8, 2026-08-30: the stdlib's own log hardening, which this module used
# to opt out of by accident. `BaseHTTPRequestHandler.log_message` translates
# C0 controls, DEL and the C1 range to `\xHH` before writing - OVERRIDING the
# method silently drops that, and the request target is attacker-controlled
# from anywhere the `HOST = "::"` bind reaches (dashboard/server.py:35).
# Measured: `GET /api/<ESC>[31m...` put a raw 0x1b into the record, and the
# sink is logs/YYYY-MM-DD.log, which the operator reads in a terminal.
#
# Borrowed from the stdlib rather than re-rolled so it tracks any future
# widening of the table; the fallback covers a Python that drops the private
# attribute, and is asserted equivalent by tests.
_CONTROL_CHAR_TABLE = getattr(BaseHTTPRequestHandler, "_control_char_table", None)
_SCRUB_RANGES = tuple(range(0x00, 0x20)) + tuple(range(0x7F, 0xA0))


def _scrub_log(text: str) -> str:
    """Escape control characters so a request cannot inject into the log."""
    if _CONTROL_CHAR_TABLE is not None:
        return text.translate(_CONTROL_CHAR_TABLE)
    # The backslash escape is not decoration: without it a client can type
    # the literal six characters `\x1b[31m` and produce a log line byte-for-
    # byte identical to a scrubbed real ESC, so the escaping stops being
    # injective. The stdlib table maps `\` to `\\` for exactly this reason,
    # and the fallback is asserted equivalent to it by test.
    return "".join(
        f"\\x{ord(ch):02x}" if ord(ch) in _SCRUB_RANGES
        else ("\\\\" if ch == "\\" else ch)
        for ch in text
    )

# OVL2 (Electron Phase 6, Pengu Surface C): loopback origins always allowed
# to read responses cross-origin. The Pengu Loader plugin (pengu/) runs in
# the League client UX at https://127.0.0.1:<port> and fetches /api/state.
_CORS_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _cors_allowed_origin(origin: str) -> str | None:
    """Return the Origin to echo in Access-Control-Allow-Origin, or None.

    Client-origin-GATED, never wildcard: only a loopback origin (the Pengu
    Loader plugin's League-client origin) or an exact match in the optional
    ``RC_CORS_ALLOW_ORIGINS`` env allowlist (comma-separated) is echoed back.
    Everything else (remote hosts, the LAN bind, ``null``, absent) returns
    None so the browser blocks the cross-origin read. RC is LAN-only and this
    only governs READING GET responses (cross-origin POSTs are still rejected
    by ``_csrf_ok``), so echoing a same-machine loopback origin is safe.
    """
    if not origin or origin == "null":
        return None
    from urllib.parse import urlparse
    try:
        host = (urlparse(origin).hostname or "").lower()
    except Exception:  # noqa: BLE001
        return None
    if not host:
        return None
    if host in _CORS_LOOPBACK_HOSTS:
        return origin
    allow = os.environ.get("RC_CORS_ALLOW_ORIGINS", "")
    if allow:
        if origin in {o.strip() for o in allow.split(",") if o.strip()}:
            return origin
    return None


def proxy_error_status(path: str, upstream_code: int | None) -> int:
    """Status the :8888 proxy returns when a supervisor fetch fails.

    item 281: ``/api/minimap-crop`` has no frame to serve whenever the
    vision producer is idle/down (1-PC with no separate screen agent) - a
    normal condition, not an error. Forwarding the supervisor's non-2xx made
    the browser log a 502 console error on every ~2s poll. Collapse it to
    204 No Content so the panel hides quietly with zero console noise.
    Every other proxied path forwards the upstream code (or 502 when the
    supervisor is unreachable) so genuine outages still surface.
    """
    if path.startswith("/api/minimap-crop"):
        return 204
    return upstream_code if upstream_code is not None else 502


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

# RM-152: wall-clock budget for reading a POST body off the socket. The cap
# above bounds SIZE, which does nothing about a client that declares a legal
# length and then sends nothing - that pins a ThreadingHTTPServer thread until
# the client goes away, reachable from anywhere the "::" bind reaches, and it
# happens before the RC_DASH_TOKEN check so no token gates it.
#
# 10s is roughly three orders of magnitude more than a real 1 MiB body needs
# over loopback or the LAN, which is the only place RC's clients live.
_BODY_READ_TIMEOUT_S = 10.0

# High-frequency dashboard pollers - the dashboard hits these at 2Hz across
# every open tab and they make up ~90% of log_message volume (~7100 lines/hr
# in a 2.5h sample). Suppress at the BaseHTTPRequestHandler request-trace
# hook only; do not suppress lower-frequency endpoints (they retain
# diagnostic value when something breaks). Error/info log calls elsewhere
# in the handler are unaffected.
_SUPPRESS_LOG_PATHS = (
    "GET /api/state",
    "GET /api/decisions",
    "GET /api/decisions/heartbeat",
    "GET /api/vision-state",
    "GET /api/asset-stamp",
    "GET /api/ui-version",
    "GET /api/activity",
    "GET /api/env",
    "GET /api/locked-champion",
    "GET /api/minimap-crop",
    "POST /api/loadout/list",
)


class Handler(BaseHTTPRequestHandler):
    def _peer(self) -> str:
        """Client address for a log line, never raising.

        The stdlib prefixes ``address_string()`` to every log_message; this
        override used to drop it, so no HTTP log line named who sent the
        request - on a port reachable from the whole LAN and the tailnet.

        Narrowed deliberately rather than suppressed with a noqa: the
        stdlib body is ``return self.client_address[0]``, so the only ways
        it fails are a missing attribute or a client_address that is not
        indexable. Anything else is a real bug and should surface.
        """
        try:
            return self.address_string()
        except (AttributeError, IndexError, TypeError):
            return "?"

    def log_message(self, fmt: str, *a: object) -> None:
        msg = "HTTP " + (fmt % a if a else fmt)
        for needle in _SUPPRESS_LOG_PATHS:
            if needle in msg:
                return
        # Suppression matches on the raw text so the needle set keeps its
        # existing meaning; only what is EMITTED is scrubbed and attributed.
        log.debug("%s %s", self._peer(), _scrub_log(msg))

    def _minimap_no_frame(self) -> None:
        """Send 204 No Content for a minimap-crop with no frame to serve."""
        self._send(204, b"", "application/octet-stream")

    def _read_body_deadlined(self, n: int) -> bytes:
        """Read exactly ``n`` body bytes or raise ``TimeoutError``.

        The deadline is armed on the socket immediately before the read and
        restored in the ``finally``, so it is scoped to the request BODY and
        nothing else. The simpler alternative - a class-level ``timeout``,
        which socketserver arms on the connection in ``setup()`` - is wrong,
        though MEASURED 2026-08-04 not for the reason RM-152 assumed. It does
        NOT truncate the long responses on this socket: with it armed, an
        8 MiB ``_proxy_to_supervisor`` payload still arrived byte-complete at
        a reader stalled 3s mid-stream, and ``/api/state-stream`` still
        delivered frames. What it does break is the READ side, because it
        also deadlines the request line and headers: a client slow to speak,
        or one whose headers arrive in two packets with a gap, is aborted
        outright. Every 2 Hz poller opens a fresh connection (this handler
        answers HTTP/1.0, so there is no keep-alive) and would be exposed.

        The budget is absolute, not per-chunk: a trickle client that sends
        one byte every second must not be able to re-arm it forever, so the
        remaining time is recomputed on each pass rather than reset.

        With no socket to arm, the read is performed plainly. That is the
        correct semantics rather than a concession: the thing being defended
        against is a peer holding a socket open, so where there is no socket
        there is nothing to defend. It also matters for correctness of the
        REPLY, because this read runs ahead of the RC_DASH_TOKEN gate below
        and ``do_POST`` funnels every exception raised here into a 400 - so
        an unhandled failure to arm would answer bad_body to a caller who is
        owed 401.
        """
        sock = getattr(self, "connection", None)
        if not callable(getattr(sock, "settimeout", None)):
            return self.rfile.read(n)
        try:
            prior = sock.gettimeout()
        except OSError:
            prior = None
        deadline = time.monotonic() + _BODY_READ_TIMEOUT_S
        chunks: list[bytes] = []
        remaining = n
        try:
            while remaining > 0:
                left = deadline - time.monotonic()
                if left <= 0:
                    raise TimeoutError("body read exceeded the deadline")
                sock.settimeout(left)
                chunk = self.rfile.read(min(remaining, 65536))
                if not chunk:
                    break  # client closed early - caller sees a short body
                chunks.append(chunk)
                remaining -= len(chunk)
            return b"".join(chunks)
        finally:
            try:
                sock.settimeout(prior)
            except OSError:
                pass

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
            if proxy_error_status(self.path, e.code) == 204:
                self._minimap_no_frame()
                return
            # Forward the non-2xx response - 404 from supervisor should
            # still look like 404 to the dashboard, not 500 here.
            try:
                body = e.read() or b""
            except Exception:  # noqa: BLE001
                body = b""
            ctype = e.headers.get("Content-Type", "application/json") if e.headers else "application/json"
            self._send(e.code, body, ctype)
        except Exception as exc:  # noqa: BLE001
            # The exception text is scrubbed too. MEASURED: no currently
            # reachable exception here carries raw control bytes (int()'s
            # ValueError repr-escapes its operand, and urllib does not raise
            # on an ESC in the path at all), so this closes the CLASS rather
            # than a demonstrated instance - the alternative is betting on
            # every future exception type formatting its payload safely.
            log.debug("proxy %s: %s", _scrub_log(self.path), _scrub_log(str(exc)))
            if proxy_error_status(self.path, None) == 204:
                self._minimap_no_frame()
                return
            self._send(502, b'{"error":"supervisor_unreachable"}', "application/json")

    def _send(self, code: int, body: bytes, ctype: str, cache_control: str | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache_control or "no-store")
        # AUDIT 2026-04-29: Strict-Transport-Security so any browser that
        # touches the dashboard once over HTTPS never falls back to plain
        # HTTP for this origin again - eliminates the original Game-PC
        # "http://... not connecting" symptom permanently. 1-year max-age is
        # standard. We don't include preload / includeSubDomains because
        # this is LAN-only and we don't own the rest of the IP space.
        # Only set when the connection itself is TLS - when wrap_socket
        # is in play, the underlying request socket has an .cipher() attr.
        try:
            sock = self.connection
            if hasattr(sock, "cipher") and callable(sock.cipher):
                self.send_header("Strict-Transport-Security", "max-age=31536000")
        except Exception:  # noqa: BLE001
            pass
        # OVL2: client-origin-gated CORS. Echo the request Origin only when it
        # is an allowed cross-origin client (loopback / env allowlist), never
        # wildcard, so the Pengu Loader plugin can read /api/state. Vary:Origin
        # keeps any cache from serving one origin's ACAO to another.
        try:
            allow_origin = _cors_allowed_origin(self.headers.get("Origin", "") or "")
            if allow_origin:
                self.send_header("Access-Control-Allow-Origin", allow_origin)
                self.send_header("Vary", "Origin")
        except Exception:  # noqa: BLE001
            pass
        self.end_headers()
        try: self.wfile.write(body)
        except Exception: pass  # noqa: BLE001

    def do_GET(self) -> None:
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
        the same machine. Absent both headers -> allow (script caller).
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
        except Exception:  # noqa: BLE001
            # Don't block POSTs on parse errors - fail open with a log.
            log.debug("csrf_ok parse failed; allowing")
            return True

    def do_POST(self) -> None:
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
            log.warning("do_POST CSRF reject peer=%s path=%s origin=%r "
                        "referer=%r host=%r",
                        self._peer(),
                        _scrub_log(self.path),
                        self.headers.get("Origin"),
                        self.headers.get("Referer"),
                        self.headers.get("Host"))
            self._send(403, b'{"error":"cross_origin"}', "application/json")
            return
        # Lane 8, 2026-08-30: every body control below keys off Content-Length
        # - the 1 MiB cap, the read deadline, and the dict-or-400 guard. A
        # chunked request carries no Content-Length, so `n` was 0, the declared
        # body was never read off the socket, and the route was dispatched with
        # `{}` as though the client had sent an empty object. Measured against
        # the real Handler: a chunked POST /api/command reached
        # _dispatch._validate_request_body. That is a body silently DISCARDED,
        # not merely uncapped. Nothing in RC sends chunked (web/js uses fetch
        # with a string body, which sets Content-Length), so 411 is both
        # correct per RFC 7230 and free.
        # get_all, NOT get: `Message.get` returns only the FIRST header of a
        # repeated name, and the adversarial pass measured the bypass - two
        # Transfer-Encoding lines (`identity` then `chunked`) made `get` read
        # "identity", walked past this guard, and the body was discarded
        # exactly as before the fix. A comma-joined view of EVERY value is the
        # only shape that cannot be split across duplicate headers.
        _te = ", ".join(self.headers.get_all("Transfer-Encoding", []) or [])
        if "chunked" in _te.lower():
            log.warning("do_POST chunked body refused peer=%s path=%s",
                        self._peer(), _scrub_log(self.path))
            self.close_connection = True
            self._send(411, b'{"error":"length_required"}', "application/json")
            return
        try:
            n = int(self.headers.get("Content-Length", "0"))
            # Lane 8, 2026-08-03: the `n > _MAX_POST_BYTES` cap above does not
            # bound a NEGATIVE length - int("-1") is -1, which passes the cap,
            # and `self.rfile.read(n) if n else b""` then treats -1 as truthy
            # and reads to EOF. Measured against the real Handler on an
            # ephemeral port: the request hung with no response and completed
            # in 0.00s the instant the client shut down its write side. The
            # server binds HOST "::" on a ThreadingHTTPServer, so the cost is
            # one pinned thread per request, from anywhere on the LAN or
            # tailnet. Identical defect to the one closed in
            # vision_server/_http.py the same day (LEDGER 1177) - that sweep
            # did not look across files, so the wider surface kept it.
            if n < 0:
                self._send(400, b'{"error":"bad_body"}', "application/json")
                return
            if n > _MAX_POST_BYTES:
                self._send(413, b'{"error":"payload_too_large"}', "application/json")
                return
            # RM-152: the size cap above is not a bound on TIME. A legal
            # Content-Length with a body that never arrives pinned a handler
            # thread for as long as the client cared to hold the socket -
            # measured 4.01s with no response, released 0.18s after SHUT_WR.
            try:
                body = self._read_body_deadlined(n) if n else b""
            except TimeoutError:
                log.warning("do_POST body read timed out peer=%s path=%s "
                            "declared=%d",
                            self._peer(), _scrub_log(self.path), n)
                self.close_connection = True
                self._send(408, b'{"error":"body_read_timeout"}',
                           "application/json")
                return
            payload = json.loads(body.decode("utf-8", errors="replace")) if body else {}
        except Exception as exc:  # noqa: BLE001
            log.debug("do_POST bad_body: %s", _scrub_log(str(exc)))
            self._send(400, b'{"error":"bad_body"}', "application/json")
            return

        # Lane 8, 2026-08-03: a syntactically valid but NON-DICT body (`[1,2,3]`,
        # `"hello"`, `7`) reached the routes, which all call `payload.get(...)`.
        # Measured on the real handler: POST /api/command with `[1,2,3]` raised
        # an UNCAUGHT AttributeError at routes_state.py:516 - traceback to
        # stderr and the connection closed with NO HTTP RESPONSE AT ALL. Same
        # for /api/input; ds-preview, build-order and speak turned it into a
        # 500. `_dispatch._validate_request_body` already NOTICES this ("expected
        # dict, got list") and then returns without acting, because it is
        # soft-warn by design. Fixed here, at the single trust boundary, rather
        # than in ~40 route handlers: verified that zero POST routes consume a
        # positional/list body, so dict-or-400 costs nothing. Same root-cause
        # family as LEDGER 1180 - a payload shape assumed rather than asserted.
        if not isinstance(payload, dict):
            log.debug("do_POST non_dict_body: %s", type(payload).__name__)
            self._send(400, b'{"error":"bad_body"}', "application/json")
            return

        # D9: Control Endpoint Auth
        path_base = self.path.split("?", 1)[0]
        if path_base in ("/api/command", "/api/input", "/api/analyze", "/api/loop-control"):
            dash_token = os.environ.get("RC_DASH_TOKEN", "").strip()
            if dash_token:
                req_token = (self.headers.get("X-RC-Token") or "").strip()
                # Constant-time compare. Graded honestly: RC_DASH_TOKEN is set
                # NOWHERE in this deployment, so this gate does not run today
                # and the change is inert defense-in-depth, not a live fix.
                # Both operands are encoded because compare_digest rejects a
                # str containing any non-ASCII, and the header is caller-set.
                # `surrogatepass` is not decoration: os.environ round-trips
                # lone surrogates on Windows, and a plain .encode() then raises
                # UnicodeEncodeError, turning this 401 into a traceback. It
                # must be surrogatepass and NOT surrogateescape - the latter
                # only covers the U+DC80..U+DCFF range that decoding produces,
                # so it still raises on a U+D800 and the first version of this
                # fix was wrong until the regression test caught it. The header
                # itself is iso-8859-1-decoded and cannot carry a surrogate, so
                # the handler only ever fires on the configured side.
                if not hmac.compare_digest(
                        req_token.encode("utf-8", "surrogatepass"),
                        dash_token.encode("utf-8", "surrogatepass")):
                    log.warning("control endpoint auth reject: peer=%s path=%s",
                                self._peer(), path_base)
                    self._send(401, b'{"error":"unauthorized"}', "application/json")
                    return

        # Slice 2C-7d (2026-05-01): every POST route lives in
        # dashboard/routes_*. Dispatcher handled or it's a 404.
        if _dispatch.dispatch_post(self, payload):
            return
        self._send(404, b"not found", "text/plain")
