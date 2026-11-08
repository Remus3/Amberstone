"""legion_off.ps1 comments no longer describe unregistered tasks as live (S144-P-463).

The 2026-10-31 launcher cutover unregistered RC-Supervisor, RC-Phase3-Supervisor
and RC-DaemonSlayer, and RC-DSKeepalive was never registered (docs/OPERATIONS.md,
"Moved to the app"). ``tools/legion_off.ps1`` still said, in the present tense,
that step 0 holds the keepalive so DS is not relaunched "through RC-DaemonSlayer"
and that step 1 stops "AtLogon + AtStartup RC-* scheduled tasks", so a reader
looked for tasks that are not there. The code already prints MISSING for an
absent task; only the comments were stale. They now carry a Status paragraph
naming the cutover and the rc-shell service host.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LEGION_OFF = REPO / "tools" / "legion_off.ps1"

# The two old phrasings, as a present-tense claim about a live task.
OLD_CLAIMS = (
    re.compile(r"relaunch DS through RC-DaemonSlayer"),
    re.compile(r"Stop AtLogon \+ AtStartup RC-\* scheduled tasks"),
)


def _comments(text: str) -> str:
    return "\n".join(ln for ln in text.splitlines() if ln.lstrip().startswith("#"))


def _stale_claims(text: str) -> list[str]:
    comments = _comments(text)
    return [rx.pattern for rx in OLD_CLAIMS if rx.search(comments)]


def test_no_present_tense_live_task_claim_is_left():
    assert _stale_claims(LEGION_OFF.read_text(encoding="ascii")) == []


def test_a_status_paragraph_names_the_cutover_and_the_service_host():
    comments = _comments(LEGION_OFF.read_text(encoding="ascii"))
    assert re.search(r"Status \(2026-10-31 launcher cutover\)", comments)
    assert re.search(r"service host", comments, re.IGNORECASE)
    assert "RC-Supervisor" in comments and "RC-Phase3-Supervisor" in comments


def test_step_0_comment_says_the_keepalive_and_ds_task_are_not_registered():
    text = LEGION_OFF.read_text(encoding="ascii")
    step0 = text[text.index("# 0. Hold the DS keepalive"):text.index("$dsStop =")]
    assert "never registered" in step0
    assert "DsWatchdog" in step0


def test_the_code_is_unchanged_the_flag_is_still_written_and_tasks_still_listed():
    text = LEGION_OFF.read_text(encoding="ascii")
    assert "DS_KEEPALIVE_STOP" in text
    assert "Set-Content -LiteralPath $dsStop" in text
    for name in ("RC-Supervisor", "RC-Phase3-Supervisor", "RC-DS-MatchDB-MCP"):
        assert f"'{name}'" in text, name
    assert "MISSING (task not registered)" in text


def test_the_check_flags_the_old_phrasing_and_passes_the_new_one():
    old = ("# legion_off\n# 0. x\n# DS: with RC down it would relaunch DS through "
           "RC-DaemonSlayer within a minute.\n# 1. Stop AtLogon + AtStartup RC-* "
           "scheduled tasks (dep order)\n")
    new = "# 1. Stop the RC-* scheduled tasks that are still registered\n"
    assert len(_stale_claims(old)) == 2
    assert _stale_claims(new) == []


def test_operations_premise_the_cutover_unregistered_the_tasks():
    ops = (REPO / "docs" / "OPERATIONS.md").read_text(encoding="utf-8")
    moved = ops[ops.index("Moved to the app"):][:1500]
    for name in ("RC-Supervisor", "RC-Phase3-Supervisor", "RC-DaemonSlayer"):
        assert name in moved, name
    assert "`RC-DSKeepalive` was never registered" in moved
    assert "DsWatchdog" in (REPO / "core" / "daemon_slayer_client.py").read_text(
        encoding="utf-8")
