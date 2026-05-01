# Wakeup Notes — 2026-05-01 (session 5 hand-off)

> Hand-off from session that shipped Tier 1 #4 (task_queue.jsonl compaction).
> Next session picks up Tier 1 #5 fresh.

---

## What just shipped

| Commit | Summary |
|---|---|
| 5e24afb | `Scheduler.compact()` + hourly daemon thread on `agents/state/task_queue.jsonl`. Keeps the latest event per task_id; `_load()` already had latest-wins semantics, so in-memory state is unchanged. Threshold 2 MB, interval 1h. 3 unit tests added (`test_compact_*` in `test_agent1.py`). Live-file dry-run: 571 → 200 lines, 605 KB → 305 KB (50% reduction). |

## State at hand-off

- **7 unpushed commits** on `main` (was 6). User decides on push before 5/10 cloud routine.
- **RC NOT yet restarted** — both the log-retention daemon (#3) and now the queue-compaction daemon (#4) only start on next RC restart. Until then, no behavioural change in production.
  - Once restarted, the compactor's first wake-up runs `_maybe_compact()` and skips (file is 605 KB, under the 2 MB threshold). It's preventative; the file has months of headroom at current growth rates.
- Restart timing is user's call. `echo restart > restart_trigger.txt` triggers it; supervisor restarts in ~5s; verify via `ops/runtime/health.json`.
- Game-PC bridge still dead. Liveclient relay snapshots still stale. Doesn't affect this work.
- `RC-PatchRefresh` still showing residual `last_result=2147942402` — fixed at script level, residual code clears on next scheduled run.
- `agents/agent3_testing/suite/test_scheduler_lock.py::test_two_processes_no_interleaved_lines` is flaky on Windows (PermissionError on file read under contention) — passes on re-run, predates this session's work, not introduced here.

## Next: Tier 1 #5 — split `web_dashboard.py` (5,775-line monolith)

`web_dashboard.py` at the project root is the single biggest file in the codebase and a known maintenance hazard. Per the Tier 1 audit it needs decomposition.

**First-step questions to answer before coding:**
- What are the natural seams? Likely candidates: (a) HTTP route handlers vs. data assembly, (b) the per-route handlers themselves (`/api/state`, `/api/health`, `/api/input`, `/api/command`, `/api/loadout/*`, `/api/ocr*`, `/api/vision-state`, `/api/analyze`, …), (c) the static-asset serving block, (d) the MetricsCache integration, (e) the per-thread sqlite conn cache that landed in 9bca527.
- Is there shared module-level state that pinning route handlers in separate files would force into globals? (If so, define the seam carefully — a `DashboardServer` class holding the cache + DB conn is probably cleaner than module globals.)
- Is `web_dashboard` imported anywhere besides `main.py`? (`grep` for it.) Any external import surface constrains the refactor.

**Likely shape:**
1. Inventory the file: routes, helper functions, top-level state.
2. Pick a decomposition. Probably: `web/` package with `web/__init__.py` (server lifecycle), `web/routes_state.py`, `web/routes_loadout.py`, `web/routes_ocr.py`, `web/routes_command.py`, `web/static.py`, plus a shared `web/_context.py` for the cache + db conn.
3. Move route handlers in groups, run `python -m py_compile` after each move, verify dashboard still serves on `:8888`.
4. Keep `web_dashboard.py` as a tiny shim that imports + re-exports the public entry from the new package, so `main.py` doesn't have to change.

This one is bigger than #1–4 — likely takes a full session by itself just to inventory and ship the first split. Don't try to do it all at once.

## After #5

- Tier 1 list complete after #5. Tier 2 priorities live in `git show 201ff3a -- WAKEUP_NOTES.md` (audit's original prioritization).

## Session workflow note

Scoped sessions per CLAUDE.md "Session workflow". `/clear` between Tier items.
