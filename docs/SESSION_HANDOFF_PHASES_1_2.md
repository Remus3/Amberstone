# Riot Commander — Session Handoff: Ops System Phases 1-3
## For: Claude Sonnet 4.6 (next session)
## From: Claude Opus 4.6 (this session)
## Date: April 10, 2026

---

## CURRENT SYSTEM STATE (VERIFIED LIVE)

The new ops infrastructure is **running and verified** as of this handoff:

```
✅ Supervisor: RUNNING (PID tracking, auto-restart on crash/stale heartbeat)
✅ File Bridge: RUNNING (handles PowerShell, clipboard, screenshots, log tail)
✅ DevRuntime: RUNNING (heartbeat every 1s, command listener every 0.5s)
✅ App: RUNNING (client mode, LCU auto-accept enabled)
✅ Health: alive=true, last_reload_ok=true
```

Health file location: `C:\Riot Commander\ops\runtime\health.json`
Status file location: `C:\Riot Commander\ops\runtime\status.json`
Supervisor log: `C:\Riot Commander\ops\runtime\logs\supervisor.log`
File bridge log: `C:\Riot Commander\ops\runtime\logs\file_bridge.log`
App log: `C:\Riot Commander\logs\2026-04-10.log`

---

## WHAT WAS COMPLETED (Phases 1 & 2)

### Phase 1 — Infrastructure (DONE)

All ops files written and verified:

| File | Purpose | Status |
|------|---------|--------|
| `ops/rc_dev_runtime.py` | In-process heartbeat + command handler + module reload | ✅ Deployed |
| `ops/rc_transactional_deploy.py` | Staged deploy with compile check + backup + rollback | ✅ Deployed |
| `ops/rc_supervisor.py` | Process manager: auto-start, crash recovery, deploy handler | ✅ Deployed |
| `ops/rc_file_bridge.py` | Windows-MCP replacement: PowerShell, clipboard, screenshot, grep | ✅ Deployed |
| `ops/run_self_healing_watchdog.ps1` | Outer loop keeping supervisor + bridge alive | ✅ Deployed |
| `ops/rc_config.json` | Configured for this system (`pythonw.exe` from PATH) | ✅ Deployed |
| `ops/__init__.py` | Package init | ✅ Deployed |
| `ops/launch_new_system.bat` | One-click launcher (kills old, starts new) | ✅ Deployed |
| `ops/start_ops.bat` | Alternative launcher with directory setup | ✅ Deployed |

All runtime directories created:
```
ops/runtime/control/commands/     ← DevRuntime reads commands from here
ops/runtime/control/results/      ← DevRuntime writes results here
ops/runtime/deploy_requests/      ← Supervisor reads deploy requests
ops/runtime/deploy_results/       ← Deploy results written here
ops/runtime/bridge_requests/      ← File bridge reads requests from here
ops/runtime/bridge_results/       ← File bridge writes results here
ops/runtime/supervisor_requests/  ← Supervisor restart/shutdown requests
ops/runtime/logs/                 ← Supervisor + bridge logs
ops/staging/                      ← Staged files before deployment
ops/backups/                      ← Auto-backups before each deploy
```

### Phase 2 — App Integration (DONE)

`main.py` modified to:
1. Import and start `DevRuntime` at module level (before app creation)
2. Register state provider after app creation (reports mode, tft_mode, has_game, etc.)
3. Stop DevRuntime on quit and in finally block
4. Write fatal errors to `ops/runtime/last_fatal.txt` on crash

Key integration code in `main.py`:
```python
# At module level:
from ops.rc_dev_runtime import DevRuntime
_dev_runtime = DevRuntime(project_root=APP_DIR, app_name="riot-commander")
_dev_runtime.start()

# After app creation:
_dev_runtime.set_state_provider(lambda: {
    "mode": getattr(app, "mode", "unknown"),
    "tft_mode": getattr(app, "_tft_mode", False),
    "aram_mode": getattr(app, "_aram_mode", False),
    "arena_mode": getattr(app, "_arena_mode", False),
    "has_game": getattr(app, "_was_in_game", False),
})
```

### Verified Operations (all tested and confirmed working)

