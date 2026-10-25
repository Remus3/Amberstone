"""Kill switch, per spawn path: with the route refused, NO headless `claude` starts.

Companion to `tests/test_headless_env.py` (the helper itself). Each test below
drives one real spawn path with the user variable deleted (the store reads
"absent") and asserts the process seam was never reached, then drives it with a
fake open route and asserts the child env carries the routed URL while the
parent env does not. All values are fakes; no real probe, registry read or
process.

RM-801: every process fake is bound into the spawn chain's OWN `subprocess`
names (`_chain()`, tests/_module_view.py bind_subprocess), never onto the
shared subprocess module that every other thread of the xdist worker calls.
"""
from __future__ import annotations

import contextlib
import importlib.util
import os
import sys
from pathlib import Path
from subprocess import CompletedProcess
from unittest import mock

import pytest

from ops.loop import headless_env as he
from tests._module_view import bind_subprocess, bind_which

ROOT = Path(__file__).resolve().parent.parent
FAKE_URL = "http://127.0.0.1:65534"
_TRIP = "spawned with no route"


def _chain():
    """Every module on this file's spawn paths whose own globals call
    subprocess: the callers (executor ops/loop/executor.py:945/977, ci_watchdog
    tools/ci_watchdog.py:459, drain ops/loop/drain_waves_2_3.py:180, the
    supervisor facade + agents/_supervisor_ephemeral.py), fleet_route (the
    conftest launch forwarder calls fleet_route.subprocess.run) and the kit
    (its launch ops/fleet_kit/fleet_headless.py:1734 Popen, its git probe :1613
    and taskkill :1703 run). A tripwire bound here is as strong for these paths
    as the old process-wide one, and blind to every other thread's module."""
    import agents._supervisor_ephemeral as sup_eph  # noqa: PLC0415
    import agents.supervisor as sup  # noqa: PLC0415
    from ops.loop import fleet_route as fr  # noqa: PLC0415
    return (executor, cw, drain, sup_eph, sup, fr, fr.kit())


def _bind_chain(mp, **fakes):
    for mod in _chain():
        bind_subprocess(mp, mod, **fakes)


@contextlib.contextmanager
def _faked(**fakes):
    """FAKES (run= / Popen=) for the spawn chain only, for the with-block."""
    with pytest.MonkeyPatch.context() as mp:
        _bind_chain(mp, **fakes)
        yield


@contextlib.contextmanager
def _claude_on_path():
    """`claude` resolves to /fake/claude for the supervisor ephemeral path's
    OWN `shutil` names only (RM-880): agents/_supervisor_ephemeral.py calls
    shutil.which(CLAUDE_CLI); its facade agents.supervisor keeps `import
    shutil`. The shared shutil module another thread calls stays real."""
    import agents._supervisor_ephemeral as sup_eph  # noqa: PLC0415
    import agents.supervisor as sup  # noqa: PLC0415
    with pytest.MonkeyPatch.context() as mp:
        for mod in (sup_eph, sup):
            bind_which(mp, mod, lambda *_a, **_k: "/fake/claude")
        yield


def _trip():
    return mock.MagicMock(side_effect=AssertionError(_TRIP))


@pytest.fixture
def refused(monkeypatch, tmp_path):
    monkeypatch.setattr(he, "_read_user_var", lambda name: None)  # var deleted
    monkeypatch.setattr(he, "_probe", lambda h, p, t: pytest.fail("probe on an unset var"))
    monkeypatch.setattr(he, "REFUSAL_LOG", tmp_path / "refusals.log")
    # A stale inherited copy in the parent must NOT revive the route.
    monkeypatch.setenv(he.ENV_VAR, FAKE_URL)
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    return tmp_path / "refusals.log"


@pytest.fixture
def routed(monkeypatch, tmp_path):
    monkeypatch.setattr(he, "_read_user_var", lambda name: FAKE_URL)
    monkeypatch.setattr(he, "_probe", lambda h, p, t: None)
    monkeypatch.setattr(he, "REFUSAL_LOG", tmp_path / "refusals.log")
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# ops/loop/executor.py - the sdk channel
# ---------------------------------------------------------------------------

executor = _load("rc_loop_executor_route_test", "ops/loop/executor.py")


