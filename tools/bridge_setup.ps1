# bridge_setup.ps1 - one-shot bootstrap for a peer's bridge tooling (Peer).
# Downloads bridge_fetch / bridge_ping / bridge_heartbeat from Legion,
# then runs the ping validator so the user sees PASS/FAIL immediately.
#
# Usage (single-line paste on the peer, never wraps):
#   iex (iwr https://legion-rc:8888/agent/bridge_setup.ps1).Content

$ErrorActionPreference = 'Stop'
$dest = 'C:\RC-Agent'
if (-not (Test-Path $dest)) { New-Item -ItemType Directory -Path $dest | Out-Null }

$files = @('bridge_fetch.py', 'bridge_ping.py', 'bridge_heartbeat.py')
foreach ($f in $files) {
    $url = "https://legion-rc:8888/agent/$f"
    $out = Join-Path $dest $f
    try {
        Invoke-WebRequest -Uri $url -OutFile $out -UseBasicParsing
        $sz = (Get-Item $out).Length
        Write-Host "  [ok] $f  ($sz bytes)"
    } catch {
        Write-Host "  [FAIL] $f  $($_.Exception.Message)"
    }
}

# Reset last-seen ledger so a fresh bridge_fetch sees the backlog.
$seen = Join-Path $env:LOCALAPPDATA 'rc-bridge-last-seen.txt'
if (Test-Path $seen) { Remove-Item $seen; Write-Host "  [ok] cleared last-seen ledger" }

Write-Host ""
Write-Host "== running bridge_ping =="
# Resolve a real interpreter rather than the bare-py launcher: on Legion
# bare `py` resolves via PEP 514 to a dep-less pymanager runtime (documented
# incident). bridge_ping.py is stdlib-only, but pin the interpreter the
# daemons use so the validator runs under the same Python.
$pingScript = Join-Path $dest 'bridge_ping.py'
$pyExe = ""
$pyCandidates = @(
    "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
    "C:\Python314\python.exe",
    "C:\Python313\python.exe"
)
foreach ($c in $pyCandidates) {
    if (Test-Path -LiteralPath $c) { $pyExe = $c; break }
}
if (-not $pyExe) {
    $pyExe = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
}
if (-not $pyExe) {
    Write-Host "  [FAIL] no python.exe found; install Python or run bridge_ping.py manually"
} else {
    & $pyExe $pingScript
}
