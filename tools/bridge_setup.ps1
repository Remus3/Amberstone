# bridge_setup.ps1 — one-shot bootstrap for Game-PC bridge tooling.
# Downloads bridge_fetch / bridge_ping / bridge_heartbeat from Legion,
# then runs the ping validator so the user sees PASS/FAIL immediately.
#
# Usage (single-line paste on Game-PC, never wraps):
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
& py (Join-Path $dest 'bridge_ping.py')
