# P-audit8-h02 - task_queue.jsonl state-machine leak

- **Severity:** HIGH
- **Owner:** Agent 2 (backend)
- **Source:** `20260525-025744-eighth-audit-phase3.md` H-02
- **File:** `agents/state/task_queue.jsonl`

## Observed

Per-task last-event status tally across 1392 events:

- ready=442 (filed, never dispatched)
- in_progress=449 (dispatched, never closed)
- completed=452
- failed=2
- needs_explicit_approval=46

`filed`=488 / `dispatched`=450 / `completed`=450 / `failed`=2. The
completed count tracks dispatched (-> dispatched tasks close cleanly),
but 442 of 488 filed envelopes never reach `dispatched`. Top ops:
`game-summary` (615), `coaching-insight-advisory` (240),
`test-round22-*` family (~320).

## Proposed

1. **Reconciler in Agent 1's task loop.** Every N minutes, scan the
   per-task last status; for any `in_progress` envelope older than
   30 minutes with no completion event, emit either:
   - `dispatched` (retry) - if the op is idempotent + within retry
     budget
   - `failed` with reason=`timeout-no-terminal-event` - otherwise
   Both close the per-task view.
2. **`dropped`/`deduped` event.** When the filing path intentionally
   drops or dedupes a filed task (e.g. game-summary collapse,
   priority-zero shedding), emit a terminal event of the same shape
   so the audit math reconciles (filed == dispatched + dropped +
   deduped). Today the audit can't tell drop from leak.
3. **One-shot recovery on supervisor start.** On boot, re-emit any
   `in_progress` envelope older than 1 hour as `failed`
   reason=`supervisor-restart`. The append-only file means restart
   currently can't trivially re-dispatch; an explicit failed event
   makes the state visible.

## Out of scope

- Schema migration of historic events (1392 lines). The reconciler
  reasons over per-task last-event so the historic backlog can stay
  as-is; only new envelopes need the new terminal events.

## Estimated cost

Small. ~50 LOC in the Agent 1 task loop + a unit test asserting
`filed == dispatched + dropped + deduped + ready-still-pending`.
