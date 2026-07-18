# C-01 cron silent-fail - implementation report

- Proposal: `agents/agent6_auditor/proposals/20260621-100200-c01-cron-silent-fail/PROPOSAL.md`
- Severity: CRITICAL
- Implemented by: Agent 2 (backend) on 2026-06-21
- Task: `t-13931c55261b`

## Changes

### 1. `agents/_supervisor_ephemeral.py`

Added `_write_agent6_failure_stub(task_id, op, payload, exit_code, sidecar_log, started_ts)`.
Called from `spawn_ephemeral_llm` in the `if proc.returncode != 0` branch when `agent == "6"`.

On any non-zero exit for an agent-6 spawn the function atomically writes:
`agents/agent6_auditor/reports/<YYYYMMDD-HHMMSS>-FAILED-<task_id>.md`

Stub contains: task_id, op, exit_code, dispatched_at (from payload.filed_at),
started_at, completed_at, pointer to `logs/agents/task-<task_id>.log`.

### 2. `dashboard/routes_state.py`

Added `_agent6_audit_outcomes(max_count=3)` - scans `agents/state/task_queue.jsonl`
for the last N `agent6-full-audit-pass` final events (completed / failed /
reclassified_completed), oldest-first.

Added `agent6` block to `_serve_health_all` rollup:
```json
{
  "last_outcomes": [...up to 3 entries...],
  "status": "green" | "yellow"
}
```
Status is `"yellow"` when the last 2 outcomes are both `"failed"` (consecutive
failures), `"green"` otherwise.

`agent6_degraded` now participates in the top-level status yellow condition
alongside `bridge_degraded` and `peer_degraded`.

## Acceptance criteria verified

- Syntax clean: `py_compile` on both files passes.
- Failure stub logic: any `claude exit N` for agent 6 writes the .md artifact
  before raising `EphemeralSpawnFailed`.
- `/api/health/all` now returns `agent6.last_outcomes` (length <= 3).
- Two-in-a-row failures set `agent6.status = "yellow"` which caps the
  top-level dot at yellow.

## Note on past failures (not backfilled)

The three past silent failures (t-b0af80b08abc 2026-06-01, t-0e64d21ea495 2026-06-07,
t-9061a61f1ef1 2026-06-14) have no per-task log on disk (pruned by the 7-day
retention cap in `prune_task_logs`). Their `task_queue.jsonl` records remain
as-is. Future failures will produce .md stubs from this point forward.
