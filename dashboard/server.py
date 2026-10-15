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

import logging
import socket
import threading
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
HOST = "::"


class _DualStackMixin:
    """Bind AF_INET6 with IPV6_V6ONLY disabled so a single listener accepts both
    IPv6 and IPv4 (v4-mapped) connections. Must set the sockopt before bind, so
    we hook server_bind (the socket already exists, unbound, at this point)."""

    address_family = socket.AF_INET6

    def server_bind(self) -> None:
        try:
            self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
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
      * 0x16 (TLS ClientHello)  -> wrap in the TLS context, hand off as TLS
      * anything else           -> emit an inline 301 to https://<host>:8888,
                                   close, raise OSError so the framework
                                   skips the slot.
    """

    def __init__(self, server_address, handler_class, *, ssl_ctx) -> None:
        super().__init__(server_address, handler_class)
        self._ssl_ctx = ssl_ctx

    def get_request(self) -> tuple:
        sock, addr = self.socket.accept()
        try:
            import socket as _socket
            sock.settimeout(5.0)
            first = sock.recv(1, _socket.MSG_PEEK)
        except (OSError, ValueError):
            try: sock.close()
            except OSError: pass
            raise
        if first == b"\x16":
            # TLS ClientHello - wrap and hand off. Wrap can raise on a
            # malformed handshake; that's a normal scanner / probe and
            # should be silently dropped.
            try:
                wrapped = self._ssl_ctx.wrap_socket(sock, server_side=True)
                wrapped.settimeout(None)
                return wrapped, addr
            except OSError as exc:
                try: sock.close()
                except OSError: pass
                raise OSError(f"TLS handshake failed: {exc}")
        # Plain HTTP - answer with a 301 inline + close.
        try:
            self._inline_redirect(sock)
        except OSError:
            pass
        finally:
            try: sock.close()
            except OSError: pass
        # Tell socketserver to skip this slot. It catches OSError quietly.
        raise OSError("plain HTTP redirected to HTTPS")

    def _inline_redirect(self, sock) -> None:
        """Read enough of the request to extract Host + path, send a 301,
        close. Best-effort - scanner/garbage traffic just gets a generic
        redirect to /."""
        sock.settimeout(2.0)
        buf = b""
        while b"\r\n\r\n" not in buf and len(buf) < 8192:
            try:
                chunk = sock.recv(4096)
            except (OSError, ValueError):
                break
            if not chunk:
                break
            buf += chunk
        path = "/"
        host = "127.0.0.1"
        try:
            head, _, _ = buf.partition(b"\r\n\r\n")
            lines = head.split(b"\r\n")
            if lines:
                req = lines[0].decode("ascii", errors="replace").split(" ")
                if len(req) >= 2 and req[1].startswith("/"):
                    # cap path length to keep the Location header sane
                    path = req[1][:512]
            for h in lines[1:]:
                lo = h.lower()
                if lo.startswith(b"host:"):
                    raw = h.split(b":", 1)[1].decode("ascii", errors="replace").strip()
                    # Strip the existing port; we always redirect to PORT.
                    host = raw.split(":", 1)[0] or host
                    break
        except (UnicodeDecodeError, ValueError):
            pass
        location = f"https://{host}:{PORT}{path}"
        body = (
            b"<!doctype html><meta charset=utf-8>"
            b"<title>RC dashboard \xe2\x86\x92 HTTPS</title>"
            b"<p>RC dashboard requires HTTPS. Open "
            b"<a href=\"" + location.encode("utf-8") + b"\">"
            + location.encode("utf-8") + b"</a>.</p>"
        )
        resp = (
            b"HTTP/1.1 301 Moved Permanently\r\n"
            b"Location: " + location.encode("utf-8") + b"\r\n"
            b"Content-Type: text/html; charset=utf-8\r\n"
            b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n"
            b"Connection: close\r\n\r\n"
        ) + body
        try:
            sock.sendall(resp)
        except OSError:
            pass


def start_dashboard(app_dir: Path) -> None:
    """Launch the dashboard HTTP(S) server in a daemon thread. Idempotent-ish.
    If ops/tls/rc.pem + rc-key.pem exist (mkcert-issued), serves TLS via
    _DualProtocolHTTPServer (HTTP requests get a 301 to HTTPS on the same
    port); otherwise falls back to plain HTTP."""
    import web_dashboard
    from dashboard._handler import Handler
    app_dir = Path(app_dir)
    # Defensive backward-compat: mutate web_dashboard._APP_DIR so any
    # external caller that still reads it sees the resolved root. No
    # in-package consumer reads it as of Tier 2 #6 (champ-select brief
    # extraction switched to dashboard._context.APP_DIR).
    web_dashboard._APP_DIR = app_dir
    handler_class = Handler

    cert_path = app_dir / "ops" / "tls" / "rc.pem"
    key_path  = app_dir / "ops" / "tls" / "rc-key.pem"
    scheme = "http"
    srv = None
    if cert_path.exists() and key_path.exists():
        try:
            import ssl
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
            srv = _DualProtocolHTTPServer((HOST, PORT), handler_class, ssl_ctx=ctx)
            scheme = "https"
        except Exception as exc:  # noqa: BLE001
            _log.warning("TLS setup failed, falling back to HTTP: %s", exc)
            srv = None
    if srv is None:
        try:
            srv = _DualStackHTTPServer((HOST, PORT), handler_class)
        except OSError as exc:
            _log.warning("Dashboard port %d unavailable: %s", PORT, exc)
            return

    t = threading.Thread(target=srv.serve_forever, daemon=True, name="WebDashboard")
    t.start()
    if scheme == "https":
        _log.info("Web dashboard on https://%s:%d/  (HTTP requests on the "
                  "same port 301-redirect)",
                  HOST, PORT)
    else:
        _log.info("Web dashboard on http://%s:%d/  (no TLS cert)", HOST, PORT)

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
