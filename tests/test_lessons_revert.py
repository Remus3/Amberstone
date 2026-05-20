"""Tests for core/lessons_revert (Phase 4 (c) auto-revert).

Covers: tests-pass apply path, tests-fail queued fallback, tests-fail +
commit_sha revert path, git revert failure, _tail trimming, CLI exit
codes.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import core.lessons_revert as lr


# ---------------------------------------------------------------------------
# Stubs / fixtures
# ---------------------------------------------------------------------------

class _FakeProc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _stub_receiver(monkeypatch, *, raises=None):
    captured: dict = {}

    def fake_post(lesson_id, decision, rationale, receiver_notes=""):
        captured["lesson_id"] = lesson_id
        captured["decision"] = decision
        captured["rationale"] = rationale
        captured["receiver_notes"] = receiver_notes
        if raises is not None:
            raise raises
        return {"ts": 1.0, "lesson_id": lesson_id, "decision": decision,
                "memory_path": "/m/x.md", "ack_ok": True}

    monkeypatch.setattr(lr._receiver, "post_decision", fake_post)
    return captured


def _stub_bridge(monkeypatch, *, ok=True, detail="ok"):
    captured: dict = {}

    def fake_send(*, source, summary, kind, target, body, in_reply_to=None):
        captured["source"] = source
        captured["summary"] = summary
        captured["kind"] = kind
        captured["target"] = target
        captured["body"] = body
        captured["in_reply_to"] = in_reply_to
        return (ok, detail)

    monkeypatch.setattr(lr._bridge, "send", fake_send)
    return captured


def _stub_run(monkeypatch, *, returncode=0, stdout="", stderr="",
              raise_exc=None):
    calls: list = []

    def fake_run(cmd, **kwargs):
        calls.append((tuple(cmd), kwargs))
        if raise_exc is not None:
            raise raise_exc
        # First call = pytest; subsequent = git revert / git rev-parse
        # The fake honours the same return contract for all.
        if cmd[0:3] == ["git", "rev-parse", "HEAD"]:
            return _FakeProc(0, "newshaabc\n", "")
        if cmd[0:2] == ["git", "revert"]:
            return _FakeProc(0, "ok\n", "")
        return _FakeProc(returncode, stdout, stderr)

    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls


# ---------------------------------------------------------------------------
# _tail
# ---------------------------------------------------------------------------

def test_tail_short_string_untrimmed():
    assert lr._tail("abc") == "abc"


def test_tail_trims_to_last_bytes():
    s = "x" * 5000
    out = lr._tail(s, max_bytes=100)
    assert len(out.encode("utf-8")) <= 100


def test_tail_prefers_line_boundary():
    s = "first\n" + ("y" * 200) + "\nlast\n"
    out = lr._tail(s, max_bytes=120)
    assert "first" not in out
    assert out.endswith("last\n")


def test_tail_empty():
    assert lr._tail("") == ""


# ---------------------------------------------------------------------------
# Branch 1: tests pass -> applied, no revert, no follow-up ack
# ---------------------------------------------------------------------------

def test_apply_tests_pass(monkeypatch, tmp_path):
    _stub_run(monkeypatch, returncode=0, stdout="1 passed\n")
    rec = _stub_receiver(monkeypatch)
    ack = _stub_bridge(monkeypatch)

    rep = lr.apply_with_revert(
        "lesson-AAA", commit_sha="deadbeef",
        rationale="ok", receiver_notes="manual notes",
        tests=("tests/test_lessons_ack_watcher.py",),
        timeout_s=10.0, cwd=tmp_path,
    )
    assert rep.decision == "applied"
    assert rep.auto_reverted is False
    assert rep.tests_ok is True
    assert rep.tests_returncode == 0
    assert rec["lesson_id"] == "lesson-AAA"
    assert rec["decision"] == "applied"
    # post_decision handles its own ack; we do NOT send a duplicate.
    assert ack == {}


# ---------------------------------------------------------------------------
# Branch 2: tests fail, no commit_sha -> queued
# ---------------------------------------------------------------------------

def test_tests_fail_no_commit_queues(monkeypatch, tmp_path):
    _stub_run(monkeypatch, returncode=1, stdout="1 failed\n")
    rec = _stub_receiver(monkeypatch)
    ack = _stub_bridge(monkeypatch)

    rep = lr.apply_with_revert(
        "lesson-BBB", commit_sha=None, tests=("tests/x.py",),
        timeout_s=10.0, cwd=tmp_path,
    )
    assert rep.decision == "queued"
    assert rep.auto_reverted is False
    assert rep.tests_ok is False
    assert rep.revert_commit_sha is None
    assert rec["decision"] == "queued"
    # Receiver's post_decision handles the queued ack; no second send.
    assert ack == {}


# ---------------------------------------------------------------------------
# Branch 3: tests fail + commit_sha -> revert + follow-up ack
# ---------------------------------------------------------------------------

def test_tests_fail_with_commit_reverts(monkeypatch, tmp_path):
    calls = _stub_run(monkeypatch, returncode=1, stdout="FAILED test_x\n")
    rec = _stub_receiver(monkeypatch)
    ack = _stub_bridge(monkeypatch)

    rep = lr.apply_with_revert(
        "lesson-CCC", commit_sha="cafef00d",
        rationale="tried", receiver_notes="initial",
        tests=("tests/x.py",), timeout_s=10.0, cwd=tmp_path,
    )
    assert rep.decision == "applied"
    assert rep.auto_reverted is True
    assert rep.tests_ok is False
    assert rep.revert_commit_sha == "newshaabc"
    # Receiver got the applied + auto-revert annotations
    assert rec["decision"] == "applied"
    assert "auto-revert" in (rec["receiver_notes"] or "")
    # Follow-up ack carries auto_reverted=True so the origin's
    # ack-watcher can flip 'took' for the sender ledger.
    assert ack["kind"] == "result"
    assert ack["in_reply_to"] == "lesson-CCC"
    assert ack["body"]["auto_reverted"] is True
    assert ack["body"]["decision"] == "applied"
    assert ack["body"]["took"] is False
    assert ack["body"]["revert_commit_sha"] == "newshaabc"
    # Verify git revert was actually invoked (not just claimed)
    cmds = [c[0] for c in calls]
    assert any(c[:2] == ("git", "revert") for c in cmds)


def test_revert_failure_still_records(monkeypatch, tmp_path):
    """git revert exit nonzero: we still mark applied + still send the
    follow-up ack so the peer knows what happened, but revert_commit_sha
    stays None."""
    def fake_run(cmd, **kwargs):
        if cmd[0:2] == ["git", "revert"]:
            return _FakeProc(128, "", "fatal: bad revision\n")
        if cmd[0:3] == ["git", "rev-parse", "HEAD"]:
            return _FakeProc(0, "oldshax\n", "")
        return _FakeProc(1, "FAILED\n", "")
    monkeypatch.setattr(subprocess, "run", fake_run)
    rec = _stub_receiver(monkeypatch)
    ack = _stub_bridge(monkeypatch)

    rep = lr.apply_with_revert(
        "lesson-DDD", commit_sha="badsha",
        tests=("tests/x.py",), timeout_s=10.0, cwd=tmp_path,
    )
    assert rep.decision == "applied"
    assert rep.auto_reverted is True
    assert rep.revert_commit_sha is None
    # Follow-up ack still sent
    assert ack["in_reply_to"] == "lesson-DDD"
    assert ack["body"]["auto_reverted"] is True
    assert "revert_commit_sha" not in ack["body"] or ack["body"]["revert_commit_sha"] is None


def test_pytest_timeout_caught(monkeypatch, tmp_path):
    """A pytest TimeoutExpired must not crash the wrapper."""
    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout"),
                                        output="partial out", stderr="")
    monkeypatch.setattr(subprocess, "run", fake_run)
    _stub_receiver(monkeypatch)
    _stub_bridge(monkeypatch)

    rep = lr.apply_with_revert(
        "lesson-EEE", commit_sha=None, tests=("tests/x.py",),
        timeout_s=1.0, cwd=tmp_path,
    )
    assert rep.tests_ok is False
    assert rep.tests_returncode == 124  # timeout sentinel
    assert "timeout" in rep.tests_tail.lower()
    assert rep.decision == "queued"


def test_receiver_lookup_error_caught(monkeypatch, tmp_path):
    """post_decision LookupError (lesson not in bridge) must surface in
    receiver_entry without crashing the apply_with_revert call."""
    _stub_run(monkeypatch, returncode=0)
    rec = _stub_receiver(monkeypatch, raises=LookupError("not found"))
    _stub_bridge(monkeypatch)
    rep = lr.apply_with_revert(
        "lesson-FFF", commit_sha=None, tests=("tests/x.py",),
        timeout_s=1.0, cwd=tmp_path,
    )
    assert rep.decision == "applied"  # tests passed
    assert "not found" in str(rep.receiver_entry)


# ---------------------------------------------------------------------------
# Report shape
# ---------------------------------------------------------------------------

def test_report_to_dict():
    rep = lr.RevertReport(
        lesson_id="L1", decision="applied", auto_reverted=False,
        tests_ok=True, tests_returncode=0, tests_tail="",
        revert_commit_sha=None, receiver_entry={"ok": True},
    )
    d = rep.to_dict()
    assert d["lesson_id"] == "L1"
    assert d["decision"] == "applied"
    assert d["auto_reverted"] is False
    assert d["receiver_entry"] == {"ok": True}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_exit_codes(monkeypatch, capsys, tmp_path):
    _stub_run(monkeypatch, returncode=0)
    _stub_receiver(monkeypatch)
    _stub_bridge(monkeypatch)
    rc = lr._cli(["lesson-CLI-OK"])
    assert rc == 0
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed["decision"] == "applied"
    assert parsed["auto_reverted"] is False


def test_cli_auto_revert_exit_2(monkeypatch, capsys, tmp_path):
    _stub_run(monkeypatch, returncode=1, stdout="FAILED\n")
    _stub_receiver(monkeypatch)
    _stub_bridge(monkeypatch)
    rc = lr._cli(["lesson-CLI-REV", "--commit-sha", "cafef00d"])
    assert rc == 2
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["auto_reverted"] is True


def test_cli_queued_exit_1(monkeypatch, capsys, tmp_path):
    _stub_run(monkeypatch, returncode=1, stdout="FAILED\n")
    _stub_receiver(monkeypatch)
    _stub_bridge(monkeypatch)
    rc = lr._cli(["lesson-CLI-Q"])
    assert rc == 1
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["decision"] == "queued"
