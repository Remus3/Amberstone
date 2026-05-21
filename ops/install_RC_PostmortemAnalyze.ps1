# Install RC-PostmortemAnalyze scheduled task.
#
# Runs ops/run_postmortem_with_restart.ps1 weekly Sundays 04:15 - 15 min
# after RC-RewindCatchup (04:00) so new matches land in rewind_history.db
# before the analyzer reads them. Writes data/coaching/death_patterns.json
# then triggers RC restart so coach prompts pick up the new PERSONAL
# CONTEXT block at module load.
#
# Idempotent: unregisters any existing task with the same name first.
# Path-safe (Register-ScheduledTask handles spaces in "Riot Commander").
#
# Run from an elevated PowerShell. Verify after with:
#   Get-ScheduledTask -TaskName RC-PostmortemAnalyze
#   Get-ScheduledTaskInfo -TaskName RC-PostmortemAnalyze

$ErrorActionPreference = "Stop"

$TaskName  = "RC-PostmortemAnalyze"
$PsExe     = "powershell.exe"
$Wrapper   = "C:\Riot Commander\ops\run_postmortem_with_restart.ps1"
$Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$Wrapper`""

if (-not (Test-Path $Wrapper)) { throw "wrapper not found at $Wrapper" }

Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue |
    Unregister-ScheduledTask -Confirm:$false

$action    = New-ScheduledTaskAction `
    -Execute $PsExe `
    -Argument $Arguments
$trigger   = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At 4:15AM
$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Highest
$settings  = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15)
# -MultipleInstancesPolicy is not exposed on New-ScheduledTaskSettingsSet
# in Windows PowerShell 5.1; set it via the property after construction.
$settings.MultipleInstances = "IgnoreNew"

Register-ScheduledTask `
    -TaskName    $TaskName `
    -Description "Refresh data/coaching/death_patterns.json then bounce RC. Weekly Sundays 04:15 (after RC-RewindCatchup 04:00)." `
    -Action      $action `
    -Trigger     $trigger `
    -Principal   $principal `
    -Settings    $settings | Out-Null

Write-Output "Registered $TaskName."
Get-ScheduledTaskInfo -TaskName $TaskName |
    Select-Object TaskName, LastRunTime, NextRunTime, LastTaskResult |
    Format-List
