"""The responder's single process seam - flags, timeout, tree kill, kill budget.

WHY THIS EXISTS. Every child process the inbox responder creates is born in
`tools/inbox_responder_procs.py` and nowhere else, so the properties that are
invisible in CI - the console-flash flag on Legion, the per-cycle kill
allowance that keeps the summed timeout under the scheduled task's execution
time limit - have exactly one place to be pinned.

Two of the arms here are the reason the seam is a module rather than an inline
call. The console-flash guard (tests/test_no_console_flash_scheduled_tools.py)
recognises only calls spelled `subprocess.<run|Popen|...>(`, so concentrating
the two literal spawns in one file gives that guard exactly the calls that
matter. And `KillBudget` is load-bearing arithmetic, not tidiness: without it,
a cycle in which every process times out costs 14 kill terms of 60 s each and
blows past the 600 s ETL (spec section 11, the recorded REFUTED figure 1160).
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools import inbox_responder_procs as procs  # noqa: E402

MODULE_REL = "tools/inbox_responder_procs.py"


# ---------------------------------------------------------------------------
# Doubles. A recorder stands in for subprocess.Popen; no test in this file
# creates a real process.
# ---------------------------------------------------------------------------


class FakeProc:
    """A Popen stand-in that records what the seam asked of it."""

    def __init__(self, *, communicate_timeout=False, wait_timeout=False,
                 out=b"stdout-bytes", err=b"stderr-bytes", returncode=0, pid=424242):
        self.pid = pid
        self.returncode = returncode
        self.communicate_calls = []
        self.wait_calls = []
        self.kill_calls = 0
        self._communicate_timeout = communicate_timeout
        self._wait_timeout = wait_timeout
        self._out = out
        self._err = err

    def communicate(self, **kwargs):
        self.communicate_calls.append(kwargs)
        if self._communicate_timeout:
            raise subprocess.TimeoutExpired(cmd="fake", timeout=kwargs.get("timeout"))
        return (self._out, self._err)

    def wait(self, *args, **kwargs):
        self.wait_calls.append((args, kwargs))
        if self._wait_timeout:
            raise subprocess.TimeoutExpired(cmd="fake", timeout=args[0] if args else None)
        return self.returncode

    def kill(self):
        self.kill_calls += 1


class PopenRecorder:
    """Records every (argv, kwargs) and hands back the queued FakeProc."""

    def __init__(self, procs_to_return):
        self._queue = list(procs_to_return)
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if not self._queue:
            raise AssertionError("PopenRecorder called more times than it has procs")
        return self._queue.pop(0)

    @property
    def last_kwargs(self):
        return self.calls[-1][1]


def _install(monkeypatch, *fake_procs):
    rec = PopenRecorder(fake_procs)
    monkeypatch.setattr(procs.subprocess, "Popen", rec)
    assert procs.subprocess.Popen is rec, "the recorder must be in place BEFORE the drive"
    return rec


def _capture(rec_budget, **overrides):
    kwargs = dict(
        cwd=str(ROOT),
        env={"PATH": "x"},
        stdin_bytes=b"envelope",
        timeout_s=7,
        kill_budget=rec_budget,
    )
    kwargs.update(overrides)
    return procs.popen_capture(["fake-exe", "--flag"], **kwargs)


# ---------------------------------------------------------------------------
# The flag
# ---------------------------------------------------------------------------


def test_creation_flags_is_create_no_window_on_nt_and_zero_elsewhere():
    import os
    expected = 0x08000000 if os.name == "nt" else 0
    assert procs.CREATION_FLAGS == expected


def test_popen_call_carries_creationflags_and_the_three_pipes(monkeypatch):
    import os
    rec = _install(monkeypatch, FakeProc())
    _capture(procs.KillBudget(1))

    argv, kwargs = rec.calls[0]
    assert list(argv) == ["fake-exe", "--flag"]
    assert kwargs["creationflags"] == procs.CREATION_FLAGS
    assert kwargs["stdin"] is subprocess.PIPE
    assert kwargs["stdout"] is subprocess.PIPE
    assert kwargs["stderr"] is subprocess.PIPE
    assert kwargs["cwd"] == str(ROOT)
    assert kwargs["env"] == {"PATH": "x"}
    # start_new_session is a POSIX concept - it must be True only off nt.
    assert kwargs["start_new_session"] is (os.name != "nt")
    assert kwargs.get("shell", False) is False


# ---------------------------------------------------------------------------
# The timeout
# ---------------------------------------------------------------------------


def test_communicate_receives_the_timeout_and_the_stdin_bytes(monkeypatch):
    fake = FakeProc()
    _install(monkeypatch, fake)
    _capture(procs.KillBudget(1), timeout_s=13)

    assert len(fake.communicate_calls) == 1
    call = fake.communicate_calls[0]
    assert call["timeout"] == 13
    assert call["input"] == b"envelope"


def test_a_clean_run_reports_the_exit_code_and_no_kill(monkeypatch):
    _install(monkeypatch, FakeProc(returncode=3, out=b"OUT", err=b"ERR"))
    res = _capture(procs.KillBudget(1))

    assert res.exit_code == 3
    assert res.stdout == b"OUT"
    assert res.stderr == b"ERR"
    assert res.timed_out is False
    assert res.survived_kill is False
    assert res.kill_skipped is False
    assert res.exc is None
    assert isinstance(res.wall_ms, int) and res.wall_ms >= 0


def test_timeout_with_a_fresh_budget_tree_kills_then_waits(monkeypatch):
    fake = FakeProc(communicate_timeout=True, pid=9911)
    _install(monkeypatch, fake)
    killed = []
    monkeypatch.setattr(procs, "kill_tree", lambda pid: killed.append(pid))

    res = _capture(procs.KillBudget(1))

    assert killed == [9911], "the first timeout of a cycle gets the FULL tree kill"
    assert fake.wait_calls, "the full sequence waits for the tree to die"
    assert fake.wait_calls[0][0] == (procs.KILL_WAIT_S,)
    assert fake.kill_calls == 0
    assert res.timed_out is True
    assert res.kill_skipped is False
    assert res.survived_kill is False
    assert res.exit_code is None


def test_a_second_timeout_on_the_same_budget_kills_only_and_never_waits(monkeypatch):
    first = FakeProc(communicate_timeout=True, pid=1)
    second = FakeProc(communicate_timeout=True, pid=2)
    _install(monkeypatch, first, second)
    killed = []
    monkeypatch.setattr(procs, "kill_tree", lambda pid: killed.append(pid))

    budget = procs.KillBudget(procs.KILL_ALLOWANCE_PER_CYCLE)
    res_first = _capture(budget)
    res_second = _capture(budget)

    assert killed == [1], "the allowance is spent - the second timeout gets no tree kill"
    assert second.wait_calls == [], "a skipped kill costs 0 s by construction"
    assert second.kill_calls == 1, "proc.kill() only - TerminateProcess on the immediate child"
    assert res_first.kill_skipped is False
    assert res_second.kill_skipped is True
    assert res_second.timed_out is True
    assert res_second.exit_code is None


def test_survived_kill_is_recorded_and_never_raised(monkeypatch):
    fake = FakeProc(communicate_timeout=True, wait_timeout=True, pid=77)
    _install(monkeypatch, fake)
    monkeypatch.setattr(procs, "kill_tree", lambda pid: None)

    res = _capture(procs.KillBudget(1))

    assert res.survived_kill is True
    assert res.timed_out is True
    assert res.kill_skipped is False
    assert res.exit_code is None


def test_a_spawn_that_cannot_start_is_recorded_not_raised(monkeypatch):
    def boom(argv, **kwargs):
        raise FileNotFoundError(2, "no such binary")

    monkeypatch.setattr(procs.subprocess, "Popen", boom)
    res = _capture(procs.KillBudget(1))

    assert res.exc == "FileNotFoundError"
    assert res.exit_code is None
    assert res.timed_out is False
    assert res.stdout == b""


# ---------------------------------------------------------------------------
# The budget
# ---------------------------------------------------------------------------


def test_kill_budget_allows_the_first_n_takes_then_refuses():
    budget = procs.KillBudget(2)
    assert budget.take() is True
    assert budget.take() is True
    assert budget.take() is False
    assert budget.take() is False

    assert procs.KillBudget(0).take() is False


def test_kill_budget_defaults_to_the_per_cycle_allowance():
    budget = procs.KillBudget()
    for _ in range(procs.KILL_ALLOWANCE_PER_CYCLE):
        assert budget.take() is True
    assert budget.take() is False


# ---------------------------------------------------------------------------
# kill_tree
# ---------------------------------------------------------------------------


def test_kill_tree_on_nt_runs_taskkill_with_the_flag_and_a_timeout(monkeypatch):
    monkeypatch.setattr(procs.os, "name", "nt")
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        seen["kwargs"] = kwargs
        return None

    monkeypatch.setattr(procs.subprocess, "run", fake_run)
    procs.kill_tree(4321)

    assert seen["argv"] == ["taskkill", "/F", "/T", "/PID", "4321"]
    assert seen["kwargs"]["creationflags"] == procs.CREATION_FLAGS
    assert seen["kwargs"]["timeout"] == procs.KILL_CMD_TIMEOUT_S


def test_kill_tree_swallows_a_taskkill_failure(monkeypatch):
    monkeypatch.setattr(procs.os, "name", "nt")

    def blow_up(argv, **kwargs):
        raise OSError("taskkill is missing")

    monkeypatch.setattr(procs.subprocess, "run", blow_up)
    procs.kill_tree(4321)  # must not raise


def test_kill_tree_off_nt_signals_the_process_group(monkeypatch):
    monkeypatch.setattr(procs.os, "name", "posix")
    seen = []
    monkeypatch.setattr(procs.os, "killpg", lambda pid, sig: seen.append((pid, sig)), raising=False)

    procs.kill_tree(555)

    assert len(seen) == 1
    assert seen[0][0] == 555


# ---------------------------------------------------------------------------
# The constant census - the task test (S4) reads these three names from HERE.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "value"),
    [("KILL_CMD_TIMEOUT_S", 30), ("KILL_WAIT_S", 30), ("KILL_ALLOWANCE_PER_CYCLE", 1)],
)
def test_each_kill_constant_is_assigned_exactly_once_at_module_level(name, value):
    tree = ast.parse((ROOT / MODULE_REL).read_text(encoding="utf-8"))
    assignments = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        for tgt in node.targets
        if isinstance(tgt, ast.Name) and tgt.id == name
    ]
    assert len(assignments) == 1, (
        f"{name} must be assigned exactly once at module level - the summed-timeout "
        f"arm in tests/test_inbox_responder_task.py derives the ETL bound from this census"
    )
    assert getattr(procs, name) == value


# ---------------------------------------------------------------------------
# The console-flash guard must be green on the new file, and must SEE it.
# ---------------------------------------------------------------------------


def test_the_new_module_is_listed_in_scheduled_spawners():
    from tests import test_no_console_flash_scheduled_tools as guard
    assert MODULE_REL in guard.SCHEDULED_SPAWNERS


def test_the_console_flash_guard_passes_on_the_new_module():
    from tests import test_no_console_flash_scheduled_tools as guard
    guard.test_every_subprocess_spawn_passes_creationflags(MODULE_REL)
    guard.test_the_no_window_constant_is_the_real_win32_value(MODULE_REL)
