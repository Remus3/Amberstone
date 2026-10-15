# arch: Mission Control HTTPS server (:8895, tailnet + loopback only) | section=mc | frozen=no
"""Bind, TLS and serve for Mission Control.

Three deliberate differences from dashboard/server.py, each with a reason:

  1. EXPLICIT NARROW BIND, not a dual-stack wildcard. One socket per address
     in BIND_ADDRESSES. A wildcard bind would put a process-killing surface
     on the LAN, which operator decision 2026-07-31 rules out.
  2. BIND FAILURE EXITS NON-ZERO. dashboard/server.py logs a warning and
     returns when the port is unavailable, leaving RC up and the dashboard
     silently absent. For a control plane that is the worst shape a failure
     can take, so this exits and lets the scheduled task's restart policy
     (RestartCount=3, RestartInterval=1min) engage and record it.
  3. NO HOT-RELOAD WATCHER. core.hot_reload is deliberately not started -
     a control plane must not restart itself when an unrelated .py
     changes.

TLS reuses the existing mkcert material at ops/tls/rc.pem. A SAN is
host-scoped, not port-scoped, and tools/regen_rc_cert.ps1 already lists
the tailnet node name, its tailnet FQDN and the tailnet address (per-host
config, ops/local_hosts.json `cert_sans`), so :8895 validates with NO cert
regen. -k is not acceptable on a surface that can kill.
"""
from __future__ import annotations

import logging
import ssl
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

from core import local_hosts
from mc.handler import Handler

log = logging.getLogger("rc.mc.server")

ROOT = Path(__file__).resolve().parent.parent
PORT = 8895


def bind_addresses(cfg=None) -> list:
    """Loopback plus the Tailscale address. NOT the LAN address and NOT a
    wildcard - see the module docstring. The tailnet address is per-host
    config (gitignored ops/local_hosts.json `tailnet_ipv4`, validated to
    100.64.0.0/10); absent or invalid = loopback only."""
    out = ["127.0.0.1"]
    tailnet = local_hosts.tailnet_ipv4(cfg)
    if tailnet:
        out.append(tailnet)
    return out


BIND_ADDRESSES = bind_addresses()

CERT_PATH = ROOT / "ops" / "tls" / "rc.pem"
KEY_PATH = ROOT / "ops" / "tls" / "rc-key.pem"


def _ssl_context() -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile=str(CERT_PATH), keyfile=str(KEY_PATH))
    return ctx


class _CappedStartEvent(threading.Event):
    """``Thread._started`` with a ceiling on the wait ``Thread.start()`` makes."""

    def __init__(self, cap_s: float) -> None:
        super().__init__()
        self._cap_s = cap_s

    def wait(self, timeout: float | None = None) -> bool:
        if timeout is None or timeout > self._cap_s:
            timeout = self._cap_s
        return super().wait(timeout)


class _RequestThread(threading.Thread):
    """RM-738: a per-request thread whose ``start()`` cannot park the accept loop.

    ``Thread.start()`` waits on ``self._started`` with no timeout, and only the
    NEW thread sets it (``_bootstrap_inner``, after ``_set_native_id``). A
    thread that dies in bootstrap - MemoryError under commit-charge
    exhaustion, RM-735 / RM-737 - would park ``serve_forever`` for good. Here
    that wait is capped; a thread not started by then is abandoned and the
    server drops the connection. One that starts late sees the abandon in
    ``run()`` and returns without touching the dropped socket.
    """

    def __init__(self, server: "_Server", request, client_address) -> None:
        super().__init__(daemon=server.daemon_threads)
        self._started = _CappedStartEvent(server.thread_start_timeout_s)
        self._job: tuple | None = (server, request, client_address)
        self._gate = threading.Lock()
        self._outcome: str | None = None        # "claimed" | "abandoned"

    def run(self) -> None:
        with self._gate:
            if self._outcome is not None:
                return
            self._outcome = "claimed"
            job, self._job = self._job, None
        server, request, client_address = job
        server.process_request_thread(request, client_address)

    def abandon_if_unstarted(self) -> bool:
        if self._started.is_set():
            return False
        with self._gate:
            if self._outcome is not None:
                return False
            self._outcome = "abandoned"
            self._job = None
            return True


