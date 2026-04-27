@echo off
REM tools\dev_cli.cmd -- Riot Commander local developer/operator CLI.
REM Usage: tools\dev_cli.cmd <subcommand> [options]
REM Phase 3 Step 3: uses py launcher (py.exe) with fallback to python,
REM eliminating the hardcoded absolute Python path.
REM Run from any directory; resolves project root via %~dp0
setlocal
cd /d "%~dp0\.."

REM Prefer Windows Py Launcher (py.exe); fall back to python in PATH.
where py >nul 2>&1
if %ERRORLEVEL%==0 (
    py tools\dev_cli.py %*
) else (
    python tools\dev_cli.py %*
)
exit /b %ERRORLEVEL%
