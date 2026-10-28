"""
tests/snapshot_panels/test_mock_server_teardown_s144q13.py
RM-1023 (RM-909 follow-up (c), part 2) - the snapshot_panels mock server
left one handler thread per rendered page alive after the session ended.

Measured one file per process before the fix: test_home_snapshot_card.py
left 4 `Thread-N (process_request_thread)` threads and
test_ds_statcheck_champ_rebind_rm196.py left 1 - one per page, because every
page boot opens /api/state-stream and `_send_sse` then held that handler in
an unconditional 15 s sleep. `_MockServer.stop()` only called `shutdown()`,
which stops `serve_forever` but neither wakes a held handler nor closes the
listening socket (`server_close()` was never called, and ThreadingHTTPServer
handler threads are daemons, so even `server_close()` would not join them).

The contract pinned here:
  - while the server runs, the SSE hold still HOLDS (the render-timing
    behaviour the `_send_sse` docstring records must not change);
  - `stop()` releases every held handler, joins it, and closes the
    listening socket, and it returns promptly.
"""
import http.client
import threading
import time

from tests.snapshot_panels.conftest import _MockServer


def _handler_threads() -> set:
    return {t for t in threading.enumerate()
            if "process_request_thread" in t.name}


def _open_stream(srv: _MockServer) -> http.client.HTTPConnection:
    """Open /api/state-stream and read the one event, so the handler is
    parked in the SSE hold when this returns."""
    host, port = srv.url.split("//", 1)[1].split(":")
    conn = http.client.HTTPConnection(host, int(port), timeout=10)
    conn.request("GET", "/api/state-stream")
    resp = conn.getresponse()
    assert resp.status == 200
    assert resp.fp.readline().startswith(b"data: ")
    return conn


def test_sse_hold_still_holds_while_the_server_runs():
    before = _handler_threads()
    srv = _MockServer()
    srv.set_fixture("lobby")
    srv.start()
    conn = None
    try:
        conn = _open_stream(srv)
        time.sleep(0.5)
        held = _handler_threads() - before
        assert held, "the SSE handler returned at once; the hold is gone"
        assert all(t.is_alive() for t in held)
    finally:
        if conn is not None:
            conn.close()
        srv.stop()


def test_stop_releases_and_joins_every_sse_handler():
    before = _handler_threads()
    srv = _MockServer()
    srv.set_fixture("lobby")
    srv.start()
    conns = [_open_stream(srv) for _ in range(3)]
    for c in conns:
        c.close()
    started = time.monotonic()
    srv.stop()
    elapsed = time.monotonic() - started
    left = [t.name for t in _handler_threads() - before if t.is_alive()]
    assert left == [], f"handler threads outlived stop(): {left}"
    assert elapsed < 5.0, f"stop() took {elapsed:.1f}s"


class _SlowReleaseEvent(threading.Event):
    """A `closing` event whose waiters linger 1 s after release, so a
    `stop()` that does not JOIN its handlers returns while they still run
    (`shutdown()` alone takes about 0.5 s, its poll interval)."""

    def wait(self, timeout=None):
        fired = super().wait(timeout)
        time.sleep(1.0)
        return fired


def test_stop_joins_a_handler_that_is_still_finishing():
    before = _handler_threads()
    srv = _MockServer()
    srv._closing = _SlowReleaseEvent()
    srv.set_fixture("lobby")
    srv.start()
    conn = _open_stream(srv)
    conn.close()
    srv.stop()
    left = [t.name for t in _handler_threads() - before if t.is_alive()]
    assert left == [], f"stop() returned before joining: {left}"


def test_stop_closes_the_listening_socket():
    srv = _MockServer()
    srv.start()
    server = srv._server
    srv.stop()
    assert server.socket.fileno() == -1, "listening socket still open"
