"""RM-738 (DS :8860): a periodic liveness self-heal replaces the one-shot.

BEFORE: ``core.daemon_slayer_client.ensure_running`` ran ONCE, at dashboard
start (``dashboard/server.py`` start_dashboard, its only caller): one
``/health`` probe, one spawn of ``tools/start_daemon_slayer.py`` if nothing
answered. A DS that died or wedged later stayed down until RC itself
restarted, and every coach / dashboard DS call read the hole as ``None``.

AFTER: ``ensure_running`` starts (once per process) ``DsWatchdog``, modelled
on the RM-735 vision watchdog (``dashboard/_vision_watchdog.py``): a
rate-limited ``/health`` re-check that relaunches DS when it is down, backs
off after every spawn (no relaunch storm), never starts a second DS while the
port is held or a DS process is still booting (``HTTPServer`` binds with
SO_REUSEADDR, which on Windows lets a second process bind a held port), and
replaces a HUNG holder only when it is verifiably a DS process. Every side
effect is stubbed here; nothing in this file probes or spawns for real.
"""
from __future__ import annotations

import threading
import unittest
from unittest import mock

import core.daemon_slayer_client as dsc

OK, DOWN, HUNG = dsc.OK, dsc.DOWN, dsc.HUNG


class _Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


class _Rig:
    """Stubbed probe / port holder / DS-process scan / kill / launcher."""

    def __init__(self, *, state: str = OK, holder=None, booting=None,
                 is_ds: bool = True, kill_ok: bool = True,
                 released_after_kill: bool = True) -> None:
        self.state = state
        self.holder = holder
        self.booting = booting
        self.is_ds = is_ds
        self.kill_ok = kill_ok
        self.released_after_kill = released_after_kill
        self.spawns = 0
        self.kills: list[int] = []
        self.probes = 0
        self.spawn_error: BaseException | None = None
        self.clock = _Clock()

    def probe(self, port: int, timeout_s: float) -> str:
        self.probes += 1
        return self.state

    def find_holder(self, port: int):
        return self.holder

    def find_ds_process(self):
        return self.booting

    def is_ds_pid(self, pid: int) -> bool:
        return self.is_ds

    def kill(self, pid: int) -> bool:
        self.kills.append(pid)
        if self.kill_ok and self.released_after_kill:
            self.holder = None
        return self.kill_ok

    def spawn(self) -> int:
        self.spawns += 1
        if self.spawn_error is not None:
            raise self.spawn_error
        return 4242

    def watchdog(self, **kw) -> "dsc.DsWatchdog":
        kw.setdefault("grace_s", 120.0)
        kw.setdefault("max_grace_s", 1800.0)
        kw.setdefault("fail_threshold", 3)
        return dsc.DsWatchdog(
            probe=self.probe, find_holder=self.find_holder,
            find_ds_process=self.find_ds_process, is_ds=self.is_ds_pid,
            kill=self.kill, spawn=self.spawn, clock=self.clock,
            sleep=lambda s: None, **kw)


