# C-01 cron silent-fail report stub (audit-10)

- Target agent: 2 (backend)
- Severity: CRITICAL
- Audit: `20260621-100200-tenth-audit-phase3.md`

## Problem

`agent6-full-audit-pass` task dispatches recorded in
`agents/state/task_queue.jsonl`:

- 2026-06-01 `t-b0af80b08abc` -> `claude exit 1` (empty stderr)
- 2026-06-07 `t-0e64d21ea495` -> `claude exit 1` (empty stderr)
- 2026-06-14 `t-9061a61f1ef1` -> `claude exit 1` (empty stderr)
- 2026-06-21 `t-d213fa672bac` -> succeeded (this report)

No report stub. No proposal. No health surface. 21 days of silent
audit failures.

## Concrete fix (sketch)

1. In the scheduler's claude-spawn wrapper (`agents/supervisor.py` or
   wherever `agent6-full-audit-pass` is dispatched from), capture both
   stdout and stderr to
   `agents/agent6_auditor/reports/<ts>-FAILED-<task_id>.log`. Always
   write the file even when stderr is empty - record exit code,
   wallclock, payload digest.
2. On non-zero exit, also write a minimal report stub
   `agents/agent6_auditor/reports/<ts>-FAILED-<task_id>.md` containing
   the task id, exit code, dispatched_at, completed_at, and a pointer
   to the sidecar log.
3. Expose a `agent6` block in `/api/health/all` rollup with the last
   3 audit-pass outcomes (succeeded / failed-empty / failed-with-trace).
   The dashboard top-right dot should turn yellow on two consecutive
   failures.

## Files likely touched

- `agents/supervisor.py` (Phase 3 framework supervisor; NOT frozen
  per s243)
- `agents/_supervisor_common.py`
- `dashboard/routes_state.py` (extend rollup with `agent6` block)

## Acceptance

- Force a `claude exit 1` and confirm a `<ts>-FAILED-<task_id>.md`
  stub appears.
- `/api/health/all` returns `agent6.last_outcomes` array of length <= 3.
- Two-in-a-row failure caps top-level status at yellow.
