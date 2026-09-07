# Install RC-RewindCatchup scheduled task.
#
# Runs scripts/rewind_catchup.py weekly to pull any new Match-V5 records
# into rewind_history.db. The script is idempotent + resumable via
# data/rewind_catchup.state.json and INSERT OR IGNORE.
#
# Trigger: Sundays at 04:00 (after RC-DDragonMirrorRefresh, before peak).
# Operator's cadence is sparse (~5 games / 5 months 2026-05) - weekly is
# enough; daily would just be ~52 no-op runs.
#
# Idempotent: unregisters any existing task with the same name first.

$ErrorActionPreference = "Stop"

$TaskName = "RC-RewindCatchup"
$Python   = "$env:LOCALAPPDATA\Programs\Python\Python314\pythonw.exe"
$Script   = "C:\Riot Commander\scripts\rewind_catchup.py"
$Args     = "`"$Script`""

if (-not (Test-Path $Python)) { throw "python not found at $Python" }
if (-not (Test-Path $Script)) { throw "script not found at $Script" }

Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue |
    Unregister-ScheduledTask -Confirm:$false

$action    = New-ScheduledTaskAction `
    -Execute $Python `
    -Argument $Args
$trigger   = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At 4:00AM
$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Highest
$settings  = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 20)
# -MultipleInstancesPolicy is not exposed on New-ScheduledTaskSettingsSet
# in Windows PowerShell 5.1; set it via the property after construction
# (same workaround as install_RC_DDragonMirror.ps1).
$settings.MultipleInstances = "IgnoreNew"

Register-ScheduledTask `
    -TaskName    $TaskName `
    -Description "Pull new Match-V5 records into rewind_history.db. Weekly Sundays 04:00." `
    -Action      $action `
    -Trigger     $trigger `
    -Principal   $principal `
    -Settings    $settings | Out-Null

Write-Output "Registered $TaskName."
Get-ScheduledTaskInfo -TaskName $TaskName |
    Select-Object TaskName, LastRunTime, NextRunTime, LastTaskResult |
    Format-List
