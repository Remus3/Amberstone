"""s144 true-audit of dashboard/routes_state.py ``_serve_state_stream``
(/api/state-stream SSE; filing RM-1032, sibling of the routes_events F4).

Two findings, each pinned here (synthetic payloads only, no live game):
  F1  a client that stops reading held its dispatcher thread and one of the 8
      subscriber slots forever. dashboard/server.py hands the handler an
      UNTIMED socket, so once the send buffer filled, ``wfile.write`` blocked
      with no bound, and the 600 s lifetime cap is only checked between
      writes. Eight such clients answered every new stream 503. Writes are now
      bounded by _SSE_WRITE_STALL_S on the socket, restored in finally.
  F2  the lifetime cap and the heartbeat ran on the WALL clock (time.time). A
      wall clock stepped back (an NTP correction, a resume from sleep) kept a
      stream open past its 600 s cap by the size of the step and suppressed
      the heartbeat for as long. Both now run on time.monotonic.
"""
from __future__ import annotations

import io
import socket
import socketserver
import sys
import threading
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import dashboard.routes_state as rs  # noqa: E402


class _H:
    def __init__(self, wfile=None, connection=None):
        self.wfile = io.BytesIO() if wfile is None else wfile
        self.connection = connection
        self.code = None
        self.sent = None

    def send_response(self, code):
        self.code = code

    def send_header(self, *a):
        pass

    def end_headers(self):
        pass

    def _send(self, status, payload, ctype):
        self.sent = (status, payload, ctype)


# -- F1: a stalled reader frees its thread and its slot -----------------------

def test_stalled_reader_releases_thread_and_slot():
    """Real socket pair, client never reads, payload changes every tick (as
    it does in a live game): the stream must end by itself."""
    srv, cli = socket.socketpair()
    try:
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
        cli.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
        srv.settimeout(None)
        req = _H(wfile=socketserver._SocketWriter(srv), connection=srv)
        n = [0]

        def payload():
            # Measured (routes_events F4): a Windows loopback pair takes
            # ~2.7 MB before a send blocks, so emit a fresh 16 KB body per
            # tick until the stream ends.
            n[0] += 1
            return b'{"n":%d,"pad":"%s"}' % (n[0], b"X" * 16000)

        done = threading.Event()

        def run():
            try:
                with mock.patch.object(rs, "_state_payload_cached", side_effect=payload), \
                        mock.patch.object(rs, "_SSE_TICK_S", 0.001), \
                        mock.patch.object(rs, "_SSE_WRITE_STALL_S", 0.3, create=True):
                    rs._serve_state_stream(req)
            finally:
                done.set()

        with mock.patch.object(rs, "_sse_count", 0):
            threading.Thread(target=run, daemon=True).start()
            finished = done.wait(10.0)
            if not finished:                 # unblock the writer, then fail
                cli.close()
                done.wait(5.0)
            assert finished, "stalled reader held the state-stream thread"
            assert rs._sse_count == 0, "subscriber slot leaked"
        assert srv.gettimeout() is None      # prior timeout restored
    finally:
        for s in (srv, cli):
            try:
                s.close()
            except OSError:
                pass


def test_write_stall_arms_and_restores_the_socket_timeout():
    calls = []

    class Conn:
        def __init__(self):
            self.t = 7.0

        def gettimeout(self):
            return self.t

        def settimeout(self, v):
            calls.append(v)
            self.t = v

    conn = Conn()
    req = _H(connection=conn)
    with mock.patch.object(rs, "_state_payload_cached", return_value=b'{"x":1}'), \
            mock.patch.object(rs, "_SSE_MAX_DURATION_S", 0.05), \
            mock.patch.object(rs, "_SSE_TICK_S", 0.01), \
            mock.patch.object(rs, "_sse_count", 0):
        rs._serve_state_stream(req)
        assert rs._sse_count == 0
    assert calls and calls[0] == rs._SSE_WRITE_STALL_S
    assert conn.t == 7.0, "the socket's prior timeout was not restored"
    assert b'data: {"x":1}' in req.wfile.getvalue()


def test_write_stall_restored_even_when_the_stream_raises():
    class Conn:
        t = None

        def gettimeout(self):
            return self.t

        def settimeout(self, v):
            self.t = v

    conn = Conn()
    req = _H(connection=conn)

    def boom(*a):
        raise RuntimeError("header write failed")

    req.end_headers = boom
    with mock.patch.object(rs, "_sse_count", 0):
        try:
            rs._serve_state_stream(req)
        except RuntimeError:
            pass
        else:
            raise AssertionError("the header failure was swallowed")
        assert rs._sse_count == 0
    assert conn.t is None


