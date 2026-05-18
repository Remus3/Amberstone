@echo off
:: install_startup.bat
:: Adds rc_league_watcher.ps1 to Windows startup so it runs automatically
:: on login - hidden, no window. Run this ONCE.

echo ========================================
echo  Riot Commander - Startup Installer
echo ========================================
echo.

set SCRIPT_DIR=%~dp0
set WATCHER=%SCRIPT_DIR%rc_league_watcher.ps1
set CONFIG=%SCRIPT_DIR%rc_config.json
set STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
set SHORTCUT=%STARTUP%\RiotCommanderWatcher.lnk

:: Remove old shortcut/bat if present
del /f /q "%STARTUP%\RiotCommander*.lnk" 2>nul
del /f /q "%STARTUP%\RiotCommander*.bat" 2>nul

:: Create a .vbs launcher (silently runs PowerShell, no flashing window)
set VBS=%SCRIPT_DIR%rc_watcher_launch.vbs
echo Set oShell = CreateObject("WScript.Shell") > "%VBS%"
echo oShell.Run "powershell.exe -WindowStyle Hidden -ExecutionPolicy Bypass -File ""%WATCHER%"" -ConfigPath ""%CONFIG%""", 0, False >> "%VBS%"

:: Create shortcut in Windows Startup folder pointing to the VBS launcher
powershell -Command ^
  "$ws = New-Object -ComObject WScript.Shell; ^
   $s = $ws.CreateShortcut('%STARTUP%\RiotCommanderWatcher.lnk'); ^
   $s.TargetPath = 'wscript.exe'; ^
   $s.Arguments = '/nologo \"%SCRIPT_DIR%rc_watcher_launch.vbs\"'; ^
   $s.WorkingDirectory = '%SCRIPT_DIR%'; ^
   $s.Description = 'Riot Commander League Watcher'; ^
   $s.WindowStyle = 7; ^
   $s.Save()"

echo.
if exist "%STARTUP%\RiotCommanderWatcher.lnk" (
    echo [OK] Startup entry created:
    echo      %STARTUP%\RiotCommanderWatcher.lnk
    echo.
    echo Riot Commander will now auto-start when League opens,
    echo and auto-stop when League closes.
    echo.
    echo To start immediately without rebooting, run:
    echo   wscript.exe /nologo "%SCRIPT_DIR%rc_watcher_launch.vbs"
) else (
    echo [FAIL] Could not create startup shortcut. Try running as Administrator.
)
echo.
pause
