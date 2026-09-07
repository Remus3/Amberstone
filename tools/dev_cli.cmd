@echo off
REM tools\dev_cli.cmd -- Riot Commander local developer/operator CLI.
REM Usage: tools\dev_cli.cmd <subcommand> [options]
REM Pins the canonical interpreter; falls back to python on PATH.
REM Bare py is banned (resolves to a dep-less pymanager runtime).
REM Run from any directory; resolves project root via %~dp0
setlocal
cd /d "%~dp0\.."

set "RC_PY=%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
if exist "%RC_PY%" (
    "%RC_PY%" tools\dev_cli.py %*
) else (
    python tools\dev_cli.py %*
)
exit /b %ERRORLEVEL%
