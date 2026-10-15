"""RM-740 (d): every RM-738 thread-start cap, checked against this box.

RM-738 bounds the wait ``Thread.start()`` makes in each in-tree
thread-per-request HTTP server: a request thread not started within
``thread_start_timeout_s`` loses its connection. The worry filed as RM-740
(d): under RM-737 commit-charge pressure a merely SLOW start could cross the
cap, and the client would read the dropped connection as the server being
down.

MEASURED (session 114, 2026-10-14, Legion, Python 3.14.4): a probe process
timed ``Thread.start()`` (start call to return, i.e. until the new thread
sets ``_started``) and the real dashboard ``_DualStackHTTPServer``'s guarded
``process_request`` while a gated ``-n 8 --dist loadfile`` dual suite ran
(the RM-737 condition; system commit peaked at 35.6 of 47.2 GiB = 75.4
percent, CPU max 83.8 percent, 430 s of full load):

  bare Thread.start()        n=20560  p50 0.15 ms  p99 1.17 ms  max 24.1 ms
  dashboard guarded server   n=8096   p50 0.18 ms  p99 1.26 ms  max 24.5 ms
  same, one GIL-busy thread  n=1547   p50 32.3 ms  p99 86.4 ms  max 156.5 ms
    in the probe process (over the whole 21-minute probe run: max 157.1 ms)

No start was dropped and no start raised. The worst start seen, 157 ms, is
about 1/13 of the 2.0 s caps and 1/32 of the DS 5.0 s cap, so every cap is
KEPT; the reasoning sits beside each cap in the code. A larger cap would buy
nothing measured and would park the accept loop longer behind a start that
truly died (RM-735's case, the one the cap exists for).

Two checks per server, each built by its production constructor:
  * a start that completes just under the class cap (cap minus 0.5 s, about
    3x the measured worst start) is SERVED - not dropped, not counted as a
    failed start - so the bounded wait honours a slow-but-alive thread for
    the whole cap;
  * each class cap stays at least 10x the measured worst start. Lowering a
    cap below that reds here: re-measure (this file's numbers) first.

Fault seam: ``threading.Thread._set_native_id`` (RM-735's, present on 3.12
CI and 3.14 Legion), slowed instead of killed. No skip on purpose: if the
seam disappears, patch.object raises and these FAIL.
"""
from __future__ import annotations

import importlib
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler
from unittest import mock

import pytest

from tests.test_misc_servers_thread_start_rm738 import (
    _SERVERS as _PART3_SERVERS,
)
from tests.test_misc_servers_thread_start_rm738 import _close, _serve

# The worst thread start measured under the gated -n 8 suite (module
# docstring), and the margins derived from it.
_MEASURED_WORST_START_S = 0.157
_UNDER_CAP_MARGIN_S = 0.5      # about 3x the worst start
_CAP_HEADROOM = 10             # each cap >= 10x the worst start

# (module, class) of every RM-738 server; the class default is the cap.
_CAP_OWNERS = {
    "dashboard_dual_stack": ("dashboard.server", "_DualStackHTTPServer"),
    "dashboard_tls": ("dashboard.server", "_DualProtocolHTTPServer"),
    "ds": ("agents.daemon_slayer.server", "_RcThreadingHTTPServer"),
    "matchdb": ("tools.ds_matchdb_mcp_server", "_MatchDBHTTPServer"),
    "mc": ("mc.server", "_Server"),
    "replay": ("tools.replay_session", "_ReplayHTTPServer"),
    "supervisor": ("agents._supervisor_http", "_WebServer"),
}


class _Ok(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 (stdlib name)
        body = b'{"ok": true}'
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a: object) -> None:
        pass


def _dashboard_dual_stack(tmp_path, monkeypatch):
    from dashboard import server
    srv = server._DualStackHTTPServer(("::1", 0), _Ok)
    _serve(srv)
    return srv, "::1", "/"


def _dashboard_tls(tmp_path, monkeypatch):
    # The TLS class with its accept reduced to a plain accept: the peek /
    # wrap / redirect is not under test, the class's process_request is.
    from dashboard import server

    class _PlainDualProtocol(server._DualProtocolHTTPServer):
        def get_request(self) -> tuple:
            return self.socket.accept()

    srv = _PlainDualProtocol(("::1", 0), _Ok, ssl_ctx=None)
    _serve(srv)
    return srv, "::1", "/"


