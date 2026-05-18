# HEADLESS BRIEF - s171.8 docs + tests backfill (overnight run)

> **Staged**: 2026-05-12 ~02:15 by Claude Opus 4.7
> **Mode**: `/loop` self-paced, 1M context
> **Cap**: 5 commits OR 4 hours OR test failure (whichever first)
> **Risk profile**: LOW - docs + tests only, no behavior changes

## Goal

Backfill the documentation and test gaps for the s171.8 work that shipped
during session 172 (commits `3e3b14e`, `1aba0da`, `876fd01`). That session
fixed three live bugs and one meta-bug, but the doc/test coverage was
tactical not strategic. This brief closes that.

## Context - you have no memory of session 172, read these first

1. `CLAUDE.md` - project conventions, frozen file list, restart workflow
2. `WAKEUP_NOTES.md` - last 3 sessions (s171.8 is the most recent at top)
3. `git log --oneline -10` - the four s171.8 commits to understand
4. `docs/ARCHITECTURE.md` - module map (sections on dashboard + view router)
5. `docs/adr/ADR-007-event-coach-pivot.md` - most recent ADR for tone match

## Tasks (in strict order - each is its own commit, push between)

### Task 1: Integration tests for view-router state machine

**Files**:
- New: `tests/test_view_router_state.py` (or similar - match repo's
  pytest convention; existing tests live under `tests/` or
  `agents/agent3_testing/suite/`)

**Why**: s171.8 added sticky-guard inference + dodge clearing in
`web/js/main.js:_viewAutoDerive` (around line 482-551). The logic is
non-trivial but currently has zero unit coverage - only the static
panel snapshot tests touch it. Operator can't easily re-verify the
state machine without playing a live game.

**Approach**: extract the pure state transition logic into a testable
form. Two options, pick whichever has less impact:

  - **A**: Port the transition logic to a Python helper in a new
    `dashboard/view_router_state.py` module, then call it from tests.
    Don't change main.js - keep the JS as the source of truth for
    runtime, the Python as a test mirror. Mark the module as a "test
    mirror" in its docstring so future drift is obvious.

  - **B**: Add a Node-driven unit test under `tests/` that imports
    `web/js/main.js` via dynamic ESM and drives `_viewAutoDerive`
    directly. Requires extracting that function from inside the IIFE
    closure - invasive.

  Recommend A unless B turns out clean. A risk: drift between JS and
  Python mirror. Mitigation: docstring with "if you change one, change
  both, both should agree on the same transition table."

**Cover**:
- ChampSelect → GameStart → InProgress → EndOfGame → Lobby (clean cycle)
- ChampSelect → Lobby (dodge - sticky should clear, not get stuck)
- ChampSelect → null → GameStart (transient null, sticky should hold)
- ChampSelect → null (extended, no GameStart observed) - sticky-guard
  inference advances to "game-start" per s171.8 fix
- InProgress → null/None/Lobby - gameStarted stays "in-progress"
- EndOfGame after in-progress → clears sticky
- Manual view sticky → auto-derive returns same view + urgent banner

**Verify**: `py -m pytest tests/test_view_router_state.py -v`
all green; full smoke suite still green
(`py -m pytest tests/phase2_smoke tests/phase8_smoke -q`).

**Commit message**: `test: view-router state machine integration coverage`

---

### Task 2: Sync ROADMAP.md with s171.8 work

**Files**: `ROADMAP.md`

