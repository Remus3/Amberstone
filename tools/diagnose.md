---
description: Systematic debugging loop. Use when something is broken or behaving unexpectedly and you need to find the cause without flailing. Replaces ad-hoc investigation with a five-phase loop borrowed from mattpocock/skills.
---

You will diagnose ONE specific failure, methodically, in five phases.
Do not skip phases. Do not start fixing until phase 4.

# Phase 1 — REPRODUCE

State the failure in one sentence. Then reproduce it cleanly:
- What command / input triggers it?
- What's the smallest invocation that still fails?
- Does it fail every time? Intermittently? Only in certain states?

If you cannot reproduce it on demand, you cannot diagnose it. Stop and
ask the operator for a reliable repro before continuing.

# Phase 2 — MINIMIZE

Strip the failing case to its smallest form:
- Remove unrelated state (other coaches running, other modes, other peers)
- Remove unrelated config (env vars, flags, optional features)
- Remove unrelated input (large prompts → smallest test prompt)

Goal: the minimal repro should fit in your head AND in 5 lines of
description. If it doesn't, keep stripping.

# Phase 3 — HYPOTHESIZE

Write down 2-4 candidate explanations for what's going wrong.
For each:
- What evidence would CONFIRM this hypothesis?
- What evidence would REFUTE it?
- What's the cheapest experiment to gather that evidence?

Rank by likelihood × cheap-to-test. Pick the top one.

# Phase 4 — INSTRUMENT + TEST

Add JUST enough instrumentation to confirm/refute the top hypothesis.
Examples:
- A `_log.warning("debug: state=%s", state)` at the suspected branch
- A breakpoint via `breakpoint()` in a script you control
- A `git bisect` if the regression has a commit window
- A `print(json.dumps(envelope))` in the bridge_watcher action lane

Run the minimal repro. Did the evidence match the hypothesis?
- YES → go to phase 5
- NO → return to phase 3 with the next hypothesis

# Phase 5 — FIX

ONLY now write the fix. The fix should:
- Address the root cause, not the symptom
- Not change anything unrelated to the diagnosed failure
- Include a regression test if RC has test coverage in this area

Verify by running the original repro from phase 1. If it still fails,
the diagnosis was wrong — go back to phase 1, do not patch around it.

# Anti-patterns

- "Let me try changing this and see if it works" → no, instrument and test
- "It might be A or B or C, let me fix all three" → no, pick one, prove it
- "The fix is obvious" → still write the hypothesis; obvious fixes are
  often wrong about the actual cause
- Skipping reproduction because "I think I see it in the code" → no
