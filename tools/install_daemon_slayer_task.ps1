# Install (or refresh) the RC-DaemonSlayer scheduled task. Idempotent.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File tools\install_daemon_slayer_task.ps1
#   powershell -ExecutionPolicy Bypass -File tools\install_daemon_slayer_task.ps1 -Start
#
# Mirrors the install pattern used by RC-BridgeWatcher:
# delete-then-create from the XML in ops/, optionally start immediately.

[CmdletBinding()]
param(
    [switch]$Start
)

$ErrorActionPreference = 'Stop'

$TaskName = 'RC-DaemonSlayer'
$XmlPath = Join-Path $PSScriptRoot '..\ops\RC-DaemonSlayer.xml' | Resolve-Path

Write-Host "[install] Task: $TaskName"
Write-Host "[install] XML : $XmlPath"

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "[install] Existing task found; deleting..."
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

schtasks /Create /TN $TaskName /XML "$XmlPath" /F | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "schtasks /Create failed with exit code $LASTEXITCODE"
}
Write-Host "[install] Created."

if ($Start) {
    Write-Host "[install] Starting..."
    schtasks /Run /TN $TaskName | Out-Null
    Start-Sleep -Seconds 3
    try {
        $resp = Invoke-WebRequest -Uri 'http://127.0.0.1:8860/health' -UseBasicParsing -TimeoutSec 4
        Write-Host "[install] :8860/health -> $($resp.StatusCode) $($resp.Content)"
    } catch {
        Write-Warning "[install] :8860 not responding yet: $($_.Exception.Message)"
        Write-Warning "[install] Check logs and run: schtasks /Query /TN $TaskName"
    }
}

Write-Host "[install] Done."
