"""Guards for the hook invocation log in tools/rc_facts.py.

WHY THIS EXISTS. CS measured on 2026-09-07 that its watcher "does not read the
hook payload, does not read the `source` field, and writes no record of having
been invoked", and downgraded its own /clear-survival status from UNVERIFIED to
UNMEASURABLE AS BUILT. RSC measured the same about RSC. RC then measured the
same about RC, and refused a credit CS had extended to it: RC had a poller-side
process log and no hook invocation record at all.

The shared defect is the one this repo keeps paying for in other forms - a
check that is ABSENT reads identically to a check that PASSED. A watcher whose
only output is a report to a human cannot be audited by anyone, its author
included, because firing leaves nothing behind.

So the property under test is not "the hook works". It is: AFTER THE FACT, CAN
ANYONE TELL WHETHER IT FIRED, AND FROM WHICH SESSION SOURCE. Every assertion
here is derived from a specific way that answer has already been unavailable.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tools.inbox_responder_runner as runner  # noqa: E402
from tools.rc_facts import (  # noqa: E402
    _LOG_KEEP,
    _hook_source,
    _read_hook_payload,
    record_invocation,
)

_PY = sys.executable
_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------- the record


def test_one_line_per_invocation_appended(tmp_path):
    """Three fires leave three lines. The count IS the audit."""
    log = tmp_path / "hooks.jsonl"
    for _ in range(3):
        record_invocation("SessionStart", {"source": "startup"}, path=log)
    assert len([ln for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip()]) == 3


def test_line_carries_timestamp_and_source(tmp_path):
    """The two fields CS named. Without both, /clear survival stays unmeasurable."""
    log = tmp_path / "hooks.jsonl"
    record_invocation("SessionStart", {"source": "clear"}, path=log)
    rec = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
    assert rec["source"] == "clear"
    assert rec["event"] == "SessionStart"
    # A timestamp that cannot be ordered is not a timestamp.
    assert rec["ts"][:4].isdigit() and "T" in rec["ts"]


def test_clear_is_distinguishable_from_startup(tmp_path):
    """The whole point. If these two collapse, the log answers nothing."""
    log = tmp_path / "hooks.jsonl"
    record_invocation("SessionStart", {"source": "startup"}, path=log)
    record_invocation("SessionStart", {"source": "clear"}, path=log)
    sources = [json.loads(ln)["source"] for ln in log.read_text(encoding="utf-8").splitlines()]
    assert sources == ["startup", "clear"]


def test_absent_source_is_recorded_explicitly_never_omitted(tmp_path):
    """An absent field must not read as a present one.

    UserPromptSubmit carries no `source`. If the key were simply dropped, a
    reader could not distinguish "this event has no source" from "the log was
    written by an older build that did not record it" - which is the same
    absent-reads-as-passed shape the whole log exists to kill.
    """
    log = tmp_path / "hooks.jsonl"
    record_invocation("UserPromptSubmit", {"session_id": "abc"}, path=log)
    rec = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
    assert "source" in rec
    assert rec["source"] == "unknown"


def test_a_real_fire_is_distinguishable_from_a_manual_cli_run(tmp_path):
    """rc_facts.py is a hook AND a CLI, and both reach the same function.

    Without this field the log would answer "rc_facts ran" when the question
    asked is "the HOOK fired" - an operator running it by hand would look
    identical to Claude Code invoking it, which is the same absent-reads-as-
    present shape one level up.
    """
    log = tmp_path / "hooks.jsonl"
    record_invocation("SessionStart", {"source": "startup"}, path=log)  # real fire
    record_invocation("SessionStart", {}, path=log)  # manual run, no payload
    got = [json.loads(ln)["payload"] for ln in log.read_text(encoding="utf-8").splitlines()]
    assert got == [True, False]


def test_record_carries_no_prompt_text_and_no_paths(tmp_path):
    """This channel pulled a 48-file drop for operator PII eight hours ago.

    A hook payload carries the operator's literal prompt and cwd. A log that
    persists either is a new disclosure surface on every keystroke.
    """
    log = tmp_path / "hooks.jsonl"
    # COMPOSED, never a literal. Writing the realistic form inline put a real
    # account-shaped home path into a tracked runnable file and turned
    # test_no_hardcoded_home_path.py red - a test asserting a home path is not
    # LOGGED, which hardcoded one to say so. The runtime value is unchanged, so
    # the assertion below is exactly as strong as it was.
    fake_cwd = os.path.join("C:" + os.sep, "Users", "SOMEONE", "private")
    record_invocation(
        "UserPromptSubmit",
        {"prompt": "SECRETPROMPT", "cwd": fake_cwd, "session_id": "s1"},
        path=log,
    )
    blob = log.read_text(encoding="utf-8")
    assert "SECRETPROMPT" not in blob
    assert "SOMEONE" not in blob
    assert "private" not in blob


# ------------------------------------------------------- a hook must not fail


@pytest.mark.parametrize(
    "payload",
    [None, {}, {"source": None}, {"source": 12}, {"source": "x" * 5000}],
)
def test_never_raises_on_hostile_payload(tmp_path, payload):
    """`main()` already swallows OSError so a hook never fails the turn.

    A logger that raises would convert a working hook into a broken one, which
    is strictly worse than having no log.
    """
    record_invocation("SessionStart", payload, path=tmp_path / "hooks.jsonl")


def test_never_raises_when_path_is_unwritable(tmp_path):
    """An unwritable log must degrade to silence, never to an exception."""
    victim = tmp_path / "nodir" / "deeper" / "hooks.jsonl"
    record_invocation("SessionStart", {"source": "startup"}, path=victim)


def test_oversized_source_is_bounded(tmp_path):
    """An unbounded field is an unbounded file. RSC wrote 492674 files today."""
    log = tmp_path / "hooks.jsonl"
    record_invocation("SessionStart", {"source": "y" * 10000}, path=log)
    assert len(log.read_text(encoding="utf-8")) < 1024


def test_log_is_bounded_and_keeps_the_newest(tmp_path):
    """A log that grows forever gets deleted, and then measures nothing.

    Rotation must drop the OLDEST. A rotation that keeps the oldest answers
    "did it fire in April" instead of "did it fire since the last /clear".
    """
    log = tmp_path / "hooks.jsonl"
    for i in range(1200):
        record_invocation("SessionStart", {"source": f"s{i}"}, path=log)
    lines = [ln for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) <= 1000
    assert json.loads(lines[-1])["source"] == "s1199"


# ------------------------------------------------------------ reading stdin


def test_concurrent_fires_do_not_interleave(tmp_path):
    """Subagent starts fire this hook concurrently.

    A torn line is worse than a missing one: it reads as corruption of the
    audit rather than as an absent fire, and json.loads would reject the
    whole log.
    """
    log = tmp_path / "hooks.jsonl"
    with ThreadPoolExecutor(max_workers=16) as ex:
        list(ex.map(lambda i: record_invocation("SessionStart", {"source": f"c{i}"}, path=log), range(64)))
    lines = [ln for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 64
    for ln in lines:
        json.loads(ln)  # every line whole and parseable


def test_hook_source_extracts_the_payload_field():
    assert _hook_source({"source": "resume"}) == "resume"
    assert _hook_source({}) == "unknown"
    assert _hook_source(None) == "unknown"


def test_read_hook_payload_returns_empty_on_no_stdin():
    """CS's exact finding was that its watcher never reads stdin at all.

    Reading it introduces a hang risk the previous design did not have, so
    the no-stdin case is asserted rather than assumed.
    """
    assert _read_hook_payload(stream=None) == {}


def test_read_hook_payload_parses_json():
    import io

    assert _read_hook_payload(stream=io.StringIO('{"source":"clear"}')) == {"source": "clear"}


def test_read_hook_payload_survives_garbage():
    import io

    assert _read_hook_payload(stream=io.StringIO("not json at all")) == {}


# ------------------------------------------- the thing that actually matters


def _old_complete_rows(before: bytes | None) -> list[bytes]:
    old = (before or b"").splitlines(keepends=True)
    if old and not old[-1].endswith(b"\n"):
        old = old[:-1]  # a foreign row mid-write when `before` was read
    return old


def _diff_rows(before: bytes | None, after: bytes | None) -> tuple[int, list[bytes]]:
    """(old rows no longer present, terminated rows in `after` not in `before`)."""
    old = _old_complete_rows(before)
    remaining = Counter(old)
    appended = []
    for line in (after or b"").splitlines(keepends=True):
        if remaining[line] > 0:
            remaining[line] -= 1
        elif line.endswith(b"\n"):
            appended.append(line)
    return sum(remaining.values()), appended


def _live_log_problems(before: bytes | None, after: bytes | None, child_pid: int) -> list:
    """What moved in the live hook log that a FOREIGN hook fire cannot explain.

    Append-only rules (deletion, truncation, a rewritten or removed row outside a
    legitimate head trim, a non-record line, a row written by this process or by
    the child) are delegated to `runner.hook_log_violations`, the RM-434 rule the
    responder dry cycle itself uses. On top, ANY appended row with a null or
    blank session fails: a real hook fire always carries one (RM-451), so such a
    row is a hand run - the class this test exists to keep off the live log. A
    row carrying some other non-empty session is another live session and is
    ignored, which is the flake fix.

    ORDER is checked here as well, because the runner rule compares rows as a
    MULTISET and so cannot see a same-count reorder. A foreign writer can only
    append at the tail or drop rows from the head, so the surviving old rows
    must still open the file, byte for byte, in their original order.
    """
    problems = list(runner.hook_log_violations(before, after, {os.getpid(), child_pid}, frozenset()))
    if after is None:
        return problems
    removed, appended = _diff_rows(before, after)
    if not after.startswith(b"".join(_old_complete_rows(before)[removed:])):
        problems.append("existing rows rewritten or reordered in place")
    for line in appended:
        try:
            rec = json.loads(line)
        except ValueError:
            continue  # already reported by the runner rule
        if not isinstance(rec, dict):
            continue
        session = rec.get("session")
        if not (isinstance(session, str) and session.strip()):
            problems.append(f"null-session row appended {line[:60]!r}")
    return problems


def _row(session, pid=4242, ts="2026-09-17T00:00:00") -> bytes:
    rec = {
        "ts": ts,
        "event": "UserPromptSubmit",
        "source": "unknown",
        "payload": True,
        "stdin": "json",
        "session": session,
        "pid": pid,
    }
    return (json.dumps(rec, separators=(",", ":")) + "\n").encode("utf-8")


_BASE = b"".join(_row(f"s-{i}", pid=1000 + i, ts=f"2026-09-17T00:00:{i:02d}") for i in range(5))
_CHILD_PID = 777777


def test_live_log_rule_ignores_a_foreign_session_append():
    """Anchor: the rule is not always-red, so the failing arms below mean something."""
    assert _live_log_problems(_BASE, _BASE, _CHILD_PID) == []
    assert _live_log_problems(_BASE, _BASE + _row("foreign-session"), _CHILD_PID) == []
    assert _live_log_problems(None, None, _CHILD_PID) == []


@pytest.mark.parametrize("session", [None, "", "   "])
def test_live_log_rule_fails_on_a_seeded_null_session_row(session):
    problems = _live_log_problems(_BASE, _BASE + _row(session), _CHILD_PID)
    assert any("null-session" in p for p in problems), problems


def test_live_log_rule_fails_on_a_null_session_row_into_a_fresh_log():
    assert _live_log_problems(None, _row(None), _CHILD_PID)


def test_live_log_rule_fails_on_the_child_pid():
    assert _live_log_problems(_BASE, _BASE + _row("s-x", pid=_CHILD_PID), _CHILD_PID)


def test_live_log_rule_fails_on_this_process_pid():
    assert _live_log_problems(_BASE, _BASE + _row("s-x", pid=os.getpid()), _CHILD_PID)


def test_live_log_rule_fails_on_truncation():
    lines = _BASE.splitlines(keepends=True)
    assert _live_log_problems(_BASE, b"".join(lines[:-1]), _CHILD_PID)
    assert _live_log_problems(_BASE, b"", _CHILD_PID)


def test_live_log_rule_fails_on_deletion():
    assert _live_log_problems(_BASE, None, _CHILD_PID)


def test_live_log_rule_fails_on_a_rewritten_row():
    lines = _BASE.splitlines(keepends=True)
    lines[2] = _row("s-rewritten", pid=1002, ts="2026-09-17T00:00:02")
    assert _live_log_problems(_BASE, b"".join(lines), _CHILD_PID)


def test_live_log_rule_fails_on_a_reorder_that_keeps_every_row():
    """The multiset rule alone passes this; the order check must not."""
    lines = _BASE.splitlines(keepends=True)
    reordered = b"".join([lines[0], lines[2], lines[1], lines[3], lines[4]])
    assert runner.hook_log_violations(_BASE, reordered, {_CHILD_PID}, frozenset()) == []
    assert _live_log_problems(_BASE, reordered, _CHILD_PID)


def test_live_log_rule_fails_on_a_head_drop_under_the_keep_cap():
    lines = _BASE.splitlines(keepends=True)
    assert _live_log_problems(_BASE, b"".join(lines[1:]) + _row("s-new"), _CHILD_PID)


def test_live_log_rule_allows_a_foreign_head_trim_at_the_keep_cap():
    """What `_trim_invocation_log` does when another session's fire passes the cap."""
    full = [_row(f"s-{i}", pid=2000 + i) for i in range(_LOG_KEEP)]
    before = b"".join(full)
    after = b"".join(full[1:]) + _row("foreign-session")
    assert _live_log_problems(before, after, _CHILD_PID) == []
    after_null = b"".join(full[1:]) + _row(None)
    assert _live_log_problems(before, after_null, _CHILD_PID)


