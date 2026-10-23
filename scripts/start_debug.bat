@echo off
:: scripts\start_debug.bat - console launch with --debug. Lives in scripts\
:: (moved from the repo root 2026-10-09, MAIN 2246 sec 3); the repo root is
:: this file's parent folder.
setlocal
for %%I in ("%~dp0..") do set "RC_ROOT=%%~fI"
set RIOT_COMMANDER_DEBUG=1

cd /d "%RC_ROOT%"
:: RM-810 key check: the same lines as start.bat, which says why. A check
:: that cannot run leaves the variable alone and the launch goes ahead.
set "RC_KEY_EMBED=%RC_ROOT%\python-embed\python.exe"
set "RC_KEY_MOD=%RC_ROOT%\core\anthropic_key.py"
set "RC_KEY_PY="
if exist "%RC_KEY_EMBED%" set "RC_KEY_PY=%RC_KEY_EMBED%"
if not defined RC_KEY_PY for %%I in (python.exe) do set "RC_KEY_PY=%%~$PATH:I"
if not defined RC_KEY_PY call set "RC_KEY_SP=%%PATH:"=%%"
if not defined RC_KEY_PY for %%I in (python.exe) do set "RC_KEY_PY=%%~$RC_KEY_SP:I"
set "RC_KEY_SP="
set "RC_KEY_EC=none"
if defined RC_KEY_PY "%RC_KEY_PY%" -I -c "import os,runpy,sys;k=runpy.run_path(sys.argv[1]);e=os.environ.get(k['ENV_VAR'],'').strip();sys.exit(10 if k['usable_key'](e) else 11 if k['read_anthropic_key']() else 12)" "%RC_KEY_MOD%"
if defined RC_KEY_PY set RC_KEY_EC=%errorlevel%
if "%RC_KEY_EC%"=="11" set "ANTHROPIC_API_KEY="
if "%RC_KEY_EC%"=="12" set "ANTHROPIC_API_KEY="
set "RC_KEY_PY="
set "RC_KEY_EMBED="
set "RC_KEY_MOD="
set "RC_KEY_EC="
title Amberstone [DEBUG]
python.exe main.py --debug
pause
