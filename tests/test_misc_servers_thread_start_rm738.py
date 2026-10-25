"""RM-738 part 3: four more thread-per-request servers keep RM-735's wedge.

THE WEDGE (RM-735, reproduced on :8889 in session 108): socketserver
``ThreadingMixIn.process_request`` starts one thread per request FROM the
``serve_forever`` thread, and ``Thread.start()`` then waits on
``self._started`` with NO timeout. ``_started`` is set inside the NEW thread
(``Thread._bootstrap_inner``, after ``_set_ident`` / ``_set_native_id``), so a
thread that dies in bootstrap - MemoryError under commit-charge exhaustion,
RM-737 - parks the accept loop forever while the listen socket stays bound.

The four servers here, each built by its own production code path:

  supervisor  agents/_supervisor_http.py ``start_web_server`` -> ``_WebServer``
              (socketserver.ThreadingTCPServer), :8890
  mc          mc/server.py ``_make_server`` (ThreadingHTTPServer), :8895
  matchdb     tools/ds_matchdb_mcp_server.py ``serve_forever``
              (ThreadingHTTPServer), :8861
  replay      tools/replay_session.py ``make_server`` (ThreadingHTTPServer),
              dev CLI, default :8897

Each keeps thread-per-request (no concurrency cap is introduced) but caps the
wait ``Thread.start()`` makes: a thread that has not started within
``thread_start_timeout_s`` is abandoned and its connection is closed, so the
client sees EOF / reset instead of a hang and the next request is served.
The tests lower the cap so a run stays fast. Against the pre-RM-738 servers
the first test hangs on the faulted request (measured red); the second shows
the abandoned request being served late, on a socket the accept loop had
already given up on.

Fault seam: ``threading.Thread._set_native_id`` (RM-735's, present on 3.12 CI
and 3.14 Legion). No skip on purpose: if the seam disappears, patch.object
raises and these FAIL rather than go quietly vacuous.

RM-740 (b): a ``Thread.start()`` that itself RAISES (``RuntimeError: can't
start new thread``) is a failed start too. Before the fix the exception left
``process_request``; socketserver's ``_handle_request_noblock`` closed the
connection through ``handle_error`` + ``shutdown_request``, so the client saw
a close, but ``thread_start_failures`` stayed 0 and no RM-738 line was
logged (measured red on all four servers). The dashboard
(``dashboard/server.py`` ``_GuardedThreadStartMixin``) and DS servers already
caught it; these four now do the same.
"""
from __future__ import annotations

import contextlib
import io
import socket
import socketserver
import sys
import threading
import time
from unittest import mock

import pytest

# The simulated fault kills a thread in bootstrap, outside run(); CPython
# reports that through sys.unraisablehook, which pytest turns into a warning.
# That death is the scenario under test, not a defect of the test.
pytestmark = pytest.mark.filterwarnings(
    "ignore::pytest.PytestUnraisableExceptionWarning")

_FAULT = "commit charge exhausted (simulated, RM-738)"
_CAP_S = 0.3


class _Hung(AssertionError):
    pass


