# tools/install_lane_widget_shortcut.ps1
# Create / refresh / remove the Desktop one-click button for the lane-widget
# Electron app.
#
# THIS SCRIPT IS OPERATOR-RUN, NEVER SESSION-RUN. It writes a .lnk to the
# Desktop, which is OUTSIDE the repository root, and a write outside the tree
# is a standing halt-and-ping point in this repo. The session that authored
# this file deliberately did not execute it.
#
# Modelled on tools/install_headless_launcher_shortcut.ps1 (same WScript.Shell
# COM pattern), with the three halves that model is missing: a pre-flight that
# refuses to produce a shortcut that cannot launch, a dry-run that echoes
# exactly what it would write, and an uninstall path.
#
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools\install_lane_widget_shortcut.ps1
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools\install_lane_widget_shortcut.ps1 -DryRun
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools\install_lane_widget_shortcut.ps1 -Uninstall
#
# Idempotent in both directions: installing twice overwrites the same .lnk and
# never produces a duplicate, and uninstalling twice is silent the second time.
#
# 7-bit ASCII only. A UTF-8 em-dash inside a double-quoted string in a no-BOM
# .ps1 is ANSI-decoded by PowerShell 5.1 into a smart quote that terminates the
# string and cascades into a parse failure - that incident is why the rule
# exists. Use " - " for a clause break.

[CmdletBinding()]
param(
    # Remove the shortcut instead of creating it. Silent when already absent.
    [switch]$Uninstall,
    # Print exactly what would be written or removed, then exit without
    # touching the Desktop.
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$RepoRoot   = "C:\Riot Commander"
$WidgetDir  = Join-Path $RepoRoot "lane-widget"
# The rc-shell Electron binary. lane-widget adds no second Electron install -
# it runs on the one rc-shell already vendors, which is the exact path
# tools/legion_on.ps1:81-89 already launches for the rc-shell overlay.
$Electron   = Join-Path $RepoRoot "rc-shell\node_modules\electron\dist\electron.exe"
$LinkName   = "Lane Monitor.lnk"

$desktop = [Environment]::GetFolderPath("Desktop")
if ([string]::IsNullOrWhiteSpace($desktop)) {
    Write-Error "could not resolve the Desktop folder - refusing to guess a path"
    exit 1
}
$lnkPath = Join-Path $desktop $LinkName

# ---------------------------------------------------------------- uninstall --
if ($Uninstall) {
    if (Test-Path -LiteralPath $lnkPath) {
        if ($DryRun) {
            Write-Host "[dry-run] would remove $lnkPath"
            exit 0
        }
        Remove-Item -LiteralPath $lnkPath -Force
        Write-Host "removed $lnkPath"
    } else {
        # Silent-when-absent on purpose: re-running uninstall is not an error.
        Write-Host "nothing to remove - $lnkPath is not present"
    }
    exit 0
}

# ---------------------------------------------------------------- pre-flight --
# Refuse rather than produce a shortcut that cannot launch. A .lnk pointing at
# a missing target is worse than no .lnk: it fails at click time, far from the
# cause.
$problems = @()
if (-not (Test-Path -LiteralPath $Electron -PathType Leaf)) {
    $problems += "electron binary not found: $Electron"
}
if (-not (Test-Path -LiteralPath $WidgetDir -PathType Container)) {
    $problems += "lane-widget package directory not found: $WidgetDir"
}
if (-not (Test-Path -LiteralPath (Join-Path $WidgetDir "package.json") -PathType Leaf)) {
    $problems += "lane-widget\package.json not found - $WidgetDir is not a package dir"
}
if ($problems.Count -gt 0) {
    Write-Host "pre-flight FAILED - no shortcut written:"
    foreach ($p in $problems) { Write-Host "  - $p" }
    Write-Host ""
    Write-Host "The electron binary ships with rc-shell. If it is missing, run"
    Write-Host "'npm install' in $RepoRoot\rc-shell first."
    exit 1
}

# ------------------------------------------------------------------- install --
$target   = $Electron
$arguments = '"' + $WidgetDir + '"'
$workDir  = $WidgetDir
# shell32.dll,22 is the generic monitor / display glyph - close enough to a
# desktop monitor panel, and it needs no asset committed to the repo.
$icon     = "$env:SystemRoot\System32\shell32.dll,22"
$descr    = "Lane / worker monitor - read-only widget over every participating repo"

$existed = Test-Path -LiteralPath $lnkPath

Write-Host "would write:"
Write-Host "  path             = $lnkPath"
Write-Host "  TargetPath       = $target"
Write-Host "  Arguments        = $arguments"
Write-Host "  WorkingDirectory = $workDir"
Write-Host "  IconLocation     = $icon"
Write-Host "  Description      = $descr"
if ($existed) {
    Write-Host "  (a shortcut of that name already exists and will be OVERWRITTEN in place)"
}

if ($DryRun) {
    Write-Host ""
    Write-Host "[dry-run] nothing was written"
    exit 0
}

$ws  = New-Object -ComObject WScript.Shell
$lnk = $ws.CreateShortcut($lnkPath)
$lnk.TargetPath       = $target
$lnk.Arguments        = $arguments
$lnk.WorkingDirectory = $workDir
$lnk.IconLocation     = $icon
$lnk.Description      = $descr
$lnk.WindowStyle      = 1
$lnk.Save()

if ($existed) {
    Write-Host "refreshed $lnkPath"
} else {
    Write-Host "created $lnkPath"
}
Write-Host "  target = $($lnk.TargetPath) $($lnk.Arguments)"
Write-Host ""
Write-Host "The widget holds its own single-instance lock, so clicking it twice"
Write-Host "focuses the existing window rather than opening a second one."
