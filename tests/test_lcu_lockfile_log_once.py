"""The LCU lockfile-not-found notice fires once per gap, then at most once per
throttle interval - never once per tick.

Measured 2026-07-29 on logs/2026-07-29.log: 20144 of 21082 lines (95.6 percent,
2.4 MB) were the single line "LCU lockfile not found - client may not be
running". The first fix demoted the repeat from INFO to DEBUG, which fixed the
console but NOTHING ON DISK, because core/log_setup.py calls
fh.setLevel(logging.DEBUG) unconditionally ("always verbose to file").

Re-measured 2026-08-04 on logs/2026-08-04.log: the same line was 13316 of 13692
lines (97.3 percent) over a 6771.5 s window - 1.97 lines/sec, because TWO 1 Hz
LCU pollers emit it.

CORRECTED 2026-08-08: the sentence that stood here attributed that pairing to
two PROCESSES, "pythonw main.py and tools/lcu_agent", and concluded it was
therefore not fixable in-process. Both halves are wrong. `tools/lcu_agent.py:72`
logs to `logs/lcu_agent.log`, not the daily file, and it never imports
LcuClient. `main.py:40` is the ONLY caller of `core.log_setup.setup`, so
`logs/YYYY-MM-DD.log` has exactly one writer process.

The pairing is ONE client with TWO 1 Hz callers of `connect()` racing its
shared throttle timestamp: the frozen auto-accept tick (`lcu/lcu_client.py:260`)
and the rune writer's poll (`lcu/lcu_rune_writer.py:626`), which holds the very
same object - `main.py:226` builds it, `main.py:244` hands it to `_RuneWriter`.
Both are spawned on one AppLoop, hence the same-millisecond pair. The
discriminator is that the first-of-gap line at `:110` is never paired (19
singles on 2026-08-07, one per boot) while the `:114` repeat is 1143 pairs:
two independent clients would each announce the gap. `lcu/lockfile_notice.py`
dedupes across callers; the per-instance throttle pinned below is unchanged and
still the first line of defense.

The contract pinned here therefore has two halves:

  TRANSITION - the FIRST notice of a gap is INFO and immediate, because an
  operator reading the log needs to see exactly when League went away and
  exactly when it came back. A gap that ends and later re-opens re-notifies
  immediately even if the previous throttle window has not expired.

  THROTTLE - the repeat, which carries no information the first line did not,
  is emitted at most once per _LOCKFILE_MISSING_REPEAT_S on the MONOTONIC
  clock. Wall clock is not consulted: it can jump backwards (NTP, DST) and
  would then stall the notice for hours.

Downstream consumer: tools/lcu_push_watcher.py _RE_LOCKFILE_GAP parses these
lines to detect a lockfile gap. Its state machine LATCHES (gap_pending stays
True until the next "LCU connected:" line) and never looks at timestamps, so
one line per gap is sufficient - which the immediate first INFO already
guarantees. That is asserted end-to-end below rather than argued.
"""
from __future__ import annotations

import contextlib
import logging
import time as _real_time
import types
import unittest
from pathlib import Path
from unittest import mock

from lcu import lockfile_notice
from lcu.lcu_client import _LOCKFILE_MISSING_REPEAT_S, LcuClient
from tools.lcu_push_watcher import _RE_LOCKFILE_GAP, classify_events


_MISSING = [Path(r"Z:\definitely-not-a-real-lockfile\lockfile")]
_MSG = "lockfile not found"


def _not_found_records(cm) -> list:
    return [r for r in cm.records if _MSG in r.getMessage()]


def _fake_clock(now_ref):
    """Module-namespace stand-in for `time` exposing ONLY monotonic and sleep.

    Any use of time.time() in the throttle raises AttributeError here, so the
    monotonic requirement is enforced by construction rather than by review.
    sleep is kept because the module's auto-accept loop uses it.
    """
    return types.SimpleNamespace(
        monotonic=lambda: now_ref[0],
        sleep=_real_time.sleep,
    )


def _both_clocks(now_ref):
    """There are TWO monotonic throttles on this line now - the per-instance
    one in the frozen client and the process-wide one in lcu/lockfile_notice.py.
    A test that advances only the client's clock silently measures the other
    one against real elapsed time and sees every repeat suppressed."""
    stack = contextlib.ExitStack()
    stack.enter_context(mock.patch("lcu.lcu_client.time", _fake_clock(now_ref)))
    stack.enter_context(
        mock.patch("lcu.lockfile_notice.time", _fake_clock(now_ref)))
    return stack


def _found_lockfile():
    fake = mock.MagicMock(spec=Path)
    fake.exists.return_value = True
    fake.read_text.return_value = "LeagueClient:1234:2999:sekret:https"
    fake.stat.return_value = mock.MagicMock(st_mtime=1.0)
    return fake


