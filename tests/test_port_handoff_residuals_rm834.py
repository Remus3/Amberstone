"""RM-834: the port hand-off residuals left by RM-832 (session 129).

``core/port_handoff.await_port`` decides FREE / LIVE / STUCK after a held
port's window ends, by one ``/health`` probe of the holder. Three shapes:

(b) FIXED. The probe gave up after 2 s, so a genuinely live server whose
    ``/health`` took longer (a loaded box) read as "does not answer as this
    server": the launchers logged "not started (exit 1)" beside a server that
    was serving. The probe now waits ``HEALTH_TIMEOUT_S`` (10 s), read at call
    time, so a slow live holder reads LIVE.
(c) FIXED IN PART, rest ACCEPTED. ``health_answers`` sent its headers (the
    match-DB bearer) to any ``host`` a caller named; only ``await_port``
    checked loopback. It now refuses a non-loopback host before it opens a
    connection, so the bearer can only ever reach whatever holds a loopback
    port. That loopback holder is still not identified before the bearer is
    sent: recorded as accepted in the module doc (every MCP client sends the
    same bearer to the same port on every call).
(a) RECORDED, not fixed. A holder that keeps answering ``/health`` for the
    whole window while it is being ended reads LIVE. The test below pins that
    bound so a future fix flips it on purpose; the Reverses-if is in the
    module doc.

In process on ephemeral loopback ports, as ``tests/test_port_handoff_restart_race.py``.
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
from core.port_handoff import FREE, LIVE, await_port, health_answers

_ROOT = Path(__file__).resolve().parent.parent
# Over the old 2.0 s probe timeout, well under the new one.
_SLOW_S = 2.6


def _slow_handler(doc: dict, delay_s: float, *, status: int = 200):
    body = json.dumps(doc).encode()

    class _H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - stdlib name
            time.sleep(delay_s)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    return _H


@pytest.fixture()
def slow_holder():
    """Start a JSON server whose every GET answers after ``delay_s``; yield its port."""
    started = []

    def _start(doc: dict, delay_s: float = _SLOW_S) -> int:
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _slow_handler(doc, delay_s))
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        started.append((srv, t))
        return srv.server_address[1]

    yield _start
    for srv, t in started:
        srv.shutdown()
        srv.server_close()
        t.join(timeout=5)


def _load_launcher(rel: str):
    """Load a launcher in isolation; it chdirs to the repo root at import."""
    cwd = os.getcwd()
    try:
        spec = importlib.util.spec_from_file_location("_rm834_" + Path(rel).stem, _ROOT / rel)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        os.chdir(cwd)


class _Run:
    def __init__(self) -> None:
        self.served: list[tuple[str, int]] = []
        self.lines: list[str] = []

    def serve(self, host: str, port: int) -> int:
        self.served.append((host, port))
        return 7

    def log(self, msg: str) -> None:
        self.lines.append(msg)


# -- (b) a slow /health on a live server -------------------------------------------
def test_the_liveness_probe_outwaits_a_loaded_server():
    # The probe runs once, after a 30 s window: a few more seconds to tell a
    # slow live server from a mute holder is cheap; 2 s was not enough.
    assert port_handoff.HEALTH_TIMEOUT_S >= 10.0


def test_health_answers_reads_the_timeout_at_call_time(monkeypatch):
    seen = []

    class _Conn:
        def __init__(self, host, port, timeout=None):
            seen.append(timeout)

        def request(self, *a, **k):
            raise OSError("no server")

        def close(self):
            pass

    monkeypatch.setattr(port_handoff.http.client, "HTTPConnection", _Conn)
    monkeypatch.setattr(port_handoff, "HEALTH_TIMEOUT_S", 0.123)
    assert health_answers("127.0.0.1", 1) is False
    assert seen == [0.123]


def test_a_slow_live_holder_is_LIVE_not_STUCK(slow_holder):
    port = slow_holder({"alive": True})
    h = await_port("127.0.0.1", port, window_s=0.1, poll_s=0.05,
                   holder_live=lambda: health_answers("127.0.0.1", port))
    assert h.state == LIVE
    assert h.waited_s >= _SLOW_S


def test_ds_launcher_skips_with_0_beside_a_slow_live_engine(slow_holder):
    sds = _load_launcher("tools/start_daemon_slayer.py")
    port = slow_holder({"status": "ok", "engine_version": "x"})
    run = _Run()
    code = sds.main(host="127.0.0.1", port=port, serve=run.serve, log=run.log,
                    window_s=0.1, poll_s=0.05)
    assert code == 0, run.lines
    assert run.served == []
    assert not any("not started" in line for line in run.lines), run.lines


def test_matchdb_live_check_accepts_a_slow_real_shaped_server(slow_holder):
    from tools import ds_matchdb_mcp_server as mdb
    port = slow_holder({"alive": True, "uptime_s": 1, "tools": []})
    assert mdb.holder_is_matchdb("127.0.0.1", port) is True


# -- (c) the bearer never leaves loopback ------------------------------------------
@pytest.fixture()
def no_connection(monkeypatch):
    """Record every HTTPConnection the probe opens (none may open)."""
    opened = []

    class _Conn:
        def __init__(self, host, port, timeout=None):
            opened.append((host, port))

        def request(self, *a, **k):
            raise OSError("refused")

        def close(self):
            pass

    monkeypatch.setattr(port_handoff.http.client, "HTTPConnection", _Conn)
    return opened


@pytest.mark.parametrize("host", ["192.0.2.1", "0.0.0.0", "", "rc-host", "100.64.0.7"])
def test_health_answers_never_connects_off_loopback(no_connection, host):
    assert health_answers(host, 8861, headers={"Authorization": "Bearer t"}) is False
    assert no_connection == []


def test_matchdb_live_check_never_sends_the_bearer_off_loopback(no_connection):
    from tools import ds_matchdb_mcp_server as mdb
    assert mdb.holder_is_matchdb("192.0.2.1", 8861) is False
    assert no_connection == []


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
def test_health_answers_still_probes_loopback(no_connection, host):
    assert health_answers(host, 8861) is False
    assert no_connection == [(host, 8861)]


# -- (a) recorded: a holder answering for the whole window reads LIVE --------------
def test_a_holder_answering_through_the_whole_window_reads_LIVE_recorded_bound():
    # RECORDED, not fixed (RM-834 a): no outside probe can tell a holder that
    # answers /health while it is being ended from a live one. The bound is the
    # window: one probe, after it. Flip this test only with a holder that can
    # say it is stopping (see the module doc's Reverses-if).
    t = [0.0]
    asked = []
    h = await_port("127.0.0.1", 1, window_s=30.0, poll_s=1.0,
                   holder_live=lambda: asked.append(t[0]) or True,
                   bind_ok=lambda host, port: False,
                   clock=lambda: t[0],
                   sleep=lambda s: t.__setitem__(0, t[0] + s))
    assert h.state == LIVE
    assert asked == [30.0]


def test_a_free_port_still_skips_every_probe():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    h = await_port("127.0.0.1", port, holder_live=lambda: pytest.fail("asked"),
                   window_s=1.0, poll_s=0.05)
    assert h.state == FREE
