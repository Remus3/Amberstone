# install_RC_LegionBridgeDaemon.ps1 - register RC-BridgeDaemon on Legion.
#
# Registers the autonomous /process-bridge-tasks consumer for Legion.
# Idempotent: safe to re-run; the registration is -Force so a stale def
# gets replaced.
#
# Operator decision 2026-05-20: Legion needed an autonomous /process-bridge-
# tasks consumer to match the Peer peer; without it, kind=task envelopes
# escalated by the watcher classifier but never auto-actioned (the
# push-notif spawn in the frozen bridge_watcher.py uses bare argv[0]='claude'
# which subprocess.run cannot resolve to claude.cmd on Windows -> tasks sat
# unhandled until an interactive Claude session ran /process-bridge-tasks).

$ErrorActionPreference = 'Stop'

$pyW    = 'C:\Users\Administrator\AppData\Local\Programs\Python\Python314\pythonw.exe'
$script = 'C:\Riot Commander\tools\legion_bridge_daemon.py'

if (-not (Test-Path $pyW))    { Write-Host "pythonw missing at $pyW" -ForegroundColor Red; exit 1 }
if (-not (Test-Path $script)) { Write-Host "script missing at $script" -ForegroundColor Red; exit 1 }

$action   = New-ScheduledTaskAction -Execute $pyW -Argument "`"$script`""
$trigger  = New-ScheduledTaskTrigger -AtLogOn -User 'Administrator'
$settings = New-ScheduledTaskSettingsSet `
              -MultipleInstances IgnoreNew `
              -RestartCount 3 `
              -RestartInterval (New-TimeSpan -Minutes 1) `
              -ExecutionTimeLimit ([TimeSpan]::Zero) `
              -StartWhenAvailable
$prin     = New-ScheduledTaskPrincipal -UserId 'Administrator' -LogonType Interactive -RunLevel Highest

Register-ScheduledTask `
    -TaskName 'RC-BridgeDaemon' `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $prin `
    -Description 'Zero-cost bridge sentinel - polls /api/bridge for tasks targeted at legion + invokes claude --print /process-bridge-tasks (mirrors the Peer daemon, added 2026-05-20 to close fleet symmetry gap).' `
    -Force | Out-Null

Write-Host 'RC-BridgeDaemon registered' -ForegroundColor Green

Start-ScheduledTask -TaskName 'RC-BridgeDaemon'
Start-Sleep -Seconds 2

$t = Get-ScheduledTask -TaskName 'RC-BridgeDaemon'
$i = Get-ScheduledTaskInfo -TaskName 'RC-BridgeDaemon'
'state={0}  LastRun={1}  LastResult=0x{2:X8}' -f $t.State, $i.LastRunTime, $i.LastTaskResult
