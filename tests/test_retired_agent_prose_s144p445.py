"""The two unscheduled agent modules do not point at a deploy folder that is gone.

tools/screen_agent.py is retired (docs/ARCHITECTURE.md agent table: DISABLED, no
task; the vision server self-grabs frames) and tools/keybind_listener.py is an
optional, unscheduled feature. Their docstrings still told a reader to copy the
file to C:\\RC-Agent and to run or register it from there, a folder that has not
existed since the 1-PC consolidation (the registered agents ran from the repo),
and screen_agent's "Run (one time)" recipe never said the agent is retired, so a
reader could start a second capture beside the vision server's own self-grab.

This pins the corrected prose: neither module names the C:\\RC-Agent folder, and
screen_agent's docstring says it is retired before it gives a recipe. The
paste-me task recipes stay (tests/test_scheduled_task_docstring_commands.py
parses them); only their target path and framing changed.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MODULES = ("tools/screen_agent.py", "tools/keybind_listener.py")
DEPLOY_DIR_CLAIM = re.compile(r"C:[\\/]+RC-Agent", re.I)


def _text(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def test_no_module_names_the_gone_deploy_folder():
    bad = []
    for rel in MODULES:
        for no, line in enumerate(_text(rel).splitlines(), 1):
            if DEPLOY_DIR_CLAIM.search(line):
                bad.append(f"{rel}:{no}: {line.strip()}")
    assert not bad, "\n".join(bad)


def test_screen_agent_says_retired_before_its_first_recipe():
    doc = ast.get_docstring(ast.parse(_text("tools/screen_agent.py"))) or ""
    low = doc.lower()
    status = low.find("status: retired")
    assert status >= 0, "docstring has no 'Status: RETIRED' line"
    first_recipe = min(
        i for i in (low.find("run (one time)"), low.find("register-scheduledtask"),
                    low.find("scheduled tasks"))
        if i >= 0)
    assert status < first_recipe


def test_the_claim_pattern_catches_the_old_prose():
    """Positive control: the pattern fires on every spelling the modules used."""
    for old in (
        "2. Copy this file to:   C:\\\\RC-Agent\\\\keybind_listener.py",
        "python.exe C:\\RC-Agent\\screen_agent.py --monitor 0",
        "# deployed copy at C:/RC-Agent/ has no repo above it.",
    ):
        assert DEPLOY_DIR_CLAIM.search(old), old


def test_the_premise_the_architecture_table_still_says_so():
    """The prose follows docs/ARCHITECTURE.md; if that row changes, re-read."""
    rows = {
        m.group(1): m.group(2)
        for m in re.finditer(r"^\| `(\w+\.py)` \| ([^|]+) \|",
                             _text("docs/ARCHITECTURE.md"), re.M)
    }
    assert rows["screen_agent.py"].startswith("DISABLED")
    assert rows["keybind_listener.py"].startswith("OPTIONAL")


def test_phase_watcher_says_retired_before_its_deploy_recipe():
    """S144-P-448: phase_watcher is DISABLED (ARCHITECTURE) and no service-host
    service starts it, but its docstring opened "Runs Legion-local alongside the
    LCU polling agent" and went straight to a one-time deploy recipe. Its
    installer and its test still deploy to the RC-Agent folder by design (a kept
    reference, TLS-floor test cites it), so that folder stays named: only the
    retired status is pinned, ahead of the recipe."""
    doc = ast.get_docstring(ast.parse(_text("tools/phase_watcher.py"))) or ""
    low = doc.lower()
    status = low.find("status: retired")
    assert status >= 0, "docstring has no 'Status: RETIRED' line"
    recipe = low.find("deploy (one-time)")
    assert recipe >= 0, "the deploy recipe moved; re-read this guard"
    assert status < recipe
    assert "service host" in low[status:recipe], "status must say who does NOT start it"


def test_phase_watcher_premise_no_service_starts_it_and_architecture_says_disabled():
    rows = {
        m.group(1): m.group(2)
        for m in re.finditer(r"^\| `(\w+\.py)` \| ([^|]+) \|",
                             _text("docs/ARCHITECTURE.md"), re.M)
    }
    assert rows["phase_watcher.py"].startswith("DISABLED")
    assert "phase_watcher" not in _text("ops/launcher/services.json")
