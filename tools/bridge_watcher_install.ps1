# bridge_watcher_install.ps1 -- idempotent installer for the Peer peer.
#
# Phase 1 per BRIDGE_WATCHER_PLAN.md §10. Run on Peer:
#
#   iex (iwr -UseBasicParsing https://legion-rc:8888/agent/bridge_watcher_install.ps1).Content
#
# Or with explicit args:
#
#   .\bridge_watcher_install.ps1 -Node peer -BridgeUrl https://127.0.0.1:8888/api/bridge -InstallDir C:\path\to\peer-vip\tools
#   .\bridge_watcher_install.ps1 -Node peer -EnableLanes read,ops
#
# What it does (idempotent -- safe to re-run):
#   1. Detects which node from $env:COMPUTERNAME if -Node not passed.
#   2. Pulls latest bridge_watcher.py + bridge_watcher_classify.py +
#      bridge_watcher_config.json + bridge_watcher_hook.ps1 from Legion's /agent/.
#   3. Selects per-node defaults (install dir, bridge URL, target).
#   4. Creates scheduled task RC-BridgeWatcher-<Node> with appropriate args.
#   5. Optionally registers UserPromptSubmit hook in ~/.claude/settings.json
#      (with -InstallHook flag; default off so existing hook config isn't
#      clobbered without operator consent).
#   6. Verifies first poll succeeds + heartbeat written within 30s.
#   7. Prints follow-up steps (cancel /loop cron in interactive Claude session).

param(
    [ValidateSet("peer")]
    [string]$Node = "",
    [string]$InstallDir = "",
    [string]$BridgeUrl = "",
    [string]$LegionAgentBase = "https://legion-rc:8888/agent",
    [ValidateSet("", "read", "ops", "read,ops", "ops,read")]
    [string]$EnableLanes = "",
    [switch]$InstallHook,
    [switch]$DryRun,
    [switch]$Force
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

# ── 1. Detect node ──────────────────────────────────────────────────────

if (-not $Node) {
    $hn = $env:COMPUTERNAME.ToLower()
    if ($hn -like "*peer-host*" -or $hn -like "*peer*") { $Node = "peer" }
    else {
        Write-Error "could not auto-detect node from COMPUTERNAME=$hn -- pass -Node peer"
    }
}
Write-Step "Node = $Node"

# ── 2. Per-node defaults ────────────────────────────────────────────────

$NodeDefaults = @{
    "peer" = @{
        InstallDir = (Join-Path (Get-Location) "tools")
        BridgeUrl  = "https://127.0.0.1:8888/api/bridge"
        TaskName   = "RC-BridgeWatcher-Peer"
    }
}
$d = $NodeDefaults[$Node]
if (-not $InstallDir) { $InstallDir = $d.InstallDir }
if (-not $BridgeUrl)  { $BridgeUrl  = $d.BridgeUrl }
$TaskName = $d.TaskName

Write-Step "InstallDir = $InstallDir"
Write-Step "BridgeUrl  = $BridgeUrl"
Write-Step "TaskName   = $TaskName"
Write-Step "EnableLanes = $(if ($EnableLanes) { $EnableLanes } else { '(none; classifier never returns auto-* lanes)' })"

# ── 3. Pull files from Legion ──────────────────────────────────────────

$Files = @(
    "bridge_watcher.py",
    "bridge_watcher_classify.py",
    "bridge_watcher_config.json",
    "bridge_watcher_hook.ps1"
)

if (-not (Test-Path -LiteralPath $InstallDir)) {
    Write-Step "Creating $InstallDir"
    if (-not $DryRun) { New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null }
}

# Cert bypass: legion serves a mkcert-signed cert that Peer may not
# have trusted (rc_rootCA.pem is in /agent/ but not auto-installed). PS5.1
# and PS6+ require different bypass mechanisms - set both.
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12
[System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }

# PS6+ Invoke-WebRequest accepts -SkipCertificateCheck; PS5.1 uses the
# global callback above. Build IWR splat per-version to keep one code path.
$IwrCommonArgs = @{ UseBasicParsing = $true }
if ($PSVersionTable.PSVersion.Major -ge 6) {
    $IwrCommonArgs["SkipCertificateCheck"] = $true
}

foreach ($f in $Files) {
    $url  = "$LegionAgentBase/$f"
    $dest = [System.IO.Path]::Combine($InstallDir, $f)
    Write-Step "Pull $f"
    if ($DryRun) { Write-Host "    [dry-run] would fetch $url -> $dest"; continue }
    try {
        Invoke-WebRequest -Uri $url -OutFile $dest @IwrCommonArgs
        $sz = (Get-Item -LiteralPath $dest).Length
        Write-Ok "$f  $sz bytes"
    } catch {
        Write-Error "failed to pull ${f}: $_"
    }
}

# ── 4. Locate Python ────────────────────────────────────────────────────

$Pythonw = ""
$Candidates = @(
    "$env:LOCALAPPDATA\Programs\Python\Python314\pythonw.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python313\pythonw.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python312\pythonw.exe",
    "C:\Python314\pythonw.exe",
    "C:\Python313\pythonw.exe"
)
foreach ($c in $Candidates) {
    if (Test-Path -LiteralPath $c) { $Pythonw = $c; break }
}
if (-not $Pythonw) {
    # Fall back to "py.exe -w" via where.exe
    $py = (Get-Command py.exe -ErrorAction SilentlyContinue).Source
    if ($py) {
        Write-Warn "no pythonw.exe found; using $py instead -- task will spawn a console window"
        $Pythonw = $py
    } else {
        Write-Error "could not locate pythonw.exe or py.exe -- install Python or pass via -Pythonw"
    }
}
Write-Step "Pythonw = $Pythonw"

# ── 5. Cancel any existing watcher scheduled task before re-install ─────

$prevEAP = $ErrorActionPreference
$ErrorActionPreference = "SilentlyContinue"
$null = & schtasks /Query /TN $TaskName 2>&1
$existed = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = $prevEAP

if ($existed) {
    Write-Step "Existing $TaskName found; will stop + replace"
    if (-not $DryRun) {
        $prevEAP2 = $ErrorActionPreference
        $ErrorActionPreference = "SilentlyContinue"
        $null = & schtasks /End    /TN $TaskName    2>&1
        $null = & schtasks /Delete /TN $TaskName /F 2>&1
        $ErrorActionPreference = $prevEAP2
    }
}

# ── 6. Create scheduled task XML ────────────────────────────────────────

$WatcherPath = [System.IO.Path]::Combine($InstallDir, "bridge_watcher.py")
$LanesArg = ""
if ($EnableLanes) {
    $LanesArg = " --enable-auto-action-lanes $EnableLanes"
}
$XmlContent = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Date>$(Get-Date -Format "yyyy-MM-ddTHH:mm:ss")</Date>
    <Description>Cross-Claude bridge watcher daemon (Phase 1). See https://legion-rc:8888/agent/BRIDGE_WATCHER_PLAN.md</Description>
  </RegistrationInfo>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <DisallowStartIfOnBatteries>true</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>true</StopIfGoingOnBatteries>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <RestartOnFailure>
      <Interval>PT1M</Interval>
      <Count>3</Count>
    </RestartOnFailure>
  </Settings>
  <Triggers>
    <LogonTrigger>
      <StartBoundary>$(Get-Date -Format "yyyy-MM-ddTHH:mm:ss")</StartBoundary>
    </LogonTrigger>
  </Triggers>
  <Actions Context="Author">
    <Exec>
      <Command>"$Pythonw"</Command>
      <Arguments>"$WatcherPath" --node $Node --bridge-url $BridgeUrl --data-dir "$InstallDir" --log-dir "$InstallDir\logs" --poll 15$LanesArg</Arguments>
    </Exec>
  </Actions>
</Task>
"@

$XmlPath = Join-Path $env:TEMP "$TaskName.xml"
# schtasks /Create /XML demands UTF-16 LE w/ BOM
$bytes = [System.Text.Encoding]::Unicode.GetPreamble() + [System.Text.Encoding]::Unicode.GetBytes($XmlContent)
if (-not $DryRun) {
    [System.IO.File]::WriteAllBytes($XmlPath, $bytes)
}

Write-Step "Creating scheduled task $TaskName"
if ($DryRun) {
    Write-Host "    [dry-run] would: schtasks /Create /TN $TaskName /XML $XmlPath /F"
} else {
    $createOut = & schtasks /Create /TN $TaskName /XML $XmlPath /F 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Error "schtasks /Create failed: $createOut"
    }
    Write-Ok "$TaskName registered"
}

