"""Lane 8 - deep audit of core/coaching_data_lock.py.

`core.coaching_data_lock` is the serialization point for the four measured
holders of `coaching_data.json` - coach_integration/_coach.py:117 and :678,
dashboard/_writers.py:60 and dashboard/routes_state.py:637 - all threads of
the single RC `pythonw.exe main.py` process.

Sections:

  A   Characterization. Behaviour that must not regress.
  B   The defects this cycle fixed, each pinned by a test that was RED
      against the pre-rewrite module.
  C   The behaviours the rewrite INTRODUCED (stats snapshot, log
      suppression, handle force-close, mkdir memo), which had no coverage.

REFUTED, RECORDED SO IT IS NOT REINTRODUCED. An earlier draft of D3 claimed
that an exception from the bookkeeping above the in-process release could
strand `_LOCK`, and proved it with a stub whose `__bool__` raised. That was
the fixture supplying the bug (`feedback_subagent_fixture_shaped_to_bug`):
`portalocker.Lock` defines neither `__bool__` nor `__len__`, so default
object truthiness cannot raise, and the real `release()` failure is
`LockException` - an `Exception`, which even the pre-rewrite handler caught.
Those tests are deleted. D3 below tests the mechanism that IS real and is
strictly worse: the pre-rewrite `__enter__` took the process-wide `_LOCK`
before any handler, so a `BaseException` (KeyboardInterrupt, SystemExit)
raised anywhere after that orphaned `_LOCK` forever - and `__exit__` never
runs when `__enter__` raises, so nothing could ever recover it.

Every fault here is INJECTED with a recording stub, never borrowed from the
OS, so the same code path runs on win32 and on Linux CI. The stubs RECORD
into a list rather than raising - an `except Exception` fail-soft boundary
swallows an AssertionError from a raising spy, which would make these tests
pass whether or not the call happened.
"""
from __future__ import annotations

import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import portalocker

from core import coaching_data_lock as cdl

_LOGGER_NAME = "core.coaching_data_lock"

# How long a holder keeps the lock while we prove a second entrant is shut
# out. Must stay well below the module's _TL_TIMEOUT_S.
_SERIALIZE_PROBE_S = 0.15

# The degradation WARNING must NAME the degradation, not merely log
# something. Contract: the file-lock message contains "cross-process" plus
# one of these failure words, so one grep of logs/YYYY-MM-DD.log answers
# "was the lock working" directly.
_DEGRADED_MARKER = "cross-process"
_DEGRADED_HINTS = ("not acquired", "unavailable", "degraded")


class _FakeHandle:
    """Stand-in for portalocker.Lock.fh - records whether it was closed."""

    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class _FaultSwitch:
    """A settable fault source, so one installed stub can be flipped between
    failing and healthy mid-test.

    Needed for the episode-cap tests, which drive many fail / recover cycles:
    re-installing a stub per half-cycle would stack 16 mock patches in one
    test and obscure what is being measured.
    """

    def __init__(self, error=None):
        self.error = error

    def __call__(self):
        return self.error


def _make_file_lock_stub(record, instances, construct_error=None,
                         acquire_error=None, release_error=None):
    """Build a recording stand-in for `portalocker.Lock`.

    No real OS lock is taken and no file is opened, so the suite never
    touches the live `ops/runtime/coaching_data.lock`.

    Any of the three error arguments may be an exception instance or a
    zero-argument callable returning one (or None for "no fault this time").
    """

    def _fault(source):
        if source is None:
            return None
        return source() if callable(source) else source

    class _StubFileLock:
        def __init__(self, path, mode=None, timeout=None):
            record.append(("construct", str(path), mode, timeout))
            instances.append(self)
            self.path = path
            self.fh = None
            err = _fault(construct_error)
            if err is not None:
                raise err

        def acquire(self):
            record.append(("acquire",))
            err = _fault(acquire_error)
            if err is not None:
                raise err
            # Real portalocker sets .fh at the END of a successful acquire.
            self.fh = _FakeHandle()
            return self.fh

        def release(self):
            record.append(("release",))
            err = _fault(release_error)
            if err is not None:
                # portalocker.Lock.release() calls unlock() BEFORE close(),
                # so a raising unlock leaves .fh set and the handle open.
                raise err
            self.fh = None

    return _StubFileLock


class _CombinedLockTestBase(unittest.TestCase):
    """Redirects the lockfile to a temp dir, stubs portalocker, and resets
    the module's process-global degradation state around every test.

    The reset is mandatory, not hygiene: the module deliberately suppresses
    repeat WARNINGs behind a module-global transition flag and memoizes the
    mkdir, so without it one test's degraded state makes the next test
    unable to observe the log it asserts on.
    """

    def setUp(self):
        cdl._reset_state_for_tests()
        self.addCleanup(cdl._reset_state_for_tests)
        self.record = []
        self.fl_instances = []
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        # The module mkdir()s _LOCK_FILE.parent. Point it at a temp dir so no
        # test can create, touch or remove anything under the repo's real
        # ops/runtime/ (a root-level pytest run once deleted the live
        # supervisor lock).
        self.lock_dir = Path(tmp.name) / "runtime"
        self._patch(cdl, "_LOCK_FILE", self.lock_dir / "coaching_data.lock")
        self.install_file_lock()

    def _patch(self, target, attr, value):
        p = mock.patch.object(target, attr, value)
        p.start()
        self.addCleanup(p.stop)

    def install_file_lock(self, **kwargs):
        """Install (or re-install, stacking) the portalocker.Lock stub."""
        stub = _make_file_lock_stub(self.record, self.fl_instances, **kwargs)
        self._patch(cdl.portalocker, "Lock", stub)
        return stub

    def record_mkdirs(self):
        """Spy on Path.mkdir, returning the list of paths it is called on.

        Delegates to the real mkdir so the directory really is created -
        this measures the memo, it does not fake it.
        """
        calls = []
        real_mkdir = Path.mkdir

        def _spy(path_self, *args, **kwargs):
            if str(path_self) == str(self.lock_dir):
                calls.append(str(path_self))
            return real_mkdir(path_self, *args, **kwargs)

        self._patch(Path, "mkdir", _spy)
        return calls

    def tearDown(self):
        # Hygiene net. `_LOCK` is a module global shared with four production
        # call sites and with tests/test_p2w1_app_b.py; a test that leaked it
        # would wedge every later test in this process rather than failing
        # locally. The tests themselves assert the release, so this only ever
        # cleans up after an already-failing case.
        if cdl._LOCK.locked():
            try:
                cdl._LOCK.release()
            except RuntimeError:
                pass


# ---------------------------------------------------------------------------
# SECTION A - CHARACTERIZATION.
# ---------------------------------------------------------------------------

