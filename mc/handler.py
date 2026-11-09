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
import re
import time
from http.server import BaseHTTPRequestHandler

from core.http_head_deadline import HeadDeadlineMixin
from core.http_host_gate import HostAllowlistMixin
from core.log_scrub import scrub_log
from mc import auth, routes

log = logging.getLogger("rc.mc.handler")

# RC is single-operator and these bodies are tiny (an action plus an
# idempotency key). Mirrors the dashboard's 1 MiB cap.
_MAX_POST_BYTES = 1 * 1024 * 1024

# s144 true-audit F4 (S144-T-689): one ABSOLUTE budget for the request body,
# the :8888 dashboard's RM-152 value. The head already has its own deadline
# (RM-747); before this the body had none, so a caller that declared 100
# bytes and sent one held its handler thread for as long as it kept the
# socket open (measured: no reply at all until the client closed).
_BODY_READ_TIMEOUT_S = 10.0

# s144 true-audit F2 (S144-T-689): RFC 9110 8.6 - Content-Length is 1*DIGIT.
# `int()` is not that grammar: it accepts "1_0" (PEP 515) and "+2", so the
# body was framed by a value no HTTP peer would agree with (measured: "1_0"
# read 10 bytes). Optional whitespace around the field value is legal and is
# stripped. A short cap on the digit count keeps a 5000-digit value from ever
# reaching int().
_CONTENT_LENGTH_RE = re.compile(r"[0-9]{1,16}")


def _header_values(headers, name: str) -> list:
    """EVERY value of header ``name``, not just the first.

    ``Message.get`` returns only the first of a repeated header, which is how
    two Transfer-Encoding lines (``identity`` then ``chunked``) walked past
    the dashboard's first chunked guard. A plain mapping (the fake-request
    tests) has at most one value per name.
    """
    get_all = getattr(headers, "get_all", None)
    if callable(get_all):
        return list(get_all(name, []) or [])
    value = headers.get(name)
    return [] if value is None else [value]


def _content_length(headers) -> int | None:
    """The declared body length, 0 when absent, None when malformed.

    Malformed = any value that is not 1*DIGIT, or two values that disagree
    (RFC 9112 6.3: unrecoverable). Identical repeats are one value.
    """
    values = {str(v).strip() for v in _header_values(headers, "Content-Length")}
    if not values:
        return 0
    if len(values) != 1:
        return None
    (value,) = values
    if not _CONTENT_LENGTH_RE.fullmatch(value):
        return None
    return int(value)


def _peer(h) -> str:
    """The client address for a log line, or '?' when ``h`` has none (the
    fake-request tests drive ``do_POST`` on a bare object)."""
    try:
        return h.address_string()
    except (AttributeError, IndexError, TypeError):
        return "?"


def _refuse(h, status: int, error: str, why: str) -> None:
    """A fixed framing refusal, logged with the peer, connection closed.

    Every caller is past the bearer check, so one line per request cannot
    be driven by a stranger. The connection closes because an unread or
    unframed body is still on the stream.
    """
    log.warning("do_POST %s from %s: %s refused (%d)",
                scrub_log(h.path), _peer(h), why, status)
    h.close_connection = True
    h._send_json(status, {"ok": False, "error": error})


def _read_body_deadlined(h, n: int) -> bytes:
    """Read up to ``n`` body bytes inside one absolute deadline (F4).

    Raises ``TimeoutError`` once ``_BODY_READ_TIMEOUT_S`` is spent. The
    budget is recomputed on every pass, never reset, so a client
    trickling one byte at a time cannot re-arm it. The socket's own
    timeout is restored in the ``finally``, so the deadline covers the
    body and nothing else. With no socket (an in-process double) the
    read is plain: there is no peer holding a connection to defend
    against. A client that closes early returns a SHORT result; the
    caller compares it with ``n``.
    """
    sock = getattr(h, "connection", None)
    if not callable(getattr(sock, "settimeout", None)):
        return h.rfile.read(n)
    try:
        prior = sock.gettimeout()
    except OSError:
        prior = None
    read1 = getattr(h.rfile, "read1", None) or h.rfile.read
    deadline = time.monotonic() + _BODY_READ_TIMEOUT_S
    chunks: list[bytes] = []
    remaining = n
    try:
        while remaining > 0:
            left = deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError("body read exceeded the deadline")
            sock.settimeout(left)
            # read1, not read: a buffered ``read(k)`` loops raw receives
            # until it has k bytes, and each receive gets the full ``left``
            # again, so a one-byte trickle never came back here to have the
            # budget checked. A receive that outlives ``left`` raises
            # socket.timeout, which is TimeoutError since Python 3.10.
            chunk = read1(min(remaining, 65536))
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


