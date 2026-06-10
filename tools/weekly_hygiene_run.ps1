# weekly_hygiene_run.ps1 - unattended weekly /weekly-hygiene pass on Legion.
#
# Registered as the RC-WeeklyHygiene scheduled task (Sunday 04:17, after the
# nightly DDragon mirror 03:30 + Gemini audit 03:00 so the anomaly-triage step
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

Write-Host "[weekly_hygiene] $stamp start (model=$Model)"
& claude -p $prompt --model $Model --allowedTools $tools --dangerously-skip-permissions *>&1 |
    Tee-Object -FilePath $log
$code = $LASTEXITCODE
Write-Host "[weekly_hygiene] exit=$code log=$log"
exit $code
