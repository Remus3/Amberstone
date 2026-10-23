"""RM-796: an unwritable report silently dropped an ARMED finding.

Measured at adbd2c93f: `_run` called `write_report` unguarded, so an OSError
on the report path fell through to main()'s outer guard. `_record_internal_error`
then wrote a `findings: []` internal-error row to the history and the hook
returned 0 with nothing on stdout - the finding reached neither the model, nor
the report, nor the history.

Adjudicated 2026-10-23 (distinct adjudicator agent, option A): the report is
bookkeeping like the history and the seen set (`test_history_failure_never_
breaks_the_gate`), so its failure must not suppress the verdict. Armed, fresh
and not re-entry, the hook still emits its ONE feedback line, exit 0, nothing on
stderr; the line ends `; report unwritable` instead of `; see <path>`, because
the path may hold an EARLIER Stop's report. The history keeps the real findings
plus a separate `report_error` field (`reason` stays the stop_hook_active slot).
Report-only mode and re-entry stay silent; the seen set is unchanged.
"""
import json
import subprocess
import sys
from pathlib import Path

from tools import stop_claim_gate as gate

ROOT = Path(__file__).resolve().parent.parent
GATE = ROOT / "tools" / "stop_claim_gate.py"

CLAIM = "The full suite passes."
UNWRITABLE_TAIL = "; report unwritable"


def _transcript(tmp_path, *texts):
    path = tmp_path / "transcript.jsonl"
    rows = [{"type": "assistant",
             "message": {"role": "assistant",
                         "content": [{"type": "text", "text": t}]}} for t in texts]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return path


