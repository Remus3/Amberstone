# Registers RC-DSKeepalive (RM-750): the RC-independent restarter for the
# Daemon Slayer engine on :8860. Run ONCE, elevated, as the operator:
#   powershell -ExecutionPolicy Bypass -File tools\install_ds_keepalive_task.ps1
# Idempotent (-Force re-registers). It registers the task and reads it back;
# it does not start the keepalive (the 1-minute repeat does, or run
# `schtasks /Run /TN RC-DSKeepalive`) and it never touches the DS owner task.
# Remove: Unregister-ScheduledTask -TaskName RC-DSKeepalive -Confirm:$false
# Hold without removing: create ops\runtime\DS_KEEPALIVE_STOP (legion_off.ps1
# does; legion_on.ps1 removes it).
#
# Why its own task: RestartOnFailure on the DS owner task is inert for a crash
# exit (exit 1 logged as success, no relaunch within 161 s; LEDGER 1731), and
# RC's DsWatchdog only runs while RC is up. tools/ds_keepalive.py runs the same
# watchdog (a real GET /health round trip, never a port or pid check) while
# RC's watchdog heartbeat is stale, relaunching only through the owner task.
#
# Shape = RC-MissionControl's measured working shape
# (tools/install_mission_control_task.ps1, fix rounds 1-3):
#   - AtStartup: up at boot before any logon, like the DS owner task.
#   - A -Once trigger with a real StartBoundary and a 1-minute indefinite
#     repetition (Duration unset, StopAtDurationEnd explicitly False - an
#     inherited True reads as a zero-length window and never fires). With
#     MultipleInstances IgnoreNew every firing is a no-op while the keepalive
#     runs, and starts it again within a minute if it died.
#   - SYSTEM / Highest: the DS owner task's principal, so the keepalive can run
#     that task, read the DS process's command line and taskkill a wedged DS.
#   - ExecutionTimeLimit 0: a long-lived loop, never a timed run.
$ErrorActionPreference = 'Stop'

$TaskName = 'RC-DSKeepalive'
$python   = "$env:LOCALAPPDATA\Programs\Python\Python314\pythonw.exe"
$workdir  = Split-Path -Parent $PSScriptRoot
$script   = Join-Path $workdir 'tools\ds_keepalive.py'
if (-not (Test-Path -LiteralPath $python)) { throw "pythonw.exe not found at $python" }
if (-not (Test-Path -LiteralPath $script)) { throw "keepalive not found at $script" }

$action = New-ScheduledTaskAction -Execute $python -Argument "`"$script`"" -WorkingDirectory $workdir

$bootTrigger = New-ScheduledTaskTrigger -AtStartup
$onceTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 1)
$onceTrigger.Repetition.Duration = $null
$onceTrigger.Repetition.StopAtDurationEnd = $false

$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$settings  = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger @($bootTrigger, $onceTrigger) -Principal $principal -Settings $settings -Force | Out-Null
Write-Host "[install] $TaskName registered."

# Read back: a silent no-op assignment was RC-MissionControl's round-2 failure.
$check = Get-ScheduledTask -TaskName $TaskName
Write-Host "[install] action    = $($check.Actions[0].Execute) $($check.Actions[0].Arguments)"
Write-Host "[install] principal = $($check.Principal.UserId) / $($check.Principal.RunLevel)"
Write-Host "[install] settings  = MultipleInstances $($check.Settings.MultipleInstances), ExecutionTimeLimit $($check.Settings.ExecutionTimeLimit)"
foreach ($t in $check.Triggers) {
    Write-Host "[install] trigger $($t.CimClass.CimClassName): start '$($t.StartBoundary)' interval '$($t.Repetition.Interval)' duration '$($t.Repetition.Duration)' stopAtEnd $($t.Repetition.StopAtDurationEnd)"
}
$info = Get-ScheduledTaskInfo -TaskName $TaskName
if ([string]::IsNullOrEmpty([string]$info.NextRunTime)) {
    Write-Warning "[install] NextRunTime is blank - the 1-minute repeat will stay inert."
    exit 1
}
Write-Host "[install] NextRunTime = $($info.NextRunTime)"
