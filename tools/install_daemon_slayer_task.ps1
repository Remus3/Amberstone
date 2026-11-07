# Install (or refresh) the RC-DaemonSlayer scheduled task. Idempotent.
#
# Status (2026-10-31 launcher cutover): the cutover UNREGISTERED the
# RC-DaemonSlayer task this script installs (docs/OPERATIONS.md, "Moved to the
# app"); RC's DsWatchdog now starts Daemon Slayer as its own child. Do NOT
# re-run this script on a cut-over host: it would register a second starter
# beside the host (tools/rc_facts.py LAUNCHER_OWNED_TASKS flags that). Kept for
# a host that still registers the task.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File tools\install_daemon_slayer_task.ps1
#   powershell -ExecutionPolicy Bypass -File tools\install_daemon_slayer_task.ps1 -Start
#
# Mirrors the install pattern used by RC-BridgeWatcher:
# delete-then-create from the XML in ops/, optionally start immediately.
#
# RM-723: ops\RC-DaemonSlayer.xml is a machine-free TEMPLATE. It is rendered
# first (tools\install_render_task_xml.ps1 fills the checkout root, account and pinned
# interpreter into a temporary UTF-16 file) and only the rendered file is
# imported. A refused render stops BEFORE the existing task is deleted.

[CmdletBinding()]
param(
    [switch]$Start
)

$ErrorActionPreference = 'Stop'

$TaskName = 'RC-DaemonSlayer'
$Renderer = Join-Path $PSScriptRoot 'install_render_task_xml.ps1'
$Rendered = Join-Path ([System.IO.Path]::GetTempPath()) ('rc-task-' + [guid]::NewGuid().ToString('N') + '.xml')

Write-Host "[install] Task: $TaskName"

try {
    # First statement in the try: a refused render throws straight to the
    # finally, so the existing task is never deleted.
    & $Renderer -Name $TaskName -OutFile $Rendered | Out-Null
    Write-Host "[install] XML : rendered from ops\$TaskName.xml"

    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Host "[install] Existing task found; deleting..."
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    }

    schtasks /Create /TN $TaskName /XML "$Rendered" /F | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "schtasks /Create failed with exit code $LASTEXITCODE"
    }
} finally {
    Remove-Item -LiteralPath $Rendered -Force -ErrorAction SilentlyContinue
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
