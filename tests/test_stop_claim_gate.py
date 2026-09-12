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

from tools import stop_claim_gate as gate

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

# Node's built-in test runner (rc-shell) reports in a DIFFERENT shape: no
# "N passed", no trailing "in X.Ys", and an information marker glyph in
# front of every summary line. The glyph and the newlines are built with
# chr() so this file stays 7-bit ASCII (repo hard rule) and carries no
# escape-sequence ambiguity.
_INFO = chr(0x2139)
_NL = chr(10)
NODE_GREEN = _NL.join([
    _INFO + " tests 328",
    _INFO + " suites 0",
    _INFO + " pass 328",
    _INFO + " fail 0",
    _INFO + " cancelled 0",
    _INFO + " skipped 0",
    _INFO + " todo 0",
    _INFO + " duration_ms 2040.4645",
]) + _NL

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


def test_counterfactual_file_mention_is_not_a_claim(tmp_path):
    """A hypothetical edit asserts nothing about what this session did.

    MEASURED 2026-08-03: this exact sentence blocked four consecutive Stops on a
    session that had edited no such file. CLAIM_FILE sees `added ... CLAUDE.md`
    and cannot tell the indicative from the conditional, but "an entry ADDED to
    CLAUDE.md WOULD leave the watchdog auto-merging" describes a hypothetical
    future edit by someone else. There is no way to retract a sentence already in
    the transcript, so a false positive here is unfixable by the model and blocks
    the session forever - which is why this is a check fix, not a prose fix.
    """
    rows = [_assistant(_text(
        "Nothing asserted the two still matched, so an entry added to CLAUDE.md "
        "alone would leave the watchdog silently auto-merging into a "
        "newly-frozen file."))]
    report = _run_gate(tmp_path, rows)
    assert "file_claim_without_edit" not in _checks(report)


def test_conditional_phrasings_do_not_launder_a_real_edit_claim(tmp_path):
    """The suppression must not become an evasion hatch.

    A first-person completed-action marker VETOES the hypothetical suppression,
    so a real claim carrying an incidental modal still flags. Without this the
    fix would be a loosening rather than a precision gain - the exact failure the
    drift-guard rule warns about.
    """
    for text in (
        "I edited CLAUDE.md, which would break the watchdog.",
        "We added a row to core/ports.py so it could be reused later.",
        "I have modified tools/foo.py, if that matters.",
    ):
        report = _run_gate(tmp_path, [_assistant(_text(text))])
        assert "file_claim_without_edit" in _checks(report), text


def test_plain_hypothetical_without_modal_still_flags(tmp_path):
    """Suppression needs an unreality marker - absence of one is still a claim."""
    rows = [_assistant(_text("An entry added to CLAUDE.md leaves it stale."))]
    report = _run_gate(tmp_path, rows)
    assert "file_claim_without_edit" in _checks(report)


def test_a_file_cited_as_a_precedent_is_not_an_edit_claim(tmp_path):
    """Naming the file you COPIED FROM is a pointer, not a claim of authorship.

    MEASURED 2026-08-03, lane 8: this exact sentence blocked the Stop on a
    session whose whole point was that it copied an existing containment pattern
    rather than inventing one. CLAIM_FILE matches a claim-verb within 40 chars of
    a filename and cannot tell "fixed X" from "fixed it the way X does".

    Same unfixable-by-the-model shape as the counterfactual above: the sentence
    is already in the transcript and cannot be retracted, so every later Stop
    blocks too. Worse, the pressure it creates is backwards - the cheapest way to
    satisfy the gate would be to stop citing precedent, and citing precedent is
    the behaviour the repo wants.
    """
    rows = [_assistant(_text(
        "Fixed with the in-tree precedent at dashboard/routes_static.py:64-67 - "
        "resolve the root, resolve the candidate, assert relative_to."))]
    report = _run_gate(tmp_path, rows)
    assert "file_claim_without_edit" not in _checks(report)


@pytest.mark.parametrize("sentence", [
    "Fixed per core/polled_json.py, which owns the atomic writer.",
    "Hardened it, see tools/truth_gate.py for the deeper check.",
    "Added the guard following the example in tests/test_ports.py.",
])
def test_every_citation_marker_form_suppresses(tmp_path, sentence):
    report = _run_gate(tmp_path, [_assistant(_text(sentence))])
    assert "file_claim_without_edit" not in _checks(report), sentence


@pytest.mark.parametrize("sentence", [
    "I fixed it per the precedent in dashboard/routes_static.py.",
    "We added the guard following the example in tests/test_ports.py.",
    "I patched it as in tools/truth_gate.py.",
])
def test_a_citation_marker_cannot_launder_a_first_person_edit(tmp_path, sentence):
    """The suppression must not become an evasion hatch.

    A first-person completed-action marker VETOES it, exactly as it vetoes the
    counterfactual suppression. Without this, wrapping any real claim in "per
    the precedent in X" would silence the check.

    Every sentence here puts the citation marker BETWEEN the verb and the path,
    which is the only position that triggers the suppression at all - an earlier
    draft of this test used trailing markers, so it passed with the veto deleted
    and proved nothing. Mutation testing caught that; contrast the second case
    with its marker-identical, first-person-free twin above, which must suppress.
    """
    report = _run_gate(tmp_path, [_assistant(_text(sentence))])
    assert "file_claim_without_edit" in _checks(report), sentence


def test_a_citation_marker_after_the_filename_does_not_suppress(tmp_path):
    """Only a marker BETWEEN the verb and the path puts the path in a citation
    role. One trailing "per the precedent" must not retro-license the claim."""
    rows = [_assistant(_text(
        "Updated core/ports.py per the precedent."))]
    report = _run_gate(tmp_path, rows)
    assert "file_claim_without_edit" in _checks(report)


