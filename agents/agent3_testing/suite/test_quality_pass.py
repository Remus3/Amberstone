"""Quality-pass tests (audit L1-L4).

The three backup-label helper tests left with the retired Game-PC SMB push
module (deleted 2026-10-22, C6 F4, phase3-d026); the port-preflight tests stay.
"""
from __future__ import annotations

from agents.supervisor import _port_available


def test_port_available_returns_true_for_random_high_port() -> None:
    # 127.0.0.1:59999 (ephemeral unused) - should be available on a freshly
    # booted machine. Might occasionally clash; accept either True or
    # a graceful False (not a raise). Loopback, the supervisor's own default
    # (RM-231 BIND_HOST): a test has no reason to bind every interface
    # (CodeQL py/bind-socket-all-network-interfaces, alert 48).
    ok = _port_available("127.0.0.1", 59999)
    assert isinstance(ok, bool)


def test_port_available_detects_taken_port() -> None:
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    _, port = s.getsockname()
    try:
        # Bound on loopback so 0.0.0.0 probe sees the conflict.
        assert _port_available("127.0.0.1", port) is False
    finally:
        s.close()
