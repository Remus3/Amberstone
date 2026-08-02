# run_lane.ps1 - detached runner for one headless claude -p lane (spawned hidden by
# spawn_lanes.ps1). Pipes the prompt file to claude on stdin (no cmdline quoting risk).
param(
  [Parameter(Mandatory)][string]$PromptFile,
  [Parameter(Mandatory)][string]$Cwd,
  [Parameter(Mandatory)][string]$Log
)
$ErrorActionPreference = "Continue"   # native stderr must not kill the lane; it all goes to the log

# Ride the Max subscription login, never the API key. MEASURED 2026-08-02: the
# `gated` lane spawned correctly and died 3s later with "Credit balance is too
# low", because ANTHROPIC_API_KEY is set at MACHINE scope on Legion, the
# scheduled task that spawns lanes inherits it, and the CLI prefers it over the
# claude.ai login ("claude.ai connectors are disabled because ANTHROPIC_API_KEY
# ... takes precedence"). That same warning is in the 2026-07-31 research-lane
# log, which then ran 15 minutes to exit 0 - so this was latent for as long as
# the key had credit, and it fails the whole lane the moment it does not.
# Verified with the var cleared: same CLI, same model, exit 0.
# Scoped to this runner's own process on purpose. The machine-wide variable is
# left alone; other consumers (RC's own coaches read API-Key-Claude.txt, not
# this) are none of this script's business, and a lane is exactly the workload
# the subscription is for (memory feedback_no_dollar_cap_on_max_subscription).
$env:ANTHROPIC_API_KEY = $null

$claude = (Get-Command claude -ErrorAction Stop).Source
Set-Location $Cwd
"lane start $(Get-Date -Format s) cwd=$Cwd prompt=$PromptFile" | Out-File $Log -Encoding utf8
Get-Content $PromptFile -Raw | & $claude -p --model claude-opus-4-8 --dangerously-skip-permissions *>> $Log
"lane exit $(Get-Date -Format s) code=$LASTEXITCODE" | Out-File $Log -Append -Encoding utf8
