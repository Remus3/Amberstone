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
  3. NO HOT-RELOAD WATCHER. The file-change watcher used elsewhere in RC to
     restart a process on an unrelated edit is deliberately not started
     here. A guard test in tests/test_mission_control_server.py asserts
     this module never spells out that watcher's dotted module name, not
     even in prose, so this paragraph avoids it on purpose.

TLS reuses the existing mkcert material at ops/tls/rc.pem. A SAN is
host-scoped, not port-scoped, and tools/regen_rc_cert.ps1 already lists
legion-rc, legion-rc.tailc150de.ts.net and 100.70.22.55, so :8895 validates
with NO cert regen. -k is not acceptable on a surface that can kill.
"""
from __future__ import annotations

import logging
import socket
import ssl
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

from mc.handler import Handler

log = logging.getLogger("rc.mc.server")

ROOT = Path(__file__).resolve().parent.parent
PORT = 8895
# Loopback plus the Tailscale address. NOT the LAN address (192.168.8.230)
# and NOT a wildcard - see the module docstring.
BIND_ADDRESSES = ["127.0.0.1", "100.70.22.55"]

CERT_PATH = ROOT / "ops" / "tls" / "rc.pem"
KEY_PATH = ROOT / "ops" / "tls" / "rc-key.pem"


def _ssl_context() -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile=str(CERT_PATH), keyfile=str(KEY_PATH))
    return ctx


def _make_server(address: str, ctx: ssl.SSLContext) -> ThreadingHTTPServer:
    """One bound, TLS-wrapped server. Raises on failure - callers do not
    swallow it, they exit."""
    srv = ThreadingHTTPServer((address, PORT), Handler)
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    return srv


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
