# tools/gemini_audit.ps1 - RC/DS Gemini read-only auditor (PROVISIONAL)
# See docs/GEMINI_AUDIT_CONFIG.md. Gemini reads + critiques ONLY; this
# deterministic runner is the SOLE writer of the review file. Gemini is launched
# read-only (--approval-mode plan --skip-trust) and its stdout is captured. The
# prompt is piped via STDIN to dodge the Windows command-line length limit.
param(
  [string]$Model = $(if ($env:RC_GEMINI_MODEL) { $env:RC_GEMINI_MODEL } elseif ([Environment]::GetEnvironmentVariable("RC_GEMINI_MODEL", "User")) { [Environment]::GetEnvironmentVariable("RC_GEMINI_MODEL", "User") } else { "gemini-2.5-flash" }),
  [string]$RepoRoot = "C:\Riot Commander",
  [string]$Since = "",
  [int]$MaxWaitSec = 180
)
$ErrorActionPreference = "Stop"
Set-Location $RepoRoot
$logAbs = Join-Path $RepoRoot "logs\gemini_audit.log"
function Fail($msg, $code) {
  # Log the reason + exit with the intended code. NB: Write-Error under
  # $ErrorActionPreference='Stop' TERMINATES before `exit N`, masking the real
  # code as a bare 1 with NO diagnostic (the 2026-06-07 RC-GeminiAudit failure:
  # gemini empty -> Write-Error threw -> task LastTaskResult=1, nothing logged).
  try { "$((Get-Date).ToString('s')) FAIL code=$code $msg" | Add-Content $logAbs } catch {}
  Write-Warning $msg
  exit $code
}
function Log($msg) { try { "$((Get-Date).ToString('s')) $msg" | Add-Content $logAbs } catch {} }
# Native git writes "fatal: ..." to stderr for an unresolvable sha; under
# $ErrorActionPreference='Stop' a native stderr write can surface as a terminating
# NativeCommandError, so probe with the preference relaxed and read $LASTEXITCODE.
function Test-CommitResolves($sha) {
  if (-not $sha) { return $false }
  $prev = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  try { & git cat-file -e "$sha^{commit}" 2>$null; return ($LASTEXITCODE -eq 0) }
  catch { return $false }
  finally { $ErrorActionPreference = $prev }
}
# Unconditional first write: every later branch is conditional, so without this a
# run that dies before its first Add-Content is indistinguishable from one that
# never fired at all. The 2026-07-19 03:00 run exited 0xC000013A with an EMPTY
# logs/ directory entry, and that ambiguity cost a full root-cause pass.
Log "START pid=$PID model=$Model repo=$RepoRoot"

$key = [Environment]::GetEnvironmentVariable("GEMINI_API_KEY", "User")
if (-not $key) { Fail "GEMINI_API_KEY missing in User scope" 2 }
$env:GEMINI_API_KEY = $key

$markerAbs = Join-Path $RepoRoot "ops\runtime\gemini_last_audit.txt"
$head = (git rev-parse HEAD).Trim()
if (-not $Since) {
  if (Test-Path $markerAbs) { $Since = (Get-Content $markerAbs -Raw).Trim() }
  # A marker sha that no longer resolves silently no-ops the whole nightly:
  # `git log <dangling>..HEAD` fatals to stderr, $commits comes back empty, and the
  # run takes the "nothing to audit" exit 0 below - producing no review AND no log
  # line. That is exactly how this audit went dark for 28 nights (last review
  # 2026-06-21, marker pinned at edd76db3 which never survived cherry-pick).
  # Worktree-slice shas that vanish are an EXPECTED class here (see the
  # docs/LEDGER.md preamble), so the marker has to self-heal rather than wedge.
  if ($Since -and -not (Test-CommitResolves $Since)) {
    Log "WARN marker sha '$Since' no longer resolves - self-healing to HEAD~10"
    $Since = ""
  }
  if (-not $Since) { $Since = (git rev-parse "HEAD~10").Trim() }
}
$range = "$Since..$head"
$commits = (git log --oneline $range | Out-String).Trim()
if (-not $commits) { Log "SKIP code=0 no new commits in $range - nothing to audit"; "no new commits in $range - nothing to audit"; exit 0 }

$diffStat = (git diff --stat $range | Out-String)
$diff = (git diff $range | Out-String)
if ($diff.Length -gt 60000) { $diff = $diff.Substring(0, 60000) + "`n...[diff truncated at 60k chars]" }
function Tail($p, $n) { if (Test-Path $p) { (Get-Content $p -Tail $n | Out-String) } else { "" } }
# Head: the FIRST n lines. ROADMAP.md / BACKLOG.md are priority/newest at the TOP
# (open high-priority items first), so the auditor must read the HEAD, not the tail
# (which is the oldest/settled boilerplate) - same newest-first inversion the loop
# director's LEDGER read was fixed for (2026-06-27).
function Head($p, $n) { if (Test-Path $p) { (Get-Content $p -TotalCount $n | Out-String) } else { "" } }

