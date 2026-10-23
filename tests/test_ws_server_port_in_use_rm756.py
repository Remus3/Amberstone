"""RM-756: the Phase 3 ws_server fails loud when its port is already held.

``WSServer.start()`` awaited websockets' ``serve()`` bare, so a held port
surfaced as asyncio's raw ``OSError`` (WinError 10048) from deep inside the
event loop, and the standalone entry point threw ``_main``'s return value
away (``asyncio.run(...)`` with no ``sys.exit``). The supervisor's own
preflight (``agents/supervisor.py`` "port ... is already in use") only covers
the supervisor path. Now:

  - ``start()`` turns the bind ``OSError`` into a ``RuntimeError`` naming
    host:port with the same ``netstat -ano | findstr :<port>`` hint as the
    supervisor preflight, chained to the ``OSError``; no heartbeat task is
    started and nothing claims the server started;
  - ``_main`` logs that one line at ERROR and returns 1;
  - ``python -m agents.agent2_backend.ws_server`` exits with that status and
    prints no traceback.

Every coroutine runs through tests._asyncio_isolation.run_coro, and the
module's file loggers are replaced by an in-memory handler (same fixture as
tests/test_ws_server_true_audit.py), so the in-process tests write no
logs/ws/ lines.

RM-776: the entry-point test runs a CHILD process, which builds the real
RotatingFileHandler loggers and cannot take the in-memory swap, so it used to
append-open (and could rotate) the live logs/ws/*.log. ``WSServer`` now reads
its log root from ``RC_WS_LOG_DIR`` at construction time, and
tests/_fleet_guard_config.ENV_ROOTS points that at tmp_path for every test,
so the child inherits a tmp log root and logs/ws/ is left alone.
"""
from __future__ import annotations

import logging
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from agents.agent2_backend import ws_server
from tests import _fleet_guard_config
from tests._asyncio_isolation import run_coro

ROOT = Path(__file__).resolve().parent.parent


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
        lg = logging.Logger(f"test_ws_server_port_in_use_rm756.{name}", logging.DEBUG)
        lg.addHandler(handler)
        lg.propagate = False
        return lg

    monkeypatch.setattr(ws_server, "_build_logger", _fake_build)
    return handler


@pytest.fixture
def held_port():
    """A loopback port held by a plain listening socket for the whole test."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        yield sock.getsockname()[1]
    finally:
        sock.close()


def test_start_raises_runtimeerror_naming_host_and_port(logs, held_port):
    srv = ws_server.WSServer(host="127.0.0.1", port=held_port, origin_hosts=())
    with pytest.raises(RuntimeError) as exc:
        run_coro(srv.start(), timeout=30.0)
    msg = str(exc.value)
    assert f"127.0.0.1:{held_port}" in msg
    assert f"netstat -ano | findstr :{held_port}" in msg
    assert isinstance(exc.value.__cause__, OSError)
    assert srv._hb_task is None
    assert srv._server is None
    assert not any("ws-start" in m for m in logs.messages())


def test_main_logs_one_error_and_returns_1(logs, held_port, monkeypatch, caplog):
    # _main's basicConfig must not touch the root logger inside the test run.
    monkeypatch.setattr(logging, "basicConfig", lambda **_kw: None)
    with caplog.at_level(logging.ERROR, logger=ws_server.__name__):
        rc = run_coro(ws_server._main("127.0.0.1", held_port), timeout=30.0)
    assert rc == 1
    errors = [
        r for r in caplog.records
        if r.name == ws_server.__name__ and r.levelno >= logging.ERROR
    ]
    assert len(errors) == 1, [r.getMessage() for r in errors]
    assert f"127.0.0.1:{held_port}" in errors[0].getMessage()


_LOG_DIR_ENV = ws_server.LOG_DIR_ENV


def test_the_suite_redirects_the_ws_log_root():
    assert _LOG_DIR_ENV == "RC_WS_LOG_DIR"
    assert _LOG_DIR_ENV in _fleet_guard_config.ENV_ROOTS


def _redirected_log_root(tmp_path: Path) -> Path:
    """The ws log root the suite hands every test (and every child it starts)."""
    value = (os.environ.get(_LOG_DIR_ENV) or "").strip()
    assert value, f"{_LOG_DIR_ENV} is not redirected for this test (RM-776)"
    root = Path(value)
    assert root.is_relative_to(tmp_path), (root, tmp_path)
    return root


def test_module_entry_point_exits_nonzero_without_traceback(held_port, tmp_path):
    log_root = _redirected_log_root(tmp_path)
    out = subprocess.run(
        [sys.executable, "-m", "agents.agent2_backend.ws_server",
         "--host", "127.0.0.1", "--port", str(held_port)],
        cwd=ROOT, capture_output=True, text=True, timeout=60,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert out.returncode == 1, (out.returncode, out.stderr[-800:])
    assert f"127.0.0.1:{held_port}" in out.stderr, out.stderr[-800:]
    assert "Traceback" not in out.stderr, out.stderr[-800:]
    # RM-776: the child's RotatingFileHandlers opened their files under the
    # tmp root it inherited, not under the checkout's logs/ws/.
    assert sorted(p.name for p in log_root.iterdir()) == ["ingest.log", "push.log"]


def test_log_root_follows_the_env_at_construction(monkeypatch, tmp_path):
    seen: list[tuple[str, Path]] = []

    def _record(name, path):
        seen.append((name, path))
        return logging.Logger(f"test_ws_server_port_in_use_rm756.rec.{name}")

    monkeypatch.setattr(ws_server, "_build_logger", _record)
    monkeypatch.setenv(_LOG_DIR_ENV, str(tmp_path / "elsewhere"))
    ws_server.WSServer(host="127.0.0.1", port=0, origin_hosts=())
    assert seen == [
        ("ws.ingest", tmp_path / "elsewhere" / "ingest.log"),
        ("ws.push", tmp_path / "elsewhere" / "push.log"),
    ]


@pytest.mark.parametrize("value", [None, "", "   "])
def test_log_root_defaults_to_the_checkout_logs_ws(monkeypatch, value):
    seen: list[Path] = []

    def _record(name, path):
        seen.append(path)
        return logging.Logger(f"test_ws_server_port_in_use_rm756.def.{name}")

    monkeypatch.setattr(ws_server, "_build_logger", _record)
    if value is None:
        monkeypatch.delenv(_LOG_DIR_ENV, raising=False)
    else:
        monkeypatch.setenv(_LOG_DIR_ENV, value)
    ws_server.WSServer(host="127.0.0.1", port=0, origin_hosts=())
    assert seen == [ROOT / "logs" / "ws" / "ingest.log", ROOT / "logs" / "ws" / "push.log"]
