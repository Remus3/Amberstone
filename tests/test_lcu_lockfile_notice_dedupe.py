"""The lockfile-not-found notice is deduped across every caller of connect().

`tests/test_lcu_lockfile_log_once.py` pins the throttle for one caller. That
throttle is instance state (`lcu/lcu_client.py:73` + `:77`) read and written
with no lock, and the RC process drives it from TWO 1 Hz callers on ONE shared
client - the frozen auto-accept tick (`lcu/lcu_client.py:260`) and the rune
writer's poll (`lcu/lcu_rune_writer.py:626`), which holds the same object
(`main.py:226` builds it, `main.py:244` hands it over). Both run their body via
`asyncio.to_thread`, so they race the read-compare-write at
`lcu/lcu_client.py:108` + `:113-115`: both read the old timestamp, both pass,
both log.

MEASURED on the daily logs this run (`logs/YYYY-MM-DD.log` has exactly one
writer process - `main.py:40` is the only caller of `core.log_setup.setup`):

    2026-08-06  2567 / 4924 lines (52.1 pct), 1052 duplicates (41.0 pct)
    2026-08-07  2681 / 4756 lines (56.4 pct), 1143 duplicates (42.6 pct)
    2026-08-08  1587 / 2651 lines (59.9 pct),  654 duplicates (41.2 pct)

Per-timestamp histogram `{1: n, 2: m}` on every day sampled - never 3 - with the
pair 0-1 ms apart. That it is one client and not two is measured: on 2026-08-07
the first-of-gap line at `lcu/lcu_client.py:110` is 19 singles and NEVER paired
(one per boot, and that day had 19 boots) while the `:114` repeat is 1143 pairs.
Two clients would each own `_lockfile_missing_logged` and both would announce
the gap.

The anti-degrade half is the important half. `lcu/lcu_client.py:105-107`
records the intent that "a re-opened gap must not be swallowed by a
still-running window", so the dedupe suppresses per EPISODE, not per window:
a gap that ends and re-opens inside a live throttle window MUST still notify.
`test_a_reopened_gap_still_notifies_across_instances` is that assertion.
"""
from __future__ import annotations

import logging
import threading
import time as _real_time
import types
import unittest
from pathlib import Path
from unittest import mock

from lcu import lockfile_notice
from lcu.lcu_client import _LOCKFILE_MISSING_REPEAT_S, LcuClient
from lcu.lockfile_notice import LockfileNoticeFilter, install
from tools.lcu_push_watcher import _RE_LOCKFILE_GAP, classify_events


_MISSING = [Path(r"Z:\definitely-not-a-real-lockfile\lockfile")]
_MSG = "lockfile not found"


def _not_found_records(cm) -> list:
    return [r for r in cm.records if _MSG in r.getMessage()]


def _fake_clock(now_ref):
    """`time` stand-in exposing only monotonic + sleep, so any use of
    time.time() in either throttle raises rather than silently passing."""
    return types.SimpleNamespace(
        monotonic=lambda: now_ref[0],
        sleep=_real_time.sleep,
    )


def _found_lockfile():
    fake = mock.MagicMock(spec=Path)
    fake.exists.return_value = True
    fake.read_text.return_value = "LeagueClient:1234:2999:sekret:https"
    fake.stat.return_value = mock.MagicMock(st_mtime=1.0)
    return fake


