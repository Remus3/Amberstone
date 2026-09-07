@echo off
REM tools\bootstrap_env_check.cmd -- environment/bootstrap diagnostic.
REM Pins the canonical interpreter; falls back to python on PATH.
REM Bare py is banned (resolves to a dep-less pymanager runtime).
REM Run from any directory.
setlocal
cd /d "%~dp0\.."
set "RC_PY=%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
if exist "%RC_PY%" (
    "%RC_PY%" tools\bootstrap_env_check.py %*
) else (
    python tools\bootstrap_env_check.py %*
)
exit /b %ERRORLEVEL%
