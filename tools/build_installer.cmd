@echo off
REM tools\build_installer.cmd -- build installer staging directory.
REM Phase 5 Step 3: uses py launcher with fallback to python.
setlocal
cd /d "%~dp0\.."
where py >nul 2>&1
if %ERRORLEVEL%==0 (
    py tools\build_installer.py %*
) else (
    python tools\build_installer.py %*
)
exit /b %ERRORLEVEL%
