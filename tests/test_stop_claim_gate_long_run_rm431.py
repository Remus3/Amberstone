"""RM-431: a TRUE count from a run longer than the foreground tool timeout must
be backable, or a headless loop deadlocks on correct claims.

`pytest tests` takes ~85 minutes, so it can only ever run backgrounded; the
600 s foreground cap means the run and its summary can never share one tool
call. MEASURED 2026-09-16: the gate credited the first full-suite figure and
refused the CONFIRMING run's figure, permanently, because the confirming run
was launched while the first was still open and the single deferred slot was
consumed by the first summary read.

Resolution adopted: candidate (a) of the row - credit a count that appears in a
background run's output when the session reads it, with the artifact still the
evidence. Implemented by the RM-498 per-launch deferred list. Candidate (c),
"backtick every suite figure by convention", is NOT adopted: it would quietly
retire the gate.
"""

from tests.test_stop_claim_gate import (
    _assistant,
    _run_gate,
    _text,
    _tool_result,
    _tool_use,
)

RUN1 = "22520 passed, 104 skipped in 5101.30s (1:25:01)"
RUN2 = "22525 passed, 104 skipped in 5098.77s (1:24:58)"


def _bg(task):
    return _tool_result(f"Command running in background with ID: {task}. Output is "
                        f"being written to: C:\\tmp\\tasks\\{task}.output")


def _session(claim):
    return [
        _assistant(_tool_use("Bash", command="python -m pytest tests/test_a.py -q")),
        _tool_result("==== 403 passed in 9.10s ===="),
        _assistant(_tool_use("PowerShell", command="python -m pytest tests -q")),
        _bg("long0001"),
        # The confirming run is launched while the first is still running.
        _assistant(_tool_use("PowerShell", command="python -m pytest tests -q")),
        _bg("long0002"),
        # Foreground work in between keeps crediting its own counts.
        _assistant(_tool_use("Bash", command="python -m pytest tests/test_b.py -q")),
        _tool_result("==== 162 passed in 4.00s ===="),
        _assistant(_tool_use("Read", file_path="C:/tmp/tasks/long0001.output")),
        _tool_result(RUN1),
        _assistant(_tool_use("Read", file_path="C:/tmp/tasks/long0002.output")),
        _tool_result(RUN2),
        _assistant(_text(claim)),
    ]


def test_confirming_long_run_count_is_credited(tmp_path):
    report = _run_gate(tmp_path, _session(
        "The first full suite gave 22520 passed; the confirming suite gave 22525 passed."))
    assert report["findings"] == [], report["findings"]


def test_long_run_does_not_launder_an_unobserved_count(tmp_path):
    report = _run_gate(tmp_path, _session("The confirming suite gave 22530 passed."))
    assert {f["claimed"] for f in report["findings"]
            if f["check"] == "count_mismatch"} == {"22530"}
