# claude-rc — launch a fresh Windows Terminal window with Claude Code
# pre-running in the Riot Commander project directory.
#
# Usage:
#   claude-rc          # opens new WT window, launches `claude` in C:\Riot Commander
#   claude-rc -BareTab # current window, new tab (no new window)

param(
    [switch]$BareTab
)

$ProjectDir = "C:\Riot Commander"

if (-not (Test-Path $ProjectDir)) {
    Write-Error "Project dir not found: $ProjectDir"
    exit 1
}

# `wt` accepts:
#   -w 0     → use current window
#   -w new   → force new window
#   nt       → new tab subcommand
#   -d       → starting directory for the tab
#   -p       → profile name
#   --title  → tab title
# Then a literal command to run in the spawned shell.
#
# We invoke claude.ps1 via powershell so it runs in a real PowerShell host
# (claude is installed as a npm-shim .ps1 in PATH).

$tabTitle = "RC Claude"
$claudeCmd = "powershell.exe -NoExit -Command `"Set-Location '$ProjectDir'; claude`""

if ($BareTab) {
    & wt -w 0 nt -d "$ProjectDir" --title "$tabTitle" powershell.exe -NoExit -Command "claude"
} else {
    & wt -w new nt -d "$ProjectDir" --title "$tabTitle" powershell.exe -NoExit -Command "claude"
}
