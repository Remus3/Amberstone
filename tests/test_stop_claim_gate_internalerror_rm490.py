"""RM-490: a pytest run that dies with INTERNALERROR is not evidence of a pass.

`EV_VACUOUS` matched only `no tests ran|collected 0 items`, so a run that
crashed with INTERNALERROR (RC's own recorded precedents: an xdist worker crash
that misreported a count, and an OOM `INTERNALERROR MemoryError` during a
parallel run) was not scored vacuous and the gate's verdict rested on whatever
else happened to be in the transcript.
"""

from tests.test_stop_claim_gate import (
    PYTEST_GREEN,
    _assistant,
    _checks,
    _run_gate,
    _text,
    _tool_result,
    _tool_use,
)

XDIST_CRASH = "\n".join([
    "INTERNALERROR> Traceback (most recent call last):",
    "INTERNALERROR>   File \"xdist/dsession.py\", line 190, in loop_once",
    "INTERNALERROR> RuntimeError: Unexpectedly no active workers available",
])

OOM_CRASH = "\n".join([
    "INTERNALERROR> Traceback (most recent call last):",
    "INTERNALERROR> MemoryError",
    "==== 22 failed in 301.10s ====",
])


def _session(output):
    return [
        _assistant(_tool_use("Bash", command="python -m pytest tests -q -n 8")),
        _tool_result(output),
        _assistant(_text("Tests pass.")),
    ]


def test_internalerror_run_scores_vacuous(tmp_path):
    assert "vacuous_run" in _checks(_run_gate(tmp_path, _session(XDIST_CRASH)))


def test_internalerror_with_a_misreported_summary_still_scores_vacuous(tmp_path):
    """The LEDGER precedent: the crash printed a count anyway. A count printed
    by a run that crashed is not a run's verdict."""
    assert "vacuous_run" in _checks(_run_gate(tmp_path, _session(OOM_CRASH)))


def test_genuine_pass_is_not_vacuous(tmp_path):
    """Positive control: a real green summary still scores as passed."""
    report = _run_gate(tmp_path, _session(PYTEST_GREEN))
    assert "vacuous_run" not in _checks(report)
    assert report["findings"] == [], report["findings"]


def test_prose_mention_of_internalerror_does_not_poison_a_real_run(tmp_path):
    """The word in a log line that is not a pytest INTERNALERROR prefix is not a
    crash - the pattern is anchored on pytest's own `INTERNALERROR>` marker."""
    out = "the LEDGER mentions an INTERNALERROR once\n" + PYTEST_GREEN
    assert "vacuous_run" not in _checks(_run_gate(tmp_path, _session(out)))
