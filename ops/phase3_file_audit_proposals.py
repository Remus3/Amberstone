"""File the 7 audit follow-up tasks into Agent 1's queue.

Idempotent: if any task with the same ``proposal_id`` already exists
(non-terminal), it is skipped.
"""
from __future__ import annotations

from agents.agent1_lead import Scheduler, TaskStatus


# (severity, label, owner_agent, title, fix_snippet or discussion)
PROPOSALS = [
    (
        "high", "P-audit-h1", "2",
        "Reject path traversal in evaluator",
        "Add _has_traversal() helper that splits path on / and \\ and rejects "
        "any segment equal to '..' or '%2e%2e'. Invoke at the top of "
        "Evaluator.evaluate() with REASON_DESTINATION (criterion 3) so the "
        "rejection label reads 'destination_traversal'. Rolls in M3 subdir "
        "substring-match tightening — require subdir to immediately follow "
        "RCClient\\.",
    ),
    (
        "high", "P-audit-h2", "2",
        "Process-level lock on task_queue.jsonl",
        "Scheduler._append_log uses threading.RLock only — concurrent Python "
        "processes can interleave. Add msvcrt.locking(f.fileno(), "
        "msvcrt.LK_NBLCK, 1) with a ~100ms retry loop when another writer "
        "holds it. Windows-only; Linux equivalent via fcntl if ever needed.",
    ),
    (
        "high", "P-audit-h3", "2",
        "Supervisor ephemeral stub must fail(), not complete()",
        "supervisor.spawn_ephemeral_llm currently returns success for every "
        "call. Dispatch loop then calls scheduler.complete(). Until real "
        "Claude subprocess spawning lands, stub should return "
        "{'substrate': 'stub_no_op'} and the dispatcher must call "
        "scheduler.fail(task_id, 'stub_no_op') instead of complete(). "
        "Prevents silent false-positive completions for ALL LLM-agent "
        "work — including the audit task itself.",
    ),
    (
        "medium", "P-audit-m1", "3",
        "Test backup path of smb_push",
        "Extend test_smb_push.test_push_web_roundtrip (or add "
        "test_push_web_overwrites_creates_backup) to push the same "
        "filename twice with distinct payloads. Assert the second push "
        "result['backup'] is non-None, file at backup path has the first "
        "payload, file at remote path has the second.",
    ),
    (
        "medium", "P-audit-m2", "2",
        "Migration: skip rows with null tracked_team_id",
        "migration_rewind._split_comp currently falls back to "
        "'tracked_team_id or 100', defaulting null to blue side — that "
        "silently corrupts the ally/enemy split for rows where the "
        "tracked player was on red. Skip the match entirely when "
        "tracked_team_id is null; log at DEBUG with match_id.",
    ),
    (
        "medium", "P-audit-m4", "2",
        "Scheduler: validate blocked_by ids on file_task",
        "Scheduler._blocked returns True forever if a blocked_by id "
        "doesn't resolve. file_task should WARN-log and drop any "
        "unknown id so tasks don't silently stall.",
    ),
    (
        "medium", "P-audit-m5", "2",
        "Explicit max_size on websockets.serve",
        "Document the 1 MB frame cap by passing max_size=2**20 explicitly "
        "to serve() in WSServer.start. If screenshot streaming ever "
        "moves to WS, bump to 8*2**20 or None.",
    ),
]


def main() -> int:
    s = Scheduler()

    filed = 0
    skipped = 0

    for severity, label, owner, title, fix in PROPOSALS:
        # Idempotency: any existing task carrying this proposal_id in any
        # non-terminal state blocks a new filing.
        already = any(
            t.payload.get("proposal_id") == label
            and t.status not in (TaskStatus.DEAD_LETTER, TaskStatus.FAILED, TaskStatus.COMPLETED)
            for t in [*s.list_by_status(TaskStatus.READY),
                      *s.list_by_status(TaskStatus.IN_PROGRESS),
                      *s.list_by_status(TaskStatus.NEEDS_APPROVAL),
                      *s.list_by_status(TaskStatus.AGENT0_REVIEW),
                      *s.list_by_status(TaskStatus.RETRY_PENDING)]
        )
        if already:
            skipped += 1
            print(f"  skip  {label} already queued")
            continue

        priority = {"high": 10, "medium": 30, "low": 60}.get(severity, 50)
        t = s.file_task(
            op=f"apply-proposal-{label.lower()}",
            owner_agent=owner,
            priority=priority,
            categories=[],  # all are local code changes, ungated
            payload={
                "proposal_id": label,
                "severity": severity,
                "title": title,
                "fix_snippet": fix,
                "source_report": "agents/agent6_auditor/reports/20260422-095110-first-audit.md",
                "filed_by": "agent6",
            },
        )
        filed += 1
        print(f"  filed {label} -> {t.id} priority={t.priority} owner=agent{owner}")

    print(f"\n{filed} filed, {skipped} already present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
