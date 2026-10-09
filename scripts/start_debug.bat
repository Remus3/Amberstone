@echo off
:: scripts\start_debug.bat - console launch with --debug. Lives in scripts\
:: (moved from the repo root 2026-10-09, MAIN 2246 sec 3); the repo root is
:: this file's parent folder.
setlocal
for %%I in ("%~dp0..") do set "RC_ROOT=%%~fI"

set API_FILE=%RC_ROOT%\API-Key-Claude.txt
if exist "%API_FILE%" (
    set /p ANTHROPIC_API_KEY=<"%API_FILE%"
    set ANTHROPIC_API_KEY=%ANTHROPIC_API_KEY: =%
)
set RIOT_COMMANDER_DEBUG=1

cd /d "%RC_ROOT%"
title Amberstone [DEBUG]
python.exe main.py --debug
pause