class LockfileNotFoundLogOnceTests(unittest.TestCase):
    def setUp(self):
        # Nothing configures logging in a bare pytest process, so rc.lcu
        # inherits the root logger's WARNING and every record emitted OUTSIDE
        # an assertLogs block is dropped before any handler or filter sees it -
        # including the "LCU connected:" line that re-arms the process-wide
        # episode in lcu/lockfile_notice.py. Production never sees that skew:
        # there is no level that passes the DEBUG repeat while dropping the
        # INFO connect line. Pin DEBUG so the fixture measures the throttle
        # rather than the ambient level.
        logger = logging.getLogger("rc.lcu")
        self.addCleanup(logger.setLevel, logger.level)
        logger.setLevel(logging.DEBUG)

    def test_repeat_ticks_log_the_not_found_line_once(self):
        """50 connects inside one instant produce exactly one record AT ANY
        LEVEL - the DEBUG capture is the point, since the file handler is DEBUG.
        """
        client = LcuClient()
        now = [1000.0]
        with mock.patch("lcu.lcu_client._LOCKFILE_PATHS", _MISSING), \
                _both_clocks(now):
            with self.assertLogs("rc.lcu", level="DEBUG") as cm:
                for _ in range(50):
                    self.assertFalse(client.connect())
        records = _not_found_records(cm)
        self.assertEqual(
            len(records),
            1,
            "50 cold connects emitted more than one record; at 1 Hz across two "
            "processes this is the 13316-line flood measured on 2026-08-04",
        )
        self.assertEqual(records[0].levelname, "INFO")

    def test_repeat_is_throttled_to_one_per_interval_not_one_per_tick(self):
        """Suppression must not destroy the evidence - a repeat still reaches
        the file, but on the interval rather than on every tick, and at DEBUG so
        the console stays quiet.

        Re-expresses the old test_repeats_still_reach_the_file_at_debug: same
        intent (repeats stay diagnosable on disk at DEBUG), new rate.
        """
        client = LcuClient()
        now = [1000.0]
        interval = _LOCKFILE_MISSING_REPEAT_S
        with mock.patch("lcu.lcu_client._LOCKFILE_PATHS", _MISSING), \
                _both_clocks(now):
            with self.assertLogs("rc.lcu", level="DEBUG") as cm:
                # 1 Hz for a little over two intervals.
                for _ in range(int(interval * 2) + 5):
                    client.connect()
                    now[0] += 1.0
        levels = [r.levelname for r in _not_found_records(cm)]
        self.assertEqual(
            levels,
            ["INFO", "DEBUG", "DEBUG"],
            "expected one immediate INFO plus one DEBUG repeat per elapsed "
            f"{interval} s window, got {levels}",
        )

    def test_measured_flood_window_collapses_to_about_two_hundred_lines(self):
        """Regression pin on the interval itself, in the units that were
        measured: the 2026-08-04 window was 6771.5 s and 13316 lines.
        """
        client = LcuClient()
        now = [0.0]
        window_s = 6771.5
        with mock.patch("lcu.lcu_client._LOCKFILE_PATHS", _MISSING), \
                _both_clocks(now):
            with self.assertLogs("rc.lcu", level="DEBUG") as cm:
                # 1.97 lines/sec was TWO processes at 1 Hz; one process ticks 1 Hz.
                while now[0] < window_s:
                    client.connect()
                    now[0] += 1.0
        emitted = len(_not_found_records(cm))
        self.assertLessEqual(
            emitted,
            250,
            f"{emitted} lines over the measured 6771.5 s window; the pre-fix "
            "count for a single 1 Hz process was 6658",
        )

    def test_a_second_loss_after_a_successful_connect_logs_again(self):
        """The transition contract: League closing a second time is news."""
        client = LcuClient()
        with mock.patch("lcu.lcu_client._LOCKFILE_PATHS", _MISSING):
            with self.assertLogs("rc.lcu", level="INFO") as first:
                client.connect()
        self.assertEqual(len(_not_found_records(first)), 1)

        # Simulate the success path having run (connect() sets these on a real
        # lockfile); the reset is what re-arms the notice. In production that
        # same success path also emits "LCU connected:", which is what re-arms
        # the process-wide episode in lcu/lockfile_notice.py - poking the
        # instance flag alone decouples the two, so re-arm both here. The
        # sibling test below drives the real connect and needs no such help.
        client._port = 2999
        client._lockfile_missing_logged = False
        lockfile_notice.current().reset()

        with mock.patch("lcu.lcu_client._LOCKFILE_PATHS", _MISSING):
            with self.assertLogs("rc.lcu", level="INFO") as second:
                client.connect()
        self.assertEqual(
            len(_not_found_records(second)),
            1,
            "a fresh loss after a connect must re-notify, or the operator "
            "cannot tell from the log when League went away",
        )

    def test_a_real_connect_rearms_the_notice(self):
        """End-to-end over connect() itself: missing -> found -> missing must
        produce two INFO lines, with the re-arm done by the success path rather
        than by the test poking the flag.
        """
        client = LcuClient()
        with mock.patch("lcu.lcu_client._LOCKFILE_PATHS", _MISSING):
            with self.assertLogs("rc.lcu", level="INFO") as cm1:
                client.connect()
                client.connect()
        self.assertEqual(len(_not_found_records(cm1)), 1)

        with mock.patch("lcu.lcu_client._LOCKFILE_PATHS", [_found_lockfile()]):
            self.assertTrue(client.connect())
        self.assertEqual(client._port, 2999)

        with mock.patch("lcu.lcu_client._LOCKFILE_PATHS", _MISSING):
            with self.assertLogs("rc.lcu", level="INFO") as cm2:
                client.connect()
        self.assertEqual(len(_not_found_records(cm2)), 1)

    def test_a_reopened_gap_notifies_immediately_inside_a_live_window(self):
        """The easiest thing to get wrong: a gap that ENDS and re-opens while
        the previous throttle window is still running must NOT be swallowed.

        The whole sequence runs inside one interval on the fake clock, so a
        throttle that gates the first notice as well as the repeat fails here.
        """
        client = LcuClient()
        now = [500.0]
        with _both_clocks(now):
            with mock.patch("lcu.lcu_client._LOCKFILE_PATHS", _MISSING):
                with self.assertLogs("rc.lcu", level="DEBUG") as first:
                    client.connect()
            self.assertEqual(len(_not_found_records(first)), 1)

            now[0] += 1.0  # League launches one second later
            with mock.patch("lcu.lcu_client._LOCKFILE_PATHS", [_found_lockfile()]):
                self.assertTrue(client.connect())

            now[0] += 1.0  # and closes again, still deep inside the old window
            with mock.patch("lcu.lcu_client._LOCKFILE_PATHS", _MISSING):
                with self.assertLogs("rc.lcu", level="DEBUG") as second:
                    client.connect()

        records = _not_found_records(second)
        self.assertEqual(
            len(records),
            1,
            "the re-opened gap was swallowed by the still-running throttle "
            f"window ({_LOCKFILE_MISSING_REPEAT_S} s)",
        )
        self.assertEqual(
            records[0].levelname,
            "INFO",
            "a re-opened gap must re-notify at INFO, not as a DEBUG repeat",
        )

    def test_return_value_is_unchanged_by_the_suppression(self):
        """Suppression is a logging change only - every caller branches on the
        bool, so a regression here would silently disable auto-accept.
        """
        client = LcuClient()
        with mock.patch("lcu.lcu_client._LOCKFILE_PATHS", _MISSING):
            self.assertEqual(
                [client.connect() for _ in range(3)], [False, False, False]
            )


