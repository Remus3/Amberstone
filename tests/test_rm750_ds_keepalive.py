"""RM-750 (DS :8860): a restarter that works while RC is down.

BEFORE: the only DS relauncher was RC's own ``DsWatchdog``
(``core/daemon_slayer_client.py``, started by ``dashboard/server.py``).
Task Scheduler RestartOnFailure on RC-DaemonSlayer is inert for a crash exit
(the kill's exit 1 was logged as "successfully completed" and nothing
relaunched within 161 s, LEDGER 1731), so while RC is down (crash loop,
tripped circuit breaker, operator stop) a crashed or wedged DS stayed down.

AFTER: ``tools/ds_keepalive.py``, hosted by its own SYSTEM scheduled task
RC-DSKeepalive (``tools/install_ds_keepalive_task.ps1``), runs the SAME
``DsWatchdog`` - liveness is a real ``GET /health`` round trip, never a port,
a pid or a task state (memory reference_ds_wedges_with_every_signal_green) -
but only while RC's watchdog is not live (RC's loop now leaves a heartbeat),
relaunches ONLY through the RC-DaemonSlayer task, never as a child, and idles
while ``ops/runtime/DS_KEEPALIVE_STOP`` exists (legion_off writes it).

Every side effect is stubbed: nothing here probes :8860, kills, spawns, or
reads or changes a scheduled task for real.
"""
from __future__ import annotations

import importlib
import io
import json
import os
import subprocess
import threading
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import pytest

import core.daemon_slayer_client as dsc

