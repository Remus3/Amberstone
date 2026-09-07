---
description: End-of-session ritual - auto-commit any pending changes, push, do the /wrap checks, then signal "ready for /clear" so the next session starts fresh without context bloat. Use when work is wrapped and you want a clean exit.
---

> **SUBAGENT-FIRST (standing protocol, operator 2026-06-20, restated 2026-07-30).** Orchestrated + multi-agent + self-adjudicating + self-adversarial is the DEFAULT shape, not an escalation.
> 1. **Spec first:** a Plan/design subagent (or the loop director) emits the spec/plan BEFORE any code; verify it vs ground truth (grep cited file:line, live `/api/state` + `ops/runtime/health.json`, git) - never scaffold on assumptions.
> 2. **New session:** interview the loop director (or the operator) for intent + acceptance criteria, re-probe live state, THEN build. Verify before building.
> 3. **Act via subagents:** worktree-isolated build agents on disjoint files (sole merger) + a read-only `verifier` subagent gate before any merge or "done" claim.
> 4. **Self-adjudicating:** the agent that produced a thing never grades it. **Self-adversarial:** every finding gets an independent pass trying to REFUTE it, defaulting to refuted when uncertain. Two agents agreeing is not evidence (`feedback_row_agreement_is_not_evidence`).
> 5. Trivial one-line cosmetic edits may inline (refines R9). See `CLAUDE.md` "Session Default".

The user wants to end the session cleanly so the next one starts with a fresh context window. This is /wrap, but with auto-commit instead of "stop and ask". Run all sections in order; surface a tight final banner.

> **SHAPE (measured 2026-07-26, LEDGER 1065; section 2c retired 2026-08-04, RM-157).**
> This ritual is FOUR PHASES, and the ordering is load-bearing rather than cosmetic:
> **Phase 1** the fast local gate (section 0-0c, target 60-90s) -
> **Phase 2** commit + push, which FIRES the full suite at CI by itself (sections 1-2) -
> **Phase 3** all the paperwork WHILE CI runs (sections 3-7) -
> **Phase 4** collect CI, banner, next-session prompt (sections 8-10).
>
> **Why:** the old shape ran a ~27-minute local dual suite and THEN blocked on a
> CI watch, with ~15 minutes of doc writing after that. Measured: the local dual
> suite is **1642s / 23,250 tests**, while the SAME suite on CI's ubuntu runner
> is **16m47s / 22,749 tests (97.8% of local)** - CI is FASTER than this machine
> and it is off the box. Pushing at Phase 2 makes the ~15 minutes of paperwork
> overlap the ~20-minute CI run, so the wrap costs the LONGER of the two instead
> of their sum.
>
> **That overlap no longer needs a manual dispatch, and must not get one back.**
> Until 2026-08-04, section 2c fired `gh workflow run ci.yml` here. RM-119's
> second half (2026-07-28) put the identical `pytest tests/
> agents/daemon_slayer/tests/ ...` onto the `check` job of every push, so from
> that day the dispatch only re-ran what the push run was already running.
> MEASURED over 2026-08-01..04: 18 such dispatches, **485.8 minutes of runner
> wall clock in four days for zero added signal**, 22.8% of all runner time in
> the window. The push IS the full suite. Wait for it; never summon a second one.
>
> **Do NOT reintroduce a full local dual suite into Phase 1.** It was measured
> and it does not have a slow minority to trim: the slowest 40 tests are only
> **10.7%** of wall clock and the mean is 71ms across 23,250 tests, so the cost
> is broad, not concentrated. The targeted slice plus the push CI run is the
> replacement, not a shortcut.

> **MEASURED 2026-07-26 - pytest-xdist is an 11.4x win and is NOT yet adopted.**
> `pytest tests agents/daemon_slayer/tests -q -n 8 --dist loadfile` runs the full
> dual suite in **144.65s (2m24s) against the serial 1642s (27m22s)**, with
> **6 failures out of 23,272**. Those six are shared-state artifacts that serial
> execution was hiding - four fail-soft "never raises on garbage" tests
> (`test_aram_fight_risk` x3, `test_aram_action_rule`), one rune-registry
> fail-soft (`test_rune_offense_jack_of_all_trades_r156`), and one genuine
> asyncio conflict (`preflip_mode/test_body_data_mode_no_flap` -
> "Runner.run() cannot be called from a running event loop").
> **Fix those six, then this replaces the CI dispatch as the primary gate** and
> the whole wrap collapses to a couple of minutes. Until they are fixed, `-n 8`
> is not trustworthy as a gate. Do NOT adopt it by suppressing the six.

