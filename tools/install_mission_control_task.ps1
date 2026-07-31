# Registers RC-MissionControl. Independent of RC's supervisor by design:
# an RC restart for a game-overlay change must not touch the control plane.
# RestartCount/RestartInterval are load-bearing - choosing a scheduled task
# over an rc_supervisor entry gave up auto-restart, and ONLOGON fires once.
$python  = 'C:\Users\Administrator\AppData\Local\Programs\Python\Python314\pythonw.exe'
$script  = 'C:\Riot Commander\mission_control.py'
$workdir = 'C:\Riot Commander'

$action    = New-ScheduledTaskAction -Execute $python -Argument "`"$script`"" -WorkingDirectory $workdir
$trigger   = New-ScheduledTaskTrigger -AtLogOn
$principal = New-ScheduledTaskPrincipal -UserId 'Administrator' -RunLevel Highest
$settings  = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName 'RC-MissionControl' -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force
Write-Host 'RC-MissionControl registered. Start it with: schtasks /Run /TN RC-MissionControl'
