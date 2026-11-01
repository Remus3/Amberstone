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
:: RM-1229: and only when the stamp's requirements_sha256 is the SHA-256 of
:: this tree's requirements.txt (the A45b launcher's embedFitness predicate;
:: the same lines as start.bat, which carries the long comment).
set "EMBED_OK="
set "EMBED_WHY="
set "EMBED_WANT="
if exist "%EMBED_PYW%" if not exist "%RC_ROOT%\python-embed\EMBED_STAMP.json" set "EMBED_WHY=python-embed has no EMBED_STAMP.json, so it was not built by tools\build_python_embed.py"
if exist "%EMBED_PYW%" if not defined EMBED_WHY if not exist "%RC_ROOT%\requirements.txt" set "EMBED_WHY=there is no requirements.txt to check python-embed\EMBED_STAMP.json against"
if exist "%EMBED_PYW%" if not defined EMBED_WHY for /f "skip=1 delims=" %%H in ('%SystemRoot%\System32\certutil.exe -hashfile "%RC_ROOT%\requirements.txt" SHA256 2^>nul') do if not defined EMBED_WANT set "EMBED_WANT=%%H"
if defined EMBED_WANT set "EMBED_WANT=%EMBED_WANT: =%"
if exist "%EMBED_PYW%" if not defined EMBED_WHY if not defined EMBED_WANT set "EMBED_WHY=certutil could not hash requirements.txt to check python-embed\EMBED_STAMP.json"
if exist "%EMBED_PYW%" if not defined EMBED_WHY if "%EMBED_WANT:~63,1%"=="" set "EMBED_WHY=certutil could not hash requirements.txt to check python-embed\EMBED_STAMP.json"
if exist "%EMBED_PYW%" if not defined EMBED_WHY if not "%EMBED_WANT:~64%"=="" set "EMBED_WHY=certutil could not hash requirements.txt to check python-embed\EMBED_STAMP.json"
if exist "%EMBED_PYW%" if not defined EMBED_WHY "%SystemRoot%\System32\findstr.exe" /i /l /c:"\"requirements_sha256\": \"%EMBED_WANT%\"" "%RC_ROOT%\python-embed\EMBED_STAMP.json" >nul 2>&1 && set "EMBED_OK=1"
if exist "%EMBED_PYW%" if not defined EMBED_OK if not defined EMBED_WHY set "EMBED_WHY=python-embed\EMBED_STAMP.json does not name the SHA-256 of this tree's requirements.txt, so it was built from another lock or the stamp is unreadable"
if defined EMBED_WHY echo %EMBED_WHY% - using pythonw.exe from PATH
if defined EMBED_OK (
    start "" "%EMBED_PYW%" "%RC_ROOT%\main.py"
) else (
    start "" pythonw.exe "%RC_ROOT%\main.py"
)
echo Done!
"%SystemRoot%\System32\timeout.exe" /t 3
