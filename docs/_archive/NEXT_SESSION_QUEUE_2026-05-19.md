# NEXT SESSION QUEUE - single-prompt overnight autonomous run

> Queued 2026-05-19. Execute this file end to end after /clear. Self-contained on purpose: /clear wipes context, so do not assume anything from the prior session beyond CLAUDE.md + MEMORY.md + WAKEUP_NOTES.md + git log.

## Run-wide authorization and rules

- OPERATOR AUTHORIZED full read/write to ALL files INCLUDING every frozen file in the CLAUDE.md frozen list, for this entire run. Treat this queue as the explicit per-file approval the frozen-files hard rule requires. Still: py_compile before every restart, atomic writes only, restart via restart_trigger.txt, never Stop-Process (taskkill /F /PID as hard fallback), verify ops/runtime/health.json pid/alive/last_reload_ok after each restart.
- Caveman ultra stays on (headless overnight). ASCII only, no em/en dashes, no smart quotes, in every authored byte.
- Run autonomous. Do not stop to check in. Continue until Phase 3 completes or a hard blocker. Use /done, compact, refactor, split, test, research, expand, archive as needed between units of work.
- Commit + push after every discrete unit. Conventional-commit style matching the repo log.

## Phase 0 - setup tasks (do first, in order, each its own commit+push)

1. OPEN LEVER - scope the full-pytest PostToolUse hook to skip docs-only edits.
   - Locate the PostToolUse pytest hook (machine-local gitignored .claude/settings.json; it may call a tracked tools/ script or run pytest inline).
   - Add a guard so an Edit/Write whose paths are ONLY *.md / docs/** / *.txt skips the suite; any *.py or other code-path edit still runs it.
   - Prefer the gate logic in a tracked tools/ script so it is committable; if it can only live in settings.json (gitignored), document the exact change in WAKEUP_NOTES.
   - Verify: a docs-only edit does NOT trigger pytest; a .py edit DOES. Commit+push any tracked artifact.

2. Extend the ship-batch skill: one pass that selects the next Daemon Slayer batch from ROADMAP, implements it, runs the full DS suite, bumps ENGINE_VERSION with a guard test, verifies :8893 /health, commits, pushes, and appends the WAKEUP_NOTES hand-off. Locate the skill file; honor the sync-all-md precedence (tracked tools/ copy wins, mirror to .claude/commands, both byte-identical and ASCII-clean).

3. Trace all LLM calls in the codebase. Group by model tier (Haiku vs Sonnet vs Opus advisor). Tag polling/interval callers. Reconcile tracked cost against the dashboard total and explain any gap. Write findings to docs/ and summarize in WAKEUP_NOTES.

4. Re-verify the corrected insights report numbers (ENGINE version, DS test count, RC suite count, commit count, patch) against live /health :8893 + agents/daemon_slayer/__init__.py + git + the .md docs. Flag every divergence and regenerate the narrative from verified values. Artifact (LOCAL, not in repo): C:\Users\Administrator\.claude\usage-data\report-corrected-2026-05-19.html.

5. Parallel Multi-Batch Engine Pipeline. Spin up 3 to 12 worktree subagents: A = next item-effects batch, B = augment registry against live cdragon, C = scorer tuning, plus any further split that expedites. Each adds tests on its own branch. Then act as integration coordinator: merge all subagent work without error, run the full DS suite, resolve a SINGLE ENGINE_VERSION bump, ship one commit, /done.

6. Self-Healing Cost and Health Watchdog. 15-minute cron on the existing cron/bridge loop: probe RC daemon health, bridge connectivity, tracked-vs-dashboard API cost. On a 1.5x baseline breach or a daemon flap: trace the call chain, identify the Sonnet-calling files, apply a debounce/interval or pythonw fix, add a regression test, commit, post a summary to WAKEUP_NOTES. Never silently restart without logging.

7. Test-First Spec-to-Ship Autopilot. A skill that takes a batch spec, scaffolds property-based tests from live cdragon/Riot math (no hardcoded magic numbers, no fragile cross-item comparison asserts), loops Edit/pytest until 100% green, then bumps ENGINE_VERSION, commits, pushes, /done.

## Phase 1 - overnight headless DS audit (minimum 4 hours, iterative loop)

Full-permission iterative audit on Daemon Slayer. Loop: test -> fix -> bump -> commit+push -> /done -> continue.
- Verify all engine math (the linear->Riot-quadratic stat-growth fix is already in ENGINE 1.5.0; re-verify everything else - DPS, EHP, penetration pipeline, attack-speed scaling, ability lambdas, build-order unique-passive families).
- Run every variable sim that can be wired up.
- Verify and validate pick/ban logic against itself AND against every system that interacts with it even sidelong (champ-select routes, smoothed_rates, draft composition, coaches).
- Re-verify and improve enemy-team item modeling with 1-item, 2-item, 3-item, 4-item, 5-item and 6-item variations, across varying timeframes and varying champion levels.
- Any "trivial" nuance discovered: scope it out and apply it.

## Phase 2 - backlog drain

Stop the DS audit loop ONLY after 10+ consecutive iterations with NO change. Track the no-change streak and report "stale N/10, est remaining M" every loop. Then process BACKLOG.md in priority order with the same loop discipline (test, commit+push, /done, continue).

## Phase 3 - full conventions audit (only if the backlog finishes)

Fully inclusive: every line + every document + every code trail. Verify top-tier professional coding conventions are enacted and exceed the project standard. Fix, commit, push, document.

## Stop / report discipline

- Every loop: surface iteration count, no-change streak, estimated remaining.
- py_compile before every restart; verify health.json after.
- Frozen-file writes AUTHORIZED for this run (operator explicit) - still compile + restart-verify.
- Hard blocker -> stop, write the blocker + state to WAKEUP_NOTES, do not thrash.
