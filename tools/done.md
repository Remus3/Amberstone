---
description: End-of-session ritual - auto-commit any pending changes, push, do the /wrap checks, then signal "ready for /clear" so the next session starts fresh without context bloat. Use when work is wrapped and you want a clean exit.
---

> **SUBAGENT-FIRST (standing protocol, operator 2026-06-20).** Always use subagents for substantive work; do not build solo in the main thread.
> 1. **Spec first:** a Plan/design subagent (or the Gemini director) emits the spec/plan BEFORE any code; verify it vs ground truth (grep cited file:line, live `/api/state` + `ops/runtime/health.json`, git) - never scaffold on assumptions.
> 2. **New session:** interview the Gemini director (or the operator if Gemini is down) for intent + acceptance criteria, re-probe live state, THEN build.
> 3. **Act via subagents:** worktree-isolated build agents on disjoint files (sole merger) + a read-only `verifier` subagent gate before any merge or "done".
> 4. Trivial one-line cosmetic edits may inline (refines R9). See `CLAUDE.md` "Subagent-First Protocol" + memory `feedback_subagent_first_protocol`.

The user wants to end the session cleanly so the next one starts with a fresh context window. This is /wrap, but with auto-commit instead of "stop and ask". Run all sections in order; surface a tight final banner.

### 0. Local check gate - commit only when green

Versioning is cheap; lost work is not. The operator never passes up a commit + push. So the DEFAULT is: always commit + push when local checks are green. Do NOT leave authored work uncommitted at session end just because a change feels small or unfinished - if it passes its checks, it ships.

- Identify the files authored this session: `git -C "C:/Riot Commander" status -s`.
- Run the cheap local gate on the touched surface:
  - `"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" -m ruff check .` (must report ALL CHECKS PASSED)
  - `"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" -m py_compile <each touched .py>` (syntax - silent-crash guard per CLAUDE.md hard rule)
  - **Authored-source hygiene (ALWAYS run, every /done - this is the same step CI runs):** `"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" -m pytest tests/test_smart_quote_hygiene.py tests/test_mojibake_hygiene.py tests/test_u2500_hygiene.py -q`. Must be green. No smart quotes / em-en dashes / NBSP / ellipsis / mojibake / U+2500 in authored source. The `Share/src` DS data mirror is excluded as external data. If this fails, it is NEVER "pre-existing / unrelated / not in CI" - it is in CI now; fix it (`"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" tools/strip_smart_quotes.py --apply` for smart-quote/dash drift) before the gate is green.
  - Test slice covering the change: full `tests/` for broad edits, the targeted module for narrow ones, DS suite `agents/daemon_slayer/tests/` if the engine was touched.
- Ground truth, not memory (per CLAUDE.md Verification Discipline): run the gate FRESH this turn, read the pass/fail counts you observe now, and `ls` any test file you cite as added - never carry forward a prior or subagent-reported green. If the work came from parallel slices, the `verifier` subagent's CONFIRM is the gate, not the slice agent's claim.
- GREEN: proceed to commit (section 1).
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

### 1. Auto-commit any pending changes

- `git -C "C:/Riot Commander" status -s`
- If output is empty: skip to section 2.
- Otherwise:
  - **Audit before staging**: refuse to auto-commit any path matching `*SECRET*`, `*HANDSHAKE*`, `*PIVOT*`, `*REPLY*`, `*TOKEN*`, `*KEY*`, `.env*`, `local_paths.json`, `API-Key-Claude.txt`, or anything that looks like credentials. If matched: stop and ask the operator before proceeding.
  - **Frozen-file guard**: per `CLAUDE.md`, several files require explicit user approval before editing. If any modified path is in the frozen list, stop and ask - auto-commit is too dangerous here. Frozen list lives at the top of CLAUDE.md.
  - Stage only the changes you authored this session (`git add <specific files>`). Do NOT use `git add -A` - accidentally commits .env / runtime junk.
  - Draft a one-line commit message summarising the session's work (1-2 sentences, "why" over "what"). If multiple distinct themes: list them as bullets in the body.
  - Commit with the standard `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` trailer.
  - If pre-commit hooks fail: fix and create a new commit (never `--amend`).

### 2. Push

- `git -C "C:/Riot Commander" log @{u}.. --oneline` - list local commits not on origin.
- If empty: skip.
- Otherwise: `git -C "C:/Riot Commander" push origin <branch>`. No confirmation prompt - pushing is part of the exit ritual.
- Surface the push result (e.g. `23854e1..b56f247 main -> main`) in the final summary.
- Only ask the operator if the push fails (auth, conflict, hook).

### 2b. GitHub CI verification

- After the push lands, confirm CI goes green for the pushed SHA:
  - `gh run list --branch <branch> --limit 1` to find the run id (gh = `C:/Program Files/GitHub CLI/gh.exe`; use the absolute path in older shells).
  - `gh run watch <run-id> --exit-status` - blocks until the run finishes; exit 0 = green.
- Report the CI result in the banner: `green | red | pending`.
- If CI goes RED on a real test/lint failure: surface the failing job ABOVE the banner and add "resolve CI <job> before /clear" to the bottom line. The local gate (section 0) should have caught it, so a red here usually means an env-only delta - investigate before declaring the session cleanly wrapped.
- Do NOT block /clear on flaky-infra red, but do NOT silently ignore a genuine failure either.

### 3. Background tasks started this session

- TaskList - show anything still running.
- Each one: TaskStop. DO NOT leave monitors armed; they're useless after /clear.

### 3b. Peer bridge probe - DEPRECATED (operator 2026-06-21)

- The Peer cross-Claude bridge loop-liveness probe is NO LONGER part of /done. Do
  not dispatch a bridge_task probe and do not flag a dead Peer `/loop
  /process-bridge-tasks` at wrap. Skip this section entirely.

### 4. RC restart pending

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

### Safety rails

- NEVER force-push, NEVER use `--amend`, NEVER skip hooks (`--no-verify`).
- NEVER auto-commit secrets, frozen files, or runtime junk.
- NEVER run `/clear` from inside the skill - it's a Claude Code built-in handled by the harness, not the model. Just print the banner and let the operator type it.
- If git push needs auth (gh CLI prompt, etc.): stop and ask. Don't keep retrying.