def _sdk(tmp_path):
    cfg = {"channel": "sdk", "repo_root": str(tmp_path), "cycle_deadline_sec": 60,
           "executor_cmd": "claude"}
    return executor.build(cfg, tmp_path, log=lambda m: None, stop=lambda m: None,
                          awrite=lambda p, t: None)


_SDK_DONE = ('{"is_error": false, "structured_output": {"sha": "a", '
             '"tests_pass": "1", "regressions": false, "summary": "s"}}')


def test_executor_refuses_without_route(refused, tmp_path, monkeypatch):
    monkeypatch.setattr(executor, "_git_head", lambda root: "")
    with _faked(run=_trip(), Popen=_trip()):
        rec = _sdk(tmp_path).run(1, "b", "fixed")
    assert rec.error == "headless route refused: unset"
    assert '"reason": "unset"' in refused.read_text(encoding="utf-8")


def test_executor_child_env_carries_route(routed, tmp_path, monkeypatch):
    monkeypatch.setattr(executor, "_git_head", lambda root: "")
    run = mock.MagicMock(return_value=_done(_SDK_DONE))
    with _faked(run=run):
        rec = _sdk(tmp_path).run(1, "b", "fixed")
    assert rec.error is None
    env = run.call_args.kwargs["env"]
    assert env["ANTHROPIC_BASE_URL"] == FAKE_URL
    # kit v10 child_env: a headless run is exempt from the SUBAGENT-FIRST hook
    assert env["FLEET_SUBAGENT_FIRST"] == "off"
    parent_has_base_url = "ANTHROPIC_BASE_URL" in os.environ
    assert parent_has_base_url is False


# ---------------------------------------------------------------------------
# ops/loop/adjudicator.py
# ---------------------------------------------------------------------------

adjudicator = _load("rc_loop_adjudicator_route_test", "ops/loop/adjudicator.py")
_ADJ_CFG = {"claude_adjudicator": {"cmd": "claude.cmd", "model": "opus"}}


def _done(stdout='{"result": "ok"}', rc=0, stderr=""):
    return CompletedProcess(args=["claude"], returncode=rc, stdout=stdout, stderr=stderr)


def test_adjudicator_refuses_without_route(refused, tmp_path):
    with _faked(run=_trip()):
        adj = adjudicator.ClaudeAdjudicator(_ADJ_CFG, tmp_path)
        assert adj.ask("b", "i") is None
    assert "unset" in adj.last_stderr


def test_adjudicator_child_env_carries_route(routed, tmp_path):
    run = mock.MagicMock(return_value=_done())
    with _faked(run=run):
        assert adjudicator.ClaudeAdjudicator(_ADJ_CFG, tmp_path).ask("b", "i") == "ok"
    assert run.call_args.kwargs["env"]["ANTHROPIC_BASE_URL"] == FAKE_URL


# ---------------------------------------------------------------------------
# tools/ci_watchdog.py - the default runner's claude_fix step
# ---------------------------------------------------------------------------

from tools import ci_watchdog as cw  # noqa: E402


def _fake_run_factory(calls, diff=""):
    def _fake_run(cmd, cwd=None, timeout=120, env=None):
        calls.append((list(cmd), env))
        if "diff" in cmd and "--name-only" in cmd:
            return 0, diff
        return 0, ""
    return _fake_run


