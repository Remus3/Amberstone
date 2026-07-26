---
description: Root-cause-first TDD loop for any bug or data fix. Forces a failing reproduction test BEFORE touching production code, a deliberate grep for every sibling case sharing the same root cause, then the minimal fix, then an explicit corrupted-data backfill check. Use whenever a bug is reported or a data/pollution/scorer fix is needed - it converts a too-narrow first attempt into a provably-complete one.
---

> **SUBAGENT-FIRST (standing protocol, operator 2026-06-20).** Always use subagents for substantive work; do not build solo in the main thread.
> 1. **Spec first:** a Plan/design subagent (or the Gemini director) emits the spec/plan BEFORE any code; verify it vs ground truth (grep cited file:line, live `/api/state` + `ops/runtime/health.json`, git) - never scaffold on assumptions.
> 2. **New session:** interview the Gemini director (or the operator if Gemini is down) for intent + acceptance criteria, re-probe live state, THEN build.
> 3. **Act via subagents:** worktree-isolated build agents on disjoint files (sole merger) + a read-only `verifier` subagent gate before any merge or "done".
> 4. Trivial one-line cosmetic edits may inline (refines R9). See `CLAUDE.md` "Subagent-First Protocol" + memory `feedback_subagent_first_protocol`.

The recurring failure mode here is the too-narrow first fix: a wrong or single-case hypothesis that ships, then needs a second comprehensive pass (item 208 marksman pollution missed Golden Spatula + duplicate paths -> item 213 cleanup; item 211 race guard left corrupted rows -> two backfill rounds). This loop prevents that. Run the steps in order; do not skip step 1 or step 2.

### 1. Reproduce BEFORE fixing (RED)

- Do NOT start by editing production code. Write a failing test that reproduces the exact reported symptom first.
- Run it and confirm it FAILS for the stated reason (a test that passes immediately proves nothing). Read the failure output from a file if the stdout pipe is unreliable.
- This locks the symptom and gives you the proof-of-fix oracle.

### 2. Find every sibling case (the anti-narrow step)

Before writing any fix, find ALL entities that share the root cause - this is where narrow fixes die:

- Grep the codebase for the same pattern: other champions, other game modes (sr/aram/arena), duplicate data paths, all coach prompts, every consumer of the buggy function.
- For a data/pollution bug: query the data for every row/entry matching the bad shape, not just the one reported.
- Add a failing test (or a parametrized case) for each distinct sibling you find. The fix is not scoped until the sibling sweep is done.
- Record the sibling list explicitly in your working notes so the fix's completeness is auditable.

### 3. Implement the minimal fix (GREEN)

- Write the least code that turns every red test (the reproduction + all sibling cases) green.
- Prefer fixing at the single chokepoint (the load-time / single-source layer) over patching each consumer - item 238 corrected abilities at load time so all scorers saw the fix uniformly, rather than per-consumer patches.
- Re-run the full relevant suite fresh and confirm zero regressions. Verify counts against ground truth (see CLAUDE.md Verification Discipline) - never trust a stale or subagent-reported green.

### 4. Backfill already-corrupted state (do NOT stop at prevention)

- A fix that only prevents FUTURE occurrences is half done if existing data is already wrong.
- Explicitly ask: did this bug already corrupt rows / files / cached state? If yes, write + run the recovery/backfill pass in the SAME change and verify the historical rows are corrected live (item 211: gameId-keyed ingest guard + a separate backfill tool + Match-V5 recovery for orphans).
- If no historical corruption is possible, state that explicitly so the absence of a backfill is a decision, not an oversight.

### 5. Report completeness

State which sibling cases you proactively covered, the exact fresh pass/fail counts you observed, and whether a backfill was needed + run. "Fixed the reported case" is not the deliverable; "fixed the root cause across all N sibling cases + recovered M corrupted rows" is.
