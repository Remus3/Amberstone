"""RM-820: the RM-768 siblings in the phase3 installer pair.

(a) ``ops/phase3_setup.py`` ``atomic_write_json`` wrote ``json.dumps(...)``
with no trailing newline, so a bare re-run of the setup helper rewrote the
TRACKED ``agents/state/resolved_decisions.json`` one byte short (its final
newline dropped) - a dirty tree from an "idempotent" script. The re-run test
drives the real ``main()`` against a tmp root seeded with the tracked file's
bytes and asserts the file comes back byte-identical.

(b) ``ops/phase3_install.ps1`` justified running the scheduled task as the
installing account by cross-machine SMB pushes and cmdkey-stored credentials
for a peer box - the 2-PC path ADR-011 retired. The comment must state the
1-PC reason, and the file must still parse under Windows PowerShell 5.1.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

import ops.phase3_setup as phase3_setup

REPO_ROOT = Path(__file__).resolve().parent.parent
DECISIONS_REL = Path("agents") / "state" / "resolved_decisions.json"
INSTALLER = REPO_ROOT / "ops" / "phase3_install.ps1"
PS51 = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
        / "WindowsPowerShell" / "v1.0" / "powershell.exe")


# -- (a) a re-run is byte-identical ------------------------------------------

def test_atomic_write_json_ends_with_exactly_one_newline(tmp_path: Path) -> None:
    target = tmp_path / "x.json"
    phase3_setup.atomic_write_json(target, {"a": 1})
    raw = target.read_bytes()
    assert raw.endswith(b"}\n"), raw[-8:]
    assert not raw.endswith(b"\n\n"), raw[-8:]
    assert b"\r" not in raw, "LF only - the tracked file is eol=lf"


def test_rerun_leaves_tracked_register_byte_identical(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    tracked = (REPO_ROOT / DECISIONS_REL).read_bytes()
    # Anchor the premise, so this cannot pass on an empty or odd seed.
    assert tracked.endswith(b"}\n") and len(tracked) > 1000
    seeded = tmp_path / DECISIONS_REL
    seeded.parent.mkdir(parents=True)
    seeded.write_bytes(tracked)

    monkeypatch.setattr(phase3_setup, "ROOT", tmp_path)
    assert phase3_setup.main() == 0
    capsys.readouterr()

    after = seeded.read_bytes()
    assert after == tracked, (
        f"re-run rewrote the register: {len(tracked)} -> {len(after)} bytes, "
        f"tail {tracked[-6:]!r} -> {after[-6:]!r}")


def test_rerun_never_touches_the_real_tree(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    # The byte test above is only honest if main() writes under ROOT alone.
    real = REPO_ROOT / DECISIONS_REL
    before = (real.read_bytes(), real.stat().st_mtime_ns)
    monkeypatch.setattr(phase3_setup, "ROOT", tmp_path)
    phase3_setup.main()
    capsys.readouterr()
    assert (real.read_bytes(), real.stat().st_mtime_ns) == before
    assert json.loads((tmp_path / DECISIONS_REL).read_text(encoding="utf-8"))


# -- (b) the installer comment states the 1-PC reason -------------------------

def _trigger_comment() -> str:
    lines = INSTALLER.read_text(encoding="utf-8-sig").splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("# Trigger:"))
    block = []
    for ln in lines[start:]:
        if not ln.startswith("#"):
            break
        block.append(ln)
    return "\n".join(block)


def test_installer_comment_states_the_one_pc_reason() -> None:
    comment = _trigger_comment()
    assert len(comment.splitlines()) >= 3, comment
    assert "1-PC" in comment and "ADR-011" in comment, comment


def test_installer_names_no_two_pc_credential_path() -> None:
    text = INSTALLER.read_text(encoding="utf-8-sig")
    hits = re.findall(r"\bSMB\b|cmdkey|cross-machine|\\\\\d{1,3}(?:\.\d{1,3}){3}",
                      text, re.I)
    assert not hits, f"installer still explains the retired 2-PC path: {hits}"


def test_installer_parses_under_windows_powershell_51() -> None:
    if not PS51.is_file():
        pytest.skip("Windows PowerShell 5.1 not available on this host")
    command = (
        "$e = $null; "
        f"[void][System.Management.Automation.Language.Parser]::ParseFile('{INSTALLER}', [ref]$null, [ref]$e); "
        "Write-Output ('ERRORS=' + $e.Count)"
    )
    proc = subprocess.run([str(PS51), "-NoProfile", "-Command", command],
                          capture_output=True, text=True, timeout=90,
                          creationflags=0x08000000 if os.name == "nt" else 0)
    assert "ERRORS=0" in proc.stdout, f"{proc.stdout}\n{proc.stderr}"