class TestCombinedLockCharacterization(_CombinedLockTestBase):

    def test_context_manager_holds_and_releases_the_process_lock(self):
        manager = cdl.coaching_data_lock()
        self.assertTrue(hasattr(manager, "__enter__"))
        self.assertTrue(hasattr(manager, "__exit__"))
        self.assertFalse(cdl._LOCK.locked())
        with manager as handle:
            self.assertIs(handle, manager)
            self.assertTrue(cdl._LOCK.locked(),
                            "the in-process lock was not held inside the block")
        self.assertFalse(cdl._LOCK.locked(),
                         "the in-process lock survived the block")

    def test_process_lock_is_released_when_the_body_raises(self):
        with self.assertRaises(ValueError):
            with cdl.coaching_data_lock():
                self.assertTrue(cdl._LOCK.locked())
                raise ValueError("writer blew up mid read-modify-write")
        self.assertFalse(cdl._LOCK.locked(),
                         "a raising body leaked the in-process lock")

    def test_exit_does_not_suppress_the_body_exception(self):
        manager = cdl.coaching_data_lock()
        manager.__enter__()
        suppressed = manager.__exit__(ValueError, ValueError("boom"), None)
        self.assertFalse(suppressed,
                         "__exit__ returned truthy and would swallow writer errors")
        self.assertFalse(cdl._LOCK.locked())

    def test_body_runs_when_the_file_lock_acquire_times_out(self):
        """Fail-open on LockException is deliberate (module docstring)."""
        self.install_file_lock(acquire_error=portalocker.LockException("timed out"))
        ran = []
        with cdl.coaching_data_lock():
            ran.append(cdl._LOCK.locked())
        self.assertEqual(ran, [True],
                         "the body did not run, or ran without the in-process lock")
        self.assertFalse(cdl._LOCK.locked())
        self.assertNotIn(("release",), self.record,
                         "released a file lock that was never acquired")

    def test_body_runs_when_the_file_lock_acquire_raises_oserror(self):
        """The AV / permission case.

        portalocker.Lock.acquire() wraps most failures in LockException, but
        `self._get_fh()` (which opens the lockfile) is called OUTSIDE that
        try, so a raw OSError from opening the file propagates un-wrapped.
        Both `except` arms in _acquire_file_lock are live.
        """
        self.install_file_lock(acquire_error=PermissionError(13, "Access is denied"))
        ran = []
        with cdl.coaching_data_lock():
            ran.append(cdl._LOCK.locked())
        self.assertEqual(ran, [True])
        self.assertFalse(cdl._LOCK.locked())
        self.assertNotIn(("release",), self.record,
                         "released a file lock that was never acquired")

    def test_a_second_thread_cannot_enter_while_the_first_is_inside(self):
        inside = threading.Event()
        let_go = threading.Event()
        second_entered = threading.Event()

        def _first():
            with cdl.coaching_data_lock():
                inside.set()
                let_go.wait(timeout=30.0)

        def _second():
            with cdl.coaching_data_lock():
                second_entered.set()

        t1 = threading.Thread(target=_first, daemon=True)
        t1.start()
        self.assertTrue(inside.wait(timeout=10.0), "the first thread never entered")
        t2 = threading.Thread(target=_second, daemon=True)
        t2.start()
        try:
            # Probe window is deliberately far shorter than _TL_TIMEOUT_S, so
            # this measures mutual exclusion and not the fail-open timeout.
            self.assertFalse(
                second_entered.wait(timeout=_SERIALIZE_PROBE_S),
                "a second thread entered the critical section while the first held it")
        finally:
            let_go.set()
            t2.join(timeout=10.0)
            t1.join(timeout=10.0)
        self.assertTrue(second_entered.is_set(),
                        "the second thread never got in after the first released")
        self.assertFalse(cdl._LOCK.locked())

    def test_file_lock_is_built_for_the_module_lock_path_with_a_bounded_timeout(self):
        with cdl.coaching_data_lock():
            pass
        constructs = [r for r in self.record if r[0] == "construct"]
        self.assertEqual(len(constructs), 1)
        _, path, mode, timeout = constructs[0]
        self.assertEqual(path, str(cdl._LOCK_FILE))
        self.assertEqual(mode, "a+b")
        self.assertEqual(timeout, cdl._LOCK_TIMEOUT_S)
        self.assertGreater(cdl._LOCK_TIMEOUT_S, 0)

    def test_file_lock_is_acquired_then_released_around_the_body(self):
        with cdl.coaching_data_lock():
            self.assertIn(("acquire",), self.record)
            self.assertNotIn(("release",), self.record,
                             "the file lock was released before the body ran")
        self.assertEqual([r[0] for r in self.record],
                         ["construct", "acquire", "release"])


# ---------------------------------------------------------------------------
# SECTION B - the four defects this cycle fixed.
# ---------------------------------------------------------------------------

class TestD1FileLockFailureIsSilent(_CombinedLockTestBase):
    """D1 - a failed OS lock acquire used to leave no trace anywhere.

    Pre-rewrite, both `except` arms swallowed the failure with no log call,
    and the module imported only threading / pathlib / portalocker - there
    was no logger in it at all. An RC running for hours with the
    cross-process lock permanently unavailable was indistinguishable from a
    healthy one.
    """

    def _assert_degradation_warning(self, records):
        self.assertTrue(records, "no WARNING was emitted for the lost file lock")
        blob = " ".join(r.getMessage() for r in records).lower()
        self.assertIn(_DEGRADED_MARKER, blob,
                      "the warning does not say WHICH lock was lost")
        self.assertTrue(
            any(hint in blob for hint in _DEGRADED_HINTS),
            "the warning does not say the lock was NOT acquired; got: " + blob)

    def test_lock_exception_emits_a_degradation_warning(self):
        self.install_file_lock(acquire_error=portalocker.LockException("timed out"))
        with self.assertLogs(_LOGGER_NAME, level="WARNING") as cm:
            with cdl.coaching_data_lock():
                pass
        self._assert_degradation_warning(cm.records)

    def test_generic_oserror_emits_a_degradation_warning(self):
        self.install_file_lock(acquire_error=PermissionError(13, "Access is denied"))
        with self.assertLogs(_LOGGER_NAME, level="WARNING") as cm:
            with cdl.coaching_data_lock():
                pass
        self._assert_degradation_warning(cm.records)

    def test_the_happy_path_stays_quiet(self):
        """A clean, never-degraded acquire logs nothing - the coach takes
        this lock on every poll tick."""
        with self.assertNoLogs(_LOGGER_NAME, level="WARNING"):
            with cdl.coaching_data_lock():
                pass

    def test_repeat_failures_are_counted_not_logged(self):
        """A permanently broken lock must not flood logs/YYYY-MM-DD.log."""
        self.install_file_lock(acquire_error=portalocker.LockException("timed out"))
        with self.assertLogs(_LOGGER_NAME, level="WARNING") as cm:
            for _ in range(5):
                with cdl.coaching_data_lock():
                    pass
        self.assertEqual(len(cm.records), 1,
                         "every repeat logged; a wedged lock would flood the log")
        self.assertEqual(cdl.coaching_data_lock_stats()["file_lock_failures"], 5,
                         "suppressed repeats were not counted either")

    def test_recovery_after_a_failure_is_logged_exactly_once(self):
        """The end of an episode is logged too, at WARNING, so one grep
        shows the whole outage rather than only its opening. The recovery
        line must not then repeat on every later success."""
        self.install_file_lock(acquire_error=portalocker.LockException("timed out"))
        with cdl.coaching_data_lock():
            pass
        self.install_file_lock()
        with self.assertLogs(_LOGGER_NAME, level="WARNING") as cm:
            with cdl.coaching_data_lock():
                pass
        self.assertEqual(len(cm.records), 1,
                         "recovery was not logged exactly once")
        self.assertIn("recovered", cm.records[0].getMessage().lower())
        with self.assertNoLogs(_LOGGER_NAME, level="WARNING"):
            with cdl.coaching_data_lock():
                pass


