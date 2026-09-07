# legion_agent_boot.ps1 - per-session launcher for the Legion-local agents.
#
# Relocated 2026-05-29 (ADR-011, 1-PC consolidation). League + RC + the
# helper agents all run ON Legion now; Game-PC is out of the pipeline. This
# script refreshes the relocated agent scripts from the canonical /agent/
# allowlist on Legion, then launches them per session (idempotent - a process
# already alive for a script is left as-is, never double-launched).
#
# Agents launched: lcu_agent.py (LCU reader / rune + item-set push, console
# MINIMIZED) and liveclient_relay.py + hotkey_listener.py (hidden, no window).
# The continuous screen-agent loop is retired in favor of RC's in-process
# self-grab relay, so screen_agent.py is fetched (kept current) but not started.
#
# Logon persistence for these agents lives in their own RC-* scheduled tasks
# (RC-LCUAgent / RC-LiveClientRelay / RC-HotkeyListener) - this script is the
# per-session refresh+launch path, not the persistence owner.
#
# Usage (desktop shortcut target):
#   powershell -ExecutionPolicy Bypass -NoExit -Command "iex (iwr https://legion-rc:8888/agent/legion_agent_boot.ps1).Content"

$ErrorActionPreference = 'Stop'
$dest = 'C:\RC-Agent'
if (-not (Test-Path $dest)) { New-Item -ItemType Directory -Path $dest | Out-Null }

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
[System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }

Write-Host ''
Write-Host '=== Legion agent boot ===' -ForegroundColor Cyan

# 1. Refresh agent scripts + slash commands from Legion (canonical source) so
#    edits ship via the /agent/ allowlist on every run.
$AGENT_SCRIPTS   = @('screen_agent.py','lcu_agent.py','liveclient_relay.py','hotkey_listener.py')
$SUPPORT_SCRIPTS = @()
foreach ($s in ($AGENT_SCRIPTS + $SUPPORT_SCRIPTS)) {
    $out = Join-Path $dest $s
    & curl.exe -sk -m 5 -o $out "https://legion-rc:8888/agent/$s" 2>$null
    if ($LASTEXITCODE -eq 0 -and (Test-Path $out) -and (Get-Item $out).Length -gt 0) {
        Write-Host "  fetched $s" -ForegroundColor Green
    } elseif (Test-Path $out) {
        Write-Host "  fetch $s failed, using local copy" -ForegroundColor Yellow
    } else {
        Write-Host "  fetch $s FAILED, no local copy" -ForegroundColor Red
    }
}
# Slash-command sync removed 2026-06-24: the only entry (process-bridge-tasks.md)
# was deleted with the cross-Claude bridge decommission (ADR-012).

# 2. Interpreters. pythoncore-3.14-64 is the bettercam-capable interpreter the
#    screen agent requires; fall back to the standard Python314 install.
$pyCore = "$env:LOCALAPPDATA\Python\pythoncore-3.14-64"
$pyW = Join-Path $pyCore 'pythonw.exe'
$pyC = Join-Path $pyCore 'python.exe'
if (-not (Test-Path $pyW)) { $pyW = "$env:LOCALAPPDATA\Programs\Python\Python314\pythonw.exe" }
if (-not (Test-Path $pyC)) { $pyC = "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe" }

function Test-AgentRunning {
    param([string]$scriptName)
    $p = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
         Where-Object { $_.CommandLine -like "*$scriptName*" } | Select-Object -First 1
    return [bool]$p
}

# 3. Launch agents PER SESSION (no scheduled-task persistence here). Idempotent -
#    a process already alive for a script is left as-is (never double-launch).

# Screen agent - NOT launched (1-PC, ADR-011). The continuous screen-grab loop
# is retired in favor of RC's in-process self-grab relay. screen_agent.py is
# kept current above for a manual relay if ever needed.
Write-Host '  screen agent not launched - in-process self-grab relay (1-PC, ADR-011)' -ForegroundColor Yellow

# LCU agent - operator wants its console window MINIMIZED (visible/accessible,
# out of the way), not hidden. Console python so the window exists.
if (Test-AgentRunning 'lcu_agent.py') {
    Write-Host '  lcu agent: already running' -ForegroundColor Green
} else {
    Start-Process -WindowStyle Minimized -FilePath $pyC -ArgumentList 'C:\RC-Agent\lcu_agent.py'
    Write-Host '  lcu agent launched (minimized)' -ForegroundColor Green
}

# Liveclient relay + hotkey listener - hidden (no window needed).
foreach ($s in @('liveclient_relay.py','hotkey_listener.py')) {
    if (Test-AgentRunning $s) {
        Write-Host "  ${s}: already running" -ForegroundColor Green
    } else {
        Start-Process -WindowStyle Hidden -FilePath $pyW -ArgumentList "C:\RC-Agent\$s"
        Write-Host "  $s launched" -ForegroundColor Green
    }
}

Write-Host ''
Write-Host '=== agents up ===' -ForegroundColor Cyan
Write-Host ''
Write-Host '(this window auto-closes in 15s)' -ForegroundColor DarkGray
Start-Sleep -Seconds 15
[Environment]::Exit(0)
