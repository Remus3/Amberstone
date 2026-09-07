"""F1 P1+P2: the executor seam (ops/loop/executor.py).

The ahk channel is a REFACTOR ONLY, so the tests that matter most here are the
byte-equality ones: directive_payload must produce exactly what the controller
used to inline, because the AHK bridge skips line 1 and types line 2 as a slash
command. A shape change there does not crash - it silently types `/clear` as
prose, which is a scar this channel already carries.

The sdk channel is new behavior, so it is tested against a stub `claude` that
prints a real result envelope on stdout.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

_spec = importlib.util.spec_from_file_location(
    "rc_loop_executor_under_test", ROOT / "ops" / "loop" / "executor.py")
executor = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = executor
_spec.loader.exec_module(executor)


# ---- byte-equality with the pre-seam inline strings -------------------------

def test_director_payload_is_byte_identical_to_the_inline_original():
    """The typed payload is pinned byte-for-byte, deliberately blunt.

    The command name changed on 2026-08-01 (`/gemini-headless-upgrade` ->
    `/directed-headless-upgrade`) when the second vendor was decommissioned and
    the command stopped being named after it. This pin caught that, which is
    exactly its job: the payload is TYPED into a live session, so a drifted
    string is a directive that silently does nothing.

    Updating the expected value here is only correct alongside the matching
    rename of the command doc itself - `tools/directed-headless-upgrade.md` and
    the gitignored `.claude/commands/` mirror. If this test fails and that file
    does not exist under the name below, the payload is wrong, not the pin.
    """
    assert executor.directive_payload(3, "ignored body", "director") == (
        "CYCLE=3\n/clear\n"
        "/directed-headless-upgrade and Read the file ops/loop/control/directive.md and fully execute it now. "
        "No questions; auto-pick the recommended option and proceed."
    )
    assert (ROOT / "tools" / "directed-headless-upgrade.md").is_file(), \
        "the payload types a command whose doc does not exist - the loop would no-op"


def test_cycle_command_and_fixed_type_the_body_verbatim():
    assert executor.directive_payload(1, "/RC2-Continue", "cycle_command") == \
        "CYCLE=1\n/clear\n/RC2-Continue"
    assert executor.directive_payload(9, "noop", "fixed") == "CYCLE=9\n/clear\nnoop"


def test_clear_each_cycle_false_drops_the_clear_line_only():
    assert executor.directive_payload(2, "x", "fixed", clear_each_cycle=False) == \
        "CYCLE=2\nx"


def test_cycle_header_is_always_the_first_line():
    """The AHK bridge skips line 1; a body on line 1 would never be typed."""
    for src in ("director", "cycle_command", "fixed"):
        assert executor.directive_payload(7, "b", src).splitlines()[0] == "CYCLE=7"


# ---- channel dispatch -------------------------------------------------------

def _deps():
    return dict(log=lambda m: None, stop=lambda m: None, awrite=lambda p, t: None,
                wait_for=lambda *a, **k: True, wait_gone=lambda *a, **k: True,
                rjson=lambda p, d=None: d, stall_action=lambda n: "stop",
                stall_recovery_directive=lambda c: "")


def test_build_defaults_to_ahk(tmp_path: Path):
    assert executor.build({}, tmp_path, **_deps()).name == "ahk"


def test_build_selects_sdk(tmp_path: Path):
    assert executor.build({"channel": "sdk"}, tmp_path, **_deps()).name == "sdk"


def test_unknown_channel_fails_loud_rather_than_falling_back(tmp_path: Path):
    """A typo must not quietly run the singleton channel during a concurrent run."""
    with pytest.raises(ValueError, match="unknown executor channel"):
        executor.build({"channel": "skd"}, tmp_path, **_deps())


# ---- ahk channel ------------------------------------------------------------

class _Rec:
    """Minimal controller-shaped dependency recorder."""

    def __init__(self, ctl: Path, done: dict):
        self.ctl = ctl
        self.done = done
        self.written: dict = {}
        self.logs: list = []
        self.stopped: list = []

    def deps(self):
        return dict(
            log=self.logs.append,
            stop=self.stopped.append,
            awrite=lambda p, t: self.written.__setitem__(Path(p).name, t),
            wait_for=lambda p, d, watch_bridge=False: True,
            wait_gone=lambda p, d: True,
            rjson=lambda p, d=None: self.done,
            stall_action=lambda n: "stop",
            stall_recovery_directive=lambda c: f"recover {c}")


def test_ahk_run_writes_the_payload_and_maps_the_done_record(tmp_path: Path):
    r = _Rec(tmp_path, {"sha": "a" * 40, "tests_pass": "13061",
                        "regressions": False, "summary": "ok"})
    ex = executor.build({"channel": "ahk", "cycle_deadline_sec": 5}, tmp_path, **r.deps())
    rec = ex.run(4, "body", "fixed")
    assert r.written["gemini.ready"] == "CYCLE=4\n/clear\nbody"
    assert rec.sha == "a" * 40
    assert rec.tests_pass == "13061"
    assert rec.regressions is False
    assert rec.raw == r.done
    # the ahk channel returns no receipt - this is why the controller still scrapes
    assert rec.cost_usd == 0.0 and rec.session_id is None


def test_ahk_stops_when_the_bridge_never_types(tmp_path: Path):
    r = _Rec(tmp_path, {})
    deps = r.deps()
    deps["wait_gone"] = lambda p, d: False
    ex = executor.build({"channel": "ahk", "cycle_deadline_sec": 5}, tmp_path, **deps)
    ex.run(2, "body", "fixed")
    assert r.stopped and "never typed" in r.stopped[0]


def test_ahk_passes_watch_bridge_to_the_done_wait(tmp_path: Path):
    """RC-specific: the deadline wait watches the AHK heartbeat, LW's does not."""
    seen = {}
    r = _Rec(tmp_path, {"sha": "b" * 40})
    deps = r.deps()

    def wait_for(p, d, watch_bridge=False):
        seen["watch_bridge"] = watch_bridge
        return True

    deps["wait_for"] = wait_for
    executor.build({"channel": "ahk", "cycle_deadline_sec": 5}, tmp_path, **deps).run(
        1, "b", "fixed")
    assert seen["watch_bridge"] is True


def test_ahk_stall_recovery_reinjects_then_stops_on_the_second_breach(tmp_path: Path):
    r = _Rec(tmp_path, {"sha": "c" * 40})
    deps = r.deps()
    breaches = {"n": 0}

    def wait_for(p, d, watch_bridge=False):
        breaches["n"] += 1
        return breaches["n"] > 2  # miss twice, then land

    deps["wait_for"] = wait_for
    deps["stall_action"] = lambda n: "stop" if n >= 2 else "recover"
    ex = executor.build({"channel": "ahk", "cycle_deadline_sec": 5}, tmp_path, **deps)
    ex.run(6, "body", "fixed")
    assert r.written["gemini.ready"] == "recover 6", "the recovery directive should be re-typed"
    assert r.stopped and "hard hang" in r.stopped[0]


# ---- sdk channel ------------------------------------------------------------

def _stub_claude(tmp_path: Path, payload: str, rc: int = 0) -> list:
    """A fake `claude` that prints a fixed envelope and exits."""
    p = tmp_path / "stub_claude.py"
    p.write_text(
        "import sys\n"
        "sys.stdin.read()\n"
        f"sys.stdout.write({payload!r})\n"
        f"sys.exit({rc})\n", encoding="utf-8")
    return [sys.executable, str(p)]


def _sdk(tmp_path: Path, **over):
    cfg = {"channel": "sdk", "repo_root": str(tmp_path), "cycle_deadline_sec": 60}
    cfg.update(over)
    return executor.build(cfg, tmp_path, log=lambda m: None, stop=lambda m: None,
                          awrite=lambda p, t: None)


def test_sdk_argv_carries_schema_model_and_budget(tmp_path: Path):
    argv = _sdk(tmp_path, executor_cmd="claude.cmd", executor_model="claude-opus-5",
                cycle_budget_usd=25.0).build_argv(1)
    assert argv[0] == "claude.cmd"
    assert "-p" in argv and "--output-format" in argv
    assert argv[argv.index("--model") + 1] == "claude-opus-5"
    assert argv[argv.index("--max-budget-usd") + 1] == "25.0"
    schema = json.loads(argv[argv.index("--json-schema") + 1])
    assert schema["required"] == ["sha", "tests_pass", "regressions", "summary"]


def test_sdk_starts_a_fresh_session_when_clear_each_cycle(tmp_path: Path):
    ex = _sdk(tmp_path, clear_each_cycle=True)
    ex.session_id = "prior"
    assert "--session-id" in ex.build_argv(2) and "--resume" not in ex.build_argv(2)


def test_sdk_resumes_the_session_when_clear_each_cycle_is_off(tmp_path: Path):
    ex = _sdk(tmp_path, clear_each_cycle=False)
    ex.session_id = "prior"
    argv = ex.build_argv(2)
    assert argv[argv.index("--resume") + 1] == "prior"


def test_sdk_returns_the_receipt_the_ahk_channel_never_could(tmp_path: Path):
    payload = json.dumps({
        "total_cost_usd": 0.6583, "session_id": "sess-1", "is_error": False,
        "structured_output": {"sha": "e" * 40, "tests_pass": "13061",
                              "regressions": False, "summary": "did the thing"}})
    rec = _sdk(tmp_path, executor_cmd=_stub_claude(tmp_path, payload)).run(1, "b", "fixed")
    assert rec.error is None
    assert rec.sha == "e" * 40
    assert rec.tests_pass == "13061"
    assert rec.cost_usd == 0.6583
    assert rec.session_id == "sess-1"


def test_sdk_missing_structured_output_is_a_failed_cycle_not_an_invented_sha(tmp_path: Path):
    """A fabricated sha would defeat the controller's same-sha no-progress guard."""
    payload = json.dumps({"total_cost_usd": 0.1, "session_id": "s", "is_error": False})
    rec = _sdk(tmp_path, executor_cmd=_stub_claude(tmp_path, payload)).run(1, "b", "fixed")
    assert rec.sha == ""
    assert "structured_output" in rec.error


def test_sdk_incomplete_structured_output_is_rejected(tmp_path: Path):
    payload = json.dumps({"is_error": False, "structured_output": {"sha": "f" * 40}})
    rec = _sdk(tmp_path, executor_cmd=_stub_claude(tmp_path, payload)).run(1, "b", "fixed")
    assert rec.sha == "" and rec.error


def test_sdk_error_envelope_is_surfaced(tmp_path: Path):
    payload = json.dumps({"is_error": True, "result": "credit balance too low",
                          "total_cost_usd": 0.0})
    rec = _sdk(tmp_path, executor_cmd=_stub_claude(tmp_path, payload)).run(1, "b", "fixed")
    assert rec.error == "credit balance too low"


def test_sdk_unparseable_stdout_is_a_failed_cycle(tmp_path: Path):
    rec = _sdk(tmp_path, executor_cmd=_stub_claude(tmp_path, "not json at all")).run(
        1, "b", "fixed")
    assert "unparseable" in rec.error


def test_sdk_nonzero_exit_is_a_failed_cycle(tmp_path: Path):
    payload = json.dumps({"is_error": False, "result": "boom"})
    rec = _sdk(tmp_path, executor_cmd=_stub_claude(tmp_path, payload, rc=1)).run(
        1, "b", "fixed")
    assert rec.error


def test_sdk_timeout_kills_the_tree_and_fails_the_cycle(tmp_path: Path):
    slow = tmp_path / "slow.py"
    slow.write_text("import time\ntime.sleep(60)\n", encoding="utf-8")
    t0 = time.time()
    rec = _sdk(tmp_path, executor_cmd=[sys.executable, str(slow)],
               cycle_deadline_sec=2).run(1, "b", "fixed")
    assert "timeout" in rec.error
    assert time.time() - t0 < 45, "the timeout path should not wait out the child"


# ---- sdk channel: killing a wedged child on BOTH platforms ------------------
#
# MEASURED 2026-07-27, nightly ubuntu CI. The kill path was `taskkill /F /T` and
# nothing else, so on POSIX it was a missing executable whose OSError was
# swallowed; the child survived, and the `proc.wait(timeout=30)` that followed
# re-raised TimeoutExpired out of the handler. The test above ERRORED - against
# an injected deadline of 2s, reporting 30 - instead of asserting, and an
# unattended cycle would have died on the same exception. `os.access` has a
# precedent here (_is_on_disk_executable): the platform that is not under the
# operator's feet gets a monkeypatched seam, never a skipif.


class _FakeProc:
    """Just enough Popen surface for the teardown seam."""

    def __init__(self, pid: int = 4242):
        self.pid = pid
        self.killed = False

    def kill(self):
        self.killed = True


