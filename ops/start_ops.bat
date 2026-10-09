@echo off
set "RC_ROOT=%~dp0.."
echo [Ops] Creating runtime directories...
mkdir "%RC_ROOT%\ops\runtime\deploy_requests" 2>nul
mkdir "%RC_ROOT%\ops\runtime\deploy_results" 2>nul
mkdir "%RC_ROOT%\ops\runtime\logs" 2>nul
mkdir "%RC_ROOT%\ops\runtime\supervisor_requests" 2>nul
mkdir "%RC_ROOT%\ops\examples" 2>nul
mkdir "%RC_ROOT%\ops\staging" 2>nul
mkdir "%RC_ROOT%\ops\backups" 2>nul
echo [Ops] Directories ready.
echo.
echo [Ops] Starting self-healing watchdog...
echo [Ops] This replaces the old watchdog.ps1
echo [Ops] Press Ctrl+C to stop.
powershell -ExecutionPolicy Bypass -File "%RC_ROOT%\ops\run_self_healing_watchdog.ps1"
