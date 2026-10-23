"""Phase 3 WebSocket relay server.

Now Legion-only (1-PC, ADR-011). Two paths served on the same port (S11.5):

  /ingest  - a local frame producer connects and streams live-client / LCU
             JSON frames here. Each incoming frame is fanned out to all
             /push subscribers after being stamped with an ``ingested_at``
             field. (Originally the 2-PC Game-PC Forwarder; that pre-1PC
             topology is retired - the producer is now Legion-local.)

  /push    - the dashboard / any local Chrome client subscribes here. They
             receive every frame the producer pushes plus any payloads the
             supervisor broadcasts internally via ``broadcast_push()``.
             (Originally a Game-PC Chrome kiosk; now Legion-local.)

Heartbeat: a JSON ``{"type":"heartbeat","t":<epoch>}`` is broadcast to all
/push subscribers every 5 seconds. A subscriber whose send does not finish
within ``PUSH_SEND_TIMEOUT_SEC`` is evicted from the fanout AND its socket is
closed (code 1011), so its client sees a disconnect and reconnects instead of
staying connected and silently unfed. websockets' own ``close()`` waits in
``drain()`` with no bound while the transport is paused, so a close that does
not finish within ``PUSH_CLOSE_TIMEOUT_SEC`` falls back to aborting the
transport (lane 8 true-audit, session 124). ``stop()`` bounds websockets' own
connection closes the same way (``STOP_CLOSE_TIMEOUT_SEC``), so one stalled
subscriber cannot hang the supervisor's shutdown.

Handshake policy (``handshake_refusal``; browsers always send ``Origin`` on a
WebSocket handshake, and any web page can open ws://127.0.0.1):
  /ingest  - refused when the request carries ANY Origin (no browser client
             exists for it) or the peer is not loopback.
  /push    - accepted with no Origin (local tools) or an http(s) Origin whose
             host is loopback or one of the dashboard's own cert SAN hosts
             (``core.local_hosts.cert_sans``); refused otherwise (403).

Logging split:
  logs/ws/ingest.log   - /ingest connect/disconnect/frame traffic (SEND/ERROR)
  logs/ws/push.log     - /push connect/disconnect/broadcast fanout
A non-empty ``RC_WS_LOG_DIR`` replaces logs/ws/ as the root of both files; it
is read when a ``WSServer`` is constructed (RM-776: the test suite points it
at tmp_path, so a child process a test starts leaves the live logs alone).

Usage (standalone test):
  python -m agents.agent2_backend.ws_server --host 127.0.0.1 --port 8891

In production the supervisor imports and runs ``WSServer.run_forever()`` on
its event loop.
"""
from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import logging
import logging.handlers
import os
import sys
import time
from collections.abc import Iterable, Sequence
from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import websockets
from websockets.asyncio.server import ServerConnection, serve
from websockets.http11 import Request, Response

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_LOG_ROOT = _PROJECT_ROOT / "logs" / "ws"
LOG_DIR_ENV = "RC_WS_LOG_DIR"

log = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"  # RM-231: loopback; widen only deliberately
DEFAULT_PORT = 8891
HEARTBEAT_INTERVAL_SEC = 5.0

# Per-subscriber fanout bound (audit P-audit3-h01) and the bound on closing
# an evicted subscriber before its transport is aborted (lane 8, s124).
PUSH_SEND_TIMEOUT_SEC = 2.0
PUSH_CLOSE_TIMEOUT_SEC = 2.0
# Bound on stop()'s wait for the server's own connection closes before the
# remaining transports are aborted.
STOP_CLOSE_TIMEOUT_SEC = 5.0

# Explicit per-frame cap (audit P-audit-m5). 1 MiB covers JSON game-state
# frames (LCU + live-client) with plenty of headroom. Screenshots are
# routed through the separate :8889 HTTP vision server, not WS - if that
# ever changes, bump this (or pass None) and add a size-log at ingest.
WS_MAX_FRAME_BYTES = 1 << 20

# Longest peer-supplied value (path, origin, frame type) written to a log
# line; values are logged as repr() so a newline cannot forge a log line.
_LOG_FIELD_MAX = 80


def _clip(value: Any) -> str:
    """repr() of a peer-supplied value, clipped for a single log line."""
    text = repr(value)
    if len(text) > _LOG_FIELD_MAX:
        text = text[:_LOG_FIELD_MAX] + "...(clipped)"
    return text


def _utf8_len(raw: Any) -> int:
    if isinstance(raw, str):
        return len(raw.encode("utf-8", "surrogatepass"))
    return len(raw)


