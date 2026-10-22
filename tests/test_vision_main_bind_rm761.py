"""RM-761b: vision_server.main() must fail CLEAN when the :8889 bind fails.

make_server raised the bind OSError straight out of main(). Under pythonw the
traceback goes nowhere, so the dashboard's vision watchdog saw only a dead
child. main() now logs the failure and returns exit code 1, the same shape as
tools/ds_matchdb_mcp_server.py.

Every side-effecting step before the bind is stubbed: the API-key check, the
"already running" connect probe (pointed at a free port), the stale-instance
reap (it kills other vision-server processes - it must never run from a test)
and the Anthropic client.
"""
from __future__ import annotations

import logging
import socket

import pytest

import vision_server
from vision_server import _reap


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture()
def stubbed_main(monkeypatch):
    monkeypatch.setattr(vision_server, "api_key_present", lambda: True)
    monkeypatch.setattr(vision_server, "PORT", _free_port())
    monkeypatch.setattr(_reap, "reap_stale_vision_instances", lambda: [])
    monkeypatch.setattr(vision_server, "_get_client", lambda: None)
    return monkeypatch


def test_bind_oserror_returns_1_and_logs(stubbed_main, caplog):
    def _boom(host, port, handler=None):
        raise OSError(10048, "Only one usage of each socket address")

    stubbed_main.setattr(vision_server, "make_server", _boom)
    with caplog.at_level(logging.ERROR, logger=vision_server.log.name):
        rc = vision_server.main()
    assert rc == 1
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(errors) == 1
    msg = errors[0].getMessage()
    assert "bind" in msg and "failed" in msg
    assert str(vision_server.PORT) in msg


def test_non_oserror_from_make_server_still_raises(stubbed_main):
    # Only the bind failure class is converted; a programming error surfaces.
    def _bug(host, port, handler=None):
        raise TypeError("not a bind failure")

    stubbed_main.setattr(vision_server, "make_server", _bug)
    with pytest.raises(TypeError):
        vision_server.main()
