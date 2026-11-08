"""Task installers and supervisor prose carry the launcher-cutover status (S144-P-464).

The 2026-10-31 launcher cutover unregistered RC-Phase3-Supervisor and
RC-DaemonSlayer, and RC-DSKeepalive was never registered (docs/OPERATIONS.md,
"Moved to the app"), and OPERATIONS says never to re-run the three installers
because each re-registers a task the rc-shell service host replaces. Their
headers said nothing of it, so a reader following a file header would register
a second starter beside the host. Each header now carries a Status paragraph.
Two docstrings also named the live task / the retired task as a present-tense
pattern or state; they are now dated and name the module / the service host.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

INSTALLERS = {
    "ops/phase3_install.ps1": "RC-Phase3-Supervisor",
    "tools/install_daemon_slayer_task.ps1": "RC-DaemonSlayer",
    "tools/install_ds_keepalive_task.ps1": "RC-DSKeepalive",
}

STATUS_RX = re.compile(r"^# Status \(2026-10-31 launcher cutover\):", re.MULTILINE)


def _header(text: str) -> str:
    """The leading comment block of a .ps1 (everything before the first code line)."""
    out = []
    for ln in text.splitlines():
        if ln.strip() and not ln.lstrip().startswith("#"):
            break
        out.append(ln)
    return "\n".join(out)


def _has_status(text: str) -> bool:
    head = _header(text)
    return bool(STATUS_RX.search(head)) and "OPERATIONS" in head and "Do NOT" in head


def test_each_installer_header_carries_the_cutover_status():
    for rel, task in INSTALLERS.items():
        text = (REPO / rel).read_text(encoding="ascii")
        assert _has_status(text), rel
        assert task in _header(text), rel
        assert "LAUNCHER_OWNED_TASKS" in _header(text), rel


def test_installer_code_is_unchanged_each_still_names_its_task():
    for rel, task in INSTALLERS.items():
        text = (REPO / rel).read_text(encoding="ascii")
        assert f"'{task}'" in text, rel


def test_supervisor_docstring_names_the_module_not_the_retired_task():
    text = (REPO / "agents" / "supervisor.py").read_text(encoding="utf-8")
    assert "existing RC-Supervisor pattern" not in text
    assert "``ops/rc_supervisor.py``" in text


def test_supervisor_suite_docstring_dates_the_live_task_claim():
    text = (REPO / "agents" / "agent3_testing" / "suite" / "test_supervisor.py"
            ).read_text(encoding="utf-8")
    assert "its normal\n    state on Legion)" not in text
    assert "launcher cutover since unregistered" in text


def test_the_check_flags_a_bare_header_and_passes_a_status_header():
    bare = "# Install the task.\n#\n# Usage:\n\n$x = 1\n"
    good = ("# Install the task.\n#\n# Status (2026-10-31 launcher cutover): the\n"
            "# cutover UNREGISTERED it (docs/OPERATIONS.md). Do NOT re-run.\n\n$x = 1\n")
    late = "# Install the task.\n\n$x = 1\n# Status (2026-10-31 launcher cutover): x\n"
    assert not _has_status(bare)
    assert _has_status(good)
    assert not _has_status(late)


def test_operations_premise_never_rerun_the_three_installers():
    ops = (REPO / "docs" / "OPERATIONS.md").read_text(encoding="utf-8")
    moved = ops[ops.index("Moved to the app"):][:2500]
    for rel in ("tools/install_daemon_slayer_task.ps1",
                "tools/install_ds_keepalive_task.ps1", "ops/phase3_install.ps1"):
        assert rel in moved, rel
    assert "Never re-run" in moved
    assert "`RC-DSKeepalive` was never registered" in moved
    rc_facts = (REPO / "tools" / "rc_facts.py").read_text(encoding="utf-8")
    assert "LAUNCHER_OWNED_TASKS" in rc_facts
