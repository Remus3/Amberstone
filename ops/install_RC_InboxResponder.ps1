# Install RC-InboxResponder scheduled task.
#
# Runs tools/inbox_responder_runner.py --cycle every 5 minutes to answer
# cross-repo inbox notes from the sibling checkouts. Cmdlet-based
# registration (ScheduledTasks module), never schtasks XML.
#
# REGISTRATION LANDS DISARMED. The task may be registered Enabled, but the
# runner answers NOTHING until the OPERATOR hand-writes the arming record
# ops/runtime/inbox_responder_agreement.json. With no record present every
# tick terminates disarmed/no_agreement and writes only a log row - that
# idle tick IS the evidence the task fires. Installing this task is
# therefore not an act of arming; the agreement record is.
#
# The STOP flag ops/runtime/INBOX_RESPONDER_STOP always wins: it is checked
# at the first gate and again immediately before delivery, so a late STOP
# holds a finished draft rather than sending it. Disable-ScheduledTask is
# maintenance-off only - it is not the kill switch, the STOP flag is.
#
# One-shot dry cycle: write ops/runtime/INBOX_RESPONDER_DRY (one line, the
# scratch dir path). The runner consumes (unlinks) the flag before the
# cycle runs, so it takes precedence over a live agreement for exactly one
# tick and can never repeat itself.
#
# 7-bit ASCII only. PowerShell 5.1 ANSI-decodes a no-BOM .ps1, so a single
# non-ASCII glyph inside a double-quoted string terminates the string early
# and cascades into a parse failure.
#
# Idempotent: unregisters any existing task with the same name first.
# Path-safe (Register-ScheduledTask handles spaces in "Riot Commander").
#
# Run from an elevated PowerShell:
#   powershell -ExecutionPolicy Bypass -File "C:\Riot Commander\ops\install_RC_InboxResponder.ps1"
#   powershell -ExecutionPolicy Bypass -File "C:\Riot Commander\ops\install_RC_InboxResponder.ps1" -Probe
#   powershell -ExecutionPolicy Bypass -File "C:\Riot Commander\ops\install_RC_InboxResponder.ps1" -Remove

param(
    [switch]$Remove,
    [switch]$Probe
)

$ErrorActionPreference = "Stop"

$TaskName  = "RC-InboxResponder"
$Root      = "C:\Riot Commander"
$Python    = "$env:LOCALAPPDATA\Programs\Python\Python314\pythonw.exe"
$Script    = "$Root\tools\inbox_responder_runner.py"
$Arguments = "`"$Script`" --cycle"
$Agreement = "$Root\ops\runtime\inbox_responder_agreement.json"
$StopFlag  = "$Root\ops\runtime\INBOX_RESPONDER_STOP"
$DryFlag   = "$Root\ops\runtime\INBOX_RESPONDER_DRY"

function Show-ResponderState {
    # Read-back: task identity, schedule and the two arming facts.
    $t = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $t) {
        Write-Output "$TaskName is NOT registered."
        return
    }
    $i = Get-ScheduledTaskInfo -TaskName $TaskName
    Write-Output ("State={0}  Enabled={1}  NextRunTime={2}  LastRunTime={3}  LastTaskResult={4}" -f `
        $t.State, $t.Settings.Enabled, $i.NextRunTime, $i.LastRunTime, $i.LastTaskResult)
    foreach ($trg in $t.Triggers) {
        Write-Output ("Repetition: Interval={0}  Duration={1}  StopAtDurationEnd={2}" -f `
            $trg.Repetition.Interval, $trg.Repetition.Duration, $trg.Repetition.StopAtDurationEnd)
    }
    Write-Output ("MultipleInstances={0}  ExecutionTimeLimit={1}" -f `
        $t.Settings.MultipleInstances, $t.Settings.ExecutionTimeLimit)

    if (Test-Path $Agreement) {
        Write-Output "ARMED: agreement record present at $Agreement (the runner still fails closed on a malformed or expired record)."
    } else {
        Write-Output "DISARMED: no agreement record at $Agreement - every tick terminates disarmed/no_agreement."
    }
    if (Test-Path $StopFlag) { Write-Output "STOP flag PRESENT at $StopFlag - no delivery will happen." }
    if (Test-Path $DryFlag)  { Write-Output "DRY flag PRESENT at $DryFlag - the next tick is a one-shot dry cycle." }
}

if ($Probe) {
    Show-ResponderState
    return
}

if ($Remove) {
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($existing) {
        $existing | Unregister-ScheduledTask -Confirm:$false
        Write-Output "Unregistered $TaskName."
    } else {
        Write-Output "$TaskName was not registered - nothing to remove."
    }
    return
}

if (-not (Test-Path $Python)) { throw "pythonw not found at $Python" }
if (-not (Test-Path $Script)) { throw "runner not found at $Script" }
if (-not (Test-Path $Root))   { throw "repo root not found at $Root" }

Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue |
    Unregister-ScheduledTask -Confirm:$false

# pythonw.exe, not python.exe - a background daemon must not flash a console.
$action  = New-ScheduledTaskAction `
    -Execute          $Python `
    -Argument         $Arguments `
    -WorkingDirectory $Root

# One trigger a minute out, repeating every 5 minutes forever. A null
# Duration with StopAtDurationEnd false is the indefinite-repeat shape;
# leaving Duration at its default expires the repetition after a day.
$trigger = New-ScheduledTaskTrigger `
    -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 5)
$trigger.Repetition.Duration          = $null
$trigger.Repetition.StopAtDurationEnd = $false

# S4U: runs without a stored password and without an interactive session,
# so a logged-out box still ticks. An S4U task inherits MACHINE-scope
# environment only - that is why the dry-run switch is a flag file and not
# an env var. The account is resolved at INSTALL time from the installing
# shell; no account name is written into this script.
$principal = New-ScheduledTaskPrincipal `
    -UserId    $env:USERNAME `
    -LogonType S4U `
    -RunLevel  Highest

# 10 minutes is TASK_ETL_S = 600 in tools/inbox_responder_runner.py, and the
# summed worst-case cycle (see the spec section 11 formula) is bounded well
# under it. A 10-minute limit under a 5-minute repeat skips at most one tick,
# and IgnoreNew makes that skip a no-op rather than an overlap.
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
# The repo carries both spellings of this: some installers pass
# -MultipleInstances IgnoreNew to New-ScheduledTaskSettingsSet, others set
# the property afterwards because that parameter was reported missing on
# Windows PowerShell 5.1. The property assignment works on both 5.1 and 7,
# so it is the one used here - the resulting task setting is identical.
$settings.MultipleInstances = "IgnoreNew"

Register-ScheduledTask `
    -TaskName    $TaskName `
    -Description "Cross-repo inbox responder, every 5 minutes (tools/inbox_responder_runner.py --cycle). Registered DISARMED: answers nothing until the operator hand-writes ops/runtime/inbox_responder_agreement.json, and ops/runtime/INBOX_RESPONDER_STOP always wins." `
    -Action      $action `
    -Trigger     $trigger `
    -Principal   $principal `
    -Settings    $settings | Out-Null

Write-Output "Registered $TaskName (DISARMED - no agreement record is required to register, and none is written here)."
Show-ResponderState