class CrossInstanceDedupeTests(unittest.TestCase):
    """Two clients, one gap - one line."""

    def setUp(self):
        attached = lockfile_notice.current()
        self.assertIsNotNone(
            attached, "lcu/__init__.py must install the filter at package import")
        attached.reset()
        # coaches/_base_coach.py:228 raises this logger to WARNING at import,
        # which drops the episode-END lines before any filter sees them and
        # makes the re-open look swallowed. Not a production concern (no level
        # passes the DEBUG repeat while dropping the INFO connect line) but it
        # has to be pinned here or the fixture measures the wrong thing.
        logger = logging.getLogger("rc.lcu")
        self.addCleanup(logger.setLevel, logger.level)
        logger.setLevel(logging.DEBUG)

    def test_two_racing_callers_on_one_client_log_the_notice_once(self):
        """The PRODUCTION topology: one client, two callers in two worker
        threads, both reading the throttle timestamp before either writes it.

        Barriers inside both clocks park the threads past their
        `now = time.monotonic()` reads (`lcu/lcu_client.py:108` and the filter's
        own) so the interleaving is forced rather than hoped for. Serialised
        callers would self-suppress, so a sequential test cannot reach this
        defect at all - which is why the sibling two-client tests, though
        useful for caller-agnosticism, do not cover the production topology.

        SCOPE, measured by mutation rather than asserted: removing the filter
        entirely fails this test, so it pins the fix. Replacing the filter's
        lock with a nullcontext does NOT fail it - the unlocked window is too
        narrow to preempt reliably. Mutual exclusion is pinned separately and
        deterministically by
        `FilterUnitTests.test_the_throttle_decision_is_mutually_exclusive`.
        """
        client = LcuClient()
        now = [1000.0]

        def racing_clock():
            """Both throttles read their clock BEFORE taking any lock, so
            barriering the read parks both threads past the check and makes the
            interleaving deterministic instead of hoping for it. One barrier
            each: the two clocks are read once per thread per throttle."""
            barrier = threading.Barrier(2, timeout=10)
            return types.SimpleNamespace(
                monotonic=lambda: (barrier.wait(), now[0])[1],
                sleep=_real_time.sleep,
            )

        with mock.patch("lcu.lcu_client._LOCKFILE_PATHS", _MISSING):
            # main.py:227 connects synchronously before either loop spawns, so
            # the gap is already announced and both callers take the throttled
            # repeat branch - which is why :110 is never paired in the logs.
            with mock.patch("lcu.lcu_client.time", _fake_clock(now)), \
                    mock.patch("lcu.lockfile_notice.time", _fake_clock(now)):
                client.connect()

            now[0] += _LOCKFILE_MISSING_REPEAT_S  # both callers now due
            errors = []

            def caller():
                try:
                    client.connect()
                except BaseException as exc:  # noqa: BLE001
                    errors.append(exc)

            # BOTH clocks are barriered. Patching only the client's would park
            # the threads before the frozen throttle but let them run the
            # filter one after the other, and the filter's lock would then be
            # untested - verified by mutation: with only the client barriered,
            # replacing the lock with a nullcontext still passed.
            with mock.patch("lcu.lcu_client.time", racing_clock()), \
                    mock.patch("lcu.lockfile_notice.time", racing_clock()):
                with self.assertLogs("rc.lcu", level="DEBUG") as cm:
                    threads = [threading.Thread(target=caller) for _ in range(2)]
                    for t in threads:
                        t.start()
                    for t in threads:
                        t.join(timeout=15)
            self.assertEqual(errors, [])
            self.assertFalse([t for t in threads if t.is_alive()])

        self.assertEqual(
            len(_not_found_records(cm)),
            1,
            "both racing callers logged the same repeat; that unsynchronized "
            "read-compare-write is the measured duplicate",
        )

    def test_two_clients_in_one_gap_log_the_notice_once(self):
        """Caller-agnostic by construction: the dedupe must also hold for an
        emitter it has never heard of, so this drives two separate clients
        rather than the two callers production actually has."""
        first, second = LcuClient(), LcuClient()
        now = [1000.0]
        with mock.patch("lcu.lcu_client._LOCKFILE_PATHS", _MISSING), \
                mock.patch("lcu.lcu_client.time", _fake_clock(now)), \
                mock.patch("lcu.lockfile_notice.time", _fake_clock(now)):
            with self.assertLogs("rc.lcu", level="DEBUG") as cm:
                self.assertFalse(first.connect())
                self.assertFalse(second.connect())
        self.assertEqual(
            len(_not_found_records(cm)),
            1,
            "the second client re-logged the same gap; that duplicate was "
            "41-43 percent of every emission measured on the daily logs",
        )

    def test_two_clients_polling_a_whole_window_log_the_notice_once(self):
        """Sustained: both clients tick 1 Hz for two throttle windows. The
        per-instance throttle alone yields 2 lines per window - one each."""
        first, second = LcuClient(), LcuClient()
        now = [1000.0]
        with mock.patch("lcu.lcu_client._LOCKFILE_PATHS", _MISSING), \
                mock.patch("lcu.lcu_client.time", _fake_clock(now)), \
                mock.patch("lcu.lockfile_notice.time", _fake_clock(now)):
            with self.assertLogs("rc.lcu", level="DEBUG") as cm:
                for _ in range(int(_LOCKFILE_MISSING_REPEAT_S * 2) + 5):
                    first.connect()
                    second.connect()
                    now[0] += 1.0
        levels = [r.levelname for r in _not_found_records(cm)]
        self.assertEqual(
            levels,
            ["INFO", "DEBUG", "DEBUG"],
            f"expected one line per elapsed window across BOTH clients, got {levels}",
        )

    def test_a_reopened_gap_still_notifies_across_instances(self):
        """ANTI-DEGRADE. A gap that ends and re-opens deep inside a live
        throttle window must re-notify - `lcu/lcu_client.py:105-107` records
        that intent, and a shared timestamp with no episode notion would eat it.

        Driven across two clients on purpose: the client that reports the
        re-opened gap is NOT the one that opened the previous episode.
        """
        first, second = LcuClient(), LcuClient()
        now = [500.0]
        with mock.patch("lcu.lcu_client.time", _fake_clock(now)), \
                mock.patch("lcu.lockfile_notice.time", _fake_clock(now)):
            with mock.patch("lcu.lcu_client._LOCKFILE_PATHS", _MISSING):
                with self.assertLogs("rc.lcu", level="DEBUG") as opening:
                    first.connect()
                    second.connect()
            self.assertEqual(len(_not_found_records(opening)), 1)

            now[0] += 1.0  # League launches a second later
            with mock.patch("lcu.lcu_client._LOCKFILE_PATHS", [_found_lockfile()]):
                self.assertTrue(first.connect())
                self.assertTrue(second.connect())

            now[0] += 1.0  # and closes again, still deep inside the old window
            with mock.patch("lcu.lcu_client._LOCKFILE_PATHS", _MISSING):
                with self.assertLogs("rc.lcu", level="DEBUG") as reopened:
                    second.connect()

        records = _not_found_records(reopened)
        self.assertEqual(
            len(records),
            1,
            "the re-opened gap was swallowed by the still-running window "
            f"({_LOCKFILE_MISSING_REPEAT_S} s) - that is a lost signal, not a saving",
        )
        self.assertEqual(
            records[0].levelname,
            "INFO",
            "a re-opened gap is a transition and must re-notify at INFO",
        )

    def test_the_surviving_line_still_matches_the_watcher_regex(self):
        """`tools/lcu_push_watcher.py` latches on this line; deduping must not
        change what it reads."""
        client = LcuClient()
        with mock.patch("lcu.lcu_client._LOCKFILE_PATHS", _MISSING):
            with self.assertLogs("rc.lcu", level="DEBUG") as cm:
                client.connect()
        msg = _not_found_records(cm)[0].getMessage()
        self.assertTrue(_RE_LOCKFILE_GAP.search(msg))
        verdicts = classify_events([
            "INFO rc.lcu LCU connected: port 1111 (from x)",
            f"INFO rc.lcu {msg}",
            "INFO rc.lcu LCU connected: port 2222 (from x)",
            "INFO rc.rune RuneWriter: champ select entered",
            "INFO rc.rune RuneWriter: champion=Ezreal mode=ARAM - applying runes",
            "INFO rc.rune RuneWriter: champ select ended - re-armed",
        ])
        self.assertEqual(len(verdicts), 1)
        self.assertEqual(verdicts[0]["restart_reason"], "lockfile_gap")


