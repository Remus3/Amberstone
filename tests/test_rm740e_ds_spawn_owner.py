"""RM-740 (e): who owns the Daemon Slayer process after a watchdog relaunch.

BEFORE: ``core.daemon_slayer_client.spawn_ds`` - the ``DsWatchdog`` relaunch
path - always ``Popen``-ed ``tools/start_daemon_slayer.py`` as a CHILD of the
RC process. The session 110 live re-probe found DS running that way, with the
RC-DaemonSlayer scheduled task ``Ready``: the task (boot trigger, SYSTEM,
restart-on-failure, MultipleInstancesPolicy IgnoreNew) no longer owned DS,
and the child sat inside the RC-Supervisor task's job object instead.

AFTER (decision recorded in BACKLOG RM-740 (e) and LEDGER 1722): the
relaunch goes THROUGH the task (``schtasks /Run /TN RC-DaemonSlayer``), the
same route ``ops/rc_supervisor.py`` ``_default_restarter`` takes for its own
Phase 3 task, so the task stays the single owner and IgnoreNew de-duplicates
the watchdog against the task's own restart-on-failure. A direct child is the
fallback ONLY where no such task is registered (a dev box, a fresh clone, a
non-Windows host). A task that exists but refuses ``/Run`` (still running
after a kill, disabled) raises instead of spawning a second engine beside it;
``DsWatchdog._respawn`` logs it and retries after the grace.

Every subprocess is stubbed here; nothing in this file runs schtasks or
starts a process for real.
"""
from __future__ import annotations

import os
import subprocess
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

import pytest

import core.daemon_slayer_client as dsc
from tests._module_view import bind_subprocess

CREATE_NO_WINDOW = 0x08000000


class NoWindowFlag(unittest.TestCase):
    """The flag value itself: CREATE_NO_WINDOW on Windows, 0 elsewhere.

    The route tests below assert that spawn_ds passes exactly ``dsc._NO_WINDOW``
    (so a stray DETACHED_PROCESS bit reds them on every OS); this class pins
    what that constant is, per OS. CI's ubuntu runner has no CREATE_NO_WINDOW,
    and the module deliberately uses 0 there (session 115 CI red on 687920398).
    """

    @unittest.skipUnless(os.name == "nt", "CREATE_NO_WINDOW is Windows-only")
    def test_windows_flag_is_create_no_window_alone(self):
        self.assertEqual(dsc._NO_WINDOW, CREATE_NO_WINDOW)

    @unittest.skipIf(os.name == "nt", "non-Windows hosts pass no creation flags")
    def test_non_windows_flag_is_zero(self):
        self.assertEqual(dsc._NO_WINDOW, 0)


class _Schtasks:
    """Fake ``subprocess.run`` for schtasks: per-verb exit codes, records argv."""

    def __init__(self, run_rc: int = 0, query_rc: int = 0,
                 run_error: BaseException | None = None) -> None:
        self.run_rc = run_rc
        self.query_rc = query_rc
        self.run_error = run_error
        self.calls: list[tuple[list, dict]] = []

    def __call__(self, argv, **kw):
        self.calls.append((list(argv), kw))
        if argv[1] == "/Run":
            if self.run_error is not None:
                raise self.run_error
            return SimpleNamespace(returncode=self.run_rc, stdout=b"", stderr=b"")
        if argv[1] == "/Query":
            return SimpleNamespace(returncode=self.query_rc, stdout=b"", stderr=b"")
        raise AssertionError(f"unexpected schtasks verb {argv!r}")


class _Popen:
    def __init__(self) -> None:
        self.calls: list[tuple[list, dict]] = []

    def __call__(self, argv, **kw):
        self.calls.append((list(argv), kw))
        return SimpleNamespace(pid=31337)


