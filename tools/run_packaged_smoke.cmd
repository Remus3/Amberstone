@echo off
REM tools\run_packaged_smoke.cmd -- packaged artifact smoke harness.
REM Phase 5 Step 2: uses py launcher with fallback to python.
REM Run from any directory.
setlocal
cd /d "%~dp0\.."
where py >nul 2>&1
if %ERRORLEVEL%==0 (
    py tools\run_packaged_smoke.py %*
) else (
    python tools\run_packaged_smoke.py %*
)
exit /b %ERRORLEVEL%