class _Server(ThreadingHTTPServer):
    """ThreadingHTTPServer whose per-request thread start is capped (RM-738)
    and whose TLS handshake runs per connection, off the accept loop (RM-739).

    The listen socket stays PLAIN. Wrapping it made ``SSLSocket.accept()`` run
    each handshake inline on the ``serve_forever`` thread with no timeout, so
    one client that connected and never sent a ClientHello parked that bind
    address for every other client.
    """

    # A thread start normally takes well under a millisecond. RM-740 (d),
    # measured 2026-10-14 under a gated -n 8 suite: max 25 ms, 157 ms with a
    # GIL-busy thread in the process; 2.0 s (~13x) is KEPT - a larger cap
    # only parks the accept loop longer behind a start that truly died.
    # tests/test_rm740d_thread_start_caps.py pins both.
    thread_start_timeout_s = 2.0
    thread_start_failures = 0
    # A loopback / tailnet handshake takes milliseconds; past this the
    # connection is dropped. The same 5 s dashboard/server.py gives its peek.
    tls_handshake_timeout_s = 5.0

    def __init__(self, server_address, handler_class, *,
                 ssl_ctx: ssl.SSLContext) -> None:
        super().__init__(server_address, handler_class)
        self.ssl_ctx = ssl_ctx

    def process_request_thread(self, request, client_address) -> None:
        # Runs on the request's own thread (RM-738 _RequestThread.run), so a
        # silent, slow or hostile handshake holds only this connection.
        conn = request
        try:
            request.settimeout(self.tls_handshake_timeout_s)
            conn = self.ssl_ctx.wrap_socket(request, server_side=True)
            conn.settimeout(None)
        except (OSError, ValueError):
            # Deadline passed, alert, EOF, reset or a plaintext probe: drop
            # this connection only. A failed wrap has already closed its own
            # socket; shutting the detached original down is a no-op.
            self.shutdown_request(conn)
            return
        super().process_request_thread(conn, client_address)

    def process_request(self, request, client_address) -> None:
        # ThreadingMixIn.process_request with a capped start. The stdlib's
        # _threads bookkeeping is not carried: it never holds daemon threads.
        t = _RequestThread(self, request, client_address)
        start_error: Exception | None = None
        try:
            t.start()
        except Exception as exc:  # noqa: BLE001 - e.g. "can't start new thread"
            # RM-740 (b): a start that raises is a failed start too - dropped,
            # counted and logged here, never left to escape to handle_error.
            # No traceback kept: it would pin this frame (and the request).
            # abandon_if_unstarted() still arbitrates: a thread that did
            # come up before the raise owns its request.
            start_error = exc.with_traceback(None)
        if not t.abandon_if_unstarted():
            return
        # Count and log BEFORE the close (the dashboard's order), so a client
        # that has seen its connection dropped can rely on both.
        self.thread_start_failures += 1
        try:
            if self.thread_start_failures == 1 or self.thread_start_failures % 100 == 0:
                why = (f"did not start within {self.thread_start_timeout_s:.1f}s"
                       if start_error is None else f"start raised {start_error!r}")
                log.warning("Mission Control: request thread %s - dropped "
                            "connection #%d from %s (RM-738)", why,
                            self.thread_start_failures, client_address)
        except Exception:  # noqa: BLE001 - logging can fail under the same memory pressure
            pass
        self.shutdown_request(request)


def _make_server(address: str, ctx: ssl.SSLContext) -> ThreadingHTTPServer:
    """One bound server; every connection it accepts is TLS-wrapped on its
    own request thread (RM-739), never served plain. Raises on failure -
    callers do not swallow it, they exit."""
    return _Server((address, PORT), Handler, ssl_ctx=ctx)


def main() -> int:
    """Serve until killed. Returns a process exit code; never returns 0
    from a failure path."""
    if not (CERT_PATH.exists() and KEY_PATH.exists()):
        log.error("Mission Control: TLS material missing at %s / %s. "
                  "A control plane that can kill processes does not serve "
                  "plaintext - refusing to start.", CERT_PATH, KEY_PATH)
        return 2

    try:
        ctx = _ssl_context()
    except (ssl.SSLError, OSError) as exc:
        log.error("Mission Control: TLS setup failed: %s", exc)
        return 2

    servers = []
    try:
        for address in BIND_ADDRESSES:
            servers.append(_make_server(address, ctx))
            log.info("Mission Control listening on https://%s:%d/", address, PORT)
    except OSError as exc:
        for srv in servers:
            srv.server_close()
        log.error("Mission Control: bind failed on :%d (%s). Exiting so the "
                  "scheduled task records the failure.", PORT, exc)
        return 3

    threads = []
    for srv in servers[1:]:
        t = threading.Thread(target=srv.serve_forever, daemon=True,
                             name=f"MissionControl-{srv.server_address[0]}")
        t.start()
        threads.append(t)
    try:
        servers[0].serve_forever()
    except KeyboardInterrupt:
        log.info("Mission Control: interrupted, shutting down")
    finally:
        for srv in servers:
            srv.server_close()
    return 0
