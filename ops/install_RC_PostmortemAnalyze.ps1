# Install RC-PostmortemAnalyze scheduled task.
#
# Runs ops/run_postmortem_with_restart.ps1 weekly Sundays 04:15 - 15 min
# after RC-RewindCatchup (04:00) so new matches land in rewind_history.db
# before the analyzer reads them. Writes data/coaching/death_patterns.json
# then triggers RC restart so coach prompts pick up the new PERSONAL
# CONTEXT block at module load.
#
# HIDDEN LAUNCH (MAIN FIX note 2026-10-11 2226). The action is
#   wscript.exe //B //NoLogo "<repo>\ops\run_postmortem_hidden.vbs"
# and the .vbs runs the powershell command line with WScript.Shell
# Run(cmd, 0, True), then WScript.Quit with its exit code. Executing
# powershell.exe directly is not enough even with -WindowStyle Hidden:
# PowerShell 5.1 is a console program, so conhost paints the window first and
# the host hides it only after it initialises. Window style 0 creates it
# hidden; //B keeps a script error from raising a modal dialog. The live task
# had also drifted (read 2026-10-12: powershell.exe with no -WindowStyle).
#
# BACKUP FIRST. Before unregistering, the existing task is exported to
#   ops\runtime\task_backups\RC-PostmortemAnalyze.<yyyyMMdd-HHmmss>.xml
# (gitignored, UTF-16 as Export-ScheduledTask declares it). The export must
# succeed or nothing is unregistered. Restore with:
#   schtasks /Create /TN RC-PostmortemAnalyze /XML "<backup file>" /F
#
# Idempotent: every run backs up, unregisters and re-registers the same
# definition, then reads the action back and fails if it is not the wrapper.
# Path-safe (Register-ScheduledTask handles spaces in the checkout path).
# 7-bit ASCII, LF only.
#
# Run from an elevated PowerShell:
#   powershell -NoProfile -ExecutionPolicy Bypass -File "<repo>\ops\install_RC_PostmortemAnalyze.ps1"
#   powershell -NoProfile -ExecutionPolicy Bypass -File "<repo>\ops\install_RC_PostmortemAnalyze.ps1" -Probe
# -Probe is read-only: it prints the registered action and schedule, nothing else.

param(
    [switch]$Probe
)

$ErrorActionPreference = "Stop"

$TaskName  = "RC-PostmortemAnalyze"
$Root      = Split-Path -Parent $PSScriptRoot
$Wscript   = "wscript.exe"
$Launcher  = Join-Path $PSScriptRoot "run_postmortem_hidden.vbs"
$Wrapper   = Join-Path $PSScriptRoot "run_postmortem_with_restart.ps1"
$Arguments = "//B //NoLogo `"$Launcher`""
$BackupDir = Join-Path $Root "ops\runtime\task_backups"

function Show-TaskAction {
    # Read-back: what the Task Scheduler actually holds, not what was sent.
    $t = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $t) {
        Write-Output "$TaskName is NOT registered."
        return
    }
    foreach ($a in $t.Actions) {
        Write-Output ("Action: Execute={0}  Arguments={1}  WorkingDirectory={2}" -f `
            $a.Execute, $a.Arguments, $a.WorkingDirectory)
    }
    Write-Output ("Principal: LogonType={0}  RunLevel={1}" -f `
        $t.Principal.LogonType, $t.Principal.RunLevel)
    Write-Output ("Settings: MultipleInstances={0}  ExecutionTimeLimit={1}  StartWhenAvailable={2}" -f `
        $t.Settings.MultipleInstances, $t.Settings.ExecutionTimeLimit, $t.Settings.StartWhenAvailable)
    $i = Get-ScheduledTaskInfo -TaskName $TaskName
    Write-Output ("State={0}  NextRunTime={1}  LastRunTime={2}  LastTaskResult={3}" -f `
        $t.State, $i.NextRunTime, $i.LastRunTime, $i.LastTaskResult)
}

if ($Probe) {
    Show-TaskAction
    return
}

if (-not (Test-Path $Launcher)) { throw "launcher not found at $Launcher" }
if (-not (Test-Path $Wrapper))  { throw "wrapper not found at $Wrapper" }

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    # Fail closed: an export error throws here, before anything is unregistered.
    if (-not (Test-Path $BackupDir)) { New-Item -ItemType Directory -Path $BackupDir | Out-Null }
    $stamp  = Get-Date -Format "yyyyMMdd-HHmmss"
    $backup = Join-Path $BackupDir "$TaskName.$stamp.xml"
    $xml    = Export-ScheduledTask -TaskName $TaskName
    if (-not $xml) { throw "Export-ScheduledTask returned nothing for $TaskName - not unregistering" }
    $tmp = "$backup.tmp"
    [System.IO.File]::WriteAllText($tmp, $xml, [System.Text.Encoding]::Unicode)
    Move-Item -LiteralPath $tmp -Destination $backup -Force
    Write-Output "Backed up $TaskName to $backup"
    $existing | Unregister-ScheduledTask -Confirm:$false
}

$action    = New-ScheduledTaskAction `
    -Execute $Wscript `
    -Argument $Arguments
$trigger   = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At 4:15AM
# S4U, matching the live task read 2026-09-15. S4U runs on a non-interactive
# desktop, so the task structurally cannot show a window; -LogonType Interactive
# here would have re-created exactly the flash this installer is meant to avoid.
$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType S4U `
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
Show-TaskAction
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $task) { throw "read-back failed: $TaskName is not registered after Register-ScheduledTask" }
$act = @($task.Actions)
if ($act.Count -ne 1 -or $act[0].Execute -ne $Wscript -or $act[0].Arguments -ne $Arguments) {
    throw "read-back mismatch: the registered action is not $Wscript $Arguments"
}
Write-Output "Read-back OK: $TaskName executes $Wscript $Arguments"
