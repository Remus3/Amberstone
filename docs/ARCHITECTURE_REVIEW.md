# Riot Commander Architecture Review

## Executive Summary

The current loop is slow for one reason above all others: every ordinary code change is treated like a cold restart problem. That creates a deterministic tax on every iteration. The second major drag is the Windows-MCP dependency for routine diagnostics. The third is the mutation path itself: direct live writes and fragile string-replacement patching create rework loops.

The fastest path to sub-10-second iterations is not a full rewrite. It is a control-plane redesign:

1. staged transactional deploys instead of live writes
2. in-process heartbeat and hot-reload callbacks
3. a persistent supervisor with auto-rollback
4. a file-based debug bridge that replaces Windows-MCP for routine tasks

## Top 5 Bottlenecks

1. Full restart plus manual verification after almost every change.
2. Windows-MCP timeouts, oversized snapshots, and failed screenshot / PowerShell operations.
3. Fragile patch application through direct file replacement and string `.replace()` patch scripts.
4. Manual diagnosis caused by weak observability and silent failure modes.
5. Web scraping and data acquisition on the active development path.

## Redundant Steps to Remove

- direct live write -> trigger file -> watchdog poll -> restart.bat -> optional patch script -> manual log tail
- separate `restart.bat` and `restart_clean.bat`
- separate live-write and patch-script mutation paths
- Windows-MCP for routine PowerShell, clipboard, process, and screenshot tasks
- repeated full-process restart for code that could be hot-reloaded

## Target Architecture

### Phase 1 ✅ DONE
- add `ops/rc_dev_runtime.py`
- add `ops/rc_supervisor.py`
- add `ops/rc_transactional_deploy.py`
- add `ops/rc_file_bridge.py`
- replace old watchdog with `run_self_healing_watchdog.ps1`

### Phase 2 ✅ DONE
- integrate heartbeat into `main.py` / `app.py`
- register reload callbacks for UI and worker rebuilds (PARTIALLY — state provider done, callbacks TODO)
- move deploys to staged files + deploy request JSON (infrastructure done, workflow conversion TODO)

### Phase 3 — TODO
- split stable overlay shell from volatile mode workers
- hot-reload worker modules and restart only the worker when possible
- implement reload callbacks in app.py (reload_ui, reload_tft_overlay, reload_mode_worker)
- convert Claude's deploy workflow from direct writes to staged deploys

## Expected Timing After Redesign

### Hot-reload path
- write staged file: 1-2s
- compile + backup + activate: 1-2s
- in-process module reload / callback: 1-3s
- heartbeat verify: 1-2s

Expected total: 4-8s

### Restart fallback path
- deploy + backup: 1-2s
- controlled restart under supervisor: 4-6s
- heartbeat verify: 1-2s

Expected total: 6-9s

## Model Recommendations

- Opus for architecture, cross-file recovery, and high-risk refactors
- Sonnet for routine debug / patch sessions
- Haiku for runtime coaching and latency-sensitive flows
- prompt caching for large fixed instruction blocks
- batches only for offline evals / backfills
