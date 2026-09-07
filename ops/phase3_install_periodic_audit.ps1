# Schedule a weekly Agent 6 self-audit.
# Idempotent: unregisters then re-registers.
# Default: every Sunday 03:00 local. Change the $trigger line to taste.
#
# Run as: powershell.exe -ExecutionPolicy Bypass -File ops\phase3_install_periodic_audit.ps1

$ErrorActionPreference = 'Stop'

$ProjectRoot = 'C:\Riot Commander'
$PythonExe   = "$env:LOCALAPPDATA\Programs\Python\Python314\pythonw.exe"
$TaskName    = 'RC-Phase3-PeriodicAudit'

$action = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument '-m ops.phase3_file_audit' `
    -WorkingDirectory $ProjectRoot

# Weekly Sunday 03:00 local.
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At '03:00'

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::FromMinutes(5))

$principal = New-ScheduledTaskPrincipal `
    -UserId 'Administrator' `
    -LogonType Interactive `
    -RunLevel Highest

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "scheduled task already present: $TaskName -- replacing"
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description 'Files a priority-0 Agent 6 full audit task once a week so Phase 3 self-audits without human prompt.' | Out-Null

Write-Host "scheduled task registered: $TaskName (weekly Sunday 03:00 local)"
