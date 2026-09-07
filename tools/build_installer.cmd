@echo off
REM tools\build_installer.cmd -- build installer staging directory.
REM Pins the canonical interpreter; falls back to python on PATH.
REM Bare py is banned (resolves to a dep-less pymanager runtime).
setlocal
cd /d "%~dp0\.."
set "RC_PY=%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
if exist "%RC_PY%" (
    "%RC_PY%" tools\build_installer.py %*
) else (
    python tools\build_installer.py %*
)
exit /b %ERRORLEVEL%
