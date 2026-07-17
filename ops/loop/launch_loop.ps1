param(
  [ValidateSet("dry", "live")][string]$Mode = "dry",
  [int]$Regressions = 0,
  [switch]$Hang,
  [string]$Cfg = ""
)
$ErrorActionPreference = "Stop"
$py = "C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe"
$root = "C:\Riot Commander"
$ctl = "$root\ops\loop\control"
$ahk = "C:\Program Files\AutoHotkey\v2\AutoHotkey64.exe"
$bridge = "$root\ops\loop\claude_gui_bridge.ahk"
$ctrl = "$root\ops\loop\loop_controller.py"
$stub = "$root\ops\loop\claude_stub.py"
$env:GEMINI_API_KEY = [Environment]::GetEnvironmentVariable("GEMINI_API_KEY", "User")
if (-not $Cfg) { $Cfg = if ($Mode -eq "live") { "$root\ops\loop\config.json" } else { "$root\ops\loop\config.dry.json" } }

# pre-clean stale sentinels so a prior run's STOP cannot early-kill this one
"STOP", "gemini.ready", "typed.flag", "claude.done", "cycle.txt" | ForEach-Object {
  Remove-Item "$ctl\$_" -Force -ErrorAction SilentlyContinue
}
# kill ONLY this repo's bridge instances - a global AutoHotkey64 kill murders the
# sibling Sibling-A loop's bridge mid-run (and vice versa). Scoped by cmdline.
Get-CimInstance Win32_Process -Filter "Name='AutoHotkey64.exe'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -like "*Riot Commander\ops\loop*" } |
  ForEach-Object { & taskkill /F /PID $_.ProcessId | Out-Null }
Start-Sleep -Milliseconds 300

if ($Mode -eq "dry") {
  $sa = @("`"$stub`"")
  if ($Regressions) { $sa += "--regressions"; $sa += "1" }
  if ($Hang) { $sa += "--hang" }
  Start-Process $py -ArgumentList $sa -WorkingDirectory $root
  Write-Host "dry: claude_stub launched (regress=$Regressions hang=$($Hang.IsPresent))"
}
else {
  $win = Get-Process claude -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle } | Select-Object -First 1
  if (-not $win) { Write-Error "no Claude window with a title found - open the executor session first"; exit 1 }
  Set-Content "$ctl\target_pid.txt" -Value $win.Id -Encoding ascii
  Set-Content "$ctl\ahk_mode.txt" -Value "live" -Encoding ascii
  Start-Process $ahk -ArgumentList "`"$bridge`""
  Write-Host "live: AHK bridge -> Claude pid $($win.Id)"
}
Start-Process $py -ArgumentList "`"$ctrl`"", "`"$Cfg`"" -WorkingDirectory $root -WindowStyle Hidden
Write-Host "controller launched cfg=$(Split-Path $Cfg -Leaf)"
Write-Host "control dir: $ctl"
Write-Host "abort: create $ctl\STOP   |   live log: $ctl\controller.log"
