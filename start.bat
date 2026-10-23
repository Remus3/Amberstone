@echo off
setlocal

:: Option B launch: use embedded Python runtime if present,
:: fall back to PATH-based pythonw.exe if not (Option A compatibility).
set EMBED_PYW=%~dp0python-embed\pythonw.exe

cd /d "%~dp0"

:: RM-810 key check. This file never reads, parses, prints or sets the key:
:: core\anthropic_key.py, the one lookup every Python reader uses, decides
:: (an inherited ANTHROPIC_API_KEY when usable, else API-Key-Claude.txt). It
:: runs by path under python -I and exits 10 when the inherited variable is
:: usable, 11 when that variable is absent or unusable but the key file is
:: usable, 12 when no usable key exists - codes no interpreter emits on its
:: own, so any other exit means the check could not run. On 11 and 12 the
:: inherited variable is cleared, so junk never shadows the key file in any
:: reader; the app then reads the file itself. The interpreter is an
:: absolute path, python-embed first, else python.exe searched on PATH only
:: (a quote-stripped copy of it: the PATH-only search finds nothing in a
:: quoted entry), and the check runs after the cd above: a bare "python" was
:: looked up in the caller's folder first, where a planted python.bat would
:: run. (The old
:: read parsed the key inside a ( ... ) block, where cmd expands a variable
:: when the block is parsed, before set /p ran: with no inherited variable
:: the key became " =".) The same lines are in scripts\restart.bat and
:: scripts\start_debug.bat; tests\test_launcher_key_read_rm810.py runs all
:: three.
set "RC_KEY_EMBED=%~dp0python-embed\python.exe"
set "RC_KEY_MOD=%~dp0core\anthropic_key.py"
set "RC_KEY_PY="
if exist "%RC_KEY_EMBED%" set "RC_KEY_PY=%RC_KEY_EMBED%"
set "RC_KEY_SP=%PATH:"=%"
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

:: Validate key
if "%RC_KEY_EC%"=="12" (
    echo Anthropic API key missing or invalid.
    echo Edit API-Key-Claude.txt with your key, or run install.bat
    pause
    exit /b 1
)
if not "%RC_KEY_EC%"=="10" if not "%RC_KEY_EC%"=="11" (
    echo Could not check the Anthropic API key - is Python installed? Run install.bat
    pause
    exit /b 1
)
set "RC_KEY_EC="

:: Prefer embedded runtime (Option B); fall back to PATH (Option A)
if exist "%EMBED_PYW%" (
    start "" "%EMBED_PYW%" main.py
) else (
    start "" pythonw.exe main.py
)
