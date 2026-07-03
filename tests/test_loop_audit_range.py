# arch: tests for loop_controller auditor diff-window (R61) | section=tests | frozen=no
"""Regression guard for the gemini-headless AUDITOR diff window (R61).

ROOT CAUSE (false-positive REGRESS recursion, cycle 13 escalation): the auditor
scored only the SINGLE cycle's commits (prev_sha..new_sha). A /done docs-sync
commit that lands in its own cycle was then judged in isolation - the auditor saw
docs asserting an engine/logic change whose code was committed a cycle earlier
and lay OUTSIDE the window, so the lone docs commit read as a regression. That
fed a FIX-FIRST directive with nothing to fix, which shipped another docs commit,
audited alone again: an infinite REGRESS loop.

Fix: audit_range() bases the diff on the OLDER of the last-CLEAN anchor and
new_sha~2, so a docs commit always carries the commit it documents, and an
unresolved REGRESS chain keeps its full context back to the last known-good sha.

Loaded by file path so the module's argv-driven CFG load needs no real launch
(the .json-suffix guard makes import-under-pytest fall back to the real config).
"""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

_CTRL = Path(__file__).resolve().parent.parent / "ops" / "loop" / "loop_controller.py"


@pytest.fixture(scope="module")
def lc():
    spec = importlib.util.spec_from_file_location("loop_controller_uut_auditrange", _CTRL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True, text=True, check=True).stdout.strip()


def _init(root: Path) -> None:
    _run(root, "init", "-q")
    _run(root, "config", "user.email", "t@t")
    _run(root, "config", "user.name", "t")


def _commit(root: Path, name: str, content: str = "x") -> str:
    (root / name).write_text(content, encoding="utf-8")
    _run(root, "add", "-A")
    _run(root, "commit", "-q", "-m", f"commit {name}")
    return _run(root, "rev-parse", "HEAD")


def _log_count(root: Path, rng: str) -> int:
    out = subprocess.run(
        ["git", "-C", str(root), "log", "--oneline", rng],
        capture_output=True, text=True).stdout.strip()
    return len([ln for ln in out.splitlines() if ln.strip()])


# --- the exact false-positive: docs-sync commit following a fix ---------------

def test_docs_after_fix_spans_multiple_commits(lc, tmp_path, monkeypatch):
    """A lone /done docs commit whose fix landed the prior cycle must be audited
    together WITH that fix - never in isolation. This is the R61 acceptance test
    the verifier subagent re-runs: multi-commit diff when docs-sync follows a fix."""
    _init(tmp_path)
    _commit(tmp_path, "base.txt")                                   # C0 clean baseline
    c_fix = _commit(tmp_path, "engine.py", "def f():\n    return 1\n")  # the real FIX
    c_docs = _commit(tmp_path, "LEDGER.md", "docs sync of the fix")    # docs-only /done commit
    monkeypatch.setattr(lc, "ROOT", tmp_path)
    # last CLEAN anchor is the fix commit (its cycle audited clean); docs is HEAD
    rng = lc.audit_range(c_fix, c_docs)
    assert _log_count(tmp_path, rng) >= 2, f"docs+fix must both be in {rng}"
    # the fix's file must be visible in the audited diff (not the lone docs commit)
    diff = subprocess.run(
        ["git", "-C", str(tmp_path), "diff", rng],
        capture_output=True, text=True).stdout
    assert "engine.py" in diff, "the fix the docs document must be inside the window"


# --- fallback: no clean anchor recorded -> HEAD~2 floor -----------------------

def test_fallback_head2_when_no_clean_anchor(lc, tmp_path, monkeypatch):
    _init(tmp_path)
    _commit(tmp_path, "a.txt")
    _commit(tmp_path, "b.txt")
    _commit(tmp_path, "c.txt")
    c3 = _commit(tmp_path, "d.txt")
    monkeypatch.setattr(lc, "ROOT", tmp_path)
    rng = lc.audit_range(None, c3)             # no clean anchor -> HEAD~2 fallback
    assert _log_count(tmp_path, rng) == 2, f"HEAD~2 floor must give 2 commits, got {rng}"


# --- unresolved REGRESS chain: keep full context back to last clean -----------

def test_keeps_clean_anchor_when_older_than_floor(lc, tmp_path, monkeypatch):
    _init(tmp_path)
    c0 = _commit(tmp_path, "a.txt")            # last known-good
    _commit(tmp_path, "b.txt")
    _commit(tmp_path, "c.txt")
    _commit(tmp_path, "d.txt")
    c4 = _commit(tmp_path, "e.txt")
    monkeypatch.setattr(lc, "ROOT", tmp_path)
    rng = lc.audit_range(c0, c4)               # clean far older than HEAD~2
    assert _log_count(tmp_path, rng) == 4, f"must span the whole regress chain, got {rng}"


# --- young repo edge: never raise, never emit a bogus range -------------------

def test_young_repo_single_commit_does_not_raise(lc, tmp_path, monkeypatch):
    _init(tmp_path)
    c0 = _commit(tmp_path, "only.txt")
    monkeypatch.setattr(lc, "ROOT", tmp_path)
    rng = lc.audit_range(None, c0)             # no ancestors at all
    assert isinstance(rng, str) and c0 in rng  # git diff <sha> is a valid whole-tree diff


# --- backward-compat: auditor() still callable with 2 positional args ---------

def test_auditor_signature_backward_compatible(lc):
    import unittest.mock as mock
    with mock.patch.object(lc, "gemini", return_value=None), \
            mock.patch.object(lc, "git", return_value="someoutput"):
        verdict = lc.auditor("aaaaaa", "bbbbbb")   # legacy 2-arg call
    assert verdict.startswith("VERDICT: CLEAN")
