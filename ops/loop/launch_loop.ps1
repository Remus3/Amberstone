param(
  [ValidateSet("dry", "live")][string]$Mode = "dry",
  [int]$Regressions = 0,
  [switch]$Hang,
  [string]$Cfg = ""
)
$ErrorActionPreference = "Stop"
$py = "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe"
$root = "C:\Riot Commander"
$ctl = "$root\ops\loop\control"
$ahk = "C:\Program Files\AutoHotkey\v2\AutoHotkey64.exe"
$bridge = "$root\ops\loop\claude_gui_bridge.ahk"
$ctrl = "$root\ops\loop\loop_controller.py"
$stub = "$root\ops\loop\claude_stub.py"
$env:GEMINI_API_KEY = [Environment]::GetEnvironmentVariable("GEMINI_API_KEY", "User")
if (-not $Cfg) { $Cfg = if ($Mode -eq "live") { "$root\ops\loop\config.json" } else { "$root\ops\loop\config.dry.json" } }

# pre-clean stale sentinels so a prior run's STOP cannot early-kill this one.
# ahk_heartbeat.txt: a stale one reads as a LIVE bridge until it ages past the staleness
# window. ahk_partial.flag: it latches the bridge OFF, so a leftover flag would make the
# new run refuse every directive. adjudicator_active.txt: a stale marker claims a backend
# pass is still running.
"STOP", "gemini.ready", "typed.flag", "claude.done", "cycle.txt",
"ahk_heartbeat.txt", "ahk_heartbeat.tmp", "ahk_partial.flag", "adjudicator_active.txt" | ForEach-Object {
  Remove-Item "$ctl\$_" -Force -ErrorAction SilentlyContinue
}
# seed the LIVE timings copy from the shipped defaults. Only when absent - control/ is
# runtime state, so an operator's tuning survives a relaunch.
if (-not (Test-Path "$ctl\ahk_timings.json")) {
  Copy-Item "$root\ops\loop\ahk_timings.default.json" "$ctl\ahk_timings.json" -Force -ErrorAction SilentlyContinue
}
# kill ONLY this repo's PRIOR controller. Without this a relaunch orphans its
# predecessor: the old controller keeps its own cycle counter and its own deadline, keeps
# appending to the shared controller.log, and keeps typing into the same Claude window, so
# its stale deadline eventually breaches and injects a stall recovery INTO AN UNRELATED
# LIVE CYCLE. Measured 2026-07-21: PID 22768 (start 00:51:36, its cycle 7) breached at
# 10:13:25 and interrupted the 08:43:51 controller's healthy cycle 2. Scoped by cmdline for
# the same reason the AutoHotkey kill below is - a bare python kill would take out RC
# itself, the Daemon Slayer server and every scheduled task.
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -like "*Riot Commander\ops\loop\loop_controller.py*" } |
  Where-Object { $_.ProcessId -ne $PID } |
  ForEach-Object { & taskkill /F /PID $_.ProcessId | Out-Null }

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
elseif ((Get-Content $Cfg -Raw | ConvertFrom-Json).channel -eq "sdk") {
  # The sdk channel runs headless `claude -p`: no window, no typing, nothing for
  # the bridge to do. Starting it anyway would resurrect the machine-wide
  # singleton that F1 removed and could block the sibling Sibling-A loop,
  # and the strict window-bind below would refuse to launch at all whenever no
  # window is titled claude_window_title. Both are pure AHK-channel concerns.
  # LW parity: Sibling-A c47b2b8.
  Write-Host "live: channel=sdk - no AHK bridge, no window bind"
}
else {
  # STRICT window-bind (LW a703ac1 parity): ONE claude.exe process owns MULTIPLE
  # project windows (Image/RC/Claude), so "first titled claude process" is WRONG
  # on a multi-project desktop and a bare pid is ambiguous across its windows.
  # Enumerate top-level windows, require exactly ONE titled config
  # claude_window_title AND owned by a claude process, and bind its HWND.
  if (-not ([System.Management.Automation.PSTypeName]'WinEnum').Type) {
    Add-Type -Language CSharp -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Text;
public class WinEnum {
  public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc cb, IntPtr lParam);
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int count);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
  public static System.Collections.Generic.List<string> ListWindows() {
    var rows = new System.Collections.Generic.List<string>();
    EnumWindows(delegate(IntPtr h, IntPtr l) {
      if (!IsWindowVisible(h)) return true;
      var sb = new StringBuilder(512);
      GetWindowText(h, sb, 512);
      if (sb.Length == 0) return true;
      uint pid; GetWindowThreadProcessId(h, out pid);
      rows.Add(((long)h).ToString() + "|" + pid + "|" + sb.ToString());
      return true;
    }, IntPtr.Zero);
    return rows;
  }
}
'@
  }
  $title = (Get-Content $Cfg -Raw | ConvertFrom-Json).claude_window_title
  if (-not $title) { Write-Error "config $Cfg has no claude_window_title - cannot window-bind"; exit 1 }
  $cpids = @(Get-Process claude -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id)
  $rows = @([WinEnum]::ListWindows() | ForEach-Object {
    $p = $_ -split '\|', 3
    [pscustomobject]@{ Hwnd = $p[0]; OwnerPid = [int]$p[1]; Title = $p[2] }
  } | Where-Object { $cpids -contains $_.OwnerPid })
  $wins = @($rows | Where-Object { $_.Title -eq $title })
  if ($wins.Count -ne 1) {
    $seen = ($rows | ForEach-Object { $_.Title }) -join ' | '
    Write-Error "need exactly ONE claude window titled '$title' (found $($wins.Count)); claude window titles: [$seen]"
    exit 1
  }
  Set-Content "$ctl\target_hwnd.txt" -Value $wins[0].Hwnd -Encoding ascii
  Set-Content "$ctl\target_pid.txt" -Value $wins[0].OwnerPid -Encoding ascii
  Set-Content "$ctl\ahk_mode.txt" -Value "live" -Encoding ascii
  Start-Process $ahk -ArgumentList "`"$bridge`""
  Write-Host "live: AHK bridge -> hwnd $($wins[0].Hwnd) (claude pid $($wins[0].OwnerPid)) title '$title'"
}
Start-Process $py -ArgumentList "`"$ctrl`"", "`"$Cfg`"" -WorkingDirectory $root -WindowStyle Hidden
Write-Host "controller launched cfg=$(Split-Path $Cfg -Leaf)"
Write-Host "control dir: $ctl"
Write-Host "abort: create $ctl\STOP   |   live log: $ctl\controller.log"
