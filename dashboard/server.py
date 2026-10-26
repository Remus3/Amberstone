"""HTTP/TLS server + bootstrap for the dashboard.

Slice 2D (2026-05-01): extracts _DualProtocolHTTPServer + cert lookup
+ start_dashboard from web_dashboard.py.

Owns the HTTP/TLS multiplexing socket layer (the 2026-04-28 Game-PC fix
for plain-HTTP clients hanging on a TLS-only listen socket), the cert
lookup at ops/tls/rc.pem + rc-key.pem, and the daemon-thread bootstrap
that spins up the vision_tracker and obs_publisher loops alongside
the server. (decision_detector moved to agents/supervisor.py - T3 #15.)

Tier 2 #7 (2026-05-01): `Handler` was extracted out of web_dashboard.py
into `dashboard/_handler.py`. We import it directly here. The
`web_dashboard._APP_DIR` mutation below is kept as a defensive backward-
compat hook for any external caller that still reads it; nothing in
the dashboard package consumes it anymore.
"""
from __future__ import annotations

import functools
import html
import ipaddress
import logging
import os
import re
import socket
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

_log = logging.getLogger("rc.web_dashboard")

PORT = 8888
# Dual-stack bind. The tailnet node name resolves IPv6-first on clients (Tailscale AAAA
# fd7a:... + link-local fe80::). A v4-only 0.0.0.0 listener left the browser's
# IPv6 connect attempts - including the long-lived /api/state-stream EventSource
# that carries live data - failing with no listener, so the hostname "loaded the
# page but showed no live data" (page survived via IPv4 fallback) while typed
# IPv4 URLs worked fully. "::" + IPV6_V6ONLY=0 answers both families. (2026-06-02)
# HOST is the DEFAULT bind; the live one is bind_host() (PKG-5, below).
HOST = "::"

# PKG-5 (docs/PACKAGING_PLAN.md, security MUST-FIX M5): the bind host is an
# IP literal from RC_DASH_BIND; unset keeps HOST (Legion unchanged - the
# tailnet view and LAN page viewers depend on the wildcard). The packaged
# launcher sets LOOPBACK_BIND (127.0.0.1: the shell's default origin, and
# Chromium treats it as a secure context without a cert).
BIND_ENV = "RC_DASH_BIND"
LOOPBACK_BIND = "127.0.0.1"


def bind_host(environ=None) -> str:
    """The host :8888 binds: ``RC_DASH_BIND`` when set, else ``HOST``.

    Only an IP literal is accepted - no name resolution at bind time, and no
    host name has to be written anywhere. Anything else FAILS CLOSED to
    ``LOOPBACK_BIND`` (logged): a typo must narrow exposure, never widen it.
    """
    env = os.environ if environ is None else environ
    value = (env.get(BIND_ENV) or "").strip()
    if not value:
        return HOST
    try:
        ipaddress.ip_address(value)
    except ValueError:
        _log.warning("%s=%r is not an IP literal - binding %s instead (PKG-5)",
                     BIND_ENV, value[:64], LOOPBACK_BIND)
        return LOOPBACK_BIND
    return value


def _family_for(host: str) -> int:
    """AF_INET for an IPv4 literal; AF_INET6 (the dual-stack default) for
    every other value, so ``"::"`` / ``"::1"`` / ``""`` bind as before."""
    try:
        if ipaddress.ip_address(host).version == 4:
            return socket.AF_INET
    except ValueError:
        pass
    return socket.AF_INET6


# PKG-5 (M5): who may drive the control endpoints (dashboard/_handler.py
# ``is_control_endpoint``: /api/lcu-cmd, /api/loadout/apply,
# /api/sr-draft/apply, /api/command, /api/input, /api/analyze, every POST
# under /api/decisions/) when no RC_DASH_TOKEN is configured. Tailscale
# numbers its nodes from the CGNAT block and its own ULA /48.
CONTROL_NETS_ENV = "RC_DASH_CONTROL_NETS"
TAILNET_NETS = (
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("fd7a:115c:a1e0::/48"),
)