**What to add**:
- New entry (likely #29 - check current numbering) summarizing:
  - Loading-view sticky-guard inference (`web/js/main.js:491-551`)
  - Phase 3 file_ingest LCU phase overlay (`agents/agent2_backend/file_ingest.py`)
  - Build-variant persistence (`web/js/panels/champ_select.js` -
    `_csvBuildVariantsFor` + `_csvSaveChoice`)
  - Unified asset-hash + auto-reload (`dashboard/_static.py` +
    `dashboard/routes_state.py`)
- Cross-reference the three commits
- Mark items 13/14 (vision calibration, DS calibration) as still
  blocked on live game

**Don't**: rewrite history, restructure existing entries, or remove
completed items. Append + cross-reference only.

**Commit message**: `docs: sync ROADMAP - s171.8 view-router + asset-hash fixes`

---

### Task 3: Draft ADR-008 for unified asset-hash decision

**Files**: New: `docs/adr/ADR-008-unified-asset-hash.md`

**Why**: The two-divergent-file-lists bug was a textbook example of
parallel-implementations drift. The architectural lesson - "one
source of truth for cache-busting" - deserves capture so a future
contributor doesn't re-introduce it.

**Structure** (match `docs/adr/ADR-007-event-coach-pivot.md` for tone):
- **Context**: two functions, `compute_asset_hash` and `_serve_ui_version`,
  each maintaining its own file allow-list. Diverged since s164 introduced
  `champ_select.js` to one but not the other. Resulted in browsers serving
  pre-s171.7 code from cache the entire CS→s171.7 window.
- **Decision**: `/api/ui-version` defers to `compute_asset_hash`. The
  parts list is the union of: root assets (index.html, dashboard.css,
  dashboard.js, main.js, sim.js, ws_client.js) + walked subdirs
  (web/css/panels/*.css, web/js/panels/*.js, web/js/lib/*.js).
- **Consequences**: future panel additions auto-bust caches without
  registry edits. Auto-reload poller fires on any watched file change.
- **Trade-offs**: more file stats per asset-hash compute (cached 2s,
  so negligible cost in practice).
- **Status**: Accepted, shipped 2026-05-12 (commits 1aba0da + 876fd01).

**Commit message**: `docs(adr): ADR-008 unified asset-hash for cache + auto-reload`

---

### Task 4: Prune WAKEUP_NOTES.md → history_notes.md

**Files**: `WAKEUP_NOTES.md`, `docs/history_notes.md`

**What**: Move the s170 section (currently the oldest in WAKEUP_NOTES)
to `docs/history_notes.md`. Keep last 3 sessions in WAKEUP_NOTES
(s171, s171 wrap, s171.8 - the new entry from task 5 below).

**Check first**: `scripts/wakeup_prune.py` may exist and automate this.
If so, run it. If not, do it by hand.

**Commit message**: `chore: prune WAKEUP_NOTES - s170 → history_notes`

---

### Task 5: Add s171.8 wrap to WAKEUP_NOTES.md

**Files**: `WAKEUP_NOTES.md` (top of file, push older sessions down)

**Structure** (match the existing s171 wrap entry for shape):
- Session date + theme
- Ships table (4 commits: 3e3b14e, 1aba0da, 876fd01 - and the wrap
  commit /done will create)
- Findings table (esp. the two-asset-hash drift bug)
- Open items
- Files touched

**Commit message**: `docs: WAKEUP wrap - s171.8 view-router + cache-bust unification`

---

## Stopping conditions (READ CAREFULLY)

| Trigger | Action |
|---|---|
| All 5 tasks shipped + CI green on each | Final commit + push + done |
| Any test failure mid-task | STOP. Append note to `WAKEUP_NOTES.md` under "🚨 headless run halted". Do NOT attempt to fix. |
| Any CI run red after push | STOP. Same note. |
| 4 hours elapsed | STOP. Note progress in `WAKEUP_NOTES.md`. |
| Frozen file accidentally touched (see CLAUDE.md list) | REVERT immediately. STOP if revert fails. |

## Safety rails

- **NEVER** `--no-verify` on any git command
- **NEVER** force-push
- **NEVER** amend a published commit
- Commit one task at a time; `gh run watch <id>` after each push;
  wait for green before starting the next task
- Conventional Commit format (project enforces via commit-msg hook):
  `<type>(<scope>)?: <description>` - types: feat, fix, docs, chore,
  refactor, test, perf, ci, build, style
- Co-Authored-By trailer: `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`
- Frozen files (do NOT modify): `main.py`, `core/log_setup.py`,
  `core/moon_proxy.py`, `lcu/lcu_client.py`, `core/game_snapshot.py`,
  `ops/rc_dev_runtime.py`, `ops/rc_supervisor.py`, `app/__init__.py`,
  `app/_loop.py`, `app/_health_monitor.py`, `app/_remediation.py`,
  `app/_state_authority.py`, `app/_overlay_manager.py`,
  `app/_game_lifecycle.py`, `tools/bridge_watcher*.py`,
  `dashboard/routes_bridge_pending.py`, `ops/RC-BridgeWatcher.xml`,
  `tools/process-bridge-tasks.md`, `tools/diagnose.md`,
  `tools/caveman.md`. (Full list always in CLAUDE.md.)

## End-of-run

When all 5 tasks ship green, append one final line to
`WAKEUP_NOTES.md` (top section): `**headless run complete** - N commits,
T elapsed. Operator: run morning audit brief (`HEADLESS_BRIEF_2026-05-12_AUDIT.md`)
when ready.`

Then stop the loop. No further iterations.
