# Riot Commander — Claude Implementation Brief
# (Originally from ChatGPT Pro Extended Thinking, April 10, 2026)
# Status annotations added by Claude Opus 4.6 after implementation.

## Current Status Summary

| Phase | Status | Notes |
|-------|--------|-------|
| Phase 1 — Infrastructure | ✅ DONE | All ops files deployed, directories created |
| Phase 2 — App Integration | ✅ DONE | DevRuntime in main.py, heartbeat working, state provider registered |
| Phase 3 — Deploy Conversion | 🔲 TODO | Infrastructure ready, workflow not yet converted |
| Phase 4 — File Bridge Conversion | ✅ PARTIALLY | Bridge running and tested, not yet default workflow |

## Acceptance Criteria Progress

1. ☐ Pure Python coaching-module edit → live in <10s (needs Phase 3 hot-reload test)
2. ☐ UI-only edit → live in <10s (needs reload callbacks in app.py)
3. ☐ Bad patch auto-rolls back (needs Phase 3 test with broken file)
4. ✅ Crashed app auto-relaunched by supervisor (verified in supervisor.log)
5. ✅ File bridge handles log tail, clipboard, screenshot (verified with ping, tail, clipboard)
6. ☐ restart_trigger.txt no longer normal path (Phase 3)
7. ☐ apply_patches.py no longer normal path (Phase 3)

## What the Next Session Should Do

### Immediate (Phase 3 Step 1): Test Hot-Reload
1. Write a trivial change to `ops/staging/tft/tft_coach_engine.py`
2. Write deploy request to `ops/runtime/deploy_requests/`
3. Verify module reloads without process restart (PID unchanged in health.json)

### Then: Implement Reload Callbacks
Add to `app.py` OverlayApp class:
```python
def reload_ui_modules(self):
    # Destroy and recreate game windows + client windows
    pass

def reload_tft_overlay(self):
    # If TFT coach is active, destroy and recreate its overlay
    pass

def reload_mode_worker(self):
    # Restart the current mode's coach without full process restart
    pass
```
Register in main.py after app creation:
```python
_dev_runtime.register_reload_callback("reload_ui", app.reload_ui_modules)
_dev_runtime.register_reload_callback("reload_tft_overlay", app.reload_tft_overlay)
_dev_runtime.register_reload_callback("reload_mode_worker", app.reload_mode_worker)
```

### Then: Convert Claude's Deploy Workflow
Instead of:
```python
Filesystem:write_file("C:\\Riot Commander\\tft\\tft_coach_engine.py", content)
Filesystem:write_file("C:\\Riot Commander\\restart_trigger.txt", "reason")
```

Do:
```python
Filesystem:write_file("C:\\Riot Commander\\ops\\staging\\tft\\tft_coach_engine.py", content)
Filesystem:write_file("C:\\Riot Commander\\ops\\runtime\\deploy_requests\\deploy-001.json", deploy_request)
# Then read: ops/runtime/deploy_results/deploy-001.json for success/failure
```

See OPS_QUICK_REFERENCE.md for the full deploy request JSON format.
