# run_lane.ps1 - detached runner for one headless lane worker (spawned hidden by
# ops/loop/lane_launcher.py). The worker reads its whole prompt from stdin, so
# there is no command-line quoting risk and no argv length limit.
#
# FLEET-KIT v10 (MAIN 0839 ORDER step 5, ruled: "RC: route lanes through spawn /
# the CLI, use effort="): the worker starts ONLY through the fleet kit, via
# ops/loop/fleet_route.py -> ops/fleet_kit/fleet_headless.spawn. Never `claude`
# from here. The route fails closed through ops/loop/headless_env.py first (exit
# 3, nothing started), then the kit applies its own proxy check, the
# 120-runs-per-24h budget, the lean flags (strict MCP + project,local sources;
# not --bare, RC floors live in project hooks), the hidden console, the usage
# line, the status file, FLEET_SUBAGENT_FIRST=off for the child and a
# whole-tree kill on timeout. fleet_route.py is resolved next to THIS file, and
# this runner always lives in the MAIN tree (lane_launcher RUNNER), so the
# budget / status / usage files land in the MAIN checkout while the child runs
# in the lane worktree ($Cwd). The lane progress file progress/lane-<i>.json is
# written by lane_launcher in the MAIN checkout before this runner starts.
#
# ASCII only (PowerShell 5.1 ANSI-decodes a no-BOM script).
param(
  [Parameter(Mandatory)][string]$PromptFile,
  [Parameter(Mandatory)][string]$Cwd,
  [Parameter(Mandatory)][string]$Log
)
$ErrorActionPreference = "Continue"   # native stderr must not kill the lane; it all goes to the log

# Ride the subscription route, never the API key. MEASURED 2026-08-02: the
# `gated` lane died 3s after spawning with "Credit balance is too low", because
# ANTHROPIC_API_KEY is set at MACHINE scope on Legion, the scheduled task that
# spawns lanes inherits it, and the CLI prefers it over the login. The kit's
# child_env strips it (and every provider switch) from the child as well; it is
# cleared here too so nothing else in this runner's tree can pick it up. Scoped
# to this process only; the machine-wide variable is left alone.
$env:ANTHROPIC_API_KEY = $null

# Wait long enough for the worker's background subagents (notably the
# non-negotiable verifier gate) to finish before the CLI terminates them. The
# default ceiling is 600s; MEASURED 2026-08-30 (lane 8 cycle 3): the verifier
# was still re-running the dual suite at 600s, the CLI killed it, and the worker
# exited 0 having committed NOTHING. 2400000 ms (40 min) stays bounded so a
# truly wedged task still exits. The kit's child env is a copy of this
# process's env, so the child inherits the ceiling.
$env:CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS = "2400000"

# The route prints the worker's result text; a pipe on Windows defaults to the
# ANSI code page, which cannot encode every character a result may carry.
$env:PYTHONIOENCODING = "utf-8"

# Model and effort come from ops/loop/config.json (executor_model,
# executor_effort) so the lanes track the loop controller instead of a second
# hardcoded copy that silently drifts. Operator 2026-09-16: the headless lanes
# run at effort HIGH - passed as the kit's own effort=, never an RC argv knob.
# Read via $PSScriptRoot, NOT the worktree cwd: $Cwd is a fresh worktree that
# may not carry a gitignored config. A missing or unparseable file keeps the
# fallback model and passes no effort (the kit then picks), because a lane must
# never fail to spawn over a config read.
$model = "claude-opus-5-5"
$effort = ""
try {
  $cfgPath = Join-Path $PSScriptRoot "config.json"
  if (Test-Path $cfgPath) {
    $cfg = Get-Content $cfgPath -Raw | ConvertFrom-Json
    if ($cfg.executor_model) { $model = [string]$cfg.executor_model }
    if ($cfg.executor_effort) { $effort = [string]$cfg.executor_effort }
  }
} catch {
  # any read or parse fault keeps the fallbacks set above
}

$pyC = "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe"
if (-not (Test-Path $pyC)) { $pyC = "python" }
$route = Join-Path $PSScriptRoot "fleet_route.py"
$note = "lane-" + [System.IO.Path]::GetFileNameWithoutExtension($PromptFile)
# 6 h ceiling per lane run: the kit's spawn is bounded, so an unattended worker
# must be too (same ceiling as tools/headless_run.ps1). queue_loop's own cycle
# timeout still applies on top.
$timeoutS = "21600"

# Arguments as an ARRAY: PowerShell 5.1 drops an empty native argument, so a
# value that may be empty is appended only when set. The `--` separator hands
# the RC permission flag to the kit's extra=.
$routeArgs = @("--caller", "run_lane", "--note", $note, "--kind", "build", "--writes-code",
  "--model", $model, "--cwd", $Cwd, "--timeout", $timeoutS,
  "--prompt-file", $PromptFile, "--prompt-stdin")
if ($effort) { $routeArgs += @("--effort", $effort) }
$routeArgs += @("--", "--dangerously-skip-permissions")

"lane start $(Get-Date -Format s) cwd=$Cwd model=$model effort=$effort prompt=$PromptFile route=fleet_route" | Out-File $Log -Encoding utf8
# `*>&1 |` merges every stream into the pipeline so Out-File sets the encoding
# (UTF-8): the redirection operators alone write UTF-16LE on Windows PowerShell
# 5.1 (MEASURED 2026-08-02, a mixed-encoding lane log). The reader stays
# tolerant of the old shape for logs already on disk
# (dashboard/routes_loop_status._decode_lane_log).
& $pyC $route @routeArgs *>&1 | Out-File $Log -Append -Encoding utf8
$code = $LASTEXITCODE
if ($code -eq 3) {
  "lane refused $(Get-Date -Format s) - fleet route refused (exit 3), nothing started; see logs\headless_route.log and ops\loop\control\inbox_status.json" | Out-File $Log -Append -Encoding utf8
  exit 3
}
"lane exit $(Get-Date -Format s) code=$code" | Out-File $Log -Append -Encoding utf8
exit $code
