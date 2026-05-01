# Riot Commander — Claude Code launcher
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

# 2. RC-VisionServer scheduled task
$vs = Get-ScheduledTask -TaskName "RC-VisionServer" -ErrorAction SilentlyContinue
if ($vs) {
    if ($vs.State -ne "Running") {
        Write-Host "  RC-VisionServer: starting..." -ForegroundColor Yellow
        Start-ScheduledTask -TaskName "RC-VisionServer"
        Start-Sleep -Seconds 2
    } else {
        Write-Host "  RC-VisionServer: running" -ForegroundColor Green
    }
} else {
    Write-Host "  RC-VisionServer: TASK NOT FOUND -- check Task Scheduler" -ForegroundColor Red
}

# 3. Wait briefly for HTTP endpoints to come up if just started
Start-Sleep -Seconds 3

# 4. Probe vision server :8889
try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:8889/health" -TimeoutSec 3 -UseBasicParsing
    Write-Host "  Vision server :8889 alive" -ForegroundColor Green
} catch {
    Write-Host "  Vision server :8889 NOT responding" -ForegroundColor Red
}

# 5. Probe RC dashboard :8888 (HTTPS, self-signed cert)
try {
    $r = Invoke-WebRequest -Uri "https://127.0.0.1:8888/api/health" -TimeoutSec 3 -UseBasicParsing
    Write-Host "  RC dashboard :8888 alive" -ForegroundColor Green
} catch {
    Write-Host "  RC dashboard :8888 not yet responding (may still be booting)" -ForegroundColor Yellow
}

# 6. Check Game-PC screen agent via vision server's latest-frame age
try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:8889/latest-frame" -TimeoutSec 3 -UseBasicParsing
    if ($r.StatusCode -eq 200) {
        Write-Host "  Game-PC screen agent: pushing frames" -ForegroundColor Green
    }
} catch {
    Write-Host "  Game-PC screen agent: no frames -- start gamepc_screen_agent.py on Game-PC" -ForegroundColor Yellow
}

# 7. Check Game-PC MCP server :8892 (inbound listener — Bearer auth, /health endpoint).
#    Process-not-listening + missing firewall rule are the two failure modes.
try {
    $h = @{ 'Authorization' = 'Bearer 8e8f131e212b329438218eca27372dde' }
    $r = Invoke-WebRequest -Uri "http://192.168.8.237:8892/health" -Headers $h -TimeoutSec 3 -UseBasicParsing
    if ($r.StatusCode -eq 200) {
        Write-Host "  Game-PC MCP server :8892 alive" -ForegroundColor Green
    }
} catch {
    Write-Host "  Game-PC MCP server :8892 NOT reachable -- run C:\RC-Agent\gamepc_boot.ps1 on Game-PC" -ForegroundColor Yellow
}

# 7. Echo health.json snapshot
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
claude --dangerously-skip-permissions