def _peer_ip(value):
    """An address string as an ``ipaddress`` object, or None.

    The %-zone is dropped (a link-local peer and the address it reached
    share it) and a v4-mapped IPv6 address - what the dual-stack listener
    reports for every IPv4 client - is unwrapped to its IPv4 form.
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        ip = ipaddress.ip_address(value.split("%", 1)[0])
    except ValueError:
        return None
    mapped = getattr(ip, "ipv4_mapped", None)
    return mapped if mapped is not None else ip


@functools.lru_cache(maxsize=8)
def _extra_control_nets(raw: str) -> tuple:
    nets = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            nets.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            _log.warning("%s: ignoring %r (not a CIDR) (PKG-5)",
                         CONTROL_NETS_ENV, part[:64])
    return tuple(nets)


def control_peer_allowed(peer, local=None, environ=None) -> bool:
    """True when ``peer`` may POST a control endpoint with no token set.

    ``peer`` is the client address, ``local`` the address the connection
    arrived on (``getsockname()``; None when unknown). Admitted:

    * loopback;
    * this machine itself: peer == local (a browser on this box opening
      its own LAN or tailnet address);
    * the tailnet: peer AND local inside ``TAILNET_NETS``, so a LAN host
      that happens to number from 100.64.0.0/10 is not admitted by
      arriving on the LAN address; an unknown ``local`` admits no tailnet
      peer;
    * any CIDR in ``RC_DASH_CONTROL_NETS`` (comma-separated; the explicit
      opt-in to readmit a LAN range).

    Everything else - the LAN, link-local, an unparseable peer - is False.

    Limits, by design (know them before relying on this gate):

    * ``RC_DASH_CONTROL_NETS`` matches per address family AFTER a v4-mapped
      peer is unwrapped: ``0.0.0.0/0`` admits EVERY IPv4 peer (the whole
      LAN and anything routed in), while ``::/0`` admits every IPv6 peer
      and NO IPv4 peer. Name the narrowest range that works.
    * The tailnet rule is range-only: any overlay network numbering from
      100.64.0.0/10 or fd7a:115c:a1e0::/48 on an interface of this machine
      is admitted, not just Tailscale. It also relies on the OS dropping a
      packet that arrives on the LAN interface addressed to the tailnet IP
      (Windows' default strong-host receive model does; enabling
      weakhostreceive or IP forwarding on that interface weakens it).
    * A local reverse proxy or tunnel (Tailscale Funnel / serve, ngrok, an
      SSH -R forward) connects from loopback, so every remote caller it
      forwards looks like loopback and is admitted. Run none in front of
      :8888, or set RC_DASH_TOKEN (which then gates every peer).
    """
    ip = _peer_ip(peer)
    if ip is None:
        return False
    if ip.is_loopback:
        return True
    here = _peer_ip(local)
    if here is not None and ip == here:
        return True
    if here is not None and any(ip in net for net in TAILNET_NETS) \
            and any(here in net for net in TAILNET_NETS):
        return True
    env = os.environ if environ is None else environ
    raw = (env.get(CONTROL_NETS_ENV) or "").strip()
    return bool(raw) and any(ip in net for net in _extra_control_nets(raw))


class _DualStackMixin:
    """Bind AF_INET6 with IPV6_V6ONLY disabled so a single listener accepts both
    IPv6 and IPv4 (v4-mapped) connections. Must set the sockopt before bind, so
    we hook server_bind (the socket already exists, unbound, at this point).

    PKG-5: an IPv4-literal host (the packaged ``LOOPBACK_BIND``) gets an
    AF_INET socket instead - an AF_INET6 socket cannot bind 127.0.0.1. Set
    per INSTANCE before the socket exists; the class default stays AF_INET6.
    """

    address_family = socket.AF_INET6

    def __init__(self, server_address, *args, **kwargs) -> None:
        self.address_family = _family_for(server_address[0])
        super().__init__(server_address, *args, **kwargs)

    def server_bind(self) -> None:
        if self.address_family == socket.AF_INET6:
            try:
                self.socket.setsockopt(socket.IPPROTO_IPV6,
                                       socket.IPV6_V6ONLY, 0)
            except (AttributeError, OSError):
                # Platform without dual-stack support: fall back to v6-only bind.
                pass
        super().server_bind()


class _BoundedStartEvent(threading.Event):
    """A request thread's ``_started`` event whose untimed wait is bounded."""

    def __init__(self, bound_s: float) -> None:
        super().__init__()
        self._bound_s = bound_s

    def wait(self, timeout: float | None = None) -> bool:
        return super().wait(self._bound_s if timeout is None else timeout)


