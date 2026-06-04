# gamepc_boot.ps1 - shortcut-only launcher for the Game-PC agents.
#
# Remodeled 2026-05-16 (operator decision). The "RC Agent claude" desktop
# shortcut is the SOLE initiator. This script NO LONGER installs ONLOGON
# persistence for the agents or for itself - agents are launched per session
# only. The ONLY logon persistence kept is the bridge infra (RC-BridgeDaemon
# + the pre-existing RC-BridgeWatcher-GamePC / RC-WatcherHealthPublisher-GamePC)
# so cross-Claude coordination survives a reboot without the shortcut. This
# script ensures RC-BridgeDaemon and intentionally leaves the other two alone.
#
# Screen-agent --monitor args reflect the post-Q27GAZD-swap DXGI mapping
# confirmed by task-45f704742197 + Legion cross-check:
#   bettercam device_idx=0  output_idx 0 = Duet/dashboard (1920x1280)
#                            output_idx 1 = Q27GAZD/League (1920x1080)
# So league/minimap -> --monitor 1, ui -> --monitor 0. The 0/1 index order is
# NOT stable across reboots/display changes - re-confirm by RESOLUTION, not
# index, if displays change again.
#
# Claude: opens the Claude Code Desktop app. The exact launch command is
# resolved on Game-PC and written to C:\RC-Agent\claude_code_app.txt; falls
# back to the legacy CLI launcher (start_gamepc_claude.ps1) if absent.
#
# Usage (desktop shortcut target):
#   powershell -ExecutionPolicy Bypass -NoExit -Command "iex (iwr https://legion-rc:8888/agent/gamepc_boot.ps1).Content"

$ErrorActionPreference = 'Stop'
$dest = 'C:\RC-Agent'
if (-not (Test-Path $dest)) { New-Item -ItemType Directory -Path $dest | Out-Null }

