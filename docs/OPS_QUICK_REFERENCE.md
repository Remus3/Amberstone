# Riot Commander Ops — Quick Reference Card

## Check System Health
Read: `C:\Riot Commander\ops\runtime\health.json`
Read: `C:\Riot Commander\ops\runtime\status.json`

## Start System
Run: `C:\Riot Commander\ops\launch_new_system.bat`

## File Bridge Operations (write JSON to ops/runtime/bridge_requests/)

### Tail log
```json
{"id": "tail-001", "type": "tail_file", "path": "C:\\Riot Commander\\logs\\2026-04-10.log", "lines": 15}
```

### Grep log
```json
{"id": "grep-001", "type": "grep_file", "path": "C:\\Riot Commander\\logs\\2026-04-10.log", "pattern": "ERROR|CRITICAL", "max_matches": 20}
```

### Get clipboard
```json
{"id": "clip-001", "type": "get_clipboard"}
```

### Set clipboard
```json
{"id": "clip-002", "type": "set_clipboard", "text": "content here"}
```

### Run PowerShell
```json
{"id": "ps-001", "type": "run_powershell", "command": "Get-Process pythonw", "timeout_seconds": 10}
```

### Screenshot region
```json
{"id": "ss-001", "type": "screenshot_region", "bbox": [1600, 0, 1920, 900]}
```

Results appear in: `ops/runtime/bridge_results/{id}.json`

## App Commands (write JSON to ops/runtime/control/commands/)

### Ping app
```json
{"id": "cmd-001", "type": "ping"}
```

### Get app state
```json
{"id": "cmd-002", "type": "dump_state"}
```

### Hot-reload modules
```json
{"id": "cmd-003", "type": "reload_modules", "modules": ["tft.tft_coach_engine"]}
```

### Run callback
```json
{"id": "cmd-004", "type": "callback", "name": "reload_ui"}
```

Results appear in: `ops/runtime/control/results/{id}.result.json`

## Staged Deploy (write JSON to ops/runtime/deploy_requests/)
```json
{
  "request_id": "deploy-001",
  "project_root": "C:\\Riot Commander",
  "staging_root": "C:\\Riot Commander\\ops\\staging",
  "files": [
    {"staged": "tft/tft_coach_engine.py", "live": "tft/tft_coach_engine.py", "reload_mode": "hot_reload", "modules": ["tft.tft_coach_engine"]}
  ]
}
```

Results appear in: `ops/runtime/deploy_results/{request_id}.json`

## Restart via Supervisor
```json
// Write to ops/runtime/supervisor_requests/restart-001.json
{"type": "restart", "reason": "manual restart request"}
```
