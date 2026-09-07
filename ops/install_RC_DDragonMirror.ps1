# Install RC-DDragonMirrorRefresh scheduled task.
#
# Runs tools/ddragon_mirror_refresh.py --check-changed once a day at 03:30
# to keep the local DDragon mirror at web/data/ddragon/<patch>/ in sync
# with the live CDN (patch flips + mid-patch revisions).
#
# Idempotent: unregisters any existing task with the same name first.
# Path-safe (Register-ScheduledTask handles spaces in "Riot Commander").
#
# Run from an elevated PowerShell. Verify after with:
#   Get-ScheduledTask -TaskName RC-DDragonMirrorRefresh
#   Get-ScheduledTaskInfo -TaskName RC-DDragonMirrorRefresh

$ErrorActionPreference = "Stop"

$TaskName  = "RC-DDragonMirrorRefresh"
$Python    = "$env:LOCALAPPDATA\Programs\Python\Python314\pythonw.exe"
$Script    = "C:\Riot Commander\tools\ddragon_mirror_refresh.py"
$Arguments = "`"$Script`" --check-changed"

if (-not (Test-Path $Python)) { throw "python not found at $Python" }
if (-not (Test-Path $Script)) { throw "script not found at $Script" }

Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue |
    Unregister-ScheduledTask -Confirm:$false

$action    = New-ScheduledTaskAction `
    -Execute $Python `
    -Argument $Arguments
$trigger   = New-ScheduledTaskTrigger -Daily -At 3:30AM
$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Highest
$settings  = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
# -MultipleInstancesPolicy is not exposed on New-ScheduledTaskSettingsSet
# in Windows PowerShell 5.1; set it via the property after construction.
$settings.MultipleInstances = "IgnoreNew"

Register-ScheduledTask `
    -TaskName    $TaskName `
    -Description "Refresh local DDragon mirror (patch + mid-patch deltas). Daily 03:30." `
    -Action      $action `
    -Trigger     $trigger `
    -Principal   $principal `
    -Settings    $settings | Out-Null

Write-Output "Registered $TaskName."
Get-ScheduledTaskInfo -TaskName $TaskName |
    Select-Object TaskName, LastRunTime, NextRunTime, LastTaskResult |
    Format-List
