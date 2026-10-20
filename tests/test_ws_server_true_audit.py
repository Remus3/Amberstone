"""Lane 8 true-audit of agents/agent2_backend/ws_server.py (session 124).

The Phase 3 WebSocket relay (:8891) had one bind test (RM-231) and nothing
that exercised a single frame. This module pins the relay end to end on a
real loopback socket, then reproduces every weakness the audit found:

  W1  a stalled /push subscriber was evicted from the fanout set but its
      socket was never closed, so the client never saw a disconnect and never
      reconnected (agent 6 report N1). websockets 17 close() waits in drain()
      with no bound while the transport is paused, so a graceful close alone
      can hang; the fix falls back to transport.abort().
  W2  an /ingest binary frame that is not UTF-8 raised UnicodeDecodeError past
      the JSONDecodeError-only catch and killed the producer connection.
  W3  a deeply nested /ingest frame raised RecursionError and did the same.
  W4  an unknown path longer than ~110 bytes made the 1008 close itself raise
      ProtocolError (close reason > 123 bytes, the path was echoed into it),
      so the handler crashed and the peer got 1011.
  W5  any browser page could open ws://127.0.0.1:8891 (cross-site WebSocket
      hijacking): /ingest frames drive the dashboard's onState / onHealth /
      lcu handlers, and /push streams the live game state. /ingest now
      refuses every Origin (no browser client exists for it) and non-loopback
      peers; /push accepts no Origin, loopback origins and the dashboard's own
      cert SAN hosts only.
  W6  peer-supplied strings (frame type, path) reached the log raw, so a
      newline forged log lines; the frame log's ``bytes=`` counted characters.
  W7  stop() awaited websockets' Server.close() with no bound; a write-stalled
      subscriber not yet evicted blocked it in drain() forever, hanging the
      supervisor's shutdown before its lock release. stop() now bounds the
      wait, aborts every routed connection that is left, and never raises.

Every coroutine runs through tests._asyncio_isolation.run_coro (a bare
asyncio.run breaks under the snapshot_panels loop marker). The module's file
loggers are replaced by an in-memory handler, so no test writes logs/ws/.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import socket
import time

import pytest
import websockets
from websockets.asyncio.client import connect
from websockets.protocol import State

from agents.agent2_backend import ws_server
from tests._asyncio_isolation import run_coro


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    def messages(self) -> list[str]:
        return [r.getMessage() for r in self.records]


@pytest.fixture
def logs(monkeypatch):
    handler = _ListHandler()

    def _fake_build(name, _path):
        # An UNREGISTERED Logger (not via getLogger), so no global logging
        # state changes and the NOW-7 logger-leak gate stays quiet.
        lg = logging.Logger(f"test_ws_server_true_audit.{name}", logging.DEBUG)
        lg.addHandler(handler)
        lg.propagate = False
        return lg

    monkeypatch.setattr(ws_server, "_build_logger", _fake_build)
    return handler


def _run(coro, timeout=30.0):
    return run_coro(coro, timeout=timeout)


async def _serve(body, **kw):
    srv = ws_server.WSServer(host="127.0.0.1", port=0, **kw)
    await srv.start()
    try:
        port = srv._server.sockets[0].getsockname()[1]
        return await body(srv, f"ws://127.0.0.1:{port}", port)
    finally:
        await srv.stop()


async def _recv_json(ws, timeout=2.0):
    return json.loads(await asyncio.wait_for(ws.recv(), timeout))


async def _wait_for(pred, timeout=5.0, step=0.01):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        await asyncio.sleep(step)
    return pred()


# ---------------------------------------------------------------- characterization


def test_ingest_frame_is_stamped_cached_and_fanned_out(logs):
    async def body(srv, base, _port):
        async with connect(base + "/push") as sub, connect(base + "/ingest") as ing:
            assert await _wait_for(lambda: srv.push_subscribers == 1)
            t0 = time.time()
            await ing.send(json.dumps({"type": "state", "x": 1}))
            got = await _recv_json(sub)
            t1 = time.time()
            assert got["type"] == "state" and got["x"] == 1
            assert t0 <= got["ingested_at"] <= t1
            assert srv.last_frame == got
            assert srv.ingest_sources == 1

    _run(_serve(body))


def test_ingest_frame_without_type_defaults_to_ingest_frame(logs):
    async def body(srv, base, _port):
        async with connect(base + "/push") as sub, connect(base + "/ingest") as ing:
            assert await _wait_for(lambda: srv.push_subscribers == 1)
            await ing.send(json.dumps({"k": "v"}))
            got = await _recv_json(sub)
            assert got["type"] == "ingest_frame" and got["k"] == "v"

    _run(_serve(body))


def test_ingest_drops_non_dict_and_bad_json_but_keeps_connection(logs):
    async def body(srv, base, _port):
        async with connect(base + "/push") as sub, connect(base + "/ingest") as ing:
            assert await _wait_for(lambda: srv.push_subscribers == 1)
            await ing.send("[1, 2]")
            await ing.send("not json")
            await ing.send(json.dumps({"type": "state", "n": 3}))
            got = await _recv_json(sub)
            assert got["n"] == 3
            assert ing.state is State.OPEN
        errors = [m for m in logs.messages() if m.startswith("ERROR")]
        assert len(errors) == 2, errors

    _run(_serve(body))


def test_push_subscriber_gets_last_frame_on_connect(logs):
    async def body(srv, base, _port):
        async with connect(base + "/ingest") as ing:
            await ing.send(json.dumps({"type": "state", "snap": True}))
            assert await _wait_for(lambda: srv.last_frame is not None)
        async with connect(base + "/push") as sub:
            got = await _recv_json(sub)
            assert got["snap"] is True

    _run(_serve(body))


def test_unknown_path_is_closed_with_1008(logs):
    async def body(srv, base, _port):
        async with connect(base + "/nope") as ws:
            with pytest.raises(websockets.ConnectionClosed) as ei:
                await asyncio.wait_for(ws.recv(), 2.0)
            assert ei.value.rcvd is not None and ei.value.rcvd.code == 1008

    _run(_serve(body))


def test_push_client_messages_are_ignored(logs):
    async def body(srv, base, _port):
        async with connect(base + "/push") as sub:
            assert await _wait_for(lambda: srv.push_subscribers == 1)
            await sub.send("hello")
            await sub.send(json.dumps({"type": "state"}))
            await asyncio.sleep(0.1)
            assert srv.push_subscribers == 1
            assert srv.last_frame is None
            assert sub.state is State.OPEN

    _run(_serve(body))


def test_heartbeat_reaches_subscribers(logs, monkeypatch):
    monkeypatch.setattr(ws_server, "HEARTBEAT_INTERVAL_SEC", 0.05)

    async def body(srv, base, _port):
        async with connect(base + "/push") as sub:
            got = await _recv_json(sub)
            assert got["type"] == "heartbeat"
            assert isinstance(got["t"], float)

    _run(_serve(body))


def test_stop_finishes_heartbeat_and_closes_server(logs):
    async def body():
        srv = ws_server.WSServer(host="127.0.0.1", port=0)
        await srv.start()
        await srv.stop()
        assert srv._hb_task.done()
        assert not srv._server.is_serving()

    _run(body())


# ---------------------------------------------------------------- fakes for fanout


class _FakeTransport:
    def __init__(self) -> None:
        self.aborted = False

    def abort(self) -> None:
        self.aborted = True


class _FakeWS:
    """A push subscriber double. ``send_delay`` None = instant send."""

    def __init__(self, send_delay=None, close_delay=None, send_exc=None):
        self.send_delay = send_delay
        self.close_delay = close_delay
        self.send_exc = send_exc
        self.sent: list[str] = []
        self.close_calls: list[tuple[int, str]] = []
        self.remote_address = ("127.0.0.1", 50000)
        self.transport = _FakeTransport()

    async def send(self, msg):
        if self.send_exc is not None:
            raise self.send_exc
        if self.send_delay is not None:
            await asyncio.sleep(self.send_delay)
        self.sent.append(msg)

    async def close(self, code=1000, reason=""):
        self.close_calls.append((code, reason))
        if self.close_delay is not None:
            await asyncio.sleep(self.close_delay)


def test_broadcast_returns_live_subscriber_count_after_eviction(logs):
    async def body():
        srv = ws_server.WSServer(host="127.0.0.1", port=0)
        ok, dead = _FakeWS(), _FakeWS(send_exc=RuntimeError("closed"))
        srv._push_clients.update({ok, dead})
        n = await srv.broadcast_push({"type": "state", "v": 1})
        assert n == 1
        assert srv._push_clients == {ok}
        assert json.loads(ok.sent[0]) == {"type": "state", "v": 1}
        await asyncio.sleep(0.05)

    _run(body())


# ---------------------------------------------------------------- W1 stalled subscriber


def test_w1_evicted_stalled_subscriber_is_closed(logs, monkeypatch):
    monkeypatch.setattr(ws_server, "PUSH_SEND_TIMEOUT_SEC", 0.05, raising=False)

    async def body():
        srv = ws_server.WSServer(host="127.0.0.1", port=0)
        ok, stalled = _FakeWS(), _FakeWS(send_delay=30)
        srv._push_clients.update({ok, stalled})
        t0 = time.monotonic()
        n = await srv.broadcast_push({"type": "state"})
        assert time.monotonic() - t0 < 1.0, "fanout must not wait on the close"
        assert n == 1 and stalled not in srv._push_clients
        assert await _wait_for(lambda: stalled.close_calls, timeout=2.0)
        assert stalled.close_calls[0][0] == 1011
        assert ok.close_calls == []

    _run(body())


def test_w1_evicted_subscriber_whose_close_hangs_is_aborted(logs, monkeypatch):
    monkeypatch.setattr(ws_server, "PUSH_SEND_TIMEOUT_SEC", 0.05, raising=False)
    monkeypatch.setattr(ws_server, "PUSH_CLOSE_TIMEOUT_SEC", 0.05, raising=False)

    async def body():
        srv = ws_server.WSServer(host="127.0.0.1", port=0)
        stalled = _FakeWS(send_delay=30, close_delay=30)
        srv._push_clients.add(stalled)
        await srv.broadcast_push({"type": "state"})
        assert await _wait_for(lambda: stalled.transport.aborted, timeout=3.0)

    _run(body())


def test_w1_evicted_subscriber_that_closes_cleanly_is_not_aborted(logs, monkeypatch):
    monkeypatch.setattr(ws_server, "PUSH_SEND_TIMEOUT_SEC", 0.05, raising=False)

    async def body():
        srv = ws_server.WSServer(host="127.0.0.1", port=0)
        stalled = _FakeWS(send_delay=30)
        srv._push_clients.add(stalled)
        await srv.broadcast_push({"type": "state"})
        assert await _wait_for(lambda: stalled.close_calls, timeout=2.0)
        await asyncio.sleep(0.05)
        assert stalled.transport.aborted is False

    _run(body())


def test_w1_stop_aborts_a_pending_evicted_close(logs, monkeypatch):
    monkeypatch.setattr(ws_server, "PUSH_SEND_TIMEOUT_SEC", 0.05, raising=False)
    monkeypatch.setattr(ws_server, "PUSH_CLOSE_TIMEOUT_SEC", 30.0, raising=False)

    async def body():
        srv = ws_server.WSServer(host="127.0.0.1", port=0)
        await srv.start()
        stalled = _FakeWS(send_delay=30, close_delay=30)
        srv._push_clients.add(stalled)
        await srv.broadcast_push({"type": "state"})
        assert await _wait_for(lambda: stalled.close_calls, timeout=2.0)
        t0 = time.monotonic()
        await srv.stop()
        assert time.monotonic() - t0 < 5.0
        assert stalled.transport.aborted is True

    _run(body())


def test_w1_stalled_real_client_is_disconnected(logs, monkeypatch):
    """Real socket: a client that completes the handshake and then never
    reads. Before the fix it was evicted but stayed OPEN indefinitely."""
    monkeypatch.setattr(ws_server, "PUSH_SEND_TIMEOUT_SEC", 0.2, raising=False)
    monkeypatch.setattr(ws_server, "PUSH_CLOSE_TIMEOUT_SEC", 0.2, raising=False)

    async def body(srv, _base, port):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
        sock.connect(("127.0.0.1", port))
        sock.setblocking(False)
        reader, writer = await asyncio.open_connection(sock=sock, limit=4096)
        try:
            key = base64.b64encode(os.urandom(16)).decode("ascii")
            writer.write((
                "GET /push HTTP/1.1\r\n"
                f"Host: 127.0.0.1:{port}\r\n"
                "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
            ).encode("ascii"))
            await writer.drain()
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5.0)
            assert b" 101 " in head
            assert await _wait_for(lambda: srv.push_subscribers == 1)
            conn = next(iter(srv._push_clients))
            blob = "x" * (256 * 1024)
            for _ in range(800):
                await srv.broadcast_push({"type": "bulk", "blob": blob})
                if srv.push_subscribers == 0:
                    break
            assert srv.push_subscribers == 0, "client never stalled"
            assert await _wait_for(lambda: conn.state is State.CLOSED, timeout=5.0), (
                f"evicted subscriber left {conn.state.name}"
            )
        finally:
            writer.transport.abort()

    _run(_serve(body), timeout=90.0)


def test_w1_stop_is_bounded_with_a_stalled_unevicted_subscriber(logs, monkeypatch):
    """Real socket: a write-stalled subscriber that no fanout has evicted
    yet. websockets' Server.close() waits on its close() with no bound, and
    that close() waits in drain(), so stop() used to hang forever."""
    monkeypatch.setattr(ws_server, "STOP_CLOSE_TIMEOUT_SEC", 0.3, raising=False)

    async def body():
        srv = ws_server.WSServer(host="127.0.0.1", port=0)
        await srv.start()
        port = srv._server.sockets[0].getsockname()[1]
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
        sock.connect(("127.0.0.1", port))
        sock.setblocking(False)
        reader, writer = await asyncio.open_connection(sock=sock, limit=4096)
        sends = []
        try:
            key = base64.b64encode(os.urandom(16)).decode("ascii")
            writer.write((
                "GET /push HTTP/1.1\r\n"
                f"Host: 127.0.0.1:{port}\r\n"
                "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
            ).encode("ascii"))
            await writer.drain()
            await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5.0)
            assert await _wait_for(lambda: srv.push_subscribers == 1)
            conn = next(iter(srv._push_clients))
            blob = "y" * (256 * 1024)
            for _ in range(800):
                sends.append(asyncio.create_task(conn.send(blob)))
                await asyncio.sleep(0.001)
                if conn.transport.get_write_buffer_size() > (1 << 20):
                    break
            assert conn.transport.get_write_buffer_size() > (1 << 20), "client never stalled"
            t0 = time.monotonic()
            await asyncio.wait_for(srv.stop(), 10.0)
            assert time.monotonic() - t0 < 5.0
            assert conn.state is State.CLOSED
        finally:
            writer.transport.abort()
            await asyncio.gather(*sends, return_exceptions=True)

    _run(body(), timeout=60.0)


def test_w7_routed_connections_are_tracked_then_released(logs):
    """stop()'s abort set (``_connections``) holds every live routed
    connection, any path, and drains as they close - no per-connection
    leak for a server that runs for days."""
    async def body(srv, base, _port):
        async with connect(base + "/push"), connect(base + "/ingest"):
            assert await _wait_for(lambda: len(srv._connections) == 2)
        async with connect(base + "/nope") as ws:
            with pytest.raises(websockets.ConnectionClosed):
                await asyncio.wait_for(ws.recv(), 2.0)
        assert await _wait_for(lambda: not srv._connections), srv._connections

    _run(_serve(body))


class _NeverClosingServer:
    """A server double whose wait_closed() never returns."""

    def __init__(self) -> None:
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1

    async def wait_closed(self) -> None:
        await asyncio.sleep(3600)


def test_w7_stop_never_raises_or_hangs_when_the_server_will_not_close(logs, monkeypatch):
    """stop() runs inside agents/supervisor.py stop() BEFORE the lock
    release, so it must return - not hang, not raise - even when the
    server never finishes closing after the abort."""
    monkeypatch.setattr(ws_server, "STOP_CLOSE_TIMEOUT_SEC", 0.05, raising=False)

    async def body():
        srv = ws_server.WSServer(host="127.0.0.1", port=0)
        fake = _NeverClosingServer()
        srv._server = fake
        await asyncio.wait_for(srv.stop(), 5.0)
        assert fake.close_calls == 1
        assert any("giving up" in m for m in logs.messages())

    _run(body())


# ---------------------------------------------------------------- W2 / W3 malformed ingest


@pytest.mark.parametrize("bad", [
    pytest.param(b"\x80not-utf8", id="w2-invalid-utf8-binary"),
    pytest.param("[" * 100_000, id="w3-deeply-nested"),
])
def test_w2_w3_malformed_ingest_frame_keeps_producer_connected(logs, bad):
    async def body(srv, base, _port):
        async with connect(base + "/push") as sub, connect(base + "/ingest") as ing:
            assert await _wait_for(lambda: srv.push_subscribers == 1)
            await ing.send(bad)
            await ing.send(json.dumps({"type": "state", "after": True}))
            got = await _recv_json(sub)
            assert got["after"] is True
            assert ing.state is State.OPEN
        assert any(m.startswith("ERROR parse") for m in logs.messages())

    _run(_serve(body))


# ---------------------------------------------------------------- W4 long unknown path


def test_w4_long_unknown_path_closes_1008_without_echoing_it(logs):
    async def body(srv, base, _port):
        async with connect(base + "/" + "a" * 200) as ws:
            with pytest.raises(websockets.ConnectionClosed) as ei:
                await asyncio.wait_for(ws.recv(), 2.0)
            assert ei.value.rcvd is not None
            assert ei.value.rcvd.code == 1008
            assert "aaaa" not in ei.value.rcvd.reason
        assert await _wait_for(lambda: any("unknown-path" in m for m in logs.messages()))
        line = next(m for m in logs.messages() if "unknown-path" in m)
        assert len(line) < 200, "peer-supplied path must be clipped in the log"

    _run(_serve(body))


# ---------------------------------------------------------------- W5 origin gate


async def _handshake_status(url, origin):
    try:
        async with connect(url, origin=origin) as ws:
            return 101 if ws.state is State.OPEN else -1
    except websockets.InvalidStatus as e:
        return e.response.status_code


@pytest.mark.parametrize("origin", [
    "https://evil.example",
    "https://127.0.0.1:8888",
    "null",
])
def test_w5_ingest_refuses_every_browser_origin(logs, origin):
    async def body(srv, base, _port):
        assert await _handshake_status(base + "/ingest", origin) == 403
        assert srv.ingest_sources == 0

    _run(_serve(body))


def test_w5_ingest_without_origin_is_accepted(logs):
    async def body(srv, base, _port):
        assert await _handshake_status(base + "/ingest", None) == 101

    _run(_serve(body))


def test_w5_push_refuses_a_foreign_origin_by_default(logs, monkeypatch):
    """Default construction (the supervisor's), with no SAN hosts configured:
    a foreign page origin is refused. At HEAD this was a 101 accept."""
    from core import local_hosts
    monkeypatch.setattr(local_hosts, "cert_sans", lambda cfg=None: [])

    async def body(srv, base, _port):
        assert await _handshake_status(base + "/push", "https://evil.example") == 403
        assert await _handshake_status(base + "/push", "https://127.0.0.1:8888") == 101

    _run(_serve(body))


@pytest.mark.parametrize("origin", [
    "https://evil.example",
    "http://evil.example:8888",
    "null",
    "https://127.0.0.1.evil.example:8888",
    "ftp://127.0.0.1",
    "https://evilrc-host:8888",
    "https://rc-host.evil.example:8888",
    "https://sub.rc-host:8888",
])
def test_w5_push_refuses_foreign_origins(logs, origin):
    async def body(srv, base, _port):
        assert await _handshake_status(base + "/push", origin) == 403
        assert srv.push_subscribers == 0
        assert any("REFUSE" in m for m in logs.messages())

    _run(_serve(body, origin_hosts=["rc-host"]))


@pytest.mark.parametrize("origin", [
    None,
    "https://127.0.0.1:8888",
    "https://localhost:8888",
    "http://127.0.0.1:8890",
    "https://[::1]:8888",
    "https://RC-HOST:8888",
    "https://rc-host.example-tailnet.ts.net:8888",
])
def test_w5_push_accepts_loopback_and_dashboard_san_origins(logs, origin):
    async def body(srv, base, _port):
        assert await _handshake_status(base + "/push", origin) == 101

    _run(_serve(body, origin_hosts=["rc-host", "rc-host.example-tailnet.ts.net"]))


def test_w5_default_origin_hosts_come_from_local_hosts_cert_sans(logs, monkeypatch):
    from core import local_hosts
    monkeypatch.setattr(local_hosts, "cert_sans", lambda cfg=None: [" Rc-Host ", "100.64.0.7"])
    srv = ws_server.WSServer(host="127.0.0.1", port=0)
    assert srv._origin_hosts == frozenset({"rc-host", "100.64.0.7"})


@pytest.mark.parametrize("path,origins,peer,refused", [
    ("/ingest", [], ("127.0.0.1", 1), False),
    ("/ingest", [], ("::1", 1, 0, 0), False),
    ("/ingest", [], ("100.64.0.9", 1), True),
    ("/ingest", [], None, True),
    ("/ingest", ["https://127.0.0.1:8888"], ("127.0.0.1", 1), True),
    ("/push", [], ("100.64.0.9", 1), False),
    ("/push", ["https://127.0.0.1:8888", "https://127.0.0.1:8888"], ("127.0.0.1", 1), True),
    ("/push", ["https://rc-host:8888"], ("127.0.0.1", 1), False),
    ("/push", ["https://other-host:8888"], ("127.0.0.1", 1), True),
    ("/push", ["https://evilrc-host:8888"], ("127.0.0.1", 1), True),
    ("/push", ["https://rc-host.evil.example:8888"], ("127.0.0.1", 1), True),
    ("/push", ["https://sub.rc-host:8888"], ("127.0.0.1", 1), True),
    ("/push", ["https://evil.example@127.0.0.1"], ("127.0.0.1", 1), True),
    ("/push", ["https://127.0.0.1:8888/x"], ("127.0.0.1", 1), True),
    ("/push", ["https://127.0.0.1\t:8888"], ("127.0.0.1", 1), True),
    ("/push", ["https://[::1"], ("127.0.0.1", 1), True),
    ("/nope", ["https://evil.example"], ("127.0.0.1", 1), False),
])
def test_w5_handshake_policy_table(path, origins, peer, refused):
    reason = ws_server.handshake_refusal(path, origins, peer, frozenset({"rc-host"}))
    assert (reason is not None) is refused, reason


# ---------------------------------------------------------------- W6 log hygiene


def test_w6_frame_log_neutralises_peer_controlled_newlines(logs):
    async def body(srv, base, _port):
        async with connect(base + "/push") as sub, connect(base + "/ingest") as ing:
            assert await _wait_for(lambda: srv.push_subscribers == 1)
            await ing.send(json.dumps({"type": "x\nFORGED 2026-01-01 INFO fake"}))
            await _recv_json(sub)
        frame_lines = [m for m in logs.messages() if m.startswith("SEND frame")]
        assert frame_lines, logs.messages()
        for m in logs.messages():
            assert "\n" not in m, m

    _run(_serve(body))


def test_w6_frame_log_counts_utf8_bytes(logs):
    async def body(srv, base, _port):
        # chr() keeps this source file 7-bit ASCII (tests/test_py_source_ascii_rm300.py).
        raw = json.dumps({"type": "state", "name": chr(0xE9) * 3}, ensure_ascii=False)
        async with connect(base + "/push") as sub, connect(base + "/ingest") as ing:
            assert await _wait_for(lambda: srv.push_subscribers == 1)
            await ing.send(raw)
            await _recv_json(sub)
        frame_lines = [m for m in logs.messages() if m.startswith("SEND frame")]
        assert frame_lines and frame_lines[-1].endswith(f"bytes={len(raw.encode('utf-8'))}")
        assert len(raw.encode("utf-8")) != len(raw)

    _run(_serve(body))
