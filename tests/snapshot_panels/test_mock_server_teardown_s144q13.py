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
    listening socket, and it returns promptly;
  - that includes a handler parked on an idle connection - a Windows
    HTTP/1.1 keep-alive connection the client left open - which has no
    read timeout, so `stop()` ends the accepted connection itself
    (RM-1025).

A handler thread is this server's when the passive lineage hook in
tests/_module_view.py traces it to the server's serve_forever thread, not
when its name says `process_request_thread`: another stdlib server serving
in the same worker meanwhile must not read as a leak (RM-1029).
"""
import http.client
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from tests import _module_view
from tests.snapshot_panels.conftest import _MockServer


def _from_server(thread, srv: _MockServer, before: set) -> bool:
    """True when `thread` descends from `srv`'s serve_forever thread, by the
    creator lineage the passive audit hook in tests/_module_view.py records.
    A thread whose nearest pre-existing ancestor is some OTHER thread alive
    at `before` (another server, pool or poller in the same worker) is not
    this server's handler (RM-1029); a thread with no recorded creator is
    still counted, the old answer."""
    seen = set()
    while thread not in seen:
        seen.add(thread)
        creator, _file = _module_view._lineage_of(thread)
        if creator is None or creator is srv.serve_thread:
            return True
        if creator in before:
            return False
        thread = creator
    return True


def _server_threads(srv: _MockServer, before: set) -> list:
    """Live threads that appeared since `before` and that `srv` started."""
    return [t for t in threading.enumerate()
            if t not in before and t.is_alive()
            and _from_server(t, srv, before)]


def _left_after(srv: _MockServer, before: set) -> list:
    """Names of `srv`'s handler threads still alive."""
    return [t.name for t in _server_threads(srv, before)]


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
    before = set(threading.enumerate())
    srv = _MockServer()
    srv.set_fixture("lobby")
    srv.start()
    conn = None
    try:
        conn = _open_stream(srv)
        time.sleep(0.5)
        held = _server_threads(srv, before)
        assert held, "the SSE handler returned at once; the hold is gone"
    finally:
        if conn is not None:
            conn.close()
        srv.stop()


def test_stop_releases_and_joins_every_sse_handler():
    before = set(threading.enumerate())
    srv = _MockServer()
    srv.set_fixture("lobby")
    srv.start()
    conns = [_open_stream(srv) for _ in range(3)]
    for c in conns:
        c.close()
    started = time.monotonic()
    srv.stop()
    elapsed = time.monotonic() - started
    left = _left_after(srv, before)
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
    before = set(threading.enumerate())
    srv = _MockServer()
    srv._closing = _SlowReleaseEvent()
    srv.set_fixture("lobby")
    srv.start()
    conn = _open_stream(srv)
    conn.close()
    srv.stop()
    left = _left_after(srv, before)
    assert left == [], f"stop() returned before joining: {left}"


def _wait_for_handler(srv: _MockServer, before: set) -> list:
    """Poll until `srv` has started a handler thread for an accepted
    connection, so a test knows the handler is parked before it stops."""
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        held = _server_threads(srv, before)
        if held:
            return held
        time.sleep(0.02)
    return []


def test_stop_ends_a_handler_parked_on_an_idle_connection(capfd):
    """RM-1025: a handler blocked reading a request that never comes
    (the state an idle keep-alive connection leaves it in) has no read
    timeout, so `stop()` used to spend its whole join budget and return
    with that thread alive. It must end the connection itself, and the
    read it cuts must not print a traceback."""
    before = set(threading.enumerate())
    srv = _MockServer()
    srv.start()
    host, port = srv.url.split("//", 1)[1].split(":")
    client = socket.create_connection((host, int(port)), timeout=10)
    try:
        assert _wait_for_handler(srv, before), "control: no handler parked"
        started = time.monotonic()
        srv.stop()
        elapsed = time.monotonic() - started
        left = _left_after(srv, before)
        assert left == [], f"idle handler outlived stop(): {left}"
        assert elapsed < 2.0, f"stop() waited {elapsed:.1f}s on an idle handler"
        err = capfd.readouterr().err
        assert "Traceback" not in err, f"stop() printed: {err}"
    finally:
        client.close()
        srv.stop()


