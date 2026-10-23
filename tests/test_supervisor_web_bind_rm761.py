"""RM-761a: the Phase 3 supervisor's web server fails loud on a held port.

``start_web_server`` constructed ``_WebServer((BIND_HOST, port), ...)`` bare,
so a held :8890 surfaced as the raw ``OSError`` (WinError 10048) from
socketserver, and ``_run`` let it escape ``asyncio.run`` - under pythonw.exe
that traceback goes nowhere. The ``_port_available`` preflight did not close
this: on Windows it reported a port as free when the holder set SO_REUSEADDR
(measured for RM-756). RM-777 since drops SO_REUSEADDR from the Windows probe
(a plain bind, NOT an exclusive one, which this row ruled out as a TIME_WAIT
restart-loop risk), but a holder can still appear between the preflight and
the real bind, so this fail-loud path stays. Now, in the
RM-756 (ws_server) shape:

  - ``start_web_server`` turns the bind ``OSError`` into a ``RuntimeError``
    naming host:port with the preflight's ``netstat -ano | findstr :<port>``
    hint, chained to the ``OSError``; no "web-http" thread is started;
  - ``_run`` catches that ``RuntimeError`` from ``Supervisor.start()``, logs
    it as one ERROR line, still runs ``stop()``, and returns 1.

The ``_run`` test swaps in a fake Supervisor and an unregistered in-memory
logger, so it writes no logs/supervisor.log line and takes no real lock.
"""
from __future__ import annotations

import logging
import socket
import threading

import pytest

from agents import _supervisor_http, supervisor
from agents._supervisor_common import BIND_HOST
from tests._asyncio_isolation import run_coro


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def held_port():
    """A port on the supervisor's bind host, held by a plain listener."""
    family = socket.AF_INET6 if ":" in BIND_HOST else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    try:
        sock.bind((BIND_HOST, 0))
        sock.listen()
        yield sock.getsockname()[1]
    finally:
        sock.close()


@pytest.fixture
def mem_log(monkeypatch):
    # An UNREGISTERED Logger (not via getLogger), so no global logging state
    # changes and the real supervisor.log file handler never sees a record.
    handler = _ListHandler()
    lg = logging.Logger("test_supervisor_web_bind_rm761", logging.DEBUG)
    lg.addHandler(handler)
    lg.propagate = False
    monkeypatch.setattr(supervisor, "log", lg)
    return handler


def _web_threads() -> list[threading.Thread]:
    return [t for t in threading.enumerate() if t.name == "web-http" and t.is_alive()]


def test_start_web_server_raises_runtimeerror_with_netstat_hint(held_port):
    before = set(_web_threads())
    with pytest.raises(RuntimeError) as exc:
        _supervisor_http.start_web_server(held_port, supervisor=None)
    msg = str(exc.value)
    assert f"{BIND_HOST}:{held_port}" in msg
    assert f"netstat -ano | findstr :{held_port}" in msg
    assert isinstance(exc.value.__cause__, OSError)
    assert set(_web_threads()) - before == set()


class _FailingSupervisor:
    stopped = 0

    async def start(self) -> None:
        raise RuntimeError(
            "web server cannot bind 127.0.0.1:65000 - port already in use? "
            "run: `netstat -ano | findstr :65000` to identify the holder"
        )

    async def stop(self) -> None:
        type(self).stopped += 1


def test_run_logs_one_error_stops_and_returns_1(monkeypatch, mem_log):
    _FailingSupervisor.stopped = 0
    monkeypatch.setattr(supervisor, "acquire_lock", lambda: True)
    monkeypatch.setattr(supervisor, "Supervisor", _FailingSupervisor)
    rc = run_coro(supervisor._run(), timeout=30.0)
    assert rc == 1
    errors = [r for r in mem_log.records if r.levelno >= logging.ERROR]
    assert len(errors) == 1, [r.getMessage() for r in errors]
    assert "netstat -ano | findstr :65000" in errors[0].getMessage()
    assert _FailingSupervisor.stopped == 1


def test_run_keeps_the_traceback_for_a_non_bind_runtimeerror(monkeypatch, mem_log):
    # The real Supervisor.start(), failing at its FIRST step (a fail-closed
    # verifier, not a bind): _run still returns 1, but the ERROR record must
    # carry the stack. stop() is replaced so the real lock files of a live
    # supervisor are never released by the test.
    def _drift() -> None:
        raise RuntimeError("decisions-file version drift")

    stops: list[int] = []

    async def _no_stop(self) -> None:
        stops.append(1)

    monkeypatch.setattr(supervisor, "acquire_lock", lambda: True)
    monkeypatch.setattr(supervisor, "_verify_decisions_version", _drift)
    monkeypatch.setattr(supervisor.Supervisor, "stop", _no_stop)
    rc = run_coro(supervisor._run(), timeout=30.0)
    assert rc == 1
    assert stops == [1]
    errors = [r for r in mem_log.records if r.levelno >= logging.ERROR]
    assert len(errors) == 1, [r.getMessage() for r in errors]
    assert "decisions-file version drift" in errors[0].getMessage()
    assert errors[0].exc_info is not None
    assert isinstance(errors[0].exc_info[1], RuntimeError)
    assert errors[0].exc_info[2] is not None


def test_run_does_not_swallow_non_runtime_errors(monkeypatch, mem_log):
    class _Boom(_FailingSupervisor):
        async def start(self) -> None:
            raise ValueError("not a bind failure")

    monkeypatch.setattr(supervisor, "acquire_lock", lambda: True)
    monkeypatch.setattr(supervisor, "Supervisor", _Boom)
    with pytest.raises(ValueError):
        run_coro(supervisor._run(), timeout=30.0)
