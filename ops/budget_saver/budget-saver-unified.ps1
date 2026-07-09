param(
    [ValidateSet("Local","Smart")]
    [string]$Tier = "Local",
    [Parameter(ValueFromRemainingArguments=$true)] $Rest
)
$ErrorActionPreference = "Stop"
$BudgetRoot = "C:\Riot Commander\ops\budget_saver"
. (Join-Path $BudgetRoot "env.local.ps1")

# -- project picker --
Write-Host ""
Write-Host "  ========================================" -ForegroundColor Cyan
Write-Host "   Budget-Saver Unified Launcher"          -ForegroundColor Cyan
Write-Host "  ========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Project:" -ForegroundColor Yellow
Write-Host "    [R]  Riot Commander   (C:\Riot Commander)"
Write-Host "    [L]  Sibling-A (C:\Sibling-A)"
Write-Host ""
Write-Host "  Tier:" -ForegroundColor Yellow
Write-Host "    [1]  Local  (llama3.1:8b - keep-lights-on)"
Write-Host "    [2]  Smart  (DeepSeek-pro - real work)"
Write-Host ""

$projKey = Read-Host "  Project [R/L]"
$tierKey = Read-Host "  Tier    [1/2]"

switch ($projKey.ToLower()) {
    "r" {
        $ProjectRoot = "C:\Riot Commander"
        $ClaudeMd    = Join-Path $ProjectRoot "CLAUDE.md"
        $ClaudeBak   = Join-Path $ProjectRoot "CLAUDE.md.full"
        $LeanMd      = Join-Path $BudgetRoot "LEAN_CLAUDE.md"
        $McpConfig   = Join-Path $BudgetRoot "lean-mcp.json"
        $Settings    = Join-Path $BudgetRoot "lean-settings.json"
        $ProjectName = "Riot Commander"
    }
    "l" {
        $ProjectRoot = "C:\Sibling-A"
        $LwBudget    = Join-Path $ProjectRoot "ops\budget_saver"
        $ClaudeMd    = Join-Path $ProjectRoot "CLAUDE.md"
        $ClaudeBak   = Join-Path $ProjectRoot "CLAUDE.md.full"
        $LeanMd      = Join-Path $LwBudget "LEAN_CLAUDE.md"
        $McpConfig   = Join-Path $LwBudget "lean-mcp.json"
        $Settings    = Join-Path $LwBudget "lean-settings.json"
        $ProjectName = "Sibling-A"
    }
    default {
        Write-Host "  Invalid choice '$projKey' - valid: R or L" -ForegroundColor Red
        Read-Host "  Press Enter to exit"
        exit 1
    }
}

switch ($tierKey) {
    "1" { $ModelTier = "Local"  }
    "2" { $ModelTier = "Smart"  }
    default {
        Write-Host "  Invalid choice '$tierKey' - valid: 1 or 2" -ForegroundColor Red
        Read-Host "  Press Enter to exit"
        exit 1
    }
}

# -- model config --
if ($ModelTier -eq "Smart") {
    $env:ANTHROPIC_MODEL               = "rc-deepseek-pro"
    $env:ANTHROPIC_DEFAULT_HAIKU_MODEL = "rc-deepseek"
    $env:MAX_THINKING_TOKENS           = ""     # DeepSeek has thinking
    $StateModel = "rc-deepseek-pro"
    $TierLabel  = "smart"
} else {
    $env:ANTHROPIC_MODEL               = "rc-main"
    $env:ANTHROPIC_DEFAULT_HAIKU_MODEL = "rc-background"
    $env:MAX_THINKING_TOKENS           = "0"
    $StateModel = "rc-main"
    $TierLabel  = "local"
}

$env:ANTHROPIC_BASE_URL    = "http://127.0.0.1:4000"
$env:ANTHROPIC_AUTH_TOKEN  = $env:LITELLM_MASTER_KEY

# -- verify proxy up --
try { Invoke-WebRequest "http://127.0.0.1:4000/health/liveliness" -TimeoutSec 3 | Out-Null }
catch { Write-Warning "LiteLLM proxy not reachable on :4000 - run start-proxy.ps1 first." }

# -- verify lean files exist --
if (-not (Test-Path $LeanMd))    { throw "Missing: $LeanMd" }
if (-not (Test-Path $McpConfig)) { throw "Missing: $McpConfig" }
if (-not (Test-Path $Settings))  { throw "Missing: $Settings" }

# -- context swap --
if (Test-Path $ClaudeBak) {
    Write-Warning "CLAUDE.md.full still exists (prior crash? restoring before swap)"
    Copy-Item $ClaudeBak $ClaudeMd -Force
    Remove-Item $ClaudeBak
}
Copy-Item $ClaudeMd $ClaudeBak
Copy-Item $LeanMd $ClaudeMd -Force

Write-Host ""
Write-Host "  Project : $ProjectName ($ProjectRoot)" -ForegroundColor Green
Write-Host "  Tier    : $TierLabel ($StateModel)"        -ForegroundColor Green
Write-Host "  Launching Claude Code..."                   -ForegroundColor Green
Write-Host ""

# -- launch --
Push-Location $ProjectRoot
try {
    & $BudgetRoot\.venv\Scripts\python.exe -c "import sys; sys.path.insert(0,r'$BudgetRoot'); import state; state.write('$TierLabel','$StateModel')"
    claude --strict-mcp-config --mcp-config $McpConfig --settings $Settings @Rest
} finally {
    Pop-Location
    if (Test-Path $ClaudeBak) {
        Copy-Item $ClaudeBak $ClaudeMd -Force
        Remove-Item $ClaudeBak
        Write-Host "[budget-saver] restored full CLAUDE.md" -ForegroundColor Gray
    }
}
