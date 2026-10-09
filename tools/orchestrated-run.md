# orchestrated-run

> **SUBAGENT-FIRST (standing protocol, operator 2026-06-20, restated 2026-07-30).** Orchestrated + multi-agent + self-adjudicating + self-adversarial is the DEFAULT shape, not an escalation.
> 1. **Spec first:** a Plan/design subagent (or the loop director) emits the spec/plan BEFORE any code; verify it vs ground truth (grep cited file:line, live `/api/state` + `ops/runtime/health.json`, git) - never scaffold on assumptions.
> 2. **New session:** interview the loop director (or the operator) for intent + acceptance criteria, re-probe live state, THEN build. Verify before building.
> 3. **Act via subagents:** worktree-isolated build agents on disjoint files (sole merger) + a read-only `verifier` subagent gate before any merge or "done" claim.
> 4. **Self-adjudicating:** the agent that produced a thing never grades it. **Self-adversarial:** every finding gets an independent pass trying to REFUTE it, defaulting to refuted when uncertain. Two agents agreeing is not evidence (`feedback_row_agreement_is_not_evidence`).
> 5. Trivial one-line cosmetic edits may inline (refines R9). See `CLAUDE.md` "Session Default".

> **DISPATCH (FLEET-KIT v10 banner; MAIN 2026-10-08 0839 ORDER step 4).** In an interactive main session this skill is never run inline.
> 1. The main session dispatches the WHOLE skill to ONE sub-agent (Agent tool): this file plus the invocation arguments. It relays only that agent's final output - the line(s) this skill names as its chat output, nothing when it names none - with no narration around it.
> 2. No quick-read or trivial-edit exception in the main thread; this supersedes any "may inline" line in this file. Its Bash / PowerShell / Read / Edit / Write / Grep / Glob / NotebookEdit calls meet the kit PreToolUse hook `ops/fleet_kit/fleet_subagent_first.py` (gitignored mode file `ops/loop/control/subagent_first.mode`: log first, then deny).
> 3. The dispatched sub-agent, and a headless run (the kit's `spawn()` sets `FLEET_SUBAGENT_FIRST=off`), execute this skill directly and never re-dispatch the whole of it.

> **RACE GUARDS (FLEET-KIT v12, FLEET-COMMON item 16; MAIN 2026-10-08 2031 ORDER step 5).** Enforced by the kit hook `ops/fleet_kit/fleet_claims.py` (PreToolUse + SubagentStop in the project settings), not by this text.
> 1. Every `git commit` / `git push` runs through the tree's git lock: `python ops/fleet_kit/fleet_gitlock.py run --owner <id> -- git commit -F <tmpfile>` (same shape for `git push ...`). Python code uses `fleet_gitlock.git_lock(dir, owner)`. A bare commit or push is denied.
> 2. A WHOLE suite (pytest naming no test file) runs through the machine-wide gate: `python ops/fleet_kit/fleet_suite_gate.py run --owner <id> -- <suite cmd>`. A slice that names its test files needs no gate.
> 3. `<id>` is your own claims owner id, `<session_id>.<agent_id>` (`.main` in a main thread); a deny reason names it. The hook also denies an edit, a redirect or a `git add` of a file another live agent holds - leave that file to its agent.

Bootstrap a gemini-directed, orchestrated parallel multi-agent fanout run that
exhausts a multi-session program of work across a set of themes. This is the
generic initializer for the pattern proven by the A1..F1 run (see
docs/ORCHESTRATION_PLAN.md). gemini-3-pro-preview is the read-only DIRECTOR +
AUDITOR; ops/loop/loop_controller.py is the brain; the AHK bridge types one
directive per cycle into THIS Claude window and /clears between cycles.

ARGS (free-form, optional): the themes / scope for this run. Default themes if
none given: (1) LoL research, (2) lift work, (3) Daemon Slayer schema + surfacing
DS data in context, (4) UI/UX updates + per-page audit + visual validation,
(5) wiring/surfacing components marked "not implemented yet".

ASCII only. No em-dashes, en-dashes, or smart quotes (repo hard rule).

## Steps

1. INVESTIGATE current state. Launch parallel read-only Explore agents (one per
   theme) to map concrete OPEN candidates from ROADMAP.md / BACKLOG.md /
   WAKEUP_NOTES.md / docs/LEDGER.md and from grepping for unsurfaced / deferred
   components. Each agent returns a terse structured list and explicitly flags
   anything CLOSED / "do not re-litigate" so it is NOT planned.

2. DRAFT the session backlog. Order sessions by value x headless-safety. Each
   session = one cycle / one /clear. EXCLUDE anything that needs a live game or
   operator validation (flag flips, live producers, Haiku flips, live-game
   captures) - list those in an EXCLUDED section instead.

3. SEED the living plan: write docs/ORCHESTRATION_PLAN.md with (a) the per-cycle
   contract, (b) a session table (ID | Theme | Scope | Status OPEN|WIP|DONE |
   Commit), (c) the EXCLUDED list, (d) an empty Findings log. If the file exists
   from a prior run, reset statuses or append a new phase as appropriate.

4. WIRE the loop (idempotent - skip what is already correct):
   - ops/loop/director_prompt.md: primary work source = docs/ORCHESTRATION_PLAN.md;
     pick the next OPEN session; instruct the executor to flip WIP -> DONE + sha and
     append new findings; keep all hard rules (fanout, verifier-gate, TDD,
     py_compile, no AskUserQuestion, REGRESS-first, escalation-first, final
     done_sentinel line); UI sessions add the 5-phase audit + Claude_Preview check;
     emit NO_WORK when no session is OPEN.
   - ops/loop/loop_controller.py: the director() context must inject the full
     docs/ORCHESTRATION_PLAN.md so gemini can read it.
   - ops/loop/config.json: directive_suffix instructs commit + push to origin/main
     + /done ritual; max_cycles >= sessions + margin; dry_run=false.

5. VERIFY pre-launch: py_compile any touched .py; confirm config.json parses;
   confirm docs/ORCHESTRATION_PLAN.md session table is well-formed; full suite green.

6. COMMIT + PUSH the setup (so it survives the first /clear), then LAUNCH:
   powershell ops/loop/launch_loop.ps1 -Mode live
   This /clears THIS window and turns it into the ephemeral executor. The loop runs
   until the director emits NO_WORK (plan drained) or max_cycles. Abort by creating
   ops/loop/control/STOP. Live log: ops/loop/control/controller.log.

## Per-cycle contract (the director enforces; restated for humans)

orchestrator multi-agent fanout (disjoint-file worktree subagents in ONE message,
sole merger, run the verifier subagent on each slice before merge, merge only
green+verified) -> TDD failing test first -> py_compile before any restart -> full
pytest suite green -> UI sessions also pass the 5-phase fixture audit + a
Claude_Preview visual check vs /api/state -> commit (descriptive) -> push
origin/main -> /done ritual (docs/LEDGER.md append, ROADMAP + ORCHESTRATION_PLAN
sync) -> "C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" ops/loop/done_sentinel.py --tests <N> --regressions <0|1>. Full
authority, no user gating; auto-pick the safest option on any fork.
