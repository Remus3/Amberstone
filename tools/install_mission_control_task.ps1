# Registers RC-MissionControl. Independent of RC's supervisor by design:
# an RC restart for a game-overlay change must not touch the control plane.
# RestartCount/RestartInterval are load-bearing - choosing a scheduled task
# over an rc_supervisor entry gave up auto-restart, and ONLOGON fires once.
#
# Fix round 1 (2026-07-31): a plain AtLogOn trigger fires exactly once, so
# when the instance died there was no future firing for RestartCount /
# RestartInterval to attach to - live-measured, nothing came back within a
# 4-minute observation window. The trigger now repeats every 1 minute,
# indefinitely, via the borrow-the-Repetition-object idiom below. Combined
# with MultipleInstances=IgnoreNew (explicit here, not left to the default)
# this is what makes it self-healing: process alive -> the repeat fires,
# Task Scheduler sees a running instance, IgnoreNew discards it at near-zero
# cost; process dead -> the repeat fires and starts it. Same lifecycle
# mechanism as before (Task Scheduler is the watchdog), just a corrected
# trigger shape - not a new approach.
#
# Fix round 2 (2026-07-31): round 1's repetition interval attached, but the
# watchdog stayed inert - live-measured, still dead after 3+ minutes. Root
# cause: borrowing the Repetition object off a -Once trigger also carries
# StopAtDurationEnd=True, and with Duration left empty that reads as "the
# repeat window is zero", so it never fires. An indefinite repetition needs
# Interval set, Duration unset, AND StopAtDurationEnd explicitly False - the
# third field does not default correctly when inherited this way. Set all
# three explicitly and read them back after registering; do not trust the
# assignment silently stuck.
#
# Fix round 3 (2026-07-31): round 2's repetition fields were all correct
# (Interval PT1M, Duration empty, StopAtDurationEnd False) but NextRunTime
# stayed blank and the watchdog was STILL inert. Root cause: the trigger
# TYPE. A LogonTrigger has no StartBoundary, so Task Scheduler has no anchor
# to compute a next-repeat time from, and `schtasks /Run` executes the
# ACTION directly without ever firing the TRIGGER - so the repetition clock
# never starts. That can only be proven by an actual logoff/logon cycle,
# which nobody will ever re-run to re-verify this, so we route around it
# instead of depending on it: a SECOND trigger is added, a -Once trigger
# with a real StartBoundary (near "now") and its own 1-minute indefinite
# repetition. The AtLogOn trigger stays - it is still the fast boot-time
# start - but the -Once trigger is what actually gives Task Scheduler a
# computable NextRunTime, independent of logon state. MultipleInstances=
# IgnoreNew is what makes the once-a-minute firing a no-op while the
# process is alive; RestartCount/RestartInterval are unchanged.
$python  = "$env:LOCALAPPDATA\Programs\Python\Python314\pythonw.exe"
$script  = 'C:\Riot Commander\mission_control.py'
$workdir = 'C:\Riot Commander'

$action = New-ScheduledTaskAction -Execute $python -Argument "`"$script`"" -WorkingDirectory $workdir

# Trigger 1: AtLogOn, unchanged - fast start at boot/logon.
$logonTrigger = New-ScheduledTaskTrigger -AtLogOn

# Trigger 2: -Once with a real StartBoundary (near "now") plus a 1-minute
# indefinite repetition. This is the one Task Scheduler can actually
# compute a NextRunTime from, so it is the one that makes the watchdog
# self-healing regardless of logon state.
$onceTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 1)
$onceTrigger.Repetition.Duration = $null
$onceTrigger.Repetition.StopAtDurationEnd = $false

$principal = New-ScheduledTaskPrincipal -UserId 'Administrator' -RunLevel Highest
$settings  = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName 'RC-MissionControl' -Action $action -Trigger @($logonTrigger, $onceTrigger) -Principal $principal -Settings $settings -Force
Write-Host 'RC-MissionControl registered. Start it with: schtasks /Run /TN RC-MissionControl'

# Verify both triggers actually took as intended - a silent no-op assignment
# is the likely failure mode, as it was in round 2.
$check = Get-ScheduledTask -TaskName 'RC-MissionControl'
foreach ($t in $check.Triggers) {
    Write-Host "--- Trigger: $($t.CimClass.CimClassName) ---"
    Write-Host "  StartBoundary = '$($t.StartBoundary)'"
    Write-Host "  Repetition.Interval = '$($t.Repetition.Interval)'"
    Write-Host "  Repetition.Duration = '$($t.Repetition.Duration)'"
    Write-Host "  Repetition.StopAtDurationEnd = $($t.Repetition.StopAtDurationEnd)"
}
$info = Get-ScheduledTaskInfo -TaskName 'RC-MissionControl'
Write-Host "NextRunTime = '$($info.NextRunTime)'"
if ([string]::IsNullOrEmpty($info.NextRunTime)) {
    Write-Host 'WARNING: NextRunTime is still blank - the watchdog will stay inert.'
} else {
    Write-Host 'Confirmed: NextRunTime is non-blank.'
}