class DeadAliveAndNoStorm(unittest.TestCase):
    def test_alive_never_relaunches(self) -> None:
        rig = _Rig(state=OK, holder=777)
        wd = rig.watchdog()
        for _ in range(20):
            self.assertEqual(wd.tick(), "ok")
            rig.clock.t += 30
        self.assertEqual(rig.spawns, 0)
        self.assertEqual(rig.kills, [])

    def test_dead_relaunches_once(self) -> None:
        rig = _Rig(state=DOWN, holder=None)
        wd = rig.watchdog()
        self.assertEqual(wd.tick(), "spawned")
        self.assertEqual(rig.spawns, 1)

    def test_repeated_dead_within_the_backoff_is_not_a_storm(self) -> None:
        rig = _Rig(state=DOWN, holder=None)
        wd = rig.watchdog(grace_s=120.0)
        self.assertEqual(wd.tick(), "spawned")
        for _ in range(3):                       # 30, 60, 90 s later: still dead
            rig.clock.t += 30
            self.assertEqual(wd.tick(), "grace")
        self.assertEqual(rig.spawns, 1, "relaunched inside the back-off")
        rig.clock.t += 31                        # 121 s: the grace has ended
        self.assertEqual(wd.tick(), "spawned")
        self.assertEqual(rig.spawns, 2)
        # The back-off doubled: 239 s later is still inside it.
        rig.clock.t += 239
        self.assertEqual(wd.tick(), "grace")
        rig.clock.t += 2
        self.assertEqual(wd.tick(), "spawned")
        self.assertEqual(rig.spawns, 3)

    def test_the_backoff_is_capped(self) -> None:
        rig = _Rig(state=DOWN, holder=None)
        wd = rig.watchdog(grace_s=120.0, max_grace_s=300.0)
        for _ in range(6):
            self.assertEqual(wd.tick(), "spawned")
            rig.clock.t += 301
        self.assertEqual(rig.spawns, 6)

    def test_a_failing_launcher_still_backs_off(self) -> None:
        rig = _Rig(state=DOWN, holder=None)
        rig.spawn_error = OSError("launcher missing (test)")
        wd = rig.watchdog()
        self.assertEqual(wd.tick(), "spawned")
        rig.clock.t += 30
        self.assertEqual(wd.tick(), "grace")
        self.assertEqual(rig.spawns, 1)

    def test_answering_again_resets_the_backoff(self) -> None:
        rig = _Rig(state=DOWN, holder=None)
        wd = rig.watchdog(grace_s=120.0)
        wd.tick()
        rig.clock.t += 121
        wd.tick()                                # second spawn, grace now 240
        rig.state, rig.holder = OK, 777
        rig.clock.t += 30
        self.assertEqual(wd.tick(), "ok")
        rig.state, rig.holder = DOWN, None       # dies again later
        rig.clock.t += 600
        self.assertEqual(wd.tick(), "spawned")
        rig.clock.t += 121                       # back to the base 120 s grace
        self.assertEqual(wd.tick(), "spawned")
        self.assertEqual(rig.spawns, 4)


class NeverADuplicate(unittest.TestCase):
    def test_refused_while_the_port_is_held_does_not_spawn(self) -> None:
        # A full accept backlog answers a SYN with a reset: refused, but a
        # process still holds the port. A spawn there is a duplicate DS.
        rig = _Rig(state=DOWN, holder=777, is_ds=False)
        wd = rig.watchdog()
        for _ in range(10):
            wd.tick()
            rig.clock.t += 30
        self.assertEqual(rig.spawns, 0)
        self.assertEqual(rig.kills, [])

    def test_a_ds_still_booting_is_not_doubled(self) -> None:
        # The launcher loads the snapshot BEFORE it binds, so for a while a
        # DS process exists and nothing listens (a bounce, a logon start).
        rig = _Rig(state=DOWN, holder=None, booting=5150)
        wd = rig.watchdog()
        for _ in range(5):
            self.assertEqual(wd.tick(), "starting")
            rig.clock.t += 30
        self.assertEqual(rig.spawns, 0)
        self.assertEqual(rig.kills, [])

    def test_hung_ds_holder_is_replaced_only_after_the_threshold(self) -> None:
        rig = _Rig(state=HUNG, holder=777, is_ds=True)
        wd = rig.watchdog(fail_threshold=3)
        self.assertEqual(wd.tick(), "suspect")
        rig.clock.t += 30
        self.assertEqual(wd.tick(), "suspect")
        self.assertEqual((rig.spawns, rig.kills), (0, []))
        rig.clock.t += 30
        self.assertEqual(wd.tick(), "replaced")
        self.assertEqual(rig.kills, [777])
        self.assertEqual(rig.spawns, 1)
        rig.clock.t += 30                        # still hung: inside the grace
        self.assertEqual(wd.tick(), "grace")
        self.assertEqual(rig.spawns, 1)

    def test_one_good_probe_clears_the_hung_count(self) -> None:
        rig = _Rig(state=HUNG, holder=777)
        wd = rig.watchdog(fail_threshold=3)
        wd.tick()
        wd.tick()
        rig.state = OK
        wd.tick()
        rig.state = HUNG
        wd.tick()
        wd.tick()
        self.assertEqual(rig.kills, [])

    def test_a_hung_foreign_holder_is_left_alone(self) -> None:
        rig = _Rig(state=HUNG, holder=777, is_ds=False)
        wd = rig.watchdog(fail_threshold=2)
        wd.tick()
        self.assertEqual(wd.tick(), "foreign")
        self.assertEqual((rig.spawns, rig.kills), (0, []))

    def test_a_failed_kill_does_not_spawn(self) -> None:
        rig = _Rig(state=HUNG, holder=777, is_ds=True, kill_ok=False)
        wd = rig.watchdog(fail_threshold=1)
        self.assertEqual(wd.tick(), "kill-failed")
        self.assertEqual(rig.spawns, 0)

    def test_a_port_still_held_after_the_kill_waits_for_the_next_tick(self) -> None:
        rig = _Rig(state=HUNG, holder=777, is_ds=True,
                   released_after_kill=False)
        wd = rig.watchdog(fail_threshold=1)
        self.assertEqual(wd.tick(), "killed")
        self.assertEqual(rig.spawns, 0)
        rig.holder, rig.state = None, DOWN       # the port is released now
        rig.clock.t += 30
        self.assertEqual(wd.tick(), "spawned")
        self.assertEqual(rig.spawns, 1)

    def test_hung_with_no_visible_holder_is_never_spawned_over(self) -> None:
        # psutil missing or the lookup failed: the holder cannot be verified,
        # so a spawn could be a duplicate. Count, warn, never act.
        rig = _Rig(state=HUNG, holder=None)
        wd = rig.watchdog(fail_threshold=2)
        for _ in range(6):
            wd.tick()
            rig.clock.t += 30
        self.assertEqual((rig.spawns, rig.kills), (0, []))


