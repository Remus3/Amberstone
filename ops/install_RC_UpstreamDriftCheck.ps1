# Install RC-UpstreamDriftCheck scheduled task.
#
# Runs tools/upstream_drift_check.py --bridge-note once a day at 03:45
# to detect upstream content drift (DDragon versions.json + Meraki
# patchLastChanged + CDragon content-metadata). Alert mode only: it
# detects, advances the sentinel, and posts a bridge note on a real
# content change. It does NOT --auto-refresh (that stays operator-opt-in).
# RC-DDragonMirrorRefresh runs 03:30, so 03:45 stays clear of it.
#
# Idempotent: unregisters any existing task with the same name first.
# Path-safe (Register-ScheduledTask handles spaces in "Riot Commander").
#
# Run from an elevated PowerShell. Verify after with:
#   Get-ScheduledTask -TaskName RC-UpstreamDriftCheck
#   Get-ScheduledTaskInfo -TaskName RC-UpstreamDriftCheck

$ErrorActionPreference = "Stop"

$TaskName  = "RC-UpstreamDriftCheck"
$Python    = "$env:LOCALAPPDATA\Programs\Python\Python314\pythonw.exe"
$Script    = "C:\Riot Commander\tools\upstream_drift_check.py"
$Arguments = "`"$Script`" --bridge-note"

if (-not (Test-Path $Python)) { throw "python not found at $Python" }
if (-not (Test-Path $Script)) { throw "script not found at $Script" }

Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue |
    Unregister-ScheduledTask -Confirm:$false

$action    = New-ScheduledTaskAction `
    -Execute $Python `
    -Argument $Arguments
$trigger   = New-ScheduledTaskTrigger -Daily -At 3:45AM
$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Highest
$settings  = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
# -MultipleInstancesPolicy is not exposed on New-ScheduledTaskSettingsSet
# in Windows PowerShell 5.1; set it via the property after construction.
$settings.MultipleInstances = "IgnoreNew"

Register-ScheduledTask `
    -TaskName    $TaskName `
    -Description "Daily upstream content-drift detector (DDragon versions.json + Meraki patchLastChanged + CDragon content-metadata). Alerts via bridge note on a real content change. Daily 03:45." `
    -Action      $action `
    -Trigger     $trigger `
    -Principal   $principal `
    -Settings    $settings | Out-Null

Write-Output "Registered $TaskName."
Get-ScheduledTaskInfo -TaskName $TaskName |
    Select-Object TaskName, LastRunTime, NextRunTime, LastTaskResult |
    Format-List
