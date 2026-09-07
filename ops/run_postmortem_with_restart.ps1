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

$ErrorActionPreference = "Stop"

$Python  = "$env:LOCALAPPDATA\Programs\Python\Python314\pythonw.exe"
$Script  = "C:\Riot Commander\scripts\postmortem_analyze.py"
$Trigger = "C:\Riot Commander\restart_trigger.txt"
$LogDir  = "C:\Riot Commander\logs"

if (-not (Test-Path $Python)) { throw "python not found at $Python" }
if (-not (Test-Path $Script)) { throw "script not found at $Script" }
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }

$Stamp = (Get-Date -Format "yyyy-MM-dd")
$Log   = Join-Path $LogDir "postmortem_analyze.$Stamp.log"

# pythonw.exe has no console; pipe stderr/stdout to log file directly.
$startInfo = New-Object System.Diagnostics.ProcessStartInfo
$startInfo.FileName               = $Python
$startInfo.Arguments              = "`"$Script`""
$startInfo.RedirectStandardOutput = $true
$startInfo.RedirectStandardError  = $true
$startInfo.UseShellExecute        = $false
$startInfo.CreateNoWindow         = $true

$proc = [System.Diagnostics.Process]::Start($startInfo)
$proc.WaitForExit()
$out = $proc.StandardOutput.ReadToEnd()
$err = $proc.StandardError.ReadToEnd()
$code = $proc.ExitCode

$ts = (Get-Date -Format "o")
Add-Content -Path $Log -Value "=== $ts exit=$code ==="
if ($out) { Add-Content -Path $Log -Value $out }
if ($err) { Add-Content -Path $Log -Value $err }

if ($code -eq 0) {
    Set-Content -Path $Trigger -Value "postmortem-analyze refresh" -Encoding ASCII
    Add-Content -Path $Log -Value "restart_trigger.txt written"
}

exit $code
