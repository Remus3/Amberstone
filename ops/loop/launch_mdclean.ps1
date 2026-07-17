# launch_mdclean.ps1 - arm the 2026-07-16 md-cleanup loop pinned STRICTLY to the
# Claude Code session window titled exactly "RC". Mirrors launch_loop.ps1 live branch, plus:
#   - SELF-SERIALIZING vs the sibling Sibling-A loop: if an LW bridge is typing,
#     spawn a hidden waiter that arms this loop only after the LW bridge exits
#     (two foreground-Send AHK bridges on one desktop WILL interleave keystrokes).
#   - SCOPED bridge kill (this repo's bridge only, never LW's).
#   - errors out instead of grabbing the first titled Claude window.
param([switch]$Deferred)
$ErrorActionPreference = "Stop"
$py = "C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe"
$root = "C:\Riot Commander"
$ctl = "$root\ops\loop\control"
$ahk = "C:\Program Files\AutoHotkey\v2\AutoHotkey64.exe"
$bridge = "$root\ops\loop\claude_gui_bridge.ahk"
$ctrl = "$root\ops\loop\loop_controller.py"
$cfg = "$root\ops\loop\config.mdclean.json"
$env:GEMINI_API_KEY = [Environment]::GetEnvironmentVariable("GEMINI_API_KEY", "User")

function Get-LwBridge {
  Get-CimInstance Win32_Process -Filter "Name='AutoHotkey64.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*Sibling-A*" }
}

if (-not $Deferred) {
  if (Get-LwBridge) {
    Start-Process powershell -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"", "-Deferred" -WindowStyle Hidden
    Write-Host "Sibling-A bridge active - hidden waiter spawned; RC md-cleanup loop arms itself when the LW loop exits (poll 60s, cap 8h)."
    exit 0
  }
}
else {
  $tries = 0
  while (Get-LwBridge) {
    Start-Sleep -Seconds 60
    $tries++
    if ($tries -ge 480) {
      Set-Content "$ctl\mdclean_waiter_timeout.txt" -Value "LW bridge still alive after 8h; RC loop NOT armed ($(Get-Date -Format s))" -Encoding ascii
      exit 1
    }
  }
  Start-Sleep -Seconds 120   # let the LW run finish its final commit/push before we take the desktop
}

# pre-clean stale sentinels so a prior run's STOP cannot early-kill this one
"STOP", "gemini.ready", "typed.flag", "claude.done", "cycle.txt" | ForEach-Object {
  Remove-Item "$ctl\$_" -Force -ErrorAction SilentlyContinue
}
# kill ONLY this repo's bridge instances (never the LW sibling's)
Get-CimInstance Win32_Process -Filter "Name='AutoHotkey64.exe'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -like "*Riot Commander\ops\loop*" } |
  ForEach-Object { & taskkill /F /PID $_.ProcessId | Out-Null }
Start-Sleep -Milliseconds 300

$win = Get-Process claude -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -eq "RC" } | Select-Object -First 1
if (-not $win) {
  Set-Content "$ctl\mdclean_waiter_timeout.txt" -Value "no Claude window titled exactly 'RC' at arm time; loop NOT armed ($(Get-Date -Format s))" -Encoding ascii
  Write-Error "no Claude window titled exactly 'RC' found - retitle the executor session to RC first (strict match, no fallback)"
  exit 1
}
Set-Content "$ctl\target_pid.txt" -Value $win.Id -Encoding ascii
Set-Content "$ctl\ahk_mode.txt" -Value "live" -Encoding ascii
Start-Process $ahk -ArgumentList "`"$bridge`""
Start-Process $py -ArgumentList "`"$ctrl`"", "`"$cfg`"" -WorkingDirectory $root -WindowStyle Hidden
Write-Host "mdclean loop armed -> Claude window 'RC' pid $($win.Id) cfg=config.mdclean.json (8 cycles, Tier-0 docs-only)"
