# Process-start tracer. Co-launch with tools/console_flash_detector.py.
#
# WHY A SECOND PROCESS. A console flash lives about 20-40 ms. A single-runspace
# recorder that resolves each process start inline blocks for about 65 ms per
# lookup (measured 2026-09-14 from the inter-event spacing of exactly such a
# sampler) - longer than the window it is trying to see, and blind precisely
# when a window exists. So the window detector and this tracer run as two
# processes, neither does a lookup in its hot path, and the join happens later
# in tools/console_flash_attribute.py on (pid, creation time).
#
# WHAT IS DELIBERATELY NOT COLLECTED. Win32_ProcessStartTrace carries no command
# line, and that is a feature here: a command line names the account home
# directory and the directories of neighbouring projects on this box. Default
# output is basenames and ids only. -CommandLines opts in for a local
# investigation; that output must never be committed.
#
# The two Win32_Process snapshots exist because a long-lived ancestor started
# before the capture has no PROCESS event, so ancestry would stop one hop early.
# They carry ProcessName / ProcessId / ParentProcessId / CreationDate only.
#
# ASCII ONLY, no BOM: Windows PowerShell 5.1 ANSI-decodes a no-BOM .ps1, so a
# non-ASCII dash inside a double-quoted string terminates the string and
# cascades into a parse failure.
#
# Usage:
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File tools/console_flash_trace.ps1 -Seconds 90

[CmdletBinding()]
param(
    [double]$Seconds = 90,
    [string]$Out = "",
    [switch]$CommandLines
)

$ErrorActionPreference = "Stop"

function Get-Stamp {
    return (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.ffffffZ")
}

$repoRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($Out)) {
    $outDir = Join-Path $repoRoot "ops\runtime\console_flash"
    $Out = Join-Path $outDir "console_flash_trace.log"
} else {
    $outDir = Split-Path -Parent $Out
}
if (-not (Test-Path $outDir)) {
    New-Item -ItemType Directory -Path $outDir -Force | Out-Null
}

function Write-Line {
    param([string]$Text)
    Add-Content -LiteralPath $script:Out -Value $Text -Encoding Ascii
}

function Write-Snapshot {
    param([string]$Phase)
    $stamp = Get-Stamp
    $props = @("ProcessId", "ParentProcessId", "Name", "CreationDate")
    if ($script:CommandLines) { $props += "CommandLine" }
    try {
        $rows = Get-CimInstance -ClassName Win32_Process -Property $props -ErrorAction Stop
    } catch {
        Write-Line "SNAPSHOT-UNAVAILABLE phase=$Phase ts=$stamp reason=win32-process-query-failed"
        return
    }
    foreach ($row in $rows) {
        $created = ""
        if ($row.CreationDate) {
            $created = ([datetime]$row.CreationDate).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.ffffffZ")
        }
        $line = "SNAPSHOT phase=$Phase ts=$stamp name=$($row.Name) pid=$($row.ProcessId) ppid=$($row.ParentProcessId) created=$created"
        if ($script:CommandLines -and $row.CommandLine) {
            $line = "$line cmd=$($row.CommandLine)"
        }
        Write-Line $line
    }
}

$sourceId = "ConsoleFlashTrace_" + [guid]::NewGuid().ToString("N")
$action = {
    # STAMP FIRST, then format. No lookup of any kind inside this block.
    $stamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.ffffffZ")
    $ev = $Event.SourceEventArgs.NewEvent
    $created = ""
    try {
        $created = [datetime]::FromFileTimeUtc([int64]$ev.TIME_CREATED).ToString("yyyy-MM-ddTHH:mm:ss.ffffffZ")
    } catch {
        $created = $stamp
    }
    $line = "PROCESS ts=$stamp name=$($ev.ProcessName) pid=$($ev.ProcessID) ppid=$($ev.ParentProcessID) created=$created"
    Add-Content -LiteralPath $Event.MessageData -Value $line -Encoding Ascii
}

$subscribed = $false
try {
    Register-CimIndicationEvent -ClassName Win32_ProcessStartTrace `
        -SourceIdentifier $sourceId -Action $action -MessageData $Out -ErrorAction Stop | Out-Null
    $subscribed = $true
} catch {
    # A failed subscription is the one outcome that must never look like a
    # quiet machine: the attributor reads this line and reports every console
    # event UNATTRIBUTED instead of joining against a partial trace.
    Write-Line ("START-TRACE UNAVAILABLE ts=" + (Get-Stamp) + " reason=cim-subscription-refused")
}

if ($subscribed) {
    Write-Line ("START-TRACE ts=" + (Get-Stamp) + " seconds=$Seconds out=" + (Split-Path -Leaf $Out))
    Write-Snapshot -Phase "START"
}

$deadline = (Get-Date).AddSeconds($Seconds)
$nextBeat = (Get-Date).AddSeconds(30)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 250
    if ((Get-Date) -ge $nextBeat) {
        # Counted from the FILE, not from the subscriber. MEASURED 2026-09-15:
        # $sub.Action.Output.Count reported 0 across a run that wrote 587
        # PROCESS lines, because an -Action scriptblock's output is consumed,
        # not accumulated. A liveness counter that reads 0 on a live tracer is
        # worse than none - it is the exact "quiet machine" misreading this
        # whole tool exists to prevent. The re-read is outside the hot path.
        $count = 0
        if (Test-Path -LiteralPath $Out) {
            $count = @(Select-String -LiteralPath $Out -Pattern "^PROCESS " -CaseSensitive).Count
        }
        Write-Line ("HEARTBEAT-TRACE ts=" + (Get-Stamp) + " events=$count")
        $nextBeat = (Get-Date).AddSeconds(30)
    }
}

if ($subscribed) {
    Write-Snapshot -Phase "END"
    Unregister-Event -SourceIdentifier $sourceId -ErrorAction SilentlyContinue
}
Write-Line ("END-TRACE ts=" + (Get-Stamp))