def test_a_socket_that_refuses_a_timeout_still_streams():
    class Conn:
        def gettimeout(self):
            raise OSError("closed")

        def settimeout(self, v):
            raise OSError("closed")

    req = _H(connection=Conn())
    with mock.patch.object(rs, "_state_payload_cached", return_value=b'{"x":2}'), \
            mock.patch.object(rs, "_SSE_MAX_DURATION_S", 0.05), \
            mock.patch.object(rs, "_SSE_TICK_S", 0.01), \
            mock.patch.object(rs, "_sse_count", 0):
        rs._serve_state_stream(req)
        assert rs._sse_count == 0
    assert b'data: {"x":2}' in req.wfile.getvalue()


def test_a_socket_closed_before_the_restore_still_frees_the_slot():
    class Conn:
        t = None

        def gettimeout(self):
            return self.t

        def settimeout(self, v):
            if v is None:                    # the restore: socket now closed
                raise OSError("closed")
            self.t = v

    req = _H(connection=Conn())
    with mock.patch.object(rs, "_state_payload_cached", return_value=b'{"x":5}'), \
            mock.patch.object(rs, "_SSE_MAX_DURATION_S", 0.05), \
            mock.patch.object(rs, "_SSE_TICK_S", 0.01), \
            mock.patch.object(rs, "_sse_count", 0):
        rs._serve_state_stream(req)
        assert rs._sse_count == 0


def test_write_stall_is_bounded_and_outlasts_a_heartbeat_gap():
    assert rs._SSE_HEARTBEAT_S < rs._SSE_WRITE_STALL_S <= 120.0


# -- F2: lifetime cap and heartbeat run on the monotonic clock ----------------

class _Runaway(Exception):
    pass


class _SteppedClock:
    """A fake ``time`` module: monotonic advances only through sleep(); the
    wall clock reads one hour BEHIND from its fourth read on (a step back
    after the stream's first emit)."""

    def __init__(self, max_sleeps):
        self.mono = 1000.0
        self.wall_reads = 0
        self.sleeps = 0
        self.max_sleeps = max_sleeps

    def monotonic(self):
        return self.mono

    def time(self):
        self.wall_reads += 1
        # Wall and monotonic clocks have unrelated epochs, as in reality.
        return 1.7e9 + self.mono + (0.0 if self.wall_reads <= 3 else -3600.0)

    def sleep(self, s):
        self.sleeps += 1
        if self.sleeps > self.max_sleeps:
            raise _Runaway()
        self.mono += s


def test_wall_clock_step_back_does_not_extend_the_lifetime_cap():
    clock = _SteppedClock(max_sleeps=1200)   # 2x the 600 one-second ticks
    req = _H()
    with mock.patch.object(rs, "time", clock), \
            mock.patch.object(rs, "_state_payload_cached", return_value=b'{"x":3}'), \
            mock.patch.object(rs, "_SSE_TICK_S", 1.0), \
            mock.patch.object(rs, "_SSE_MAX_DURATION_S", 600.0), \
            mock.patch.object(rs, "_sse_count", 0):
        try:
            rs._serve_state_stream(req)
        except _Runaway:
            raise AssertionError(
                "a wall clock stepped back kept the stream open past its cap")
        assert rs._sse_count == 0
    assert clock.sleeps <= 601


def test_wall_clock_step_back_does_not_suppress_the_heartbeat():
    clock = _SteppedClock(max_sleeps=1200)
    req = _H()
    with mock.patch.object(rs, "time", clock), \
            mock.patch.object(rs, "_state_payload_cached", return_value=b'{"x":4}'), \
            mock.patch.object(rs, "_SSE_TICK_S", 1.0), \
            mock.patch.object(rs, "_SSE_MAX_DURATION_S", 120.0), \
            mock.patch.object(rs, "_sse_count", 0):
        try:
            rs._serve_state_stream(req)
        except _Runaway:
            pass
    # Unchanged payload: one emit at start, then one per 15 s heartbeat.
    emits = req.wfile.getvalue().count(b'data: {"x":4}')
    assert emits >= 120 // int(rs._SSE_HEARTBEAT_S), emits
