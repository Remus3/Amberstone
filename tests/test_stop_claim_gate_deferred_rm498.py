"""RM-498: a backgrounded run's summaries must ALL be credited, not only the first.

`collect_evidence` held ONE `deferred` slot for the whole session and cleared
it on the first summary-bearing read. Measured consequences (BACKLOG RM-498):
one background job running BOTH suites credited only the first count; two
CONCURRENT background jobs credited only one; and a later launch's summary
could be swallowed by an earlier launch that the harness backgrounded. Every
one was a FALSE POSITIVE on a true number.

The terminal-summary shape requirement (`EV_SUMMARY_LINE`) is load-bearing and
stays: these tests also pin that a floating count is still not credited.
"""

from tests.test_stop_claim_gate import (
    BG_HANDOFF,
    BIG_SUMMARY,
    _assistant,
    _checks,
    _run_gate,
    _text,
    _tool_result,
    _tool_use,
)

DS_SUMMARY = "10933 passed, 12 skipped in 146.45s (0:02:26)"
RC_SUMMARY = "24711 passed, 104 skipped, 4 failed in 6418.22s (1:46:58)"
BG_HANDOFF_2 = ("Command running in background with ID: b2nd0000. Output is being "
                "written to: C:\\tmp\\tasks\\b2nd0000.output")
BG_HANDOFF_3 = ("Command running in background with ID: b3rd0000. Output is being "
                "written to: C:\\tmp\\tasks\\b3rd0000.output")


def _fg_small():
    """A foreground run so `observed_counts` is non-empty and check 2 is live."""
    return [
        _assistant(_tool_use("Bash", command="python -m pytest tests/test_x.py -q")),
        _tool_result("==== 30 passed in 2.68s ===="),
    ]


def _read(path, text):
    return [_assistant(_tool_use("Bash", command=f"tail -4 {path}")),
            _tool_result(text)]


def _claims(report):
    return {f["claimed"] for f in report["findings"] if f["check"] == "count_mismatch"}


def test_one_background_job_emitting_two_summaries_credits_both(tmp_path):
    rows = _fg_small() + [
        _assistant(_tool_use("Bash", command=(
            "python -m pytest agents/daemon_slayer -q; python -m pytest tests -q"))),
        _tool_result(BG_HANDOFF),
        *_read("C:/tmp/tasks/bsw0jw8f5.output", DS_SUMMARY),
        *_read("C:/tmp/tasks/bsw0jw8f5.output", RC_SUMMARY),
        _assistant(_text("DS 10933 passed; RC 24711 passed.")),
    ]
    report = _run_gate(tmp_path, rows)
    assert _claims(report) == set(), report["findings"]


def test_two_concurrent_background_jobs_each_credit_their_summary(tmp_path):
    rows = _fg_small() + [
        _assistant(_tool_use("Bash", command="python -m pytest agents/daemon_slayer -q")),
        _tool_result(BG_HANDOFF),
        _assistant(_tool_use("Bash", command="python -m pytest tests -q")),
        _tool_result(BG_HANDOFF_2),
        *_read("C:/tmp/tasks/bsw0jw8f5.output", DS_SUMMARY),
        *_read("C:/tmp/tasks/b2nd0000.output", RC_SUMMARY),
        _assistant(_text("DS 10933 passed; RC 24711 passed.")),
    ]
    report = _run_gate(tmp_path, rows)
    assert _claims(report) == set(), report["findings"]


def test_a_later_launch_is_credited_after_earlier_ones_were_read(tmp_path):
    """The THIRD measurement: a separate later launch was not credited."""
    rows = _fg_small() + [
        _assistant(_tool_use("Bash", command="python -m pytest agents/daemon_slayer -q")),
        _tool_result(BG_HANDOFF),
        _assistant(_tool_use("Bash", command="python -m pytest tests -q")),
        _tool_result(BG_HANDOFF_2),
        *_read("C:/tmp/tasks/bsw0jw8f5.output", DS_SUMMARY),
        *_read("C:/tmp/tasks/b2nd0000.output", RC_SUMMARY),
        _assistant(_tool_use("Bash", command="python -m pytest tests -q")),
        _tool_result(BG_HANDOFF_3),
        *_read("C:/tmp/tasks/b3rd0000.output", BIG_SUMMARY),
        _assistant(_text("Re-run: 17784 passed. Earlier 24711 passed and 10933 passed.")),
    ]
    report = _run_gate(tmp_path, rows)
    assert _claims(report) == set(), report["findings"]


def test_single_summary_positive_control(tmp_path):
    rows = _fg_small() + [
        _assistant(_tool_use("Bash", command="python -m pytest tests -q")),
        _tool_result(BG_HANDOFF),
        *_read("C:/tmp/tasks/bsw0jw8f5.output", BIG_SUMMARY),
        _assistant(_text("Full suite: 17784 passed.")),
    ]
    assert _run_gate(tmp_path, rows)["findings"] == []


def test_a_wrong_count_is_still_flagged_with_open_background_runs(tmp_path):
    rows = _fg_small() + [
        _assistant(_tool_use("Bash", command="python -m pytest tests -q")),
        _tool_result(BG_HANDOFF),
        *_read("C:/tmp/tasks/bsw0jw8f5.output", BIG_SUMMARY),
        _assistant(_text("Full suite: 99999 passed.")),
    ]
    assert _claims(_run_gate(tmp_path, rows)) == {"99999"}


def test_floating_count_in_a_read_is_still_not_credited(tmp_path):
    """Only the summary LINES of a read are attached, never the whole result:
    a floating `N passed` sitting next to a real summary is not evidence."""
    mixed = "an old note says 55555 passed earlier\n" + BIG_SUMMARY
    rows = _fg_small() + [
        _assistant(_tool_use("Bash", command="python -m pytest tests -q")),
        _tool_result(BG_HANDOFF),
        *_read("C:/tmp/tasks/bsw0jw8f5.output", mixed),
        _assistant(_text("Suite: 55555 passed.")),
    ]
    assert "count_mismatch" in _checks(_run_gate(tmp_path, rows))


def test_a_background_launch_credits_at_most_two_reads(tmp_path):
    """Bound on the widening: one launch opens room for the dual suite (two
    summaries), not for every summary-shaped line read for the rest of the
    session."""
    rows = _fg_small() + [
        _assistant(_tool_use("Bash", command="python -m pytest tests -q")),
        _tool_result(BG_HANDOFF),
        *_read("a.output", DS_SUMMARY),
        *_read("b.output", RC_SUMMARY),
        *_read("docs/LEDGER.md", "77777 passed, 1 skipped in 12.00s"),
        _assistant(_text("Suite: 77777 passed.")),
    ]
    assert _claims(_run_gate(tmp_path, rows)) == {"77777"}
