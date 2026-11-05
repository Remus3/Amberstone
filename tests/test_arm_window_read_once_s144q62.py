# arch: the arm reply advertises the window the arm record used | section=tests | frozen=no
"""RM-1373: `_handle_arm` read the arm window twice.

`armgate.arm(target_action, target)` read `window_s()` itself to compute the
record's `expires_at`, and `_handle_arm` then called `armgate.window_s()` AGAIN
for the reply's `window_s` and `detail`. `window_s()` is read at call time
(HOLE 5 in tests/test_arm_confirm_server_gate.py), so an `RC_MC_ARM_WINDOW_S`
change between the two reads made the reply advertise a window the record did
not use. The fix reads the window once and passes it to `arm(..., window)`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dashboard import _arm_confirm as armgate  # noqa: E402
from dashboard import _idempotency as idem  # noqa: E402
from dashboard import routes_loop_control as mod  # noqa: E402

FIXED_NOW = 1_000_000.0


class FakeHandler:
    def __init__(self, path: str = "/api/loop-control"):
        self.path = path
        self.sent: tuple | None = None

    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.sent = (status, body, ctype)


@pytest.fixture(autouse=True)
def clean_tables(tmp_path, monkeypatch):
    idem.clear()
    armgate.clear()
    ctl = tmp_path / "control"
    ctl.mkdir()
    monkeypatch.setattr(mod, "CONTROL_DIR", ctl)
    monkeypatch.setattr(armgate, "_now", lambda: FIXED_NOW)
    yield
    idem.clear()
    armgate.clear()


class ShiftingWindow:
    """window_s() stand-in whose value changes on every read."""

    def __init__(self, values):
        self.values = list(values)
        self.calls = 0

    def __call__(self) -> float:
        value = self.values[min(self.calls, len(self.values) - 1)]
        self.calls += 1
        return value


def _arm_interrupt():
    h = FakeHandler()
    mod._serve_loop_control(h, {"action": "arm", "target_action": "interrupt"})
    assert h.sent is not None
    status, raw, _ctype = h.sent
    return status, json.loads(raw.decode("utf-8"))


@pytest.mark.parametrize("values", [(5.0, 600.0), (600.0, 5.0)])
def test_the_reply_window_equals_the_record_window(monkeypatch, values):
    shifting = ShiftingWindow(values)
    monkeypatch.setattr(armgate, "window_s", shifting)
    status, payload = _arm_interrupt()
    assert status == 200
    assert payload["expires_at"] - FIXED_NOW == pytest.approx(payload["window_s"])


def test_the_window_is_read_exactly_once_per_arm(monkeypatch):
    shifting = ShiftingWindow((5.0, 600.0))
    monkeypatch.setattr(armgate, "window_s", shifting)
    status, payload = _arm_interrupt()
    assert status == 200
    assert shifting.calls == 1
    assert payload["window_s"] == 5.0
    assert payload["expires_at"] == FIXED_NOW + 5.0


def test_the_detail_names_the_window_the_record_used(monkeypatch):
    monkeypatch.setattr(armgate, "window_s", ShiftingWindow((5.0, 600.0)))
    _status, payload = _arm_interrupt()
    assert "armed for 5s" in payload["detail"]


def test_the_stored_record_expires_at_the_advertised_window(monkeypatch):
    monkeypatch.setattr(armgate, "window_s", ShiftingWindow((5.0, 600.0)))
    _status, payload = _arm_interrupt()
    rec = armgate._ARMED[payload["arm_token"]]
    assert rec["expires_at"] == FIXED_NOW + payload["window_s"]