class _HeldLockContentionMixin:
    """Shared driver for the two defects that only appear under contention.

    Not a TestCase - D2 and D4 both need this helper, and making D4 a
    subclass of D2 would silently re-run every D2 test under a second name.
    """

    def _enter_against_a_held_lock(self, ceiling_s=3.0):
        """Hold `_LOCK` from one thread, try to enter from another.

        Never blocks the suite: the contender runs in a daemon thread and the
        holder is released on a timeout whether or not the contender got in.
        """
        result = {}
        holder_ready = threading.Event()
        release_holder = threading.Event()
        entered = threading.Event()

        def _holder():
            cdl._LOCK.acquire()
            holder_ready.set()
            release_holder.wait(timeout=30.0)
            try:
                cdl._LOCK.release()
            except RuntimeError as exc:
                # The contender stole a lock this thread owned.
                result["holder_release_error"] = repr(exc)

        def _contender():
            started = time.monotonic()
            try:
                with cdl.coaching_data_lock():
                    result["elapsed_s"] = time.monotonic() - started
                    result["body_ran"] = True
                    entered.set()
                result["locked_after_exit"] = cdl._LOCK.locked()
                result["exit_ok"] = True
            except RuntimeError as exc:
                # threading.Lock.release() on a lock this instance never took.
                result["exit_error"] = repr(exc)

        ht = threading.Thread(target=_holder, daemon=True)
        ht.start()
        self.assertTrue(holder_ready.wait(timeout=10.0),
                        "the holder thread never took the lock")
        ct = threading.Thread(target=_contender, daemon=True)
        ct.start()
        result["entered_in_time"] = entered.wait(timeout=ceiling_s)
        if result["entered_in_time"]:
            # Let the contender finish its __exit__ while the holder is STILL
            # holding, so `locked_after_exit` measures the D4 question.
            ct.join(timeout=10.0)
        release_holder.set()
        ct.join(timeout=15.0)
        ht.join(timeout=15.0)
        return result


class TestD2UnboundedProcessLockAcquire(_HeldLockContentionMixin, _CombinedLockTestBase):
    """D2 - the in-process acquire used to be unbounded.

    Pre-rewrite `__enter__` called `self._tl.acquire()` with no timeout, the
    one path that could block a coach thread forever - the exact outcome the
    module's own stated fail-open policy exists to avoid, and which it
    already honoured for the file lock.

    Contract: `_TL_TIMEOUT_S` is a positive float; when another thread holds
    `_LOCK` for longer than it, `__enter__` gives up within roughly that
    window, warns, and PROCEEDS into the body.
    """

    def test_module_exposes_a_bounded_process_lock_timeout(self):
        timeout = getattr(cdl, "_TL_TIMEOUT_S", None)
        self.assertIsNotNone(
            timeout,
            "no _TL_TIMEOUT_S - __enter__ acquires the in-process lock unbounded")
        self.assertIsInstance(timeout, float)
        self.assertGreater(timeout, 0)
        # Cross-file constraint: tests/test_p2w1_app_b.py:338
        # (test_reset_state_holds_coaching_data_lock) holds _LOCK for 0.25s and
        # asserts the writer is still BLOCKED. A timeout at or under that turns
        # that test red, so keep a wide margin.
        self.assertGreaterEqual(
            timeout, 1.0,
            "too short: tests/test_p2w1_app_b.py:338 blocks a writer for 0.25s")

    def test_enter_gives_up_on_a_held_process_lock_and_runs_the_body(self):
        with mock.patch.object(cdl, "_TL_TIMEOUT_S", 0.2):
            result = self._enter_against_a_held_lock(ceiling_s=3.0)
        self.assertTrue(result.get("entered_in_time"),
                        "__enter__ blocked past the ceiling on a held lock")
        self.assertTrue(result.get("body_ran"),
                        "fail-open means the body still runs; it did not")
        self.assertLess(result.get("elapsed_s", 1e9), 3.0)
        self.assertGreaterEqual(
            result.get("elapsed_s", 0.0), 0.1,
            "returned far too fast - it did not actually wait for the lock")
        self.assertEqual(cdl.coaching_data_lock_stats()["thread_lock_timeouts"], 1)

    def test_giving_up_on_the_process_lock_emits_a_warning(self):
        with mock.patch.object(cdl, "_TL_TIMEOUT_S", 0.2):
            with self.assertLogs(_LOGGER_NAME, level="WARNING") as cm:
                result = self._enter_against_a_held_lock(ceiling_s=3.0)
        self.assertTrue(result.get("entered_in_time"))
        blob = " ".join(r.getMessage() for r in cm.records).lower()
        self.assertTrue(
            any(hint in blob for hint in _DEGRADED_HINTS),
            "a lost update went completely unlogged; got: " + blob)


class TestD3BaseExceptionOrphansTheProcessLock(_CombinedLockTestBase):
    """D3 - a BaseException must never orphan the process-wide lock.

    REPLACES a refuted first draft. That draft asserted an exception from
    the bookkeeping above the in-process release could strand `_LOCK`, and
    manufactured it with a stub whose `__bool__` raised. `portalocker.Lock`
    has no `__bool__` and no `__len__`, so default object truthiness cannot
    raise, and its real release failure is `LockException` - an `Exception`,
    which even the pre-rewrite handler caught. The mechanism could not fire
    in production and the tests were deleted.

    The real mechanism is worse. Pre-rewrite `__enter__` took the
    process-wide `_LOCK` on its first line, before any handler existed, and
    `__exit__` never runs when `__enter__` raises. A KeyboardInterrupt or
    SystemExit arriving anywhere in the rest of `__enter__` therefore
    orphaned `_LOCK` for the life of the process, deadlocking all four
    writers with nothing able to recover it. The fix is the
    `except BaseException: self._release_thread_lock(); raise` block in
    `__enter__` plus the `finally` in `__exit__`.

    KeyboardInterrupt is used because it is a BaseException that can genuinely
    arrive at any bytecode boundary, including inside portalocker's own
    open/lock/close calls - unlike a synthetic method the real class does not
    define.
    """

    def test_keyboard_interrupt_during_file_lock_acquire_does_not_orphan_the_lock(self):
        self.install_file_lock(acquire_error=KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):
            with cdl.coaching_data_lock():
                self.fail("the body must not run when __enter__ is interrupted")
        self.assertFalse(
            cdl._LOCK.locked(),
            "an interrupt inside __enter__ orphaned the process-wide lock; "
            "__exit__ never runs when __enter__ raises, so nothing recovers it")

    def test_keyboard_interrupt_while_building_the_file_lock_does_not_orphan_the_lock(self):
        """The same hazard one call earlier - portalocker's constructor opens
        nothing, but `_ensure_lock_dir()` runs right before it and does touch
        the filesystem."""
        self.install_file_lock(construct_error=KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):
            with cdl.coaching_data_lock():
                self.fail("the body must not run when __enter__ is interrupted")
        self.assertFalse(cdl._LOCK.locked())

    def test_keyboard_interrupt_during_file_lock_release_does_not_orphan_the_lock(self):
        """The `finally` half of the same fix: `__exit__` releases the
        in-process lock even when the file-lock release is interrupted."""
        self.install_file_lock(release_error=KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):
            with cdl.coaching_data_lock():
                pass
        self.assertFalse(
            cdl._LOCK.locked(),
            "an interrupt during __exit__ orphaned the process-wide lock")

    def test_ordinary_lock_exception_from_release_still_releases_the_process_lock(self):
        """The ordinary case, which is what actually happens in production:
        portalocker raises LockException from unlock. It must be absorbed and
        the in-process lock released."""
        self.install_file_lock(release_error=portalocker.LockException("unlock failed"))
        with cdl.coaching_data_lock():
            pass
        self.assertFalse(cdl._LOCK.locked(),
                         "a failed file-lock release stranded the in-process lock")

    def test_the_lock_is_reusable_after_an_interrupted_enter(self):
        """The consequence, stated as behaviour: a later writer must still be
        able to take the lock. This is what an orphaned lock destroys."""
        self.install_file_lock(acquire_error=KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):
            with cdl.coaching_data_lock():
                pass
        self.install_file_lock()
        entered = threading.Event()

        def _later_writer():
            with cdl.coaching_data_lock():
                entered.set()

        t = threading.Thread(target=_later_writer, daemon=True)
        t.start()
        got_in = entered.wait(timeout=3.0)
        if not got_in and cdl._LOCK.locked():
            # The lock is orphaned and this writer is parked on it. Free it
            # and drain the thread HERE, so it cannot wake inside a later
            # test holding a module-global lock behind its back.
            try:
                cdl._LOCK.release()
            except RuntimeError:
                pass
            entered.wait(timeout=10.0)
        t.join(timeout=10.0)
        self.assertFalse(t.is_alive(), "the probe writer thread leaked")
        self.assertTrue(got_in, "a later writer deadlocked on the orphaned lock")


