@echo off
setlocal
REM ============================================================
REM Install Legion's mkcert root CA into Game-PC's trust store.
REM
REM What this does:
REM   - Adds rc-mkcert-rootCA.pem to LocalMachine\Root via certutil.
REM   - After this runs, Edge / Chrome / Firefox on Game-PC trust
REM     the dashboard cert at https://192.168.8.230:8888/ with no
REM     warning click-through.
REM
REM This installs into the LOCAL MACHINE store (system-wide) so
REM both Edge and Chrome/Firefox pick it up. Requires admin
REM elevation (UAC will prompt).
REM
REM To run:
REM   1. Open Explorer to \\192.168.8.230\RCClient\  (or wherever
REM      this file landed) - same share Legion pushed it via.
REM      Or local copy at C:\RC-Agent\install-rc-rootca-on-gamepc.cmd.
REM   2. Right-click → Run as administrator.
REM   3. Watch the output, press a key when done.
REM ============================================================

echo.
echo === RC dashboard root CA install - Game-PC side ===
echo.

REM Verify admin.
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [error] Must be run as administrator. Right-click → Run as administrator.
    pause
    exit /b 1
)

REM Resolve cert path. RCClient is hosted on Game-PC ITSELF
REM (\\DESKTOP-3NT1UG3\RCClient ≡ \\192.168.8.237\RCClient). Legion pushes
REM files there from off-host; on Game-PC the files are local. We try, in order:
REM   1. Same directory as this script (most common - user double-clicked it
REM      from inside the RCClient share via Explorer).
REM   2. \\DESKTOP-3NT1UG3\RCClient\rc-mkcert-rootCA.pem (NetBIOS self-reference).
REM   3. \\192.168.8.237\RCClient\rc-mkcert-rootCA.pem (LAN IP self-reference).
REM   4. C:\RC-Agent\rc-mkcert-rootCA.pem (local copy if user staged it there).
set CERT=
for %%P in (
    "%~dp0rc-mkcert-rootCA.pem"
    "\\DESKTOP-3NT1UG3\RCClient\rc-mkcert-rootCA.pem"
    "\\192.168.8.237\RCClient\rc-mkcert-rootCA.pem"
    "C:\RC-Agent\rc-mkcert-rootCA.pem"
) do (
    if exist %%~P (
        set CERT=%%~P
        goto :found
    )
)
:found
if "%CERT%"=="" (
    echo [error] Couldn't find rc-mkcert-rootCA.pem next to this script,
    echo         on \\DESKTOP-3NT1UG3\RCClient\, on \\192.168.8.237\RCClient\,
    echo         or at C:\RC-Agent\.
    echo         Copy it from Legion: C:\Users\Administrator\AppData\Local\mkcert\rootCA.pem
    pause
    exit /b 1
)

echo Installing %CERT% into LocalMachine\Root...
echo.

certutil -addstore -f "Root" "%CERT%"
if %errorlevel% neq 0 (
    echo.
    echo [error] certutil failed with exit code %errorlevel%.
    pause
    exit /b %errorlevel%
)

echo.
echo === Verify ===
certutil -store "Root" | findstr /I "mkcert development CA Administrator@"
if %errorlevel% neq 0 (
    echo [warn] mkcert CA not visible after add. Restart browser to test anyway.
)

echo.
echo === Done ===
echo Open https://192.168.8.230:8888/ in Edge or Chrome on Game-PC.
echo The cert should be trusted with no warning. (Restart browsers if open.)
echo.
pause
endlocal
