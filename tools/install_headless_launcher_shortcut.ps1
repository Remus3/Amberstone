# tools/install_headless_launcher_shortcut.ps1
# Create / refresh the Desktop one-click button for rc_headless_launcher.ps1.
# Idempotent: overwrites the same .lnk each run.
$desktop = [Environment]::GetFolderPath("Desktop")
$lnkPath = Join-Path $desktop "RC Headless.lnk"
$script  = "C:\Riot Commander\tools\rc_headless_launcher.ps1"
$ws  = New-Object -ComObject WScript.Shell
$lnk = $ws.CreateShortcut($lnkPath)
$lnk.TargetPath       = Join-Path $PSHOME "powershell.exe"
$lnk.Arguments        = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $script + '"'
$lnk.WorkingDirectory = "C:\Riot Commander"
$lnk.IconLocation     = "$env:SystemRoot\System32\shell32.dll,137"
$lnk.Description       = "Idempotent one-click headless-upgrade launcher (AHK desktop send)"
$lnk.WindowStyle      = 7
$lnk.Save()
"created $lnkPath"
"  target = $($lnk.TargetPath) $($lnk.Arguments)"
