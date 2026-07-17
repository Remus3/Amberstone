# run_lane.ps1 - detached runner for one headless claude -p lane (spawned hidden by
# spawn_lanes.ps1). Pipes the prompt file to claude on stdin (no cmdline quoting risk).
param(
  [Parameter(Mandatory)][string]$PromptFile,
  [Parameter(Mandatory)][string]$Cwd,
  [Parameter(Mandatory)][string]$Log
)
$ErrorActionPreference = "Continue"   # native stderr must not kill the lane; it all goes to the log
$claude = (Get-Command claude -ErrorAction Stop).Source
Set-Location $Cwd
"lane start $(Get-Date -Format s) cwd=$Cwd prompt=$PromptFile" | Out-File $Log -Encoding utf8
Get-Content $PromptFile -Raw | & $claude -p --model claude-opus-4-8 --dangerously-skip-permissions *>> $Log
"lane exit $(Get-Date -Format s) code=$LASTEXITCODE" | Out-File $Log -Append -Encoding utf8
