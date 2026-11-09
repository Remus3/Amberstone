"""s144 true-audit cycle 260 (S144-T-691): vision_server.main() fails clean.

``vision_server/__init__.py`` ``main`` is the :8889 entrypoint the RC vision
watchdog spawns under pythonw, where an uncaught traceback goes nowhere and
the watchdog sees only a dead child. Three paths escaped it:

* F1 - ``RC_VISION_BIND`` is a documented override that may name a
  non-loopback host (``0.0.0.0`` is pinned as accepted by
  ``tests/test_vision_server_bind_rm150.py``). When :8889 was already held,
  main handed that host to ``core.port_handoff.await_port``, whose
  ``require_loopback`` raised ValueError straight out of main.
* F2 - a failure inside ``serve_forever`` other than KeyboardInterrupt
  escaped unlogged, and no exit path ever called ``server_close``: the
  listening socket and the 16 pool workers were never released (the
  KeyboardInterrupt branch called ``shutdown()``, a no-op once
  ``serve_forever`` has already returned).
* F3 - the Anthropic client warm-up ran before the bind and its failure (an
  ImportError, a constructor error) killed main, so the LCU / Live Client
  relays - which need no client - never came up. Inference already builds
  the client lazily inside its own try per call.

Every side-effecting step is stubbed: the API-key check, the reap (it kills
processes), the client and the server itself.
"""
from __future__ import annotations

import logging
import socket

import pytest

import vision_server
from vision_server import _reap

_SECRET = "sk-ant-api03-SYNTHETIC-NOT-A-KEY"  # rc-credential-scan: allow-fixture


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _Srv:
    def __init__(self, exc: BaseException | None = None) -> None:
        self.exc = exc
        self.closed = 0
        self.served = 0

    def serve_forever(self) -> None:
        self.served += 1
        if self.exc is not None:
            raise self.exc

    def shutdown(self) -> None:
        return None

    def server_close(self) -> None:
        self.closed += 1


@pytest.fixture
def stubbed(monkeypatch):
    made: list[tuple[str, int]] = []
    srv = _Srv()

    def _make(host, port, handler=None):
        made.append((host, port))
        return srv

    monkeypatch.setattr(vision_server, "api_key_present", lambda: True)
    monkeypatch.setattr(vision_server, "PORT", _free_port())
    monkeypatch.setattr(_reap, "reap_stale_vision_instances", list)
    monkeypatch.setattr(vision_server, "_get_client", lambda: None)
    monkeypatch.setattr(vision_server, "make_server", _make)
    monkeypatch.delenv("RC_VISION_BIND", raising=False)
    return made, srv, monkeypatch


@pytest.fixture
def held_port():
    """A real loopback listener, so main's 'already running' probe connects."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    s.listen(8)
    try:
        yield s.getsockname()[1]
    finally:
        s.close()


# -- F1: a non-loopback override with :8889 held ---------------------------

@pytest.mark.parametrize("bind", ["0.0.0.0", "192.0.2.10", "rc-host"])
def test_non_loopback_override_with_port_held_exits_clean(stubbed, held_port,
                                                          caplog, bind):
    made, _srv, mp = stubbed
    mp.setattr(vision_server, "PORT", held_port)
    mp.setenv("RC_VISION_BIND", bind)
    mp.setattr(vision_server, "_HANDOFF_WINDOW_S", 0.1, raising=False)
    mp.setattr(vision_server, "_HANDOFF_POLL_S", 0.05, raising=False)
    with caplog.at_level(logging.WARNING, logger=vision_server.log.name):
        rc = vision_server.main()
    assert rc == 0
    assert made == []
    msgs = [r.getMessage() for r in caplog.records
            if r.levelno >= logging.WARNING]
    assert any(str(held_port) in m and bind in m for m in msgs), msgs


def test_loopback_override_with_port_held_still_waits(stubbed, held_port):
    # The loopback path keeps the session-129 handoff (a live holder that
    # never frees the port is still left alone, exit 0, no bind).
    made, _srv, mp = stubbed
    mp.setattr(vision_server, "PORT", held_port)
    mp.setenv("RC_VISION_BIND", "127.0.0.1")
    mp.setattr(vision_server, "_HANDOFF_WINDOW_S", 0.1, raising=False)
    mp.setattr(vision_server, "_HANDOFF_POLL_S", 0.05, raising=False)
    assert vision_server.main() == 0
    assert made == []


def test_non_loopback_override_with_port_free_still_binds_it(stubbed):
    # The override itself is unchanged (RM-150 pins 0.0.0.0 as accepted).
    made, srv, mp = stubbed
    mp.setenv("RC_VISION_BIND", "0.0.0.0")
    assert vision_server.main() == 0
    assert made == [("0.0.0.0", vision_server.PORT)]
    assert srv.closed == 1


# -- F2: the serve loop's exit paths ----------------------------------------

def test_clean_return_closes_the_server(stubbed):
    made, srv, _mp = stubbed
    assert vision_server.main() == 0
    assert made == [("127.0.0.1", vision_server.PORT)]
    assert srv.served == 1
    assert srv.closed == 1


def test_keyboard_interrupt_closes_the_server(stubbed):
    _made, srv, _mp = stubbed
    srv.exc = KeyboardInterrupt()
    assert vision_server.main() == 0
    assert srv.closed == 1


def test_serve_failure_is_logged_closed_and_exit_1(stubbed, caplog):
    _made, srv, _mp = stubbed
    srv.exc = OSError(10038, "not a socket")
    with caplog.at_level(logging.ERROR, logger=vision_server.log.name):
        rc = vision_server.main()
    assert rc == 1
    assert srv.closed == 1
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(errors) == 1
    assert errors[0].exc_info is not None
    assert str(vision_server.PORT) in errors[0].getMessage()


def test_system_exit_from_serve_still_closes(stubbed):
    # A BaseException that is not an Exception is not swallowed, but the
    # socket and the pool are still released on the way out.
    _made, srv, _mp = stubbed
    srv.exc = SystemExit(3)
    with pytest.raises(SystemExit):
        vision_server.main()
    assert srv.closed == 1


# -- F3: a failed client warm-up does not take the relays down ---------------

@pytest.mark.parametrize("exc", [ImportError("No module named 'anthropic'"),
                                 RuntimeError(_SECRET),
                                 ValueError(_SECRET)])
def test_client_warmup_failure_still_serves(stubbed, caplog, exc):
    made, srv, mp = stubbed

    def _boom():
        raise exc

    mp.setattr(vision_server, "_get_client", _boom)
    with caplog.at_level(logging.DEBUG, logger=vision_server.log.name):
        rc = vision_server.main()
    assert rc == 0
    assert made == [("127.0.0.1", vision_server.PORT)]
    assert srv.served == 1
    warns = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any(type(exc).__name__ in r.getMessage() for r in warns), warns
    # The exception text never reaches a log record (it could carry a key).
    for r in caplog.records:
        assert _SECRET not in r.getMessage()
        assert r.exc_info is None


def test_main_docstring_names_no_module_entrypoint():
    # The package has no __main__.py (vision_server/_reap.py says so), so
    # ``python -m vision_server`` cannot start a server; main() must not
    # claim it as an entry point.
    import importlib.util

    assert importlib.util.find_spec("vision_server.__main__") is None
    doc = " ".join((vision_server.main.__doc__ or "").split())
    assert "-m vision_server" not in doc
