# /RC2-Continue

> **SUBAGENT-FIRST (standing protocol, operator 2026-06-20, restated 2026-07-30).** Orchestrated + multi-agent + self-adjudicating + self-adversarial is the DEFAULT shape, not an escalation.
> 1. **Spec first:** a Plan/design subagent (or the loop director) emits the spec/plan BEFORE any code; verify it vs ground truth (grep cited file:line, live `/api/state` + `ops/runtime/health.json`, git) - never scaffold on assumptions.
> 2. **New session:** interview the loop director (or the operator) for intent + acceptance criteria, re-probe live state, THEN build. Verify before building.
> 3. **Act via subagents:** worktree-isolated build agents on disjoint files (sole merger) + a read-only `verifier` subagent gate before any merge or "done" claim.
> 4. **Self-adjudicating:** the agent that produced a thing never grades it. **Self-adversarial:** every finding gets an independent pass trying to REFUTE it, defaulting to refuted when uncertain. Two agents agreeing is not evidence (`feedback_row_agreement_is_not_evidence`).
> 5. Trivial one-line cosmetic edits may inline (refines R9). See `CLAUDE.md` "Session Default".

Resume the RC 2.0 program after any interrupt (`**/clear`, crash, restart, new session).

ASCII only. No em-dashes or smart quotes. Caveman ULTRA output.

## CONTRACT

1. Read `docs/RC2_PLAN.md` (the living source of truth). This file IS the state -
   git history + `docs/LEDGER.md` carry the detail.
2. Find the FIRST stage not `DONE`/`CLOSED`/`LIVE` (top-to-bottom, Phase 1 -> 9).
3. Recompute the PROGRESS banner: `% = DONE_stages / TOTAL_stages * 100`. If
   stages were added/removed, fix TOTAL first, then the percent. Print one line:
   `Phase X of 9 - Stage Y of N - ~Z% complete`.
4. Sync the background-task pane: ensure one TaskCreate chip per phase exists;
   mark the active phase `in_progress`, completed phases `completed`.
5. If the next stage is the P2 `GATE` (design HTML) and the operator has NOT
   greenlit: do NOT block. Build the new design behind a flag, keep the current
   design live, and continue to the next non-DONE stage.

## EXECUTE

For the selected stage, run the per-stage ritual from `docs/RC2_PLAN.md`:
- Swarm where the work is parallelizable (worktree-isolated, disjoint files,
  sole merger, verifier-gate before merge) - up to 100 agents, no session cap.
- TDD (failing test first) for logic; py_compile before any restart.
- Tiered verification (R5-R7): full dual suite only on Tier-2 (schema / engine /
  ENGINE_VERSION / item-effect); Tier-0/1 run the scoped check once.
- UI stages: 5-phase fixture audit (STRUCTURE / TYPOGRAPHY / HIT-TARGETS / ASCII /
  HIERARCHY) + Claude_Preview vs `/api/state` BEFORE commit.
- DS seams DEFAULT-OFF + ENGINE bump + DS :8860 restart in the same
  commit; live flip -> `docs/LIVE_GAME_GATED_SYNC.md`.
- commit + push + CI green -> `/done` (append `docs/LEDGER.md` as `RC2-<stage>`,
  sync `docs/RC2_PLAN.md` + ROADMAP).
- Flip the stage row to `DONE` with the commit sha; re-derive the banner.

## POLICY (active for this program)

- No budget; Gemini-credit fallback = best judgment, never default to operator.
- Frozen-file edits AUTHORIZED. Full computer usage AUTHORIZED (download/install/run).
- If loop director is unavailable, the executor self-directs from `docs/RC2_PLAN.md`.

## DRAIN

When every stage is DONE/CLOSED/LIVE: run Phase 9 once (delta research + design
re-synthesis, Gemini-gated to make headless), then print the RC 2.0 completion
banner and stop. The headless loop launches via `ops/loop/launch_loop.ps1 -Mode live`;
abort by dropping `ops/loop/control/STOP`.