def test_a_negated_commit_statement_is_not_a_commit_claim(tmp_path):
    """"Nothing is committed yet" asserts the OPPOSITE of having committed.

    MEASURED 2026-08-03, lane 8: reporting honestly that no commit had happened
    was itself flagged as an unbacked commit claim. CLAIM_COMMIT matches the word
    and cannot see the negation governing it - the same assertion-versus-denial
    blindness the counterfactual fix addressed for CLAIM_FILE.
    """
    for text in ("Nothing is committed yet.",
                 "I have not committed this.",
                 "No part of it is committed."):
        report = _run_gate(tmp_path, [_assistant(_text(text))])
        assert "commit_claim_without_commit" not in _checks(report), text


def test_a_negated_push_statement_is_not_a_push_claim(tmp_path):
    """Same shape, the sibling check - fixed together, not one at a time."""
    for text in ("Nothing is pushed yet.", "The branch is not pushed."):
        report = _run_gate(tmp_path, [_assistant(_text(text))])
        assert "push_claim_without_push" not in _checks(report), text


@pytest.mark.parametrize("sentence", [
    "I committed the fix, but not the docs.",
    "The branch is pushed, not merged.",
])
def test_a_trailing_negation_does_not_launder_a_real_claim(tmp_path, sentence):
    """The negation must GOVERN the claim word, not merely share the sentence."""
    report = _run_gate(tmp_path, [_assistant(_text(sentence))])
    checks = _checks(report)
    assert ("commit_claim_without_commit" in checks
            or "push_claim_without_push" in checks), sentence


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


# --------------------------- space-grouped thousands are ONE number (RM-398)
# Same family as the ordinal narrowing above, different separator. MEASURED
# 2026-09-10 against the prose "10 856 passed": CLAIM_COUNT.findall returns
# ('10', '856'), so the gate reports the session claimed "856" - a string that
# appears nowhere in the transcript. The claim is TRUE (the run printed 10856)
# and the finding is a pure false positive.
#
# The discriminator is EVIDENCE-DERIVED, not shape-only: the pair is dropped
# only when the JOINED form is in observed_counts. A shape-only first version
# was measured the same day to swallow "lane 8 328 passed" against an observed
# 1397, which reads as an ordinary suite total - see CLAIM_COUNT_GROUPED for
# the full refutation. An unobserved join falls through to the ORIGINAL
# behaviour, so nothing that used to flag stops flagging.

GROUPED_GREEN = "==== 10856 passed, 12 skipped in 410.02s ===="


def test_space_grouped_thousands_are_not_read_as_two_numbers(tmp_path):
    """The load-bearing case: a TRUE claim written with a space separator."""
    rows = [
        _assistant(_tool_use("Bash", command="python -m pytest -q")),
        _tool_result(GROUPED_GREEN),
        _assistant(_text("Full suite green: 10 856 passed.")),
    ]
    report = _run_gate(tmp_path, rows)
    assert "count_mismatch" not in _checks(report), (
        "'856' was never claimed - it is the trailing group of 10856")


def test_a_space_grouped_count_nobody_observed_still_flags(tmp_path):
    """The same prose with NO 10856 run behind it must still flag.

    Suppression is licensed by the evidence, not by the shape. Observed is
    1397, so the join 10856 is unobserved and the pair falls through to the
    original behaviour.
    """
    rows = [
        _assistant(_tool_use("Bash", command="python -m pytest -q")),
        _tool_result(PYTEST_GREEN),
        _assistant(_text("Full suite green: 10 856 passed.")),
    ]
    assert "count_mismatch" in _checks(_run_gate(tmp_path, rows))


def test_a_word_then_digit_then_three_digit_total_still_flags(tmp_path):
    """Regression fence for the hole the shape-only version opened.

    MEASURED 2026-09-10: under the blanket drop this went FLAG -> SILENT, which
    made every 3-digit suite total 000-999 unflaggable behind any 1-3 digit
    token. "lane 8 328 passed" reads as an ordinary suite total, so the
    "no reader parses it as a total" fence was false.
    """
    rows = [
        _assistant(_tool_use("Bash", command="python -m pytest -q")),
        _tool_result(PYTEST_GREEN),
        _assistant(_text("On lane 8 328 passed and nothing failed.")),
    ]
    report = _run_gate(tmp_path, rows)
    assert "count_mismatch" in _checks(report)
    claimed = [f["claimed"] for f in report["findings"]
               if f["check"] == "count_mismatch"]
    assert claimed == ["328"], (
        "the claim is 328 - reporting the join 8328 would invent a string "
        "that appears nowhere in the prose")


def test_a_digit_prefix_that_is_not_a_grouping_is_left_alone(tmp_path):
    """Anti-join fence: "run 2 1397 passed" is two numbers, and 1397 is TRUE.

    Green today and green under the evidence-derived guard, because a 4-digit
    count never reaches it. It exists to fail loudly if the length test is ever
    widened, which would read this as a claim of 21397.
    """
    rows = [
        _assistant(_tool_use("Bash", command="python -m pytest -q")),
        _tool_result(PYTEST_GREEN),
        _assistant(_text("In run 2 1397 passed and nothing failed.")),
    ]
    assert "count_mismatch" not in _checks(_run_gate(tmp_path, rows))


