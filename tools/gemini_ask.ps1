# tools/gemini_ask.ps1 - in-session / headless read-only Q/A to Gemini (PROVISIONAL)
# Claude calls this mid-session to ask Gemini a research/context question. Gemini
# is read-only (--approval-mode plan); it may READ repo files to answer but never
# writes/commits. The answer is echoed to stdout AND saved to gemini_io/answer_<id>.md
# (gitignored). See docs/GEMINI_AUDIT_CONFIG.md + docs/GEMINI_REVIEW_CONSUMPTION.md.
param(
  [Parameter(Mandatory = $true)][string]$Question,
  [string]$Model = $(if ($env:RC_GEMINI_MODEL) { $env:RC_GEMINI_MODEL } elseif ([Environment]::GetEnvironmentVariable("RC_GEMINI_MODEL", "User")) { [Environment]::GetEnvironmentVariable("RC_GEMINI_MODEL", "User") } else { "gemini-2.5-flash" }),
  [string]$RepoRoot = "C:\Riot Commander",
  [string]$Id = ""
)
$ErrorActionPreference = "Stop"
Set-Location $RepoRoot

$key = [Environment]::GetEnvironmentVariable("GEMINI_API_KEY", "User")
if (-not $key) { Write-Error "GEMINI_API_KEY missing in User scope"; exit 2 }
$env:GEMINI_API_KEY = $key

$preamble = "You are the READ-ONLY research/context advisor for the RC/DS repo (see GEMINI.md if present). Answer the question below. You MAY read repo files read-only to ground the answer; never edit/write/commit. ASCII only, no em-dashes, terse. If you cannot ground an answer, say so plainly. Output the answer only.`n`nQUESTION:`n"
$prompt = $preamble + $Question

# Relax Stop around the gemini call (benign stderr warnings) + retry on empty.
$savedEAP = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$answer = ""
for ($try = 1; $try -le 3 -and -not $answer.Trim(); $try++) {
  $answer = ($prompt | & gemini -p "Answer the question in the input." -m $Model --approval-mode plan --skip-trust 2>$null | Out-String)
  if (-not $answer.Trim() -and $try -lt 3) { Start-Sleep -Seconds (8 * $try) }
}
$ErrorActionPreference = $savedEAP
if (-not $answer.Trim()) { Write-Error "gemini empty after 3 tries (model=$Model - check quota/billing)"; exit 3 }

$ioDir = Join-Path $RepoRoot "gemini_io"
if (-not (Test-Path $ioDir)) { New-Item -ItemType Directory -Path $ioDir | Out-Null }
if (-not $Id) { $Id = Get-Date -Format "yyyyMMdd-HHmmss" }
$outAbs = Join-Path $ioDir "answer_$Id.md"
$qOneLine = ($Question -replace "\r?\n", " ")
$hdr = "<!-- gemini ($Model) read-only answer. Q: $qOneLine -->`n`n"
[IO.File]::WriteAllText($outAbs, $hdr + $answer)
"--- gemini_io/answer_$Id.md ($($answer.Length) chars) ---"
$answer.Trim()
