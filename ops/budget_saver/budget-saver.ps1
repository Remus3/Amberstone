param([Parameter(ValueFromRemainingArguments=$true)] $Rest)
$ErrorActionPreference = "Stop"
$Root = "C:\Riot Commander\ops\budget_saver"
. (Join-Path $Root "env.local.ps1")

function _SwapContext {
    $ClaudeMd = "C:\Riot Commander\CLAUDE.md"
    $ClaudeBak = "C:\Riot Commander\CLAUDE.md.full"
    $LeanMd = (Join-Path $Root "LEAN_CLAUDE.md")
    if (Test-Path $ClaudeBak) {
        Write-Warning "CLAUDE.md.full still exists (prior crash? restoring before swap)"
        Copy-Item $ClaudeBak $ClaudeMd -Force
        Remove-Item $ClaudeBak
    }
    Copy-Item $ClaudeMd $ClaudeBak
    Copy-Item $LeanMd $ClaudeMd -Force
    Write-Output "[budget-saver] swapped LEAN_CLAUDE.md -> CLAUDE.md (80 lines vs 223; .full saved)"
}

function _RestoreContext {
    $ClaudeMd = "C:\Riot Commander\CLAUDE.md"
    $ClaudeBak = "C:\Riot Commander\CLAUDE.md.full"
    if (Test-Path $ClaudeBak) {
        Copy-Item $ClaudeBak $ClaudeMd -Force
        Remove-Item $ClaudeBak
        Write-Output "[budget-saver] restored full CLAUDE.md"
    }
}

# ensure proxy up
try { Invoke-WebRequest "http://127.0.0.1:4000/health/liveliness" -TimeoutSec 3 | Out-Null }
catch { Write-Warning "LiteLLM proxy not reachable on :4000 - run setup.ps1 / start the proxy first." }

$env:ANTHROPIC_BASE_URL            = "http://127.0.0.1:4000"
$env:ANTHROPIC_AUTH_TOKEN          = $env:LITELLM_MASTER_KEY
$env:ANTHROPIC_MODEL               = "rc-main"        # local-first, escalates on ctx/error
$env:ANTHROPIC_DEFAULT_HAIKU_MODEL = "rc-background"  # background -> local llama3.1
$env:MAX_THINKING_TOKENS           = "0"             # llama3.1 has no thinking mode

& $Root\.venv\Scripts\python.exe -c "import sys; sys.path.insert(0,r'$Root'); import state; state.write('main','rc-main')"

_SwapContext
try {
    claude --strict-mcp-config --mcp-config (Join-Path $Root "lean-mcp.json") --settings (Join-Path $Root "lean-settings.json") @Rest
} finally {
    _RestoreContext
}
