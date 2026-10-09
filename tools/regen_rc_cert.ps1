# regen_rc_cert.ps1 - refresh ops/tls/rc.pem + rc-key.pem with the canonical
# SAN list. One-stop helper so future cert refreshes don't have to relearn
# which names belong (the s30 mkcert regen had to reconstruct this by hand).
#
# Canonical SAN list = loopback names below PLUS this machine's own names and
# addresses from the GITIGNORED per-host config ops/local_hosts.json
# (`cert_sans`; template ops/local_hosts.example.json). When adding a new
# identity for Legion (new tailnet rename, additional VPN, second LAN bridge),
# add it there and re-run - never as a literal in this tracked file. Legion's
# existing trust of the mkcert root CA covers any new leaf as long as the root
# doesn't rotate.
#
# Usage (from project root):
#   pwsh -ExecutionPolicy Bypass -File tools\regen_rc_cert.ps1
#   # OR (Windows PowerShell 5.1):
#   powershell -ExecutionPolicy Bypass -File tools\regen_rc_cert.ps1
#
# After regen:
#   1. Restart RC: `echo regen-cert > restart_trigger.txt`
#   2. Verify SAN: openssl x509 -in ops\tls\rc.pem -noout -ext subjectAltName
#   3. From Legion: iwr https://<tailnet-name>:8888/api/health  (no -SkipCertificateCheck)

$ErrorActionPreference = 'Stop'

# Resolve project root from the script location (tools\ is one level deep).
$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $projectRoot) { $projectRoot = (Get-Location).Path }

# Canonical SAN list: loopback here, then the per-host names and addresses
# from ops/local_hosts.json `cert_sans` (absent file = loopback-only leaf).
# mkcert auto-classifies IPs; ordering is just for readability.
$SAN_NAMES = @('localhost', '127.0.0.1')
$hostsFile = Join-Path $projectRoot 'ops\local_hosts.json'
if (Test-Path $hostsFile) {
    $hostsCfg = Get-Content -Raw -Path $hostsFile | ConvertFrom-Json
    foreach ($san in @($hostsCfg.cert_sans)) {
        if ($san -is [string] -and $san.Trim() -and ($SAN_NAMES -notcontains $san.Trim())) {
            $SAN_NAMES += $san.Trim()
        }
    }
} else {
    Write-Host 'ops\local_hosts.json absent: loopback-only SANs (copy ops\local_hosts.example.json)' -ForegroundColor Yellow
}
$tlsDir = Join-Path $projectRoot 'ops\tls'
if (-not (Test-Path $tlsDir)) {
    New-Item -ItemType Directory -Path $tlsDir | Out-Null
}

$certOut = Join-Path $tlsDir 'rc.pem'
$keyOut  = Join-Path $tlsDir 'rc-key.pem'

# Sanity: mkcert must be on PATH. Don't try to install it - that's a
# one-time setup the operator already did (winget install FiloSottile.mkcert
# + mkcert -install).
$mkcert = Get-Command mkcert -ErrorAction SilentlyContinue
if (-not $mkcert) {
    Write-Host 'mkcert not on PATH. Install: winget install FiloSottile.mkcert ; mkcert -install' -ForegroundColor Red
    exit 1
}

Write-Host ''
Write-Host '=== regenerating RC TLS cert ===' -ForegroundColor Cyan
Write-Host "  cert: $certOut"
Write-Host "  key:  $keyOut"
Write-Host '  SAN:'
foreach ($n in $SAN_NAMES) { Write-Host "    - $n" }
Write-Host ''

# mkcert overwrites in place. Existing cert (if any) is replaced; the
# leaf changes, root CA stays the same so trust survives.
& mkcert -cert-file $certOut -key-file $keyOut @SAN_NAMES
if ($LASTEXITCODE -ne 0) {
    Write-Host "mkcert failed (exit $LASTEXITCODE)" -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host ''
Write-Host '=== verify ===' -ForegroundColor Cyan
$openssl = Get-Command openssl -ErrorAction SilentlyContinue
if ($openssl) {
    & openssl x509 -in $certOut -noout -ext subjectAltName
    & openssl x509 -in $certOut -noout -dates
} else {
    Write-Host '  (openssl not on PATH; skipping SAN dump - install with: winget install ShiningLight.OpenSSL.Light)' -ForegroundColor Yellow
}

Write-Host ''
Write-Host '=== next steps ===' -ForegroundColor Cyan
Write-Host '  1. Restart RC to pick up new leaf:  echo regen-cert > restart_trigger.txt'
Write-Host '  2. From a peer node, sanity-check trust:  iwr https://<tailnet-name>:8888/api/health'
Write-Host '     (should return 200 with NO -SkipCertificateCheck flag)'
Write-Host ''
