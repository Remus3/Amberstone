@echo off
:: scripts\kill.bat - stop Amberstone (moved from the repo root 2026-10-09, MAIN 2246 sec 3).
echo Closing Amberstone...
"%SystemRoot%\System32\wbem\wmic.exe" process where "commandline like '%%main.py%%'" delete >nul 2>&1
"%SystemRoot%\System32\taskkill.exe" /F /IM pythonw.exe >nul 2>&1
echo Done.
