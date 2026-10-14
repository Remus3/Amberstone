"""RM-740 (c) + (g): the dashboard (:8888) and DS (:8860) guarded starts.

RM-738 bounded the per-request ``Thread.start()`` wait on both servers with a
one-shot claim lock: whoever takes the claim owns the request socket. Two
gaps were left in the same two ``process_request`` functions
(``dashboard/server.py`` ``_GuardedThreadStartMixin.process_request`` and
``agents/daemon_slayer/server.py`` ``_RcThreadingHTTPServer.process_request``):

(c) A thread that dies in bootstrap (the RM-735 MemoryError in
    ``_set_native_id``) never reaches ``del _limbo[self]`` in
    ``Thread._bootstrap_inner``, so its ``Thread`` object stays in
    ``threading._limbo`` for the process lifetime. The dashboard's target
    closure and DS's ``args`` both held the request, so every such failure
    pinned the dropped, closed request socket for good. The part-3 servers
    (``mc/server.py`` / ``agents/_supervisor_http.py`` ``_RequestThread``)
    drop their job reference in ``abandon_if_unstarted``; these two now do
    the same.

(g) A ``Thread.start()`` that RAISES was closed by the accept loop without
    the claim. ``start()`` can raise from its final ``_started.wait()``
    after the new thread is already running and has claimed the request;
    the accept loop then closed the socket under the serving thread. The
    part-3 servers ask ``abandon_if_unstarted()`` first since RM-740 (b);
    these two now take the claim (and respect a thread that came up) too.

Fault seams: ``threading.Thread._set_native_id`` (RM-735's, present on 3.12 CI
and 3.14 Legion) and each module's ``_BoundedStartEvent.wait`` (the wait
``Thread.start()`` ends in). No skip on purpose: if a seam disappears,
``patch.object`` raises and these FAIL rather than go quietly vacuous.
"""
from __future__ import annotations

import gc
import socket
import sys
import threading
import time
import urllib.request
import weakref
from http.server import BaseHTTPRequestHandler
from unittest import mock

import pytest

from agents.daemon_slayer import server as ds_server
from dashboard import server as dash_server

# The simulated fault kills a thread in bootstrap, outside run(); CPython
# reports that through sys.unraisablehook. That death is the scenario under
# test, not a defect of the test.
pytestmark = pytest.mark.filterwarnings(
    "ignore::pytest.PytestUnraisableExceptionWarning")

_FAULT = "commit charge exhausted (simulated, RM-740 c)"
_CLOSED = (ConnectionResetError, ConnectionAbortedError)


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 (stdlib name)
        body = b'{"ok": true}'
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a: object) -> None:
        pass


class _PlainDualProtocol(dash_server._DualProtocolHTTPServer):
    """The dashboard TLS class with its accept path reduced to a plain accept;
    its real ``process_request`` (the class MRO) is what is under test."""

    def __init__(self, server_address, handler_class) -> None:
        super().__init__(server_address, handler_class, ssl_ctx=None)

    def get_request(self) -> tuple:
        return self.socket.accept()


# (server class, bind host, module owning _BoundedStartEvent, failure counter)
_CASES = {
    "dashboard-dual-stack": (dash_server._DualStackHTTPServer, "::1",
                             dash_server, "start_failures"),
    "dashboard-dual-protocol": (_PlainDualProtocol, "::1",
                                dash_server, "start_failures"),
    "ds": (ds_server._RcThreadingHTTPServer, "127.0.0.1",
           ds_server, "thread_start_failures"),
}


@pytest.fixture(params=sorted(_CASES))
def served(request):
    cls, host, module, counter = _CASES[request.param]
    srv = cls((host, 0), _Handler)
    port = srv.server_address[1]
    serve = threading.Thread(target=srv.serve_forever, daemon=True,
                             name="rm740-cg-serve")
    serve.start()
    try:
        yield srv, host, port, module, counter
    finally:
        # Bounded: a wedged accept loop never acknowledges shutdown().
        stopper = threading.Thread(target=srv.shutdown, daemon=True)
        stopper.start()
        stopper.join(timeout=2)
        srv.server_close()
        serve.join(timeout=2)


def _url_host(host: str) -> str:
    return f"[{host}]" if ":" in host else host


def _get(host: str, port: int, timeout: float = 5.0) -> int:
    with urllib.request.urlopen(
            f"http://{_url_host(host)}:{port}/", timeout=timeout) as resp:
        resp.read()
        return resp.status


def _raw_request(host: str, port: int, timeout: float) -> bytes:
    """One request on a raw socket; every byte received before the server
    closed it. A reset counts as a close; a hang raises TimeoutError."""
    s = socket.create_connection((host, port), timeout=timeout)
    try:
        s.sendall(b"GET / HTTP/1.0\r\nHost: localhost\r\n\r\n")
        chunks = []
        while True:
            try:
                chunk = s.recv(4096)
            except _CLOSED:
                break
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        s.close()


def _chain_types(exc: BaseException | None) -> list[type]:
    seen: list[type] = []
    while exc is not None and len(seen) < 10:
        seen.append(type(exc))
        exc = exc.__context__
    return seen


