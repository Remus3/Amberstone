# tools/rc_headless_launcher.ps1
# One-click idempotent launcher for the headless-upgrade run.
# Operator config: Claude started by AHK desktop-app send. The second-vendor
# auditor step was removed 2026-08-01 when that vendor was retired.
#
# Per click:
#   1. (removed 2026-08-01 - was a nightly second-vendor audit kick.)
#   2. Send the headless-upgrade command into the Claude desktop window via claude_send.ahk.
#      Guarded by ops/runtime/headless_launcher.lock so a double-click does NOT inject the
#      prompt twice into the same session. The lock self-heals: cleared when the Claude desktop
#      app is not running (run ended / closed) or when the lock is older than -StaleHours.
#
# -Force    send regardless of the lock.
# -DryRun   no side effects: call AHK in its own dry-run mode (verify only).

param(
  [switch]$Force,
  [switch]$DryRun,
  [string]$Command = "/headless-upgrade",
  [int]$StaleHours = 12
)

$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

$ahk  = "C:\Program Files\AutoHotkey\v2\AutoHotkey64.exe"
$send = Join-Path $repo "tools\claude_send.ahk"
$lock = Join-Path $repo "ops\runtime\headless_launcher.lock"
$log  = Join-Path $repo "logs\headless_launcher.log"

function Log($m) {
  $ts = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
  ("{0} {1}" -f $ts, $m) | Add-Content -Encoding ascii -Path $log
  Write-Host ("{0} {1}" -f $ts, $m)
}
function Notify($msg) {
  try { (New-Object -ComObject WScript.Shell).Popup($msg, 5, "RC Headless Launcher", 64) | Out-Null } catch {}
}
function Invoke-Ahk([bool]$live) {
  # AutoHotkey64.exe is a GUI-subsystem app: '&' returns immediately and never sets
  # $LASTEXITCODE. Start-Process -Wait -PassThru blocks until ExitApp and captures the
  # real exit code. Quote the script path explicitly (it contains a space) so AHK parses
  # exactly one script arg, then the command, then the optional live "go" token.
  $argLine = if ($live) { '"{0}" "{1}" go' -f $send, $Command } else { '"{0}" "{1}"' -f $send, $Command }
  $p = Start-Process -FilePath $ahk -ArgumentList $argLine -Wait -PassThru -WindowStyle Hidden
  return $p.ExitCode
}

$summary = @()

# 1. (was: kick the second-vendor nightly auditor. Removed 2026-08-01 with the
#     vendor - the loop self-adjudicates and RC-GeminiAudit no longer exists.)

# 2. Claude desktop app presence (self-heal lock if absent).
$running = [bool](Get-Process -Name claude -ErrorAction SilentlyContinue)
if (-not $running) {
  if (Test-Path $lock) { Remove-Item -Force $lock; Log "cleared stale lock (claude.exe not running)" }
  Log "claude desktop app not running - cannot send '$Command'"
  $summary += "Claude: NOT running - open the Claude desktop app, then click again"
  Notify ($summary -join "`n")
  exit 3
}

# 3. Idempotency guard on the AHK send.
if ((Test-Path $lock) -and -not $Force -and -not $DryRun) {
  $age = (Get-Date) - (Get-Item $lock).LastWriteTime
  if ($age.TotalHours -lt $StaleHours) {
    Log ("lock present (age {0}m) + claude running - assume run active; skip send. -Force or delete {1} to re-arm." -f [int]$age.TotalMinutes, $lock)
    $summary += "Claude: run already launched - skipped (idempotent)"
    Notify ($summary -join "`n")
    exit 0
  }
  Log ("lock stale (age {0}h >= {1}) - re-arming" -f [int]$age.TotalHours, $StaleHours)
}

# 4. Fire the AHK desktop send (live unless -DryRun).
if ($DryRun) {
  $code = Invoke-Ahk $false
  Log "DRYRUN ahk '$Command' exit=$code (0=window-ok 2=no-window)"
  $summary += "Claude: dry-run ahk exit $code"
} else {
  $code = Invoke-Ahk $true
  Log "ahk send '$Command' exit=$code"
  if ($code -eq 0) {
    Set-Content -Encoding ascii -Path $lock -Value ("launched {0} cmd={1}" -f (Get-Date).ToString('s'), $Command)
    Log "wrote lock $lock"
    $summary += "Claude: '$Command' sent to desktop app"
  } elseif ($code -eq 2) {
    if (Test-Path $lock) { Remove-Item -Force $lock }
    $summary += "Claude: no window found (exit 2)"
  } elseif ($code -eq 3) {
    $summary += "Claude: window activate failed (exit 3)"
  } else {
    $summary += "Claude: ahk exit $code"
  }
}

Notify ($summary -join "`n")
exit 0