# ── 7. Start the task ───────────────────────────────────────────────────

if (-not $DryRun) {
    Write-Step "Starting $TaskName"
    $runOut = & schtasks /Run /TN $TaskName 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "schtasks /Run returned nonzero: $runOut"
    } else {
        Write-Ok "$TaskName started"
    }
}

# ── 8. Verify heartbeat within 30s ──────────────────────────────────────

if (-not $DryRun) {
    $HealthFile = [System.IO.Path]::Combine($InstallDir, "bridge_watcher_health.json")
    Write-Step "Waiting up to 30s for heartbeat at $HealthFile"
    $deadline = (Get-Date).AddSeconds(30)
    $found = $false
    while ((Get-Date) -lt $deadline) {
        if (Test-Path -LiteralPath $HealthFile) {
            try {
                $h = Get-Content -LiteralPath $HealthFile -Raw -Encoding UTF8 | ConvertFrom-Json
                if ($h.alive -and $h.last_poll_ok) {
                    Write-Ok "heartbeat OK -- pid=$($h.pid) queue_depth=$($h.queue_depth)"
                    $found = $true
                    break
                }
            } catch {
                # partial write; retry
            }
        }
        Start-Sleep -Milliseconds 500
    }
    if (-not $found) {
        Write-Warn "no healthy heartbeat after 30s -- check $InstallDir\logs\bridge_watcher_*.log"
    }
}

# ── 9. UserPromptSubmit hook (opt-in) ───────────────────────────────────