def _request(port: int, path: str, timeout: float = 3.0) -> tuple[str, int | None]:
    """One raw HTTP/1.0 GET. ("served", status) or ("closed", None); raises
    _Hung when the server neither answers nor closes within ``timeout``."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout) as s:
            s.sendall(f"GET {path} HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n".encode())
            buf = b""
            try:
                while True:
                    chunk = s.recv(4096)
                    if not chunk:
                        break
                    buf += chunk
            except (ConnectionResetError, ConnectionAbortedError):
                if not buf:
                    return ("closed", None)
    except TimeoutError as exc:
        raise _Hung(f"no answer and no close on {path} within {timeout}s: "
                    f"the accept loop is parked in Thread.start() "
                    f"(RM-735/RM-738 wedge)") from exc
    if not buf:
        return ("closed", None)
    return ("served", int(buf.split(b" ", 2)[1]))


def _serve(srv) -> None:
    threading.Thread(target=srv.serve_forever, daemon=True,
                     name="rm738-serve").start()


def _close(srv) -> None:
    # Bounded: a wedged accept loop never acknowledges shutdown(), and a
    # teardown that blocked forever would hang the run instead of reporting.
    stopper = threading.Thread(target=srv.shutdown, daemon=True)
    stopper.start()
    stopper.join(timeout=2)
    srv.server_close()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# -- the four servers, each from its production constructor -----------------

def _supervisor(tmp_path, monkeypatch):
    from agents import _supervisor_http as mod
    (tmp_path / "ok.txt").write_text("ok\n", encoding="utf-8")
    monkeypatch.setattr(mod, "WEB_ROOT", tmp_path)
    srv = mod.start_web_server(port=0)       # starts its own serve thread
    return srv, "/ok.txt"


def _mc(tmp_path, monkeypatch):
    from mc import server as mod

    class _PlainContext:
        # TLS is not under test here; the accept path is.
        def wrap_socket(self, sock, server_side=False):
            return sock

    monkeypatch.setattr(mod, "PORT", 0)
    srv = mod._make_server("127.0.0.1", _PlainContext())
    _serve(srv)
    return srv, "/rm738-unrouted"            # JSON 404, no route code runs


def _matchdb(tmp_path, monkeypatch):
    # serve_forever builds and runs its server inline; capture the instance
    # it runs so the test talks to exactly what production binds.
    import tools.ds_matchdb_mcp_server as mod
    port = _free_port()
    captured: list = []
    real = socketserver.BaseServer.serve_forever

    def recording(self, *a, **kw):
        captured.append(self)
        return real(self, *a, **kw)

    # On the class this server builds (its own subclass), never the shared
    # socketserver.BaseServer every other server of the worker inherits
    # serve_forever from (RM-880).
    with mock.patch.object(mod._MatchDBHTTPServer, "serve_forever", recording):
        threading.Thread(target=mod.serve_forever, args=("127.0.0.1", port),
                         daemon=True, name="rm738-matchdb").start()
        deadline = time.monotonic() + 5
        while not captured and time.monotonic() < deadline:
            time.sleep(0.01)
    assert captured, "ds_matchdb_mcp_server.serve_forever never served"
    return captured[0], "/health"            # 401 without the bearer token


def _replay(tmp_path, monkeypatch):
    from tools import replay_session as rs
    srv = rs.make_server(rs.ReplayState({}), port=0)
    _serve(srv)
    return srv, "/api/state"                 # 404 no_frame_yet


_SERVERS = {"matchdb": _matchdb, "mc": _mc, "replay": _replay,
            "supervisor": _supervisor}


@pytest.fixture(params=sorted(_SERVERS))
def served(request, tmp_path, monkeypatch):
    srv, path = _SERVERS[request.param](tmp_path, monkeypatch)
    try:
        yield srv, srv.server_address[1], path
    finally:
        _close(srv)


@contextlib.contextmanager
def _bootstrap_fault(srv, side_effect):
    """Arm the fault, with the server's start cap lowered for the window only
    (requests outside it keep the production cap, so a loaded CI box cannot
    turn a slow-but-healthy start into a dropped control request)."""
    srv.thread_start_timeout_s = _CAP_S
    try:
        with mock.patch.object(threading.Thread, "_set_native_id",
                               side_effect=side_effect):
            yield
    finally:
        del srv.thread_start_timeout_s


def test_a_thread_dying_in_bootstrap_drops_that_connection_and_keeps_serving(served):
    srv, port, path = served
    assert _request(port, path)[0] == "served", "control request before the fault"
    with _bootstrap_fault(srv, MemoryError(_FAULT)):
        try:
            outcome = _request(port, path, timeout=3)
        except _Hung as exc:
            pytest.fail(str(exc))
    assert outcome == ("closed", None), (
        "the request whose thread died must be dropped, not answered")
    assert _request(port, path)[0] == "served", "the next request must be served"
    assert srv.thread_start_failures == 1


def test_a_thread_that_starts_after_the_cap_never_touches_the_dropped_socket(served):
    srv, port, path = served
    handled: list = []
    real_finish = srv.finish_request

    def counting(request, client_address):
        handled.append(client_address)
        return real_finish(request, client_address)

    srv.finish_request = counting
    woke = threading.Event()

    def slow_bootstrap(*_a):
        time.sleep(_CAP_S * 3)               # alive, just later than the cap
        woke.set()

    with _bootstrap_fault(srv, slow_bootstrap):
        outcome = _request(port, path, timeout=3)
        assert woke.wait(5), "the slow thread never finished bootstrapping"
    time.sleep(0.3)                          # let it reach run()
    assert outcome == ("closed", None), "past the cap the connection is dropped"
    assert handled == [], "an abandoned thread ran the request anyway"
    assert _request(port, path)[0] == "served"
    assert len(handled) == 1


def test_the_default_start_cap_is_short_and_finite(served):
    srv, _port, _path = served
    cap = type(srv).thread_start_timeout_s
    assert 0 < cap <= 5, cap


# Where each server reports a failed start: its module logger's warning(), or
# stderr for the replay dev CLI, which has no logger.
_REPORTERS = {
    "agents._supervisor_http": "log",
    "mc.server": "log",
    "tools.ds_matchdb_mcp_server": "log",
    "tools.replay_session": None,
}


@contextlib.contextmanager
def _reports(srv):
    """Collect what the server reports while the window is open."""
    seen: list[str] = []
    module_name = type(srv).__module__
    assert module_name in _REPORTERS, f"unmapped server module {module_name}"
    attr = _REPORTERS[module_name]
    if attr is None:
        class _Lines(io.StringIO):
            def write(self, s):
                seen.append(s)
                return len(s)

        patcher = mock.patch.object(sys, "stderr", _Lines())
    else:
        def warning(msg, *args, **_kw):
            seen.append(msg % args if args else msg)

        logger = getattr(sys.modules[module_name], attr)
        patcher = mock.patch.object(logger, "warning", warning)
    with patcher:
        yield seen


def test_a_start_that_raises_is_counted_logged_and_dropped(served):
    """RM-740 (b): ``Thread.start()`` raising is dropped, counted and logged
    by the server itself (first and every 100th, like a missed cap), never
    left to escape into socketserver's ``handle_error`` uncounted."""
    srv, port, path = served
    escaped: list = []
    srv.handle_error = lambda _request, client_address: escaped.append(
        client_address)
    assert _request(port, path)[0] == "served", "control request before the fault"
    with _reports(srv) as reports, mock.patch.object(
            threading.Thread, "start",
            side_effect=RuntimeError("can't start new thread")):
        try:
            first = _request(port, path, timeout=3)
            second = _request(port, path, timeout=3)
        except _Hung as exc:
            pytest.fail(str(exc))
    assert first == second == ("closed", None), (
        "a request whose thread could not start must be dropped")
    assert escaped == [], (
        "the start error escaped process_request into handle_error")
    assert srv.thread_start_failures == 2
    logged = [r for r in reports if "(RM-738)" in r]
    assert len(logged) == 1, f"first failure logged, second not: {reports!r}"
    assert "can't start new thread" in logged[0], logged[0]
    assert "#1" in logged[0], logged[0]
    assert _request(port, path)[0] == "served", "the next request must be served"