class TheLoop(unittest.TestCase):
    def test_run_outlives_a_failing_tick(self) -> None:
        rig = _Rig()
        wd = rig.watchdog(interval_s=0.0)
        calls = []
        stop = threading.Event()

        def boom() -> str:
            calls.append(1)
            if len(calls) >= 3:
                stop.set()
            raise RuntimeError("tick failure (test)")

        with mock.patch.object(wd, "tick", boom):
            wd.run(stop)
        self.assertEqual(len(calls), 3)


class EnsureRunningStartsTheWatchdogOnce(unittest.TestCase):
    def test_ensure_running_starts_one_periodic_watchdog_per_process(self) -> None:
        made: list[object] = []
        ran = threading.Event()

        class FakeWatchdog:
            def __init__(self, *a, **kw) -> None:
                made.append(self)

            def run(self, stop: threading.Event) -> None:
                ran.set()

        with mock.patch.object(dsc, "_WATCHDOG", None), \
                mock.patch.object(dsc, "DsWatchdog", FakeWatchdog):
            self.assertIsNone(dsc.ensure_running())
            self.assertIsNone(dsc.ensure_running())
            self.assertTrue(ran.wait(5), "the watchdog thread never ran")
        self.assertEqual(len(made), 1, "a second call started a second loop")

    def test_the_watchdog_cadence_is_rate_limited(self) -> None:
        self.assertGreaterEqual(dsc.WATCHDOG_INTERVAL_S, 10.0)
        self.assertGreaterEqual(dsc.WATCHDOG_GRACE_S, 60.0)
        self.assertGreaterEqual(dsc.WATCHDOG_FAIL_THRESHOLD, 2)


class DsProcessMarkers(unittest.TestCase):
    def test_the_launcher_and_the_cli_serve_form_are_ds(self) -> None:
        for argv in (
            [r"C:\Py\pythonw.exe", r"C:\repo\tools\start_daemon_slayer.py"],
            ["python3", "tools/start_daemon_slayer.py"],
            ["python.exe", "-m", "agents.daemon_slayer", "serve"],
            ["python", "-m", "agents.daemon_slayer.cli", "serve", "--port", "8860"],
        ):
            self.assertTrue(dsc.is_ds_cmdline(argv), argv)

    def test_lookalikes_are_not_ds(self) -> None:
        for argv in (
            ["python", "-m", "pytest",
             "tests/phase7_polish/test_start_daemon_slayer_logging.py"],
            ["notepad.exe", r"C:\repo\tools\start_daemon_slayer.py"],
            ["python", "-m", "agents.daemon_slayer", "rank", "Jinx"],
            ["python", "-m", "agents.daemon_slayer", "serve", "--port", "9999"],
            ["python", "-m", "agents.daemon_slayer.cli", "serve", "--port=9999"],
            ["python", "main.py"],
            [],
        ):
            self.assertFalse(dsc.is_ds_cmdline(argv), argv)


if __name__ == "__main__":
    unittest.main()
