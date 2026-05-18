# claude-rc - launch the "Legion" Claude session in a visible Windows
# Terminal window with statusline + bridge hooks active.
#
# Mirrors tools/start_gamepc_claude.ps1's pattern: idempotent (skip if a
# Claude window titled "Legion" is already alive), helper-cmd indirection
# to dodge wt/PowerShell argv mangling around --name + the slash-permission
# flag, visible WT window so the operator can interact.
#
# Triggered by the desktop shortcut (Claude RC.lnk → powershell -Hidden
# -File this script). Can also be run standalone:
#   powershell -ExecutionPolicy Bypass -File "C:\Riot Commander\tools\claude-rc.ps1"

$ErrorActionPreference = 'Stop'
$ProjectDir  = 'C:\Riot Commander'
$RuntimeDir  = Join-Path $ProjectDir 'ops\runtime'
$Helper      = Join-Path $RuntimeDir '_legion_claude_helper.cmd'
$SessionName = 'Legion'

if (-not (Test-Path $ProjectDir)) {
    Write-Error "Project dir not found: $ProjectDir"
    exit 1
}

# Idempotency: skip if a window titled "Legion ..." is already alive.
# Matches the WT tab title that `claude --name Legion` sets, so a re-click
# of the shortcut won't stack duplicate sessions.
$existing = Get-Process -ErrorAction SilentlyContinue |
            Where-Object { $_.MainWindowTitle -like "$SessionName*" }
if ($existing) { return }

# Refresh the helper .cmd every launch - self-heals if it's been edited or
# deleted. cmd quoting is more forgiving than wt's argv parsing for the
# embedded --name "Legion" + --dangerously-skip-permissions combination.
if (-not (Test-Path $RuntimeDir)) {
    New-Item -ItemType Directory -Path $RuntimeDir -Force | Out-Null
}

@'
@echo off
cd /d "C:\Riot Commander"
title Legion
claude --name "Legion" --dangerously-skip-permissions
'@ | Set-Content -Path $Helper -Encoding ASCII

# wt.exe has its own argv parser that doesn't reliably round-trip
# PowerShell's per-arg quoting when paths contain spaces (e.g.
# "C:\Riot Commander"). Build the command line as one pre-quoted string
# and pass it via -ArgumentList <string>, which Start-Process forwards
# verbatim - no re-quoting by PowerShell.
$wt = Get-Command wt.exe -ErrorAction SilentlyContinue
if ($wt) {
    $cmdLine = "-d `"$ProjectDir`" cmd /k `"$Helper`""
    Start-Process wt.exe -ArgumentList $cmdLine | Out-Null
} else {
    Start-Process cmd.exe -ArgumentList "/k `"$Helper`"" -WorkingDirectory $ProjectDir | Out-Null
}
