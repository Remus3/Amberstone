# Wakeup Notes — 2026-05-01 (session 4 hand-off)

> Hand-off from session that shipped Tier 1 #3 (log retention sweep).
> Next session picks up Tier 1 #4 fresh.

---

## What just shipped

| Commit | Summary |
|---|---|
| _pending_ | New `core/log_retention.py` — daemon thread that prunes `logs/*.log*` hourly. Two-pass policy: (1) delete >14d files, (2) if total still >100 MB, delete oldest-first until under cap. Wired into `main.py` after `liveclient_cache` block. `core/log_setup.py` left untouched (frozen) — its 30-day boot prune is now a no-op once the periodic 14-day sweep is running. |

## State at hand-off

- 5 unpushed commits on `main` (2× audit/fix + Tier 1 #2 perf + this one). User decides on push before 5/10 cloud routine.
- **RC NOT yet restarted** — the wired-in `start()` only fires on next RC restart. Until then, logs/ stays at 175 MB. After restart, first prune sweep (immediate, before interval wait) will:
  - Delete 0 files by age (every `*.log*` has mtime ≥ 2026-04-19 from the migration touch — files cross 14d on 2026-05-03)
  - Delete ~37 oldest files / ~77 MB by size cap (175 MB → ~98 MB)
  - From 2026-05-03 onward, age policy starts trimming as files cross the 14-day boundary
- Restart timing is user's call. `echo restart > restart_trigger.txt` triggers it; supervisor restarts in ~5s; verify via `ops/runtime/health.json`.
- Game-PC bridge still dead (last gamepc bridge 54645s as of session start). Liveclient relay snapshots still stale. Doesn't affect this work.
- `RC-PatchRefresh` still showing residual `last_result=2147942402` — fixed at script level, residual code clears on next scheduled run.

## Next: Tier 1 #4 — agents/state/task_queue.jsonl rotation

`agents/state/task_queue.jsonl` currently 600 KB, no rotation policy. Append-only file fed by Phase 3 stack — risks unbounded growth.

**Goal:** add rotation/cap. Likely pattern:
1. Cap at e.g. 5 MB; on rollover, rename `.jsonl` → `.jsonl.1`, keep N backups.
2. OR: trim from the head — keep last N entries, atomic rewrite.

Trim-from-head is probably better here: the queue is FIFO, oldest entries are the least interesting, and keeping a single file simplifies any consumer that scans it.

**Questions to answer before coding:**
- Who reads this file? (`agents/supervisor.py`? Phase 3 dashboard at `:8890`?)
- Is it read whole, or tailed? (Tailed → rename-and-rotate is fine; whole-file scan → trim-from-head is friendlier.)
- Is there a writer lock or file-locking discipline? (If naive append, atomic rewrite needs care — lock or `.tmp` + `replace`.)

## After #4

- Tier 1 #5 — split `web_dashboard.py` (5,775-line monolith)

Full Tier 1–4 list lives in git: `git show 201ff3a -- WAKEUP_NOTES.md` for the audit's original prioritization.

## Session workflow note

Scoped sessions per CLAUDE.md "Session workflow". `/clear` between Tier items.
