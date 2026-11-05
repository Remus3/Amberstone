"""RM-1371: the loop-control 400s answer with fixed text, never the caller's value.

dashboard/routes_loop_control.py validated six caller-supplied names - the
fire_lane `lane`, the queue_intent `intent`, the steer `tier`, the
apply_action and route_action `action`, and the arm `target_action` - and
each refusal put the raw value back into the reply as an unclipped repr
(`f"unknown lane: {lane!r}"` and siblings). A 4000-char or markup-laden value
came straight back.

Each reply now carries a fixed `error` line and keeps its `valid` / `gated`
list, so a client still learns what WOULD have been accepted. No in-tree
client reads the text (the web/mc panel was retired; mc/handler.py forwards
the JSON untouched), so the change is reply-shape only.
"""
from __future__ import annotations

import json
import sys
import types

import pytest

from dashboard import _arm_confirm as armgate
from dashboard import _idempotency as idem
from dashboard import routes_loop_control as mod

PROBE = "<b>S144Q57-PROBE</b>\x07" + "z" * 4000


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    idem.clear()
    ctl = tmp_path / "control"
    ctl.mkdir()
    monkeypatch.setattr(mod, "CONTROL_DIR", ctl)
    yield ctl
    idem.clear()


def _no_echo(payload: dict) -> None:
    text = json.dumps(payload)
    assert "S144Q57-PROBE" not in text, payload
    assert "zzzzzzzz" not in text, payload
    assert len(text) < 1000, len(text)


class _Lanes:
    LANES = ("repo", "queue")

    def __init__(self):
        self.calls = []

    def try_acquire_lane(self, lane, *, run_id, worktree, root=None):
        self.calls.append(lane)
        return {"ok": True}


def test_fire_lane_unknown_lane_is_fixed_text(monkeypatch):
    fake = _Lanes()
    monkeypatch.setattr(mod, "_lanes", lambda: fake)
    status, payload = mod._fire_lane({"lane": PROBE, "run_id": "cafe0001",
                                      "worktree": "wt/x"})
    assert status == 400 and payload["ok"] is False
    assert payload["error"] == "unknown lane"
    assert payload["valid"] == ["repo", "queue"]
    assert payload["action"] == "fire_lane"
    assert fake.calls == []
    _no_echo(payload)


def test_queue_intent_unknown_intent_is_fixed_text(_isolate):
    status, payload = mod._queue_intent({"intent": PROBE}, "k1")
    assert status == 400 and payload["ok"] is False
    assert payload["error"] == "unknown intent"
    assert payload["valid"] == list(mod._INTENT_FILES)
    assert list(_isolate.iterdir()) == []
    _no_echo(payload)


def test_steer_unknown_tier_is_fixed_text(monkeypatch):
    appended = []
    fake = types.SimpleNamespace(
        TIERS=("note", "steer"),
        append=lambda *a, **k: appended.append((a, k)) or {"id": 1})
    monkeypatch.setitem(sys.modules, mod._STEER_MODULE, fake)
    status, payload = mod._steer({"tier": PROBE, "text": "hello"}, "k1")
    assert status == 400 and payload["ok"] is False
    assert payload["error"] == "unknown tier"
    assert payload["valid"] == ["note", "steer"]
    assert appended == []
    _no_echo(payload)


def test_apply_action_unknown_action_is_fixed_text():
    status, payload = mod.apply_action(PROBE, {})
    assert status == 400 and payload["ok"] is False
    assert payload["error"] == "unknown action"
    assert payload["valid"] == list(mod._VALID_ACTIONS)
    _no_echo(payload)


def test_route_action_unknown_action_is_fixed_text():
    status, payload = mod.route_action(PROBE, {})
    assert status == 400 and payload["ok"] is False
    assert payload["error"] == "unknown action"
    assert payload["valid"] == (list(armgate.ROUTE_ACTIONS)
                                + list(mod._VALID_ACTIONS))
    _no_echo(payload)


def test_arm_ungated_target_action_is_fixed_text():
    status, payload = mod._handle_arm({"target_action": PROBE})
    assert status == 400 and payload["ok"] is False
    assert payload["error"] == (
        "not a gated action - only irreversible acts are armed, the rest "
        "fire directly")
    assert payload["gated"] == list(armgate.GATED_ACTIONS)
    _no_echo(payload)


def test_the_served_reply_carries_no_echo():
    """The HTTP handler path, end to end, for the outermost site."""
    sent = []

    class H:
        def _send(self, status, body, ctype):
            sent.append((status, body))

    mod._serve_loop_control(H(), {"action": PROBE})
    status, body = sent[0]
    assert status == 400
    payload = json.loads(body.decode("utf-8"))
    assert payload["error"] == "unknown action"
    _no_echo(payload)
