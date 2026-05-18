@echo off
:: restart.bat - kill and relaunch Riot Commander
echo [Riot Commander] Restarting...
wmic process where "commandline like '%%main.py%%'" delete >nul 2>&1
taskkill /F /IM pythonw.exe >nul 2>&1
timeout /t 2 /nobreak >nul

setlocal
set API_FILE=%~dp0API-Key-Claude.txt
if exist "%API_FILE%" (
    set /p ANTHROPIC_API_KEY=<"%API_FILE%"
    set ANTHROPIC_API_KEY=%ANTHROPIC_API_KEY: =%
)
cd /d "%~dp0"
:: Apply any pending patches
if exist "apply_patches.py" (
    echo [Riot Commander] Applying patches...
    python apply_patches.py
)
start "" pythonw.exe main.py
echo [Riot Commander] Relaunched.
