@echo off
:: tools\snapshot.cmd
:: Creates a timestamped git checkpoint commit of the current repo state.
:: Safe to run at any time - no-op if nothing has changed.
:: Run from C:\Riot Commander

setlocal
cd /d "C:\Riot Commander"

:: Get timestamp
for /f "tokens=*" %%T in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd_HH-mm-ss"') do set TS=%%T

echo [snapshot] Staging all changes...
git add -A

:: Check if there's anything to commit
git diff --cached --quiet
if %errorlevel%==0 (
    echo [snapshot] Nothing to commit - working tree clean.
    exit /b 0
)

echo [snapshot] Committing checkpoint %TS%...
git commit -m "checkpoint %TS%"

if errorlevel 1 (
    echo [snapshot] FAIL: git commit failed.
    exit /b 1
)

echo [snapshot] Done. Use tools\rollback_last.cmd to undo.
exit /b 0