@pytest.mark.parametrize("sentence", [
    "Full suite green: 1234 passed.",          # bare, unchanged
    "Full suite green: 1,234 passed.",         # comma-grouped, unchanged
    "Full suite: 3 failed 856 passed.",        # two real numbers, unchanged
])
def test_unseparated_and_comma_grouped_counts_still_flag(tmp_path, sentence):
    """Every shape the narrowing must NOT reach. Observed is 1397."""
    rows = [
        _assistant(_tool_use("Bash", command="python -m pytest -q")),
        _tool_result(PYTEST_GREEN),
        _assistant(_text(sentence)),
    ]
    assert "count_mismatch" in _checks(_run_gate(tmp_path, rows))


# ---------------------------------- gh invoked by absolute path via a variable
# Third false positive, measured 2026-08-01 during /done. EV_CI required `gh`
# ADJACENT to its subcommand, but OPERATIONS/the done ritual mandate the
# absolute path (`GH="C:/Program Files/GitHub CLI/gh.exe"; "$GH" run list`), so
# the literal "gh run" never appears and a real, repeated CI probe read as none.
# The gate's own house style guaranteed this fires on every wrap.

GH_ABS = 'GH="C:/Program Files/GitHub CLI/gh.exe"; "$GH" run list --branch main --limit 3'


def test_gh_invoked_by_absolute_path_counts_as_a_ci_probe(tmp_path):
    rows = [
        _assistant(_tool_use("Bash", command=GH_ABS)),
        _tool_result("completed success ci 30722182355"),
        _assistant(_text("All CI settled green.")),
    ]
    assert "ci_claim_without_probe" not in _checks(_run_gate(tmp_path, rows))


def test_plain_gh_run_still_counts(tmp_path):
    rows = [
        _assistant(_tool_use("Bash", command="gh run list --limit 3")),
        _tool_result("completed success"),
        _assistant(_text("CI is green.")),
    ]
    assert "ci_claim_without_probe" not in _checks(_run_gate(tmp_path, rows))


def test_a_ci_claim_with_no_gh_probe_at_all_still_flags(tmp_path):
    """The load-bearing negative: widening the BINARY form must not turn the
    check off. A bare claim with no probe remains the whole point of check 4."""
    rows = [_assistant(_text("CI is green on that commit."))]
    assert "ci_claim_without_probe" in _checks(_run_gate(tmp_path, rows))


def test_an_unrelated_run_word_is_not_a_ci_probe(tmp_path):
    """`run` is a common word. Without a gh binary it proves nothing."""
    rows = [
        _assistant(_tool_use("Bash", command="python -m pytest tests/ -q  # full run")),
        _tool_result("==== 12 passed in 1.00s ===="),
        _assistant(_text("CI is green.")),
    ]
    assert "ci_claim_without_probe" in _checks(_run_gate(tmp_path, rows))


# Fourth false positive, measured 2026-08-01 on the NEXT wrap after the third.
# Same family again - the right evidence in a place the parser could not look.
# EV_CI's span is `[^|&\n]`, single-line and &-terminated by construction, so the
# class-3 fix only reaches the SEMICOLON form. Two shapes used repeatedly in one
# wrap still read as "no CI probe": the binary bound to a variable and used after
# an `&&`, and the same binding used from a multi-line `python -c` argv list.
# Fixed by binding the SAME NAME (EV_CI_VAR), never by widening EV_CI's span -
# widening it would credit any later `run` after any gh mention, which is the
# looseness that produced the first armed session's 9 false positives.

GH_AMP = ('cd "C:/Riot Commander" && GH="C:/Program Files/GitHub CLI/gh.exe" '
          '&& "$GH" run list --limit 3')
GH_SUBPROCESS = (
    'cd "C:/Riot Commander" && python -c "\n'
    "import json,subprocess\n"
    "GH=r'C:/Program Files/GitHub CLI/gh.exe'\n"
    "out=subprocess.run([GH,'run','list','--json','status,conclusion'])\n"
    '"'
)


def test_gh_bound_to_a_variable_across_an_ampersand_is_a_ci_probe(tmp_path):
    rows = [
        _assistant(_tool_use("Bash", command=GH_AMP)),
        _tool_result("completed success ci 30725437519"),
        _assistant(_text("CI green.")),
    ]
    assert "ci_claim_without_probe" not in _checks(_run_gate(tmp_path, rows))


def test_gh_used_from_a_multiline_subprocess_argv_is_a_ci_probe(tmp_path):
    rows = [
        _assistant(_tool_use("Bash", command=GH_SUBPROCESS)),
        _tool_result("full-suite completed success"),
        _assistant(_text("Working tree clean, all four commits pushed, CI green.")),
    ]
    assert "ci_claim_without_probe" not in _checks(_run_gate(tmp_path, rows))


def test_assigning_a_gh_path_without_ever_using_it_is_not_a_probe(tmp_path):
    """Load-bearing negative. The binding alone is setup, not evidence - a
    variable that is assigned and never invoked probed nothing."""
    rows = [
        _assistant(_tool_use("Bash", command='GH="C:/Program Files/GitHub CLI/gh.exe"\necho ready')),
        _tool_result("ready"),
        _assistant(_text("CI is green.")),
    ]
    assert "ci_claim_without_probe" in _checks(_run_gate(tmp_path, rows))


def test_a_heredoc_documenting_a_gh_invocation_is_not_a_probe(tmp_path):
    """Load-bearing negative, and the reason EV_CI_VAR strips heredocs even
    though it deliberately keeps quoted literals. Writing the recipe into a doc
    is documentation; running it is a probe. Without this the /done ritual doc
    itself would credit every session that merely quotes the command."""
    rows = [
        _assistant(_tool_use("Bash", command=(
            "cat > docs/note.md <<'EOF'\n"
            'Check CI with GH="C:/Program Files/GitHub CLI/gh.exe" then "$GH" run list\n'
            "EOF"))),
        _tool_result(""),
        _assistant(_text("CI is green.")),
    ]
    assert "ci_claim_without_probe" in _checks(_run_gate(tmp_path, rows))


