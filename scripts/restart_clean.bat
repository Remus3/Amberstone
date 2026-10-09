@echo off
:: scripts\restart_clean.bat -- Option B: uses embedded Python if present, falls back to PATH.
:: Lives in scripts\ (moved from the repo root 2026-10-09, MAIN 2246 sec 3);
:: the repo root is this file's parent folder.
setlocal
for %%I in ("%~dp0..") do set "RC_ROOT=%%~fI"
cd /d "%RC_ROOT%"

set EMBED_PYW=%RC_ROOT%\python-embed\pythonw.exe

echo Clearing Python cache...
rd /s /q "%RC_ROOT%\__pycache__" 2>nul
del /q "%RC_ROOT%\*.pyc" 2>nul
del /q "%RC_ROOT%\apply_patches.py" 2>nul

echo Killing old processes...
taskkill /f /im pythonw.exe 2>nul
timeout /t 2 /nobreak >nul

echo Starting Amberstone...
if exist "%EMBED_PYW%" (
    start "" "%EMBED_PYW%" "%RC_ROOT%\main.py"
) else (
    start "" pythonw.exe "%RC_ROOT%\main.py"
)
echo Done!
timeout /t 3
