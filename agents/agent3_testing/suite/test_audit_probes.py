"""Wire Agent 6's `_audit_probes.py` into the pytest suite so evaluator
regressions (traversal acceptance, subdir bypass, dotfile/no-ext
acceptance) surface as a red test instead of living in an ad-hoc
manual-smoke script. Audit P-audit3-l03.
"""
from __future__ import annotations

import pytest

from agents.agent0_gatekeeper import Evaluator, Task


@pytest.fixture()
def evaluator() -> Evaluator:
    return Evaluator()


def test_traversal_sibling_rejected(evaluator: Evaluator) -> None:
    t = Task(op="push-web-ui", originating_agent="5",
             remote_path=r"\\192.168.8.237\RCClient\web\..\forwarder\evil.py",
             payload_ext=".py", tag="trav-sibling")
    d = evaluator.evaluate(t)
    assert d.accepted is False
    assert d.rejection.reason_code == 3


def test_traversal_escape_rejected(evaluator: Evaluator) -> None:
    t = Task(op="push-web-ui", originating_agent="5",
             remote_path=r"\\192.168.8.237\RCClient\web\..\..\x.html",
             payload_ext=".html", tag="trav-escape")
    d = evaluator.evaluate(t)
    assert d.accepted is False
    assert d.rejection.reason_code == 3


def test_double_prefix_trick_rejected(evaluator: Evaluator) -> None:
    t = Task(op="push-web-ui", originating_agent="5",
             remote_path=r"\\192.168.8.237\RCClient\web\..\..\RCClient\forwarder\x.py",
             payload_ext=".py", tag="trav-double")
    d = evaluator.evaluate(t)
    assert d.accepted is False
    assert d.rejection.reason_code == 3


def test_subdir_substring_attack_rejected(evaluator: Evaluator) -> None:
    t = Task(op="push-web-ui", originating_agent="5",
             remote_path=r"\\192.168.8.237\RCClient\forwarder\web\x.html",
             payload_ext=".html", tag="sneaky-subdir")
    d = evaluator.evaluate(t)
    assert d.accepted is False
    assert d.rejection.reason_code == 3


def test_dotfile_rejected(evaluator: Evaluator) -> None:
    t = Task(op="push-web-ui", originating_agent="5",
             remote_path=r"\\192.168.8.237\RCClient\web\.env",
             payload_ext=".env", tag="dotfile")
    d = evaluator.evaluate(t)
    assert d.accepted is False
    # extension not in allowlist
    assert d.rejection.reason_code == 2


def test_no_extension_rejected(evaluator: Evaluator) -> None:
    t = Task(op="push-web-ui", originating_agent="5",
             remote_path=r"\\192.168.8.237\RCClient\web\noext",
             payload_ext="", tag="noext")
    d = evaluator.evaluate(t)
    assert d.accepted is False
    assert d.rejection.reason_code == 2