class _GuardedThreadStartMixin:
    """One thread per request, started so it cannot park the accept loop (RM-738).

    ``ThreadingMixIn.process_request`` runs on the ``serve_forever`` thread and
    ``Thread.start()`` waits on the new thread's ``_started`` with no timeout.
    A thread that dies before setting it (MemoryError in bootstrap under
    commit-charge exhaustion, RM-737) parks the accept loop for good: the port
    stays bound, every client hangs, the request socket is never closed - the
    RM-735 :8889 wedge. Here that wait is bounded: a start that raises, or a
    thread not started within ``thread_start_timeout_s``, loses its connection
    (closed + logged) and the loop accepts the next one. A one-shot claim lock
    decides who owns the socket, so a thread that boots late finds it taken
    and returns without serving. The request travels in a job list that only
    the claim holder empties: a thread that truly died in bootstrap stays in
    threading's limbo table (the stdlib has no public way to drop it), but no
    longer pins the dropped request socket (RM-740 (c), the part-3
    ``abandon_if_unstarted`` shape). A start that RAISES is arbitrated the
    same way: its ``_started.wait()`` can raise after the thread came up and
    claimed the request, and that thread then keeps it (RM-740 (g)).

    Why not RM-735's pre-started pool: this server holds long-lived SSE
    streams (/api/state-stream and /api/events, up to 8 each, 600 s per
    connection) in their request threads, and RM-296e relies on a slow request
    blocking only its own thread. A fixed pool is a budget those streams can
    exhaust; an unbounded thread per request with a bounded start is not.
    """

    # Bootstrap normally takes milliseconds; the bound only has to beat GIL
    # and scheduler latency under load. A healthy thread that misses it costs
    # one dropped connection (EventSource and the pollers retry).
    # RM-740 (d), measured 2026-10-14 under a gated -n 8 suite (commit 75
    # percent): start p99 1.3 ms, max 25 ms; with a GIL-busy thread in the
    # process, max 157 ms. 2.0 s (~13x that worst case) is KEPT: a larger cap
    # buys nothing measured and parks the accept loop longer behind a start
    # that truly died. tests/test_rm740d_thread_start_caps.py pins both.
    thread_start_timeout_s = 2.0
    start_failures = 0

    def process_request(self, request, client_address) -> None:
        claim = threading.Lock()
        # RM-740 (c): the thread's target reaches the request ONLY through
        # this list, emptied by whoever takes the claim. Never name request
        # or client_address inside the closure: a closure cell would pin the
        # socket from a bootstrap-dead thread left in threading._limbo.
        job = [request, client_address]

        def process_request_thread() -> None:
            if claim.acquire(blocking=False):
                req, addr = job
                job.clear()
                self.process_request_thread(req, addr)

        started = _BoundedStartEvent(self.thread_start_timeout_s)
        t = threading.Thread(target=process_request_thread,
                             daemon=self.daemon_threads)
        t._started = started  # the seam: Thread.start() ends in _started.wait()
        try:
            t.start()
        except Exception as exc:  # noqa: BLE001 - e.g. "can't start new thread"
            # RM-740 (g): start() can raise from its final _started.wait()
            # after the thread came up; that thread owns the request.
            if self._abandon_unstarted(started, claim, job):
                self._drop_unstarted(request, client_address, repr(exc))
            return
        # No server_close() join list to feed: ThreadingHTTPServer sets
        # daemon_threads, and the stdlib list skips daemon threads anyway.
        if self._abandon_unstarted(started, claim, job):
            self._drop_unstarted(
                request, client_address,
                f"not started within {self.thread_start_timeout_s:.1f}s")

    @staticmethod
    def _abandon_unstarted(started: threading.Event, claim: threading.Lock,
                           job: list) -> bool:
        """Take the request from a thread that never came up (RM-740 (c)/(g)).

        False when the thread started (it claims and serves) or already holds
        the claim. True when the accept loop now owns the request; the job
        list is emptied so the abandoned Thread no longer references it.
        """
        if started.is_set() or not claim.acquire(blocking=False):
            return False
        job.clear()
        return True

    def _drop_unstarted(self, request, client_address, why: str) -> None:
        self.start_failures += 1
        n = self.start_failures
        if n == 1 or n % 100 == 0:
            _log.warning("request thread failed to start (%s) - dropped "
                         "connection #%d from %s (RM-738)",
                         why, n, client_address)
        self.shutdown_request(request)