def _host_is_loopback(host: str | None) -> bool:
    if not host:
        return False
    host = host.strip().lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _load_origin_hosts() -> frozenset[str]:
    """The dashboard's cert SAN hosts from per-host config (gitignored
    ops/local_hosts.json). An absent or malformed file gives none, which
    leaves only loopback origins accepted on /push."""
    from core import local_hosts
    return _normalise_hosts(local_hosts.cert_sans())


def _normalise_hosts(hosts: Iterable[str]) -> frozenset[str]:
    return frozenset(h.strip().lower() for h in hosts if isinstance(h, str) and h.strip())


def handshake_refusal(
    path: str,
    origins: Sequence[str],
    peer: Any,
    origin_hosts: frozenset[str],
) -> str | None:
    """Why a WebSocket handshake must be refused, or None to accept it.

    ``origins`` is every ``Origin`` header value on the request (more than one
    is malformed), ``peer`` the socket's remote address tuple (or None),
    ``origin_hosts`` the lower-cased non-loopback hosts a /push page may be
    served from. Paths other than /ingest and /push are left to the router,
    which closes them with 1008.
    """
    if path == "/ingest":
        if origins:
            return "browser origin on /ingest"
        peer_host = peer[0] if isinstance(peer, (tuple, list)) and peer else None
        if not _host_is_loopback(peer_host if isinstance(peer_host, str) else None):
            return "non-loopback peer on /ingest"
        return None
    if path == "/push":
        if not origins:
            return None
        if len(origins) > 1:
            return "multiple Origin headers"
        origin = origins[0]
        # A serialized origin is printable ASCII with no whitespace (urlsplit
        # silently drops CR / LF / TAB; same rule as dashboard/_handler.py
        # _cors_allowed_origin) and is scheme://host[:port] only.
        if any(not ("!" <= ch <= "~") for ch in origin):
            return "malformed origin"
        try:
            parts = urlsplit(origin)
            host = parts.hostname
        except ValueError:
            return "unparseable origin"
        if "@" in parts.netloc or parts.path or parts.query or parts.fragment:
            return "malformed origin"
        if parts.scheme not in ("http", "https") or not host:
            return "origin is not an http(s) page"
        if _host_is_loopback(host) or host.lower() in origin_hosts:
            return None
        return "origin host not allowed"
    return None


def _log_root() -> Path:
    """logs/ws/, or a non-empty ``RC_WS_LOG_DIR`` (RM-776)."""
    override = (os.environ.get(LOG_DIR_ENV) or "").strip()
    return Path(override) if override else _LOG_ROOT