def test_a_different_variable_cannot_borrow_the_gh_binding(tmp_path):
    """Load-bearing negative. The name is captured and back-referenced on
    purpose: some OTHER variable in front of `run` is not a gh invocation."""
    rows = [
        _assistant(_tool_use("Bash", command=(
            'GH="C:/x/gh.exe"\nsubprocess.run([PYTHON, "run", "the_thing"])'))),
        _tool_result("done"),
        _assistant(_text("CI is green.")),
    ]
    assert "ci_claim_without_probe" in _checks(_run_gate(tmp_path, rows))


# FIFTH false positive, measured 2026-08-04 during /done - and this one is the
# ROOT of the whole family rather than another shape of it. The three fixes
# above all widened where EV_CI could LOOK; none noticed that
# strip_command_noise DELETES quoted literals, and Windows forces the gh path to
# be quoted because of the space in "Program Files". So the single most obvious
# invocation - the absolute quoted path the /done ritual itself prescribes -
# reduced to " run view <id>" with no `gh` token left for any pattern to match.
# A session that ran it SEVEN times was still flagged ci_claim_without_probe.
#
# Fixed in strip_command_noise, not in EV_CI: a quoted token that is an
# EXECUTABLE PATH collapses to its basename instead of vanishing. The
# prose-stripping the deletion exists for is unchanged, which the negative
# cases below are what pin.

GH_QUOTED_ABS = ('cd "C:/Riot Commander" && "C:/Program Files/GitHub CLI/gh.exe" '
                 "run view 30957597488 --json status,conclusion")


def test_gh_quoted_absolute_path_counts_as_a_ci_probe(tmp_path):
    rows = [
        _assistant(_tool_use("Bash", command=GH_QUOTED_ABS)),
        _tool_result("completed success"),
        _assistant(_text("CI collected - green.")),
    ]
    assert "ci_claim_without_probe" not in _checks(_run_gate(tmp_path, rows))


def test_a_gh_invocation_quoted_in_PROSE_is_still_not_evidence(tmp_path):
    """The load-bearing negative. Only an .exe PATH is spared; a quoted
    SENTENCE that happens to name gh is documentation, and crediting it would
    trade this false negative for the false positive the stripping was added to
    stop."""
    rows = [
        _assistant(_tool_use("Bash", command='echo "gh run list is how you check CI"')),
        _tool_result("gh run list is how you check CI"),
        _assistant(_text("CI is green.")),
    ]
    assert "ci_claim_without_probe" in _checks(_run_gate(tmp_path, rows))


def test_quoted_python_path_still_reads_as_a_pytest_run(tmp_path):
    """Same deletion hurt the pytest evidence path for the same reason - the
    interpreter is always invoked by quoted absolute path on this machine."""
    cmd = ('"C:/Users/Administrator/AppData/Local/Programs/Python/Python314/'
           'python.exe" -m pytest tests/test_x.py -q')
    rows = [
        _assistant(_tool_use("Bash", command=cmd)),
        _tool_result("==== 12 passed in 1.00s ===="),
        _assistant(_text("The suite is green.")),
    ]
    assert "suite_claim_without_run" not in _checks(_run_gate(tmp_path, rows))


# ------------------------------------------------- node runner (rc-shell)
# MEASURED FALSE POSITIVE 2026-08-11: the gate flagged an accurate
# "rc-shell 328 passed / 0 failed" as count_mismatch because it only ever
# parsed pytest's "N passed". The whole second test suite in this repo was
# invisible to it, which also means it could never have caught a FALSE
# rc-shell claim. These three cases pin the fix in both directions.

def test_node_test_run_backs_an_accurate_count_claim(tmp_path):
    # The claim is worded with 'suite' deliberately: if the node run were
    # NOT recognised, tests_pass_without_run would fire. Asserting only the
    # absence of count_mismatch would pass vacuously, because that check is
    # skipped entirely when no run was observed.
    rows = [
        _assistant(_tool_use("Bash", command="cd rc-shell && npm test")),
        _tool_result(NODE_GREEN),
        _assistant(_text("The rc-shell suite is green: 328 passed.")),
    ]
    report = _run_gate(tmp_path, rows)
    assert "tests_pass_without_run" not in _checks(report), (
        "npm test must count as a test run: " + str(report["findings"]))
    assert "count_mismatch" not in _checks(report), (
        "an accurate count over a real node run must not flag: "
        + str(report["findings"]))


def test_node_test_run_still_catches_a_wrong_count(tmp_path):
    # The widening must not become a blanket pass - a node run backs the
    # numbers it actually printed and no others.
    rows = [
        _assistant(_tool_use("Bash", command="npm test")),
        _tool_result(NODE_GREEN),
        _assistant(_text("The rc-shell suite is green: 400 passed.")),
    ]
    report = _run_gate(tmp_path, rows)
    assert "count_mismatch" in _checks(report)
    finding = next(f for f in report["findings"]
                   if f["check"] == "count_mismatch")
    assert "400" in finding["claimed"]
    assert "328" in finding["observed"]


def test_node_summary_without_a_run_command_is_not_evidence(tmp_path):
    # Same rule as pytest: a floating summary is not an observation of a run.
    rows = [
        _assistant(_text("For reference the runner prints:" + _NL + NODE_GREEN)),
        _assistant(_text("The rc-shell suite is green: 328 passed.")),
    ]
    report = _run_gate(tmp_path, rows)
    assert "tests_pass_without_run" in _checks(report)


