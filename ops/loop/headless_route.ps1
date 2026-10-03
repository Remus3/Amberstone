# headless_route.ps1 - the PowerShell side of headless account routing.
#
# Operator contract 2026-10-02: every headless `claude -p` this tree starts rides
# the local subscription proxy named by the USER env var CLAUDE_HEADLESS_BASE_URL.
# Dot-source this file, then call Assert-HeadlessRoute BEFORE the first claude
# invocation. It asks ops/loop/headless_env.py (the ONE shared helper - same
# registry-first read, loopback check and TCP probe as every Python spawn path)
# for the URL and sets ANTHROPIC_BASE_URL in THIS PROCESS ONLY, so the claude
# child inherits it and nothing user-wide or machine-wide changes. On refusal it
# logs why and exits the script with code 3 - fail closed, never a direct
# claude, never the proxy's own fallback mode. Deleting the user var is the kill
# switch.
#
# ASCII only (PowerShell 5.1 ANSI-decodes a no-BOM script).

function Assert-HeadlessRoute {
  param(
    [Parameter(Mandatory)][string]$Caller,
    [string]$Log = ""
  )
  # $PSScriptRoot inside a dot-sourced function is THIS file's directory.
  $helper = Join-Path $PSScriptRoot "headless_env.py"
  $py = "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe"
  if (-not (Test-Path $py)) { $py = "python" }
  $url = ""
  $code = 1
  try {
    $url = (& $py $helper --url --caller $Caller 2>$null | Select-Object -First 1)
    $code = $LASTEXITCODE
  } catch {
    $code = 1
  }
  if ($code -ne 0 -or -not $url) {
    $msg = "headless route refused for $Caller (helper exit $code) - spawn skipped, see logs\headless_route.log"
    Write-Host "[headless_route] $msg"
    if ($Log) { $msg | Out-File $Log -Append -Encoding utf8 }
    exit 3
  }
  $env:ANTHROPIC_BASE_URL = [string]$url.Trim()
}
