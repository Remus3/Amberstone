# weekly_hygiene_run.ps1 - unattended weekly /weekly-hygiene pass on Legion.
#
# Registered as the RC-WeeklyHygiene scheduled task (Sunday 04:17, after the
# nightly DDragon mirror 03:30 so the anomaly-triage step
# sees fresh scheduled-task results). Runs Claude Code headless against the
# repo: the /weekly-hygiene skill does its relocate-only doc trims + memory
# staleness scan + session-start anomaly triage, then appends a dated entry to
# WAKEUP_NOTES.md so the operator sees flagged items at next session start.
# Mirrors tools/headless_run.ps1's `claude -p` invocation.
#
# Usage (manual):
#   powershell -ExecutionPolicy Bypass -File "C:\Riot Commander\tools\weekly_hygiene_run.ps1"

param(
    [string]$Model = "claude-sonnet-4-6"
)

$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

$stamp = Get-Date -Format "yyyy-MM-dd"
$log   = Join-Path $repo "logs\weekly_hygiene_$stamp.log"

$prompt = @'
Run /weekly-hygiene. This is an UNATTENDED scheduled run - no operator is
watching the chat. After the pass, append a short dated "weekly-hygiene"
entry to WAKEUP_NOTES.md listing (a) what you relocated and committed and
(b) every judgment call you flagged (memory suspects, actionable anomalies),
so I see them at next session start. Commit + push the relocate-only doc
trims and the WAKEUP entry when local checks are green, then exit. Do NOT
make engine/code changes and do NOT run /sync-all-md.
'@

$tools = "Edit,Read,Write,Bash,Grep,Glob,TaskCreate,TaskUpdate,TaskList"

# FLEET-KIT-v1 (MAIN order 2026-10-03): the run starts ONLY through the fleet
# kit, via ops/loop/fleet_route.py, which fails closed through
# ops/loop/headless_env.py (exit 3, nothing started) and owns the proxy route,
# run budget, model pick (sonnet: this pass writes docs, never code - so
# -Model is no longer passed to the CLI), lean flags and hidden console.
$pyC = "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe"
if (-not (Test-Path $pyC)) { $pyC = "python" }
$route = Join-Path $repo "ops\loop\fleet_route.py"
$promptFile = Join-Path $env:TEMP "rc_weekly_hygiene_prompt.txt"
[System.IO.File]::WriteAllText($promptFile, $prompt, [System.Text.Encoding]::ASCII)

Write-Host "[weekly_hygiene] $stamp start (requested model=$Model; the fleet kit picks)"
$out = & $pyC $route --caller "weekly_hygiene" --note "weekly-hygiene" --timeout 7200 --prompt-file $promptFile -- --allowedTools $tools --dangerously-skip-permissions *>&1 |
    Tee-Object -FilePath $log
$code = $LASTEXITCODE
Write-Host "[weekly_hygiene] exit=$code log=$log"
if ($code -eq 3) {
    Write-Host "[weekly_hygiene] headless route refused - spawn skipped, see logs\headless_route.log"
    exit 3
}

# A weekly maintenance pass that fails ONLY because the Anthropic account hit a
# transient billing / availability limit (credit exhausted, rate limit, 429 /
# 529 overloaded) is not a repo fault. Leaving the task red on that condition
# fires a false anomaly at every session-start probe until the next weekly run.
# Detect the transient class, log it loudly, and exit 0 (it self-resolves).
# Mirrors item 438's credit-depletion hardening (originally built for the
# retired second-vendor wrapper; the detection generalizes). The detection
# scans the captured in-memory stream (not the on-disk log) to dodge the
# UTF-16/BOM re-read encoding pitfall.
if ($code -ne 0) {
    $text = ($out | Out-String)
    $transient = 'credit balance is too low|rate limit|rate_limit|overloaded|too many requests|status(?: code)? (?:429|529)|insufficient (?:credit|quota)'
    if ($text -imatch $transient) {
        Write-Host "[weekly_hygiene] SKIPPED: transient Anthropic API condition (credit/rate/availability) - not a hygiene failure; exiting 0 so the scheduled task is not falsely red."
        exit 0
    }
}
exit $code