def test_ci_watchdog_refuses_claude_fix_without_route(refused, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(cw, "_run", _fake_run_factory(calls))
    monkeypatch.setattr(cw, "_write_context", lambda *a, **k: None)
    with _faked(run=_trip()):
        res = cw.execute_dispatch(1, "h" * 12, arm=True, worktree=tmp_path)
    assert res["action"] == "error" and res["stage"] == "claude_fix_route"
    assert not any(c[0] and c[0][0] == "claude" for c in calls)


def test_ci_watchdog_claude_fix_env_carries_route(routed, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(cw, "_run", _fake_run_factory(calls))
    monkeypatch.setattr(cw, "_write_context", lambda *a, **k: None)
    run = mock.MagicMock(return_value=_done('{"result": "fixed"}'))
    with _faked(run=run):
        cw.execute_dispatch(1, "h" * 12, arm=True, worktree=tmp_path)
    assert run.call_count == 1, "exactly one process: the kit's claude_fix run"
    kw = run.call_args.kwargs
    assert kw["env"]["ANTHROPIC_BASE_URL"] == FAKE_URL
    # the child runs in the throwaway worktree, not in the kit's root
    assert kw["cwd"] == str(tmp_path)
    # no claude step went through the generic git/gh runner, and every
    # git/gh step keeps the inherited env
    assert not any(c[0] and c[0][0] == "claude" for c in calls)
    assert all(env is None for _cmd, env in calls)


# ---------------------------------------------------------------------------
# agents/_supervisor_ephemeral.py
# ---------------------------------------------------------------------------


def test_ephemeral_refuses_without_route(refused):
    from agents.supervisor import EphemeralSpawnFailed, spawn_ephemeral_llm
    with _claude_on_path(), \
         _faked(run=_trip()):
        with pytest.raises(EphemeralSpawnFailed) as ei:
            spawn_ephemeral_llm("6", "t-route-refused", "demo", {})
    assert "headless route refused" in str(ei.value)


def test_ephemeral_child_env_carries_route(routed):
    from agents.supervisor import spawn_ephemeral_llm
    proc = CompletedProcess(args=["claude"], returncode=0, stdout='{"result":"x"}', stderr="")
    run = mock.MagicMock(return_value=proc)
    with _claude_on_path(), \
         _faked(run=run):
        spawn_ephemeral_llm("6", "t-route-ok", "demo", {})
    assert run.call_args.kwargs["env"]["ANTHROPIC_BASE_URL"] == FAKE_URL


# ---------------------------------------------------------------------------
# tools/inbox_responder_spawn.py - real_spawner
# ---------------------------------------------------------------------------

from tools import inbox_responder_spawn as irs  # noqa: E402


def _request(tmp_path):
    return irs.SpawnRequest(argv=["x"], stdin_bytes=b"", env={"PATH": "p"},
                            cwd=tmp_path, timeout_s=1, kill_budget=irs.procs.KillBudget())


def test_responder_refuses_without_route(refused, tmp_path, monkeypatch):
    monkeypatch.setattr(irs.procs, "popen_capture",
                        lambda *a, **k: pytest.fail("popen reached with no route"))
    res = irs.real_spawner(_request(tmp_path))
    assert res.exc == "HeadlessRouteRefused"
    assert irs.spawn_ok(res) == ("exc:HeadlessRouteRefused", None)


def test_responder_child_env_carries_route(routed, tmp_path, monkeypatch):
    seen = {}

    def _capture(argv, **kw):
        seen.update(kw)
        return mock.Mock(exit_code=0, stdout=b"", stderr=b"", exc=None, wall_ms=1,
                         timed_out=False, survived_kill=False, kill_skipped=False)

    monkeypatch.setattr(irs.procs, "popen_capture", _capture)
    req = _request(tmp_path)
    irs.real_spawner(req)
    assert seen["env"]["ANTHROPIC_BASE_URL"] == FAKE_URL
    assert "ANTHROPIC_BASE_URL" not in req.env


# ---------------------------------------------------------------------------
# FLEET-KIT-v1: every routed path provably calls the kit's spawn
#
# `fleet_route._kit_spawn` replaces `fleet_headless.spawn` with a recorder, so
# these prove the CALL (code RC, the per-path writes_code / bare / note, the
# RC flags as extras, stdin for the body) without starting anything. The kit's
# own behaviour is the kit's business; tests/test_fleet_route.py covers the
# adapter around it.
# ---------------------------------------------------------------------------

from ops.loop import fleet_route  # noqa: E402
from tests import _kit_platform  # noqa: E402
from tests._kit_platform import assert_kit_killed  # noqa: E402

kit_platform = _kit_platform.kit_platform  # fixture, registered by module attribute


@pytest.fixture
def kit_calls(routed, monkeypatch):
    calls = []

    def _fake(root, code, prompt, **kw):
        calls.append({"root": root, "code": code, "prompt": prompt, **kw})
        proc = kw["run"](["claude-fake.exe", "-p", prompt], cwd=str(root), env={},
                         capture_output=True, text=True, timeout=kw["timeout"],
                         creationflags=0)
        return {"rc": proc.returncode, "result": None, "model": "sonnet"}

    monkeypatch.setattr(fleet_route, "_kit_spawn", _fake)
    return calls


def test_kit_call_adjudicator(kit_calls, tmp_path):
    run = mock.MagicMock(return_value=_done('{"result": "go"}'))
    with _faked(run=run):
        assert adjudicator.ClaudeAdjudicator(_ADJ_CFG, tmp_path).ask("BODY", "INST") == "go"
    (c,) = kit_calls
    assert c["code"] == "RC" and c["prompt"] == "INST"
    assert c["writes_code"] is False and c["bare"] is False
    assert list(c["extra"]) == ["--permission-mode", "plan"]
    assert run.call_args.kwargs["input"] == "BODY"


def test_kit_call_ci_watchdog(kit_calls, tmp_path, monkeypatch):
    monkeypatch.setattr(cw, "_run", _fake_run_factory([]))
    monkeypatch.setattr(cw, "_write_context", lambda *a, **k: None)
    run = mock.MagicMock(return_value=_done())
    with _faked(run=run):
        cw.execute_dispatch(1, "h" * 12, arm=True, worktree=tmp_path)
    assert run.called, "the kit's launch reached the chain's fake"
    (c,) = kit_calls
    assert c["code"] == "RC" and c["writes_code"] is True and c["bare"] is False
    extra = list(c["extra"])
    assert "--append-system-prompt-file" in extra and "--allowedTools" in extra
    assert "--output-format" not in extra, "the kit owns --output-format"
    assert "--dangerously-skip-permissions" not in extra


def test_kit_call_supervisor_ephemeral(kit_calls):
    from agents.supervisor import spawn_ephemeral_llm
    run = mock.MagicMock(return_value=_done('{"result":"x"}'))
    with _claude_on_path(), \
         _faked(run=run):
        spawn_ephemeral_llm("6", "t-kit-call", "demo", {})
    (c,) = kit_calls
    assert c["code"] == "RC" and c["bare"] is False
    assert c["writes_code"] is True, "agent 6 runs opus, i.e. writes code"
    assert "--max-budget-usd" in list(c["extra"])
    assert "--model" not in list(c["extra"]), "the kit owns the model pick"
    assert "t-kit-call" in run.call_args.kwargs["input"]


# ops/loop/drain_waves_2_3.py - `_spawn`, the drain launcher's one claude door.
# It loads fleet_route by path under its own module name; seeding that name
# with the imported module puts the test fixtures' patches in its path.

drain = _load("rc_drain_waves_route_test", "ops/loop/drain_waves_2_3.py")


@pytest.fixture
def drain_dirs(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "rc_ops_loop_fleet_route", fleet_route)
    monkeypatch.setattr(drain, "DRAIN_DIR", tmp_path / "drain")
    monkeypatch.setattr(drain, "STOP_FILE", tmp_path / "DRAIN_STOP")
    monkeypatch.setattr(drain, "LOG", tmp_path / "drain.log")
    return tmp_path


def test_drain_refuses_without_route(refused, drain_dirs):
    with _faked(run=_trip(), Popen=_trip()):
        res = drain._spawn("P", task="t-refused", extra=(), cwd=drain_dirs, timeout=5)
    assert res["rc"] is None and res["error"].startswith("refused:")


def test_kit_call_drain_waves(kit_calls, drain_dirs):
    with _faked(run=mock.MagicMock(return_value=_done('{"result":"x"}'))):
        res = drain._spawn("PROMPT", task="t-kit", extra=drain.VERIFY_EXTRA,
                           cwd=drain_dirs, timeout=5)
    (c,) = kit_calls
    assert c["code"] == "RC" and c["writes_code"] is True and c["bare"] is False
    assert list(c["extra"]) == list(drain.VERIFY_EXTRA)
    assert res["rc"] == 0
    assert (drain_dirs / "drain" / "t-kit.out.txt").is_file()


class _HangPopen:
    """The kit's `_run` sees a child that never answers: communicate times out
    once, then the reap after the tree kill returns."""

    made: list = []

    def __init__(self, argv, stdin=None, **kw):
        self.argv, self.pid, self.returncode, self.n = list(argv), 777, None, 0
        self.killed = False
        _HangPopen.made.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def communicate(self, input=None, timeout=None):
        self.n += 1
        if self.n == 1:
            import subprocess as _sp
            raise _sp.TimeoutExpired(self.argv, timeout)
        self.returncode = 1
        return ("", "")

    def wait(self, timeout=None):
        # kit v10 POSIX tree-kill waits on the child between SIGTERM and SIGKILL
        return self.returncode

    def kill(self):
        self.killed = True


@pytest.fixture
def kit_hang(routed, kit_platform, monkeypatch):
    """REAL kit spawn + the kit's own `_run`; only Popen and taskkill faked.
    Runs once per kit kill branch (win32 taskkill /T, POSIX group kill) via
    `kit_platform`, so the ubuntu CI and Legion both cover both branches."""
    monkeypatch.setattr(fleet_route, "_launch", None)
    _HangPopen.made = []
    kills = []
    _bind_chain(monkeypatch, Popen=_HangPopen,
                run=lambda argv, **kw: kills.append(list(argv)) or
                CompletedProcess(args=argv, returncode=0, stdout="", stderr=""))
    return kit_platform, kills


def _assert_tree_killed(hang):
    plat, kills = hang
    (p,) = _HangPopen.made
    assert p.argv[1] == "-p", "started by the kit's argv builder"
    assert_kit_killed(plat, kills, p.killed, 777)


def test_adjudicator_timeout_kills_tree_via_kit(kit_hang, tmp_path):
    assert adjudicator.ClaudeAdjudicator(_ADJ_CFG, tmp_path).ask("BODY", "INST") is None
    _assert_tree_killed(kit_hang)


def test_ci_watchdog_timeout_kills_tree_via_kit(kit_hang, tmp_path, monkeypatch):
    monkeypatch.setattr(cw, "_run", _fake_run_factory([]))
    monkeypatch.setattr(cw, "_write_context", lambda *a, **k: None)
    cw.execute_dispatch(1, "h" * 12, arm=True, worktree=tmp_path)
    _assert_tree_killed(kit_hang)


def test_supervisor_ephemeral_timeout_kills_tree_via_kit(kit_hang):
    from agents.supervisor import EphemeralSpawnFailed, spawn_ephemeral_llm
    with _claude_on_path():
        with pytest.raises(EphemeralSpawnFailed) as ei:
            spawn_ephemeral_llm("6", "t-kit-hang", "demo", {})
    assert "timed out" in str(ei.value)
    _assert_tree_killed(kit_hang)


# ops/loop/executor.py - the loop controller's sdk channel (MAIN 0839 ORDER,
# kit v10 step 5): kit spawn with the operator's effort as effort=, the whole
# prompt on stdin, and the session flag as the kit's session_id= / resume=.


def test_kit_call_executor(kit_calls, tmp_path, monkeypatch):
    monkeypatch.setattr(executor, "_git_head", lambda root: "")
    ex = executor.build({"channel": "sdk", "repo_root": str(tmp_path),
                         "cycle_deadline_sec": 60, "executor_effort": "high",
                         "executor_model": "claude-opus-5-5"}, tmp_path,
                        log=lambda m: None, stop=lambda m: None, awrite=lambda p, t: None)
    with _faked(run=mock.MagicMock(return_value=_done(_SDK_DONE))):
        rec = ex.run(1, "BODY", "fixed")
    assert rec.error is None
    (c,) = kit_calls
    assert c["code"] == "RC" and c["writes_code"] is True and c["bare"] is False
    assert c["effort"] == "high" and c["model"] == "claude-opus-5-5"
    assert c["stdin"] is True and "BODY" in c["prompt"]
    assert c["kind"] == "build" and c["session_id"] and "resume" not in c
    extra = list(c["extra"])
    for owned in ("--effort", "--model", "--output-format", "--strict-mcp-config",
                  "--setting-sources", "--session-id", "--resume", "-p"):
        assert owned not in extra, f"the kit owns {owned}"
    assert "--json-schema" in extra and "--permission-mode" in extra


def test_executor_timeout_kills_tree_via_kit(kit_hang, tmp_path, monkeypatch):
    monkeypatch.setattr(executor, "_git_head", lambda root: "")
    rec = _sdk(tmp_path).run(1, "b", "fixed")
    assert "timeout" in rec.error
    _assert_tree_killed(kit_hang)


def test_kit_call_supervisor_non_opus_agent_does_not_write_code(kit_calls):
    from agents.supervisor import spawn_ephemeral_llm
    run = mock.MagicMock(return_value=_done('{"result":"x"}'))
    with _claude_on_path(), \
         _faked(run=run):
        spawn_ephemeral_llm("7", "t-kit-call-7", "demo", {})
    assert run.called, "the kit's launch reached the chain's fake"
    (c,) = kit_calls
    assert c["writes_code"] is False
