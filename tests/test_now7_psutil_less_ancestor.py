"""NOW-7 residual: in a psutil-less environment a genuinely nested child
pytest was always gated, because is_live_ancestor fell to its fail-safe False.

The stdlib fallback proves only the DIRECT parent (os.getppid() is fixed at
this process's creation). Deeper chains, and any pid that is not ours, still
answer False - an unverifiable stamp must never disarm the gate.
"""
from __future__ import annotations

import os
import sys

import pytest

from tests import _logger_leak_report as leak


@pytest.fixture()
def no_psutil(monkeypatch):
    monkeypatch.setitem(sys.modules, "psutil", None)  # import raises ImportError


def test_direct_parent_is_an_ancestor_without_psutil(no_psutil):
    assert leak.is_live_ancestor(os.getppid(), os.getpid()) is True


def test_unrelated_pid_is_not_an_ancestor_without_psutil(no_psutil):
    assert leak.is_live_ancestor(os.getpid() + 7919, os.getpid()) is False


def test_fallback_only_speaks_for_this_process(no_psutil):
    """A query about ANOTHER pid's parent chain is unverifiable: False."""
    assert leak.is_live_ancestor(os.getppid(), os.getppid()) is False


def test_garbage_stamp_is_not_an_ancestor_without_psutil(no_psutil):
    assert leak.is_live_ancestor("not-a-pid", os.getpid()) is False
