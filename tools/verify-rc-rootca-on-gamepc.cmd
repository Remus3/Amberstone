@echo off
setlocal
REM ============================================================
REM Verify the mkcert root CA was installed correctly on Game-PC,
REM AND fully kill Chrome so the next launch isn't using the
REM cached "untrusted" verdict from before the install.
REM
REM Run this AFTER install-rc-rootca-on-gamepc.cmd. Right-click →
REM Run as administrator (needed to read LocalMachine\Root).
REM ============================================================

echo.
echo === Step 1: is mkcert root CA in LocalMachine\Root? ===
echo.

set FOUND_LM=0
certutil -store "Root" 2>nul | findstr /I /C:"mkcert" >nul
if %errorlevel% equ 0 (
    echo [ok] LocalMachine\Root has a mkcert entry.
    set FOUND_LM=1
) else (
    echo [miss] LocalMachine\Root has NO mkcert entry.
)

echo.
echo === Step 2: is it in CurrentUser\Root (wrong place)? ===
echo.

set FOUND_CU=0
certutil -user -store "Root" 2>nul | findstr /I /C:"mkcert" >nul
if %errorlevel% equ 0 (
    echo [warn] CurrentUser\Root has a mkcert entry — Chrome on modern
    echo        Windows ONLY trusts certs installed to LocalMachine\Root.
    echo        Re-run the installer elevated, or add to the right store:
    echo            certutil -addstore -f "Root" "\\192.168.8.230\RCClient\rc-mkcert-rootCA.pem"
    set FOUND_CU=1
)

echo.
echo === Step 3: full Chrome kill (background processes survive close-window) ===
echo.

REM Chrome keeps background helper processes after you close the window —
REM they hold the previous "untrusted" verdict for the URL. Kill them all.
taskkill /F /IM chrome.exe /T 2>nul
if %errorlevel% equ 0 (
    echo [ok] Chrome processes terminated.
) else (
    echo [info] No Chrome processes running.
)

REM Edge has the same caching behaviour.
taskkill /F /IM msedge.exe /T 2>nul
if %errorlevel% equ 0 (
    echo [ok] Edge processes terminated.
)

echo.
echo === Step 4: verdict ===
echo.

if "%FOUND_LM%"=="1" (
    echo Cert is in the right store.
    echo Open Chrome again and visit https://192.168.8.230:8888/ —
    echo it should load with the padlock and no warning.
    echo.
    echo If it STILL shows "Not Secure":
    echo   - In Chrome address bar: chrome://net-internals/#hsts
    echo     Under "Delete domain security policies" type 192.168.8.230
    echo     and click Delete. Then revisit the URL.
    echo   - Or visit chrome://flags/#test-third-party-cookie-phaseout-impact
    echo     and search "root store" — make sure no flag forces CRS-only.
) else (
    echo Cert is NOT in LocalMachine\Root yet.
    echo Run install-rc-rootca-on-gamepc.cmd as administrator first
    echo ^(right-click the .cmd, choose "Run as administrator"^).
)

echo.
pause
endlocal
