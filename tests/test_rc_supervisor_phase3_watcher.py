"""Unit tests for ops/rc_supervisor.py:_Phase3Watcher — the subordinate
watch that detects Phase 3 supervisor death / heartbeat staleness and
re-launches the RC-Phase3-Supervisor scheduled task.

Watcher is dependency-injected with stub clock / pid-checker / restarter,
so no Phase 3 supervisor needs to be running. Lockfile is a temp file the
test owns. Per-test breaker state file lives under tmp_path.
"""
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

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
        restarter.assert_called_once_with("RC-Phase3-Supervisor")

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
        # Heartbeat is essentially "now" — should be healthy
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

            # Advance only 10s — still inside the 30s cooldown
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


if __name__ == "__main__":
    unittest.main()
