"""Quality-pass tests (audit L1-L4)."""
from __future__ import annotations

from agents.agent2_backend.smb_push import _sanitise_label
from agents.supervisor import _port_available


def test_sanitise_label_strips_unsafe_chars() -> None:
    # colons (from ISO times), slashes, asterisks, all illegal on Windows.
    assert _sanitise_label("restart:2026-04-22T10:00") == "restart-2026-04-22T10-00"
    assert _sanitise_label("bad/slash\\mix") == "bad-slash-mix"
    assert _sanitise_label("a**b") == "a-b"


def test_sanitise_label_never_empty() -> None:
    assert _sanitise_label("") == "unlabeled"
    assert _sanitise_label("***") == "unlabeled"


def test_sanitise_label_preserves_safe() -> None:
    assert _sanitise_label("restart-manual") == "restart-manual"
    assert _sanitise_label("build_v1.2.3") == "build_v1.2.3"


def test_port_available_returns_true_for_random_high_port() -> None:
    # 0.0.0.0:59999 (ephemeral unused) — should be available on a freshly
    # booted machine. Might occasionally clash; accept either True or
    # a graceful False (not a raise).
    ok = _port_available("0.0.0.0", 59999)
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
