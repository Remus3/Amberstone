# gamepc_boot.ps1 — idempotent boot script for the 4 Game-PC agents.
#
# Run from the Game-PC desktop shortcut. Ensures each agent is actually
# *bound* to its expected port, not just running with a matching command
# line — covers the 2026-04-30 zombie py.exe case where the MCP process
# was running but never listening. Also installs the firewall rule for
# the inbound MCP port (8892) if missing.
#
# Pulls the canonical script from Legion before launching, so a stale
# copy on Game-PC self-heals on next boot.
#
# Usage (single-line paste, never wraps):
#   iex (iwr https://legion-rc:8888/agent/gamepc_boot.ps1).Content
#
# Or, after installation, just run from C:\RC-Agent\:
#   powershell -ExecutionPolicy Bypass -File C:\RC-Agent\gamepc_boot.ps1

$ErrorActionPreference = 'Stop'
$dest = 'C:\RC-Agent'
if (-not (Test-Path $dest)) { New-Item -ItemType Directory -Path $dest | Out-Null }

# Self-elevate for firewall rule + scheduled task creation.
$principal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Start-Process powershell.exe -ArgumentList '-NoExit','-ExecutionPolicy','Bypass','-File',"`"$PSCommandPath`"" -Verb RunAs
    exit
}

# PS 5.1 defaults to TLS 1.0/1.1 which the RC dashboard rejects.
# ServicePointManager state is per-process; setting it here covers
# every Invoke-WebRequest call below.
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
[System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }

Write-Host ''
Write-Host '=== Game-PC pre-flight ===' -ForegroundColor Cyan

# 1. Refresh agent scripts from Legion (canonical source).
$AGENTS = @(
    @{ name = 'gamepc_screen_agent.py';     port = $null;  task = 'RC-ScreenAgent'      },
    @{ name = 'gamepc_lcu_agent.py';        port = $null;  task = 'RC-LCU'              },
    @{ name = 'gamepc_liveclient_relay.py'; port = $null;  task = 'RC-LiveClientRelay'  },
    @{ name = 'gamepc_mcp_server.py';       port = 8892;   task = 'RC-MCP-Server'       },
    @{ name = 'gamepc_hotkey_listener.py';  port = $null;  task = 'RC-HotkeyListener'   }
)

# Non-agent support scripts (launchers, helpers) pulled fresh on each boot
# so updates ship via the same /agent/ allowlist.
$SUPPORT_SCRIPTS = @('start_gamepc_claude.ps1', 'gamepc_bridge_daemon.py')
foreach ($s in $SUPPORT_SCRIPTS) {
    $url = "https://legion-rc:8888/agent/$s"
    $out = Join-Path $dest $s
    & curl.exe -sk -m 5 -o $out $url 2>$null
    if ($LASTEXITCODE -eq 0 -and (Test-Path $out) -and (Get-Item $out).Length -gt 0) {
        Write-Host "  fetched $s" -ForegroundColor Green
    } elseif (Test-Path $out) {
        Write-Host "  fetch $s failed, using existing local copy" -ForegroundColor Yellow
    } else {
        Write-Host "  fetch $s FAILED and no local copy" -ForegroundColor Red
    }
}

# Slash-command files for Claude on Game-PC. RC-BridgeDaemon (step 6)
# invokes `claude --print /process-bridge-tasks` when tasks are pending,
# so process-bridge-tasks.md must live in ~/.claude/commands/ even though
# there's no always-running /loop. Pulled fresh on each boot so RC-side
# edits propagate without a manual copy.
$cmdsDir = Join-Path $env:USERPROFILE '.claude\commands'
if (-not (Test-Path $cmdsDir)) {
    New-Item -ItemType Directory -Path $cmdsDir | Out-Null
}
# Each entry: @{src='<filename on /agent/>'; dst='<local name in ~/.claude/commands>'}
# dst differs from src for peer-variant skills (e.g., done-gamepc.md is served
# but lands as done.md so the user can type /done).
$SLASH_COMMANDS = @(
    @{ src = 'process-bridge-tasks.md'; dst = 'process-bridge-tasks.md' },
    @{ src = 'done-gamepc.md';          dst = 'done.md' }
)
foreach ($c in $SLASH_COMMANDS) {
    $url = "https://legion-rc:8888/agent/$($c.src)"
    $out = Join-Path $cmdsDir $c.dst
    & curl.exe -sk -m 5 -o $out $url 2>$null
    if ($LASTEXITCODE -eq 0 -and (Test-Path $out) -and (Get-Item $out).Length -gt 0) {
        Write-Host "  fetched $($c.src) → ~/.claude/commands/$($c.dst)" -ForegroundColor Green
    } elseif (Test-Path $out) {
        Write-Host "  fetch $($c.src) failed, using existing local copy at $($c.dst)" -ForegroundColor Yellow
    } else {
        Write-Host "  fetch $($c.src) FAILED and no local copy" -ForegroundColor Red
    }
}

# Use curl.exe (bundled with Win10/11 in System32) instead of
# Invoke-WebRequest. PS 5.1's iwr fails the TLS handshake against the
# dashboard's self-signed cert under iex even with SecurityProtocol set
# and ServerCertificateValidationCallback assigned — the callback
# doesn't take effect from inside an iex'd script. curl.exe -sk is
# unaffected by any of that.
foreach ($a in $AGENTS) {
    $url = "https://legion-rc:8888/agent/$($a.name)"
    $out = Join-Path $dest $a.name
    & curl.exe -sk -m 5 -o $out $url 2>$null
    if ($LASTEXITCODE -eq 0 -and (Test-Path $out) -and (Get-Item $out).Length -gt 0) {
        Write-Host "  fetched $($a.name)" -ForegroundColor Green
    } elseif (Test-Path $out) {
        Write-Host "  fetch $($a.name) failed, using existing local copy" -ForegroundColor Yellow
    } else {
        Write-Host "  fetch $($a.name) FAILED and no local copy" -ForegroundColor Red
    }
}

# 2. Firewall — ensure inbound rule for the MCP server port. The other
#    three agents don't accept inbound (they're outbound-only POSTs).
$fw = Get-NetFirewallRule -DisplayName 'RC-MCP' -ErrorAction SilentlyContinue
if (-not $fw) {
    try {
        New-NetFirewallRule -DisplayName 'RC-MCP' -Direction Inbound -Protocol TCP -LocalPort 8892 -Action Allow -Profile Any -ErrorAction Stop | Out-Null
        Write-Host '  firewall rule RC-MCP (TCP 8892) added' -ForegroundColor Green
    } catch {
        Write-Host "  firewall rule add FAILED: $($_.Exception.Message)" -ForegroundColor Red
    }
} else {
    Write-Host '  firewall rule RC-MCP already present' -ForegroundColor Green
}

# 3. Per-agent: verify it's actually listening (port-bound, not just
#    process-alive — the zombie case). If a stale process owns the
#    CommandLine but no listener exists, taskkill /F it before relaunch.
function Ensure-Agent {
    param($name, $port, $task)

    $script = Join-Path 'C:\RC-Agent' $name

    # For agents that bind a port, the listener is the source of truth.
    $listenerOk = $false
    if ($port) {
        $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
        if ($conn) { $listenerOk = $true }
    }

    # Find any python process whose command line mentions the script.
    $procs = Get-CimInstance Win32_Process -Filter "Name='py.exe' OR Name='python.exe' OR Name='pythonw.exe'" |
             Where-Object { $_.CommandLine -like "*$name*" }

    if ($port -and -not $listenerOk -and $procs) {
        # Zombie: process exists but no listener. Kill before restart.
        foreach ($p in $procs) {
            Write-Host "  $name`: zombie PID $($p.ProcessId) (no listener), killing" -ForegroundColor Yellow
            taskkill /F /PID $p.ProcessId 2>&1 | Out-Null
        }
        $procs = $null
    }

    if ($procs) {
        Write-Host "  $name`: running (PID $($procs[0].ProcessId))" -ForegroundColor Green
        return
    }

    if (-not (Test-Path $script)) {
        Write-Host "  $name`: SCRIPT MISSING at $script" -ForegroundColor Red
        return
    }
    Start-Process -WindowStyle Hidden py -ArgumentList $script
    Write-Host "  $name`: started" -ForegroundColor Green

    # If a port is expected, give it 3s to bind and verify.
    if ($port) {
        Start-Sleep -Seconds 3
        $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
        if ($conn) {
            Write-Host "    bound :$port" -ForegroundColor Green
        } else {
            Write-Host "    WARNING: did not bind :$port within 3s" -ForegroundColor Red
        }
    }
}

