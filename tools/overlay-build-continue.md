# /overlay-build-continue

> **SUBAGENT-FIRST (standing protocol, operator 2026-06-20, restated 2026-07-30).** Orchestrated + multi-agent + self-adjudicating + self-adversarial is the DEFAULT shape, not an escalation.
> 1. **Spec first:** a Plan/design subagent (or the loop director) emits the spec/plan BEFORE any code; verify it vs ground truth (grep cited file:line, live `/api/state` + `ops/runtime/health.json`, git) - never scaffold on assumptions.
> 2. **New session:** interview the loop director (or the operator) for intent + acceptance criteria, re-probe live state, THEN build. Verify before building.
> 3. **Act via subagents:** worktree-isolated build agents on disjoint files (sole merger) + a read-only `verifier` subagent gate before any merge or "done" claim.
> 4. **Self-adjudicating:** the agent that produced a thing never grades it. **Self-adversarial:** every finding gets an independent pass trying to REFUTE it, defaulting to refuted when uncertain. Two agents agreeing is not evidence (`feedback_row_agreement_is_not_evidence`).
> 5. Trivial one-line cosmetic edits may inline (refines R9). See `CLAUDE.md` "Session Default".

Resume the Overlay + Adaptive-Build program after any interrupt (`/clear`, crash, new session).

ASCII only. No em-dashes or smart quotes. Caveman ULTRA chat output. Opus 4.8 ultracode.

## CONTRACT

1. Read `docs/OVERLAY_BUILD_MASTER_PLAN.md` - it IS the living source of truth. The Section J
   EXECUTION TRACKER is the state; git history + `docs/LEDGER.md` carry the detail.
2. In the Section J tracker, find the FIRST work package with Status `OPEN` whose every dependency
   is `DONE`, honoring the Section H wave order + the shared-file collision map. Skip `GATED`
   (needs a live game or an operator decision) and `DEFER`/DS-batch rows. If a `GATED` WP is the
   only thing left and its gate is an operator decision (e.g. F4a ward keep-vs-retire), make the
   call per `feedback_decisions_not_operator_gated`, record it in `RC_WORK_TRACKER.md`, and proceed.
3. Flip that WP to `WIP` in the tracker (atomic write) and commit nothing yet.
4. Print one status line: `WP-<id> (wave W<n>, tier T<x>) - <N> DONE / <M> total`.

## EXECUTE (one WP per cycle, multi-agent inside)

For the selected WP, run its row from `docs/OVERLAY_BUILD_MASTER_PLAN.md` end to end:

- **TDD first:** write the WP's named failing characterization/regression test BEFORE the
  implementation. Cite the exact file:line targets from the plan; re-grep to confirm each symbol
  still exists before editing (never scaffold on an assumed API surface).
- **Swarm where parallelizable:** worktree-isolated build agents on the WP's disjoint files (you
  are the sole merger), per the Section H collision map. Single-file or trivial WPs inline (R9).
  Give substantive agents (C2 beam search, B2/B3 module, D2 radial) high-effort budgets.
- **Tiered verification (R5-R7):** Tier-0 cosmetic = edit + py_compile if .py. Tier-1 = py_compile
  + that module's own tests. Tier-2 (A4a, C5) = full dual suite (DS dir + `tests/`) + DS :8860
  restart in the SAME commit.
- **UI WPs** (A1, A4b, A5, A6, B2, B3, B4, D1, D2, D3): run the Section G.9 5-phase UI-audit
  ritual (STRUCTURE / TYPOGRAPHY / HIT-TARGETS / ASCII / HIERARCHY) + Claude_Preview vs `/api/state`
  BEFORE commit; resolve every MUST-FIX in the same slice. Honor the Section G UX doctrine
  (sizing/color/radial/tooltip/hysteresis MUST rules).
- **Verifier gate (R7):** a read-only `verifier` subagent re-runs the WP test FRESH, confirms every
  cited test file exists on disk, and reports THIS-run pass/fail BEFORE you merge or claim done.
  Never carry a subagent-reported count forward.
- **Adaptive module (Section C) sits ABOVE DS:** never change DS fundamentals, scoring, or
  ENGINE_VERSION. Read `/api/ds-preview` + `/api/build-order` as read-only ground truth. The new
  `/api/build-plan` route uses HTTP, not an in-process DS import (split-brain guard
  `test_routes_state_has_no_in_process_engine_import`). Per-match build state is IN-MEMORY only.
- **Restart safely:** py_compile before any restart; restart via `echo restart > restart_trigger.txt`.
  Atomic writes only. ADR-008: editing `web/{js,css}/panels/*` auto-reloads (no RC restart).
- **Ship:** commit + push + confirm CI green, then run `/done` (append a per-WP entry to
  `docs/LEDGER.md`; sync ROADMAP if the WP closed a ROADMAP item). Flip the WP row to `DONE` with
  the commit sha in the Section J tracker.

## POLICY

- No budget cap on the executor. Frozen-file + .md edits AUTHORIZED for this program. Full computer
  usage AUTHORIZED. Auto-pick the recommended option; ask no questions; never block on operator
  sign-off (record decisions in `RC_WORK_TRACKER.md`).
- Each WP is independently shippable + tested + UI-audited so `main` stays green (RC main-per-cycle
  convention; CI watchdog guards red main). Build agents use auto-cleaned git worktrees; scratch
  files go in the session scratchpad, never the repo tree.

## DRAIN

When every Section J row is `DONE`/`GATED`/`DEFER` (no `OPEN` left): print the program completion
banner with the DONE/total count + the live-gated tail (F1-01/04/05/06 verify-pass after a real
game) + the DS-batch tail (F.2, separate ENGINE sessions), then stop. The loop launches via
`ops/loop/launch_loop.ps1 -Mode live -Cfg ops/loop/config.overlay.json`; abort by dropping
`ops/loop/control/STOP`.