class FilterUnitTests(unittest.TestCase):
    """The filter itself, driven without a client."""

    def _record(self, message: str, level: int = logging.INFO):
        return logging.LogRecord(
            "rc.lcu", level, __file__, 0, message, None, None)

    def test_unrelated_records_are_never_dropped(self):
        f = LockfileNoticeFilter()
        for message in ("Auto-accept started (1.0s interval, async)",
                        "Queue auto-accepted!",
                        "LCU lockfile parse (ValueError): bad"):
            self.assertTrue(f.filter(self._record(message)), message)

    def test_repeat_inside_one_episode_is_throttled_on_the_shared_clock(self):
        now = [0.0]
        with mock.patch("lcu.lockfile_notice.time", _fake_clock(now)):
            f = LockfileNoticeFilter()
            rec = lambda: self._record(  # noqa: E731 - one-line record factory
                "LCU lockfile not found - client may not be running")
            self.assertTrue(f.filter(rec()))
            now[0] += _LOCKFILE_MISSING_REPEAT_S - 0.001
            self.assertFalse(f.filter(rec()))
            now[0] += 0.001
            self.assertTrue(f.filter(rec()))

    def test_every_episode_end_line_rearms_the_notice(self):
        for ender in ("LCU connected: port 2999 (from C:\\x\\lockfile)",
                      "LCU reconnected: port 3000 (lockfile rotated, from C:\\x)",
                      "LCU lockfile gone - client closed; creds cleared"):
            with self.subTest(ender=ender):
                now = [0.0]
                with mock.patch("lcu.lockfile_notice.time", _fake_clock(now)):
                    f = LockfileNoticeFilter()
                    missing = self._record(
                        "LCU lockfile not found - client may not be running")
                    self.assertTrue(f.filter(missing))
                    self.assertTrue(f.filter(self._record(ender)))
                    now[0] += 0.001
                    self.assertTrue(
                        f.filter(missing),
                        "a gap re-opened after a connection event must notify",
                    )

    def test_the_throttle_decision_is_mutually_exclusive(self):
        """The defect being fixed IS a race (two `asyncio.to_thread` callers
        read the throttle timestamp before either writes it), so the filter's
        own check-and-update must not reproduce it one layer up.

        Asserted by holding the filter's lock and proving `filter()` cannot
        reach its decision - a real lock blocks, a nullcontext does not.
        Behavioural rather than an isinstance check, and unlike the racing test
        above it kills the lock-removal mutant deterministically.
        """
        f = LockfileNoticeFilter()
        reached = threading.Event()

        def call_filter():
            f.filter(self._record(
                "LCU lockfile not found - client may not be running"))
            reached.set()

        with f._lock:
            worker = threading.Thread(target=call_filter, daemon=True)
            worker.start()
            self.assertFalse(
                reached.wait(0.5),
                "filter() reached the throttle decision while the lock was "
                "held, so concurrent callers can both pass it",
            )
        self.assertTrue(reached.wait(5), "filter() never completed")
        worker.join(timeout=5)
        self.assertFalse(worker.is_alive())

    def test_install_is_idempotent_and_attached_to_the_client_logger(self):
        logger = logging.getLogger("rc.lcu")
        before = [f for f in logger.filters
                  if isinstance(f, LockfileNoticeFilter)]
        self.assertEqual(len(before), 1, "lcu/__init__.py must install exactly one")
        self.assertIs(install(), before[0])
        self.assertEqual(
            len([f for f in logger.filters
                 if isinstance(f, LockfileNoticeFilter)]), 1)

    def test_the_repeat_interval_does_not_drift_from_the_frozen_client(self):
        """The constant is copied, not imported (a package-level import of the
        frozen client would be circular), so pin the copy to the original."""
        self.assertEqual(lockfile_notice.REPEAT_S, _LOCKFILE_MISSING_REPEAT_S)

    def test_the_needles_are_the_literals_the_frozen_client_emits(self):
        """Read the contract off disk: a reworded log line in the frozen module
        would otherwise disable the dedupe silently."""
        source = (Path(__file__).resolve().parent.parent
                  / "lcu" / "lcu_client.py").read_text(encoding="utf-8")
        self.assertIn(lockfile_notice.MISSING_NEEDLE, source)
        for needle in lockfile_notice.EPISODE_END_NEEDLES:
            self.assertIn(needle, source)


if __name__ == "__main__":
    unittest.main()
