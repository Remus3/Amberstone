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
