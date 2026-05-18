---
description: End-of-session ritual for Game-PC Claude - wrap-gamepc checks + drain pending bridge tasks + ready-for-/clear banner. Game-PC has no git repo (agents pulled fresh from Legion's /agent/ allowlist), so there's no commit/push step - this is a state-check + drain ritual, not a "ship the work" ritual.
---

The user is about to /clear on Game-PC. Verify peer state so Legion-side workflow doesn't lose anything. Run all sections in order; surface a tight banner.

### 1. Drain any pending bridge tasks targeted at this node

- `py C:\RC-Agent\bridge_pull_tasks.py --target gamepc` - any open tasks?
- If non-empty: invoke `/process-bridge-tasks` once to drain. Per the canonical skill, exit silently if empty.
- After draining: re-pull and confirm count = 0. If still non-empty after one round, the loop has a live task it couldn't classify - surface in banner ABOVE the box.

### 2. The 5 (or more) agent processes - all alive?

```powershell
Get-CimInstance Win32_Process -Filter "Name='py.exe' OR Name='python.exe' OR Name='pythonw.exe'" |
  Where-Object { $_.CommandLine -match 'gamepc_(screen_agent|lcu_agent|liveclient_relay|mcp_server|hotkey_listener)' } |
  Select-Object ProcessId, @{n='agent';e={ ($_.CommandLine -split '\\')[-1] }}, CreationDate |
  Format-Table -AutoSize
```

Expect 5+ entries. Note any missing (banner: ⚠️ agent X dead).

### 3. MCP server `:8892` listening

```powershell
Get-NetTCPConnection -LocalPort 8892 -State Listen -ErrorAction SilentlyContinue
curl.exe -sk -m 3 http://127.0.0.1:8892/health -o NUL -w "HTTP %%{http_code}`n"
```

If not 200: ⚠️ in banner.

### 4. bridge_watcher scheduled task healthy

```powershell
schtasks /Query /TN RC-BridgeWatcher-GamePC /V /FO LIST | Select-String -Pattern 'Status|Last Run Time|Last Result'
Get-Content C:\RC-Agent\bridge_watcher_health.json | ConvertFrom-Json | Select-Object pid, alive, last_poll_ok, queue_depth, escalations_since_boot, auto_actions_since_boot, auto_err_since_boot
```

Confirm `alive=True`, `last_poll_ok=True`. If `Last Result` is non-zero hex: ⚠️.

### 5. Bridge health publisher (if installed)

```powershell
schtasks /Query /TN RC-WatcherHealthPublisher-GamePC /V /FO LIST 2>$null | Select-String -Pattern 'Status|Last Run Time|Last Result'
curl.exe -sk -m 3 https://legion-rc:8888/api/health/peer/gamepc -o gp_peer.json
type gp_peer.json | ConvertFrom-Json | Select-Object stale, age_s
```

If publisher task missing entirely: note in banner - Legion's fleet rollup won't see this node until installed.
If `stale=true`: ⚠️ in banner - publisher running but POST failing (check token, network).

### 6. /loop /process-bridge-tasks status

- Type `/loop list` and confirm a `/process-bridge-tasks` job is armed.
- **CRITICAL:** /loop dies on /clear. After /clear the operator must re-run `/loop /process-bridge-tasks` (or `/loop 1m /process-bridge-tasks` for fixed cadence) to resume auto-flow.
- Banner explicitly mentions this so the operator doesn't forget.

### 7. League state

```powershell
Get-Process | Where-Object { $_.Name -like 'League*' -or $_.Name -like 'RiotClient*' } | Select-Object Id, Name, MainWindowTitle | Format-Table -AutoSize
```

If mid-game: WARN. /clear here won't crash League but kills live cross-Claude bridge auto-flow until next session + /loop re-arm.

### 8. Edge dashboard window still up

```powershell
Get-Process msedge -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -like '*Riot Commander*' -or $_.MainWindowTitle -like '*Phase 3*' } | Select-Object Id, MainWindowTitle | Format-Table -AutoSize
```

Expect 1 window. The dashboard should keep rendering after /clear (it's just an Edge tab); confirm presence so operator knows nothing visible was lost.

### 9. Final banner

```
══════════════════════════════════════════════════════════════════
  /done complete (gamepc) - context ready for /clear
══════════════════════════════════════════════════════════════════
  • pending bridge tasks  : drained <N> | empty
  • agents alive          : <count>/5+
  • MCP :8892 health      : ✅ 200 | ❌ <code>
  • bridge_watcher        : pid=<pid> alive=<bool> q=<depth>
  • health publisher       : ✅ fresh (<age>s) | not installed | ⚠️ stale
  • /loop bridge-tasks    : ✅ armed - WILL DIE ON /clear
  • League / mid-game     : no | YES - bridge auto-flow ends until re-arm
══════════════════════════════════════════════════════════════════
  Type /clear to start a fresh session.
  After /clear: re-run /loop /process-bridge-tasks to restore auto-flow.
══════════════════════════════════════════════════════════════════
```

If anything ⚠️/❌, surface ABOVE the banner with concrete remediation.

### Safety rails

- NO git operations (no repo on Game-PC).
- NEVER taskkill RC-BridgeWatcher-GamePC - it's the daemon supervisor will restart cleanly.
- NEVER run /clear from inside the skill - operator types it.
- /loop death is the easy-to-forget thing - make it loud.
