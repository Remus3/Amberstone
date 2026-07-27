"""Scheduled tools must not flash a console window on Legion.

WHY THIS EXISTS. `pythonw.exe` suppresses the console of the process IT hosts,
not of any child that process spawns. So a scheduled task can be correctly
configured to use `pythonw.exe` and STILL flash: every `subprocess.run` of a
console program (powershell, git, schtasks, cmd) allocates its own console.

Measured 2026-07-26: `tools/replay_chain_watch.py` runs under RC-ReplayChainWatch
every 15 minutes and calls `_ps()` from three sites, so the operator saw three
windows flash in sequence, four times an hour. `tools/ci_watchdog.py` already
carried the correct guard (and a comment naming this exact symptom), which is
what made the omission next door easy to miss.

The guard is `creationflags=CREATE_NO_WINDOW` (0x08000000) on every spawn in a
module that runs unattended on a schedule. This test pins that, because the
symptom is invisible in CI - it only shows up as a flicker on a desktop.

SCOPE: only modules invoked by an RC-* scheduled task. Interactive tools
(strip_em_dashes, repair_mojibake, build_installer) are deliberately NOT listed;
a console is expected when a human runs them from a shell.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent

CREATE_NO_WINDOW = 0x08000000

# Modules run unattended by an RC-* scheduled task that spawn a child process.
SCHEDULED_SPAWNERS = (
    "tools/replay_chain_watch.py",
    "tools/ci_watchdog.py",
    # 2026-07-26: RC-Supervisor is one of only three RC-* tasks that must stay
    # Interactive (it drives the Electron overlay), so it KEEPS a desktop after
    # the S4U sweep and its console children would flash. The other 13 tasks are
    # now S4U and structurally cannot show a window.
    "ops/rc_supervisor.py",
    # Already compliant when swept; pinned so it stays that way. The 2026-07-26
    # hand-off claimed this file was unguarded - it was not, both of its spawn
    # sites already carried the platform-guarded flag.
    "ops/rc_dev_runtime.py",
)

_SPAWN_ATTRS = {"run", "Popen", "check_output", "call", "check_call"}


def _spawn_calls(tree: ast.AST) -> list[ast.Call]:
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (isinstance(func, ast.Attribute)
                and func.attr in _SPAWN_ATTRS
                and isinstance(func.value, ast.Name)
                and func.value.id == "subprocess"):
            found.append(node)
    return found


@pytest.mark.parametrize("rel", SCHEDULED_SPAWNERS)
def test_every_subprocess_spawn_passes_creationflags(rel: str) -> None:
    path = ROOT / rel
    assert path.exists(), f"{rel} is missing - update SCHEDULED_SPAWNERS"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    calls = _spawn_calls(tree)
    assert calls, f"{rel} has no subprocess spawn - remove it from the list"
    for call in calls:
        kwargs = {kw.arg for kw in call.keywords if kw.arg}
        assert "creationflags" in kwargs, (
            f"{rel}:{call.lineno} spawns a child process without "
            f"creationflags. Under a pythonw.exe-hosted scheduled task this "
            f"flashes a console window on the operator's desktop. Pass "
            f"creationflags=0x08000000 (CREATE_NO_WINDOW) on Windows."
        )


@pytest.mark.parametrize("rel", SCHEDULED_SPAWNERS)
def test_the_no_window_constant_is_the_real_win32_value(rel: str) -> None:
    # A typo here fails open: the spawn still works and the console still
    # flashes, so the kwarg being present is not by itself sufficient.
    text = (ROOT / rel).read_text(encoding="utf-8")
    assert "0x08000000" in text, (
        f"{rel} must define CREATE_NO_WINDOW as the literal 0x08000000"
    )
