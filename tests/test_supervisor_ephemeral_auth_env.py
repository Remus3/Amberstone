"""Regression tests for the ephemeral `claude` spawn's auth environment.

MEASURED ROOT CAUSE (2026-09-29): `ANTHROPIC_API_KEY` is set machine-wide
on Legion. `RC-Phase3-Supervisor` runs `pythonw -m agents.supervisor` and
inherits it; `spawn_ephemeral_llm` called `subprocess.run(...)` with no
`env=` argument, so the spawned `claude -p` child inherited it too. That
key is org-scoped, not workspace-scoped, and it takes PRECEDENCE over the
machine's Claude subscription login, so every Agent-6 dispatch since
2026-08-02 died exit 1 with one of two signatures:

  - "This API key is not scoped to a workspace ..."
  - "claude.ai connectors are disabled because ANTHROPIC_API_KEY or
     another auth source is set and takes precedence over your claude.ai
     login"

The fix is scoped to the SPAWN ONLY: an explicit env dict with the
overriding variables removed. RC's coaches keep reading the key from the
supervisor's own `os.environ` for direct Anthropic API calls, so the
parent environment must be left exactly as it was.

Every subprocess here is a FAKE. Nothing in this module invokes the real
`claude` CLI, spawns a real ephemeral agent, or touches the live
supervisor.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

import pytest

from agents._supervisor_common import LOG_ROOT
from agents.supervisor import EphemeralSpawnFailed, spawn_ephemeral_llm

# Agent 7 (haiku) has a real charter on disk and, unlike agent 6, does not
# write a failure stub - so the failure-path tests leave no artifact behind.
_AGENT = "7"

_SIG_WORKSPACE = (
    "API Error: 400 This API key is not scoped to a workspace, so this "
    "request must include the anthropic-workspace-id header with the ID "
    "of the workspace to use."
)
_SIG_CONNECTORS = (
    "claude.ai connectors are disabled because ANTHROPIC_API_KEY or "
    "another auth source is set and takes precedence over your claude.ai "
    "login - Unset it to load your organization's connectors"
)
_SIG_OAUTH = "Failed to authenticate: OAuth session expired and could not be refreshed"


class _Recorder:
    """Stand-in for ``subprocess.run`` that records the kwargs it was given."""

    def __init__(self, returncode: int = 0, stdout: str = "{}", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.kwargs: dict = {}
        self.calls = 0

    def __call__(self, cmd, **kwargs):
        self.calls += 1
        self.kwargs = kwargs
        return CompletedProcess(
            args=cmd, returncode=self.returncode,
            stdout=self.stdout, stderr=self.stderr,
        )


def _run(rec: _Recorder, task_id: str, agent: str = _AGENT):
    with patch("agents.supervisor.shutil.which", return_value="/fake/claude"), \
         patch("agents.supervisor.subprocess.run", rec):
        return spawn_ephemeral_llm(agent, task_id, "demo", {})


def _task_log(task_id: str) -> Path:
    return LOG_ROOT / f"task-{task_id}.log"


# `tests/test_no_environ_in_assert_operands.py` forbids an assertion operand
# that would render the whole process environment - keys AND values, so every
# secret on the box - into a failure message. The two helpers below do the
# comparison here and hand back key NAMES only, so the assertions stay just as
# strong while staying safe to fail in a public CI log.

def _environ_key_drift(baseline: dict[str, str]) -> list[str]:
    """Names of keys whose presence or value differs from ``baseline``."""
    now = dict(os.environ)
    return sorted(k for k in set(baseline) | set(now)
                  if baseline.get(k) != now.get(k))


def _spawn_env_key_diff(
    spawn_env: dict[str, str], stripped: set[str],
) -> tuple[list[str], list[str]]:
    """``(dropped, leaked)`` key names for a spawn env against the parent.

    ``dropped`` are inheritable parent keys missing from the spawn env.
    ``leaked`` are keys the spawn env carries that the parent would not pass
    through - a stripped auth override that survived, or a key the spawn
    invented. Both empty is exactly ``set(spawn_env) == inheritable``, so this
    pair is as strong as the set equality it replaced.
    """
    inheritable = {k for k in os.environ if k.upper() not in stripped}
    dropped = sorted(inheritable - set(spawn_env))
    leaked = sorted(set(spawn_env) - inheritable)
    return dropped, leaked


# --------------------------------------------------------------------------
# env construction
# --------------------------------------------------------------------------

def test_spawn_env_omits_anthropic_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """The key is present in the parent env and ABSENT from the spawn env."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-testkeytestkeytestkey0001")
    rec = _Recorder()
    _run(rec, "t-authenv-strip")
    env = rec.kwargs.get("env")
    assert env is not None, "subprocess.run was called with no env= argument"
    assert "ANTHROPIC_API_KEY" not in env
    # Removed, not blanked - an empty string can still read as "configured".
    assert not any(k.upper() == "ANTHROPIC_API_KEY" for k in env)


def test_spawn_env_omits_auth_token_and_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """The other two variables that override the subscription login go too."""
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok-testtesttesttesttest0001")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://example.invalid/v1")
    rec = _Recorder()
    _run(rec, "t-authenv-strip2")
    env = rec.kwargs["env"]
    assert "ANTHROPIC_AUTH_TOKEN" not in env
    assert "ANTHROPIC_BASE_URL" not in env


