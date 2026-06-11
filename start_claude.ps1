# Riot Commander - Claude Code launcher
# Verifies background agents are up, then launches Claude in this project.

# Self-elevate if not running as admin
$principal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Start-Process powershell.exe -ArgumentList "-NoExit","-ExecutionPolicy","Bypass","-File","`"$PSCommandPath`"" -Verb RunAs
    exit
}

Set-Location "C:\Riot Commander"
[System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }

Write-Host ""
Write-Host "=== RC Pre-flight ===" -ForegroundColor Cyan

# 1. RC-Supervisor scheduled task (runs main.py via pythonw)
$sup = Get-ScheduledTask -TaskName "RC-Supervisor" -ErrorAction SilentlyContinue
if ($sup) {
    if ($sup.State -ne "Running") {
        Write-Host "  RC-Supervisor: starting..." -ForegroundColor Yellow
        Start-ScheduledTask -TaskName "RC-Supervisor"
        Start-Sleep -Seconds 2
    } else {
        Write-Host "  RC-Supervisor: running" -ForegroundColor Green
    }
} else {
    Write-Host "  RC-Supervisor: TASK NOT FOUND -- check Task Scheduler" -ForegroundColor Red
}

# 2. Vision server has NO scheduled task (removed 2026-06-11, deep-audit P2):
#    dashboard/server.py self-heals :8889 in-process; step 7 probes it.

# 3. RC-DaemonSlayer (Daemon Slayer build engine :8893)
$ds = Get-ScheduledTask -TaskName "RC-DaemonSlayer" -ErrorAction SilentlyContinue
if ($ds) {
    if ($ds.State -ne "Running") {
        Write-Host "  RC-DaemonSlayer: starting..." -ForegroundColor Yellow
        Start-ScheduledTask -TaskName "RC-DaemonSlayer"
        Start-Sleep -Seconds 2
    } else {
        Write-Host "  RC-DaemonSlayer: running" -ForegroundColor Green
    }
} else {
    Write-Host "  RC-DaemonSlayer: TASK NOT FOUND -- run tools\install_daemon_slayer_task.ps1" -ForegroundColor Red
}

# 4. RC-Phase3-Supervisor (agents framework :8890/:8891)
$p3 = Get-ScheduledTask -TaskName "RC-Phase3-Supervisor" -ErrorAction SilentlyContinue
if ($p3) {
    if ($p3.State -ne "Running") {
        Write-Host "  RC-Phase3-Supervisor: starting..." -ForegroundColor Yellow
        Start-ScheduledTask -TaskName "RC-Phase3-Supervisor"
        Start-Sleep -Seconds 2
    } else {
        Write-Host "  RC-Phase3-Supervisor: running" -ForegroundColor Green
    }
} else {
    Write-Host "  RC-Phase3-Supervisor: TASK NOT FOUND -- run ops\phase3_install.ps1" -ForegroundColor Red
}

# 5. RC-BridgeWatcher (bridge escalation monitor - should always be Running)
$bw = Get-ScheduledTask -TaskName "RC-BridgeWatcher" -ErrorAction SilentlyContinue
if ($bw) {
    if ($bw.State -ne "Running") {
        Write-Host "  RC-BridgeWatcher: NOT running (state=$($bw.State))" -ForegroundColor Yellow
    } else {
        Write-Host "  RC-BridgeWatcher: running" -ForegroundColor Green
    }
} else {
    Write-Host "  RC-BridgeWatcher: TASK NOT FOUND" -ForegroundColor Red
}

# 6. Wait briefly for HTTP endpoints to come up if just started
Start-Sleep -Seconds 3

# 7. Probe vision server :8889
try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:8889/health" -TimeoutSec 3 -UseBasicParsing
    Write-Host "  Vision server :8889 alive" -ForegroundColor Green
} catch {
    Write-Host "  Vision server :8889 NOT responding" -ForegroundColor Red
}

# 8. Probe RC dashboard :8888 (HTTPS, self-signed cert)
try {
    $r = Invoke-WebRequest -Uri "https://127.0.0.1:8888/api/health" -TimeoutSec 3 -UseBasicParsing
    Write-Host "  RC dashboard :8888 alive" -ForegroundColor Green
} catch {
    Write-Host "  RC dashboard :8888 not yet responding (may still be booting)" -ForegroundColor Yellow
}

# 9. Probe Daemon Slayer :8893
try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:8893/health" -TimeoutSec 3 -UseBasicParsing
    $ds_info = ($r.Content | ConvertFrom-Json)
    Write-Host ("  Daemon Slayer :8893 alive  engine={0}  patch={1}" -f $ds_info.engine_version, $ds_info.patch) -ForegroundColor Green
} catch {
    Write-Host "  Daemon Slayer :8893 NOT responding" -ForegroundColor Red
}

# 10. Probe Phase 3 supervisor :8890
try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:8890/" -TimeoutSec 3 -UseBasicParsing
    Write-Host "  Phase 3 supervisor :8890 alive" -ForegroundColor Green
} catch {
    Write-Host "  Phase 3 supervisor :8890 NOT responding" -ForegroundColor Yellow
}

# 11. Check vision frames via the local vision server's latest-frame
#     (1-PC, ADR-011: the screen agent runs Legion-local; the retired
#      Game-PC MCP :8892 probe was removed - it always failed post-consolidation)
try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:8889/latest-frame" -TimeoutSec 3 -UseBasicParsing
    if ($r.StatusCode -eq 200) {
        Write-Host "  Vision frames: present (Legion-local screen agent)" -ForegroundColor Green
    }
} catch {
    Write-Host "  Vision frames: none yet (only populated mid-game)" -ForegroundColor Yellow
}

# 12. Echo health.json snapshot
$healthPath = "C:\Riot Commander\ops\runtime\health.json"
if (Test-Path $healthPath) {
    try {
        $h = Get-Content $healthPath -Raw | ConvertFrom-Json
        Write-Host ("  health.json: pid={0} alive={1} mode={2}" -f $h.pid, $h.alive, $h.mode) -ForegroundColor Cyan
    } catch {}
}

Write-Host ""
Write-Host "=== Launching Claude ===" -ForegroundColor Cyan
Write-Host ""
claude --name "Legion" --dangerously-skip-permissions
