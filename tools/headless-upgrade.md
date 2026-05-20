---
description: Headless autonomous-run skill embodying the safety + session-management spirit of overnight RC runs (items 99, 107, 108, 2026-05-20). Use when the operator says "continue headless" with explicit pre-approval to touch frozen files and run unattended for hours. Hard-coded with the don't-redo list, interrupt protocol, and the synopsis-on-Desktop heartbeat.
---

The operator has authorized a long unattended autonomous run with:
- Frozen-file edits allowed (the grant is for THIS run only; do NOT carry forward into later sessions).
- RC-wide test coverage at every stage gate.
- Multi-agent dispatch for research + parallel slices when appropriate.
- A living synopsis maintained atomically on the Legion Desktop.
- Interrupt protocol: any operator statement of intent to complete = finish current tasks + /done ritual.

This skill is the durable record of how to run that loop cleanly. Run sections in order.

### 1. Pre-flight baseline (do this FIRST, every time)

- Read `CLAUDE.md` Active priorities + `MEMORY.md` index + `ROADMAP.md` top 80 lines + `BACKLOG.md` headings + recent 15 commits.
- Probe live state: `ops/runtime/health.json` (pid, alive, last_reload_ok), `https://127.0.0.1:8888/api/state` (RC), `http://127.0.0.1:8893/health` (DS engine_version).
- If DS engine_version is stale vs the repo `agents/daemon_slayer/__init__.py` ENGINE_VERSION constant, bounce DS via `Stop-Process` + `Start-Process pythonw start_daemon_slayer.py` (DS is NOT supervisor-watched).
- Probe CI: `gh run list --limit 6`. Baseline must be green before starting; if a recent push is red, fix the red before any new work.
- Write the initial synopsis to `C:/Users/Administrator/Desktop/RC_HEADLESS_SYNOPSIS_<YYYY-MM-DD>.md` (atomic Write). Header carries: HEAD sha, ENGINE_VERSION, DS test count, RC test count, CI status, item count, scope, stop rules, phase log table.
- TaskCreate for each phase in the run so progress is visible.

### 2. Phase loop discipline

Each phase is one focused vertical slice. After EVERY phase:

1. **Lint locally before push**: `py -m py_compile <touched files>`; if any Python file was edited, also run `ruff check <touched files>` (or `py -m ruff check .` if available). F541 (f-string no placeholder) is the most common CI-killer; catch it locally.
2. **Test gate**: run the relevant test subset green BEFORE committing. For DS engine changes: `py -m pytest agents/daemon_slayer/tests/ -q`. For RC backend: `py -m pytest tests/ --ignore=tests/daemon_slayer -q`. For frontend snapshots: `py -m pytest tests/snapshot_panels/ -q`.
3. **Restart-aware**: editing dashboard routes -> `echo restart > restart_trigger.txt && sleep 7`; editing `_effects_data.py` / engine math -> taskkill+relaunch DS server; editing asset hashes (web/css|js/panels/*) -> auto-reload via `compute_asset_hash` (per ADR-008), no RC restart.
4. **Commit + push**: do NOT `git add -A`; explicitly stage only the files you authored. Unstage `_scratch/` (gitignored by convention but uncovered) and any stray `.playwright-mcp/*.png`. Use HEREDOC commit message ending with the `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>` trailer.
5. **CI check after push**: `gh run list --limit 4`. If the just-pushed run goes red, FIX before starting the next phase. The cost of pausing to fix < the cost of compounding broken state.
6. **Synopsis sync**: update the Desktop synopsis table row for the phase with status + short-SHA. Atomic Write.
7. **TaskUpdate** to mark the phase completed; set the next phase in_progress.

### 3. Frozen-file edits under this run's grant

- The grant is operator-authorized for the CURRENT run only. Do NOT extend into future sessions; the grant does NOT carry forward (per item 108 + 99).
- When you DO touch a frozen file, route AROUND when possible. Adding a single import line in main.py to wire a non-frozen module is fine; rewriting `_loop.py` is a separate dedicated session.
- Every frozen-file commit body explicitly notes "frozen-file edit under operator's headless-upgrade grant".

### 4. ASCII hygiene (hard rule)

- No em-dash, no en-dash, no smart quotes anywhere in authored text (.py / .md / .ps1 / .css / .js / commit messages / chat output).
- Use ` - ` (spaced hyphen) for a clause break, `-` otherwise.
- The `"-"` no-data sentinel in dashboard rendering is OPERATOR-APPROVED and stays.
- Pytest_guard catches Python; check `.md`/`.css`/`.js` by `grep -P "[\xE2\x80\x93\xE2\x80\x94\xE2\x80\x98\xE2\x80\x99\xE2\x80\x9C\xE2\x80\x9D]"` before commit when in doubt.

### 5. Multi-agent dispatch

- Dispatch parallel research agents in a SINGLE message with multiple Agent tool blocks for true concurrency (operator's "parallel" instruction).
- Each agent prompt MUST list the don't-redo set so it doesn't re-research closed topics. Examples for LoL overlay research: coachless.gg, baronbuff.com, aggregator Z13, aggregator J, draft tool L (the community fork), league_record, KebsCS, Pengu Loader, all generic LCU clients, ML win-predictors, .rofl parsing.
- Agents return TRIAGED triage (NOW / FUTURE / CLOSED with reasons). Synthesize into a BACKLOG.md section + open issues for NOW items; do NOT auto-implement everything.

### 6. DS audit iteration loop

- Stop rule: 11 consecutive no-change iterations.
- Source of truth: Meraki bulk (`/items.json`, `/items_meraki.json`, champion `aram_modifiers`) - never aggregator D, never aggregator A scrape.
- Each iteration touches ONE math lane (lethality, %-pen compose, on-hit family, immolate family, etc) and either ships ENGINE_VERSION bump + tests, or records "no-change" with explicit reasoning.
- After each ENGINE bump, sync 13-14 ENGINE_VERSION pins across tests + bounce DS server (it is NOT supervisor-watched).
- Wider-and-edge-case test variability: when ADDING tests, prefer parametrized property-style (parameterize over (level x AP/AD x item-set) tuples) over single-pin checks. Mathematical invariants > exact values.

### 7. Interrupt protocol

- Any operator message saying "finish the current run", "wrap up", "complete and done ritual", or similar = STOP starting new phases, FINISH the in-flight phase, then run `/done`.
- If the operator asks a question mid-run, prefer answering in the operator's preferred ultra-caveman mode (no preamble, no narration, paths/numbers stand alone) per the SessionStart hook.
- If a question would interrupt a critical path (e.g. mid-restart), finish the critical path FIRST then answer.

### 8. Headless cadence health

- Living synopsis on Desktop: update every phase complete (atomic Write); never delete the file mid-run; final state survives the run as the durable record.
- Living docs (CLAUDE.md item N+1, ROADMAP.md, BACKLOG.md, WAKEUP_NOTES.md, docs/DAEMON_SLAYER.md): updated at run END as a single sync commit, NOT per phase. Sync is surgical, not full rewrite.
- 10h+ extension: if still running past 10 hours, transition to a full RC refactor audit (multi-agent codebase split). Frozen-file edits still allowed; tests required.
- Token budget: caveman ULTRA is the default for fleet-wide overnight (per the SessionStart hook). Compress chat output ~90 percent; keep code tokens / paths / numbers / error strings byte-exact.

### 9. The /done ritual at run end

Run `/done` (existing skill) which handles auto-commit + push + WAKEUP_NOTES + living-doc sync + final banner. DO NOT skip; the WAKEUP_NOTES update is what unblocks the next session's bootstrap.

### 10. Anti-patterns (caught from past runs - do NOT repeat)

- Do NOT `git add -A` without unstaging _scratch/ first (item 108 contains the same warning twice).
- Do NOT skip the `ruff check` local lint - F541 has killed CI 2x. (this run: 1x, fixed in `cb73757`).
- Do NOT amend commits; always create new commits per CLAUDE.md hard rules.
- Do NOT trust the agent's premise without verifying against live data (e.g. one research agent claimed Meraki bulk lacked ARAM modifiers; live probe verified it DOES have them on the CHAMPION bulk, not the ITEM bulk).
- Do NOT dispatch a research agent without an explicit don't-redo list; you'll waste budget re-litigating closed items.
- Do NOT skip `compute_asset_hash` reload mention when shipping frontend changes; the operator needs to see in chat that no RC restart is required.
- Do NOT add a feature flag for changes that should just BE the new behavior. CLAUDE.md says no feature flags / no backwards-compat shims.
- Do NOT add comments that say WHAT the code does. Comments are for WHY only.

### 11. Final banner

When the operator's interrupt fires (or the work queue is empty), emit one tight banner:

```
HEADLESS UPGRADE WRAP
  HEAD: <short-sha> (<N> commits this run)
  ENGINE: <old> -> <new>
  DS: <N> tests / <N> subtests
  RC: <N> tests
  CI: <N>/<N> green (<N> red)
  Synopsis: C:/Users/Administrator/Desktop/RC_HEADLESS_SYNOPSIS_<date>.md
  Ready for /done.
```

Then call `/done`.