### 0. Local check gate - commit only when green

**First, peek for a queued Mission Control intent** (shortcuts 1 + 2, S3). The done ritual IS the safe boundary a queued intent waits for:

```
python tools/session_intent.py --peek
```

`{"pending": null}` - nothing queued, run the ritual as normal. A pending `halt_save` or `done_continue` means the operator fired the dashboard button while this session was mid-turn: finish the current step, run the whole ritual, and consume it in section 10. Never abandon work to service an intent - a queued intent never kills anything.

**Then drain the steer channel** (S7). The done ritual is the SAFE BOUNDARY a NOTE waits for, so this is where queued guidance gets read:

```
python tools/session_steer.py --drain --format text
```

`(no steers pending)` and exit 1 - nothing queued, carry on. Otherwise each line is free-text guidance the operator sent while this session was running. A steer is GUIDANCE, NOT A COMMAND: it executes nothing, it never killed anything, and it is not an instruction you must obey blindly - read it, say in the wrap what it said and what you did about it, and fold anything still open into the next-session prompt in section 10. Draining advances a cursor; the log itself is append-only and stays as the audit trail.

Versioning is cheap; lost work is not. The operator never passes up a commit + push. So the DEFAULT is: always commit + push when local checks are green. Do NOT leave authored work uncommitted at session end just because a change feels small or unfinished - if it passes its checks, it ships.

- Identify the files authored this session: `git -C "C:/Riot Commander" status -s`.
- Run the cheap local gate on the touched surface:
  - `"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" -m ruff check .` (must report ALL CHECKS PASSED)
  - `"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" -m py_compile <each touched .py>` (syntax - silent-crash guard per CLAUDE.md hard rule)
  - **Authored-source hygiene (ALWAYS run, every /done - this is the same step CI runs):** `"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" -m pytest tests/test_smart_quote_hygiene.py tests/test_mojibake_hygiene.py tests/test_u2500_hygiene.py -q`. Must be green. No smart quotes / em-en dashes / NBSP / ellipsis / mojibake / U+2500 in authored source. The `Share/src` DS data mirror is excluded as external data. If this fails, it is NEVER "pre-existing / unrelated / not in CI" - it is in CI now; fix it (`"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" tools/strip_smart_quotes.py --apply` for smart-quote/dash drift) before the gate is green.
  - Test slice covering the change: **the targeted module**, plus the DS suite `agents/daemon_slayer/tests/` if the engine was touched (that one is genuinely fast; measure its size with `pytest agents/daemon_slayer --collect-only -q`, never from a recited figure, since suite counts are unguarded and this line said "9932 tests in ~115s" until 2026-08-16). Do NOT run the full `tests/` suite here; section 2c dispatches it to CI instead. **Run any suite from the REPO ROOT** - running the DS suite with cwd `agents/daemon_slayer/` yields 13 FALSE failures whose names read like registry regressions (CWD-relative registry opens plus two ASCII-hygiene tests). See memory `reference_ds_suite_run_from_repo_root`.
- Ground truth, not memory (per CLAUDE.md Verification Discipline): run the gate FRESH this turn, read the pass/fail counts you observe now, and `ls` any test file you cite as added - never carry forward a prior or subagent-reported green. If the work came from parallel slices, the `verifier` subagent's CONFIRM is the gate, not the slice agent's claim.
- GREEN: proceed to section 0c, then commit (section 1).
- RED: fix and re-run. If the failure is pre-existing and unrelated to this session's work, note it ABOVE the banner and commit only the green-verified authored files - never commit over a regression you introduced.


### 0b. DS Share package sync (when Daemon Slayer was touched)

The `Share/` folder is the external-facing DS review package (engine source + DS tooling + reference-data snapshot + authored handoff docs). It MUST stay in lock-step with the live engine on every change that touches DS or its components - this is the durable update path. The package has two halves: the deterministic `src` mirror (auto-generated) and the authored docs (`README.md` + `CHANGELOG.md` + `docs/01..05`). BOTH must be kept fresh - the authored docs are where staleness silently accrues, so they have a hard gate now too.

