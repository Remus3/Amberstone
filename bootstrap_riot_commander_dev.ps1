param(
    [string]$Root = "C:\Riot Commander"
)

$ErrorActionPreference = "Stop"

function Write-Step([string]$Message) {
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Ensure-Dir([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType Directory -Force -Path $Path | Out-Null
    }
}

function Install-WingetPackage([string]$Id) {
    Write-Step "Installing or upgrading $Id"
    winget install --id $Id -e --source winget --silent --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) {
        throw "winget failed for $Id (exit $LASTEXITCODE)"
    }
}

function Find-Git() {
    $cmd = Get-Command git.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }

    $candidates = @(
        "C:\Program Files\Git\cmd\git.exe",
        "C:\Program Files\Git\bin\git.exe",
        "C:\Program Files (x86)\Git\cmd\git.exe",
        "C:\Program Files (x86)\Git\bin\git.exe"
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) { return $candidate }
    }
    return $null
}

if (-not (Test-Path -LiteralPath $Root)) {
    throw "Project root not found: $Root"
}

Write-Step "Installing core Windows tools"
$packages = @(
    "Git.Git",
    "Microsoft.PowerShell",
    "astral-sh.uv",
    "BurntSushi.ripgrep.MSVC",
    "jqlang.jq"
)

foreach ($pkg in $packages) {
    Install-WingetPackage $pkg
}

Write-Step "Creating Python virtual environment"
$venv = Join-Path $Root ".venv"
if (-not (Test-Path -LiteralPath $venv)) {
    & py -3.14 -m venv $venv
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create venv with py -3.14. Install Python 3.14 or adjust the script."
    }
}

$python = Join-Path $venv "Scripts\python.exe"
$pip = @(
    "-m", "pip", "install", "--upgrade",
    "pip",
    "wheel",
    "anthropic",
    "httpx",
    "orjson",
    "tenacity",
    "psutil",
    "pywin32",
    "mss",
    "watchfiles",
    "pydantic-settings",
    "ruff"
)

Write-Step "Installing Python packages into .venv"
& $python $pip
if ($LASTEXITCODE -ne 0) {
    throw "pip install failed"
}

$pywinPost = Join-Path (Split-Path $python -Parent) "pywin32_postinstall.py"
if (Test-Path $pywinPost) {
    Write-Step "Running pywin32 post-install"
    & $python $pywinPost -install
}

Write-Step "Creating project directories"
$dirs = @(
    "ops",
    "ops\staging",
    "ops\backups",
    "ops\runtime",
    "ops\runtime\deploy_requests",
    "ops\runtime\deploy_results",
    "ops\runtime\health",
    "ops\bridge",
    "ops\bridge\requests",
    "ops\bridge\results",
    "tools"
)

foreach ($dir in $dirs) {
    Ensure-Dir (Join-Path $Root $dir)
}

Write-Step "Writing requirements-dev.txt"
@'
anthropic
httpx
orjson
tenacity
psutil
pywin32
mss
watchfiles
pydantic-settings
ruff
'@ | Set-Content -LiteralPath (Join-Path $Root "requirements-dev.txt") -Encoding UTF8

Write-Step "Writing ruff.toml"
@'
target-version = "py39"
line-length = 100

[lint]
select = ["E", "F", "I", "UP", "B"]
ignore = ["E501"]

[format]
quote-style = "double"
indent-style = "space"
line-ending = "lf"
'@ | Set-Content -LiteralPath (Join-Path $Root "ruff.toml") -Encoding UTF8

Write-Step "Writing .gitignore"
@'
# Secrets
API-Key-Claude.txt
.env
.env.*
*.secret
*.secrets.json

# Python
.venv/
__pycache__/
*.pyc
*.pyo
*.pyd

# Logs and temp
logs/
*.log
restart_trigger.txt
apply_patches.py

# Runtime state
ops/runtime/health/
ops/runtime/deploy_results/
ops/bridge/results/
data/coaching_data.json
data/tft_coaching_data.json
data/tft_live_data.json
data/comp_state.json
data/ratings/
data/match_history.db

# Build / cache
.pytest_cache/
.ruff_cache/
.mypy_cache/
'@ | Set-Content -LiteralPath (Join-Path $Root ".gitignore") -Encoding UTF8

Write-Step "Writing tools\\preflight.cmd"
@'
@echo off
setlocal
cd /d C:\Riot Commander
.\.venv\Scripts\ruff.exe check .
if errorlevel 1 exit /b 1
.\.venv\Scripts\python.exe -m compileall -q .
if errorlevel 1 exit /b 1
echo PRECHECK OK
'@ | Set-Content -LiteralPath (Join-Path $Root "tools\preflight.cmd") -Encoding ASCII

Write-Step "Writing tools\\snapshot.cmd"
@'
@echo off
setlocal
cd /d C:\Riot Commander
for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd_HH-mm-ss"') do set TS=%%I
git add -A
git commit --allow-empty -m "checkpoint %TS%"
'@ | Set-Content -LiteralPath (Join-Path $Root "tools\snapshot.cmd") -Encoding ASCII

Write-Step "Writing tools\\rollback_last.cmd"
@'
@echo off
setlocal
cd /d C:\Riot Commander
git reset --hard HEAD~1
'@ | Set-Content -LiteralPath (Join-Path $Root "tools\rollback_last.cmd") -Encoding ASCII

Write-Step "Initializing git repository"
$git = Find-Git
if (-not $git) {
    throw "git.exe not found after installation"
}

& $git config --global core.longpaths true
& $git config --global core.autocrlf false

$userName = (& $git config --global user.name 2>$null)
if (-not $userName) {
    & $git config --global user.name "Riot Commander AI"
}

$userEmail = (& $git config --global user.email 2>$null)
if (-not $userEmail) {
    & $git config --global user.email "riot-commander@local"
}

if (-not (Test-Path -LiteralPath (Join-Path $Root ".git"))) {
    & $git -C $Root init -b main
}

& $git -C $Root add -A
try {
    & $git -C $Root commit --allow-empty -m "checkpoint: baseline dev stack"
} catch {
    Write-Host "Initial commit skipped or already up to date." -ForegroundColor Yellow
}

Write-Step "Done"
Write-Host ""
Write-Host "Next commands:" -ForegroundColor Green
Write-Host "  C:\Riot Commander\tools\preflight.cmd"
Write-Host "  C:\Riot Commander\tools\snapshot.cmd"
Write-Host "  C:\Riot Commander\tools\rollback_last.cmd"
