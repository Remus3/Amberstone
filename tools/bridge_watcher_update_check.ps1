# bridge_watcher_update_check.ps1 -- drift check for peer watcher fileset.
#
# Reads the Legion-side manifest at /agent/_watcher_manifest.json and
# diffs the sha256 of the local install copy. Reports stale files; with
# -Apply, re-pulls them and restarts the scheduled task.
#
# Pair-piece to bridge_watcher_install.ps1 (which is frozen, hence the
# split): install does the first-time setup, this script handles ongoing
# drift detection without modifying the installer.
#
# Run on Peer from a fresh shell:
#
#   iex (iwr -UseBasicParsing `
#     https://legion-rc:8888/agent/bridge_watcher_update_check.ps1).Content
#
# Or with explicit args:
#
#   .\bridge_watcher_update_check.ps1                 # check only, exit 1 if stale
#   .\bridge_watcher_update_check.ps1 -Apply          # also re-pull stale files
#   .\bridge_watcher_update_check.ps1 -Apply -Restart # also bounce the scheduled task
#   .\bridge_watcher_update_check.ps1 -Quiet          # cron-friendly, headline only
#
# Exit codes:
#   0  up-to-date (no stale files)
#   1  stale files detected (and re-pulled if -Apply was passed)
#   2  manifest fetch failed or remote unreachable
#   3  local install dir not found
#
# Scope: covers the full runtime fileset the watcher daemon imports at
# module load (bridge_watcher.py + classify/actions/history modules +
# config json + hook ps1 + action prompt md), NOT just the 4-file pull
# set the original installer ships. If install set drift is found in
# files outside the installer's 4 (e.g. bridge_watcher_actions.py), the
# script still flags + can still re-pull them via /agent/ (each runtime
# file is allowlisted there).

param(
    [string]$InstallDir = "",
    [string]$LegionAgentBase = "https://legion-rc:8888/agent",
    [string]$TaskName = "",
    [switch]$Apply,
    [switch]$Restart,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"

function Write-Step([string]$msg) {
    if (-not $Quiet) { Write-Host "==> $msg" -ForegroundColor Cyan }
}
function Write-Ok([string]$msg) {
    if (-not $Quiet) { Write-Host "    OK $msg" -ForegroundColor Green }
}
function Write-Warn([string]$msg) {
    Write-Host "    !! $msg" -ForegroundColor Yellow
}
function Write-Stale([string]$msg) {
    Write-Host "    -- $msg" -ForegroundColor Yellow
}

# -- 1. Resolve InstallDir + TaskName ----------------------------------

if (-not $InstallDir) {
    $candidates = @(
        "C:\RC-Agent",
        (Join-Path (Get-Location) "tools"),
        (Get-Location).Path
    )
    foreach ($c in $candidates) {
        if (Test-Path -LiteralPath (Join-Path $c "bridge_watcher.py")) {
            $InstallDir = $c
            break
        }
    }
}
if (-not $InstallDir -or -not (Test-Path -LiteralPath $InstallDir)) {
    Write-Warn "install dir not found (tried C:\RC-Agent, .\tools, .). Pass -InstallDir explicitly."
    exit 3
}
Write-Step "InstallDir = $InstallDir"

# Auto-detect the scheduled task name from $env:COMPUTERNAME if not passed.
if ($Restart -and -not $TaskName) {
    $hn = $env:COMPUTERNAME.ToLower()
    if ($hn -like "*peer-host*" -or $hn -like "*peer*") { $TaskName = "RC-BridgeWatcher-Peer" }
    else {
        Write-Warn "could not auto-detect task name from COMPUTERNAME=$hn; pass -TaskName"
        $Restart = $false
    }
}
if ($Restart) { Write-Step "TaskName   = $TaskName" }

# -- 2. Cert bypass (mkcert root cert not always trusted on peers) -----
#
# PS 5.1 Invoke-WebRequest has a known wart against RC's self-signed
# dashboard cert ("The underlying connection was closed: An unexpected
# error occurred on a send" even with ServerCertificateValidationCallback
# set). Bridge_watcher_install.ps1 uses IWR but is frozen; this newer
# script side-steps the issue via raw [Net.HttpWebRequest], which works
# on PS 5.1 + PS 6+ alike.

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]'Tls12,Tls11,Tls'
[Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }

function Fetch-Text([string]$url) {
    $req = [Net.HttpWebRequest]::Create($url)
    $req.UserAgent = "rc-watcher-update-check/1.0"
    $req.Timeout   = 15000
    $resp = $req.GetResponse()
    try {
        $reader = New-Object IO.StreamReader($resp.GetResponseStream())
        return $reader.ReadToEnd()
    } finally {
        $resp.Close()
    }
}

