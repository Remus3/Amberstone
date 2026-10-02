"""NOW-6 regression: a test that leaks a MODULE-logger mutation blinds caplog
in a DIFFERENT test file, and the failure lands on the victim rather than the
leaker.

The defect (measured 2026-10-01). `scripts/rewind_catchup.py:166`
`setup_file_logging()` sets `propagate = False` on `rc.scripts.rewind_catchup`,
raises its level to INFO and attaches a RotatingFileHandler. `main()` calls it
unconditionally, so any test invoking `rc.main()` mutates a logger that outlives
the test. `tests/test_rewind_timeline_429_retry.py::_DbCase` restored its three
`mock.patch` objects and nothing else, so the mutation was permanent for the
rest of the process. `caplog`'s handler sits on the ROOT logger, so with
propagation cut at the EMITTING logger `caplog.records` is empty even though the
subject warns unconditionally - and three tests in
`tests/test_rm413_wal_pragma_result_checked.py` failed, in a file that never
touches logging at all.

WHY THIS FILE EXISTS RATHER THAN JUST THE FIX. The symptom was indistinguishable
from a defect in the victim: it reproduced only in a full-suite run, passed in
isolation, and was CI-green because CI's ordering differed. A diagnosis bucket
named after the SUBJECT's property absorbed a defect that belonged to somebody
else entirely - so the guard below is deliberately pinned at the LEAKER, and
fails at the leaker's own site if the restoration is ever dropped.

ANTI-VACUITY. Both tests fail if the `_DbCase` restoration is reverted - the
first by asserting the observed pytest outcome of the exact minimal pair, the
second by exercising the fixture contract in-process. A "nothing was logged"
style pass is not available to either.
"""
from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# The minimal 2-element reproduction, measured 2026-10-01: this pair produced
# `3 failed, 119 passed` before the fix and `121 passed` plus the leaker's own
# tests after it. The subject file alone is `121 passed` either way, which is
# exactly why the leak was invisible for so long.
_LEAKER = (
    "tests/test_rewind_timeline_429_retry.py"
    "::CatchupRetryOnlyDryRunTests"
    "::test_retry_only_dry_run_leaves_db_bytes_unchanged"
)
_VICTIM = "tests/test_rm413_wal_pragma_result_checked.py"


def test_the_minimal_pair_that_reproduced_now6_is_green():
    """Run the leaker and the victim together, in that order, in a subprocess.

    A subprocess is the point: the defect is process-global logging state, so an
    in-process assertion could be satisfied by this file's own test ordering.
    """
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", _LEAKER, _VICTIM, "-q", "-p", "no:cacheprovider"],
        cwd=str(ROOT), capture_output=True, text=True,
    )
    tail = proc.stdout[-4000:] + proc.stderr[-2000:]
    assert proc.returncode == 0, (
        "the NOW-6 minimal pair is RED again. The leaker almost certainly stopped "
        "restoring the rc.scripts.rewind_catchup logger in _DbCase.tearDown. "
        "Do NOT 'fix' this by changing the victim file - the victim never touches "
        "logging.\n" + tail
    )
    # Anti-vacuity: a run that collected nothing would also exit 0.
    assert "failed" not in tail.split("=")[-1], tail
    assert " passed" in tail, "no tests were collected - this guard would pass vacuously\n" + tail


def test_dbcase_restores_the_module_logger_it_mutates():
    """Exercise the fixture contract directly, without running a victim.

    Catches the narrower regression where setUp/tearDown survive but stop
    snapshotting one of the THREE mutated attributes.
    """
    sys.path.insert(0, str(ROOT))
    import scripts.rewind_catchup as rc  # noqa: PLC0415 - import after sys.path
    from tests.test_rewind_timeline_429_retry import _DbCase  # noqa: PLC0415

    before = (rc._log.propagate, rc._log.level, list(rc._log.handlers))

    case = _DbCase(methodName="run")
    case.setUp()
    try:
        # This is what rc.main() does to the module logger.
        rc.setup_file_logging()
        assert rc._log.propagate is False, (
            "setup_file_logging no longer sets propagate=False. If that is "
            "deliberate, this guard's premise changed - re-measure NOW-6 rather "
            "than deleting the restoration it protects."
        )
    finally:
        case.tearDown()

    after = (rc._log.propagate, rc._log.level, list(rc._log.handlers))
    assert after[0] == before[0], f"propagate leaked: {before[0]} -> {after[0]}"
    assert after[1] == before[1], f"level leaked: {before[1]} -> {after[1]}"
    assert after[2] == before[2], (
        "a handler leaked out of _DbCase. An orphaned RotatingFileHandler keeps "
        f"a file open and blinds caplog downstream: {before[2]} -> {after[2]}"
    )
    assert isinstance(rc._log, logging.Logger)
