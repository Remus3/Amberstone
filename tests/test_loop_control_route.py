# arch: tests for POST /api/loop-control (headless-loop remote control) | section=tests | frozen=no
"""Behavior tests for dashboard.routes_loop_control.

The route is the WRITE complement to GET /api/loop-status: it writes the
headless-loop control files (ops/loop/control/{STOP,directive_override.md}) so
the operator can halt / resume / queue a directive override from the phone over
Tailscale. It must be fail-soft, atomic (tmp + os.replace, no stray .tmp), cap
input sizes, reject unknown / empty actions with 400, and never execute anything
itself. All file IO is redirected at the module-level CONTROL_DIR constant so
these tests touch only a tmp dir.
"""
from __future__ import annotations

import json

import pytest

from dashboard import routes_loop_control as mod


class FakeHandler:
    """Minimal handler stand-in capturing _send(status, body, ctype)."""

    def __init__(self, path: str = "/api/loop-control") -> None:
        self.path = path
        self.sent: tuple | None = None

    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.sent = (status, body, ctype)


@pytest.fixture
def ctldir(tmp_path, monkeypatch):
    ctl = tmp_path / "control"
    ctl.mkdir()
    monkeypatch.setattr(mod, "CONTROL_DIR", ctl)
    return ctl


def _post(body):
    h = FakeHandler()
    mod._serve_loop_control(h, body)
    assert h.sent is not None
    status, raw, ctype = h.sent
    return status, json.loads(raw.decode("utf-8")), ctype


# --------------------------------------------------------------------------- stop
def test_stop_writes_STOP_with_reason(ctldir):
    status, payload, ctype = _post({"action": "stop", "reason": "operator halt"})
    assert status == 200 and payload["ok"] is True
    assert payload["action"] == "stop" and payload["state"] == "stopped"
    assert (ctldir / "STOP").read_text(encoding="utf-8") == "operator halt"
    assert ctype == "application/json"


def test_stop_default_reason(ctldir):
    status, payload, _ = _post({"action": "stop"})
    assert status == 200
    assert (ctldir / "STOP").read_text(encoding="utf-8") == "stopped from dashboard"


def test_stop_reason_capped(ctldir):
    status, _payload, _ = _post({"action": "stop", "reason": "x" * 999})
    assert status == 200
    assert len((ctldir / "STOP").read_text(encoding="utf-8")) == mod.MAX_REASON


# --------------------------------------------------------------------------- resume
def test_resume_unlinks_STOP(ctldir):
    (ctldir / "STOP").write_text("halted", encoding="utf-8")
    status, payload, _ = _post({"action": "resume"})
    assert status == 200 and payload["ok"] is True
    assert not (ctldir / "STOP").exists()
    assert payload["state"] == "idle"


def test_resume_when_no_stop_is_idempotent(ctldir):
    status, _payload, _ = _post({"action": "resume"})
    assert status == 200 and not (ctldir / "STOP").exists()


def test_resume_running_when_cycle_present(ctldir):
    (ctldir / "STOP").write_text("halted", encoding="utf-8")
    (ctldir / "cycle.txt").write_text("7", encoding="utf-8")
    _status, payload, _ = _post({"action": "resume"})
    assert payload["state"] == "running"


# --------------------------------------------------------------------------- set_directive
def test_set_directive_writes_override(ctldir):
    status, payload, _ = _post({"action": "set_directive", "text": "Do the thing."})
    assert status == 200 and payload["ok"] is True
    assert (ctldir / "directive_override.md").read_text(encoding="utf-8") == "Do the thing."


def test_set_directive_empty_text_400(ctldir):
    status, payload, _ = _post({"action": "set_directive", "text": "   "})
    assert status == 400 and payload["ok"] is False
    assert not (ctldir / "directive_override.md").exists()


def test_set_directive_capped(ctldir):
    status, _payload, _ = _post({"action": "set_directive", "text": "y" * 99999})
    assert status == 200
    assert len((ctldir / "directive_override.md").read_text(encoding="utf-8")) == mod.MAX_DIRECTIVE


# --------------------------------------------------------------------------- clear_directive
def test_clear_directive_unlinks(ctldir):
    (ctldir / "directive_override.md").write_text("queued", encoding="utf-8")
    status, _payload, _ = _post({"action": "clear_directive"})
    assert status == 200 and not (ctldir / "directive_override.md").exists()


# --------------------------------------------------------------------------- bad input
def test_unknown_action_400(ctldir):
    status, payload, _ = _post({"action": "nuke"})
    assert status == 400 and payload["ok"] is False
    assert "valid" in payload


def test_missing_action_400(ctldir):
    status, _payload, _ = _post({})
    assert status == 400


def test_non_dict_body_400(ctldir):
    status, _payload, _ = _post(["not", "a", "dict"])
    assert status == 400


# --------------------------------------------------------------------------- atomic + registration
def test_atomic_no_tmp_left(ctldir):
    _post({"action": "stop", "reason": "x"})
    _post({"action": "set_directive", "text": "z"})
    assert not list(ctldir.glob("*.tmp"))


def test_route_is_post_only():
    assert mod.GET_ROUTES == []
    assert len(mod.POST_ROUTES) == 1
    matcher, _fn = mod.POST_ROUTES[0]
    assert matcher("/api/loop-control") is True
    assert matcher("/api/loop-status") is False
