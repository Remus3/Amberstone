"""Two Phase 3 passages stop calling RC-Phase3-Supervisor a live task (S144-P-457).

The 2026-10-31 launcher cutover unregistered RC-Phase3-Supervisor
(docs/OPERATIONS.md, "Moved to the app"); the rc-shell service host now runs
``-m agents.supervisor`` itself, dev profile only (ops/launcher/services.json,
service ``phase3_supervisor``). Two passages kept the old picture in the
present tense:

- agents/_supervisor_common.py's ``_env_port`` docstring said a test runs on
  free ports "while the live RC-Phase3-Supervisor still holds :8890/:8891";
- agents/_supervisor_ephemeral.py's env-scrub comment said "The
  RC-Phase3-Supervisor task runs `pythonw -m agents.supervisor`".

This pins a cutover Status clause in each, naming the unregistered task and
the service host, so a reader does not look for a Task Scheduler entry.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
COMMON = "agents/_supervisor_common.py"
EPHEMERAL = "agents/_supervisor_ephemeral.py"
STATUS = re.compile(r"Status \(2026-10-31 launcher cutover\):")
LIVE_TASK_CLAIMS = (
    re.compile(r"the live RC-Phase3-Supervisor still holds"),
    re.compile(r"The\s+(?:#\s+)?RC-Phase3-Supervisor task runs"),
)


def _text(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def test_env_port_docstring_names_the_service_host():
    text = _text(COMMON)
    start = text.index("def _env_port")
    block = text[start:text.index('"""', text.index('"""', start) + 3)]
    m = STATUS.search(block)
    assert m, "the _env_port docstring has no cutover Status clause"
    tail = block[m.start():]
    assert "unregistered" in tail
    assert "service host" in tail


def test_ephemeral_env_scrub_comment_names_the_service_host():
    text = _text(EPHEMERAL)
    start = text.index("# Env vars removed from the ephemeral spawn")
    end = text.index("# Each entry is a variable", start)
    block = text[start:end]
    m = STATUS.search(block)
    assert m, "the env-scrub comment has no cutover Status clause"
    tail = block[m.start():]
    assert "unregistered" in tail
    assert "service host" in tail


def test_no_live_phase3_task_claim_remains():
    bad = []
    for rel in (COMMON, EPHEMERAL):
        text = _text(rel)
        for m in LIVE_TASK_CLAIMS:
            for hit in m.finditer(text):
                no = text.count("\n", 0, hit.start()) + 1
                bad.append(f"{rel}:{no}: {hit.group(0)}")
    assert not bad, "\n".join(bad)


def test_the_patterns_match_the_old_prose_and_not_the_new():
    """Positive control for the claim patterns."""
    old1 = "the live RC-Phase3-Supervisor still holds :8890/:8891."
    old2 = "# RC-Phase3-Supervisor task runs `pythonw -m agents.supervisor`"
    old2_wrapped = "# MEASURED: set. The\n# RC-Phase3-Supervisor task runs `x`"
    assert LIVE_TASK_CLAIMS[0].search(old1)
    assert LIVE_TASK_CLAIMS[1].search(old2.replace("# ", "The ", 1))
    assert LIVE_TASK_CLAIMS[1].search(old2_wrapped)
    new = ("Status (2026-10-31 launcher cutover): the RC-Phase3-Supervisor task "
           "is unregistered; the service host runs it")
    assert not any(p.search(new) for p in LIVE_TASK_CLAIMS)


def test_premise_the_cutover_unregistered_the_task():
    """If OPERATIONS stops saying so, the Status prose is wrong - re-measure."""
    ops = _text("docs/OPERATIONS.md")
    assert "`RC-Phase3-Supervisor` and `RC-DaemonSlayer`" in ops


def test_premise_the_service_host_runs_agents_supervisor_in_dev():
    manifest = json.loads(_text("ops/launcher/services.json"))
    rows = [s for s in manifest["services"] if s.get("name") == "phase3_supervisor"]
    assert len(rows) == 1
    assert rows[0]["argv"] == ["-m", "agents.supervisor"]
    assert rows[0]["profiles"] == ["dev"]
