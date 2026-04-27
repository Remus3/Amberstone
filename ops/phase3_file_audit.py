"""File a fresh agent6-full-audit-pass task into the scheduler queue.

Invoked by the ``RC-Phase3-PeriodicAudit`` scheduled task on a weekly
cadence so Agent 6 does a self-review even when no human is asking.

Idempotent: if a non-terminal audit task already exists, this no-ops so
we don't pile up duplicate audits during multi-day outages.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone

from agents.agent1_lead import Scheduler, TaskStatus

AUDIT_OP = "agent6-full-audit-pass"
NON_TERMINAL = (
    TaskStatus.READY, TaskStatus.IN_PROGRESS,
    TaskStatus.NEEDS_APPROVAL, TaskStatus.AGENT0_REVIEW,
    TaskStatus.RETRY_PENDING, TaskStatus.PENDING,
)


def main() -> int:
    s = Scheduler()
    # Skip when a prior audit is still queued / running.
    for status in NON_TERMINAL:
        for t in s.list_by_status(status):
            if t.op == AUDIT_OP:
                print(f"skip: {AUDIT_OP} already {t.status} ({t.id})")
                return 0

    t = s.file_task(
        op=AUDIT_OP,
        owner_agent="6",
        priority=0,
        categories=[],
        payload={
            "scope": "full-phase3-repo-audit",
            "blocks_all_subsequent": True,
            "trigger": "periodic-cron",
            "filed_at": datetime.now(timezone.utc).isoformat(),
            "spawn_budget_usd": 3.00,        # a bit more headroom than $2
            "spawn_timeout_sec": 1200,       # 20 min
        },
        user_override=True,                  # cron-filed counts as implicit approval
    )
    print(f"filed: {t.id} priority={t.priority} status={t.status}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
