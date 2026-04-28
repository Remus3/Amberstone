# Safeguards — supervisor startup invariants

Agent 6 tracks the pre-dispatch invariants the supervisor must verify
before handing work to any substrate. Current status after the first
audit pass:

## Invariants (MUST hold at `Supervisor.start()` return)

| # | Invariant | Enforced today? | Location |
|---|-----------|-----------------|----------|
| 1 | Lockfile acquisition succeeded (single live supervisor) | Yes | `agents/supervisor.py:acquire_lock` |
| 2 | All five mode DBs exist with schema | Yes (`init_all_dbs`) | `supervisor.start` |
| 3 | SMB cmdkey present OR cross-machine dispatch disabled | Yes (flag) | `supervisor.start` |
| 4 | Rewind migration has been run at least once | **NO — implicit via tests only** | — |
| 5 | Web port 8890 available | Yes (audit L2 landed) | `supervisor.py:286, 1499-1501` |
| 6 | WS port 8891 available | Yes (audit L2 landed) | `supervisor.py:286, 1499-1501` |
| 7 | `task_queue.jsonl` not corrupted (all lines parse) | Partial — bad lines logged loudly (audit3 M-04) | `Scheduler._load` lines 243, 466, 580 |
| 8 | `resolved_decisions.json` version matches code expectations | Yes (audit3 H-03 landed) | `supervisor.py:258-282`, called at `:1489` |
| 9 | DDragon cache populated OR scheduled for first fetch | NO | — |

## Required follow-ups (filed as proposals)

- Invariant 4 — add a startup check that queries `matches` across all 5
  DBs; if total==0, file a task to re-run `migration_rewind`. Still open.
- Invariant 9 — DDragon cache populated OR scheduled for first fetch.
  Still open.

## Resolved (recorded for audit history)

- Invariants 5/6: preflight bind landed via audit L2.
- Invariant 7: corrupted `task_queue.jsonl` lines now log error+offset
  instead of silent drop (audit3 M-04).
- Invariant 8: `resolved_decisions.json` version mismatch fails closed
  in `Supervisor.start()` (audit3 H-03).

## Hard rules Agent 6 enforces on other agents' proposals

1. **Never touch the frozen-files list in CLAUDE.md §Hard rules**
   without user sign-off (file a hard-gate task with `categories=[1]`).
2. **Never `Stop-Process`** — all process termination must use `taskkill
   /F /PID`. Any proposal containing `Stop-Process` is rejected.
3. **Atomic writes for every JSON/config touched**. Any PR touching
   `data/` or `agents/state/` without `.tmp → os.replace` is rejected.
4. **Every `subprocess.run` with variable args must be argv-list,
   never shell=True**. Injection is a dead-letter category.
5. **Never widen `allowed_ops.json`** without a corresponding audit entry
   here justifying the new op class.

## Auto-escalation triggers (send a task to Agent 6)

- Any scraper sees >=5 consecutive network errors within a 10-min window.
- Any hot-path function takes >200ms p95 over a 100-call sample.
- Disk free on `C:` drops below 5 GB.
- `logs/` directory exceeds 1 GB aggregate.
- Supervisor restart count exceeds 3/hour.
