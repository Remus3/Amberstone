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


def _build_merge_repo(root: Path) -> dict:
    """feat -> merge --no-ff (feature = the merge SECOND parent) -> docs -> test.

    The exact R113 topology that produced FALSE-POSITIVE REGRESS #5: an engine
    change lands on a feature branch, gets merged via `git merge --no-ff` (so the
    feature commit is the merge's SECOND parent), then a docs-sync and a test
    commit sit on top. A first-parent-only `~2` floor walks straight past the
    second-parent feature, leaving it OUTSIDE the audit window."""
    _init(root)
    c0 = _commit(root, "base.txt")                                   # clean baseline
    main = _run(root, "rev-parse", "--abbrev-ref", "HEAD")
    _run(root, "checkout", "-q", "-b", "feature")
    c_feat = _commit(root, "engine.py", "def burst():\n    return 42\n")   # the real engine FIX
    _run(root, "checkout", "-q", main)
    _run(root, "merge", "--no-ff", "-m", "merge feature", "feature")       # feature = 2nd parent
    c_merge = _run(root, "rev-parse", "HEAD")
    c_docs = _commit(root, "LEDGER.md", "docs sync of the engine seam")    # finalize docs
    c_test = _commit(root, "test_seam.py", "def test_seam():\n    assert True\n")  # regression guard
    return {"c0": c0, "feat": c_feat, "merge": c_merge, "docs": c_docs, "test": c_test}


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
    with mock.patch.object(lc, "adjudicate", return_value=None), \
            mock.patch.object(lc, "git", return_value="someoutput"):
        verdict = lc.auditor("aaaaaa", "bbbbbb")   # legacy 2-arg call
    assert verdict.startswith("VERDICT: CLEAN")


# --- FALSE-POSITIVE REGRESS #5: feature merged via a merge SECOND parent ------

def test_merge_second_parent_feature_in_window(lc, tmp_path, monkeypatch):
    """feat-then-merge-then-finalize: the second-parent feature (and its diff) MUST
    be inside the audit window. A first-parent `~2` floor lands on the merge, so
    the two-dot window excludes the merged engine change; the auditor then sees
    docs+tests asserting a change with no code in range -> false-positive REGRESS."""
    r = _build_merge_repo(tmp_path)
    monkeypatch.setattr(lc, "ROOT", tmp_path)
    # merge cycle audited CLEAN (clean anchor = the docs commit); the test is HEAD
    rng = lc.audit_range(r["docs"], r["test"])
    log_shas = subprocess.run(
        ["git", "-C", str(tmp_path), "log", "--format=%H", rng],
        capture_output=True, text=True).stdout
    assert r["feat"] in log_shas, f"second-parent feature commit must be in {rng}"
    diff = subprocess.run(
        ["git", "-C", str(tmp_path), "diff", rng],
        capture_output=True, text=True).stdout
    assert "engine.py" in diff, f"the engine change the docs document must be in {rng}"


def test_merge_second_parent_in_window_no_clean_anchor(lc, tmp_path, monkeypatch):
    """Same merge topology with no clean anchor recorded: the bare HEAD~2 floor
    alone would still skip the second-parent feature. The merge-aware floor must
    still pull the engine diff into the window."""
    r = _build_merge_repo(tmp_path)
    monkeypatch.setattr(lc, "ROOT", tmp_path)
    rng = lc.audit_range(None, r["test"])
    diff = subprocess.run(
        ["git", "-C", str(tmp_path), "diff", rng],
        capture_output=True, text=True).stdout
    assert "engine.py" in diff, f"feature diff must be in {rng} even with no clean anchor"


# --- FALSE-POSITIVE REGRESS #6: head-truncation hides late-sorting paths ------


def _build_truncation_repo(root: Path) -> dict:
    """A commit whose early-sorting mirror files alone exceed the diff budget.

    The exact R136 topology that produced FALSE-POSITIVE REGRESS #6: one commit
    edited BOTH a generated mirror tree (139 files, since retired) and the true
    source (agents/daemon_slayer/, 129 files). git emits paths in byte order,
    so an upper-case-initial directory ('M', 0x4D) precedes every 'a' (0x61)
    path. The mirror content alone overran the auditor's head-truncation
    budget, so the true source never reached the prompt and the auditor
    concluded it was 'missing from the diff' -> REGRESS on a commit that was in
    fact complete and CI-green. The tree below reproduces that ORDERING, which
    is the property under test; the generator that produced the original mirror
    is irrelevant to it."""
    _init(root)
    c0 = _commit(root, "base.txt")
    (root / "Mirror").mkdir()
    (root / "agents").mkdir()
    for i in range(8):
        (root / "Mirror" / f"mirror_{i}.py").write_text(
            "# generated mirror - do not edit\n" + ("x = 1\n" * 3000), encoding="utf-8")
    (root / "agents" / "engine_true_source.py").write_text(
        "def rm101_rune_numerator():\n    return 1\n", encoding="utf-8")
    # auditor() reads its prompt template relative to ROOT
    (root / "ops" / "loop").mkdir(parents=True)
    (root / "ops" / "loop" / "auditor_prompt.md").write_text("AUDIT PROMPT", encoding="utf-8")
    _run(root, "add", "-A")
    _run(root, "commit", "-q", "-m", "mirror + true source in one commit")
    return {"c0": c0, "head": _run(root, "rev-parse", "HEAD")}


def test_truncated_diff_still_lists_late_sorting_true_source(lc, tmp_path, monkeypatch):
    """The auditor prompt MUST name every changed file even when the diff body is
    head-truncated. Without a complete manifest the auditor cannot distinguish
    'file absent from the commit' from 'file past the truncation point', which is
    exactly how a complete commit gets audited as a REGRESS."""
    r = _build_truncation_repo(tmp_path)
    monkeypatch.setattr(lc, "ROOT", tmp_path)
    captured = {}

    def _fake_gemini(body, _instruction):
        captured["body"] = body
        return "VERDICT: CLEAN"

    monkeypatch.setattr(lc, "adjudicate", _fake_gemini)
    lc.auditor(r["c0"], r["head"])
    body = captured["body"]
    # precondition: the mirror really does overrun the budget on its own
    assert "truncated" in body, "test repo must be large enough to trigger truncation"
    assert "engine_true_source.py" in body, (
        "a changed file that sorts after the truncation point must still be named "
        "in the prompt - otherwise the auditor reports it as missing")
