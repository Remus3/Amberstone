# headless_run.ps1 - crash-resilient wrapper for unattended headless-upgrade runs.
#
# Two runs have died mid-orchestration on API 400 / socket-close errors, wasting
# the whole run. This wrapper relaunches on any non-zero exit and, on each retry,
# reads the slice manifest (tools/slice_orchestrator.py) so the resumed run skips
# already-committed slices and continues only the incomplete ones. Pair it with
# per-slice checkpoint commits so a crash loses at most one in-flight slice.
#
# Usage (from anywhere):
#   powershell -ExecutionPolicy Bypass -File "<repo>\tools\headless_run.ps1"
#   powershell -File "...\headless_run.ps1" -Prompt "continue next backlog item" -MaxAttempts 6

param(
    [string]$Prompt = "Run /headless-upgrade. Init a slice manifest via tools/slice_orchestrator.py, commit + push after every completed slice and mark it committed in the manifest, then /done.",
    [int]$MaxAttempts = 4,
    [string]$Manifest = "ops/runtime/slice_manifest.json"
)

$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

# Pin the canonical interpreter for the resume-manifest read. Bare `py` on
# Legion resolves via PEP 514 to a dep-less pymanager runtime (the
# tests/test_bare_py_ban.py incident class), so slice_orchestrator.py would run
# under a deps-less interpreter. Fall back to `python` on PATH only if the
# canonical path is absent (mirrors the tools/*.cmd wrappers).
$pyC = "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe"
if (-not (Test-Path $pyC)) { $pyC = "python" }

$tools = "Edit,Read,Write,Bash,Grep,Glob,Agent,TaskCreate,TaskUpdate,TaskList"

# FLEET-KIT-v1 (MAIN order 2026-10-03): the run starts ONLY through the fleet
# kit, via ops/loop/fleet_route.py, which fails closed through
# ops/loop/headless_env.py (exit 3, nothing started) and owns the proxy route,
# run budget, model pick, lean flags and hidden console. The prompt travels in
# a file, never through PowerShell native-argument quoting. 6 h ceiling per
# attempt: the kit's spawn is bounded, an unattended run must be too.
$route = Join-Path $repo "ops\loop\fleet_route.py"
$promptFile = Join-Path $env:TEMP "rc_headless_run_prompt.txt"

for ($i = 1; $i -le $MaxAttempts; $i++) {
    if ($i -eq 1) {
        $p = $Prompt
    } else {
        $incomplete = ""
        try {
            $incomplete = (& $pyC "$repo\tools\slice_orchestrator.py" --manifest $Manifest resume) -join " "
        } catch {
            $incomplete = ""
        }
        $p = "Resume the previous autonomous headless run. Already-committed slices are durable - do NOT redo them. Incomplete slice ids from the manifest: [$incomplete]. Re-verify each against ground truth before continuing, commit + push after each slice and mark it committed in the manifest, then run /done."
    }

    Write-Host "[headless_run] attempt $i/$MaxAttempts"
    # Re-checked EVERY attempt: deleting the var stops the retry loop too, and a
    # downed proxy exits 3 here instead of retrying another way.
    [System.IO.File]::WriteAllText($promptFile, $p, [System.Text.Encoding]::ASCII)
    & $pyC $route --caller "headless_run" --note "headless-upgrade" --writes-code --timeout 21600 --prompt-file $promptFile -- --allowedTools $tools --dangerously-skip-permissions
    $code = $LASTEXITCODE
    if ($code -eq 3) {
        Write-Host "[headless_run] headless route refused - spawn skipped, see logs\headless_route.log"
        exit 3
    }

    if ($code -eq 0) {
        Write-Host "[headless_run] clean exit on attempt $i"
        exit 0
    }

    Write-Host "[headless_run] attempt $i exited $code - resuming after 10s"
    Start-Sleep -Seconds 10
}

Write-Host "[headless_run] exhausted $MaxAttempts attempts - manual review needed"
exit 1
