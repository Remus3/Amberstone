"""RM-136 - Stop-hook claim gate (CCR-127 wire + CCR-143 taxonomy).

Written test-first. Fixture transcripts are BUILT here rather than checked in as
.jsonl blobs: the shape is measured (2026-08-01, CLI 2.1.220) and a builder keeps
every case readable and diffable. The two load-bearing cases are the NEGATIVES -
a clean session and a genuinely-backed claim must NOT flag. A detector that flags
everything is the same dead-guard class as a parser that matches nothing.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
GATE = ROOT / "tools" / "stop_claim_gate.py"


def _assistant(*blocks):
    return {"type": "assistant", "message": {"role": "assistant", "content": list(blocks)}}


def _text(text):
    return {"type": "text", "text": text}


def _tool_use(name, **kwargs):
    return {"type": "tool_use", "name": name, "input": kwargs}


def _tool_result(text):
    return {"type": "user",
            "message": {"role": "user",
                        "content": [{"type": "tool_result", "content": text}]}}


def _write_transcript(tmp_path, rows):
    path = tmp_path / "transcript.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return path


def _run_gate(tmp_path, rows):
    """Invoke the gate exactly as a Stop hook would: JSON on stdin."""
    transcript = _write_transcript(tmp_path, rows)
    report = tmp_path / "report.json"
    payload = json.dumps({
        "session_id": "test-session",
        "transcript_path": str(transcript),
        "cwd": str(ROOT),
        "hook_event_name": "Stop",
        "stop_hook_active": False,
    })
    proc = subprocess.run(
        [sys.executable, str(GATE), "--report", str(report),
         "--history", str(tmp_path / "history.jsonl")],
        input=payload, capture_output=True, text=True, cwd=str(ROOT), check=False)
    assert proc.returncode == 0, f"report-only mode must exit 0: {proc.stderr}"
    return json.loads(report.read_text(encoding="utf-8"))


def _checks(report):
    return {f["check"] for f in report["findings"]}


PYTEST_GREEN = "==== 1397 passed, 12 skipped in 41.02s ===="


def test_gate_exists():
    assert GATE.exists(), "tools/stop_claim_gate.py must exist"


# ---------------------------------------------------------------- positives

def test_tests_pass_claim_with_no_test_run_is_flagged(tmp_path):
    rows = [_assistant(_text("Done - the full suite passes."))]
    report = _run_gate(tmp_path, rows)
    assert "tests_pass_without_run" in _checks(report)


def test_count_claim_mismatching_observed_summary_is_flagged(tmp_path):
    rows = [
        _assistant(_tool_use("Bash", command="python -m pytest -q")),
        _tool_result(PYTEST_GREEN),
        _assistant(_text("Suite green: 1500 passed.")),
    ]
    report = _run_gate(tmp_path, rows)
    assert "count_mismatch" in _checks(report)
    finding = next(f for f in report["findings"] if f["check"] == "count_mismatch")
    assert "1500" in finding["claimed"]
    assert "1397" in finding["observed"]


def test_file_edited_claim_with_no_edit_is_flagged(tmp_path):
    rows = [_assistant(_text("I updated core/ports.py to add the constant."))]
    report = _run_gate(tmp_path, rows)
    assert "file_claim_without_edit" in _checks(report)


def test_ci_green_claim_without_probe_is_flagged(tmp_path):
    rows = [_assistant(_text("CI is green on that commit."))]
    report = _run_gate(tmp_path, rows)
    assert "ci_claim_without_probe" in _checks(report)


def test_hook_bypass_is_flagged_on_evidence_alone(tmp_path):
    rows = [_assistant(_tool_use("Bash", command="git commit --no-verify -m wip"))]
    report = _run_gate(tmp_path, rows)
    assert "hook_bypass" in _checks(report)


def test_commit_claim_without_commit_is_flagged(tmp_path):
    rows = [_assistant(_text("Committed and pushed."))]
    checks = _checks(_run_gate(tmp_path, rows))
    assert "commit_claim_without_commit" in checks
    assert "push_claim_without_push" in checks


def test_full_suite_claim_over_a_filtered_run_is_flagged(tmp_path):
    rows = [
        _assistant(_tool_use("Bash", command="python -m pytest tests/test_ports.py -k ds")),
        _tool_result("==== 3 passed in 0.40s ===="),
        _assistant(_text("Full suite green - 3 passed.")),
    ]
    report = _run_gate(tmp_path, rows)
    assert "full_suite_claim_over_filtered_run" in _checks(report)


def test_no_tests_ran_under_a_pass_claim_is_flagged(tmp_path):
    rows = [
        _assistant(_tool_use("Bash", command="python -m pytest -q")),
        _tool_result("no tests ran in 0.01s"),
        _assistant(_text("Tests pass.")),
    ]
    report = _run_gate(tmp_path, rows)
    assert "vacuous_run" in _checks(report)


# ---------------------------------------------------------------- negatives
# These two are the load-bearing cases. A gate that fails them gets disabled.

def test_clean_session_with_no_claims_does_not_flag(tmp_path):
    rows = [
        _assistant(_text("Here is what core/ports.py currently declares.")),
        _assistant(_tool_use("Read", file_path="core/ports.py")),
        _tool_result("PORT_DS = 8860"),
        _assistant(_text("That is the whole answer - no changes needed.")),
    ]
    report = _run_gate(tmp_path, rows)
    assert report["findings"] == [], report["findings"]


def test_backed_claims_do_not_flag(tmp_path):
    rows = [
        _assistant(_tool_use("Edit", file_path=str(ROOT / "core" / "ports.py"))),
        _tool_result("ok"),
        _assistant(_tool_use("Bash", command="python -m pytest -q")),
        _tool_result(PYTEST_GREEN),
        _assistant(_tool_use("Bash", command="git commit -m 'feat: x'")),
        _tool_result("[main abc1234] feat: x"),
        _assistant(_tool_use("Bash", command="git push")),
        _tool_result("main -> main"),
        _assistant(_text("I updated core/ports.py; the suite is green at 1397 passed, "
                         "committed and pushed.")),
    ]
    report = _run_gate(tmp_path, rows)
    assert report["findings"] == [], report["findings"]


# ---------------------------------------------------------------- contract

def test_report_is_written_atomically_and_is_report_only(tmp_path):
    report = _run_gate(tmp_path, [_assistant(_text("The suite passes."))])
    assert report["mode"] == "report-only"
    assert report["armed"] is False
    assert report["session_id"] == "test-session"
    assert isinstance(report["findings"], list)


def test_missing_transcript_is_soft_failure(tmp_path):
    payload = json.dumps({"session_id": "s", "transcript_path": str(tmp_path / "nope.jsonl"),
                          "hook_event_name": "Stop"})
    out = tmp_path / "r.json"
    proc = subprocess.run([sys.executable, str(GATE), "--report", str(out),
                           "--history", str(tmp_path / "history.jsonl")],
                          input=payload, capture_output=True, text=True,
                          cwd=str(ROOT), check=False)
    assert proc.returncode == 0
    assert json.loads(out.read_text(encoding="utf-8"))["error"] == "transcript-unreadable"


@pytest.mark.parametrize("flag", ["--no-verify", "--no-gpg-sign", "-c core.hooksPath="])
def test_every_bypass_form_is_caught(tmp_path, flag):
    rows = [_assistant(_tool_use("Bash", command=f"git commit {flag} -m x"))]
    assert "hook_bypass" in _checks(_run_gate(tmp_path, rows))


# ------------------------------------------------- false positives, measured
# All three classes below were produced by the ARMED gate against this repo's
# own session on 2026-08-01: 9 findings, 9 false positives. Every one came from
# the gate reading a DESCRIPTION of a thing as the thing itself.

def test_bypass_flag_quoted_inside_a_heredoc_is_not_a_bypass(tmp_path):
    """The session was writing documentation that names the flag, not using it."""
    doc = ("python - <<'PYEOF'\n"
           "entry = 'hook bypass (--no-verify / --no-gpg-sign / core.hooksPath=), "
           "which fires on EVIDENCE alone'\n"
           "PYEOF")
    report = _run_gate(tmp_path, [_assistant(_tool_use("Bash", command=doc))])
    assert report["findings"] == [], report["findings"]


def test_prose_containing_no_tests_ran_does_not_poison_a_real_run(tmp_path):
    """One phrase in unrelated output must not mark the whole session vacuous."""
    rows = [
        _assistant(_tool_use("Bash", command="python -m pytest -q")),
        _tool_result(PYTEST_GREEN),
        _assistant(_tool_use("Bash", command="git commit -F msg.txt")),
        _tool_result("wrote: a pass claim over a run whose output says no tests ran"),
        _assistant(_text("Suite green at 1397 passed.")),
    ]
    report = _run_gate(tmp_path, rows)
    assert report["findings"] == [], report["findings"]


def test_a_claim_quoted_as_an_example_is_not_a_claim(tmp_path):
    """Backticked and quoted text is a quotation. Only bare prose asserts."""
    rows = [_assistant(_text(
        'The fixture is `"I updated core/ports.py to add X"` and the probe claimed '
        '"I updated core/nonexistent_probe.py" - both are examples.'))]
    report = _run_gate(tmp_path, rows)
    assert report["findings"] == [], report["findings"]


def test_counts_come_only_from_a_paired_pytest_run(tmp_path):
    """A number in unrelated output is not an observation of a suite result."""
    rows = [
        _assistant(_tool_use("Bash", command="git log --oneline")),
        _tool_result("older entry mentioning 9999 passed"),
        _assistant(_tool_use("Bash", command="python -m pytest -q")),
        _tool_result(PYTEST_GREEN),
        _assistant(_text("The suite is green at 1397 passed.")),
    ]
    assert _run_gate(tmp_path, rows)["findings"] == []


def test_the_real_transcript_that_produced_nine_false_positives_is_clean(tmp_path):
    """Regression anchor: the actual 2026-08-01 session, replayed."""
    # The fixture is TRACKED, so a checkout always has it and skipping on its
    # absence is an always-passing guard - the exact class
    # test_skip_condition_hygiene bans. If it goes missing, that is the
    # regression anchor being deleted, and it must FAIL loudly.
    fixture = Path(__file__).parent / "fixtures" / "stop_claim_gate_false_positives.jsonl"
    assert fixture.exists(), f"tracked regression anchor is missing: {fixture}"
    out = tmp_path / "r.json"
    payload = json.dumps({"session_id": "replay", "transcript_path": str(fixture),
                          "hook_event_name": "Stop", "stop_hook_active": False})
    proc = subprocess.run([sys.executable, str(GATE), "--report", str(out),
                           "--history", str(tmp_path / "history.jsonl")],
                          input=payload, capture_output=True, text=True,
                          cwd=str(ROOT), check=False)
    assert proc.returncode == 0
    findings = json.loads(out.read_text(encoding="utf-8"))["findings"]
    assert findings == [], f"{len(findings)} false positive(s) still fire"


# ---------------------------------------------------------------- armed mode
# Exit 2 on Stop does not merely warn: it BLOCKS the session from ending and
# feeds stderr back to the model. That makes re-entry the danger, not noise.

def _run_armed(tmp_path, rows, stop_hook_active=False):
    transcript = _write_transcript(tmp_path, rows)
    report = tmp_path / "report.json"
    payload = json.dumps({"session_id": "armed", "transcript_path": str(transcript),
                          "hook_event_name": "Stop", "stop_hook_active": stop_hook_active})
    proc = subprocess.run([sys.executable, str(GATE), "--arm", "--report", str(report),
                           "--history", str(tmp_path / "history.jsonl")],
                          input=payload, capture_output=True, text=True,
                          cwd=str(ROOT), check=False)
    return proc, json.loads(report.read_text(encoding="utf-8"))


def test_armed_blocks_on_findings(tmp_path):
    proc, report = _run_armed(tmp_path, [_assistant(_text("The full suite passes."))])
    assert proc.returncode == 2
    assert report["mode"] == "armed"
    # stderr is what the model is shown, so it must name the check and the quote.
    assert "tests_pass_without_run" in proc.stderr
    assert "full suite passes" in proc.stderr


def test_armed_is_silent_on_a_clean_session(tmp_path):
    proc, report = _run_armed(tmp_path, [_assistant(_text("Read the file, no changes."))])
    assert proc.returncode == 0
    assert report["findings"] == []


def test_armed_never_blocks_twice_on_re_entry(tmp_path):
    """stop_hook_active means we already blocked once. Blocking again loops."""
    rows = [_assistant(_text("The full suite passes."))]
    proc, report = _run_armed(tmp_path, rows, stop_hook_active=True)
    assert proc.returncode == 0, "re-entry must not block again"
    assert report["findings"], "it still reports - it just stops blocking"
    assert report["blocked"] is False
    assert report["reason"] == "stop_hook_active"


# ------------------------------------------------------- rolling history
# The report is overwritten on every Stop, so it can only ever say "the LAST
# session was clean". The arm/disarm call needs "quiet ACROSS sessions", which
# is an n greater than 1 - and n=1 is exactly what the first arm decision had.

def _run_with_history(tmp_path, rows, history, extra=(), armed=False, name="s"):
    transcript = _write_transcript(tmp_path, rows)
    payload = json.dumps({"session_id": name, "transcript_path": str(transcript),
                          "hook_event_name": "Stop", "stop_hook_active": False})
    cmd = [sys.executable, str(GATE), "--report", str(tmp_path / f"{name}.json"),
           "--history", str(history), *extra]
    if armed:
        cmd.insert(2, "--arm")
    return subprocess.run(cmd, input=payload, capture_output=True, text=True,
                          cwd=str(ROOT), check=False)


def _history(path):
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln]


def test_history_appends_one_line_per_run(tmp_path):
    hist = tmp_path / "h.jsonl"
    for i in range(3):
        _run_with_history(tmp_path, [_assistant(_text("Read the file."))], hist, name=f"s{i}")
    rows = _history(hist)
    assert len(rows) == 3
    assert [r["session_id"] for r in rows] == ["s0", "s1", "s2"]


def test_history_records_a_clean_session_too(tmp_path):
    """A quiet run MUST leave a line. Logging only findings cannot prove quiet."""
    hist = tmp_path / "h.jsonl"
    _run_with_history(tmp_path, [_assistant(_text("Read the file, no changes."))], hist)
    row, = _history(hist)
    assert row["findings"] == 0
    assert row["checks"] == []
    assert row["blocked"] is False


def test_history_line_carries_the_decision_fields(tmp_path):
    hist = tmp_path / "h.jsonl"
    proc = _run_with_history(tmp_path, [_assistant(_text("The full suite passes."))],
                             hist, armed=True, name="armed")
    assert proc.returncode == 2
    row, = _history(hist)
    assert row["armed"] is True and row["mode"] == "armed"
    assert row["blocked"] is True
    assert row["findings"] == 1
    assert row["checks"] == ["tests_pass_without_run"]
    assert row["ts"].startswith("20") and row["ts"].endswith("+00:00")


def test_history_records_the_soft_failure_path(tmp_path):
    """transcript-unreadable is signal, not silence - a run that audited nothing."""
    hist = tmp_path / "h.jsonl"
    payload = json.dumps({"session_id": "bad", "hook_event_name": "Stop",
                          "transcript_path": str(tmp_path / "nope.jsonl")})
    proc = subprocess.run([sys.executable, str(GATE), "--report", str(tmp_path / "r.json"),
                           "--history", str(hist)],
                          input=payload, capture_output=True, text=True,
                          cwd=str(ROOT), check=False)
    assert proc.returncode == 0
    row, = _history(hist)
    assert row["reason"] == "transcript-unreadable"


def test_history_rolls_to_the_cap_keeping_the_newest(tmp_path):
    hist = tmp_path / "h.jsonl"
    for i in range(6):
        _run_with_history(tmp_path, [_assistant(_text("Read it."))], hist,
                          extra=["--history-max", "3"], name=f"n{i}")
    rows = _history(hist)
    assert len(rows) == 3
    assert [r["session_id"] for r in rows] == ["n3", "n4", "n5"]


def test_history_failure_never_breaks_the_gate(tmp_path):
    """Bookkeeping is not the gate. An unwritable history must not change the
    exit code or lose the report - a Stop hook that raises is worse than one
    that keeps no history."""
    blocked_path = tmp_path / "adir"
    blocked_path.mkdir()  # a directory where a file is expected
    report = tmp_path / "r.json"
    transcript = _write_transcript(tmp_path, [_assistant(_text("The full suite passes."))])
    payload = json.dumps({"session_id": "x", "transcript_path": str(transcript),
                          "hook_event_name": "Stop", "stop_hook_active": False})
    proc = subprocess.run([sys.executable, str(GATE), "--arm", "--report", str(report),
                           "--history", str(blocked_path)],
                          input=payload, capture_output=True, text=True,
                          cwd=str(ROOT), check=False)
    assert proc.returncode == 2, "the gate still blocks even with no history"
    assert json.loads(report.read_text(encoding="utf-8"))["findings"]


# ------------------------------------- backgrounded runs defer their summary
# Measured 2026-08-01: the gate blocked a Stop on a claim that WAS backed. A
# pytest run started with run_in_background gets a launcher handoff as its
# paired tool_result ("Command running in background with ID: ..."), so the real
# summary - which arrives later when the output file is read - was never
# collected, and every count in it read as unobserved. The evidence collector
# was blind to a transport, which is the shape of
# reference_ds_route_seam_transport_vs_flag. Widening EVIDENCE, never the claim.

BG_HANDOFF = ("Command running in background with ID: bsw0jw8f5. Output is being "
              "written to: C:\tmp\tasks\bsw0jw8f5.output")
BIG_SUMMARY = "17784 passed, 108 skipped, 1370 subtests passed in 170.67s (0:02:50)"


def _backgrounded_suite(claim, summary=BIG_SUMMARY):
    """The MEASURED shape, and the leading foreground run is load-bearing.

    With no counts collected at all, check 2 is inert - `observed_counts` is
    empty and nothing can mismatch. The real session had small foreground runs
    (26, 29, 30, 52) that filled it, and THAT is what made the big deferred
    number read as unobserved. A fixture without them tests nothing.
    """
    return [
        _assistant(_tool_use("Bash", command="python -m pytest tests/test_x.py -q")),
        _tool_result("==== 30 passed in 2.68s ===="),
        _assistant(_tool_use("Bash", command="python -m pytest tests/ -q -n 8")),
        _tool_result(BG_HANDOFF),
        _assistant(_tool_use("Bash", command="tail -4 C:/tmp/tasks/bsw0jw8f5.output")),
        _tool_result(summary),
        _assistant(_text(claim)),
    ]


def test_background_run_summary_read_later_is_credited(tmp_path):
    report = _run_gate(tmp_path, _backgrounded_suite(
        "Full suite fresh: 17784 passed, 108 skipped, 0 failed."))
    assert report["findings"] == [], report["findings"]


def test_background_run_still_catches_a_wrong_count(tmp_path):
    """Crediting the deferred summary must not stop the check working."""
    report = _run_gate(tmp_path, _backgrounded_suite("Full suite fresh: 99999 passed."))
    finding = next(f for f in report["findings"] if f["check"] == "count_mismatch")
    assert finding["claimed"] == "99999"
    assert "17784" in finding["observed"]


def test_a_floating_count_is_not_a_summary_even_after_a_background_run(tmp_path):
    """The load-bearing negative. Only pytest TERMINAL-SUMMARY shape counts; a
    bare 'N passed' anywhere in a tool result is what poisoned the first armed
    gate and must stay uncredited."""
    rows = _backgrounded_suite("The suite is green at 99999 passed.",
                               summary="the log mentions 99999 passed items earlier")
    assert "count_mismatch" in _checks(_run_gate(tmp_path, rows))


def test_no_background_run_means_no_deferred_crediting(tmp_path):
    """Without a backgrounded run there is nothing to defer, so a summary-shaped
    string in an unrelated tool result must NOT become evidence."""
    rows = [
        _assistant(_tool_use("Bash", command="python -m pytest tests/ -q")),
        _tool_result("==== 12 passed in 1.00s ===="),
        _assistant(_tool_use("Read", file_path="notes.md")),
        _tool_result("an old note says 17784 passed in 170.67s"),
        _assistant(_text("The suite is green at 17784 passed.")),
    ]
    assert "count_mismatch" in _checks(_run_gate(tmp_path, rows))


# ------------------------------------ prose ordinals are not pytest counts
# Second false positive measured 2026-08-01, from replaying this session's own
# transcript: "Test 1 passed for the wrong reason" was read as a claim of a
# 1-test suite. "Test <n> passed" is an ordinal reference to one named case,
# never a summary count. Narrowing the CLAIM parser, not the check.

@pytest.mark.parametrize("sentence", [
    "Test 1 passed for the wrong reason - the check was inert.",
    "Mutant 2 passed, so that guard is untested.",
    "Step 3 passed and the rest were skipped.",
])
def test_prose_ordinals_are_not_read_as_suite_counts(tmp_path, sentence):
    rows = [
        _assistant(_tool_use("Bash", command="python -m pytest -q")),
        _tool_result(PYTEST_GREEN),
        _assistant(_text(sentence)),
    ]
    assert "count_mismatch" not in _checks(_run_gate(tmp_path, rows))


def test_a_real_count_claim_next_to_a_noun_still_flags(tmp_path):
    """The narrowing must not swallow a genuine miscount."""
    rows = [
        _assistant(_tool_use("Bash", command="python -m pytest -q")),
        _tool_result(PYTEST_GREEN),
        _assistant(_text("The suite reports 1500 passed.")),
    ]
    assert "count_mismatch" in _checks(_run_gate(tmp_path, rows))
