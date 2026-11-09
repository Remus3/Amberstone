"""The DS relaunch prose says the RC-DaemonSlayer task is gone (S144-P-450).

The 2026-10-31 launcher cutover unregistered RC-DaemonSlayer and
RC-DSKeepalive was never registered (docs/OPERATIONS.md, "Moved to the app").
RC's DsWatchdog now starts DS as its own child, but the RM-740 (e) comment in
core/daemon_slayer_client.py still opened "the scheduled task that owns DS"
as a present-tense fact and tools/ds_keepalive.py named the RC-DSKeepalive
task as its host without saying that no such task exists. A reader following
either would look for a task that is not there. This pins a Status line, in
each, that names the cutover and the unregistered task, placed before the
text it qualifies.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CLIENT = "core/daemon_slayer_client.py"
KEEPALIVE = "tools/ds_keepalive.py"
STATUS = re.compile(r"Status \(2026-10-31 launcher cutover\):")


def _text(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def test_client_task_comment_carries_a_status_line_first():
    text = _text(CLIENT)
    anchor = text.index("DS_TASK_NAME = ")
    block = text[text.rindex("\n\n", 0, anchor):anchor]
    assert "# RM-740 (e)" in block
    m = STATUS.search(block)
    assert m, "RM-740 (e) comment has no cutover Status line"
    assert "unregistered" in block[m.start():]
    assert "own child" in block[m.start():]
    assert block.index("Status (") < block.index("boot trigger, SYSTEM")


def test_keepalive_host_paragraph_carries_a_status_line_first():
    text = _text(KEEPALIVE)
    host = text.index("Host: the RC-DSKeepalive scheduled task")
    head = text[:host]
    m = STATUS.search(head)
    assert m, "keepalive docstring has no cutover Status line before Host:"
    tail = head[m.start():]
    assert "never registered" in tail
    assert "RC-DaemonSlayer" in tail


def test_the_status_pattern_rejects_the_old_prose():
    """Positive control: the old comment and docstring do not match."""
    assert not STATUS.search("# RM-740 (e): the scheduled task that owns DS (boot trigger")
    assert not STATUS.search("Host: the RC-DSKeepalive scheduled task")
    assert STATUS.search("# Status (2026-10-31 launcher cutover): the task is unregistered")


def test_premise_the_cutover_unregistered_the_ds_task():
    """If OPERATIONS stops saying so, the Status prose is wrong - re-measure."""
    ops = _text("docs/OPERATIONS.md")
    assert "no `RC-DaemonSlayer` task since the 2026-10-31 launcher cutover" in ops
    assert "`RC-DSKeepalive` was never registered" in ops