def test_node_direct_invocation_counts_as_a_run(tmp_path):
    rows = [
        _assistant(_tool_use("Bash",
                             command="node --test test/config.test.js")),
        _tool_result(NODE_GREEN),
        _assistant(_text("The suite is green: 328 passed.")),
    ]
    report = _run_gate(tmp_path, rows)
    assert "tests_pass_without_run" not in _checks(report)
    assert "count_mismatch" not in _checks(report)


# ------------------------------------------------- CI-log evidence (2026-09-06)
#
# The gate indexes LOCAL pytest invocations, so a suite count read out of a CI
# log was never in `observed_counts` and every accurate report of one scored as
# count_mismatch. Measured this session: a true "31706 passed" taken from
# `gh run view <id> --log` was flagged twice while the session's local runs
# topped out at 1869.
#
# That cries wolf on correctly-sourced figures, and a gate that cries wolf gets
# waved through - which is exactly when it stops catching the real thing. It
# caught a real one the same session: a "25 passed" that had been computed as
# 28 minus 3 rather than observed.
#
# The widening is deliberately NARROW. A CI log echoes the workflow file, whose
# comments carry STALE historical counts, so only a genuine terminal-summary
# shape is credited - never a bare "N passed" floating in the log.

CI_LOG_OUTPUT = (
    "check\tfull dual suite\t2026-09-07T02:19:07Z \x1b[36;1m"
    "# 19m42s / 23607 passed / 258 skipped / 6032 subtests / 0 failed\x1b[0m\n"
    "check\tfull dual suite\t2026-09-07T03:17:39Z "
    "31706 passed, 262 skipped, 5 warnings, 18565 subtests passed in 3508.32s (0:58:28)\n"
)


def test_ci_log_summary_counts_as_observed_evidence(tmp_path):
    """A count read from a fetched CI log is evidence, not an unbacked claim.

    The local pytest run is REQUIRED for this test to mean anything. With no
    runs at all the count check never arms, so an assertion that nothing was
    flagged passes vacuously - which is how the first draft of this test went
    green while proving nothing.
    """
    rows = [
        _assistant(_tool_use("Bash", command="python -m pytest -q")),
        _tool_result(PYTEST_GREEN),
        _assistant(_tool_use("Bash", command="gh run view 34075783861 --log")),
        _tool_result(CI_LOG_OUTPUT),
        _assistant(_text("CI green: 31706 passed.")),
    ]
    assert "count_mismatch" not in _checks(_run_gate(tmp_path, rows))


def test_a_stale_count_in_a_workflow_comment_is_not_evidence(tmp_path):
    """The narrowing that keeps this a widening of EVIDENCE, not of belief.

    23607 appears in the same fetched log, inside an echoed workflow comment
    recording a historical run. It has no terminal-summary shape, so claiming it
    must still fail - otherwise a CI fetch would launder every number printed
    anywhere in a workflow file.
    """
    rows = [
        _assistant(_tool_use("Bash", command="python -m pytest -q")),
        _tool_result(PYTEST_GREEN),
        _assistant(_tool_use("Bash", command="gh run view 34075783861 --log")),
        _tool_result(CI_LOG_OUTPUT),
        _assistant(_text("CI green: 23607 passed.")),
    ]
    assert "count_mismatch" in _checks(_run_gate(tmp_path, rows))


def test_a_ci_count_with_no_ci_fetch_is_still_unbacked(tmp_path):
    """Claiming a CI figure the session never fetched stays a mismatch."""
    rows = [
        _assistant(_tool_use("Bash", command="python -m pytest -q")),
        _tool_result(PYTEST_GREEN),
        _assistant(_text("CI green: 31706 passed.")),
    ]
    assert "count_mismatch" in _checks(_run_gate(tmp_path, rows))


# -------------------------------- the gh.exe basename form (measured 2026-09-10)
#
# EV_CI_LOG required a literal `gh` token; EV_CI, twenty lines below it, already
# wrote the same binary as `gh(?:\.exe)?`. RC's prescribed invocation is a quoted
# absolute path, which strip_command_noise collapses to the basename `gh.exe`, so
# the `.` broke `\bgh\s+run` and the fetch was never indexed. Found by corpus
# measurement over 91 transcripts - 4 of the 28 count_mismatch findings were this
# miss, across three different shapes: `> file`, a PowerShell `&` call operator,
# and a `| grep` pipe.

GH_LOG_REDIRECT = ('"C:/Program Files/GitHub CLI/gh.exe" run view 31874678071 '
                   "--log-failed > ci.txt")
GH_LOG_CALLOP = ('& "C:/Program Files/GitHub CLI/gh.exe" run view 30770489475 '
                 "--log --job=98765432")
GH_LOG_PIPE = ('"C:/Program Files/GitHub CLI/gh.exe" run view 34538335778 '
               "--log-failed | grep -i fail")


@pytest.mark.parametrize("command", [GH_LOG_REDIRECT, GH_LOG_CALLOP, GH_LOG_PIPE])
def test_ci_log_fetched_by_absolute_path_counts_as_evidence(tmp_path, command):
    """All three corpus shapes. The local run is required or this is vacuous."""
    rows = [
        _assistant(_tool_use("Bash", command="python -m pytest -q")),
        _tool_result(PYTEST_GREEN),
        _assistant(_tool_use("Bash", command=command)),
        _tool_result(CI_LOG_OUTPUT),
        _assistant(_text("CI green: 31706 passed.")),
    ]
    assert "count_mismatch" not in _checks(_run_gate(tmp_path, rows))