class TestD4ReleasingAnUnheldLock(_HeldLockContentionMixin, _CombinedLockTestBase):
    """D4 - the release used to be unconditional.

    Pre-rewrite `__exit__` ended in a bare `self._tl.release()` that never
    consulted whether this instance had acquired the lock. That was inert
    only because the unbounded acquire could not return without it; the
    moment D2 landed, the fail-open path reached that line holding nothing.
    `threading.Lock.release()` on an unheld lock raises RuntimeError, and on
    a lock another thread owns it SUCCEEDS - handing that thread's critical
    section to everybody, because threading.Lock has no owner check.
    """

    def test_exit_after_a_timed_out_acquire_neither_raises_nor_steals_the_lock(self):
        with mock.patch.object(cdl, "_TL_TIMEOUT_S", 0.2):
            result = self._enter_against_a_held_lock(ceiling_s=3.0)
        self.assertTrue(result.get("entered_in_time"),
                        "__enter__ never timed out, so the D4 path was not reached")
        self.assertIsNone(
            result.get("exit_error"),
            "__exit__ called release() on a lock it never acquired: "
            + str(result.get("exit_error")))
        self.assertTrue(result.get("exit_ok"), "__exit__ did not complete")
        self.assertTrue(
            result.get("locked_after_exit"),
            "__exit__ released a lock the holder thread still owned")
        self.assertIsNone(
            result.get("holder_release_error"),
            "the holder's own release() failed - its lock had been stolen: "
            + str(result.get("holder_release_error")))


# ---------------------------------------------------------------------------
# SECTION C - behaviours the rewrite INTRODUCED.
# ---------------------------------------------------------------------------

class TestDegradationStats(_CombinedLockTestBase):

    def test_stats_reports_every_declared_counter(self):
        """The KEY SET is the contract, so it is asserted exhaustively - but
        the test name deliberately does not carry a count, which is what made
        the previous name drift the moment a fourth counter landed."""
        stats = cdl.coaching_data_lock_stats()
        self.assertEqual(sorted(stats), [
            "degradation_episodes",
            "file_lock_failures",
            "file_lock_release_failures",
            "thread_lock_timeouts",
        ])
        self.assertEqual(set(stats.values()), {0})
        self.assertTrue(all(isinstance(v, int) for v in stats.values()))

    def test_stats_returns_a_copy_not_the_live_dict(self):
        """Ops and tests read this; a live handle would let any reader
        silently zero the module's own counters."""
        snapshot = cdl.coaching_data_lock_stats()
        snapshot["file_lock_failures"] = 999
        snapshot["injected_key"] = 1
        fresh = cdl.coaching_data_lock_stats()
        self.assertEqual(fresh["file_lock_failures"], 0,
                         "coaching_data_lock_stats() handed out the live dict")
        self.assertNotIn("injected_key", fresh)

    def test_a_snapshot_does_not_move_under_later_activity(self):
        snapshot = cdl.coaching_data_lock_stats()
        self.install_file_lock(acquire_error=portalocker.LockException("timed out"))
        with cdl.coaching_data_lock():
            pass
        self.assertEqual(snapshot["file_lock_failures"], 0,
                         "an already-returned snapshot tracked the live counter")
        self.assertEqual(cdl.coaching_data_lock_stats()["file_lock_failures"], 1)


class TestSuppressionIsLoggingOnly(_CombinedLockTestBase):
    """The trap this pins: a log-suppression cache that silently becomes a
    behaviour gate. The transition flag must never decide whether a lock is
    attempted, whether the body runs, or whether a counter moves."""

    def test_repeat_acquires_still_attempt_the_file_lock_and_run_the_body(self):
        self.install_file_lock(acquire_error=portalocker.LockException("timed out"))
        held_inside = []
        for _ in range(4):
            with cdl.coaching_data_lock():
                held_inside.append(cdl._LOCK.locked())
            self.assertFalse(cdl._LOCK.locked(),
                             "a suppressed repeat leaked the in-process lock")
        self.assertEqual(held_inside, [True] * 4,
                         "a suppressed repeat skipped the in-process lock")
        constructs = [r for r in self.record if r[0] == "construct"]
        acquires = [r for r in self.record if r[0] == "acquire"]
        self.assertEqual(len(constructs), 4,
                         "suppression stopped the file lock from being ATTEMPTED")
        self.assertEqual(len(acquires), 4)
        self.assertEqual(cdl.coaching_data_lock_stats()["file_lock_failures"], 4,
                         "suppression stopped the failure from being COUNTED")

    def test_a_degraded_lock_still_acquires_successfully_once_the_fault_clears(self):
        self.install_file_lock(acquire_error=portalocker.LockException("timed out"))
        with cdl.coaching_data_lock():
            pass
        self.install_file_lock()
        with cdl.coaching_data_lock():
            pass
        self.assertIn(("release",), self.record,
                      "the recovered acquire never took a real file lock")
        self.assertEqual(cdl.coaching_data_lock_stats()["file_lock_failures"], 1)


class TestFileLockReleaseFailure(_CombinedLockTestBase):
    """A failed release() must force-close the handle.

    `portalocker.Lock.release()` unlocks BEFORE it closes, so a raising
    unlock leaves the handle open with the byte range still locked, and the
    class has no finalizer. Dropping the last reference would strand the OS
    lock until process exit, after which every later acquire burns the full
    2s poll.
    """

    def _release_once_with_failure(self):
        self.install_file_lock(
            release_error=portalocker.LockException("unlock failed"))
        with cdl.coaching_data_lock():
            pass
        self.assertEqual(len(self.fl_instances), 1)
        return self.fl_instances[0]

    def test_a_failed_release_force_closes_the_underlying_handle(self):
        fl = self._release_once_with_failure()
        self.assertIsNotNone(fl.__dict__.get("path"))
        self.assertIsNone(fl.fh, "fl.fh was not cleared after the force-close")

    def test_the_handle_object_itself_is_closed(self):
        handles = []
        real_stub = _make_file_lock_stub(self.record, self.fl_instances,
                                         release_error=portalocker.LockException("x"))

        class _Watched(real_stub):
            def acquire(self):
                fh = super().acquire()
                handles.append(fh)
                return fh

        self._patch(cdl.portalocker, "Lock", _Watched)
        with cdl.coaching_data_lock():
            pass
        self.assertEqual(len(handles), 1)
        self.assertTrue(handles[0].closed,
                        "the OS lock stays held: the handle was never closed")

    def test_a_failed_release_increments_its_own_counter(self):
        self._release_once_with_failure()
        stats = cdl.coaching_data_lock_stats()
        self.assertEqual(stats["file_lock_release_failures"], 1)
        self.assertEqual(stats["file_lock_failures"], 0,
                         "a release failure was miscounted as an acquire failure")

    def test_a_failed_release_warns(self):
        self.install_file_lock(
            release_error=portalocker.LockException("unlock failed"))
        with self.assertLogs(_LOGGER_NAME, level="WARNING") as cm:
            with cdl.coaching_data_lock():
                pass
        blob = " ".join(r.getMessage() for r in cm.records).lower()
        self.assertIn("release", blob)

    def test_a_failed_release_still_releases_the_process_lock(self):
        self._release_once_with_failure()
        self.assertFalse(cdl._LOCK.locked())