- Detect whether this session touched DS: `git -C "C:/Riot Commander" status -s` shows any path under `agents/daemon_slayer/`, `tools/daemon_slayer_*`, `tools/ds_*`, or `data/daemon_slayer/`. If NONE: skip this section (the package is unchanged).
- Otherwise re-mirror + verify (ground truth, not memory):
  - `"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" "C:/Riot Commander/tools/ds_share_sync.py"` - regenerates `Share/src` from the live engine, restamps `Share/MANIFEST.md` (engine version, file counts, UTC timestamp), AND auto-rewrites the MECHANICAL version/patch anchors in the authored docs (`ENGINE_VERSION = "X"` + `data patch \`X\`` + `"patch": "X"`) to the live values. You do NOT hand-edit those literals; the tool owns them.
  - `"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" "C:/Riot Commander/tools/ds_share_sync.py" --check` - must report "Share/src + doc anchors in sync" (this is the exact guard CI runs; a DS change that forgets the src mirror OR a doc anchor fails CI).
- **Authored-doc freshness (the SEMANTIC half the auto-rewrite cannot do - update / add / archive as the change warrants):**
  - **Update.** Walk `Share/docs/01..05` for prose that this change made stale and fix it in place. The usual decay points: a capability that was "staged / next" in `04_GAPS_AND_ROADMAP.md` and SHIPPED this session moves from section 2/3 to section 1 (Included); `05_AUDIT_AND_REFACTOR.md`'s test-count / file-count line and any "now applied" refactor note; a registry-table cell in `02_FUNCTION_REFERENCE.md` whose entry count or field list grew. Numbers come from THIS session's fresh runs, not memory.
  - **Add.** If the change introduced a whole new subsystem the five docs do not describe, add the section (or, rarely, a new `docs/NN_*.md`) and link it from `README.md`'s "How to read this package" list.
  - **Archive.** If an authored doc - or a standalone repo-internal DS plan doc (e.g. a `docs/DS_*_PLAN.md`) - describes a one-off effort that is now COMPLETE, fold it to its done-state (the five Share docs are evergreen, so this is usually an in-place "now applied" edit) or, for a genuinely point-in-time standalone doc, move it under `docs/_archive/` (or `Share/docs/_archive/`) so it stops reading as pending. The audit/refactor doc's "prior recommendations, now applied" section is the model: completed work is named as done, not deleted and not left describing a future.
  - Keep the authored docs CLEAN (external voice): no item numbers, session refs, operator names, or outside-project names - frame DS work by technical substance only.
- If `ENGINE_VERSION` changed this session: prepend a dated release entry to `Share/CHANGELOG.md` (header `## ENGINE_VERSION <v> - <UTC timestamp>`, then a tight bullet list of the engine changes) and append a one-line entry under the sync-history section. Credit the upstream sources of truth (Riot Data Dragon / CommunityDragon / Meraki Analytics) in the entry when the change added or corrected formula data. (A plain patch bump - new `current.txt` patch, no engine code change - also needs a manual doc pass for the patch FORMS the auto-rewrite leaves alone: the `data/daemon_slayer/<patch>/` path citations and the CommunityDragon two-segment pin in `03_DATA_AND_SOURCES.md`.)
- Stage `Share/` with the rest of the authored files in section 1 - the package sync is part of the SAME commit as the engine change, never a trailing afterthought. Credit the sources of truth in the commit body too.

### 0c. Drift guard - the check that saves the cleanup sessions

```
"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" "C:/Riot Commander/tools/drift_guard.py"
```

After an ENGINE bump, pass the version you bumped FROM so the anchor sweep runs:

```
"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" "C:/Riot Commander/tools/drift_guard.py" 1.258.0
```

Runs in well under a second and exits 1 on any breach. It checks doc-size budgets, `tools/*.md` vs `.claude/commands/*.md` mirror parity, memory-index integrity, stale version anchors (HTML included), self-inconsistent counted claims, and authored files git is not tracking.

**Every check exists because that exact drift ACTUALLY HAPPENED here and later cost a whole dedicated session** - ROADMAP silently breaching its CI budget and sitting over it, two copies of THIS file diverging for a month while preserving a decommissioned instruction, 27 orphaned docs, 11 command docs with zero version control, a fourth ENGINE anchor site found only 25 minutes into a CI run. Detection is seconds; repair is a session. Fix what it reports NOW rather than letting it accrue - that is the entire point of the guard.

Do NOT silence a breach by loosening the check. If a finding is genuinely a false positive, fix the check and add a case to `tests/test_drift_guard.py` (which asserts both the breach and the clean path for every check, so a check cannot silently degrade into always-passing).

### 1. Auto-commit any pending changes

