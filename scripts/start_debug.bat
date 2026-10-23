@echo off
:: scripts\start_debug.bat - console launch with --debug. Lives in scripts\
:: (moved from the repo root 2026-10-09, MAIN 2246 sec 3); the repo root is
:: this file's parent folder.
setlocal
for %%I in ("%~dp0..") do set "RC_ROOT=%%~fI"

:: Read the API key (RM-810): the same lines as start.bat, which says why.
set API_FILE=%RC_ROOT%\API-Key-Claude.txt
setlocal enabledelayedexpansion
set "RC_KEY="
if defined ANTHROPIC_API_KEY set "RC_KEY=!ANTHROPIC_API_KEY: =!"
if defined RC_KEY set "RC_NOQ=!RC_KEY:"=!"
if not "!RC_KEY:~0,7!"=="sk-ant-" set "RC_KEY="
if defined RC_KEY if not "!RC_NOQ!"=="!RC_KEY!" set "RC_KEY="
if not defined RC_KEY if exist "!API_FILE!" set /p RC_KEY=<"!API_FILE!"
if defined RC_KEY set "RC_KEY=!RC_KEY: =!"
if defined RC_KEY set "RC_NOQ=!RC_KEY:"=!"
if not "!RC_KEY:~0,7!"=="sk-ant-" set "RC_KEY="
if defined RC_KEY if not "!RC_NOQ!"=="!RC_KEY!" set "RC_KEY="
endlocal & set "ANTHROPIC_API_KEY=%RC_KEY%"
set RIOT_COMMANDER_DEBUG=1

cd /d "%RC_ROOT%"
title Amberstone [DEBUG]
python.exe main.py --debug
pause