@pytest.mark.parametrize("command", [GH_LOG_REDIRECT, GH_LOG_CALLOP, GH_LOG_PIPE])
def test_basename_fetch_still_honours_the_summary_line_restriction(tmp_path, command):
    """Widening the COMMAND must not widen the LINE filter.

    23607 sits in the same fetched log inside an echoed workflow comment with no
    terminal-summary shape, so it must still fail however the log was fetched.
    """
    rows = [
        _assistant(_tool_use("Bash", command="python -m pytest -q")),
        _tool_result(PYTEST_GREEN),
        _assistant(_tool_use("Bash", command=command)),
        _tool_result(CI_LOG_OUTPUT),
        _assistant(_text("CI green: 23607 passed.")),
    ]
    assert "count_mismatch" in _checks(_run_gate(tmp_path, rows))


# ---------------------------- the WINDOWS BACKSLASH path form (RM-400, 2026-09-10)
#
# The block above fixed the pattern that CONSUMES the basename. This one fixes the
# pattern that PRODUCES it. `_QUOTED_EXE` ended its optional directory group on
# `[\/]`, which inside a character class is a forward slash and nothing else, so
# only a POSIX-spelled path ever collapsed to `gh.exe`. A native Windows spelling
# - `"C:\Program Files\GitHub CLI\gh.exe"` - matched no exe branch at all, fell
# through to `_QUOTED`, and was DELETED whole, leaving ` run view <id> --log` with
# no binary token for EV_CI_LOG or EV_CI to see. Same end state as the 2026-08-04
# defect that created `_QUOTED_EXE` in the first place, reached by a different
# spelling of the very same command.
#
# Three forms are pinned because each fails differently: pure backslash (the
# native spelling), MIXED separators (a path pasted from one shell into another),
# and a bare `"gh.exe"` with no directory at all, which already worked and must
# keep working - the fix must not make the directory group mandatory.
GH_LOG_BACKSLASH = ('"C:\\Program Files\\GitHub CLI\\gh.exe" run view 31874678071 '
                    "--log-failed > ci.txt")
GH_LOG_MIXED = ('"C:\\Program Files/GitHub CLI\\gh.exe" run view 30770489475 '
                "--log --job=98765432")
GH_LOG_BARE = '"gh.exe" run view 34538335778 --log-failed | grep -i fail'
_BACKSLASH_FORMS = [GH_LOG_BACKSLASH, GH_LOG_MIXED, GH_LOG_BARE]


@pytest.mark.parametrize("command", _BACKSLASH_FORMS)
def test_ci_log_fetched_by_a_backslash_path_counts_as_evidence(tmp_path, command):
    """End to end. The local run is required or the count check never arms."""
    rows = [
        _assistant(_tool_use("Bash", command="python -m pytest -q")),
        _tool_result(PYTEST_GREEN),
        _assistant(_tool_use("Bash", command=command)),
        _tool_result(CI_LOG_OUTPUT),
        _assistant(_text("CI green: 31706 passed.")),
    ]
    assert "count_mismatch" not in _checks(_run_gate(tmp_path, rows))


@pytest.mark.parametrize("command", _BACKSLASH_FORMS)
def test_backslash_fetch_still_honours_the_summary_line_restriction(tmp_path, command):
    """THE FENCE. This widening moves BELIEF, so the line filter is pinned here.

    Recognising one more command spelling is the whole change; what may be
    credited from the fetched output is untouched. 23607 sits in the same log
    inside an echoed workflow comment with no terminal-summary shape, and it must
    stay uncreditable however the log was fetched. Without this test a fix that
    also relaxed EV_SUMMARY_LINE would pass the test above.
    """
    rows = [
        _assistant(_tool_use("Bash", command="python -m pytest -q")),
        _tool_result(PYTEST_GREEN),
        _assistant(_tool_use("Bash", command=command)),
        _tool_result(CI_LOG_OUTPUT),
        _assistant(_text("CI green: 23607 passed.")),
    ]
    assert "count_mismatch" in _checks(_run_gate(tmp_path, rows))


def test_the_exe_rewrite_is_a_basename_and_nothing_else():
    """Unit level, because the end-to-end tests cannot see WHAT was left behind.

    Both halves matter. The binary must survive as a bare basename, and the
    directory it came from must not - leaking `C:\\Program Files` back into the
    command would hand the evidence patterns tokens the operator never invoked.
    """
    for command in _BACKSLASH_FORMS:
        stripped = gate.strip_command_noise(command)
        assert " gh.exe " in stripped, stripped
        assert "Program Files" not in stripped, stripped
        assert "GitHub CLI" not in stripped, stripped


def test_a_quoted_backslash_literal_that_is_not_an_exe_is_still_deleted():
    """Scope pin. The rewrite is for EXECUTABLES; other quoted data is DATA.

    A quoted Windows path to a LOG is an argument, not a command, and must keep
    vanishing with the rest of the quoted literals. If the backslash alternative
    were added somewhere broader than the exe branch, this would leak.
    """
    assert (gate.strip_command_noise(r'type "C:\Riot Commander\logs\no tests ran.txt"')
            == "type  ")
