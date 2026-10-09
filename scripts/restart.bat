@echo off
:: scripts\restart.bat - kill and relaunch Amberstone. Lives in scripts\
:: (moved from the repo root 2026-10-09, MAIN 2246 sec 3); the repo root is
:: this file's parent folder.
echo [Amberstone] Restarting...
wmic process where "commandline like '%%main.py%%'" delete >nul 2>&1
taskkill /F /IM pythonw.exe >nul 2>&1
timeout /t 2 /nobreak >nul

setlocal
for %%I in ("%~dp0..") do set "RC_ROOT=%%~fI"
set API_FILE=%RC_ROOT%\API-Key-Claude.txt
if exist "%API_FILE%" (
    set /p ANTHROPIC_API_KEY=<"%API_FILE%"
    set ANTHROPIC_API_KEY=%ANTHROPIC_API_KEY: =%
)
cd /d "%RC_ROOT%"
:: Apply any pending patches
if exist "apply_patches.py" (
    echo [Amberstone] Applying patches...
    python apply_patches.py
)
start "" pythonw.exe main.py
echo [Amberstone] Relaunched.
