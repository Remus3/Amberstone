@echo off
REM tools\run_phase3_snapshot_regressions.cmd
REM Phase 3 Step 2 snapshot regression harness.
REM Usage: tools\run_phase3_snapshot_regressions.cmd
setlocal
cd /d "%~dp0\.."
"%LOCALAPPDATA%\Programs\Python\Python314\python.exe" tools\run_phase3_snapshot_regressions.py %*
exit /b %ERRORLEVEL%
