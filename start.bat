@echo off
setlocal

:: Option B launch: use embedded Python runtime if present,
:: fall back to PATH-based pythonw.exe if not (Option A compatibility).
set EMBED_PYW=%~dp0python-embed\pythonw.exe
set EMBED_PY=%~dp0python-embed\python.exe

:: RM-810 key check. This file never reads, parses, prints or sets the key:
:: core\anthropic_key.py, the one lookup every Python reader uses, decides
:: (an inherited ANTHROPIC_API_KEY when usable, else API-Key-Claude.txt). It
:: runs by path with python -I and exits 0 when the inherited variable is
:: usable, 2 when that variable is absent or unusable but the key file is
:: usable, 3 when no usable key exists. On 2 and 3 the inherited variable is
:: cleared, so junk never shadows the key file in any reader; the app then
:: reads the file itself. Any other exit means the check could not run.
:: (The old read parsed the key here inside a ( ... ) block, where cmd
:: expands a variable when the block is parsed, before set /p ran: with no
:: inherited variable the key became " =".) The same lines are in
:: scripts\restart.bat and scripts\start_debug.bat; the check uses the
:: interpreter this file launches with.
:: tests\test_launcher_key_read_rm810.py runs all three.
set "RC_KEY_PY=python"
if exist "%EMBED_PY%" set "RC_KEY_PY=%EMBED_PY%"
set "RC_KEY_MOD=%~dp0core\anthropic_key.py"
"%RC_KEY_PY%" -I -c "import os,runpy,sys;k=runpy.run_path(sys.argv[1]);e=os.environ.get(k['ENV_VAR'],'').strip();sys.exit(0 if k['usable_key'](e) else 2 if k['read_anthropic_key']() else 3)" "%RC_KEY_MOD%"
set RC_KEY_EC=%errorlevel%
if "%RC_KEY_EC%"=="2" set "ANTHROPIC_API_KEY="
if "%RC_KEY_EC%"=="3" set "ANTHROPIC_API_KEY="
set "RC_KEY_PY="
set "RC_KEY_MOD="

:: Validate key
if "%RC_KEY_EC%"=="3" (
    echo Anthropic API key missing or invalid.
    echo Edit API-Key-Claude.txt with your key, or run install.bat
    pause
    exit /b 1
)
if not "%RC_KEY_EC%"=="0" if not "%RC_KEY_EC%"=="2" (
    echo Could not check the Anthropic API key - is Python installed? Run install.bat
    pause
    exit /b 1
)
set "RC_KEY_EC="

cd /d "%~dp0"

:: Prefer embedded runtime (Option B); fall back to PATH (Option A)
if exist "%EMBED_PYW%" (
    start "" "%EMBED_PYW%" main.py
) else (
    start "" pythonw.exe main.py
)