def test_live_log_rule_tolerates_a_foreign_row_mid_write_at_first_read():
    tail = _row("foreign-session")
    before = _BASE + tail[:20]
    assert _live_log_problems(before, _BASE + tail, _CHILD_PID) == []


def test_cli_does_not_hang_without_stdin(tmp_path):
    """The regression this change could plausibly introduce.

    rc_facts.py is a SessionStart hook, a UserPromptSubmit hook AND a CLI. A
    blocking stdin read would hang the CLI and, under pythonw.exe where there
    is no stdin at all, hang the hook. Measured end to end rather than argued.

    Also asserts this test does not write into the LIVE log. It used to: a
    subprocess cannot be handed `path=`, so it took the default, and the
    default was production. One line per suite run, indistinguishable from a
    real fire.
    """
    live = _ROOT / "ops" / "runtime" / "hook_invocations.jsonl"
    # RM-459 (2): NOT a whole-file byte compare. Other live sessions append to
    # this file mid-run, which flaked the old `after == before`. The rows are
    # attributed instead - see `_live_log_problems`.
    before = live.read_bytes() if live.exists() else None

    # A stdin-less run has no session id, and without one the watcher fails
    # OPEN: it prints as before and writes NEITHER the per-session record nor
    # the report file. Captured here because this is the one arm that runs the
    # real CLI against the real _ROOT, so a writer that ignored the sid rule
    # would create live ops/runtime files from the suite.
    reported = _ROOT / "ops" / "runtime" / "sync_inbox_reported.json"
    report = _ROOT / "ops" / "runtime" / "sync_inbox_report.txt"
    reported_before = reported.read_bytes() if reported.exists() else None
    report_before = report.read_bytes() if report.exists() else None

    env = dict(os.environ, RC_HOOK_LOG=str(tmp_path / "redirected.jsonl"))
    proc = subprocess.Popen(
        [_PY, str(_ROOT / "tools" / "rc_facts.py"), "--inbox-only"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    proc.communicate(timeout=30)
    assert proc.returncode == 0

    after = live.read_bytes() if live.exists() else None
    problems = _live_log_problems(before, after, proc.pid)
    assert not problems, f"the suite wrote into the live invocation log: {problems}"
    # RM-451: a payload-less run on a tty is a hand run and records NOTHING.
    # Windows reports NUL as a tty, POSIX /dev/null is not one, so the row is
    # expected exactly when DEVNULL is not a tty. Either way it never reaches
    # the live log; tests/test_hook_log_live_isolation.py proves the redirect
    # with an empty pipe, which is a non-tty on every OS.
    with open(os.devnull, "rb") as nul:
        devnull_is_tty = nul.isatty()
    assert (tmp_path / "redirected.jsonl").exists() is (not devnull_is_tty), (
        "the redirect did not take effect, or a tty hand run was recorded")
    # RM-459 (1): the refused tty run is not silent - its marker follows the
    # redirect too.
    assert (tmp_path / "redirected.skipped.jsonl").exists() is devnull_is_tty

    reported_after = reported.read_bytes() if reported.exists() else None
    report_after = report.read_bytes() if report.exists() else None
    assert reported_after == reported_before, "a sid-less run wrote the reported record"
    assert report_after == report_before, "a sid-less run wrote the inbox report file"
