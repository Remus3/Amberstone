"""Two more DS-owner passages stop calling RC-DaemonSlayer a live task (S144-P-454).

The 2026-10-31 launcher cutover unregistered RC-DaemonSlayer (docs/OPERATIONS.md,
"Moved to the app"); RC's DsWatchdog starts DS as its own child now (see
tests/test_ds_task_prose_s144p450.py for the client and the keepalive). Two more
passages kept the old picture in the present tense:

- core/hot_reload.py's module docstring said Daemon Slayer "is its own
  scheduled-task process (RC-DaemonSlayer)";
- tools/start_daemon_slayer.py said "Used by the RC-DaemonSlayer scheduled
  task" and carried a comment on how "the RC-DaemonSlayer scheduled task runs
  as SYSTEM".

This pins a Status (2026-10-31 launcher cutover) line in each, before the text
it qualifies, that names the unregistered task and who starts DS now.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HOT_RELOAD = "core/hot_reload.py"
LAUNCHER = "tools/start_daemon_slayer.py"
STATUS = re.compile(r"Status \(2026-10-31 launcher cutover\):")
LIVE_TASK_CLAIMS = (
    re.compile(r"its own scheduled-task process", re.I),
    re.compile(r"Used by the ``RC-DaemonSlayer`` scheduled task"),
    re.compile(r"The RC-DaemonSlayer scheduled task runs as SYSTEM"),
)


def _text(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def test_hot_reload_ds_bullet_carries_a_status_line():
    text = _text(HOT_RELOAD)
    bullet = text.index("Daemon Slayer :8860 is unchanged")
    caveats = text.index("Caveats:")
    block = text[bullet:caveats]
    m = STATUS.search(block)
    assert m, "the Daemon Slayer bullet has no cutover Status line"
    tail = block[m.start():]
    assert "unregistered" in tail
    assert "DsWatchdog" in tail
    assert "own child" in tail


def test_launcher_docstring_carries_a_status_line_before_the_task_claim():
    text = _text(LAUNCHER)
    doc_end = text.index('"""', 3)
    doc = text[:doc_end]
    m = STATUS.search(doc)
    assert m, "the launcher docstring has no cutover Status line"
    tail = doc[m.start():]
    assert "unregistered" in tail
    assert "DsWatchdog" in tail


def test_launcher_fallback_log_comment_is_not_a_live_system_task_claim():
    text = _text(LAUNCHER)
    anchor = text.index("_FALLBACK_LOG_FILE = (")
    block = text[text.rindex("_LOG_FILE = ", 0, anchor):anchor]
    assert "unregistered" in block or "a task registered" in block
    assert "scheduled task runs as SYSTEM" not in block


def test_no_live_ds_task_claim_remains():
    bad = []
    for rel in (HOT_RELOAD, LAUNCHER):
        for no, line in enumerate(_text(rel).splitlines(), 1):
            if any(p.search(line) for p in LIVE_TASK_CLAIMS):
                bad.append(f"{rel}:{no}: {line.strip()}")
    assert not bad, "\n".join(bad)


def test_the_patterns_reject_the_new_prose_and_match_the_old():
    """Positive control for the claim patterns and the status pattern."""
    old = ("  - Daemon Slayer :8860 is unchanged: it is its own "
           "scheduled-task process\n")
    assert any(p.search(old) for p in LIVE_TASK_CLAIMS)
    assert any(p.search("Used by the ``RC-DaemonSlayer`` scheduled task. Manual")
               for p in LIVE_TASK_CLAIMS)
    assert not any(p.search("Status (2026-10-31 launcher cutover): the task is "
                            "unregistered; DsWatchdog starts DS as its own child")
                   for p in LIVE_TASK_CLAIMS)
    assert not STATUS.search("it is its own scheduled-task process")


def test_premise_the_cutover_unregistered_the_ds_task():
    """If OPERATIONS stops saying so, the Status prose is wrong - re-measure."""
    ops = _text("docs/OPERATIONS.md")
    assert "no `RC-DaemonSlayer` task since the 2026-10-31 launcher cutover" in ops


def test_premise_the_launcher_is_still_what_the_child_route_runs():
    """The launcher stays in use (spawn_ds child route), only its task owner went."""
    client = _text("core/daemon_slayer_client.py")
    assert '"tools" / "start_daemon_slayer.py"' in client
    assert "def _spawn_child" in client
