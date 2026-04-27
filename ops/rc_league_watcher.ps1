# ops\rc_league_watcher.ps1
#
# Lightweight always-on League presence watcher.
# Runs hidden at Windows startup. No interaction required.
#
# When LeagueClient.exe or League of Legends.exe is detected:
#   → Starts supervisor + file bridge (full Riot Commander stack)
#   → The supervisor owns the PID lock and starts the app
# When all League processes disappear:
#   → Cleanly stops the full stack
#
# Phase 0: Deprecated paths
#   watchdog.ps1              — replaced by rc_self_monitor inside rc_supervisor
#   run_self_healing_watchdog.ps1 — supervisor now owns self-healing directly
#   restart.bat / restart_clean.bat / start.bat — replaced by this watcher
#
# Install: run ops\install_startup.bat once to add this to Windows startup.

param(
    [string]$ConfigPath = ""
)

$ErrorActionPreference = "SilentlyContinue"

# ── Config ────────────────────────────────────────────────────────────────────
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if ([string]::IsNullOrWhiteSpace($ConfigPath)) {
    $ConfigPath = Join-Path $ScriptDir "rc_config.json"
}
$config      = Get-Content -Raw -Path $ConfigPath | ConvertFrom-Json
$projectRoot = $config.project_root
$runtimeDir  = if ($config.runtime_dir) { $config.runtime_dir } else { Join-Path $projectRoot "ops\runtime" }
$logDir      = Join-Path $runtimeDir "logs"
$logFile     = Join-Path $logDir "league_watcher.log"
$stopFile    = Join-Path $runtimeDir "watchdog.stop"
# Use python_exe from config — consistent with supervisor and bridge
$pythonExe   = if ($config.python_exe) { $config.python_exe } else { "pythonw.exe" }

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

# League process names to watch for (client OR game)
$leagueProcesses = @("LeagueClient", "LeagueClientUx", "League of Legends")

# Poll interval (seconds)
$pollInterval    = 4
# Grace period after League disappears before stopping (seconds)
# Prevents false stops during client restarts / patch updates
$gracePeriod     = 12

# ── Helpers ───────────────────────────────────────────────────────────────────
function Write-Log {
    param([string]$Text)
    $stamp = (Get-Date).ToString("s")
    $line  = "[$stamp] [watcher] $Text"
    Add-Content -Path $logFile -Value $line -ErrorAction SilentlyContinue
}

function League-Running {
    foreach ($name in $leagueProcesses) {
        if (Get-Process -Name $name -ErrorAction SilentlyContinue) { return $true }
    }
    return $false
}

function Stack-Running {
    $sup    = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
              Where-Object { $_.CommandLine -like "*rc_supervisor.py*" }
    $bridge = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
              Where-Object { $_.CommandLine -like "*rc_file_bridge.py*" }
    return ($sup -or $bridge)
}

function Start-Stack {
    Write-Log "League detected — starting Riot Commander stack"

    # Clear stale stop file so watchdog doesn't immediately exit
    Remove-Item $stopFile -Force -ErrorAction SilentlyContinue

    # Ensure runtime dirs exist
    $dirs = @(
        "deploy_requests","deploy_results","bridge_requests","bridge_results",
        "bridge_results\images","logs","supervisor_requests",
        "control\commands","control\results"
    )
    foreach ($d in $dirs) {
        New-Item -ItemType Directory -Force -Path (Join-Path $runtimeDir $d) | Out-Null
    }

    $supervisorScript = Join-Path $projectRoot "ops\rc_supervisor.py"
    $bridgeScript     = Join-Path $projectRoot "ops\rc_file_bridge.py"
    $pidLockFile      = Join-Path $runtimeDir  "supervisor.pid"

    # ── Kill deprecated watchdog processes first ──────────────────────────
    # watchdog.ps1 (old) and run_self_healing_watchdog.ps1 must not run
    # alongside the new supervisor stack — they create duplicate restarts.
    $legacyWatchdogs = @(
        "*\\watchdog.ps1*",
        "*run_self_healing_watchdog.ps1*"
    )
    foreach ($pattern in $legacyWatchdogs) {
        $legacyProcs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
            $_.CommandLine -like $pattern
        }
        foreach ($p in $legacyProcs) {
            Write-Log "Killing legacy watchdog PID $($p.ProcessId): $($p.Name)"
            Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
        }
    }

    # ── Check PID lock — don't start supervisor if one is already running ─
    if (Test-Path $pidLockFile) {
        $existingPid = $null
        try {
            $rawContent = Get-Content $pidLockFile -Raw -ErrorAction Stop
            $rawContent = $rawContent.Trim()
            # Support both legacy plain-integer format and Phase 0 JSON format
            if ($rawContent.StartsWith('{')) {
                $lockData    = $rawContent | ConvertFrom-Json
                $existingPid = [int]$lockData.pid
            } else {
                $existingPid = [int]$rawContent
            }
        } catch {
            Write-Log "PID lock parse error: $_  (treating as stale)"
            Remove-Item $pidLockFile -Force -ErrorAction SilentlyContinue
            $existingPid = $null
        }
        if ($existingPid) {
            $existingProc = Get-Process -Id $existingPid -ErrorAction SilentlyContinue
            if ($existingProc) {
                Write-Log "Supervisor already running (PID=$existingPid) — skipping start"
                return
            }
        }
        Remove-Item $pidLockFile -Force -ErrorAction SilentlyContinue
    }

        # Start supervisor (owns PID lock + SelfMonitor as threads)
    Start-Process -FilePath $pythonExe `
        -ArgumentList @($supervisorScript, "--config", $ConfigPath) `
        -WorkingDirectory $projectRoot `
        -WindowStyle Hidden
    Start-Sleep -Seconds 1

    # Start file bridge — skip if a healthy instance is already running
    $bridgePidFile = Join-Path $runtimeDir "bridge.pid"
    $bridgeAlreadyRunning = $false
    if (Test-Path $bridgePidFile) {
        try {
            $bRaw = (Get-Content $bridgePidFile -Raw).Trim()
            $bPid = if ($bRaw.StartsWith('{')) { [int]($bRaw | ConvertFrom-Json).pid } else { [int]$bRaw }
            if ($bPid -and (Get-Process -Id $bPid -ErrorAction SilentlyContinue)) {
                Write-Log "Bridge already running (PID=$bPid) — skipping start"
                $bridgeAlreadyRunning = $true
            }
        } catch {}
    }
    if (-not $bridgeAlreadyRunning) {
        Start-Process -FilePath $pythonExe `
            -ArgumentList @($bridgeScript, "--config", $ConfigPath) `
            -WorkingDirectory $projectRoot `
            -WindowStyle Hidden
    }

    Write-Log "Stack started (supervisor [+self_monitor] + bridge)"
}

