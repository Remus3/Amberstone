# Start the LiteLLM proxy (Anthropic /v1/messages gateway) bound to 127.0.0.1 only.
$ErrorActionPreference = "Stop"
$Root = "C:\Riot Commander\ops\budget_saver"
. (Join-Path $Root "env.local.ps1")
& (Join-Path $Root ".venv\Scripts\litellm.exe") --config (Join-Path $Root "config.yaml") --host 127.0.0.1 --port 4000
