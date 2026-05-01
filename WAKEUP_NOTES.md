# Wakeup Notes — 2026-05-01 (session 3 hand-off)

> Hand-off from session that shipped Tier 1 #2 (centralized LiveClient fetch).
> Next session picks up Tier 1 #3 fresh.

---

## What just shipped

| Commit | Summary |
|---|---|
| _pending_ | New `core/liveclient_cache.py` — singleton background poll at 0.5s feeds the latest relay snapshot via immutable `Snapshot` dataclass (`data`, `ts`, `fetched_at`, `no_game`, `age_s` property). Module-level reference + atomic rebind under GIL — no reader lock. Auto-starts on first `get()`; `start()` wired in `main.py` near MetricsCache so the cache is warm before web_dashboard or coaches launch. Migrated 3 consumers off direct HTTP: `coaches/_base_coach._fetch_game_data`, `core/vision_tracker._fetch_snapshot`, `core/decision_detector._fetch_snapshot`. Idle relay traffic drops from ~6–8 polls/s → ~2/s (cache 0.5s + game_reader's overlay-loop poll). |

## State at hand-off

- 4 unpushed commits on `main` (`201ff3a` audit, `0bceb14` regression fix, `9bca527` perf, _pending Tier 1 #2_). User decides on push before 5/10 cloud routine.
- RC alive on Legion — verified post-restart: pid=10916, alive=True, last_reload_ok=True, cache+tracker+detector all logged clean start lines.
- Game-PC `/loop /process-bridge-tasks` was dead at session start (53453s since last bridge result); not re-armed. Liveclient relay snapshot is also stale (Game-PC not pushing fresh data) — cache correctly returns stale snap with age_s ~15h, consumers see age > 12s and treat as no-game. Once Game-PC bridge revives, cache will start serving fresh data immediately.
- `RC-PatchRefresh` scheduled task still showing `last_result=2147942402` — already fixed at the script level (see `project_rc_patchrefresh_fixed.md`); residual error code is from the prior failed run, will clear on next scheduled execution.

## Next: Tier 1 #3 — log retention sweep

`logs/` directory at 191 MB, no day-cap or rotation. Daily log files keep accumulating.

**Goal:** add a retention policy that caps total log dir size or trims by age (e.g. keep last 14 days). Atomic + safe — run from supervisor or dedicated daemon thread.

**Sketch:**
1. New `core/log_retention.py` — function that scans `logs/*.log`, sorts by date, deletes anything older than N days (default 14) OR older than oldest file when total > 100 MB.
2. Call from supervisor on its own slow cadence (every hour, say) OR from main.py at startup + via threading.Timer for periodic runs.
3. Frozen file alert: `core/log_setup.py` is on the frozen list — don't touch its rotation logic. New module sits beside it.

## After #3

- Tier 1 #4 — `agents/state/task_queue.jsonl` rotation (600 KB, no policy)
- Tier 1 #5 — split `web_dashboard.py` (5,775-line monolith)

Full Tier 1–4 list lives in git: `git show 201ff3a -- WAKEUP_NOTES.md` for the audit's original prioritization.

## Session workflow note

Scoped sessions per CLAUDE.md "Session workflow". `/clear` between Tier items.
