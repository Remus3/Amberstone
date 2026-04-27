# PHASE_0_HARDENING.md
# Riot Commander — Phase 0: Persistent Self-Monitor Control Plane
# Implementation reference. Keep next to audit/ for Claude session resume.

---

## Files Changed

### New files

| file | purpose |
|---|---|
| `config/self_monitor_profile.json` | Persistent self-monitor config. Survives reboots and chat interruptions. |
| `ops/rc_self_monitor.py` | Self-monitor engine (runs as daemon threads inside supervisor). |
| `ops/rc_incident_log.py` | Structured JSONL incident logger with retention purge. |
| `ops/rc_screen_validator.py` | Low-rate output validator (≤30s interval, no OCR by default). |
| `ops/runtime/monitor_state.json` | Human-readable current monitor state. Claude reads this at session start. |

### Modified files

| file | what changed |
|---|---|
| `app.py` | Item 8: Riot API polling moved to background thread. Removed synchronous `_poll_game()` from `__init__`. Added `_game_poll_worker`, `_drain_game_q`, `_process_game_state`. Exponential backoff 1.5s → 8s max when no game. |
| `ops/rc_supervisor.py` | Added `PidLock` class (RC-1 fix). Added `CircuitBreaker` class. Added rollback request handler. Integrated `SelfMonitor` as daemon threads. Resume-on-boot from profile. |
| `ops/rc_dev_runtime.py` | Added `monitor_control` command type with actions: on/off/status/pause/resume/safe_mode/reset_ladder. |
| `ops/rc_league_watcher.ps1` | Kills legacy watchdog processes on start. Checks PID lock before starting supervisor. Removes watchdog from Stop-Stack. Removes run_self_healing_watchdog.ps1 from Start-Stack. |

### Deprecated (marker files written, originals preserved)

| file | replacement |
|---|---|
| `watchdog.ps1` | `SelfMonitor` threads inside `rc_supervisor.py` |
| `ops/run_self_healing_watchdog.ps1` | `SelfMonitor` threads inside `rc_supervisor.py` |
| `restart.bat` | `rc_league_watcher.ps1` auto-start |
| `restart_clean.bat` | `rc_transactional_deploy.py` rollback path |
| `start.bat` | `rc_league_watcher.ps1` auto-start |

---

## Startup / Resume Flow

```
[Windows boot]
    rc_league_watcher.ps1 starts (Windows Startup entry)
            │
    [League detected]
            │
            ├── Kill any legacy watchdog.ps1 / run_self_healing_watchdog.ps1
            ├── Check ops/runtime/supervisor.pid → exit if another supervisor alive
            │
            ├── pythonw.exe rc_supervisor.py --config rc_config.json
            │       │
            │       ├── PidLock.acquire()  → writes supervisor.pid
            │       ├── _start_self_monitor()
            │       │       ├── reads config/self_monitor_profile.json
            │       │       ├── if resume_on_boot=true AND enabled=true:
            │       │       │       SelfMonitor.set_armed(True)
            │       │       └── SelfMonitor.start()  [2 daemon threads]
            │       │               ├── SelfMonitor-Main  (every 5s)
            │       │               └── SelfMonitor-Cmd   (every 1s)
            │       │
            │       └── start_app("supervisor_boot")
            │               └── pythonw.exe main.py
            │                       └── DevRuntime.start()
            │                               ├── heartbeat thread  (every 1s)
            │                               └── command thread    (every 0.5s)
            │
            └── pythonw.exe rc_file_bridge.py --config rc_config.json

[Overlay now running]
    app.py.__init__:
        self.root.after(200, self._start_game_poll)
            └── [after mainloop enters]
                    _game_poll_worker thread starts
                    [polls Riot API in background, never blocks tkinter]
```

### After a chat interruption / Claude session end

The local processes keep running independently:
- `SelfMonitor-Main` still ticks every 5s
- `SelfMonitor-Cmd` still watches `ops/runtime/monitor_commands/`
- `health.json` is still written every 1s by DevRuntime
- `ops/runtime/incident_log.jsonl` accumulates all events
- `ops/runtime/monitor_state.json` is updated every tick

When Claude reconnects, it reads `ops/runtime/incident_summary.json` to resume context.

---

## Failure / Recovery Flow

### App crash (process exit)

```
[main.py exits]
    Supervisor detects process.poll() is not None on next 1s tick
        CircuitBreaker.allow_restart() → True (if < 5 restarts in 120s)
            stop_app() → start_app("process_exit")
        False (circuit tripped) → log, SelfMonitor records ERROR, wait cooldown
```

### App frozen (heartbeat stale > 15s)

```
[health.json mtime > 15s]
    Supervisor: heartbeat_stale() → restart_app("heartbeat_stale")

    Simultaneously:
    SelfMonitor-Main tick:
        _check_health() → False
        consecutive_fails++ (1st fail: health_check step — wait)
        (2nd fail): thread_restart → DevRuntime callback "restart_game_poll"
        (3rd fail): panel_rebuild → DevRuntime callbacks per allowed panel key
        (4th fail): hot_reload → DevRuntime reload_modules (allowlisted only)
        (5th fail): app_restart → supervisor_requests/restart.json
        (6th fail): rollback → supervisor_requests/rollback.json
```

### Crash loop (5 crashes in 120s)

```
CircuitBreaker trips:
    allow_restart() returns False
    Supervisor logs "circuit_breaker TRIPPED"
    SelfMonitor records ERROR severity entry
    All restart attempts blocked for 300s (default)
    After 300s: CircuitBreaker auto-resets, restarts allowed again
```