| Operation | Method | Result |
|-----------|--------|--------|
| Ping file bridge | Write JSON to `bridge_requests/` | ✅ pong in <1s |
| Tail log file | `tail_file` bridge request | ✅ Returns last N lines |
| Get clipboard | `get_clipboard` bridge request | ✅ Returns clipboard text |
| Ping app (DevRuntime) | Write JSON to `control/commands/` | ✅ pong in <1s |
| Dump app state | `dump_state` command | ✅ Returns live mode/flags |
| Supervisor auto-start | Kill pythonw → supervisor restarts | ✅ Confirmed in logs |

---

## HOW TO USE THE NEW SYSTEM (Protocols)

### Starting the System
```
Double-click: C:\Riot Commander\ops\launch_new_system.bat
```
This kills old processes, clears `__pycache__`, starts supervisor + file bridge.
The supervisor auto-starts the app (`main.py`).

### Stopping the System
Write a stop file: `C:\Riot Commander\ops\runtime\watchdog.stop` (any content)
Or kill all python processes manually.

### Checking Health
Read: `C:\Riot Commander\ops\runtime\health.json`
- `alive: true` = app running, heartbeat current
- `last_reload_ok: true` = last module reload succeeded
- `mode: "client"` / `"game"` = current app mode

Read: `C:\Riot Commander\ops\runtime\status.json`
- `process_running: true` = supervisor sees app alive
- `pid` = current app process ID
- `last_restart_reason` = why the app was last started

### Using the File Bridge (replaces Windows-MCP)

Write a JSON request to `ops/runtime/bridge_requests/{id}.json`.
Read the result from `ops/runtime/bridge_results/{id}.json`.

**Tail a log file:**
```json
{
  "id": "tail-001",
  "type": "tail_file",
  "path": "C:\\Riot Commander\\logs\\2026-04-10.log",
  "lines": 15
}
```

**Grep a file:**
```json
{
  "id": "grep-001",
  "type": "grep_file",
  "path": "C:\\Riot Commander\\logs\\2026-04-10.log",
  "pattern": "ERROR|CRITICAL|traceback",
  "max_matches": 20
}
```

**Run PowerShell (with timeout, hidden window):**
```json
{
  "id": "ps-001",
  "type": "run_powershell",
  "command": "Get-Process pythonw | Select-Object Id, CPU",
  "timeout_seconds": 10
}
```

**Get/Set clipboard:**
```json
{"id": "clip-001", "type": "get_clipboard"}
{"id": "clip-002", "type": "set_clipboard", "text": "hello world"}
```

**Screenshot a region (saves PNG to disk):**
```json
{
  "id": "ss-001",
  "type": "screenshot_region",
  "bbox": [1600, 0, 1920, 900]
}
```
Result includes `image_path` pointing to the saved PNG.

### Sending Commands to the Running App (DevRuntime)

Write JSON to `ops/runtime/control/commands/{id}.json`.
Read result from `ops/runtime/control/results/{id}.result.json`.

**Ping:**
```json
{"id": "cmd-001", "type": "ping"}
```

**Dump state:**
```json
{"id": "cmd-002", "type": "dump_state"}
```

**Reload modules (hot-reload):**
```json
{
  "id": "cmd-003",
  "type": "reload_modules",
  "modules": ["tft.tft_coach_engine", "tft.tft_live_analysis"]
}
```

**Run a registered callback:**
```json
{
  "id": "cmd-004",
  "type": "callback",
  "name": "reload_ui"
}
```

**Shutdown app:**
```json
{"id": "cmd-005", "type": "shutdown"}
```

---

## PHASE 3 — TRANSACTIONAL DEPLOYS (TODO)

Phase 3 converts the development workflow from direct file writes to staged transactional deploys with automatic backup and rollback.

### The New Deploy Pipeline

```
CURRENT (Phase 2):
  Claude writes file directly → triggers restart_trigger.txt → watchdog restarts

TARGET (Phase 3):
  Claude writes to ops/staging/ → writes deploy request JSON → 
  supervisor picks up → rc_transactional_deploy.py runs:
    1. Compile check staged files
    2. Backup existing live files
    3. Atomic copy staged → live
    4. Clear __pycache__ for touched files
    5. Hot-reload modules OR trigger callback OR request restart
    6. Verify heartbeat updated
    7. If any step fails → restore backup → restart
    8. Write result JSON
```

