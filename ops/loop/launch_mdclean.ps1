# launch_mdclean.ps1 - arm the 2026-07-16 md-cleanup loop pinned STRICTLY to the
# Claude Code session window titled exactly "RC". Mirrors launch_loop.ps1 live branch, plus:
#   - SELF-SERIALIZING vs the sibling Sibling-A loop: if an LW bridge is typing,
#     spawn a hidden waiter that arms this loop only after the LW bridge exits
#     (two foreground-Send AHK bridges on one desktop WILL interleave keystrokes).
#   - SCOPED bridge kill (this repo's bridge only, never LW's).
#   - errors out instead of grabbing the first titled Claude window.
param([switch]$Deferred)
$ErrorActionPreference = "Stop"
$py = "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe"
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

# STRICT window-bind (LW a703ac1 parity): ONE claude.exe process owns MULTIPLE
# project windows (Image/RC/Claude), so Get-Process MainWindowTitle sees only one
# of them and a bare pid is AMBIGUOUS across all of them. Enumerate top-level
# windows, require exactly ONE titled config claude_window_title AND owned by a
# claude process, and bind its HWND. The bridge targets ahk_id only (no fallback).
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
$title = (Get-Content $cfg -Raw | ConvertFrom-Json).claude_window_title
$cpids = @(Get-Process claude -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id)
$rows = @([WinEnum]::ListWindows() | ForEach-Object {
  $p = $_ -split '\|', 3
  [pscustomobject]@{ Hwnd = $p[0]; OwnerPid = [int]$p[1]; Title = $p[2] }
} | Where-Object { $cpids -contains $_.OwnerPid })
$wins = @($rows | Where-Object { $_.Title -eq $title })
if ($wins.Count -ne 1) {
  $seen = ($rows | ForEach-Object { $_.Title }) -join ' | '
  Set-Content "$ctl\mdclean_waiter_timeout.txt" -Value "need exactly ONE Claude window titled '$title' at arm time (found $($wins.Count)); titles seen: [$seen]; loop NOT armed ($(Get-Date -Format s))" -Encoding ascii
  Write-Error "need exactly ONE claude window titled '$title' (found $($wins.Count)); claude window titles: [$seen] - retitle the executor session first (strict match, no fallback)"
  exit 1
}
Set-Content "$ctl\target_hwnd.txt" -Value $wins[0].Hwnd -Encoding ascii
Set-Content "$ctl\target_pid.txt" -Value $wins[0].OwnerPid -Encoding ascii
Set-Content "$ctl\ahk_mode.txt" -Value "live" -Encoding ascii
Start-Process $ahk -ArgumentList "`"$bridge`""
Start-Process $py -ArgumentList "`"$ctrl`"", "`"$cfg`"" -WorkingDirectory $root -WindowStyle Hidden
Write-Host "mdclean loop armed -> Claude window '$title' hwnd $($wins[0].Hwnd) (pid $($wins[0].OwnerPid)) cfg=config.mdclean.json (8 cycles, Tier-0 docs-only)"
