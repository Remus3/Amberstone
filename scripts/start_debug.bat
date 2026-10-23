@echo off
:: scripts\start_debug.bat - console launch with --debug. Lives in scripts\
:: (moved from the repo root 2026-10-09, MAIN 2246 sec 3); the repo root is
:: this file's parent folder.
setlocal
for %%I in ("%~dp0..") do set "RC_ROOT=%%~fI"

:: RM-810 key check: the same lines as start.bat, which says why. A check
:: that cannot run leaves the variable alone and the launch goes ahead.
set "RC_KEY_PY=python.exe"
set "RC_KEY_MOD=%RC_ROOT%\core\anthropic_key.py"
"%RC_KEY_PY%" -I -c "import os,runpy,sys;k=runpy.run_path(sys.argv[1]);e=os.environ.get(k['ENV_VAR'],'').strip();sys.exit(0 if k['usable_key'](e) else 2 if k['read_anthropic_key']() else 3)" "%RC_KEY_MOD%"
set RC_KEY_EC=%errorlevel%
if "%RC_KEY_EC%"=="2" set "ANTHROPIC_API_KEY="
if "%RC_KEY_EC%"=="3" set "ANTHROPIC_API_KEY="
set "RC_KEY_PY="
set "RC_KEY_MOD="
set "RC_KEY_EC="
set RIOT_COMMANDER_DEBUG=1

cd /d "%RC_ROOT%"
title Amberstone [DEBUG]
python.exe main.py --debug
pause
