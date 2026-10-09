Set oShell = CreateObject("WScript.Shell")
Set oFso = CreateObject("Scripting.FileSystemObject")
opsDir = oFso.GetParentFolderName(WScript.ScriptFullName)
oShell.Run "powershell.exe -WindowStyle Hidden -ExecutionPolicy Bypass -File """ & opsDir & "\rc_league_watcher.ps1"" -ConfigPath """ & opsDir & "\rc_config.json""", 0, False
