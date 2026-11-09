"""legion_on.ps1 step 1b never claims it started a task that is not registered (S144-P-461).

The 2026-10-31 launcher cutover unregistered RC-HotkeyListener, RC-LCUAgent and
RC-LiveClientRelay (docs/OPERATIONS.md, "Moved to the app"); the rc-shell
service host runs those agents now. Step 1b of ``tools/legion_on.ps1`` still did

    Start-ScheduledTask -TaskName $a.Task -ErrorAction SilentlyContinue
    Write-Host "[on] $($a.Task) : started"

so on a cut-over host it printed "started" for three tasks that do not exist
and started nothing: the output said the agents were up while hotkeys, the LCU
agent and the relay were all down. Step 1 right above it already says
"MISSING (task not registered)" for an absent task; 1b now does the same and
only prints "started" after a task lookup found the task.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LEGION_ON = REPO / "tools" / "legion_on.ps1"
SERVICE_HOST_AGENTS = ("RC-HotkeyListener", "RC-LCUAgent", "RC-LiveClientRelay")


def _agent_loop(text: str) -> str:
    """The step-1b ``foreach ($a in $agents) { ... }`` body, braces balanced."""
    start = text.index("foreach ($a in $agents)")
    depth = 0
    for i in range(text.index("{", start), len(text)):
        depth += {"{": 1, "}": -1}.get(text[i], 0)
        if depth == 0:
            return text[start:i + 1]
    raise AssertionError("unbalanced foreach in legion_on.ps1")


def _starts_unregistered_task_unchecked(loop: str) -> bool:
    """True when the loop starts ``$a.Task`` with no prior Get-ScheduledTask
    lookup of ``$a.Task`` and no not-registered branch."""
    code = "\n".join(ln for ln in loop.splitlines() if not ln.strip().startswith("#"))
    start_at = code.find("Start-ScheduledTask")
    if start_at < 0:
        return False
    lookup = re.search(r"Get-ScheduledTask\s+-TaskName\s+\$a\.Task", code[:start_at])
    absent = re.search(r"not registered", code[:start_at], re.IGNORECASE)
    return not (lookup and absent)


def test_step_1b_looks_the_task_up_before_it_starts_it():
    loop = _agent_loop(LEGION_ON.read_text(encoding="ascii"))
    assert not _starts_unregistered_task_unchecked(loop), (
        "step 1b still starts $a.Task without a Get-ScheduledTask lookup and a "
        "not-registered branch, so it prints 'started' for an absent task")


def test_step_1b_still_lists_the_three_moved_agents():
    loop_host = LEGION_ON.read_text(encoding="ascii")
    for name in SERVICE_HOST_AGENTS:
        assert f"'{name}'" in loop_host, name


def test_step_1b_names_the_service_host_for_an_absent_task():
    loop = _agent_loop(LEGION_ON.read_text(encoding="ascii"))
    assert re.search(r"service host", loop, re.IGNORECASE), (
        "the not-registered line must say who runs the agent now")


def test_the_check_flags_the_old_shape_and_passes_a_guarded_one():
    old = (
        "foreach ($a in $agents) {\n"
        "  Start-ScheduledTask -TaskName $a.Task -ErrorAction SilentlyContinue\n"
        '  Write-Host "[on] $($a.Task) : started"\n'
        "}\n"
    )
    new = (
        "foreach ($a in $agents) {\n"
        "  $t = Get-ScheduledTask -TaskName $a.Task -ErrorAction SilentlyContinue\n"
        '  if ($null -eq $t) { Write-Host "x : not registered"; continue }\n'
        "  Start-ScheduledTask -TaskName $a.Task\n"
        "}\n"
    )
    assert _starts_unregistered_task_unchecked(_agent_loop(old))
    assert not _starts_unregistered_task_unchecked(_agent_loop(new))


def test_operations_premise_the_cutover_unregistered_the_three_tasks():
    ops = (REPO / "docs" / "OPERATIONS.md").read_text(encoding="utf-8")
    moved = ops[ops.index("Moved to the app"):]
    for name in SERVICE_HOST_AGENTS:
        assert name in moved[:1500], name
