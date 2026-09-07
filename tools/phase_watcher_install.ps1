# phase_watcher_install.ps1 -- Legion-local scheduled-task installer.
#
# Item 207 LCU phase-capture watcher. Run on Legion:
#
#   .\phase_watcher_install.ps1
#
# What it does (idempotent -- safe to re-run):
#   1. Pulls latest phase_watcher.py from Legion's /agent/.
#   2. Writes to C:\RC-Agent\phase_watcher.py.
#   3. Ensures sidecar dir C:\RC-Agent\event_captures exists.
#   4. Creates scheduled task RC-PhaseWatcher with at-logon trigger.
#   5. Starts the task immediately + verifies the process is alive.
#
# Prereqs (one-time):
#   py -m pip install bettercam websocket-client
#
# Operator scope-fork (item 207 session):
#   Q1 capture target = BOTH monitors per event
#   Q2 debounce = per (topic, sub_phase, queue_id) per gameflow cycle
#   Q3 frame format = JPEG q75
#   Q4 Cherry urgency = standard debounce
#   Q5 bridge envelope = YES emit kind=ui_capture
#
# These are baked into the watcher source; the installer carries no
# config flags. Re-deploy via this script after watcher source changes.

param(
    [string]$InstallDir = "C:\RC-Agent",
    [string]$SidecarDir = "C:\RC-Agent\event_captures",
    [string]$LegionAgentBase = "https://legion-rc:8888/agent",
    [string]$TaskName = "RC-PhaseWatcher",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

function Write-Step([string]$msg) {
    Write-Host "==> $msg" -ForegroundColor Cyan
}
function Write-Ok([string]$msg) {
    Write-Host "    OK $msg" -ForegroundColor Green
}
function Write-Warn([string]$msg) {
    Write-Host "    !! $msg" -ForegroundColor Yellow
}

# 1. Ensure dirs exist

Write-Step "Ensuring install + sidecar dirs"
foreach ($d in @($InstallDir, $SidecarDir)) {
    if (-not (Test-Path $d)) {
        if ($DryRun) {
            Write-Warn "DryRun: would create $d"
        } else {
            New-Item -ItemType Directory -Force -Path $d | Out-Null
            Write-Ok "Created $d"
        }
    } else {
        Write-Ok "$d already exists"
    }
}

# 2. Pull watcher source from Legion

$WatcherPath = Join-Path $InstallDir "phase_watcher.py"
$Url = "$LegionAgentBase/phase_watcher.py"
Write-Step "Pulling watcher source from $Url"
if ($DryRun) {
    Write-Warn "DryRun: would download to $WatcherPath"
} else {
    try {
        Invoke-WebRequest -UseBasicParsing -Uri $Url `
            -OutFile "$WatcherPath.new" -TimeoutSec 30
        if ((Get-Item "$WatcherPath.new").Length -lt 1000) {
            throw "downloaded file too small (<1KB); abort"
        }
        Move-Item -Force -Path "$WatcherPath.new" -Destination $WatcherPath
        Write-Ok "Wrote $WatcherPath"
    } catch {
        Write-Warn "download failed: $($_.Exception.Message)"
        Write-Warn "Falling back to local copy if present"
        if (-not (Test-Path $WatcherPath)) {
            Write-Error "no local copy at $WatcherPath; cannot proceed"
        }
    }
}

# 3. Stop any running watcher process

Write-Step "Killing any running watcher python pid"
try {
    $existing = Get-CimInstance Win32_Process -Filter "Name='python.exe'" `
        -ErrorAction SilentlyContinue | Where-Object {
            $_.CommandLine -like "*phase_watcher*"
        }
    if ($existing) {
        foreach ($p in $existing) {
            if ($DryRun) {
                Write-Warn "DryRun: would taskkill /F /PID $($p.ProcessId)"
            } else {
                & taskkill /F /PID $p.ProcessId | Out-Null
                Write-Ok "killed pid $($p.ProcessId)"
            }
        }
    } else {
        Write-Ok "no existing watcher pid"
    }
} catch {
    Write-Warn "process probe failed: $($_.Exception.Message)"
}

# 4. Register scheduled task at-logon

Write-Step "Registering scheduled task $TaskName"
$Python = "$env:LOCALAPPDATA\Programs\Python\Python314\pythonw.exe"
if (-not (Test-Path $Python)) {
    # Fallback to py launcher.
    $Python = (Get-Command pythonw -ErrorAction SilentlyContinue).Source
    if (-not $Python) {
        $Python = (Get-Command python -ErrorAction SilentlyContinue).Source
    }
}

$Args = "`"$WatcherPath`" --sidecar-dir `"$SidecarDir`""
$Action = New-ScheduledTaskAction -Execute $Python -Argument $Args
$Trigger = New-ScheduledTaskTrigger -AtLogOn
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME `
    -LogonType Interactive -RunLevel Highest
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -RestartInterval (New-TimeSpan -Minutes 1) -RestartCount 3

if ($DryRun) {
    Write-Warn "DryRun: would register task $TaskName"
} else {
    try {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false `
            -ErrorAction SilentlyContinue
    } catch {}
    Register-ScheduledTask -TaskName $TaskName -Action $Action `
        -Trigger $Trigger -Principal $Principal -Settings $Settings `
        -Description "RC LCU phase-capture watcher (item 207)" | Out-Null
    Write-Ok "Registered $TaskName"
}

# 5. Start + verify

Write-Step "Starting + verifying"
if ($DryRun) {
    Write-Warn "DryRun: would Start-ScheduledTask $TaskName"
} else {
    Start-ScheduledTask -TaskName $TaskName
    Start-Sleep -Seconds 3
    $info = Get-ScheduledTaskInfo -TaskName $TaskName
    Write-Ok ("LastTaskResult={0} NextRunTime={1}" -f `
        $info.LastTaskResult, $info.NextRunTime)
    $alive = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" `
        -ErrorAction SilentlyContinue | Where-Object {
            $_.CommandLine -like "*phase_watcher*"
        }
    if ($alive) {
        Write-Ok ("pid={0} alive" -f $alive.ProcessId)
    } else {
        Write-Warn "no live pythonw.exe matching watcher; check Task Scheduler log"
    }
}

Write-Step "Done"
Write-Host "Sidecar dir: $SidecarDir" -ForegroundColor Gray
Write-Host "Watcher log: pythonw.exe is silent; check task scheduler" -ForegroundColor Gray
Write-Host "To uninstall: Unregister-ScheduledTask -TaskName $TaskName -Confirm:`$false" -ForegroundColor Gray
