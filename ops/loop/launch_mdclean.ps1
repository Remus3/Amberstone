# launch_mdclean.ps1 - arm the 2026-07-16 md-cleanup loop pinned STRICTLY to the
# Claude Code session window titled exactly "RC". Mirrors launch_loop.ps1 live branch,
# but errors out instead of grabbing the first titled Claude window.
$ErrorActionPreference = "Stop"
$py = "C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe"
$root = "C:\Riot Commander"
$ctl = "$root\ops\loop\control"
$ahk = "C:\Program Files\AutoHotkey\v2\AutoHotkey64.exe"
$bridge = "$root\ops\loop\claude_gui_bridge.ahk"
$ctrl = "$root\ops\loop\loop_controller.py"
$cfg = "$root\ops\loop\config.mdclean.json"
$env:GEMINI_API_KEY = [Environment]::GetEnvironmentVariable("GEMINI_API_KEY", "User")

# pre-clean stale sentinels so a prior run's STOP cannot early-kill this one
"STOP", "gemini.ready", "typed.flag", "claude.done", "cycle.txt" | ForEach-Object {
  Remove-Item "$ctl\$_" -Force -ErrorAction SilentlyContinue
}
Get-Process AutoHotkey64 -ErrorAction SilentlyContinue | ForEach-Object { $_.Kill() }; Start-Sleep -Milliseconds 300

$win = Get-Process claude -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -eq "RC" } | Select-Object -First 1
if (-not $win) {
  Write-Error "no Claude window titled exactly 'RC' found - retitle the executor session to RC first (strict match, no fallback)"
  exit 1
}
Set-Content "$ctl\target_pid.txt" -Value $win.Id -Encoding ascii
Set-Content "$ctl\ahk_mode.txt" -Value "live" -Encoding ascii
Start-Process $ahk -ArgumentList "`"$bridge`""
Start-Process $py -ArgumentList "`"$ctrl`"", "`"$cfg`"" -WorkingDirectory $root -WindowStyle Hidden
Write-Host "mdclean loop armed -> Claude window 'RC' pid $($win.Id) cfg=config.mdclean.json (8 cycles, Tier-0 docs-only)"