def _fail(h, verb: str, exc: Exception) -> None:
    """The one exit for an exception a request let out (F7 / F8).

    A hang-up (any ``ConnectionError``) is the client's act, not a server
    fault: DEBUG, and no reply to a socket that is gone. Anything else is
    logged at WARNING with the client's text scrubbed (RM-811) and gets the
    fixed 500 - unless the reply already began, when writing again would
    corrupt it. The connection closes either way: a request that died
    part-way leaves the stream in an unknown state. The 500 write itself
    hitting a dead socket stays here instead of escaping into
    socketserver's stderr traceback.
    """
    h.close_connection = True
    path = scrub_log(str(getattr(h, "path", "?")))
    if isinstance(exc, ConnectionError):
        log.debug("do_%s %s: client went away (%s)", verb, path,
                  type(exc).__name__)
        return
    started = bool(getattr(h, "_reply_started", False))
    log.warning("do_%s %s: %s (reply_started=%s)", verb, path,
                scrub_log(str(exc)), started)
    if started:
        return
    try:
        h._send_json(500, {"ok": False, "error": "internal error"})
    except OSError as send_exc:
        log.debug("do_%s %s: 500 not delivered (%s)", verb, path,
                  type(send_exc).__name__)


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

    # s144 true-audit F7 (S144-T-689): set by send_response, so the reply
    # guard can tell a route that failed BEFORE it replied (answer 500) from
    # one that failed after its status line went out (write nothing - a
    # second status line corrupted the first reply, measured as
    # `200 ...{"ok": true}HTTP/1.0 500 ...` on one connection). Reset at the
    # start of every request; the dashboard's RM-1288 shape.
    _reply_started = False

    def send_response(self, code, message=None):
        self._reply_started = True
        super().send_response(code, message)

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
        except ConnectionError:
            # Client hung up; nothing to do and nothing to log loudly.
            # ConnectionError, not (BrokenPipeError, ConnectionResetError):
            # a hang-up on Windows is usually ConnectionAbortedError
            # (WinError 10053), which the narrower pair let escape (F8).
            self.close_connection = True

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
        self._reply_started = False
        try:
            for matcher, handler in routes.GET_ROUTES:
                if matcher(self.path):
                    handler(self)
                    return
            self._send_json(404, {"ok": False, "error": "not found"})
        except Exception as exc:  # noqa: BLE001 - never take the server down
            # RM-811: the request target and the exception text are the
            # client's (RM-321 class), so _fail scrubs both.
            _fail(self, "GET", exc)

    def do_POST(self) -> None:
        self._reply_started = False
        try:
            # The bearer gate stays FIRST: no framing verdict is an oracle for
            # a caller who does not hold the token.
            ok, status, body = auth.check(self.headers.get("Authorization"))
            if not ok:
                self._send_json(status, body)
                return
            # F1 (S144-T-689): any Transfer-Encoding is 411. RFC 9112 6.3:
            # it overrides Content-Length, and this handler decodes no
            # transfer coding, so the body cannot be framed. Before this a
            # chunked POST had its body discarded and ran its route with {}
            # (the :8888 fix, LEDGER 1279, never reached this sibling).
            # EVERY value is read: `get` sees only the first of a repeat. The
            # header's PRESENCE is the refusal, an empty value included.
            if _header_values(self.headers, "Transfer-Encoding"):
                _refuse(self, 411, "length required", "Transfer-Encoding body")
                return
            # F2 / F3: 1*DIGIT and one agreed value, else 400. This also
            # covers a negative length, which `n > _MAX_POST_BYTES` never
            # catches and on which a socket rfile.read(-1) reads to EOF.
            n = _content_length(self.headers)
            if n is None:
                _refuse(self, 400, "invalid content-length",
                             "malformed Content-Length")
                return
            if n > _MAX_POST_BYTES:
                _refuse(self, 413, "payload too large",
                             f"Content-Length {n} over the cap")
                return
            # F4: one absolute deadline on the body (the head has RM-747's).
            try:
                raw = _read_body_deadlined(self, n) if n else b""
            except TimeoutError:
                _refuse(self, 408, "body read timeout",
                             f"body not complete in {_BODY_READ_TIMEOUT_S}s")
                return
            # F5: a body that ended short is never parsed as if complete.
            if len(raw) != n:
                _refuse(self, 400, "incomplete body",
                             f"body {len(raw)} of {n} bytes")
                return
            # RM-760b: deep nesting raises RecursionError and an over-long
            # integer raises ValueError (int max-str-digits), neither a
            # JSONDecodeError, so both used to fall through to the 500 below.
            # F6: strict UTF-8 (RFC 8259 8.1) - a UnicodeDecodeError is a
            # ValueError, so invalid bytes are 400, never U+FFFD stand-ins.
            # Only the parse is wrapped: a route raising either stays a 500.
            try:
                payload = json.loads(raw.decode("utf-8")) if raw else {}
            except (ValueError, RecursionError) as exc:
                # RM-811: this 400 used to log nothing, so a client sending
                # garbage to the control plane left no trace. The reply
                # stays fixed.
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
            self.close_connection = True
            if not getattr(self, "_reply_started", False):
                try:
                    self._send_json(400, {"ok": False, "error": "invalid json"})
                except OSError:
                    pass
        except Exception as exc:  # noqa: BLE001 - never take the server down
            # RM-811: the request target and the exception text are the
            # client's (RM-321 class), so _fail scrubs both.
            _fail(self, "POST", exc)
