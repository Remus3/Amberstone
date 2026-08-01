# arch: guard - launch_loop.ps1 must kill a prior controller | section=tests | frozen=no
"""The launcher must be single-instance for loop_controller.py.

REGRESSION (measured 2026-07-21): launch_loop.ps1 killed only this repo's
AutoHotkey64 bridge instances and never its own prior controller, so a relaunch
ORPHANED its predecessor. Two controllers then shared one controller.log, one
control/ directory and one target Claude window while keeping SEPARATE cycle
counters and deadlines. Ghost PID 22768 (started 00:51:36, on its cycle 7)
breached its stale deadline at 10:13:25 and injected a stall-recovery directive
into the 08:43:51 controller's healthy cycle 2.

The kill MUST stay scoped by command line. A bare "kill python.exe" would take
out RC itself, the Daemon Slayer server on :8860 and every RC-* scheduled task,
which is why the sibling AutoHotkey kill is cmdline-scoped too.
"""
from __future__ import annotations

from pathlib import Path

import pytest

_LAUNCHER = Path(__file__).resolve().parent.parent / "ops" / "loop" / "launch_loop.ps1"


@pytest.fixture(scope="module")
def script() -> str:
    return _LAUNCHER.read_text(encoding="utf-8")


def test_launcher_exists() -> None:
    assert _LAUNCHER.is_file(), f"missing launcher: {_LAUNCHER}"


def test_kills_a_prior_controller(script: str) -> None:
    """Some block must target loop_controller.py for termination."""
    assert "loop_controller.py" in script
    controller_kill = [
        line
        for line in script.splitlines()
        if "loop_controller.py" in line and "CommandLine" in line
    ]
    assert controller_kill, (
        "launch_loop.ps1 never matches a running loop_controller.py by command "
        "line - a relaunch will orphan the prior controller and two cycle "
        "counters will race for the same Claude window"
    )


def test_controller_kill_is_cmdline_scoped_to_this_repo(script: str) -> None:
    """Scoped to this repo, so a sibling loop's controller survives."""
    for line in script.splitlines():
        if "loop_controller.py" in line and "CommandLine" in line:
            assert "Riot Commander" in line, (
                "the prior-controller match must be scoped to this repo's path; "
                f"unscoped match would kill a sibling loop: {line.strip()}"
            )


def test_controller_kill_does_not_target_bare_python(script: str) -> None:
    """No unfiltered python kill - that would take out RC, DS :8860 and the tasks."""
    for line in script.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if "taskkill" in stripped and "python" in stripped.lower():
            assert "ProcessId" in stripped, (
                "a python taskkill must go through a CimInstance ProcessId "
                f"filter, never an image name: {stripped}"
            )


def test_controller_kill_excludes_self(script: str) -> None:
    """The launcher must not be able to kill its own process."""
    lines = script.splitlines()
    idx = [i for i, line in enumerate(lines) if "loop_controller.py" in line and "CommandLine" in line]
    assert idx, "no prior-controller match block to check for a self-kill guard"
    window = "\n".join(lines[idx[0]: idx[0] + 4])
    assert "$PID" in window, (
        "the prior-controller kill must exclude $PID so the launcher (or a "
        f"controller invoking it) cannot terminate itself:\n{window}"
    )


def test_uses_taskkill_not_stop_process(script: str) -> None:
    """Repo hard rule: Stop-Process hangs the MCP pipe - taskkill /F /PID only."""
    assert "Stop-Process" not in script
