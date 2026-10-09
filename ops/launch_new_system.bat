@echo off
set "RC_ROOT=%~dp0.."
echo ========================================
echo  Riot Commander - New Ops System Launch
echo ========================================
echo.

:: Create required runtime directories
mkdir "%RC_ROOT%\ops\runtime\deploy_requests" 2>nul
mkdir "%RC_ROOT%\ops\runtime\deploy_results" 2>nul
mkdir "%RC_ROOT%\ops\runtime\logs" 2>nul
mkdir "%RC_ROOT%\ops\runtime\supervisor_requests" 2>nul
mkdir "%RC_ROOT%\ops\runtime\control\commands" 2>nul
mkdir "%RC_ROOT%\ops\runtime\control\results" 2>nul

:: Kill any existing processes
echo Stopping old processes...
taskkill /F /IM pythonw.exe 2>nul
taskkill /F /IM python.exe /FI "WINDOWTITLE eq rc_supervisor*" 2>nul
timeout /t 2 /nobreak >nul

:: Clear stale pycache
rd /s /q "%RC_ROOT%\__pycache__" 2>nul
rd /s /q "%RC_ROOT%\ops\__pycache__" 2>nul
rd /s /q "%RC_ROOT%\tft\__pycache__" 2>nul

:: Remove any leftover watchdog stop file
del /f /q "%RC_ROOT%\ops\runtime\watchdog.stop" 2>nul

:: Start supervisor (hidden - no console window to accidentally close)
echo Starting supervisor...
start "" /B pythonw.exe "%RC_ROOT%\ops\rc_supervisor.py" --config "%RC_ROOT%\ops\rc_config.json"

:: Start watchdog (auto-restarts supervisor if it dies)
:: Runs as a hidden PowerShell process - no window to close
echo Starting self-healing watchdog...
start "" /B powershell.exe -WindowStyle Hidden -ExecutionPolicy Bypass -File "%RC_ROOT%\ops\run_self_healing_watchdog.ps1" --ConfigPath "%RC_ROOT%\ops\rc_config.json"

echo.
echo [OK] Supervisor + Watchdog launched (all hidden, no windows to close)
echo [OK] Supervisor will auto-start the app (main.py)
echo [OK] Watchdog will restart supervisor if it crashes
echo [OK] Health: %RC_ROOT%\ops\runtime\health.json
echo [OK] Supervisor log: %RC_ROOT%\ops\runtime\logs\supervisor.log
echo.
echo Waiting for app startup...
timeout /t 6 /nobreak >nul

:: Check health
if exist "%RC_ROOT%\ops\runtime\health.json" (
    echo [OK] App is ALIVE - health.json:
    type "%RC_ROOT%\ops\runtime\health.json"
) else (
    echo [WARN] No health.json yet - check: ops\runtime\logs\supervisor.log
)
echo.
if exist "%RC_ROOT%\ops\runtime\status.json" (
    echo [OK] Supervisor status:
    type "%RC_ROOT%\ops\runtime\status.json"
)
echo.
echo All processes running in background. This window can be closed.
pause
