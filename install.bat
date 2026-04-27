@echo off
setlocal enabledelayedexpansion
title Riot Commander Setup
color 0A

:: Option B: detect embedded Python runtime
set EMBED_PY=%~dp0python-embed\python.exe
set OPTION_B=0
if exist "%EMBED_PY%" set OPTION_B=1

:: Create logs dir first so temp files can always be written
if not exist "%~dp0logs" mkdir "%~dp0logs" 2>nul

:: Step result log
set LOG_FILE=%~dp0logs\_setup_results.txt
if exist "%LOG_FILE%" del "%LOG_FILE%" 2>nul
echo. >> "%LOG_FILE%"

set ERRORS=0
set PY_VER=unknown

echo.
echo  ================================================
echo    RIOT COMMANDER - SETUP
echo  ================================================
echo.

:: 
:: STEP 1 -- Python
:: 
echo [1/6] Checking Python installation...
if "%OPTION_B%"=="1" (
    echo  [OK]   Embedded Python found: %EMBED_PY%
    echo  [OK]   Step 1 - Embedded Python ^(Option B^) >> "%LOG_FILE%"
    :: Use embedded python for version check
    for /f "tokens=2 delims= " %%v in ('"%EMBED_PY%" --version 2^>^&1') do set PY_VER=%%v
    echo  [OK]   Python %PY_VER% ^(embedded^)
    goto :STEP2
)
:: Option A: check system PATH python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    color 0C
    echo.
    echo  [FAIL] Python not found. No embedded runtime and no system Python on PATH.
    echo.
    echo  Option B ^(recommended^): ensure python-embed\ is present in this folder.
    echo  Option A ^(fallback^): install Python 3.10+ from https://python.org/downloads
    echo.
    echo  [FAIL] Step 1 - Python not found >> "%LOG_FILE%"
    set ERRORS=1
    goto :SUMMARY
)
for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PY_VER=%%v
echo  [OK]   Python %PY_VER% found ^(system PATH^)
echo  [OK]   Step 1 - Python %PY_VER% found ^(Option A^) >> "%LOG_FILE%"

:STEP2

:: 
:: STEP 2 -- pip packages
:: 
echo.
echo [2/6] Checking required packages ^(anthropic, Pillow^)...
echo       This may take a moment on first install...

set PIP_LOG=%~dp0logs\_pip_install.tmp

if "%OPTION_B%"=="1" (
    :: Option B: packages are pre-installed in embedded runtime
    "%EMBED_PY%" -c "import anthropic, PIL" >nul 2>&1
    if %errorlevel% neq 0 (
        echo  [INFO]  Packages missing from embedded runtime, installing...
        "%EMBED_PY%" -m pip install -r "%~dp0requirements.txt" --quiet >"%PIP_LOG%" 2>&1
    )
    "%EMBED_PY%" -c "import anthropic, PIL" >nul 2>&1
    set IMPORT_EC=%errorlevel%
) else (
    python -m pip install --upgrade pip --quiet >nul 2>&1
    python -m pip install -r "%~dp0requirements.txt" --quiet >"%PIP_LOG%" 2>&1
    python -c "import anthropic, PIL" >nul 2>&1
    set IMPORT_EC=%errorlevel%
)

if %IMPORT_EC% neq 0 (
    color 0C
    echo  [FAIL] Package install failed - anthropic or Pillow could not be imported.
    echo.
    if exist "%PIP_LOG%" (
        echo  pip output:
        echo  ----------------------------------------
        type "%PIP_LOG%"
        echo  ----------------------------------------
    )
    echo.
    echo  Common causes:
    echo    - No internet connection
    echo    - Firewall blocking pip
    echo    - Run: python -m ensurepip   then re-run setup
    echo  [FAIL] Step 2 - packages could not be imported after install >> "%LOG_FILE%"
    set ERRORS=1
    goto :SUMMARY
)

echo  [OK]   anthropic and Pillow installed and verified
echo  [OK]   Step 2 - anthropic + Pillow installed >> "%LOG_FILE%"
if exist "%PIP_LOG%" del "%PIP_LOG%" 2>nul

:: 
:: STEP 3 -- API Key
:: 
echo.
echo [3/6] Reading Anthropic API Key...
set API_FILE=%~dp0API-Key-Claude.txt

if not exist "%API_FILE%" (
    color 0E
    echo  [WARN] API-Key-Claude.txt not found - creating template.
    echo sk-ant-YOUR-KEY-HERE> "%API_FILE%"
    echo.
    echo  Opening file. Paste your key, save it, then re-run setup.
    notepad "%API_FILE%"
    echo  [FAIL] Step 3 - API key file was missing ^(template created^) >> "%LOG_FILE%"
    set ERRORS=1
    goto :SUMMARY
)

set /p API_KEY=<"%API_FILE%"
set API_KEY=%API_KEY: =%

