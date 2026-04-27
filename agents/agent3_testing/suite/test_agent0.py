"""Unit tests for Agent 0 evaluator — 6 criteria × pass/fail per §7."""
from __future__ import annotations

import pytest

from agents.agent0_gatekeeper import Evaluator, Task


@pytest.fixture()
def evaluator() -> Evaluator:
    return Evaluator()


def _valid_task(**overrides) -> Task:
    base = dict(
        op="push-web-ui",
        originating_agent="5",
        remote_path=r"\\192.168.8.237\RCClient\web\index.html",
        payload_ext=".html",
        tag="ui-update",
    )
    base.update(overrides)
    return Task(**base)


def test_accept_happy_path(evaluator: Evaluator) -> None:
    d = evaluator.evaluate(_valid_task())
    assert d.accepted is True
    assert d.criteria_passed == [1, 2, 3, 4, 5, 6]


def test_reject_unknown_operation(evaluator: Evaluator) -> None:
    d = evaluator.evaluate(_valid_task(op="nuke-all"))
    assert d.accepted is False
    assert d.rejection.reason_code == 6
    assert d.rejection.disposition == "dead_letter"


def test_reject_target_mismatch(evaluator: Evaluator) -> None:
    d = evaluator.evaluate(_valid_task(remote_path=r"\\10.0.0.1\web\x.html"))
    assert d.accepted is False
    assert d.rejection.reason_code == 1


def test_reject_payload_mismatch(evaluator: Evaluator) -> None:
    d = evaluator.evaluate(_valid_task(payload_ext=".exe",
                                       remote_path=r"\\192.168.8.237\RCClient\web\x.exe"))
    assert d.accepted is False
    assert d.rejection.reason_code == 2


def test_reject_destination_outside_allowlist(evaluator: Evaluator) -> None:
    d = evaluator.evaluate(_valid_task(remote_path=r"\\192.168.8.237\RCClient\etc\x.html"))
    assert d.accepted is False
    assert d.rejection.reason_code == 3


def test_reject_authority(evaluator: Evaluator) -> None:
    d = evaluator.evaluate(_valid_task(originating_agent="7"))
    assert d.accepted is False
    assert d.rejection.reason_code == 6


def test_protected_window_blocks_restart_during_match() -> None:
    e = Evaluator(game_state_probe=lambda: "IN_PROGRESS")
    d = e.evaluate(Task(
        op="trigger-forwarder-restart",
        originating_agent="2",
        remote_path=r"\\192.168.8.237\RCClient\forwarder\restart_trigger.txt",
        payload_ext=".txt",
        tag="restart-forwarder",
    ))
    assert d.accepted is False
    assert d.rejection.reason_code == 4
    assert d.rejection.disposition == "retry_once"


def test_protected_window_allows_restart_between_matches() -> None:
    e = Evaluator(game_state_probe=lambda: "NONE")
    d = e.evaluate(Task(
        op="trigger-forwarder-restart",
        originating_agent="2",
        remote_path=r"\\192.168.8.237\RCClient\forwarder\restart_trigger.txt",
        payload_ext=".txt",
        tag="restart-forwarder",
    ))
    assert d.accepted is True


def test_repeat_pattern_trips_on_third_attempt() -> None:
    e = Evaluator()
    t = Task(
        op="push-web-ui",
        originating_agent="5",
        remote_path=r"\\192.168.8.237\RCClient\web\x.html",
        payload_ext=".html",
        signature="test-sig-repeat",
    )
    first = e.evaluate(t)
    second = e.evaluate(t)
    third = e.evaluate(t)
    assert first.accepted and second.accepted
    assert third.accepted is False
    assert third.rejection.reason_code == 5
    assert third.rejection.disposition == "retry_once"


# --- traversal / path-safety cases (audit P-audit-h1) -------------------

@pytest.mark.parametrize("bad_path", [
    r"\\192.168.8.237\RCClient\web\..\..\x.html",
    r"\\192.168.8.237\RCClient\web\..\forwarder\x.html",
    r"\\192.168.8.237\RCClient\web\subdir\..\..\etc\x.html",
    r"\\192.168.8.237/RCClient/web/../../x.html",            # mixed separators
    r"\\192.168.8.237\RCClient\web\%2e%2e\x.html",           # url-encoded
])
def test_reject_path_traversal(bad_path: str) -> None:
    """Traversal check must fire before any other criterion — including
    mixed-separator paths, so no attacker can hide behind target_mismatch.
    """
    e = Evaluator()
    d = e.evaluate(Task(
        op="push-web-ui", originating_agent="5",
        remote_path=bad_path, payload_ext=".html", tag="trav",
    ))
    assert d.accepted is False
    assert d.rejection.reason_code == 3
    assert d.rejection.reason_label == "destination_traversal"


def test_reject_subdir_substring_attack() -> None:
    """Was M3 pre-fix: ``RCClient\\forwarder\\web\\x.html`` could match web-subdir
    via `in` substring; now we require subdir to follow RCClient immediately.
    """
    e = Evaluator()
    d = e.evaluate(Task(
        op="push-web-ui", originating_agent="5",
        remote_path=r"\\192.168.8.237\RCClient\forwarder\web\x.html",
        payload_ext=".html", tag="substr",
    ))
    assert d.accepted is False
    # Rejected at destination prefix — forwarder prefix is not allowed for
    # push-web-ui's web-subdir expectation.
    assert d.rejection.reason_code == 3
