# tools/gemini_audit.ps1 - RC/DS Gemini read-only auditor (PROVISIONAL)
# See docs/GEMINI_AUDIT_CONFIG.md. Gemini reads + critiques ONLY; this
# deterministic runner is the SOLE writer of the review file. Gemini is launched
# read-only (--approval-mode plan --skip-trust) and its stdout is captured. The
# prompt is piped via STDIN to dodge the Windows command-line length limit.
param(
  [string]$Model = $(if ($env:RC_GEMINI_MODEL) { $env:RC_GEMINI_MODEL } elseif ([Environment]::GetEnvironmentVariable("RC_GEMINI_MODEL", "User")) { [Environment]::GetEnvironmentVariable("RC_GEMINI_MODEL", "User") } else { "gemini-2.5-flash" }),
  [string]$RepoRoot = "C:\Riot Commander",
  [string]$Since = ""
)
$ErrorActionPreference = "Stop"
Set-Location $RepoRoot

$key = [Environment]::GetEnvironmentVariable("GEMINI_API_KEY", "User")
if (-not $key) { Write-Error "GEMINI_API_KEY missing in User scope"; exit 2 }
$env:GEMINI_API_KEY = $key

$markerAbs = Join-Path $RepoRoot "ops\runtime\gemini_last_audit.txt"
$head = (git rev-parse HEAD).Trim()
if (-not $Since) {
  if (Test-Path $markerAbs) { $Since = (Get-Content $markerAbs -Raw).Trim() }
  if (-not $Since) { $Since = (git rev-parse "HEAD~10").Trim() }
}
$range = "$Since..$head"
$commits = (git log --oneline $range | Out-String).Trim()
if (-not $commits) { "no new commits in $range - nothing to audit"; exit 0 }

$diffStat = (git diff --stat $range | Out-String)
$diff = (git diff $range | Out-String)
if ($diff.Length -gt 60000) { $diff = $diff.Substring(0, 60000) + "`n...[diff truncated at 60k chars]" }
function Tail($p, $n) { if (Test-Path $p) { (Get-Content $p -Tail $n | Out-String) } else { "" } }

$tmpl = Get-Content (Join-Path $RepoRoot "tools\gemini_audit_prompt.md") -Raw
$prompt = $tmpl + "`n`n=== COMMITS ($range) ===`n" + $commits +
  "`n`n=== DIFF STAT ===`n" + $diffStat +
  "`n`n=== ROADMAP (tail) ===`n" + (Tail "ROADMAP.md" 120) +
  "`n`n=== BACKLOG (tail) ===`n" + (Tail "BACKLOG.md" 80) +
  "`n`n=== FULL DIFF ===`n" + $diff

# gemini writes benign warnings to stderr; under Stop those wrap as a terminating
# NativeCommandError. Relax to Continue. Retry on empty output - free-tier RPM
# throttling can return an empty body the cli's own backoff misses.
$savedEAP = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$review = ""
for ($try = 1; $try -le 3 -and -not $review.Trim(); $try++) {
  $review = ($prompt | & gemini -p "Perform the read-only audit described in this input. Output the markdown review only." -m $Model --approval-mode plan --skip-trust 2>$null | Out-String)
  if (-not $review.Trim() -and $try -lt 3) { Start-Sleep -Seconds (10 * $try) }
}
$ErrorActionPreference = $savedEAP
if (-not $review.Trim()) { Write-Error "gemini empty after 3 tries (model=$Model - check quota/billing/RPM)"; exit 3 }

$date = Get-Date -Format "yyyy-MM-dd"
$outAbs = Join-Path $RepoRoot "docs\EXTERNAL_REVIEW_$date.md"
$tmpAbs = "$outAbs.tmp"
$hdr = "<!-- PROVISIONAL external review by Gemini ($Model), range $range. Read-only advisory - Claude verifies before acting. -->`n`n"
[IO.File]::WriteAllText($tmpAbs, $hdr + $review)
Move-Item -Force $tmpAbs $outAbs
[IO.File]::WriteAllText($markerAbs, $head)
$logAbs = Join-Path $RepoRoot "logs\gemini_audit.log"
"$((Get-Date).ToString('s')) model=$Model range=$range out=$outAbs len=$($review.Length)" | Add-Content $logAbs
"WROTE $outAbs (model=$Model, $($review.Length) chars)"
