---
description: End-of-session ritual - auto-commit any pending changes, push, do the /wrap checks, rewrite RC-NEXT-SESSION.txt carrying forward every unacted item, then print ONLY "Done ritual complete, safe to clear". Use when work is wrapped and you want a clean exit.
---

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

> **PATHS (MAIN 2246 ORDER section 3).** No machine path is written in this file. `<repo>` = this tree's MAIN checkout root (in the main session it is the cwd; from a worktree, the parent of `git rev-parse --path-format=absolute --git-common-dir`). `%LOCALAPPDATA%` / `%USERPROFILE%` expand per account (`$env:LOCALAPPDATA` in PowerShell, `$LOCALAPPDATA` in Git Bash). `%USERPROFILE%/.claude/projects/<project-slug>/` = Claude Code's project dir for this checkout (`core/claude_project.py` `project_dir()`; under the account's own config dir when `CLAUDE_CONFIG_DIR` is set).

The user wants to end the session cleanly so the next one starts with a fresh context window. This is /wrap, but with auto-commit instead of "stop and ask". Run all sections in order - in the ONE dispatched executor below, never in the main session.

> **/done DISPATCH PROTOCOL (FLEET-KIT v10; MAIN 2026-10-08 0839 ORDER step 4).** The WHOLE ritual - sections 0 through 10 - runs in ONE sub-agent, the /done EXECUTOR. The main session runs none of it.
> - **Main session, before the dispatch (no Bash / PowerShell / Read / Edit / Write / Grep / Glob):** stop the monitors IT armed this session (TaskStop - section 3's monitor half; TaskStop is not a hooked tool). Note the background agents and commands still running, and do NOT stop them (FLEET-COMMON banner). Then launch ONE sub-agent (Agent tool, general-purpose, NOT worktree-isolated: it commits and pushes the main checkout) whose prompt carries what only the main session knows: the session number `<n>`; this session's `Session <n> checklist` with every task marked done (and what was read back) or not done; the in-flight agents / commands with their progress-file paths; and every steer, operator instruction or decision made in chat that the hand-off must carry. The prompt ends: "You are the /done executor. Run tools/done.md sections 0-10 in order yourself; never re-dispatch the whole ritual. Your FINAL message is exactly one line: `Done ritual complete, safe to clear` or `/done stopped: <reason>`."
> - **Main session, after:** wait for the executor's completion notification and relay its final line VERBATIM as the only chat output - nothing before or after it. If the executor ends without one of those two lines, relay `/done stopped: done executor returned no final line`.
> - **The executor:** runs every section below itself. It may fan out its own helpers (a `verifier`, a background CI watch), but it owns the ritual and its final line. Section 3 covers the tasks IT started; the main session's in-flight work arrives in the prompt and goes into the hand-off as in-flight. Section 9's done marker and the one line are its last acts.

> **CHAT OUTPUT CONTRACT (FLEET-KIT v3 items 2, 3 and 5; operator order 2026-10-03).**
> /done's ONLY chat output is the single line `Done ritual complete, safe to clear`,
> or, when something stopped the ritual, one line `/done stopped: <reason>` instead -
> the executor's final line, relayed verbatim by the main session (DISPATCH PROTOCOL above).
> No banner, no review, no recap, no checklist, and NEVER the hand-off or a
> next-session prompt in chat. The LAST act before that line is the kit done
> marker `python ops/fleet_kit/fleet_done.py mark --session <n> --status done`
> (FLEET-KIT v9 item 15; section 9). Everything a section below used to "surface" or
> "report in the banner" goes into `RC-NEXT-SESSION.txt` (section 10) instead.
> Run long steps (CI watch, suites) as background commands so the pane shows only
> the compact summaries.

> **SESSION CHECKLIST (FLEET-KIT v7 item 13; operator order 2026-10-05, relayed by MAIN).**
> `/done` is the LAST line of every `Session <n> checklist` and RUNS UNPROMPTED once no
> other task remains - the session invokes it itself; the operator then only clears.
> The "no checklist" above is about /done's OWN output: it prints no checklist, review
> or recap, only the one completion line. The session counter is the `SESSION: <n>`
> line in `RC-NEXT-SESSION.txt` (owner: `tools/session_checklist.py`); section 10
> writes `SESSION: <n+1>`.

> **SHAPE (measured 2026-07-26, LEDGER 1065; push CI reshaped 2026-10-09 by W-A, LEDGER 1706; section 2c re-ruled 2026-10-22, session 126).**
> This ritual is FOUR PHASES, and the ordering is load-bearing rather than cosmetic:
> **Phase 1** the fast local gate (section 0-0b, target 60-90s) -
> **Phase 2** commit + push, which fires CI's fast guards plus an IMPACT SLICE (sections 1-2), then at most ONE full-suite dispatch when nothing else covers the pushed tree (section 2c) -
> **Phase 3** all the paperwork WHILE CI runs (sections 3-7) -
> **Phase 4** collect CI, write the hand-off file, print the one completion line (sections 8-10).
>
> **What the push path really runs (read from `.githooks/pre-push` and `.github/workflows/ci.yml`; re-read both before editing this block).** The local pre-push hook runs NO tests: the identity gate, the sibling-name sweep, the credential scan, then the LFS upload. On GitHub, a push to main that changes any non-`.md` path runs the `check` job's fast guards plus the test modules `tools/ci_impact_selector.py` maps to the changed paths (the impact slice); the selector ESCALATES the push to the full dual suite only when it cannot see the coupling (conftest / pytest.ini / dependency pins / the workflow / the selector itself / an unresolvable push base / more than 300 changed paths). A `.md`-only push runs no `ci` at all (`paths-ignore`); `docs-guards.yml` is its complement. The full dual suite runs on pull_request, on workflow_dispatch, on an escalated push and in the nightly schedule. A slice is NOT the suite: coupling the source never spells is invisible to the selector map (RM-734 datum: the slice missed `tests/test_atomic_write_guard_rm258_rm261.py`).
>
> **Why the overlap:** the old shape ran a ~27-minute local dual suite and THEN blocked on a CI watch, with ~15 minutes of doc writing after that. Pushing at Phase 2 makes the paperwork overlap the push run (13-28 minutes on 2026-10-22's slice pushes), so the wrap costs the LONGER of the two instead of their sum.
>
> **RM-157 still forbids DUPLICATES.** Until 2026-08-04 section 2c fired `gh workflow run ci.yml` on every /done while every push already ran the full suite. MEASURED over 2026-08-01..04: 18 such dispatches, **485.8 minutes of runner wall clock in four days for zero added signal**. The waste was the duplicate, not the dispatch: section 2c now fires one only when no full run covers the pushed tree, and never a second one.
>
> **Do NOT reintroduce a SERIAL local dual suite into Phase 1.** It was measured
> and it does not have a slow minority to trim: the slowest 40 tests are only
> **10.7%** of wall clock and the mean is 71ms across 23,250 tests, so the cost
> is broad, not concentrated. For Tier-0/1 work the targeted slice plus the push
> CI run (and section 2c's one dispatch, when it fires) is the replacement, not a
> shortcut. A Tier-2 session's whole suite is the TIER TABLE's ONE gated parallel
> run (below), by its merger; /done runs it only when no such run already covers
> the tree being committed.

> **TIER TABLE (MAIN kit-v13 ORDER section 2, PERF-AUDIT items 3-4, 2026-10-09). The ONE tier table: every command doc points here instead of restating a suite policy.** Every suite runs from the REPO ROOT; never `pytest .`.
> | Tier | Change | What runs | Who |
> |---|---|---|---|
> | Tier-0 | cosmetic, docs, comments, strings | `py_compile` only (the PostToolUse hook `tools/pytest_guard.py`, which never runs a suite); no restart | anyone |
> | Tier-1 | one module / local logic | `py_compile` + ruff on authored files + the touched modules' test FILES named on the command line (naming files needs no gate) | the slice agent |
> | Tier-2 | schema / engine / scorer / item-effect / `ENGINE_VERSION`, or a merged multi-slice wave | the full dual suite ONCE, on the final merged tree, through the gate (command below), plus the DS `:8860` restart for engine work | the merger only - a slice never runs a whole suite |
> | Verifier | any done-claim | re-runs ONLY the test files the claim cites, plus `python -m pytest <cited paths> --collect-only -q` for counts; never a whole suite | the read-only `verifier` |
>
> Tier-2 command, one gated run over both trees (`<id>` = your claims owner id, RACE GUARDS block; `python` = the canonical interpreter in CLAUDE.md "Paths", which carries pytest-xdist and pytest-timeout): `python ops/fleet_kit/fleet_suite_gate.py run --owner <id> -- python -m pytest tests agents/daemon_slayer/tests -q -n 8 --dist loadfile --timeout=300`. A DS-only or `tests/snapshot_panels/` pre-merge run uses the same gate and flags with that one path. Run that command directly, never through a helper that polls its output: write the output to a FILE and print the summary line AND the exit code in the SAME launch call (shape: `<that command> > <file> 2>&1; echo "EXIT=$?"; tail -n 3 <file>`; RM-736 ruling, session 126: a graded count must appear in the output of the call that ran it), then assert on both: a crashed xdist run leaves no summary, and a FAILED count over it reads 0. Serial whole suites are RETIRED: 27m22s serial against 2m24s at `-n 8` (MAIN measure 2026-10-08), and a serial run held one of the machine's 2 suite slots for ~45 minutes. xdist is not new: CI's `check` job has run `-n auto --dist loadfile` since 2026-07-27, when the six shared-state failures that once made `-n 8` untrustworthy were fixed rather than suppressed (the comment above that step in `.github/workflows/ci.yml` records it).
>
> **CI `check`-job steps the gated suite never runs (RM-790; session 126: `c6bbd1577` went red at the DS index step after a green local Tier-2 run, fixed forward in `376443c8a`).** A green TIER TABLE run is not all of CI. Before the push, run the steps the change touches:
> - **DS data change** (anything under `data/daemon_slayer/`, or `tools/ds_feed_index.py`): `python tools/ds_feed_index.py --write`, commit `tools/ds_feed_index.json` with the data, then `python tools/ds_feed_index.py --check` (exit 0 = in sync, 1 = drift).
> - **Build-order tables** (`data/daemon_slayer/build_orders/`): the "shipped build-order tables" step's test files with `RC_REQUIRE_BUILD_ORDER_TABLES=1`, which turns a skip into a failure.
> - **Hooks** (`.githooks/`, `scripts/install_hooks.py`): the "git hook gate" step's test files with `RC_REQUIRE_HOOK_GATE=1`.
> - **Trees outside the dual suite:** `tools/tests` and `oss/win32_atomic_io/tests`, each in its own process, when their code or anything they import changes (the DS extractors included).
> - **Whole tree:** `ruff check .`, the py_compile sweep, and the hashed-install check against `requirements.in` after a dependency change.
> This list is derived from the `check` job: `tests/test_done_md_push_ci_shape.py` fails when ci.yml gains a step of these kinds that this table does not name. Read the job itself when in doubt.

### 0. Local check gate - commit only when green

**Pre-flight (FLEET-KIT v7 item 13): every checklist task done or carried into the hand-off.** Walk this session's `Session <n> checklist`: each task is either done (read back) or copied into the section-10 hand-off as an open item. None is dropped.

**Pre-flight: hand-off size - BEFORE any commit or push (FLEET-KIT v18 fail mode).** Since kit v18, section 9's `fleet_done.py mark --status done` FAILS on a hand-off over 30720 bytes (`HANDOFF_WARN_BYTES` = 30 KB in `ops/fleet_kit/fleet_done.py`; the raw on-disk size of `RC-NEXT-SESSION.txt`). The mark is the LAST act, so without this step the cap is met only after every commit and push. So, here:
1. Draft the section-10 hand-off now (carry-forward rule included) into its temp file and measure it: `wc -c <tmp>`.
2. Run the kit's archive dry run from the repo root: `python ops/fleet_kit/fleet_done.py archive` (writes nothing; prints `archive dry-run: would move N block(s) to docs/handoff-archive/RC-<YYYY-MM-DD>.txt (<before> -> <after> bytes)`). It moves only framed CLOSED blocks: a rule line of 20+ `=`, a heading starting `CLOSED` (or containing ` - CLOSED`), a second rule; no open word (NOT CLOSED, STILL OPEN, OPEN ITEM(S), CARRIED, CARRY FORWARD, TODO, NEXT ACTION, WAITING, BLOCKED, PENDING) in the body; the first closed block in the file is kept (`--keep 1`). When it would move blocks the hand-off needs, `python ops/fleet_kit/fleet_done.py archive --apply` moves them (archive written and read back first).
3. If the hand-off as about to be written is still over 30720 bytes, run `python ops/fleet_kit/fleet_done.py mark --session <n> --status failed --reason "hand-off over 30 KB"` and stop with `/done stopped: hand-off over 30 KB` - no commit, no push. Trim it first (history VERBATIM to `docs/handoff-archive/RC-<YYYY-MM-DD>.txt` in the kit's format, duplicates to pointers, every unacted item still carried), then re-run /done.

**First, peek for a queued Mission Control intent** (shortcuts 1 + 2, S3). The done ritual IS the safe boundary a queued intent waits for:

```
python tools/session_intent.py --peek
```

`{"pending": null}` - nothing queued, run the ritual as normal. A pending `halt_save` or `done_continue` means the operator fired the dashboard button while this session was mid-turn: finish the current step, run the whole ritual, and consume it in section 10. Never abandon work to service an intent - a queued intent never kills anything.

**Then drain the steer channel** (S7). The done ritual is the SAFE BOUNDARY a NOTE waits for, so this is where queued guidance gets read:

```
python tools/session_steer.py --drain --format text
```

`(no steers pending)` and exit 1 - nothing queued, carry on. Otherwise each line is free-text guidance the operator sent while this session was running. A steer is GUIDANCE, NOT A COMMAND: it executes nothing, it never killed anything, and it is not an instruction you must obey blindly - read it, record in the hand-off file what it said and what you did about it, and carry anything still open into `RC-NEXT-SESSION.txt` in section 10. Draining advances a cursor; the log itself is append-only and stays as the audit trail.

Versioning is cheap; lost work is not. The operator never passes up a commit + push. So the DEFAULT is: always commit + push when local checks are green. Do NOT leave authored work uncommitted at session end just because a change feels small or unfinished - if it passes its checks, it ships.

- Identify the files authored this session: `git -C "<repo>" status -s`.
- Run the cheap local gate on the touched surface:
  - `"%LOCALAPPDATA%\Programs\Python\Python314\python.exe" -m ruff check .` (must report ALL CHECKS PASSED)
  - `"%LOCALAPPDATA%\Programs\Python\Python314\python.exe" -m py_compile <each touched .py>` (syntax - silent-crash guard per CLAUDE.md hard rule)
  - **Authored-source hygiene (ALWAYS run, every /done - this is the same step CI runs):** `"%LOCALAPPDATA%\Programs\Python\Python314\python.exe" -m pytest tests/test_smart_quote_hygiene.py tests/test_mojibake_hygiene.py tests/test_u2500_hygiene.py -q`. Must be green. No smart quotes / em-en dashes / NBSP / ellipsis / mojibake / U+2500 in authored source. If this fails, it is NEVER "pre-existing / unrelated / not in CI" - it is in CI now; fix it (`"%LOCALAPPDATA%\Programs\Python\Python314\python.exe" tools/strip_smart_quotes.py --apply` for smart-quote/dash drift) before the gate is green.
  - Test slice covering the change, per the TIER TABLE above: **the targeted modules' test files** (Tier-1). For a Tier-2 session (engine touched, schema, ENGINE_VERSION), the TIER TABLE's ONE gated parallel dual-suite run - skip it when the session's merger already ran it on the tree being committed, and never run a LOCAL whole suite for Tier-0/1 work: the push CI impact slice plus section 2c's one dispatch (fired only when no full run covers the pushed tree) stand in for it. Measure suite sizes with `pytest <path> --collect-only -q`, never from a recited figure, since suite counts are unguarded and this line said "9932 tests in ~115s" until 2026-08-16. **Run any suite from the REPO ROOT** - running the DS suite with cwd `agents/daemon_slayer/` yields 13 FALSE failures whose names read like registry regressions (CWD-relative registry opens plus two ASCII-hygiene tests). See memory `reference_ds_suite_run_from_repo_root`.
- **Any WHOLE suite run locally** (here or anywhere in this ritual; a verifier never runs one, per the TIER TABLE) goes through the kit's machine-wide suite gate (FLEET-KIT v12, FLEET-COMMON item 16 c): `python "<repo>/ops/fleet_kit/fleet_suite_gate.py" run --owner <id> -- <suite cmd>`, where `<suite cmd>` is the TIER TABLE's parallel `-n 8 --dist loadfile` form, never a serial one. A slice that names its test files needs no gate. `<id>` is your claims owner id (RACE GUARDS block above); exit 3 = no slot in time or another live agent's uncommitted edit straddles the run - wait, never bypass.
- Ground truth, not memory (per CLAUDE.md Verification Discipline): run the gate FRESH this turn, read the pass/fail counts you observe now, and `ls` any test file you cite as added - never carry forward a prior or subagent-reported green. If the work came from parallel slices, the `verifier` subagent's CONFIRM is the gate, not the slice agent's claim.
- GREEN: proceed to section 0b, then commit (section 1).
- RED: fix and re-run. If the failure is pre-existing and unrelated to this session's work, record it in the hand-off file (section 10) and commit only the green-verified authored files - never commit over a regression you introduced.


### 0b. Drift guard - the check that saves the cleanup sessions

```
"%LOCALAPPDATA%\Programs\Python\Python314\python.exe" "<repo>/tools/drift_guard.py"
```

After an ENGINE bump, pass the version you bumped FROM so the anchor sweep runs:

```
"%LOCALAPPDATA%\Programs\Python\Python314\python.exe" "<repo>/tools/drift_guard.py" 1.258.0
```

Runs in well under a second and exits 1 on any breach. It checks doc-size budgets, `tools/*.md` vs `.claude/commands/*.md` mirror parity, memory-index integrity, stale version anchors (HTML included), self-inconsistent counted claims, and authored files git is not tracking.

**Every check exists because that exact drift ACTUALLY HAPPENED here and later cost a whole dedicated session** - ROADMAP silently breaching its CI budget and sitting over it, two copies of THIS file diverging for a month while preserving a decommissioned instruction, 27 orphaned docs, 11 command docs with zero version control, a fourth ENGINE anchor site found only 25 minutes into a CI run. Detection is seconds; repair is a session. Fix what it reports NOW rather than letting it accrue - that is the entire point of the guard.

Do NOT silence a breach by loosening the check. If a finding is genuinely a false positive, fix the check and add a case to `tests/test_drift_guard.py` (which asserts both the breach and the clean path for every check, so a check cannot silently degrade into always-passing).

### 1. Auto-commit any pending changes

**Reap merged worktrees - before this section's commit (FLEET-KIT v22 KIT-V22-REAP; MAIN 2026-10-25 1926 ORDER step 5).** Run from the repo root:

```
python ops/fleet_kit/fleet_done.py reap --apply
```

It removes only a linked worktree that can lose nothing (`git worktree remove`, never --force; `git branch -d`, never -D) and LISTS every other one with its reason; listed worktrees stay. Keep its summary line for the section-10 hand-off. A reap failure is a hand-off line, never a ritual failure.

- `git -C "<repo>" status -s`
- If output is empty: skip to section 2.
- Otherwise:
  - **Audit before staging**: refuse to auto-commit any path matching `*SECRET*`, `*HANDSHAKE*`, `*PIVOT*`, `*REPLY*`, `*TOKEN*`, `*KEY*`, `.env*`, `local_paths.json`, `API-Key-Claude.txt`, or anything that looks like credentials. If matched: stop and ask the operator before proceeding.
  - **Frozen-file guard**: per `CLAUDE.md`, several files require explicit user approval before editing. If any modified path is in the frozen list, stop and ask - auto-commit is too dangerous here. Frozen list lives at the top of CLAUDE.md.
  - Stage only the changes you authored this session (`git add <specific files>`). Do NOT use `git add -A` - accidentally commits .env / runtime junk.
  - Draft a one-line commit message summarising the session's work (1-2 sentences, "why" over "what"). If multiple distinct themes: list them as bullets in the body.
  - **Do NOT add a `Co-Authored-By: Claude` trailer.** Operator policy 2026-06-03: this repo
    never emits one. `.githooks/commit-msg` STRIPS any `^Co-Authored-By: Claude` line before
    the subject is validated, so adding one is a silent no-op, not a choice - it is removed
    whether or not you meant it. A harness whose own instructions add the trailer by habit is
    fine; the hook absorbs it. Do not spend a line of the message on it, and do not "restore"
    it when you notice it missing from a prior commit - that absence is the policy working.
    (This instruction previously said to add the trailer "the RUNNING HARNESS specifies", and
    before that hardcoded `Claude Opus 4.7 (1M context)`. Both were wrong in the same
    direction: prose describing a step the tooling deletes. Verify against `.githooks/` before
    re-editing this line.)
  - **Commit through the tree's git lock** (FLEET-KIT v12, FLEET-COMMON item 16 a): write the message to a tmpfile (ASCII), then `python "<repo>/ops/fleet_kit/fleet_gitlock.py" run --owner <id> -- git -C "<repo>" commit -F <tmpfile>`. A bare `git commit` is denied by the claims hook. Exit 3 = the lock, a leftover index.lock, or a staged path another live agent claims refused the run (its stderr line says which): wait or unstage that path, never bypass.
  - If pre-commit hooks fail: fix and create a new commit (never `--amend`).

### 2. Push

- `git -C "<repo>" log @{u}.. --oneline` - list local commits not on origin.
- If empty: skip.
- Otherwise: `python "<repo>/ops/fleet_kit/fleet_gitlock.py" run --owner <id> -- git -C "<repo>" push origin <branch>` (the git lock, FLEET-KIT v12 item 16 a; a bare `git push` is denied). No confirmation prompt - pushing is part of the exit ritual.
- Record the push range (e.g. `23854e1..b56f247 main -> main`) in the hand-off file, not in chat.
- Then `python "<repo>/tools/bot_merge_check.py"` (MAIN ORDER 2026-10-19-0034; a merge done on GitHub bypasses every local hook): exit 1 = a non-operator / bot identity or a `Co-authored-by:` line reached the default branch. Record it as the hand-off's FIRST next action (fix only with `fleet_rewrite.py` under MAIN 2312's scope, at the halt boundary); it never fails the ritual.
- If the push fails (auth, conflict, hook): stop with `/done stopped: push failed - <cause>`.

### 2b. GitHub CI verification

- **Do NOT block here.** This is Phase 2; the CI run is collected in section 8c after the
  paperwork is done. Just capture the run id so 8c can find it.
- Note the push-triggered `check` run for the pushed SHA:
  - `gh run list --branch <branch> --limit 1` to find the run id (gh = `C:/Program Files/GitHub CLI/gh.exe`; use the absolute path in older shells).
- Record the CI result in the hand-off file: `green | red | pending`.
- If CI goes RED on a real test/lint failure: record the failing job in the hand-off file as the FIRST next action ("resolve CI <job>"). The local gate (section 0) should have caught it, so a red here usually means an env-only delta - investigate before declaring the session cleanly wrapped.
- Do NOT block /clear on flaky-infra red, but do NOT silently ignore a genuine failure either.

### 2c. At most ONE full CI run, only when nothing covers the pushed tree (ruled 2026-10-22, session 126)

The section-2 push ran the fast guards plus the impact slice, not the full dual suite (SHAPE above), and the nightly that does run it blocks nothing and can land a day later. So, straight after sections 2 and 2b and before section 3, check whether a full dual suite already covers HEAD, and dispatch ONE when none does. Every input is read, never assumed.

1. **Candidates.** (a) The head commits of the latest full CI runs on main - any status except cancelled; a red one still covers, and its failure is what the hand-off records:

```
for ev in schedule workflow_dispatch; do gh run list --workflow ci.yml --branch main --event "$ev" --limit 5 --json headSha,conclusion --jq '.[] | select(.conclusion != "cancelled") | .headSha'; done
```

   (b) the section-2 push's own head, when `python tools/ci_impact_selector.py --base <old> --head <new>` over that push range prints `mode=full` (the push escalated); (c) the commit of any graded local TIER TABLE run this session - not VOID (no WinError 1455 / MemoryError), its summary line and exit code printed in its own launch call; the dispatch prompt names it.
2. **Covered** when, for at least one candidate `<c>`, `git -C "<repo>" diff --quiet <c> HEAD -- . ':(exclude)*.md' ':(exclude)RC-NEXT-SESSION.txt'` exits 0 (the trees differ at most in docs and the hand-off, which `ci` ignores or `docs-guards` covers). Then do NOT dispatch; write `full suite: covered by <c> (<run id> | local <file>)` into the hand-off.
3. **Not covered:** run `gh workflow run ci.yml --ref main` ONCE, then `gh run list --workflow ci.yml --event workflow_dispatch --limit 1 --json databaseId,headSha,status` and confirm its `headSha` is HEAD (a dispatch builds the branch tip at trigger time). Write `full suite: dispatched run <id>` into the hand-off. A dispatch runs the `check` job's fast guards plus the full dual suite once (`ci.yml` EVENT MATRIX), in its own concurrency group (RM-370), so a later push neither cancels it nor is cancelled by it.

- **Never a second dispatch in one /done.** The two no-`ci` cases below are never a reason to dispatch either.
- **This is not RM-157 coming back.** RM-157 retired an UNCONDITIONAL dispatch that duplicated a push run already running the full suite (18 runs, 485.8 runner minutes in four days, zero added signal). Since W-A (LEDGER 1706, 2026-10-09) a push runs a slice, and step 2 fires the dispatch only when no full run covers the tree. `ci.yml` names workflow_dispatch "the merge/batch cadence"; this is that cadence at the session boundary.
- **It never blocks the wrap.** A full run takes 20-55 minutes on the runner (nightly 2026-10-17..22: 20m57s .. 55m39s); the paperwork takes ~15. Section 8c collects it only if it has finished; otherwise the hand-off records `pending <run id>` and the next session's first act is `gh run view <run id>`.
- **It is off the box, so the local suite rules do not apply to it.** "Never a LOCAL whole suite for Tier-0/1 work" is about this machine (memory: RM-737 / RM-755; xdist stall: RM-754). A dispatch is not a local suite and is not a licence for one.
- **`docs-guards` was measured in the same pass and the answer is LEAVE IT ALONE.** It has the largest run COUNT (109 push runs) but is the smallest job: **178.8 min, avg 1.6** - 8.4% of the total, and it is the only thing watching a docs-only push. That is not where the minutes go; do not "optimise" it on run count.
- **`CodSpeed` was measured too (62 runs / 77.7 min, avg 1.3 - 3.7%) and the verdict "leave it alone" was SUPERSEDED on 2026-09-06: the workflow and the `benchmarks/` tree are DELETED.** Minutes were never the reason - it was dropped because it benchmarked `item_advisor.py` and `composition_advisor.py`, which took 3 and 1 commits in 90 days, while `agents/daemon_slayer/` took 310 and had no perf coverage at all. A perf gate on static code is green by construction. Full reasoning in docs/OPERATIONS.md "Why CodSpeed was dropped". **Do not re-add it** as a minute-saver reversal; the minute argument was the one thing that never applied.
- **Two cases genuinely run no `ci` at all, and neither is a reason to dispatch.** A docs-only push is skipped by `ci.yml`'s `paths-ignore: '**/*.md'`, and `docs-guards.yml` is its purpose-built complement (selector-derived, pinned by `tests/test_ci_docs_guard_coverage.py`) - a full suite adds nothing that a .md-only commit could have broken. A push to a NON-main branch with no PR matches neither `ci.yml` trigger, and a `--ref main` dispatch there would test main rather than your branch, so it is worse than useless. Open the PR instead.
- The ~142 tests that SKIP on Linux (Windows paths, PowerShell, scheduled tasks) are the residue CI cannot cover. If this session's work was in that surface, run those locally rather than trusting the CI green.
- **Billing.** The repo is PUBLIC (read back 2026-10-22: `gh repo view --json visibility`), so standard-runner minutes are not metered. It was private when this section was first written and once tripped its spending limit; if it goes private again, a 2-3 second "failure" carrying a "job was not started" annotation is the spending limit, not the code (memory `reference_ci_billing_fastfail`).

### 3. Background tasks started this session

- TaskList - find anything still running (do not print it). In the executor this lists the tasks IT started; the main session's in-flight work came in the dispatch prompt (DISPATCH PROTOCOL above).
- Monitors / watchers armed: TaskStop. DO NOT leave monitors armed; they're useless after /clear. The main session stopped its own before the dispatch; the executor stops any it armed.
- A still-running build agent or long command is NOT killed to end the session (FLEET-COMMON banner: never stop or kill running work to look at it). Record it in the hand-off file as in-flight, with its progress file path if it has one - including every in-flight item the dispatch prompt named.


### 5. RC restart pending

- Check `<repo>/restart_trigger.txt` - if non-empty, RC may still be reloading. Confirm `ops/runtime/health.json` shows `alive=true` AND `last_reload_ok=true` before declaring done.

### 6. WAKEUP_NOTES update

- The next session will bootstrap from `<repo>/WAKEUP_NOTES.md` + `MEMORY.md` + git log. Make sure tomorrow-you can pick up cleanly.
- Append a short entry (<=20 lines) describing this session's work: commits shipped, key decisions, what's next. Don't rewrite history; just append.
- Note explicitly any blockers or things tomorrow-you should NOT redo (e.g. "lobby pill fix already shipped in bb4cff9 - don't re-investigate").

### 6b. Living-doc sync (ROADMAP / CLAUDE.md / README)

Update the three living docs based on what shipped this session. These are surgical edits - never full rewrites.

**ROADMAP.md**
- Find any item that shipped this session: flip its marker from `[!]` to `[x]` and append the commit short-SHA in parentheses.
- Add new `[!]` entries for anything that's now next or in-flight.
- Do NOT touch items that are already `[x]` or haven't been worked on.

**Per-item completion ledger -> `docs/LEDGER.md` (NOT CLAUDE.md)**
- Append the new item entry at the TOP of the `docs/LEDGER.md` body (newest-first), in the existing entry format.
- CLAUDE.md "Active priorities" is now a STATIC POINTER - do NOT add item entries to CLAUDE.md (CI size-budgeted < 60KB).
- In CLAUDE.md touch only the `### Settled` summary or the one-line DS reference when relevant - never the ledger.

**README.md**
- Update only if something structural changed (new endpoint, new panel, new agent). Light-touch: one bullet or badge line at most.
- If nothing structural changed: skip entirely - don't update the README just to say you ran /done.

**Standalone plan docs**
- If a standalone `docs/DS_*_PLAN.md` (or any similar one-off plan doc) COMPLETED this session, fold it to its done-state or move it under `docs/_archive/` - otherwise it keeps reading as pending work to the next session.

**docs/DAEMON_SLAYER.md + docs/ARCHITECTURE.md changelogs**
- Changelog: newest first, ONE line per ENGINE bump - never append to a prior version's line. On an ENGINE_VERSION bump, prepend a new bullet to the DAEMON_SLAYER.md `## Changelog` section (one bullet per ENGINE version); do NOT extend an existing version's bullet. Bump the short status header (ENGINE_VERSION + test count + patch) in the same edit.
- ARCHITECTURE.md keeps a short DS summary + structural bullets + a `see docs/DAEMON_SLAYER.md changelog` pointer - do NOT paste the per-version narrative there. Appending to a prior version's line is what produced the unreadable single-line megastring this rule retired.

Commit all three with a message like `docs: sync living docs - <session-topic>`. If none needed editing, skip the commit.

### 6c. WAKEUP_NOTES archiving

Keep WAKEUP_NOTES.md to last 2-3 full sessions only. Bridge spawn overhead grows linearly with file size (each `claude --print` cold-loads it).

Run the auto-prune helper:

```
"%LOCALAPPDATA%\Programs\Python\Python314\python.exe" "<repo>/scripts/wakeup_prune.py" --keep 3
```

This moves any session block past the 3 most recent into `docs/history_notes.md` (newest-first, atomic write). It is a no-op when WAKEUP_NOTES already has <=3 sessions, so always-safe to run. Add `--dry-run` first if you want to preview what would move.

Manual follow-ups (only if needed):
- Compaction rule for archive entries older than 5 sessions: compress to a 1-2 line bullet (date, commit SHA, theme). The auto-prune does NOT compact - it only moves. Compact by hand once entries get stale.
- No commit needed for WAKEUP_NOTES changes - already tracked in section 6 above.

### 7. Memory updates

- List new/modified files under `%USERPROFILE%/.claude/projects/<project-slug>/memory/` since session start.
- Confirm `MEMORY.md` indexes any new memories; add if missing.

### 8. Game state safety check

- Hit `https://127.0.0.1:8888/api/state` - note `lcu.phase` and `mode_key`.
- If user is mid-game: finish the ritual, then output `/done stopped: game in progress - /clear would cut live coaching` instead of the completion line.

### 8b. Session-size check (folded from /wrap)

- Find the active session jsonl: `Get-ChildItem "%USERPROFILE%/.claude/projects/<project-slug>/" -Filter "*.jsonl" | Sort-Object LastWriteTime -Descending | Select-Object -First 1 Name, @{N='MB';E={[math]::Round($_.Length/1MB,1)}}`
- > 10 MB: record "session file > 10 MB - /clear overdue" in the hand-off file.
- > 20 MB: same, flagged first in the hand-off file - at this size compaction is lossy and the model is already degraded.

### 8c. Collect the CI run (Phase 4)

By now the paperwork has overlapped most of the push run (fast guards + impact slice). Collect it, and the section-2c dispatch only if that one has finished - never summon another (RM-157, section 2c):

```
gh run watch <check-run-id> --exit-status
```

- Run the watch as a background command; record the result in the hand-off file as `green | red | pending`.
- The section-2c dispatch, when one fired: `gh run view <dispatch-run-id> --json status,conclusion`. Finished: record `green | red`. Still running: record `pending <run id>` and move on - never `gh run watch` it here.
- A RED run (push slice or dispatch) means fixing FORWARD on main - that is the accepted trade for not paying 27 minutes locally before every commit. Record the failing job as the FIRST next action in the hand-off file.
- Distinguish a real failure from a runner block: a 2-3 second "failure" with a "job was not started" annotation is a billing or runner block, not your code (memory `reference_ci_billing_fastfail`; the repo is PUBLIC, section 2c "Billing").
- Do NOT block /clear on flaky-infra red, but never silently ignore a genuine failure.

### 9. Final output - ONE line, nothing else

RETIRED 2026-10-03 (FLEET-KIT v3, operator order): the banner and the end-of-session review. Do not restore them.

The whole chat output of /done is exactly one line, printed LAST, after section 10 has written and committed the hand-off file:

```
Done ritual complete, safe to clear
```

**Status board - once, after the hand-off read-back and before the done marker (FLEET-KIT v23 item 18, LOCAL ONLY; MAIN 2026-10-25 1926 ORDER step 4).** Write this session's last printed `Session <n> checklist` to a temp file and run from the repo root:

```
python ops/fleet_kit/fleet_board.py render --final --session <n> --checklist <tmp>
```

It writes status.json, state.json and board.html to `ops/loop/control/board/` in the MAIN checkout and pushes nothing: no Artifact / ArtifactData call, no board URL, no `pushed` or `account` verb of fleet_board (all retired by v23; the operator views board.html locally). `{"rendered": false, "reason": "headless"}` means nothing to do. A failed render is a hand-off line (`Board render failed: <reason>`, committed with the hand-off and read back), never a ritual failure.

**Done marker - the LAST act, immediately before that line (FLEET-KIT v9 item 15; MAIN 2026-10-07 2354 ORDER).** After section 10's hand-off is committed and READ BACK (the last commit and any last push are done), run from the repo root:

```
python ops/fleet_kit/fleet_done.py mark --session <n> --status done
```

- `<n>` is THIS session's number (the `Session <n> checklist` counter); the hand-off now carries `SESSION: <n+1>`. Add `--bg <N>` when section 3 recorded N background tasks still running (the marker is then not safe to clear).
- The kit reads HEAD and hashes `RC-NEXT-SESSION.txt` ITSELF and writes `ops/loop/control/session_done.json` (gitignored) in the MAIN checkout. The project Stop hook (`ops/fleet_kit/fleet_done.py stop-hook`) turns a valid marker into the tab title `RC DONE S<n> - safe to clear`.
- Nothing is committed or edited after the mark: a later commit or hand-off edit invalidates it (that is the point - it detects work after /done).
- A step that stopped the ritual still calls it, with `--status failed --reason "<the step>"`, and then prints `/done stopped: <reason>`. If `mark --status done` exits 1 (the kit downgraded it to failed: hand-off or HEAD unreadable, or - kit v18 - the hand-off is over 30 KB, second stdout line `fail: hand-off <N> KB > 30 KB; ...`), print `/done stopped: done marker failed` instead of the completion line. The section-0 size pre-flight exists so that the size case never reaches this point.
- Its one `session_done S<n> ...` line is tool output, not chat output.

If something stopped the ritual (commit blocked, push failed, frozen-file or secret refusal, mid-game), print instead the one line `/done stopped: <reason>` and nothing else. Every status figure the old banner carried (commits, push range, gate, CI, RC health, WAKEUP_NOTES, living docs, session size) goes into `RC-NEXT-SESSION.txt`, never into chat.

### 10. Next-session prompt (ALWAYS - never skip)

Every /done hands the next session a running start - in the FILE, never in chat (FLEET-KIT v3 item 5). Do NOT print the hand-off or any next-session prompt.

**CARRY FORWARD - the rule that matters most.** The operator starts sessions with "continue" or with whatever they want to work on, so a session often never touches the items the previous hand-off listed. Before writing:

1. READ the current `RC-NEXT-SESSION.txt` in the repo root (it is the previous hand-off).
2. For EVERY item in it, decide: acted on this session (done, or superseded with a named reason) or NOT acted on.
3. Every item NOT acted on is copied into the new file, verbatim or tighter. Never drop an item because this session worked on something else. Only an item that was done, or explicitly retracted with its reason, may leave the file.

Then add this session's own items, sourced from ground truth this turn, not memory:

- The "what's next" line you just wrote into `WAKEUP_NOTES.md` (section 6).
- The top open item in `ROADMAP.md` (the next `[!]` / NEXT).
- Any blocker or do-NOT-redo flagged this session, any open steer (section 0), in-flight background work (section 3), and the status figures from sections 0-8c (commits + push range, gate, CI result, full-suite coverage from section 2c, RC health, session size).

Keep it self-contained - the next session boots with zero context: name the next action first, then the key file paths / endpoints / live-state, the acceptance check, and any "already shipped - don't re-investigate" note:

**SESSION counter (FLEET-KIT v7 item 13).** Before writing, read the next value:
`python tools/session_checklist.py --next` (prints n+1 from the CURRENT file's
`SESSION: <n>` line; exit 1 when the line is missing - then derive n from
`git log --oneline -- RC-NEXT-SESSION.txt | wc -l` + 1 and say so in the hand-off).
Put `SESSION: <n+1>` as the line under the `------------` underline. After the write,
`python tools/session_checklist.py --stamp <n+1>` (idempotent; inserts the line if the
block lost it) and read it back with `--current` - that read-back is the recorded act.
The next session's SessionStart hook (`tools/rc_facts.py`) prints `Session <n+1> checklist`
from it.

```
NEXT SESSION
------------
SESSION: <n+1>
Next action: <the one thing "continue" should work on>
Carried forward (not acted on yet): <every unacted item from the previous file>
Context: <key files / endpoints / live-state to probe first>
Acceptance: <how the next session knows it is done>
Do NOT redo: <anything shipped this session that still looks open>
Status: <commits / push range / gate / CI / full suite (2c) / RC health / session size>
Start with: read this file first, then CLAUDE.md + MEMORY.md + WAKEUP_NOTES + git log.
```

This is mandatory on every /done - even when the only next task is "pick the next ROADMAP item".

**WRITE it to `RC-NEXT-SESSION.txt` in the REPO ROOT, every time, OVERWRITING the whole file.** The file is TRACKED (moved off the Desktop 2026-09-06), so each session's hand-off is versioned and diffable, and `Desktop\RC-NEXT-SESSION.lnk` is a shortcut to it. **Commit it with the session's other work.** Write the block to a temp file, re-check its size against the section-0 pre-flight (`wc -c <tmp>` <= 30720; over it, stop with `/done stopped: hand-off over 30 KB` before this write and its commit), and run:

```
python tools/session_intent.py --write-prompt --prompt-file <tmp>
```

Read the file back after the write (that read-back is the recorded act, FLEET-COMMON item 5). Do not report the byte count in chat. This needs no queued intent and consumes nothing; a pending intent stays pending for section 10b.

**Why this line exists (2026-09-06):** it used to be absent, and the ONLY writer of the Desktop file was section 10b's `--consume`, which is gated on a pending intent. So an ordinary /done printed the prompt and wrote nothing, and `RC-NEXT-SESSION.txt` sat three days stale while every sibling project's was current the same day. The stale copy's own header named a headless lane - the only route that ever had an intent queued. Writing and consuming are now separate: writing is unconditional, consuming is not.

#### 10b. Consume a queued intent (only when section 0 found one pending)

Write the exact block you wrote in section 10 to a temp file, then hand it over. This is the only writer of `RC-NEXT-SESSION.txt` in the REPO ROOT (RC- namespaced: the `RC-` prefix is enforced by the consumer). **Do NOT write a Desktop copy** - the Desktop is OUTSIDE the repository root, so writing there is a boundary HALT, and a second copy is untracked, invisible to review and free to diverge:

```
python tools/session_intent.py --consume --prompt-file <tmp>
```

- `{"ok": true, ...}` - the prompt is in the repo root and the intent is marked `consumed`. Nothing to print.
- `already_consumed` / `no_pending_intent` - a refusal, not an error. Nothing was written twice; move on silently.
- **halt_save**: `control/STOP` stays raised on purpose. Do not clear it - the operator is parking the work and will change topic. End the session.
- **done_continue**: same line of work. After the completion line, the operator (or the bridge) `/clear`s and re-feeds `RC-NEXT-SESSION.txt` from the REPO ROOT verbatim. Emit no directive of your own - the consumed prompt is the whole hand-off.

### Safety rails

- NEVER force-push, NEVER use `--amend`, NEVER skip hooks (`--no-verify`).
- NEVER auto-commit secrets, frozen files, or runtime junk.
- NEVER run `/clear` from inside the skill - it's a Claude Code built-in handled by the harness, not the model. Just print the one completion line and let the operator type it.
- If git push needs auth (gh CLI prompt, etc.): stop and ask. Don't keep retrying.