def _unwritable_report(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, not a directory", encoding="utf-8")
    return blocker / "r.json"


def _run(tmp_path, transcript, *extra, stop_hook_active=False):
    payload = json.dumps({"session_id": "rm796", "cwd": str(ROOT),
                          "transcript_path": str(transcript),
                          "hook_event_name": "Stop",
                          "stop_hook_active": stop_hook_active})
    return subprocess.run([sys.executable, str(GATE), *extra], input=payload,
                          capture_output=True, text=True, cwd=str(tmp_path),
                          check=False, timeout=120)


def _history(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()
            if line.strip()]


def _context(stdout):
    lines = stdout.splitlines()
    assert len(lines) == 1, f"exactly one stdout line: {stdout!r}"
    out = json.loads(lines[0])
    assert set(out) == {"hookSpecificOutput"}
    spec = out["hookSpecificOutput"]
    assert spec["hookEventName"] == "Stop"
    context = spec["additionalContext"]
    assert "\n" not in context and len(context) <= gate.FEEDBACK_MAX, context
    return context


def test_an_unwritable_report_still_emits_one_line_naming_the_count(tmp_path):
    history = tmp_path / "h.jsonl"
    proc = _run(tmp_path, _transcript(tmp_path, CLAIM), "--arm",
                "--report", str(_unwritable_report(tmp_path)), "--history", str(history))
    assert proc.returncode == 0
    assert proc.stderr == "", proc.stderr
    context = _context(proc.stdout)
    assert context == ("stop_claim_gate: 1 unbacked claim (tests_pass_without_run)"
                       + UNWRITABLE_TAIL), context
    assert "see " not in context, "never point at a report this Stop did not write"


def test_the_history_keeps_the_real_findings_and_names_the_report_error(tmp_path):
    history = tmp_path / "h.jsonl"
    _run(tmp_path, _transcript(tmp_path, CLAIM), "--arm",
         "--report", str(_unwritable_report(tmp_path)), "--history", str(history))
    rows = _history(history)
    assert len(rows) == 1, rows
    row = rows[0]
    assert row["findings"] == 1 and row["checks"] == ["tests_pass_without_run"], row
    assert row["blocked"] is True
    assert row["report_error"] == "report-unwritable"
    assert row["reason"] != "internal-error", "not the outer guard's empty row"


def test_report_only_mode_stays_silent_with_an_unwritable_report(tmp_path):
    history = tmp_path / "h.jsonl"
    proc = _run(tmp_path, _transcript(tmp_path, CLAIM),
                "--report", str(_unwritable_report(tmp_path)), "--history", str(history))
    assert proc.returncode == 0
    assert proc.stdout == "" and proc.stderr == "", (proc.stdout, proc.stderr)
    row = _history(history)[-1]
    assert row["findings"] == 1 and row["report_error"] == "report-unwritable", row


def test_re_entry_stays_silent_with_an_unwritable_report(tmp_path):
    history = tmp_path / "h.jsonl"
    proc = _run(tmp_path, _transcript(tmp_path, CLAIM), "--arm",
                "--report", str(_unwritable_report(tmp_path)), "--history", str(history),
                stop_hook_active=True)
    assert proc.returncode == 0
    assert proc.stdout == "" and proc.stderr == "", "re-entry emits nothing - it would loop"
    row = _history(history)[-1]
    assert row["reason"] == "stop_hook_active" and row["blocked"] is False, row
    assert row["report_error"] == "report-unwritable", row


def test_an_unreadable_transcript_with_an_unwritable_report_keeps_its_reason(tmp_path):
    """Sibling call site: the transcript-unreadable early return wrote its
    report unguarded too, so the history said internal-error instead."""
    history = tmp_path / "h.jsonl"
    proc = _run(tmp_path, tmp_path / "missing.jsonl", "--arm",
                "--report", str(_unwritable_report(tmp_path)), "--history", str(history))
    assert proc.returncode == 0
    assert proc.stdout == "" and proc.stderr == ""
    row = _history(history)[-1]
    assert row["reason"] == "transcript-unreadable", row
    assert row["report_error"] == "report-unwritable", row


class _Stdin:
    def __init__(self, text):
        self._text = text

    def read(self):
        return self._text


def test_a_failed_second_report_write_still_emits_the_line(tmp_path, monkeypatch, capsys):
    """The fired path rewrites the report with its message; a failure THERE
    used to escape to the outer guard after the first write had succeeded."""
    real = gate.write_report
    calls = []

    def flaky(report, target):
        calls.append(target)
        if len(calls) > 1:
            raise OSError("synthetic: disk full on the second write")
        real(report, target)

    monkeypatch.setattr(gate, "write_report", flaky)
    monkeypatch.setattr(sys, "stdin", _Stdin(json.dumps(
        {"session_id": "rm796-second", "transcript_path": str(_transcript(tmp_path, CLAIM))})))
    report = tmp_path / "r.json"
    assert gate.main(["--arm", "--report", str(report),
                      "--history", str(tmp_path / "h.jsonl")]) == 0
    assert len(calls) == 2, calls
    out = capsys.readouterr()
    assert out.err == ""
    context = _context(out.out)
    assert context.startswith("stop_claim_gate: 1 unbacked claim (tests_pass_without_run)")
    assert context.endswith("r.json"), "the first write landed: this Stop's report is there"
    assert json.loads(report.read_text(encoding="utf-8"))["findings"], "first write kept"


def test_feedback_line_unit_says_unwritable_in_place_of_the_path():
    line = gate.feedback_line([{"check": "count_mismatch"}], gate.DEFAULT_REPORT,
                              unwritable=True)
    assert line == "stop_claim_gate: 1 unbacked claim (count_mismatch)" + UNWRITABLE_TAIL


def test_feedback_line_unit_unwritable_truncates_codes_within_the_limit():
    findings = [{"check": f"code_{i:02d}_with_a_long_name"} for i in range(12)]
    line = gate.feedback_line(findings, "C:/" + "p" * 200 + "/r.json", unwritable=True)
    assert len(line) <= gate.FEEDBACK_MAX and "\n" not in line
    assert line.startswith("stop_claim_gate: 12 unbacked claims (code_00_with_a_long_name,")
    assert line.endswith("more)" + UNWRITABLE_TAIL), line


def test_feedback_line_unit_default_is_unchanged():
    assert gate.feedback_line([{"check": "count_mismatch"}], gate.DEFAULT_REPORT) == (
        "stop_claim_gate: 1 unbacked claim (count_mismatch); "
        "see ops/runtime/stop_claim_report.json")
