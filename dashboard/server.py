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
# Dual-stack bind. `legion-rc` resolves IPv6-first on clients (Tailscale AAAA
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


class _DualStackHTTPServer(_DualStackMixin, ThreadingHTTPServer):
    """Plain (no-TLS) dual-stack fallback used when the mkcert pair is absent."""


class _DualProtocolHTTPServer(_DualStackMixin, ThreadingHTTPServer):
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
        host = "192.168.8.230"
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
                  "same port 301-redirect)  (iPad: https://192.168.8.230:%d/)",
                  HOST, PORT, PORT)
    else:
        _log.info("Web dashboard on http://%s:%d/  (no TLS cert)", HOST, PORT)

    # Vision server: ensure moon_vision_server.py is listening on :8889.
    # No-op if already up; spawns it as a detached background process otherwise.
    try:
        import socket as _sock
        _p = _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM)
        _p.settimeout(1)
        _vision_up = _p.connect_ex(("127.0.0.1", 8889)) == 0
        _p.close()
        if not _vision_up:
            import subprocess
            import sys as _sys
            _vis = app_dir / "moon_vision_server.py"
            subprocess.Popen(
                [_sys.executable, str(_vis)],
                cwd=str(app_dir),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                creationflags=0x08000000,  # CREATE_NO_WINDOW
            )
            _log.info("vision server not running - spawned %s", _vis.name)
    except Exception as exc:  # noqa: BLE001
        _log.warning("vision server startup check failed: %s", exc)

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
