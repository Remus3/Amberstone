# legion_off.ps1 - stop all Legion RC processes cleanly.
# Idempotent: re-run on already-stopped fleet = no-op.
# Hard rule: never Stop-Process (hangs MCP pipe per CLAUDE.md) - use taskkill /F /PID.
# Does NOT kill: Claude Code CLI sessions, Claude Desktop, Tailscale, windows-mcp, system services.
#
# Status (2026-10-31 launcher cutover): RC-Supervisor and RC-Phase3-Supervisor are
# unregistered and the rc-shell service host runs the supervisor, the LCU agent, the
# relay, the hotkey listener and Phase 3 (docs/OPERATIONS.md, "Moved to the app"). Step 1
# therefore reports them MISSING on a cut-over host and the real stop is the step 2 and
# 2b process sweeps; quitting the app is the clean stop. docs/OPERATIONS.md records the
# wider rework of this script for the app as open.

$ErrorActionPreference = 'SilentlyContinue'
Write-Host "=== Legion OFF ==="

# 0. Hold the DS keepalive (RC-DSKeepalive, RM-750) BEFORE the sweep below kills
# DS: with RC down a registered keepalive would relaunch DS within a minute.
# legion_on.ps1 removes the flag. Status (2026-10-31 launcher cutover): RC-DSKeepalive
# was never registered and RC-DaemonSlayer is unregistered (RC's DsWatchdog starts DS
# as its own child), so on a cut-over host the flag holds nothing; it is still written
# so a host that registers the keepalive stays held.
$dsStop = Join-Path (Split-Path -Parent $PSScriptRoot) 'ops\runtime\DS_KEEPALIVE_STOP'
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dsStop) | Out-Null
Set-Content -LiteralPath $dsStop -Value 'legion_off' -Encoding Ascii
Write-Host "[off] DS keepalive held (ops\runtime\DS_KEEPALIVE_STOP)"

# 1. Stop the RC-* scheduled tasks that are still registered (dep order: app-level first, infra last)
$tasks = @(
  'RC-Supervisor',
  'RC-Phase3-Supervisor',
  'RC-DS-MatchDB-MCP'
)
foreach ($t in $tasks) {
  $task = Get-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue
  if ($null -eq $task) { Write-Host "[off] $t : MISSING (task not registered)"; continue }
  if ($task.State -eq 'Running') {
    Stop-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue
    Write-Host "[off] $t : stopped"
  } else {
    Write-Host "[off] $t : already $($task.State)"
  }
}

# Let the scheduler reap task wrappers
Start-Sleep -Seconds 2

# 2. taskkill any orphaned RC python processes (catches manual DS launch + any zombie children)
$pat = 'Riot Commander|moon_vision_server|rc_supervisor|agents\.supervisor|start_daemon_slayer|start_ds_matchdb|main\.py'
$rcProcs = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -and $_.CommandLine -match $pat }
if ($null -eq $rcProcs -or $rcProcs.Count -eq 0) {
  Write-Host "[off] no orphan RC python processes"
} else {
  foreach ($p in $rcProcs) {
    & taskkill.exe /F /PID $p.ProcessId 2>&1 | Out-Null
    Write-Host "[off] taskkill /F /PID $($p.ProcessId) ($($p.Name))"
  }
}

# 2b. Kill the rc-shell Electron overlay (main + helper procs). Matched ONLY by the
# rc-shell path in the command line, so other Electron apps (Claude Desktop, editors)
# are left running. taskkill /F /PID per the hard rule - never Stop-Process.
$rcShell = Get-CimInstance Win32_Process -Filter "Name='electron.exe'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -and $_.CommandLine -match 'rc-shell' }
if ($null -eq $rcShell -or $rcShell.Count -eq 0) {
  Write-Host "[off] no rc-shell Electron overlay running"
} else {
  foreach ($p in $rcShell) {
    & taskkill.exe /F /PID $p.ProcessId 2>&1 | Out-Null
    Write-Host "[off] taskkill /F /PID $($p.ProcessId) (rc-shell overlay)"
  }
}

# 3. Verify ports cleared (informational - if still listening, something is alive that we missed)
Start-Sleep -Seconds 1
$ports = 8888, 8889, 8890, 8891, 8860, 8861
$stillUp = @()
foreach ($port in $ports) {
  $c = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
  if ($c) { $stillUp += $port }
}
if ($stillUp.Count -gt 0) {
  Write-Host "[off] WARN: ports still listening: $($stillUp -join ', ')"
} else {
  Write-Host "[off] all RC ports cleared (8888 8889 8890 8891 8860 8861)"
}

Write-Host "=== Legion OFF complete ==="
Write-Host "Press any key to close..."
$null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