class TestLockDirectoryMemo(_CombinedLockTestBase):
    """`_ensure_lock_dir` memoizes the mkdir per process.

    ops/runtime/ is gitignored and absent in a fresh clone, so the mkdir is
    load-bearing on first run - but running it on every acquire put an
    unbounded filesystem syscall inside the process-wide critical section,
    on exactly the antivirus / OneDrive path this module adopted portalocker
    to survive.
    """

    def test_the_lock_directory_is_created_when_missing(self):
        calls = self.record_mkdirs()
        self.assertFalse(self.lock_dir.exists())
        with cdl.coaching_data_lock():
            pass
        self.assertTrue(self.lock_dir.is_dir(), "the lockfile parent was not created")
        self.assertEqual(len(calls), 1)

    def test_the_mkdir_does_not_repeat_on_a_later_acquire(self):
        calls = self.record_mkdirs()
        for _ in range(3):
            with cdl.coaching_data_lock():
                pass
        self.assertEqual(len(calls), 1,
                         "the mkdir syscall ran again inside the critical section")

    # ORDERING, because it made an earlier assertion read oddly:
    # `_ensure_lock_dir()` runs at the TOP of the acquire, so a re-arm caused
    # by a failure takes effect on the FOLLOWING acquire, never on the one
    # that failed. Every test below therefore measures three acquires.

    def test_a_directory_implicating_failure_rearms_the_mkdir_memo(self):
        """Without the re-arm, a transiently deleted ops/runtime leaves the
        lock permanently degraded behind a stale memo - the directory is
        never recreated, so every later acquire fails too."""
        calls = self.record_mkdirs()
        with cdl.coaching_data_lock():
            pass
        self.assertEqual(len(calls), 1)

        self.install_file_lock(
            acquire_error=FileNotFoundError(2, "No such file or directory"))
        with cdl.coaching_data_lock():
            pass
        self.assertEqual(len(calls), 1,
                         "the re-arm must take effect on the NEXT acquire, "
                         "not retroactively on the one that failed")

        self.install_file_lock()
        with cdl.coaching_data_lock():
            pass
        self.assertEqual(len(calls), 2,
                         "a directory-implicating failure did not re-arm the memo")

    def test_a_file_only_failure_does_not_rearm_the_mkdir_memo(self):
        """The whole point of narrowing the re-arm.

        A persistent antivirus block on the lock FILE leaves the DIRECTORY
        intact. Re-arming on those failures would put the mkdir syscall back
        inside the process-wide critical section on every acquire - in
        exactly the degraded state where acquires are most frequent and
        slowest, which is the state the memo exists for.
        """
        calls = self.record_mkdirs()
        with cdl.coaching_data_lock():
            pass
        self.assertEqual(len(calls), 1)

        self.install_file_lock(
            acquire_error=PermissionError(13, "Access is denied"))
        for _ in range(3):
            with cdl.coaching_data_lock():
                pass
        self.assertTrue(self.lock_dir.is_dir(), "the directory is still intact")

        self.install_file_lock()
        with cdl.coaching_data_lock():
            pass
        self.assertEqual(
            len(calls), 1,
            "a file-only failure re-armed the memo, so the mkdir syscall is "
            "back inside the critical section on every degraded acquire")

    def test_the_acquire_after_a_directory_failure_recreates_the_directory(self):
        """The recovery path, end to end: re-arming is only worth anything if
        the next acquire actually rebuilds the directory and the lock works
        again afterwards."""
        calls = self.record_mkdirs()
        with cdl.coaching_data_lock():
            pass
        self.assertEqual(len(calls), 1)

        self.install_file_lock(
            acquire_error=FileNotFoundError(2, "No such file or directory"))
        with cdl.coaching_data_lock():
            pass

        # The directory really is gone now.
        shutil.rmtree(self.lock_dir)
        self.assertFalse(self.lock_dir.exists())

        self.install_file_lock()
        del self.record[:]
        with cdl.coaching_data_lock():
            pass
        self.assertEqual(len(calls), 2, "the deleted lock directory was never recreated")
        self.assertTrue(self.lock_dir.is_dir())
        self.assertEqual([r[0] for r in self.record], ["construct", "acquire", "release"],
                         "the lock did not come back after the directory was rebuilt")
        self.assertEqual(cdl.coaching_data_lock_stats()["file_lock_failures"], 1,
                         "the recovered acquire failed again")


def _wrap_chain(leaf, depth):
    """Wrap `leaf` in `depth` LockExceptions linked by __cause__.

    depth=0 returns the leaf itself, depth=1 puts it one link down, and so
    on - which is how portalocker presents an infrastructure failure it
    re-raised as a LockException.
    """
    exc = leaf
    for i in range(depth):
        outer = portalocker.LockException(f"wrapper {i}")
        outer.__cause__ = exc
        exc = outer
    return exc


class TestImplicatesLockDir(unittest.TestCase):
    """`_implicates_lock_dir` decides whether the mkdir memo is re-armed, so
    a wrong answer either restores the syscall-in-critical-section defect
    (too broad) or leaves a deleted ops/runtime unrecoverable (too narrow)."""

    def test_a_direct_file_not_found_implicates_the_directory(self):
        self.assertTrue(cdl._implicates_lock_dir(FileNotFoundError(2, "missing")))

    def test_a_direct_not_a_directory_implicates_the_directory(self):
        self.assertTrue(cdl._implicates_lock_dir(NotADirectoryError(20, "not a dir")))

    def test_it_finds_a_cause_one_link_deep(self):
        exc = _wrap_chain(FileNotFoundError(2, "missing"), 1)
        self.assertTrue(cdl._implicates_lock_dir(exc))

    def test_it_finds_a_cause_two_links_deep(self):
        exc = _wrap_chain(FileNotFoundError(2, "missing"), 2)
        self.assertTrue(cdl._implicates_lock_dir(exc))

    def test_an_unrelated_exception_does_not_implicate_the_directory(self):
        self.assertFalse(cdl._implicates_lock_dir(PermissionError(13, "denied")))
        self.assertFalse(cdl._implicates_lock_dir(ValueError("unrelated")))
        self.assertFalse(cdl._implicates_lock_dir(
            portalocker.LockException("plain timeout")))

    def test_an_unrelated_cause_chain_does_not_implicate_the_directory(self):
        exc = _wrap_chain(PermissionError(13, "denied"), 3)
        self.assertFalse(cdl._implicates_lock_dir(exc))

    def test_the_walk_is_bounded_and_gives_up_on_a_deep_chain(self):
        """A cause chain deeper than the bound must return False rather than
        walking it - the bound is what makes this safe to call on an
        arbitrary exception handed up by a third-party library."""
        exc = _wrap_chain(FileNotFoundError(2, "missing"), 6)
        self.assertFalse(cdl._implicates_lock_dir(exc))

    def test_a_cyclic_cause_chain_terminates(self):
        """__cause__ can be set by hand, so a cycle is constructible. The
        bound is the only thing that terminates the walk - the chain never
        ends. Run it off-thread so an unbounded walk fails this test instead
        of hanging the suite.
        """
        a = portalocker.LockException("a")
        b = portalocker.LockException("b")
        a.__cause__ = b
        b.__cause__ = a
        out = []
        t = threading.Thread(target=lambda: out.append(cdl._implicates_lock_dir(a)),
                             daemon=True)
        t.start()
        t.join(timeout=5.0)
        self.assertFalse(t.is_alive(), "the cause-chain walk never terminated")
        self.assertEqual(out, [False])


