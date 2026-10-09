# Phase 3 installer for Legion-PC (§11.12).
# Idempotent: safe to re-run. Requires an elevated shell.
#
# What this does:
#   1. Inbound firewall rules for the LAN subnet only:
#       - RC-Phase3-WebUI    : TCP 8890
#       - RC-Phase3-WSIngest : TCP 8891
#   2. Task Scheduler entry "RC-Phase3-Supervisor":
#       - Triggers at startup, 30s delay
#       - Runs pythonw.exe -m agents.supervisor in the repo root
#       - Highest privileges as the installing account
#       - Restart 5x on failure, 1 min interval

$ErrorActionPreference = 'Stop'

$ProjectRoot  = Split-Path -Parent $PSScriptRoot
$PythonExe    = "$env:LOCALAPPDATA\Programs\Python\Python314\pythonw.exe"
$TaskName     = 'RC-Phase3-Supervisor'

# The LAN subnet is per-host config (gitignored ops\local_hosts.json
# `lan_subnet`, template ops\local_hosts.example.json), never a tracked literal.
$LanSubnet    = ''
$hostsFile    = Join-Path $ProjectRoot 'ops\local_hosts.json'
if (Test-Path $hostsFile) {
    $LanSubnet = [string](Get-Content -Raw -Path $hostsFile | ConvertFrom-Json).lan_subnet
}
if (-not $LanSubnet.Trim()) {
    Write-Host 'set lan_subnet in ops\local_hosts.json first (no firewall rule without it)' -ForegroundColor Red
    exit 1
}

function Ensure-FirewallRule {
    param(
        [string]$Name,
        [int]$Port,
        [string]$Description
    )
    $existing = Get-NetFirewallRule -DisplayName $Name -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Host "firewall rule already exists: $Name (port $Port) -- updating"
        Remove-NetFirewallRule -DisplayName $Name -ErrorAction SilentlyContinue
    }
    New-NetFirewallRule `
        -DisplayName $Name `
        -Direction Inbound `
        -Action Allow `
        -Protocol TCP `
        -LocalPort $Port `
        -RemoteAddress $LanSubnet `
        -Profile Any `
        -Description $Description | Out-Null
    Write-Host "firewall rule set: $Name TCP/$Port from $LanSubnet"
}

Write-Host '=== Phase 3 installer ==='
Write-Host "ProjectRoot: $ProjectRoot"
Write-Host "Python:      $PythonExe"
Write-Host "LAN:         $LanSubnet"
Write-Host ''

# --- 1. firewall --------------------------------------------------------
Ensure-FirewallRule -Name 'RC-Phase3-WebUI'    -Port 8890 -Description 'Riot Commander Phase 3 web UI'
Ensure-FirewallRule -Name 'RC-Phase3-WSIngest' -Port 8891 -Description 'Riot Commander Phase 3 WebSocket relay'

# --- 2. scheduled task --------------------------------------------------
$action = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument '-m agents.supervisor' `
    -WorkingDirectory $ProjectRoot

# Trigger: at the installing account's logon + 30s delay. Matches the existing
# RC-Supervisor convention (CLAUDE.md §"Scheduled tasks"). With the
# machine set to auto-logon as that account, this is effectively
# at-boot. Running as that account is required so cross-machine SMB
# pushes can access the per-user cmdkey-stored credentials for
# \\192.0.2.237 (SYSTEM does not share those creds).
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$trigger.Delay = 'PT30S'

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 5 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Highest

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "scheduled task already present: $TaskName -- replacing"
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description 'Riot Commander Phase 3 -- agent-framework supervisor' | Out-Null

Write-Host "scheduled task registered: $TaskName"
Write-Host ''
Write-Host '=== done ==='
