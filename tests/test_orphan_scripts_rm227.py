"""RM-227(a) dead-code drift guard.

Pins the five dead ops scripts removed 2026-08-30 (LANE 7 headless-repo,
operator-approved) as PERMANENTLY removed. Each had ZERO live consumers at
removal time - only doc / generated-HTML / self / mutual references:

  ops/_scheduler_client.py - an HTTP-first task-filing wrapper that no caller
      ever adopted. Every ops script and agent files tasks by calling
      Scheduler.file_task() directly; the wrapper's sole importer was one
      self-test, removed in the same commit.
  ops/phase3_file_audit_proposals.py    - one-shot Agent-6 queue seeders. None
  ops/phase3_file_rc_audit_proposals.py   was wired to a task, runner, or
  ops/phase3_queue_first_audit.py         import; the live weekly self-audit
  ops/phase3_summary.py                   runs `-m ops.phase3_file_audit`
                                          (RC-Phase3-PeriodicAudit), a distinct
                                          kept sibling.

Same shape as tests/test_orphan_scripts_item195.py. If you find yourself adding
any of these back, first confirm a real consumer exists - otherwise the script
is dead-on-arrival. See BACKLOG RM-227(a).
"""
from __future__ import annotations

import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent

_DELETED_ORPHAN_FILES: tuple[str, ...] = (
    "ops/_scheduler_client.py",
    "ops/phase3_file_audit_proposals.py",
    "ops/phase3_file_rc_audit_proposals.py",
    "ops/phase3_queue_first_audit.py",
    "ops/phase3_summary.py",
)


class Rm227OrphanScriptAbsenceTests(unittest.TestCase):
    def test_rm227_orphan_scripts_stay_deleted(self):
        offenders = [
            rel for rel in _DELETED_ORPHAN_FILES if (_PROJECT_ROOT / rel).exists()
        ]
        self.assertEqual(
            offenders,
            [],
            "RM-227(a) dead scripts reappeared - investigate: " + "; ".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
