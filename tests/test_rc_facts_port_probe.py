# arch: rc_facts port-probe retry regression | section=tests | frozen=no
"""Regression for rc_facts._port_listening false-alarming a busy-but-listening
port as down (2026-06-07: :8889 vision server LISTENING yet a 0.4s connect
intermittently timed out -> "vision server not listening" anomaly).

A connect timeout (accept loop briefly busy) must be retried; a refused
connection (truly down) must fail fast without retrying.
"""
from __future__ import annotations

import socket
import threading

import tools.rc_facts as rc_facts
from tests._module_view import bind_socket_class

_REAL_SOCKET = socket.socket


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


# Every fake below is bound to rc_facts' own `socket` name, never to the
# process-wide socket module (tests/_module_view.py).

def test_timeout_then_success_retries(monkeypatch) -> None:
    bind_socket_class(monkeypatch, rc_facts, _factory(["timeout", "ok"]))
    assert rc_facts._port_listening(9999) is True


def test_all_timeouts_false(monkeypatch) -> None:
    bind_socket_class(monkeypatch, rc_facts, _factory(["timeout", "timeout", "timeout"]))
    assert rc_facts._port_listening(9999, attempts=3) is False


def test_refused_does_not_retry(monkeypatch) -> None:
    # Only ONE _FakeSock provided; a retry would StopIteration -> proves no retry.
    bind_socket_class(monkeypatch, rc_facts, _factory(["refused"]))
    assert rc_facts._port_listening(9999) is False


def test_another_threads_socket_does_not_consume_the_fake_sequence(monkeypatch) -> None:
    # The fake must reach rc_facts' probe only. Bound on the process-wide
    # socket module it handed a sequence item to ANY thread's socket.socket()
    # (an xdist worker runs leftover servers and pollers), so the probe then
    # got the wrong outcome or StopIteration (CI run 39877078008 shape).
    go, done, seen = threading.Event(), threading.Event(), []

    def foreign() -> None:
        go.wait(5)
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            seen.append(type(s))
            s.close()
        except Exception as exc:  # noqa: BLE001 - a broken foreign socket is the finding
            seen.append(exc)
        done.set()

    worker = threading.Thread(target=foreign, daemon=True)
    worker.start()
    bind_socket_class(monkeypatch, rc_facts, _factory(["refused"]))
    go.set()
    assert done.wait(5)
    worker.join(5)
    assert seen == [_REAL_SOCKET], seen
    assert rc_facts._port_listening(9999) is False
