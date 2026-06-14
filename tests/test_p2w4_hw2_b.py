# arch: P2 cycle-15 hw2 slice-B regression tests for ops phase3 + loop controller | section=tests | frozen=no
"""Regression tests for DEEP_AUDIT_CHARTER P2 cycle 15 half-wave 2 slice B
(ops/phase3_* audit + ops/loop/* headless-audit loop controller).

NO network, NO loop execution, NO restart. Subprocess is monkeypatched - the
real ``git`` / ``head`` binaries are never invoked.

FIX-NOW covered here (friction class #4 - subprocess no-timeout):

  ops/loop/loop_controller.py ``git()`` is the loop BRAIN's only git accessor
  (head/director/auditor/tail all funnel through it). It ran ``subprocess.run``
  with NO ``timeout``, so a wedged git (a stale ``.git/index.lock`` from a
  crashed parallel worktree agent, a hung pre-commit hook, an editor parked on
  COMMIT_EDITMSG) blocks the synchronous call forever. The controller's only
  deadlines guard the AHK/claude handshake (``wait_for``/``wait_gone``), NOT the
  in-line git calls - so a git hang strands the entire unattended run with no
  STOP. The fix bounds every git call with a finite timeout and degrades a
  timeout / failure to "" (the same empty-string contract callers already
  tolerate: ``prev_sha[:8]`` slices "", ``done.get("sha") or head()`` falls
  through, ``auditor`` guards ``if not new_sha``).

  The same one-line no-timeout pattern lived in ``head()`` of
  ops/loop/done_sentinel.py (Claude's FINAL cycle step) and
  ops/loop/claude_stub.py (dry-run typist sim); both now bound + degrade.
"""
from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

import pytest

_OPS_LOOP = Path(__file__).resolve().parent.parent / "ops" / "loop"
if str(_OPS_LOOP) not in sys.path:
    sys.path.insert(0, str(_OPS_LOOP))


@pytest.fixture
def lc():
    """Import (or re-import) the controller module. Top-level loads config.json
    and mkdir's the real control dir - both idempotent + side-effect-safe."""
    mod = importlib.import_module("loop_controller")
    return importlib.reload(mod)


# --------------------------------------------------------------------------- git() bounds every call
class TestLoopControllerGitHasTimeout:
    """Every ``git()`` invocation MUST pass a finite timeout so a wedged git
    cannot hang the headless controller forever."""

    def test_git_passes_finite_timeout(self, lc, monkeypatch):
        captured = {}

        def fake_run(*args, **kwargs):
            captured.update(kwargs)

            class _R:
                stdout = "deadbeef\n"

            return _R()

        monkeypatch.setattr(lc.subprocess, "run", fake_run)
        out = lc.git("rev-parse", "HEAD")
        assert out == "deadbeef"
        assert "timeout" in captured, "git() must pass a timeout= to subprocess.run"
        assert captured["timeout"] is not None
        assert captured["timeout"] > 0

    def test_git_timeout_degrades_to_empty(self, lc, monkeypatch):
        # A TimeoutExpired (or any subprocess/OS error) must NOT propagate and
        # strand the loop - it degrades to "" (callers tolerate empty).
        def fake_run(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd="git", timeout=kwargs.get("timeout", 1))

        monkeypatch.setattr(lc.subprocess, "run", fake_run)
        assert lc.git("rev-parse", "HEAD") == ""

    def test_git_oserror_degrades_to_empty(self, lc, monkeypatch):
        def fake_run(*args, **kwargs):
            raise OSError("git binary missing")

        monkeypatch.setattr(lc.subprocess, "run", fake_run)
        assert lc.git("rev-parse", "HEAD") == ""

    def test_head_degrades_to_empty_on_timeout(self, lc, monkeypatch):
        # head() is the launch-time + post-cycle sha read; an empty return must
        # be safe (prev_sha[:8] of "" is "").
        def fake_run(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd="git", timeout=kwargs.get("timeout", 1))

        monkeypatch.setattr(lc.subprocess, "run", fake_run)
        sha = lc.head()
        assert sha == ""
        assert sha[:8] == ""  # the actual downstream slice never raises


# --------------------------------------------------------------------------- done_sentinel head() bounds
class TestDoneSentinelHeadHasTimeout:
    """done_sentinel.head() is Claude's FINAL cycle action; a git hang there
    means claude.done is never written. Bound it + degrade to ""."""

    def test_done_sentinel_head_passes_timeout(self, monkeypatch):
        ds = importlib.import_module("done_sentinel")
        ds = importlib.reload(ds)
        captured = {}

        def fake_run(*args, **kwargs):
            captured.update(kwargs)

            class _R:
                stdout = "cafef00d\n"

            return _R()

        monkeypatch.setattr(ds.subprocess, "run", fake_run)
        assert ds.head() == "cafef00d"
        assert captured.get("timeout") is not None
        assert captured["timeout"] > 0

    def test_done_sentinel_head_degrades_to_empty(self, monkeypatch):
        ds = importlib.import_module("done_sentinel")
        ds = importlib.reload(ds)

        def fake_run(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd="git", timeout=5)

        monkeypatch.setattr(ds.subprocess, "run", fake_run)
        assert ds.head() == ""


# --------------------------------------------------------------------------- claude_stub head() bounds
class TestClaudeStubHeadHasTimeout:
    """The dry-run typist sim's head() shares the same no-timeout pattern."""

    def test_claude_stub_head_passes_timeout(self, monkeypatch):
        cs = importlib.import_module("claude_stub")
        cs = importlib.reload(cs)
        captured = {}

        def fake_run(*args, **kwargs):
            captured.update(kwargs)

            class _R:
                stdout = "0badf00d\n"

            return _R()

        monkeypatch.setattr(cs.subprocess, "run", fake_run)
        assert cs.head() == "0badf00d"
        assert captured.get("timeout") is not None
        assert captured["timeout"] > 0
