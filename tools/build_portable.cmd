@echo off
REM tools\build_portable.cmd -- build portable staging bundle.
REM Phase 4 Step 3: uses py launcher with fallback to python.
REM Run from any directory.
setlocal
cd /d "%~dp0\.."
where py >nul 2>&1
if %ERRORLEVEL%==0 (
    py tools\build_portable.py %*
) else (
    python tools\build_portable.py %*
)
exit /b %ERRORLEVEL%
