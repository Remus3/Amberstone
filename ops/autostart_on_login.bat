@echo off
REM ============================================================
REM  Riot Commander - Auto-start on Windows login
REM  Place shortcut to this file in:
REM  %APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
REM ============================================================
echo [%DATE% %TIME%] Riot Commander ops auto-start >> "%TEMP%\rc_autostart.log"

REM Wait 15 seconds for desktop to fully load before launching
"%SystemRoot%\System32\timeout.exe" /t 15 /nobreak >nul

cd /d "%~dp0.."

REM Kill any leftover processes from previous session
"%SystemRoot%\System32\taskkill.exe" /F /IM pythonw.exe 2>nul
"%SystemRoot%\System32\timeout.exe" /t 2 /nobreak >nul

REM Launch the full ops system (supervisor + watchdog + app)
start "" /B "%SystemRoot%\System32\cmd.exe" /C "%~dp0launch_new_system.bat" >> "%TEMP%\rc_autostart.log" 2>&1

echo [%DATE% %TIME%] launch_new_system.bat started >> "%TEMP%\rc_autostart.log"
