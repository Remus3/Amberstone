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

# Wait long enough for the worker's background subagents (notably the
# non-negotiable verifier gate) to finish before the CLI terminates them. The
# default ceiling is 600s; MEASURED 2026-08-30 (lane 8 cycle 3): the verifier
# was still re-running the dual suite at 600s, the CLI killed it, and the worker
# exited 0 having committed NOTHING - a whole audit lost. 2400000 ms (40 min) is
# ample for the RC + DS suites plus the re-read, while staying bounded so a truly
# wedged task still exits and reports rather than hanging forever.
$env:CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS = "2400000"

$claude = (Get-Command claude -ErrorAction Stop).Source
Set-Location $Cwd

# Model id comes from ops/loop/config.json (executor_model) so the lanes track
# the same model as the loop controller instead of keeping a second hardcoded
# copy that silently drifts. Read via $PSScriptRoot, NOT the worktree cwd: this
# runner always lives in the MAIN tree (lane_launcher RUNNER =
# ops/loop/run_lane.ps1), while $Cwd is a fresh worktree checkout that may not
# carry a gitignored config. Falls back to a known-good model when the file is
# missing or unparseable, because a lane must never fail to spawn over a config
# read.
$model = "claude-opus-5"
try {
  $cfgPath = Join-Path $PSScriptRoot "config.json"
  if (Test-Path $cfgPath) {
    $cfg = Get-Content $cfgPath -Raw | ConvertFrom-Json
    if ($cfg.executor_model) { $model = [string]$cfg.executor_model }
  }
} catch {
  # any read or parse fault keeps the fallback model set above
}

"lane start $(Get-Date -Format s) cwd=$Cwd model=$model prompt=$PromptFile" | Out-File $Log -Encoding utf8
# `*>> $Log` wrote the worker's output as UTF-16LE: on Windows PowerShell 5.1
# the redirection operators use the shell's default Unicode encoding, while the
# header line above is UTF-8. MEASURED 2026-08-02 on a real 4298-byte lane log:
# UTF-8 BOM plus a UTF-8 header for 119 bytes, then UTF-16LE for the remaining
# 4179 - 2066 NUL bytes in one file. Anything reading it as one encoding got
# "C\0y\0c\0l\0e" for the half that matters, which is what Mission Control
# would have rendered into its lane-log panel.
# `*>&1 |` merges every stream into the pipeline so Out-File can set the
# encoding, keeping the "native stderr must not kill the lane" property above:
# the streams are still folded into the same file, they are just written as
# UTF-8 now. The reader stays tolerant of the old shape for logs already on
# disk (dashboard/routes_loop_status._decode_lane_log).
Get-Content $PromptFile -Raw |
  & $claude -p --model $model --dangerously-skip-permissions *>&1 |
  Out-File $Log -Append -Encoding utf8
"lane exit $(Get-Date -Format s) code=$LASTEXITCODE" | Out-File $Log -Append -Encoding utf8