def test_a_finished_connection_is_forgotten():
    """A connection its handler already closed must leave the server's
    open-connection set, so `stop()` never shuts down or cancels I/O on
    a closed (and possibly reused) socket handle (RM-1025)."""
    before = set(threading.enumerate())
    srv = _MockServer()
    srv.set_fixture("lobby")
    srv.start()
    host, port = srv.url.split("//", 1)[1].split(":")
    conn = http.client.HTTPConnection(host, int(port), timeout=10)
    try:
        conn.request("GET", "/api/state", headers={"Connection": "close"})
        conn.getresponse().read()
        for t in _wait_for_handler(srv, before):
            t.join(5)
        assert _left_after(srv, before) == [], "control: handler still open"
        assert srv._server._open_requests == set()
    finally:
        conn.close()
        srv.stop()


@pytest.mark.skipif(sys.platform != "win32",
                    reason="keep-alive (HTTP/1.1) is the Windows-only path; "
                           "HTTP/1.0 closes after every response")
def test_stop_ends_an_idle_keep_alive_connection():
    """RM-1025, the real shape: one request answered on a persistent
    connection that the client then leaves open. The connection must stay
    up while the server runs (keep-alive is the Windows flake fix) and must
    not survive `stop()`."""
    before = set(threading.enumerate())
    srv = _MockServer()
    srv.set_fixture("lobby")
    srv.start()
    host, port = srv.url.split("//", 1)[1].split(":")
    conn = http.client.HTTPConnection(host, int(port), timeout=10)
    try:
        conn.request("GET", "/api/state")
        resp = conn.getresponse()
        resp.read()
        assert resp.status == 200
        time.sleep(0.3)
        assert _server_threads(srv, before), (
            "control: the keep-alive connection closed while the server ran")
        started = time.monotonic()
        srv.stop()
        elapsed = time.monotonic() - started
        left = _left_after(srv, before)
        assert left == [], f"keep-alive handler outlived stop(): {left}"
        assert elapsed < 2.0, f"stop() waited {elapsed:.1f}s on keep-alive"
    finally:
        conn.close()
        srv.stop()


def test_stop_closes_the_listening_socket():
    srv = _MockServer()
    srv.start()
    server = srv._server
    srv.stop()
    assert server.socket.fileno() == -1, "listening socket still open"


class _ForeignHold(BaseHTTPRequestHandler):
    """A stdlib handler that holds its request until released: another
    module's ThreadingHTTPServer serving in the same worker (RM-1029)."""
    release = threading.Event()

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()
        self.wfile.flush()
        self.release.wait(10)

    def log_message(self, *args):
        pass


@pytest.mark.parametrize("foreign_first", [True, False],
                         ids=["foreign-server-predates", "foreign-server-mid-test"])
def test_a_foreign_handler_is_not_blamed_on_stop(foreign_first):
    """A handler thread some OTHER server starts while this test runs is
    not this server's handler, so it must not read as one that outlived
    stop() (RM-1029: the check used to go by thread name alone)."""
    foreign = None
    foreign_live = []
    _ForeignHold.release.clear()

    def start_foreign():
        server = ThreadingHTTPServer(("127.0.0.1", 0), _ForeignHold)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return server

    if foreign_first:
        foreign = start_foreign()
    before = set(threading.enumerate())
    if not foreign_first:
        foreign = start_foreign()
    srv = _MockServer()
    srv.set_fixture("lobby")
    srv.start()
    conn = None
    try:
        c = _open_stream(srv)
        c.close()
        conn = http.client.HTTPConnection(*foreign.server_address, timeout=10)
        conn.request("GET", "/")
        assert conn.getresponse().status == 200
        srv.stop()
        foreign_live = [t for t in threading.enumerate()
                        if t not in before and t.is_alive()
                        and "process_request_thread" in t.name]
        assert foreign_live, "control: the foreign handler is not held"
        assert _left_after(srv, before) == []
    finally:
        _ForeignHold.release.set()
        if conn is not None:
            conn.close()
        srv.stop()
        foreign.shutdown()
        foreign.server_close()
        for t in foreign_live:
            t.join(5)


def test_an_unrecorded_new_thread_is_still_counted(monkeypatch):
    """A new thread whose creator the audit hook never recorded is counted
    as this server's, so a lineage gap cannot hide a leaked handler."""
    srv = _MockServer()
    before = set(threading.enumerate())
    hold = threading.Event()
    t = threading.Thread(target=hold.wait, args=(10,), daemon=True)
    t.start()
    try:
        assert t not in _server_threads(srv, before)
        monkeypatch.setattr(_module_view, "_lineage_of",
                            lambda thread: _module_view._UNRECORDED)
        assert t in _server_threads(srv, before)
    finally:
        hold.set()
        t.join(5)