- `git -C "C:/Riot Commander" status -s`
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
  - If pre-commit hooks fail: fix and create a new commit (never `--amend`).

### 2. Push

- `git -C "C:/Riot Commander" log @{u}.. --oneline` - list local commits not on origin.
- If empty: skip.
- Otherwise: `git -C "C:/Riot Commander" push origin <branch>`. No confirmation prompt - pushing is part of the exit ritual.
- Surface the push result (e.g. `23854e1..b56f247 main -> main`) in the final summary.
- Only ask the operator if the push fails (auth, conflict, hook).

### 2b. GitHub CI verification

- **Do NOT block here.** This is Phase 2; the CI run is collected in section 8c after the
  paperwork is done. Just capture the run id so 8c can find it.
- Note the push-triggered `check` run for the pushed SHA:
  - `gh run list --branch <branch> --limit 1` to find the run id (gh = `C:/Program Files/GitHub CLI/gh.exe`; use the absolute path in older shells).
- Report the CI result in the banner: `green | red | pending`.
- If CI goes RED on a real test/lint failure: surface the failing job ABOVE the banner and add "resolve CI <job> before /clear" to the bottom line. The local gate (section 0) should have caught it, so a red here usually means an env-only delta - investigate before declaring the session cleanly wrapped.
- Do NOT block /clear on flaky-infra red, but do NOT silently ignore a genuine failure either.

### 2c. The full suite is ALREADY running - do NOT dispatch a second one

RETIRED 2026-08-04 (RM-157). This section used to run `gh workflow run ci.yml --ref main`. Do not restore it. Since RM-119's second half (2026-07-28), the `check` job on every push runs the identical command that dispatch triggers:

```
pytest tests/ agents/daemon_slayer/tests/ -q --tb=short --timeout=300 -n auto --dist loadfile
```

So the push in section 2a has already fired the full dual suite. Note its run id in 2b, go straight to section 3, and collect it in 8c.

