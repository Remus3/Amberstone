"""NOW-7 step 1: REPORT-ONLY census of tests that leak logger state.

WHAT THIS IS FOR. NOW-6 (LEDGER 1457) was a test that called production code
which set ``propagate = False`` on a module logger and never restored it. That
blinded ``caplog`` for the rest of the process, and three tests failed in a
DIFFERENT file - one that never touches logging. The failure landed on the
victim, not on the leaker. The class fix is a gate that fails the LEAKER at its
own site.

WHY THIS FILE ASSERTS NOTHING. The gate cannot be armed until the leak count is
known. Every leak it would find is a test that goes from green to red, across a
suite of roughly 24.7k tests, and a detector that reddens an unknown number of
greens in one commit is indistinguishable from a broken detector. So this is a
census: it observes, it prints, and it NEVER fails a test or the session.

WHY IT IS NOT IN ``conftest.py``, AND THIS IS DELIBERATE. A conftest plugin is
active for every run by every caller, which is exactly the arming this row
forbids. This file is loaded only when asked for explicitly:

    PYTHONPATH=tools python -m pytest tests -p logger_leak_census -q

``tools`` is not a package, so the module is found by putting ``tools`` on
``PYTHONPATH`` and naming the bare module to ``-p``. Nothing imports it
otherwise.

BUCKET NAMING IS LOAD-BEARING. A bucket that absorbs the INSTRUMENT's own
failures must not be named after a property of the SUBJECT, or every bug in the
instrument is published as a finding about somebody else's test (RC memory
``feedback_your_failure_bucket_vs_the_subjects``, and the cross-repo note that
prompted it). So:

* ``MUTATED``   - a pre-existing logger's state differs after the test. This is
                  a claim ABOUT THE TEST.
* ``CREATED_PRISTINE`` - a logger that did not exist before the test does now,
                  and it is at stdlib defaults (``propagate=True``,
                  ``level=NOTSET``, no handlers). INFORMATIONAL and NOT a leak:
                  importing a module legitimately creates its logger, and the
                  first test to import it is not at fault.
* ``CREATED_DIRTY`` - a logger that did not exist before the test does now AND is
                  NOT at defaults. **This IS a leak and is counted as one.** The
                  logger persists in the manager for the rest of the process
                  carrying whatever state the test left on it.

                  THIS BUCKET EXISTS BECAUSE THE FIRST VERSION OF THIS FILE DID
                  NOT HAVE IT, and its positive controls caught that: 4 of 5
                  deliberate leaks were absorbed by a single ``CREATED`` bucket
                  and reported as informational, because ``getLogger`` creates
                  the logger inside the test that then leaks it. A bucket named
                  after a benign property of the subject ("it is new") was
                  swallowing the exact defect class the census exists to find -
                  which is the lesson in
                  ``feedback_your_failure_bucket_vs_the_subjects``, reproduced by
                  this file against itself.
* ``UNOBSERVED`` - the census could not take a reading. This is a claim ABOUT
                  THIS FILE, and it is counted and printed separately so it can
                  never be read as a clean result.

EVIDENCE IS PRINTED BESIDE THE VERDICT, never just a count. Each row carries the
logger name and the before/after values, because the only reliable way these
defects get caught is a human recognising a row.
"""
from __future__ import annotations

import json
import logging
import os
from collections import Counter

import pytest

# The report lands under ops/runtime by default. ``RC_LOGGER_CENSUS_REPORT_DIR``
# redirects it, which is what the guard test uses so that running the guard can
# never clobber a real census the operator is reading.
_REPORT_DIR = os.environ.get("RC_LOGGER_CENSUS_REPORT_DIR") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ops", "runtime")
_REPORT_JSON = os.path.join(_REPORT_DIR, "logger_leak_census.json")
_REPORT_TXT = os.path.join(_REPORT_DIR, "logger_leak_census.txt")

# The three fields NOW-6 proved a test can leak, in the order a reader wants
# them. ``handlers`` is the identity tuple, not a count: swapping one handler for
# another is a leak that a count cannot see (a cardinality predicate cannot see a
# wrong row).
_FIELDS = ("propagate", "level", "handlers")


def _state(lg):
    return (lg.propagate, lg.level, tuple(id(h) for h in lg.handlers))


# A freshly created stdlib Logger. Anything else on a newly created logger is
# state the creating test left behind.
_PRISTINE = (True, logging.NOTSET, ())


def _pristine(state):
    return state == _PRISTINE


def _snapshot():
    """Map logger name -> state. Returns None if a reading cannot be taken."""
    try:
        snap = {"": _state(logging.getLogger())}
        for name, lg in list(logging.Logger.manager.loggerDict.items()):
            # PlaceHolder entries are not Loggers and have no state to leak.
            if isinstance(lg, logging.Logger):
                snap[name] = _state(lg)
        return snap
    except Exception:  # noqa: BLE001 - a census must never break the run
        return None


def _describe(name, before, after):
    diffs = []
    for i, field in enumerate(_FIELDS):
        if before[i] != after[i]:
            if field == "handlers":
                diffs.append(f"handlers {len(before[i])} -> {len(after[i])}"
                             f" (identities changed)" if len(before[i]) == len(after[i])
                             else f"handlers {len(before[i])} -> {len(after[i])}")
            else:
                diffs.append(f"{field} {before[i]!r} -> {after[i]!r}")
    return f"{name or '<root>'}: " + ", ".join(diffs)