if "%API_KEY%"=="" (
    color 0C
    echo  [FAIL] API-Key-Claude.txt is empty.
    echo         Paste your Anthropic API key into the file and re-run setup.
    notepad "%API_FILE%"
    echo  [FAIL] Step 3 - API key file was empty >> "%LOG_FILE%"
    set ERRORS=1
    goto :SUMMARY
)

if "%API_KEY:~0,7%" neq "sk-ant-" (
    color 0C
    echo  [FAIL] API key format invalid.
    echo.
    echo         Key does not start with sk-ant-
    echo.
    echo         Get your key at: https://console.anthropic.com/keys
    echo         Opening file - paste the correct key and re-run.
    notepad "%API_FILE%"
    echo  [FAIL] Step 3 - API key format invalid >> "%LOG_FILE%"
    set ERRORS=1
    goto :SUMMARY
)

rem AUDIT-OPUS SEC-001 fix: no longer echo last-4 chars of API key to console
rem or log.  Previously leaked %KEY_TAIL% to logs\_setup_results.txt.
echo  [OK]   API key valid  ^(sk-ant-***^)
echo  [OK]   Step 3 - API key loaded ^(sk-ant-***^) >> "%LOG_FILE%"

:: 
:: STEP 4 -- Environment variable
:: 
echo.
echo [4/6] Saving ANTHROPIC_API_KEY to user environment...
setx ANTHROPIC_API_KEY "%API_KEY%" >nul 2>&1
if %errorlevel% neq 0 (
    echo  [WARN] setx failed - key will load from file at each launch instead.
    echo         This is non-fatal. start.bat reads API-Key-Claude.txt directly.
    echo  [WARN] Step 4 - setx failed ^(non-fatal, key loads from file^) >> "%LOG_FILE%"
) else (
    echo  [OK]   ANTHROPIC_API_KEY saved to user environment
    echo  [OK]   Step 4 - ANTHROPIC_API_KEY saved to user environment >> "%LOG_FILE%"
)

:: 
:: STEP 5 -- Directories
:: 
echo.
echo [5/6] Creating runtime directories...
set DIR_ERRORS=0

for %%D in (data logs config) do (
    if not exist "%~dp0%%D" (
        mkdir "%~dp0%%D" 2>nul
        if !errorlevel! neq 0 (
            echo  [FAIL] Could not create: %%D\
            set DIR_ERRORS=1
        ) else (
            echo  [OK]   Created:  %%D\
        )
    ) else (
        echo  [OK]   Exists:   %%D\
    )
)

if %DIR_ERRORS% neq 0 (
    echo.
    echo  Check write permissions on: %~dp0
    echo  [FAIL] Step 5 - directory creation failed >> "%LOG_FILE%"
    set ERRORS=1
    goto :SUMMARY
)
echo  [OK]   Step 5 - all directories ready >> "%LOG_FILE%"

:: 
:: STEP 6 -- Runtime config
:: 
echo.
echo [6/6] Writing launch configuration...
(
echo {
echo   "install_path": "%~dp0",
echo   "api_key_file": "API-Key-Claude.txt",
echo   "python": "python",
echo   "first_run_complete": true
echo }
) > "%~dp0config\runtime.json" 2>nul

if %errorlevel% neq 0 (
    echo  [WARN] Could not write config\runtime.json ^(non-fatal^)
    echo  [WARN] Step 6 - runtime.json write failed ^(non-fatal^) >> "%LOG_FILE%"
) else (
    echo  [OK]   config\runtime.json written
    echo  [OK]   Step 6 - configuration written >> "%LOG_FILE%"
)

:: 
:: SUMMARY
:: 
:SUMMARY
echo.
echo  ================================================

if %ERRORS% equ 0 goto :SHOW_SUCCESS
goto :SHOW_FAILURE

:SHOW_SUCCESS
color 0A
echo    SETUP COMPLETE - Everything looks good!
echo  ================================================
echo.
echo  STEP RESULTS:
type "%LOG_FILE%"
echo.
echo  HOW TO LAUNCH:
echo    start.bat          Run normally ^(no console^)
echo    start_debug.bat    Run with console + verbose log
echo.
echo  WHAT WAS INSTALLED:
echo    Python %PY_VER%
echo    anthropic SDK + Pillow image library
echo    API key stored in environment and API-Key-Claude.txt
echo    Folders: data\  logs\  config\
echo.
echo  To change your API key later:
echo    1. Paste the new key into API-Key-Claude.txt
echo    2. Re-run install.bat
echo.
pause
exit /b 0

:SHOW_FAILURE
color 0C
echo    SETUP INCOMPLETE - One or more steps failed
echo  ================================================
echo.
echo  STEP RESULTS:
type "%LOG_FILE%"
echo.
echo  Review the errors above, fix the issue,
echo  then re-run install.bat to try again.
echo.
echo  For help, check the logs\ folder for details.
echo.
pause
exit /b 1