class WatcherGapDetectionSurvivesTheThrottleTests(unittest.TestCase):
    """tools/lcu_push_watcher.py must still detect the gap at this interval."""

    def test_the_emitted_message_still_matches_the_watcher_regex(self):
        client = LcuClient()
        with mock.patch("lcu.lcu_client._LOCKFILE_PATHS", _MISSING):
            with self.assertLogs("rc.lcu", level="DEBUG") as cm:
                client.connect()
        msg = _not_found_records(cm)[0].getMessage()
        self.assertTrue(
            _RE_LOCKFILE_GAP.search(msg),
            f"_RE_LOCKFILE_GAP no longer matches the emitted line: {msg!r}",
        )

    def test_one_gap_line_per_gap_is_enough_for_the_watcher(self):
        """The watcher LATCHES gap_pending until the next connect and never
        reads timestamps, so the single immediate INFO carries the detection.
        Fed here as the minimum the throttle can produce: exactly ONE gap line.
        """
        verdicts = classify_events([
            "INFO rc.lcu LCU connected: port 1111 (from x)",
            "INFO rc.lcu LCU lockfile not found - client may not be running",
            "INFO rc.lcu LCU connected: port 2222 (from x)",
            "INFO rc.rune RuneWriter: champ select entered",
            "INFO rc.rune RuneWriter: champion=Ezreal mode=ARAM - applying runes",
            "INFO rc.rune RuneWriter: champ select ended - re-armed",
        ])
        self.assertEqual(len(verdicts), 1)
        self.assertEqual(verdicts[0]["restart_reason"], "lockfile_gap")
        self.assertEqual(verdicts[0]["verdict"], "PASS")


if __name__ == "__main__":
    unittest.main()
