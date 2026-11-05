"""RM-725 (b): the tools/claude_send.ahk header states its real wiring.

The header said "(PROVISIONAL)" and "NOT wired into any loop or trigger - it
only acts when invoked explicitly", written 2026-06-04 when the script was a
standalone self-clear primitive. One day later tools/rc_headless_launcher.ps1
(the one-click Desktop launcher that tools/install_headless_launcher_shortcut.ps1
installs) started calling it to send /headless-upgrade into the Claude
desktop window, so the header read as dead code to an outsider while a live
launcher still drove it.

These tests pin the header to the caller, in both directions: the header names
the launcher and no longer claims to be unwired, and the launcher still names
the script. If the launcher ever stops calling it, the second test goes red so
the header (or the script) is revisited instead of going stale again.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AHK = REPO_ROOT / "tools" / "claude_send.ahk"
LAUNCHER = REPO_ROOT / "tools" / "rc_headless_launcher.ps1"


def _header() -> str:
    """The leading comment block: every line before the first non-comment."""
    lines = []
    for line in AHK.read_text(encoding="ascii").splitlines():
        if line.startswith((";", "#Requires")) or not line.strip():
            lines.append(line)
            continue
        break
    assert len(lines) > 3, "claude_send.ahk header not found"
    return "\n".join(lines)


def test_header_does_not_claim_unwired_or_provisional():
    header = _header()
    assert "NOT wired" not in header
    assert "PROVISIONAL" not in header


def test_header_names_its_caller():
    assert "tools/rc_headless_launcher.ps1" in _header()


def test_launcher_still_invokes_claude_send():
    text = LAUNCHER.read_text(encoding="ascii")
    assert 'Join-Path $repo "tools\\claude_send.ahk"' in text
    assert "Invoke-Ahk" in text