function Fetch-File([string]$url, [string]$dest) {
    $req = [Net.HttpWebRequest]::Create($url)
    $req.UserAgent = "rc-watcher-update-check/1.0"
    $req.Timeout   = 30000
    $resp = $req.GetResponse()
    try {
        $in  = $resp.GetResponseStream()
        $out = [IO.File]::Create($dest)
        try { $in.CopyTo($out) }
        finally { $out.Close() }
    } finally {
        $resp.Close()
    }
}

# -- 3. Fetch manifest -------------------------------------------------

$ManifestUrl = "$LegionAgentBase/_watcher_manifest.json"
Write-Step "Fetch $ManifestUrl"
try {
    $manifestText = Fetch-Text $ManifestUrl
    $manifest = $manifestText | ConvertFrom-Json
} catch {
    Write-Warn "manifest fetch failed: $_"
    exit 2
}
if (-not $manifest.files) {
    Write-Warn "manifest response missing .files key"
    exit 2
}
Write-Ok ("schema_version={0} files={1}" -f $manifest.schema_version, ($manifest.files.PSObject.Properties | Measure-Object).Count)

# -- 4. Hash local + diff ----------------------------------------------

$Stale  = New-Object System.Collections.Generic.List[string]
$Missing = New-Object System.Collections.Generic.List[string]
$Errors = New-Object System.Collections.Generic.List[string]

foreach ($prop in $manifest.files.PSObject.Properties) {
    $name   = $prop.Name
    $entry  = $prop.Value
    if ($entry.error) {
        $Errors.Add(("{0}: remote read error: {1}" -f $name, $entry.error)) | Out-Null
        continue
    }
    $localPath = Join-Path $InstallDir $name
    if (-not (Test-Path -LiteralPath $localPath)) {
        $Missing.Add($name) | Out-Null
        continue
    }
    # Get-FileHash works on PS5.1 + PS6+; default algorithm is SHA256.
    $localSha = (Get-FileHash -LiteralPath $localPath -Algorithm SHA256).Hash.ToLower()
    $remoteSha = $entry.sha256.ToLower()
    if ($localSha -ne $remoteSha) {
        $Stale.Add($name) | Out-Null
    }
}

# -- 5. Report ---------------------------------------------------------

if ($Errors.Count -gt 0) {
    foreach ($e in $Errors) { Write-Warn $e }
}
if ($Missing.Count -gt 0) {
    Write-Step ("MISSING ({0}):" -f $Missing.Count)
    foreach ($m in $Missing) { Write-Stale $m }
}
if ($Stale.Count -gt 0) {
    Write-Step ("STALE ({0}):" -f $Stale.Count)
    foreach ($s in $Stale) { Write-Stale $s }
}

$NeedAction = ($Missing.Count + $Stale.Count) -gt 0

if (-not $NeedAction) {
    Write-Ok "watcher fileset up-to-date"
    exit 0
}

if (-not $Apply) {
    Write-Step ("{0} file(s) need re-pull. Re-run with -Apply to fix (and -Restart to bounce the task)." -f ($Missing.Count + $Stale.Count))
    exit 1
}

# -- 6. -Apply: re-pull stale + missing --------------------------------

$ToPull = @($Stale) + @($Missing)
foreach ($name in $ToPull) {
    $url  = "$LegionAgentBase/$name"
    $dest = Join-Path $InstallDir $name
    Write-Step "Pull $name"
    try {
        # Atomic-ish replace: write to .tmp then move over.
        $tmp = "$dest.tmp"
        Fetch-File $url $tmp
        Move-Item -LiteralPath $tmp -Destination $dest -Force
        Write-Ok ("{0}  {1} bytes" -f $name, (Get-Item -LiteralPath $dest).Length)
    } catch {
        Write-Warn ("pull failed for {0}: {1}" -f $name, $_)
    }
}

# -- 7. Optionally bounce the scheduled task ---------------------------

if ($Restart -and $TaskName) {
    Write-Step "Bouncing scheduled task $TaskName"
    try {
        $prevEAP = $ErrorActionPreference
        $ErrorActionPreference = "SilentlyContinue"
        $null = & schtasks /End /TN $TaskName 2>&1
        $ErrorActionPreference = $prevEAP
        Start-Sleep -Seconds 2
        $runOut = & schtasks /Run /TN $TaskName 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Ok "task restarted"
        } else {
            Write-Warn ("schtasks /Run returned nonzero: {0}" -f $runOut)
        }
    } catch {
        Write-Warn "task restart failed: $_"
    }
}

Write-Step "Done; pulled $($ToPull.Count) file(s)."
exit 1
