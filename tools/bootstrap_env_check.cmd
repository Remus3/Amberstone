@echo off
REM tools\bootstrap_env_check.cmd -- environment/bootstrap diagnostic.
REM Phase 3 Step 3: uses py launcher with fallback to python.
REM Run from any directory.
setlocal
cd /d "%~dp0\.."
where py >nul 2>&1
if %ERRORLEVEL%==0 (
    py tools\bootstrap_env_check.py %*
) else (
    python tools\bootstrap_env_check.py %*
)
exit /b %ERRORLEVEL%