---

## How "Self-Monitor" Works Across Reboots

### Enabling

```
# Via Claude MCP (chat phrase "self-monitor on"):
# Claude writes: ops/runtime/control/commands/{id}.json
# { "type": "monitor_control", "action": "on" }
#
# DevRuntime handles it:
# → config/self_monitor_profile.json: enabled=true, resume_on_boot=true
# → ops/runtime/monitor_commands/{id}.json: { "action": "on" }
# → SelfMonitor-Cmd picks it up in <1s → sets armed=True
```

**On next reboot:** `rc_supervisor.py._start_self_monitor()` reads the profile,
sees `resume_on_boot=true` and `enabled=true`, calls `SelfMonitor.set_armed(True)`.
Monitor runs automatically with no Claude involvement.

### State files that persist across reboots

| file | what it stores |
|---|---|
| `config/self_monitor_profile.json` | enabled, resume_on_boot, ladder config, allowlists |
| `ops/runtime/monitor_state.json` | last action, consecutive_fails, circuit_breaker state |
| `ops/runtime/incident_log.jsonl` | full structured event history |
| `ops/runtime/incident_summary.json` | last 20 entries + error counts (Claude reads this) |

### Command routing (no Claude memory required)

```
Chat phrase → Claude generates DevRuntime command → written to control/commands/
DevRuntime command → "monitor_control" handler → profile JSON + monitor_commands/
SelfMonitor-Cmd → reads monitor_commands/ → updates armed/paused state
```

The chat phrase is just a trigger. The behavior is 100% determined by the profile JSON.

---

## How to Disable It Instantly

### Method 1: Kill switch file (fastest — takes effect within 5s)

```
# From any process, script, or PowerShell:
New-Item "C:\Riot Commander\ops\runtime\self_monitor_off.flag" -Force
```

SelfMonitor-Main checks this file every 5s tick. When found:
- `_armed = False` immediately
- All auto-repair stops
- Telemetry (incident_log) continues
- Flag is NOT deleted by the monitor — must be removed manually to re-arm

### Method 2: Monitor off command (persisted)

```
# From Claude MCP:
# "self-monitor off"
# → profile enabled=false, resume_on_boot=false
# → kill_flag written
# → persists across reboots
```

### Method 3: Safe mode (telemetry on, auto-repair off)

```
# From Claude MCP: "self-monitor safe mode"
# → _safe_mode = True
# → health checks and incident logging continue
# → no remediation actions taken
# → does NOT persist across reboots (in-process state only)
```

### Method 4: Pause (temporary, file-based)

```
New-Item "C:\Riot Commander\ops\runtime\monitor_paused.flag" -Force
# Removes: Remove-Item "C:\Riot Commander\ops\runtime\monitor_paused.flag"
```

---

## What Old Paths Are Deprecated

These files are still on disk (not deleted) but are NOT started by anything in the
new stack. `.DEPRECATED` marker files explain this next to each original.

### watchdog.ps1 (project root)

**Was:** Started via Windows Startup, monitored app via restart_trigger.txt.
**Now:** Replaced by `SelfMonitor` daemon threads inside `rc_supervisor.py`.
`rc_league_watcher.ps1` actively kills any running instance of this on start.

### ops/run_self_healing_watchdog.ps1

**Was:** Started by league_watcher, restarted supervisor + bridge every 2s.
**Now:** Supervisor restarts itself are handled by `PidLock` + `CircuitBreaker`.
Bridge restart is no longer needed (bridge is stateless, league_watcher restarts
the whole stack if League closes and reopens).
`rc_league_watcher.ps1` actively kills any running instance on start.

### restart.bat / restart_clean.bat

**Was:** Manual restart triggers, called apply_patches.py.
**Now:** `rc_transactional_deploy.py` handles all patching with rollback.
Supervisor restart is via `supervisor_requests/restart.json`.

### start.bat

**Was:** Manual app start.
**Now:** `rc_league_watcher.ps1` starts the stack automatically when League opens.

---

## Item 8: Before/After Comparison

### Before (blocking main thread)

```python
# In OverlayApp.__init__ — blocks main thread for 2s on every cold start:
if self.reader: self._poll_game()  # urllib.request → 2s timeout on connection refused

# Then every 1.5s:
def _poll_game(self):
    state = self.reader.read_game()  # blocks main thread for up to 2s when no game
    ...
    self.root.after(POLL_GAME_MS, self._poll_game)
```

**Effect:** Every poll cycle when no game running = 2s freeze. Startup = 2s freeze before mainloop.

### After (background thread, non-blocking)

```python
# In __init__ — no blocking call, schedules after mainloop:
self.root.after(200, self._start_game_poll)

# Background thread (never touches tkinter):
def _game_poll_worker(self):
    backoff = 1.5  # starts at 1.5s
    while not self._game_poll_stop.is_set():
        state = self.reader.read_game()  # blocks HERE, not on main thread
        self._game_q.put_nowait(state)
        backoff = 1.5  # reset on success
        # on exception: backoff = min(backoff * 1.5, 8.0)
        self._game_poll_stop.wait(backoff)

# Main thread (drains queue, never blocks):
def _drain_game_q(self):
    while not self._game_q.empty():
        self._process_game_state(self._game_q.get_nowait())
    self.root.after(POLL_GAME_MS, self._drain_game_q)
```

**Effect:** Startup is instant. No-game polling backs off to 8s max. UI always responsive.
