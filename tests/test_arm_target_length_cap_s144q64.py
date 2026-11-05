# arch: the arm refuses an over-long target with a fixed 400 | section=tests | frozen=no
"""RM-1375: the Mission Control arm accepted an unbounded `target`.

`_handle_arm` took `str(body["target"]).strip()` (or the same string derived
from the body's `lane` / `intent` by `armgate.target_of`) with no length bound,
stored it in the arm record (up to `armgate.MAX_ARMED` records) and echoed it in
the 200 reply. A legitimate target is a lane name, an intent id or the constant
"interrupt" (measured: the longest is "done_continue", 13 chars), and the
confirm only succeeds for a target the side-effect layer accepts, so an arm past
`armgate.MAX_TARGET` can never be confirmed. It now gets a fixed-text 400 that
echoes nothing and arms nothing.
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
from ops.loop import lanes as lanes_mod  # noqa: E402

MARK = "zq"


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
    yield
    idem.clear()
    armgate.clear()


def _serve(body: dict):
    h = FakeHandler()
    mod._serve_loop_control(h, body)
    assert h.sent is not None
    status, raw, _ctype = h.sent
    return status, raw.decode("utf-8"), json.loads(raw.decode("utf-8"))


def _legit_targets() -> list[str]:
    return (list(lanes_mod.LANES) + list(mod._INTENT_FILES)
            + [armgate.target_of("interrupt", {})])


def test_the_cap_admits_every_legitimate_target():
    assert isinstance(armgate.MAX_TARGET, int)
    assert max(len(t) for t in _legit_targets()) <= armgate.MAX_TARGET
    # A cap is a bound, not a formality.
    assert armgate.MAX_TARGET <= 256


@pytest.mark.parametrize("body", [
    {"action": "arm", "target_action": "fire_lane", "lane": "queue"},
    {"action": "arm", "target_action": "queue_intent", "intent": "done_continue"},
    {"action": "arm", "target_action": "interrupt"},
    {"action": "arm", "target_action": "fire_lane", "target": "true-audit"},
])
def test_a_legitimate_arm_still_arms(body):
    status, _raw, payload = _serve(body)
    assert status == 200
    assert payload["ok"] is True
    assert payload["arm_token"] in armgate._ARMED


def test_an_explicit_target_at_the_cap_arms():
    target = "a" * armgate.MAX_TARGET
    status, _raw, payload = _serve({"action": "arm", "target_action": "fire_lane",
                                    "target": target})
    assert status == 200
    assert payload["target"] == target


def test_the_cap_applies_after_the_strip():
    status, _raw, payload = _serve({"action": "arm", "target_action": "fire_lane",
                                    "target": " " * 5000 + "queue" + " " * 5000})
    assert status == 200
    assert payload["target"] == "queue"


@pytest.mark.parametrize("body", [
    {"action": "arm", "target_action": "fire_lane",
     "target": MARK * 40_000},
    {"action": "arm", "target_action": "fire_lane",
     "lane": MARK * 40_000},
    {"action": "arm", "target_action": "queue_intent",
     "intent": MARK * 40_000},
])
def test_an_over_long_target_is_refused_and_arms_nothing(body):
    status, raw, payload = _serve(body)
    assert status == 400
    assert payload["ok"] is False
    assert payload["action"] == "arm"
    assert payload["error"] == "arm 'target' is too long"
    assert payload["max_target"] == armgate.MAX_TARGET
    assert MARK * 4 not in raw
    assert "arm_token" not in payload
    assert armgate._ARMED == {}


def test_one_char_past_the_cap_is_refused():
    status, _raw, payload = _serve({"action": "arm", "target_action": "fire_lane",
                                    "target": "a" * (armgate.MAX_TARGET + 1)})
    assert status == 400
    assert armgate._ARMED == {}
