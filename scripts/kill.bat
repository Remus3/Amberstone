@echo off
:: scripts\kill.bat - stop Amberstone (moved from the repo root 2026-10-09, MAIN 2246 sec 3).
echo Closing Amberstone...
wmic process where "commandline like '%%main.py%%'" delete >nul 2>&1
taskkill /F /IM pythonw.exe >nul 2>&1
echo Done.