$tmpl = Get-Content (Join-Path $RepoRoot "tools\gemini_audit_prompt.md") -Raw
$prompt = $tmpl + "`n`n=== COMMITS ($range) ===`n" + $commits +
  "`n`n=== DIFF STAT ===`n" + $diffStat +
  "`n`n=== ROADMAP (open items, top) ===`n" + (Head "ROADMAP.md" 120) +
  "`n`n=== BACKLOG (top) ===`n" + (Head "BACKLOG.md" 80) +
  "`n`n=== FULL DIFF ===`n" + $diff

# gemini writes benign warnings to stderr; under Stop those wrap as a terminating
# NativeCommandError. Relax to Continue. Retry on empty output - free-tier RPM
# throttling can return an empty body the cli's own backoff misses.
function Invoke-GeminiAudit($model, $tries) {
  $out = ""
  for ($try = 1; $try -le $tries -and -not $out.Trim() -and (Get-Date) -lt $deadline; $try++) {
    $out = ($prompt | & gemini -p "Perform the read-only audit described in this input. Output the markdown review only." -m $model --approval-mode plan --skip-trust 2>$null | Out-String)
    if (-not $out.Trim() -and $try -lt $tries -and (Get-Date).AddSeconds(10 * $try) -lt $deadline) { Start-Sleep -Seconds (10 * $try) }
  }
  return $out
}
$savedEAP = $ErrorActionPreference
$ErrorActionPreference = "Continue"
# Bound the primary + fallback retry passes by one shared wall-clock deadline so
# a 429-backoff or hung gemini CLI cannot stall the scheduled run (P2 gap).
$deadline = (Get-Date).AddSeconds($MaxWaitSec)
# Primary model = the operator's RC_GEMINI_MODEL. On persistent empty output
# (quota / RPM / preview-model throttling - e.g. the gemini-3-pro-preview outage
# that broke the 2026-06-07 nightly run while it had worked on 06-06) fall back to
# a more available model so the advisory audit still produces a review.
$usedModel = $Model
$review = Invoke-GeminiAudit $Model 3
$fallback = if ($env:RC_GEMINI_FALLBACK_MODEL) { $env:RC_GEMINI_FALLBACK_MODEL } else { "gemini-2.5-flash" }
if (-not $review.Trim() -and $fallback -ne $Model) {
  "$((Get-Date).ToString('s')) primary '$Model' empty after 3 tries; falling back to '$fallback'" | Add-Content $logAbs
  $usedModel = $fallback
  $review = Invoke-GeminiAudit $fallback 2
}
$ErrorActionPreference = $savedEAP
# A nightly ADVISORY audit producing no review ONLY because the external Gemini
# service returned empty after every primary + fallback retry (account quota /
# billing / RPM throttle / preview-model availability - the gemini-3-pro-preview
# emptiness that began 2026-06-18) is not a repo fault. The audit is PROVISIONAL
# and read-only (Claude verifies before acting), so a missing review is
# degraded-not-broken. Leaving the scheduled task red on this external condition
# fires a false anomaly at every session-start probe until the next nightly run.
# Log it loudly and exit 0. Mirrors item 444 / item 438 (the sibling
# weekly_hygiene_run.ps1 transient-API hardening). A genuine config fault (missing
# GEMINI_API_KEY) still exits 2 above and stays correctly red.
if (-not $review.Trim()) {
  $msg = "gemini empty after retries (primary=$Model fallback=$fallback) - external quota/billing/RPM/availability, not a repo fault; advisory audit skipped this run"
  try { "$((Get-Date).ToString('s')) SKIP code=0 $msg" | Add-Content $logAbs } catch {}
  Write-Warning $msg
  exit 0
}

$date = Get-Date -Format "yyyy-MM-dd"
$outAbs = Join-Path $RepoRoot "docs\EXTERNAL_REVIEW_$date.md"
$tmpAbs = "$outAbs.tmp"
$hdr = "<!-- PROVISIONAL external review by Gemini ($usedModel), range $range. Read-only advisory - Claude verifies before acting. -->`n`n"
[IO.File]::WriteAllText($tmpAbs, $hdr + $review)
Move-Item -Force $tmpAbs $outAbs
[IO.File]::WriteAllText($markerAbs, $head)
"$((Get-Date).ToString('s')) model=$usedModel range=$range out=$outAbs len=$($review.Length)" | Add-Content $logAbs
"WROTE $outAbs (model=$usedModel, $($review.Length) chars)"