def test_parent_environ_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """The supervisor's own env keeps the key - RC coaches still need it."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-testkeytestkeytestkey0002")
    baseline = dict(os.environ)
    rec = _Recorder()
    _run(rec, "t-authenv-parent")
    key_after = os.environ.get("ANTHROPIC_API_KEY")
    assert key_after == "sk-ant-testkeytestkeytestkey0002"
    drifted = _environ_key_drift(baseline)
    assert not drifted, f"the spawn mutated parent environment keys: {drifted}"


def test_rest_of_environment_passes_through(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the auth overrides are dropped; everything else is inherited."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-testkeytestkeytestkey0003")
    monkeypatch.setenv("RC_AUTHENV_PROBE", "kept-value")
    rec = _Recorder()
    _run(rec, "t-authenv-passthru")
    env = rec.kwargs["env"]
    assert env.get("RC_AUTHENV_PROBE") == "kept-value"
    stripped = {"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"}
    dropped, leaked = _spawn_env_key_diff(env, stripped)
    assert not dropped, f"inheritable parent keys missing from the spawn env: {dropped}"
    assert not leaked, f"auth overrides survived into the spawn env: {leaked}"


def test_spawn_env_has_no_none_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """subprocess on Windows rejects None values in the env mapping."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-testkeytestkeytestkey0004")
    rec = _Recorder()
    _run(rec, "t-authenv-nonone")
    env = rec.kwargs["env"]
    assert all(isinstance(k, str) for k in env)
    assert all(isinstance(v, str) for v in env.values())


# --------------------------------------------------------------------------
# legibility of the three auth failure signatures
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "task_id,stream,text,needle",
    [
        ("t-authenv-sig-ws-err", "stderr", _SIG_WORKSPACE, "workspace-scoped"),
        ("t-authenv-sig-ws-out", "stdout", _SIG_WORKSPACE, "workspace-scoped"),
        ("t-authenv-sig-conn", "stderr", _SIG_CONNECTORS, "overriding the Claude subscription"),
        ("t-authenv-sig-oauth", "stderr", _SIG_OAUTH, "OAuth session on this host is expired"),
    ],
)
def test_auth_signature_produces_a_named_cause(
    task_id: str, stream: str, text: str, needle: str
) -> None:
    """A dead spawn must name the actual cause, not just say `exit 1`."""
    rec = _Recorder(returncode=1, stdout="", stderr="")
    setattr(rec, stream, text)
    with pytest.raises(EphemeralSpawnFailed) as ei:
        _run(rec, task_id)
    msg = str(ei.value)
    # Existing message shape preserved ...
    assert msg.startswith(f"claude exit 1 for task {task_id}:")
    # ... plus the named cause.
    assert "AUTH-CAUSE" in msg
    assert needle in msg
    assert needle in _task_log(task_id).read_text(encoding="utf-8")


def test_non_auth_failure_has_no_auth_cause() -> None:
    """An ordinary failure must not be mislabelled as an auth problem."""
    rec = _Recorder(returncode=2, stdout="", stderr="intentional test failure")
    with pytest.raises(EphemeralSpawnFailed) as ei:
        _run(rec, "t-authenv-plainfail")
    msg = str(ei.value)
    assert msg.startswith("claude exit 2 for task t-authenv-plainfail:")
    assert "AUTH-CAUSE" not in msg


# --------------------------------------------------------------------------
# preserved behaviour
# --------------------------------------------------------------------------

def test_secrets_still_redacted_in_log_and_exception() -> None:
    """Redaction of child output survives the auth-legibility change."""
    leak = "ANTHROPIC_API_KEY=sk-ant-leakleakleakleakleak0001 " + _SIG_WORKSPACE
    rec = _Recorder(returncode=1, stdout=leak, stderr=leak)
    with pytest.raises(EphemeralSpawnFailed) as ei:
        _run(rec, "t-authenv-redact")
    msg = str(ei.value)
    assert "sk-ant-leakleakleakleakleak0001" not in msg
    assert "[REDACTED-SECRET]" in msg
    body = _task_log("t-authenv-redact").read_text(encoding="utf-8")
    assert "sk-ant-leakleakleakleakleak0001" not in body
    assert "[REDACTED-SECRET]" in body


def test_agent6_failure_stub_still_written() -> None:
    """The agent-6 stub call is preserved (patched - no artifact is written)."""
    rec = _Recorder(returncode=1, stdout="", stderr=_SIG_OAUTH)
    with patch("agents.supervisor.shutil.which", return_value="/fake/claude"), \
         patch("agents.supervisor.subprocess.run", rec), \
         patch("agents._supervisor_ephemeral._write_agent6_failure_stub") as stub:
        with pytest.raises(EphemeralSpawnFailed):
            spawn_ephemeral_llm("6", "t-authenv-stub", "demo", {})
    assert stub.call_count == 1


def test_happy_path_envelope_and_timeout_preserved(monkeypatch: pytest.MonkeyPatch) -> None:
    """JSON envelope parsing and TimeoutExpired handling are untouched."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-testkeytestkeytestkey0005")
    rec = _Recorder(returncode=0, stdout='{"ok": "yes"}')
    out = _run(rec, "t-authenv-ok")
    assert out["ok"] is True
    assert out["result"] == {"ok": "yes"}

    def _boom(cmd, **kwargs):
        assert "ANTHROPIC_API_KEY" not in kwargs["env"]
        raise subprocess.TimeoutExpired(cmd, 900)

    with patch("agents.supervisor.shutil.which", return_value="/fake/claude"), \
         patch("agents.supervisor.subprocess.run", _boom):
        with pytest.raises(EphemeralSpawnFailed) as ei:
            spawn_ephemeral_llm(_AGENT, "t-authenv-timeout", "demo", {})
    assert "timed out" in str(ei.value)