class SpawnDsRoute(unittest.TestCase):
    def _spawn(self, sched: _Schtasks, *, use_task: bool = True):
        popen = _Popen()
        with mock.patch.object(dsc, "_USE_TASK", use_task, create=True), \
                pytest.MonkeyPatch.context() as mp:
            # dsc's own subprocess name only (RM-801, tests/_module_view.py).
            bind_subprocess(mp, dsc, run=sched, Popen=popen)
            try:
                result = dsc.spawn_ds()
                error = None
            except Exception as exc:  # noqa: BLE001 - the route under test
                result, error = None, exc
        return result, error, popen

    def test_relaunch_runs_the_scheduled_task_and_starts_no_child(self):
        sched = _Schtasks(run_rc=0)
        result, error, popen = self._spawn(sched)
        self.assertIsNone(error)
        self.assertEqual(popen.calls, [],
                         "a relaunch with the task registered must not Popen a "
                         "DS child of RC - the task owns DS (RM-740 (e))")
        self.assertEqual(len(sched.calls), 1)
        argv, kw = sched.calls[0]
        self.assertEqual(argv, ["schtasks", "/Run", "/TN", "RC-DaemonSlayer"])
        self.assertEqual(kw.get("creationflags"), dsc._NO_WINDOW)
        self.assertIsNotNone(kw.get("timeout"), "schtasks must be bounded")
        self.assertIn("RC-DaemonSlayer", str(result))

    def test_task_name_is_the_registered_ds_task(self):
        self.assertEqual(dsc.DS_TASK_NAME, "RC-DaemonSlayer")

    def test_unregistered_task_falls_back_to_a_windowless_child(self):
        sched = _Schtasks(run_rc=1, query_rc=1)
        result, error, popen = self._spawn(sched)
        self.assertIsNone(error)
        self.assertEqual([c[0][1] for c in sched.calls], ["/Run", "/Query"])
        self.assertEqual(len(popen.calls), 1)
        argv, kw = popen.calls[0]
        self.assertEqual(argv, [sys.executable, str(dsc._LAUNCHER)])
        # CREATE_NO_WINDOW alone: DETACHED_PROCESS (0x8) is the silent no-op
        # worker class, so the flags are pinned exactly (the per-OS value of
        # dsc._NO_WINDOW is pinned by NoWindowFlag above).
        self.assertEqual(kw.get("creationflags"), dsc._NO_WINDOW)
        self.assertEqual(kw.get("cwd"), str(dsc._LAUNCHER.parent.parent))
        self.assertIs(kw.get("stdout"), subprocess.DEVNULL)
        self.assertIs(kw.get("stderr"), subprocess.DEVNULL)
        self.assertIn("31337", str(result))

    def test_registered_task_that_refuses_run_raises_and_spawns_no_child(self):
        # IgnoreNew refuses /Run while the killed instance is still exiting;
        # a child here would boot beside the task's own restart-on-failure.
        sched = _Schtasks(run_rc=1, query_rc=0)
        result, error, popen = self._spawn(sched)
        self.assertIsInstance(error, RuntimeError)
        self.assertEqual(popen.calls, [])

    def test_no_schtasks_binary_falls_back_to_a_child(self):
        sched = _Schtasks(run_error=FileNotFoundError("schtasks"))
        result, error, popen = self._spawn(sched)
        self.assertIsNone(error)
        self.assertEqual(len(popen.calls), 1)

    def test_a_schtasks_timeout_raises_and_spawns_no_child(self):
        sched = _Schtasks(run_error=subprocess.TimeoutExpired("schtasks", 15))
        result, error, popen = self._spawn(sched)
        self.assertIsInstance(error, subprocess.TimeoutExpired)
        self.assertEqual(popen.calls, [])

    def test_non_windows_host_spawns_the_child_without_schtasks(self):
        sched = _Schtasks()
        result, error, popen = self._spawn(sched, use_task=False)
        self.assertIsNone(error)
        self.assertEqual(sched.calls, [])
        self.assertEqual(len(popen.calls), 1)


class WatchdogUsesTheTaskRoute(unittest.TestCase):
    def test_default_spawn_is_spawn_ds(self):
        wd = dsc.DsWatchdog()
        self.assertIs(wd._spawn, dsc.spawn_ds)

    def test_not_running_tick_relaunches_through_the_task(self):
        sched, popen = _Schtasks(run_rc=0), _Popen()
        wd = dsc.DsWatchdog(probe=lambda port, t: dsc.DOWN,
                            find_holder=lambda port: None,
                            find_ds_process=lambda: None,
                            clock=lambda: 1000.0, sleep=lambda s: None)
        with mock.patch.object(dsc, "_USE_TASK", True, create=True), \
                pytest.MonkeyPatch.context() as mp, \
                self.assertLogs("rc.core.daemon_slayer_client", "WARNING") as logs:
            bind_subprocess(mp, dsc, run=sched, Popen=popen)
            self.assertEqual(wd.tick(), "spawned")
        self.assertEqual([c[0][:2] for c in sched.calls], [["schtasks", "/Run"]])
        self.assertEqual(popen.calls, [])
        self.assertTrue(any("RC-DaemonSlayer" in line for line in logs.output),
                        logs.output)

    def test_a_refused_task_run_is_logged_and_backs_off(self):
        sched, popen = _Schtasks(run_rc=1, query_rc=0), _Popen()
        wd = dsc.DsWatchdog(probe=lambda port, t: dsc.DOWN,
                            find_holder=lambda port: None,
                            find_ds_process=lambda: None,
                            clock=lambda: 1000.0, sleep=lambda s: None)
        with mock.patch.object(dsc, "_USE_TASK", True, create=True), \
                pytest.MonkeyPatch.context() as mp, \
                self.assertLogs("rc.core.daemon_slayer_client", "WARNING") as logs:
            bind_subprocess(mp, dsc, run=sched, Popen=popen)
            self.assertEqual(wd.tick(), "spawned")
            self.assertEqual(wd.tick(), "grace")
        self.assertEqual(popen.calls, [])
        self.assertTrue(any("relaunch failed" in line for line in logs.output),
                        logs.output)


if __name__ == "__main__":
    unittest.main()
