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
from tests._lcu_notice_isolation import isolate_lockfile_notice
from tests._timing_budget import fleet_test_guard
from tools.lcu_push_watcher import _RE_LOCKFILE_GAP, classify_events


_MISSING = [Path(r"Z:\definitely-not-a-real-lockfile\lockfile")]
_MSG = "lockfile not found"


def _racing_clock(now_ref, racers, timeout):
    """`time` stand-in whose monotonic() parks each RACER thread at a 2-party
    barrier before returning now_ref[0]. Returns (clock, barrier).

    Only racers park. The patch replaces a MODULE global, so any other
    LcuClient in the process that ticks meanwhile reads this clock too; were
    it to park, it would take a racer's slot, release one racer early and
    strand the other until the barrier broke (forced by
    `test_a_foreign_poller_cannot_take_a_racers_barrier_slot`)."""
    barrier = threading.Barrier(2, timeout=timeout)

    def monotonic():
        if threading.current_thread() in racers:
            barrier.wait()
        return now_ref[0]

    return types.SimpleNamespace(monotonic=monotonic, sleep=_real_time.sleep), barrier


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
        # Gate rc.lcu to this test's threads, THEN reset the installed filter
        # and pin DEBUG (tests/_lcu_notice_isolation.py says why each step and
        # its order). Without the gate a foreign LcuClient's real-clock repeat
        # lands in the shared filter and suppresses this test's fake-clock
        # notices: the s140 gated-suite red.
        self._gate = isolate_lockfile_notice(self)

    def test_two_racing_callers_on_one_client_log_the_notice_once(self):
        """The PRODUCTION topology: one client, two callers in two worker
        threads, both reading the throttle timestamp before either writes it.

        Barriers inside both clocks park the threads past their
        `now = time.monotonic()` reads (`lcu/lcu_client.py:108` and the filter's
        own) so the interleaving is forced rather than hoped for. Serialised
        callers would self-suppress, so a sequential test cannot reach this
        defect at all - which is why the sibling two-client tests, though
        useful for caller-agnosticism, do not cover the production topology.

        SCOPE, measured by mutation rather than asserted: a filter that still
        reads its clock but passes every record fails this test, so it pins
        the dedupe decision. A filter removed ENTIRELY passed 3 of 3 (s140
        re-measure): nothing then parks at the second barrier and one racer's
        write lands before the other's check. Replacing the filter's lock with
        a nullcontext does NOT fail it either - the unlocked window is too
        narrow to preempt reliably. Mutual exclusion is pinned separately and
        deterministically by
        `FilterUnitTests.test_the_throttle_decision_is_mutually_exclusive`.
        """
        self.assertEqual(
            len(self._race_two_callers()),
            1,
            "both racing callers logged the same repeat; that unsynchronized "
            "read-compare-write is the measured duplicate",
        )

    def _race_two_callers(self, before_first_connect=None, before_racers=None):
        """One client, an announced gap, then two caller threads racing the
        due repeat. Returns the not-found records the race emitted.

        `before_first_connect()` and `before_racers(client_barrier)` are seams
        for the foreign-emitter tests below; the production-topology test
        passes neither."""
        client = LcuClient()
        now = [1000.0]
        if before_first_connect is not None:
            before_first_connect()

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

            racers = [self._gate.own(threading.Thread(
                target=caller, daemon=True, name=f"lcu-notice-racer-{i}"))
                for i in range(2)]
            # Both throttles read their clock BEFORE taking any lock, so
            # barriering the read parks both racers past the check and makes
            # the interleaving deterministic instead of hoping for it. BOTH
            # clocks are barriered: patching only the client's would let the
            # racers run the filter one after the other, and the filter's lock
            # would then be untested - verified by mutation: with only the
            # client barriered, replacing the lock with a nullcontext passed.
            wait_s = fleet_test_guard.budget(10)
            client_clock, client_barrier = _racing_clock(now, set(racers), wait_s)
            notice_clock, _ = _racing_clock(now, set(racers), wait_s)
            with mock.patch("lcu.lcu_client.time", client_clock), \
                    mock.patch("lcu.lockfile_notice.time", notice_clock):
                if before_racers is not None:
                    before_racers(client_barrier)
                with self.assertLogs("rc.lcu", level="DEBUG") as cm:
                    for t in racers:
                        t.start()
                    for t in racers:
                        t.join(timeout=fleet_test_guard.budget(15))
                    # Inside the capture, so a racer that raised or is still
                    # parked names itself instead of reading as "no logs".
                    self.assertEqual(errors, [])
                    self.assertFalse([t for t in racers if t.is_alive()])
        return _not_found_records(cm)

    def _foreign_poller(self, last_log):
        """A long-lived LcuClient elsewhere in this process - what a poller
        leaked by an earlier test in the same xdist worker looks like: past its
        first notice (so it takes the repeat branch, `lcu/lcu_client.py:135`)
        and ticking on its OWN thread. `last_log` is its real-clock throttle
        stamp. Returns (client, thread); the thread is not started."""
        foreign = LcuClient()
        foreign._lockfile_missing_logged = True
        foreign._lockfile_missing_last_log = last_log
        thread = threading.Thread(target=foreign.connect, daemon=True,
                                  name="foreign-lcu-poller")
        return foreign, thread

    def test_a_foreign_poller_tick_before_the_race_cannot_suppress_it(self):
        """s140 REPRO of the gated-suite red (ops/runtime/kit_v24_suite.log,
        45803 passed / 1 failed): "no logs of level DEBUG or higher triggered
        on rc.lcu", with ONE captured `lcu_client.py:136` DEBUG and NO `:132`
        INFO from this test's own first connect.

        That signature is not the race and not a slow box (a window closed by
        load still shows the `:132` INFO - measured). It is a foreign repeat on
        the REAL clock reaching the process-wide filter after the per-test
        reset: the filter stamps a real monotonic (hundreds of thousands of
        seconds), so this test's fake 1000 s and 1060 s read as inside a live
        window and the INFO and both racing repeats are all dropped."""
        foreign, thread = self._foreign_poller(-_LOCKFILE_MISSING_REPEAT_S)

        def foreign_tick():
            with mock.patch("lcu.lcu_client._LOCKFILE_PATHS", _MISSING):
                thread.start()
                thread.join(timeout=fleet_test_guard.budget(5))
            self.assertFalse(thread.is_alive())
            # Non-vacuity: the foreign client really took its repeat branch
            # and logged (the stamp moves only on the logging path).
            self.assertGreater(foreign._lockfile_missing_last_log, 0)

        self.assertEqual(len(self._race_two_callers(before_first_connect=foreign_tick)), 1)

    def test_a_foreign_poller_cannot_take_a_racers_barrier_slot(self):
        """The sibling window of the same leak: a foreign client ticking WHILE
        the clocks are barriered reads the same patched module global
        (`lcu.lcu_client.time`), so it can park at the racers' 2-party barrier,
        release one racer early and strand the other until the barrier breaks.
        Forced here by parking the foreign tick before the racers start."""
        foreign, thread = self._foreign_poller(_real_time.monotonic())

        def foreign_tick(client_barrier):
            thread.start()
            deadline = _real_time.monotonic() + fleet_test_guard.budget(5)
            while (thread.is_alive() and client_barrier.n_waiting == 0
                   and _real_time.monotonic() < deadline):
                _real_time.sleep(0.005)

        self.assertEqual(len(self._race_two_callers(before_racers=foreign_tick)), 1)

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
