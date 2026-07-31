# arch: tests for the INTERRUPT actions on /api/loop-control (S9) | section=tests | frozen=no
"""S9 at the route seam - the two actions that expose the interrupt to the UI.

`interrupt_preview` names the victims. `interrupt` kills them, but only the
ones the preview named: it carries back the fingerprint the preview minted and
the module re-probes rather than trusting it. These tests pin the route half of
that contract, and one property the module cannot enforce on its own - that the
GUIDANCE action still refuses tier "interrupt" with a 400, so there is no path
through this route that turns the act into a note.

The interrupt module is stubbed wholesale. No test here may kill anything.
"""
from __future__ import annotations

import importlib
import json

import pytest

mod = importlib.import_module("dashboard.routes_loop_control")
idem = importlib.import_module("dashboard._idempotency")

KEY_A = "3f2a1b4c-5d6e-4f70-8192-a3b4c5d6e7f8"
KEY_B = "8c7b6a59-4d3e-4c2b-9a10-fedcba987654"


class FakeHandler:
    def __init__(self, path: str = "/api/loop-control") -> None:
        self.path = path
        self.sent: tuple | None = None

    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.sent = (status, body, ctype)


@pytest.fixture(autouse=True)
def clean_table():
    idem.clear()
    yield
    idem.clear()


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
    status, raw, _ = h.sent
    return status, json.loads(raw.decode("utf-8"))


VICTIM = {"pid": 4242, "name": "claude.exe", "kind": "lane", "lane": "ds",
          "run_id": "r1", "cmdline": "claude -p", "ppid": 100, "started": 1.0}


class FakeInterrupt:
    """Stand-in for ops.loop.interrupt - records, never kills."""

    TIER = "interrupt"
    EMPTY_FINGERPRINT = "0" * 16

    def __init__(self, result=None, victims=(VICTIM,), fp="abc123"):
        self.executed: list = []
        self.previews = 0
        self._result = result
        self._victims = list(victims)
        self._fp = fp

    def preview(self, root=None):
        self.previews += 1
        return {"ok": True, "victims": self._victims,
                "count": len(self._victims), "fingerprint": self._fp,
                "ts": 1.0}

    def execute(self, expected_fingerprint, *, key, root=None, killer=None):
        self.executed.append({"fp": expected_fingerprint, "key": key})
        if self._result is not None:
            return dict(self._result)
        return {"ok": True, "victims": self._victims,
                "count": len(self._victims), "fingerprint": self._fp,
                "killed": [v["pid"] for v in self._victims], "failed": []}


@pytest.fixture
def fake(monkeypatch):
    f = FakeInterrupt()
    monkeypatch.setattr(mod, "_interrupt", lambda: f)
    return f


# --------------------------------------------------------------------------- preview
def test_preview_names_the_victims_and_kills_nothing(ctldir, fake):
    status, out = _post({"action": "interrupt_preview"})

    assert status == 200
    assert out["ok"] is True
    assert out["victims"][0]["pid"] == 4242
    assert out["fingerprint"] == "abc123"
    assert fake.executed == [], "preview must never reach execute"


def test_preview_needs_no_idempotency_key(ctldir, fake):
    """Asking twice is the same world - a read has nothing to replay."""
    status, out = _post({"action": "interrupt_preview"})
    assert status == 200
    assert out["ok"] is True
    assert fake.previews == 1


def test_preview_is_not_remembered_by_the_replay_table(ctldir, fake):
    """A remembered preview would freeze a stale victim list into every arm."""
    _post({"action": "interrupt_preview"})
    _post({"action": "interrupt_preview"})
    assert fake.previews == 2


# --------------------------------------------------------------------------- execute
def test_interrupt_requires_an_idempotency_key(ctldir, fake):
    status, out = _post({"action": "interrupt", "fingerprint": "abc123"})

    assert status == 400
    assert out["ok"] is False
    assert fake.executed == []


def test_interrupt_requires_a_fingerprint(ctldir, fake):
    """No fingerprint means no preview was shown, so nothing was ever named."""
    status, out = _post({"action": "interrupt", "idempotency_key": KEY_A})

    assert status == 400
    assert "fingerprint" in out["error"]
    assert fake.executed == []


def test_interrupt_forwards_the_fingerprint_verbatim(ctldir, fake):
    status, out = _post({"action": "interrupt", "idempotency_key": KEY_A,
                         "fingerprint": "abc123"})

    assert status == 200
    assert out["ok"] is True
    assert fake.executed == [{"fp": "abc123", "key": KEY_A}]


def test_a_stale_fingerprint_refuses_with_200_not_an_error(ctldir, monkeypatch):
    """A refusal is a normal answer. 4xx would push the UI into an error path
    for what is simply "the machine moved since you looked"."""
    f = FakeInterrupt(result={
        "ok": False, "refused": "victims_changed", "victims": [VICTIM],
        "count": 1, "fingerprint": "fresh99", "killed": [], "failed": []})
    monkeypatch.setattr(mod, "_interrupt", lambda: f)

    status, out = _post({"action": "interrupt", "idempotency_key": KEY_A,
                         "fingerprint": "stale00"})

    assert status == 200
    assert out["ok"] is False
    assert out["refused"] == "victims_changed"
    assert out["fingerprint"] == "fresh99", "the UI needs the fresh list to re-arm"


def test_a_repeat_key_replays_and_does_not_kill_twice(ctldir, fake):
    """The layer that survives a phone retrying over Tailscale."""
    _post({"action": "interrupt", "idempotency_key": KEY_A,
           "fingerprint": "abc123"})
    status, out = _post({"action": "interrupt", "idempotency_key": KEY_A,
                         "fingerprint": "abc123"})

    assert status == 200
    assert out["replayed"] is True
    assert len(fake.executed) == 1, "a replay must not execute a second kill"


def test_a_fresh_key_executes_again(ctldir, fake):
    _post({"action": "interrupt", "idempotency_key": KEY_A,
           "fingerprint": "abc123"})
    _post({"action": "interrupt", "idempotency_key": KEY_B,
           "fingerprint": "abc123"})
    assert len(fake.executed) == 2


def test_a_missing_interrupt_module_is_503_not_a_crash(ctldir, monkeypatch):
    def boom():
        raise ModuleNotFoundError("no ops.loop.interrupt")

    monkeypatch.setattr(mod, "_interrupt", boom)
    status, out = _post({"action": "interrupt", "idempotency_key": KEY_A,
                         "fingerprint": "abc123"})

    assert status == 503
    assert out["ok"] is False


# --------------------------------------------------------------------------- no downgrade
def test_the_steer_action_still_refuses_the_interrupt_tier(ctldir):
    """There must be NO path through this route that demotes the act to a note.

    The guidance action validates against steer.TIERS, which excludes
    "interrupt" on purpose. If a later change ever folds the tier in for
    convenience, this fails.
    """
    status, out = _post({"action": "steer", "idempotency_key": KEY_A,
                         "tier": "interrupt", "text": "stop everything"})

    assert status == 400
    assert "interrupt" in out["error"]


def test_interrupt_is_a_distinct_action_from_steer():
    assert "interrupt" in mod._VALID_ACTIONS
    assert "interrupt_preview" in mod._VALID_ACTIONS
    assert "interrupt" in mod._IDEMPOTENT_ACTIONS
    assert "interrupt_preview" not in mod._IDEMPOTENT_ACTIONS