# Self-elevate - firewall rule + RC-BridgeDaemon ensure need admin.
$principal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Start-Process powershell.exe -ArgumentList '-NoExit','-ExecutionPolicy','Bypass','-File',"`"$PSCommandPath`"" -Verb RunAs
    exit
}

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
[System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }

Write-Host ''
Write-Host '=== Game-PC boot (shortcut-only model) ===' -ForegroundColor Cyan

# 1. Refresh agent + support scripts + slash commands from Legion (canonical
#    source) so edits ship via the /agent/ allowlist on every shortcut run.
$AGENT_SCRIPTS  = @('gamepc_screen_agent.py','gamepc_lcu_agent.py','gamepc_liveclient_relay.py','gamepc_mcp_server.py','gamepc_hotkey_listener.py')
$SUPPORT_SCRIPTS = @('start_gamepc_claude.ps1','gamepc_bridge_daemon.py')
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
$cmdsDir = Join-Path $env:USERPROFILE '.claude\commands'
if (-not (Test-Path $cmdsDir)) { New-Item -ItemType Directory -Path $cmdsDir | Out-Null }
$SLASH = @(@{src='process-bridge-tasks.md';dst='process-bridge-tasks.md'}, @{src='done-gamepc.md';dst='done.md'})
foreach ($c in $SLASH) {
    $out = Join-Path $cmdsDir $c.dst
    & curl.exe -sk -m 5 -o $out "https://legion-rc:8888/agent/$($c.src)" 2>$null
    if ($LASTEXITCODE -eq 0 -and (Test-Path $out) -and (Get-Item $out).Length -gt 0) {
        Write-Host "  fetched $($c.src) -> ~/.claude/commands/$($c.dst)" -ForegroundColor Green
    }
}

# 2. Firewall - inbound rule for the MCP server port (others are outbound-only).
if (-not (Get-NetFirewallRule -DisplayName 'RC-MCP' -ErrorAction SilentlyContinue)) {
    try {
        New-NetFirewallRule -DisplayName 'RC-MCP' -Direction Inbound -Protocol TCP -LocalPort 8892 -Action Allow -Profile Any -ErrorAction Stop | Out-Null
        Write-Host '  firewall rule RC-MCP added' -ForegroundColor Green
    } catch { Write-Host "  firewall add FAILED: $($_.Exception.Message)" -ForegroundColor Red }
} else { Write-Host '  firewall rule RC-MCP present' -ForegroundColor Green }

# 3. Interpreters. pythoncore-3.14-64 is the bettercam-capable interpreter the
#    screen agents require; fall back to the standard Python314 install.
$pyCore = 'C:\Users\Administrator\AppData\Local\Python\pythoncore-3.14-64'
$pyW = Join-Path $pyCore 'pythonw.exe'
$pyC = Join-Path $pyCore 'python.exe'
if (-not (Test-Path $pyW)) { $pyW = 'C:\Users\Administrator\AppData\Local\Programs\Python\Python314\pythonw.exe' }
if (-not (Test-Path $pyC)) { $pyC = 'C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe' }

function Test-AgentRunning {
    param([string]$scriptName)
    $p = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
         Where-Object { $_.CommandLine -like "*$scriptName*" } | Select-Object -First 1
    return [bool]$p
}

# 4. Launch agents PER SESSION (no scheduled-task persistence). Idempotent -
#    a process already alive for a script is left as-is (never double-launch).

# Screen agents x3 - corrected post-swap mapping (output_idx 1 = Q27GAZD/
# League, 0 = Duet/dashboard). pythonw (no window), bettercam DXGI.
$SCREEN = @(
    '--monitor 1 --channel game-pc-league',
    '--monitor 0 --channel game-pc-ui --no-primary',
    '--monitor 1 --channel minimap --no-primary --crop 1580,780,1920,1080 --interval 0.2'
)
# === Screen agents NOT launched (1-PC, ADR-011) ===
# Game-PC is out of the League/RC pipeline (2026-05-29). The continuous
# screen-agent loop is retired in favor of Legion's in-process self-grab
# relay, so the 3 screen agents are not started here. $SCREEN is left
# defined above if a manual relay is ever needed.
Write-Host '  screen agents not launched - Game-PC out of pipeline (1-PC, ADR-011)' -ForegroundColor Yellow
# if (Test-AgentRunning 'gamepc_screen_agent.py') {
#     Write-Host '  screen agents: already running, leaving as-is' -ForegroundColor Green
# } else {
#     foreach ($a in $SCREEN) {
#         Start-Process -WindowStyle Hidden -FilePath $pyW -ArgumentList "C:\RC-Agent\gamepc_screen_agent.py $a"
#     }
#     Write-Host '  screen agents x3 launched' -ForegroundColor Green
# }

# LCU agent - operator wants its console window MINIMIZED (visible/accessible,
# out of the way), not hidden. Console python so the window exists.
if (Test-AgentRunning 'gamepc_lcu_agent.py') {
    Write-Host '  lcu agent: already running' -ForegroundColor Green
} else {
    Start-Process -WindowStyle Minimized -FilePath $pyC -ArgumentList 'C:\RC-Agent\gamepc_lcu_agent.py'
    Write-Host '  lcu agent launched (minimized)' -ForegroundColor Green
}

# Liveclient relay + hotkey listener - hidden (no window needed).
foreach ($s in @('gamepc_liveclient_relay.py','gamepc_hotkey_listener.py')) {
    if (Test-AgentRunning $s) {
        Write-Host "  ${s}: already running" -ForegroundColor Green
    } else {
        Start-Process -WindowStyle Hidden -FilePath $pyW -ArgumentList "C:\RC-Agent\$s"
        Write-Host "  $s launched" -ForegroundColor Green
    }
}

# MCP server - verify it actually binds :8892 (zombie case: process alive but
# never listening). Kill a non-listening stale process before relaunch.
$mcpListening = [bool](Get-NetTCPConnection -LocalPort 8892 -State Listen -ErrorAction SilentlyContinue)
$mcpProcs = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
            Where-Object { $_.CommandLine -like '*gamepc_mcp_server.py*' }
if ($mcpProcs -and -not $mcpListening) {
    foreach ($p in $mcpProcs) { taskkill /F /PID $p.ProcessId 2>&1 | Out-Null }
    $mcpProcs = $null
}
if ($mcpProcs) {
    Write-Host '  mcp server: running + bound :8892' -ForegroundColor Green
} else {
    Start-Process -WindowStyle Hidden -FilePath $pyW -ArgumentList 'C:\RC-Agent\gamepc_mcp_server.py'
    Start-Sleep -Seconds 3
    if (Get-NetTCPConnection -LocalPort 8892 -State Listen -ErrorAction SilentlyContinue) {
        Write-Host '  mcp server launched + bound :8892' -ForegroundColor Green
    } else {
        Write-Host '  mcp server launched but NOT bound :8892 within 3s' -ForegroundColor Red
    }
}

# 5. Bridge infra - the ONLY logon persistence kept (operator decision):
#    coordination must survive a reboot without the shortcut. Ensure the
#    RC-BridgeDaemon scheduled task exists + running. RC-BridgeWatcher-GamePC
#    and RC-WatcherHealthPublisher-GamePC are pre-existing ONLOGON tasks -
#    hardened (not fabricated) in step 5b below (Audit7 H-01).
$daemonScript = Join-Path $dest 'gamepc_bridge_daemon.py'
$pyW314 = 'C:\Users\Administrator\AppData\Local\Programs\Python\Python314\pythonw.exe'
if (-not (Test-Path $pyW314)) { $pyW314 = $pyW }
if (-not (Get-ScheduledTask -TaskName 'RC-BridgeDaemon' -ErrorAction SilentlyContinue)) {
    if (Test-Path $daemonScript) {
        $action   = New-ScheduledTaskAction -Execute $pyW314 -Argument $daemonScript
        $trigger  = New-ScheduledTaskTrigger -AtLogOn -User 'Administrator'
        $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
        $prin     = New-ScheduledTaskPrincipal -UserId 'Administrator' -LogonType Interactive -RunLevel Highest
        Register-ScheduledTask -TaskName 'RC-BridgeDaemon' -Action $action -Trigger $trigger -Settings $settings -Principal $prin -Description 'Zero-cost bridge sentinel (kept on logon by operator decision 2026-05-16).' -Force | Out-Null
        Write-Host '  RC-BridgeDaemon task installed' -ForegroundColor Green
    } else { Write-Host '  gamepc_bridge_daemon.py missing; skipping' -ForegroundColor Yellow }
} else { Write-Host '  RC-BridgeDaemon task present' -ForegroundColor Green }
$dt = Get-ScheduledTask -TaskName 'RC-BridgeDaemon' -ErrorAction SilentlyContinue
if ($dt -and $dt.State -ne 'Running') { Start-ScheduledTask -TaskName 'RC-BridgeDaemon'; Write-Host '  RC-BridgeDaemon started' -ForegroundColor Green }

# 5b. Harden the pre-existing bridge watcher + health-publisher ONLOGON
#     tasks (Audit7 H-01, 2026-05-18). They predate the RC-BridgeDaemon
#     pattern above and shipped with ExecutionTimeLimit=PT72H (Task
#     Scheduler force-kills these infinite daemons after 72h) and a
#     logon-only trigger (once RestartCount exhausts they stay dead until
#     the next logon - the 2026-05-17 ~3h silent-publisher incident that
#     Audit7 H-01's alarm now also detects). Re-apply the same robust
#     settings as RC-BridgeDaemon plus a 10-min self-heal repetition
#     (IgnoreNew makes the re-fire a no-op while alive), and start any
#     that aren't running. Idempotent. We harden existing tasks but do
#     NOT fabricate them - the canonical --node/--*-file/--*-url args
#     live in the installer; warn if absent so the drift stays visible.
foreach ($tn in 'RC-BridgeWatcher-GamePC','RC-WatcherHealthPublisher-GamePC') {
    $bt = Get-ScheduledTask -TaskName $tn -ErrorAction SilentlyContinue
    if (-not $bt) {
        Write-Host "  $tn ABSENT - run the installer (not fabricated here)" -ForegroundColor Yellow
        continue
    }
    try {
        $tLogon  = New-ScheduledTaskTrigger -AtLogOn -User 'Administrator'
        $tRepeat = New-ScheduledTaskTrigger -Once -At (Get-Date).Date -RepetitionInterval (New-TimeSpan -Minutes 10) -RepetitionDuration (New-TimeSpan -Days 3650)
        $bset    = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable
        Set-ScheduledTask -TaskName $tn -Trigger @($tLogon, $tRepeat) -Settings $bset | Out-Null
        Write-Host "  $tn hardened (ETL=0, +10m self-heal)" -ForegroundColor Green
    } catch {
        Write-Host "  $tn harden failed: $($_.Exception.Message)" -ForegroundColor Yellow
    }
    $bt = Get-ScheduledTask -TaskName $tn -ErrorAction SilentlyContinue
    if ($bt -and $bt.State -ne 'Running') {
        Start-ScheduledTask -TaskName $tn
        Write-Host "  $tn started" -ForegroundColor Green
    }
}

Write-Host ''
Write-Host '=== agents up ===' -ForegroundColor Cyan
Write-Host ''

# 6. Open Claude Desktop (operator decision 2026-05-20: shortcut opens the
#    Squirrel-installed Claude Desktop chat app, NOT the Claude Code CLI).
#    Prior section 6a resolved AppData\Roaming\Claude\claude-code\<ver>\claude.exe
#    which IS the CLI native installer (comment was wrong) - that launch path
#    was the cause of the auth-conflict warning (ANTHROPIC_API_KEY + claude.ai
#    OAuth both visible to the CLI). The chat app reads neither, so opening it
#    sidesteps the conflict entirely. CLI fallback removed: operator does NOT
#    want the CLI launched here under any circumstance.
$ccDesktop = 'C:\Users\Administrator\AppData\Local\AnthropicClaude\claude.exe'
$ccMarker  = Join-Path $dest 'claude_code_app.txt'
$launched  = $false

# 6a. Primary: Squirrel-installed Claude Desktop (AnthropicClaude\claude.exe).
#     The Squirrel stub auto-resolves the newest app-<ver>\ subdir, so we do
#     not need to enumerate versions ourselves.
if (Test-Path $ccDesktop) {
    try {
        Write-Host 'Opening Claude Desktop...' -ForegroundColor Cyan
        Start-Process -FilePath $ccDesktop
        $launched = $true
    } catch { Write-Host "  Claude Desktop launch failed: $($_.Exception.Message)" -ForegroundColor Yellow }
}

# 6b. Fallback: claude_code_app.txt marker (manual override). Kept for the
#     rare case where Claude Desktop is reinstalled to a non-standard path.
#     Operator-edited file; if absent, this branch is a no-op.
if (-not $launched -and (Test-Path $ccMarker)) {
    $cc = Get-Content -Raw $ccMarker -ErrorAction SilentlyContinue
    if ($cc) { $cc = $cc.Trim() }
    if ($cc) {
        try {
            Write-Host '  primary Desktop path missed - using claude_code_app.txt marker' -ForegroundColor Yellow
            Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', $cc -WindowStyle Hidden
            $launched = $true
        } catch { Write-Host "  marker launch failed: $($_.Exception.Message)" -ForegroundColor Yellow }
    }
}

if (-not $launched) {
    Write-Host '  Claude Desktop not found - skipping launch (CLI fallback intentionally removed)' -ForegroundColor Red
}

Write-Host ''
Write-Host '(this window auto-closes in 15s; Claude stays open)' -ForegroundColor DarkGray
Start-Sleep -Seconds 15
[Environment]::Exit(0)
