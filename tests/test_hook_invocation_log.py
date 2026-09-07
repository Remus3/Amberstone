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
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.rc_facts import (  # noqa: E402
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
    record_invocation(
        "UserPromptSubmit",
        {"prompt": "SECRETPROMPT", "cwd": r"C:\Users\SOMEONE\private", "session_id": "s1"},
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


def test_cli_does_not_hang_without_stdin():
    """The regression this change could plausibly introduce.

    rc_facts.py is a SessionStart hook, a UserPromptSubmit hook AND a CLI. A
    blocking stdin read would hang the CLI and, under pythonw.exe where there
    is no stdin at all, hang the hook. Measured end to end rather than argued.
    """
    r = subprocess.run(
        [_PY, str(_ROOT / "tools" / "rc_facts.py"), "--inbox-only"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=30,
    )
    assert r.returncode == 0
