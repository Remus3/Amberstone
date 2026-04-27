@echo off
REM tools\package_portable.cmd -- build redistributable portable archive.
REM Phase 4 Step 4: uses py launcher with fallback to python.
REM Run from any directory.
setlocal
cd /d "%~dp0\.."
where py >nul 2>&1
if %ERRORLEVEL%==0 (
    py tools\package_portable.py %*
) else (
    python tools\package_portable.py %*
)
exit /b %ERRORLEVEL%
