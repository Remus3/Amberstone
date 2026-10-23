@echo off
setlocal

:: Option B launch: use embedded Python runtime if present,
:: fall back to PATH-based pythonw.exe if not (Option A compatibility).
set EMBED_PYW=%~dp0python-embed\pythonw.exe
set EMBED_PY=%~dp0python-embed\python.exe

:: Read the API key (RM-810) in the order of core\anthropic_key.py: an
:: inherited ANTHROPIC_API_KEY first when it is usable, else the first line of
:: API-Key-Claude.txt, else nothing. Usable = starts with sk-ant- once every
:: space is removed, and holds no double quote (the value crosses endlocal on
:: the last line through one percent expansion, where a quote would end the
:: quoted set and run the rest as a command). Delayed expansion and no
:: ( ... ) block: inside a block cmd expands percent variables once, when the
:: whole block is parsed, so the old in-block read saw the variable from
:: BEFORE set /p ran (no inherited one: the key became " ="). The same lines
:: are in scripts\restart.bat and scripts\start_debug.bat
:: (tests\test_launcher_key_read_rm810.py runs all three).
set API_FILE=%~dp0API-Key-Claude.txt
setlocal enabledelayedexpansion
set "RC_KEY="
if defined ANTHROPIC_API_KEY set "RC_KEY=!ANTHROPIC_API_KEY: =!"
if defined RC_KEY set "RC_NOQ=!RC_KEY:"=!"
if not "!RC_KEY:~0,7!"=="sk-ant-" set "RC_KEY="
if defined RC_KEY if not "!RC_NOQ!"=="!RC_KEY!" set "RC_KEY="
if not defined RC_KEY if exist "!API_FILE!" set /p RC_KEY=<"!API_FILE!"
if defined RC_KEY set "RC_KEY=!RC_KEY: =!"
if defined RC_KEY set "RC_NOQ=!RC_KEY:"=!"
if not "!RC_KEY:~0,7!"=="sk-ant-" set "RC_KEY="
if defined RC_KEY if not "!RC_NOQ!"=="!RC_KEY!" set "RC_KEY="
endlocal & set "ANTHROPIC_API_KEY=%RC_KEY%"

:: Validate key (the read above leaves the variable defined only when usable)
if not defined ANTHROPIC_API_KEY (
    echo Anthropic API key missing or invalid.
    echo Edit API-Key-Claude.txt with your key, or run install.bat
    pause
    exit /b 1
)

cd /d "%~dp0"

:: Prefer embedded runtime (Option B); fall back to PATH (Option A)
if exist "%EMBED_PYW%" (
    start "" "%EMBED_PYW%" main.py
) else (
    start "" pythonw.exe main.py
)
