"""The service-host agents do not describe a boot task that no longer exists.

The 2026-10-31 launcher cutover unregistered RC-LCUAgent, RC-LiveClientRelay
and RC-HotkeyListener (docs/OPERATIONS.md, "Moved to the app"); the rc-shell
service host (ops/launcher/service_host.py) starts all three agents now and
nothing starts them at boot. Their docstrings and comments kept saying a logon
task launches them, which sent a reader to a Task Scheduler entry that is gone
(the liveclient relay's docstring even carried a paste-me schtasks /Create that
would start a SECOND relay beside the host's). This pins the corrected prose: a
mention of an ONLOGON task in these modules is only allowed beside the word
"unregistered", and a "logon task" / "task runs" / "task's Last Result" /
"schtasks /Create" / out-of-tree agent-directory claim is never allowed.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MODULES = (
    "tools/lcu_agent.py",
    "tools/hotkey_listener.py",
    "tools/liveclient_relay.py",
)
LIVE_TASK_CLAIMS = (
    re.compile(r"(?<![A-Za-z])logon task", re.I),
    re.compile(r"\btask runs\b", re.I),
    re.compile(r"task's Last Result", re.I),
    re.compile(r"(?<![A-Za-z])Registered as the RC-\w+ ONLOGON"),
    re.compile(r"\bscheduled task runs\b", re.I),
    re.compile(r"\bschtasks /Create\b", re.I),
    re.compile(r"\.exe\s+C:[\\/]+RC-Agent"),
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
        "The scheduled task runs this under pythonw.exe",
        '(optional task) schtasks /Create /TN "RC-LiveClientRelay" /SC ONLOGON',
        "python.exe C:\\RC-Agent\\liveclient_relay.py",
    )
    for text in old:
        assert any(p.search(text) for p in LIVE_TASK_CLAIMS), text


def test_the_host_still_owns_every_agent():
    """The premise: services.json starts each agent (else the prose is wrong)."""
    manifest = (REPO / "ops/launcher/services.json").read_text(encoding="utf-8")
    for rel in MODULES:
        assert rel in manifest, rel
