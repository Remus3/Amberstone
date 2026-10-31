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
"%SystemRoot%\System32\taskkill.exe" /f /im pythonw.exe 2>nul
"%SystemRoot%\System32\timeout.exe" /t 2 /nobreak >nul

echo Starting Amberstone...
:: A45b: the embedded runtime only when tools\build_python_embed.py stamped it
:: (EMBED_STAMP.json); a hand-made python-embed is named and skipped.
set "EMBED_OK="
if exist "%EMBED_PYW%" if exist "%RC_ROOT%\python-embed\EMBED_STAMP.json" set "EMBED_OK=1"
if exist "%EMBED_PYW%" if not defined EMBED_OK echo python-embed has no EMBED_STAMP.json, so it was not built by tools\build_python_embed.py - using pythonw.exe from PATH
if defined EMBED_OK (
    start "" "%EMBED_PYW%" "%RC_ROOT%\main.py"
) else (
    start "" pythonw.exe "%RC_ROOT%\main.py"
)
echo Done!
"%SystemRoot%\System32\timeout.exe" /t 3