# SIXTH shape, and the first that makes the gate blind rather than noisy. Every
# fix above narrowed what the gate would FLAG; this one is the opposite failure
# - a claim the gate never got to examine at all.
#
# strip_prose_noise deleted every span between two single quotes. In PROSE a
# single quote is far more often an apostrophe than a delimiter, so two ordinary
# possessives or contractions in one paragraph paired as if they opened and
# closed a quotation, and the whole span between them was deleted before the
# claim scan ever ran. Measured: "The runner's log says 9999 passed, and the
# session's report agrees." stripped to "The runner s report agrees." and the
# count claim vanished; the same sentence with no apostrophes was flagged.
#
# The fix is a SEPARATE prose-only pattern. strip_command_noise keeps the
# original, because shell quoting has no possessives and narrowing there would
# change evidence detection for commands - a different blast radius entirely.
# The direction of this fix WIDENS what the gate examines, which is exactly the
# direction that produced the nine false positives of LEDGER 1154, so the
# suppression half below is as load-bearing as the exposure half.

PROBE_POSSESSIVE = ("The runner's log says 9999 passed, and the session's "
                    "report agrees.")


def test_a_pair_of_possessives_no_longer_swallows_a_count_claim(tmp_path):
    """The measured defect, end to end: two apostrophes hid a false count."""
    rows = [
        _assistant(_tool_use("Bash", command="python -m pytest -q")),
        _tool_result(PYTEST_GREEN),
        _assistant(_text(PROBE_POSSESSIVE)),
    ]
    assert "count_mismatch" in _checks(_run_gate(tmp_path, rows))


def test_strip_prose_noise_keeps_a_possessive_sentence_intact():
    """Unit-level pin on the same sentence - nothing is deleted at all."""
    assert gate.strip_prose_noise(PROBE_POSSESSIVE) == PROBE_POSSESSIVE


def test_a_genuine_single_quoted_claim_is_still_suppressed(tmp_path):
    """The anti-regression half. A real quotation must still be quotation."""
    rows = [
        _assistant(_tool_use("Bash", command="python -m pytest -q")),
        _tool_result(PYTEST_GREEN),
        _assistant(_text("An example of a bad claim is 'the run reported 9999 "
                         "passed' and that is all it is.")),
    ]
    assert _run_gate(tmp_path, rows)["findings"] == []


def test_a_quoted_span_containing_a_contraction_is_suppressed_end_to_end(tmp_path):
    """An apostrophe INSIDE a quotation must not terminate it early.

    Truncating there would re-expose the tail of the quotation as prose, which
    is the same false-positive class the stripping exists to prevent.
    """
    rows = [
        _assistant(_tool_use("Bash", command="python -m pytest -q")),
        _tool_result(PYTEST_GREEN),
        _assistant(_text("An example of a bad claim is 'the runner doesn't "
                         "say 9999 passed' and that is all it is.")),
    ]
    assert _run_gate(tmp_path, rows)["findings"] == []


def test_a_quoted_span_at_the_start_of_the_text_is_suppressed(tmp_path):
    rows = [
        _assistant(_tool_use("Bash", command="python -m pytest -q")),
        _tool_result(PYTEST_GREEN),
        _assistant(_text("'the run reported 9999 passed' was only an example.")),
    ]
    assert _run_gate(tmp_path, rows)["findings"] == []


def test_a_quoted_span_at_the_end_of_the_text_is_suppressed(tmp_path):
    rows = [
        _assistant(_tool_use("Bash", command="python -m pytest -q")),
        _tool_result(PYTEST_GREEN),
        _assistant(_text("The example reads 'the run reported 9999 passed'")),
    ]
    assert _run_gate(tmp_path, rows)["findings"] == []


def test_the_double_quote_branch_is_unaffected(tmp_path):
    """The defect is single-quote only; the double-quote branch is untouched."""
    rows = [
        _assistant(_tool_use("Bash", command="python -m pytest -q")),
        _tool_result(PYTEST_GREEN),
        _assistant(_text('The fixture says "the run reported 9999 passed" and '
                         'that is all it is.')),
    ]
    assert _run_gate(tmp_path, rows)["findings"] == []


PROBE_MIXED_QUOTES = ('The agent\'s note "quote with the runner\'s word" then '
                      '9999 passed and "a second quote" end.')


def test_an_apostrophe_span_no_longer_eats_a_double_quote_delimiter(tmp_path):
    """The INTERACTION between the two branches, which neither test above pins.

    test_the_double_quote_branch_is_unaffected carries no apostrophe at all, so
    it exercises the double-quote branch in ISOLATION and stays green under the
    old pattern. The real corpus hit needed both branches at once: under the old
    `_QUOTED` the apostrophe of "agent's" paired with the one in "runner's", and
    that span swallowed the OPENING double quote of the first quotation. The
    orphaned closing quote then paired with a LATER quote, so the deletion ran
    past the count and hid it - measured at 988 chars in the corpus, and here as

        OLD: The agent s word a second quote" end.
        NEW: The agent's note   then 9999 passed and   end.

    Both halves are asserted, because either alone is satisfiable by a wrong
    pattern: a branch that simply stopped deleting single-quoted spans would
    expose the count AND leak both quotations back into the claim scan, which is
    the false-positive class of LEDGER 1154. The exposure half is end to end on
    a real count_mismatch finding; the suppression half is asserted at the strip
    level, because two suppressed quotations produce NO finding to assert on and
    an empty findings list cannot distinguish "both stripped" from "the sentence
    never reached the scanner at all".
    """
    rows = [
        _assistant(_tool_use("Bash", command="python -m pytest -q")),
        _tool_result(PYTEST_GREEN),
        _assistant(_text(PROBE_MIXED_QUOTES)),
    ]
    findings = _run_gate(tmp_path, rows)["findings"]
    assert any(f["check"] == "count_mismatch" and f["claimed"] == "9999"
               for f in findings), findings
    stripped = gate.strip_prose_noise(PROBE_MIXED_QUOTES)
    assert "quote with the runner" not in stripped
    assert "a second quote" not in stripped
    assert '"' not in stripped
    assert "9999 passed" in stripped


