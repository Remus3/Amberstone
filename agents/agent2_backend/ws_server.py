"""Phase 3 WebSocket relay server.

Two paths served on the same port (§11.5):

  /ingest  — Game-PC Forwarder connects and streams live-client / LCU JSON
             frames here. Each incoming frame is fanned out to all /push
             subscribers after being stamped with an ``ingested_at`` field.

  /push    — Chrome kiosk(s) on Game-PC subscribe here. They receive every
             frame the forwarder pushes plus any payloads the supervisor
             broadcasts internally via ``broadcast_push()``.

Heartbeat: a JSON ``{"type":"heartbeat","t":<epoch>}`` is broadcast to all
/push subscribers every 5 seconds so stale connections drop quickly.

Logging split:
  logs/ws/ingest.log   — /ingest connect/disconnect/frame traffic (SEND/ERROR)
  logs/ws/push.log     — /push connect/disconnect/broadcast fanout

Usage (standalone test):
  python -m agents.agent2_backend.ws_server --host 0.0.0.0 --port 8891

In production the supervisor imports and runs ``WSServer.run_forever()`` on
its event loop.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import logging.handlers
import time
from pathlib import Path
from typing import Any

import websockets
from websockets.asyncio.server import ServerConnection, serve

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_LOG_ROOT = _PROJECT_ROOT / "logs" / "ws"

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8891
HEARTBEAT_INTERVAL_SEC = 5.0

# Explicit per-frame cap (audit P-audit-m5). 1 MiB covers JSON game-state
# frames (LCU + live-client) with plenty of headroom. Screenshots are
# routed through the separate :8889 HTTP vision server, not WS — if that
# ever changes, bump this (or pass None) and add a size-log at ingest.
WS_MAX_FRAME_BYTES = 1 << 20


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
    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
        self.host = host
        self.port = port
        self._push_clients: set[ServerConnection] = set()
        self._ingest_clients: set[ServerConnection] = set()
        self._last_frame: dict[str, Any] | None = None
        self._ingest_log = _build_logger("ws.ingest", _LOG_ROOT / "ingest.log")
        self._push_log = _build_logger("ws.push", _LOG_ROOT / "push.log")
        self._stop = asyncio.Event()
        self._server = None
        self._hb_task: asyncio.Task | None = None

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

        Returns the number of clients the message was queued to.

        AUDIT P-audit3-h01 (2026-04-22): fanout is now parallel with a
        per-client 2s timeout. One laggy iPad/forwarder WS cannot block
        the other subscribers — the 1-2s latency-tier promise in
        resolved_decisions.json stays honoured.
        """
        msg = json.dumps(payload)
        clients = list(self._push_clients)

        async def _send_one(ws: ServerConnection) -> ServerConnection | None:
            try:
                await asyncio.wait_for(ws.send(msg), timeout=2.0)
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

        self._push_log.info(
            "SEND fanout type=%s n=%d",
            payload.get("type", "?"), len(self._push_clients),
        )
        return len(self._push_clients)

    # ----- handlers ----------------------------------------------------
    async def _handle_ingest(self, ws: ServerConnection) -> None:
        self._ingest_clients.add(ws)
        self._ingest_log.info("SEND ingest-connect peer=%s", ws.remote_address)
        try:
            async for raw in ws:
                try:
                    data = json.loads(raw) if isinstance(raw, (str, bytes, bytearray)) else raw
                except json.JSONDecodeError as e:
                    self._ingest_log.error("ERROR parse: %s", e)
                    continue
                if not isinstance(data, dict):
                    self._ingest_log.error("ERROR non-dict payload: %r", type(data).__name__)
                    continue
                data.setdefault("type", "ingest_frame")
                data["ingested_at"] = time.time()
                self._last_frame = data
                self._ingest_log.info("SEND frame type=%s bytes=%d", data.get("type"), len(raw))
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

    async def _router(self, ws: ServerConnection) -> None:
        path = ws.request.path if ws.request else "/"
        if path == "/ingest":
            await self._handle_ingest(ws)
        elif path == "/push":
            await self._handle_push(ws)
        else:
            await ws.close(code=1008, reason=f"unknown path {path}")

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
        self._server = await serve(
            self._router, self.host, self.port,
            max_size=WS_MAX_FRAME_BYTES,
        )
        self._hb_task = asyncio.create_task(self._heartbeat_loop())
        self._ingest_log.info("SEND ws-start host=%s port=%d", self.host, self.port)
        self._push_log.info("SEND ws-start host=%s port=%d", self.host, self.port)

    async def stop(self) -> None:
        self._stop.set()
        if self._hb_task:
            self._hb_task.cancel()
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def run_forever(self) -> None:
        await self.start()
        try:
            await self._stop.wait()
        finally:
            await self.stop()


async def _main(host: str, port: int) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    srv = WSServer(host=host, port=port)
    await srv.start()
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
    asyncio.run(_main(args.host, args.port))
