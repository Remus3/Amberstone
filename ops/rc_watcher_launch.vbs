Set oShell = CreateObject("WScript.Shell")
oShell.Run "powershell.exe -WindowStyle Hidden -ExecutionPolicy Bypass -File ""C:\Riot Commander\ops\rc_league_watcher.ps1"" -ConfigPath ""C:\Riot Commander\ops\rc_config.json""", 0, False