def test_strip_command_noise_still_deletes_every_single_quoted_literal():
    """strip_command_noise is DELIBERATELY unchanged - pinned, not assumed.

    Shell quoting carries no possessives, so the prose narrowing has no reason
    to reach here, and applying it would change which commands count as
    evidence. Both halves are pinned: a real shell literal still vanishes, and
    the naive apostrophe pairing that the prose path now rejects still happens
    here.
    """
    assert (gate.strip_command_noise("echo 'no tests ran' && git status")
            == "echo   && git status")
    assert (gate.strip_command_noise("a runner's log and a session's report")
            == "a runner s report")


# ------------------------------------------------------- RM-217, REFUTED
# The gate has no retraction path and is not getting one. RM-396 rejected a
# retraction token by name (LEDGER 1379, "a self-serve silencer"), RM-398
# recorded the decision to "keep the strict behaviour and ACCEPT that
# retractions flag", and RM-217's ACCEPTANCE - which prescribed exactly the
# refused marker - was re-measured and closed on 2026-09-12.
#
# These two tests are the fence, kept as code because the row above them was a
# standing invitation to rebuild the thing for 28 days.


def test_a_retraction_naming_the_figure_does_not_clear_the_count_claim(tmp_path):
    """A retraction is a self-serve silencer, and the attack is one sentence.

    MEASURED 2026-09-12 over a FROZEN 123-transcript corpus. A fabricated
    `28150 passed` plus the appended sentence "I retract the 28150 figure"
    goes SILENT under both candidate shapes - the loose one (a retraction verb
    anywhere in a sentence naming the number) and the tightened one (the verb
    within 40 chars of the number, strictly later than the claim, and the
    number never re-asserted afterwards). The honest case and the fabrication
    are the same sentence, so nothing separates them.

    Two phrasings are asserted, because the SECOND is a trap a retraction path
    would have to handle and the first is not. A retraction that names the bare
    figure ("the 28150 figure") adds no finding of its own - `CLAIM_COUNT`
    wants `N passed`. A retraction that QUOTES what it withdraws, which is the
    natural way to withdraw a number and is the form the corpus actually
    contains, re-spells `N passed` and so becomes a fresh claim in the same
    breath. Measured 2026-09-12: session 17e9bb48's honest "Retracting: I have
    not observed 16 passed, 18226 passed" is ITSELF one of the corpus findings.
    So a retraction path would have to exempt its own retraction sentence,
    widening the surface a second time. A first draft of this test asserted the
    self-flag for both phrasings and was RED against the real gate - the
    property is real but narrower than written, and the test is what caught it.

    The standing remedy is unchanged and it is PROSPECTIVE: backtick the
    figure, which `strip_prose_noise` deletes before any check runs. That is
    not the same cost as a retraction. A backtick must be spent at the moment
    of writing and it withdraws the assertion's force; a retraction is spent
    AFTER the gate has fired, which is exactly when a fabricator needs it and
    long after the number has been read.
    """
    fabricated = _assistant(
        _text("I ran the full suite. The tree is green: 28150 passed."))
    run = [_assistant(_tool_use("Bash", command="python -m pytest tests")),
           _tool_result(PYTEST_GREEN)]
    for name in ("bare", "quoting"):
        (tmp_path / name).mkdir()

    bare = _run_gate(tmp_path / "bare", [
        fabricated, *run,
        _assistant(_text("Correction. I retract the 28150 figure - "
                         "it was not observed here.")),
    ])["findings"]
    bare_mismatches = [f for f in bare if f["check"] == "count_mismatch"]
    assert [f["claimed"] for f in bare_mismatches] == ["28150"], bare_mismatches
    assert "green: 28150 passed" in bare_mismatches[0]["quote"]

    quoting = _run_gate(tmp_path / "quoting", [
        fabricated, *run,
        _assistant(_text("Retracting: I have not observed 28150 passed.")),
    ])["findings"]
    quoting_mismatches = [f for f in quoting if f["check"] == "count_mismatch"]
    assert [f["claimed"] for f in quoting_mismatches] == ["28150", "28150"], \
        quoting_mismatches
    assert any("Retracting" in f["quote"] for f in quoting_mismatches), \
        "a retraction that quotes the figure is itself a claim"


def test_the_armed_block_message_names_a_remedy_that_actually_works(tmp_path):
    """The instrument must not prescribe a remedy it does not implement.

    The armed emit told the model to "Fix or retract, then finish". There is no
    retraction path in `audit` and there never was, so half that instruction is
    false - and it is not inert advice, because it told sessions to keep doing
    the thing that cannot work. The gate re-scans the WHOLE transcript every
    Stop and an earlier turn cannot be edited, so the same sentence re-flags
    forever. Measured 2026-09-12 over `ops/runtime/stop_claim_history.jsonl`
    (500 rows, its rolling cap): one session carries 49 Stops with findings, 48
    of them count_mismatch, and five more carry 14 or more.

    Asserted on the real stderr the model is shown, not on the source string.
    """
    proc, _report = _run_armed(
        tmp_path, [_assistant(_text("The full suite passes."))])
    assert proc.returncode == 2
    assert "retract" not in proc.stderr.lower(), (
        "retraction does not clear a finding - RM-217 REFUTED 2026-09-12; "
        f"stderr was: {proc.stderr}")
    assert "backtick" in proc.stderr.lower(), (
        "the emit must name the remedy that does work - a backticked figure is "
        f"deleted by strip_prose_noise before any check; stderr was: {proc.stderr}")
