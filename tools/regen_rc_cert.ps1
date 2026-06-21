# regen_rc_cert.ps1 - refresh ops/tls/rc.pem + rc-key.pem with the canonical
# SAN list. One-stop helper so future cert refreshes don't have to relearn
# which names belong (the s30 mkcert regen had to reconstruct this by hand).
#
# Canonical SAN list - when adding a new identity for Legion (new tailnet
# rename, additional VPN, second LAN bridge), update $SAN_NAMES below and
# re-run. Legion's existing trust of the mkcert root CA covers any new
# leaf as long as the root doesn't rotate.
#
# Usage (from project root):
#   pwsh -ExecutionPolicy Bypass -File tools\regen_rc_cert.ps1
#   # OR (Windows PowerShell 5.1):
#   powershell -ExecutionPolicy Bypass -File tools\regen_rc_cert.ps1
#
# After regen:
#   1. Restart RC: `echo regen-cert > restart_trigger.txt`
#   2. Verify SAN: openssl x509 -in ops\tls\rc.pem -noout -ext subjectAltName
#   3. From Legion: iwr https://legion-rc:8888/api/health  (no -SkipCertificateCheck)

$ErrorActionPreference = 'Stop'

# Canonical SAN list. Mirrors what's already trusted on Legion (and the Peer bridge peer).
# Keep DNS names first, then IP addresses. mkcert auto-classifies IPs;
# explicit ordering here is just for readability.
$SAN_NAMES = @(
    'localhost',
    'legion-rc',
    'legion-rc.tailc150de.ts.net',
    '127.0.0.1',
    '192.168.8.230',
    '100.70.22.55'
)

# Resolve project root from the script location (tools\ is one level deep).
$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $projectRoot) { $projectRoot = (Get-Location).Path }
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
Write-Host '  2. From a peer node, sanity-check trust:  iwr https://legion-rc:8888/api/health'
Write-Host '     (should return 200 with NO -SkipCertificateCheck flag)'
Write-Host ''
