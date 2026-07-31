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
$python  = 'C:\Users\Administrator\AppData\Local\Programs\Python\Python314\pythonw.exe'
$script  = 'C:\Riot Commander\mission_control.py'
$workdir = 'C:\Riot Commander'

$action  = New-ScheduledTaskAction -Execute $python -Argument "`"$script`"" -WorkingDirectory $workdir
$trigger = New-ScheduledTaskTrigger -AtLogOn
# Borrow the Repetition object from a throwaway -Once trigger - this is the
# standard idiom for attaching a repetition pattern to a non-Once trigger.
$repeatSource = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 1)
$trigger.Repetition = $repeatSource.Repetition
# Explicitly force an INDEFINITE repetition. Duration unset + StopAtDurationEnd
# false is what "repeat forever" actually means in Task Scheduler; the
# borrowed object's StopAtDurationEnd=True (round 1's bug) is overridden here.
$trigger.Repetition.Duration = $null
$trigger.Repetition.StopAtDurationEnd = $false

$principal = New-ScheduledTaskPrincipal -UserId 'Administrator' -RunLevel Highest
$settings  = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName 'RC-MissionControl' -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force
Write-Host 'RC-MissionControl registered. Start it with: schtasks /Run /TN RC-MissionControl'

# Verify the repetition actually took - a silent no-op assignment is the
# likely failure mode for the borrow-the-Repetition-object idiom above.
# All three fields matter: Interval must be set, StopAtDurationEnd must be
# False (round 2's bug was exactly this field silently staying True).
$check = Get-ScheduledTask -TaskName 'RC-MissionControl'
$rep = $check.Triggers[0].Repetition
Write-Host "Repetition.Interval = $($rep.Interval)"
Write-Host "Repetition.Duration = '$($rep.Duration)'"
Write-Host "Repetition.StopAtDurationEnd = $($rep.StopAtDurationEnd)"
if ([string]::IsNullOrEmpty($rep.Interval)) {
    Write-Host 'WARNING: registered trigger has an EMPTY repetition interval - the fix did not take.'
} elseif ($rep.StopAtDurationEnd -eq $true) {
    Write-Host 'WARNING: StopAtDurationEnd is still True - the watchdog will stay inert.'
} else {
    Write-Host 'Confirmed: repetition interval set and StopAtDurationEnd is False.'
}
