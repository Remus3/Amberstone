# Test-First Spec-to-Ship Autopilot

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

Given a batch spec, drive it strictly test-first to 100% green, then ship it.
Run end to end without checking in. ASCII only, no em/en dashes or smart
quotes in any authored byte. This is the TDD-strict sibling of `ship-batch`:
ship-batch SELECTS and implements a ROADMAP batch; this one takes a spec you
already have and proves it with derived tests before a line of impl exists.

## 0. Pin the spec + ground truth

- Restate the spec as a one-paragraph contract: exact behavior, the inputs,
  the expected outputs. State assumptions explicitly before any code.
- Source every expected number from LIVE Riot/Meraki/cdragon math, never a
  guess. Use the repo's existing UA-aware data path (`tools/daemon_slayer_extract.py`,
  the vendored `data/daemon_slayer/<patch>/items_meraki.json`,
  `core/augment_external_source.py`). raw.communitydragon.org 403s a UA-less
  urllib request - do not hand-roll a fetch.
- NO hardcoded magic numbers: a test asserts `engine(x) == formula(x)` where
  `formula` is the Riot/Meraki expression evaluated in the test, not a literal
  pasted constant. NO fragile cross-item comparison asserts (never
  "item A dps > item B dps"); assert on the computed quantity itself.

## 1. RED - scaffold the tests first

- Write the failing tests BEFORE implementation, in `agents/daemon_slayer/tests/`
  (follow the existing `test_*_sNNN.py` / `test_*_pipeline_*.py` naming).
- Prefer property/derivation tests: recompute the expected value from the
  formula for several levels / stack counts / target states and assert the
  engine matches each. Pin boundary cases (level 1, level 18, 0 stacks, max
  stacks) where the formula has known exact values.
- When stubbing a method accessed via the class, wrap it with `@staticmethod`
  correctly.
- Run the new tests and CONFIRM THEY FAIL for the right reason (RED). A test
  that passes before implementation is not testing the spec.

## 2. GREEN - loop Edit / pytest

- Implement the minimal change to satisfy the spec.
- Loop: `python -m pytest agents/daemon_slayer/tests/<new>.py -q` -> Edit ->
  repeat until the new tests pass.
- Then the FULL gate, which must be 100% green with zero regressions: ONE
  gated parallel run over both trees (the TIER TABLE in `tools/done.md`; the
  DS baseline is ENGINE-pinned - know the current passed + subtests count and
  do not drop it):
  `python ops/fleet_kit/fleet_suite_gate.py run --owner <id> -- python -m pytest tests agents/daemon_slayer/tests -q -n 8 --dist loadfile --timeout=300`.
- Do not weaken a real assertion to get green. If a prior pin legitimately
  moved because the spec corrects it, rebaseline it deliberately and say so
  in the commit; never silently.

## 3. Ship

- `python -m py_compile` every changed `.py` (silent crash under pythonw.exe
  otherwise).
- Single ENGINE_VERSION bump in `agents/daemon_slayer/__init__.py` (semver:
  minor for a feature/correctness batch, patch for a pure fix) + sweep every
  pinned `ENGINE_VERSION == "<old>"` guard assertion (about 14, in
  agents/daemon_slayer/tests/test_*; the pin IS the guard - a stale pin fails,
  proving the bump was deliberate). Re-run the gated dual suite above once,
  fully green.
- Conventional commit naming the spec + ENGINE delta; push origin main.
  Confirm the pre-commit reports py_compile OK.
- Verify live: `RC-DaemonSlayer` task is NOT supervisor-watched - restart it
  (`schtasks /End /TN RC-DaemonSlayer` then `/Run`; hard fallback
  `taskkill /F /PID <:8860 pid>` then `/Run`; never `Stop-Process`) and
  confirm `curl -sk http://127.0.0.1:8860/health` serves the new
  engine_version. If RC core changed: `echo restart > restart_trigger.txt`
  then verify `ops/runtime/health.json` (new pid, alive, last_reload_ok).
- Sync living docs on the ENGINE bump (CLAUDE.md / docs/DAEMON_SLAYER.md /
  README: version + test count; do not rewrite dated ledgers).
  Append a WAKEUP_NOTES.md hand-off (last 2-3 sessions full, archive older).
  `/done`.

## Mirror discipline

Canonical copy is the tracked `tools/test-first-autopilot.md`. The gitignored
`.claude/skills/test-first-autopilot/SKILL.md` and
`.claude/commands/test-first-autopilot.md` are byte-identical ASCII mirrors of
it (tracked tools/ wins; never let a `.claude/` copy diverge or re-inject
non-ASCII). Re-mirror after any edit.
