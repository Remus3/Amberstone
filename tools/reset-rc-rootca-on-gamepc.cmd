@echo off
setlocal EnableDelayedExpansion
REM ============================================================
REM Hard reset for the mkcert root CA trust on Game-PC.
REM
REM Symptom: chrome://settings/certificates shows the cert in
REM multiple places, but Chrome still flags https://192.168.8.230
REM as Not Secure. This is what to run.
REM
REM What this does:
REM   1. Deletes EVERY copy of "mkcert" CA from:
REM        LocalMachine\Root        (system trusted roots)
REM        LocalMachine\CA          (system intermediate CAs)
REM        LocalMachine\AuthRoot    (third-party trusted roots)
REM        CurrentUser\Root         (per-user trusted roots)
REM        CurrentUser\CA
REM        CurrentUser\AuthRoot
REM   2. Re-adds ONE clean copy into LocalMachine\Root.
REM   3. Kills every chrome.exe and msedge.exe so the next launch
REM      builds a fresh trust verdict.
REM
REM Run elevated. Right-click → Run as administrator.
REM ============================================================

echo.
echo === RC dashboard root CA - hard reset ===
echo.

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [error] Must run as administrator. Right-click → Run as administrator.
    pause
    exit /b 1
)

REM Find cert.
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
    echo [error] rc-mkcert-rootCA.pem not found. Aborting.
    pause
    exit /b 1
)
echo Cert source: %CERT%
echo.

REM Resolve the cert thumbprint we expect - we delete by thumbprint to
REM avoid wiping unrelated CAs that happen to match a substring search.
for /f "tokens=*" %%H in ('certutil -dump "%CERT%" ^| findstr /I /C:"Cert Hash(sha1)"') do (
    set HASHLINE=%%H
)
REM HASHLINE looks like: "Cert Hash(sha1): aabbccdd ee ff ..."
REM Extract just the hex (no spaces).
set THUMB=!HASHLINE:Cert Hash(sha1):=!
set THUMB=!THUMB: =!
echo Cert thumbprint (sha1): %THUMB%
echo.

echo === Step 1: removing every mkcert copy from all stores ===
echo.

REM PowerShell sweep - finds and deletes by issuer-substring AND thumbprint
REM across every common store on both LocalMachine and CurrentUser.
REM 2026-04-28: previous version built the Remove-Item path manually from
REM PSParentPath which produced a malformed string ('Cert:\:\CurrentUser\...')
REM and silently failed. Switched to pipeline Remove-Item which deletes
REM via the real PSPath.
powershell -NoProfile -Command ^
    "$thumb = '%THUMB%';" ^
    "$paths = @(" ^
    "  'Cert:\LocalMachine\Root', 'Cert:\LocalMachine\CA', 'Cert:\LocalMachine\AuthRoot'," ^
    "  'Cert:\CurrentUser\Root',  'Cert:\CurrentUser\CA',  'Cert:\CurrentUser\AuthRoot'" ^
    ");" ^
    "$total = 0;" ^
    "foreach ($p in $paths) {" ^
    "  Get-ChildItem $p -ErrorAction SilentlyContinue |" ^
    "    Where-Object { $_.Subject -match 'mkcert' -or $_.Issuer -match 'mkcert' -or ($thumb -and $_.Thumbprint -eq $thumb) } |" ^
    "    ForEach-Object {" ^
    "      Write-Host ('  delete '+$_.PSPath+' '+$_.Subject);" ^
    "      $_ | Remove-Item -Force -ErrorAction SilentlyContinue;" ^
    "      $total++" ^
    "    }" ^
    "};" ^
    "Write-Host ('Removed '+$total+' entry(s).')"

echo.
echo === Step 2: adding one clean copy to LocalMachine\Root ===
echo.

certutil -addstore -f "Root" "%CERT%"
if %errorlevel% neq 0 (
    echo [error] certutil add failed. Exit %errorlevel%.
    pause
    exit /b %errorlevel%
)

echo.
echo === Step 3: verify what's now in the right place ===
echo.

powershell -NoProfile -Command ^
    "Get-ChildItem 'Cert:\LocalMachine\Root' -ErrorAction SilentlyContinue |" ^
    "  Where-Object { $_.Subject -match 'mkcert' -or $_.Issuer -match 'mkcert' } |" ^
    "  ForEach-Object { Write-Host ('  LocalMachine\Root: '+$_.Thumbprint+' '+$_.Subject) };" ^
    "Get-ChildItem 'Cert:\CurrentUser\Root' -ErrorAction SilentlyContinue |" ^
    "  Where-Object { $_.Subject -match 'mkcert' -or $_.Issuer -match 'mkcert' } |" ^
    "  ForEach-Object { Write-Host ('  CurrentUser\Root (should be empty): '+$_.Thumbprint+' '+$_.Subject) }"

echo.
echo === Step 4: kill every Chrome / Edge process ===
echo.
taskkill /F /IM chrome.exe /T >nul 2>&1 && echo   chrome.exe processes killed.
taskkill /F /IM msedge.exe /T >nul 2>&1 && echo   msedge.exe processes killed.

echo.
echo === Step 5: clear Chrome HSTS for 192.168.8.230 ===
echo.
echo  After Chrome relaunches, paste this in the address bar:
echo.
echo      chrome://net-internals/#hsts
echo.
echo  Under "Delete domain security policies", type:
echo      192.168.8.230
echo  and click Delete. This clears any pinned-cert state Chrome learned
echo  from the earlier failed visits.
echo.
echo  Then visit: https://192.168.8.230:8888/
echo  Should padlock cleanly.
echo.
pause
endlocal
