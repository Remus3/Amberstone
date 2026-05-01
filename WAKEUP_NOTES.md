# Wakeup Notes — 2026-05-01 (session 2 hand-off)

> Hand-off from session that fixed the audit regression and shipped Tier 1 #1.
> Next session picks up Tier 1 #2 fresh. The 2026-05-01 audit hand-off is preserved
> in git history at commit `201ff3a` if you need it.

---

## What just shipped

| Commit | Summary |
|---|---|
| `0bceb14` | Re-add `import threading` to `app/__init__.py` — undo audit regression that crash-looped RC every supervisor restart (NameError on `threading.Event()` at line 130). Other audit-touched frozen files re-verified clean. |
| `9bca527` | Per-thread sqlite conn cache in `web_dashboard.py` (Tier 1 #1). Helper `_ro_conn()` near `_DIAG_CACHE`. All 6 `sqlite3.connect()` sites migrated. Measured: p50 3.7 ms warm vs ~20–80 ms cold pre-refactor. |

## State at hand-off

- 3 unpushed commits on `main` (`201ff3a` audit, `0bceb14` regression fix, `9bca527` perf). User decides on push before 5/10 cloud routine.
- RC is alive on Legion — verify each session via `ops/runtime/health.json` (pid varies).
- Game-PC `/loop /process-bridge-tasks` was dead at session start; not re-armed. If the user invokes Game-PC Claude, type `/loop 1m /process-bridge-tasks` over there to revive bridge auto-flow.
- `_archive/2026-05-01-audit/` quarantine still in place. After a few clean days, user may `rm -rf` it.

## Next: Tier 1 #2 — centralize LiveClient fetch

`coaches/_base_coach.py` × 4 modes (aram, arena, brawl, sr) each spawn 2 daemon threads, all polling `127.0.0.1:8889/latest-liveclient` every 1.5 s. Plus `vision_tracker` (0.75 s) and `decision_detector` (1.0 s) hit the same endpoint. Idle relay sees ~6–8 polls/sec with no game running.

**Goal:** consolidate into one shared 0.5 s poll cached process-wide. Each consumer reads from cache; no consumer hits HTTP directly. Model: `_STATE_CACHE_PAYLOAD` at `web_dashboard.py:1261`.

**Sketch:**
1. New `core/liveclient_cache.py` — module with `get()` returning the latest cached payload + ts, `start()` launching the singleton fetcher thread.
2. `_base_coach.py` poll loop and vision loop call `liveclient_cache.get()` instead of urlopen. Drop the HTTP fetch from each mode coach.
3. `vision_tracker.py` and `decision_detector.py` migrate to the same cache.
4. `main.py` calls `liveclient_cache.start()` once near MetricsCache init.

**Safety:** cache TTL <= 0.5 s so consumers see ~live data; if no game, fetch returns None (existing semantics).

## After #2

- Tier 1 #3 — log retention sweep (logs/ at 191 MB, no day-cap)
- Tier 1 #4 — `agents/state/task_queue.jsonl` rotation (600 KB, no policy)
- Tier 1 #5 — split `web_dashboard.py` (5,775-line monolith)

Full Tier 1–4 list lives in git: `git show 201ff3a -- WAKEUP_NOTES.md` for the audit's original prioritization.

## Session workflow note

CLAUDE.md now codifies scoped-session discipline: commit + WAKEUP_NOTES update + memory write at end of each task; `/clear` to start fresh. Auto-compact at 75% is a safety net, not the primary tool. See "Session workflow" section in CLAUDE.md.
