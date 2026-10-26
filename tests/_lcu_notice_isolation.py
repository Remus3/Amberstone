"""Shield the process-wide LCU lockfile-notice dedupe from the rest of the
test process (s140).

`lcu/__init__.py` attaches ONE `LockfileNoticeFilter` to the `rc.lcu` logger
for the whole process, by design: in production it must dedupe every caller
of `connect()`. In a test worker the same property makes it shared state with
every OTHER `LcuClient` the process holds. A long-lived client left behind by
an earlier test file in the same xdist worker keeps logging its not-found
repeat (`lcu/lcu_client.py:136`) on the REAL monotonic clock; when one of
those records lands after the per-test `reset()`, the filter stamps a real
time (hundreds of thousands of seconds), and a test driving a fake clock at
1000 s reads as inside a live window - its first INFO and every repeat are
dropped and the failure reads "no logs of level DEBUG or higher triggered on
rc.lcu". Measured: the 2026-10-26 gated suite (45803 passed, 1 failed;
`ops/runtime/kit_v24_suite.log`) captured exactly that one foreign `:136`
DEBUG and no `:132` INFO; the forced repro is
`tests/test_lcu_lockfile_notice_dedupe.py::CrossInstanceDedupeTests::
test_a_foreign_poller_tick_before_the_race_cannot_suppress_it`.

`isolate_lockfile_notice(testcase)` puts a gate IN FRONT of that filter for
the test's duration: a record from any thread the test does not own is
refused before it can touch the dedupe state (or reach the test's
`assertLogs` capture). The installed filter itself is still the one under
test - nothing is swapped for a private copy.
"""
from __future__ import annotations

import logging
import threading

from lcu import lockfile_notice


class OwnThreadsOnly(logging.Filter):
    """Pass a record only when it is emitted on a thread the test owns: the
    thread that built the gate plus every thread handed to `own()`. Logging
    runs logger filters on the EMITTING thread, so `current_thread()` is the
    emitter."""

    def __init__(self) -> None:
        super().__init__()
        self._owned = {threading.current_thread()}

    def own(self, thread: threading.Thread) -> threading.Thread:
        """Admit `thread`. Call before `thread.start()`, so its first record
        cannot race the registration."""
        self._owned.add(thread)
        return thread

    def filter(self, record: logging.LogRecord) -> bool:
        return threading.current_thread() in self._owned


def isolate_lockfile_notice(testcase) -> OwnThreadsOnly:
    """Gate `rc.lcu` to the test's own threads, then reset the installed
    dedupe filter and pin the logger to DEBUG; every change is undone by
    `testcase.addCleanup`. Returns the gate so the test can `own()` the
    worker threads it starts.

    Order matters twice. The gate goes to the FRONT of the logger's filter
    list because the dedupe filter was attached at package import and logging
    runs filters in list order. The reset comes AFTER the gate, so no foreign
    record can land between the two."""
    logger = logging.getLogger(lockfile_notice.LOGGER_NAME)
    gate = OwnThreadsOnly()
    logger.filters.insert(0, gate)
    testcase.addCleanup(logger.removeFilter, gate)
    attached = lockfile_notice.current()
    testcase.assertIsNotNone(
        attached, "lcu/__init__.py must install the filter at package import")
    attached.reset()
    # coaches/_base_coach.py raises this logger to WARNING at import, and a
    # bare pytest process leaves it at the root's WARNING: either way every
    # record emitted OUTSIDE an assertLogs block - including the "LCU
    # connected:" line that closes an episode - would be dropped before the
    # filter sees it. Production has no level that passes the DEBUG repeat
    # while dropping the INFO connect line, so pin DEBUG.
    testcase.addCleanup(logger.setLevel, logger.level)
    logger.setLevel(logging.DEBUG)
    return gate
