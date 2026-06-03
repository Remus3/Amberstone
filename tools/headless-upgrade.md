---
description: Headless autonomous-run skill. Folds in /done /clear /continue /compact /memory /audit /test /iterate /new-tech. Full authority - no mid-run user gating (long 100 percent acceptance track record). Orchestrator pattern - one Claude merges; up to 100 worktree agents in parallel per task. Caveman ULTRA default. Reoriented to find cost/latency savings without degrading the product. Hard-coded with the durable don't-redo set, interrupt protocol, and Desktop synopsis heartbeat.
---

The operator has authorized a long unattended autonomous run with:
- Frozen-file edits allowed (this run only; do NOT carry forward).
- RC-wide test coverage at every stage gate.
- Up to 100 worktree subagents in parallel per task; orchestrator (this Claude) merges + resolves conflicts.
- Living synopsis maintained atomically on Legion Desktop (one file per run, sections only, no repeat content).
- Interrupt protocol: any operator intent-to-complete = finish current tasks + /done ritual.
- Research / cleanroom / lift as needed; expand beyond LoL when warranted (UI/UX inspiration).
- If a term is unknown, make best recommended conclusion and implement it (no user gating).

This skill is the durable record of how to run that loop cleanly. Sections in order.

### 1. Pre-flight baseline

- Read `CLAUDE.md` Active priorities + `MEMORY.md` index + `ROADMAP.md` headers + `BACKLOG.md` headers + recent 15 commits.
- Probe live: `ops/runtime/health.json`, `https://127.0.0.1:8888/api/health/all`, `http://127.0.0.1:8893/health` (DS engine_version).
- If DS engine_version stale vs repo `agents/daemon_slayer/__init__.py:ENGINE_VERSION`, bounce DS (taskkill + relaunch `start_daemon_slayer.py`; not supervisor-watched).
- Probe CI: `gh run list --limit 6`. Baseline must be green; fix red before any new work.
- Atomic Write the run synopsis to `C:/Users/Administrator/Desktop/RC_HEADLESS_SYNOPSIS_<YYYY-MM-DD>.md`. Header: HEAD sha, ENGINE, RC test count, DS test count, CI status, start time, end-target time, scope, stop rules, phase log table.
- TaskCreate for each phase so progress is visible.

### 2. Phase loop discipline

Every phase is one focused vertical slice. After EVERY phase:

1. **Lint locally**: `py -m py_compile <touched>` and `py -m ruff check <touched>` if Python. F541 (f-string no placeholder) is the most common CI killer. Catch before push.
2. **Test gate**: relevant subset green BEFORE commit. DS engine: `py -m pytest agents/daemon_slayer/tests/ -q`. RC backend: `py -m pytest tests/ --ignore=tests/daemon_slayer -q`. Frontend DOM: `py -m pytest tests/snapshot_panels/ -q`.
3. **Restart-aware**: dashboard route edits -> `echo restart > restart_trigger.txt` + wait ~5s. `_effects_data.py` / engine math -> taskkill+relaunch DS. Asset edits (web/{js,css}/panels/*) -> ADR-008 auto-reload; no RC restart.
4. **Commit + push**: never `git add -A`; stage by filename. Unstage `_scratch/`. HEREDOC commit ending `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`.
5. **CI verify**: `gh run list --limit 4` after push. Red = fix BEFORE next phase.
6. **Synopsis sync**: append phase row to Desktop synopsis table (atomic Write). Sections only; no repeat content.
7. **TaskUpdate** mark phase completed; next in_progress.

### 3. Orchestrator + parallel agent pattern

- Up to **100 parallel worktree agents per task** via `Agent` tool in a SINGLE message (true concurrency).
- Disjoint slices only - each agent owns named files; no two agents touch the same file.
- Each agent prompt MUST:
  - State the goal + the don't-redo set (so it doesn't re-research closed topics).
  - Receive: file paths, line numbers, design intent, exact change expected.
  - Return: branch name, commit sha, test result summary, paths touched.
- Orchestrator (this Claude) merges branches in order, resolves any conflicts, bumps shared counters (ENGINE_VERSION pins) once, pushes once.
- Research agents triage NOW / FUTURE / CLOSED with reasons; orchestrator synthesizes into BACKLOG.md.

### 4. Cost + latency lever sweep (do this every run)

Reoriented to find savings without product degradation. Each lever is evaluated against: does it keep RC ahead of competitors? does it preserve product fidelity?

- **Prompt-cache hit rate**: any new prompt -> static system prefix + dynamic tail; verify cache hit in usage MCP.
- **Model tier traces**: any new advisor() / coach call -> log Haiku vs Sonnet vs Opus selection; default to lowest sufficient tier.
- **Repeat fetches**: 5-min TTL caches for any new dashboard route; cache key invariants over volatile inputs.
- **Polling cadence**: anything polling sub-1s without a real-time gate -> raise to event-driven or 2-5s.
- **Bundle bloat**: any web asset added without an asset-hash bump audit -> investigate.
- **Dead code**: any fleet / vestigial endpoint not referenced -> mark for separate cleanup.
- **Scheduled task overhead**: any cron firing more than once per hour for sparse-cadence data -> downshift.

If a lever conflicts with product fidelity, do NOT apply it; record the conflict in the synopsis.

### 5. UI/UX deep dive checklist (per page when touched)

Beyond LoL when warranted. Research lift sources: Linear, Vercel, Figma, Apple HIG, Material 3, Carbon, Radix, Stripe Docs - methodology only, do NOT vendor.

- **Layout**: 8px grid; consistent paddings; left-rail / right-rail / main grid math.
- **Spacing**: vertical rhythm; section breaks; no orphan controls.
- **Typography**: 4-tier scale max; line-height 1.4-1.6 body; tabular-nums for stats.
- **Color theory**: semantic (good/warn/bad/dim/accent) > brand-only; data-attr driven, not class-explosion.
- **Unification**: same widget for same job everywhere; no two date pickers, two chip styles.
- **Overlay design**: position relative to anchor; ESC closes; backdrop opacity calibrated; never modal for read-only.
- **Ease of use**: 1-click to most-common action; muscle memory > novelty; persistent state via localStorage with explicit migration on shape change.

Per-page UI audit ritual: subagent reviews; orchestrator applies; tests pin contracts; commit; synopsis row.

### 6. A/B tutoring prompt-style coach (when on the coach-prompt task)

Reorient the coach output from prose-block to A/B choice format:

- Each coaching tick produces 1-3 micro-decisions with explicit A / B (sometimes C) options.
- Each option carries: short label, expected outcome, confidence band (low/mid/high), data source tag.
- UI prominence: coach prompt is the SECOND-most-prominent element after live game data; never buried below 3 fold.
- Choice is read-only logged (no input wired yet) so post-game can replay decisions with outcomes.

### 7. DS audit iteration

- Stop rule: 11 consecutive no-change iterations.
- Source of truth: Meraki bulk (`/items.json`, `/items_meraki.json`, champion `aram_modifiers`). Never aggregator D, never aggregator A scrape.
- One math lane per iteration (lethality, %-pen compose, on-hit family, immolate, lich/spellblade, nashor/AP-on-hit, etc).
- Each ENGINE bump: sync 13-14 ENGINE pins across tests + bounce DS server.
- Wider-and-edge-case test variability: prefer parametrized property-style (level x AP/AD x item-set tuples) over single-pin.

### 8. Rewind DB live wire

- `rewind_history.db` weekly catchup task already registered (`RC-RewindCatchup` Sundays 04:00).
- Live wire = streaming new match into DB as soon as Match-V5 returns post-game, without waiting for cron.
- Hook point: `post_game_*` route or `dashboard/_state_authority.py` end-of-game callback.
- Idempotent INSERT OR IGNORE; reuse PUUID-rotation auto-handling via Account-V1.

### 9. Frozen-file edits

- Operator authorization is for CURRENT run only; do NOT carry forward.
- Route AROUND when possible (new sibling module > editing frozen).
- Commit body explicitly notes "frozen-file edit under operator's headless-upgrade grant".

### 10. ASCII hygiene (hard rule)

- No em-dash / en-dash / smart quotes anywhere in authored text (.py / .md / .ps1 / .css / .js / commits / chat).
- Use ` - ` (spaced hyphen) for clause break, `-` otherwise.
- `"-"` no-data sentinel in dashboard renders is operator-approved.
- pytest_guard catches Python; verify .md/.css/.js via grep before commit when in doubt.

### 11. Memory + audit + iterate (folded in)

- **Memory**: save non-obvious patterns surfaced during the run (lift methodologies, anti-patterns, calibration thresholds). Update `MEMORY.md` index single-line.
- **Audit**: per-page UI audit ritual + cost/latency sweep + DS coverage drift + ASCII drift.
- **Iterate**: per-phase, lint -> test -> commit -> CI -> synopsis. No multi-phase batching without commit gate.
- **Test**: prefer parametrized property tests; pin invariants not values; mathematical equivalence > exact float.
- **Improve**: each phase leaves a real, shippable improvement; no half-finished implementations.
- **New tech**: each run sweeps for upstream changes (Riot patch notes, claude API model bumps, browser API additions, repo deps).

### 12. Interrupt protocol

- Operator intent-to-complete ("finish the current run", "wrap up", "complete and done ritual") = STOP starting new phases; FINISH in-flight; run /done.
- Mid-run questions: answer in caveman ULTRA per SessionStart hook unless on critical path; finish critical path FIRST then answer.

### 13. Headless cadence

- Synopsis: per-phase atomic update; never delete mid-run; survives as durable record.
- Living docs (CLAUDE.md item N+1, ROADMAP.md, BACKLOG.md, WAKEUP_NOTES.md, docs/DAEMON_SLAYER.md): one sync commit at run END; surgical, not full rewrite.
- 10h+ extension: transition to full RC refactor audit (multi-agent codebase split).
- Token budget: caveman ULTRA fleet default (SessionStart hook). Compress chat ~90 percent; keep code tokens / paths / numbers / error strings byte-exact.

### 14. The /done ritual at run end

Run `/done` skill: auto-commit + push + WAKEUP_NOTES + living-doc sync + final banner. DO NOT skip.

### 15. Anti-patterns (caught from past runs - do NOT repeat)

- Do NOT `git add -A` without unstaging `_scratch/` first.
- Do NOT skip local `ruff check` (F541 has killed CI 2x).
- Do NOT amend commits; always new commits.
- Do NOT trust agent premise without live-data verification.
- Do NOT dispatch research agent without explicit don't-redo list.
- Do NOT omit ADR-008 asset-hash reload mention on frontend ships.
- Do NOT add feature flags / backwards-compat shims (CLAUDE.md hard rule).
- Do NOT add WHAT-the-code-does comments; comments are for WHY only.
- Do NOT widen one frozen-file grant into wholesale frozen edits; route around.
- Do NOT poll Game-PC manually for state the bridge already delivers.
- Do NOT use `Stop-Process` (hangs MCP pipe); always `taskkill /F /PID`.

### 16. Final banner

When operator interrupt fires or work queue empty:

```
HEADLESS UPGRADE WRAP
  HEAD: <short-sha> (<N> commits this run)
  ENGINE: <old> -> <new>
  DS: <N> tests / <N> subtests
  RC: <N> tests
  CI: <N>/<N> green (<N> red)
  Cost/latency wins: <N> levers applied
  UI/UX: <N> panel passes
  Synopsis: C:/Users/Administrator/Desktop/RC_HEADLESS_SYNOPSIS_<date>.md
  Ready for /done.
```

Then call `/done`.