### Deploy Request Format

Write to `ops/runtime/deploy_requests/{request_id}.json`:

```json
{
  "request_id": "deploy-tft-coach-001",
  "project_root": "C:\\Riot Commander",
  "staging_root": "C:\\Riot Commander\\ops\\staging",
  "runtime_dir": "C:\\Riot Commander\\ops\\runtime",
  "health_file": "C:\\Riot Commander\\ops\\runtime\\health.json",
  "backups_root": "C:\\Riot Commander\\ops\\backups",
  "command_timeout_seconds": 8.0,
  "health_timeout_seconds": 10.0,
  "force_restart": false,
  "files": [
    {
      "staged": "tft/tft_coach_engine.py",
      "live": "tft/tft_coach_engine.py",
      "reload_mode": "hot_reload",
      "modules": ["tft.tft_coach_engine"]
    }
  ]
}
```

### Reload Mode Policy

| reload_mode | When to Use | What Happens |
|-------------|-------------|--------------|
| `hot_reload` | Pure logic modules (coach engine, state reader, game reader, performance tracker, item advisor, composition advisor, core utilities) | `importlib.reload()` on listed modules |
| `callback` | UI modules, overlay panels, comp control | Sends a named callback command to DevRuntime (e.g., `reload_ui`, `reload_tft_overlay`) |
| `restart` | main.py, logging bootstrap, startup order changes | Supervisor performs full process restart |

### Hot-Reload Safe Modules
These can be reloaded without restarting:
- `tft/tft_coach_engine.py` → modules: `["tft.tft_coach_engine"]`
- `tft/tft_live_analysis.py` → modules: `["tft.tft_live_analysis"]`
- `tft/tft_state_reader.py` → modules: `["tft.tft_state_reader"]`
- `coach_integration.py` → modules: `["coach_integration"]`
- `game_reader.py` → modules: `["game_reader"]`
- `performance_tracker.py` → modules: `["performance_tracker"]`
- `composition_advisor.py` → modules: `["composition_advisor"]`
- `item_advisor.py` → modules: `["item_advisor"]`

### Callback-Required Modules
These need registered callbacks (NOT YET IMPLEMENTED — Phase 3 task):
- `ui/*.py` → callback: `reload_ui`
- `tft/tft_overlay.py` → callback: `reload_tft_overlay`
- `tft/comp_control.py` → callback: `reload_tft_overlay`
- `app.py` → callback: `reload_mode_worker`

### Full-Restart Required
- `main.py`
- `overlay.py`
- `core/log_setup.py`
- `ops/rc_dev_runtime.py`

### Phase 3 Implementation Steps

1. **Implement Claude-side deploy helper**: Instead of `Filesystem:write_file` to live paths, write to `ops/staging/` then write a deploy request JSON.

2. **Register reload callbacks in app.py**: Add methods like `reload_ui()`, `reload_tft_overlay()`, `reload_mode_worker()` to `OverlayApp`. Register them with DevRuntime.

3. **Test one hot-reload**: Edit `tft_coach_engine.py` via staged deploy, verify it reloads without restart.

4. **Test one callback reload**: Edit `tft_overlay.py` via staged deploy with callback, verify UI rebuilds.

5. **Test one restart path**: Edit `main.py` via staged deploy with `force_restart: true`, verify supervisor restarts cleanly.

6. **Test rollback**: Deploy a file with a syntax error, verify it auto-rolls back and app stays alive.

7. **Deprecate old workflow**: Stop using `restart_trigger.txt` and `apply_patches.py` for normal code changes.

---

## LEGACY SYSTEM (Still Present, Deprecated)

These files still exist but should NOT be used for normal development:

| File | Old Purpose | New Replacement |
|------|-------------|-----------------|
| `watchdog.ps1` | Poll restart_trigger.txt, restart app | `ops/rc_supervisor.py` |
| `run_watchdog.bat` | Start old watchdog | `ops/launch_new_system.bat` |
| `restart_trigger.txt` | Signal to restart | Deploy request JSON |
| `apply_patches.py` | Fragile string-replace patching | Staged transactional deploy |
| `restart.bat` | Kill + restart app | Supervisor auto-manages |
| `restart_clean.bat` | Kill + clear cache + restart | Supervisor + __pycache__ clearing in deploy |

