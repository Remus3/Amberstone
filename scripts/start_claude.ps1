# Amberstone - Claude Code launcher
# Verifies background agents are up, then launches Claude in this project.
# Lives in scripts\ (moved from the repo root 2026-10-09, MAIN 2246 sec 3);
# the repo root is this file's parent folder.
$RepoRoot = Split-Path -Parent $PSScriptRoot

# Self-elevate if not running as admin
$principal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Start-Process powershell.exe -ArgumentList "-NoExit","-ExecutionPolicy","Bypass","-File","`"$PSCommandPath`"" -Verb RunAs
    exit
}

Set-Location $RepoRoot
[System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }

Write-Host ""
Write-Host "=== RC Pre-flight ===" -ForegroundColor Cyan

# 1. The rc-shell service host. Since the 2026-10-31 launcher cutover
#    (docs/PACKAGING_PLAN.md section 5) NO scheduled task starts RC: rc-shell
#    launched with --profile dev spawns ops/launcher/service_host.py, which
#    runs the supervisor (main.py, vision :8889, DS :8860), the LCU agent,
#    the Live Client relay, the hotkey listener and Phase 3 (:8890/:8891).
#    Read-only here: this pre-flight starts nothing and must never re-register
#    a moved task (tools/rc_facts.py flags one that is registered again).
#    The host rewrites its status file at least every 5 s; 30 s = stale.
$statusPath = Join-Path $RepoRoot "ops\runtime\launcher_status.json"
$hostUp = $false
if (Test-Path -LiteralPath $statusPath) {
    try {
        $st = Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
        $upd = $st.updated
        if ($upd -isnot [DateTime]) {
            $upd = [DateTime]::Parse([string]$upd, [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::RoundtripKind)
        }
        $age = ((Get-Date).ToUniversalTime() - $upd.ToUniversalTime()).TotalSeconds
        if ($st.state -ne 'halted' -and $age -le 30) {
            $hostUp = $true
            Write-Host ("  Shell host: {0} (mode={1} pid={2})" -f $st.state, $st.mode, $st.host_pid) -ForegroundColor Green
        }
    } catch {}
}
if (-not $hostUp) {
    Write-Host "  Shell host: NOT running -- launch the app: electron.exe . --profile dev from rc-shell" -ForegroundColor Yellow
}

# 2. Vision server has NO scheduled task (removed 2026-06-11, deep-audit P2):
#    dashboard/server.py self-heals :8889 in-process; step 7 probes it.

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

# 9. Probe Daemon Slayer :8860
try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:8860/health" -TimeoutSec 3 -UseBasicParsing
    $ds_info = ($r.Content | ConvertFrom-Json)
    Write-Host ("  Daemon Slayer :8860 alive  engine={0}  patch={1}" -f $ds_info.engine_version, $ds_info.patch) -ForegroundColor Green
} catch {
    Write-Host "  Daemon Slayer :8860 NOT responding" -ForegroundColor Red
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
#      off-box MCP :8892 probe was removed - it always failed post-consolidation)
try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:8889/latest-frame" -TimeoutSec 3 -UseBasicParsing
    if ($r.StatusCode -eq 200) {
        Write-Host "  Vision frames: present (Legion-local screen agent)" -ForegroundColor Green
    }
} catch {
    Write-Host "  Vision frames: none yet (only populated mid-game)" -ForegroundColor Yellow
}

# 12. Echo health.json snapshot
$healthPath = Join-Path $RepoRoot "ops\runtime\health.json"
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