def _build_logger(name: str, path: Path) -> logging.Logger:
    lg = logging.getLogger(name)
    if lg.handlers:
        return lg
    lg.setLevel(logging.INFO)
    path.parent.mkdir(parents=True, exist_ok=True)
    h = logging.handlers.RotatingFileHandler(path, maxBytes=3 * 1024 * 1024, backupCount=3, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    lg.addHandler(h)
    lg.propagate = False
    return lg


class WSServer:
    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        origin_hosts: Iterable[str] | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self._push_clients: set[ServerConnection] = set()
        self._ingest_clients: set[ServerConnection] = set()
        self._last_frame: dict[str, Any] | None = None
        log_root = _log_root()
        self._ingest_log = _build_logger("ws.ingest", log_root / "ingest.log")
        self._push_log = _build_logger("ws.push", log_root / "push.log")
        self._stop = asyncio.Event()
        self._server = None
        self._hb_task: asyncio.Task | None = None
        # Strong refs to in-flight evicted-subscriber closes: the event loop
        # holds only weak refs to tasks, so an unreferenced one can vanish.
        self._closing: set[asyncio.Task] = set()
        self._connections: set[ServerConnection] = set()
        self._origin_hosts = (
            _load_origin_hosts() if origin_hosts is None
            else _normalise_hosts(origin_hosts)
        )

    # ----- client-facing API -------------------------------------------
    @property
    def push_subscribers(self) -> int:
        return len(self._push_clients)

    @property
    def ingest_sources(self) -> int:
        return len(self._ingest_clients)

    @property
    def last_frame(self) -> dict[str, Any] | None:
        return self._last_frame

    async def broadcast_push(self, payload: dict[str, Any]) -> int:
        """Send ``payload`` (JSON-serialisable) to every /push subscriber.

        Returns the number of /push subscribers still registered after the
        fanout (dead or stalled ones are evicted first).

        AUDIT P-audit3-h01 (2026-04-22): fanout is now parallel with a
        per-client ``PUSH_SEND_TIMEOUT_SEC`` timeout. One laggy subscriber
        WS cannot block the other subscribers - the 1-2s latency-tier
        promise in resolved_decisions.json stays honoured. An evicted
        subscriber is also closed in the background (``_close_evicted``),
        so the fanout never waits on it.
        """
        msg = json.dumps(payload)
        clients = list(self._push_clients)

        async def _send_one(ws: ServerConnection) -> ServerConnection | None:
            try:
                await asyncio.wait_for(ws.send(msg), timeout=PUSH_SEND_TIMEOUT_SEC)
                return None
            except (websockets.ConnectionClosed, RuntimeError,
                    asyncio.TimeoutError):
                return ws   # mark dead/stalled

        if clients:
            results = await asyncio.gather(
                *(_send_one(ws) for ws in clients),
                return_exceptions=False,
            )
            for dead_ws in filter(None, results):
                self._push_clients.discard(dead_ws)
                self._schedule_close(dead_ws)

        self._push_log.info(
            "SEND fanout type=%s n=%d",
            _clip(payload.get("type", "?")), len(self._push_clients),
        )
        return len(self._push_clients)

    def _schedule_close(self, ws: ServerConnection) -> None:
        task = asyncio.create_task(self._close_evicted(ws))
        self._closing.add(task)
        task.add_done_callback(self._closing.discard)

    async def _close_evicted(self, ws: ServerConnection) -> None:
        """Close an evicted subscriber so its client sees a disconnect and
        reconnects. A graceful close is tried first; when it does not finish
        within ``PUSH_CLOSE_TIMEOUT_SEC`` (a stalled peer keeps the transport
        paused, and websockets' close() then waits in drain() with no bound)
        or is cancelled by stop(), the transport is aborted instead."""
        closed = False
        try:
            await asyncio.wait_for(
                ws.close(code=1011, reason="stalled"),
                timeout=PUSH_CLOSE_TIMEOUT_SEC,
            )
            closed = True
        except asyncio.TimeoutError:
            self._push_log.warning(
                "SEND evict-close-timeout peer=%s - aborting transport",
                ws.remote_address,
            )
        finally:
            if not closed:
                transport = getattr(ws, "transport", None)
                if transport is not None:
                    transport.abort()
        self._push_log.info("SEND evicted peer=%s n=%d", ws.remote_address, len(self._push_clients))

    # ----- handlers ----------------------------------------------------
    async def _handle_ingest(self, ws: ServerConnection) -> None:
        self._ingest_clients.add(ws)
        self._ingest_log.info("SEND ingest-connect peer=%s", ws.remote_address)
        try:
            async for raw in ws:
                try:
                    data = json.loads(raw) if isinstance(raw, (str, bytes, bytearray)) else raw
                except (ValueError, RecursionError) as e:
                    # ValueError covers JSONDecodeError AND the
                    # UnicodeDecodeError a non-UTF-8 binary frame raises;
                    # RecursionError is a deeply nested frame. Each used to
                    # escape and kill the producer connection.
                    self._ingest_log.error("ERROR parse: %s %s", type(e).__name__, _clip(str(e)))
                    continue
                if not isinstance(data, dict):
                    self._ingest_log.error("ERROR non-dict payload: %r", type(data).__name__)
                    continue
                data.setdefault("type", "ingest_frame")
                data["ingested_at"] = time.time()
                self._last_frame = data
                self._ingest_log.info(
                    "SEND frame type=%s bytes=%d", _clip(data.get("type")), _utf8_len(raw),
                )
                await self.broadcast_push(data)
        except websockets.ConnectionClosed:
            pass
        finally:
            self._ingest_clients.discard(ws)
            self._ingest_log.info("SEND ingest-disconnect peer=%s", ws.remote_address)

    async def _handle_push(self, ws: ServerConnection) -> None:
        self._push_clients.add(ws)
        self._push_log.info("SEND push-connect peer=%s n=%d", ws.remote_address, len(self._push_clients))
        # Send most recent frame on connect so UI paints immediately.
        if self._last_frame is not None:
            try:
                await ws.send(json.dumps(self._last_frame))
            except websockets.ConnectionClosed:
                pass
        try:
            async for _msg in ws:
                # Push clients shouldn't send; ignore.
                pass
        except websockets.ConnectionClosed:
            pass
        finally:
            self._push_clients.discard(ws)
            self._push_log.info("SEND push-disconnect peer=%s n=%d", ws.remote_address, len(self._push_clients))

    def _process_request(self, connection: ServerConnection, request: Request) -> Response | None:
        """Opening-handshake gate (see ``handshake_refusal``): 403 or None."""
        origins = request.headers.get_all("Origin")
        reason = handshake_refusal(
            request.path, origins, connection.remote_address, self._origin_hosts,
        )
        if reason is None:
            return None
        self._push_log.warning(
            "REFUSE handshake path=%s origin=%s peer=%s reason=%s",
            _clip(request.path), _clip(origins), connection.remote_address, reason,
        )
        return connection.respond(HTTPStatus.FORBIDDEN, "Forbidden\n")

    async def _router(self, ws: ServerConnection) -> None:
        # Every routed connection, whatever its path, so stop() can abort
        # one that websockets' own close cannot finish.
        self._connections.add(ws)
        try:
            path = ws.request.path if ws.request else "/"
            if path == "/ingest":
                await self._handle_ingest(ws)
            elif path == "/push":
                await self._handle_push(ws)
            else:
                # Fixed reason: echoing the path overflowed the 123-byte close
                # reason limit for a long path, so close() raised ProtocolError
                # and the peer got 1011 instead of 1008.
                self._push_log.warning(
                    "SEND unknown-path peer=%s path=%s", ws.remote_address, _clip(path),
                )
                await ws.close(code=1008, reason="unknown path")
        finally:
            self._connections.discard(ws)

    async def _heartbeat_loop(self) -> None:
        """AUDIT P-audit3-h02 (2026-04-22): inner exceptions are now
        logged and swallowed so the loop survives transient broadcast
        failures. Only CancelledError stops the task."""
        try:
            while not self._stop.is_set():
                await asyncio.sleep(HEARTBEAT_INTERVAL_SEC)
                try:
                    await self.broadcast_push({"type": "heartbeat", "t": time.time()})
                except Exception as e:           # noqa: BLE001
                    self._push_log.exception("heartbeat fanout raised: %s", e)
        except asyncio.CancelledError:
            pass

    # ----- lifecycle ---------------------------------------------------
    async def start(self) -> None:
        """Bind and start serving. A bind failure (RM-756: a held port used
        to surface as asyncio's raw OSError, e.g. WinError 10048) raises a
        RuntimeError naming host:port with the supervisor preflight's
        netstat hint; no heartbeat task is started in that case."""
        try:
            self._server = await serve(
                self._router, self.host, self.port,
                max_size=WS_MAX_FRAME_BYTES,
                process_request=self._process_request,
            )
        except OSError as e:
            raise RuntimeError(
                f"ws_server cannot bind {self.host}:{self.port} - port already in use? "
                f"run: `netstat -ano | findstr :{self.port}` to identify the holder ({e})"
            ) from e
        self._hb_task = asyncio.create_task(self._heartbeat_loop())
        self._ingest_log.info("SEND ws-start host=%s port=%d", self.host, self.port)
        self._push_log.info("SEND ws-start host=%s port=%d", self.host, self.port)

    async def stop(self) -> None:
        self._stop.set()
        if self._hb_task:
            self._hb_task.cancel()
        # Pending evicted-subscriber closes: cancelling one aborts its
        # transport (``_close_evicted`` finally), so nothing is left open.
        closing = list(self._closing)
        for task in closing:
            task.cancel()
        if closing:
            await asyncio.gather(*closing, return_exceptions=True)
        if self._server:
            # websockets' Server.close() closes each open connection and
            # waits with no bound; a write-stalled subscriber not yet evicted
            # blocks that close in drain() forever, which used to hang
            # stop() and with it the supervisor's shutdown (lock release
            # included). Bound it, then abort whatever is still connected.
            self._server.close()
            try:
                await asyncio.wait_for(self._server.wait_closed(), timeout=STOP_CLOSE_TIMEOUT_SEC)
            except asyncio.TimeoutError:
                stuck = list(self._connections)
                self._push_log.warning(
                    "SEND stop-close-timeout - aborting %d connection(s)", len(stuck),
                )
                for ws in stuck:
                    transport = getattr(ws, "transport", None)
                    if transport is not None:
                        transport.abort()
                try:
                    await asyncio.wait_for(self._server.wait_closed(), timeout=STOP_CLOSE_TIMEOUT_SEC)
                except asyncio.TimeoutError:
                    # Never raise out of stop(): the supervisor's shutdown
                    # still has its lock release to run after this call.
                    self._push_log.error(
                        "SEND stop-close-timeout - server still closing after abort; giving up",
                    )

    async def run_forever(self) -> None:
        await self.start()
        try:
            await self._stop.wait()
        finally:
            await self.stop()


async def _main(host: str, port: int) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    srv = WSServer(host=host, port=port)
    try:
        await srv.start()
    except RuntimeError as e:
        log.error("%s", e)
        return 1
    try:
        await asyncio.Future()
    finally:
        await srv.stop()
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--host", default=DEFAULT_HOST)
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = p.parse_args()
    sys.exit(asyncio.run(_main(args.host, args.port)))