def test_c_a_thread_dead_in_bootstrap_no_longer_pins_the_dropped_socket(served):
    """RM-740 (c): once the accept loop abandons a start, the thread object
    left in ``threading._limbo`` must not keep the request socket alive."""
    srv, host, port, _module, counter = served
    assert _get(host, port) == 200, "control request before the fault"
    dropped: list[weakref.ref] = []
    real_shutdown = srv.shutdown_request

    def recording_shutdown(request) -> None:
        dropped.append(weakref.ref(request))
        real_shutdown(request)

    # Only exception TYPES are kept: a stored traceback would pin frames.
    died: list[list[type]] = []
    limbo_before = set(threading._limbo)
    dead: list[threading.Thread] = []
    try:
        with mock.patch.object(sys, "unraisablehook",
                               lambda u: died.append(_chain_types(u.exc_value))), \
                mock.patch.object(threading.Thread, "_set_native_id",
                                  side_effect=MemoryError(_FAULT)):
            # The cap is lowered for the faulted request only (read per
            # request), so a loaded box cannot turn a slow-but-healthy
            # control request outside the window into a dropped one.
            srv.thread_start_timeout_s = 0.5
            srv.shutdown_request = recording_shutdown
            try:
                got = _raw_request(host, port, timeout=4.0)
            finally:
                del srv.shutdown_request
                del srv.thread_start_timeout_s
            deadline = time.monotonic() + 2
            while not died and time.monotonic() < deadline:
                time.sleep(0.02)
        dead = [t for t in list(threading._limbo)
                if t not in limbo_before and not t.is_alive()]
        assert any(MemoryError in chain for chain in died), (
            f"the armed fault never fired - vacuous: {died!r}")
        assert got == b"", "the failed request must be closed, not answered"
        assert getattr(srv, counter) == 1
        assert len(dead) == 1, (
            f"expected the bootstrap-dead thread left in threading._limbo: {dead!r}")
        assert len(dropped) == 1, dropped
        ref = dropped[0]
        deadline = time.monotonic() + 2
        while ref() is not None and time.monotonic() < deadline:
            gc.collect()
            time.sleep(0.02)
        assert ref() is None, (
            "the abandoned thread (left in threading._limbo) still pins the "
            "dropped request socket")
    finally:
        # The stdlib never drops these entries; this test's own are removed
        # so later tests see a clean table.
        with threading._active_limbo_lock:
            for t in dead:
                threading._limbo.pop(t, None)
    assert _get(host, port) == 200, "the next request must be served"


def test_g_a_start_wait_raising_after_the_thread_claimed_does_not_close_its_socket(served):
    """RM-740 (g): ``Thread.start()`` raising from its ``_started.wait()``
    after the new thread came up and claimed the request must leave the
    request to that thread: served exactly once, not closed under it."""
    srv, host, port, module, counter = served
    assert _get(host, port) == 200, "control request before the fault"
    entered = threading.Event()       # the request thread owns the request
    loop_done = threading.Event()     # the accept loop is done with it
    served_to: list = []
    handler_errors: list[str] = []
    fired: list[bool] = []

    def finish(request, client_address) -> None:
        # Read the request head first, so the close after the reply is a
        # clean FIN (unread bytes would turn it into a reset on Windows).
        request.settimeout(5)
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = request.recv(4096)
            if not chunk:
                break
            buf += chunk
        entered.set()
        loop_done.wait(5)
        request.sendall(b"HTTP/1.0 200 OK\r\nContent-Length: 2\r\n\r\nok")
        served_to.append(client_address)

    real_process = srv.process_request

    def process(request, client_address) -> None:
        try:
            real_process(request, client_address)
        finally:
            loop_done.set()

    real_wait = module._BoundedStartEvent.wait

    def raising_wait(event, timeout=None):
        ok = real_wait(event, timeout)
        if fired:
            return ok
        entered.wait(5)
        # Recorded after the claim, not from the bounded wait: a slow box
        # that misses the bound still proves the thread came up first.
        fired.append(event.is_set())
        raise RuntimeError("start wait failed after the thread came up "
                           "(simulated, RM-740 g)")

    srv.finish_request = finish
    srv.process_request = process
    srv.handle_error = lambda _request, _addr: handler_errors.append(
        repr(sys.exc_info()[1]))
    try:
        with mock.patch.object(module._BoundedStartEvent, "wait", raising_wait):
            got = _raw_request(host, port, timeout=12.0)
    finally:
        del srv.finish_request
        del srv.process_request
        del srv.handle_error
    assert fired == [True], (
        f"the start wait never ran with the thread up - vacuous: {fired!r}")
    assert got == b"HTTP/1.0 200 OK\r\nContent-Length: 2\r\n\r\nok", (
        "the accept loop closed the socket under the thread that had claimed "
        f"it: got {got!r}, handler errors {handler_errors!r}")
    assert len(served_to) == 1, "the claimed request must be served exactly once"
    assert handler_errors == []
    assert getattr(srv, counter) == 0, (
        "a start whose thread came up and owns its request is not a failed start")
    assert _get(host, port) == 200, "the next request must be served"


def test_g_a_start_that_raises_before_any_thread_runs_is_still_dropped(served):
    """The other side of (g): when no thread ever ran (``_start_new_thread``
    itself raised), the accept loop takes the claim and drops the request -
    counted, closed, and the next request is served."""
    srv, host, port, _module, counter = served
    with mock.patch.object(threading.Thread, "start",
                           side_effect=RuntimeError("can't start new thread")):
        got = _raw_request(host, port, timeout=4.0)
    assert got == b""
    assert getattr(srv, counter) == 1
    assert _get(host, port) == 200
