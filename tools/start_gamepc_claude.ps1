# start_gamepc_claude.ps1 - idempotent launcher for Game-PC's interactive
# Claude session.
#
# Behavior:
#   1. Checks for an existing window titled "Game-PC bridge". If one exists,
#      exits silently (idempotent - safe to run from boot script + scheduled
#      task + manual shortcut click).
#   2. Otherwise spawns a visible Windows Terminal window in C:\RC-Agent\
#      running a plain interactive Claude session:
#         claude --name "Game-PC bridge" --dangerously-skip-permissions
#      Bridge-task processing is handled automatically by RC-BridgeDaemon
#      (gamepc_boot.ps1 step 6), which polls Legion every 30s and invokes
#      claude --print /process-bridge-tasks only when tasks are pending.
#      No /loop needed here - that would burn idle cycles for nothing.
#
# Called from gamepc_boot.ps1 at the end of the boot sequence. Can also be
# run standalone:
#   powershell -ExecutionPolicy Bypass -File C:\RC-Agent\start_gamepc_claude.ps1

$ErrorActionPreference = 'Stop'
$Cwd = 'C:\RC-Agent'
$SessionName = 'Game-PC bridge'

# Idempotency: window-title sniff. Claude Code sets the terminal title to
# the --name value, so any process advertising "Game-PC bridge" in its
# MainWindowTitle is our bridge session. Covers both wt.exe and bare pwsh
# host windows.
$existing = Get-Process -ErrorAction SilentlyContinue |
            Where-Object { $_.MainWindowTitle -like "*$SessionName*" }
if ($existing) {
    Write-Host "  Claude bridge session already running (PID $($existing[0].Id))" -ForegroundColor Green
    return
}

# Quoting-safe approach: write the actual claude invocation to a tiny helper
# .cmd, then have the new terminal run that. Keeps PowerShell argument
# binding from mangling the embedded single+double quote mix.
$helper = Join-Path $Cwd '_bridge_loop_helper.cmd'
@'
@echo off
cd /d C:\RC-Agent
title Game-PC bridge
claude --name "Game-PC bridge" --dangerously-skip-permissions
'@ | Set-Content -Path $helper -Encoding ASCII

$wt = Get-Command wt.exe -ErrorAction SilentlyContinue
if ($wt) {
    # wt.exe with -d sets the new tab's working directory; the trailing
    # `cmd /k` keeps the window open after Claude exits so the user can
    # re-launch in place if needed.
    Start-Process wt.exe -ArgumentList @('-d', $Cwd, 'cmd', '/k', $helper) | Out-Null
    Write-Host "  Claude bridge session launched (Windows Terminal)" -ForegroundColor Green
} else {
    # Fallback: bare cmd window. Visible, interactive, same /k semantics.
    Start-Process cmd.exe -ArgumentList @('/k', $helper) -WorkingDirectory $Cwd | Out-Null
    Write-Host "  Claude bridge session launched (cmd fallback)" -ForegroundColor Green
}
