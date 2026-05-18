"""Tests for the ephemeral-LLM dispatch path.

Pre-2026-04-22: stub always raised EphemeralStubNotWired so tasks
would fail() rather than silently complete (audit H3).

Post-2026-04-22: real claude subprocess spawn. EphemeralStubNotWired is
now only raised when the CLI is missing from PATH or the agent has no
model mapping. EphemeralSpawnFailed signals a subprocess-level failure.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from agents.supervisor import (
    AGENT_MODELS,
    EphemeralSpawnFailed,
    EphemeralStubNotWired,
    spawn_ephemeral_llm,
)


def test_unknown_agent_raises_stub_not_wired() -> None:
    with pytest.raises(EphemeralStubNotWired) as ei:
        spawn_ephemeral_llm("99", "t-fake", "demo", {})
    assert "no model mapping" in str(ei.value)


def test_missing_cli_raises_stub_not_wired() -> None:
    with patch("agents.supervisor.shutil.which", return_value=None):
        with pytest.raises(EphemeralStubNotWired) as ei:
            spawn_ephemeral_llm("6", "t-fake", "demo", {})
        assert "not found on PATH" in str(ei.value)


def test_nonzero_exit_raises_spawn_failed() -> None:
    """Simulate a claude subprocess that exits non-zero - the wrapper
    must raise EphemeralSpawnFailed (dispatcher routes to fail())."""
    from subprocess import CompletedProcess
    fake_proc = CompletedProcess(
        args=["claude"], returncode=2,
        stdout="", stderr="intentional test failure",
    )
    with patch("agents.supervisor.shutil.which", return_value="/fake/claude"), \
         patch("agents.supervisor.subprocess.run", return_value=fake_proc):
        with pytest.raises(EphemeralSpawnFailed) as ei:
            spawn_ephemeral_llm("6", "t-exitfail", "demo", {})
    assert "exit 2" in str(ei.value)


def test_zero_exit_returns_ephemeral_result() -> None:
    """Happy path - exit 0 with valid JSON stdout → normal result dict."""
    from subprocess import CompletedProcess
    fake_proc = CompletedProcess(
        args=["claude"], returncode=0,
        stdout='{"type":"result","subtype":"success","result":"done"}',
        stderr="",
    )
    with patch("agents.supervisor.shutil.which", return_value="/fake/claude"), \
         patch("agents.supervisor.subprocess.run", return_value=fake_proc):
        r = spawn_ephemeral_llm("6", "t-happy", "demo", {})
    assert r["ok"] is True
    assert r["substrate"] == "ephemeral_claude_cli"
    assert r["model"] == AGENT_MODELS["6"]
    assert r["result"]["result"] == "done"


def test_non_json_stdout_falls_back_to_raw() -> None:
    from subprocess import CompletedProcess
    fake_proc = CompletedProcess(
        args=["claude"], returncode=0,
        stdout="plain text output",
        stderr="",
    )
    with patch("agents.supervisor.shutil.which", return_value="/fake/claude"), \
         patch("agents.supervisor.subprocess.run", return_value=fake_proc):
        r = spawn_ephemeral_llm("6", "t-raw", "demo", {})
    assert r["result"]["raw_stdout"] == "plain text output"
