"""A server restart must not end with nothing listening (session 129).

Measured 2026-10-23: after ``schtasks /End /TN RC-DS-MatchDB-MCP`` the old
process lingered; an immediate ``/Run`` found :8861 still bound, logged "port
8861 already bound - skipping (exit 0)" and exited, then the old pid died and
:8861 stayed down until a second ``/Run``. The same point-in-time "held means
live" check sat in ``tools/start_daemon_slayer.py``, in
``tools/ds_matchdb_mcp_server.serve_forever`` and in ``vision_server.main``.

Every test here is in-process on ephemeral loopback ports: a "dying holder"
is a real listening socket closed by a timer, a "live holder" is a real HTTP
server, a "mute holder" is a listening socket that never accepts. No
scheduled task, live port or live log is touched (each launcher's startup
log is injected).
"""
from __future__ import annotations

import http.server
import importlib.util
import json
import os
import socket
import threading
import time
from pathlib import Path

import pytest

from core import port_handoff
from core.port_handoff import FREE, LIVE, STUCK, await_port, health_answers

_ROOT = Path(__file__).resolve().parent.parent


# -- holders ---------------------------------------------------------------------
def _listening_socket() -> tuple[socket.socket, int]:
    """A real listener on an ephemeral loopback port that never accepts."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    s.listen(8)
    return s, s.getsockname()[1]


@pytest.fixture()
def dying_holder():
    """A holder that releases its port ~0.4 s from now (the lingering old pid)."""
    s, port = _listening_socket()
    timer = threading.Timer(0.4, s.close)
    timer.start()
    try:
        yield port
    finally:
        timer.cancel()
        s.close()


@pytest.fixture()
def mute_holder():
    """Bound and listening, never answers: a wedged or foreign holder."""
    s, port = _listening_socket()
    try:
        yield port
    finally:
        s.close()


def _serve(handler_cls) -> tuple[http.server.ThreadingHTTPServer, threading.Thread]:
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, t


def _stop(srv, t) -> None:
    srv.shutdown()
    srv.server_close()
    t.join(timeout=5)


def _json_handler(status: int, doc: dict):
    body = json.dumps(doc).encode()

    class _H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - stdlib name
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    return _H


@pytest.fixture()
def http_holder():
    """Start a JSON server answering every GET with (status, doc); yield its port."""
    started = []

    def _start(status: int, doc: dict) -> int:
        srv, t = _serve(_json_handler(status, doc))
        started.append((srv, t))
        return srv.server_address[1]

    yield _start
    for srv, t in started:
        _stop(srv, t)


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# -- core.port_handoff --------------------------------------------------------------
def test_a_free_port_is_free_at_once_and_the_holder_is_never_asked():
    asked = []
    h = await_port("127.0.0.1", _free_port(), holder_live=lambda: asked.append(1),
                   window_s=5.0, poll_s=0.05)
    assert h.state == FREE
    assert h.waited_s < 1.0
    assert asked == []


def test_a_holder_that_dies_inside_the_window_hands_the_port_over(dying_holder):
    # The measured race: the old pid still holds the port when the new start
    # looks, then dies. The new start must take the port, not skip.
    h = await_port("127.0.0.1", dying_holder, holder_live=lambda: True,
                   window_s=10.0, poll_s=0.05)
    assert h.state == FREE
    assert 0.3 <= h.waited_s < 5.0


def test_an_answering_holder_is_trusted_only_after_the_whole_window():
    # A process being ended can still answer for a moment. Bind fails three
    # times, then succeeds; the holder "answers" throughout - it must never be
    # consulted before the window ends, so the verdict is FREE, not LIVE.
    t = [0.0]
    binds = iter([False, False, False, True])
    asked = []
    h = await_port("127.0.0.1", 1, window_s=10.0, poll_s=1.0,
                   holder_live=lambda: asked.append(t[0]) or True,
                   bind_ok=lambda host, port: next(binds),
                   clock=lambda: t[0],
                   sleep=lambda s: t.__setitem__(0, t[0] + s))
    assert h.state == FREE
    assert asked == []
    assert h.waited_s == pytest.approx(3.0)


def test_a_live_holder_at_the_end_of_the_window_is_LIVE(http_holder):
    port = http_holder(200, {"alive": True})
    h = await_port("127.0.0.1", port, window_s=0.3, poll_s=0.05,
                   holder_live=lambda: health_answers("127.0.0.1", port))
    assert h.state == LIVE
    assert h.waited_s >= 0.3


def test_a_mute_holder_is_STUCK_never_reported_as_serving(mute_holder):
    h = await_port("127.0.0.1", mute_holder, window_s=0.3, poll_s=0.05,
                   holder_live=lambda: health_answers("127.0.0.1", mute_holder,
                                                      timeout_s=0.5))
    assert h.state == STUCK


def test_a_raising_liveness_probe_is_not_a_live_holder(mute_holder):
    def _boom():
        raise RuntimeError("probe broke")
    h = await_port("127.0.0.1", mute_holder, window_s=0.1, poll_s=0.05,
                   holder_live=_boom)
    assert h.state == STUCK


def test_a_holder_that_dies_during_the_liveness_probe_is_FREE():
    binds = iter([False, True])
    h = await_port("127.0.0.1", 1, window_s=0.0, holder_live=lambda: False,
                   bind_ok=lambda host, port: next(binds))
    assert h.state == FREE


def test_the_probe_bind_cannot_co_bind_a_reuseaddr_server(http_holder):
    # The real servers bind WITH SO_REUSEADDR (HTTPServer.allow_reuse_address);
    # the probe must still see their port as held.
    port = http_holder(200, {})
    assert port_handoff.can_bind("127.0.0.1", port) is False


def test_health_answers_needs_a_200_and_the_check(http_holder):
    ok = http_holder(200, {"engine_version": "x"})
    unauth = http_holder(401, {"error": "unauthorized"})
    by_shape = port_handoff.json_check(lambda d: "engine_version" in d)
    assert health_answers("127.0.0.1", ok, check=by_shape) is True
    assert health_answers("127.0.0.1", ok,
                          check=port_handoff.json_check(lambda d: "alive" in d)) is False
    assert health_answers("127.0.0.1", unauth) is False
    assert health_answers("127.0.0.1", _free_port(), timeout_s=0.5) is False


# -- the two launchers ----------------------------------------------------------------
def _load_launcher(rel: str):
    """Load a launcher in isolation; it chdirs to the repo root at import."""
    cwd = os.getcwd()
    try:
        name = "_c10_" + Path(rel).stem
        spec = importlib.util.spec_from_file_location(name, _ROOT / rel)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        os.chdir(cwd)


_LAUNCHERS = ("tools/start_ds_matchdb_mcp.py", "tools/start_daemon_slayer.py")


@pytest.fixture(params=_LAUNCHERS, scope="module")
def launcher(request):
    return _load_launcher(request.param)


class _Run:
    def __init__(self, code: int = 7) -> None:
        self.code = code
        self.served: list[tuple[str, int]] = []
        self.lines: list[str] = []

    def serve(self, host: str, port: int) -> int:
        self.served.append((host, port))
        return self.code

    def log(self, msg: str) -> None:
        self.lines.append(msg)


def test_launcher_starts_on_a_free_port(launcher):
    run = _Run()
    port = _free_port()
    code = launcher.main(host="127.0.0.1", port=port, serve=run.serve, log=run.log,
                         window_s=5.0, poll_s=0.05)
    assert run.served == [("127.0.0.1", port)]
    assert code == 7


def test_launcher_waits_out_a_dying_holder_and_starts(launcher, dying_holder):
    # The measured RC-DS-MatchDB-MCP failure: /End, then /Run while the old
    # pid still held the port. Before the fix the launcher exited 0 at once
    # and nothing listened after the old pid died.
    run = _Run()
    code = launcher.main(host="127.0.0.1", port=dying_holder, serve=run.serve,
                         log=run.log, window_s=10.0, poll_s=0.05,
                         holder_live=lambda: True)
    assert run.served == [("127.0.0.1", dying_holder)]
    assert code == 7
    assert any("released" in line for line in run.lines), run.lines


def test_launcher_skips_with_0_for_a_live_holder(launcher, http_holder):
    run = _Run()
    port = http_holder(200, {"alive": True})
    code = launcher.main(host="127.0.0.1", port=port, serve=run.serve, log=run.log,
                         window_s=0.3, poll_s=0.05, holder_live=lambda: True)
    assert code == 0
    assert run.served == []
    assert any("live" in line and "skipping" in line for line in run.lines), run.lines


def test_launcher_refuses_success_for_a_mute_holder(launcher, mute_holder):
    run = _Run()
    code = launcher.main(host="127.0.0.1", port=mute_holder, serve=run.serve,
                         log=run.log, window_s=0.3, poll_s=0.05)
    assert code == 1
    assert run.served == []
    assert any("not started" in line for line in run.lines), run.lines


def test_launcher_reports_a_serve_crash_as_exit_1(launcher):
    run = _Run()

    def _crash(host, port):
        raise RuntimeError("boom")

    code = launcher.main(host="127.0.0.1", port=_free_port(), serve=_crash,
                         log=run.log, window_s=1.0, poll_s=0.05)
    assert code == 1
    assert any("UNHANDLED EXCEPTION" in line for line in run.lines), run.lines


def test_launcher_live_check_rejects_a_foreign_http_holder(launcher, http_holder):
    # Something answers 200 on the port, but not as this server: not "live".
    run = _Run()
    port = http_holder(200, {"hello": "world"})
    code = launcher.main(host="127.0.0.1", port=port, serve=run.serve, log=run.log,
                         window_s=0.2, poll_s=0.05)
    assert code == 1
    assert run.served == []


def test_ds_launcher_live_check_accepts_a_ds_shaped_health(http_holder):
    sds = _load_launcher("tools/start_daemon_slayer.py")
    port = http_holder(200, {"status": "ok", "engine_version": "x"})
    assert sds.holder_is_ds("127.0.0.1", port) is True


# -- the match-DB server itself ----------------------------------------------------
@pytest.fixture(scope="module")
def mdb():
    from tools import ds_matchdb_mcp_server
    return ds_matchdb_mcp_server


@pytest.fixture()
def real_matchdb(mdb):
    srv, t = _serve(mdb._Handler)
    try:
        yield srv.server_address[1]
    finally:
        _stop(srv, t)


def test_matchdb_live_check_accepts_the_real_server(mdb, real_matchdb):
    assert mdb.holder_is_matchdb("127.0.0.1", real_matchdb) is True


def test_matchdb_launcher_skips_for_the_real_server(real_matchdb):
    smm = _load_launcher("tools/start_ds_matchdb_mcp.py")
    run = _Run()
    code = smm.main(host="127.0.0.1", port=real_matchdb, serve=run.serve,
                    log=run.log, window_s=0.2, poll_s=0.05)
    assert code == 0
    assert run.served == []


def test_matchdb_live_check_rejects_a_401(mdb, http_holder):
    port = http_holder(401, {"error": "unauthorized"})
    assert mdb.holder_is_matchdb("127.0.0.1", port) is False


class _FakeServer:
    instances: list = []

    def __init__(self, addr, handler) -> None:
        self.addr = addr
        _FakeServer.instances.append(self)

    def serve_forever(self) -> None:
        return None


@pytest.fixture()
def fake_bind(mdb, monkeypatch):
    _FakeServer.instances = []
    monkeypatch.setattr(mdb, "_MatchDBHTTPServer", _FakeServer)
    monkeypatch.setattr(mdb, "_HANDOFF_POLL_S", 0.05)
    return _FakeServer.instances


def test_matchdb_serve_forever_waits_out_a_dying_holder(mdb, fake_bind, dying_holder,
                                                        monkeypatch):
    monkeypatch.setattr(mdb, "_HANDOFF_WINDOW_S", 10.0)
    assert mdb.serve_forever("127.0.0.1", dying_holder) == 0
    assert [s.addr for s in fake_bind] == [("127.0.0.1", dying_holder)]


def test_matchdb_serve_forever_exits_0_for_a_live_instance(mdb, fake_bind,
                                                           real_matchdb, monkeypatch):
    monkeypatch.setattr(mdb, "_HANDOFF_WINDOW_S", 0.2)
    assert mdb.serve_forever("127.0.0.1", real_matchdb) == 0
    assert fake_bind == []


def test_matchdb_serve_forever_exits_1_for_a_mute_holder(mdb, fake_bind, mute_holder,
                                                         monkeypatch):
    monkeypatch.setattr(mdb, "_HANDOFF_WINDOW_S", 0.2)
    assert mdb.serve_forever("127.0.0.1", mute_holder) == 1
    assert fake_bind == []


# -- the vision server's start guard --------------------------------------------------
@pytest.fixture()
def vision_main(monkeypatch):
    """vision_server.main() with every side effect before the bind stubbed (the
    stale-instance reap kills real processes: it must never run from a test)."""
    import vision_server
    from vision_server import _reap
    made = []

    class _Srv:
        def serve_forever(self):
            return None

        def shutdown(self):
            return None

    def _make(host, port, handler=None):
        made.append((host, port))
        return _Srv()

    monkeypatch.setattr(vision_server, "api_key_present", lambda: True)
    monkeypatch.setattr(_reap, "reap_stale_vision_instances", lambda: [])
    monkeypatch.setattr(vision_server, "_get_client", lambda: None)
    monkeypatch.setattr(vision_server, "make_server", _make)
    monkeypatch.setattr(vision_server, "_HANDOFF_POLL_S", 0.05, raising=False)
    monkeypatch.delenv("RC_VISION_BIND", raising=False)
    return vision_server, made, monkeypatch


def test_vision_waits_out_a_dying_holder_then_binds(vision_main, dying_holder):
    # The watchdog kills a hung holder and spawns at once; the dying holder
    # still accepts connections. Before the fix main() saw the connect succeed,
    # returned 0 without binding, and :8889 stayed down until the watchdog's
    # 90 s grace ran out.
    vs, made, mp = vision_main
    mp.setattr(vs, "PORT", dying_holder)
    mp.setattr(vs, "_HANDOFF_WINDOW_S", 10.0, raising=False)
    assert vs.main() == 0
    assert made == [("127.0.0.1", dying_holder)]


def test_vision_still_exits_0_beside_a_live_instance(vision_main, http_holder):
    vs, made, mp = vision_main
    port = http_holder(200, {"alive": True})
    mp.setattr(vs, "PORT", port)
    mp.setattr(vs, "_HANDOFF_WINDOW_S", 0.2, raising=False)
    assert vs.main() == 0
    assert made == []


def test_vision_leaves_a_mute_holder_to_the_watchdog(vision_main, mute_holder):
    # A holder that accepts but never answers is the watchdog's to kill (it
    # verifies the holder is a vision process first); main() does not bind
    # over it, as before.
    vs, made, mp = vision_main
    mp.setattr(vs, "PORT", mute_holder)
    mp.setattr(vs, "_HANDOFF_WINDOW_S", 0.2, raising=False)
    t0 = time.monotonic()
    assert vs.main() == 0
    assert made == []
    assert time.monotonic() - t0 >= 0.2
