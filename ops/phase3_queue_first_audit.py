"""Queue the post-setup first task: agent6-full-audit-pass (§11.14).

Priority 0 (highest - lowest number wins heap order) and flagged as
``blocks_all_subsequent`` so Agent 1's future dispatch logic can refuse to
hand out any work until this audit completes.

Idempotent: if a task with this exact op is already present, no-op.
"""
from __future__ import annotations

import sys

from agents.agent1_lead import Scheduler, TaskStatus


AUDIT_OP = "agent6-full-audit-pass"


def main() -> int:
    s = Scheduler()

    # Idempotency - skip if this op already exists in any non-terminal state.
    existing = [
        t for t in s.list_by_status(TaskStatus.READY) + s.list_by_status(TaskStatus.IN_PROGRESS)
        if t.op == AUDIT_OP
    ]
    if existing:
        t = existing[0]
        print(f"already queued: id={t.id} status={t.status} priority={t.priority}")
        return 0

    t = s.file_task(
        op=AUDIT_OP,
        owner_agent="6",                     # Opus 4.7 per AGENT_MODELS
        priority=0,                          # highest
        categories=[],                        # ungated (agent 6 is category 6 - ungated in §7)
        payload={
            "scope": "full-phase3-repo-audit",
            "target_paths": [
                "agents/",
                "lib/",
                "web/",
                "data/db/",
                "logs/",
            ],
            "charter": "Analyse and clean up the Phase 3 framework after setup/migration. "
                       "Report safeguards to add, perf hotspots, inconsistencies vs resolved_decisions.json. "
                       "Propose-and-queue any code changes to agent4/agent6 proposal dirs.",
            "blocks_all_subsequent": True,
            "rationale_ref": "spec §11.14",
        },
    )
    print(f"filed: id={t.id} op={t.op} owner=agent{t.owner_agent} status={t.status} priority={t.priority}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
