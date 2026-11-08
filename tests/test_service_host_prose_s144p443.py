"""The service-host agents do not describe a boot task that no longer exists.

The 2026-10-31 launcher cutover unregistered RC-LCUAgent and RC-HotkeyListener
(docs/OPERATIONS.md, "Moved to the app"); the rc-shell service host
(ops/launcher/service_host.py) starts both agents now and nothing starts them
at boot. Their docstrings and comments kept saying a logon task launches them,
which sent a reader to a Task Scheduler entry that is gone. This pins the
corrected prose: a mention of an ONLOGON task in these two modules is only
allowed beside the word "unregistered", and a "logon task" / "task runs" /
"task's Last Result" claim is never allowed.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MODULES = ("tools/lcu_agent.py", "tools/hotkey_listener.py")
LIVE_TASK_CLAIMS = (
    re.compile(r"(?<![A-Za-z])logon task", re.I),
    re.compile(r"\btask runs\b", re.I),
    re.compile(r"task's Last Result", re.I),
    re.compile(r"(?<![A-Za-z])Registered as the RC-\w+ ONLOGON"),
)


def _lines(rel: str) -> list[str]:
    return (REPO / rel).read_text(encoding="utf-8").splitlines()


def test_no_live_boot_task_claim():
    bad = []
    for rel in MODULES:
        for no, line in enumerate(_lines(rel), 1):
            if any(p.search(line) for p in LIVE_TASK_CLAIMS):
                bad.append(f"{rel}:{no}: {line.strip()}")
    assert not bad, "\n".join(bad)


def test_onlogon_mention_is_marked_unregistered():
    bad = []
    for rel in MODULES:
        lines = _lines(rel)
        for no, line in enumerate(lines, 1):
            if "ONLOGON" not in line:
                continue
            window = " ".join(lines[max(0, no - 4):no + 3]).lower()
            if "unregistered" not in window:
                bad.append(f"{rel}:{no}: {line.strip()}")
    assert not bad, "\n".join(bad)


def test_the_claim_patterns_catch_the_old_prose():
    """Positive control: each pattern fires on the sentence it was written for."""
    old = (
        "Registered as the RC-LCUAgent ONLOGON task (Legion-neutral task name).",
        "The logon task runs this file as a script",
        "so the RC-LCUAgent task's Last Result is not a",
        "the RC-HotkeyListener ONLOGON scheduled task runs THIS in-repo file",
    )
    for text in old:
        assert any(p.search(text) for p in LIVE_TASK_CLAIMS), text


def test_the_host_still_owns_both_agents():
    """The premise: services.json starts both agents (else the prose is wrong)."""
    manifest = (REPO / "ops/launcher/services.json").read_text(encoding="utf-8")
    assert "tools/lcu_agent.py" in manifest
    assert "tools/hotkey_listener.py" in manifest