class _DualStackHTTPServer(_DualStackMixin, _GuardedThreadStartMixin,
                           ThreadingHTTPServer):
    """Plain (no-TLS) dual-stack fallback used when the mkcert pair is absent."""


class _DualProtocolHTTPServer(_DualStackMixin, _GuardedThreadStartMixin,
                              ThreadingHTTPServer):
    """Accept BOTH plain HTTP and TLS on the same port (2026-04-28
    Game-PC fix). Stdlib wrap_socket() over the listen socket forces every
    accept() into a TLS handshake - a plaintext `http://` request from a
    LAN host then connects, never receives bytes back, and times out.

    This server peeks the first byte per connection:
      * 0x16 (TLS ClientHello)  -> wrap in the TLS context, serve as TLS
      * anything else           -> emit an inline 301 to https://<host>:8888
                                   and close.

    All of that runs on the connection's own request thread (RM-742), never
    on the ``serve_forever`` thread: ``get_request`` is the inherited bare
    accept. It used to peek (5.0 s timeout), redirect (2.0 s per recv) and
    handshake before returning, so one silent client stalled every other
    :8888 accept for 5 s and a trickling one for longer (measured live
    2026-10-15: 4.8 s behind one silent client, 14.8 s behind three). The
    peek, the redirect read and the handshake now share ONE total deadline
    (``negotiate_deadline_s``); a failure drops and logs that connection only
    (the RM-739 ``mc/server.py`` shape).
    """

    # Total for a connection's setup: peek + 301 head read + TLS handshake.
    # A loopback / tailnet handshake takes milliseconds; 5.0 s is the
    # per-operation peek timeout this replaces (and RM-739's mc deadline),
    # now a deadline across every step.
    negotiate_deadline_s = 5.0
    negotiate_failures = 0

    def __init__(self, server_address, handler_class, *, ssl_ctx) -> None:
        super().__init__(server_address, handler_class)
        self._ssl_ctx = ssl_ctx
        self._negotiate_lock = threading.Lock()

    def process_request_thread(self, request, client_address) -> None:
        # Runs on the request's own thread (RM-738 guarded start), so a
        # silent, trickling or hostile client holds only this connection.
        if self._ssl_ctx is None:
            # Seam: no TLS context, nothing to negotiate - serve the
            # connection as it arrived. start_dashboard never builds this
            # class without one (it falls back to _DualStackHTTPServer); the
            # RM-738 / RM-740 tests do, to exercise the guarded start.
            super().process_request_thread(request, client_address)
            return
        conn = self._negotiate(request, client_address)
        if conn is not None:
            super().process_request_thread(conn, client_address)

    def _negotiate(self, sock, client_address):
        """Peek, then TLS-wrap or 301, all before one deadline. Returns the
        wrapped socket to serve, or None when the connection is finished
        (redirected and closed) or dropped."""
        deadline = time.monotonic() + self.negotiate_deadline_s
        conn = sock
        try:
            sock.settimeout(_time_left(deadline))
            first = sock.recv(1, socket.MSG_PEEK)
            if first == b"\x16":
                # TLS ClientHello. The handshake gets the time left as its
                # socket timeout; CPython bounds do_handshake() by one
                # deadline built from it, not per read (the trickled-
                # handshake test in tests/test_dashboard_tls_accept_rm742.py
                # pins that).
                sock.settimeout(_time_left(deadline))
                conn = self._ssl_ctx.wrap_socket(sock, server_side=True)
                # No timeout from here: the Handler bounds the request head
                # itself (RM-744, core/http_head_deadline.py) and then leaves
                # the socket untimed for the body read, long responses and SSE.
                conn.settimeout(None)
                return conn
            # Plain HTTP - answer with a 301 inline + close.
            self._inline_redirect(sock, deadline)
        except Exception as exc:  # noqa: BLE001 - one connection's setup; never surface raw
            # Deadline passed, EOF, reset, alert or a malformed handshake:
            # drop this connection only. A failed wrap has already closed
            # its own socket; shutting the detached original is a no-op.
            self._drop_setup(conn, client_address, exc)
            return None
        self.shutdown_request(sock)
        return None

    def _drop_setup(self, conn, client_address, exc: Exception) -> None:
        with self._negotiate_lock:
            self.negotiate_failures += 1
            n = self.negotiate_failures
        # Count and log BEFORE the close (the RM-738 order), so a client
        # that has seen its connection dropped can rely on both.
        try:
            if n == 1 or n % 100 == 0:
                _log.info("dashboard connection setup failed (%r) - dropped "
                          "connection #%d from %s (RM-742)",
                          exc, n, client_address)
        except Exception:  # noqa: BLE001 - logging must not keep the socket open
            pass
        self.shutdown_request(conn)

    def _inline_redirect(self, sock, deadline: float) -> None:
        """Read enough of the request to extract Host + path, send a 301.
        Best-effort - scanner/garbage traffic, or a head not complete by
        ``deadline``, just gets a redirect built from what arrived (or /).
        The caller closes the socket."""
        buf = b""
        while b"\r\n\r\n" not in buf and len(buf) < 8192:
            try:
                sock.settimeout(_time_left(deadline))
                chunk = sock.recv(4096)
            except (OSError, ValueError):
                break
            if not chunk:
                break
            buf += chunk
        # Both parts come from the client's own bytes and land in a header
        # and an HTML body, so neither may carry a line break or markup
        # (RM-745: a bare LF in the Host value or the path used to inject a
        # header line into the client's own 301).
        path = "/"
        host = "127.0.0.1"
        head, _, _ = buf.partition(b"\r\n\r\n")
        lines = head.split(b"\r\n")
        req = lines[0].split(b" ")
        if len(req) >= 2 and req[1].startswith(b"/"):
            # cap path length to keep the Location header sane
            path = _redirect_path(req[1][:512])
        for h in lines[1:]:
            if h.lower().startswith(b"host:"):
                # RM-772: a name the RM-759 allowlist refuses is never
                # echoed; the redirect falls back to the loopback default.
                candidate = _redirect_host(h.split(b":", 1)[1])
                if candidate and _redirect_host_allowed(candidate):
                    host = candidate
                break
        location = f"https://{host}:{PORT}{path}"
        link = html.escape(location, quote=True).encode("ascii")
        body = (
            b"<!doctype html><meta charset=utf-8>"
            b"<title>RC dashboard \xe2\x86\x92 HTTPS</title>"
            b"<p>RC dashboard requires HTTPS. Open "
            b"<a href=\"" + link + b"\">" + link + b"</a>.</p>"
        )
        resp = (
            b"HTTP/1.1 301 Moved Permanently\r\n"
            b"Location: " + location.encode("ascii") + b"\r\n"
            b"Content-Type: text/html; charset=utf-8\r\n"
            b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n"
            b"Connection: close\r\n\r\n"
        ) + body
        try:
            # sendall's timeout is a total. A sub-1 KB reply into an empty
            # send buffer is instant, so a head read that used the whole
            # deadline still gets a short floor to deliver its 301.
            sock.settimeout(max(deadline - time.monotonic(),
                                _REDIRECT_SEND_FLOOR_S))
            sock.sendall(resp)
        except (OSError, ValueError):
            pass


