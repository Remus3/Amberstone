@echo off
:: tools\preflight.cmd
:: Runs ruff lint + Python syntax check before a deploy.
:: Uses system Python (matches the deployed app runtime).
:: Run from C:\Riot Commander

setlocal
cd /d "C:\Riot Commander"

echo [preflight] Starting checks...
echo.

:: ── Ruff lint ─────────────────────────────────────────────────────────────
:: Try ruff from PATH first, fall back to known install locations
set RUFF=
where ruff >nul 2>&1 && set RUFF=ruff
if "%RUFF%"=="" if exist ".venv\Scripts\ruff.exe" set RUFF=.venv\Scripts\ruff.exe
if "%RUFF%"=="" (
    echo [preflight] WARN: ruff not found - install with: pip install ruff
    echo [preflight] Skipping lint check.
) else (
    echo [preflight] Ruff lint: %RUFF% check .
    %RUFF% check .
    if errorlevel 1 (
        echo [preflight] FAIL: Ruff found errors. Fix before deploying.
        exit /b 1
    )
    echo [preflight] Lint: OK
)

echo.

:: ── Python syntax check ───────────────────────────────────────────────────
:: Use system python (same as deployed app)
python -m compileall -q -x "ops[\\/]staging|ops[\\/]backups|ops[\\/]runtime|\.venv|__pycache__" .
if errorlevel 1 (
    echo [preflight] FAIL: Syntax errors found. Fix before deploying.
    exit /b 1
)
echo [preflight] Syntax: OK

echo.
echo [preflight] All checks passed.
exit /b 0
