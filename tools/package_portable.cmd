@echo off
REM tools\package_portable.cmd -- build redistributable portable archive.
REM Pins the canonical interpreter; falls back to python on PATH.
REM Bare py is banned (resolves to a dep-less pymanager runtime).
REM Run from any directory.
setlocal
cd /d "%~dp0\.."
set "RC_PY=%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
if exist "%RC_PY%" (
    "%RC_PY%" tools\package_portable.py %*
) else (
    python tools\package_portable.py %*
)
exit /b %ERRORLEVEL%