# The 301's own write budget once the setup deadline is spent (RM-742).
_REDIRECT_SEND_FLOOR_S = 0.25

# RM-745: what a 301 may echo back of the client's Host. A DNS name or an
# IPv4 literal (letters, digits, dot, hyphen, underscore), or the inside of
# a bracketed IPv6 literal (hex, colons, dots, a %-zone of the same set).
_REDIRECT_NAME = re.compile(r"[A-Za-z0-9._-]{1,253}")
_REDIRECT_V6 = re.compile(r"[0-9A-Za-z:.%_-]{2,64}")
_REDIRECT_PORT = re.compile(r"(?::[0-9]{0,5})?")


def _redirect_host(value: bytes) -> str | None:
    """The host part of a Host header value, or None when it is not a plain
    host (RM-745). Any other byte - a line break, a control, whitespace
    inside, ``/``, ``@``, non-ASCII - refuses the whole value; the port is
    checked and dropped (the 301 always names PORT)."""
    try:
        text = value.strip(b" \t").decode("ascii")
    except UnicodeDecodeError:
        return None
    if text.startswith("["):
        inner, sep, port = text[1:].partition("]")
        if not sep or not _REDIRECT_V6.fullmatch(inner):
            return None
        try:
            ipaddress.IPv6Address(inner)
        except ValueError:
            return None
        host = f"[{inner}]"
    else:
        host, sep, port = text.partition(":")
        port = sep + port
        if not _REDIRECT_NAME.fullmatch(host):
            return None
    if not _REDIRECT_PORT.fullmatch(port):
        return None
    return host


