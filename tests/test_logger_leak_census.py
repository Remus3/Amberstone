"""Guard: `tools/logger_leak_census.py` can actually DETECT a leaked logger.

WHY THIS FILE EXISTS. The census (NOW-7 step 1) reports which tests leave logger
state mutated. Its whole value is a count, and **a count from an instrument
nobody has watched produce a positive is worthless** - a census that is blind
reports a clean suite and reads exactly like a clean suite. The first version of
that file WAS blind to 4 of the 5 leaks below: a test that CREATES its logger and
then leaks it landed in a bucket called `CREATED` which the file treated as
informational, so the precise defect class NOW-6 was about was being filed as "a
new logger appeared". The bucket was split into `CREATED_PRISTINE` and
`CREATED_DIRTY` as a result.

That is the trap in `feedback_your_failure_bucket_vs_the_subjects`, committed by
the instrument built to find it, and it was caught only because these controls
were written BEFORE the clean result was trusted. So they are a tracked guard
rather than a transcript anecdote.

ANTI-VACUITY. Both halves are asserted. Positive controls MUST be reported; the
negative controls MUST NOT be. A census that flagged everything would pass a
positives-only test while being just as useless as one that flagged nothing.

The census is run in a SUBPROCESS on purpose: it measures process-global logging
state, so running the controls in this process would let this file's own imports
and fixtures contaminate the thing under test.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "tools" / "logger_leak_census.py"

_CONTROLS = '''
import logging


def test_pos_propagate():
    logging.getLogger("census.ctl.propagate").propagate = False


def test_pos_level():
    logging.getLogger("census.ctl.level").setLevel(logging.CRITICAL)


def test_pos_handler():
    logging.getLogger("census.ctl.handler").addHandler(logging.NullHandler())


def test_pos_mutates_preexisting():
    # Created by the import above in a PRIOR test, so this one mutates a logger
    # that already existed - the other half of the detector.
    logging.getLogger("census.ctl.propagate").setLevel(logging.ERROR)


def test_pos_swaps_handler_keeping_count():
    lg = logging.getLogger("census.ctl.handler")
    old = lg.handlers[0]
    lg.removeHandler(old)
    lg.addHandler(logging.NullHandler())


def test_neg_restores_everything():
    lg = logging.getLogger("census.ctl.clean")
    prior = (lg.propagate, lg.level, list(lg.handlers))
    h = logging.NullHandler()
    lg.addHandler(h)
    lg.propagate = False
    lg.setLevel(logging.DEBUG)
    lg.removeHandler(h)
    lg.propagate = prior[0]
    lg.setLevel(prior[1])
    assert list(lg.handlers) == prior[2]


def test_neg_touches_nothing():
    assert 1 + 1 == 2
'''

_POSITIVES = {
    "test_pos_propagate",
    "test_pos_level",
    "test_pos_handler",
    "test_pos_mutates_preexisting",
    "test_pos_swaps_handler_keeping_count",
}
_NEGATIVES = {"test_neg_restores_everything", "test_neg_touches_nothing"}


@pytest.fixture(scope="module")
def census(tmp_path_factory):
    """Run the census over the controls in a subprocess, return its JSON report."""
    assert PLUGIN.is_file(), f"the census plugin is missing at {PLUGIN}"
    work = tmp_path_factory.mktemp("census")
    ctl = work / "test_census_controls.py"
    ctl.write_text(_CONTROLS, encoding="utf-8")
    report_dir = work / "report"
    report_dir.mkdir()
    env = {
        **_clean_env(),
        "PYTHONPATH": str(ROOT / "tools"),
        "RC_LOGGER_CENSUS_REPORT_DIR": str(report_dir),
    }
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(ctl), "-p", "logger_leak_census",
         "-q", "-p", "no:cacheprovider"],
        cwd=str(work), env=env, capture_output=True, text=True,
    )
    payload = report_dir / "logger_leak_census.json"
    assert payload.is_file(), (
        "the census wrote no report. stdout tail:\n" + proc.stdout[-2000:]
        + "\nstderr tail:\n" + proc.stderr[-1000:])
    return json.loads(payload.read_text(encoding="utf-8")), proc


def _clean_env():
    import os
    # Keep the parent's environment but drop anything that would make the inner
    # run load this repo's conftest chain from a different rootdir.
    env = dict(os.environ)
    env.pop("PYTEST_ADDOPTS", None)
    env.pop("PYTEST_CURRENT_TEST", None)
    return env


def _flagged(report):
    return {row["nodeid"].rsplit("::", 1)[-1] for row in report["mutated"]}


def test_the_controls_all_ran(census):
    report, proc = census
    assert report["tests_observed"] == len(_POSITIVES) + len(_NEGATIVES), (
        f"the census observed {report['tests_observed']} tests, expected "
        f"{len(_POSITIVES) + len(_NEGATIVES)}. If it observed zero, every other "
        "assertion here would pass vacuously.\n" + proc.stdout[-1500:])
    assert report["loggers_observed_max"] > 0, (
        "the census never observed a single logger, so a zero leak count means "
        "nothing at all")


def test_the_census_reports_its_own_blind_spots_separately(census):
    report, proc = census
    assert report["UNOBSERVED_tests"] == 0, (
        "the census failed to read logger state for some test. That is a defect "
        "in the INSTRUMENT, and the leak count is incomplete by that many tests."
        "\n" + proc.stdout[-1500:])


@pytest.mark.parametrize("name", sorted(_POSITIVES))
def test_every_positive_control_is_detected(census, name):
    report, proc = census
    flagged = _flagged(report)
    assert name in flagged, (
        f"the census did NOT flag {name}, so it is blind to that leak shape and a "
        "clean report over the real suite would prove nothing. Flagged: "
        f"{sorted(flagged)}\n" + proc.stdout[-1500:])


@pytest.mark.parametrize("name", sorted(_NEGATIVES))
def test_no_negative_control_is_flagged(census, name):
    report, proc = census
    flagged = _flagged(report)
    assert name not in flagged, (
        f"the census flagged {name}, which restores everything it touches. An "
        "instrument that flags clean tests is as useless as one that flags "
        f"nothing. Flagged: {sorted(flagged)}\n" + proc.stdout[-1500:])


def test_a_created_and_leaked_logger_is_counted_as_a_leak_not_as_information(census):
    """The exact blind spot the first version of the census had."""
    report, _ = census
    assert report["CREATED_DIRTY_logger_names"] >= 3, (
        "CREATED_DIRTY should hold the loggers the positive controls created and "
        "left non-default. If this is 0, the CREATED bucket has been merged back "
        "together and the census is absorbing real leaks as information again - "
        f"report: {report['CREATED_DIRTY_logger_names']}")


def test_the_census_never_fails_the_run_it_observes(census):
    """REPORT-ONLY is the contract NOW-7 depends on before the gate is armed."""
    _, proc = census
    assert proc.returncode == 0, (
        "the inner run did not exit 0. The census must never fail a test or the "
        "session - it is a measurement pass, and arming it is a separate, "
        "operator-visible decision.\n" + proc.stdout[-2000:])
