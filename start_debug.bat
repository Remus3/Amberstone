@echo off
setlocal

set API_FILE=%~dp0API-Key-Claude.txt
if exist "%API_FILE%" (
    set /p ANTHROPIC_API_KEY=<"%API_FILE%"
    set ANTHROPIC_API_KEY=%ANTHROPIC_API_KEY: =%
)
set RIOT_COMMANDER_DEBUG=1

cd /d "%~dp0"
title Riot Commander [DEBUG]
python.exe main.py --debug
pause