def _redirect_host_allowed(host: str) -> bool:
    """True when the 301 may name ``host`` (a ``_redirect_host`` result).

    RM-772: the shape check alone let ANY well-formed name through, so a name
    this machine does not answer to was redirected to itself (measured live:
    ``Host: rebind.example`` -> ``Location: https://rebind.example:8888/``).
    The redirect now applies the HTTPS handler's own RM-759 allowlist -
    loopback, any IP literal, this machine's configured names - read the
    same way (``host_header_hostname`` then ``is_allowed_host``). Any failure
    refuses, so the caller keeps its loopback default.

    RM-819 (c), DECIDED 2026-10-23: ANY IP literal is still echoed, exactly
    as the RM-759 allowlist passes any IP literal; not narrowed to this
    machine's own addresses. A browser sets Host from the URL it connected
    to, so an IP-literal Host names the address the client already reached -
    the 301 sends it back to that same address over TLS, never to a third
    party - and a rebinding needs a NAME. Narrowing would break a LAN viewer
    across a DHCP move (the RM-759 reason). Alternative considered: echo
    only the configured / bound addresses. Reverses if: a proxy or other
    in-path client is measured sending an IP-literal Host that differs from
    the address it connected to, or the RM-759 allowlist narrows IP literals.
    """
    try:
        # Deferred like start_dashboard's Handler import, and from the
        # shared gate (RM-819) rather than dashboard._handler, which pulls
        # in the route dispatch that a socket-layer import need not.
        from core.http_host_gate import host_header_hostname, is_allowed_host
        return is_allowed_host(host_header_hostname(host))
    except Exception:  # noqa: BLE001 - fail closed to the loopback default
        return False


def _redirect_path(target: bytes) -> str:
    """The request target with every byte outside printable ASCII (CR, LF,
    other controls, DEL, non-ASCII) percent-encoded, so it can sit in a
    header line as-is (RM-745)."""
    return "".join(chr(b) if 0x21 <= b <= 0x7E else f"%{b:02X}" for b in target)


def _time_left(deadline: float) -> float:
    """Seconds until ``deadline`` (time.monotonic); TimeoutError once spent."""
    left = deadline - time.monotonic()
    if left <= 0:
        raise TimeoutError("dashboard connection setup deadline passed (RM-742)")
    return left


def _tls_context(cert_path: Path, key_path: Path):
    """The :8888 server context: the shared RC TLS floor (RM-752,
    core/tls_policy.py) plus the mkcert chain. Split out of start_dashboard
    so a test can build it without starting the server's side effects."""
    from core.tls_policy import server_context
    ctx = server_context()
    ctx.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
    return ctx


def _build_server(app_dir: Path, handler_class, *, host: str | None = None,
                  port: int = PORT):
    """The :8888 listener, bound to ``host`` (default ``bind_host()``, PKG-5).

    If ops/tls/rc.pem + rc-key.pem exist (mkcert-issued), a
    _DualProtocolHTTPServer (HTTP requests get a 301 to HTTPS on the same
    port); otherwise, or when TLS setup fails, plain HTTP. Returns
    ``(server, scheme)``, or ``(None, scheme)`` when the port cannot be
    bound. Split out of start_dashboard so a test can bind it on an
    ephemeral port without the start-up side effects.
    """
    host = bind_host() if host is None else host
    cert_path = Path(app_dir) / "ops" / "tls" / "rc.pem"
    key_path = Path(app_dir) / "ops" / "tls" / "rc-key.pem"
    if cert_path.exists() and key_path.exists():
        try:
            ctx = _tls_context(cert_path, key_path)
            return (_DualProtocolHTTPServer((host, port), handler_class,
                                            ssl_ctx=ctx), "https")
        except Exception as exc:  # noqa: BLE001
            _log.warning("TLS setup failed, falling back to HTTP: %s", exc)
    try:
        return _DualStackHTTPServer((host, port), handler_class), "http"
    except OSError as exc:
        _log.warning("Dashboard port %d on %s unavailable: %s", port, host, exc)
        return None, "http"


