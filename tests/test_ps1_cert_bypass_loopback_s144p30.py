"""RM-1181: a PowerShell certificate-check bypass stays loopback-only.

RM-1175 pinned that no Python script in scripts/ turns TLS verification off
for a public host; its sweep is .py-only. The PowerShell side has the same
hazard in a different spelling:

- ``[System.Net.ServicePointManager]::ServerCertificateValidationCallback =
  { $true }`` accepts EVERY certificate for every later .NET web request in
  the process (Invoke-WebRequest, Invoke-RestMethod, WebClient);
- ``[System.Net.ServicePointManager]::CertificatePolicy = ...`` is the older
  spelling of the same thing;
- ``-SkipCertificateCheck`` (PowerShell 7) and ``curl -k`` / ``--insecure``
  turn it off for one request.

Measured 2026-10-31 over the 33 tracked .ps1 / .psm1 files (the repo walk
skips the one under docs/_archive/, which has none): exactly ONE real
bypass, scripts/start_claude.ps1 (the launcher's pre-flight), and every web
request in that file goes to 127.0.0.1 - the RC dashboard's :8888 uses a
self-signed certificate. tools/regen_rc_cert.ps1 NAMES -SkipCertificateCheck,
but only in a comment and a Write-Host string telling the operator NOT to use
it. The sweep below strips comments and strings before it looks, so those two
mentions stay legal, and it pins the bypass set to the allowlist. A file on
the allowlist must keep every URL it names on loopback and every web request
on a literal loopback URL, so a public fetch cannot be added later under the
process-wide accept-all callback.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests._repo_walk import relative_posix, repo_files  # noqa: E402

# Tracked PowerShell files allowed a certificate-check bypass, with the reason.
_BYPASS_ALLOWED = {
    "scripts/start_claude.ps1": (
        "launcher pre-flight; every probe is 127.0.0.1 (the :8888 dashboard "
        "serves a self-signed certificate)"
    ),
}

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "[::1]"})

_BYPASS_PATTERNS = (
    # ServicePointManager and HttpClientHandler spellings of the callback.
    re.compile(
        r"(?:Server|Remote)Certificate(?:Custom)?ValidationCallback\s*=",
        re.IGNORECASE,
    ),
    re.compile(r"ServicePointManager\]::CertificatePolicy\s*=", re.IGNORECASE),
    # The switch, a splat key (@{SkipCertificateCheck=$true}) included.
    re.compile(r"\bSkipCertificateCheck\b", re.IGNORECASE),
    # curl -k, a short-flag cluster holding k (-sk, -ks), or --insecure.
    re.compile(
        r"\bcurl(?:\.exe)?\b[^\n|;]*\s(?:-[A-Za-z]{0,3}k[A-Za-z]{0,3}|--insecure)"
        r"(?=\s|$)",
        re.IGNORECASE | re.MULTILINE,
    ),
)

_WEB_CALL = re.compile(
    r"\b(?:Invoke-WebRequest|Invoke-RestMethod|iwr|irm|curl(?:\.exe)?)\b"
    r"|Net\.WebClient|Net\.Http\.HttpClient",
    re.IGNORECASE,
)

_URL = re.compile(r"https?://([^/\s:'\"`]+)", re.IGNORECASE)


def _segments(text: str) -> list[tuple[str, str]]:
    """Split PowerShell source into ("code" | "string" | "comment", text).

    Handles ``<# ... #>`` block comments, ``#`` line comments, single- and
    double-quoted strings and both here-string forms. Good enough for a
    guard over this tree; it is not a full PowerShell parser.
    """
    out: list[tuple[str, str]] = []
    i, n = 0, len(text)
    code_start = 0

    def flush_code(end: int) -> None:
        if end > code_start:
            out.append(("code", text[code_start:end]))

    while i < n:
        ch = text[i]
        two = text[i:i + 2]
        if two == "<#":
            flush_code(i)
            end = text.find("#>", i + 2)
            end = n if end < 0 else end + 2
            out.append(("comment", text[i:end]))
            i = code_start = end
        elif ch == "#":
            flush_code(i)
            end = text.find("\n", i)
            end = n if end < 0 else end
            out.append(("comment", text[i:end]))
            i = code_start = end
        elif two in ("@'", '@"') and text[i + 2:i + 3] in ("\n", "\r"):
            flush_code(i)
            closer = "\n" + two[1] + "@"
            end = text.find(closer, i + 2)
            end = n if end < 0 else end + len(closer)
            out.append(("string", text[i:end]))
            i = code_start = end
        elif ch in ("'", '"'):
            flush_code(i)
            j = i + 1
            while j < n:
                if ch == '"' and text[j] == "`":
                    j += 2
                    continue
                if text[j] == ch:
                    if text[j + 1:j + 2] == ch:  # doubled quote = escape
                        j += 2
                        continue
                    break
                j += 1
            end = min(j + 1, n)
            out.append(("string", text[i:end]))
            i = code_start = end
        else:
            i += 1
    flush_code(n)
    return out


def _code_only(text: str) -> str:
    return "".join(t for kind, t in _segments(text) if kind == "code")


def _without_comments(text: str) -> str:
    return "".join(t for kind, t in _segments(text) if kind != "comment")


def _bypass_hits(text: str) -> list[str]:
    code = _code_only(text)
    return [m.group(0) for p in _BYPASS_PATTERNS for m in p.finditer(code)]


def _powershell_files() -> dict[str, str]:
    files = repo_files(ROOT, ("*.ps1", "*.psm1"))
    return {
        relative_posix(p, ROOT): p.read_text(encoding="utf-8", errors="replace")
        for p in files
    }


def test_powershell_universe_is_not_empty():
    files = _powershell_files()
    # An empty walk would pass every sweep below; anchor it.
    assert len(files) >= 20, sorted(files)
    for rel in _BYPASS_ALLOWED:
        assert rel in files, f"allowlisted {rel} is not a tracked file"


def test_bypass_set_equals_allowlist():
    found = {
        rel for rel, text in _powershell_files().items() if _bypass_hits(text)
    }
    assert found == set(_BYPASS_ALLOWED), (
        "PowerShell certificate-check bypass outside the allowlist: "
        f"{sorted(found - set(_BYPASS_ALLOWED))}; allowlisted but no longer "
        f"bypassing (drop the entry): {sorted(set(_BYPASS_ALLOWED) - found)}"
    )


@pytest.mark.parametrize("rel", sorted(_BYPASS_ALLOWED))
def test_allowlisted_file_names_only_loopback_urls(rel):
    text = (ROOT / rel).read_text(encoding="utf-8")
    hosts = [m.group(1).lower() for m in _URL.finditer(_without_comments(text))]
    assert hosts, f"{rel}: no URL found - the sweep is reading the wrong file"
    off_box = sorted(set(hosts) - _LOOPBACK_HOSTS)
    assert not off_box, f"{rel} bypasses cert checks and names {off_box}"


@pytest.mark.parametrize("rel", sorted(_BYPASS_ALLOWED))
def test_allowlisted_file_web_calls_use_literal_loopback_url(rel):
    text = (ROOT / rel).read_text(encoding="utf-8")
    calls = 0
    for line in _without_comments(text).splitlines():
        if not _WEB_CALL.search(line):
            continue
        calls += 1
        hosts = {m.group(1).lower() for m in _URL.finditer(line)}
        assert hosts and hosts <= _LOOPBACK_HOSTS, (
            f"{rel}: web call without a literal loopback URL: {line.strip()}"
        )
    assert calls, f"{rel}: no web call found - the sweep is reading the wrong file"


# --- the scanner itself, on synthetic text (mutation anchors) -------------

@pytest.mark.parametrize("src", [
    "[System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }",
    "[Net.ServicePointManager]::CertificatePolicy = New-Object TrustAll",
    "Invoke-WebRequest -Uri $u -SkipCertificateCheck",
    "curl.exe -s -k https://example.invalid/",
    "curl --insecure https://example.invalid/",
    "curl.exe -sk https://example.invalid/",
    "$p = @{ Uri = $u; SkipCertificateCheck = $true }",
    "$h.ServerCertificateCustomValidationCallback = { $true }",
])
def test_scanner_flags_a_real_bypass(src):
    assert _bypass_hits(src), src


@pytest.mark.parametrize("src", [
    "# iwr https://host:8888/ (no -SkipCertificateCheck)",
    "<#\n ServerCertificateValidationCallback = { $true }\n#>",
    "Write-Host '(should return 200 with NO -SkipCertificateCheck flag)'",
    'Write-Host "use curl -k only on loopback"',
    "$s = @'\nServerCertificateValidationCallback = x\n'@",
    "curl.exe -s https://127.0.0.1:8888/api/health -o out.json",
    "curl -Uri $u -SkipHttpErrorCheck",
])
def test_scanner_ignores_comments_strings_and_plain_calls(src):
    assert not _bypass_hits(src), src


def test_loopback_check_rejects_a_public_url():
    src = (
        "[System.Net.ServicePointManager]::ServerCertificateValidationCallback"
        " = { $true }\n"
        'Invoke-WebRequest -Uri "https://example.invalid/x" -UseBasicParsing\n'
    )
    hosts = {m.group(1).lower() for m in _URL.finditer(_without_comments(src))}
    assert hosts - _LOOPBACK_HOSTS == {"example.invalid"}
