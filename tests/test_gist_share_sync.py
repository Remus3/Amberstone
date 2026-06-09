"""Regression tests for tools/gist_share_sync.py push-failure surfacing.

Incident 2026-06-03 -> 2026-06-09: the gist post-commit hook ran
`git push origin HEAD` under subprocess `check=True`; a non-fast-forward
rejection (remote diverged from a manual gist edit) raised
CalledProcessError that the post-commit context swallowed. 45 regenerated
commits piled up unpushed for 6 days while the published gist sat stale and
nothing surfaced the failure.

These tests pin the hardened contract: a push failure must be VISIBLE -
recorded to ops/runtime/gist_sync_status.json (ok=False + unpushed count),
appended to logs/YYYY-MM-DD.log with git's stderr, echoed to stderr, and the
call must return a non-zero exit code.
"""
from __future__ import annotations

import json
import subprocess
import types

import tools.gist_share_sync as g


def _fake_completed(stdout: str = "") -> types.SimpleNamespace:
    return types.SimpleNamespace(stdout=stdout, stderr="", returncode=0)


def _redirect_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(g, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(g, "STATUS_PATH", tmp_path / "gist_sync_status.json")


def test_push_failure_is_surfaced(tmp_path, monkeypatch, capsys):
    _redirect_paths(tmp_path, monkeypatch)
    rejected = "! [rejected]        HEAD -> main (non-fast-forward)"

    def fake_git(*args):
        if args[0] == "push":
            raise subprocess.CalledProcessError(
                1, ["git", "push"], output="", stderr=rejected
            )
        if args[:2] == ("rev-list", "--count") or args[1:3] == ("rev-list", "--count"):
            return _fake_completed("45\n")
        if args[0] == "rev-list":
            return _fake_completed("45\n")
        return _fake_completed("")

    monkeypatch.setattr(g, "_git", fake_git)

    rc = g._do_push("1.120.0", "16.12.1", 346, "https://gist.github.com/abc.git")

    assert rc == g.PUSH_FAIL_EXIT
    assert rc != 0

    status = json.loads((tmp_path / "gist_sync_status.json").read_text(encoding="utf-8"))
    assert status["ok"] is False
    assert status["unpushed_commits"] == 45
    assert "non-fast-forward" in status["detail"]

    logs = list((tmp_path / "logs").glob("*.log"))
    assert logs, "a log file must be written on push failure"
    log_text = logs[0].read_text(encoding="utf-8")
    assert "non-fast-forward" in log_text
    assert "FAILED" in log_text

    assert "non-fast-forward" in capsys.readouterr().err


def test_push_success_records_ok(tmp_path, monkeypatch):
    _redirect_paths(tmp_path, monkeypatch)

    def fake_git(*args):
        return _fake_completed("")

    monkeypatch.setattr(g, "_git", fake_git)

    rc = g._do_push("1.120.0", "16.12.1", 346, "https://gist.github.com/abc.git")

    assert rc == 0
    status = json.loads((tmp_path / "gist_sync_status.json").read_text(encoding="utf-8"))
    assert status["ok"] is True
    assert status["unpushed_commits"] == 0


def test_unpushed_count_parses_and_is_error_safe(monkeypatch):
    def ok_git(*args):
        if args[0] == "rev-list":
            return _fake_completed("7\n")
        return _fake_completed("")

    monkeypatch.setattr(g, "_git", ok_git)
    assert g._unpushed_count() == 7

    def boom_git(*args):
        raise subprocess.CalledProcessError(128, ["git"], output="", stderr="no upstream")

    monkeypatch.setattr(g, "_git", boom_git)
    assert g._unpushed_count() == 0
