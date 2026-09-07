@echo off
REM Pins the canonical interpreter; falls back to python on PATH.
REM Bare py is banned (resolves to a dep-less pymanager runtime).
setlocal
cd /d "%~dp0\.."
set "RC_PY=%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
if exist "%RC_PY%" (
    "%RC_PY%" tools\run_phase2_perf.py %*
) else (
    python tools\run_phase2_perf.py %*
)
exit /b %ERRORLEVEL%
