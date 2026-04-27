@echo off
:: run_watchdog.bat — start the auto-restart watchdog in a background window
:: Run this ONCE. Claude will then be able to auto-restart the overlay.
echo [Watchdog] Starting...
powershell -WindowStyle Minimized -ExecutionPolicy Bypass -File "%~dp0watchdog.ps1"