ROOT = Path(__file__).resolve().parent.parent
INSTALLER = ROOT / "tools" / "install_ds_keepalive_task.ps1"
LEGION_OFF = ROOT / "tools" / "legion_off.ps1"
LEGION_ON = ROOT / "tools" / "legion_on.ps1"
PS51 = Path(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")

OK, DOWN, HUNG = dsc.OK, dsc.DOWN, dsc.HUNG


def _ka():
    """Import lazily so a missing module fails each test, not the collection."""
    return importlib.import_module("tools.ds_keepalive")


class _Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


class _Rig:
    """Stubbed probe / holder / DS-process scan / kill / spawner."""

    def __init__(self, *, state: str = OK, holder=None, booting=None) -> None:
        self.state = state
        self.holder = holder
        self.booting = booting
        self.probes = 0
        self.kills: list[int] = []
        self.spawns = 0
        self.clock = _Clock()

    def probe(self, port: int, timeout_s: float) -> str:
        self.probes += 1
        return self.state

    def kill(self, pid: int) -> bool:
        self.kills.append(pid)
        self.holder = None
        return True

    def spawn(self) -> str:
        self.spawns += 1
        return "scheduled task RC-DaemonSlayer"

    def watchdog(self, **kw) -> dsc.DsWatchdog:
        return dsc.DsWatchdog(
            probe=self.probe, find_holder=lambda port: self.holder,
            find_ds_process=lambda: self.booting, is_ds=lambda pid: True,
            kill=self.kill, spawn=self.spawn, clock=self.clock,
            sleep=lambda s: None, **kw)


# -- RC's watchdog leaves a heartbeat -------------------------------------------


class RcWatchdogHeartbeat(unittest.TestCase):
    def test_run_leaves_a_heartbeat_before_every_tick(self) -> None:
        order: list[str] = []
        stop = threading.Event()
        wd = _Rig().watchdog(interval_s=0.0,
                             heartbeat=lambda: order.append("beat"))

        def tick() -> str:
            order.append("tick")
            if order.count("tick") >= 3:
                stop.set()
            return "ok"

        with mock.patch.object(wd, "tick", tick):
            wd.run(stop)
        self.assertEqual(order, ["beat", "tick"] * 3)

    def test_a_failing_heartbeat_never_stops_the_loop(self) -> None:
        ticks: list[int] = []
        stop = threading.Event()

        def boom() -> None:
            raise OSError("disk full (test)")

        wd = _Rig().watchdog(interval_s=0.0, heartbeat=boom)

        def tick() -> str:
            ticks.append(1)
            if len(ticks) >= 3:
                stop.set()
            return "ok"

        with mock.patch.object(wd, "tick", tick):
            wd.run(stop)
        self.assertEqual(len(ticks), 3)

    def test_no_heartbeat_by_default(self) -> None:
        # The keepalive's own watchdog must not write RC's heartbeat.
        self.assertIsNone(_Rig().watchdog()._heartbeat)

    def test_ensure_running_wires_the_rc_heartbeat(self) -> None:
        seen: list[dict] = []
        ran = threading.Event()

        class FakeWatchdog:
            def __init__(self, *a, **kw) -> None:
                seen.append(kw)

            def run(self, stop: threading.Event) -> None:
                ran.set()

        with mock.patch.object(dsc, "_WATCHDOG", None), \
                mock.patch.object(dsc, "DsWatchdog", FakeWatchdog):
            dsc.ensure_running()
            self.assertTrue(ran.wait(5), "the watchdog thread never ran")
        self.assertEqual(len(seen), 1)
        self.assertIs(seen[0].get("heartbeat"), dsc.write_rc_watchdog_heartbeat)


class HeartbeatContract(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "runtime" / "ds_watchdog_rc.json"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _live(self, now: float, pid_alive=lambda pid: True) -> bool:
        return dsc.rc_watchdog_live(self.path, now=lambda: now,
                                    pid_alive=pid_alive)

    def test_round_trip_is_live(self) -> None:
        dsc.write_rc_watchdog_heartbeat(self.path, now=lambda: 5000.0)
        doc = json.loads(self.path.read_text(encoding="ascii"))
        self.assertEqual(doc["owner"], "rc")
        self.assertEqual(doc["pid"], os.getpid())
        self.assertEqual(doc["updated"], 5000.0)
        self.assertTrue(self._live(5010.0))

    def test_a_stale_heartbeat_is_not_live(self) -> None:
        dsc.write_rc_watchdog_heartbeat(self.path, now=lambda: 5000.0)
        self.assertTrue(self._live(5000.0 + dsc.RC_HEARTBEAT_MAX_AGE_S - 1))
        self.assertFalse(self._live(5000.0 + dsc.RC_HEARTBEAT_MAX_AGE_S + 1))

    def test_a_dead_rc_pid_is_not_live_at_once(self) -> None:
        # RC crashed: no need to wait out the staleness window.
        dsc.write_rc_watchdog_heartbeat(self.path, now=lambda: 5000.0)
        self.assertFalse(self._live(5001.0, pid_alive=lambda pid: False))

    def test_a_far_future_heartbeat_is_not_live(self) -> None:
        dsc.write_rc_watchdog_heartbeat(self.path, now=lambda: 9000.0)
        self.assertFalse(self._live(9000.0 - dsc.RC_HEARTBEAT_MAX_AGE_S - 1))

    def test_missing_or_malformed_heartbeat_is_not_live(self) -> None:
        self.assertFalse(self._live(5000.0))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for raw in (b"", b"{not json", b"[1, 2]", b'{"pid": 1}',
                    b'{"pid": "x", "updated": 5000}',
                    b'{"pid": 1, "updated": "soon"}'):
            self.path.write_bytes(raw)
            self.assertFalse(self._live(5000.0), raw)

    def test_the_write_never_raises(self) -> None:
        blocker = Path(self._tmp.name) / "a_file"
        blocker.write_bytes(b"x")
        dsc.write_rc_watchdog_heartbeat(blocker / "under_a_file.json")

    def test_the_max_age_outlasts_the_slowest_rc_tick(self) -> None:
        # One RC loop = the interval + its slowest tick: probe timeout,
        # taskkill (15 s cap in dashboard/_vision_watchdog.kill_pid), the
        # port-release wait, then schtasks /Run and /Query.
        slowest_gap = (dsc.WATCHDOG_INTERVAL_S + dsc.WATCHDOG_TIMEOUT_S + 15.0
                       + dsc.WATCHDOG_RELEASE_WAIT_S
                       + 2 * dsc._SCHTASKS_TIMEOUT_S)
        self.assertGreater(dsc.RC_HEARTBEAT_MAX_AGE_S, slowest_gap)

    def test_the_live_heartbeat_sits_in_the_gitignored_runtime_dir(self) -> None:
        self.assertEqual(dsc.RC_WATCHDOG_HEARTBEAT,
                         ROOT / "ops" / "runtime" / "ds_watchdog_rc.json")


# -- the keepalive relaunches only through the task -----------------------------


class TaskOnlyRelaunch(unittest.TestCase):
    def test_it_runs_the_owner_task(self) -> None:
        calls: list[tuple] = []

        def schtasks(*args: str) -> int:
            calls.append(args)
            return 0

        with mock.patch.object(dsc, "_schtasks", schtasks), \
                mock.patch.object(dsc, "_spawn_child",
                                  side_effect=AssertionError("child")):
            route = dsc.spawn_ds_task_only()
        self.assertEqual(calls, [("/Run", "/TN", dsc.DS_TASK_NAME)])
        self.assertIn(dsc.DS_TASK_NAME, route)

    def test_a_refused_or_unregistered_task_raises_and_never_starts_a_child(self) -> None:
        for rc in (1, 2):
            with mock.patch.object(dsc, "_schtasks", return_value=rc), \
                    mock.patch.object(dsc, "_spawn_child",
                                      side_effect=AssertionError("child")):
                with self.assertRaises(RuntimeError):
                    dsc.spawn_ds_task_only()

    def test_no_schtasks_raises_and_never_starts_a_child(self) -> None:
        with mock.patch.object(dsc, "_schtasks", side_effect=OSError("none")), \
                mock.patch.object(dsc, "_spawn_child",
                                  side_effect=AssertionError("child")):
            with self.assertRaises(OSError):
                dsc.spawn_ds_task_only()


# -- the keepalive loop ---------------------------------------------------------


class KeepaliveStep(unittest.TestCase):
    def _keepalive(self, rig: _Rig, *, rc_live, stopped=lambda: False):
        made: list[dsc.DsWatchdog] = []

        def make() -> dsc.DsWatchdog:
            wd = rig.watchdog()
            made.append(wd)
            return wd

        ka = _ka().DsKeepalive(rc_live=rc_live, stopped=stopped,
                               make_watchdog=make)
        return ka, made

    def test_rc_live_defers_without_probing(self) -> None:
        rig = _Rig(state=DOWN)
        ka, made = self._keepalive(rig, rc_live=lambda: True)
        for _ in range(3):
            self.assertEqual(ka.step(), "deferred")
        self.assertEqual((rig.probes, rig.spawns, made), (0, 0, []))

    def test_rc_down_relaunches_a_dead_ds(self) -> None:
        rig = _Rig(state=DOWN)
        ka, made = self._keepalive(rig, rc_live=lambda: False)
        self.assertEqual(ka.step(), "spawned")
        self.assertEqual(rig.spawns, 1)
        self.assertEqual(ka.step(), "grace", "a relaunch storm")
        self.assertEqual(len(made), 1)

    def test_rc_down_replaces_a_wedged_ds_that_holds_the_port(self) -> None:
        # The wedge memory: task Running, port LISTEN, pid alive - only the
        # /health round trip says HUNG. The keepalive must act on that.
        rig = _Rig(state=HUNG, holder=4321)
        ka, _ = self._keepalive(rig, rc_live=lambda: False)
        got = [ka.step() for _ in range(3)]
        self.assertEqual(got, ["suspect", "suspect", "replaced"])
        self.assertEqual((rig.kills, rig.spawns), ([4321], 1))

    def test_a_healthy_ds_is_left_alone(self) -> None:
        rig = _Rig(state=OK, holder=4321)
        ka, _ = self._keepalive(rig, rc_live=lambda: False)
        for _ in range(5):
            self.assertEqual(ka.step(), "ok")
        self.assertEqual((rig.kills, rig.spawns), ([], 0))

    def test_rc_back_stands_down_and_a_later_takeover_starts_clean(self) -> None:
        rig = _Rig(state=HUNG, holder=4321)
        live = {"rc": False}
        ka, made = self._keepalive(rig, rc_live=lambda: live["rc"])
        self.assertEqual([ka.step(), ka.step()], ["suspect", "suspect"])
        live["rc"] = True
        self.assertEqual(ka.step(), "deferred")
        live["rc"] = False
        # Two suspects were counted before RC came back; a carried count
        # would kill on this tick. A fresh watchdog counts from zero.
        self.assertEqual(ka.step(), "suspect")
        self.assertEqual(rig.kills, [])
        self.assertEqual(len(made), 2)
        self.assertIsNot(made[0], made[1])

    def test_the_stop_flag_idles_even_while_rc_is_down(self) -> None:
        rig = _Rig(state=DOWN)
        ka, made = self._keepalive(rig, rc_live=lambda: False,
                                   stopped=lambda: True)
        for _ in range(3):
            self.assertEqual(ka.step(), "stopped")
        self.assertEqual((rig.probes, rig.spawns, made), (0, 0, []))

    def test_run_outlives_a_failing_step(self) -> None:
        ka = _ka().DsKeepalive(rc_live=lambda: True, stopped=lambda: False,
                               make_watchdog=lambda: None)
        calls: list[int] = []
        stop = threading.Event()

        def boom() -> str:
            calls.append(1)
            if len(calls) >= 3:
                stop.set()
            raise RuntimeError("step failure (test)")

        with mock.patch.object(ka, "step", boom):
            ka.run(stop, interval_s=0.0)
        self.assertEqual(len(calls), 3)


class KeepaliveDefaults(unittest.TestCase):
    def test_the_default_watchdog_relaunches_only_through_the_task(self) -> None:
        wd = _ka().make_keepalive_watchdog()
        self.assertIsInstance(wd, dsc.DsWatchdog)
        self.assertIs(wd._spawn, dsc.spawn_ds_task_only)
        self.assertIsNone(wd._heartbeat)

    def test_the_default_watchdog_probes_a_real_health_round_trip(self) -> None:
        wd = _ka().make_keepalive_watchdog()
        self.assertIs(wd._probe, dsc.probe_ds_health)
        self.assertEqual(wd.port, dsc.DEFAULT_PORT)

    def test_the_defaults_read_rc_heartbeat_and_the_runtime_stop_flag(self) -> None:
        ka = _ka()
        self.assertEqual(ka.STOP_FLAG, ROOT / "ops" / "runtime" / "DS_KEEPALIVE_STOP")
        k = ka.DsKeepalive()
        self.assertIs(k._rc_live, dsc.rc_watchdog_live)
        self.assertIs(k._make_watchdog, ka.make_keepalive_watchdog)

    def test_the_stop_flag_check_reads_the_flag_file(self) -> None:
        import tempfile
        ka = _ka()
        with tempfile.TemporaryDirectory() as tmp:
            flag = Path(tmp) / "DS_KEEPALIVE_STOP"
            self.assertFalse(ka.stop_flag_present(flag))
            flag.write_bytes(b"legion_off")
            self.assertTrue(ka.stop_flag_present(flag))

    def test_status_reads_and_acts_on_nothing(self) -> None:
        ka = _ka()
        out = io.StringIO()
        with mock.patch.object(dsc, "probe_ds_health", return_value=DOWN), \
                mock.patch.object(dsc, "rc_watchdog_live", return_value=False), \
                mock.patch.object(ka, "stop_flag_present", return_value=False), \
                mock.patch.object(ka.DsKeepalive, "run",
                                  side_effect=AssertionError("ran the loop")), \
                mock.patch.object(dsc, "_schtasks",
                                  side_effect=AssertionError("ran schtasks")), \
                redirect_stdout(out):
            self.assertEqual(ka.main(["--status"]), 0)
        doc = json.loads(out.getvalue())
        self.assertEqual(doc, {"health": DOWN, "rc_watchdog_live": False,
                               "stop_flag": False})


# -- rc_facts reads the keepalive as a long-lived service ----------------------


def test_rc_facts_reads_the_keepalive_as_a_service() -> None:
    import tools.rc_facts as rc_facts
    assert "RC-DSKeepalive" in rc_facts.LONG_LIVED_SERVICE_TASKS
    verdict, _detail = rc_facts.classify_task_result(
        "RC-DSKeepalive", "Running", rc_facts.TASK_RESULT_RUNNING,
        last_run_age_s=3600.0,
    )
    assert verdict == rc_facts.VERDICT_OK


# -- the installer and the legion on/off hold -----------------------------------


def _code_lines(path: Path) -> list[str]:
    return [ln.strip() for ln in path.read_text(encoding="ascii").splitlines()
            if ln.strip() and not ln.strip().startswith("#")]


@pytest.mark.parametrize("path", [INSTALLER, LEGION_OFF, LEGION_ON],
                         ids=lambda p: p.name)
def test_touched_ps1_is_ascii_lf(path: Path) -> None:
    raw = path.read_bytes()
    assert all(b < 128 for b in raw), f"{path.name} is not 7-bit ASCII"
    assert b"\r" not in raw, f"{path.name} carries CR bytes"


def test_installer_registers_the_self_healing_service_shape() -> None:
    code = "\n".join(_code_lines(INSTALLER))
    for needle in ("'RC-DSKeepalive'", "tools\\ds_keepalive.py", "pythonw.exe",
                   "-AtStartup", "-RepetitionInterval (New-TimeSpan -Minutes 1)",
                   ".Repetition.StopAtDurationEnd = $false",
                   "-UserId 'SYSTEM'", "-MultipleInstances IgnoreNew",
                   "-ExecutionTimeLimit ([TimeSpan]::Zero)",
                   "Register-ScheduledTask", "Get-ScheduledTaskInfo"):
        assert needle in code, f"installer lacks {needle!r}"


def test_installer_never_touches_the_ds_owner_task() -> None:
    for line in _code_lines(INSTALLER):
        assert "RC-DaemonSlayer" not in line, line
    code = "\n".join(_code_lines(INSTALLER))
    for verb in ("schtasks", "Start-ScheduledTask", "Stop-ScheduledTask",
                 "Disable-ScheduledTask", "Unregister-ScheduledTask",
                 "Stop-Process", "taskkill"):
        assert verb not in code, f"installer runs {verb}"


def test_legion_off_holds_the_keepalive_before_the_kill_sweep() -> None:
    code = _code_lines(LEGION_OFF)
    flag_at = next(i for i, ln in enumerate(code) if "DS_KEEPALIVE_STOP" in ln)
    sweep_at = next(i for i, ln in enumerate(code) if "taskkill.exe /F /PID" in ln)
    assert flag_at < sweep_at, "the flag must land before DS is killed"
    assert any("Set-Content" in ln and "$dsStop" in ln for ln in code)


def test_legion_on_releases_the_keepalive_hold() -> None:
    code = _code_lines(LEGION_ON)
    assert any("DS_KEEPALIVE_STOP" in ln for ln in code)
    assert any("Remove-Item" in ln and "$dsStop" in ln for ln in code)


@pytest.mark.parametrize("path", [INSTALLER, LEGION_OFF, LEGION_ON],
                         ids=lambda p: p.name)
def test_touched_ps1_parses_under_windows_powershell_51(path: Path) -> None:
    if not PS51.is_file():
        pytest.skip("Windows PowerShell 5.1 not available on this host")
    command = (
        "$e = $null; "
        f"[void][System.Management.Automation.Language.Parser]::ParseFile('{path}', [ref]$null, [ref]$e); "
        "Write-Output ('ERRORS=' + $e.Count)"
    )
    proc = subprocess.run([str(PS51), "-NoProfile", "-Command", command],
                          capture_output=True, text=True, timeout=90,
                          creationflags=0x08000000 if os.name == "nt" else 0)
    assert "ERRORS=0" in proc.stdout, f"{proc.stdout}\n{proc.stderr}"
