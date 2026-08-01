"""Unit tests for ops/rc_supervisor.py:_Phase3Watcher - the subordinate
watch that detects Phase 3 supervisor death / heartbeat staleness and
re-launches the RC-Phase3-Supervisor scheduled task.

Watcher is dependency-injected with stub clock / pid-checker / restarter,
so no Phase 3 supervisor needs to be running. Lockfile is a temp file the
test owns. Per-test breaker state file lives under tmp_path.
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock
from unittest.mock import MagicMock

_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from ops import rc_supervisor as rc_sup  # noqa: E402
from ops.rc_supervisor import _Phase3Watcher  # noqa: E402


def _iso_utc(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _write_lockfile(path: Path, pid: int, hb_dt: datetime, host: str = "TEST-HOST") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "pid": pid,
        "heartbeat_at": _iso_utc(hb_dt),
        "host": host,
    }), encoding="utf-8")


def _write_lockfile_started(path: Path, pid: int, hb_dt: datetime,
                            started_dt: datetime, host: str = "TEST-HOST") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "pid": pid,
        "started_at": _iso_utc(started_dt),
        "heartbeat_at": _iso_utc(hb_dt),
        "host": host,
    }), encoding="utf-8")


def _make_code_file(root: Path, rel: str, mtime_epoch: float) -> Path:
    """Create a watched import-chain file with a controlled mtime."""
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("# test\n", encoding="utf-8")
    os.utime(p, (mtime_epoch, mtime_epoch))
    return p


class _FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _build_watcher(tmp_dir: Path, *, restarter=None, pid_alive=None, clock=None):
    """Common watcher fixture. Returns (watcher, lockfile_path, restarter_mock, clock)."""
    lockfile = tmp_dir / "lockfile"
    budget_state = tmp_dir / "phase3_breaker_state.json"
    restarter_mock = restarter if restarter is not None else MagicMock(return_value=True)
    pid_alive_mock = pid_alive if pid_alive is not None else (lambda pid: True)
    clk = clock if clock is not None else _FakeClock()
    log_calls = []
    watcher = _Phase3Watcher(
        project_root=tmp_dir,
        runtime_dir=tmp_dir,
        log_fn=log_calls.append,
        lockfile_path=lockfile,
        budget_state_file=budget_state,
        restarter=restarter_mock,
        pid_alive_fn=pid_alive_mock,
        clock=clk,
    )
    return watcher, lockfile, restarter_mock, clk, log_calls


class LockfileReadingTests(unittest.TestCase):
    def test_missing_lockfile_triggers_restart(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            w, _lf, restarter, _clk, _logs = _build_watcher(Path(td))
            r = w.check()
        self.assertEqual(r["state"], "restarting")
        self.assertEqual(r["trigger"], "missing_lockfile")
        self.assertTrue(r["acted"])
        # No lockfile -> pid 0 -> the watcher passes None as the stale pid.
        restarter.assert_called_once_with("RC-Phase3-Supervisor", None)

    def test_malformed_lockfile_treated_as_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            w, lf, restarter, _clk, _logs = _build_watcher(Path(td))
            lf.write_text("not-json{", encoding="utf-8")
            r = w.check()
        self.assertEqual(r["trigger"], "missing_lockfile")
        self.assertTrue(r["acted"])

    def test_lockfile_without_heartbeat_field_treated_as_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            w, lf, restarter, _clk, _logs = _build_watcher(Path(td))
            lf.write_text(json.dumps({"pid": 1234, "host": "X"}), encoding="utf-8")
            r = w.check()
        self.assertEqual(r["trigger"], "missing_lockfile")
        self.assertTrue(r["acted"])


class HealthyPathTests(unittest.TestCase):
    def test_fresh_heartbeat_and_alive_pid_no_restart(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            w, lf, restarter, _clk, _logs = _build_watcher(Path(td))
            _write_lockfile(lf, 9999, datetime.now(timezone.utc))
            r = w.check()
        self.assertEqual(r["state"], "healthy")
        self.assertFalse(r["acted"])
        self.assertEqual(r["pid"], 9999)
        self.assertIsNotNone(r["heartbeat_age_s"])
        restarter.assert_not_called()


class UnhealthyTriggerTests(unittest.TestCase):
    def test_stale_heartbeat_triggers_restart(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            w, lf, restarter, _clk, _logs = _build_watcher(Path(td))
            stale = datetime.now(timezone.utc) - timedelta(seconds=120)
            _write_lockfile(lf, 9999, stale)
            r = w.check()
        self.assertEqual(r["state"], "restarting")
        self.assertEqual(r["trigger"], "stale_heartbeat")
        self.assertTrue(r["acted"])
        restarter.assert_called_once()
        self.assertGreater(r["heartbeat_age_s"], 100)

    def test_dead_pid_triggers_restart_even_with_fresh_heartbeat(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            w, lf, restarter, _clk, _logs = _build_watcher(
                Path(td), pid_alive=lambda pid: False,
            )
            _write_lockfile(lf, 9999, datetime.now(timezone.utc))
            r = w.check()
        self.assertEqual(r["state"], "restarting")
        self.assertEqual(r["trigger"], "dead_pid")
        self.assertTrue(r["acted"])
        restarter.assert_called_once()

    def test_naive_heartbeat_assumed_utc(self) -> None:
        """heartbeat_at without timezone should be treated as UTC."""
        with tempfile.TemporaryDirectory() as td:
            w, lf, restarter, _clk, _logs = _build_watcher(Path(td))
            # Write heartbeat as naive (no +00:00)
            hb = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
            lf.write_text(json.dumps({
                "pid": 9999, "heartbeat_at": hb, "host": "X",
            }), encoding="utf-8")
            r = w.check()
        # Heartbeat is essentially "now" - should be healthy
        self.assertEqual(r["state"], "healthy")
        self.assertFalse(r["acted"])


class CooldownGateTests(unittest.TestCase):
    def test_second_restart_within_cooldown_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            clk = _FakeClock(start=1000.0)
            w, lf, restarter, _clk, _logs = _build_watcher(Path(td), clock=clk)
            stale = datetime.now(timezone.utc) - timedelta(seconds=120)
            _write_lockfile(lf, 9999, stale)

            r1 = w.check()
            self.assertTrue(r1["acted"])

            # Advance only 10s - still inside the 30s cooldown
            clk.advance(10.0)
            # Lockfile is still stale (we haven't updated it)
            r2 = w.check()

        self.assertEqual(r2["state"], "cooldown")
        self.assertFalse(r2["acted"])
        self.assertEqual(r2["trigger"], "stale_heartbeat")
        self.assertGreater(r2["cooldown_remaining_s"], 0)
        # Restarter only invoked once across both checks
        self.assertEqual(restarter.call_count, 1)

    def test_restart_eligible_after_cooldown_elapses(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            clk = _FakeClock(start=1000.0)
            w, lf, restarter, _clk, _logs = _build_watcher(Path(td), clock=clk)
            stale = datetime.now(timezone.utc) - timedelta(seconds=120)
            _write_lockfile(lf, 9999, stale)

            r1 = w.check()
            self.assertTrue(r1["acted"])

            clk.advance(31.0)  # past the 30s cooldown
            r2 = w.check()

        self.assertTrue(r2["acted"])
        self.assertEqual(restarter.call_count, 2)


class CircuitBreakerGateTests(unittest.TestCase):
    def test_budget_blocks_after_max_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            clk = _FakeClock(start=1000.0)
            w, lf, restarter, _clk, _logs = _build_watcher(Path(td), clock=clk)
            stale = datetime.now(timezone.utc) - timedelta(seconds=120)
            _write_lockfile(lf, 9999, stale)

            # Exhaust the 5-attempt budget by advancing past each cooldown
            for _ in range(5):
                r = w.check()
                self.assertTrue(r["acted"], f"expected acted on attempt; got {r}")
                clk.advance(31.0)

            r_blocked = w.check()

        self.assertEqual(r_blocked["state"], "restart_blocked")
        self.assertFalse(r_blocked["acted"])
        self.assertGreater(r_blocked["budget_cooldown_s"], 0)
        self.assertEqual(restarter.call_count, 5)


class RestarterFailureTests(unittest.TestCase):
    def test_restarter_returning_false_surfaces_invocation_failed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            restarter = MagicMock(return_value=False)
            w, lf, _restarter, _clk, _logs = _build_watcher(Path(td), restarter=restarter)
            stale = datetime.now(timezone.utc) - timedelta(seconds=120)
            _write_lockfile(lf, 9999, stale)
            r = w.check()
        self.assertEqual(r["state"], "restart_invocation_failed")
        self.assertTrue(r["acted"])
        self.assertEqual(r["trigger"], "stale_heartbeat")


class ToDictTests(unittest.TestCase):
    def test_to_dict_includes_all_keys_initially(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            w, _lf, _r, _clk, _logs = _build_watcher(Path(td))
            d = w.to_dict()
        for k in ("last_state", "last_pid", "last_heartbeat_age_s",
                  "last_acted_at", "stale_threshold_s", "restart_cooldown_s",
                  "scheduled_task", "budget"):
            self.assertIn(k, d, f"key {k} missing from to_dict()")
        self.assertEqual(d["scheduled_task"], "RC-Phase3-Supervisor")
        self.assertEqual(d["last_state"], "unknown")

    def test_to_dict_reflects_check_state(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            w, lf, _r, _clk, _logs = _build_watcher(Path(td))
            _write_lockfile(lf, 9999, datetime.now(timezone.utc))
            w.check()
            d = w.to_dict()
        self.assertEqual(d["last_state"], "healthy")
        self.assertEqual(d["last_pid"], 9999)
        self.assertIsNotNone(d["last_heartbeat_age_s"])


class LoggingTests(unittest.TestCase):
    def test_restart_event_logs_line(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            w, lf, _r, _clk, logs = _build_watcher(Path(td))
            stale = datetime.now(timezone.utc) - timedelta(seconds=120)
            _write_lockfile(lf, 9999, stale)
            w.check()
        self.assertTrue(any("phase3 stale_heartbeat" in line for line in logs),
                        f"expected log line; got {logs}")

    def test_healthy_check_does_not_log(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            w, lf, _r, _clk, logs = _build_watcher(Path(td))
            _write_lockfile(lf, 9999, datetime.now(timezone.utc))
            w.check()
        self.assertEqual(logs, [])


class StaleCodeDetectionTests(unittest.TestCase):
    """2026-05-18: an otherwise-healthy Phase-3 process whose started_at
    predates the newest import-chain mtime must be restarted (it's
    serving stale code - the 2026-05-17 WS-mirror incident). Backward
    compatible: a lockfile without started_at (old supervisor) is never
    false-restarted."""

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    def test_code_newer_than_started_at_triggers_restart(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            w, lf, r, _clk, logs = _build_watcher(root)
            started = self._now() - timedelta(hours=2)
            _write_lockfile_started(lf, 9999, self._now(), started)
            _make_code_file(root, "core/queue_modes.py",
                             started.timestamp() + 600)
            res = w.check()
        self.assertTrue(res["acted"])
        self.assertEqual(res["trigger"], "stale_code")
        self.assertEqual(res["state"], "restarting")
        # stale_code keeps the process alive -> its pid is threaded to
        # the restarter so it can be killed before schtasks /Run.
        r.assert_called_once_with("RC-Phase3-Supervisor", 9999)
        self.assertTrue(any("phase3 stale_code" in ln for ln in logs))

    def test_agents_package_py_also_watched(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            w, lf, r, _clk, _logs = _build_watcher(root)
            started = self._now() - timedelta(hours=2)
            _write_lockfile_started(lf, 9999, self._now(), started)
            _make_code_file(root, "agents/agent2_backend/file_ingest.py",
                             started.timestamp() + 600)
            res = w.check()
        self.assertTrue(res["acted"])
        self.assertEqual(res["trigger"], "stale_code")

    def test_daemon_slayer_edit_does_not_trigger_stale_code(self) -> None:
        # agents/daemon_slayer is the standalone DS engine (its own
        # process on :8860); it is excluded from the Phase 3 watch so
        # the active DS work cadence does not bounce the supervisor.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            w, lf, r, _clk, _logs = _build_watcher(root)
            started = self._now() - timedelta(hours=2)
            _write_lockfile_started(lf, 9999, self._now(), started)
            _make_code_file(root, "agents/daemon_slayer/ability_dps.py",
                            started.timestamp() + 600)
            res = w.check()
        self.assertFalse(res["acted"])
        self.assertEqual(res["state"], "healthy")
        r.assert_not_called()

    def test_non_ds_agents_edit_still_triggers_when_ds_also_changed(self) -> None:
        # The exclusion is scoped, not global: a real Phase-3
        # import-chain edit still triggers even if a newer
        # daemon_slayer file is also present.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            w, lf, r, _clk, _logs = _build_watcher(root)
            started = self._now() - timedelta(hours=2)
            _write_lockfile_started(lf, 9999, self._now(), started)
            _make_code_file(root, "agents/daemon_slayer/ability_dps.py",
                            started.timestamp() + 9000)   # newer, excluded
            _make_code_file(root, "agents/agent7_context/warm_session.py",
                            started.timestamp() + 600)     # triggers
            res = w.check()
        self.assertTrue(res["acted"])
        self.assertEqual(res["trigger"], "stale_code")

    def test_code_older_than_started_at_stays_healthy(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            w, lf, r, _clk, _logs = _build_watcher(root)
            started = self._now()
            _write_lockfile_started(lf, 9999, self._now(), started)
            _make_code_file(root, "core/queue_modes.py",
                             started.timestamp() - 600)
            res = w.check()
        self.assertFalse(res["acted"])
        self.assertEqual(res["state"], "healthy")
        r.assert_not_called()

    def test_within_grace_stays_healthy(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            w, lf, r, _clk, _logs = _build_watcher(root)
            started = self._now()
            _write_lockfile_started(lf, 9999, self._now(), started)
            # +2s < the 5s grace margin
            _make_code_file(root, "core/queue_modes.py",
                             started.timestamp() + 2)
            res = w.check()
        self.assertFalse(res["acted"])
        self.assertEqual(res["state"], "healthy")

    def test_missing_started_at_skips_stale_check(self) -> None:
        # Old supervisor (pre-2026-05-18): lockfile has no started_at.
        # Even with much-newer code it must NOT be false-restarted.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            w, lf, r, _clk, _logs = _build_watcher(root)
            _write_lockfile(lf, 9999, self._now())  # no started_at
            _make_code_file(root, "core/queue_modes.py",
                            self._now().timestamp() + 99999)
            res = w.check()
        self.assertFalse(res["acted"])
        self.assertEqual(res["state"], "healthy")
        r.assert_not_called()

    def test_unparseable_started_at_skips(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            w, lf, r, _clk, _logs = _build_watcher(root)
            lf.parent.mkdir(parents=True, exist_ok=True)
            lf.write_text(json.dumps({
                "pid": 9999, "started_at": "not-a-date",
                "heartbeat_at": _iso_utc(self._now()), "host": "T",
            }), encoding="utf-8")
            _make_code_file(root, "core/queue_modes.py",
                            self._now().timestamp() + 99999)
            res = w.check()
        self.assertFalse(res["acted"])
        self.assertEqual(res["state"], "healthy")

    def test_stale_heartbeat_takes_precedence_over_stale_code(self) -> None:
        # A dead/stale process is the more urgent trigger; stale_code
        # only upgrades an otherwise-healthy one.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            w, lf, r, _clk, _logs = _build_watcher(root)
            started = self._now() - timedelta(hours=2)
            stale_hb = self._now() - timedelta(seconds=120)
            _write_lockfile_started(lf, 9999, stale_hb, started)
            _make_code_file(root, "core/queue_modes.py",
                            started.timestamp() + 600)
            res = w.check()
        self.assertEqual(res["trigger"], "stale_heartbeat")

    def test_stale_code_restart_respects_cooldown(self) -> None:
        clk = _FakeClock()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            w, lf, r, _clk, _logs = _build_watcher(root, clock=clk)
            started = self._now() - timedelta(hours=2)
            _write_lockfile_started(lf, 9999, self._now(), started)
            _make_code_file(root, "core/queue_modes.py",
                            started.timestamp() + 600)
            r1 = w.check()
            clk.advance(5.0)  # < 30s cooldown
            r2 = w.check()
        self.assertTrue(r1["acted"])
        self.assertEqual(r1["trigger"], "stale_code")
        self.assertFalse(r2["acted"])
        self.assertEqual(r2["state"], "cooldown")


class StaleCodeToDictTests(unittest.TestCase):
    def test_to_dict_exposes_grace(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            w, _lf, _r, _clk, _logs = _build_watcher(Path(td))
            self.assertIn("stale_code_grace_s", w.to_dict())


class DefaultRestarterTests(unittest.TestCase):
    """The production _default_restarter must terminate an alive stale
    pid before `schtasks /Run` (the task is IgnoreNew - /Run alone is
    refused with 0x800710E0 while an instance is live), and must NOT
    taskkill when the pid is already dead or not supplied. The DI tests
    above stub the restarter, so this is the only coverage of the real
    kill-then-run path."""

    @staticmethod
    def _fake_run_collector(calls):
        def fake_run(args, **kw):
            calls.append(list(args))
            m = MagicMock()
            m.returncode = 0
            return m
        return fake_run

    def test_alive_pid_killed_before_run(self) -> None:
        calls = []
        # alive at the gate check, dead immediately after kill so the
        # bounded wait loop exits without a real sleep.
        alive = MagicMock(side_effect=[True, False])
        with mock.patch.object(rc_sup.subprocess, "run",
                               side_effect=self._fake_run_collector(calls)), \
             mock.patch.object(rc_sup, "_pid_alive", alive):
            ok = _Phase3Watcher._default_restarter("RC-Phase3-Supervisor", 4242)
        self.assertTrue(ok)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0], ["taskkill", "/F", "/PID", "4242"])
        self.assertEqual(
            calls[1], ["schtasks", "/Run", "/TN", "RC-Phase3-Supervisor"])

    def test_dead_pid_no_taskkill(self) -> None:
        calls = []
        with mock.patch.object(rc_sup.subprocess, "run",
                               side_effect=self._fake_run_collector(calls)), \
             mock.patch.object(rc_sup, "_pid_alive", lambda _p: False):
            ok = _Phase3Watcher._default_restarter("RC-Phase3-Supervisor", 4242)
        self.assertTrue(ok)
        self.assertEqual(
            calls, [["schtasks", "/Run", "/TN", "RC-Phase3-Supervisor"]])

    def test_no_pid_no_taskkill(self) -> None:
        calls = []
        with mock.patch.object(rc_sup.subprocess, "run",
                               side_effect=self._fake_run_collector(calls)), \
             mock.patch.object(rc_sup, "_pid_alive", lambda _p: True):
            ok = _Phase3Watcher._default_restarter("RC-Phase3-Supervisor", None)
        self.assertTrue(ok)
        self.assertEqual(
            calls, [["schtasks", "/Run", "/TN", "RC-Phase3-Supervisor"]])

    def test_run_nonzero_returns_false(self) -> None:
        def fake_run(args, **kw):
            m = MagicMock()
            m.returncode = 1
            return m
        with mock.patch.object(rc_sup.subprocess, "run", side_effect=fake_run), \
             mock.patch.object(rc_sup, "_pid_alive", lambda _p: False):
            ok = _Phase3Watcher._default_restarter("RC-Phase3-Supervisor", None)
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