def start_dashboard(app_dir: Path) -> None:
    """Launch the dashboard HTTP(S) server in a daemon thread. Idempotent-ish.
    The listener (TLS when the mkcert pair exists, else plain HTTP) and its
    bind host come from _build_server."""
    import web_dashboard
    from dashboard._handler import Handler
    app_dir = Path(app_dir)
    # Defensive backward-compat: mutate web_dashboard._APP_DIR so any
    # external caller that still reads it sees the resolved root. No
    # in-package consumer reads it as of Tier 2 #6 (champ-select brief
    # extraction switched to dashboard._context.APP_DIR).
    web_dashboard._APP_DIR = app_dir

    host = bind_host()
    srv, scheme = _build_server(app_dir, Handler, host=host)
    if srv is None:
        return

    t = threading.Thread(target=srv.serve_forever, daemon=True, name="WebDashboard")
    t.start()
    if scheme == "https":
        _log.info("Web dashboard on https://%s:%d/  (HTTP requests on the "
                  "same port 301-redirect)",
                  host, PORT)
    else:
        _log.info("Web dashboard on http://%s:%d/  (no TLS cert)", host, PORT)

    # Vision server: keep a LIVE moon_vision_server.py on :8889 (RM-735).
    # Was a one-shot connect_ex here, which checked port ownership once at
    # dashboard start: a server wedged while holding the port, or one that
    # died later, stayed broken until RC restarted. The watchdog thread probes
    # GET /health every 15 s, spawns when nothing listens, and kills +
    # respawns a holder that stops answering (dashboard/_vision_watchdog.py).
    try:
        from dashboard._vision_watchdog import start_vision_watchdog
        start_vision_watchdog(app_dir)
    except Exception as exc:  # noqa: BLE001
        _log.warning("vision server watchdog failed to start: %s", exc)

    # Daemon Slayer: ensure the local DPS engine on :8860 is running.
    # No-op if already up; spawns tools/start_daemon_slayer.py otherwise.
    try:
        from core.daemon_slayer_client import ensure_running as _ds_ensure
        _ds_ensure()
    except Exception as exc:  # noqa: BLE001
        _log.warning("daemon_slayer startup check failed: %s", exc)

    # TFT opponent scouting (s134): a GET-only LCU poller that fires ONE
    # scouting run per TFT game at game start (EOG fallback post-game) and
    # publishes data/tft_scouting.json. Kill switch RC_TFT_SCOUTING=0.
    try:
        from tft.tft_scouting import start_scouting_watcher
        start_scouting_watcher()
    except Exception as exc:  # noqa: BLE001
        _log.warning("tft scouting watcher failed to start: %s", exc)

    # Vision tracker: derives fog-of-war state from Live Client position
    # freshness, writes data/vision_state.json. Consumed by the minimap
    # overlay layer and (later) by coach prompt builders.
    try:
        from core.vision_tracker import get_tracker
        get_tracker().start_background()
    except Exception as exc:  # noqa: BLE001
        _log.warning("vision_tracker failed to start: %s", exc)

    # Decision detector loop now runs in the Phase 3 supervisor process
    # (agents/supervisor.py) - Tier 3 #15, 2026-05-01. The dashboard still
    # reads pending + writes choices via DecisionStore directly; cross-
    # process locking on data/decisions_pending.json is provided by
    # core.decision_detector._decisions_critical_section.

    # OBS publisher (Tier 3 #11, 2026-05-01): pushes a one-line RC
    # state summary to an OBS Text source via OBS-WebSocket v5. Opt-in
    # via config/coach_settings.json `obs.enabled`. start_background()
    # is a no-op when the config block is absent or disabled.
    try:
        from core.obs_publisher import get_publisher
        get_publisher().start_background()
    except Exception as exc:  # noqa: BLE001
        _log.warning("obs_publisher failed to start: %s", exc)
