param(
    [string]$ConfigPath = ""
)

$ErrorActionPreference = "SilentlyContinue"

function Write-Log {
    param([string]$Text)
    $stamp = (Get-Date).ToString("s")
    $line = "[$stamp] $Text"
    Write-Host $line
    # Also append to watchdog log
    $logPath = Join-Path $runtimeDir "logs\watchdog.log"
    Add-Content -Path $logPath -Value $line -ErrorAction SilentlyContinue
}

if ([string]::IsNullOrWhiteSpace($ConfigPath)) {
    $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $ConfigPath = Join-Path $ScriptDir "rc_config.json"
}

if (-not (Test-Path $ConfigPath)) {
    Write-Host "[$(Get-Date -Format 's')] Config not found: $ConfigPath"
    exit 1
}

$config = Get-Content -Raw -Path $ConfigPath | ConvertFrom-Json
$projectRoot = $config.project_root

# Always use pythonw.exe for hidden background processes
$pythonExe = "pythonw.exe"

$runtimeDir = $config.runtime_dir
if ([string]::IsNullOrWhiteSpace($runtimeDir)) {
    $runtimeDir = Join-Path $projectRoot "ops\runtime"
}
$logDir = Join-Path $runtimeDir "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$supervisorScript = Join-Path $projectRoot "ops\rc_supervisor.py"
$bridgeScript     = Join-Path $projectRoot "ops\rc_file_bridge.py"

Write-Log "Self-healing watchdog started (PID=$PID)"
Write-Log "Config: $ConfigPath"
Write-Log "Python: $pythonExe"

# League process names — watchdog exits if League closes (league_watcher handles restart)
$leagueNames = @("LeagueClient", "LeagueClientUx", "League of Legends")
$leagueGoneAt = $null
$leagueGraceSecs = 15

while ($true) {
    # Check for stop file
    $stopFile = Join-Path $runtimeDir "watchdog.stop"
    if (Test-Path $stopFile) {
        Write-Log "Stop file detected. Exiting watchdog."
        Remove-Item $stopFile -Force -ErrorAction SilentlyContinue
        break
    }

    # Check League presence — exit watchdog if League has been gone > grace period
    # (rc_league_watcher.ps1 will restart the whole stack when League reopens)
    $leagueUp = $false
    foreach ($name in $leagueNames) {
        if (Get-Process -Name $name -ErrorAction SilentlyContinue) { $leagueUp = $true; break }
    }
    if (-not $leagueUp) {
        if ($leagueGoneAt -eq $null) {
            $leagueGoneAt = Get-Date
            Write-Log "League not detected — grace period started (${leagueGraceSecs}s)"
        } elseif (((Get-Date) - $leagueGoneAt).TotalSeconds -ge $leagueGraceSecs) {
            Write-Log "League closed — watchdog exiting (league_watcher will handle restart)"
            break
        }
    } else {
        $leagueGoneAt = $null   # reset if League comes back
    }

    # Check supervisor
    $supervisor = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -like "*rc_supervisor.py*"
    } | Select-Object -First 1

    if (-not $supervisor) {
        Write-Log "Supervisor not running - starting rc_supervisor.py"
        Start-Process -FilePath $pythonExe `
            -ArgumentList @($supervisorScript, "--config", $ConfigPath) `
            -WorkingDirectory $projectRoot `
            -WindowStyle Hidden
        Start-Sleep -Seconds 2
    }

    # Check file bridge
    $bridge = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -like "*rc_file_bridge.py*"
    } | Select-Object -First 1

    if (-not $bridge) {
        Write-Log "File bridge not running - starting rc_file_bridge.py"
        Start-Process -FilePath $pythonExe `
            -ArgumentList @($bridgeScript, "--config", $ConfigPath) `
            -WorkingDirectory $projectRoot `
            -WindowStyle Hidden
        Start-Sleep -Seconds 1
    }

    Start-Sleep -Seconds 2
}

Write-Log "Watchdog exited cleanly."
