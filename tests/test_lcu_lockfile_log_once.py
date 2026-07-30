"""The LCU lockfile-not-found INFO must fire once per transition, not once per tick.

Measured 2026-07-29 on logs/2026-07-29.log: 20144 of 21082 lines (95.6 percent,
2.4 MB) were the single line "LCU lockfile not found - client may not be
running". Two ~1 Hz callers drive it while League is closed - the auto-accept
heartbeat (lcu/lcu_client.py _auto_accept_tick, which calls connect() whenever
_port is falsy) and the per-request cold connect in
dashboard/_lcu_inprocess.py - so the line repeats forever with no new
information after the first one.

This is a signal-to-noise defect, not merely disk volume: the cost/health
watchdog and every future log audit read a file that is 96 percent one line.
The sibling _refresh_conn_if_changed already documents the intended contract in
its own docstring ("it neither re-parses nor log-spams"), and the auto-accept
loop's except handler already reasons explicitly about not flooding the log at
1 Hz. The cold-start connect() path was the one place that did not honor it.

The contract pinned here is deliberately about TRANSITIONS rather than a rate
limit or a sampled every-Nth line: an operator reading the log needs to see
exactly when League went away and exactly when it came back, and a rate limiter
would eventually re-emit a line that says nothing.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from lcu.lcu_client import LcuClient


_MISSING = [Path(r"Z:\definitely-not-a-real-lockfile\lockfile")]


def _not_found_records(cm) -> list:
    return [r for r in cm.records if "lockfile not found" in r.getMessage()]


class LockfileNotFoundLogOnceTests(unittest.TestCase):
    def test_repeat_ticks_log_the_not_found_line_once(self):
        client = LcuClient()
        with mock.patch("lcu.lcu_client._LOCKFILE_PATHS", _MISSING):
            with self.assertLogs("rc.lcu", level="INFO") as cm:
                for _ in range(50):
                    self.assertFalse(client.connect())
        self.assertEqual(
            len(_not_found_records(cm)),
            1,
            "50 cold connects emitted more than one INFO; at 1 Hz this is the "
            "20144-line flood measured on 2026-07-29",
        )

    def test_repeats_still_reach_the_file_at_debug(self):
        """Suppression must not destroy the evidence - core/log_setup.py sends
        DEBUG to file unconditionally, so a repeat stays diagnosable on disk.
        """
        client = LcuClient()
        with mock.patch("lcu.lcu_client._LOCKFILE_PATHS", _MISSING):
            with self.assertLogs("rc.lcu", level="DEBUG") as cm:
                for _ in range(5):
                    client.connect()
        self.assertEqual(len(_not_found_records(cm)), 5)
        levels = [r.levelname for r in _not_found_records(cm)]
        self.assertEqual(levels, ["INFO", "DEBUG", "DEBUG", "DEBUG", "DEBUG"])

    def test_a_second_loss_after_a_successful_connect_logs_again(self):
        """The transition contract: League closing a second time is news."""
        client = LcuClient()
        with mock.patch("lcu.lcu_client._LOCKFILE_PATHS", _MISSING):
            with self.assertLogs("rc.lcu", level="INFO") as first:
                client.connect()
        self.assertEqual(len(_not_found_records(first)), 1)

        # Simulate the success path having run (connect() sets these on a real
        # lockfile); the reset is what re-arms the notice.
        client._port = 2999
        client._lockfile_missing_logged = False

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

        fake = mock.MagicMock(spec=Path)
        fake.exists.return_value = True
        fake.read_text.return_value = "LeagueClient:1234:2999:sekret:https"
        fake.stat.return_value = mock.MagicMock(st_mtime=1.0)
        with mock.patch("lcu.lcu_client._LOCKFILE_PATHS", [fake]):
            self.assertTrue(client.connect())
        self.assertEqual(client._port, 2999)

        with mock.patch("lcu.lcu_client._LOCKFILE_PATHS", _MISSING):
            with self.assertLogs("rc.lcu", level="INFO") as cm2:
                client.connect()
        self.assertEqual(len(_not_found_records(cm2)), 1)

    def test_return_value_is_unchanged_by_the_suppression(self):
        """Suppression is a logging change only - every caller branches on the
        bool, so a regression here would silently disable auto-accept.
        """
        client = LcuClient()
        with mock.patch("lcu.lcu_client._LOCKFILE_PATHS", _MISSING):
            self.assertEqual(
                [client.connect() for _ in range(3)], [False, False, False]
            )


if __name__ == "__main__":
    unittest.main()
