@echo off
:: restart_clean.bat -- Option B: uses embedded Python if present, falls back to PATH.
cd /d "%~dp0"

set EMBED_PYW=%~dp0python-embed\pythonw.exe

echo Clearing Python cache...
rd /s /q "%~dp0__pycache__" 2>nul
del /q "%~dp0*.pyc" 2>nul
del /q "%~dp0apply_patches.py" 2>nul

echo Killing old processes...
taskkill /f /im pythonw.exe 2>nul
timeout /t 2 /nobreak >nul

echo Starting Riot Commander...
if exist "%EMBED_PYW%" (
    start "" "%EMBED_PYW%" "%~dp0main.py"
) else (
    start "" pythonw.exe "%~dp0main.py"
)
echo Done!
timeout /t 3
