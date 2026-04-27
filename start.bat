@echo off
setlocal

:: Option B launch: use embedded Python runtime if present,
:: fall back to PATH-based pythonw.exe if not (Option A compatibility).
set EMBED_PYW=%~dp0python-embed\pythonw.exe
set EMBED_PY=%~dp0python-embed\python.exe

:: Read API key from file
set API_FILE=%~dp0API-Key-Claude.txt
if exist "%API_FILE%" (
    set /p ANTHROPIC_API_KEY=<"%API_FILE%"
    set ANTHROPIC_API_KEY=%ANTHROPIC_API_KEY: =%
)

:: Validate key
if "%ANTHROPIC_API_KEY:~0,7%" neq "sk-ant-" (
    echo Anthropic API key missing or invalid.
    echo Edit API-Key-Claude.txt with your key, or run install.bat
    pause
    exit /b 1
)

cd /d "%~dp0"

:: Prefer embedded runtime (Option B); fall back to PATH (Option A)
if exist "%EMBED_PYW%" (
    start "" "%EMBED_PYW%" main.py
) else (
    start "" pythonw.exe main.py
)