class _EpisodeDrivingMixin:
    """Drives fail / recover episodes through one installed, flippable stub.

    Not a TestCase: the cap tests and the decay tests both need it, and
    subclassing one from the other would silently re-run its tests.
    """

    def install_switch(self):
        self.switch = _FaultSwitch()
        self.install_file_lock(acquire_error=self.switch)

    def _fail(self, n=1):
        self.switch.error = portalocker.LockException("timed out")
        for _ in range(n):
            with cdl.coaching_data_lock():
                pass

    def _succeed(self, n=1):
        self.switch.error = None
        for _ in range(n):
            with cdl.coaching_data_lock():
                pass

    def _cycle(self, n):
        """Drive n full fail-then-recover episodes."""
        for _ in range(n):
            self._fail()
            self._succeed()

    @staticmethod
    def _split(records):
        msgs = [r.getMessage() for r in records]
        return ([m for m in msgs if "DEGRADED to in-process" in m],
                [m for m in msgs if "RECOVERED" in m])


class TestEpisodeLoggingCap(_EpisodeDrivingMixin, _CombinedLockTestBase):
    """A transition-based suppressor bounds a STUCK lock but not a FLAPPING
    one: alternating fail / succeed opens a new episode every cycle and would
    emit a DEGRADED + RECOVERED pair each time, flooding the log at exactly
    the rate the suppression was added to prevent. `_MAX_EPISODES_LOGGED`
    caps it; the counters carry the signal past the cap."""

    def setUp(self):
        super().setUp()
        self.install_switch()

    def test_a_flapping_lock_logs_at_most_the_capped_number_of_episodes(self):
        cycles = cdl._MAX_EPISODES_LOGGED + 3
        with self.assertLogs(_LOGGER_NAME, level="WARNING") as cm:
            self._cycle(cycles)
        degraded, recovered = self._split(cm.records)
        self.assertEqual(len(degraded), cdl._MAX_EPISODES_LOGGED,
                         "a flapping lock logged past the episode cap")
        self.assertLessEqual(len(recovered), cdl._MAX_EPISODES_LOGGED)

    def test_the_episode_counter_keeps_counting_past_the_cap(self):
        cycles = cdl._MAX_EPISODES_LOGGED + 3
        self._cycle(cycles)
        stats = cdl.coaching_data_lock_stats()
        self.assertEqual(stats["degradation_episodes"], cycles,
                         "the cap silently stopped counting episodes too, so the "
                         "signal is lost once the log goes quiet")
        self.assertEqual(stats["file_lock_failures"], cycles)

    def test_a_suppressed_episode_never_emits_an_unpaired_recovered_line(self):
        """The bug the `_episode_logged` flag exists to prevent: capping only
        the DEGRADED half would leave RECOVERED lines appearing forever with
        nothing to pair them to."""
        self._cycle(cdl._MAX_EPISODES_LOGGED)  # exhaust the cap
        with self.assertNoLogs(_LOGGER_NAME, level="WARNING"):
            self.switch.error = portalocker.LockException("timed out")
            with cdl.coaching_data_lock():
                pass
        with self.assertNoLogs(_LOGGER_NAME, level="WARNING"):
            self.switch.error = None
            with cdl.coaching_data_lock():
                pass

    def test_the_last_logged_episode_still_gets_its_recovered_line(self):
        """The cap must not cost the pairing of the episodes it DOES log."""
        with self.assertLogs(_LOGGER_NAME, level="WARNING") as cm:
            self._cycle(cdl._MAX_EPISODES_LOGGED)
        degraded, recovered = self._split(cm.records)
        self.assertEqual(len(degraded), cdl._MAX_EPISODES_LOGGED)
        self.assertEqual(len(recovered), cdl._MAX_EPISODES_LOGGED,
                         "an episode within the cap lost its closing line")

    def test_the_cap_is_logging_only_and_never_gates_behaviour(self):
        """Same shape as TestSuppressionIsLoggingOnly, for the second
        suppressor. Past the cap the lock must still be ATTEMPTED, the body
        must still run, the failure must still be COUNTED, and the in-process
        lock must still be held and released."""
        self._cycle(cdl._MAX_EPISODES_LOGGED)
        del self.record[:]
        before = cdl.coaching_data_lock_stats()["file_lock_failures"]
        self.switch.error = portalocker.LockException("timed out")
        held_inside = []
        for _ in range(4):
            with cdl.coaching_data_lock():
                held_inside.append(cdl._LOCK.locked())
            self.assertFalse(cdl._LOCK.locked(),
                             "a capped acquire leaked the in-process lock")
        self.assertEqual(held_inside, [True] * 4,
                         "a capped acquire skipped the in-process lock")
        self.assertEqual(len([r for r in self.record if r[0] == "construct"]), 4,
                         "the cap stopped the file lock from being ATTEMPTED")
        self.assertEqual(len([r for r in self.record if r[0] == "acquire"]), 4)
        self.assertEqual(
            cdl.coaching_data_lock_stats()["file_lock_failures"], before + 4,
            "the cap stopped the failure from being COUNTED")


class TestExactDirectoryFallback(_CombinedLockTestBase):
    """GUARD 1 - the exact `is_dir()` confirmation behind the heuristic.

    `_implicates_lock_dir` walks `__cause__`, but portalocker's timeout
    branch re-raises a SAVED `LockException` (`if exception: raise exception`)
    which carries no `__cause__` at all. A directory-missing failure arriving
    that way looks file-only to the heuristic, so without the fallback the
    memo is never re-armed and the lock is permanently degraded - strictly
    worse than the extra syscalls the narrowing was avoiding.

    Every test below is built on that exact exception shape: a bare
    LockException with no chain, which is why each one first asserts the
    heuristic MISSES it. If the heuristic ever started catching it these
    tests would pass for the wrong reason.
    """

    def _unchained(self):
        exc = portalocker.LockException("timed out")
        self.assertIsNone(exc.__cause__)
        self.assertFalse(
            cdl._implicates_lock_dir(exc),
            "the heuristic caught this, so the fallback is not what is under test")
        return exc

    def _patch_is_dir_to_raise(self):
        real_is_dir = Path.is_dir
        target = str(self.lock_dir)

        def _spy(path_self, *args, **kwargs):
            if str(path_self) == target:
                raise OSError(5, "Input/output error")
            return real_is_dir(path_self, *args, **kwargs)

        self._patch(Path, "is_dir", _spy)

    def test_an_unchained_failure_with_the_directory_gone_rearms_the_memo(self):
        calls = self.record_mkdirs()
        with cdl.coaching_data_lock():
            pass
        self.assertEqual(len(calls), 1)
        self.assertTrue(cdl._lock_dir_ready)

        shutil.rmtree(self.lock_dir)
        self.install_file_lock(acquire_error=self._unchained())
        with cdl.coaching_data_lock():
            pass
        self.assertFalse(
            cdl._lock_dir_ready,
            "the heuristic missed it and nothing confirmed - the deleted lock "
            "directory would never be recreated")

        self.install_file_lock()
        with cdl.coaching_data_lock():
            pass
        self.assertEqual(len(calls), 2)
        self.assertTrue(self.lock_dir.is_dir())

    def test_an_unchained_failure_with_the_directory_present_does_not_rearm(self):
        """The pair that proves the fallback is EXACT and not always-true.

        Without this, a fallback hardcoded to True would look identical to a
        working one on the test above.
        """
        calls = self.record_mkdirs()
        with cdl.coaching_data_lock():
            pass
        self.assertEqual(len(calls), 1)

        self.install_file_lock(acquire_error=self._unchained())
        for _ in range(3):
            with cdl.coaching_data_lock():
                pass
        self.assertTrue(self.lock_dir.is_dir(), "the directory is still intact")
        self.assertTrue(
            cdl._lock_dir_ready,
            "a file-only failure re-armed the memo, so the mkdir syscall is back "
            "inside the critical section on every degraded acquire")

        self.install_file_lock()
        with cdl.coaching_data_lock():
            pass
        self.assertEqual(len(calls), 1)

    def test_a_stat_that_itself_fails_rearms_the_memo(self):
        """Failing to PROVE the directory is healthy must not be read as
        proof that it is. The conservative branch is the correct one: a
        needless mkdir costs a syscall, a missed re-arm costs the lock."""
        with cdl.coaching_data_lock():
            pass
        self.assertTrue(cdl._lock_dir_ready)

        self._patch_is_dir_to_raise()
        self.install_file_lock(acquire_error=self._unchained())
        with cdl.coaching_data_lock():
            pass
        self.assertFalse(
            cdl._lock_dir_ready,
            "an unreadable directory was treated as a healthy one")

    def test_the_fallback_costs_no_stat_on_a_successful_acquire(self):
        """It is one stat per FAILED acquire, never on the hot path."""
        seen = []
        real_is_dir = Path.is_dir
        target = str(self.lock_dir)

        def _spy(path_self, *args, **kwargs):
            if str(path_self) == target:
                seen.append(1)
            return real_is_dir(path_self, *args, **kwargs)

        self._patch(Path, "is_dir", _spy)
        for _ in range(5):
            with cdl.coaching_data_lock():
                pass
        self.assertEqual(seen, [], "the exact check ran on the success path")


