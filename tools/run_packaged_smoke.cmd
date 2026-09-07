@echo off
REM tools\run_packaged_smoke.cmd -- packaged artifact smoke harness.
REM Pins the canonical interpreter; falls back to python on PATH.
REM Bare py is banned (resolves to a dep-less pymanager runtime).
REM Run from any directory.
setlocal
cd /d "%~dp0\.."
set "RC_PY=%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
if exist "%RC_PY%" (
    "%RC_PY%" tools\run_packaged_smoke.py %*
) else (
    python tools\run_packaged_smoke.py %*
)
exit /b %ERRORLEVEL%