if ($InstallHook) {
    Write-Step "Registering UserPromptSubmit hook in ~/.claude/settings.json"
    $SettingsDir  = Join-Path $env:USERPROFILE ".claude"
    $SettingsPath = Join-Path $SettingsDir "settings.json"
    if (-not (Test-Path -LiteralPath $SettingsDir)) {
        New-Item -ItemType Directory -Force -Path $SettingsDir | Out-Null
    }
    $current = @{}
    if (Test-Path -LiteralPath $SettingsPath) {
        try {
            $current = Get-Content -LiteralPath $SettingsPath -Raw -Encoding UTF8 | ConvertFrom-Json -AsHashtable
        } catch {
            Write-Warn "settings.json unreadable; backing up to settings.json.bak before overwrite"
            Copy-Item -LiteralPath $SettingsPath -Destination "$SettingsPath.bak" -Force
            $current = @{}
        }
    }
    if (-not $current.hooks) { $current.hooks = @{} }
    if (-not $current.hooks.UserPromptSubmit) { $current.hooks.UserPromptSubmit = @() }

    $hookPath = [System.IO.Path]::Combine($InstallDir, 'bridge_watcher_hook.ps1')
    $hookCmd  = "powershell -NoProfile -ExecutionPolicy Bypass -File `"$hookPath`""

    # Per Peer 2026-05-03 install report: Claude Code's settings.json schema
    # requires UserPromptSubmit entries to be wrapped in {hooks: [{type, command, timeout}]}.
    # Bare {command: ...} entries pass JSON validation but the harness ignores
    # them silently. The wrapped shape matches the existing bridge_fetch hook
    # entry on Peer side.
    $alreadyPresent = $false
    foreach ($entry in $current.hooks.UserPromptSubmit) {
        $entryHooks = $entry.hooks
        if ($entryHooks) {
            foreach ($eh in $entryHooks) {
                if ($eh.command -eq $hookCmd) { $alreadyPresent = $true; break }
            }
            if ($alreadyPresent) { break }
        }
        # Tolerate the legacy bare-command shape from earlier installer versions
        if ($entry.command -eq $hookCmd) { $alreadyPresent = $true; break }
    }
    if ($alreadyPresent) {
        Write-Ok "hook already present in settings.json"
    } else {
        $newEntry = @{
            hooks = @(
                @{
                    type    = "command"
                    command = $hookCmd
                    timeout = 2
                }
            )
        }
        if ($DryRun) {
            Write-Host "    [dry-run] would append to UserPromptSubmit:"
            Write-Host ($newEntry | ConvertTo-Json -Depth 5)
        } else {
            $current.hooks.UserPromptSubmit += $newEntry
            $current | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $SettingsPath -Encoding UTF8
            Write-Ok "hook added to settings.json (wrapped {hooks: [{type, command, timeout}]} shape)"
        }
    }
} else {
    Write-Warn "UserPromptSubmit hook NOT installed (pass -InstallHook to install)"
    Write-Host ""
    Write-Host "    To install manually, add to ~/.claude/settings.json:"
    Write-Host ""
    Write-Host '      {' -ForegroundColor DarkGray
    Write-Host '        "hooks": {' -ForegroundColor DarkGray
    Write-Host '          "UserPromptSubmit": [' -ForegroundColor DarkGray
    Write-Host '            {' -ForegroundColor DarkGray
    Write-Host '              "hooks": [' -ForegroundColor DarkGray
    $exampleHookPath = [System.IO.Path]::Combine($InstallDir, 'bridge_watcher_hook.ps1')
    Write-Host '                {' -ForegroundColor DarkGray
    Write-Host '                  "type": "command",' -ForegroundColor DarkGray
    Write-Host "                  ""command"": ""powershell -NoProfile -ExecutionPolicy Bypass -File \""$exampleHookPath\""""," -ForegroundColor DarkGray
    Write-Host '                  "timeout": 2' -ForegroundColor DarkGray
    Write-Host '                }' -ForegroundColor DarkGray
    Write-Host '              ]' -ForegroundColor DarkGray
    Write-Host '            }' -ForegroundColor DarkGray
    Write-Host '          ]' -ForegroundColor DarkGray
    Write-Host '        }' -ForegroundColor DarkGray
    Write-Host '      }' -ForegroundColor DarkGray
}

# ── 10. Operator follow-ups ─────────────────────────────────────────────

Write-Host ""
Write-Step "DONE. Follow-ups for operator:"
Write-Host "  1. If your interactive Claude session has a /loop /process-bridge-tasks cron,"
Write-Host "     run CronList then CronDelete <id>. The watcher now owns the polling."
Write-Host "  2. If you didn't pass -InstallHook, add the snippet above to ~/.claude/settings.json"
Write-Host "     so unclaimed escalations surface in your prompt."
Write-Host "  3. Verify heartbeat: Get-Content '$InstallDir\bridge_watcher_health.json'"
Write-Host "  4. Stop with: schtasks /End /TN $TaskName ; schtasks /Delete /TN $TaskName /F"
Write-Host ""
exit 0
