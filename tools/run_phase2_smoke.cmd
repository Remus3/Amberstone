@echo off
REM tools\run_phase2_smoke.cmd -- Phase 3 Step 3: uses py launcher with fallback.
setlocal
cd /d "%~dp0\.."
where py >nul 2>&1
if %ERRORLEVEL%==0 (
    py tools\run_phase2_smoke.py %*
) else (
    python tools\run_phase2_smoke.py %*
)
exit /b %ERRORLEVEL%