function Stop-Stack {
    Write-Log "League closed — stopping Riot Commander stack"

    # Ask supervisor to shut down cleanly via its request dir.
    # Supervisor will stop the app by owned PID and release the lock.
    $supReqDir = Join-Path $runtimeDir "supervisor_requests"
    if (Test-Path $supReqDir) {
        $shutdownReq = @{ type = "shutdown"; reason = "league_watcher_stop"; at = (Get-Date -Format o) }
        $shutdownReq | ConvertTo-Json | Set-Content -Path (Join-Path $supReqDir "watcher-shutdown-$(Get-Date -Format yyyyMMddHHmmss).json") -Encoding UTF8 -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 3
    }

    # If supervisor is still alive after the grace period, kill it by its own PID only.
    $pidLockFile = Join-Path $runtimeDir "supervisor.pid"
    if (Test-Path $pidLockFile) {
        $supervisorPid = $null
        try {
            $raw = (Get-Content $pidLockFile -Raw).Trim()
            if ($raw.StartsWith('{')) { $supervisorPid = [int]($raw | ConvertFrom-Json).pid }
            else                      { $supervisorPid = [int]$raw }
        } catch {}
        if ($supervisorPid) {
            $proc = Get-Process -Id $supervisorPid -ErrorAction SilentlyContinue
            if ($proc) {
                Write-Log "Killing supervisor PID=$supervisorPid by owned PID"
                Stop-Process -Id $supervisorPid -Force -ErrorAction SilentlyContinue
            }
        }
        Remove-Item $pidLockFile -Force -ErrorAction SilentlyContinue
    }

    # Kill file bridge by its own PID file if present, otherwise by command-line match
    $bridgePidFile = Join-Path $runtimeDir "bridge.pid"
    if (Test-Path $bridgePidFile) {
        try {
            $raw = (Get-Content $bridgePidFile -Raw).Trim()
            $bridgePid = if ($raw.StartsWith('{')) { [int]($raw | ConvertFrom-Json).pid } else { [int]$raw }
            Stop-Process -Id $bridgePid -Force -ErrorAction SilentlyContinue
            Write-Log "Bridge stopped by owned PID=$bridgePid"
        } catch {}
        Remove-Item $bridgePidFile -Force -ErrorAction SilentlyContinue
    } else {
        # Fallback: rc_file_bridge.py is specific enough to be safe
        Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
            $_.CommandLine -like "*rc_file_bridge.py*"
        } | ForEach-Object {
            Write-Log "Bridge fallback-kill PID=$($_.ProcessId)"
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }
    }

    Write-Log "Stack stopped"
}

# ── Main loop ─────────────────────────────────────────────────────────────────
Write-Log "League watcher started (PID=$PID) — polling every ${pollInterval}s"
Write-Log "Watching for: $($leagueProcesses -join ', ')"

$stackRunning    = $false
$leagueGoneTime  = $null   # timestamp when League first disappeared

while ($true) {
    $leagueUp = League-Running

    if ($leagueUp) {
        # Reset grace period timer whenever League is seen
        $leagueGoneTime = $null

        if (-not $stackRunning) {
            Start-Stack
            $stackRunning = $true
            Start-Sleep -Seconds 3  # brief pause after start
        }
    }
    else {
        # League not detected
        if ($stackRunning) {
            if ($leagueGoneTime -eq $null) {
                # First poll where League is gone — start grace period
                $leagueGoneTime = Get-Date
                Write-Log "League not detected — grace period started (${gracePeriod}s)"
            }
            elseif (((Get-Date) - $leagueGoneTime).TotalSeconds -ge $gracePeriod) {
                # Grace period expired — stop the stack
                Stop-Stack
                $stackRunning   = $false
                $leagueGoneTime = $null
            }
        }
        # If stack wasn't running and League isn't up: do nothing, keep waiting
    }

    Start-Sleep -Seconds $pollInterval
}
