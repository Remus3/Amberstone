@echo off
:: scripts\restart.bat - kill and relaunch Amberstone. Lives in scripts\
:: (moved from the repo root 2026-10-09, MAIN 2246 sec 3); the repo root is
:: this file's parent folder.
echo [Amberstone] Restarting...
wmic process where "commandline like '%%main.py%%'" delete >nul 2>&1
taskkill /F /IM pythonw.exe >nul 2>&1
timeout /t 2 /nobreak >nul

setlocal
for %%I in ("%~dp0..") do set "RC_ROOT=%%~fI"
:: RM-810 key check: the same lines as start.bat, which says why. A check
:: that cannot run leaves the variable alone and the relaunch goes ahead.
set "RC_KEY_PY=python"
set "RC_KEY_MOD=%RC_ROOT%\core\anthropic_key.py"
"%RC_KEY_PY%" -I -c "import os,runpy,sys;k=runpy.run_path(sys.argv[1]);e=os.environ.get(k['ENV_VAR'],'').strip();sys.exit(0 if k['usable_key'](e) else 2 if k['read_anthropic_key']() else 3)" "%RC_KEY_MOD%"
set RC_KEY_EC=%errorlevel%
if "%RC_KEY_EC%"=="2" set "ANTHROPIC_API_KEY="
if "%RC_KEY_EC%"=="3" set "ANTHROPIC_API_KEY="
set "RC_KEY_PY="
set "RC_KEY_MOD="
set "RC_KEY_EC="
cd /d "%RC_ROOT%"
:: Apply any pending patches
if exist "apply_patches.py" (
    echo [Amberstone] Applying patches...
    python apply_patches.py
)
start "" pythonw.exe main.py
echo [Amberstone] Relaunched.
