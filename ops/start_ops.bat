@echo off
echo [Ops] Creating runtime directories...
mkdir "C:\Riot Commander\ops\runtime\deploy_requests" 2>nul
mkdir "C:\Riot Commander\ops\runtime\deploy_results" 2>nul
mkdir "C:\Riot Commander\ops\runtime\bridge_requests" 2>nul
mkdir "C:\Riot Commander\ops\runtime\bridge_results" 2>nul
mkdir "C:\Riot Commander\ops\runtime\bridge_results\images" 2>nul
mkdir "C:\Riot Commander\ops\runtime\logs" 2>nul
mkdir "C:\Riot Commander\ops\runtime\supervisor_requests" 2>nul
mkdir "C:\Riot Commander\ops\examples" 2>nul
mkdir "C:\Riot Commander\ops\staging" 2>nul
mkdir "C:\Riot Commander\ops\backups" 2>nul
echo [Ops] Directories ready.
echo.
echo [Ops] Starting self-healing watchdog...
echo [Ops] This replaces the old watchdog.ps1
echo [Ops] Press Ctrl+C to stop.
powershell -ExecutionPolicy Bypass -File "C:\Riot Commander\ops\run_self_healing_watchdog.ps1"