class _Census:
    def __init__(self):
        self.mutated = []       # (nodeid, [description, ...])
        self.created_pristine = Counter()  # new logger left at stdlib defaults
        self.created_dirty = Counter()     # new logger left non-default - A LEAK
        self.unobserved = []    # nodeid, with which half failed
        self.tests_seen = 0
        self.loggers_seen_max = 0

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_protocol(self, item, nextitem):
        before = _snapshot()
        outcome = yield
        del outcome  # the census does not inspect the test's result
        after = _snapshot()
        self.tests_seen += 1
        if before is None or after is None:
            which = "before" if before is None else "after"
            self.unobserved.append((item.nodeid, f"{which} snapshot failed"))
            return
        self.loggers_seen_max = max(self.loggers_seen_max, len(before), len(after))
        rows = []
        for name, prior in before.items():
            now = after.get(name)
            if now is None:
                # A logger disappearing from the manager is not something stdlib
                # does; record it as a mutation rather than silently dropping it.
                rows.append(f"{name or '<root>'}: vanished from the logger manager")
            elif now != prior:
                rows.append(_describe(name, prior, now))
        for name in after:
            if name not in before:
                if _pristine(after[name]):
                    self.created_pristine[name] += 1
                else:
                    # Created AND left non-default: a real leak, not a courtesy.
                    self.created_dirty[name] += 1
                    rows.append(
                        f"{name or '<root>'}: CREATED and left non-default - "
                        f"propagate={after[name][0]!r}, level={after[name][1]!r}, "
                        f"handlers={len(after[name][2])}")
        if rows:
            self.mutated.append((item.nodeid, rows))

    def pytest_sessionfinish(self, session, exitstatus):
        del session, exitstatus
        leaky_tests = len(self.mutated)
        payload = {
            "tests_observed": self.tests_seen,
            "loggers_observed_max": self.loggers_seen_max,
            "MUTATED_tests": leaky_tests,
            "UNOBSERVED_tests": len(self.unobserved),
            "CREATED_PRISTINE_logger_names": len(self.created_pristine),
            "CREATED_DIRTY_logger_names": len(self.created_dirty),
            "mutated": [{"nodeid": n, "diffs": d} for n, d in self.mutated],
            "unobserved": [{"nodeid": n, "why": w} for n, w in self.unobserved],
            "created_pristine_top": self.created_pristine.most_common(25),
            "created_dirty_all": self.created_dirty.most_common(),
        }
        lines = []
        add = lines.append
        add("=" * 78)
        add("NOW-7 LOGGER LEAK CENSUS - REPORT ONLY, NOTHING WAS ASSERTED")
        add("=" * 78)
        add(f"tests observed            : {self.tests_seen}")
        add(f"loggers observed (max)    : {self.loggers_seen_max}")
        add(f"MUTATED  (about the test) : {leaky_tests}")
        add(f"UNOBSERVED (about ME)     : {len(self.unobserved)}")
        add(f"CREATED_DIRTY (a LEAK)    : {len(self.created_dirty)} distinct logger name(s)")
        add(f"CREATED_PRISTINE (info)   : {len(self.created_pristine)} distinct logger name(s)")
        add("")
        if self.tests_seen == 0 or self.loggers_seen_max == 0:
            add("!! VACUOUS CENSUS. Either no test ran, or no logger was ever")
            add("!! observed. A zero MUTATED count above means NOTHING in that")
            add("!! case - it is not a clean result, it is an absent measurement.")
            add("")
        if self.unobserved:
            add("-- UNOBSERVED: the census failed to read state. These are MY")
            add("-- failures, not findings about the tests, and the MUTATED count")
            add("-- above is incomplete by exactly this many tests.")
            for nodeid, why in self.unobserved[:50]:
                add(f"   {nodeid}  [{why}]")
            add("")
        if self.mutated:
            add("-- MUTATED: these tests changed logger state and did not restore it.")
            add("-- Evidence is printed beside each verdict on purpose.")
            for nodeid, rows in self.mutated:
                add(f"   {nodeid}")
                for r in rows:
                    add(f"       {r}")
            add("")
        else:
            add("-- MUTATED: none. Note this is only meaningful if the counts at")
            add("-- the top are non-zero and UNOBSERVED is zero.")
            add("")
        add("NEXT STEP (NOW-7): decide per MUTATED row whether to fix the test or")
        add("exempt it, THEN arm the gate. Do not arm it on this report alone.")
        text = "\n".join(lines)
        try:
            os.makedirs(_REPORT_DIR, exist_ok=True)
            with open(_REPORT_JSON, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2)
            with open(_REPORT_TXT, "w", encoding="utf-8") as fh:
                fh.write(text + "\n")
        except Exception as exc:  # noqa: BLE001 - never break the run over a report
            text += f"\n(could not write the report files: {exc})\n"
        print("\n" + text)


def pytest_configure(config):
    config.pluginmanager.register(_Census(), "now7-logger-leak-census")
