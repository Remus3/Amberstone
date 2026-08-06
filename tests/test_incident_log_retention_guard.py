"""RM-161: `IncidentLog.retention_days` is the knob with the teeth.

`ops/rc_incident_log.py` had ZERO test references before this file - measured
by scanning every `tests/**/*.py` for the stem `rc_incident_log`. It is the
store the supervisor writes every incident into, and `_purge_old_locked`
rewrites that store keeping only entries whose `ts` is newer than
`now - timedelta(days=self.retention_days)`. At `retention_days <= 0` the
window is empty or inverted, so `entry["ts"] >= cutoff_ts` is false for every
entry and the purge that exists to BOUND the log ERASES it - including the
incidents the operator opened it to read.

The value arrives from config: `ops/rc_supervisor.py:1442` (FROZEN) reads
`incident_log_retention_days` out of `config/self_monitor_profile.json` with
`int(profile.get(..., 7))` and passes it straight in. So a typo in a config
file reaches the deleter without anybody editing code, which is why the
validator now ranges that key too (`tests/test_config_validator.py`,
`RangeSpecCase`). The two guards are deliberately independent: the validator
is NON-FATAL (`main.py` discards its result), so it reports a bad profile and
does not stop it.

Raising rather than clamping is safe here and was checked against the live
consumer, not assumed: the construction sits inside `_start_self_monitor`'s
`try`, whose handler at `ops/rc_supervisor.py:1470` logs
"SelfMonitor start failed (non-fatal)". A rejected policy therefore costs a
log line and an unstarted monitor, never a supervisor crash - and never an
erased incident log.
"""
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "ops"))

from ops.rc_incident_log import IncidentLog  # noqa: E402


class IncidentLogRetentionGuardCase(unittest.TestCase):

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory(prefix="rc_incident_guard_")
        self.runtime_dir = Path(self._tmp.name) / "runtime"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # - the defect ---------------------------------------------------------

    def test_non_positive_retention_is_rejected(self):
        for bad in (0, -1, -7):
            with self.subTest(retention_days=bad):
                with self.assertRaises(ValueError) as ctx:
                    IncidentLog(runtime_dir=self.runtime_dir, retention_days=bad)
                self.assertIn("retention_days", str(ctx.exception))

    def test_rejection_happens_before_the_directory_is_created(self):
        """`__init__` mkdirs `runtime_dir`. The guard runs first, so a
        rejected policy leaves no side effect behind."""
        with self.assertRaises(ValueError):
            IncidentLog(runtime_dir=self.runtime_dir, retention_days=0)
        self.assertFalse(
            self.runtime_dir.exists(),
            "a rejected policy still created the runtime directory",
        )

    def test_the_supervisors_own_default_is_accepted(self):
        """`ops/rc_supervisor.py:1442` and `ops/rc_self_monitor.py:44` both
        carry 7. A guard that rejected the live value would be a regression."""
        log = IncidentLog(runtime_dir=self.runtime_dir, retention_days=7)
        self.assertEqual(log.retention_days, 7)
        self.assertTrue(self.runtime_dir.is_dir())

    def test_the_smallest_legal_window_is_accepted(self):
        log = IncidentLog(runtime_dir=self.runtime_dir, retention_days=1)
        self.assertEqual(log.retention_days, 1)

    # - the erase the guard prevents ---------------------------------------

    def _write_entries(self, log: IncidentLog) -> None:
        now = datetime.now(timezone.utc)
        lines = [
            json.dumps({"ts": now.isoformat(), "what": "fresh"}),
            json.dumps({"ts": (now - timedelta(days=90)).isoformat(),
                        "what": "stale"}),
        ]
        log.log_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_a_sane_window_purges_only_the_stale_entry(self):
        """Characterization: this is what the knob is FOR, and it is the
        behaviour a non-positive value silently inverts."""
        log = IncidentLog(runtime_dir=self.runtime_dir, retention_days=7)
        self._write_entries(log)
        removed = log.purge_old()
        self.assertEqual(removed, 1)
        body = log.log_file.read_text(encoding="utf-8")
        self.assertIn("fresh", body)
        self.assertNotIn("stale", body)

    def test_a_zero_window_would_have_erased_everything(self):
        """Pins WHY the guard exists rather than only that it fires. The
        purge is driven off the attribute, so this reproduces the original
        defect by writing the attribute past the constructor - exactly what
        the old code let a config file do."""
        log = IncidentLog(runtime_dir=self.runtime_dir, retention_days=7)
        self._write_entries(log)
        log.retention_days = 0
        removed = log.purge_old()
        self.assertEqual(
            removed, 2,
            "expected the empty window to sweep BOTH entries - if this ever "
            "reports fewer, the purge semantics changed and the constructor "
            "guard is no longer guarding what this test claims",
        )
        self.assertNotIn("fresh", log.log_file.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