def _ds(tmp_path, monkeypatch):
    from agents.daemon_slayer import server as ds_server
    from agents.daemon_slayer.data_loader import DataSnapshot
    srv = ds_server.start_server(host="127.0.0.1", port=0,
                                 snapshot=DataSnapshot.load())
    _serve(srv)
    return srv, "127.0.0.1", "/health"


def _part3(name):
    def make(tmp_path, monkeypatch):
        srv, path = _PART3_SERVERS[name](tmp_path, monkeypatch)
        return srv, "127.0.0.1", path
    return make


_FACTORIES = {
    "dashboard_dual_stack": _dashboard_dual_stack,
    "dashboard_tls": _dashboard_tls,
    "ds": _ds,
    **{name: _part3(name) for name in _PART3_SERVERS},
}


def test_every_rm738_server_is_covered():
    assert sorted(_FACTORIES) == sorted(_CAP_OWNERS)


@pytest.fixture(params=sorted(_FACTORIES))
def served(request, tmp_path, monkeypatch):
    srv, host, path = _FACTORIES[request.param](tmp_path, monkeypatch)
    try:
        yield srv, host, path
    finally:
        _close(srv)


def _request(host: str, port: int, path: str, timeout: float) -> tuple[str, int | None]:
    """One raw HTTP/1.0 GET: ("served", status) or ("closed", None)."""
    with socket.create_connection((host, port), timeout=timeout) as s:
        s.sendall(f"GET {path} HTTP/1.0\r\nHost: {host}\r\n\r\n".encode("ascii"))
        buf = b""
        try:
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                buf += chunk
        except (ConnectionResetError, ConnectionAbortedError):
            pass
    if not buf:
        return ("closed", None)
    return ("served", int(buf.split(b" ", 2)[1]))


def _start_failures(srv) -> int:
    # The dashboard mixin counts in start_failures; the others in
    # thread_start_failures.
    if hasattr(srv, "thread_start_failures"):
        return srv.thread_start_failures
    return srv.start_failures


def test_a_start_completing_just_under_the_cap_is_served(served):
    srv, host, path = served
    cap = type(srv).thread_start_timeout_s
    delay = cap - _UNDER_CAP_MARGIN_S
    assert delay > _MEASURED_WORST_START_S, (cap, delay)
    handled: list = []
    real_finish = srv.finish_request

    def counting(request, client_address):
        handled.append(client_address)
        return real_finish(request, client_address)

    srv.finish_request = counting
    assert _request(host, srv.server_address[1], path, timeout=5)[0] == "served", (
        "control request before the slow start")
    handled.clear()

    def slow_bootstrap(*_a):
        time.sleep(delay)                    # alive, just slower than usual

    t0 = time.monotonic()
    with mock.patch.object(threading.Thread, "_set_native_id",
                           side_effect=slow_bootstrap):
        outcome = _request(host, srv.server_address[1], path,
                           timeout=cap + 5)
    elapsed = time.monotonic() - t0
    assert elapsed >= delay, (
        f"the start was never slowed ({elapsed:.2f}s < {delay:.2f}s) - "
        "the seam did not fire, so this check proved nothing")
    assert outcome[0] == "served", (
        f"a start {delay:.2f}s long, under the {cap:.1f}s cap, was dropped")
    assert _start_failures(srv) == 0
    assert len(handled) == 1


@pytest.mark.parametrize("name", sorted(_CAP_OWNERS))
def test_each_cap_stays_far_above_the_measured_worst_start(name):
    module, cls = _CAP_OWNERS[name]
    cap = getattr(importlib.import_module(module), cls).thread_start_timeout_s
    assert cap >= _CAP_HEADROOM * _MEASURED_WORST_START_S, (
        f"{module}.{cls} cap {cap}s is under {_CAP_HEADROOM}x the worst "
        f"start measured on this box ({_MEASURED_WORST_START_S}s) - "
        "re-measure (see the module docstring) before lowering it")
