---
description: End-of-session checkpoint for Game-PC Claude. Run before Ctrl+C / closing the Game-PC Claude Code session so nothing falls on the floor before next launch.
---

The user is about to end the Claude Code session on Game-PC. Verify state so the next launch (or live game) can pick up cleanly. Run all checks; surface a tight summary at the end with each item ✅ / ⚠️ / ❌. Do NOT print results to chat for the user to relay to Legion — this checklist is for them, run on Game-PC.

### 1. The 5 agent processes — all alive?
```powershell
Get-CimInstance Win32_Process -Filter "Name='py.exe' OR Name='python.exe' OR Name='pythonw.exe'" |
  Where-Object { $_.CommandLine -match 'gamepc_(screen_agent|lcu_agent|liveclient_relay|mcp_server|hotkey_listener)' } |
  Select-Object ProcessId, @{n='agent';e={ ($_.CommandLine -split '\\')[-1] }}, CreationDate |
  Format-Table -AutoSize
```
Expect: 5+ entries (screen-league, screen-minimap, screen-ui, lcu, liveclient-relay, mcp-server, hotkey-listener — possibly more if multiple screen-agent variants). Note any missing.

### 2. MCP server bound on `:8892`
```powershell
Get-NetTCPConnection -LocalPort 8892 -State Listen -ErrorAction SilentlyContinue
curl.exe -s -m 3 -H "Authorization: Bearer 8e8f131e212b329438218eca27372dde" http://127.0.0.1:8892/health -o NUL -w "HTTP %{http_code}`n"
```

### 3. Bridge auto-flow loop alive
- Type `/loop list` — confirm a job exists running `/process-bridge-tasks`. If absent: warn the user that bridge results won't auto-flow next session unless re-armed with `/loop 1m /process-bridge-tasks`.

### 4. Pending bridge tasks for me
- Run `py C:\RC-Agent\bridge_pull_tasks.py --target gamepc` — note any unanswered tasks. The user should know if they're leaving Legion-side requests dangling.

### 5. Edge dashboard window
```powershell
Get-Process msedge -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -like '*Riot Commander*' -or $_.MainWindowTitle -like '*Phase 3*' } | Select-Object Id, MainWindowTitle | Format-Table -AutoSize
```
Expect: 1 window. Note its title for verification.

### 6. League state
```powershell
Get-Process | Where-Object { $_.Name -like 'League*' -or $_.Name -like 'RiotClient*' } | Select-Object Id, Name, MainWindowTitle | Format-Table -AutoSize
```
If League is running and the user's mid-game: WARN them — Ctrl+C only ends the Claude session, won't crash League, but they lose live bridge auto-flow until they re-launch.

### 7. Final summary
Print a short table: section / status / what's left. Last line: explicit "✅ safe to Ctrl+C" or "⚠️ resolve <X> first."

The /loop in step 3 is the easy thing to forget — it dies on session exit and the user has to re-arm it on next launch. Make that warning loud if the loop is currently active and they're about to lose it.
