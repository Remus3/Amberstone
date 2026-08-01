# install_RC_WeeklyHygiene.ps1 - register RC-WeeklyHygiene on Legion.
#
# Weekly (Sunday 04:17) unattended /weekly-hygiene pass via Claude Code
# headless (tools/weekly_hygiene_run.ps1). Mirrors the
# install_RC_LegionBridgeDaemon.ps1 registration shape. Idempotent: -Force
# replaces a stale def. 04:17 is after the nightly DDragon mirror (03:30) +
# the nightly mirror so the anomaly-triage step sees fresh scheduled-task
# results, and off the :00/:30 marks per fleet cadence policy.

$ErrorActionPreference = 'Stop'

$ps      = 'powershell.exe'
$wrapper = 'C:\Riot Commander\tools\weekly_hygiene_run.ps1'

if (-not (Test-Path $wrapper)) { Write-Host "wrapper missing at $wrapper" -ForegroundColor Red; exit 1 }

$action   = New-ScheduledTaskAction -Execute $ps `
              -Argument "-NonInteractive -ExecutionPolicy Bypass -File `"$wrapper`""
$trigger  = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At 4:17AM
$settings = New-ScheduledTaskSettingsSet `
              -MultipleInstances IgnoreNew `
              -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
              -StartWhenAvailable
$prin     = New-ScheduledTaskPrincipal -UserId 'Administrator' -LogonType Interactive -RunLevel Highest

Register-ScheduledTask `
    -TaskName 'RC-WeeklyHygiene' `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $prin `
    -Description 'Weekly unattended /weekly-hygiene pass (Sunday 04:17): relocate-only WAKEUP/LEDGER/ROADMAP doc trim + memory staleness scan + session-start anomaly triage via headless Claude Code (sonnet). Flags surface into WAKEUP_NOTES.md. Added 2026-06-09.' `
    -Force | Out-Null

Write-Host 'RC-WeeklyHygiene registered' -ForegroundColor Green

$t = Get-ScheduledTask -TaskName 'RC-WeeklyHygiene'
$i = Get-ScheduledTaskInfo -TaskName 'RC-WeeklyHygiene'
'state={0}  NextRun={1}' -f $t.State, $i.NextRunTime