- **MEASURED 2026-08-01..04, four days:** 256 runs / 2126.6 minutes of runner wall clock. `ci` on `workflow_dispatch` was **18 runs / 485.8 min (avg 27.0)** - every one of them this section, every one a duplicate of the `check` run over the same tree. 22.8% of all runner time in the window, for zero added signal.
- **`docs-guards` was measured in the same pass and the answer is LEAVE IT ALONE.** It has the largest run COUNT (109 push runs) but is the smallest job: **178.8 min, avg 1.6** - 8.4% of the total, and it is the only thing watching a docs-only push. That is not where the minutes go; do not "optimise" it on run count.
- **`CodSpeed` was measured too (62 runs / 77.7 min, avg 1.3 - 3.7%) and the verdict "leave it alone" was SUPERSEDED on 2026-09-06: the workflow and the `benchmarks/` tree are DELETED.** Minutes were never the reason - it was dropped because it benchmarked `item_advisor.py` and `composition_advisor.py`, which took 3 and 1 commits in 90 days, while `agents/daemon_slayer/` took 310 and had no perf coverage at all. A perf gate on static code is green by construction. Full reasoning in docs/OPERATIONS.md "Why CodSpeed was dropped". **Do not re-add it** as a minute-saver reversal; the minute argument was the one thing that never applied.
- **Two cases genuinely run no `ci` at all, and neither is a reason to dispatch.** A docs-only push is skipped by `ci.yml`'s `paths-ignore: '**/*.md'`, and `docs-guards.yml` is its purpose-built complement (selector-derived, pinned by `tests/test_ci_docs_guard_coverage.py`) - a full suite adds nothing that a .md-only commit could have broken. A push to a NON-main branch with no PR matches neither `ci.yml` trigger, and a `--ref main` dispatch there would test main rather than your branch, so it is worse than useless. Open the PR instead.
- The ~142 tests that SKIP on Linux (Windows paths, PowerShell, scheduled tasks) are the residue CI cannot cover. If this session's work was in that surface, run those locally rather than trusting the CI green.
- **The billing trap still applies to the run you DO get.** The repo is PRIVATE, so Actions minutes are metered and it has already tripped its spending limit once. A billing block looks exactly like a red CI - a 2-3 second "failure" carrying a "job was not started" annotation. See memory `reference_ci_billing_fastfail`.

### 3. Background tasks started this session

- TaskList - show anything still running.
- Each one: TaskStop. DO NOT leave monitors armed; they're useless after /clear.


### 5. RC restart pending

- Check `C:/Riot Commander/restart_trigger.txt` - if non-empty, RC may still be reloading. Confirm `ops/runtime/health.json` shows `alive=true` AND `last_reload_ok=true` before declaring done.

### 6. WAKEUP_NOTES update

- The next session will bootstrap from `C:/Riot Commander/WAKEUP_NOTES.md` + `MEMORY.md` + git log. Make sure tomorrow-you can pick up cleanly.
- Append a short entry (<=20 lines) describing this session's work: commits shipped, key decisions, what's next. Don't rewrite history; just append.
- Note explicitly any blockers or things tomorrow-you should NOT redo (e.g. "lobby pill fix already shipped in bb4cff9 - don't re-investigate").

### 6b. Living-doc sync (ROADMAP / CLAUDE.md / README)

Update the three living docs based on what shipped this session. These are surgical edits - never full rewrites.

**ROADMAP.md**
- Find any item that shipped this session: flip its marker from `[!]` to `✅` and append the commit short-SHA in parentheses.
- Add new `[!]` entries for anything that's now next or in-flight.
- Do NOT touch items that are already ✅ or haven't been worked on.

**Per-item completion ledger -> `docs/LEDGER.md` (NOT CLAUDE.md)**
- Append the new item entry at the TOP of the `docs/LEDGER.md` body (newest-first), in the existing entry format.
- CLAUDE.md "Active priorities" is now a STATIC POINTER - do NOT add item entries to CLAUDE.md (CI size-budgeted < 60KB).
- In CLAUDE.md touch only the `### Settled` summary or the one-line DS reference when relevant - never the ledger.

**README.md**
- Update only if something structural changed (new endpoint, new panel, new agent). Light-touch: one bullet or badge line at most.
- If nothing structural changed: skip entirely - don't update the README just to say you ran /done.

**docs/DAEMON_SLAYER.md + docs/ARCHITECTURE.md changelogs**
- Changelog: newest first, ONE line per ENGINE bump - never append to a prior version's line. On an ENGINE_VERSION bump, prepend a new bullet to the DAEMON_SLAYER.md `## Changelog` section (one bullet per ENGINE version); do NOT extend an existing version's bullet. Bump the short status header (ENGINE_VERSION + test count + patch) in the same edit.
- ARCHITECTURE.md keeps a short DS summary + structural bullets + a `see docs/DAEMON_SLAYER.md changelog` pointer - do NOT paste the per-version narrative there. Appending to a prior version's line is what produced the unreadable single-line megastring this rule retired.

Commit all three with a message like `docs: sync living docs - <session-topic>`. If none needed editing, skip the commit.

### 6c. WAKEUP_NOTES archiving

Keep WAKEUP_NOTES.md to last 2-3 full sessions only. Bridge spawn overhead grows linearly with file size (each `claude --print` cold-loads it).

Run the auto-prune helper:

```
"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" "C:/Riot Commander/scripts/wakeup_prune.py" --keep 3
```

This moves any session block past the 3 most recent into `docs/history_notes.md` (newest-first, atomic write). It is a no-op when WAKEUP_NOTES already has <=3 sessions, so always-safe to run. Add `--dry-run` first if you want to preview what would move.

Manual follow-ups (only if needed):
- Compaction rule for archive entries older than 5 sessions: compress to a 1-2 line bullet (date, commit SHA, theme). The auto-prune does NOT compact - it only moves. Compact by hand once entries get stale.
- No commit needed for WAKEUP_NOTES changes - already tracked in section 6 above.

### 7. Memory updates

- List new/modified files under `C:/Users/Administrator/.claude/projects/C--Riot-Commander/memory/` since session start.
- Confirm `MEMORY.md` indexes any new memories; add if missing.

### 8. Game state safety check

- Hit `https://127.0.0.1:8888/api/state` (or `https://192.168.8.230:8888/api/state` if local fails) - note `lcu.phase` and `mode_key`.
- If user is mid-game: warn that /clear right now will kill live coaching access until next session starts.

### 8b. Session-size check (folded from /wrap)

- Find the active session jsonl: `Get-ChildItem "C:/Users/Administrator/.claude/projects/C--Riot-Commander/" -Filter "*.jsonl" | Sort-Object LastWriteTime -Descending | Select-Object -First 1 Name, @{N='MB';E={[math]::Round($_.Length/1MB,1)}}`
- > 10 MB: add "session file > 10 MB - /clear overdue" to the banner.
- > 20 MB: escalate ABOVE the banner - at this size compaction is lossy and the model is already degraded.

### 8c. Collect the CI run (Phase 4)

By now the paperwork has overlapped most of the ~20-minute push run. There is exactly ONE run to collect - summoning a second is the RM-157 regression (section 2c):

```
gh run watch <check-run-id> --exit-status
```

- Report it in the banner as `green | red | pending`.
- A RED full run means fixing FORWARD on main - that is the accepted trade for not paying 27 minutes locally before every commit. Surface the failing job ABOVE the banner and add "resolve CI <job> before /clear" to the bottom line.
- Distinguish a real failure from a BILLING block: a 2-3 second "failure" with a "job was not started" annotation is the spending limit, not your code (memory `reference_ci_billing_fastfail`).
- Do NOT block /clear on flaky-infra red, but never silently ignore a genuine failure.

### 9. Final banner

Print a tight banner - exactly this format:

```
══════════════════════════════════════════════════════════════════
  /done complete - context ready for /clear
══════════════════════════════════════════════════════════════════
  - commits this session : <count> (pushed: <push range>)
  - local check gate     : green | red (<failing>)
  - github CI            : green | red (<job>) | pending
  - background tasks     : stopped <count>
  - RC health            : pid=<pid> alive=<bool> reload_ok=<bool>
  - WAKEUP_NOTES         : updated (+<N> lines)
  - living docs          : roadmap/claude.md/readme - <N items updated | skipped>
  - DS Share package     : synced (engine <v>, --check green) | n/a (DS untouched)
  - session file         : <N> MB <ok | /clear overdue>
  - mid-game             : no | YES - wait until safe to /clear
  - next-session prompt  : printed below
══════════════════════════════════════════════════════════════════
  Type /clear to start a fresh session with reset token budget.
══════════════════════════════════════════════════════════════════
```

If anything failed (commit blocked, push failed, mid-game, etc.), surface the issue ABOVE the banner and substitute "⚠️ resolve <X> before /clear" on the bottom line.

### 10. Next-session prompt (ALWAYS - never skip)

Every /done ends by handing the next session a running start. After the banner, ALWAYS print a fenced, copy-pasteable prompt block the operator can drop straight into a fresh `/clear`ed session. Source it from ground truth this turn, not memory:

- The "what's next" line you just wrote into `WAKEUP_NOTES.md` (section 6).
- The top open item in `ROADMAP.md` (the next `[!]` / NEXT).
- Any blocker or do-NOT-redo you flagged this session.

Keep it self-contained - the next session boots with zero context: name the single next task, the key file paths / endpoints / live-state it touches, the acceptance check, and any "already shipped - don't re-investigate" note. One tight block, no preamble:

```
NEXT SESSION
------------
Task: <one-line next task from ROADMAP/WAKEUP>
Context: <key files / endpoints / live-state to probe first>
Acceptance: <how the next session knows it is done>
Do NOT redo: <anything shipped this session that still looks open>
Start with: /clear, then bootstrap from CLAUDE.md + MEMORY.md + WAKEUP_NOTES + git log.
```

This is mandatory. Never end /done without it - even when the only next task is "pick the next ROADMAP item".

#### 10b. Consume a queued intent (only when section 0 found one pending)

Write the exact prompt block you just printed to a temp file, then hand it over. This is the only writer of `Desktop/RC-NEXT-SESSION.txt` (RC- namespaced: LW and RM own their own prefixes on the shared Desktop):

```
python tools/session_intent.py --consume --prompt-file <tmp>
```

- `{"ok": true, ...}` - the prompt is on the Desktop and the intent is marked `consumed`. Say so above the banner, with the byte count.
- `already_consumed` / `no_pending_intent` - a refusal, not an error. Nothing was written twice; report it and move on.
- **halt_save**: `control/STOP` stays raised on purpose. Do not clear it - the operator is parking the work and will change topic. End the session.
- **done_continue**: same line of work. After the banner, the operator (or the bridge) `/clear`s and re-feeds `Desktop/RC-NEXT-SESSION.txt` verbatim. Emit no directive of your own - the consumed prompt is the whole hand-off.

### Safety rails

- NEVER force-push, NEVER use `--amend`, NEVER skip hooks (`--no-verify`).
- NEVER auto-commit secrets, frozen files, or runtime junk.
- NEVER run `/clear` from inside the skill - it's a Claude Code built-in handled by the harness, not the model. Just print the banner and let the operator type it.
- If git push needs auth (gh CLI prompt, etc.): stop and ask. Don't keep retrying.