foreach ($a in $AGENTS) {
    Ensure-Agent -name $a.name -port $a.port -task $a.task
}

# 4. Persistence — install scheduled tasks at logon if missing.
#    Wildcard-prefix match so we don't create a stray RC-ScreenAgent
#    alongside an existing variant set (e.g. RC-ScreenAgent-League,
#    RC-ScreenAgent-Minimap, RC-ScreenAgent-UI). Same protection covers
#    any future agent that grows variant tasks.
# Use absolute python.exe path — 'py' launcher is not resolvable in
# task-scheduler's restricted PATH (same fix as RC-PatchRefresh on Legion).
$pyExe = "C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe"
if (-not (Test-Path $pyExe)) {
    # Fallback: find any python.exe in standard AppData install locations
    $found = Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\*\python.exe" -ErrorAction SilentlyContinue |
             Sort-Object FullName -Descending | Select-Object -First 1
    if ($found) { $pyExe = $found.FullName }
}

foreach ($a in $AGENTS) {
    $existing = Get-ScheduledTask -TaskName "$($a.task)*" -ErrorAction SilentlyContinue
    if ($existing) {
        # Already covered (exact or variant). Nothing to do.
        continue
    }
    $tr = "`"$pyExe`" C:\RC-Agent\$($a.name)"
    schtasks /Create /TN $a.task /SC ONLOGON /RL HIGHEST /F /TR $tr 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  scheduled task $($a.task) installed" -ForegroundColor Green
    } else {
        Write-Host "  scheduled task $($a.task) install failed" -ForegroundColor Red
    }
}

# 5. Logon-trigger scheduled task — auto-runs THIS script after every
#    user logon so a Game-PC reboot self-restores agents + Claude session
#    without a manual shortcut click. Idempotent: only installs if absent.
$bootTaskName = 'RC-GamePCBoot'
$bootTask = Get-ScheduledTask -TaskName $bootTaskName -ErrorAction SilentlyContinue
if (-not $bootTask) {
    $tr = "powershell.exe -ExecutionPolicy Bypass -WindowStyle Hidden -File C:\RC-Agent\gamepc_boot.ps1"
    schtasks /Create /TN $bootTaskName /SC ONLOGON /RL HIGHEST /F /TR $tr 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  scheduled task $bootTaskName installed (logon trigger)" -ForegroundColor Green
    } else {
        Write-Host "  scheduled task $bootTaskName install failed" -ForegroundColor Red
    }
} else {
    Write-Host "  scheduled task $bootTaskName already present" -ForegroundColor Green
}

# 6. Bridge daemon — zero-cost sentinel that only invokes Claude when there
#    are pending bridge tasks. Replaces the old "/loop 1m /process-bridge-tasks"
#    terminal window. Registered as a proper scheduled task (pythonw.exe, no
#    console window); self-restarts on failure.
$pyW = "C:\Users\Administrator\AppData\Local\Programs\Python\Python314\pythonw.exe"
$daemonScript = Join-Path $dest 'gamepc_bridge_daemon.py'
$daemonTask = Get-ScheduledTask -TaskName 'RC-BridgeDaemon' -ErrorAction SilentlyContinue
if (-not $daemonTask) {
    if (Test-Path $daemonScript) {
        $action   = New-ScheduledTaskAction -Execute $pyW -Argument $daemonScript
        $trigger  = New-ScheduledTaskTrigger -AtLogOn -User 'Administrator'
        $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew `
                        -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
                        -ExecutionTimeLimit ([TimeSpan]::Zero)
        $principal = New-ScheduledTaskPrincipal -UserId 'Administrator' `
                        -LogonType Interactive -RunLevel Highest
        Register-ScheduledTask -TaskName 'RC-BridgeDaemon' -Action $action `
            -Trigger $trigger -Settings $settings -Principal $principal `
            -Description 'Zero-cost bridge sentinel: polls Legion /api/bridge every 30s; invokes claude --print /process-bridge-tasks only when tasks are pending.' `
            -Force | Out-Null
        Write-Host '  RC-BridgeDaemon task installed' -ForegroundColor Green
    } else {
        Write-Host '  gamepc_bridge_daemon.py missing; skipping daemon install' -ForegroundColor Yellow
    }
} else {
    Write-Host '  RC-BridgeDaemon task already present' -ForegroundColor Green
}
# Ensure it's running right now (idempotent — IgnoreNew if already active)
$daemonTask = Get-ScheduledTask -TaskName 'RC-BridgeDaemon' -ErrorAction SilentlyContinue
if ($daemonTask -and $daemonTask.State -ne 'Running') {
    Start-ScheduledTask -TaskName 'RC-BridgeDaemon'
    Write-Host '  RC-BridgeDaemon started' -ForegroundColor Green
} elseif ($daemonTask) {
    Write-Host '  RC-BridgeDaemon already running' -ForegroundColor Green
}

Write-Host ''
Write-Host '=== ready ===' -ForegroundColor Cyan
Write-Host ''

# 7. Launch the visible Game-PC Claude session (idempotent — script
#    checks for an existing "Game-PC bridge" window and no-ops if found).
$claudeLauncher = Join-Path $dest 'start_gamepc_claude.ps1'
if (Test-Path $claudeLauncher) {
    Write-Host 'Launching Game-PC bridge Claude...' -ForegroundColor Cyan
    try {
        & $claudeLauncher
    } catch {
        Write-Host "  Claude launch warning: $($_.Exception.Message)" -ForegroundColor Yellow
    }
} else {
    Write-Host '  start_gamepc_claude.ps1 missing — skipping Claude launch' -ForegroundColor Yellow
}

Write-Host ''
Write-Host '(this window auto-closes in 15s)' -ForegroundColor DarkGray

# Auto-close: 15s is enough to read the output; Claude window stays open.
Start-Sleep -Seconds 15
[Environment]::Exit(0)