Do NOT delete these yet — they serve as fallback if the new system has issues.

---

## PROJECT CONTEXT FOR THE NEW SESSION

### What Riot Commander Does
Real-time coaching overlay for League of Legends (SR, ARAM, Arena, Brawl) and TFT. Reads game state from Riot's Live Client Data API (port 2999), sends to Anthropic Claude API for coaching, displays in transparent overlay windows.

### Current TFT Feature State
- 17 meta comps with full data (items, boards, team codes, heuristic top4%)
- Comp list sorted by top4%, item icons (36 PNGs), cost-colored unit names
- Vision-based board reading via Claude Sonnet
- Live coaching via Claude Haiku (~2-3s latency)
- LCU auto-accept queue pops
- Team planner hex codes (may not work until Set 17 live April 15)

### Key File Locations
- **Config**: `ops/rc_config.json`
- **Health**: `ops/runtime/health.json` (read this to check app state)
- **App log**: `logs/2026-MM-DD.log`
- **Meta DB**: `data/meta/tft_set17_meta.json` (17 comps, items, codes)
- **Comp state**: `data/comp_state.json` (selected comp, PBE flag)
- **Match history**: `data/match_history.db` (SQLite)

### Models in Use
- **Opus 4.6**: Architecture, multi-file refactors, this handoff (conversational)
- **Sonnet 4.6**: Routine patches, debug, feature work (next session)
- **Haiku 4.5** (`claude-haiku-4-5-20251001`): Real-time coaching during gameplay
- **Sonnet** (vision): Screen reading via `tft_vision_reader.py`

### Hardware
- Windows 11 MiniPC, 1920×1080 on Samsung Q90R at 120Hz
- League PBE at 1600×900 positioned (0,0)
- iPad Air 5th gen via Duet Display (USB-C) being added as 2nd monitor
- TKL keyboard, forbidden hotkeys: F1-F4, F8, minus

### Known Active Issues
1. **Team planner codes**: HEX format generated but PBE may not accept until live (April 15)
2. **Old watchdog still exists**: Don't run both old and new simultaneously
3. **app.py `_on_game_end`**: Had IndentationError, fixed, but verify after any edits to that method
4. **Windows-MCP**: Frequently times out — use file bridge instead for all routine ops
5. **8 B/C tier comps**: Still need data scraped from Aggregator C

---

## REFERENCE DOCUMENTS

The following documents were provided by ChatGPT (Pro, extended thinking) and guided this implementation:

1. **`RIOT_COMMANDER_ARCHITECTURE_REVIEW.md`** — Top 5 bottlenecks analysis, target architecture, timing estimates
2. **`RIOT_COMMANDER_CLAUDE_IMPLEMENTATION_BRIEF.md`** — Detailed implementation instructions, hot-reload policy, acceptance criteria, concrete integration steps

Both are in the project at `C:\Riot Commander\docs\` and were uploaded to this project's files.

### Acceptance Criteria (from ChatGPT brief)
The redesign is done only when ALL of these are true:
1. ☐ A pure Python coaching-module edit reaches verified live state in under 10 seconds
2. ☐ A UI-only edit reaches verified live state in under 10 seconds without manual log reading
3. ☐ A bad patch auto-rolls back without leaving the app dead
4. ☐ A crashed app is relaunched automatically by the supervisor ✅ (verified)
5. ☐ Log tail, clipboard, screenshot, and process checks run through file bridge ✅ (verified)
6. ☐ `restart_trigger.txt` is no longer the normal path
7. ☐ `apply_patches.py` is no longer the normal path

---

## FIRST TASK FOR THE NEW SESSION

Implement Phase 3, Step 1: **Test one hot-reload deploy**.

1. Make a trivial change to `tft/tft_coach_engine.py` (e.g., change a log message)
2. Write the changed file to `ops/staging/tft/tft_coach_engine.py`
3. Write a deploy request JSON to `ops/runtime/deploy_requests/`
4. Read the deploy result from `ops/runtime/deploy_results/`
5. Verify the module was hot-reloaded without process restart (check health.json PID unchanged)
6. Verify the change is live (check app log for new message)

If that works, proceed to implement reload callbacks in `app.py` for UI modules.
