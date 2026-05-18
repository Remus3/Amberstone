# bridge_watcher_hook.ps1 - UserPromptSubmit hook for no-dashboard nodes.
#
# Phase 1 per BRIDGE_WATCHER_PLAN.md §8 "Operator surface" - Game-PC + Peer
# don't run the RC dashboard, so the bridge_inbox_pending.json queue needs a
# non-browser surface. This hook fires on every prompt the operator submits
# in their Claude Code session. If the queue has unclaimed entries, it emits
# ONE system-reminder line; otherwise it stays silent.
#
# Wire into ~/.claude/settings.json:
#
#   {
#     "hooks": {
#       "UserPromptSubmit": [
#         { "command": "powershell -NoProfile -ExecutionPolicy Bypass -File C:/RC-Agent/bridge_watcher_hook.ps1" }
#       ]
#     }
#   }
#
# Override the pending-file path with $env:BRIDGE_PENDING_PATH if needed
# (defaults: C:\RC-Agent\bridge_inbox_pending.json on Game-PC, the script's
#  parent dir on Peer).

param(
    [string]$PendingPath = ""
)

if (-not $PendingPath) {
    if ($env:BRIDGE_PENDING_PATH) {
        $PendingPath = $env:BRIDGE_PENDING_PATH
    } else {
        # Default: same dir as this script. Installer points here.
        $here = Split-Path -Parent $MyInvocation.MyCommand.Path
        $PendingPath = Join-Path $here "bridge_inbox_pending.json"
    }
}

if (-not (Test-Path -LiteralPath $PendingPath)) {
    exit 0   # silent - watcher hasn't escalated anything yet
}

try {
    $raw  = Get-Content -LiteralPath $PendingPath -Raw -Encoding UTF8
    $data = $raw | ConvertFrom-Json
} catch {
    exit 0   # corrupt or partially-written; silent failure
}

$tasks = @($data.tasks)
$unclaimed = @($tasks | Where-Object { -not $_.claimed_by })
if ($unclaimed.Count -eq 0) { exit 0 }

# Sort oldest-first; pick the oldest unclaimed for the summary preview.
$oldest = $unclaimed | Sort-Object received_at | Select-Object -First 1
$summary = ($oldest.summary -as [string])
if (-not $summary) { $summary = "(no summary)" }
if ($summary.Length -gt 80) { $summary = $summary.Substring(0, 77) + "..." }

# One line, regardless of N. Operator types /process-bridge-tasks to drain.
Write-Output ("[bridge] {0} task(s) pending review (oldest from {1}: {2}). Run /process-bridge-tasks to drain." `
    -f $unclaimed.Count, ($oldest.from -as [string]), $summary)
exit 0
