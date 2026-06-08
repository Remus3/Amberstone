# arch: rc_facts port-probe retry regression | section=tests | frozen=no
"""Regression for rc_facts._port_listening false-alarming a busy-but-listening
port as down (2026-06-07: :8889 vision server LISTENING yet a 0.4s connect
intermittently timed out -> "vision server not listening" anomaly).

A connect timeout (accept loop briefly busy) must be retried; a refused
connection (truly down) must fail fast without retrying.
"""
from __future__ import annotations

import socket

import tools.rc_facts as rc_facts


class _FakeSock:
    """One connect attempt -> one outcome ('ok' | 'timeout' | 'refused')."""

    def __init__(self, result: str) -> None:
        self.result = result

    def settimeout(self, _t: float) -> None:
        pass

    def connect(self, _addr: tuple) -> None:
        if self.result == "timeout":
            raise socket.timeout("timed out")
        if self.result == "refused":
            raise ConnectionRefusedError("refused")
        # "ok": connection established

    def close(self) -> None:
        pass


def _factory(seq: list[str]):
    """Return a socket.socket() stand-in handing out one _FakeSock per call."""
    it = iter(seq)
    return lambda *_a, **_k: _FakeSock(next(it))


def test_listening_real_socket_true() -> None:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    try:
        assert rc_facts._port_listening(srv.getsockname()[1]) is True
    finally:
        srv.close()


def test_closed_port_false() -> None:
    # Bind+close to obtain a port number nothing is listening on. (On Windows a
    # closed loopback port may time out rather than refuse, so assert only the
    # result; the refused-fast-path is covered by test_refused_does_not_retry.)
    tmp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tmp.bind(("127.0.0.1", 0))
    port = tmp.getsockname()[1]
    tmp.close()
    assert rc_facts._port_listening(port) is False


def test_timeout_then_success_retries(monkeypatch) -> None:
    monkeypatch.setattr(rc_facts.socket, "socket", _factory(["timeout", "ok"]))
    assert rc_facts._port_listening(9999) is True


def test_all_timeouts_false(monkeypatch) -> None:
    monkeypatch.setattr(
        rc_facts.socket, "socket", _factory(["timeout", "timeout", "timeout"])
    )
    assert rc_facts._port_listening(9999, attempts=3) is False


def test_refused_does_not_retry(monkeypatch) -> None:
    # Only ONE _FakeSock provided; a retry would StopIteration -> proves no retry.
    monkeypatch.setattr(rc_facts.socket, "socket", _factory(["refused"]))
    assert rc_facts._port_listening(9999) is False
