param([Parameter(ValueFromRemainingArguments=$true)] $Rest)
$ErrorActionPreference = "Stop"
$Root = "C:\Riot Commander\ops\budget_saver"
. (Join-Path $Root "env.local.ps1")
# ensure proxy up (Task 10 provides ensure_stack); minimal check here:
try { Invoke-WebRequest "http://127.0.0.1:4000/health/liveliness" -TimeoutSec 3 | Out-Null }
catch { Write-Warning "LiteLLM proxy not reachable on :4000 - run setup.ps1 / start the proxy first." }
$env:ANTHROPIC_BASE_URL            = "http://127.0.0.1:4000"
$env:ANTHROPIC_AUTH_TOKEN          = $env:LITELLM_MASTER_KEY
$env:ANTHROPIC_MODEL               = "rc-deepseek-pro"    # reasoning-tier, accepts cost for best cheap brain
$env:ANTHROPIC_DEFAULT_HAIKU_MODEL = "rc-deepseek"  # background -> cheapseek
& $Root\.venv\Scripts\python.exe -c "import sys; sys.path.insert(0,r'$Root'); import state; state.write('smart','rc-deepseek-pro')"
claude --strict-mcp-config --mcp-config (Join-Path $Root "lean-mcp.json") --settings (Join-Path $Root "lean-settings.json") @Rest