class _FakeClock:
    """Stand-in for the module's `time` module.

    Exposes `monotonic()` and `time()` SEPARATELY and records which was
    read, so a test can drive the clock deterministically - no test in this
    file sleeps - and can also detect a module reading the wall clock where
    it should read the monotonic one. The two are moved independently
    because that divergence is the entire point of choosing monotonic.
    """

    def __init__(self, mono=1000.0, wall=1700000000.0):
        self._mono = float(mono)
        self._wall = float(wall)
        self.reads = []

    def monotonic(self):
        self.reads.append("monotonic")
        return self._mono

    def time(self):
        self.reads.append("time")
        return self._wall

    def advance(self, dt):
        """Ordinary passage of time - both clocks move together."""
        self._mono += dt
        self._wall += dt

    def advance_monotonic(self, dt):
        self._mono += dt

    def step_wall_clock(self, dt):
        """Move ONLY the wall clock. An NTP correction, a DST change and a
        VM resume all do this; none of them moves the monotonic clock."""
        self._wall += dt


class TestEpisodeLoggingRateFloor(_EpisodeDrivingMixin, _CombinedLockTestBase):
    """A burst allowance followed by a wall-clock rate floor.

    The cap alone re-created the RM-199 condition it was added to avoid: a
    long-lived RC went permanently silent after `_MAX_EPISODES_LOGGED`
    episodes, and `coaching_data_lock_stats()` has zero production callers,
    so the counters are not a substitute channel. An earlier fix counted
    consecutive successful ACQUIRES, which measures the wrong axis - the
    four holders take this lock on a poll cadence, so a streak of 50 is
    seconds rather than days. The floor is now elapsed TIME, which is
    correct in both directions.

    Every test here drives a patched clock. None sleeps.
    """

    def setUp(self):
        super().setUp()
        self.install_switch()
        self.clock = _FakeClock()
        self._patch(cdl, "time", self.clock)

    def _episodes(self, n):
        """n full fail-then-recover episodes at the current clock reading."""
        self._cycle(n)

    def _exhaust_the_burst(self):
        """Spend the burst allowance with the clock FROZEN, so nothing that
        follows can be attributed to the time floor."""
        self._episodes(cdl._MAX_EPISODES_LOGGED)

    # -- the burst allowance -------------------------------------------------

    def test_the_burst_allowance_logs_every_early_episode_with_the_clock_frozen(self):
        """A rapid-onset problem must be visible at once, not one line per
        half hour. The clock never moves here, so the floor cannot be what
        let these through."""
        with self.assertLogs(_LOGGER_NAME, level="WARNING") as cm:
            self._exhaust_the_burst()
        degraded, _ = self._split(cm.records)
        self.assertEqual(len(degraded), cdl._MAX_EPISODES_LOGGED)

    def test_past_the_burst_a_frozen_clock_stays_silent(self):
        self._exhaust_the_burst()
        with self.assertNoLogs(_LOGGER_NAME, level="WARNING"):
            self._episodes(4)

    # -- both sides of the floor boundary ------------------------------------

    def test_advancing_the_full_interval_reopens_logging(self):
        self._exhaust_the_burst()
        self.clock.advance(cdl._LOG_REOPEN_AFTER_S)
        with self.assertLogs(_LOGGER_NAME, level="WARNING") as cm:
            self._episodes(1)
        degraded, _ = self._split(cm.records)
        self.assertEqual(len(degraded), 1)

    def test_advancing_just_under_the_interval_does_not_reopen_logging(self):
        """The other side of the boundary. Without this, an always-open gate
        would pass the test above and look correct."""
        self._exhaust_the_burst()
        self.clock.advance(cdl._LOG_REOPEN_AFTER_S - 1.0)
        with self.assertNoLogs(_LOGGER_NAME, level="WARNING"):
            self._episodes(1)

    def test_a_reopen_grants_a_fresh_burst_not_a_single_line(self):
        """MEASURED, and it is NOT one line per interval.

        The floor branch sets `_episodes_logged_window = 1`, so the next
        `_MAX_EPISODES_LOGGED - 1` episodes fall back through the burst
        branch and are logged too. A re-open therefore costs a whole fresh
        burst, and the ceiling is `_MAX_EPISODES_LOGGED` lines per interval
        rather than one. That is still bounded, which is why this test pins
        it rather than calling it a defect - but it is pinned exactly, so a
        later change to `= _MAX_EPISODES_LOGGED` (one line per interval) or
        to `= 0` (one extra line per interval) both fail here.
        """
        self._exhaust_the_burst()
        self.clock.advance(cdl._LOG_REOPEN_AFTER_S)
        with self.assertLogs(_LOGGER_NAME, level="WARNING") as cm:
            self._episodes(cdl._MAX_EPISODES_LOGGED + 3)
        degraded, _ = self._split(cm.records)
        self.assertEqual(
            len(degraded), cdl._MAX_EPISODES_LOGGED,
            "a re-open did not grant exactly one fresh burst before going quiet")

    # -- the two properties the floor exists for -----------------------------

    def test_the_logging_rate_is_bounded_across_a_long_span(self):
        """Many episodes over a long simulated span must not flood."""
        interval = cdl._LOG_REOPEN_AFTER_S
        step = interval / 50.0
        cycles = 200
        with self.assertLogs(_LOGGER_NAME, level="WARNING") as cm:
            for _ in range(cycles):
                self.clock.advance(step)
                self._episodes(1)
        degraded, _ = self._split(cm.records)
        intervals = int((step * cycles) // interval)
        ceiling = cdl._MAX_EPISODES_LOGGED * (1 + intervals)
        self.assertLessEqual(len(degraded), ceiling,
                             "the logging rate is not bounded by the floor")
        self.assertLess(len(degraded), cycles, "nothing was suppressed at all")
        self.assertEqual(
            cdl.coaching_data_lock_stats()["degradation_episodes"], cycles)

    def test_a_much_later_outage_still_logs(self):
        """The RM-199 regression guard, and the whole reason the floor
        exists: a bare cap goes permanently silent, so a genuinely new
        outage on day three would never be seen."""
        self._exhaust_the_burst()
        with self.assertNoLogs(_LOGGER_NAME, level="WARNING"):
            self._episodes(1)
        self.clock.advance(86400.0)
        with self.assertLogs(_LOGGER_NAME, level="WARNING") as cm:
            self._episodes(1)
        degraded, _ = self._split(cm.records)
        self.assertEqual(len(degraded), 1,
                         "the module went permanently silent - RM-199 all over again")

    # -- the invariants a logging change must not break ----------------------

    def test_the_cumulative_episode_counter_is_never_zeroed_by_a_reopen(self):
        self._exhaust_the_burst()
        self.clock.advance(cdl._LOG_REOPEN_AFTER_S)
        self._episodes(3)
        self.clock.advance(cdl._LOG_REOPEN_AFTER_S)
        self._episodes(2)
        self.assertEqual(
            cdl.coaching_data_lock_stats()["degradation_episodes"],
            cdl._MAX_EPISODES_LOGGED + 5,
            "a re-open reset the cumulative counter, destroying the signal that "
            "is supposed to survive the quiet periods")

    def test_the_rate_floor_is_logging_only_and_never_gates_behaviour(self):
        self._exhaust_the_burst()
        del self.record[:]
        before = cdl.coaching_data_lock_stats()["file_lock_failures"]
        self.switch.error = portalocker.LockException("timed out")
        held_inside = []
        for _ in range(4):
            with cdl.coaching_data_lock():
                held_inside.append(cdl._LOCK.locked())
            self.assertFalse(cdl._LOCK.locked(),
                             "a silenced acquire leaked the in-process lock")
        self.assertEqual(held_inside, [True] * 4,
                         "a silenced acquire skipped the in-process lock")
        self.assertEqual(len([r for r in self.record if r[0] == "construct"]), 4,
                         "silence stopped the file lock from being ATTEMPTED")
        self.assertEqual(len([r for r in self.record if r[0] == "acquire"]), 4)
        self.assertEqual(
            cdl.coaching_data_lock_stats()["file_lock_failures"], before + 4,
            "silence stopped the failure from being COUNTED")

    # -- the clock itself ----------------------------------------------------

    def test_the_module_reads_the_monotonic_clock_not_the_wall_clock(self):
        """Direct, rather than inferred from behaviour: the recording clock
        reports which attribute was actually read."""
        del self.clock.reads[:]
        self._fail()
        self._succeed()
        self.assertEqual(self.clock.reads, ["monotonic"],
                         "the module read the wall clock")

    def test_a_forward_wall_clock_jump_does_not_reopen_logging(self):
        """The case that actually discriminates the two clocks.

        An NTP correction, a DST change or a VM resume steps the WALL clock
        forward while monotonic barely moves. Under a wall clock the last
        log would look a day old and the gate would re-open; under monotonic
        only a second has passed, so it must stay shut.
        """
        self._exhaust_the_burst()
        self.clock.step_wall_clock(86400.0)
        self.clock.advance_monotonic(1.0)
        with self.assertNoLogs(_LOGGER_NAME, level="WARNING"):
            self._episodes(1)

    def test_a_backward_clock_step_does_not_reopen_logging(self):
        """The other direction, pinned because the module's comment cites it.

        HONEST NOTE: this direction does not discriminate the two clocks. A
        BACKWARD step makes `now - last` negative, which suppresses under a
        wall clock as well - it is a forward jump that would wrongly re-open
        (see the test above). The property is still worth pinning; it is the
        rationale in the module comment that is stated backwards.
        """
        self._exhaust_the_burst()
        self.clock.step_wall_clock(-86400.0)
        self.clock.advance_monotonic(1.0)
        with self.assertNoLogs(_LOGGER_NAME, level="WARNING"):
            self._episodes(1)

    def test_the_first_ever_episode_logs_when_the_burst_allowance_is_zero(self):
        """Why the `_last_episode_logged_at is None` clause is load-bearing.

        With the shipped constants it is unreachable - reaching the elif
        means the window is full, which means something was logged, which
        set the timestamp. At `_MAX_EPISODES_LOGGED = 0` - a plausible
        tuning meaning "floor only, no burst" - the very first episode
        reaches the elif with no timestamp, and without the None guard the
        subtraction raises TypeError straight through the lock.
        """
        with mock.patch.object(cdl, "_MAX_EPISODES_LOGGED", 0):
            self.assertIsNone(cdl._last_episode_logged_at)
            with self.assertLogs(_LOGGER_NAME, level="WARNING") as cm:
                self._episodes(1)
            degraded, _ = self._split(cm.records)
            self.assertEqual(len(degraded), 1)

    def test_the_shipped_reopen_interval_is_positive(self):
        """Replaces a deleted test that compared two constants in different
        units. This one is a real property: a non-positive interval would
        make the floor always open and the cap inert."""
        self.assertIsInstance(cdl._LOG_REOPEN_AFTER_S, float)
        self.assertGreater(cdl._LOG_REOPEN_AFTER_S, 0)
        self.assertGreaterEqual(cdl._MAX_EPISODES_LOGGED, 0)


class TestLockDirEpochGuard(_CombinedLockTestBase):
    """GUARD 3 - an in-flight mkdir must not publish a stale memo.

    `_ensure_lock_dir` runs its mkdir OUTSIDE `_stats_lock`, because holding
    a lock across a filesystem syscall on an antivirus path is the thing this
    module exists to avoid. That opens a lost-update window: a concurrent
    `_note_file_lock_failure` can clear the memo while the mkdir is in
    flight, and the mkdir then sets it straight back to True - swallowing the
    re-arm and delaying recovery by a cycle.

    Driven deterministically rather than with threads: the concurrent re-arm
    is executed from inside the patched mkdir, which is exactly the instant
    the race needs it - after the epoch was read, before the memo is
    published. A threaded version would only hit that window by luck.
    """

    def test_a_concurrent_rearm_is_not_swallowed_by_an_in_flight_mkdir(self):
        real_mkdir = Path.mkdir
        target = str(self.lock_dir)
        fired = []

        def _mkdir_that_races(path_self, *args, **kwargs):
            result = real_mkdir(path_self, *args, **kwargs)
            if str(path_self) == target and not fired:
                fired.append(True)
                cdl._note_file_lock_failure(
                    "injected concurrent failure", FileNotFoundError(2, "gone"))
            return result

        self._patch(Path, "mkdir", _mkdir_that_races)
        self.assertFalse(cdl._lock_dir_ready)
        cdl._ensure_lock_dir()
        self.assertEqual(fired, [True], "the injected re-arm never ran")
        self.assertFalse(
            cdl._lock_dir_ready,
            "the in-flight mkdir published a stale memo over a concurrent "
            "re-arm, so the next acquire skips the mkdir and stays degraded")

    def test_an_uncontended_mkdir_publishes_the_memo(self):
        """The control. Without it the test above would pass for the trivial
        reason that the memo is never set at all."""
        self.assertFalse(cdl._lock_dir_ready)
        cdl._ensure_lock_dir()
        self.assertTrue(cdl._lock_dir_ready, "the memo was never published")
        self.assertTrue(self.lock_dir.is_dir())

    def test_a_file_only_failure_does_not_bump_the_epoch(self):
        """The epoch is the directory's version, not a general failure
        counter - bumping it on every failure would make any concurrent mkdir
        unable to ever publish."""
        with cdl.coaching_data_lock():
            pass
        before = cdl._dir_epoch
        self.install_file_lock(acquire_error=PermissionError(13, "Access is denied"))
        with cdl.coaching_data_lock():
            pass
        self.assertEqual(cdl._dir_epoch, before,
                         "a file-only failure bumped the directory epoch")

    def test_a_directory_failure_bumps_the_epoch(self):
        with cdl.coaching_data_lock():
            pass
        before = cdl._dir_epoch
        self.install_file_lock(
            acquire_error=FileNotFoundError(2, "No such file or directory"))
        with cdl.coaching_data_lock():
            pass
        self.assertEqual(cdl._dir_epoch, before + 1)


if __name__ == "__main__":
    unittest.main()
