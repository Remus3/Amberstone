# arch: server-side arm-then-confirm gate on the loop-control route | section=tests | frozen=no
"""The arm-then-confirm gate must live on the SERVER, not in client JS.

WHY THIS FILE EXISTS. Until now the only arm-then-confirm in the repo was
`web/mc/arm_confirm.js:45`, a browser module. That made the guard a property of
ONE client: anything that spoke HTTP directly - curl, a script, a wedged phone,
a second tab - reached `interrupt` (a taskkill over a named victim set) in a
SINGLE call. Retiring the Mission Control web UI would therefore have deleted
the guard silently, because deleting a client cannot make a server safer.

So the gate is ported into the route layer. `dashboard/_arm_confirm.py` holds
the state machine, `dashboard/routes_loop_control._serve_loop_control` consults
it, and the properties asserted below are the ones the JS module had:

  * a destructive action with no arm is REFUSED and has NO side effect;
  * an arm token is bound to ONE action and ONE target;
  * an arm expires on its own;
  * a token is consumed on the confirm, so a second INTENT needs a second arm.

Plus one property the JS could not have, because a browser fetch retry and an
operator's second click are indistinguishable in the DOM: a TRANSPORT-level
re-send of the same confirm resolves to the same idempotency key and replays
the stored answer rather than being refused. That is the seam where this gate
meets `dashboard/routes_loop_control._apply_idempotent` (`:482-565`), and both
halves are asserted here so neither can be "fixed" into breaking the other.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dashboard import _arm_confirm as armgate  # noqa: E402
from dashboard import _idempotency as idem  # noqa: E402
from dashboard import routes_loop_control as mod  # noqa: E402


class FakeHandler:
    """The 3-method surface the route module actually consumes."""

    def __init__(self, path: str = "/api/loop-control"):
        self.path = path
        self.sent: tuple | None = None

    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.sent = (status, body, ctype)


@pytest.fixture(autouse=True)
def clean_tables():
    """Both registries are process-global - isolate every test."""
    idem.clear()
    armgate.clear()
    yield
    idem.clear()
    armgate.clear()


@pytest.fixture
def ctldir(tmp_path, monkeypatch):
    ctl = tmp_path / "control"
    ctl.mkdir()
    monkeypatch.setattr(mod, "CONTROL_DIR", ctl)
    return ctl


def _post(body):
    """Drive the REAL route entry point - the gate must be on this path."""
    h = FakeHandler()
    mod._serve_loop_control(h, body)
    assert h.sent is not None
    status, raw, ctype = h.sent
    return status, json.loads(raw.decode("utf-8")), ctype


def _arm(target_action, **extra):
    body = {"action": "arm", "target_action": target_action}
    body.update(extra)
    status, payload, _ = _post(body)
    return status, payload


KEY_A = "aaaaaaaa-1111-2222-3333-444444444444"
KEY_B = "bbbbbbbb-1111-2222-3333-444444444444"

VICTIM = {"pid": 4242, "name": "claude.exe", "kind": "lane", "lane": "ds",
          "run_id": "r1", "cmdline": "claude -p", "ppid": 100, "started": 1.0}


class FakeInterrupt:
    """Stand-in for ops/loop/interrupt.py - records every execute()."""

    def __init__(self):
        self.executed: list = []
        self.previews = 0

    def preview(self):
        self.previews += 1
        return {"ok": True, "count": 1, "victims": [VICTIM], "fingerprint": "fp1"}

    def execute(self, fingerprint, key=None):
        self.executed.append((fingerprint, key))
        return {"ok": True, "killed": [VICTIM], "fingerprint": fingerprint}


@pytest.fixture
def irq(monkeypatch):
    fake = FakeInterrupt()
    monkeypatch.setitem(sys.modules, "ops.loop.interrupt", fake)
    return fake


class FakeLanes:
    LANES = ("ds", "repo", "uiux")

    def __init__(self):
        self.calls: list = []

    def try_acquire_lane(self, lane, run_id=None, worktree=None):
        self.calls.append({"lane": lane, "run_id": run_id, "worktree": worktree})
        return {"ok": True, "lane": lane, "run_id": run_id, "worktree": worktree}

    def release_lane(self, *a, **k):
        return True


@pytest.fixture
def lanes(monkeypatch):
    fake = FakeLanes()
    monkeypatch.setitem(sys.modules, "ops.loop.lanes", fake)
    launcher = types.SimpleNamespace(
        worktree_path=lambda lane: f"C:/wt/{lane}",
        launch_lane=lambda lane, run_id=None, token=None: {"ok": True, "pid": 999},
    )
    monkeypatch.setitem(sys.modules, "ops.loop.lane_launcher", launcher)
    return fake


# ===================================================== the headline refusal
# One unconfirmed call must not kill anything. This is the whole point of the
# file; if only one test in it survives, it must be this one.

def test_a_single_unconfirmed_interrupt_is_refused_and_kills_nothing(ctldir, irq):
    status, payload, _ = _post({"action": "interrupt", "fingerprint": "fp1",
                                "idempotency_key": KEY_A})
    assert status == 409, payload
    assert payload["ok"] is False
    assert payload["refused"] == "arm_required"
    assert payload["arm_required"] is True
    # The side effect never ran - not "ran and was undone".
    assert irq.executed == []


def test_the_confirmed_two_step_interrupt_still_fires(ctldir, irq):
    status, armed = _arm("interrupt")
    assert status == 200 and armed["ok"] is True
    token = armed["arm_token"]
    assert token

    status, payload, _ = _post({"action": "interrupt", "fingerprint": "fp1",
                                "arm_token": token, "idempotency_key": KEY_A})
    assert status == 200, payload
    assert payload["ok"] is True
    assert irq.executed == [("fp1", KEY_A)]


# ===================================================== the other gated actions

def test_a_single_unconfirmed_fire_lane_is_refused_and_acquires_nothing(ctldir, lanes):
    status, payload, _ = _post({"action": "fire_lane", "lane": "ds",
                                "run_id": "r1", "worktree": "C:/wt/ds",
                                "idempotency_key": KEY_A})
    assert status == 409 and payload["refused"] == "arm_required"
    assert lanes.calls == []


def test_the_confirmed_two_step_fire_lane_still_acquires(ctldir, lanes):
    _status, armed = _arm("fire_lane", lane="ds")
    status, payload, _ = _post({"action": "fire_lane", "lane": "ds",
                                "run_id": "r1", "worktree": "C:/wt/ds",
                                "arm_token": armed["arm_token"],
                                "idempotency_key": KEY_A})
    assert status == 200 and payload["ok"] is True
    assert len(lanes.calls) == 1 and lanes.calls[0]["lane"] == "ds"


def test_a_single_unconfirmed_queue_intent_is_refused_and_writes_nothing(ctldir):
    status, payload, _ = _post({"action": "queue_intent", "intent": "halt_save",
                                "idempotency_key": KEY_A})
    assert status == 409 and payload["refused"] == "arm_required"
    assert not (ctldir / "INTENT_HALT_SAVE.json").exists()
    assert not (ctldir / "STOP").exists()


def test_the_confirmed_two_step_queue_intent_still_writes(ctldir):
    _status, armed = _arm("queue_intent", intent="halt_save")
    status, payload, _ = _post({"action": "queue_intent", "intent": "halt_save",
                                "arm_token": armed["arm_token"],
                                "idempotency_key": KEY_A})
    assert status == 200 and payload["ok"] is True
    assert (ctldir / "INTENT_HALT_SAVE.json").exists()


# ===================================================== token binding

def test_a_token_armed_for_one_action_cannot_confirm_another(ctldir, irq, lanes):
    _status, armed = _arm("fire_lane", lane="ds")
    status, payload, _ = _post({"action": "interrupt", "fingerprint": "fp1",
                                "arm_token": armed["arm_token"],
                                "idempotency_key": KEY_A})
    assert status == 409 and payload["refused"] == "other_armed"
    assert irq.executed == []


def test_a_token_armed_for_one_lane_cannot_fire_another(ctldir, lanes):
    _status, armed = _arm("fire_lane", lane="ds")
    status, payload, _ = _post({"action": "fire_lane", "lane": "repo",
                                "run_id": "r1", "worktree": "C:/wt/repo",
                                "arm_token": armed["arm_token"],
                                "idempotency_key": KEY_A})
    assert status == 409 and payload["refused"] == "other_armed"
    assert lanes.calls == []


def test_an_invented_token_is_refused(ctldir, irq):
    status, payload, _ = _post({"action": "interrupt", "fingerprint": "fp1",
                                "arm_token": "deadbeef-0000-0000-0000-000000000000",
                                "idempotency_key": KEY_A})
    assert status == 409 and payload["refused"] == "bad_token"
    assert irq.executed == []


# ===================================================== expiry and single use

def test_an_expired_arm_is_refused(ctldir, irq, monkeypatch):
    _status, armed = _arm("interrupt")
    token = armed["arm_token"]
    # Walk the clock past the arm window without sleeping.
    monkeypatch.setattr(armgate, "_now",
                        lambda: armed["expires_at"] + 0.001)
    status, payload, _ = _post({"action": "interrupt", "fingerprint": "fp1",
                                "arm_token": token, "idempotency_key": KEY_A})
    assert status == 409 and payload["refused"] == "expired"
    assert irq.executed == []


def test_a_second_intent_on_a_consumed_token_is_refused(ctldir, irq):
    _status, armed = _arm("interrupt")
    token = armed["arm_token"]
    status, _payload, _ = _post({"action": "interrupt", "fingerprint": "fp1",
                                 "arm_token": token, "idempotency_key": KEY_A})
    assert status == 200
    # A DIFFERENT key on the same token is a SECOND operator intent wearing a
    # spent arm. One arm, one intent - so this is a refusal, not a second kill.
    status, payload, _ = _post({"action": "interrupt", "fingerprint": "fp1",
                                "arm_token": token, "idempotency_key": KEY_B})
    assert status == 409 and payload["refused"] == "consumed"
    assert len(irq.executed) == 1


def test_re_arming_after_a_fire_works(ctldir, irq):
    for _ in range(2):
        _status, armed = _arm("interrupt")
        status, _payload, _ = _post({"action": "interrupt", "fingerprint": "fp1",
                                     "arm_token": armed["arm_token"]})
        assert status == 200
    assert len(irq.executed) == 2


# ===================================================== the idempotency seam
# Requirement: the replay protection at routes_loop_control.py:482-565 must
# stay intact THROUGH the gate.

def test_a_transport_retry_of_the_confirm_replays_and_does_not_fire_twice(ctldir, irq):
    _status, armed = _arm("interrupt")
    token = armed["arm_token"]
    body = {"action": "interrupt", "fingerprint": "fp1",
            "arm_token": token, "idempotency_key": KEY_A}

    status, first, _ = _post(dict(body))
    assert status == 200 and first.get("replayed") is None

    status, second, _ = _post(dict(body))
    assert status == 200, second
    assert second["replayed"] is True
    # ONE kill, from two identical requests.
    assert len(irq.executed) == 1


def test_a_curl_caller_need_not_mint_a_key_the_arm_mints_one(ctldir, irq):
    _status, armed = _arm("interrupt")
    assert armgate.is_valid_key(armed["idempotency_key"])
    status, payload, _ = _post({"action": "interrupt", "fingerprint": "fp1",
                                "arm_token": armed["arm_token"]})
    assert status == 200 and payload["ok"] is True
    # The key the ARM minted is the one the side effect ran under.
    assert irq.executed == [("fp1", armed["idempotency_key"])]


def test_a_keyless_retry_replays_under_the_arm_minted_key(ctldir, irq):
    _status, armed = _arm("interrupt")
    body = {"action": "interrupt", "fingerprint": "fp1",
            "arm_token": armed["arm_token"]}
    assert _post(dict(body))[0] == 200
    status, second, _ = _post(dict(body))
    assert status == 200 and second["replayed"] is True
    assert len(irq.executed) == 1


# ===================================================== what is NOT gated
# The gate is a cost. It is paid only by acts that cannot be taken back.

@pytest.mark.parametrize("body", [
    {"action": "stop", "reason": "halt"},
    {"action": "resume"},
    {"action": "set_directive", "text": "do the thing"},
    {"action": "clear_directive"},
])
def test_the_four_reversible_actions_need_no_arm(ctldir, body):
    status, payload, _ = _post(body)
    assert status == 200 and payload["ok"] is True


def test_steer_needs_no_arm(ctldir, monkeypatch):
    """GUIDANCE, NOT A COMMAND - routes_loop_control.py:353-357 says so."""
    chan = types.SimpleNamespace(
        append=lambda text, tier="note", key=None: {"id": 1, "tier": tier},
        MAX_TEXT=4000, TIERS=("note", "steer"))
    monkeypatch.setitem(sys.modules, "ops.loop.steer", chan)
    status, payload, _ = _post({"action": "steer", "tier": "note",
                                "text": "hi", "idempotency_key": KEY_A})
    assert status == 200, payload
    assert payload["ok"] is True


def test_interrupt_preview_needs_no_arm_and_is_how_you_get_the_fingerprint(ctldir, irq):
    status, payload, _ = _post({"action": "interrupt_preview"})
    assert status == 200 and payload["fingerprint"] == "fp1"
    assert irq.executed == []


# ===================================================== the arm action itself

def test_arm_writes_nothing_to_the_control_dir(ctldir, irq):
    before = sorted(p.name for p in ctldir.iterdir())
    _arm("interrupt")
    assert sorted(p.name for p in ctldir.iterdir()) == before


def test_arming_an_ungated_action_is_a_400(ctldir):
    status, payload, _ = _post({"action": "arm", "target_action": "stop"})
    assert status == 400 and payload["ok"] is False
    assert "gated" in payload["error"]


def test_arm_requires_a_target_action(ctldir):
    status, payload, _ = _post({"action": "arm"})
    assert status == 400 and payload["ok"] is False


def test_disarm_discards_the_token(ctldir, irq):
    _status, armed = _arm("interrupt")
    status, payload, _ = _post({"action": "disarm",
                                "arm_token": armed["arm_token"]})
    assert status == 200 and payload["ok"] is True
    status, payload, _ = _post({"action": "interrupt", "fingerprint": "fp1",
                                "arm_token": armed["arm_token"]})
    assert status == 409 and payload["refused"] == "bad_token"
    assert irq.executed == []


def test_an_unknown_action_lists_arm_in_the_valid_set(ctldir):
    status, payload, _ = _post({"action": "nuke"})
    assert status == 400 and payload["ok"] is False
    assert "arm" in payload["valid"]
    assert "interrupt" in payload["valid"]


# ===================================================== structural pins

def test_the_gated_set_is_exactly_the_irreversible_three():
    assert set(armgate.GATED_ACTIONS) == {"fire_lane", "queue_intent", "interrupt"}


def test_every_gated_action_is_a_real_action():
    for action in armgate.GATED_ACTIONS:
        assert action in mod._VALID_ACTIONS


def test_the_registered_post_handler_is_the_gated_one():
    """A second, ungated sibling entry point would defeat the whole file."""
    assert len(mod.POST_ROUTES) == 1
    matcher, fn = mod.POST_ROUTES[0]
    assert matcher("/api/loop-control") is True
    assert fn is mod._serve_loop_control


def test_the_arm_table_is_bounded():
    """Client-supplied traffic must not grow a registry without limit."""
    for i in range(armgate.MAX_ARMED + 10):
        armgate.arm("interrupt", "interrupt")
    assert armgate.armed_count() <= armgate.MAX_ARMED
