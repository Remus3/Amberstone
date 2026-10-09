# Wrapper: run scripts/postmortem_analyze.py then bounce RC so coach prompts
# reload the new PERSONAL CONTEXT block at module import time.
#
# Invoked by the RC-PostmortemAnalyze scheduled task. Exit code mirrors the
# analyzer's exit (0=ok / 2=missing PUUIDs / 3=DB not found). The restart
# trigger fires only on a clean analyzer run (exit 0).
#
# Idempotent + side-effect-only: writes data/coaching/death_patterns.json
# atomically + writes restart_trigger.txt (supervisor clears + restarts RC
# within ~5s).
#
# -LibraryOnly defines the helpers and returns without running anything. It
# exists so tests can dot-source Invoke-DrainedProcess and exercise the pipe
# drain against a synthetic child. The scheduled task invokes this script with
# -File and no arguments, so the switch is $false in production and the task
# definition does not change.

param([switch]$LibraryOnly)

$ErrorActionPreference = "Stop"

$Python  = "$env:LOCALAPPDATA\Programs\Python\Python314\pythonw.exe"
$Root    = Split-Path -Parent $PSScriptRoot
$Script  = Join-Path $Root "scripts\postmortem_analyze.py"
$Trigger = Join-Path $Root "restart_trigger.txt"
$LogDir  = Join-Path $Root "logs"

function Invoke-DrainedProcess {
    <#
    .SYNOPSIS
    Start a child with both standard streams redirected, and drain them without
    deadlocking.

    .DESCRIPTION
    The OS pipe buffer is roughly 4 KB. Waiting for the child to exit before
    reading means a chatty child blocks on a full pipe while the parent blocks
    in WaitForExit - neither side ever proceeds, and the scheduled task's
    ExecutionTimeLimit eventually kills the run with 2147946720 (0x800710E0 /
    Win32 4320) having logged nothing at all. Reading stdout to the end and
    only then reading stderr has the same failure mode, just on the other pipe.

    Both reads are therefore started BEFORE anything blocks. ReadToEndAsync is
    .NET Framework 4.5, so Windows PowerShell 5.1 has it with no extra
    dependency, and unlike the line-oriented BeginOutputReadLine pump it
    preserves the stream text exactly.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string]$Arguments = ""
    )

    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName               = $FilePath
    $startInfo.Arguments              = $Arguments
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError  = $true
    $startInfo.UseShellExecute        = $false
    $startInfo.CreateNoWindow         = $true

    $proc = [System.Diagnostics.Process]::Start($startInfo)

    # Both pumps in flight before anything blocks.
    $outTask = $proc.StandardOutput.ReadToEndAsync()
    $errTask = $proc.StandardError.ReadToEndAsync()

    # .Result blocks until that pump reaches EOF; the other pump keeps draining
    # on its own thread meanwhile, so neither pipe can back up.
    $stdOut = $outTask.Result
    $stdErr = $errTask.Result

    # Both streams are at EOF by now, so this returns promptly. It is kept so
    # ExitCode is guaranteed readable.
    $proc.WaitForExit()

    return [pscustomobject]@{
        StdOut   = $stdOut
        StdErr   = $stdErr
        ExitCode = $proc.ExitCode
    }
}

if ($LibraryOnly) { return }

# Build the log path FIRST. Under $ErrorActionPreference = "Stop" any failure
# raised before this point is completely silent, which is how a missing
# interpreter used to produce a scheduled-task run with no trace whatsoever.
$Log = $null
try {
    if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }
    $Stamp = (Get-Date -Format "yyyy-MM-dd")
    $Log   = Join-Path $LogDir "postmortem_analyze.$Stamp.log"
} catch {
    $Log = $null
}

function Write-RunLog {
    param([string]$Text)
    if ($Log) {
        try { Add-Content -Path $Log -Value $Text } catch { }
    }
}

function Write-FatalAndExit {
    param([string]$Message)
    $ts = (Get-Date -Format "o")
    Write-RunLog "=== $ts exit=1 ==="
    Write-RunLog "FATAL: $Message"
    [Console]::Error.WriteLine("FATAL: $Message")
    exit 1
}

if (-not (Test-Path $Python)) { Write-FatalAndExit "python not found at $Python" }
if (-not (Test-Path $Script)) { Write-FatalAndExit "script not found at $Script" }

# pythonw.exe has no console; both redirected streams are drained concurrently
# and written to the log file below.
$run  = Invoke-DrainedProcess -FilePath $Python -Arguments "`"$Script`""
$out  = $run.StdOut
$err  = $run.StdErr
$code = $run.ExitCode

$ts = (Get-Date -Format "o")
Write-RunLog "=== $ts exit=$code ==="
if ($out) { Write-RunLog $out }
if ($err) { Write-RunLog $err }

if ($code -eq 0) {
    Set-Content -Path $Trigger -Value "postmortem-analyze refresh" -Encoding ASCII
    Write-RunLog "restart_trigger.txt written"
}

exit $code
