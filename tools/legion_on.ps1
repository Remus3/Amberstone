# legion_on.ps1 - start all Legion RC processes + launch Claude Desktop.
# Idempotent: re-run while everything is up = no duplicates (IgnoreNew + singleton checks).

$ErrorActionPreference = 'SilentlyContinue'
Write-Host "=== Legion ON ==="

# 1. Start AtStartup tasks first (SYSTEM context - infra), then AtLogon tasks (app-level)
$tasks = @(
  'RC-Supervisor',
  'RC-Phase3-Supervisor',
  'RC-DS-MatchDB-MCP'
)
foreach ($t in $tasks) {
  $task = Get-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue
  if ($null -eq $task) { Write-Host "[on] $t : MISSING (task not registered)"; continue }
  if ($task.State -eq 'Running') {
    Write-Host "[on] $t : already Running"
  } else {
    Start-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 500
    $now = (Get-ScheduledTask -TaskName $t).State
    Write-Host "[on] $t : started (state=$now)"
  }
}

# 1b. ONLOGON relocated agents (RC-HotkeyListener / RC-LCUAgent / RC-LiveClientRelay).
# legion_off kills these via its broad python-name pattern, but they are LogonTrigger
# tasks that do NOT auto-relaunch until the next logon - so an off/on cycle would
# silently leave hotkeys + LCU + the live-client relay dead unless we restart them here.
# Guard on the live PROCESS, not task.State: the pythonw launcher stub exits at once,
# leaving the task Ready while its child runs, so a State check would double-launch - and
# a second hotkey_listener fails RegisterHotKey (GetLastError 1409, combo already owned).
$agents = @(
  @{ Task = 'RC-HotkeyListener';  Match = 'hotkey_listener' },
  @{ Task = 'RC-LCUAgent';        Match = 'lcu_agent' },
  @{ Task = 'RC-LiveClientRelay'; Match = 'liveclient_relay' }
)
foreach ($a in $agents) {
  $alive = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -match $a.Match }
  if ($alive) {
    Write-Host "[on] $($a.Task) : already running (pid $($alive[0].ProcessId))"
  } else {
    Start-ScheduledTask -TaskName $a.Task -ErrorAction SilentlyContinue
    Write-Host "[on] $($a.Task) : started"
  }
}

# 2. DS server :8860 - not supervisor-watched per memory; launch manually if absent
$dsListening = Get-NetTCPConnection -LocalPort 8860 -State Listen -ErrorAction SilentlyContinue
if ($dsListening) {
  Write-Host "[on] DS server :8860 already listening (pid $($dsListening[0].OwningProcess))"
} else {
  $py = "$env:LOCALAPPDATA\Programs\Python\Python314\pythonw.exe"
  $ds = 'C:\Riot Commander\tools\start_daemon_slayer.py'
  if ((Test-Path $py) -and (Test-Path $ds)) {
    Start-Process -FilePath $py -ArgumentList "`"$ds`"" -WorkingDirectory 'C:\Riot Commander' -WindowStyle Hidden
    Write-Host "[on] DS server launching (start_daemon_slayer.py)"
    Start-Sleep -Seconds 5
    $dsListening = Get-NetTCPConnection -LocalPort 8860 -State Listen -ErrorAction SilentlyContinue
    if ($dsListening) { Write-Host "[on] DS server :8860 up (pid $($dsListening[0].OwningProcess))" }
    else { Write-Host "[on] WARN: DS server did not bind :8860 within 5s" }
  } else {
    Write-Host "[on] WARN: DS launcher or python not found"
  }
}

# 3. Launch Claude Desktop (Squirrel singleton - 2nd launch focuses existing window)
Start-Process -FilePath 'C:\Windows\explorer.exe' -ArgumentList 'shell:AppsFolder\Claude_pzs8sxrjxfjjc!Claude'
Write-Host "[on] Claude Desktop launched"

# 3b. rc-shell Electron overlay. The app already holds requestSingleInstanceLock so a
# 2nd launch is a no-op (focuses the existing window); we singleton-check first anyway
# to avoid spawning a doomed helper - mirrors the DS :8860 check above. Matched ONLY by
# the rc-shell path so other Electron apps (Claude Desktop) are never confused for it.
$rcShell = Get-CimInstance Win32_Process -Filter "Name='electron.exe'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -and $_.CommandLine -match 'rc-shell' }
if ($rcShell) {
  Write-Host "[on] rc-shell overlay already running (pid $($rcShell[0].ProcessId))"
} else {
  $electron = 'C:\Riot Commander\rc-shell\node_modules\electron\dist\electron.exe'
  if (Test-Path $electron) {
    # Launch via the cmd 'start' trampoline: cmd exits immediately and orphans Electron
    # with NO console attachment, so closing this Legion ON terminal can never close the
    # overlay. (A plain Start-Process -WindowStyle Hidden child inherits this console and
    # dies on its CTRL_CLOSE event - the bug this replaces.)
    $cmdLine = '/c start "rcshell" /d "C:\Riot Commander\rc-shell" "' + $electron + '" .'
    Start-Process -FilePath 'cmd.exe' -ArgumentList $cmdLine -WindowStyle Hidden
    Write-Host "[on] rc-shell overlay launching (detached)"
  } else {
    Write-Host "[on] WARN: rc-shell electron binary not found ($electron)"
  }
}

# 4. Status snapshot
Start-Sleep -Seconds 1
$ports = @{8888='dashboard'; 8889='vision'; 8890='phase3-prod'; 8891='phase3-dev'; 8860='ds'; 8861='ds-matchdb-mcp'}
foreach ($p in ($ports.Keys | Sort-Object)) {
  $c = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
  if ($c) { Write-Host "[on] :$p ($($ports[$p])) listening pid=$($c[0].OwningProcess)" }
  else    { Write-Host "[on] :$p ($($ports[$p])) NOT listening" }
}

Write-Host "=== Legion ON complete ==="
Write-Host "Overlay runs independently - safe to close this window now; it auto-closes in 8s."
Start-Sleep -Seconds 8