def test_the_child_is_spawned_in_its_own_session_on_posix(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(executor.os, "name", "posix")
    assert executor._spawn_group_kwargs() == {"start_new_session": True}, (
        "without its own process group the child shares the CONTROLLER's, and "
        "the killpg teardown would take the loop down with the child")


def test_the_group_seam_contributes_nothing_on_windows(monkeypatch: pytest.MonkeyPatch):
    """CREATE_NO_WINDOW must NOT migrate into this helper.

    tests/test_no_console_flash_scheduled_tools.py resolves `creationflags` by
    AST at every subprocess spawn site, and a `**dict` argument is opaque to that
    scan - folding the flag in here left this module's only spawn site unprovable
    and made the console-flash guard report a protection it could no longer see.
    start_new_session is POSIX-only (Windows takes it as
    `unused_start_new_session`), so on nt this seam has nothing to add at all.
    """
    monkeypatch.setattr(executor.os, "name", "nt")
    assert executor._spawn_group_kwargs() == {}


def test_the_posix_teardown_kills_the_process_group_not_just_the_child(
        monkeypatch: pytest.MonkeyPatch):
    """A wedged `claude -p` has child tool processes: killing the pid alone
    leaves them holding the pipes the cycle is blocked on."""
    proc = _FakeProc(pid=4242)
    sent = []
    monkeypatch.setattr(executor.os, "name", "posix")
    monkeypatch.setattr(executor.os, "getpgid",
                        lambda pid: 4242 if pid == 4242 else 7, raising=False)
    monkeypatch.setattr(executor.os, "killpg",
                        lambda pgid, sig: sent.append((pgid, sig)), raising=False)
    executor._kill_process_tree(proc)
    assert sent == [(4242, executor._KILL_SIG)]
    assert proc.killed is False, "the single-pid kill is the fallback, not the path"


def test_the_posix_teardown_refuses_to_killpg_the_controllers_own_group(
        monkeypatch: pytest.MonkeyPatch):
    """A child spawned WITHOUT start_new_session shares the loop's process
    group, and killpg there kills the controller doing the reaping - a self-kill
    dressed as a teardown. The single pid is the correct remedy instead."""
    proc = _FakeProc(pid=4242)
    sent = []
    monkeypatch.setattr(executor.os, "name", "posix")
    monkeypatch.setattr(executor.os, "getpgid", lambda pid: 7, raising=False)
    monkeypatch.setattr(executor.os, "killpg",
                        lambda pgid, sig: sent.append((pgid, sig)), raising=False)
    executor._kill_process_tree(proc)
    assert sent == []
    assert proc.killed is True


def test_the_windows_teardown_is_still_taskkill_and_never_stop_process(
        monkeypatch: pytest.MonkeyPatch):
    """Regression guard on the platform that already worked. `Stop-Process` is a
    CLAUDE.md hard rule (it hangs the MCP pipe) and /T is what reaches the child
    tool processes."""
    proc = _FakeProc(pid=1234)
    calls = []

    def _fake_run(argv, **kw):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(executor.os, "name", "nt")
    monkeypatch.setattr(executor.subprocess, "run", _fake_run)
    executor._kill_process_tree(proc)
    assert calls == [["taskkill", "/F", "/T", "/PID", "1234"]]
    assert proc.killed is False


def test_the_windows_teardown_falls_back_when_taskkill_cannot_run(
        monkeypatch: pytest.MonkeyPatch):
    """taskkill absent from PATH must still kill the child - and must not raise
    out of a handler whose entire job is to not raise."""
    proc = _FakeProc(pid=1234)

    def _boom(*a, **k):
        raise FileNotFoundError("taskkill")

    monkeypatch.setattr(executor.os, "name", "nt")
    monkeypatch.setattr(executor.subprocess, "run", _boom)
    executor._kill_process_tree(proc)
    assert proc.killed is True


@pytest.mark.parametrize("osname,wants_group", [("posix", True), ("nt", False)])
def test_the_sdk_spawn_carries_both_platform_kwargs(
        osname: str, wants_group: bool, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch):
    """What the spawn site actually passes, on both platforms.

    creationflags is asserted on BOTH because it is written literally at the
    call - which is what keeps tests/test_no_console_flash_scheduled_tools.py
    able to resolve it by AST. `creationflags=0` is legal on POSIX
    (subprocess.py:867 raises only on a non-zero value) and the getattr default
    IS 0 there, so the literal is free. start_new_session is POSIX-only, and on
    POSIX it is the difference between killpg reaching the CHILD's process group
    and killpg reaching the loop's own.
    """
    seen = {}

    class _P:
        pid = 4321
        returncode = 0

        def communicate(self, prompt, timeout=None):
            return (json.dumps({
                "is_error": False, "total_cost_usd": 0.0,
                "structured_output": {"sha": "a" * 40, "tests_pass": "1",
                                      "regressions": False, "summary": "s"}}), "")

    def _fake_popen(argv, **kw):
        seen.update(kw)
        return _P()

    # The grounding guard shells out to git before the spawn; stubbing HEAD to
    # empty keeps this test's ONLY subprocess use the one it is measuring.
    monkeypatch.setattr(executor, "_git_head", lambda root: "")
    monkeypatch.setattr(executor.os, "name", osname)
    monkeypatch.setattr(executor.subprocess, "Popen", _fake_popen)
    rec = _sdk(tmp_path, executor_cmd="claude").run(1, "b", "fixed")
    assert rec.error is None
    assert seen["creationflags"] == getattr(subprocess, "CREATE_NO_WINDOW", 0), (
        "the console-flash flag must reach every spawn on every platform")
    assert ("start_new_session" in seen) is wants_group


def test_the_sdk_timeout_records_a_failed_cycle_even_if_the_child_survives(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The measured linux failure, reproduced from Windows by neutering the kill.

    A child that cannot be reaped is still a FAILED CYCLE, never a crash: the
    escaping TimeoutExpired is what made the CI run report a 30s timeout for a
    2s deadline and error the test instead of asserting on rec.error.
    """
    slow = tmp_path / "slow.py"
    slow.write_text("import time\ntime.sleep(60)\n", encoding="utf-8")
    survived = []
    # Bound BEFORE the patch: monkeypatch does not unwind until teardown, so the
    # cleanup below would otherwise re-enter the recording stub.
    real_kill = executor._kill_process_tree
    monkeypatch.setattr(executor, "_kill_process_tree", survived.append)
    monkeypatch.setattr(executor, "_REAP_TIMEOUT_SEC", 0.5)
    logs = []
    ex = executor.build(
        {"channel": "sdk", "repo_root": str(tmp_path), "cycle_deadline_sec": 2,
         "executor_cmd": [sys.executable, str(slow)]}, tmp_path,
        log=logs.append, stop=lambda m: None, awrite=lambda p, t: None)
    try:
        rec = ex.run(1, "b", "fixed")
    finally:
        # The stub recorded the child instead of killing it - kill it for real
        # rather than leaking a 60s sleeper into the rest of the suite.
        for child in list(survived):
            real_kill(child)
    assert survived, "the timeout path must attempt a tree kill"
    assert "timeout" in rec.error
    assert any("not reaped" in m for m in logs)


def test_sdk_prompt_drops_the_clear_and_the_cycle_header(tmp_path: Path):
    """`-p` is already a fresh process; /clear is meaningless and the header is prose."""
    p = executor.sdk_prompt(3, "body", "director")
    assert "/clear" not in p and "CYCLE=" not in p
    assert p.startswith("/directed-headless-upgrade")
    assert "done_sentinel.py" in p, "the sdk channel returns JSON instead of the sentinel"


# ---- commit gate ------------------------------------------------------------

def _configured_hooks_path(root: Path) -> str:
    """core.hooksPath as GIT reports it - read independently of the module under
    test, so the expectation is not derived from the same code path it judges."""
    r = subprocess.run(["git", "-C", str(root), "config", "--get", "core.hooksPath"],
                       capture_output=True, text=True, timeout=60)
    return (r.stdout or "").strip() if r.returncode == 0 else ""


def test_gate_is_active_in_this_repo():
    """Two-sided, because `core.hooksPath` is LOCAL config and is NEVER cloned.

    RC installs hooks with scripts/install_hooks.py, so on the operator machine
    the gate is live and the strong assertion holds unchanged. A fresh clone -
    every CI checkout - has the tracked .githooks/ on disk and ZERO hooks
    running, so the one-sided version was asserting machine-local operator state
    as if it were a code invariant, and the nightly ubuntu run went red on it for
    being TRUE.

    Not a skip: the repo skip doctrine (tests/test_skip_condition_hygiene.py)
    allows a skip only when an environment CAPABILITY is absent, and .githooks/
    is tracked - a skip keyed on it is the exact always-passing shape that guard
    catches. Not an early return either: the ungated clone has the more
    interesting question anyway - does the function REFUSE to call it green? -
    and asserting the fresh-clone reason verbatim keeps both environments
    meaningful. The day gate_inactive_reason answers None for an unconfigured
    clone, one of these two branches goes red wherever the suite runs.
    """
    reason = executor.gate_inactive_reason(ROOT)
    if _configured_hooks_path(ROOT):
        assert reason is None, (
            f"hooks are installed in this tree and the gate reads inactive: {reason}")
    else:
        assert reason == "core.hooksPath is unset, so this clone runs ZERO git hooks", (
            "an unconfigured clone runs no hooks at all - calling it gated is the "
            f"one failure this check exists to prevent (got: {reason!r})")


def test_unset_hookspath_is_reported_as_ungated(tmp_path: Path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, timeout=60)
    (tmp_path / ".githooks").mkdir()
    reason = executor.gate_inactive_reason(tmp_path)
    assert reason and "core.hooksPath" in reason


def test_a_repo_without_githooks_is_not_this_repos_concern(tmp_path: Path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, timeout=60)
    assert executor.gate_inactive_reason(tmp_path) is None


# ---- commit gate: the index EXEC BIT ----------------------------------------
#
# Measured 2026-07-26: all five tracked hooks in .githooks/ were index mode
# 100644. git silently refuses to run a non-executable hook on any POSIX clone,
# so the whole gate was inert on every Linux checkout (incl. CI) and the
# presence-only check reported it green. These pin BOTH directions, because a
# guard that always fires and a guard that never fires look identical from the
# one side this repo usually tests.

def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, timeout=60,
                   capture_output=True)


def _tracked_hook_repo(tmp_path: Path, *, executable: bool,
                       names=("pre-commit", "commit-msg")) -> Path:
    """A synthetic clone whose hooks are TRACKED, at a chosen index mode."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, timeout=60)
    hooks = tmp_path / ".githooks"
    hooks.mkdir(exist_ok=True)
    rel = []
    for n in names:
        (hooks / n).write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        rel.append(f".githooks/{n}")
    _git(tmp_path, "add", "--", *rel)
    if executable:
        _git(tmp_path, "update-index", "--chmod=+x", "--", *rel)
    _git(tmp_path, "config", "core.hooksPath", ".githooks")
    # The index mode and the on-disk bit are two separate checks, so the fixture
    # has to be coherent in BOTH or a POSIX run fails for the wrong reason: git
    # add records whatever the disk says, so the chmod lands after update-index
    # (a 0o755 before the add would make `executable=False` record 100755).
    for n in names:
        os.chmod(hooks / n, 0o755 if executable else 0o644)
    return hooks


def test_hooks_tracked_100644_are_reported_as_ungated(tmp_path: Path):
    _tracked_hook_repo(tmp_path, executable=False)
    reason = executor.gate_inactive_reason(tmp_path)
    assert reason, "a 100644 hook does not run on a POSIX clone - that is not green"
    assert "100644" in reason and "100755" in reason
    assert "pre-commit" in reason and "commit-msg" in reason


def test_hooks_tracked_100755_are_clean(tmp_path: Path):
    """The other direction: the fix must be reachable, not a permanent breach."""
    _tracked_hook_repo(tmp_path, executable=True)
    assert executor.gate_inactive_reason(tmp_path) is None


def test_only_the_non_executable_hook_is_named(tmp_path: Path):
    _tracked_hook_repo(tmp_path, executable=True)
    _git(tmp_path, "update-index", "--chmod=-x", "--", ".githooks/commit-msg")
    reason = executor.gate_inactive_reason(tmp_path)
    assert reason and "commit-msg" in reason
    assert "pre-commit" not in reason, "naming a hook that is fine sends the fix at the wrong file"


def test_untracked_hooks_dir_is_not_reported_as_a_mode_breach(tmp_path: Path):
    """`core.hooksPath=.git/hooks` is a legitimate install - .git is never in the
    index, so ls-files returns nothing and there is no mode to judge. Reporting a
    100755 failure here would block the loop on a working configuration."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, timeout=60)
    (tmp_path / ".githooks").mkdir()
    real = tmp_path / ".git" / "hooks"
    real.mkdir(parents=True, exist_ok=True)
    for n in ("pre-commit", "commit-msg"):
        (real / n).write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        # A real .git/hooks install is executable; write_text is not. Without
        # this the on-disk check below would fire on POSIX and this test would
        # pass or fail for a reason that has nothing to do with the index.
        os.chmod(real / n, 0o755)
    _git(tmp_path, "config", "core.hooksPath", str(real))
    assert executor.gate_inactive_reason(tmp_path) is None


def test_missing_hook_file_still_wins_over_the_mode_check(tmp_path: Path):
    """Ordering is load-bearing: a missing hook is the bigger, older finding and
    its wording is already asserted above - the mode check must not preempt it."""
    _tracked_hook_repo(tmp_path, executable=False, names=("pre-commit",))
    reason = executor.gate_inactive_reason(tmp_path)
    assert reason and reason.startswith("hooks missing from")
    assert "commit-msg" in reason


# ---- commit gate: the ON-DISK exec bit --------------------------------------
#
# The index mode is what a fresh clone materializes, but it is not what git
# actually consults at commit time - that is the working-tree file. A hook can
# be tracked 100755 and still be 644 on disk (a later `chmod -x`, a clone with
# core.fileMode=false, an export/rsync/zip that dropped modes, a container
# bind-mount), and git skips it silently. The index-mode check reports green on
# every one of those, which is the same always-passing failure it was added to
# fix, one layer down.
#
# `os.access(p, os.X_OK)` is True for any existing file on nt, so the probe can
# only bite on POSIX. That is NOT a reason to skipif the tests away: skipping
# here would mean the branch that matters is the branch nothing runs. The
# platform seam is a monkeypatchable helper instead, so both directions are
# pinned on Windows and on Linux with no skip.

def test_the_on_disk_probe_is_a_documented_no_op_on_windows(tmp_path: Path):
    """Pin the platform contract itself, so the no-op is a decision not a surprise."""
    plain = tmp_path / "plain.sh"
    plain.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    os.chmod(plain, 0o644)
    if os.name == "nt":
        assert executor._is_on_disk_executable(plain) is True, (
            "nt has no exec bit to read - inventing a breach there would block "
            "the loop on the one machine that actually runs it")
    else:
        assert executor._is_on_disk_executable(plain) is False


def test_the_posix_branch_asks_the_filesystem(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Force the non-nt branch while running on nt. A helper that returned True
    unconditionally would pass every other test on this machine, so the one
    thing the POSIX side must do - actually probe X_OK - is pinned here rather
    than left for a Linux run to discover."""
    plain = tmp_path / "probe.sh"
    plain.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    seen = []

    def _fake_access(p, mode):
        seen.append((p, mode))
        return True

    monkeypatch.setattr(executor.os, "name", "posix")
    monkeypatch.setattr(executor.os, "access", _fake_access)
    assert executor._is_on_disk_executable(plain) is True
    assert seen == [(plain, os.X_OK)]


def test_a_hook_tracked_100755_but_not_executable_on_disk_is_ungated(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The index is right and the gate is still dead - green here is a lie."""
    _tracked_hook_repo(tmp_path, executable=True)
    monkeypatch.setattr(executor, "_is_on_disk_executable", lambda p: False)
    reason = executor.gate_inactive_reason(tmp_path)
    assert reason, "a 644 working-tree hook does not run, whatever the index says"
    assert "chmod +x" in reason, "the message has to carry the fix, not just the fault"
    assert "pre-commit" in reason and "commit-msg" in reason


def test_only_the_hook_whose_disk_bit_is_clear_is_named(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Same contract as the index-mode check: naming a healthy hook sends the
    operator to chmod a file that was never the problem."""
    _tracked_hook_repo(tmp_path, executable=True)
    monkeypatch.setattr(executor, "_is_on_disk_executable",
                        lambda p: Path(p).name != "commit-msg")
    reason = executor.gate_inactive_reason(tmp_path)
    assert reason and "commit-msg" in reason
    assert "pre-commit" not in reason


def test_the_disk_bit_reason_is_distinguishable_from_the_index_mode_reason(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Two different faults with two different fixes - `git update-index
    --chmod=+x` cannot repair a working-tree bit and `chmod +x` cannot repair
    the index, so a caller that cannot tell them apart gets sent to the wrong
    command half the time."""
    idx_repo, disk_repo = tmp_path / "idx", tmp_path / "disk"
    idx_repo.mkdir()
    disk_repo.mkdir()
    _tracked_hook_repo(idx_repo, executable=False)
    index_reason = executor.gate_inactive_reason(idx_repo)
    _tracked_hook_repo(disk_repo, executable=True)
    monkeypatch.setattr(executor, "_is_on_disk_executable", lambda p: False)
    disk_reason = executor.gate_inactive_reason(disk_repo)
    assert index_reason and disk_reason and index_reason != disk_reason
    assert "update-index" in index_reason and "update-index" not in disk_reason
    assert "chmod +x" in disk_reason


def test_an_executable_on_disk_hook_is_clean(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The other direction: the new check must be reachable-clean, not a breach
    nobody can clear."""
    _tracked_hook_repo(tmp_path, executable=True)
    monkeypatch.setattr(executor, "_is_on_disk_executable", lambda p: True)
    assert executor.gate_inactive_reason(tmp_path) is None


def test_missing_hook_file_still_wins_over_the_on_disk_check(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Ordering is load-bearing and already pinned against the index-mode check;
    the new check must not preempt the missing-file finding either."""
    _tracked_hook_repo(tmp_path, executable=True, names=("pre-commit",))
    monkeypatch.setattr(executor, "_is_on_disk_executable", lambda p: False)
    reason = executor.gate_inactive_reason(tmp_path)
    assert reason and reason.startswith("hooks missing from")
    assert "commit-msg" in reason


def test_an_untracked_hook_dir_is_still_judged_on_the_disk_bit(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A `.git/hooks` install has no index mode to read, which is why the
    index-mode check skips it - but the file is right there and git will skip a
    non-executable one just the same. Scoping the disk probe to tracked hooks
    would rebuild the exact hole this check exists to close."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, timeout=60)
    (tmp_path / ".githooks").mkdir()
    real = tmp_path / ".git" / "hooks"
    real.mkdir(parents=True, exist_ok=True)
    for n in ("pre-commit", "commit-msg"):
        (real / n).write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    _git(tmp_path, "config", "core.hooksPath", str(real))
    monkeypatch.setattr(executor, "_is_on_disk_executable", lambda p: False)
    reason = executor.gate_inactive_reason(tmp_path)
    assert reason and "chmod +x" in reason


# ---- FINAL STEP: one source of truth per channel ----------------------------

def test_ahk_final_step_is_the_sentinel_command_and_no_json_instruction():
    """The ahk controller blocks on control/claude.done - the sentinel IS the signal."""
    s = executor.final_step_instruction("ahk")
    assert "ops/loop/done_sentinel.py --tests <PASS_COUNT> --regressions <0_or_1>" in s
    assert "do NOT run" not in s
    assert "structured_output" not in s and "output schema" not in s


def test_sdk_final_step_is_the_json_instruction_and_no_sentinel_command():
    s = executor.final_step_instruction("sdk")
    assert "do NOT run ops/loop/done_sentinel.py" in s
    assert "output schema" in s
    assert "--tests <PASS_COUNT>" not in s


def test_final_step_defaults_to_ahk_when_the_channel_is_absent():
    """An older config with no `channel` key must keep the legacy completion step."""
    assert executor.final_step_instruction(None) == executor.AHK_FINAL_STEP
    assert executor.final_step_instruction("") == executor.AHK_FINAL_STEP


def test_final_step_rejects_an_unknown_channel_like_build_does():
    with pytest.raises(ValueError, match="unknown executor channel"):
        executor.final_step_instruction("skd")


def test_ahk_final_step_matches_rc_interpreter_path_not_lws():
    """RC's executor.py is a shape-port, not a byte-copy. Copying LW's string here
    would break RC's ahk rollback path, which only a live dry cycle catches.

    The interpreter is RESOLVED at import rather than hardcoded, so the property
    MOVED rather than being dropped: the step must still name an ABSOLUTE
    python.exe (a bare launcher is the defect tests/test_bare_py_ban.py guards),
    and it must be the interpreter THIS machine resolves - not a literal carried
    over from a sibling repo.
    """
    resolved = executor.canonical_interpreter()
    assert Path(resolved).is_absolute(), resolved
    assert Path(resolved).name in ("python.exe", "python"), resolved
    assert f'"{resolved}"' in executor.AHK_FINAL_STEP
    assert "Sibling-A" not in executor.AHK_FINAL_STEP


def test_ahk_final_step_hardcodes_no_account_specific_home_path():
    """OPS-38: a step naming one account's home silently does not run under
    another, and a step that does not run reports nothing. The SOURCE must
    carry no home-shaped literal even though the rendered value is absolute.
    """
    src = (ROOT / "ops" / "loop" / "executor.py").read_text(encoding="utf-8")
    assert not re.search(r"[A-Za-z]:[\\/]Users[\\/](?![%$<~])[A-Za-z0-9._~-]+", src), (
        "ops/loop/executor.py re-hardcoded a user home directory"
    )


def test_sdk_prompt_uses_final_step_instruction_so_it_cannot_drift():
    """Pins the no-drift property: the body and the appended step share one source."""
    assert executor.final_step_instruction("sdk") in executor.sdk_prompt(1, "b", "director")


def test_director_prompt_hardcodes_no_channel_specific_completion_step():
    """Regression guard: re-hardcoding the sentinel here re-opens the defect."""
    text = (ROOT / "ops" / "loop" / "director_prompt.md").read_text(encoding="utf-8")
    assert "{{FINAL_STEP}}" in text, "the placeholder is what the controller substitutes"
    assert "done_sentinel.py --tests" not in text


def test_directive_suffix_names_no_channel_specific_step():
    """LW's config re-introduced the contradiction from directive_suffix after the
    prompt was fixed. RC's must stay channel-neutral."""
    cfg = json.loads((ROOT / "ops" / "loop" / "config.json").read_text(encoding="utf-8"))
    suffix = cfg.get("directive_suffix", "")
    assert "done_sentinel" not in suffix
    assert "FINAL STEP" not in suffix


@pytest.mark.parametrize("channel,present,absent", [
    ("ahk", "done_sentinel.py --tests", "do NOT run"),
    ("sdk", "do NOT run ops/loop/done_sentinel.py", "--tests <PASS_COUNT>"),
])
def test_template_substitution_leaves_no_placeholder_on_either_channel(channel, present, absent):
    tmpl = (ROOT / "ops" / "loop" / "director_prompt.md").read_text(encoding="utf-8")
    out = tmpl.replace("{{FINAL_STEP}}", executor.final_step_instruction(channel))
    assert "{{FINAL_STEP}}" not in out
    assert present in out
    assert absent not in out


def test_no_budget_flag_when_cycle_budget_is_absent():
    """Operator decision 2026-07-26: no --max-budget-usd on a Max 20x SUBSCRIPTION.
    total_cost_usd is a notional API-equivalent price, not money billed, so a cap
    truncates a cycle on a number that does not track actual spend. Time
    (cycle_deadline_sec) is the executor's only real budget."""
    argv = _sdk(Path("."), executor_cmd="claude.cmd").build_argv(1)
    assert "--max-budget-usd" not in argv


def test_shipped_configs_carry_no_dollar_cap():
    """Regression guard: re-adding cycle_budget_usd silently re-arms the cap."""
    import json as _json
    for name in ("config.json", "config.p5.json", "config.gate.json"):
        cfg = _json.loads((ROOT / "ops" / "loop" / name).read_text(encoding="utf-8"))
        assert "cycle_budget_usd" not in cfg, f"{name} re-armed the dollar cap"
        assert cfg.get("cycle_deadline_sec"), f"{name} must still rail the executor on TIME"


# ---- parallel-agent disjointness guard --------------------------------------
#
# MEASURED, twice: the director wrote "dispatch 3 parallel disjoint worktree
# agents" and the named file sets were NOT disjoint (R194 collided on a shared
# guard tail, R196 put all three tails in the same two files with slice 2 a
# schema lift the other two consumed). Both times a human caught it. When nobody
# catches it, the agents clobber each other.

_DISJOINT = """THEME: F1 phase 6
Dispatch 3 parallel disjoint worktree agents on disjoint file sets.

AGENT 1: ops/loop/executor.py
AGENT 2: tests/test_loop_concurrency.py
AGENT 3: ops/loop/slots.py
"""

_R196 = """THEME: F1 phase 6
Dispatch 3 parallel disjoint worktree agents.

AGENT 1: ops/loop/executor.py plus tests/test_loop_executor.py
AGENT 2: ops/loop/executor.py schema lift the other two consume
AGENT 3: tests/test_loop_executor.py tail
"""


def test_a_directive_with_no_parallel_dispatch_is_not_judged():
    plan = executor.parallel_plan(
        "Edit ops/loop/executor.py and tests/test_loop_executor.py in this session.")
    assert plan.verdict == "none"
    assert plan.deviates is False


def test_disjoint_file_sets_pass_untouched():
    plan = executor.parallel_plan(_DISJOINT)
    assert plan.agents == 3
    assert plan.verdict == "disjoint"
    assert plan.deviates is False
    logs = []
    assert executor.enforce_agent_disjointness(4, _DISJOINT, log=logs.append) == _DISJOINT
    assert logs == [], "a directive that is already fine must produce no deviation record"


def test_overlapping_file_sets_serialize_and_record():
    plan = executor.parallel_plan(_R196)
    assert plan.verdict == "overlap"
    assert plan.deviates is True
    assert "executor.py" in plan.detail
    logs = []
    out = executor.enforce_agent_disjointness(7, _R196, log=logs.append)
    assert out != _R196
    assert logs and executor.PARALLEL_MARKER in logs[0]
    assert "SEQUENTIALLY" in out
    assert _R196.strip() in out, "the original directive text must survive verbatim"


def test_the_marker_is_distinct_from_the_winmutex_one():
    """winmutex greps UNSERIALIZED; a substring collision would cross the wires."""
    assert "UNSERIALIZED" not in executor.PARALLEL_MARKER
    assert executor.PARALLEL_MARKER.startswith("executor: ")


def test_unextractable_file_sets_are_recorded_not_silently_passed():
    """The failure mode this repo keeps hitting: a guard that degrades into
    always-passing on every input it cannot parse."""
    body = ("Dispatch three parallel worktree agents, one per scorer.\n"
            "Each agent picks its own slice and stays out of the others' way.\n")
    plan = executor.parallel_plan(body)
    assert plan.agents == 3
    assert plan.verdict == "unverified"
    assert plan.deviates is True
    logs = []
    out = executor.enforce_agent_disjointness(2, body, log=logs.append)
    assert logs and executor.PARALLEL_MARKER in logs[0]
    assert "could not verify" in logs[0].lower()
    assert out != body


def test_a_partially_extracted_directive_is_unverified_not_disjoint():
    body = ("Dispatch 3 parallel worktree agents.\n"
            "AGENT 1: ops/loop/a.py\n"
            "AGENT 2: ops/loop/b.py\n")
    plan = executor.parallel_plan(body)
    assert plan.agents == 3
    assert plan.verdict == "unverified", "2 of 3 file sets found is not proof of disjointness"


def test_a_named_agent_with_no_files_is_unverified():
    body = ("Dispatch 2 parallel worktree agents.\n"
            "AGENT 1: ops/loop/a.py\n"
            "AGENT 2: whatever is left over\n")
    assert executor.parallel_plan(body).verdict == "unverified"


def test_a_single_agent_directive_is_unaffected():
    for body in ("Do this in one session: ops/loop/executor.py, tests/test_loop_executor.py.",
                 "Dispatch 1 parallel worktree agent on ops/loop/executor.py."):
        plan = executor.parallel_plan(body)
        assert plan.verdict == "none", body
        assert executor.enforce_agent_disjointness(1, body) == body


def test_absolute_and_relative_spellings_of_one_file_still_collide():
    body = ("Dispatch 2 parallel worktree agents.\n"
            "AGENT 1: C:\\Riot Commander\\ops\\loop\\executor.py\n"
            "AGENT 2: ops/loop/executor.py\n")
    assert executor.parallel_plan(body).verdict == "overlap"


def test_word_counts_and_slice_labels_are_understood():
    body = ("Fan out two parallel slices.\n"
            "SLICE A - ops/loop/executor.py\n"
            "SLICE B - ops/loop/slots.py\n")
    plan = executor.parallel_plan(body)
    assert plan.agents == 2 and plan.verdict == "disjoint"


def test_prose_version_numbers_are_not_mistaken_for_files():
    body = ("Dispatch 2 parallel worktree agents. Bump ENGINE_VERSION to 1.260.1, e.g. "
            "in the usual places.\n"
            "AGENT 1: ops/loop/executor.py\n"
            "AGENT 2: ops/loop/slots.py\n")
    assert executor.parallel_plan(body).verdict == "disjoint"


def test_ahk_channel_rewrites_directive_md_and_types_the_serialized_body(tmp_path: Path):
    """The director path types only the opener - the session READS directive.md, so
    the correction has to land in the file or it is not applied at all."""
    r = _Rec(tmp_path, {"sha": "d" * 40})
    ex = executor.build({"channel": "ahk", "cycle_deadline_sec": 5}, tmp_path, **r.deps())
    ex.run(5, _R196, "director")
    assert "SEQUENTIALLY" in r.written["directive.md"]
    assert any(executor.PARALLEL_MARKER in m for m in r.logs)


def test_ahk_channel_leaves_a_clean_directive_alone(tmp_path: Path):
    r = _Rec(tmp_path, {"sha": "d" * 40})
    ex = executor.build({"channel": "ahk", "cycle_deadline_sec": 5}, tmp_path, **r.deps())
    ex.run(5, _DISJOINT, "fixed")
    assert "directive.md" not in r.written, "no rewrite when the directive is already fine"
    assert r.written["gemini.ready"] == f"CYCLE=5\n/clear\n{_DISJOINT}"
    assert not any(executor.PARALLEL_MARKER in m for m in r.logs)


def test_a_proven_collision_leaves_the_session_no_discretion():
    out = executor.serialize_directive(_R196, executor.parallel_plan(_R196))
    assert "ONE AT A TIME" in out
    assert "AGENT 1 -> AGENT 2 -> AGENT 3" in out, "serialize in the order named"


def test_an_unverifiable_dispatch_must_be_proven_or_serialized():
    """Not the same instruction as a proven collision. 'Fan out 10 parallel agents
    across different effect channels' names no files and may well be disjoint -
    forcing 10 scouts sequential is a real cost - but it may not be dispatched
    unexamined either, which is what the executor did before this guard."""
    body = ("Fan out 10 parallel sub-agents across DIFFERENT effect channels, "
            "each scouting one channel.\n")
    plan = executor.parallel_plan(body)
    assert plan.verdict == "unverified"
    out = executor.serialize_directive(body, plan)
    assert "file set" in out
    assert "SEQUENTIALLY" in out, "the fallback when it cannot be proven"


def test_the_real_r196_directive_is_flagged():
    """The measured incident, verbatim from the shape the director actually wrote:
    3 parallel worktree subagents, slice 2 a schema lift the other two consumed,
    and no file set stated for it at all."""
    body = (
        "Task: DS sweep kit-penetration tails from BACKLOG.md.\n"
        "Slice 1: Credit Annie R in antitank._ANTITANK_REGISTRY. Flip uncredited pin in "
        "agents/daemon_slayer/tests/test_kit_magic_pen_catalog_r190.py.\n"
        "Slice 2: Add AXIS field (PHYSICAL/MAGICAL/BOTH) to _ANTITANK_REGISTRY rows. "
        "Make guard exact via new AXIS field.\n"
        "Slice 3: Correct Amumu P in _ANTITANK_REGISTRY.\n"
        "Use ORCHESTRATOR MULTI-AGENT pattern. Dispatch 3 parallel worktree subagents "
        "(isolation:worktree).\n")
    plan = executor.parallel_plan(body)
    assert plan.agents == 3
    assert plan.deviates is True, "this exact directive shape collided twice"
    assert "SLICE 2" in plan.detail


def test_sdk_channel_records_the_deviation_too(tmp_path: Path):
    payload = json.dumps({"is_error": False, "total_cost_usd": 0.0,
                          "structured_output": {"sha": "a" * 40, "tests_pass": "1",
                                                "regressions": False, "summary": "s"}})
    logs, written = [], {}
    ex = executor.build(
        {"channel": "sdk", "repo_root": str(tmp_path), "cycle_deadline_sec": 60,
         "executor_cmd": _stub_claude(tmp_path, payload)}, tmp_path,
        log=logs.append, stop=lambda m: None,
        awrite=lambda p, t: written.__setitem__(Path(p).name, t))
    ex.run(3, _R196, "director")
    assert any(executor.PARALLEL_MARKER in m for m in logs)
    assert "SEQUENTIALLY" in written["directive.md"]


# ---- directive grounding guard ----------------------------------------------
#
# MEASURED 2026-07-27, on this loop. The director emitted control/directive.md
# TWICE carrying the same already-landed unit of work (the f1-phase6 inbox
# apply: chmod the githooks, apply moon_sync_inbox/winmutex.py.from-lw, pin the
# item-5a SHA, ack Sibling-A) which had landed across four commits that
# were all ancestors of HEAD. The directive self-reported
# `GROUNDED-AGAINST: HEAD=f173ce39 LEDGER-TOP=1074 CHAIN-LAST=cycle 4` while the
# real HEAD was 9d836162.
#
# The three grounding fields director_prompt.md:14-18 mandates are 100 percent
# self-reported: a grep for GROUNDED-AGAINST / NOT-A-DUPLICATE-OF / PREMISE-CHECK
# across the .py tree returned ZERO hits, so nothing ever read the claim back and
# the stale directive was handed to the executor verbatim.

_HEAD = ("9d836162" * 5)[:40]


class _Git:
    """A fake git, so these tests need no repository and no commits.

    resolve() records what it was asked, because HALF the contract here is which
    tokens are never probed at all - a ledger id or a test count that reached
    `git rev-parse` could come back as an ambiguous prefix and manufacture a
    finding out of a decimal number.
    """

    def __init__(self, head: str = _HEAD, landed=(), unmerged=()):
        self.head = head
        self.probed: list = []
        self._full = {}
        self._landed = set()
        for s in landed:
            self._full[s.lower()] = self._expand(s)
            self._landed.add(self._expand(s))
        for s in unmerged:
            self._full.setdefault(s.lower(), self._expand(s))

    @staticmethod
    def _expand(short: str) -> str:
        return (short.lower() * 6)[:40]

    def kwargs(self) -> dict:
        return dict(head=self.head, resolve=self.resolve, is_ancestor=self.is_ancestor)

    def resolve(self, token: str) -> str:
        self.probed.append(token)
        return self._full.get(token.lower(), "")

    def is_ancestor(self, a: str, b: str) -> bool:
        return a in self._landed and b == self.head


# The measured incident, in the shape the director actually emitted it.
_R200 = """GROUNDED-AGAINST: HEAD=f173ce39 LEDGER-TOP=1074 CHAIN-LAST=cycle 4
NOT-A-DUPLICATE-OF: the inbox apply in 04a5a534 | distinct because ops/loop/winmutex.py
is not yet applied
PREMISE-CHECK: winmutex.py still carries the old bytes [UNVERIFIED]

# f1-phase6 inbox apply
Apply moon_sync_inbox/winmutex.py.from-lw over ops/loop/winmutex.py, chmod +x the
githooks, pin the item-5a SHARED_SHA256, ack Sibling-A.
"""

_GROUNDED_CLEAN = f"""GROUNDED-AGAINST: HEAD={_HEAD[:8]} LEDGER-TOP=1074 CHAIN-LAST=cycle 5
NOT-A-DUPLICATE-OF: LEDGER 1074 | distinct because ops/loop/executor.py has no
grounding check on disk
PREMISE-CHECK: 13061 tests pass [from-digest]

Add the grounding guard. LW shipped the same shape at deadbeefcafe on its side.
"""


def test_a_stale_grounded_head_is_a_finding():
    """The claim is checkable and it was wrong - that is the whole defect."""
    found = executor.grounding_findings(_R200, **_Git(landed=["f173ce39"]).kwargs())
    stale = [f for f in found if f.kind == "stale-head"]
    assert stale, "HEAD=f173ce39 against a real HEAD of 9d836162 is not grounded"
    assert stale[0].token == "f173ce39"
    assert "9d836162" in stale[0].detail, "the real HEAD has to be named, not just the claim"


def test_a_matching_grounded_head_is_not_a_finding():
    assert executor.grounding_findings(_GROUNDED_CLEAN, **_Git().kwargs()) == []


def test_a_sha_already_merged_into_head_is_a_finding():
    found = executor.grounding_findings(_R200, **_Git(landed=["f173ce39", "04a5a534"]).kwargs())
    landed = [f for f in found if f.kind == "already-landed"]
    assert [f.token for f in landed] == ["04a5a534"]
    assert "already" in landed[0].detail.lower()


def test_a_not_a_duplicate_of_sha_is_scanned_too():
    """That line is exactly where the director cites the work it claims to be
    distinct from, so it is the line most likely to name an already-landed
    commit - excluding it would blind the guard to the measured incident."""
    body = "NOT-A-DUPLICATE-OF: 2c281443 | distinct because nothing\n"
    found = executor.grounding_findings(body, **_Git(landed=["2c281443"]).kwargs())
    assert [f.token for f in found] == ["2c281443"]


def test_an_unresolvable_hex_token_is_not_a_finding():
    """FALSE-POSITIVE side. `deadbeefcafe` matches the hex shape and is not a
    commit; resolution is the only thing that separates the two."""
    g = _Git()
    assert executor.grounding_findings(_GROUNDED_CLEAN, **g.kwargs()) == []
    assert "deadbeefcafe" in g.probed, "it must be probed and then rejected, not skipped"


def test_a_future_or_unknown_sha_that_resolves_but_is_not_merged_is_not_a_finding():
    """A directive may legitimately name a commit that is not in this history (a
    sibling repo's sha, a branch tip). Resolving is not landing."""
    body = "Mirror what LW did in 8a7d61a1 on its side.\n"
    assert executor.grounding_findings(body, **_Git(unmerged=["8a7d61a1"]).kwargs()) == []


def test_bare_decimal_and_word_tokens_are_never_probed():
    """LEDGER-TOP=1074, `cycle 4` and a 13061 test count share a line with the
    HEAD claim. Anything under git's own 7-char abbreviation is not a sha."""
    g = _Git()
    executor.grounding_findings(_GROUNDED_CLEAN, **g.kwargs())
    assert "1074" not in g.probed
    assert "13061" not in g.probed
    assert all(len(t) >= 7 for t in g.probed)


def test_the_claimed_head_is_not_double_reported_as_already_landed():
    """One fault, one finding. The stale HEAD is a grounding assertion, not
    proposed work, and it is already named by the stale-head finding."""
    found = executor.grounding_findings(_R200, **_Git(landed=["f173ce39"]).kwargs())
    assert [f.token for f in found].count("f173ce39") == 1


def test_an_unverifiable_head_is_recorded_not_silently_passed():
    """The failure mode this file keeps pinning: a guard that degrades into
    always-passing on every input it cannot check. The directive asserted a
    checkable fact and the check could not run - that is not a pass."""
    found = executor.grounding_findings(_R200, **_Git(head="").kwargs())
    assert found and found[0].kind == "unverified"


def test_a_directive_with_no_grounding_prefix_and_no_shas_is_not_judged():
    assert executor.grounding_findings(
        "Edit ops/loop/executor.py. Bump ENGINE_VERSION to 1.261.0.",
        **_Git().kwargs()) == []


def test_the_override_names_the_stale_head_and_the_landed_shas():
    found = executor.grounding_findings(_R200, **_Git(landed=["f173ce39", "04a5a534"]).kwargs())
    out = executor.reground_directive(_R200, found)
    assert out.startswith(executor.GROUNDING_HEADER)
    assert executor.GROUNDING_MARKER in out
    assert "f173ce39" in out and "04a5a534" in out
    assert _HEAD[:8] in out, "the session cannot re-ground without the real HEAD"
    assert _R200.strip() in out, "the original directive text must survive verbatim"


def test_the_grounding_marker_is_distinct_from_the_other_two():
    """winmutex greps UNSERIALIZED and the disjointness guard greps
    SERIALIZED-DEVIATION; a substring collision would cross the wires."""
    assert "UNSERIALIZED" not in executor.GROUNDING_MARKER
    assert executor.PARALLEL_MARKER not in executor.GROUNDING_MARKER
    assert executor.GROUNDING_MARKER not in executor.PARALLEL_MARKER
    assert executor.GROUNDING_MARKER.startswith("executor: ")


def test_enforce_leaves_a_correctly_grounded_directive_byte_identical(
        monkeypatch: pytest.MonkeyPatch):
    g = _Git()
    monkeypatch.setattr(executor, "_git_head", lambda root: g.head)
    monkeypatch.setattr(executor, "_git_resolve", lambda root, tok: g.resolve(tok))
    monkeypatch.setattr(executor, "_git_is_ancestor", lambda root, a, b: g.is_ancestor(a, b))
    logs, written = [], {}
    out = executor.enforce_directive_grounding(
        4, _GROUNDED_CLEAN, log=logs.append,
        awrite=lambda p, t: written.__setitem__(Path(p).name, t), ctl=Path("."))
    assert out == _GROUNDED_CLEAN
    assert logs == [] and written == {}


def test_enforce_rewrites_directive_md_and_records_the_finding(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    g = _Git(landed=["f173ce39", "04a5a534"])
    monkeypatch.setattr(executor, "_git_head", lambda root: g.head)
    monkeypatch.setattr(executor, "_git_resolve", lambda root, tok: g.resolve(tok))
    monkeypatch.setattr(executor, "_git_is_ancestor", lambda root, a, b: g.is_ancestor(a, b))
    logs, written = [], {}
    out = executor.enforce_directive_grounding(
        7, _R200, log=logs.append,
        awrite=lambda p, t: written.__setitem__(Path(p).name, t), ctl=tmp_path)
    assert logs and executor.GROUNDING_MARKER in logs[0]
    assert written["directive.md"] == out
    assert out != _R200


def test_the_grounding_override_is_advisory_and_does_not_abort_the_cycle(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Same posture as the disjointness precedent: the header is advice on top of
    a directive that still runs. Deleting it or stopping the cycle would turn a
    heuristic string match into a run-killer."""
    g = _Git(landed=["f173ce39"])
    monkeypatch.setattr(executor, "_git_head", lambda root: g.head)
    monkeypatch.setattr(executor, "_git_resolve", lambda root, tok: g.resolve(tok))
    monkeypatch.setattr(executor, "_git_is_ancestor", lambda root, a, b: g.is_ancestor(a, b))
    r = _Rec(tmp_path, {"sha": "d" * 40, "tests_pass": "1", "regressions": False,
                        "summary": "s"})
    ex = executor.build({"channel": "ahk", "cycle_deadline_sec": 5, "repo_root": str(tmp_path)},
                        tmp_path, **r.deps())
    rec = ex.run(8, _R200, "director")
    assert r.stopped == [], "a grounding finding must not stop the run"
    assert rec.sha == "d" * 40
    assert _R200.strip() in r.written["directive.md"]


def test_ahk_channel_rewrites_directive_md_on_a_stale_grounding(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Wiring: the director path types only the opener, so the correction has to
    land in control/directive.md or the session never sees it."""
    g = _Git(landed=["f173ce39", "04a5a534"])
    monkeypatch.setattr(executor, "_git_head", lambda root: g.head)
    monkeypatch.setattr(executor, "_git_resolve", lambda root, tok: g.resolve(tok))
    monkeypatch.setattr(executor, "_git_is_ancestor", lambda root, a, b: g.is_ancestor(a, b))
    r = _Rec(tmp_path, {"sha": "d" * 40})
    ex = executor.build({"channel": "ahk", "cycle_deadline_sec": 5, "repo_root": str(tmp_path)},
                        tmp_path, **r.deps())
    ex.run(5, _R200, "director")
    assert executor.GROUNDING_HEADER in r.written["directive.md"]
    assert any(executor.GROUNDING_MARKER in m for m in r.logs)


def test_sdk_channel_checks_the_grounding_too(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """It matters MORE here: a `-p` run is unattended, so nobody is reading the
    directive and noticing it re-issues landed work."""
    g = _Git(landed=["f173ce39", "04a5a534"])
    monkeypatch.setattr(executor, "_git_head", lambda root: g.head)
    monkeypatch.setattr(executor, "_git_resolve", lambda root, tok: g.resolve(tok))
    monkeypatch.setattr(executor, "_git_is_ancestor", lambda root, a, b: g.is_ancestor(a, b))
    payload = json.dumps({"is_error": False, "total_cost_usd": 0.0,
                          "structured_output": {"sha": "a" * 40, "tests_pass": "1",
                                                "regressions": False, "summary": "s"}})
    logs, written = [], {}
    ex = executor.build(
        {"channel": "sdk", "repo_root": str(tmp_path), "cycle_deadline_sec": 60,
         "executor_cmd": _stub_claude(tmp_path, payload)}, tmp_path,
        log=logs.append, stop=lambda m: None,
        awrite=lambda p, t: written.__setitem__(Path(p).name, t))
    ex.run(3, _R200, "director")
    assert any(executor.GROUNDING_MARKER in m for m in logs)
    assert executor.GROUNDING_HEADER in written["directive.md"]


def test_a_clean_directive_is_untouched_on_the_live_repo(tmp_path: Path):
    """FALSE-POSITIVE side against REAL git, not the fake: the default lookups
    must not invent a finding on a directive that names no commits. This is the
    shape every ordinary cycle has."""
    logs, written = [], {}
    body = "Edit ops/loop/executor.py and run tests/test_loop_executor.py.\n"
    out = executor.enforce_directive_grounding(
        1, body, log=logs.append,
        awrite=lambda p, t: written.__setitem__(Path(p).name, t), ctl=tmp_path,
        repo_root=str(ROOT))
    assert out == body and logs == [] and written == {}


def test_the_live_directive_suffix_sha256_pins_are_not_read_as_commits():
    """FALSE-POSITIVE side, measured against real data rather than a fixture.

    ops/loop/config.json's directive_suffix is appended to every directive and
    carries three SHARED_SHA256 file digests. A 64-char hex run has no word
    boundary at position 40, so the 7-to-40 token shape skips them whole - which
    is the difference between this guard being quiet on every live cycle and
    probing git for three digests that can never be commits.
    """
    suffix = json.loads((ROOT / "ops" / "loop" / "config.json").read_text(
        encoding="utf-8")).get("directive_suffix", "")
    assert len(suffix) > 500, "the suffix is the live operator brief - it should be long"
    assert "95077a62527c9764e896e3bd1da9027e5efd2b15631feb725fe6138cee5054f9" in suffix
    g = _Git()
    assert executor.grounding_findings(suffix, **g.kwargs()) == []
    assert g.probed == [], "a 64-char digest must not reach git at all"


def test_the_live_head_lookup_resolves_in_this_repo():
    """The injected lookups are only as good as their real implementations, and a
    silently-empty HEAD would put every directive in the unverified branch."""
    head = executor._git_head(str(ROOT))
    assert len(head) == 40 and all(c in "0123456789abcdef" for c in head)
    assert executor._git_is_ancestor(str(ROOT), head, head)
    assert executor._git_resolve(str(ROOT), head[:8]) == head
    assert executor._git_resolve(str(ROOT), "0" * 12) == ""


# ---- the third grounding field: the director's own [UNVERIFIED] tag ----------
#
# MEASURED 2026-07-27, cycle 13 of this run. The guard above judged two of the
# three mandated fields and abstained on PREMISE-CHECK as "free prose with no
# machine-readable referent". The referent is the TAG: director_prompt.md:18
# makes the director tag every claim [from-digest] or [UNVERIFIED], so an
# [UNVERIFIED] premise is the director declaring its own claim an unknown. Cycle
# 13 shipped two of them, both false on disk (`git diff --cached` was empty and
# winmutex.py was already byte-identical to the inbox copy and already SHA-
# pinned), zero findings fired, and the cycle was a full no-op - the 6th stale-
# premise cycle in 7. Propagating a verdict the director already stamped is not
# inventing one, and this file has pinned four times over that an unknown is
# never a pass (executor.py:188, :213, :478, :558).

# The cycle-13 line, verbatim. The trailing backslash is a source-wrap only - the
# value carries it as ONE line, which is the shape the field is bounded by.
_CYCLE13 = f"""GROUNDED-AGAINST: HEAD={_HEAD[:8]} LEDGER-TOP=1081 CHAIN-LAST=cycle 12
NOT-A-DUPLICATE-OF: LEDGER 1081 | distinct because the inbox apply is not on disk
PREMISE-CHECK: [from-digest] OPERATOR RUN FOCUS requires CYCLE 1 IS THE INBOX APPLY.\
 [UNVERIFIED] staged .githooks changes exist. [UNVERIFIED] moon_sync_inbox holds winmutex.py.from-lw.

# cycle 13 inbox apply
Apply the inbox copy, chmod +x the githooks, pin the SHARED_SHA256.
"""

# The false positive that WILL occur in production: this repo's own ledger rows
# and ORCHESTRATION_PLAN rows carry [UNVERIFIED] in their prose, and the director
# quotes them into the directive body constantly.
_LEDGER_QUOTE_BODY = f"""GROUNDED-AGAINST: HEAD={_HEAD[:8]} LEDGER-TOP=1081 CHAIN-LAST=cycle 12
NOT-A-DUPLICATE-OF: LEDGER 1081 | distinct because executor.py has no premise check
PREMISE-CHECK: the executor reads two of the three grounding fields [from-digest]

# item 1082 - propagate the director's own tag
Context from docs/LEDGER.md, newest first:

- **1081 - loop: the executor deviation stamp (R206)** - the two guards recorded
  their corrections where the director never reads. Rows still tagged [UNVERIFIED]
  in docs/ORCHESTRATION_PLAN.md stay [UNVERIFIED] until a session probes them on
  disk; the live-gated set is UNVERIFIED by construction.
"""


def test_the_cycle_13_premise_check_fires_one_finding_per_self_declared_unknown():
    """The regression that would have caught today. The HEAD is clean and the
    directive names no landed sha, so the old guard saw a perfect directive."""
    found = executor.grounding_findings(_CYCLE13, **_Git().kwargs())
    assert [f.kind for f in found] == ["unverified-premise", "unverified-premise"]
    assert not [f for f in found if f.kind == "stale-head"]
    joined = " | ".join(f.token for f in found)
    assert "staged .githooks changes exist" in joined
    assert "moon_sync_inbox holds winmutex.py.from-lw" in joined
    assert "OPERATOR RUN FOCUS" not in joined, "a [from-digest] claim is not an unknown"


def test_a_premise_check_of_only_from_digest_claims_is_not_a_finding():
    assert executor.grounding_findings(_GROUNDED_CLEAN, **_Git().kwargs()) == []


def test_a_directive_with_no_premise_check_line_is_not_a_finding():
    assert executor.grounding_findings(
        f"GROUNDED-AGAINST: HEAD={_HEAD[:8]} LEDGER-TOP=1081 CHAIN-LAST=none\n"
        "Bump ENGINE_VERSION to 1.261.0.", **_Git().kwargs()) == []


def test_the_word_unverified_in_the_directive_body_is_not_a_finding():
    """FALSE-POSITIVE side, and the one that decides whether this guard is usable:
    the field is scanned, never the body. A ledger row quoted into the directive
    is context, not a premise the director is relying on."""
    assert _LEDGER_QUOTE_BODY.count("[UNVERIFIED]") == 2
    assert executor.grounding_findings(_LEDGER_QUOTE_BODY, **_Git().kwargs()) == []


def test_the_prompt_templates_own_placeholder_is_not_a_premise():
    """A directive about THIS loop quotes director_prompt.md:18 verbatim, template
    angle brackets and all. `<... or [UNVERIFIED]>` carries no claim."""
    body = ("Read ops/loop/director_prompt.md:18, which mandates:\n"
            "    PREMISE-CHECK: <each factual claim you rely on, tagged [from-digest] "
            "or [UNVERIFIED]>\n")
    assert executor.grounding_findings(body, **_Git().kwargs()) == []


def test_a_trailing_tag_claim_does_not_swallow_the_preceding_from_digest_claim():
    """The tag can END its claim, and the claim before it may be a DIFFERENT one
    the director already verified. Folding them together quotes a [from-digest]
    fact back at the session as something to go and check - the wasted work this
    guard exists to prevent, dressed up as a correction."""
    body = "PREMISE-CHECK: [from-digest] the loop is armed. winmutex still old [UNVERIFIED]\n"
    found = executor.grounding_findings(body, **_Git().kwargs())
    assert [f.token for f in found] == ["winmutex still old"]
    assert "the loop is armed" not in found[0].detail


def test_two_trailing_tag_claims_on_one_line_are_attributed_separately():
    """The ambiguous shape underneath the same defect: with the tag AFTER the
    claim, the text following a tag belongs to the NEXT claim, not to it."""
    body = ("PREMISE-CHECK: the githooks are executable [UNVERIFIED]. "
            "the inbox holds the file [UNVERIFIED]\n")
    found = executor.grounding_findings(body, **_Git().kwargs())
    assert [f.token for f in found] == ["the githooks are executable",
                                        "the inbox holds the file"]


@pytest.mark.parametrize("claim", [
    "e.g. the hooks are missing",
    "i.e. the inbox is empty",
    "cf. the R206 note",
    "etc. still pending",
    "vs. the main tree",
    "no. 5 is stale",
])
def test_an_abbreviation_inside_a_claim_does_not_drop_the_claim(claim: str):
    """An abbreviation carries a dot AND the space after it, so anything cutting
    claims on sentence punctuation cuts here too. A claim that VANISHES is the
    failure direction this guard exists to close, and this reaches it from the
    tag position the live directives actually use."""
    found = executor.grounding_findings(f"PREMISE-CHECK: [UNVERIFIED] {claim}\n",
                                        **_Git().kwargs())
    assert [f.token for f in found] == [claim]


def test_an_abbreviation_does_not_drop_the_claims_after_it():
    """Per-claim, not per-line: one abbreviation must not cost the whole field."""
    body = ("PREMISE-CHECK: [UNVERIFIED] e.g. the hooks are missing. "
            "[UNVERIFIED] the inbox holds the file\n")
    found = executor.grounding_findings(body, **_Git().kwargs())
    assert [f.token for f in found] == ["e.g. the hooks are missing",
                                        "the inbox holds the file"]


def test_a_short_claim_is_still_a_claim():
    """A length floor is the wrong instrument for rejecting the prompt template -
    it silently drops real claims that happen to be terse, which is the same
    dropped-claim failure by another route."""
    for short in ("CI", "abc", "the DS suite"):
        found = executor.grounding_findings(f"PREMISE-CHECK: [UNVERIFIED] {short}\n",
                                            **_Git().kwargs())
        assert [f.token for f in found] == [short]


def test_a_block_quoted_premise_line_above_the_real_field_does_not_shadow_it():
    """This loop's directives quote the PRIOR directive routinely, indented. A
    first-match scan reads the quote and goes silent on the live field - a false
    NEGATIVE, which is the direction this whole guard exists to close."""
    body = f"""GROUNDED-AGAINST: HEAD={_HEAD[:8]} LEDGER-TOP=1081 CHAIN-LAST=cycle 12
NOT-A-DUPLICATE-OF: LEDGER 1081 | distinct because the apply is not on disk
The cycle 12 directive opened:

    PREMISE-CHECK: [from-digest] the executor seam is under test

PREMISE-CHECK: [UNVERIFIED] the githooks are executable on disk

Apply the inbox copy.
"""
    found = executor.grounding_findings(body, **_Git().kwargs())
    assert [f.token for f in found] == ["the githooks are executable on disk"]


def test_the_same_premise_quoted_twice_is_reported_once():
    """The routine cost of scanning every field instead of the first: a re-quoted
    prior directive repeats the SAME premise, and a duplicate bullet is noise the
    session learns to skim past."""
    body = ("    PREMISE-CHECK: [UNVERIFIED] the githooks are executable\n"
            "PREMISE-CHECK: [UNVERIFIED] the githooks are executable\n")
    found = executor.grounding_findings(body, **_Git().kwargs())
    assert [f.token for f in found] == ["the githooks are executable"]


def test_controller_log_tells_a_premise_finding_from_a_stale_head_one(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """GROUNDING_MARKER stays ONE grep token - operators grep it and the existing
    controller.log history carries it - so the DETAIL after it is what has to
    disambiguate. A log line that only says STALE-GROUNDING over a HEAD the same
    function just measured as current is a lie to the only human reader."""
    g = _Git(landed=["f173ce39"])
    monkeypatch.setattr(executor, "_git_head", lambda root: g.head)
    monkeypatch.setattr(executor, "_git_resolve", lambda root, tok: g.resolve(tok))
    monkeypatch.setattr(executor, "_git_is_ancestor", lambda root, a, b: g.is_ancestor(a, b))
    premise_logs, head_logs = [], []
    executor.enforce_directive_grounding(13, _CYCLE13, log=premise_logs.append)
    executor.enforce_directive_grounding(14, _R200, log=head_logs.append)
    assert "UNVERIFIED-PREMISE" in premise_logs[0]
    assert "stale digest" not in premise_logs[0]
    assert "stale digest" in head_logs[0]


def test_the_premise_finding_count_is_capped():
    """Same reason _MAX_SHA_PROBES exists: the loop is unattended, and one
    pathological line must not bury the directive under its own correction."""
    line = " ".join(f"[UNVERIFIED] claim number {i} is not on disk." for i in range(20))
    found = executor.grounding_findings(f"PREMISE-CHECK: {line}\n", **_Git().kwargs())
    assert len(found) == executor._MAX_PREMISE_FINDINGS < 20


def test_the_override_on_premise_only_findings_does_not_claim_the_head_is_stale():
    """The head is FINE on this directive. A correction that opens by calling it
    stale is the guard lying about what it measured."""
    found = executor.grounding_findings(_CYCLE13, **_Git().kwargs())
    out = executor.reground_directive(_CYCLE13, found)
    assert out.startswith(executor.PREMISE_HEADER)
    assert executor.GROUNDING_HEADER not in out
    # The marker is the operator's single grep token for this guard and stays one
    # string, so it is excised before the claim is measured. Everything the SESSION
    # reads has to be free of it.
    prose = out.lower().replace(executor.GROUNDING_MARKER.lower(), "")
    assert "stale" not in prose, "nothing here is stale - do not say it is"
    assert executor.GROUNDING_MARKER in out
    assert "staged .githooks changes exist" in out
    assert "moon_sync_inbox holds winmutex.py.from-lw" in out
    assert "--- ORIGINAL DIRECTIVE FOLLOWS, UNCHANGED ---" in out
    assert _CYCLE13.strip() in out


def test_a_premise_only_override_tells_the_session_what_to_do_on_a_no_op():
    """Matched to the already-landed step: a directive whose premises do not hold
    is a no-op, and a session told only 'verify' will verify and then run it."""
    found = executor.grounding_findings(_CYCLE13, **_Git().kwargs())
    out = executor.reground_directive(_CYCLE13, found)
    assert "on disk" in out.lower()
    assert "NON-duplicate" in out and "say which" in out


def test_a_stale_head_still_wins_the_header_when_both_kinds_fire():
    """_R200 carries both. The head being wrong is the stronger claim and the one
    the session must act on first, so the header must not soften to the premise
    wording."""
    found = executor.grounding_findings(_R200, **_Git(landed=["f173ce39"]).kwargs())
    kinds = {f.kind for f in found}
    assert kinds == {"stale-head", "unverified-premise"}
    assert executor.reground_directive(_R200, found).startswith(executor.GROUNDING_HEADER)


def test_an_unverified_premise_is_not_bucketed_with_the_stale_head_findings():
    """kind is matched exactly at executor.py:528. A prefix/substring bucket would
    print 'the grounding prefix below is stale' over a perfectly current HEAD."""
    found = executor.grounding_findings(_CYCLE13, **_Git().kwargs())
    out = executor.reground_directive(_CYCLE13, found)
    assert "grounding prefix below is stale" not in out


def test_a_premise_only_finding_reaches_the_director_through_the_stamp(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """R206 end to end: controller.log is not a director input, so the correction
    only teaches the component that caused it if it rides the claude.done stamp."""
    g = _Git()
    monkeypatch.setattr(executor, "_git_head", lambda root: g.head)
    monkeypatch.setattr(executor, "_git_resolve", lambda root, tok: g.resolve(tok))
    monkeypatch.setattr(executor, "_git_is_ancestor", lambda root, a, b: g.is_ancestor(a, b))
    r = _Rec(tmp_path, {"sha": "d" * 40, "tests_pass": "13061", "regressions": False,
                        "summary": "applied the inbox"})
    ex = executor.build({"channel": "ahk", "cycle_deadline_sec": 5, "repo_root": str(tmp_path)},
                        tmp_path, **r.deps())
    rec = ex.run(13, _CYCLE13, "director")
    assert r.stopped == [], "an unverified premise must not stop the run"
    assert executor.GROUNDING_MARKER in rec.raw["summary"]
    assert "applied the inbox" in rec.summary
    assert executor.PREMISE_HEADER in r.written["directive.md"]
    assert any(executor.GROUNDING_MARKER in m for m in r.logs)


# ---- the deviation stamp: what actually reaches the DIRECTOR -----------------
#
# MEASURED 2026-07-27, one layer above the two guards above. Both of them correct
# a bad directive and then RECORD the correction - but the only thing either put
# in front of the director was a sentence in the override header asking the
# executing model to state the deviation in its summary line. controller.log is
# not a director input: loop_controller.py:577 dumps the model-authored
# claude.done payload as `=== LAST claude.done ===` and rec.raw is that payload,
# so whether the director ever learned its directive was wrong depended on the
# model volunteering it in prose. A model that silently complies teaches the
# director nothing and it writes the same broken shape again next cycle - which
# is the exact failure both guards' own comments say recording exists to prevent.
# The stamp asks the model for nothing.


def test_no_deviations_leaves_the_summary_byte_identical():
    """Every clean cycle stays untouched; the stamp exists only for deviating ones."""
    assert executor.stamp_deviations("shipped the thing", []) == "shipped the thing"
    assert executor.stamp_deviations("shipped the thing", None) == "shipped the thing"


def test_the_stamp_is_a_prefix_and_the_models_own_summary_survives_after_it():
    out = executor.stamp_deviations("shipped the thing", [f"{executor.PARALLEL_MARKER} sets collide"])
    assert out.startswith(executor.DEVIATION_STAMP)
    assert out.endswith(" | shipped the thing")
    assert executor.PARALLEL_MARKER in out


def test_an_empty_model_summary_leaves_no_dangling_separator():
    """The error paths stamp over "" - a trailing " | " there would read as a
    truncated summary rather than as a cycle that produced none."""
    out = executor.stamp_deviations("", [f"{executor.GROUNDING_MARKER} stale"])
    assert out == f"{executor.DEVIATION_STAMP}: {executor.GROUNDING_MARKER} stale"
    assert not out.endswith("|") and " | " not in out


def test_stamping_twice_is_the_same_as_stamping_once():
    """run() applies it once per record, but the two guards both feed one list -
    a second pass over an already-stamped string must not nest the marker."""
    once = executor.stamp_deviations("s", ["a", "b"])
    assert executor.stamp_deviations(once, ["a", "b"]) == once
    assert once.count(executor.DEVIATION_STAMP) == 1
    assert once == f"{executor.DEVIATION_STAMP}: a; b | s"


def test_the_ahk_channel_stamps_a_deviation_the_model_never_mentioned(tmp_path: Path):
    """The measured shape: the model complies with the serialization and says
    nothing about it. raw is asserted explicitly because raw - not the record -
    is the seam loop_controller dumps into the next director call."""
    r = _Rec(tmp_path, {"sha": "d" * 40, "tests_pass": "13061", "regressions": False,
                        "summary": "ran the three slices, all green"})
    ex = executor.build({"channel": "ahk", "cycle_deadline_sec": 5}, tmp_path, **r.deps())
    rec = ex.run(5, _R196, "director")
    assert executor.DEVIATION_STAMP in rec.summary
    assert executor.PARALLEL_MARKER in rec.summary
    assert "ran the three slices, all green" in rec.summary
    assert executor.PARALLEL_MARKER in rec.raw["summary"]


def test_the_sdk_channel_stamps_a_deviation_the_model_never_mentioned(tmp_path: Path):
    payload = json.dumps({"is_error": False, "total_cost_usd": 0.0,
                          "structured_output": {"sha": "a" * 40, "tests_pass": "13061",
                                                "regressions": False,
                                                "summary": "ran the three slices"}})
    ex = executor.build(
        {"channel": "sdk", "repo_root": str(tmp_path), "cycle_deadline_sec": 60,
         "executor_cmd": _stub_claude(tmp_path, payload)}, tmp_path,
        log=lambda m: None, stop=lambda m: None, awrite=lambda p, t: None)
    rec = ex.run(3, _R196, "director")
    assert executor.DEVIATION_STAMP in rec.summary
    assert executor.PARALLEL_MARKER in rec.summary
    assert "ran the three slices" in rec.summary
    assert executor.PARALLEL_MARKER in rec.raw["summary"]


def test_a_clean_cycle_carries_the_models_summary_and_nothing_else(tmp_path: Path):
    r = _Rec(tmp_path, {"sha": "d" * 40, "tests_pass": "13061", "regressions": False,
                        "summary": "shipped item 7"})
    ex = executor.build({"channel": "ahk", "cycle_deadline_sec": 5}, tmp_path, **r.deps())
    rec = ex.run(5, _DISJOINT, "fixed")
    assert rec.summary == "shipped item 7"
    assert rec.raw["summary"] == "shipped item 7"


def test_the_grounding_guard_stamps_the_deviation_too(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Second instance of the same defect class: this guard's correction was just
    as invisible to the director, and it is the guard whose measured incident WAS
    the director re-issuing landed work."""
    g = _Git(landed=["f173ce39", "04a5a534"])
    monkeypatch.setattr(executor, "_git_head", lambda root: g.head)
    monkeypatch.setattr(executor, "_git_resolve", lambda root, tok: g.resolve(tok))
    monkeypatch.setattr(executor, "_git_is_ancestor", lambda root, a, b: g.is_ancestor(a, b))
    r = _Rec(tmp_path, {"sha": "d" * 40, "tests_pass": "13061", "regressions": False,
                        "summary": "applied the inbox"})
    ex = executor.build({"channel": "ahk", "cycle_deadline_sec": 5, "repo_root": str(tmp_path)},
                        tmp_path, **r.deps())
    rec = ex.run(8, _R200, "director")
    assert executor.GROUNDING_MARKER in rec.summary
    assert executor.GROUNDING_MARKER in rec.raw["summary"]
    assert "applied the inbox" in rec.summary


def test_deviations_do_not_leak_from_one_cycle_into_the_next(tmp_path: Path):
    """The executors outlive the cycle - the controller builds one and calls run()
    per cycle - so an unreset list would stamp every later clean cycle with cycle
    1's deviation and teach the director a fault that is not there."""
    r = _Rec(tmp_path, {"sha": "d" * 40, "tests_pass": "1", "regressions": False,
                        "summary": "cycle one"})
    ex = executor.build({"channel": "ahk", "cycle_deadline_sec": 5}, tmp_path, **r.deps())
    first = ex.run(1, _R196, "director")
    assert executor.DEVIATION_STAMP in first.summary
    r.done = {"sha": "e" * 40, "tests_pass": "1", "regressions": False,
              "summary": "cycle two"}
    second = ex.run(2, _DISJOINT, "fixed")
    assert second.summary == "cycle two"
    assert executor.DEVIATION_STAMP not in second.summary
    assert executor.DEVIATION_STAMP not in second.raw["summary"]


# The two tests above hand the ahk channel a payload carrying a `summary` key.
# The REAL producer does not: ops/loop/done_sentinel.py writes exactly cycle /
# sha / tests_pass / regressions, and claude_stub.py the same. So every live ahk
# cycle takes the branch neither of them exercises, which is the one worth
# pinning - a stamp that writes unconditionally would add `"summary": ""` to the
# director's context on every clean cycle, a shape change to the seam rather than
# a record of anything.


def test_a_clean_ahk_cycle_does_not_invent_a_summary_the_sentinel_never_wrote(tmp_path: Path):
    r = _Rec(tmp_path, {"sha": "d" * 40, "tests_pass": "13648", "regressions": False})
    ex = executor.build({"channel": "ahk", "cycle_deadline_sec": 5}, tmp_path, **r.deps())
    rec = ex.run(5, _DISJOINT, "fixed")
    assert rec.summary == ""
    assert "summary" not in rec.raw, "raw is the director's context - do not widen it"
    assert set(rec.raw) == {"sha", "tests_pass", "regressions"}


def test_a_deviating_ahk_cycle_stamps_although_the_sentinel_writes_no_summary(tmp_path: Path):
    """The live shape of the defect this whole section closes: no model prose to
    append to, and the correction still has to reach the director."""
    r = _Rec(tmp_path, {"sha": "d" * 40, "tests_pass": "13648", "regressions": False})
    ex = executor.build({"channel": "ahk", "cycle_deadline_sec": 5}, tmp_path, **r.deps())
    rec = ex.run(5, _R196, "director")
    assert rec.raw["summary"] == rec.summary
    assert executor.PARALLEL_MARKER in rec.raw["summary"]
    assert not rec.summary.endswith(" | "), "no dangling separator over an absent summary"


def test_an_sdk_failure_carries_the_stamp_where_the_controller_actually_reads(tmp_path: Path):
    """A cycle that deviated and then died. The controller takes `rec.raw` and
    nothing else off the record, so a stamp living only on DoneRecord.summary
    would be invisible on the one branch that has no model prose at all."""
    payload = json.dumps({"is_error": True, "result": "boom", "total_cost_usd": 0.0})
    ex = executor.build(
        {"channel": "sdk", "repo_root": str(tmp_path), "cycle_deadline_sec": 60,
         "executor_cmd": _stub_claude(tmp_path, payload)}, tmp_path,
        log=lambda m: None, stop=lambda m: None, awrite=lambda p, t: None)
    rec = ex.run(3, _R196, "director")
    assert rec.error
    assert executor.PARALLEL_MARKER in rec.raw["summary"]


def test_a_clean_sdk_failure_leaves_raw_empty_exactly_as_before(tmp_path: Path):
    payload = json.dumps({"is_error": True, "result": "boom", "total_cost_usd": 0.0})
    ex = executor.build(
        {"channel": "sdk", "repo_root": str(tmp_path), "cycle_deadline_sec": 60,
         "executor_cmd": _stub_claude(tmp_path, payload)}, tmp_path,
        log=lambda m: None, stop=lambda m: None, awrite=lambda p, t: None)
    rec = ex.run(3, _DISJOINT, "fixed")
    assert rec.error
    assert rec.raw == {}
    assert rec.summary == ""


# ---- the OTHER premise tag: [from-digest] over a path that is on disk --------
#
# MEASURED 2026-07-27, cycle 15 of this run. The guard above skips every
# [from-digest] claim outright (executor.py: `if hit.group(1).lower() != tag`),
# and as far as R208 goes that is correct - the director stamped those claims
# KNOWN, and the executor does not judge whether a semantic claim is true.
#
# Cycle 15's entire directive rested on one of them, verbatim:
#   PREMISE-CHECK: [from-digest] LAST AUDIT reports VERDICT: REGRESS for
#   corrupted uses refs in docs-guards.yml.
# and it was false. `grep -rn "uses:" .github/workflows/` returns 10 refs, every
# one a real version tag (actions/checkout@v6, actions/setup-python@v6,
# actions/cache@v4, CodSpeedHQ/action@v4); zero match the corrupted
# `@agents\...\test_x.py` shape the digest described; and `gh run list` shows
# docs-guards run 30289333992 SUCCESS at HEAD 98f29111. The claim came out of a
# model-authored audit digest, reached the executor with zero friction because of
# the tag, and burned the whole cycle.
#
# The fix is not a verdict - the executor still cannot know whether the claim
# holds, and it must not pretend to. It is the one mechanical fact available:
# the claim NAMED A FILE, that file is in this tree, so go and read it. Silence
# stays the default for every digest claim that names none.

# The cycle-15 directive. The PREMISE-CHECK, VERDICT and dispatch lines are
# verbatim off ops/loop/control/directive.md as the director emitted them; only
# the claimed HEAD is swapped to the fixture's, so the finding under test is the
# only one that fires and this reads as a premise incident rather than a stale
# one.
_CYCLE15 = f"""GROUNDED-AGAINST: HEAD={_HEAD[:8]} LEDGER-TOP=1083 CHAIN-LAST=cycle 14
NOT-A-DUPLICATE-OF: cycle 14 | distinct because this fixes docs-guards.yml corruption
PREMISE-CHECK: [from-digest] LAST AUDIT reports VERDICT: REGRESS for corrupted uses refs in docs-guards.yml.

ENGINE-IMPACT: NONE - yaml workflow fix only.

VERDICT: REGRESS. LAST AUDIT states .github/workflows/docs-guards.yml has invalid action refs
(lines 62, 69) like `@agents\\daemon_slayer\\tests\\test_x.py` instead of correct version tags (`@v4`).
Fix this regression FIRST. Restate the failure. Restore real action tags.

Direct 1 worktree subagent. No fan-out. Agent owns .github/workflows/docs-guards.yml.
"""


class _Paths:
    """A repo-path resolver over a fixed set of files that exist.

    Injected for the same reason resolve/is_ancestor are, and with the same half
    of the contract under test: `asked` records which tokens were probed at all,
    because a guard that hands every prose word to a path lookup is a guard that
    costs a subprocess per word of a directive.

    Answers a bare basename as well as a fully-spelled path, which is what the
    live resolver does and what the measured cycle-15 premise needs - that field
    says `docs-guards.yml` while the file is .github/workflows/docs-guards.yml.
    """

    def __init__(self, *known: str):
        self.known = list(known)
        self.asked: list = []

    def resolve(self, token: str) -> str:
        self.asked.append(token)
        t = token.replace("\\", "/").lower()
        for p in self.known:
            if p.lower() == t or p.lower().endswith("/" + t):
                return p
        return ""


def test_the_cycle_15_from_digest_premise_names_the_file_it_is_about():
    """The regression that would have caught cycle 15. The HEAD is clean, the
    directive names no landed sha, and every prior guard reads it as perfect."""
    p = _Paths(".github/workflows/docs-guards.yml")
    found = executor.grounding_findings(_CYCLE15, resolve_path=p.resolve, **_Git().kwargs())
    assert [f.kind for f in found] == ["digest-premise"]
    assert found[0].paths == (".github/workflows/docs-guards.yml",)
    assert ".github/workflows/docs-guards.yml" in found[0].detail
    assert "LAST AUDIT reports" in found[0].token


def test_the_cycle_15_finding_instructs_a_re_read_and_never_calls_the_claim_false():
    """The R208 line, which this finding may not cross: the executor did not open
    the file and has no standing to say whether the premise holds. It says where
    to look. A guard that invents a verdict is the failure the abstention on
    PREMISE-CHECK was guarding against in the first place."""
    p = _Paths(".github/workflows/docs-guards.yml")
    found = executor.grounding_findings(_CYCLE15, resolve_path=p.resolve, **_Git().kwargs())
    detail = found[0].detail.lower()
    assert "re-read" in detail
    for verdict in ("is false", "does not hold", "is wrong", "is not true", "stale"):
        assert verdict not in detail


def test_without_a_resolver_the_pure_function_raises_no_digest_finding():
    """Purity forces this: grounding_findings may not touch the filesystem, so
    with no probe injected there is no path to name and silence is the only
    honest output. What keeps that from becoming an always-passing guard is the
    production-caller test below, not a default buried in here."""
    assert executor.grounding_findings(_CYCLE15, **_Git().kwargs()) == []


def test_a_from_digest_claim_naming_no_path_is_silent():
    """The common case by a wide margin, and the reason this guard is usable at
    all: most digest-sourced claims are counts and states, not files."""
    p = _Paths(".github/workflows/docs-guards.yml")
    for claim in ("13061 tests pass", "the loop is armed", "LAST AUDIT reports VERDICT: PASS"):
        body = f"PREMISE-CHECK: [from-digest] {claim}\n"
        assert executor.grounding_findings(
            body, resolve_path=p.resolve, **_Git().kwargs()) == [], claim


def test_a_from_digest_claim_naming_a_path_that_is_not_on_disk_is_silent():
    """EXISTENCE is the whole false-positive defence. A path-shaped token that is
    not in the tree gives the session nothing to re-read, so naming it would be a
    bullet that costs attention and buys nothing."""
    p = _Paths(".github/workflows/docs-guards.yml")
    body = "PREMISE-CHECK: [from-digest] ops/loop/guard_that_never_existed.py carries the fix\n"
    assert executor.grounding_findings(body, resolve_path=p.resolve, **_Git().kwargs()) == []
    assert "ops/loop/guard_that_never_existed.py" in p.asked, (
        "it must be probed and then rejected, not skipped by shape")


def test_prose_words_in_a_digest_claim_are_never_handed_to_the_path_probe():
    """The other half of the same contract: the probe is a filesystem or index
    lookup, so a claim's ordinary words must not each become one."""
    p = _Paths(".github/workflows/docs-guards.yml")
    executor.grounding_findings(
        "PREMISE-CHECK: [from-digest] the last audit says the workflow is corrupted\n",
        resolve_path=p.resolve, **_Git().kwargs())
    assert p.asked == []


def test_a_mixed_premise_line_attributes_each_tag_to_its_own_kind():
    """One line, both tags. They are different findings with different remedies -
    a self-declared unknown has to be PROVEN before the work runs, a digest claim
    has to be RE-READ - so folding them into one kind sends half of them the
    wrong instruction."""
    p = _Paths(".github/workflows/docs-guards.yml")
    body = ("PREMISE-CHECK: [from-digest] the audit flags .github/workflows/docs-guards.yml. "
            "[UNVERIFIED] the staged .githooks changes exist\n")
    found = executor.grounding_findings(body, resolve_path=p.resolve, **_Git().kwargs())
    assert [f.kind for f in found] == ["unverified-premise", "digest-premise"]
    assert found[0].token == "the staged .githooks changes exist"
    assert found[0].paths == ()
    assert found[1].paths == (".github/workflows/docs-guards.yml",)
    out = executor.reground_directive(body, found)
    assert out.startswith(executor.PREMISE_HEADER), (
        "a self-declared unknown is the stronger claim and keeps the header")
    assert ".github/workflows/docs-guards.yml" in out


def test_the_unverified_premise_scan_is_unchanged_by_the_digest_scan():
    """Regression pin on the older half. _field_claims is now shared by both
    tags, and a generalization that shifted a claim boundary by one character
    would change what every cycle-13-shaped directive reports."""
    p = _Paths(".github/workflows/docs-guards.yml", "ops/loop/winmutex.py")
    found = executor.grounding_findings(_CYCLE13, resolve_path=p.resolve, **_Git().kwargs())
    assert [f.kind for f in found] == ["unverified-premise", "unverified-premise"]
    assert [f.token for f in found] == ["staged .githooks changes exist",
                                        "moon_sync_inbox holds winmutex.py.from-lw"]
    assert executor._unverified_premises(_CYCLE13) == [f.token for f in found]


def test_the_digest_override_names_the_path_and_asserts_nothing_about_the_claim():
    """What the SESSION reads. It has to carry the file to open, and it may not
    carry a verdict the executor never measured - a correction that overstates
    what it checked is discounted by the next model that reads one."""
    p = _Paths(".github/workflows/docs-guards.yml")
    found = executor.grounding_findings(_CYCLE15, resolve_path=p.resolve, **_Git().kwargs())
    out = executor.reground_directive(_CYCLE15, found)
    assert out.startswith(executor.DIGEST_HEADER)
    assert executor.GROUNDING_HEADER not in out and executor.PREMISE_HEADER not in out
    assert executor.GROUNDING_MARKER in out
    assert ".github/workflows/docs-guards.yml" in out
    prose = out.lower().replace(executor.GROUNDING_MARKER.lower(), "")
    for verdict in ("is false", "does not hold", "is wrong", "is not true", "stale"):
        assert verdict not in prose, "the executor did not open the file - do not judge it"
    assert "re-read" in prose
    assert "--- ORIGINAL DIRECTIVE FOLLOWS, UNCHANGED ---" in out
    assert _CYCLE15.strip() in out


def test_the_digest_kind_is_not_bucketed_with_the_self_declared_unknowns():
    """Exact kind matches, never a prefix or substring test - the same trap
    "unverified-premise" already sets next to "unverified". Bucketing a digest
    claim as an unknown would print "the directive declared these premises
    UNKNOWN itself" over a claim the director explicitly said it sourced."""
    p = _Paths(".github/workflows/docs-guards.yml")
    found = executor.grounding_findings(_CYCLE15, resolve_path=p.resolve, **_Git().kwargs())
    out = executor.reground_directive(_CYCLE15, found)
    assert "declared these premises UNKNOWN" not in out
    assert "grounding prefix below is stale" not in out


def test_a_stale_head_still_wins_the_header_over_a_digest_premise():
    """Same precedence rule the unverified premise already follows: the head
    being wrong is the claim the session must resolve first."""
    p = _Paths(".github/workflows/docs-guards.yml")
    body = _CYCLE15.replace(_HEAD[:8], "f173ce39")
    found = executor.grounding_findings(body, resolve_path=p.resolve,
                                        **_Git(landed=["f173ce39"]).kwargs())
    assert {f.kind for f in found} == {"stale-head", "digest-premise"}
    assert executor.reground_directive(body, found).startswith(executor.GROUNDING_HEADER)


@pytest.mark.parametrize("spelling", [
    "`.github/workflows/docs-guards.yml`",
    "(.github/workflows/docs-guards.yml)",
    "'.github/workflows/docs-guards.yml',",
    '".github/workflows/docs-guards.yml".',
    "[.github/workflows/docs-guards.yml]",
])
def test_a_quoted_or_bracketed_path_token_is_still_extracted(spelling: str):
    """Directives spell paths inside backticks, parens and quotes constantly, and
    the trailing comma or period is sentence punctuation. A leading dot is NOT -
    .github and .githooks both start with one - so the trim is asymmetric."""
    p = _Paths(".github/workflows/docs-guards.yml")
    found = executor.grounding_findings(
        f"PREMISE-CHECK: [from-digest] the audit flags {spelling} at line 62\n",
        resolve_path=p.resolve, **_Git().kwargs())
    assert [f.paths for f in found] == [(".github/workflows/docs-guards.yml",)]


def test_the_digest_finding_count_is_capped():
    """Same reason _MAX_SHA_PROBES exists: every finding is a line PREPENDED to
    the directive, so one pathological premise line must not bury it."""
    p = _Paths("ops/loop/executor.py")
    line = " ".join(f"[from-digest] claim {i} about ops/loop/executor.py in cycle {i}."
                    for i in range(20))
    found = executor.grounding_findings(f"PREMISE-CHECK: {line}\n",
                                        resolve_path=p.resolve, **_Git().kwargs())
    assert len(found) == executor._MAX_PREMISE_FINDINGS < 20


def test_the_same_digest_premise_quoted_twice_is_reported_once():
    """These directives block-quote the prior one routinely; a duplicate bullet is
    noise the session learns to skim, which is how a correction stops being read."""
    p = _Paths(".github/workflows/docs-guards.yml")
    body = ("    PREMISE-CHECK: [from-digest] the audit flags docs-guards.yml\n"
            "PREMISE-CHECK: [from-digest] the audit flags docs-guards.yml\n")
    found = executor.grounding_findings(body, resolve_path=p.resolve, **_Git().kwargs())
    assert [f.token for f in found] == ["the audit flags docs-guards.yml"]


def test_the_live_resolver_answers_a_repo_relative_path_and_a_bare_basename():
    """Against the real tree, because the injected probe is only as good as the
    implementation the production caller hands it.

    The basename branch is not a convenience: the measured cycle-15 field says
    `docs-guards.yml` and the file is .github/workflows/docs-guards.yml, so a
    root-relative-only probe would have been silent on the one incident this
    guard exists to close.
    """
    assert executor._repo_path(str(ROOT), ".github/workflows/docs-guards.yml") == \
        ".github/workflows/docs-guards.yml"
    assert executor._repo_path(str(ROOT), "docs-guards.yml") == \
        ".github/workflows/docs-guards.yml"
    assert executor._repo_path(str(ROOT), "guard-that-never-existed.yml") == ""
    assert executor._repo_path(str(ROOT), "") == ""
    assert executor._repo_path(str(ROOT), "ops/loop") == "", (
        "a directory is not something to re-read - the finding points at a file")


def test_the_production_caller_injects_a_real_path_probe(tmp_path: Path):
    """The pure function goes silent with no resolver, so the thing that has to be
    pinned is that the ONE production caller always hands it a real one - against
    the real tree, end to end, on the real cycle-15 text."""
    real = executor._git_head(str(ROOT))
    body = _CYCLE15.replace(_HEAD[:8], real[:8])
    logs, written = [], {}
    out = executor.enforce_directive_grounding(
        15, body, log=logs.append,
        awrite=lambda p, t: written.__setitem__(Path(p).name, t), ctl=tmp_path,
        repo_root=str(ROOT))
    assert out.startswith(executor.DIGEST_HEADER), (
        "the head is current and no sha has landed - this is a premise finding only")
    assert ".github/workflows/docs-guards.yml" in out
    assert written["directive.md"] == out
    assert logs and "FROM-DIGEST-PREMISE" in logs[0]


def test_an_ordinary_live_directive_raises_no_digest_finding_on_the_real_tree(tmp_path: Path):
    """FALSE-POSITIVE side against real git and the real filesystem. The shape
    every ordinary cycle has must stay byte-identical, or this guard fires on
    every cycle and is ignored by the third."""
    real = executor._git_head(str(ROOT))
    body = (f"GROUNDED-AGAINST: HEAD={real[:8]} LEDGER-TOP=1083 CHAIN-LAST=cycle 14\n"
            "PREMISE-CHECK: [from-digest] the suite is green at 13061 tests\n\n"
            "Edit ops/loop/executor.py and run tests/test_loop_executor.py.\n")
    logs, written = [], {}
    out = executor.enforce_directive_grounding(
        1, body, log=logs.append,
        awrite=lambda p, t: written.__setitem__(Path(p).name, t), ctl=tmp_path,
        repo_root=str(ROOT))
    assert out == body and logs == [] and written == {}


def test_a_digest_premise_reaches_the_director_through_the_stamp(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """R206 again: controller.log is not a director input, and the director is the
    component that wrote the digest-sourced premise. If the correction does not
    ride the claude.done stamp it writes the same shape again next cycle."""
    g = _Git()
    monkeypatch.setattr(executor, "_git_head", lambda root: g.head)
    monkeypatch.setattr(executor, "_git_resolve", lambda root, tok: g.resolve(tok))
    monkeypatch.setattr(executor, "_git_is_ancestor", lambda root, a, b: g.is_ancestor(a, b))
    monkeypatch.setattr(executor, "_repo_path",
                        lambda root, tok: ".github/workflows/docs-guards.yml"
                        if tok.endswith("docs-guards.yml") else "")
    r = _Rec(tmp_path, {"sha": "d" * 40, "tests_pass": "13061", "regressions": False,
                        "summary": "fixed the workflow"})
    ex = executor.build({"channel": "ahk", "cycle_deadline_sec": 5, "repo_root": str(tmp_path)},
                        tmp_path, **r.deps())
    rec = ex.run(15, _CYCLE15, "director")
    assert r.stopped == [], "a digest premise must not stop the run"
    assert executor.GROUNDING_MARKER in rec.raw["summary"]
    assert "fixed the workflow" in rec.summary
    assert executor.DIGEST_HEADER in r.written["directive.md"]
    assert any("FROM-DIGEST-PREMISE" in m for m in r.logs)
